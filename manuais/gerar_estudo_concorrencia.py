#!/usr/bin/env python3
"""Estudo de concorrência — Tili Pizzaria / Burguer / Sushi (Porto Seguro e Arraial d'Ajuda).

Gera manuais/Estudo_Concorrencia_Tili_AAAA-MM.pdf nas cores da marca.

Fontes:
- Tili: ALIV /admin/api/menu/full_data (lojas 150 e 155, só leitura) em 09/11/2026 e
  pedidos da semana 27/10–02/11/2026 (mix de itens, taxa de entrega, dia da semana).
- Concorrentes: trechos indexados pelo buscador (iFood, TripAdvisor, guias) em 09/11/2026.
  As páginas do iFood, Google, Instagram e TripAdvisor NÃO puderam ser abertas desta sessão;
  todo número de concorrente é "não confirmado ao vivo".

Uso: python3 manuais/gerar_estudo_concorrencia.py [--saida ARQ.pdf]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

RAIZ = Path(__file__).resolve().parent.parent
LOGO_ORIG = RAIZ / "monitor" / "assets" / "logo_tili.jpg"

VERMELHO = HexColor("#C8102E")
DOURADO = HexColor("#D4A017")
PRETO = HexColor("#1A1A1A")
CREME = HexColor("#F3EFE6")
CINZA = HexColor("#6B6B6B")
VERDE = HexColor("#2E7D32")


S = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=VERMELHO),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13.5, leading=17, textColor=VERMELHO,
                         spaceBefore=8, spaceAfter=4),
    "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=PRETO,
                         spaceBefore=5, spaceAfter=2),
    "p": ParagraphStyle("p", fontName="Helvetica", fontSize=9, leading=12.2, textColor=PRETO),
    "pc": ParagraphStyle("pc", fontName="Helvetica", fontSize=8.2, leading=10.5, textColor=PRETO),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.2, leading=9.2, textColor=CINZA),
    "cel": ParagraphStyle("cel", fontName="Helvetica", fontSize=7.6, leading=9.4, textColor=PRETO),
    "celb": ParagraphStyle("celb", fontName="Helvetica-Bold", fontSize=7.6, leading=9.4, textColor=white),
    "capa": ParagraphStyle("capa", fontName="Helvetica-Bold", fontSize=26, leading=31, textColor=VERMELHO,
                           alignment=TA_CENTER),
    "capa2": ParagraphStyle("capa2", fontName="Helvetica", fontSize=11, leading=15, textColor=PRETO,
                            alignment=TA_CENTER),
}


def logo_leve() -> str:
    """Logo reduzido (240 px) para o PDF ficar leve e caber no envio ao Drive."""
    import tempfile
    from PIL import Image
    im = Image.open(LOGO_ORIG).convert("RGB")
    im.thumbnail((240, 240))
    arq = Path(tempfile.gettempdir()) / "tili_logo_240.jpg"
    im.save(arq, quality=80)
    return str(arq)


def P(t, st="cel"):
    return Paragraph(t, S[st])


def tabela(cab, linhas, larg, destaque_col=None):
    dados = [[P(c, "celb") for c in cab]] + [[P(str(c)) for c in l] for l in linhas]
    t = Table(dados, colWidths=[w * mm for w in larg], repeatRows=1)
    est = [
        ("BACKGROUND", (0, 0), (-1, 0), VERMELHO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, HexColor("#D9CDB0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(1, len(dados)):
        if i % 2 == 0:
            est.append(("BACKGROUND", (0, i), (-1, i), CREME))
    if destaque_col is not None:
        est.append(("BACKGROUND", (destaque_col, 1), (destaque_col, -1), HexColor("#FBEFC9")))
    t.setStyle(TableStyle(est))
    return t


def caixa(texto, cor=DOURADO):
    t = Table([[P(texto, "pc")]], colWidths=[180 * mm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, cor),
                           ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FFF8E6")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def rodape(c, doc):
    c.saveState()
    c.setFillColor(VERMELHO)
    c.rect(0, A4[1] - 9 * mm, A4[0], 9 * mm, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.rect(0, A4[1] - 10.2 * mm, A4[0], 1.2 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(15 * mm, A4[1] - 6 * mm, "TILI · Estudo de concorrência · Porto Seguro e Arraial d'Ajuda")
    c.drawRightString(A4[0] - 15 * mm, A4[1] - 6 * mm, "Novembro/2026")
    c.setFillColor(CINZA)
    c.setFont("Helvetica", 7)
    c.drawString(15 * mm, 8 * mm, "Concorrentes: trechos de busca, não confirmados ao vivo · "
                 "Tili: ALIV (só leitura) · Uso interno")
    c.drawRightString(A4[0] - 15 * mm, 8 * mm, f"pág. {doc.page}")
    c.restoreState()


def capa(c, doc):
    c.saveState()
    c.setFillColor(VERMELHO)
    c.rect(0, 0, A4[0], 22 * mm, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.rect(0, 22 * mm, A4[0], 2 * mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(A4[0] / 2, 10 * mm, "Tili Pizzaria · Tili Burguer · Tili Sushi & Poke — WhatsApp (73) 99917-9941")
    c.restoreState()


# ------------------------------------------------------------------ conteúdo
def montar(saida: Path):
    doc = SimpleDocTemplate(str(saida), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=16 * mm, bottomMargin=15 * mm,
                            title="Estudo de concorrência Tili — nov/2026", author="Tili",
                            pageCompression=1)
    E = []

    # ---------------- capa + resumo
    E += [Spacer(1, 18 * mm), Image(logo_leve(), width=55 * mm, height=53 * mm), Spacer(1, 8 * mm),
          P("Estudo de concorrência", "capa"),
          P("Pizzaria delivery · Hamburgueria · Sushi", "capa2"),
          P("Porto Seguro e Arraial d'Ajuda (BA) · 09/11/2026", "capa2"), Spacer(1, 10 * mm)]
    E.append(caixa(
        "<b>Resumo em 6 pontos</b><br/>"
        "1. <b>Pizza:</b> estamos no meio da faixa. Grande muçarela R$ 56 contra entrada de R$ 38 a R$ 78 "
        "nos concorrentes (média ~R$ 58). Calabresa G R$ 64 fica acima das ofertas de entrada da Luna "
        "(½ calabresa ½ muçarela G R$ 49,90) e do combo da Delizzia (G calabresa + Coca 1L R$ 58).<br/>"
        "2. <b>Burguer:</b> estamos <b>baratos</b>. X-Burguer R$ 22 contra R$ 18,90–34 (média R$ 27,63); "
        "artesanal de entrada R$ 33 contra R$ 24,90–45 (média R$ 36,63).<br/>"
        "3. <b>Sushi:</b> estamos <b>bem mais baratos</b> que o único concorrente com preço visível (Takeshi, "
        "Arraial): temaki de salmão R$ 35,90 contra R$ 49–54; combo de 25 peças R$ 89,90 (R$ 3,60/peça) "
        "contra R$ 6,03–6,60/peça.<br/>"
        "4. <b>Nota iFood:</b> Tili Pizzaria 4,9 com 1.074 avaliações — mais avaliações que qualquer "
        "concorrente encontrado (o maior é Brasa Burger, 901).<br/>"
        "5. <b>Promoções por dia:</b> nenhuma confirmada nos concorrentes. Nós temos 3 (Terça Maluca, "
        "Quarta Maluca, Sexta do Temaki). Eles usam preço riscado (de/por), \"leve outro burger\" e "
        "combos de entrada com refri 1L.<br/>"
        "6. <b>Oportunidade estimada:</b> cerca de <b>R$ 4,5 mil/mês</b> com reajustes pequenos onde "
        "estamos abaixo do mercado, mais o potencial de uma promoção de quinta na Pizzaria."))
    E.append(Spacer(1, 4 * mm))
    E.append(caixa(
        "<b>Atenção — limite da pesquisa.</b> Esta sessão não conseguiu abrir as páginas do iFood, Google, "
        "Instagram, TripAdvisor, anota.ai, goomer e cardápios digitais (bloqueio de rede da sessão). "
        "Todos os números dos concorrentes vêm de <b>trechos que o buscador guardou</b>, com data "
        "desconhecida, e muitos são \"a partir de\". Não há taxa de entrega de nenhum concorrente. "
        "Detalhes na última página.", VERMELHO))
    E.append(PageBreak())

    # ---------------- pizzaria
    E.append(P("1. Pizzaria delivery", "h1"))
    E.append(P("Tili: P 25 cm/4 fatias · M 30 cm/6 · G 35 cm/8. Preço de cardápio do ALIV (app/balcão).", "small"))
    E.append(P("Comparação de preço", "h2"))
    E.append(tabela(
        ["Item", "Tili", "Média conc.", "Faixa conc.", "Nossa posição"],
        [["Pizza G (sabor mais barato)", "R$ 56,00 (muçarela)", "R$ 57,98", "R$ 38 – 78",
          "Na média"],
         ["Pizza G calabresa", "R$ 64,00", "—", "Luna ½ calab ½ mus R$ 49,90 · Domino's promo R$ 67,90 "
          "(cheia R$ 98)", "Acima das ofertas de entrada"],
         ["Combo G calabresa + refri", "R$ 72,90 (Coca 1,5L)", "—", "Delizzia R$ 58 (Coca 1L)",
          "R$ 14,90 acima (refri maior)"],
         ["Pizza M (mais barata)", "R$ 45,00 (muçarela)", "—", "Delizzia a partir de R$ 37",
          "Acima (1 ponto só)"],
         ["Pizza P/broto 4 fatias", "R$ 34,00 (muçarela)", "R$ 40,50", "Luana R$ 31 – San Diego R$ 50",
          "Na média"],
         ["Calabresa P / M / G", "R$ 42 / 53 / 64", "—", "não encontrado avulso", "—"],
         ["Muçarela P / M / G", "R$ 34 / 45 / 56", "—", "não encontrado avulso", "—"],
         ["Terça Maluca G", "R$ 39,99", "—", "nenhuma promo por dia achada", "Só nós temos"]],
        [40, 32, 22, 52, 34], destaque_col=1))
    E.append(Spacer(1, 2 * mm))
    E.append(P("Média de G = San Diego 78, Luna 48, Delizzia 38, Domino's 67,90 (promo). P = San Diego 50, "
               "Luana 31. Valores \"a partir de\" = sabor mais barato da casa.", "small"))
    E.append(P("Concorrentes", "h2"))
    E.append(tabela(
        ["Concorrente", "Nota iFood", "Pedido mín.", "Taxa", "Horário", "Promoções"],
        [["<b>Tili Pizzaria</b>", "<b>4,9 (1.074)</b>", "não lido no ALIV", "R$ 6,43 média (R$ 5 / 6,99)",
          "noite, 16h–01h", "Terça Maluca G R$ 39,99 · combos G + Coca 1,5L"],
         ["San Diego Pizzas e Esfirras (Arraial)", "4,9 (122)", "R$ 40", "não encontrada",
          "18h–23h59, sem quarta", "nenhuma achada"],
         ["Luna Pizzaria (Village)", "4,7 (58)", "R$ 30", "não encontrada", "todo dia 17h30–23h30",
          "G ½ calabresa ½ muçarela R$ 49,90"],
         ["Delizzia Pizzaria (Centro)", "4,6 (201)", "R$ 50", "não encontrada", "ter–dom, ~18h–00h",
          "combos G + Coca 1L (R$ 58 / 67)"],
         ["Domino's Porto Seguro", "4,6 (158)", "R$ 50", "não encontrada", "todo dia ~16h15–23h15",
          "G de R$ 97,90 por R$ 67,90 · 2 M + refri 2L R$ 115,90"]],
        [40, 20, 20, 30, 32, 38]))
    E.append(P("Fora do top 4: Pizzaria Luana (iFood 4,8/42; broto R$ 31, G R$ 46), Vovó Bela (TripAdvisor "
               "4,9/596, sem avaliações no iFood), Paolo Pizza e Da Luigi em Arraial (fortes no TripAdvisor, "
               "sem iFood achado).", "small"))
    E.append(PageBreak())

    # ---------------- burguer
    E.append(P("2. Hamburgueria", "h1"))
    E.append(P("Comparação de preço", "h2"))
    E.append(tabela(
        ["Item", "Tili", "Média conc.", "Faixa conc.", "Nossa posição"],
        [["X-Burguer (mais simples c/ queijo)", "R$ 22,00 (90 g)", "R$ 27,63",
          "Brasa R$ 18,90 (90 g) · Gringo R$ 30 · San Diego R$ 34 (100 g)", "<b>Barato</b> (-20%)"],
         ["Artesanal de entrada", "R$ 33,00 Virgulino (120 g)", "R$ 36,63",
          "Brasa R$ 24,90 (180 g) · Gringo R$ 40 · San Diego R$ 45 (160 g)", "<b>Barato</b> (-10%)"],
         ["Combo burger + batata + refri", "R$ 47,90 Coronel + batata G + lata", "—",
          "Gringo R$ 55 – 75", "Barato"],
         ["Combo de entrada (iFood)", "R$ 24,99 X + suco + batata P", "—", "não encontrado",
          "Só nós (149 vendidos/semana)"]],
        [40, 36, 20, 52, 32], destaque_col=1))
    E.append(P("Brasa Burger mostra R$ 24,90 com o selo \"Leve outro burger\" (promo do iFood); a página tem "
               "copyright de 2021. La Brasa Burger: nenhum preço achado.", "small"))
    E.append(P("Concorrentes", "h2"))
    E.append(tabela(
        ["Concorrente", "Nota iFood", "Pedido mín.", "Taxa", "Horário", "Promoções"],
        [["<b>Tili Burguer</b> (loja iFood da Pizzaria)", "não lida", "não lido", "R$ 6,43 média",
          "noite, 16h–01h", "combos X + suco + batata R$ 24,99; Combo 10.10"],
         ["San Diego Burger (Centro)", "4,7 (28)", "R$ 16", "não encontrada",
          "seg–qui 17h30–23h30; sex–sáb 17h–00h", "nenhuma achada"],
         ["Gringo Burgers (Shopping Porto Plaza)", "4,9 (11) ou 4,7 (4)", "R$ 25", "não encontrada",
          "abre 13h–14h dia útil, fecha ~23h", "combos R$ 55–75"],
         ["Hamburgueria Brasa Burger (Tabapiri)", "4,3 (901)", "R$ 25 ou R$ 15", "não encontrada",
          "dom abre 18h (resto não achado)", "\"Leve outro burger\" (iFood)"],
         ["La Brasa Burger (Taperapuan)", "4,5 (115)", "R$ 20", "não encontrada", "abre 17h30",
          "nenhuma achada"]],
        [40, 22, 18, 24, 38, 38]))
    E.append(P("Arraial d'Ajuda: Black Mamba Burger (mín. R$ 20, sem preço), Gira Mundo (TripAdvisor 4,3/214, "
               "burger ~R$ 48 em avaliação), Porkbull (smash 150 g R$ 39,60). Top Burgui fechou em 04/2024.",
               "small"))
    E.append(PageBreak())

    # ---------------- sushi
    E.append(P("3. Sushi / comida japonesa", "h1"))
    E.append(P("Comparação de preço", "h2"))
    E.append(tabela(
        ["Item", "Tili", "Concorrentes", "Nossa posição"],
        [["Combo 20–30 peças", "Econômico 24 p R$ 49,90 · Tili Salmão 24 p R$ 79,90 · Salmão 25 p R$ 89,90 "
          "· Variado 25 p R$ 89,90 · Especial 23 p R$ 99,90",
          "Takeshi: Casal Salmão 20 p R$ 132 · Básico 28 p R$ 168,90 (R$ 6,03–6,60/peça) · Yamazaki: barcas "
          "R$ 78–141 (peças não informadas, página de ~3 anos)", "<b>Barato</b>: R$ 2,08–4,34/peça"],
         ["Temaki salmão", "R$ 35,90 (Filadélfia R$ 35,90; grelhado R$ 32,99; Hot R$ 33,90)",
          "Takeshi: salmão R$ 49–54 · Philadelfia R$ 51 · grelhado phila R$ 47",
          "<b>Barato</b> (-27% a -34%)"],
         ["Temaki mais barato", "California R$ 27,99", "Takeshi: faixa R$ 40–59", "Barato"],
         ["Poke", "Mini R$ 39,90 · Poke R$ 49,90", "não encontrado em nenhum", "sem comparação"],
         ["Peça avulsa", "R$ 2,99 todo dia · R$ 1,99 na quarta", "nenhum concorrente com peça avulsa achada",
          "Só nós"]],
        [30, 58, 62, 30], destaque_col=1))
    E.append(P("Concorrentes", "h2"))
    E.append(tabela(
        ["Concorrente", "Nota iFood", "Pedido mín.", "Taxa", "Horário", "Promoções"],
        [["<b>Tili Sushi & Poke</b>", "não lida", "não lido", "R$ 7,52 média (R$ 6,99)", "noite, 16h–01h",
          "Quarta Maluca R$ 1,99/peça · Sexta do Temaki · peça R$ 2,99"],
         ["Takeshi Sushi Bar (Arraial)", "5,0 (5) ou 3,7 (3) — não confiável", "R$ 12", "não encontrada",
          "abre 18h", "nenhuma achada"],
         ["Natsuki Sushi Bar (Porto Seguro)", "sem loja no iFood achada", "—", "—",
          "ter–dom 18h–00h (fonte antiga)", "nenhuma achada; gasto R$ 80–100/pessoa"],
         ["Yamazaki Sushi (Baianão)", "não encontrada", "R$ 30", "não encontrada", "dom abre 17h",
          "\"promoções de combos\" sem detalhe"],
         ["Sushi Yang (Arraial)", "sem loja no iFood achada", "—", "—", "abre ~18h",
          "nenhuma achada; TripAdvisor 4,7 (325), $$$$"]],
        [40, 30, 18, 26, 30, 36]))
    E.append(P("Reservas: Sushi San (iFood 4,8/31, combinado 30 p sem preço), Wasabi Sushi (mín. R$ 10), "
               "Japapeii em Arraial (hot roll 12 un R$ 35).", "small"))
    E.append(PageBreak())

    # ---------------- caros / baratos / promos
    E.append(P("4. Onde estamos caros e baratos", "h1"))
    E.append(tabela(
        ["", "Itens", "Leitura"],
        [["<b>Caros</b>", "Pizza G calabresa (R$ 64) e Combo Campeão (R$ 72,90) contra ofertas de entrada de "
          "R$ 49,90–58; pizza M (R$ 45 contra Delizzia R$ 37).",
          "A diferença está na <b>porta de entrada</b> do iFood (combo barato com refri 1L), não no cardápio "
          "todo."],
         ["<b>Na média</b>", "Pizza G muçarela (R$ 56), broto/P (R$ 34), taxa de entrega.", "Manter."],
         ["<b>Baratos</b>", "X-Burguers (R$ 22), artesanais (R$ 33–52), temakis (R$ 27,99–35,99), combos de "
          "sushi (R$ 2–4/peça), peça R$ 2,99.", "Há espaço para reajuste pequeno sem perder a posição."]],
        [22, 90, 68]))
    E.append(P("Promoções que eles fazem e nós não", "h2"))
    E.append(tabela(
        ["Promoção", "Quem faz", "Tili hoje"],
        [["Preço riscado \"de / por\" no iFood", "Domino's (G de R$ 97,90 por R$ 67,90), Porkbull",
          "Não usamos (campo \"preço de comparação\" vazio em todos os itens)"],
         ["\"Leve outro burger\" (2º burger com desconto)", "Brasa Burger", "Não temos"],
         ["Pizza G meio a meio calabresa/muçarela a preço fixo baixo", "Luna (R$ 49,90)",
          "Só na terça (R$ 39,99)"],
         ["Combo G + refri 1L (entrada)", "Delizzia (R$ 58 / R$ 67)", "Só combos com 1,5L a partir de R$ 72,90"],
         ["2 pizzas médias + refri 2L", "Domino's (R$ 115,90)", "Temos 2 G a partir de R$ 115,90"]],
        [62, 58, 60]))
    E.append(P("Nenhuma promoção fixa por dia da semana foi confirmada nos concorrentes. As nossas (terça, "
               "quarta, sexta) são vantagem — a Quarta Maluca do Sushi fez 296 pedidos na quarta 28/10, "
               "o dobro de qualquer outro dia da semana.", "p"))
    E.append(Spacer(1, 3 * mm))
    E.append(P("Nossa semana (27/10–02/11, ALIV)", "h2"))
    E.append(tabela(
        ["", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"],
        [["Pizzaria pedidos", 226, 177, "<b>146</b>", "<b>130</b>", 218, 234, 309],
         ["Pizzaria vendas", "14,8 mil", "10,3 mil", "<b>9,3 mil</b>", "<b>9,5 mil</b>", "17,5 mil",
          "19,1 mil", "23,3 mil"],
         ["Sushi pedidos", "—", 74, "<b>296</b>", 96, 150, 147, 149]],
        [36, 20, 20, 20, 20, 20, 22, 22]))
    E.append(PageBreak())

    # ---------------- oportunidades
    E.append(P("5. Cinco oportunidades", "h1"))
    E.append(P("Volumes da semana 27/10–02/11 no ALIV. Impacto = receita a mais por mês (×4,3 semanas), "
               "<b>supondo volume igual</b>. É estimativa, não garantia: teste por 2 semanas e compare no "
               "fechamento semanal.", "small"))
    ops = [
        ("1. Reajustar X-Burguers em +R$ 2 (R$ 22 -> R$ 24)",
         "Ainda abaixo de Gringo (R$ 30) e San Diego (R$ 34). Inclui X-Salada, X-Bananinha, X-Burguer, "
         "Cheddar. Não mexer no combo de R$ 24,99, que é a isca do iFood.",
         "~240 un/semana × R$ 2 -> <b>~ R$ 2,1 mil/mês</b>"),
        ("2. Reajustar artesanais em +R$ 2",
         "Virgulino iria a R$ 35, ainda abaixo da média (R$ 36,63) e de Gringo/San Diego (R$ 40–45). "
         "Barão, Lampião, Maria Bonita, Serejo e Coronel são os mais vendidos.",
         "~220 un/semana × R$ 2 -> <b>~ R$ 1,9 mil/mês</b>"),
        ("3. Reajustar temakis de salmão em +R$ 3 (exceto na Sexta do Temaki)",
         "Temaki salmão R$ 38,90 continua 20% abaixo do Takeshi (R$ 49–54).",
         "~150 temakis/semana × R$ 3 -> <b>~ R$ 1,9 mil/mês</b> (menos a parte vendida na sexta)"),
        ("4. Criar uma promoção de quinta na Pizzaria",
         "Quarta e quinta são os piores dias da Pizzaria (146 e 130 pedidos, ~R$ 9,4 mil cada); na quarta os "
         "motoboys já estão cheios com a Quarta Maluca do Sushi. Ex.: \"Quinta da Pizza\" com G "
         "calabresa ou muçarela + Coca 1L por R$ 59,90, para bater o combo da Delizzia (R$ 58).",
         "Hipótese: +20 pedidos × ticket R$ 72 -> <b>~ R$ 6,2 mil/mês</b> de venda (margem menor)"),
        ("5. Usar preço riscado e combo de entrada no iFood",
         "Preencher \"preço de comparação\" nos combos (ex.: Combo Campeão de R$ 80,00 por R$ 72,90 = "
         "pizza G R$ 64 + Coca 1,5L R$ 16 avulsas) e lançar G calabresa + Coca 1L para competir com Luna e Delizzia na vitrine.",
         "Hipótese: +10 combos/semana × R$ 62 -> <b>~ R$ 2,7 mil/mês</b>"),
    ]
    for tit, txt, imp in ops:
        E.append(KeepTogether([P(tit, "h3"), P(txt, "p"), P("Impacto estimado: " + imp, "p"),
                               Spacer(1, 2.5 * mm)]))
    E.append(caixa(
        "<b>Soma:</b> reajustes 1–3 ~ <b>R$ 5,9 mil/mês</b> de receita sem custo extra (~ R$ 4,5 mil se "
        "perder 25% desse ganho por queda de volume). Itens 4–5 dependem de teste.<br/>"
        "<b>Não recomendado agora:</b> mexer na peça de R$ 2,99. É o motor do Sushi (8.242 peças, "
        "R$ 24,6 mil na semana); +R$ 0,30 renderia ~R$ 10 mil/mês, mas uma queda de 9% no volume já anula "
        "o ganho. Se testar, teste só num dia."))
    E.append(PageBreak())

    # ---------------- bloqueios
    E.append(P("6. O que não foi possível ler", "h1"))
    E.append(tabela(
        ["Página / site", "Situação", "O que faltou"],
        [["iFood (www, marketplace)", "Bloqueado pela rede e pela política de segurança da sessão",
          "Cardápio completo, calabresa/muçarela avulsas por tamanho, taxa de entrega, nota atual"],
         ["Google / Google Maps", "Bloqueado", "Nota e nº de avaliações do Google, horários"],
         ["Instagram", "Bloqueado", "Promoções por dia da semana postadas nos perfis"],
         ["TripAdvisor, anota.ai, goomer, menudino, pedidosite, linktree", "Bloqueado ou sem conteúdo",
          "Cardápios de Natsuki, Sushi Yang, Yamazaki, La Brasa"],
         ["ALIV — pedido mínimo da Tili", "Não está no full_data", "Pedido mínimo nosso"]],
        [48, 52, 80]))
    E.append(Spacer(1, 3 * mm))
    E.append(P("Todos os números de concorrentes vêm de trechos do buscador, com data desconhecida. Onde "
               "fontes divergiram, os dois valores aparecem. Nada foi estimado para preencher lacunas.", "p"))
    E.append(P("Principais fontes", "h2"))
    for f in [
        "ifood.com.br/delivery/porto-seguro-ba/luna-pizzaria-village/c6e1fe44-…",
        "ifood.com.br/delivery/porto-seguro-ba/delizzia-pizzaria-centro/de558982-…",
        "ifood.com.br/delivery/porto-seguro-ba/dominos-pizza---porto-seguro-centro/8db3d078-…",
        "ifood.com.br/delivery/porto-seguro-ba/san-diego-pizzas-e-esfirras---arraial-arraial-dajuda/7a596f99-…",
        "ifood.com.br/delivery/porto-seguro-ba/san-diego-burger-centro/a9233f4a-…",
        "ifood.com.br/delivery/porto-seguro-ba/gringo-burgers-mirante/055f1a55-…",
        "ifood.com.br/delivery/porto-seguro-ba/hamburgueria-brasa-burger-hamburguer-artesanal-tabapiri/ebf1a937-…",
        "ifood.com.br/delivery/porto-seguro-ba/la-brasa-burger-porto-seguro-taperapuan/91b274e8-…",
        "ifood.com.br/delivery/porto-seguro-ba/takeshi-sushi-bar-centro-arraial-dajuda/3ca87eed-…",
        "ifood.com.br/delivery/porto-seguro-ba/yamazaki-sushi-baianao/424f7e03-…",
        "tripadvisor.com — Natsuki Sushi Bar (d14967539), Sushi Yang (d13290835)",
    ]:
        E.append(P("• " + f, "small"))
    E.append(Spacer(1, 4 * mm))
    E.append(caixa("<b>Para a próxima versão:</b> com o iFood acessível, dá para ler o cardápio ao vivo de cada "
                   "concorrente, a taxa para um endereço de referência (ex.: Centro e Arraial) e repetir este "
                   "estudo todo mês.", VERMELHO))

    doc.build(E, onFirstPage=capa, onLaterPages=rodape)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=str(RAIZ / "manuais" / "Estudo_Concorrencia_Tili_2026-11.pdf"))
    a = ap.parse_args()
    montar(Path(a.saida))
    print(a.saida)
