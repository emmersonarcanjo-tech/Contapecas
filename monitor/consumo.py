#!/usr/bin/env python3
"""Alerta de limite de consumo dos funcionários — Tili Pizzaria (ALIV loja 150).

Regra do Emerson (26/10/2026): R$ 200,00 por funcionário por CICLO.
Ciclo = dia 26 de um mês até dia 25 do mês seguinte (zera no dia 26).
  - "perto"    = consumo do ciclo >= R$ 160,00
  - "estourou" = consumo do ciclo >= R$ 200,00
Consumo = lançamentos CONSUMO na carteira do funcionário
        + pedidos pagos como "Fiado / Carteira" no nome do funcionário
          (sem contar de novo o pedido que já virou CONSUMO na carteira).
Fora da conta: motoboys (driver) e donos (owner).

Só leitura no ALIV. Com --whatsapp manda UMA mensagem para WHATSAPP_EMERSON e
WHATSAPP_ADMIN pelo WhatsApp da loja, e só se alguém estiver perto ou estourado.
Sem --whatsapp só imprime (dry-run). Rodando de madrugada (antes das 08:00),
considera a noite anterior como "hoje" — assim a rodada das 02:20 do dia 26
ainda fecha o ciclo que terminou no dia 25.

Com --fechamento: relatório do ciclo que FECHOU (26 a 25), com todos os
funcionários que consumiram, em texto + PDF. Com --whatsapp manda os dois para
WHATSAPP_EMERSON e WHATSAPP_ADMIN (Rotina do dia 26).

Códigos de saída: 0 ok · 1 erro no ALIV · 2 faltam ALIV_USER/ALIV_PASS · 3 WhatsApp falhou.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from monitor import TZ, Aliv, AlivError, brl

LIMITE = 200.0
AVISO = 160.0
FONES = ("WHATSAPP_EMERSON", "WHATSAPP_ADMIN")
RE_FIADO = re.compile(r"Fiado[^:]*:\s*([\d.,]+)", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def valor_br(s: str) -> float:
    s = s.strip(".,")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def ciclo(hoje: date) -> tuple[date, date]:
    if hoje.day >= 26:
        ini = date(hoje.year, hoje.month, 26)
    else:
        a, m = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
        ini = date(a, m, 26)
    a, m = (ini.year, ini.month + 1) if ini.month < 12 else (ini.year + 1, 1)
    return ini, date(a, m, 25)


def calcular(api: Aliv, hoje: date) -> dict:
    ini, fim = ciclo(hoje)
    INI, HOJE = ini.isoformat(), hoje.isoformat()

    func, vistos = [], set()
    for comp in dict.fromkeys((hoje.strftime("%Y-%m"), ini.strftime("%Y-%m"))):  # inclui quem saiu no ciclo
        folha = api.get("/admin/api/finance/payroll/list", {"competence": comp})
        for r in folha.get("rows", []):
            if r.get("role") not in ("driver", "owner") and r["id"] not in vistos:
                vistos.add(r["id"]); func.append(r)

    total, ja_na_carteira = {}, set()
    for f in func:
        a = api.get(f"/admin/api/finance/driver/{f['id']}/history-audit", {"start": INI, "end": HOJE})
        c = 0.0
        for x in a.get("history", []):
            if x.get("type") != "CONSUMO":
                continue
            c += abs(float(x.get("value") or 0))
            if x.get("related_order_id"):
                ja_na_carteira.add(str(x["related_order_id"]))
        total[f["id"]] = {"nome": f.get("name", "?"), "carteira": c, "fiado": 0.0}

    pedidos, page, more = [], 1, True
    while more and page < 60:
        r = api.get("/admin/api/orders/audit", {"start_date": INI, "end_date": HOJE,
                                                "platform": "all", "page": page})
        pedidos += r.get("orders", [])
        more, page = bool(r.get("has_more")), page + 1

    nomes = [(f["id"], norm(f.get("name"))) for f in func]
    for o in pedidos:
        if re.search(r"CANCEL", str(o.get("status") or ""), re.I):
            continue
        if str(o.get("id")) in ja_na_carteira:
            continue
        m = RE_FIADO.search(str(o.get("payment") or ""))
        if not m:
            continue
        cli = norm(o.get("customer"))
        for fid, nf in nomes:
            if cli == nf or (" " not in cli and cli == nf.split(" ")[0]):
                total[fid]["fiado"] += valor_br(m.group(1))
                break

    lista = sorted(({**t, "soma": round(t["carteira"] + t["fiado"], 2)} for t in total.values()),
                   key=lambda t: -t["soma"])
    return {"ini": ini, "fim": fim, "todos": lista,
            "estourou": [t for t in lista if t["soma"] >= LIMITE],
            "perto": [t for t in lista if AVISO <= t["soma"] < LIMITE]}


def mensagem(r: dict, hoje: date) -> str | None:
    if not (r["estourou"] or r["perto"]):
        return None
    d = lambda x: x.strftime("%d/%m")
    linhas = [f"⚠️ Limite de consumo (R$ {LIMITE:.0f} de {d(r['ini'])} a {d(r['fim'])}) — {d(hoje)}"]
    linhas += [f"• {t['nome']} — {brl(t['soma'])} (estourou)" for t in r["estourou"]]
    linhas += [f"• {t['nome']} — {brl(t['soma'])} (perto)" for t in r["perto"]]
    linhas.append("Caixa: não lançar mais consumo para quem estourou neste ciclo.")
    return "\n".join(linhas)


def fim_do_ultimo_ciclo(hoje: date) -> date:
    """Dia 25 do ciclo que já fechou: dia 25 deste mês (a partir do dia 26) ou do mês passado."""
    if hoje.day >= 26:
        return date(hoje.year, hoje.month, 25)
    primeiro = hoje.replace(day=1) - timedelta(days=1)
    return date(primeiro.year, primeiro.month, 25)


def texto_fechamento(r: dict) -> str:
    d = lambda x: x.strftime("%d/%m")
    usaram = [t for t in r["todos"] if t["soma"] > 0]
    linhas = [f"📊 Fechamento de consumo dos funcionários — ciclo {d(r['ini'])} a {d(r['fim'])}",
              f"Total: {brl(sum(t['soma'] for t in usaram))} · limite {brl(LIMITE)} por funcionário"]
    if r["estourou"]:
        linhas.append(f"Estouraram ({len(r['estourou'])}):")
        linhas += [f"• {t['nome']} — {brl(t['soma'])}" for t in r["estourou"]]
    else:
        linhas.append("Ninguém estourou o limite.")
    if r["perto"]:
        linhas.append("Perto do limite: " + ", ".join(f"{t['nome']} ({brl(t['soma'])})" for t in r["perto"]))
    prox = r["fim"] + timedelta(days=1)
    linhas.append(f"Novo ciclo: {d(prox)} a 25/{(prox.replace(day=28) + timedelta(days=4)).strftime('%m')}.")
    return "\n".join(linhas)


def pdf_fechamento(r: dict, destino: Path) -> Path:
    import base64
    from diaristas import html_para_pdf
    logo = Path(__file__).resolve().parent / "assets" / "logo_tili.png"
    img = f'<img src="data:image/png;base64,{base64.b64encode(logo.read_bytes()).decode()}">' if logo.exists() else ""
    usaram = [t for t in r["todos"] if t["soma"] > 0]
    def sit(v):
        return ("<span class='tag est'>ESTOUROU</span>" if v >= LIMITE else
                "<span class='tag per'>PERTO</span>" if v >= AVISO else "<span class='tag ok'>OK</span>")
    linhas = "".join(f"<tr><td>{t['nome']}</td><td class=n>{brl(t['soma'])}</td>"
                     f"<td class=n>{brl(t['soma'] - LIMITE) if t['soma'] > LIMITE else '—'}</td><td>{sit(t['soma'])}</td></tr>"
                     for t in usaram) or "<tr><td colspan=4>Ninguém consumiu no ciclo.</td></tr>"
    exc = sum(t["soma"] - LIMITE for t in r["estourou"])
    d = lambda x: x.strftime("%d/%m/%Y")
    html = f"""<!doctype html><html><head><meta charset=utf-8><style>
