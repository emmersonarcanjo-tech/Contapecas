"""Manual de Montagem — Tili Burguer (PDF A4).

Lê dados já baixados do ALIV (só leitura) e monta o PDF:
  python3 gerar_manual_burguer.py <pasta_dados> <saida.pdf> [--paginas N]

<pasta_dados> precisa ter:
  full_data.json  -> GET /admin/api/menu/full_data (loja 150)
  recipes.json    -> {product_id: GET /admin/menu/product/{id}/recipes}

Ponto da carne, tostagem e tempos NÃO existem no ALIV: usam o padrão da casa
definido em PADRAO abaixo (conferir com o Emerson).
"""
import json
import sys
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

VERMELHO, DOURADO, PRETO = HexColor("#C8102E"), HexColor("#D4A017"), HexColor("#1A1A1A")
CINZA, CREME = HexColor("#5A5A5A"), HexColor("#FBF6EA")
W, H = A4
M = 28
LOGO = Path(__file__).resolve().parent.parent / "monitor" / "assets" / "logo_tili.png"
CATEGORIAS = {799: "ARTESANAL", 2429: "TRADICIONAL"}

FD = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("R", FD + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("B", FD + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("C", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"))

# Padrão da casa (não vem do ALIV) — ajustar aqui se o Emerson mudar.
PADRAO = {
    "blend": "Blend: BEM PASSADO e suculento, 3–4 min cada lado. Não amassar.",
    "picanha": "Hambúrguer: direto do freezer, 2–3 min cada lado, BEM PASSADO.",
    "carne_sol": "Carne de sol: dourar com a cebola, 2–3 min.",
    "frango": "Frango: BEM PASSADO, sem parte rosada, 3–4 min cada lado.",
    "file": "Filé bovino: ao ponto para bem, 2–3 min cada lado.",
    "pao": "Abrir, miolo para baixo na chapa: 30 a 40 s até DOURADO CLARO. "
           "Brioche queima rápido — não deixar escurecer.",
}


# ------------------------------------------------------------------ dados
def ingrediente(i: dict, lanches: int = 1) -> dict:
    """Converte a linha da ficha do ALIV em texto de praça + tipo de camada."""
    n, q, u, raw = i["ingredient_name"], float(i["quantity"]), i["ingredient_unit"], i["ingredient_raw_name"]
    g = lambda v: f"{round(v):g} g"
    alerta = None
    if n == "Pão brioche":
        return dict(nome="Pão brioche", qtd=f"{q:g} un", tipo="pao")
    if n == "Carne de hambúrguer":
        k = round(q / 0.12)
        return dict(nome="Blend bovino", qtd=f"{k} × 120 g" if k > 1 else "120 g", tipo="blend", n=k)
    if n == "Carne sabor picanha 90g":
        k = round(q / 0.09)
        return dict(nome="Hambúrguer sabor picanha", qtd=f"{k} × 90 g" if k > 1 else "90 g", tipo="picanha", n=k)
    if n == "Cheddar fatiado":                       # pacote 2,27 kg / 160 fatias
        f = q * 160
        k = max(1, round(f))
        return dict(nome="Cheddar fatiado", qtd=f"{k} fatia{'s' if k > 1 else ''}", tipo="cheddar")
    if n == "Maionese":                              # doypack 1 kg
        return dict(nome="Molho da casa", qtd=g(q * 1000), tipo="molho")
    if n == "Cream cheese":                          # bisnaga 1,5 kg
        return dict(nome="Cream cheese", qtd=g(q * 1500), tipo="cremoso")
    if n.startswith("Sachê"):                        # caixa 168 sachês
        return dict(nome=n.replace("Sachê de", "sachês"), qtd=f"{round(q * 168)}", tipo="emb")
    if n == "Embalagem do lanche":                   # 30x38 c/400
        return dict(nome="papel acoplado 30×38", qtd=f"{round(q * 400)} folha(s)", tipo="emb")
    if n.startswith("Papel acoplado"):               # 40x40 c/400
        return dict(nome="papel acoplado 40×40", qtd=f"{round(q * 400)} folha(s)", tipo="emb")
    if n == "Guardanapo sachê":
        return dict(nome="guardanapo sachê", qtd="1", tipo="emb",
                    alerta=f"Guardanapo: ficha diz {q:g} CAIXA por lanche (deve ser 1 un).")
    if n == "Alface":
        return dict(nome="Alface", qtd="1 folha", tipo="alface")
    if n == "Ovo":
        return dict(nome="Ovo", qtd="1 un", tipo="ovo")
    tipos = {"Queijo coalho": "coalho", "Mussarela": "mussarela", "Banana da terra": "banana",
             "Frango": "frango", "Cebola": "cebola", "Calabresa": "calabresa", "Bacon": "bacon",
             "Carne de sol": "carne_sol", "Catupiry": "cremoso", "Tomate": "tomate", "Presunto": "presunto"}
    nomes = {"Frango": "Filé de frango", "Catupiry": "Catupiry original", "Mussarela": "Muçarela"}
    gramas = q * 1000 if u == "KG" else q
    if n == "Mussarela" and gramas < 10:
        alerta = f"Muçarela: ficha diz só {gramas:g} g — provável erro de digitação."
    return dict(nome=nomes.get(n, n), qtd=g(gramas), tipo=tipos.get(n, "outro"), alerta=alerta)


# Lanches sem ficha: ingredientes do cardápio, sem gramatura.
SEM_FICHA = {
    10415: [("Pão brioche", "pao"), ("Filé bovino", "file"), ("Cheddar fatiado", "cheddar"),
            ("Picles", "picles"), ("Alface", "alface"), ("Tomate", "tomate")],
    10413: [("Pão brioche", "pao"), ("Filé bovino acebolado", "file"), ("Cebola", "cebola"),
            ("Abacaxi grelhado", "abacaxi"), ("Queijo coalho", "coalho")],
    10411: [("Pão brioche", "pao"), ("Blend de picanha", "picanha"), ("Abacaxi grelhado", "abacaxi"),
            ("Queijo coalho", "coalho")],
    10412: [("Pão brioche", "pao"), ("Blend de picanha", "picanha"), ("Abacaxi grelhado", "abacaxi"),
            ("Cheddar fatiado", "cheddar"), ("Bacon", "bacon")],
    10405: [("Pão brioche", "pao"), ("Blend de picanha", "picanha"), ("Picles", "picles"),
            ("Cheddar fatiado", "cheddar")],
    10414: [("Pão brioche", "pao"), ("Blend de picanha", "picanha"), ("Abacaxi grelhado", "abacaxi"),
            ("Cheddar fatiado", "cheddar")],
}

# Divergências cardápio × ficha conferidas em 08/11/2026.
DIVERGENCIAS = {
    10402: ["Cardápio cita BACON, mas a ficha não tem bacon.",
            "Cardápio diz 'coalho ao mel', mas a ficha não tem mel."],
    10403: ["Cardápio diz QUEIJO CHEDDAR, mas a ficha usa QUEIJO COALHO 70 g."],
    10399: ["Cardápio diz 'coalho ao mel', mas a ficha não tem mel."],
    10401: ["Cardápio diz 'coalho ao mel', mas a ficha não tem mel."],
    10404: ["Cardápio diz 'coalho ao mel', mas a ficha não tem mel."],
    10397: ["Cardápio cita MOLHO DA CASA, mas a ficha não tem molho."],
}


def carregar(pasta: Path) -> list[dict]:
    d = json.loads((pasta / "full_data.json").read_text())
    rec = json.loads((pasta / "recipes.json").read_text())
    lanches = []
    for c in d["categories"]:
        if c["id"] not in CATEGORIAS:
            continue
        for p in c["products"]:
            if not p["is_active"]:
                continue
            fd = p["full_data"]
            nome = p["name"].replace("(Tili) ", "")
            qtd_lanches = 2 if nome.startswith("Clube 2") else 1
            ficha = rec.get(str(p["id"])) or []
            ings = [ingrediente(i, qtd_lanches) for i in ficha]
            alertas = [a for a in (i.get("alerta") for i in ings) if a]
            alertas += DIVERGENCIAS.get(p["id"], [])
            if not ficha:
                ings = [dict(nome=n, qtd="—", tipo=t) for n, t in SEM_FICHA.get(p["id"], [])]
            lanches.append(dict(id=p["id"], nome=nome, cat=CATEGORIAS[c["id"]],
                                desc=fd.get("description") or "", ings=ings,
                                sem_ficha=not ficha, alertas=alertas, lanches=qtd_lanches))
    return lanches


# ------------------------------------------------------------------ montagem
ORDEM = ["alface", "tomate", "carne", "queijo", "cremoso", "presunto", "calabresa", "frango_extra",
         "bacon", "banana", "abacaxi", "cebola", "ovo", "picles"]
CARNES = ("blend", "picanha", "carne_sol", "frango", "file")
QUEIJOS = ("cheddar", "mussarela", "coalho")


def camadas(L: dict) -> list[tuple[str, str]]:
    """(tipo, rótulo) de baixo para cima."""
    t = {i["tipo"]: i for i in L["ings"]}
    out = [("pao_base", "Pão (base)" + (" + molho" if "molho" in t else ""))]
    for k in ("alface", "tomate"):
        if k in t:
            out.append((k, t[k]["nome"]))
    carne = next((k for k in CARNES if k in t), None)
    # frango principal só quando não há outra carne
    if carne == "frango" and any(k in t for k in ("blend", "picanha", "carne_sol", "file")):
        carne = next(k for k in ("blend", "picanha", "carne_sol", "file") if k in t)
    queijo = next((k for k in QUEIJOS if k in t), None)
    n = t[carne].get("n", 1) if carne else 1
    for _ in range(n):
        if carne:
            out.append(("carne", t[carne]["nome"].replace(" 120 g", "")))
        if queijo:
            out.append(("queijo_" + queijo, t[queijo]["nome"]))
    if carne != "frango" and "frango" in t:
        out.append(("frango", "Filé de frango"))
    for k in ("cremoso", "presunto", "calabresa", "bacon", "banana", "abacaxi", "cebola", "ovo", "picles"):
        if k in t:
            out.append((k, t[k]["nome"]))
    out.append(("pao_topo", "Pão (tampa)" + (" + molho" if "molho" in t else "")))
    return out


def passos(L: dict) -> list[str]:
    t = {i["tipo"]: i for i in L["ings"]}
    q = lambda k: f" {t[k]['qtd']}" if t[k]["qtd"] != "—" else ""
    s = ["Chapa bem quente. Tostar o pão (ver TOSTAGEM)."]
    carnes = [k for k in CARNES if k in t]
    for k in carnes:
        nome = {"blend": "o(s) blend(s)", "picanha": "o(s) hambúrguer(es)", "carne_sol": "a carne de sol",
                "frango": "o filé de frango", "file": "o filé bovino"}[k]
        extra = " com a cebola" if k in ("carne_sol", "file") and "cebola" in t else ""
        s.append(f"Colocar {nome}{q(k)}{extra} na chapa (ver PONTO).")
    quentes = []
    for k, txt in (("bacon", "bacon até ficar crocante"), ("calabresa", "calabresa até dourar"),
                   ("banana", "banana até caramelizar dos dois lados"),
                   ("abacaxi", "abacaxi até marcar dos dois lados"), ("presunto", "presunto só para aquecer"),
                   ("ovo", "ovo com a gema firme")):
        if k in t:
            quentes.append(txt)
    if "cebola" in t and not any(k in t for k in ("carne_sol", "file")):
        quentes.append("cebola até caramelizar")
    if quentes:
        s.append("Ao mesmo tempo, na chapa: " + "; ".join(quentes) + ".")
    if "coalho" in t:
        s.append(f"Queijo coalho{q('coalho')}: dourar na chapa dos dois lados.")
    for k in ("cheddar", "mussarela"):
        if k in t:
            s.append(f"Depois de virar a carne: {t[k]['nome'].lower()}{q(k)} por cima e abafar até derreter.")
    if "cremoso" in t:
        s.append(f"{t['cremoso']['nome']}{q('cremoso')}: espalhar por cima, sem ir à chapa.")
    s.append("Montar na ORDEM DAS CAMADAS e fechar com a tampa.")
    return s


def embalagem(L: dict) -> str:
    emb = [i for i in L["ings"] if i["tipo"] == "emb"]
    if not emb:
        return "Papel acoplado + 2 sachês de ketchup + 2 de maionese (padrão — sem ficha)."
    return "Embrulhar bem fechado: " + " · ".join(f"{i['qtd']} {i['nome']}" for i in emb) + "."


def ponto(L: dict) -> str:
    t = {i["tipo"] for i in L["ings"]}
    linhas = [PADRAO[k] for k in CARNES if k in t]
    return "  ".join(linhas[:2]) or "—"


# ------------------------------------------------------------------ desenho
def wrap(c, texto, fonte, tam, larg):
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if c.stringWidth(teste, fonte, tam) <= larg:
            atual = teste
        else:
            linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


def texto(c, x, y, txt, fonte, tam, larg, cor=PRETO, entre=1.25):
    c.setFillColor(cor)
    c.setFont(fonte, tam)
    for linha in wrap(c, txt, fonte, tam, larg):
        c.drawString(x, y, linha)
        y -= tam * entre
    return y


CORES = {
    "pao_base": "#D9A055", "pao_topo": "#D9A055", "alface": "#5DAA3C", "tomate": "#D8352A",
    "carne": "#5B3220", "queijo_cheddar": "#F2A20C", "queijo_mussarela": "#F6E7B0",
    "queijo_coalho": "#E9C27A", "cremoso": "#FFFFFF", "presunto": "#F2A6A6", "calabresa": "#A8281E",
    "frango": "#E8C08A", "bacon": "#B4473A", "banana": "#F0C93C", "abacaxi": "#F7D44C",
    "cebola": "#9B5A8C", "ovo": "#FFF6D6", "picles": "#7A9A2E",
}
ALTURA = {"pao_base": 22, "pao_topo": 46, "carne": 24, "alface": 12, "tomate": 10}


def _alturas(camadas_):
    return [ALTURA.get(k.split("_")[0] if k.startswith("queijo") else k, 11) for k, _ in camadas_]


def altura_pilha(camadas_):
    a = _alturas(camadas_)
    return max(sum(a) + 3 * len(a) + 10, 19 * len(a))


def ilustracao(c, x, y, larg, camadas_):
    """Pilha de camadas de baixo (y) para cima, com rótulos à direita. Retorna o topo."""
    cx, w = x + 58, 104
    yy = y
    alturas = [ALTURA.get(k.split("_")[0] if k.startswith("queijo") else k, 11) for k, _ in camadas_]
    total = sum(alturas) + 3 * len(camadas_)
    passo_rot = max(19, total / len(camadas_))
    rot_y = y + 4
    for (k, rotulo), h in zip(camadas_, alturas):
        cor = HexColor(CORES.get(k, "#CCCCCC"))
        c.setFillColor(cor)
        c.setStrokeColor(PRETO)
        c.setLineWidth(1.2)
        if k == "pao_topo":
            p = c.beginPath()
            p.moveTo(cx - w / 2, yy)
            p.curveTo(cx - w / 2, yy + h * 1.3, cx + w / 2, yy + h * 1.3, cx + w / 2, yy)
            p.close()
            c.drawPath(p, fill=1, stroke=1)
            c.setFillColor(HexColor("#FFF3D6"))
            for dx, dy in ((-24, 22), (-6, 30), (14, 26), (30, 16), (-36, 12)):
                c.ellipse(cx + dx - 3, yy + dy - 1.5, cx + dx + 3, yy + dy + 1.5, fill=1, stroke=0)
            mid = yy + h * 0.45
        elif k == "alface":
            p = c.beginPath()
            p.moveTo(cx - w / 2 - 8, yy + 4)
            for i in range(9):
                xx = cx - w / 2 - 8 + (i + 1) * (w + 16) / 9
                p.curveTo(xx - 10, yy + h + 4, xx - 4, yy - 3, xx, yy + 4)
            p.lineTo(cx + w / 2 + 8, yy)
            p.lineTo(cx - w / 2 - 8, yy)
            p.close()
            c.drawPath(p, fill=1, stroke=1)
            mid = yy + h / 2
        elif k.startswith("queijo") or k == "cremoso":
            c.roundRect(cx - w / 2 - 4, yy, w + 8, h, 3, fill=1, stroke=1)
            if k in ("queijo_cheddar", "queijo_mussarela", "cremoso"):
                for dx in (-32, 8, 36):
                    c.roundRect(cx + dx, yy - 7, 9, 10, 4, fill=1, stroke=0)
            mid = yy + h / 2
        else:
            r = 9 if k in ("carne", "pao_base") else 4
            c.roundRect(cx - w / 2 - (4 if k == "carne" else 0), yy, w + (8 if k == "carne" else 0), h, r,
                        fill=1, stroke=1)
            mid = yy + h / 2
        # rótulo
        c.setStrokeColor(CINZA)
        c.setLineWidth(0.8)
        c.line(cx + w / 2 + 10, mid, x + 128, rot_y + 4)
        c.setFillColor(PRETO)
        c.setFont("B", 11.5)
        c.drawString(x + 131, rot_y, rotulo)
        rot_y += passo_rot
        yy += h + 3
    return max(yy, rot_y)


def cabecalho(c, L, pag):
    c.setFillColor(VERMELHO)
    c.rect(0, H - 118, W, 118, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.rect(0, H - 124, W, 6, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.setFont("B", 13)
    c.drawString(M, H - 34, "TILI BURGUER  ·  MANUAL DE MONTAGEM")
    nome = L["nome"].upper()
    tam = 40
    while c.stringWidth(nome, "C", tam) > W - 2 * M - 150 and tam > 22:
        tam -= 1
    c.setFillColor(white)
    c.setFont("C", tam)
    c.drawString(M, H - 84, nome)
    d = wrap(c, L["desc"], "R", 11.5, W - 2 * M)
    c.setFont("R", 11.5)
    c.drawString(M, H - 104, d[0] + (" …" if len(d) > 1 else ""))
    # selo categoria
    c.setFillColor(DOURADO)
    c.roundRect(W - M - 130, H - 76, 130, 30, 15, fill=1, stroke=0)
    c.setFillColor(PRETO)
    c.setFont("B", 14)
    c.drawCentredString(W - M - 65, H - 66, L["cat"])


def rodape(c, txt, pagina=None):
    c.setFillColor(PRETO)
    c.rect(0, 0, W, 26, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.setFont("R", 9)
    c.drawString(M, 9, txt)
    c.drawRightString(W - M, 9, (f"pág. {pagina}  ·  " if pagina else "") + "Tili Pizzaria · Porto Seguro-BA")


def titulo_secao(c, x, y, txt, larg):
    c.setFillColor(PRETO)
    c.rect(x, y - 6, larg, 24, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.rect(x, y - 6, 6, 24, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("B", 14)
    c.drawString(x + 14, y + 1, txt)
    return y - 26


def pagina_lanche(c, L, pag, data_ref):
    cabecalho(c, L, pag)
    y0 = H - 150
    # ---- ingredientes (esq)
    lx, lw = M, 268
    y = titulo_secao(c, lx, y0, "INGREDIENTES E GRAMATURA", lw)
    if L["lanches"] > 1:
        y = texto(c, lx, y, f"Quantidades para os {L['lanches']} lanches.", "B", 12, lw, VERMELHO)
    linhas = [i for i in L["ings"] if i["tipo"] != "emb"]
    for k, i in enumerate(linhas):
        if k % 2 == 0:
            c.setFillColor(CREME)
            c.rect(lx, y - 8, lw, 26, fill=1, stroke=0)
        c.setFillColor(PRETO)
        c.setFont("R", 16)
        c.drawString(lx + 8, y, i["nome"])
        c.setFont("B", 17)
        c.setFillColor(VERMELHO if i["qtd"] == "—" else PRETO)
        c.drawRightString(lx + lw - 8, y, i["qtd"])
        y -= 26
    if L["sem_ficha"]:
        y -= 4
        c.setFillColor(VERMELHO)
        c.roundRect(lx, y - 30, lw, 40, 6, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("B", 14)
        c.drawCentredString(lx + lw / 2, y - 4, "SEM FICHA TÉCNICA NO ALIV")
        c.setFont("R", 11)
        c.drawCentredString(lx + lw / 2, y - 22, "Gramatura a definir — perguntar ao gerente")
        y -= 44
    y_ing = y
    # ---- camadas (dir)
    rx, rw = M + lw + 14, W - 2 * M - lw - 14
    titulo_secao(c, rx, y0, "ORDEM DAS CAMADAS", rw)
    c.setFillColor(CINZA)
    c.setFont("R", 10)
    c.drawString(rx + 4, y0 - 22, "de baixo para cima ↑")
    cam = camadas(L)
    base = y0 - 40 - altura_pilha(cam)
    ilustracao(c, rx, base, rw, cam)
    # ---- montagem
    y = min(y_ing, base - 14) - 6
    y = titulo_secao(c, M, y, "MONTAGEM NA CHAPA", W - 2 * M)
    for k, s in enumerate(passos(L), 1):
        c.setFillColor(VERMELHO)
        c.circle(M + 13, y + 5, 12, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("B", 14)
        c.drawCentredString(M + 13, y, str(k))
        y = texto(c, M + 34, y, s, "R", 16.5, W - 2 * M - 40) - 7
    # ---- caixas finais
    bw = (W - 2 * M - 20) / 3
    by, bh = 36, 138
    for j, (tit, txt) in enumerate((("PONTO DA CARNE", ponto(L)), ("TOSTAGEM DO PÃO", PADRAO["pao"]),
                                    ("EMBALAGEM", embalagem(L)))):
        bx = M + j * (bw + 10)
        c.setFillColor(CREME)
        c.setStrokeColor(DOURADO)
        c.setLineWidth(2)
        c.roundRect(bx, by, bw, bh, 8, fill=1, stroke=1)
        c.setFillColor(VERMELHO)
        c.roundRect(bx, by + bh - 28, bw, 28, 8, fill=1, stroke=0)
        c.rect(bx, by + bh - 28, bw, 10, fill=1, stroke=0)
        c.setFillColor(white)
        c.setFont("B", 14)
        c.drawCentredString(bx + bw / 2, by + bh - 19, tit)
        tam = 14.5
        while len(wrap(c, txt, "R", tam, bw - 16)) * tam * 1.22 > bh - 40 and tam > 9:
            tam -= 0.5
        texto(c, bx + 8, by + bh - 46, txt, "R", tam, bw - 16, entre=1.22)
    if y < by + bh + 8:
        print(f"AVISO: página {pag} ({L['nome']}) apertada (y={y:.0f})", file=sys.stderr)
    # alerta de divergência
    if L["alertas"]:
        c.setFillColor(DOURADO)
        c.rect(0, 26, W, 8, fill=1, stroke=0)
    rodape(c, f"Ficha ALIV loja 150 · {data_ref}"
              + ("  ·  ⚠ ver pendências no final" if L["alertas"] or L["sem_ficha"] else ""), pag)
    c.showPage()


def capa(c, lanches, data_ref):
    c.setFillColor(PRETO)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(VERMELHO)
    c.rect(0, H - 260, W, 260, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.rect(0, H - 268, W, 8, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("C", 54)
    c.drawCentredString(W / 2, H - 120, "MANUAL DE")
    c.drawCentredString(W / 2, H - 180, "MONTAGEM")
    c.setFillColor(DOURADO)
    c.setFont("B", 26)
    c.drawCentredString(W / 2, H - 228, "TILI BURGUER")
    if LOGO.exists():
        c.setFillColor(white)
        c.roundRect(W / 2 - 130, H - 560, 260, 260, 18, fill=1, stroke=0)
        c.drawImage(str(LOGO), W / 2 - 115, H - 545, 230, 230, preserveAspectRatio=True, mask="auto")
    art = [l for l in lanches if l["cat"] == "ARTESANAL"]
    tra = [l for l in lanches if l["cat"] == "TRADICIONAL"]
    c.setFillColor(white)
    c.setFont("B", 18)
    c.drawCentredString(W / 2, H - 610, f"{len(art)} lanches artesanais  ·  {len(tra)} tradicionais")
    c.setFillColor(DOURADO)
    c.setFont("R", 13)
    c.drawCentredString(W / 2, H - 640, "Uma página por lanche: ingredientes, gramatura, chapa,")
    c.drawCentredString(W / 2, H - 658, "ponto da carne, tostagem, camadas e embalagem.")
    c.setFillColor(white)
    c.setFont("R", 11)
    c.drawCentredString(W / 2, 70, f"Dados das fichas técnicas do ALIV (loja 150) · {data_ref}")
    c.drawCentredString(W / 2, 52, "Tili Pizzaria · Porto Seguro-BA")
    c.showPage()


def regras(c, data_ref):
    c.setFillColor(VERMELHO)
    c.rect(0, H - 100, W, 100, fill=1, stroke=0)
    c.setFillColor(DOURADO)
    c.rect(0, H - 106, W, 6, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("C", 34)
    c.drawString(M, H - 66, "REGRAS DA PRAÇA")
    y = H - 140
    blocos = [
        ("ANTES DE COMEÇAR", ["Mãos lavadas, touca e avental.", "Chapa limpa e bem quente antes do 1º pedido.",
                              "Conferir o pedido: tirar ou trocar ingrediente só se estiver na comanda."]),
        ("GRAMATURA", ["Pesar sempre que tiver dúvida. A gramatura da página é a da ficha técnica.",
                       "Faltou ingrediente: avisar o gerente na hora. Não trocar por conta própria."]),
        ("PONTO E SEGURANÇA", ["Frango SEMPRE bem passado, sem parte rosada.",
                               "Hambúrguer bem passado e suculento. Não amassar na chapa.",
                               "Não deixar carne crua encostar em pão ou salada."]),
        ("FECHAMENTO", ["Lanche montado sai em até 1 minuto: embalar, sachês e etiqueta.",
                        "Papel bem fechado para não abrir no caminho do motoboy."]),
    ]
    for tit, itens in blocos:
        y = titulo_secao(c, M, y, tit, W - 2 * M) - 4
        for it in itens:
            c.setFillColor(DOURADO)
            c.circle(M + 10, y + 5, 5, fill=1, stroke=0)
            y = texto(c, M + 24, y, it, "R", 16, W - 2 * M - 30) - 6
        y -= 10
    rodape(c, "Tempos e ponto são o padrão da casa (não vêm do ALIV).")
    c.showPage()


def pendencias(c, lanches, data_ref):
    c.setFillColor(VERMELHO)
    c.rect(0, H - 100, W, 100, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("C", 26)
    c.drawString(M, H - 64, "LANCHES SEM FICHA OU INCOMPLETOS")
    y = H - 135
    sem = [l for l in lanches if l["sem_ficha"]]
    inc = [l for l in lanches if l["alertas"] and not l["sem_ficha"]]
    y = titulo_secao(c, M, y, f"SEM FICHA TÉCNICA NO ALIV ({len(sem)})", W - 2 * M) - 2
    for l in sem:
        y = texto(c, M + 10, y, f"• {l['nome']} — {l['desc']}", "R", 13, W - 2 * M - 20) - 4
    y -= 10
    y = titulo_secao(c, M, y, f"FICHA INCOMPLETA OU DIFERENTE DO CARDÁPIO ({len(inc)})", W - 2 * M) - 2
    for l in inc:
        c.setFont("B", 13)
        c.setFillColor(VERMELHO)
        c.drawString(M + 10, y, l["nome"])
        y -= 17
        for a in l["alertas"]:
            y = texto(c, M + 24, y, "– " + a, "R", 12, W - 2 * M - 34) - 2
        y -= 4
    y -= 6
    y = titulo_secao(c, M, y, "PARA CONFERIR", W - 2 * M) - 2
    for a in ["Ponto da carne, tempos de chapa e tostagem não existem no ALIV: usado o padrão da casa.",
              "Alface: todas as fichas dizem '1 UN' — usei 1 folha; confirmar.",
              "Papel acoplado 30×38: as fichas dizem 4 folhas por lanche — confirmar."]:
        y = texto(c, M + 10, y, "• " + a, "R", 12, W - 2 * M - 20) - 2
    rodape(c, f"Conferido nas fichas do ALIV (loja 150) em {data_ref}. Só leitura.")
    c.showPage()


def main():
    pasta, saida = Path(sys.argv[1]), Path(sys.argv[2])
    limite = int(sys.argv[sys.argv.index("--paginas") + 1]) if "--paginas" in sys.argv else None
    lanches = carregar(pasta)
    data_ref = date.today().strftime("%d/%m/%Y")
    saida.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(saida), pagesize=A4)
    c.setTitle("Manual de Montagem — Tili Burguer")
    capa(c, lanches, data_ref)
    regras(c, data_ref)
    alvo = lanches if limite is None else lanches[:limite]
    for n, L in enumerate(alvo, 1):
        pagina_lanche(c, L, n, data_ref)
    if limite is None:
        pendencias(c, lanches, data_ref)
    c.save()
    print(f"{saida} — {len(alvo)} lanches")


if __name__ == "__main__":
    main()
