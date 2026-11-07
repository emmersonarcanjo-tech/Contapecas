#!/usr/bin/env python3
"""Lança no ALIV as despesas do WhatsApp: conta PAGA + entrada no ESTOQUE.

Usa a entrada de nota manual do ALIV (a mesma tela "Conferência da Nota"):
POST /admin/inventory/process-invoice-items-financial. Numa chamada só ela
cria a conta a pagar já paga (payment_origin=none, não mexe em caixa/banco) e dá
entrada no estoque com custo, o que alimenta o custo médio e as fichas técnicas.

Ligação item → insumo: SÓ pela tabela de-para (monitor/despesas/depara.json),
aprovada pelo Emerson. Item fora da tabela entra só como despesa (skip_stock) e
vai para a lista "insumo pendente", com sugestões. Nunca cria insumo novo.

Entrada: JSON (lista) que a Rotina monta depois de ler as fotos:

  {"wamid": "...",                     # da despesa em monitor/despesas/AAAA-MM-DD.json
   "loja": "pizzaria" | "sushi",
   "fornecedor": "Mateus Supermercados", "cnpj": "12.345.678/0001-90",   # opcionais (só texto, sem nota: omitir)
   "documento": "130439", "chave": "2926...44 dígitos",                  # opcionais
   "valor": 19.95,                       # total pago
   "forma": "Cartão Crédito" | "Dinheiro" | "Pix" | "Cartão Débito",
   "categoria": "Compras" | "Aluguel e Contas",
   "data": "2026-11-03",                 # opcional, padrão = dia da mensagem
   "itens": [{"nome": "CEBOLINHA", "qtd": 5, "unidade": "UN", "total": 19.95}]}

Outros usos:
  despesas_lancar.py --depara pizzaria "CEBOLINHA" 23642 [fator]   # aprova ligação
  despesas_lancar.py --sugerir pizzaria "cebolinha"                 # mostra candidatos

Sem --confirmar, só mostra o que faria (nada é lançado).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, Aliv, AlivError  # noqa: E402

PASTA = Path(__file__).resolve().parent / "despesas"
DEPARA = PASTA / "depara.json"
LOJAS = {"pizzaria": ("ALIV_USER", "ALIV_PASS"), "sushi": ("ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")}
FORMAS = {"cartao credito", "cartao debito", "dinheiro", "pix"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def chave_item(nome: str) -> str:
    """Nome do item do cupom normalizado para a tabela (sem acento, minúsculo, sem números soltos)."""
    t = re.sub(r"[^a-z0-9 ]", " ", norm(nome))
    return " ".join(w for w in t.split() if not w.isdigit())


def ler_depara() -> dict:
    try:
        d = json.loads(DEPARA.read_text())
    except (OSError, ValueError):
        d = {}
    for loja in LOJAS:
        d.setdefault(loja, {})
    return d


def gravar_depara(d: dict) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    DEPARA.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True))


def achar_despesa(wamid: str):
    for f in sorted(PASTA.glob("20*.json"), reverse=True):
        try:
            doc = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        for d in doc.get("despesas", []):
            if d.get("wamid") == wamid:
                return f, doc, d
    return None


class Loja:
    def __init__(self, nome: str):
        u, p = LOJAS[nome]
        if not os.environ.get(u) or not os.environ.get(p):
            raise AlivError(f"faltam {u}/{p}")
        self.nome, self.api = nome, Aliv(os.environ[u], os.environ[p])
        self.categorias = {norm(c["name"]): c["id"] for c in self.api.get("/admin/api/finance/bill-categories/list")}
        self.formas = {norm(f["name"]): f["name"] for f in self.api.get("/admin/api/finance/payment-methods/list")}
        r = self.api.get("/admin/inventory/api/ingredients")
        lst = r.get("ingredients", []) if isinstance(r, dict) else (r or [])
        self.insumos = {int(x["id"]): x for x in lst if not x.get("is_paused")}

    def contas(self, dia: str) -> list[dict]:
        d = date.fromisoformat(dia)
        return self.api.get("/admin/finance/bills", {
            "status": "all", "bill_type": "payable",
            "start_date": (d - timedelta(days=3)).isoformat(), "end_date": (d + timedelta(days=3)).isoformat()}) or []

    def sugerir(self, nome: str, n: int = 3) -> list[str]:
        alvo = chave_item(nome)
        pal = set(alvo.split())
        nota = []
        for i, x in self.insumos.items():
            k = chave_item(x.get("name"))
            comum = {w for w in pal & set(k.split()) if len(w) >= 3}
            r = difflib.SequenceMatcher(None, alvo, k).ratio()
            if not comum and r < 0.6:
                continue
            nota.append((r + len(comum) / max(1, len(pal)), i, x))
        nota.sort(key=lambda t: t[0], reverse=True)
        return [f"{i} {x['name']} ({x.get('unit')})" for s, i, x in nota[:n] if s > 0.35]

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        req = urllib.request.Request(BASE_URL + path, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        st, data = self.api._send(req)
        if st == 401:
            self.api.login()
            st, data = self.api._send(req)
        return st, data


RESP = re.compile(r"^\s*insumo\s+(?:(pizzaria|pizza|sushi)\s+)?(.+?)\s*=\s*(\d+)(?:\s*[x×]?\s*([\d.,]+))?\s*$", re.I)


def ler_respostas_insumo() -> int:
    """Lê a conversa do Emerson no chat da loja e aplica as respostas INSUMO na tabela de-para."""
    from datetime import datetime
    fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
    if not fone:
        print("falta WHATSAPP_EMERSON")
        return 2
    L = {"pizzaria": Loja("pizzaria")}
    msgs = L["pizzaria"].api.get(f"/admin/api/chat/messages/{fone}", {"limit": 200}) or []
    limite = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d")
    d = ler_depara()
    feitos = 0
    for m in msgs:
        if m.get("direction") != "incoming" or str(m.get("date_label")) < limite:
            continue
        for linha in str(m.get("body") or "").splitlines():
            r = RESP.match(linha)
            if not r:
                continue
            loja = "sushi" if (r.group(1) or "").lower() == "sushi" else "pizzaria"
            item, iid = r.group(2), int(r.group(3))
            fator = float(r.group(4).replace(",", ".")) if r.group(4) else 1.0
            if loja not in L:
                L[loja] = Loja(loja)
            ins = L[loja].insumos.get(iid)
            k = chave_item(item)
            if not ins:
                print(f"✗ {loja}: insumo {iid} não existe (resposta '{linha.strip()}')")
                continue
            atual = d[loja].get(k)
            if atual and atual["id"] == iid and atual.get("fator") == fator:
                continue
            d[loja][k] = {"id": iid, "nome": ins["name"], "unidade": ins.get("unit"), "fator": fator}
            feitos += 1
            print(f"OK {loja}: '{k}' → {iid} {ins['name']} × {fator:g}")
    if feitos:
        gravar_depara(d)
    print(f"{feitos} ligação(ões) nova(s) de insumo.")
    return 0


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main() -> int:
    ap = argparse.ArgumentParser(description="Lança despesas do WhatsApp no ALIV (pagas + estoque)")
    ap.add_argument("entrada", type=Path, nargs="?", help="JSON com as despesas lidas das fotos")
    ap.add_argument("--confirmar", action="store_true", help="lança de verdade (sem isso, só mostra)")
    ap.add_argument("--whatsapp", action="store_true", help="manda o resultado para WHATSAPP_EMERSON")
    ap.add_argument("--extra", default="", help="texto a mais no fim da mensagem")
    ap.add_argument("--depara", nargs="+", metavar="ARG", help='LOJA "ITEM" INSUMO_ID [FATOR]')
    ap.add_argument("--sugerir", nargs=2, metavar=("LOJA", "ITEM"))
    ap.add_argument("--ler-insumos", action="store_true",
                    help='aplica respostas "INSUMO [sushi] item = ID [fator]" do Emerson no WhatsApp (últimas 48h)')
    a = ap.parse_args()

    if a.ler_insumos:
        return ler_respostas_insumo()

    if a.sugerir:
        L = Loja(norm(a.sugerir[0]))
        print("\n".join(L.sugerir(a.sugerir[1], 8)) or "nenhum parecido")
        return 0
    if a.depara:
        if len(a.depara) not in (3, 4):
            ap.error('--depara LOJA "ITEM" INSUMO_ID [FATOR]')
        loja, item, iid = norm(a.depara[0]), a.depara[1], int(a.depara[2])
        fator = float(a.depara[3].replace(",", ".")) if len(a.depara) == 4 else 1.0
        L = Loja(loja)
        ins = L.insumos.get(iid)
        if not ins:
            print(f"Insumo {iid} não existe (ou está pausado) na {loja}.")
            return 1
        d = ler_depara()
        d[loja][chave_item(item)] = {"id": iid, "nome": ins["name"], "unidade": ins.get("unit"), "fator": fator}
        gravar_depara(d)
        print(f"OK {loja}: '{chave_item(item)}' → {iid} {ins['name']} ({ins.get('unit')}) × {fator:g}")
        return 0
    if not a.entrada:
        ap.error("informe o JSON de entrada")

    itens_desp = json.loads(a.entrada.read_text())
    depara = ler_depara()
    lojas: dict[str, Loja] = {}
    linhas, pendentes, erros, lancadas, no_estoque = [], [], 0, 0, 0
    for it in itens_desp:
        achado = achar_despesa(it.get("wamid"))
        if not achado:
            linhas.append(f"✗ {it.get('wamid')}: despesa não encontrada nos JSON do dia")
            erros += 1
            continue
        arq, doc, d = achado
        quem = f"{d['remetente']} {d['data'][8:10]}/{d['data'][5:7]} {d['hora']}"
        if (d.get("lancamento") or {}).get("ok"):
            linhas.append(f"= {quem}: já lançada")
            continue
        loja = norm(it.get("loja") or "pizzaria")
        try:
            L = lojas.get(loja) or lojas.setdefault(loja, Loja(loja))
        except (AlivError, KeyError) as e:
            linhas.append(f"✗ {quem}: loja '{loja}' ({e})")
            erros += 1
            continue
        it["fornecedor"] = (it.get("fornecedor") or "").strip() or "Sem nota (WhatsApp)"
        valor = round(float(it.get("valor") or 0), 2)
        forma = L.formas.get(norm(it.get("forma") or "Cartão Crédito"))
        cat = L.categorias.get(norm(it.get("categoria") or "Compras")) or L.categorias.get("compras")
        dia = it.get("data") or d["data"]
        itens = it.get("itens") or []
        soma = round(sum(float(x.get("total") or 0) for x in itens), 2)
        if valor <= 0 or not forma or norm(forma) not in FORMAS or not itens:
            linhas.append(f"✗ {quem}: falta valor, forma ou itens")
            erros += 1
            continue
        if abs(soma - valor) > 0.05:
            linhas.append(f"✗ {quem}: soma dos itens {brl(soma)} ≠ total {brl(valor)}. Não lancei.")
            erros += 1
            continue
        docnum = re.sub(r"\D", "", str(it.get("documento") or "")).lstrip("0") or None

        # duplicata nas contas da loja (mesmo valor e dia, e mesmo nº de nota ou mesmo fornecedor)
        dup = next((b for b in L.contas(dia)
                    if abs(float(b.get("amount") or 0) - valor) < 0.01 and str(b.get("due_date", ""))[:10] == dia
                    and ((docnum and docnum in str(b.get("description")) + str(b.get("document_number") or ""))
                         or (it["fornecedor"] != "Sem nota (WhatsApp)"
                             and norm(it["fornecedor"])[:10] in norm(b.get("description"))))), None)
        if dup:
            linhas.append(f"⚠️ {L.nome} · {quem} · {brl(valor)}: já existe conta #{dup['id']} "
                          f"({str(dup.get('description'))[:50]}). Não lancei.")
            continue

        payload_itens, sem_vinculo, com_vinculo = [], [], []
        for x in itens:
            m = depara.get(L.nome, {}).get(chave_item(x.get("nome")))
            base = {"name_in_invoice": str(x.get("nome"))[:120], "qty": float(x.get("qtd") or 1),
                    "cost": round(float(x.get("total") or 0), 2), "unit": (x.get("unidade") or "UN").upper(),
                    "code": None, "is_resale": False, "bill_category_id": cat}
            if m and int(m["id"]) in L.insumos:
                payload_itens.append({**base, "mapped_id": int(m["id"]), "conversion_factor": float(m.get("fator") or 1),
                                      "target_unit_id": None, "is_bonus": False, "expiration_date": None,
                                      "supplier_batch_code": None, "price_divergence": None})
                com_vinculo.append(f"{x.get('nome')} → {m['nome']}")
            else:
                payload_itens.append({**base, "mapped_id": None, "conversion_factor": 1, "target_unit_id": None,
                                      "skip_stock": True})
                sem_vinculo.append(x.get("nome"))
                pendentes.append((L, x.get("nome")))

        chave = re.sub(r"\D", "", str(it.get("chave") or ""))
        payload = {"items": payload_itens, "invoice_key": chave if len(chave) == 44 else None,
                   "invoice_number": docnum, "invoice_series": None, "issue_date": dia, "entry_date": dia,
                   "target_location_id": None,
                   "supplier": {"name": it["fornecedor"].strip(),
                                "cnpj": re.sub(r"\D", "", str(it.get("cnpj") or "")) or None},
                   "supplier_id": None, "register_supplier": False, "pending_note_id": None, "total_value": valor,
                   "is_paid": True, "payment_method": forma, "paid_date": dia, "due_date": dia,
                   "payment_origin": "none", "bank_account_id": None, "linked_draft_order": None}
        resumo = (f"{L.nome} · {brl(valor)} · {forma} · {it['fornecedor']} · {quem} · "
                  f"estoque {len(com_vinculo)}/{len(itens)}")
        if not a.confirmar:
            linhas.append(f"(teste) {resumo}" + (f" · sem insumo: {', '.join(sem_vinculo)}" if sem_vinculo else ""))
            continue
        st, resp = L.post_json("/admin/inventory/process-invoice-items-financial", payload)
        if st == 409 and isinstance(resp, dict) and resp.get("code") == "POSSIBLE_DUPLICATE":
            linhas.append(f"⚠️ {resumo}: ALIV diz que a nota já foi lançada ({resp.get('message')}). Não lancei.")
            d["lancamento"] = {"ok": False, "duplicada": True, "loja": L.nome}
            arq.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
            continue
        if st != 200 or (isinstance(resp, dict) and resp.get("success") is False):
            linhas.append(f"✗ {resumo}: HTTP {st} {str(resp)[:200]}")
            erros += 1
            continue
        d["lancamento"] = {"ok": True, "loja": L.nome, "valor": valor, "forma": forma,
                           "estoque": com_vinculo, "sem_insumo": sem_vinculo, "resposta": str(resp)[:300]}
        arq.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        lancadas += 1
        no_estoque += len(com_vinculo)
        linhas.append(f"✓ {resumo}")

    total = sum(float(i.get("valor") or 0) for i in itens_desp)
    msg = [f"*Tili Despesas* — {lancadas} lançada(s) paga(s) · {no_estoque} item(ns) no estoque · "
           f"{erros} erro(s) · total {brl(total)}" + ("" if a.confirmar else " — TESTE, nada lançado")]
    msg += linhas
    if pendentes:
        msg.append("\n*Itens sem insumo (entraram só como despesa).* Responda aqui, uma linha por item:"
                   "\n`INSUMO coentro = 6788` (no Sushi: `INSUMO sushi coentro = ID`)")
        vistos = set()
        for L, nome in pendentes:
            k = (L.nome, chave_item(nome))
            if k in vistos:
                continue
            vistos.add(k)
            sug = L.sugerir(nome)
            msg.append(f"- [{L.nome}] {nome}" + (f" → sugestões: {' | '.join(sug)}" if sug else " → sem parecido"))
    if a.extra:
        msg.append(a.extra)
    texto = "\n".join(msg)
    print(texto)
    if a.whatsapp and itens_desp:
        try:
            (lojas.get("pizzaria") or Loja("pizzaria")).api.enviar_whatsapp(os.environ.get("WHATSAPP_EMERSON", ""), texto)
            print("WhatsApp enviado.")
        except AlivError as e:
            print(f"WhatsApp não enviado: {e}")
            return 4
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