@page{{size:A4;margin:14mm}} body{{font-family:Arial,sans-serif;color:#222;font-size:12px}}
.top{{display:flex;align-items:center;gap:14px;border-bottom:4px solid #C8102E;padding-bottom:8px}} .top img{{height:58px}}
h1{{margin:0;color:#C8102E;font-size:20px}} .sub{{color:#666}}
.cards{{display:flex;gap:10px;margin:14px 0}} .card{{flex:1;border:1px solid #F2B705;background:#fffbea;border-radius:6px;padding:8px 10px}}
.card b{{display:block;font-size:20px;color:#C8102E}}
h2{{color:#fff;background:#C8102E;padding:5px 8px;font-size:13px;margin:14px 0 6px;border-left:6px solid #F2B705}}
table{{width:100%;border-collapse:collapse}} th{{background:#F2B705;text-align:left;padding:6px}} td{{padding:6px;border-bottom:1px solid #ddd}}
.n{{text-align:right}} .tag{{padding:2px 8px;border-radius:10px;color:#fff;font-weight:bold;font-size:10.5px}}
.est{{background:#C8102E}} .per{{background:#e08a00}} .ok{{background:#2e8b57}}
.box{{border:1px solid #F2B705;background:#fffbea;padding:8px 10px;margin-top:12px;line-height:1.5}}
</style></head><body>
<div class=top>{img}<div><h1>Fechamento de consumo dos funcionários</h1>
<div class=sub>Tili Pizzaria · ciclo {d(r['ini'])} a {d(r['fim'])} · limite {brl(LIMITE)} por funcionário</div></div></div>
<div class=cards><div class=card>Consumo total do ciclo<b>{brl(sum(t['soma'] for t in usaram))}</b></div>
<div class=card>Funcionários que consumiram<b>{len(usaram)}</b></div><div class=card>Estouraram o limite<b>{len(r['estourou'])}</b></div></div>
<h2>Consumo por funcionário</h2>
<table><tr><th>Funcionário</th><th class=n>Consumo no ciclo</th><th class=n>Acima do limite</th><th>Situação</th></tr>{linhas}</table>
<div class=box><b>Como foi calculado:</b> consumo lançado na conta do funcionário + pedidos pagos em "Fiado / Carteira"
no nome dele, no ciclo. Motoboys e donos ficam de fora.<br><b>Excedente total:</b> {brl(exc)} acima do limite, somando quem estourou.</div>
</body></html>"""
    return html_para_pdf(html, destino)


def enviar(api: Aliv, texto: str, pdf: Path | None = None, legenda: str = "") -> int:
    falhas = 0
    for var in FONES:
        fone = re.sub(r"\D", "", os.environ.get(var, ""))
        if not fone:
            print(f"WHATSAPP {var}: variável não definida", file=sys.stderr)
            falhas += 1
            continue
        try:
            api.enviar_whatsapp(fone, texto)
            if pdf is not None:
                api.enviar_whatsapp(fone, legenda, arquivo=pdf)
            print(f"WHATSAPP {var}: enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP {var}: falhou — {e}", file=sys.stderr)
            falhas += 1
    return falhas


def main() -> int:
    ap = argparse.ArgumentParser(description="Alerta de limite de consumo dos funcionários (ALIV, só leitura)")
    ap.add_argument("--hoje", help="simula a data (AAAA-MM-DD)")
    ap.add_argument("--whatsapp", action="store_true", help="envia o alerta (sem isso, só mostra)")
    ap.add_argument("--fechamento", action="store_true", help="relatório (texto + PDF) do ciclo que fechou no dia 25")
    ap.add_argument("--pdf", metavar="ARQ.pdf", help="onde salvar o PDF do fechamento")
    a = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: faltam ALIV_USER/ALIV_PASS.", file=sys.stderr)
        return 2
    if a.hoje:
        hoje = date.fromisoformat(a.hoje)
    else:  # madrugada (antes das 08:00) ainda conta como a noite anterior
        hoje = (datetime.now(TZ) - timedelta(hours=8)).date()
    if a.fechamento:
        hoje = fim_do_ultimo_ciclo(hoje if a.hoje else datetime.now(TZ).date())
    api = Aliv(user, pwd)
    try:
        r = calcular(api, hoje)
    except (AlivError, OSError) as e:
        print(f"ERRO ALIV: {e}", file=sys.stderr)
        return 1

    print(f"Ciclo {r['ini']:%d/%m} a {r['fim']:%d/%m} — {len(r['todos'])} funcionários")
    for t in r["todos"]:
        if t["soma"] > 0:
            print(f"  {t['nome']}: {brl(t['soma'])} (carteira {brl(t['carteira'])} + fiado {brl(t['fiado'])})")
    if a.fechamento:
        texto = texto_fechamento(r)
        print("\n" + texto)
        destino = Path(a.pdf) if a.pdf else Path(tempfile_dir()) / f"Consumo_funcionarios_{r['ini']:%d-%m}_a_{r['fim']:%d-%m}.pdf"
        try:
            pdf = pdf_fechamento(r, destino)
            print(f"PDF: {pdf}")
        except Exception as e:  # sem PDF ainda manda o texto
            print(f"PDF não gerado: {e}", file=sys.stderr)
            pdf = None
        if not a.whatsapp:
            print("\n(dry-run: WhatsApp não enviado)")
            return 0
        falhas = enviar(api, texto, pdf, f"Fechamento de consumo {r['ini']:%d/%m} a {r['fim']:%d/%m}")
        return 3 if falhas or pdf is None else 0

    msg = mensagem(r, hoje)
    if not msg:
        print("Ninguém perto do limite — nada enviado.")
        return 0
    print("\n" + msg)
    if not a.whatsapp:
        print("\n(dry-run: WhatsApp não enviado)")
        return 0

    return 3 if enviar(api, msg) else 0


def tempfile_dir() -> str:
    import tempfile
    return tempfile.gettempdir()


if __name__ == "__main__":
    sys.exit(main())
