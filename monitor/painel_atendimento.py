"""Painel em PNG da auditoria do atendimento da IA (atendimento_ia.py) — para o WhatsApp.

Mesmo desenho e mesmos formatos do painel do monitor (painel.py), com outra paleta
(azul-noite, violeta e ciano) para não confundir com o Painel da operação:
  ipad   — 3 colunas, iPad deitado, 2880 px de largura
  iphone — tela do iPhone 14 Pro Max (1290×2796), em 2 imagens:
           1/2 números do turno e problemas; 2/2 últimos 7 dias, pares propostos e regras

Não mostra nome, telefone nem endereço de cliente: só números e os pares sugeridos.
Uso: gerar_paineis(base, dia, dados, hist) → {"ipad": Path, "iphone_1": Path, "iphone_2": Path}.
"""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import date
from pathlib import Path

import painel
from diaristas import _logo_src
from painel import FORMATOS, QUEBRA, ROTULOS, _card, _e, html_para_png  # noqa: F401  (ROTULOS é reexportado)

VIOLETA, CIANO, FUNDO, CARD, LINHA = "#7C3AED", "#22D3EE", "#0B1426", "#16223A", "#2A3A57"
VERDE, VERMELHO = "#34D399", "#F87171"

CSS = (painel.CSS.replace(painel.VERMELHO, VIOLETA).replace(painel.DOURADO, CIANO)
       .replace(painel.FUNDO, FUNDO).replace("#262626", CARD).replace("#3a3a3a", LINHA)
       .replace("#333", LINHA).replace("#3a1018", "#2B1846").replace("#3a0a14", "#24124A")
       + f"""
.faixa {{ background: linear-gradient(90deg, {VIOLETA} 0 55%, {CIANO} 55% 100%) }}
.titulo span {{ color: {CIANO} }}
.card.bom {{ border-top-color: {VERDE} }}
.card.ruim {{ border-top-color: {VERMELHO}; background: #3A1A2A }}
.par {{ background: {CARD}; border-radius: 20px; padding: 20px 24px; border-left: 10px solid {VIOLETA};
        margin-bottom: 18px }}
.par.existe {{ border-left-color: {LINHA}; opacity: .55 }}
.par .n {{ font-size: 26px; color: {CIANO}; font-weight: 800; letter-spacing: 1px }}
.par .p {{ font-size: 30px; font-weight: 700; margin-top: 8px }}
.par .r {{ font-size: 28px; color: #D6DEEE; margin-top: 8px; line-height: 1.3 }}
.par .a {{ font-size: 24px; color: #FBBF24; margin-top: 8px }}
.regras {{ margin: 0 40px; background: {CARD}; border-radius: 20px; padding: 14px 24px }}
.regras li {{ font-size: 28px; padding: 8px 0 8px 34px; position: relative; list-style: none; line-height: 1.3 }}
.regras li::before {{ content: ""; position: absolute; left: 0; top: 18px; width: 16px; height: 16px;
                      border-radius: 50%; background: {CIANO} }}
.pares {{ margin: 0 40px }}
.barras .linha {{ grid-template-columns: 330px 1fr 220px }}
.colunas .pares, .colunas .regras {{ margin-left: 20px; margin-right: 20px }}
""")
CSS_IPHONE = painel.CSS_IPHONE + """
.colunas .pares, .colunas .regras { margin-left: 40px; margin-right: 40px }
"""

NOMES_CURTOS = {
    "nao_entendeu": "Não entendeu", "item_preco": "Item/preço errado", "endereco_taxa": "Endereço/taxa",
    "demora": "Demora > 5 min", "repetiu": "Perguntou 2x", "reclamou_humano": "Pediu humano",
    "nao_soube": "Não soube responder", "cancelado": "Cancelado após montar",
}


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _min(v) -> str:
    return "—" if v is None else f"{v:.1f} min".replace(".", ",")


