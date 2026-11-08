"""Painel em PNG (estilo BI) com os números do monitor.py — para mandar no WhatsApp.

Monta um HTML com as cores da Tili (vermelho #C8102E, dourado #D4A017, fundo
#1A1A1A, texto branco) e fotografa com o Chromium headless, o mesmo que já gera
os PDFs dos diaristas e prestadores. Não precisa instalar nada além disso.

Uso pelo monitor.py: gerar_painel(destino, agora, dia, r, ops, ops_h, moto, uh, l, sem, sushi).
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path

from diaristas import CHROME, _logo_src
from monitor import (META_CANCEL, META_CUSTO_IFOOD, META_ENTREGA, META_PREPARO, META_TICKET,
                     alertas_operacao, brl, num, pct, resumo)

LARGURA = 2000   # px — 2 colunas, formato do iPad em pé (~3:4) para a imagem ocupar a tela toda

VERMELHO, DOURADO, FUNDO = "#C8102E", "#D4A017", "#1A1A1A"

CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0 }}
html, body {{ background: {FUNDO}; width: {LARGURA}px }}
body {{ font-family: "Inter", "Liberation Sans", "DejaVu Sans", Arial, sans-serif; color: #fff;
       font-size: 30px; line-height: 1.2; padding: 0 0 28px }}
.faixa {{ height: 14px; background: linear-gradient(90deg, {VERMELHO} 0 62%, {DOURADO} 62% 100%) }}
.topo {{ display: flex; align-items: center; gap: 28px; padding: 30px 40px 22px }}
.logo {{ width: 128px; height: 128px; border-radius: 22px; background: #fff; padding: 8px;
         display: flex; align-items: center; justify-content: center; flex: none }}
.logo img {{ max-width: 100%; max-height: 100%; object-fit: contain }}
.titulo {{ font-size: 56px; font-weight: 800; letter-spacing: -.5px }}
.titulo span {{ color: {DOURADO} }}
.sub {{ font-size: 30px; color: #bbb; margin-top: 4px }}
.sec {{ margin: 26px 40px 14px; font-size: 30px; font-weight: 800; letter-spacing: 2px;
        color: {DOURADO}; display: flex; align-items: center; gap: 14px }}
.sec::after {{ content: ""; flex: 1; height: 3px; background: #333 }}
.grade {{ display: grid; gap: 18px; margin: 0 40px }}
.g2 {{ grid-template-columns: 1fr 1fr }}
.g3 {{ grid-template-columns: 1fr 1fr 1fr }}
.card {{ background: #262626; border-radius: 20px; padding: 22px 24px; border-top: 6px solid #3a3a3a }}
.card.v {{ border-top-color: {VERMELHO} }}
.card.d {{ border-top-color: {DOURADO} }}
.card.ruim {{ border-top-color: {VERMELHO}; background: #3a1018 }}
.card.bom {{ border-top-color: #2e9d57 }}
.rot {{ font-size: 28px; color: #bbb; font-weight: 600 }}
.val {{ font-size: 52px; font-weight: 800; margin-top: 6px; white-space: nowrap }}
.val.g {{ font-size: 66px }}
.det {{ font-size: 28px; color: #ccc; margin-top: 6px }}
.meta {{ font-size: 26px; color: #999; margin-top: 4px }}
.loja {{ font-size: 34px; font-weight: 800; margin-bottom: 4px }}
.uh {{ margin-top: 14px; padding-top: 12px; border-top: 2px solid #3a3a3a; font-size: 30px }}
.uh b {{ color: {DOURADO} }}
.alertas {{ margin: 0 40px; border-radius: 20px; overflow: hidden; border: 4px solid {VERMELHO} }}
.alertas .cab {{ background: {VERMELHO}; font-size: 36px; font-weight: 800; padding: 14px 24px }}
.alertas ul {{ list-style: none; background: #3a1018; padding: 10px 24px 14px }}
.alertas li {{ font-size: 32px; font-weight: 600; padding: 8px 0 8px 36px; position: relative }}
.alertas li::before {{ content: ""; position: absolute; left: 0; top: 19px; width: 18px; height: 18px;
                       border-radius: 50%; background: {DOURADO} }}
.semalerta {{ margin: 0 40px; border-radius: 20px; background: #16331f; border: 4px solid #2e9d57;
              font-size: 34px; font-weight: 800; padding: 18px 24px }}
.barras {{ background: #262626; border-radius: 20px; padding: 18px 24px }}
.barras .t {{ font-size: 32px; font-weight: 800; margin-bottom: 6px }}
.linha {{ display: grid; grid-template-columns: 230px 1fr 250px; align-items: center; gap: 16px;
          padding: 9px 0 }}
.linha .n {{ font-size: 30px; font-weight: 700 }}
.linha .q {{ font-size: 26px; color: #aaa; font-weight: 400 }}
.trilho {{ height: 30px; background: #333; border-radius: 15px; overflow: hidden }}
.trilho i {{ display: block; height: 100%; border-radius: 15px }}
.linha .r {{ font-size: 30px; font-weight: 800; text-align: right; white-space: nowrap }}
.lucro {{ margin: 0 40px; background: linear-gradient(135deg, #3a0a14, #262626 70%); border-radius: 20px;
          border-left: 10px solid {DOURADO}; padding: 24px 28px }}
.lucro .val {{ font-size: 80px; color: {DOURADO} }}
.lucro .contas {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 30px; margin-top: 14px;
                  font-size: 28px; color: #ccc }}
.lucro .contas b {{ color: #fff; float: right }}
.comp {{ margin: 0 40px; background: #262626; border-radius: 20px; padding: 10px 24px }}
.comp .l {{ display: grid; grid-template-columns: 1.25fr 1.15fr 1.15fr .9fr; gap: 10px; padding: 12px 0;
            border-bottom: 2px solid #333; font-size: 30px; align-items: baseline }}
.comp .l:last-child {{ border-bottom: none }}
.comp .h {{ font-size: 24px; color: #999; font-weight: 700; letter-spacing: 1px }}
.comp .x {{ text-align: right; font-weight: 800; white-space: nowrap }}
.up {{ color: #4cd17d }} .dn {{ color: #ff5a6e }}
.colunas {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0 4px; align-items: start;
             padding: 0 20px }}
.colunas .sec, .colunas .grade, .colunas .lucro, .colunas .comp {{ margin-left: 20px; margin-right: 20px }}
.colunas .g3 .val {{ font-size: 44px }}
.colunas > div > .sec:first-child {{ margin-top: 26px }}
.rodape {{ margin: 28px 40px 0; font-size: 24px; color: #888; text-align: center }}
"""


