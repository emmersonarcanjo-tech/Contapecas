"""Painel em PNG do fechamento semanal (fechamento_semanal.py) — mesmo estilo do painel.py.

Cores da Tili (vermelho #C8102E, dourado #D4A017, fundo #1A1A1A), logo no topo e o mesmo
Chromium headless do painel do monitor. Só o formato iPad (pedido do Emerson, 09/11/2026):
2360×1640, a resolução nativa do iPad deitado, uma tela só, 4 colunas. Desenhado em
1180×820 px CSS e fotografado em escala 2 (nítido). Tamanhos em rem.
"""

from __future__ import annotations

import html
import subprocess
import tempfile
from pathlib import Path

from diaristas import _logo_src
from monitor import META_CANCEL, META_CUSTO_IFOOD, META_ENTREGA, META_PREPARO, META_TICKET, brl, pct
from painel import DOURADO, FUNDO, VERMELHO, _chrome
from previsao_motoboys import DIAS_CURTO

IPAD = {"largura": 1180, "altura": 820, "escala": 2.0, "raiz": 12.6}       # 2360×1640
VERDE, VERMELHO_CLARO = "#4cd17d", "#ff5a6e"

CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0 }}
html, body {{ background: {FUNDO} }}
body {{ font-family: "Inter", "Liberation Sans", "DejaVu Sans", Arial, sans-serif; color: #fff;
       font-size: 1rem; line-height: 1.2 }}
.faixa {{ height: .5rem; background: linear-gradient(90deg, {VERMELHO} 0 62%, {DOURADO} 62% 100%) }}
.topo {{ display: flex; align-items: center; gap: 1rem; padding: .8rem 1.2rem .6rem }}
.logo {{ width: 3.6rem; height: 3.6rem; border-radius: .7rem; background: #fff; padding: .25rem;
         display: flex; align-items: center; justify-content: center; flex: none }}
