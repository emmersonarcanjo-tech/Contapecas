#!/usr/bin/env python3
"""Guias de imposto da contabilidade (Mamed) → Contas a Pagar do ALIV (Pizzaria).

Regra do Emerson (15/11/2026): as guias chegam no e-mail tilipizzariadp@gmail.com
(fiscal@ / dp@mamedcontabilidade.com.br). A Rotina baixa os PDFs pelo conector do
Gmail e chama este script, que:
  - lê o PDF (pdftotext): tipo da guia, competência, vencimento, valor e nº do documento;
  - lança na Pizzaria (matriz + filial ficam numa loja só), categoria "Impostos e
    Encargos", forma "Boleto via DDA", EM ABERTO (a baixa vem do comprovante);
  - não duplica: pula se já existe conta com o mesmo nº de documento, ou com o mesmo
    tipo + competência + empresa.
Guia que não der para ler com certeza NÃO é lançada: vai para o aviso do Emerson.
Recibos/holerites da folha NÃO entram aqui (a folha já é lançada pelo folha_clt.py).

Uso:
  guias.py lancar ENTRADA.json [--confirmar] [--whatsapp]
ENTRADA.json: [{"pdf": "/caminho/guia.pdf", "assunto": "DAS 10/2026 - ...", "arquivo": "DAS 10.2026 - SO DELIVERY .pdf",
                "msg_id": "...", "data_email": "2026-11-10"}]
Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, Aliv, AlivError, brl  # noqa: E402

ESTADO = Path(__file__).resolve().parent / "guias" / "estado.json"
TIPOS = [  # (regex no nome do arquivo/assunto/texto, rótulo)
    (r"PARC(\.|ELAMENTO)?\s*SIMPLIFICADO", "Parcelamento simplificado"),
    (r"PGFN|SISPAR", "Parcelamento PGFN"),
    (r"PARCSN|PARC\.?\s*SIMPLES", "Parcelamento Simples Nacional"),
    (r"\bDAS\b", "DAS Simples Nacional"),
    (r"FGTS|GFD", "FGTS"),
    (r"DCTF|DARF|INSS", "INSS/DARF"),
    (r"\bDAE\b|ICMS", "ICMS (DAE)"),
    (r"EXTIN[CÇ][AÃ]O DE INC[EÊ]NDIO|BOMBEIRO", "Taxa de incêndio"),
]
FOLHA = re.compile(r"RECIBO|HOLERITE|EXTRATO MENSAL|FICHA|RESCIS|ADMISS|F[EÉ]RIAS|13", re.I)


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).upper()


def num(v: str) -> float:
    return float(v.replace(".", "").replace(",", "."))


def ler_pdf(caminho: str) -> str:
    return subprocess.run(["pdftotext", "-layout", caminho, "-"], capture_output=True, text=True, timeout=60).stdout


def interpretar(item: dict) -> dict:
    """Devolve {tipo, competencia, vencimento, valor, documento, empresa} ou {erro}."""
    txt = ler_pdf(item["pdf"])
    if not txt.strip():
        return {"erro": "PDF sem texto (imagem?)"}
    base = sem_acento(f"{item.get('arquivo', '')} {item.get('assunto', '')}")
    if FOLHA.search(base) and not re.search(r"FGTS|DCTF|DARF|GUIA", base):
        return {"ignorar": "documento da folha (não é guia)"}
    tipo = next((rot for rx, rot in TIPOS if re.search(rx, base)), None) or \
        next((rot for rx, rot in TIPOS if re.search(rx, sem_acento(txt))), None)
    if not tipo:
        return {"erro": "não reconheci o tipo da guia"}
    # vencimento: "Pagar até: dd/mm/aaaa" / "DATA DE VENCIMENTO dd/mm/aaaa" / "Vencimento dd/mm/aaaa"
    venc = None
    for rx in (r"Pagar (?:este documento )?at[eé]:?\s*(\d{2}/\d{2}/\d{4})", r"DATA DE VENCIMENTO\s+(\d{2}/\d{2}/\d{4})",
               r"Vencimento:?\s*(\d{2}/\d{2}/\d{4})", r"Data de Vencimento[^\n]*\n[^\n]*?(\d{2}/\d{2}/\d{4})"):
        mm = re.search(rx, txt, re.I)
        if mm:
            venc = mm.group(1)
            break
    valor = None
    for rx in (r"Valor:\s*([\d.]+,\d{2})", r"VALOR TOTAL\s+([\d.]+,\d{2})", r"Valor Total do Documento[^\n]*\n[^\n]*?([\d.]+,\d{2})",
               r"Totais\s+([\d.]+,\d{2})", r"Total a (?:pagar|recolher):?\s*R?\$?\s*([\d.]+,\d{2})"):
        mm = re.search(rx, txt, re.I)
        if mm:
            valor = num(mm.group(1))
            break
    doc = re.search(r"(\d{2}\.\d{2}\.\d{5}\.\d{7}-\d)", txt)
    comp = re.search(r"(\d{2})[./](20\d{2})", base) or re.search(
        r"(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)/(20\d{2})", txt, re.I)
    meses = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
             "novembro", "dezembro"]
    competencia = None
    if comp:
        m1 = comp.group(1).lower().replace("ç", "c")
        competencia = f"{(meses.index(m1) + 1) if m1 in meses else int(m1):02d}/{comp.group(2)}"
    parcela = re.search(r"Parcela:\s*(\d+/\d+)", txt)
    empresa = "Tili Pizzaria e Restaurante" if "TILI PIZZARIA E RESTAURANTE" in sem_acento(base + txt) \
        and "SO DELIVERY" not in sem_acento(base) else "So Delivery (matriz + filial)"
    if not venc or not valor:
        return {"erro": f"não achei {'o vencimento' if not venc else 'o valor'} no PDF", "tipo": tipo}
    d, mth, y = venc.split("/")
    return {"tipo": tipo, "competencia": competencia, "vencimento": f"{y}-{mth}-{d}", "valor": valor,
            "documento": doc.group(1) if doc else None, "parcela": parcela.group(1) if parcela else None,
            "empresa": empresa}


def chave(g: dict) -> str:
    return sem_acento(f"{g['tipo']} {g.get('competencia') or ''} {g.get('parcela') or ''} {g['empresa']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Guias da contabilidade → Contas a Pagar do ALIV")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("lancar")
    lp.add_argument("entrada")
    lp.add_argument("--confirmar", action="store_true")
    lp.add_argument("--whatsapp", action="store_true")
    a = ap.parse_args()

    itens = json.loads(Path(a.entrada).read_text())
    try:
        est = json.loads(ESTADO.read_text())
    except (OSError, json.JSONDecodeError):
        est = {"lancadas": {}}
    api = Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"])
    try:
        api.login()
        cats = {c["name"]: c["id"] for c in api.get("/admin/finance/categories")}
        contas = api.get("/admin/finance/bills", {"bill_type": "payable", "status": "all"})
        contas = contas if isinstance(contas, list) else contas.get("bills", [])
    except (AlivError, OSError) as e:
        print(f"Tili — Guias — ERRO no ALIV\n\n{e}")
        return 1
    docs = {str(c.get("document_number") or "") for c in contas}
    descs = [sem_acento(str(c.get("description") or "")) for c in contas]
    ok, avisos = [], []
    for it in itens:
        g = interpretar(it)
        nome = it.get("arquivo") or Path(it["pdf"]).name
        if g.get("ignorar"):
            continue
        if g.get("erro"):
            avisos.append(f"{nome}: {g['erro']} — conferir no e-mail")
            continue
        desc = (f"{g['tipo']} {g.get('competencia') or ''}" + (f" parcela {g['parcela']}" if g.get("parcela") else "")
                + f" — {g['empresa']}").replace("  ", " ")
        k = chave(g)
        comp_tipo = sem_acento(f"{g['tipo']} {g.get('competencia') or ''}")
        repetida = (g.get("documento") and g["documento"] in docs) or k in est["lancadas"] or \
            any(comp_tipo in d and (not g.get("parcela") or g["parcela"] in d) for d in descs)
        txt = f"{desc} · vence {g['vencimento'][8:]}/{g['vencimento'][5:7]} · {brl(g['valor'])}"
        if repetida:
            continue
        if not a.confirmar:
            ok.append("(teste) " + txt)
            continue
        c = {"bill_type": "payable", "description": desc, "amount": f"{g['valor']:.2f}", "due_date": g["vencimento"],
             "payment_method": "Boleto via DDA", "category_id": cats.get("Impostos e Encargos"),
             "is_recurring": "false", "installments": "1", "document_number": g.get("documento") or ""}
        bnd = uuid.uuid4().hex
        body = "".join(f'--{bnd}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'
                       for n, v in c.items()) + f"--{bnd}--\r\n"
        st, d = api._send(urllib.request.Request(BASE_URL + "/admin/finance/bills/save", data=body.encode(), method="POST",
                                                 headers={"Content-Type": f"multipart/form-data; boundary={bnd}",
                                                          "Accept": "application/json"}))
        if st == 200 and isinstance(d, dict) and d.get("success"):
            ok.append("✓ " + txt + (" ⚠️ JÁ VENCIDA" if g["vencimento"] < date.today().isoformat() else ""))
            est["lancadas"][k] = {"valor": g["valor"], "venc": g["vencimento"]}
            descs.append(sem_acento(desc))
        else:
            avisos.append(f"{txt}: ALIV recusou ({str(d)[:100]})")
    if a.confirmar:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1))
    if not ok and not avisos:
        print("Tili — Guias: nada novo.")
        return 0
    texto = ("*Tili — Guias da contabilidade* lançadas no ALIV (Pizzaria, em aberto): " + str(len(ok))
             + ("" if a.confirmar else " — TESTE, nada lançado") + ("\n" + "\n".join(ok) if ok else "")
             + ("\n\n*Conferir* (não lancei):\n" + "\n".join("• " + x for x in avisos) if avisos else ""))
    print(texto)
    if a.whatsapp:
        try:
            api.enviar_whatsapp(re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", "")), texto[:3800])
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