def _barras(itens: list[tuple[str, int]], total: int) -> str:
    maior = max([v for _, v in itens] + [1])
    linhas = "".join(
        f'<div class="linha"><div class="n">{_e(n)}</div>'
        f'<div class="trilho"><i style="width:{max(v / maior * 100, 1.5):.1f}%;background:{VIOLETA}"></i></div>'
        f'<div class="r">{v}<div class="q">{_pct(v / total) if total else "—"} das conversas</div></div></div>'
        for n, v in itens)
    return f'<div class="barras"><div class="t">5 problemas mais frequentes</div>{linhas}</div>'


def _comparacao(r: dict, hist: list[dict]) -> str:
    if not hist:
        return '<div class="comp"><div class="l"><span>Sem histórico ainda</span></div></div>'

    def media(k):
        v = [h[k] for h in hist if h.get(k) is not None]
        return statistics.mean(v) if v else None

    def seta(h, m, maior_melhor):
        if h is None or m is None or abs(h - m) < 1e-9:
            return '<span class="x">=</span>'
        bom = (h > m) == maior_melhor
        return f'<span class="x {"up" if bom else "dn"}">{"▲" if h > m else "▼"} {"melhor" if bom else "pior"}</span>'

    prob_h = sum(r["problemas"].values()) / max(r["conversas"], 1)
    prob_m = statistics.mean(sum(h["problemas"].values()) / max(h["conversas"], 1) for h in hist)
    linhas = [
        ("Conversas", str(r["conversas"]), f"{media('conversas'):.0f}", '<span class="x">—</span>'),
        ("Conversão", _pct(r["conversao"]), _pct(media("conversao")), seta(r["conversao"], media("conversao"), True)),
        ("Abandono", _pct(r["abandono"]), _pct(media("abandono")), seta(r["abandono"], media("abandono"), False)),
        ("Resposta", _min(r["tempo_medio_min"]), _min(media("tempo_medio_min")),
         seta(r["tempo_medio_min"], media("tempo_medio_min"), False)),
        ("Problemas/conv.", f"{prob_h:.2f}".replace(".", ","), f"{prob_m:.2f}".replace(".", ","),
         seta(prob_h, prob_m, False)),
    ]
    cab = '<div class="l h"><span></span><span class="x">ONTEM</span><span class="x">MÉDIA 7D</span><span class="x"></span></div>'
    return ('<div class="comp">' + cab + "".join(
        f'<div class="l"><span>{_e(a)}</span><span class="x">{_e(b)}</span><span class="x">{_e(c)}</span>{d}</div>'
        for a, b, c, d in linhas) + "</div>")