.logo img {{ max-width: 100%; max-height: 100%; object-fit: contain }}
.titulo {{ font-size: 1.9rem; font-weight: 800; letter-spacing: -.02em }}
.titulo span {{ color: {DOURADO} }}
.sub {{ font-size: 1rem; color: #bbb; margin-top: .15rem }}
.selo {{ margin-left: auto; text-align: right; font-size: .9rem; color: #bbb }}
.selo b {{ display: block; font-size: 1.15rem; color: {DOURADO} }}
.sec {{ margin: .8rem 0 .45rem; font-size: .95rem; font-weight: 800; letter-spacing: .12em;
        color: {DOURADO}; display: flex; align-items: center; gap: .5rem }}
.sec::after {{ content: ""; flex: 1; height: 2px; background: #333 }}
.dest {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .6rem; margin: 0 1.2rem }}
.dest > div {{ border-radius: .7rem; padding: .55rem .8rem; font-size: 1rem; font-weight: 600; line-height: 1.25 }}
.dest .t {{ font-size: .8rem; font-weight: 800; letter-spacing: .12em; margin-bottom: .2rem }}
.d-bom {{ background: #16331f; border-left: .35rem solid #2e9d57 }} .d-bom .t {{ color: {VERDE} }}
.d-mau {{ background: #3a1018; border-left: .35rem solid {VERMELHO} }} .d-mau .t {{ color: {VERMELHO_CLARO} }}
.d-rec {{ background: #332a0c; border-left: .35rem solid {DOURADO} }} .d-rec .t {{ color: {DOURADO} }}
.kpis {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .6rem; margin: .6rem 1.2rem 0 }}
.card {{ background: #262626; border-radius: .7rem; padding: .5rem .75rem; border-top: .22rem solid #3a3a3a }}
.card.v {{ border-top-color: {VERMELHO} }} .card.d {{ border-top-color: {DOURADO} }}
.rot {{ font-size: .85rem; color: #bbb; font-weight: 600 }}
.val {{ font-size: 1.75rem; font-weight: 800; margin-top: .1rem; white-space: nowrap }}
.cmp {{ font-size: .8rem; color: #aaa; margin-top: .2rem; white-space: nowrap }}
.cmp b {{ font-weight: 800 }}
.up {{ color: {VERDE} }} .dn {{ color: {VERMELHO_CLARO} }} .neu {{ color: #aaa }}
.est {{ font-size: .7rem; color: {DOURADO}; font-weight: 800; letter-spacing: .08em }}
.cols {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0 .9rem; margin: 0 1.2rem;
         align-items: start }}
.loja {{ background: #262626; border-radius: .7rem; padding: .55rem .75rem; border-top: .22rem solid {VERMELHO} }}
.loja.s {{ border-top-color: {DOURADO} }}
.loja .n {{ display: flex; justify-content: space-between; align-items: baseline }}
.loja .n b {{ font-size: 1.2rem }} .loja .n span {{ font-size: 1.45rem; font-weight: 800 }}
.tab {{ width: 100%; border-collapse: collapse; margin-top: .25rem; font-size: .88rem }}
.tab td {{ padding: .17rem 0; border-bottom: 1px solid #333; white-space: nowrap }}
.tab tr:last-child td {{ border-bottom: none }}
.tab td:nth-child(2) {{ text-align: right; font-weight: 800 }}
.tab td:nth-child(3) {{ text-align: right; width: 4.6rem; font-size: .8rem; font-weight: 700 }}
.tab .h td {{ color: #999; font-size: .72rem; font-weight: 700; letter-spacing: .06em }}
.ruim {{ color: {VERMELHO_CLARO} }}
.barras {{ background: #262626; border-radius: .7rem; padding: .45rem .75rem; margin-top: .5rem }}
.barras .t {{ font-size: .9rem; font-weight: 800; margin-bottom: .15rem }}
.linha {{ display: grid; grid-template-columns: 7.4rem 1fr 5.6rem; align-items: center; gap: .45rem; padding: .16rem 0 }}
.linha .nm {{ font-size: .85rem; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }}
.linha .q {{ font-size: .75rem; color: #aaa; font-weight: 400 }}
.trilho {{ height: .75rem; background: #333; border-radius: .4rem; overflow: hidden }}
.trilho i {{ display: block; height: 100%; border-radius: .4rem }}
.linha .r {{ font-size: .85rem; font-weight: 800; text-align: right; white-space: nowrap }}
.mini {{ display: grid; grid-template-columns: 1fr 1fr; gap: .45rem }}
.mini .val {{ font-size: 1.3rem }}
.ranking {{ background: #262626; border-radius: .7rem; padding: .4rem .75rem; margin-top: .5rem }}
.ranking .l {{ display: grid; grid-template-columns: 1.1rem 1fr 3rem 3.2rem; gap: .3rem; font-size: .82rem;
               padding: .14rem 0; border-bottom: 1px solid #333 }}
.ranking .l:last-child {{ border-bottom: none }}
.ranking .l span:nth-child(3), .ranking .l span:nth-child(4) {{ text-align: right }}
.ranking .h {{ color: #999; font-size: .7rem; font-weight: 700 }}
.tempos {{ background: #262626; border-radius: .7rem; padding: .35rem .75rem }}
.tempos .l {{ display: grid; grid-template-columns: 1fr 3.3rem 3rem 3.2rem 5.6rem; gap: .3rem; font-size: .88rem;
              padding: .2rem 0; border-bottom: 1px solid #333; align-items: baseline }}
.tempos .l:last-child {{ border-bottom: none }}
.tempos .l span + span {{ text-align: right; font-weight: 800; white-space: nowrap }}
.tempos .h span {{ color: #999 !important; font-size: .7rem; font-weight: 700 !important }}
.dias {{ background: #262626; border-radius: .7rem; padding: .5rem .6rem .4rem }}
.graf {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: .3rem; align-items: end; height: 8.2rem }}
.graf .c {{ display: flex; flex-direction: column; justify-content: flex-end; align-items: center; height: 100% }}
.graf .vv {{ font-size: .68rem; font-weight: 800; white-space: nowrap; margin-bottom: .15rem }}
.graf .bar {{ width: 78%; display: flex; flex-direction: column; border-radius: .3rem .3rem 0 0; overflow: hidden }}
.graf .bar i {{ display: block; width: 100% }}
.graf .c.melhor .vv {{ color: {DOURADO} }} .graf .c.pior .vv {{ color: {VERMELHO_CLARO} }}
.rotd {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: .3rem; margin-top: .2rem }}
.rotd span {{ text-align: center; font-size: .72rem; color: #bbb; font-weight: 700 }}
.rotd span.melhor {{ color: {DOURADO} }} .rotd span.pior {{ color: {VERMELHO_CLARO} }}
.leg {{ font-size: .72rem; color: #aaa; margin-top: .3rem; display: flex; gap: .7rem; flex-wrap: wrap }}
.leg i {{ display: inline-block; width: .6rem; height: .6rem; border-radius: .15rem; margin-right: .2rem; vertical-align: -.05rem }}
.mes {{ background: linear-gradient(135deg, #3a0a14, #262626 70%); border-radius: .7rem; border-left: .35rem solid {DOURADO};
        padding: .5rem .75rem }}
.mes .val {{ color: {DOURADO} }}
.mes .contas {{ display: grid; grid-template-columns: 1fr; gap: .15rem .8rem; margin-top: .3rem; font-size: .82rem; color: #ccc }}
.mes .contas b {{ color: #fff; float: right }}
.rodape {{ margin: .7rem 1.2rem 0; font-size: .75rem; color: #888; text-align: center }}
.fim .faixa {{ margin-top: .5rem }}
/* iPad: altura fixa, rodapé colado embaixo */
body.ipad {{ height: {IPAD['altura']}px; display: flex; flex-direction: column; overflow: hidden }}
body.ipad .fim {{ margin-top: auto }}
"""


def _e(s) -> str:
    return html.escape(str(s))


def _cls(a: float, b: float, maior_melhor: bool = True) -> str:
    if not b or a == b:
        return "neu"
    return "up" if (a > b) == maior_melhor else "dn"


def _var(a: float, b: float, maior_melhor: bool = True, eh_pct: bool = False) -> str:
    """Seta + variação; cor verde quando é bom, vermelha quando é ruim."""
    if eh_pct:
        d = a - b
        txt = "=" if abs(d) < .0005 else f"{'▲' if d > 0 else '▼'} {abs(d) * 100:.1f} p.p.".replace(".", ",", 1)
        cls = "neu" if abs(d) < .0005 else ("up" if (d > 0) == maior_melhor else "dn")
        return f'<b class="{cls}">{_e(txt)}</b>'
    if not b:
        return '<b class="neu">—</b>'
    v = (a - b) / b
    if abs(v) < .0005:
        return '<b class="neu">=</b>'
    return f'<b class="{_cls(a, b, maior_melhor)}">{"▲" if v >= 0 else "▼"} {_e(pct(abs(v)))}</b>'


def _kpi(rot: str, val: str, a: float, b: float, c: float, mm: bool = True, ep: bool = False,
         cls: str = "", est: bool = False) -> str:
    return (f'<div class="card {cls}"><div class="rot">{_e(rot)}'
            + (' <span class="est">ESTIMATIVA</span>' if est else "") + f'</div><div class="val">{_e(val)}</div>'
            f'<div class="cmp">sem. ant. {_var(a, b, mm, ep)} · mês pass. {_var(a, c, mm, ep)}</div></div>')


def _loja(rot: str, x: dict, ant: dict | None, sushi: bool) -> str:
    def lin(nome, val, a=None, b=None, mm=True, ep=False, ruim=False):
        cmp = _var(a, b, mm, ep) if ant is not None and a is not None else ""
        return f'<tr><td>{_e(nome)}</td><td class="{"ruim" if ruim else ""}">{_e(val)}</td><td>{cmp}</td></tr>'
    a = ant or {}
    g = lambda k, d=0: a.get(k, d)
    L = [f'<div class="loja {"s" if sushi else ""}"><div class="n"><b>{_e(rot)}</b><span>{_e(brl(x["vendas"]))}</span></div>',
         '<table class="tab"><tr class="h"><td></td><td>SEMANA</td><td>VS ANT.</td></tr>',
         lin("Vendas", brl(x["vendas"]), x["vendas"], g("vendas")),
         lin("Pedidos", x["pedidos"], x["pedidos"], g("pedidos")),
         lin("Ticket médio", brl(x["ticket"]), x["ticket"], g("ticket"),
             ruim=not sushi and x["pedidos"] and x["ticket"] < META_TICKET),
         lin("Cancelados", f"{x['cancelados']} · {pct(x['taxa_cancel'])}", x["taxa_cancel"], g("taxa_cancel"),
             False, True, x["taxa_cancel"] > META_CANCEL)]
    if sushi:
        L.append(lin("Peças", f"{x['pecas']}", x["pecas"], g("pecas")))
    L += [lin("Desconto loja", brl(x["desc_loja"]), x["desc_loja"], g("desc_loja"), False),
          lin("Desconto iFood", brl(x["desc_plataforma"])),
          lin("Custo iFood", pct(x["custo_ifood"]), x["custo_ifood"], g("custo_ifood"), False, True,
              x["custo_ifood"] > META_CUSTO_IFOOD),
          lin("Lucro estimado", brl(x["l"]["lucro"]), x["l"]["lucro"], (a.get("l") or {}).get("lucro", 0)),
          "</table></div>"]
    return "".join(L)


def _barras(titulo: str, itens: list, cor: str) -> str:
    maior = max([v for _, _, v, _ in itens] + [1.0])
    linhas = "".join(
        f'<div class="linha"><div class="nm">{_e(n)} <span class="q">{q}{f" · {_e(x)}" if x else ""}</span></div>'
        f'<div class="trilho"><i style="width:{max(v / maior * 100, 1.5):.1f}%;background:{cor}"></i></div>'
        f'<div class="r">{_e(brl(v))}</div></div>'
        for n, q, v, x in itens)
    return f'<div class="barras"><div class="t">{_e(titulo)}</div>{linhas}</div>'


def _canais(x: dict, rot: str, sushi: bool) -> str:
    cor = DOURADO if sushi else VERMELHO
    itens = [(n, v[0], v[1], f"{v[2]} pç" if sushi and len(v) > 2 and v[2] else "")
             for n, v in sorted(x["canais"].items(), key=lambda i: -i[1][1])]
    out = _barras(f"Canais · {rot}", itens, cor)
    if x["ifood_lojas"]:
        it = [(n, v[0], v[1], "") for n, v in sorted(x["ifood_lojas"].items(), key=lambda i: -i[1][1])]
        out += _barras(f"iFood por loja · {rot}", it, "#8f0b21" if not sushi else "#9c7610")
    return out


def _motoboys(t: dict, turnos_moto: dict, n_lista: int) -> str:
    mini = (f'<div class="mini">'
            f'<div class="card d"><div class="rot">Turnos</div><div class="val">{t["turnos"]}</div></div>'
            f'<div class="card d"><div class="rot">Entregas</div><div class="val">{t["entregas"]}</div></div>'
            f'<div class="card d"><div class="rot">Custo <span class="est">EST.</span></div><div class="val">{_e(brl(t["custo_moto"]))}</div></div>'
            f'<div class="card d"><div class="rot">Por entrega</div><div class="val">{_e(brl(t["custo_entrega"]))}</div></div></div>')
    ls = sorted(t["motoboys"].items(), key=lambda i: -i[1])
    linhas = "".join(f'<div class="l"><span>{i}</span><span>{_e(n)}</span><span>{turnos_moto.get(n, 0)}</span><span><b>{e}</b></span></div>'
                     for i, (n, e) in enumerate(ls[:n_lista], 1))
    resto = len(ls) - n_lista
    if resto > 0:
        linhas += (f'<div class="l"><span></span><span class="h">+{resto} motoboys</span><span></span>'
                   f'<span>{sum(e for _, e in ls[n_lista:])}</span></div>')
    return (mini + '<div class="ranking"><div class="l h"><span>#</span><span>ENTREGAS POR MOTOBOY</span>'
            f'<span>TURNOS</span><span>ENTR.</span></div>{linhas}</div>')


def _tempos(c: dict) -> str:
    def lin(rot, x):
        p, r, v = (x["tempo"].get(k, (0, 0)) for k in ("prod", "rua", "vida"))
        f = lambda t: f"{t[0]:.0f} min" if t[1] else "—"
        return (f'<div class="l"><span>{_e(rot)}</span><span class="{"ruim" if p[1] and p[0] > META_PREPARO else ""}">{f(p)}</span>'
                f'<span>{f(r)}</span><span class="{"ruim" if v[1] and v[0] > META_ENTREGA else ""}">{f(v)}</span>'
                f'<span class="{"ruim" if x["pct_atraso"] > .10 else ""}">{x["atrasos"]} · {_e(pct(x["pct_atraso"]))}</span></div>')
    L = ['<div class="tempos"><div class="l h"><span>MÉDIA</span><span>PREPARO</span><span>RUA</span><span>VIDA</span><span>&gt; 45 MIN</span></div>',
         lin("Pizzaria", c["piz"])]
    if c["sushi"]:
        L.append(lin("Sushi", c["sushi"]))
    L.append(lin("Total", c["tot"]) + "</div>")
    return "".join(L)


def _dias(c: dict, melhor: dict, pior: dict) -> str:
    maior = max([d["vendas"] for d in c["por_dia"]] + [1.0])
    cols, rots = [], []
    for d in c["por_dia"]:
        cls = "melhor" if d is melhor else "pior" if d is pior else ""
        h = d["vendas"] / maior * 100
        hp = d["piz"] / d["vendas"] * 100 if d["vendas"] else 0
        cols.append(f'<div class="c {cls}"><div class="vv">{_e(brl(d["vendas"]).replace("R$ ", "").split(",")[0])}</div>'
                    f'<div class="bar" style="height:{max(h * .82, 2):.1f}%"><i style="height:{100 - hp:.1f}%;background:{DOURADO}"></i>'
                    f'<i style="height:{hp:.1f}%;background:{VERMELHO}"></i></div></div>')
        rots.append(f'<span class="{cls}">{DIAS_CURTO[d["dia"].weekday()]} {d["dia"]:%d}</span>')
    return (f'<div class="dias"><div class="graf">{"".join(cols)}</div><div class="rotd">{"".join(rots)}</div>'
            f'<div class="leg"><span><i style="background:{VERMELHO}"></i>Pizzaria</span>'
            f'<span><i style="background:{DOURADO}"></i>Sushi</span>'
            f'<span>melhor: <b style="color:{DOURADO}">{DIAS_CURTO[melhor["dia"].weekday()]} {_e(brl(melhor["vendas"]))}</b></span>'
            f'<span>pior: <b style="color:{VERMELHO_CLARO}">{DIAS_CURTO[pior["dia"].weekday()]} {_e(brl(pior["vendas"]))}</b></span></div></div>')


def _mes(R: dict) -> str:
    mt, pj = R["mtd"]["tot"], R["proj"]
    return (f'<div class="mes"><div class="rot">{_e(R["mes_nome"])} até {R["dom"]:%d/%m} · {R["dias_mtd"]} de {R["dias_mes"]} dias</div>'
            f'<div class="val">{_e(brl(mt["vendas"]))}</div>'
            f'<div class="contas"><div>Projeção do mês <b>{_e(brl(pj["vendas"]))}</b></div>'
            f'<div>Pedidos <b>{mt["pedidos"]}</b></div>'
            f'<div>Lucro est. <b>{_e(brl(mt["l"]["lucro"]))}</b></div>'
            f'<div>Lucro proj. <b>{_e(brl(pj["lucro"]))}</b></div></div></div>')


def html_painel(R: dict) -> str:
    c, a, m = R["cur"], R["ant"], R["mes"]
    t, ta, tm = c["tot"], a["tot"], m["tot"]
    topo = (f'<div class="faixa"></div><div class="topo"><div class="logo"><img src="{_logo_src()}"></div>'
            f'<div><div class="titulo">Fechamento semanal <span>Tili</span></div>'
            f'<div class="sub">{DIAS_CURTO[R["seg"].weekday()]} {R["seg"]:%d/%m} a {DIAS_CURTO[R["dom"].weekday()]} '
            f'{R["dom"]:%d/%m/%Y} · dia operacional 16h–04h</div></div>'
            f'<div class="selo">comparado com<b>sem. {R["ant_seg"]:%d/%m} e {R["mes_seg"]:%d/%m}</b></div></div>')
    d = R["dest"]
    dest = (f'<div class="dest"><div class="d-bom"><div class="t">▲ MELHOROU</div>{_e(d[0])}</div>'
            f'<div class="d-mau"><div class="t">▼ PIOROU</div>{_e(d[1])}</div>'
            f'<div class="d-rec"><div class="t">★ RECOMENDAÇÃO</div>{_e(d[2])}</div></div>')
    kpis = ('<div class="kpis">'
            + _kpi("Vendas · consolidado", brl(t["vendas"]), t["vendas"], ta["vendas"], tm["vendas"], cls="v")
            + _kpi("Pedidos", f'{t["pedidos"]}', t["pedidos"], ta["pedidos"], tm["pedidos"], cls="v")
            + _kpi("Ticket médio", brl(t["ticket"]), t["ticket"], ta["ticket"], tm["ticket"], cls="d")
            + _kpi("Cancelamento", f'{t["cancelados"]} · {pct(t["taxa_cancel"])}', t["taxa_cancel"],
                   ta["taxa_cancel"], tm["taxa_cancel"], False, True, cls="d")
            + _kpi("Lucro", brl(t["l"]["lucro"]), t["l"]["lucro"], ta["l"]["lucro"], tm["l"]["lucro"],
                   cls="d", est=True) + "</div>")
    lojas = [_loja("Pizzaria", c["piz"], a["piz"], False)]
    canais = [_canais(c["piz"], "Pizzaria", False)]
    if c["sushi"]:
        lojas.append(_loja("Sushi", c["sushi"], a["sushi"], True))
        canais.append(_canais(c["sushi"], "Sushi", True))
    moto = _motoboys(t, c["turnos_moto"], 11)
    fim = ('<div class="fim"><div class="rodape">Dados do ALIV (só leitura) · lucro é ESTIMATIVA '
           '(CMV 26,5% · imposto 9,45% · iFood 12,8% · cartão 1,6% · motoboys)</div><div class="faixa"></div></div>')
    corpo = (topo + dest + kpis + '<div class="cols">'
             f'<div><div class="sec">PIZZARIA</div>{lojas[0]}{canais[0]}</div>'
             f'<div><div class="sec">SUSHI</div>{lojas[1] if len(lojas) > 1 else "<div class=loja>indisponível</div>"}'
             f'{canais[1] if len(canais) > 1 else ""}</div>'
             f'<div><div class="sec">MOTOBOYS</div>{moto}</div>'
             f'<div><div class="sec">TEMPOS</div>{_tempos(c)}<div class="sec">DIA A DIA</div>{_dias(c, R["melhor"], R["pior"])}'
             f'<div class="sec">MÊS</div>{_mes(R)}</div></div>' + fim)
    return _pagina(corpo)


def _pagina(corpo: str) -> str:
    css = CSS + f"html {{ font-size: {IPAD['raiz']}px }} html, body {{ width: {IPAD['largura']}px }}"
    return (f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body class="ipad">{corpo}</body></html>')


def foto_fixa(pagina: str, destino: Path, largura: int, altura: int, escala: float) -> Path:
    destino.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "painel.html"
        arq.write_text(pagina, encoding="utf-8")
        subprocess.run([_chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        f"--force-device-scale-factor={escala:.4f}", f"--user-data-dir={tmp}/perfil",
                        f"--window-size={largura},{altura}", f"--screenshot={destino}", arq.as_uri()],
                       capture_output=True, timeout=90)
    if not destino.exists() or destino.stat().st_size < 1000:
        raise RuntimeError("Chromium não gerou o PNG do painel")
    return destino


def gerar_paineis(R: dict, base: Path) -> list[tuple[str, Path | Exception]]:
    """[("iPad", arquivo ou exceção)] — base_ipad.png, 2360×1640."""
    base.parent.mkdir(parents=True, exist_ok=True)
    try:
        return [("iPad", foto_fixa(html_painel(R), base.with_name(base.name + "_ipad.png"),
                                   IPAD["largura"], IPAD["altura"], IPAD["escala"]))]
    except Exception as e:
        return [("iPad", e)]