def _e(s) -> str:
    return html.escape(str(s))


def _card(rot: str, val: str, det: str = "", meta: str = "", cls: str = "", grande: bool = False) -> str:
    return (f'<div class="card {cls}"><div class="rot">{_e(rot)}</div>'
            f'<div class="val{" g" if grande else ""}">{_e(val)}</div>'
            + (f'<div class="det">{_e(det)}</div>' if det else "")
            + (f'<div class="meta">{_e(meta)}</div>' if meta else "") + "</div>")


def _situacao(bom: bool | None) -> str:
    return "" if bom is None else ("bom" if bom else "ruim")


def _barras(titulo: str, itens: list[tuple[str, int, float, str]], cor: str) -> str:
    """itens: (nome, pedidos, valor, extra)."""
    maior = max([v for _, _, v, _ in itens] + [1.0])
    linhas = "".join(
        f'<div class="linha"><div class="n">{_e(n)} <span class="q">{q}</span></div>'
        f'<div class="trilho"><i style="width:{max(v / maior * 100, 1.5):.1f}%;background:{cor}"></i></div>'
        f'<div class="r">{_e(brl(v))}{f"<div class=q>{_e(x)}</div>" if x else ""}</div></div>'
        for n, q, v, x in itens)
    return f'<div class="barras"><div class="t">{_e(titulo)}</div>{linhas}</div>'


def _var(a: float, b: float) -> str:
    if not b:
        return '<span class="x">—</span>'
    v = (a - b) / b
    return f'<span class="x {"up" if v >= 0 else "dn"}">{"▲" if v >= 0 else "▼"} {_e(pct(abs(v)))}</span>'


def _tempo(t: dict) -> str:
    return f"{num(t.get('avg_min')):.0f} min" if t and t.get("n") else "—"


def _tempo_det(t: dict, hora: dict) -> str:
    if not t or not t.get("n"):
        return "sem dados"
    h = f"{num(hora.get('avg_min')):.0f}" if hora and hora.get("n") else "—"
    return f"máx {num(t.get('max_min')):.0f} · 1h: {h}"


