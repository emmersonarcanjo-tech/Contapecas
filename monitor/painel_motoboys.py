"""Painel em PNG da previsão de motoboys (previsao_motoboys.py) — para mandar no WhatsApp.

Mesmo layout do painel de vendas (painel.py): cores da Tili, logo, 3 colunas em 2880 px,
fotografado pelo Chromium headless.

Uso: gerar_painel(destino, hoje, base, rec, motivos, semana).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path

from diaristas import _logo_src
from monitor import TZ
from painel import CSS, DOURADO, VERMELHO, _card, _e, html_para_png

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
DC = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

CSS_EXTRA = f"""
.hero {{ margin: 0 40px 6px; display: grid; grid-template-columns: 820px 1fr; gap: 36px; align-items: center;
         background: linear-gradient(135deg, #3a0a14, #262626 70%); border-radius: 20px;
         border-left: 12px solid {DOURADO}; padding: 26px 34px }}
.hero .rot {{ font-size: 32px }}
.hero .num {{ font-size: 150px; font-weight: 900; color: {DOURADO}; line-height: 1; letter-spacing: -3px }}
.hero .num small {{ font-size: 60px; color: #fff; letter-spacing: 0; font-weight: 800 }}
.hero .pq {{ font-size: 34px; line-height: 1.35 }}
.hero .pq p + p {{ margin-top: 12px; color: #ddd }}
.chips {{ margin-top: 16px; display: flex; gap: 12px; flex-wrap: wrap }}
.chip {{ background: {VERMELHO}; border-radius: 30px; padding: 6px 20px; font-size: 28px; font-weight: 800 }}
.chip.neutro {{ background: #3a3a3a; color: #ccc }}
.hora {{ display: grid; grid-template-columns: 90px 1fr 120px 210px; align-items: center; gap: 16px; padding: 8px 0 }}
.hora .h {{ font-size: 30px; font-weight: 800 }}
.hora .e {{ font-size: 30px; font-weight: 800; text-align: right }}
.hora .m {{ font-size: 30px; font-weight: 800; text-align: right; color: {DOURADO}; white-space: nowrap }}
.hora.pico .h, .hora.pico .e {{ color: {DOURADO} }}
.dias .card {{ padding: 18px 22px }}
.dias .val {{ font-size: 46px }}
.tag {{ float: right; font-size: 24px; font-weight: 800; padding: 4px 14px; border-radius: 20px }}
.tag.ok {{ background: #2e9d57 }} .tag.no {{ background: {VERMELHO} }}
.como {{ margin: 0 20px; background: #262626; border-radius: 20px; padding: 18px 24px; font-size: 27px;
         color: #ccc; line-height: 1.4 }}
.como b {{ color: #fff }}
"""


def _h(h: int) -> str:
    return f"{h % 24:02d}h"


def _f1(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def _horas(rec: dict) -> str:
    hp = rec["horas_prev"]
    maior = max(list(hp.values()) + [1.0])
    pico = max(hp, key=hp.get)
    linhas = []
    for h, v in hp.items():
        m = max(1, math.ceil(v / rec["cap"])) if v >= 1 else 0
        linhas.append(
            f'<div class="hora{" pico" if h == pico else ""}"><div class="h">{_h(h)}</div>'
            f'<div class="trilho"><i style="width:{max(v / maior * 100, 1.5):.1f}%;'
            f'background:{DOURADO if h == pico else VERMELHO}"></i></div>'
            f'<div class="e">{v:.0f}</div><div class="m">{f"{m} motoboy" + ("s" if m != 1 else "") if m else "—"}</div></div>')
    return ('<div class="barras"><div class="t">Entregas previstas por hora → motoboys na rua</div>'
            + "".join(linhas) + "</div>")


def _chuva(c: dict | None) -> str:
    if not c:
        return ""
    if c["status"] == "indisponível":
        return ('<div class="sec">CHUVA HOJE (17h–00h)</div><div class="grade">'
                + _card("Previsão do tempo", "indisponível", "a recomendação saiu sem considerar chuva") + "</div>")
    titulo = {"forte": "CHUVA FORTE", "chuva": "VAI CHOVER", "possível": "PODE CHOVER", "seco": "SEM CHUVA"}[c["status"]]
    cls = {"forte": "ruim", "chuva": "ruim", "possível": "d", "seco": "bom"}[c["status"]]
    det = (f"{c['concordam']} de {c['total']} modelos preveem chuva · ~{_f1(c['mm'])} mm")
    meta = (f"+{c['extra']} motoboys já somados na recomendação" if c["extra"]
            else "sem consenso: não somei; se começar a chover, chame +2" if c["status"] == "possível"
            else "nenhum motoboy a mais")
    linhas = "".join(
        f'<div class="hora"><div class="h">{_h(h)}</div><div class="trilho"><i style="width:{max(v, 1.5):.0f}%;'
        f'background:{"#3b82f6" if v >= 60 else "#64748b"}"></i></div><div class="e">{v:.0f}%</div>'
        f'<div class="m">{"chuva" if v >= 60 else ""}</div></div>'
        for h, v in sorted(c["horas"].items()))
    mods = " · ".join(f"{n.split(' ')[0]}: {'chuva' if m['ve_chuva'] else 'seco'} ({m['prob_max']:.0f}%, {_f1(m['mm'])} mm)"
                      for n, m in c["modelos"].items())
    return (f'<div class="sec">CHUVA HOJE (17h–00h)</div><div class="grade">'
            f'{_card("Previsão do tempo · Porto Seguro", titulo, det, meta, cls)}'
            f'<div class="barras"><div class="t">Chance de chuva por hora (média dos modelos)</div>{linhas}'
            f'<div class="meta" style="margin-top:10px">{_e(mods)}</div></div></div>')


def _dia_card(x, titulo: str) -> str:
    tag = '<span class="tag no">ESTOUROU</span>' if x.estourou else '<span class="tag ok">NO TEMPO</span>'
    sushi = "" if x.sushi_ok else " (sem Sushi)"
    return (f'<div class="card {"ruim" if x.estourou else "bom"}">{tag}'
            f'<div class="rot">{_e(titulo)}</div>'
            f'<div class="val">{x.motoboys} motoboys</div>'
            f'<div class="det">{sum(x.total_h.values())} entregas{_e(sushi)} · pico {_h(x.pico)} com {x.entregas_pico}'
            f' ({x.motos_pico} na rua)</div>'
            f'<div class="meta">{_f1(x.eph)} entregas/motoboy/h · rua {x.rua:.0f} · vida {x.vida:.0f} min · '
            f'{x.atrasos} acima de 45 min ({x.pct_atraso * 100:.0f}%)</div></div>')


def html_painel(hoje: date, base: list, rec: dict, motivos: list[str], semana: list) -> str:
    agora = datetime.now(TZ)
    P = [f'<div class="faixa"></div><div class="topo"><div class="logo"><img src="{_logo_src()}"></div>'
         f'<div><div class="titulo">Motoboys <span>Tili</span></div>'
         f'<div class="sub">Previsão para hoje, {DIAS[hoje.weekday()]} {hoje:%d/%m} · '
         f'Pizzaria + Sushi · gerado {agora:%d/%m às %H:%M}</div></div></div>']

    # Recomendação em destaque
    b = rec["base_cap"]
    p1 = f"Pico previsto de <b>~{rec['pico_prev']:.0f} entregas/h</b> às {_h(max(rec['horas_prev'], key=rec['horas_prev'].get))}" \
         f" e ~{rec['dia_prev']:.0f} entregas no dia."
    if b:
        p2 = (f"Sem atraso, cada motoboy faz até <b>{_f1(rec['cap'])} entregas/h</b> no pico "
              f"(como em {b.dia:%d/%m}, com {b.motos_pico} na rua).")
    else:
        p2 = f"Nenhum dia sem atraso na base: usei {_f1(rec['cap'])} entregas/motoboy/h, com folga."
    sobre = [x for x in rec["ruins"] if x.eph > rec["cap"]]
    if sobre:
        r = max(sobre, key=lambda x: x.eph)
        p2 += f" Em {r.dia:%d/%m} estourou com {r.motos_pico} na rua ({_f1(r.eph)}/motoboy/h)."
    elif rec["ruins"]:
        p2 += " Nos dias que estouraram não faltou motoboy: o atraso veio da cozinha/expedição."
    chips = "".join(f'<span class="chip">{_e(m)}</span>' for m in motivos) or \
        '<span class="chip neutro">dia normal · sem feriado ou promoção</span>'
    P.append(f'<div class="hero"><div><div class="rot">CHAMAR HOJE</div>'
             f'<div class="num">{rec["lo"]} a {rec["hi"]} <small>motoboys</small></div></div>'
             f'<div class="pq"><p>{p1}</p><p>{p2}</p><div class="chips">{chips}</div></div></div>')

    # Alerta da semana passada
    if semana:
        P.append(f'<div class="alertas" style="margin-top:20px"><div class="cab">ATRASO NA SEMANA PASSADA '
                 f'({len(semana)} de 7 dias com entrega acima de 45 min)</div><ul>'
                 + "".join(f"<li>{DC[d.weekday()]} {d:%d/%m}: {a} entregas acima de 45 min"
                           f"{f' ({a / n * 100:.0f}%)' if n else ''} · vida média {v:.0f} min</li>"
                           for d, a, n, v in semana) + "</ul></div>")
    else:
        P.append('<div class="semalerta" style="margin-top:20px">Semana passada sem entrega acima de 45 min</div>')

    P.append('<div class="colunas"><div>')
    # Coluna 1: previsão por hora
    P.append('<div class="sec">PREVISÃO DE HOJE</div><div class="grade g3">')
    P.append(_card("Pico previsto", f"{rec['pico_prev']:.0f}/h", "entregas na hora de pico", cls="d"))
    P.append(_card("Entregas no dia", f"~{rec['dia_prev']:.0f}", "16h às 00h", cls="d"))
    P.append(_card("Ritmo seguro", _f1(rec["cap"]), "entregas/motoboy/h", cls="v"))
    P.append('</div><div class="sec">QUANDO CHAMAR</div><div class="grade">')
    P.append(_horas(rec))
    P.append('</div>')
    P.append(_chuva(rec.get("chuva")))

    # Coluna 2: histórico
    P.append('</div><div><div class="sec">ÚLTIMAS 4 SEMANAS (MESMO DIA)</div><div class="grade dias">')
    for k, x in base:
        if k != "mês":
            P.append(_dia_card(x, f"{DIAS[x.dia.weekday()]} {x.dia:%d/%m}"))
    P.append("</div>")
    mes = [x for k, x in base if k == "mês"]
    if mes:
        P.append('<div class="sec">MESMO DIA DO MÊS PASSADO</div><div class="grade dias">')
        P.append(_dia_card(mes[0], f"{DIAS[mes[0].dia.weekday()]} {mes[0].dia:%d/%m}"))
        P.append("</div>")

    # Coluna 3: motoboys x atraso + como ler
    P.append('</div><div><div class="sec">MOTOBOYS × ATRASO NO PICO</div><div class="comp">')
    P.append('<div class="l h"><span>DIA</span><span>NA RUA</span><span>ENTREG./MOTO/H</span>'
             '<span class="x">&gt;45 MIN</span></div>')
    for k, x in sorted(base, key=lambda kx: kx[1].dia, reverse=True):
        cor = "dn" if x.estourou else "up"
        P.append(f'<div class="l"><span>{DC[x.dia.weekday()]} {x.dia:%d/%m}</span><span>{x.motos_pico}</span>'
                 f'<span>{_f1(x.eph)}</span><span class="x {cor}">{x.pct_atraso * 100:.0f}%</span></div>')
    P.append("</div>")
    P.append('<div class="sec">COMO LER</div><div class="como">'
             '<b>Na rua</b> = motoboys que levaram pedido na hora de pico. '
             '<b>Entreg./moto/h</b> = entregas do pico ÷ motoboys na rua. '
             '<b>Estourou</b> = mais de 10% das entregas acima de 45 min (ou vida média acima de 45). '
             '<b>Rua</b> = saída até a entrega; <b>vida</b> = do pedido até a entrega. '
             'Rua baixa com vida alta indica atraso na cozinha/expedição, não falta de motoboy. '
             '<b>Quando chamar</b> = entregas previstas ÷ ritmo seguro, hora a hora.</div>')
    P.append('</div></div>')
    P.append('<div class="rodape">Dados do ALIV (só leitura) · média ponderada das 4 últimas semanas + mês passado</div>'
             '<div class="faixa" style="margin-top:22px"></div>')
    return (f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><style>{CSS}{CSS_EXTRA}</style>'
            f'</head><body>{"".join(P)}</body></html>')


def gerar_painel(destino: Path, hoje: date, base: list, rec: dict, motivos: list[str], semana: list) -> Path:
    return html_para_png(html_painel(hoje, base, rec, motivos, semana), destino)
