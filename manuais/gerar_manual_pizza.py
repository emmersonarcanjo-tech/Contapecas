#!/usr/bin/env python3
"""Manual de Montagem — Tili Pizzaria (PDF A4 deitado, uma página por pizza).

Layout no estilo do "Manual Pizza Ilustrado": pizza em camadas à esquerda
(massa embaixo, cobertura em cima) e ingredientes alinhados à direita, com
gramatura P / M / G. Imagens dos ingredientes em manuais/ingredientes/.

Lê do ALIV (SÓ LEITURA, loja 150):
  GET /admin/api/menu/full_data                         → pizzas ativas (categoria 798)
  GET /admin/menu/product/{id}/recipes?size_id=268|269|270  → ficha técnica P / M / G

Uso:
  python3 manuais/gerar_manual_pizza.py [--saida manuais/x.pdf] [--paginas N]
        [--cache DIR]   # usa/grava menu.json e recipes.json nessa pasta
Credenciais: ALIV_USER / ALIV_PASS (variáveis de ambiente).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "monitor"))

LOJA = 150
CATEGORIA_PIZZAS = 798
TAMANHOS = [(268, "P", "25 cm · 4 fatias"), (269, "M", "30 cm · 6 fatias"), (270, "G", "35 cm · 8 fatias")]

VERMELHO = HexColor("#C8102E")
DOURADO = HexColor("#D4A017")
PRETO = HexColor("#1A1A1A")
CINZA = HexColor("#F3EFE6")
CINZA_ESC = HexColor("#6B6B6B")
LOGO = RAIZ / "monitor" / "assets" / "logo_tili.png"

pdfmetrics.registerFont(TTFont("Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))

# ---------------------------------------------------------------- ingredientes
# Itens da ficha que não vão na praça (embalagem/acompanhamento).
FORA_DA_PRACA = ("embalagem", "mesinha", "caixa de pizza", "sachê", "sache")

# Conversão das unidades de compra do ALIV para gramas na praça.
# (nome do ingrediente na ficha, unidade) → gramas por 1 unidade
GRAMAS_POR_UNIDADE = {
    ("molho de tomate", "UN"): 1700,   # sachê 1,7 kg
    ("azeitona", "BD"): 1800,          # balde 1,8 kg
    ("milho", "UN"): 170,              # sachê 170 g
    ("cream cheese", "UN"): 1500,      # bisnaga 1,5 kg
}

# Etapa de montagem de cada ingrediente (ordem na praça).
ETAPAS = [
    ("massa", "Disco"),
    ("base", "Base"),
    ("queijo", "Queijo"),
    ("proteina", "Recheio"),
    ("vegetal", "Recheio"),
    ("cremoso", "Cremoso"),
    ("final", "Finalização"),
    ("pos", "Depois do forno"),
]
CLASSE = {
    "massa": "massa", "molho de tomate": "base", "creme de leite": "base",
    "mussarela": "queijo", "provolone": "queijo",
    "presunto": "proteina", "frango": "proteina", "calabresa": "proteina", "bacon": "proteina",
    "lombinho canadense": "proteina", "carne de sol": "proteina", "camarão": "proteina",
    "tomate": "vegetal", "cebola": "vegetal", "pimentão": "vegetal", "milho": "vegetal",
    "ervilha": "vegetal", "ovo": "vegetal", "pimenta calabresa": "vegetal",
    "catupiry": "cremoso", "cheddar cremoso": "cremoso", "cream cheese": "cremoso",
    "parmesão": "final", "orégano": "final", "azeitona": "final",
    "chocolate ao leite": "cremoso", "nutella": "cremoso",
    "manjericão": "pos",
}
NOME_PRACA = {"mussarela": "Muçarela", "cheddar cremoso": "Cheddar", "catupiry": "Catupiry Original"}

# Palavras da descrição do cardápio que precisam aparecer na ficha (para achar fichas incompletas).
PALAVRAS_DESC = {
    "brócolis": "brócolis", "palmito": "palmito", "champignon": "champignon",
    "tomate seco": "tomate seco", "manjericão": "manjericão", "azeite": "azeite",
    "banana": "banana", "cebola": "cebola", "pimentão": "pimentão", "ervilha": "ervilha",
    "ovo": "ovo", "bacon": "bacon", "presunto": "presunto", "calabresa": "calabresa",
    "frango": "frango", "catupiry": "catupiry", "cheddar": "cheddar", "milho": "milho",
    "parmesão": "parmesão", "provolone": "provolone", "cream cheese": "cream cheese",
    "camarão": "camarão", "carne de sol": "carne de sol", "lombinho": "lombinho",
    "morango": "morango", "serenata": "serenata", "confete": "confete", "goiabada": "goiabada",
    "peito de peru": "peito de peru", "abacaxi": "abacaxi", "geleia": "geleia",
    "canela": "canela", "leite condensado": "leite condensado", "nutella": "nutella",
    "chocolate": "chocolate", "tomate": "tomate",
}


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def chave(nome: str) -> str:
    n = nome.lower().strip()
    return "massa" if n.startswith("massa") else n


def gramas(nome: str, unidade: str, qtd: float) -> tuple[float | None, str]:
    """(valor, unidade de praça)."""
    k = chave(nome)
    if k == "massa":
        return None, "disco"
    if unidade == "KG":
        return qtd * 1000, "g"
    if unidade == "G":
        return qtd, "g"
    g = GRAMAS_POR_UNIDADE.get((k, unidade))
    if g:
        return qtd * g, "g"
    if k == "ovo":
        return qtd, "un"
    return qtd, unidade.lower()


def fmt(v: float | None, un: str, massa_cm: str = "") -> str:
    if un == "disco":
        return massa_cm
    if un == "g":
        if v >= 20:
            v = 5 * round(v / 5)
        return f"{v:.0f} g"
    if un == "un":
        return f"{v:.0f} un" if v == int(v) else f"{v:g} un"
    return f"{v:g} {un}"


# ---------------------------------------------------------------- dados
def carregar(cache: Path | None) -> tuple[dict, dict]:
    if cache and (cache / "menu.json").exists() and (cache / "recipes.json").exists():
        return json.loads((cache / "menu.json").read_text()), json.loads((cache / "recipes.json").read_text())
    from monitor import Aliv
    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        sys.exit("ERRO: defina ALIV_USER e ALIV_PASS.")
    a = Aliv(user, pwd)
    menu = a.get("/admin/api/menu/full_data", {"store_id": LOJA})
    rec = {}
    for c in menu["categories"]:
        if c["id"] != CATEGORIA_PIZZAS:
            continue
        for p in c["products"]:
            if not p["is_active"]:
                continue
            rec[str(p["id"])] = {
                "name": p["name"], "desc": p["full_data"].get("description"),
                "recipes": {str(s): a.get(f"/admin/menu/product/{p['id']}/recipes", {"size_id": s})
                            for s, _, _ in TAMANHOS},
            }
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "menu.json").write_text(json.dumps(menu, ensure_ascii=False))
        (cache / "recipes.json").write_text(json.dumps(rec, ensure_ascii=False))
    return menu, rec


def montar(rec: dict) -> tuple[list[dict], list[dict]]:
    """Pizzas com ficha (prontas para a página) e pendências (sem ficha / incompleta)."""
    pizzas, pend = [], []
    for pid, p in rec.items():
        nome, desc = p["name"], (p["desc"] or "").strip()
        linhas: dict[str, dict] = {}
        tem = {s: bool(p["recipes"].get(str(s))) for s, _, _ in TAMANHOS}
        for s, _, _ in TAMANHOS:
            for i in p["recipes"].get(str(s)) or []:
                n = i["ingredient_name"]
                if sem_acento(n).startswith(tuple(sem_acento(x) for x in FORA_DA_PRACA)):
                    continue
                k = chave(n)
                v, un = gramas(n, i["ingredient_unit"], i["quantity"])
                cm = re.search(r"(\d+)\s*cm", n, re.I)
                lin = linhas.setdefault(k, {"nome": "Disco de massa" if k == "massa" else NOME_PRACA.get(k, n),
                                            "classe": CLASSE.get(k, "proteina"), "q": {}})
                lin["q"][s] = fmt(v, un, f"{cm.group(1)} cm" if cm else "1 un")
        problemas = []
        if not any(tem.values()):
            problemas.append("sem ficha técnica no ALIV")
        else:
            falta_tam = [t for s, t, _ in TAMANHOS if not tem[s]]
            if falta_tam:
                problemas.append("sem ficha no tamanho " + ", ".join(falta_tam))
            ficha_txt = sem_acento(" ".join(linhas))
            d = sem_acento(desc)
            faltando = []
            for pal, rot in PALAVRAS_DESC.items():
                pa = sem_acento(pal)
                if pa in d and pa not in ficha_txt:
                    if pa == "tomate" and ("molho de tomate" in d.replace(pa + " seco", "")
                                           and d.count("tomate") == d.count("molho de tomate")):
                        continue
                    if pa == "chocolate" and "chocolate ao leite" in ficha_txt:
                        continue
                    if pa == "frango" and "frango" in ficha_txt:
                        continue
                    faltando.append(rot)
            if "tomate seco" in faltando and "tomate" in faltando:
                faltando.remove("tomate")
            if faltando:
                problemas.append("falta na ficha: " + ", ".join(faltando))
            sem_qtd = [l["nome"] for l in linhas.values() if len(l["q"]) < 3 and l["classe"] != "massa"]
            if sem_qtd:
                problemas.append("sem gramatura em algum tamanho: " + ", ".join(sem_qtd))
        if problemas:
            pend.append({"nome": nome, "id": pid, "problemas": problemas})
        if any(tem.values()):
            ordem = [e for e, _ in ETAPAS]
            lst = sorted(linhas.values(), key=lambda l: ordem.index(l["classe"]))
            pizzas.append({"nome": nome, "id": pid, "desc": desc, "linhas": lst,
                           "doce": any(l["nome"].lower() in ("creme de leite",) for l in lst),
                           "problemas": problemas})
    pizzas.sort(key=lambda p: sem_acento(p["nome"]))
    pend.sort(key=lambda p: sem_acento(p["nome"]))
    return pizzas, pend




# ---------------------------------------------------------------- imagens
PASTA_ING = Path(__file__).resolve().parent / "ingredientes"
_CACHE_IMG: dict = {}

# chave da ficha → (arquivo, tinta RGB ou None, largura em pt, cópias)
IMAGENS = {
    "massa": ("massa", None, 300, 1),
    "molho de tomate": ("molho", None, 255, 1),
    "creme de leite": ("cream_cheese", None, 190, 1),
    "mussarela": ("queijo", None, 215, 1),
    "provolone": ("queijo", (250, 235, 190), 180, 1),
    "parmesão": ("queijo", (250, 245, 220), 150, 1),
    "presunto": ("presunto_ralado", None, 200, 1),
    "frango": ("frango", None, 190, 1),
    "calabresa": ("calabresa", None, 120, 2),
    "bacon": ("bacon", None, 190, 1),
    "lombinho canadense": ("presunto_fatia", (245, 170, 160), 110, 2),
    "carne de sol": ("carne", None, 185, 1),
    "camarão": ("camarao", None, 85, 3),
    "tomate": ("tomate", None, 85, 4),
    "cebola": ("cebola", None, 120, 2),
    "pimentão": ("pimentao", None, 105, 2),
    "milho": ("milho", None, 150, 1),
    "ervilha": ("ervilha", None, 32, 5),
    "ovo": ("ovo", None, 110, 2),
    "pimenta calabresa": ("oregano", (200, 40, 20), 140, 1),
    "catupiry": ("catupiry", None, 190, 1),
    "cheddar cremoso": ("cheddar", None, 190, 1),
    "cream cheese": ("cream_cheese", None, 170, 1),
    "chocolate ao leite": ("catupiry", (75, 40, 22), 200, 1),
    "nutella": ("catupiry", (95, 50, 30), 200, 1),
    "orégano": ("oregano", None, 150, 1),
    "azeitona": ("azeitona", None, 24, 7),
    "manjericão": ("manjericao", None, 190, 1),
}


def imagem(arq: str, tinta) -> tuple[str, float]:
    """Caminho do PNG (tingido se preciso) e proporção altura/largura."""
    k = (arq, tinta)
    if k not in _CACHE_IMG:
        from PIL import Image
        import tempfile
        im = Image.open(PASTA_ING / f"{arq}.png").convert("RGBA")
        im.thumbnail((360, 360))                 # suficiente para impressão e deixa o PDF leve
        if tinta:
            r, g, b, a = im.split()
            lum = Image.merge("RGB", (r, g, b)).convert("L")
            cor = Image.merge("RGB", [lum.point(lambda v, c=c: int(v * c / 255)) for c in tinta])
            im = Image.merge("RGBA", (*cor.split(), a))
        fd, caminho = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        im.save(caminho, optimize=True)
        _CACHE_IMG[k] = (caminho, im.size[1] / im.size[0])
    return _CACHE_IMG[k]


# ---------------------------------------------------------------- desenho
PW, PH = landscape(A4)
BORDA = 12


def moldura(c):
    c.setStrokeColor(DOURADO)
    c.setLineWidth(3)
    c.rect(BORDA, BORDA, PW - 2 * BORDA, PH - 2 * BORDA, stroke=1, fill=0)


def titulo(c, txt, num=None, cor=VERMELHO):
    tam = 44
    while c.stringWidth(txt, "Sans-B", tam) > PW - 260 and tam > 24:
        tam -= 1
    c.setFillColor(cor)
    c.setFont("Sans-B", tam)
    c.drawCentredString(PW / 2 - 20, PH - 72, txt)
    c.setFillColor(DOURADO)
    c.rect(PW / 2 - 20 - 60, PH - 86, 120, 4, stroke=0, fill=1)
    if LOGO.exists():
        c.drawImage(str(LOGO), PW - BORDA - 82, PH - BORDA - 74, 68, 68, mask="auto", preserveAspectRatio=True)
    if num is not None:
        c.setFillColor(PRETO)
        c.circle(BORDA + 40, PH - BORDA - 38, 20, stroke=0, fill=1)
        c.setFillColor(DOURADO)
        c.setFont("Sans-B", 16)
        c.drawCentredString(BORDA + 40, PH - BORDA - 44, f"{num:02d}")


def quebra(c, txt, fonte, tam, larg):
    linhas, atual = [], ""
    for w in txt.split():
        t = (atual + " " + w).strip()
        if c.stringWidth(t, fonte, tam) <= larg:
            atual = t
        else:
            linhas.append(atual)
            atual = w
    if atual:
        linhas.append(atual)
    return linhas


def depois_do_forno(p, l) -> bool:
    n = l["nome"].lower()
    return l["classe"] == "pos" or (p["doce"] and ("chocolate" in n or "nutella" in n))


def desenha_camada(c, chave_ing, cx, cy, altura_max, seed):
    import random
    arq, tinta, larg, copias = IMAGENS.get(chave_ing, ("queijo", (230, 200, 160), 150, 1))
    caminho, prop = imagem(arq, tinta)
    rnd = random.Random(seed)
    if copias == 1:
        h = min(larg * prop, altura_max)
        w = h / prop
        c.drawImage(caminho, cx - w / 2, cy - h / 2, w, h, mask="auto")
        return
    h = min(larg * prop, altura_max * 0.8)
    w = h / prop
    faixa = 230
    for k in range(copias):
        x = cx - faixa / 2 + (k + 0.5) * faixa / copias + rnd.uniform(-6, 6)
        y = cy + rnd.uniform(-altura_max * .18, altura_max * .18)
        c.drawImage(caminho, x - w / 2, y - h / 2, w, h, mask="auto")


def pagina_pizza(c, p, num, forno):
    moldura(c)
    titulo(c, p["nome"], num)
    linhas = p["linhas"]                        # massa primeiro (ordem de montagem)
    n = len(linhas)

    base_y, topo_y = 132, PH - 142
    passo = min(78, (topo_y - base_y) / max(n - 1, 1))
    ys = [base_y + i * passo for i in range(n)]

    # ---- pizza em camadas (esquerda)
    cx = 205
    for i, l in enumerate(linhas):
        k = chave(l["nome"]) if l["classe"] != "massa" else "massa"
        k = {"muçarela": "mussarela", "cheddar": "cheddar cremoso", "catupiry original": "catupiry"}.get(k, k)
        if l["classe"] == "base":                     # molho / creme deitado em cima da massa
            desenha_camada(c, k, cx, ys[0] + 14, 52, i)
        elif l["classe"] == "massa":
            desenha_camada(c, k, cx, ys[0], 92, i)
        else:
            desenha_camada(c, k, cx, ys[i] + 6, passo * 1.9, int(p["id"]) + i)

    # ---- lista à direita (de cima para baixo = última camada primeiro)
    x0 = 398
    cols = [PW - BORDA - 168, PW - BORDA - 102, PW - BORDA - 36]
    hy = ys[-1] + min(passo / 2, 26) + 6
    for (_, t, d), x in zip(TAMANHOS, cols):
        c.setFillColor(VERMELHO)
        c.roundRect(x - 29, hy, 58, 30, 6, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Sans-B", 15)
        c.drawCentredString(x, hy + 14, t)
        c.setFont("Sans", 8)
        c.drawCentredString(x, hy + 4, d.split(" · ")[0])
    tam_nome = 17 if passo >= 36 else 15
    for i, l in reversed(list(enumerate(linhas))):
        y = ys[i]
        c.setStrokeColor(HexColor("#E6DCC3"))
        c.setLineWidth(.6)
        c.line(x0, y - min(passo / 2, 22) + 2, PW - BORDA - 8, y - min(passo / 2, 22) + 2)
        c.setFillColor(DOURADO if l["classe"] != "massa" else PRETO)
        c.circle(x0 + 11, y + 5, 10, stroke=0, fill=1)
        c.setFillColor(PRETO if l["classe"] != "massa" else white)
        c.setFont("Sans-B", 11)
        c.drawCentredString(x0 + 11, y + 1, str(i + 1))
        nome = "Massa da pizza" if l["classe"] == "massa" else l["nome"]
        c.setFillColor(PRETO)
        tn = tam_nome
        while c.stringWidth(nome, "Sans-B", tn) > cols[0] - 32 - x0 - 30:
            tn -= .5
        c.setFont("Sans-B", tn)
        c.drawString(x0 + 28, y, nome)
        if depois_do_forno(p, l):
            c.setFillColor(VERMELHO)
            c.setFont("Sans-B", 9)
            c.drawString(x0 + 28, y - 11, "DEPOIS DO FORNO")
        for (s, _, _), x in zip(TAMANHOS, cols):
            v = l["q"].get(s, "—")
            c.setFillColor(VERMELHO if v == "—" else PRETO)
            c.setFont("Sans-B", 16 if passo >= 36 else 14)
            c.drawCentredString(x, y, v)

    # ---- faixa de baixo: forno e observações
    fy, fh = BORDA + 12, 62
    lw = (PW - 2 * BORDA - 36) / 2
    obs = []
    if p["problemas"]:
        obs.append("Ficha a completar: " + "; ".join(p["problemas"]) + ".")
    obs.append("Meio a meio: metade da gramatura de cada sabor.")
    for k, (tit, cor, txt) in enumerate((("PONTO DE FORNO", VERMELHO, forno),
                                         ("OBSERVAÇÕES", DOURADO, " ".join(obs)))):
        x = BORDA + 12 + k * (lw + 12)
        c.setFillColor(cor)
        c.roundRect(x, fy, lw, fh, 6, stroke=0, fill=1)
        c.setFillColor(white)
        c.roundRect(x + 108, fy + 3, lw - 111, fh - 6, 4, stroke=0, fill=1)
        c.setFillColor(white if cor == VERMELHO else PRETO)
        c.setFont("Sans-B", 11)
        for j, ln in enumerate(quebra(c, tit, "Sans-B", 11, 96)):
            c.drawString(x + 9, fy + fh - 22 - j * 13, ln)
        c.setFillColor(PRETO)
        tam = 11.5
        lins = quebra(c, txt, "Sans", tam, lw - 128)
        while len(lins) * tam * 1.2 > fh - 10 and tam > 8:
            tam -= .5
            lins = quebra(c, txt, "Sans", tam, lw - 128)
        c.setFont("Sans", tam)
        y0 = fy + fh / 2 + (len(lins) * tam * 1.2) / 2 - tam
        for j, ln in enumerate(lins):
            c.drawString(x + 117, y0 - j * tam * 1.2, ln)


def capa(c, total):
    c.setFillColor(PRETO)
    c.rect(0, 0, PW, PH, stroke=0, fill=1)
    c.setFillColor(VERMELHO)
    c.rect(0, 0, PW * .46, PH, stroke=0, fill=1)
    c.setFillColor(DOURADO)
    c.rect(PW * .46, 0, 5, PH, stroke=0, fill=1)
    if LOGO.exists():
        c.setFillColor(white)
        c.circle(PW * .23, PH / 2, 135, stroke=0, fill=1)
        c.drawImage(str(LOGO), PW * .23 - 100, PH / 2 - 100, 200, 200, mask="auto", preserveAspectRatio=True)
    x = PW * .46 + 40
    c.setFillColor(white)
    c.setFont("Sans-B", 38)
    c.drawString(x, PH * .62, "MANUAL DE")
    c.drawString(x, PH * .62 - 46, "MONTAGEM")
    c.setFillColor(DOURADO)
    c.setFont("Sans-B", 26)
    c.drawString(x, PH * .62 - 92, "TILI PIZZARIA")
    c.setFillColor(white)
    c.setFont("Sans", 14)
    c.drawString(x, PH * .62 - 130, f"{total} pizzas · gramatura P, M e G")
    c.drawString(x, PH * .62 - 150, "Ordem de montagem de baixo para cima")
    c.setFont("Sans", 10)
    c.setFillColor(HexColor("#BBBBBB"))
    c.drawString(x, 40, "Gramaturas da ficha técnica do ALIV, arredondadas de 5 em 5 g.")


def pagina_regras(c):
    moldura(c)
    titulo(c, "Regras da praça")
    regras = [
        ("Balança sempre", "Pese todo recheio. A gramatura é a da ficha técnica — é o que o custo considera."),
        ("Tamanhos", "P = disco 25 cm (4 fatias) · M = 30 cm (6 fatias) · G = 35 cm (8 fatias)."),
        ("Como ler a página", "Monte de baixo para cima, na ordem dos números: 1 é a massa, o último é a finalização."),
        ("Borda limpa", "Molho e recheio até 1 dedo da borda. Borda suja queima e vaza na caixa."),
        ("Meio a meio", "Cada metade leva metade da gramatura do seu sabor. Massa e molho, normais."),
        ("Depois do forno", "O que estiver marcado em vermelho entra só quando a pizza sai do forno."),
        ("Embalagem", "Caixa do tamanho certo, mesinha no centro, sachês de ketchup e maionese."),
    ]
    y = PH - 125
    for i, (t, d) in enumerate(regras, 1):
        x = 60 if i <= 4 else PW / 2 + 15
        if i == 5:
            y = PH - 125
        c.setFillColor(VERMELHO)
        c.circle(x + 16, y - 6, 16, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Sans-B", 17)
        c.drawCentredString(x + 16, y - 12, str(i))
        c.setFillColor(PRETO)
        c.setFont("Sans-B", 17)
        c.drawString(x + 42, y - 4, t.upper())
        c.setFont("Sans", 13.5)
        lins = quebra(c, d, "Sans", 13.5, PW / 2 - 120)
        for j, ln in enumerate(lins):
            c.drawString(x + 42, y - 24 - j * 17, ln)
        y -= 50 + len(lins) * 17


def pagina_pendencias(c, pend):
    moldura(c)
    titulo(c, "Fichas a completar no ALIV")
    c.setFillColor(CINZA_ESC)
    c.setFont("Sans", 12)
    c.drawCentredString(PW / 2 - 20, PH - 108, f"{len(pend)} pizzas ativas sem ficha técnica ou com ficha incompleta")
    meio = (len(pend) + 1) // 2
    for col, grupo in enumerate((pend[:meio], pend[meio:])):
        x = 34 + col * (PW / 2 - 22)
        larg = PW / 2 - 46
        y = PH - 128
        for k, p in enumerate(grupo):
            txt = "; ".join(p["problemas"])
            lins = quebra(c, txt, "Sans", 10, larg - 200)
            h = max(30, len(lins) * 12 + 10, len(quebra(c, p["nome"], "Sans-B", 11.5, 186)) * 13 + 8)
            c.setFillColor(CINZA if k % 2 == 0 else white)
            c.rect(x, y - h, larg, h, stroke=0, fill=1)
            c.setFillColor(PRETO)
            nl = quebra(c, p["nome"], "Sans-B", 11.5, 186)
            c.setFont("Sans-B", 11.5)
            for j, ln in enumerate(nl):
                c.drawString(x + 5, y - h / 2 - 4 + (len(nl) - 1) * 6.5 - j * 13, ln)
            c.setFillColor(VERMELHO)
            c.setFont("Sans", 10)
            y0 = y - h / 2 + (len(lins) - 1) * 6 - 3.5
            for j, ln in enumerate(lins):
                c.drawString(x + 196, y0 - j * 12, ln)
            y -= h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=str(RAIZ / "manuais" / "Manual_de_Montagem_Tili_Pizzaria.pdf"))
    ap.add_argument("--paginas", type=int, default=0, help="só as N primeiras pizzas (prévia)")
    ap.add_argument("--so", help="só as pizzas com estes nomes (separados por vírgula)")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--forno", default="Forno a 320 °C · 2 min 20 s. "
                    "Pronta quando a borda estiver dourada e a cobertura derretida.")
    a = ap.parse_args()
    _, rec = carregar(a.cache)
    pizzas, pend = montar(rec)
    lista = pizzas
    if a.so:
        alvo = {sem_acento(x.strip()) for x in a.so.split(",")}
        lista = [p for p in pizzas if sem_acento(p["nome"]) in alvo]
    if a.paginas:
        lista = lista[: a.paginas]
    c = canvas.Canvas(a.saida, pagesize=landscape(A4))
    c.setTitle("Manual de Montagem — Tili Pizzaria")
    capa(c, len(pizzas))
    c.showPage()
    pagina_regras(c)
    c.showPage()
    for p in lista:
        pagina_pizza(c, p, pizzas.index(p) + 1, a.forno)
        c.showPage()
    if not (a.paginas or a.so):
        pagina_pendencias(c, pend)
        c.showPage()
    c.save()
    print(f"{a.saida}: {len(lista)} pizzas, {len(pend)} pendências")


if __name__ == "__main__":
    main()