def lista_alertas(r: dict, ops: dict, sushi: dict | None) -> list[str]:
    """Alertas da operação + metas estouradas, na ordem de prioridade."""
    al = alertas_operacao(ops)
    out = []
    for chave, rot in (("parado", "parado >15 min"), ("em_rota", "em rota >45 min"),
                       ("sem_motoboy", "pronto sem motoboy")):
        if al[chave]:
            out.append(f"{len(al[chave])} {rot}: {', '.join(al[chave][:3])}")
    if r["pix_pendente"]:
        out.append(f"{len(r['pix_pendente'])} Pix pendente (Pizzaria)")
    if r["ia_aguardando"]:
        out.append(f"{len(r['ia_aguardando'])} pedido(s) da IA aguardando confirmação")
    s = sushi["r"] if sushi and not sushi.get("erro") else None
    if s and s["pix_pendente"]:
        out.append(f"{len(s['pix_pendente'])} Pix pendente (Sushi)")
    if s and s["ia_aguardando"]:
        out.append(f"{len(s['ia_aguardando'])} pedido(s) da IA aguardando no Sushi")
    prod, vida = resumo(ops, "prod_delivery"), resumo(ops, "life_delivery")
    if prod.get("n") and num(prod.get("avg_min")) > META_PREPARO:
        out.append(f"Preparo delivery {num(prod.get('avg_min')):.0f} min (meta {META_PREPARO:.0f})")
    if vida.get("n") and num(vida.get("avg_min")) > META_ENTREGA:
        out.append(f"Vida delivery {num(vida.get('avg_min')):.0f} min (meta {META_ENTREGA:.0f})")
    if r["taxa_cancel"] > META_CANCEL:
        out.append(f"Cancelamento Pizzaria {pct(r['taxa_cancel'])} — {r['cancelados']} pedidos (meta até 2%)")
    if s and s["taxa_cancel"] > META_CANCEL:
        out.append(f"Cancelamento Sushi {pct(s['taxa_cancel'])} — {s['cancelados']} pedidos (meta até 2%)")
    if r["custo_ifood"] > META_CUSTO_IFOOD:
        out.append(f"Custo iFood {pct(r['custo_ifood'])} (meta até 25%)")
    if r["pedidos"] and r["ticket"] < META_TICKET:
        out.append(f"Ticket Pizzaria {brl(r['ticket'])} (meta {brl(META_TICKET)})")
    if sushi and sushi.get("erro"):
        out.append("Sushi indisponível no ALIV")
    return out


