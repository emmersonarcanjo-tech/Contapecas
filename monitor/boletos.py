#!/usr/bin/env python3
"""Lista semanal de boletos a pagar (Pizzaria + Sushi) em PDF, pelo WhatsApp.

Regras do Emerson (15/11/2026), toda semana, para o WhatsApp do financeiro:
  - SEGUNDA 07:00: dois PDFs
      1. boletos de sábado, domingo e da própria segunda (e os atrasados, à parte);
      2. boletos de terça a sexta.
  - SEXTA 10:00: conferência — boletos da semana (sábado a sexta) que ficaram de
    fora das listas de segunda (lançados depois) e os que já venceram e continuam
    sem baixa no ALIV.

Só leitura no ALIV (Contas a Pagar), mais o envio pelo WhatsApp da Pizzaria.
A lista de segunda fica gravada em monitor/boletos/AAAA-MM-DD.json para a
conferência de sexta saber o que já foi enviado.

Uso:
  boletos.py segunda [--hoje AAAA-MM-DD] [--para FONE] [--pdf PASTA]
  boletos.py sexta   [--hoje AAAA-MM-DD] [--para FONE] [--pdf PASTA]
Sem --para só gera os PDFs (para conferir). Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import TZ, Aliv, AlivError, brl  # noqa: E402

PASTA = Path(__file__).resolve().parent / "boletos"
LOJAS = {"Pizzaria": ("ALIV_USER", "ALIV_PASS"), "Sushi": ("ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
VERMELHO, DOURADO = "#C8102E", "#D4A017"


def contas_abertas(api: Aliv) -> list[dict]:
    d = api.get("/admin/finance/bills", {"bill_type": "payable", "status": "all"})
    d = d if isinstance(d, list) else d.get("bills", [])
    # só boletos (fornecedor); folha, Pix e cartão não entram na lista do financeiro
    return [b for b in d if not b.get("paid_at") and b.get("due_date") and float(b.get("amount") or 0) > 0
            and "boleto" in str(b.get("payment_method") or "").lower()]


def coletar() -> dict[str, list[dict]]:
    out = {}
    for loja, (u, p) in LOJAS.items():
        if not os.environ.get(u) or not os.environ.get(p):
            raise AlivError(f"{loja}: defina {u} e {p}")
        out[loja] = contas_abertas(Aliv(os.environ[u], os.environ[p]))
    return out


def fornecedor(b: dict) -> tuple[str, str]:
    """'Compra FRISA FRIGORIFICO... - NF 45625 (1/3) (Ped #2160)' → ('FRISA FRIGORIFICO...', 'NF 45625 · 1/3')."""
    d = re.sub(r"\s*\(Ped #\d+\)", "", str(b.get("description") or "")).strip()
    d = re.sub(r"^Compra\s+", "", d)
    nf = re.search(r"NF\s*(\d+)", d)
    parc = re.search(r"\((\d+/\d+)\)", d)
    nome = re.split(r"\s+-\s+NF\s*\d+", d)[0].strip(" -")
    extra = " · ".join(x for x in ((f"NF {nf.group(1)}" if nf else (b.get("document_number") or "")),
                                   (parc.group(1) if parc else "")) if x)
    return nome[:60], extra


def venc(b: dict) -> date:
    return date.fromisoformat(str(b["due_date"])[:10])


def html_lista(titulo: str, sub: str, blocos: list[tuple[str, list[tuple[str, dict]]]], agora: datetime) -> str:
    """blocos = [(rótulo do dia, [(loja, conta), ...]), ...]"""
    total = sum(float(b["amount"]) for _, itens in blocos for _, b in itens)
    n = sum(len(itens) for _, itens in blocos)
    por_loja: dict[str, float] = {}
    for _, itens in blocos:
        for loja, b in itens:
            por_loja[loja] = por_loja.get(loja, 0) + float(b["amount"])
    resumo = " · ".join(f"{lj}: <b>{html.escape(brl(v))}</b>" for lj, v in sorted(por_loja.items()))
    corpo = []
    for rot, itens in blocos:
        if not itens:
            continue
        sub_t = sum(float(b["amount"]) for _, b in itens)
        linhas = "".join(
            f"<tr><td class=lj><span class='tag {lj.lower()}'>{lj}</span></td>"
            f"<td>{html.escape(fornecedor(b)[0])}<div class=nf>{html.escape(fornecedor(b)[1])}</div></td>"
            f"<td class=c>{venc(b):%d/%m}</td><td class=c>{html.escape(str(b.get('payment_method') or ''))}</td>"
            f"<td class=v>{html.escape(brl(float(b['amount'])))}</td><td class=ok>☐</td></tr>"
            for lj, b in sorted(itens, key=lambda x: (x[0], venc(x[1]), fornecedor(x[1])[0])))
        corpo.append(f"<h2>{html.escape(rot)} <span>{len(itens)} boleto(s) · {html.escape(brl(sub_t))}</span></h2>"
                     f"<table><thead><tr><th>Loja</th><th>Fornecedor</th><th>Venc.</th><th>Forma</th>"
                     f"<th class=v>Valor</th><th>Pago</th></tr></thead><tbody>{linhas}</tbody></table>")
    if not corpo:
        corpo.append("<p class=vazio>Nenhum boleto em aberto neste período.</p>")
    css = f"""
    @page {{ size: A4; margin: 12mm 10mm }}
    * {{ box-sizing: border-box }} body {{ font-family: "Liberation Sans", Arial, sans-serif; color: #111; font-size: 11pt; margin: 0 }}
    .faixa {{ height: 6px; background: linear-gradient(90deg,{VERMELHO} 0 62%,{DOURADO} 62% 100%) }}
    header {{ display: flex; justify-content: space-between; align-items: flex-end; margin: 8px 0 10px }}
    h1 {{ font-size: 20pt; margin: 0; color: {VERMELHO} }} h1 span {{ color: #111 }}
    .sub {{ color: #444; font-size: 10.5pt }} .tot {{ text-align: right; font-size: 10.5pt }}
    .tot b.g {{ font-size: 16pt; color: {VERMELHO} }}
    h2 {{ font-size: 12.5pt; margin: 14px 0 4px; border-bottom: 2px solid {DOURADO}; padding-bottom: 2px; text-transform: capitalize }}
    h2 span {{ float: right; font-weight: normal; font-size: 10.5pt; text-transform: none }}
    table {{ width: 100%; border-collapse: collapse; page-break-inside: auto }} tr {{ page-break-inside: avoid }}
    th {{ text-align: left; font-size: 9pt; color: #555; border-bottom: 1px solid #999; padding: 3px 4px }}
    td {{ border-bottom: 1px solid #ddd; padding: 4px; vertical-align: top }}
    .nf {{ font-size: 8.5pt; color: #666 }} .c {{ text-align: center; white-space: nowrap }}
    .v {{ text-align: right; white-space: nowrap; font-weight: bold }} .ok {{ text-align: center; font-size: 14pt; width: 34px }}
    .tag {{ font-size: 8pt; font-weight: bold; padding: 1px 5px; border-radius: 3px; color: #fff }}
    .pizzaria {{ background: {VERMELHO} }} .sushi {{ background: {DOURADO}; color: #111 }} .lj {{ width: 64px }}
    .vazio {{ font-size: 13pt; margin: 30px 0 }}
    footer {{ margin-top: 16px; font-size: 8.5pt; color: #777; text-align: center }}
    """
    return (f"<!doctype html><html lang=pt-br><head><meta charset=utf-8><style>{css}</style></head><body>"
            f"<div class=faixa></div><header><div><h1>Tili <span>· {html.escape(titulo)}</span></h1>"
            f"<div class=sub>{html.escape(sub)}</div></div>"
            f"<div class=tot>{n} boleto(s)<br><b class=g>{html.escape(brl(total))}</b><br>{resumo}</div></header>"
            + "".join(corpo)
            + f"<footer>Contas a Pagar do ALIV (Pizzaria e Sushi) · gerado em {agora:%d/%m/%Y %H:%M} · "
              f"marque ☐ quando pagar e mande o comprovante no WhatsApp da Pizzaria</footer></body></html>")


def pdf(pagina: str, destino: Path) -> Path:
    from painel import _chrome
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "lista.html"
        arq.write_text(pagina, encoding="utf-8")
        subprocess.run([_chrome(), "--headless", "--no-sandbox", "--disable-gpu", f"--user-data-dir={tmp}/p",
                        "--no-pdf-header-footer", f"--print-to-pdf={destino}", arq.as_uri()],
                       capture_output=True, timeout=120)
    if not destino.exists() or destino.stat().st_size < 1000:
        raise RuntimeError("Chromium não gerou o PDF")
    return destino


def por_dia(itens: list[tuple[str, dict]], ini: date, fim: date) -> list[tuple[str, list]]:
    out = []
    d = ini
    while d <= fim:
        out.append((f"{DIAS[d.weekday()]}, {d:%d/%m}", [(lj, b) for lj, b in itens if venc(b) == d]))
        d += timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Lista semanal de boletos (PDF) para o WhatsApp")
    ap.add_argument("modo", choices=["segunda", "sexta"])
    ap.add_argument("--hoje", help="simula o dia (AAAA-MM-DD)")
    ap.add_argument("--para", help="WhatsApp que recebe (ex.: 5573988313572)")
    ap.add_argument("--pdf", default=None, help="pasta dos PDFs (padrão: temporária)")
    a = ap.parse_args()

    agora = datetime.now(TZ)
    hoje = date.fromisoformat(a.hoje) if a.hoje else agora.date()
    pasta = Path(a.pdf) if a.pdf else Path(tempfile.mkdtemp())
    try:
        contas = coletar()
    except (AlivError, OSError) as e:
        print(f"Tili — Boletos — ERRO no ALIV\n\n{e}")
        return 1
    todas = [(lj, b) for lj, bs in contas.items() for b in bs]
    envios: list[tuple[str, Path]] = []

    if a.modo == "segunda":
        seg = hoje - timedelta(days=hoje.weekday())          # a segunda desta semana
        sab, sex = seg - timedelta(days=2), seg + timedelta(days=4)
        atras = [(lj, b) for lj, b in todas if venc(b) < sab]
        blocos1 = por_dia(todas, sab, seg)
        blocos2 = por_dia(todas, seg + timedelta(days=1), sex)
        p1 = pdf(html_lista("Boletos de sábado a segunda", f"Vencimentos de {sab:%d/%m} a {seg:%d/%m}",
                            blocos1, agora), pasta / f"Boletos_{sab:%d-%m}_a_{seg:%d-%m}.pdf")
        p2 = pdf(html_lista("Boletos de terça a sexta", f"Vencimentos de {seg + timedelta(days=1):%d/%m} a {sex:%d/%m}",
                            blocos2, agora), pasta / f"Boletos_{seg + timedelta(days=1):%d-%m}_a_{sex:%d-%m}.pdf")
        t1 = sum(float(b["amount"]) for _, it in blocos1 for _, b in it)
        t2 = sum(float(b["amount"]) for _, it in blocos2 for _, b in it)
        envios = [(f"📄 Boletos de sábado a segunda ({sab:%d/%m} a {seg:%d/%m}): "
                   f"{sum(len(i) for _, i in blocos1)} · {brl(t1)}", p1),
                  (f"📄 Boletos de terça a sexta ({seg + timedelta(days=1):%d/%m} a {sex:%d/%m}): "
                   f"{sum(len(i) for _, i in blocos2)} · {brl(t2)}", p2)]
        PASTA.mkdir(parents=True, exist_ok=True)
        enviados = sorted({f"{lj}:{b['id']}" for _, it in blocos1 + blocos2 for lj, b in it})
        (PASTA / f"{seg.isoformat()}.json").write_text(json.dumps(
            {"segunda": seg.isoformat(), "enviados": enviados, "total": round(t1 + t2, 2)}, indent=1))
    else:
        seg = hoje - timedelta(days=hoje.weekday())
        sab = seg - timedelta(days=2)
        arq = PASTA / f"{seg.isoformat()}.json"
        enviados = set(json.loads(arq.read_text()).get("enviados", [])) if arq.exists() else set()
        fora = [(lj, b) for lj, b in todas if sab <= venc(b) <= hoje + timedelta(days=0)
                and f"{lj}:{b['id']}" not in enviados]
        abertos = [(lj, b) for lj, b in todas if venc(b) < hoje and f"{lj}:{b['id']}" in enviados]
        atras = [(lj, b) for lj, b in todas if venc(b) < sab]
        blocos = [("ficaram de fora da lista de segunda", fora),
                  ("já venceram e continuam sem baixa no ALIV", abertos)]
        sub = (f"Semana {sab:%d/%m} a {hoje:%d/%m}"
               + ("" if arq.exists() else " · ATENÇÃO: lista de segunda não encontrada, tudo entra como 'de fora'"))
        p = pdf(html_lista("Conferência de boletos", sub, blocos, agora), pasta / f"Conferencia_boletos_{hoje:%d-%m}.pdf")
        if fora or abertos:
            envios = [(f"🔎 Conferência de boletos {hoje:%d/%m}: {len(fora)} fora da lista de segunda, "
                       f"{len(abertos)} vencido(s) sem baixa · "
                       f"{brl(sum(float(b['amount']) for _, it in blocos for _, b in it))}", p)]
        else:
            envios = [(f"✅ Conferência de boletos {hoje:%d/%m}: nada ficou de fora e não há boleto vencido sem baixa.", None)]

    for txt, arq_pdf in envios:
        print(txt + (f"\nPDF: {arq_pdf}" if arq_pdf else ""))
    velhos = [(lj, b) for lj, b in todas if venc(b) < hoje - timedelta(days=hoje.weekday() + 2)]
    if velhos:
        print(f"AVISO: {len(velhos)} boleto(s) vencidos antes de sábado continuam sem baixa no ALIV "
              f"({brl(sum(float(b['amount']) for _, b in velhos))}) — fora das listas.")
    if a.para:
        fone = re.sub(r"\D", "", a.para)
        api = Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"])
        try:
            for txt, arq_pdf in envios:
                api.enviar_whatsapp(fone, txt, arquivo=arq_pdf) if arq_pdf else api.enviar_whatsapp(fone, txt)
            print("WHATSAPP: enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
