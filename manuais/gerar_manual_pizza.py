#!/usr/bin/env python3
"""Manual de Montagem — Tili Pizzaria (PDF A4, uma página por pizza).

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
from reportlab.lib.pagesizes import A4
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


def passos(p: dict) -> list[str]:
    """Ordem de montagem na praça, a partir da ficha."""
    por = {}
    for l in p["linhas"]:
        por.setdefault(l["classe"], []).append(l["nome"])
    out = []
    if p["doce"]:
        out.append("Abra o disco na pá e espalhe o creme de leite até 1 dedo da borda.")
        if "queijo" in por:
            out.append("Distribua a " + ", ".join(por["queijo"]).lower() + " por toda a pizza.")
        out.append("Leve ao forno até a massa dourar.")
        cob = [n for n in por.get("cremoso", [])]
        if cob:
            out.append("Ao sair do forno, cubra com " + " e ".join(n.lower() for n in cob) + " sem deixar falhas.")
        out.append("Corte, confira a borda limpa e feche a caixa.")
        return out
    out.append("Abra o disco na pá e espalhe o molho em espiral, deixando 1 dedo de borda.")
    if "queijo" in por:
        out.append("Cubra com " + " e ".join(n.lower() for n in por["queijo"]) + " de ponta a ponta.")
    rech = por.get("proteina", []) + por.get("vegetal", [])
    if rech:
        out.append("Distribua por igual: " + ", ".join(n.lower() for n in rech) + ".")
    if "cremoso" in por:
        out.append("Finalize com " + " e ".join(por["cremoso"]) + " em espiral, do centro para fora.")
    fin = por.get("final", [])
    if fin:
        out.append("Salpique " + ", ".join(n.lower() for n in fin) + ".")
    out.append("Forno. Na saída" + (f", coloque {', '.join(n.lower() for n in por['pos'])}," if "pos" in por else "")
               + " corte e feche a caixa.")
    return out


# ---------------------------------------------------------------- desenho
W, H = A4
M = 15 * mm


def quebra(c, txt, fonte, tam, larg):
    palavras, linhas, atual = txt.split(), [], ""
    for w in palavras:
        t = (atual + " " + w).strip()
        if c.stringWidth(t, fonte, tam) <= larg:
            atual = t
        else:
            linhas.append(atual)
            atual = w
    if atual:
        linhas.append(atual)
    return linhas


def topo(c, titulo, sub=None, num=None):
    c.setFillColor(VERMELHO)
    c.rect(0, H - 42 * mm, W, 42 * mm, stroke=0, fill=1)
    c.setFillColor(DOURADO)
    c.rect(0, H - 44.5 * mm, W, 2.5 * mm, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Sans", 10)
    c.drawString(M, H - 11 * mm, "MANUAL DE MONTAGEM — TILI PIZZARIA")
    tam = 34
    while c.stringWidth(titulo.upper(), "Sans-B", tam) > W - 2 * M - 30 * mm and tam > 20:
        tam -= 1
    c.setFont("Sans-B", tam)
    c.drawString(M, H - 28 * mm, titulo.upper())
    if sub:
        c.setFont("Sans", 11)
        c.drawString(M, H - 37 * mm, sub)
    if num is not None:
        c.setFillColor(DOURADO)
        c.circle(W - M - 11 * mm, H - 22 * mm, 11 * mm, stroke=0, fill=1)
        c.setFillColor(PRETO)
        c.setFont("Sans-B", 20)
        c.drawCentredString(W - M - 11 * mm, H - 25 * mm, f"{num:02d}")


def rodape(c, pag):
    c.setStrokeColor(DOURADO)
    c.setLineWidth(1)
    c.line(M, 12 * mm, W - M, 12 * mm)
    c.setFillColor(CINZA_ESC)
    c.setFont("Sans", 8.5)
    c.drawString(M, 7.5 * mm, "Fonte: ficha técnica do ALIV (loja 150). Gramaturas arredondadas de 5 em 5 g.")
    c.drawRightString(W - M, 7.5 * mm, f"pág. {pag}")


def secao(c, y, titulo):
    c.setFillColor(PRETO)
    c.rect(M, y - 8.5 * mm, 3 * mm, 8.5 * mm, stroke=0, fill=1)
    c.setFont("Sans-B", 15)
    c.drawString(M + 5.5 * mm, y - 6.5 * mm, titulo.upper())
    return y - 11 * mm


CORES_TOP = {
    "proteina": HexColor("#A8322D"), "vegetal": HexColor("#3E8E41"), "cremoso": HexColor("#F2E8C9"),
    "final": HexColor("#2F4F2F"), "queijo": HexColor("#F7D774"), "pos": HexColor("#2E7D32"),
}


def ilustracao(c, cx, cy, r, p, seed):
    """Pizza vista de cima, com os recheios da ficha."""
    import random
    rnd = random.Random(seed)
    c.setFillColor(HexColor("#E2B169"))
    c.circle(cx, cy, r, stroke=0, fill=1)
    base = HexColor("#5A2E1B") if p["doce"] else HexColor("#C0392B")
    c.setFillColor(base)
    c.circle(cx, cy, r * 0.86, stroke=0, fill=1)
    classes = [l["classe"] for l in p["linhas"]]
    if "queijo" in classes:
        c.setFillColor(HexColor("#F7D774"))
        for _ in range(26):
            a, d = rnd.uniform(0, 2 * math.pi), rnd.uniform(0, r * 0.7)
            c.circle(cx + d * math.cos(a), cy + d * math.sin(a), r * rnd.uniform(.12, .2), stroke=0, fill=1)
    for l in p["linhas"]:
        cl = l["classe"]
        if cl in ("massa", "base", "queijo"):
            continue
        n = l["nome"].lower()
        cor = CORES_TOP.get(cl, PRETO)
        if "azeitona" in n:
            cor, qt, tam = HexColor("#556B2F"), 7, .05
        elif "orégano" in n:
            cor, qt, tam = HexColor("#4B6B2A"), 40, .012
        elif "catupiry" in n or "cream" in n:
            cor, qt, tam = HexColor("#FFF8E7"), 10, .07
        elif "cheddar" in n:
            cor, qt, tam = HexColor("#F39C12"), 10, .07
        elif "chocolate" in n or "nutella" in n:
            cor, qt, tam = HexColor("#3B1F12"), 30, .1
        elif "milho" in n or "ovo" in n:
            cor, qt, tam = HexColor("#F4D03F"), 14, .035
        elif "cebola" in n:
            cor, qt, tam = HexColor("#E8DAEF"), 10, .045
        elif "pimentão" in n:
            cor, qt, tam = HexColor("#D35400"), 9, .04
        elif "ervilha" in n or "manjericão" in n:
            cor, qt, tam = HexColor("#27AE60"), 12, .035
        elif "tomate" in n:
            cor, qt, tam = HexColor("#E74C3C"), 8, .075
        elif "parmes" in n:
            cor, qt, tam = HexColor("#FDF2CC"), 25, .018
        elif "pimenta" in n:
            cor, qt, tam = HexColor("#922B21"), 25, .012
        else:
            qt, tam = 10, .08
        c.setFillColor(cor)
        c.setStrokeColor(HexColor("#00000033"))
        for _ in range(qt):
            a, d = rnd.uniform(0, 2 * math.pi), rnd.uniform(0, r * 0.72)
            c.circle(cx + d * math.cos(a), cy + d * math.sin(a), r * tam, stroke=0, fill=1)
    c.setStrokeColor(HexColor("#FFFFFF"))
    c.setLineWidth(1.2)
    for k in range(4):
        a = k * math.pi / 4
        c.line(cx - r * .86 * math.cos(a), cy - r * .86 * math.sin(a), cx + r * .86 * math.cos(a), cy + r * .86 * math.sin(a))


def pagina_pizza(c, p, num, pag, forno):
    topo(c, p["nome"], "Ficha técnica oficial · P 25 cm · M 30 cm · G 35 cm", num)
    y = H - 52 * mm

    # ilustração + descrição
    ilustracao(c, W - M - 17 * mm, y - 16 * mm, 16 * mm, p, int(p["id"]))
    c.setFillColor(CINZA_ESC)
    c.setFont("Sans", 11)
    yy = y - 2 * mm
    for ln in quebra(c, "Como está no cardápio: " + p["desc"], "Sans", 11, W - 2 * M - 50 * mm)[:6]:
        yy -= 5 * mm
        c.drawString(M, yy, ln)
    y = min(yy - 4 * mm, y - 30 * mm)
    lista_passos = passos(p)
    fundo = 12 * mm + 32 * mm + 3 * mm          # rodapé + caixas forno/obs + folga
    for fp in (14, 13, 12, 11):
        ep = fp * 0.443 * mm                      # entrelinha dos passos
        h_passos = sum(max(10 * mm, len(quebra(c, t, "Sans", fp, W - 2 * M - 14 * mm)) * ep + 4.5 * mm)
                       for t in lista_passos)
        livre = y - fundo - h_passos - 40 * mm
        lh = max(6.6 * mm, min(10.5 * mm, livre / len(p["linhas"])))
        if livre / len(p["linhas"]) >= 6.6 * mm:
            break

    # tabela de gramaturas
    y = secao(c, y, "Ingredientes e gramatura")
    larg = W - 2 * M
    colw = 30 * mm
    col0 = larg - 3 * colw
    hh = 11 * mm
    c.setFillColor(PRETO)
    c.rect(M, y - hh, larg, hh, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Sans-B", 14)
    c.drawString(M + 3 * mm, y - 7.5 * mm, "INGREDIENTE")
    for i, (_, t, _) in enumerate(TAMANHOS):
        c.setFillColor(DOURADO)
        c.drawCentredString(M + col0 + colw * (i + .5), y - 7.5 * mm, t)
    y -= hh
    for k, l in enumerate(p["linhas"]):
        c.setFillColor(CINZA if k % 2 == 0 else white)
        c.rect(M, y - lh, larg, lh, stroke=0, fill=1)
        c.setFillColor(PRETO)
        tn = 15
        while c.stringWidth(l["nome"], "Sans-B", tn) > col0 - 6 * mm:
            tn -= .5
        c.setFont("Sans-B", tn)
        c.drawString(M + 3 * mm, y - lh / 2 - 1.8 * mm, l["nome"])
        c.setFont("Sans-B", 16)
        for i, (s, _, _) in enumerate(TAMANHOS):
            v = l["q"].get(s, "—")
            c.setFillColor(VERMELHO if v == "—" else PRETO)
            c.drawCentredString(M + col0 + colw * (i + .5), y - lh / 2 - 2 * mm, v)
        y -= lh
    c.setStrokeColor(DOURADO)
    c.setLineWidth(1.5)
    c.line(M, y, M + larg, y)
    y -= 7 * mm

    # ordem de montagem
    y = secao(c, y, "Ordem de montagem na praça")
    for i, t in enumerate(lista_passos, 1):
        lins = quebra(c, t, "Sans", fp, W - 2 * M - 14 * mm)
        c.setFillColor(VERMELHO)
        c.circle(M + 4.5 * mm, y - 4 * mm, 4.5 * mm, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Sans-B", 13)
        c.drawCentredString(M + 4.5 * mm, y - 5.6 * mm, str(i))
        c.setFillColor(PRETO)
        c.setFont("Sans", fp)
        for j, ln in enumerate(lins):
            c.drawString(M + 12 * mm, y - 5.4 * mm - j * ep, ln)
        y -= max(10 * mm, len(lins) * ep + 4.5 * mm)
    if y < 12 * mm + 2 * mm + 32 * mm:
        print(f"AVISO: página de {p['nome']} apertada (sobra {(y / mm) - 48:.0f} mm)", file=sys.stderr)
    y = 12 * mm + 2 * mm + 32 * mm

    # forno + observações (lado a lado)
    caixa_h = 32 * mm
    lw = (W - 2 * M - 6 * mm) / 2
    for i, (tit, cor) in enumerate((("PONTO DE FORNO", VERMELHO), ("OBSERVAÇÕES", DOURADO))):
        x = M + i * (lw + 6 * mm)
        c.setFillColor(cor)
        c.roundRect(x, y - caixa_h, lw, caixa_h, 3 * mm, stroke=0, fill=1)
        c.setFillColor(white)
        c.roundRect(x + 1.2 * mm, y - caixa_h + 1.2 * mm, lw - 2.4 * mm, caixa_h - 9 * mm, 2 * mm, stroke=0, fill=1)
        c.setFillColor(white if cor == VERMELHO else PRETO)
        c.setFont("Sans-B", 13)
        c.drawString(x + 4 * mm, y - 6 * mm, tit)
        c.setFillColor(PRETO)
        if i == 0:
            txt = forno
        else:
            obs = []
            if p["problemas"]:
                obs.append("Ficha a completar: " + "; ".join(p["problemas"]) + ".")
            obs.append("Pizza meio a meio: use metade da gramatura de cada sabor.")
            txt = " ".join(obs)
        tam = 12.5
        lins = quebra(c, txt, "Sans", tam, lw - 9 * mm)
        while len(lins) * tam * 0.45 * mm > caixa_h - 13 * mm and tam > 9:
            tam -= .5
            lins = quebra(c, txt, "Sans", tam, lw - 9 * mm)
        c.setFont("Sans", tam)
        for j, ln in enumerate(lins):
            c.drawString(x + 4.5 * mm, y - 14.5 * mm - j * tam * 0.45 * mm, ln)
    rodape(c, pag)


def capa(c, total):
    c.setFillColor(PRETO)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(VERMELHO)
    c.rect(0, H * .62, W, H * .38, stroke=0, fill=1)
    c.setFillColor(DOURADO)
    c.rect(0, H * .62 - 3 * mm, W, 3 * mm, stroke=0, fill=1)
    if LOGO.exists():
        c.setFillColor(white)
        c.circle(W / 2, H * .62, 52 * mm, stroke=0, fill=1)
        c.drawImage(str(LOGO), W / 2 - 34 * mm, H * .62 - 34 * mm, 68 * mm, 68 * mm, mask="auto",
                    preserveAspectRatio=True)
    c.setFillColor(white)
    c.setFont("Sans-B", 40)
    c.drawCentredString(W / 2, H * .33, "MANUAL DE MONTAGEM")
    c.setFillColor(DOURADO)
    c.setFont("Sans-B", 26)
    c.drawCentredString(W / 2, H * .33 - 14 * mm, "TILI PIZZARIA")
    c.setFillColor(white)
    c.setFont("Sans", 14)
    c.drawCentredString(W / 2, H * .33 - 30 * mm, f"{total} pizzas · gramatura P, M e G · ordem de montagem")
    c.drawCentredString(W / 2, H * .33 - 38 * mm, "Dados da ficha técnica do ALIV")


def pagina_regras(c, pag):
    topo(c, "Regras da praça", "Leia antes de começar o turno")
    y = H - 56 * mm
    regras = [
        ("Balança sempre", "Pese todo recheio. A gramatura deste manual é a da ficha técnica — é o que o custo considera."),
        ("Tamanhos", "P = disco 25 cm (4 fatias) · M = disco 30 cm (6 fatias) · G = disco 35 cm (8 fatias)."),
        ("Borda limpa", "Molho e recheio até 1 dedo da borda. Borda suja queima e vaza na caixa."),
        ("Ordem padrão", "Disco → molho → muçarela → recheios → cremosos → parmesão, orégano e azeitona → forno."),
        ("Meio a meio", "Cada metade leva metade da gramatura do seu sabor. Muçarela e molho, normais."),
        ("Doces", "Base de creme de leite. Chocolate e Nutella entram depois do forno, sobre a massa quente."),
        ("Embalagem", "Caixa do tamanho certo, mesinha no centro, sachês de ketchup e maionese."),
    ]
    for i, (t, d) in enumerate(regras, 1):
        c.setFillColor(VERMELHO)
        c.circle(M + 7 * mm, y - 6 * mm, 7 * mm, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Sans-B", 17)
        c.drawCentredString(M + 7 * mm, y - 8.2 * mm, str(i))
        c.setFillColor(PRETO)
        c.setFont("Sans-B", 17)
        c.drawString(M + 18 * mm, y - 4.5 * mm, t.upper())
        c.setFont("Sans", 14)
        lins = quebra(c, d, "Sans", 14, W - 2 * M - 20 * mm)
        for j, ln in enumerate(lins):
            c.drawString(M + 18 * mm, y - 11.5 * mm - j * 6.3 * mm, ln)
        y -= 16 * mm + len(lins) * 6.3 * mm
    rodape(c, pag)


def pagina_pendencias(c, pend, pag):
    topo(c, "Fichas a completar", f"{len(pend)} pizzas ativas sem ficha ou com ficha incompleta no ALIV")
    y = H - 54 * mm
    for k, p in enumerate(pend):
        txt = "; ".join(p["problemas"])
        lins = quebra(c, txt, "Sans", 11.5, W - 2 * M - 100 * mm)
        h = max(9 * mm, len(lins) * 5.2 * mm + 3.5 * mm)
        if y - h < 18 * mm:
            rodape(c, pag)
            c.showPage()
            pag += 1
            topo(c, "Fichas a completar", "continuação")
            y = H - 54 * mm
        c.setFillColor(CINZA if k % 2 == 0 else white)
        c.rect(M, y - h, W - 2 * M, h, stroke=0, fill=1)
        c.setFillColor(PRETO)
        tn = 13
        while c.stringWidth(p["nome"], "Sans-B", tn) > 92 * mm:
            tn -= .5
        c.setFont("Sans-B", tn)
        c.drawString(M + 3 * mm, y - 6.2 * mm, p["nome"])
        c.setFillColor(VERMELHO)
        c.setFont("Sans", 11.5)
        for j, ln in enumerate(lins):
            c.drawString(M + 98 * mm, y - 6 * mm - j * 5.2 * mm, ln)
        y -= h
    rodape(c, pag)
    return pag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=str(RAIZ / "manuais" / "Manual_de_Montagem_Tili_Pizzaria.pdf"))
    ap.add_argument("--paginas", type=int, default=0, help="só as N primeiras pizzas (prévia)")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--forno", default="Forno: ____ °C  ·  Tempo: ____ min. "
                    "Ponto: borda dourada, fundo firme e queijo borbulhando.")
    a = ap.parse_args()
    _, rec = carregar(a.cache)
    pizzas, pend = montar(rec)
    lista = pizzas[: a.paginas] if a.paginas else pizzas
    c = canvas.Canvas(a.saida, pagesize=A4)
    c.setTitle("Manual de Montagem — Tili Pizzaria")
    capa(c, len(pizzas))
    c.showPage()
    pag = 2
    pagina_regras(c, pag)
    c.showPage()
    for i, p in enumerate(lista, 1):
        pag += 1
        pagina_pizza(c, p, i, pag, a.forno)
        c.showPage()
    if not a.paginas:
        pag = pagina_pendencias(c, pend, pag + 1)
        c.showPage()
    c.save()
    print(f"{a.saida}: {len(lista)} pizzas, {len(pend)} pendências")
    for p in pend:
        print(" -", p["nome"], "→", "; ".join(p["problemas"]))


if __name__ == "__main__":
    main()