def html_painel(agora: datetime, dia: date, r: dict, ops: dict, ops_h: dict, moto: dict, uh: tuple,
                l: dict, sem: dict | None, sushi: dict | None) -> str:
    s = sushi["r"] if sushi and not sushi.get("erro") else None
    P = []
    P.append(f'<div class="faixa"></div><div class="topo"><div class="logo"><img src="{_logo_src()}"></div>'
             f'<div><div class="titulo">Painel <span>Tili</span></div>'
             f'<div class="sub">Turno {dia:%d/%m} · atualizado {agora:%d/%m às %H:%M}</div></div></div>')

    # Alertas em destaque, logo no topo
    al = lista_alertas(r, ops, sushi)
    if al:
        P.append(f'<div class="alertas"><div class="cab">ALERTAS ({len(al)})</div><ul>'
                 + "".join(f"<li>{_e(a)}</li>" for a in al[:8]) + "</ul></div>")
    else:
        P.append('<div class="semalerta">Sem alertas — operação dentro das metas</div>')

    # Duas colunas: esquerda = vendas e canais; direita = o resto
    P.append('<div class="colunas"><div>')

    # Vendas por loja
    P.append('<div class="sec">VENDAS DO DIA</div><div class="grade g2">')
    P.append(f'<div class="card v"><div class="loja">Pizzaria</div><div class="val g">{_e(brl(r["vendas"]))}</div>'
             f'<div class="det">{r["pedidos"]} pedidos</div>'
             f'<div class="uh">Última hora: <b>{uh[0]}</b> · <b>{_e(brl(uh[1]))}</b></div></div>')
    if s:
        su = sushi["uh"]
        P.append(f'<div class="card d"><div class="loja">Sushi</div><div class="val g">{_e(brl(s["vendas"]))}</div>'
                 f'<div class="det">{s["pedidos"]} pedidos · {s["pecas"]} peças</div>'
                 f'<div class="uh">Última hora: <b>{su[0]}</b> · <b>{_e(brl(su[1]))}</b></div></div>')
    else:
        P.append(_card("Sushi", "—", "indisponível" if sushi else "não configurado", cls="d"))
    P.append("</div>")

    # Canais
    P.append('<div class="sec">CANAIS</div><div class="grade">')
    nomes = {"app": "App", "ifood": "iFood", "pdv": "PDV"}
    itens = [(nomes.get(c, c.upper()), n, v, "") for c, (n, v) in sorted(r["por_canal"].items(), key=lambda x: -x[1][1])]
    P.append(_barras("Pizzaria", itens, VERMELHO))
    if r["por_loja_ifood"]:
        itens = [(re.sub(r"^Tili\s*", "", k) or k, n, v, "")
                 for k, (n, v) in sorted(r["por_loja_ifood"].items(), key=lambda x: -x[1][1])]
        P.append(_barras("iFood por loja (Pizzaria)", itens, "#8f0b21"))
    if s:
        itens = [(k, n, v, f"{pc} peças") for k, (n, v, pc) in
                 sorted(s["por_canal_sushi"].items(), key=lambda x: -x[1][1])]
        P.append(_barras("Sushi", itens, DOURADO))
    P.append("</div>")

    # Ticket e cancelamento
    P.append('<div class="sec">TICKET E CANCELAMENTO</div><div class="grade g2">')
    P.append(_card("Ticket Pizzaria", brl(r["ticket"]), meta=f"meta {brl(META_TICKET)}",
                   cls=_situacao(r["ticket"] >= META_TICKET if r["pedidos"] else None)))
    P.append(_card("Ticket Sushi", brl(s["ticket"]) if s else "—", cls="d"))
    P.append(_card("Cancelados Pizzaria", f"{r['cancelados']} · {pct(r['taxa_cancel'])}", meta="meta até 2%",
                   cls=_situacao(r["taxa_cancel"] <= META_CANCEL)))
    P.append(_card("Cancelados Sushi", f"{s['cancelados']} · {pct(s['taxa_cancel'])}" if s else "—",
                   meta="meta até 2%", cls=_situacao(s["taxa_cancel"] <= META_CANCEL) if s else "d"))
    P.append("</div>")

    P.append('</div><div>')

    # Tempos (Pizzaria): média do turno; embaixo, máximo e média da última hora
    prod, rua, vida = resumo(ops, "prod_delivery"), resumo(ops, "street"), resumo(ops, "life_delivery")
    P.append('<div class="sec">TEMPOS PIZZARIA · MÉDIA (1h = ÚLTIMA HORA)</div><div class="grade g3">')
    P.append(_card("Preparo", _tempo(prod), _tempo_det(prod, resumo(ops_h, "prod_delivery")),
                   f"meta {META_PREPARO:.0f}",
                   _situacao(num(prod.get("avg_min")) <= META_PREPARO if prod.get("n") else None)))
    P.append(_card("Rua", _tempo(rua), _tempo_det(rua, resumo(ops_h, "street")), cls="d"))
    P.append(_card("Vida", _tempo(vida), _tempo_det(vida, resumo(ops_h, "life_delivery")),
                   f"meta {META_ENTREGA:.0f}",
                   _situacao(num(vida.get("avg_min")) <= META_ENTREGA if vida.get("n") else None)))
    P.append("</div>")

    # Motoboys e descontos
    P.append('<div class="sec">MOTOBOYS E DESCONTOS</div><div class="grade g3">')
    P.append(_card("Motoboys online", f"{moto['agora']}", f"máximo do dia: {moto['maximo']}", cls="d"))
    P.append(_card("Entregas Pizzaria", f"{r['entregas_delivery']}", f"{moto['entregas']} no ALIV (c/ Sushi)", cls="d"))
    P.append(_card("Custo motoboys", brl(l["motoboys"]), "estimado", cls="d"))
    P.append(_card("Desconto loja", brl(r["desc_loja"]),
                   f"manual {brl(r['desc_manual'])}" if r["desc_manual"] else "", cls="v"))
    P.append(_card("Desconto iFood", brl(r["desc_plataforma"]), "bancado pelo iFood", cls="d"))
    P.append(_card("Custo iFood", pct(r["custo_ifood"]), "comissão + desc. loja", "meta até 25%",
                   _situacao(r["custo_ifood"] <= META_CUSTO_IFOOD if r["receita_ifood"] else None)))
    P.append("</div>")

    # Lucro estimado
    P.append('<div class="sec">LUCRO ESTIMADO · PIZZARIA</div>')
    P.append(f'<div class="lucro"><div class="rot">Margem de contribuição (estimativa)</div>'
             f'<div class="val">{_e(brl(l["lucro"]))}</div>'
             f'<div class="det">{_e(pct(l["margem"]))} da receita de {_e(brl(l["receita"]))}</div>'
             f'<div class="contas"><div>CMV 26,5% <b>{_e(brl(l["cmv"]))}</b></div>'
             f'<div>Imposto 9,45% <b>{_e(brl(l["imposto"]))}</b></div>'
             f'<div>Comissão iFood <b>{_e(brl(l["comissao"]))}</b></div>'
             f'<div>Motoboys <b>{_e(brl(l["motoboys"]))}</b></div>'
             f'<div>Cartão 1,6% <b>{_e(brl(l["cartao"]))}</b></div></div></div>')

    # Semana passada
    P.append('<div class="sec">VS. SEMANA PASSADA (MESMA HORA)</div><div class="comp">')
    P.append('<div class="l h"><span></span><span>HOJE</span><span>SEM. PASS.</span><span class="x">VAR.</span></div>')
    if sem is not None:
        P.append(f'<div class="l"><span>Pizzaria pedidos</span><span>{r["pedidos"]}</span><span>{sem["pedidos"]}</span>'
                 f'{_var(r["pedidos"], sem["pedidos"])}</div>')
        P.append(f'<div class="l"><span>Pizzaria vendas</span><span>{_e(brl(r["vendas"]))}</span>'
                 f'<span>{_e(brl(sem["vendas"]))}</span>{_var(r["vendas"], sem["vendas"])}</div>')
        P.append(f'<div class="l"><span>Pizzaria ticket</span><span>{_e(brl(r["ticket"]))}</span>'
                 f'<span>{_e(brl(sem["ticket"]))}</span>{_var(r["ticket"], sem["ticket"])}</div>')
    else:
        P.append('<div class="l"><span>Pizzaria</span><span>indisponível</span><span></span><span></span></div>')
    w = sushi.get("sem") if s else None
    if w:
        P.append(f'<div class="l"><span>Sushi pedidos</span><span>{s["pedidos"]}</span><span>{w["pedidos"]}</span>'
                 f'{_var(s["pedidos"], w["pedidos"])}</div>')
        P.append(f'<div class="l"><span>Sushi vendas</span><span>{_e(brl(s["vendas"]))}</span>'
                 f'<span>{_e(brl(w["vendas"]))}</span>{_var(s["vendas"], w["vendas"])}</div>')
        P.append(f'<div class="l"><span>Sushi peças</span><span>{s["pecas"]}</span><span>{w["pecas"]}</span>'
                 f'{_var(s["pecas"], w["pecas"])}</div>')
    P.append("</div>")
    P.append('</div></div>')
    P.append('<div class="rodape">Dados do ALIV (só leitura) · lucro é estimativa</div>'
             '<div class="faixa" style="margin-top:22px"></div>')

    return (f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><style>{CSS}</style></head>'
            f'<body>{"".join(P)}</body></html>')


