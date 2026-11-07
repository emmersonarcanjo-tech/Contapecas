#!/usr/bin/env python3
"""Lança no ALIV, como PAGAS, as despesas do WhatsApp já lidas da foto.

Entrada: um JSON (lista) que a Rotina monta depois de olhar as fotos de
monitor/despesas/fotos/. Cada item:

  {"wamid": "...",                  # da despesa em monitor/despesas/AAAA-MM-DD.json
   "loja": "pizzaria" | "sushi",
   "fornecedor": "Mateus Supermercados",
   "detalhe": "NFC-e 130439: 5 cebolinha",   # documento + itens, igual à rotina antiga
   "valor": 19.95,
   "forma": "Cartão Crédito" | "Dinheiro" | "Pix" | "Cartão Débito",
   "categoria": "Compras" | "Aluguel e Contas",   # manutenção → Aluguel e Contas
   "documento": "130439",                         # opcional
   "data": "2026-11-03"}                          # opcional, padrão = dia da mensagem

Descrição gravada (padrão da rotina antiga):
  WPP | <fornecedor> | <detalhe> | <remetente> dd/mm HH:MM

Usa POST /admin/finance/bills/save (o mesmo da tela Contas a Pagar), com
pay_on_create=true e payment_origin=none (não mexe em caixa nem banco).
Antes, confere duplicata na loja (mesmo valor no mesmo dia com o mesmo nº de
documento, ou a mesma descrição). Grava bill_id em monitor/despesas/AAAA-MM-DD.json.

Sem --confirmar, só mostra o que faria (nada é lançado).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import uuid
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, Aliv, AlivError  # noqa: E402

PASTA = Path(__file__).resolve().parent / "despesas"
LOJAS = {"pizzaria": ("ALIV_USER", "ALIV_PASS"), "sushi": ("ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")}
FORMAS = {"cartao credito", "cartao debito", "dinheiro", "pix"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def achar_despesa(wamid: str) -> tuple[Path, dict, dict] | None:
    for f in sorted(PASTA.glob("*.json"), reverse=True):
        try:
            doc = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        for d in doc.get("despesas", []):
            if d.get("wamid") == wamid:
                return f, doc, d
    return None


def post_form(api: Aliv, path: str, campos: dict) -> tuple[int, dict]:
    b = uuid.uuid4().hex
    body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                   for k, v in campos.items()) + f"--{b}--\r\n"
    req = urllib.request.Request(BASE_URL + path, data=body.encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    st, data = api._send(req)
    if st == 401:
        api.login()
        st, data = api._send(req)
    return st, data


class Loja:
    def __init__(self, nome: str):
        u, p = LOJAS[nome]
        if not os.environ.get(u) or not os.environ.get(p):
            raise AlivError(f"faltam {u}/{p}")
        self.nome, self.api = nome, Aliv(os.environ[u], os.environ[p])
        self.categorias = {norm(c["name"]): c["id"] for c in self.api.get("/admin/api/finance/bill-categories/list")}
        self.formas = {norm(f["name"]): f["name"] for f in self.api.get("/admin/api/finance/payment-methods/list")}

    def contas(self, dia: str) -> list[dict]:
        d = date.fromisoformat(dia)
        return self.api.get("/admin/finance/bills", {
            "status": "all", "bill_type": "payable",
            "start_date": (d - timedelta(days=3)).isoformat(), "end_date": (d + timedelta(days=3)).isoformat()}) or []


def main() -> int:
    ap = argparse.ArgumentParser(description="Lança despesas do WhatsApp no ALIV como pagas")
    ap.add_argument("entrada", type=Path, help="JSON com a lista de despesas lidas das fotos")
    ap.add_argument("--confirmar", action="store_true", help="lança de verdade (sem isso, só mostra)")
    ap.add_argument("--whatsapp", action="store_true", help="manda o resultado para WHATSAPP_EMERSON")
    ap.add_argument("--extra", default="", help="texto a mais no fim da mensagem (ex.: fotos sem leitura)")
    a = ap.parse_args()

    itens = json.loads(a.entrada.read_text())
    lojas: dict[str, Loja] = {}
    linhas, erros, lancadas = [], 0, 0
    for it in itens:
        w = it.get("wamid")
        achado = achar_despesa(w)
        if not achado:
            linhas.append(f"✗ {w}: despesa não encontrada nos JSON do dia")
            erros += 1
            continue
        arq, doc, d = achado
        if d.get("lancamento", {}).get("bill_id"):
            linhas.append(f"= {d['remetente']} {d['hora']}: já lançada (#{d['lancamento']['bill_id']})")
            continue
        loja = norm(it.get("loja") or "pizzaria")
        if loja not in LOJAS:
            linhas.append(f"✗ {d['remetente']} {d['hora']}: loja inválida '{it.get('loja')}'")
            erros += 1
            continue
        try:
            L = lojas.get(loja) or lojas.setdefault(loja, Loja(loja))
        except AlivError as e:
            linhas.append(f"✗ {loja}: {e}")
            erros += 1
            continue
        valor = round(float(it.get("valor") or 0), 2)
        forma = L.formas.get(norm(it.get("forma") or "Cartão Crédito"))
        cat = L.categorias.get(norm(it.get("categoria") or "Compras")) or L.categorias.get("compras")
        dia = it.get("data") or d["data"]
        if valor <= 0 or not forma or norm(forma) not in FORMAS or not it.get("fornecedor") or not it.get("detalhe"):
            linhas.append(f"✗ {d['remetente']} {d['hora']}: falta valor/forma/fornecedor/detalhe ({it})")
            erros += 1
            continue
        ddmm = f"{d['data'][8:10]}/{d['data'][5:7]}"
        desc = f"WPP | {it['fornecedor'].strip()} | {it['detalhe'].strip()} | {d['remetente']} {ddmm} {d['hora']}"
        docnum = str(it.get("documento") or "").strip()

        # duplicata: mesma descrição, ou mesmo valor+dia com mesmo documento (ou sem documento e mesmo fornecedor)
        dup = None
        for b in L.contas(dia):
            mesmo_valor = abs(float(b.get("amount") or 0) - valor) < 0.01
            mesmo_dia = str(b.get("due_date", ""))[:10] == dia
            if norm(b.get("description")) == norm(desc) or (mesmo_valor and mesmo_dia and (
                    (docnum and str(b.get("document_number") or "") == docnum)
                    or (not docnum and norm(it["fornecedor"])[:12] in norm(b.get("description"))))):
                dup = b
                break
        if dup:
            linhas.append(f"⚠️ {L.nome} · {d['remetente']} {d['hora']} · R$ {valor:.2f}: possível duplicada (#{dup['id']} "
                          f"{str(dup.get('description'))[:60]}). Não lancei.")
            if a.confirmar:
                d["lancamento"] = {"duplicada_de": dup["id"], "loja": L.nome}
                arq.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
            continue

        campos = {"bill_type": "payable", "description": desc, "amount": f"{valor:.2f}", "due_date": dia,
                  "payment_method": forma, "category_id": str(cat), "issue_date": dia,
                  "is_recurring": "false", "installments": "1",
                  "pay_on_create": "true", "payment_origin": "none", "payment_date": dia}
        if docnum:
            campos["document_number"] = docnum
        if not a.confirmar:
            linhas.append(f"(teste) {L.nome} · R$ {valor:.2f} · {forma} · {desc}")
            continue
        st, resp = post_form(L.api, "/admin/finance/bills/save", campos)
        if st != 200 or (isinstance(resp, dict) and resp.get("success") is False):
            linhas.append(f"✗ {L.nome} · {desc}: HTTP {st} {str(resp)[:150]}")
            erros += 1
            continue
        # confirma e pega o id na listagem
        bill = next((b for b in L.contas(dia) if norm(b.get("description")) == norm(desc)), None)
        if not bill:
            linhas.append(f"✗ {L.nome} · {desc}: ALIV respondeu ok, mas não achei a conta na lista")
            erros += 1
            continue
        d["lancamento"] = {"bill_id": bill["id"], "loja": L.nome, "valor": valor, "forma": forma,
                           "descricao": desc, "paga": bool(bill.get("paid_at"))}
        arq.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        lancadas += 1
        linhas.append(f"✓ {L.nome} #{bill['id']} · R$ {valor:.2f} · {forma} · {desc}"
                      + ("" if bill.get("paid_at") else " · ⚠️ NÃO ficou paga"))

    total = sum(float(it.get("valor") or 0) for it in itens)
    msg = [f"*Tili Despesas* — {lancadas} lançada(s) no ALIV como pagas · {erros} erro(s) · total lido R$ {total:.2f}"
           .replace(".", ",") + ("" if a.confirmar else " — TESTE, nada lançado")]
    msg += linhas
    if a.extra:
        msg.append(a.extra)
    texto = "\n".join(msg)
    print(texto)
    if a.whatsapp and itens:
        fone = os.environ.get("WHATSAPP_EMERSON", "")
        try:
            # sempre pelo WhatsApp da Pizzaria (loja 150), o mesmo dos outros relatórios
            (lojas.get("pizzaria") or Loja("pizzaria")).api.enviar_whatsapp(fone, texto)
            print("WhatsApp enviado.")
        except AlivError as e:
            print(f"WhatsApp não enviado: {e}")
            return 4
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