def html_painel(dia: date, dados: dict, hist: list[dict], formato: str = "ipad") -> str:
    r = dados["resumo"]
    P = [f'<div class="faixa"></div><div class="topo"><div class="logo"><img src="{_logo_src()}"></div>'
         f'<div><div class="titulo">Atendimento <span>IA</span></div>'
         f'<div class="sub">WhatsApp Pizzaria · turno {dia:%d/%m} (16:00–01:00)</div></div></div>']
    P.append('<div class="colunas"><div>')

    # Coluna 1: números do turno
    conv_ok = None
    if hist:
        conv_ok = r["conversao"] >= statistics.mean(h["conversao"] for h in hist)
    P.append('<div class="sec">TURNO</div><div class="grade g2">')
    P.append(_card("Conversas", str(r["conversas"]), f"{r['abandonadas']} sem pedido", cls="v", grande=True))
    P.append(_card("Pedidos fechados", str(r["pedidos"]), f"{r['pedidos_ia']} montados pela IA", cls="d", grande=True))
    P.append(_card("Conversão", _pct(r["conversao"]), "pedidos ÷ conversas",
                   cls="" if conv_ok is None else ("bom" if conv_ok else "ruim")))
    P.append(_card("Abandono", _pct(r["abandono"]), "conversa sem pedido",
                   cls="ruim" if r["abandono"] > 0.5 else "bom"))
    t = r["tempo_medio_min"]
    P.append(_card("Resposta média", _min(t), f"mediana {_min(r['tempo_mediana_min'])}",
                   cls="" if t is None else ("bom" if t <= 2 else "ruim" if t > 5 else "")))
    P.append(_card("Cancelados", str(r["cancelados_ia"]), "pedido da IA cancelado",
                   cls="ruim" if r["cancelados_ia"] else "bom"))
    P.append("</div></div><div>")

    # Coluna 2: problemas + 7 dias
    top = Counter(r["problemas"]).most_common(5)
    P.append('<div class="sec">PROBLEMAS</div><div class="grade">')
    P.append(_barras([(NOMES_CURTOS.get(k, k), v) for k, v in top], r["conversas"]) if top else
             '<div class="semalerta">Nenhum problema encontrado</div>')
    P.append("</div>")
    P.append(QUEBRA)
    P.append('<div class="sec">ÚLTIMOS 7 DIAS</div>' + _comparacao(r, hist))
    P.append("</div><div>")

    # Coluna 3: pares e regras
    P.append('<div class="sec">PARES PROPOSTOS</div><div class="pares">')
    for i, p in enumerate(dados["pares"], 1):
        existe = p.get("ja_existe_parecido")
        aviso = (f"já existe parecido (exemplo {existe}) — não proposto" if existe else
                 "completar o trecho entre colchetes" if p.get("falta_preencher") else "")
        P.append(f'<div class="par{" existe" if existe else ""}"><div class="n">PAR {i} · {_e(p["tema"]).upper()}</div>'
                 f'<div class="p">P: {_e(p["user"])}</div><div class="r">R: {_e(p["assistant"])}</div>'
                 + (f'<div class="a">{_e(aviso)}</div>' if aviso else "") + "</div>")
    if not dados["pares"]:
        P.append('<div class="semalerta">Nenhum par novo</div>')
    P.append("</div>")
    if dados.get("regras"):
        P.append('<div class="sec">REGRAS PARA A IA</div><ul class="regras">'
                 + "".join(f"<li>{_e(x)}</li>" for x in dados["regras"][:6]) + "</ul>")
    P.append("</div></div>")
    fim = ('<div class="fim"><div class="rodape">Dados do ALIV (só leitura) · pares só entram com o ok do Emerson</div>'
           '<div class="faixa" style="margin-top:22px"></div></div>')

    css = CSS + f"html, body {{ width: {FORMATOS[formato]['largura']}px }}" + (CSS_IPHONE if formato == "iphone" else "")

    def pagina(corpo: str) -> str:
        return (f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><style>{css}</style></head>'
                f'<body>{corpo}</body></html>')

    corpo = "".join(P)
    if formato != "iphone":
        return pagina(corpo.replace(QUEBRA, "") + fim)
    um, dois = corpo.split(QUEBRA)
    return QUEBRA.join([pagina(um + "</div></div>" + fim),
                        pagina(P[0] + '<div class="colunas"><div>' + dois + fim)])


def gerar_paineis(base: Path, dia: date, dados: dict, hist: list[dict]) -> dict[str, Path | Exception]:
    """Gera base_ipad.png, base_iphone_1.png e base_iphone_2.png. Formato que falhar vem como exceção."""
    out: dict[str, Path | Exception] = {}
    for formato, f in FORMATOS.items():
        try:
            paginas = html_painel(dia, dados, hist, formato).split(QUEBRA)
            if len(paginas) == 1:
                out[formato] = html_para_png(paginas[0], base.with_name(f"{base.stem}_{formato}.png"),
                                             f["largura"], f["escala"])
            else:
                for i, h in enumerate(paginas, 1):
                    out[f"{formato}_{i}"] = html_para_png(h, base.with_name(f"{base.stem}_{formato}_{i}.png"),
                                                          f["largura"], f["escala"])
        except Exception as e:  # noqa: BLE001
            out[formato] = e
    return out
