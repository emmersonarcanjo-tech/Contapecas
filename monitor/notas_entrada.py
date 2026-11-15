#!/usr/bin/env python3
"""Dá entrada no ALIV das notas fiscais de FORNECEDOR que chegam pela SEFAZ.

Para a Tili Pizzaria e a Tili Sushi, lê a fila "Notas pendentes" do ALIV
(/admin/inventory/invoices/pending), a mesma da tela de Estoque, e para cada nota:

  1. Itens: usa a ligação item → insumo que o próprio ALIV já memorizou (pelo
     código de barras), com o mesmo fator de conversão. Se algum item não tem
     ligação, ou o ALIV pede para conferir o fator, a nota NÃO entra e vai para a
     lista "para conferir". Nunca cria insumo novo.
  2. Custo: o valor de cada item na nota, com frete/IPI/ST/desconto rateados pelo
     valor dos itens, para o custo do estoque bater com o total da nota.
  3. Pagamento (regras do Emerson, 15/11/2026), lido do XML da nota:
     - boletos/duplicatas: uma conta a pagar por parcela, na data de vencimento;
       parcela já vencida entra como PAGA na data do vencimento (sem mexer em
       caixa/banco);
     - Norsa sem data no boleto: vence 4 dias depois da nota (só para as notas
       emitidas até NORSA_ATE; as novas vão para a lista para o Emerson dizer);
     - sem forma de pagamento (bonificação, troca, pago na entrega): entra no
       estoque com o custo real e a conta fica PAGA na data da nota, sem mexer em
       caixa/banco (o ALIV sempre cria a conta);
     - cartão/Pix/dinheiro: conta PAGA na data da nota.
  4. Lança tudo numa chamada só: POST /admin/inventory/process-invoice-items-financial
     com pending_note_id, igual ao botão "Dar entrada" da tela "Conferência da Nota".

Sem --confirmar só mostra o que faria (nada é lançado). Com --whatsapp manda o
resumo para WHATSAPP_EMERSON. Saída: 0 ok, 1 erro de ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, TZ, Aliv, AlivError, brl  # noqa: E402

LOJAS = {"Pizzaria": ("ALIV_USER", "ALIV_PASS"), "Sushi": ("ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")}
NS = "{http://www.portalfiscal.inf.br/nfe}"
BOLETO = "Boleto via DDA"
FORMA_TPAG = {"01": "Dinheiro", "03": "Cartão Crédito", "04": "Cartão Débito", "17": "Pix"}
NORSA_DIAS = 4
NORSA_ATE = date(2026, 11, 15)   # notas da Norsa sem data de boleto emitidas até aqui: +4 dias
FATOR_OK = {"memorizado", "preco"}  # "conferir" = o ALIV não tem certeza do fator → Emerson confere


def dinheiro(v) -> float:
    return round(float(v or 0) + 1e-9, 2)


class Loja:
    def __init__(self, nome: str):
        u, p = LOJAS[nome]
        if not os.environ.get(u) or not os.environ.get(p):
            raise AlivError(f"{nome}: defina {u} e {p}")
        self.nome, self.api = nome, Aliv(os.environ[u], os.environ[p])
        self.api.login()
        cats = self.api.get("/admin/finance/categories")
        cats = cats if isinstance(cats, list) else cats.get("categories", [])
        self.cat_compras = next((c["id"] for c in cats if c.get("name") == "Compras"), None)

    def post_json(self, path: str, payload: dict) -> tuple[int, object]:
        req = urllib.request.Request(BASE_URL + path, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        st, d = self.api._send(req)
        if st == 401:
            self.api.login()
            st, d = self.api._send(req)
        return st, d

    def xmls(self, ini: date, fim: date) -> dict[str, ET.Element]:
        """XMLs das notas do período (o mesmo botão 'Baixar XMLs' do ALIV), por chave."""
        url = f"{BASE_URL}/admin/inventory/invoices/xml-zip?start={ini}&end={fim}"
        with self.api.opener.open(urllib.request.Request(url), timeout=180) as r:
            z = zipfile.ZipFile(io.BytesIO(r.read()))
        out = {}
        for n in z.namelist():
            if not n.lower().endswith(".xml"):
                continue
            try:
                raiz = ET.fromstring(z.read(n))
            except ET.ParseError:
                continue
            inf = raiz.find(f".//{NS}infNFe")
            if inf is not None:
                out[inf.get("Id", "")[3:]] = raiz
        return out


def pagamento(xml: ET.Element | None, fornecedor: str, emissao: date, total: float, hoje: date):
    """Devolve (modo, dados, aviso). modo: parcelas | pago | conferir."""
    if xml is None:
        return "conferir", None, "sem XML da nota na SEFAZ"
    dups = [(date.fromisoformat(d.findtext(f"{NS}dVenc")), dinheiro(d.findtext(f"{NS}vDup")))
            for d in xml.iter(f"{NS}dup") if d.findtext(f"{NS}dVenc")]
    tpags = [d.findtext(f"{NS}tPag") for d in xml.iter(f"{NS}detPag")]
    if dups:
        soma = dinheiro(sum(v for _, v in dups))
        if soma < total - 0.02:            # parte paga à vista na entrega (ex.: Litoral)
            dups.insert(0, (emissao, dinheiro(total - soma)))
        elif soma > total + 0.02:
            return "conferir", None, f"boletos somam {brl(soma)} e a nota {brl(total)}"
        return "parcelas", sorted(dups), None
    if "15" in tpags or "14" in tpags:     # boleto sem data no XML
        if "NORSA" in fornecedor.upper() and emissao <= NORSA_ATE:
            return "parcelas", [(emissao + timedelta(days=NORSA_DIAS), total)], None
        return "conferir", None, "boleto sem data de vencimento na nota"
    forma = next((FORMA_TPAG[t] for t in tpags if t in FORMA_TPAG), None)
    if forma:
        return "pago", {"forma": forma, "data": emissao}, None
    # "90" sem pagamento / "99" outros / vazio: só estoque (regra do Emerson)
    return "pago", {"forma": "Dinheiro", "data": emissao, "sem_pagto": True}, None


def itens_payload(nota: dict, total: float, cat: int | None):
    """Monta os itens. Devolve (itens, problemas)."""
    itens, problemas = nota.get("items") or [], []
    base = [dinheiro((i.get("total_price") or 0) - (i.get("discount") or 0)) for i in itens]
    soma = sum(base)
    dif = dinheiro(total - soma)            # frete, IPI, ST, desconto no total…
    out = []
    for i, b in zip(itens, base):
        nome = i.get("xml_name") or i.get("name") or "?"
        iid = i.get("suggested_ingredient_id")
        if not iid:
            problemas.append(f"{nome}: sem insumo ligado")
            continue
        if i.get("suggested_factor_basis") not in FATOR_OK:
            problemas.append(f"{nome}: ALIV pede para conferir (→ {i.get('suggested_matched_name')})")
            continue
        acc = dinheiro(dif * b / soma) if soma else 0.0
        out.append({"name_in_invoice": i.get("name") or nome, "mapped_id": int(iid), "qty": float(i.get("qty") or 0),
                    "cost": dinheiro(b + acc), **({"accessory": acc} if acc else {}),
                    "conversion_factor": float(i.get("suggested_conversion_factor") or 1),
                    "unit": i.get("unit"), "target_unit_id": None, "code": i.get("code"), "is_resale": False,
                    "is_bonus": False, "bill_category_id": cat, "expiration_date": None,
                    "supplier_batch_code": None, "price_divergence": None})
    if out:   # ajuste de centavos no maior item, para a soma bater com a nota
        resto = dinheiro(total - sum(x["cost"] for x in out))
        if 0 < abs(resto) <= 0.05:
            maior = max(out, key=lambda x: x["cost"])
            maior["cost"] = dinheiro(maior["cost"] + resto)
    return out, problemas


def pagar_vencidas(L: Loja, chave: str, vencidas: list[date]) -> str:
    """Dá baixa (sem mexer em caixa/banco) nas parcelas já vencidas da nota recém-lançada."""
    if not vencidas:
        return ""
    contas = L.api.get("/admin/finance/bills", {"bill_type": "payable", "status": "all"})
    contas = contas if isinstance(contas, list) else contas.get("bills", [])
    ok = 0
    for c in contas:
        if str(c.get("invoice_key") or "") != chave or c.get("paid_at"):
            continue
        venc = str(c.get("due_date") or "")[:10]
        if venc and date.fromisoformat(venc) in vencidas:
            boundary = "----tili"
            campos = {"payment_method": c.get("payment_method") or BOLETO, "origin": "none", "payment_date": venc}
            body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                           for k, v in campos.items()) + f"--{boundary}--\r\n"
            req = urllib.request.Request(f"{BASE_URL}/admin/finance/bills/{c['id']}/pay", data=body.encode(),
                                         method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                                  "Accept": "application/json"})
            st, d = L.api._send(req)
            ok += st == 200 and not (isinstance(d, dict) and d.get("success") is False)
    return f" · {ok}/{len(vencidas)} vencida(s) baixada(s) como paga(s)"


def processar(L: Loja, hoje: date, confirmar: bool, so: set[int]) -> dict:
    pend = L.api.get("/admin/inventory/invoices/pending") or []
    if so:
        pend = [p for p in pend if int(p["id"]) in so]
    res = {"lancadas": [], "conferir": [], "erros": [], "vencimentos": []}
    if not pend:
        return res
    datas = [datetime.strptime(p["date"], "%d/%m/%Y").date() for p in pend if p.get("date")]
    xmls = L.xmls(min(datas) - timedelta(days=2), hoje + timedelta(days=1))
    for p in sorted(pend, key=lambda x: int(x["id"])):
        forn, total = p.get("supplier") or "?", dinheiro(p.get("total"))
        tag = f"{forn[:28]} NF {p.get('number')} {brl(total)}"
        try:
            nota = L.api.get(f"/admin/inventory/invoices/pending/{p['id']}/process")
        except AlivError as e:
            res["erros"].append(f"{tag}: {e}")
            continue
        emissao = date.fromisoformat(str((nota.get("data") or {}).get("issue_date") or "")[:10] or hoje.isoformat())
        total = dinheiro((nota.get("data") or {}).get("total_value") or total)
        if nota.get("duplicate_level") == "bloquear":
            res["conferir"].append(f"{tag}: ALIV diz que já foi lançada ({nota.get('warning')})")
            continue
        itens, problemas = itens_payload(nota, total, L.cat_compras)
        modo, pg, aviso = pagamento(xmls.get(p.get("key")), forn, emissao, total, hoje)
        if problemas or modo == "conferir":
            res["conferir"].append(f"{tag}: " + "; ".join(problemas + ([aviso] if aviso else [])))
            continue
        payload = {"items": itens, "invoice_key": nota.get("invoice_key"),
                   "invoice_number": str((nota.get("data") or {}).get("number") or p.get("number") or "").lstrip("0") or None,
                   "invoice_series": (nota.get("data") or {}).get("series"),
                   "issue_date": (nota.get("data") or {}).get("issue_date"), "entry_date": hoje.isoformat(),
                   "target_location_id": None, "supplier": nota.get("supplier"), "supplier_id": None,
                   "register_supplier": False, "pending_note_id": nota.get("note_id") or int(p["id"]),
                   "total_value": total, "linked_draft_order": None}
        vencidas: list[date] = []
        if modo == "pago":
            payload.update({"is_paid": True, "payment_method": pg["forma"], "paid_date": pg["data"].isoformat(),
                            "due_date": pg["data"].isoformat(), "payment_origin": "none", "bank_account_id": None})
            como = ("só estoque (sem pagamento na nota)" if pg.get("sem_pagto")
                    else f"pago {pg['forma']} {pg['data']:%d/%m}")
        elif len(pg) == 1 and pg[0][0] < hoje:
            payload.update({"is_paid": True, "payment_method": BOLETO, "paid_date": pg[0][0].isoformat(),
                            "due_date": pg[0][0].isoformat(), "payment_origin": "none", "bank_account_id": None})
            como = f"boleto vencido {pg[0][0]:%d/%m} → pago"
        elif len(pg) == 1:
            payload.update({"is_paid": False, "payment_method": BOLETO, "due_date": pg[0][0].isoformat()})
            como = f"boleto {pg[0][0]:%d/%m}"
            res["vencimentos"].append((pg[0][0], pg[0][1], L.nome, forn))
        else:
            payload.update({"is_paid": False, "payment_method": BOLETO,
                            "installments": [{"due_date": d.isoformat(), "amount": v} for d, v in pg]})
            vencidas = [d for d, _ in pg if d < hoje]
            como = f"{len(pg)} boletos " + ", ".join(f"{d:%d/%m}" for d, _ in pg)
            res["vencimentos"] += [(d, v, L.nome, forn) for d, v in pg if d >= hoje]
        linha = f"{tag} · {len(itens)} item(ns) · {como}"
        if not confirmar:
            res["lancadas"].append("(teste) " + linha)
            continue
        st, d = L.post_json("/admin/inventory/process-invoice-items-financial", payload)
        if st == 409 and isinstance(d, dict) and d.get("code") == "POSSIBLE_DUPLICATE":
            res["conferir"].append(f"{tag}: ALIV acha que já foi lançada ({d.get('message')})")
            continue
        if st != 200 or (isinstance(d, dict) and d.get("success") is False):
            msg = (d.get("error") or d.get("message")) if isinstance(d, dict) else str(d)
            res["erros"].append(f"{tag}: HTTP {st} {str(msg)[:180]}")
            continue
        linha += pagar_vencidas(L, nota.get("invoice_key") or "", vencidas)
        res["lancadas"].append(linha)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Entrada das notas de fornecedor (SEFAZ) no ALIV")
    ap.add_argument("--confirmar", action="store_true", help="lança de verdade (sem isso, só mostra)")
    ap.add_argument("--whatsapp", action="store_true", help="manda o resumo para WHATSAPP_EMERSON")
    ap.add_argument("--loja", choices=list(LOJAS), help="só uma loja")
    ap.add_argument("--nota", type=int, action="append", default=[], help="só estas notas pendentes (id)")
    a = ap.parse_args()

    hoje = datetime.now(TZ).date()
    txt, erro_aliv, envio = [], False, None
    tot_l = tot_c = 0
    venc = []
    for nome in ([a.loja] if a.loja else list(LOJAS)):
        try:
            L = Loja(nome)
            envio = envio or L
            r = processar(L, hoje, a.confirmar, set(a.nota))
        except (AlivError, OSError) as e:
            txt.append(f"\n*{nome}*: ERRO no ALIV — {e}")
            erro_aliv = True
            continue
        tot_l += len(r["lancadas"])
        tot_c += len(r["conferir"])
        venc += r["vencimentos"]
        txt.append(f"\n*{nome}* — {len(r['lancadas'])} lançada(s), {len(r['conferir'])} para conferir"
                   + (f", {len(r['erros'])} erro(s)" if r["erros"] else ""))
        txt += [f"✓ {x}" for x in r["lancadas"]]
        if r["conferir"]:
            txt.append("Para conferir (não lancei):")
            txt += [f"• {x}" for x in r["conferir"]]
        txt += [f"✗ {x}" for x in r["erros"]]
    prox = sorted(v for v in venc if v[0] <= hoje + timedelta(days=7))
    if prox:
        txt.append("\n*Boletos dos próximos 7 dias* (das notas lançadas agora):")
        txt += [f"• {d:%d/%m} {brl(v)} — {loja} · {f[:28]}" for d, v, loja, f in prox]
    cab = (f"*Tili — Notas de fornecedor* {hoje:%d/%m}: {tot_l} lançada(s), {tot_c} para conferir"
           + ("" if a.confirmar else " — TESTE, nada lançado"))
    texto = cab + "\n" + "\n".join(txt)
    print(texto)
    if a.whatsapp and envio is not None and (tot_l or tot_c or erro_aliv):
        fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
        try:
            envio.api.enviar_whatsapp(fone, texto[:3800])
            print("WHATSAPP: enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 1 if erro_aliv else 0


if __name__ == "__main__":
    sys.exit(main())