def _chrome() -> str:
    for c in CHROME:
        achado = shutil.which(c) if c else None
        if achado or (c and Path(c).exists()):
            return achado or c
    raise RuntimeError("Chromium não encontrado (defina DIARISTAS_CHROME)")


def html_para_png(pagina: str, destino: Path) -> Path:
    """Fotografa o HTML na largura LARGURA. 1ª passada mede a altura, 2ª tira a foto."""
    chrome = _chrome()
    destino.unlink(missing_ok=True)
    medir = '<script>document.title="ALTURA="+document.documentElement.scrollHeight</script>'
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "painel.html"
        base = [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                f"--user-data-dir={tmp}/perfil"]
        arq.write_text(pagina.replace("</body>", medir + "</body>"), encoding="utf-8")
        out = subprocess.run(base + [f"--window-size={LARGURA},1000", "--dump-dom", arq.as_uri()],
                             capture_output=True, text=True, timeout=90).stdout
        m = re.search(r"ALTURA=(\d+)", out)
        altura = min(int(m.group(1)), 8000) if m else 3600
        arq.write_text(pagina, encoding="utf-8")
        subprocess.run(base + [f"--window-size={LARGURA},{altura}", f"--screenshot={destino}", arq.as_uri()],
                       capture_output=True, timeout=90)
    if not destino.exists() or destino.stat().st_size < 1000:
        raise RuntimeError("Chromium não gerou o PNG do painel")
    return destino


def gerar_painel(destino: Path, *dados) -> Path:
    """dados = (agora, dia, r, ops, ops_h, moto, uh, l, sem, sushi), os mesmos do relatorio()."""
    return html_para_png(html_painel(*dados), destino)
