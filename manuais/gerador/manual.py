"""Gera o 'Manual de Montagem — Tili Sushi' (A4) a partir dos dados do ALIV já baixados.
Uso: python3 -I manual.py <dir_aliv> <dir_ilus> <logo> <saida.pdf> [--preview <png_dir>]
Não acessa o ALIV: lê full_data.json e recipes.json gravados antes (só leitura)."""
import sys, json, re, base64, html
from pathlib import Path

ALIV, ILUS, LOGO, OUT = (Path(a) for a in sys.argv[1:5])
PREVIEW = Path(sys.argv[sys.argv.index("--preview") + 1]) if "--preview" in sys.argv else None

VERM, OURO, PRETO = "#C8102E", "#D4A017", "#1A1A1A"
ORDEM = ["Hossomaki", "Uramaki", "Hot Roll", "Niguiri", "Gunkan", "Sashimi", "Joy", "Temaki", "Poke", "Pratos", "Combinados", "Packs"]


def b64(p: Path) -> str:
    mime = "image/png" if p.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


IMG = {p.stem: b64(p) for p in ILUS.glob("*.png")}
LOGO_SRC = b64(LOGO)
esc = html.escape

# ------------------------------------------------------------------ dados
rec = json.loads((ALIV / "recipes.json").read_text())
full = json.loads((ALIV / "full_data.json").read_text())
poke_opcoes = [p["name"] for c in full["categories"] if c["id"] == 1161 for p in c["products"]
               if p["name"] not in ("Mini Poke", "Poke", "Tamanho Poke (maior)", "Proteína Extra", "Item Extra")]

CORRECOES = {"salad": "salmão grelhado", "salmão gralhado": "salmão grelhado"}
PROCESSOS = {"empanado", "frito", "empanado e frito"}

ILUS_MAP = [  # (trecho, ilustração) — o primeiro que casar vale
    ("batata doce", None), ("arroz", "arroz"), ("alga", "nori"), ("nori", "nori"),
    ("gergelim", "gergelim"), ("salmão c/ cream cheese", "salmao_cream"),
    ("cubos de salmão", "salmao_cubos"), ("salmão em cubos", "salmao_cubos"),
    ("tataki de salmão", "salmao_cubos"), ("cubos de atum", "atum_cubos"), ("atum em cubos", "atum_cubos"),
    ("tataki de atum", "atum_cubos"), ("tataki de skin", "skin"), ("tataki de shimeji", None),
    ("lâmina de salmão", "salmao_fatia"), ("lâmina de atum", "atum_fatia"), ("lâmina de kani", "kani"),
    ("cream cheese", "cream_cheese"), ("camarão empanado", "camarao_empanado"), ("camarão", "camarao"),
    ("kani", "kani"), ("skin", "skin"), ("salmão", "salmao_lamina"), ("atum", "atum_lamina"),
    ("pepino em fios", "pepino_tiras"), ("tiras de pepino", "pepino_tiras"), ("pepino", "pepino_tiras"),
    ("manga", "manga"), ("morango", "morango"), ("nutella", "chocolate"), ("tomate seco", "tomate_seco"),
    ("cebolinha", "cebolinha"), ("tarê", "tare"), ("geleia de pimenta", "geleia_pimenta"),
    ("crispy de couve", "couve_crispy"), ("cenoura", "cenoura"), ("panko", None),
]


def ilus(nome: str):
    n = nome.lower()
    for k, v in ILUS_MAP:
        if k in n:
            return v
    return None


def limpa_nome(nome: str):
    m = re.search(r"\(\s*0?(\d+)\s*un\s*\)", nome, re.I)
    base = re.sub(r"\s*\(.*?\)\s*", " ", nome).strip()
    base = base.replace("Hosso ", "Hossomaki ").replace("Ura ", "Uramaki ")
    return base, (int(m.group(1)) if m else None)


def ingredientes(desc: str | None):
    if not desc:
        return []
    d = desc.strip().rstrip(".")
    for a, b in CORRECOES.items():
        d = re.sub(rf"\b{a}\b", b, d)
    partes = [p.strip() for p in re.split(r",\s*|\s+e\s+(?=[^,]*$)", d) if p.strip()]
    out = []
    for p in partes:
        if p.lower() in PROCESSOS:
            continue
        m = re.match(r"(\d+)\s*g\s+(?:de\s+)?(.*)", p)
        g, nome = (m.group(1) + " g", m.group(2)) if m else (None, p)
        out.append({"nome": nome[:1].upper() + nome[1:], "g": g, "img": ilus(nome)})
    return out


# ------------------------------------------------- montagem / corte / prato
def recheio(ings, sem=("arroz", "alga", "nori", "gergelim", "panko", "vasilha", "embalagem")):
    r = [i["nome"].lower() for i in ings if not i.get("topo") and not any(s in i["nome"].lower() for s in sem)]
    return ", ".join(r[:-1]) + (" e " + r[-1] if len(r) > 1 else (r[0] if r else ""))


def passos(cat, nome, ings, desc, pecas):
    n = nome.lower(); rch = recheio(ings)
    if cat == "Hossomaki":
        return ([ "1 folha inteira de nori na esteira, lado brilhante para baixo.",
                  "Espalhar o arroz sem apertar, deixando 1 cm livre na borda de cima.",
                  f"Colocar o recheio em linha no centro: {rch}.",
                  "Enrolar com a esteira, apertando firme, e fechar na borda livre."],
                f"Faca molhada. Cortar ao meio e cada metade em {pecas // 2 if pecas else 5} — {pecas or 10} peças iguais.",
                "Peças em pé, corte para cima, em 2 fileiras alinhadas.")
    if cat == "Uramaki":
        top = ("selada", "raspa", "tarê")
        rch = recheio([i for i in ings if not any(t in i["nome"].lower() for t in top)])
        p = ["Meia folha de nori na esteira (com filme), arroz cobrindo a folha toda.",
             "Polvilhar gergelim sobre o arroz.",
             "Virar a folha: arroz para baixo, nori para cima.",
             f"Recheio em linha no centro: {rch}.",
             "Enrolar com a esteira e apertar para firmar o rolo."]
        if "selada" in (desc or "") or "especial" in n:
            p.append("Cobrir o rolo com a lâmina de salmão e selar com maçarico.")
        if "raspa de limão" in (desc or ""):
            p.append("Finalizar com raspa de limão e tarê por cima.")
        return (p, f"Faca molhada. Cortar ao meio e cada metade em {pecas // 2 if pecas and pecas > 1 else 5} — {pecas if pecas and pecas > 1 else 10} peças.",
                "Peças deitadas, corte para cima, em fileira levemente inclinada.")
    if cat == "Hot Roll":
        return (["Montar o rolo com nori, arroz e o recheio: " + rch + ".",
                 "Enrolar firme com a esteira.",
                 "Empanar o rolo inteiro na farinha panko.",
                 "Fritar no óleo quente até dourar por igual; escorrer no papel."],
                f"Esperar 1 minuto e cortar com faca bem afiada em {pecas or 10} peças.",
                "Peças deitadas, corte para cima, em leque.")
    if cat == "Niguiri":
        p = ["Moldar o bolinho de arroz na mão (formato oval, sem esmagar)."]
        if "selado" in n:
            p += ["Colocar a lâmina de salmão sobre o arroz.", "Selar a superfície com maçarico."]
            if "geleia" in n:
                p.append("Finalizar com geleia de pimenta por cima.")
        elif "kani" in n or "skin" in n:
            p += [f"Colocar {'o kani' if 'kani' in n else 'o skin'} sobre o arroz.",
                  "Prender com uma tira fina de alga em volta."]
        else:
            p += ["Colocar a lâmina por cima e pressionar levemente com dois dedos."]
        return (p, "Lâmina cortada em diagonal, contra a fibra, cobrindo todo o bolinho.",
                f"{pecas or 4} peças em fileira, todas viradas para o mesmo lado.")
    if cat == "Joy":
        sem_arroz = not any("arroz" in i["nome"].lower() for i in ings)
        lam = "lâmina de atum" if any("lâmina de atum" in i["nome"].lower() for i in ings) else "lâmina de salmão"
        p = ([] if sem_arroz else ["Moldar bolinho de arroz redondo."]) + [
            f"Envolver com a {lam}" + (" " if sem_arroz else " em volta do arroz, ") +
            "formando um anel um pouco mais alto que a base."]
        tops = [i["nome"].lower() for i in ings if "arroz" not in i["nome"].lower() and "lâmina" not in i["nome"].lower()]
        if tops:
            p.append("Rechear o topo com: " + ", ".join(tops) + ".")
        if "selado" in n:
            p.append("Selar o topo com maçarico.")
        return (p, "Lâmina fina e comprida, cortada no sentido da fibra.",
                f"{pecas or 2} peças lado a lado, topo para cima.")
    if cat == "Temaki":
        return (["Meia folha de nori na mão, lado brilhante para fora.",
                 "Arroz no lado esquerdo da folha.",
                 f"Recheio na diagonal sobre o arroz: {rch}." if rch else "Recheio na diagonal sobre o arroz.",
                 "Enrolar em cone a partir do canto de baixo e fechar com um grão de arroz."]
                + (["Empanar na farinha panko e fritar até dourar."] if "hot" in n else []),
                "Recheio cortado em cubos ou tiras, do tamanho da boca do cone.",
                "Cone em pé no suporte, recheio aparecendo na abertura.")
    if cat == "Poke":
        return (["Montar no bowl seguindo os números dos ingredientes (1, 2, 3...).",
                 "Bases e camas no fundo; proteínas por cima; finalização (cebolinha, crispy, gergelim, molho) por último."],
                "Proteínas em cubos de 1,5 cm; vegetais em fios ou cubos pequenos.",
                "Cada ingrediente em sua faixa, sem misturar; finalização por cima.")
    if cat == "Gunkan":
        cob = recheio(ings)
        sem_arroz = not any("arroz" in i["nome"].lower() for i in ings)
        base = (["Vai no Pack sem Arroz: base sem bolinho de arroz — confirmar a montagem com o Emerson."]
                if sem_arroz else ["Moldar bolinho de arroz oval, como o do niguiri."])
        return (base + ["Envolver com uma faixa de nori, lado brilhante para fora, formando uma borda acima da base.",
                        "Fechar a faixa com um grão de arroz amassado.",
                        f"Preencher o topo com: {cob}." if cob else "Preencher o topo com a cobertura."],
                "Faixa de nori com a altura da base + 1 cm. Cobertura em cubos pequenos ou picada.",
                "Peças em pé, cobertura à mostra, em fileira.")
    if cat == "Pratos":
        if "yakisoba" in n:
            prot = recheio([i for i in ings if i["nome"].lower() not in ("macarrão de yakisoba", "legumes", "molho yakisoba da casa")])
            return (["Aquecer a wok bem quente com um fio de óleo.",
                     f"Selar a proteína ({prot}) e reservar.",
                     "Saltear os legumes rapidamente, mantendo crocantes.",
                     "Voltar a proteína, juntar o macarrão cozido e o molho yakisoba da casa.",
                     "Misturar até o molho envolver tudo e desligar."],
                    "Proteína em tiras; legumes em pedaços do mesmo tamanho.",
                    "Embalagem de 600 g: macarrão por baixo, proteína e legumes aparentes por cima.")
        if "sunomono" in n:
            return (["Fatiar o pepino japonês bem fino.",
                     "Temperar com o molho do sunomono e deixar gelando.",
                     "Escorrer o excesso de líquido antes de embalar."],
                    "Rodelas bem finas, no fatiador.", "Pote fechado, bem escorrido.")
        if "ceviche" in n:
            return (["Peixe limpo e gelado, cortado em cubos.",
                     "Temperar com limão e sal só na hora de servir.",
                     "Juntar os demais ingredientes (receita a cadastrar)."],
                    "Cubos de cerca de 1,5 cm.", "Pote gelado, caldo junto.")
        if "acarajapa" in n:
            return (["Pesar 30 g da massa de acarajapa (receita na página de bases).",
                     "Moldar o bolinho com as mãos úmidas, firme e sem rachar.",
                     "Arrumar na bandeja, sem encostar um no outro."],
                    "Massa já pronta; peixe bem picado para o bolinho não abrir.",
                    "Bolinhos lado a lado na bandeja, sem encostar.")
    if cat == "Sashimi":
        return (["Peixe limpo, sem pele e sem espinhas, gelado.",
                 "Cortar as lâminas e arrumar na hora de servir."],
                "Lâminas de cerca de 0,5 cm, cortadas em um único movimento, contra a fibra.",
                "Lâminas encostadas umas nas outras, em leque.")
    return ([], "", "")


# ------------------------------------------------------------------ html
CSS = f"""
@page {{ size: A4; margin: 0 }}
* {{ box-sizing: border-box; margin: 0; padding: 0 }}
body {{ font-family: Inter, 'DejaVu Sans', sans-serif; color: {PRETO}; background: #fff }}
.pg {{ width: 210mm; height: 297mm; position: relative; overflow: hidden; page-break-after: always;
       border: 3.5mm solid {PRETO}; outline: 1.2mm solid {OURO}; outline-offset: -6mm }}
.top {{ background: {PRETO}; color: {OURO}; height: 22mm; display: flex; align-items: center;
        justify-content: space-between; padding: 0 12mm; border-bottom: 2.2mm solid {VERM} }}
.top .marca {{ display: flex; align-items: center; gap: 4mm; font: 800 13pt 'Inter Display', Inter; letter-spacing: 3px }}
.top img {{ height: 15mm; background: #fff; border-radius: 2mm; padding: 1mm }}
.top .cat {{ font: 800 15pt 'Inter Display', Inter; letter-spacing: 5px; text-transform: uppercase }}
.corpo {{ padding: 8mm 14mm 0 14mm }}
h1 {{ font: 900 30pt/1.05 'Inter Display', Inter; color: {VERM}; text-transform: uppercase }}
.sub {{ font: 500 16pt Inter; margin-top: 2mm }}
.sub b {{ color: {VERM} }}
.aviso {{ display: inline-block; margin-top: 3mm; font: 600 11.5pt Inter; color: {PRETO};
          background: #FBF1D3; border-left: 2mm solid {OURO}; padding: 1.5mm 3mm }}
h2 {{ font: 800 13.5pt 'Inter Display', Inter; letter-spacing: 4px; color: {PRETO}; margin: 6mm 0 3mm;
      text-transform: uppercase; display: flex; align-items: center; gap: 3mm }}
h2::after {{ content: ''; flex: 1; height: .8mm; background: {OURO} }}
.ings {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2mm 7mm }}
.ings.col {{ grid-auto-flow: column }}
.ing {{ display: flex; align-items: center; gap: 3mm; min-height: 17mm; border-bottom: .3mm dotted #bbb }}
.ing .ph {{ width: 26mm; height: 17mm; display: flex; align-items: center; justify-content: center; flex: none }}
.ing .ph img {{ max-width: 26mm; max-height: 17mm }}
.ing .ph span {{ width: 14mm; height: 14mm; border-radius: 50%; border: .8mm solid {OURO}; display: flex;
                 align-items: center; justify-content: center; font: 800 15pt Inter; color: {VERM} }}
.ing .nm {{ flex: 1; font: 500 15pt/1.15 Inter }}
.num {{ font: 800 11pt Inter; font-style: normal; color: #fff; background: {VERM}; border-radius: 50%;
        display: inline-block; width: 6.5mm; height: 6.5mm; line-height: 6.5mm; text-align: center; margin-right: 2mm }}
.ing .g {{ font: 800 15pt Inter; color: {VERM}; white-space: nowrap }}
.ing .g.vazio {{ color: #999; font-weight: 500 }}
.ing .g {{ text-align: right }}
.ing .g small {{ display: block; font: 600 8.5pt/1.25 Inter; color: #555; text-align: right; white-space: nowrap }}
ol {{ list-style: none; counter-reset: s }}
ol li {{ counter-increment: s; font: 400 14pt/1.35 Inter; padding: 1.3mm 0 1.3mm 11mm; position: relative }}
ol li::before {{ content: counter(s); position: absolute; left: 0; top: 1.2mm; width: 7.5mm; height: 7.5mm;
                 background: {VERM}; color: #fff; border-radius: 50%; font: 800 11.5pt/7.5mm Inter; text-align: center }}
ol.plain li {{ padding-left: 0 }} ol.plain li::before {{ display: none }}
.dupla {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7mm; margin-top: 2mm }}
.box {{ border: .6mm solid {PRETO}; border-top: 3mm solid {VERM}; padding: 3mm 4mm; font: 400 14pt/1.35 Inter }}
.box b {{ display: block; font: 800 12.5pt 'Inter Display', Inter; letter-spacing: 3px; margin-bottom: 1.5mm; color: {VERM} }}
.rod {{ position: absolute; bottom: 8mm; left: 14mm; right: 14mm; display: flex; justify-content: space-between;
        font: 500 10.5pt Inter; color: #666; border-top: .4mm solid {OURO}; padding-top: 2mm }}
.capa {{ background: {PRETO}; color: #fff; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center }}
.capa img {{ width: 95mm; background: #fff; border-radius: 4mm; padding: 4mm }}
.capa .t1 {{ font: 900 20pt 'Inter Display', Inter; letter-spacing: 10px; color: {OURO}; margin-top: 14mm }}
.capa .t2 {{ font: 900 44pt/1 'Inter Display', Inter; letter-spacing: 4px; margin-top: 4mm }}
.capa .t3 {{ font: 900 30pt 'Inter Display', Inter; letter-spacing: 8px; color: {VERM}; margin-top: 3mm }}
.capa .t4 {{ font: 500 14pt Inter; color: #ccc; margin-top: 12mm }}
.capa .faixa {{ width: 120mm; height: 2mm; background: {OURO}; margin-top: 10mm }}
.txt p {{ font: 400 15pt/1.45 Inter; margin-bottom: 4mm }}
.lista td {{ font: 400 12.5pt/1.3 Inter; padding: 1.4mm 2mm; border-bottom: .3mm solid #ddd; vertical-align: top }}
.lista th {{ font: 800 12pt Inter; text-align: left; background: {PRETO}; color: {OURO}; padding: 2mm }}
.tag {{ display: inline-block; font: 700 10.5pt Inter; color: #fff; background: {VERM}; padding: .5mm 2mm; border-radius: 1mm; margin-left: 2mm; vertical-align: middle }}
.tag.cinza {{ background: #777 }}
"""


def topo(cat):
    return (f'<div class="top"><div class="marca"><img src="{LOGO_SRC}">TILI SUSHI</div>'
            f'<div class="cat">{esc(cat)}</div></div>')


def rodape(n):
    return f'<div class="rod"><span>Manual de Montagem — Tili Sushi</span><span>pág. {n}</span></div>'


def peso_html(g, n_porcao):
    """Mostra o peso por peça e, embaixo, o total da porção (niguiri e Joy)."""
    if not g:
        return '<span class="g vazio">___ g' + ('<small>por peça</small>' if n_porcao else '') + '</span>'
    if n_porcao:
        m = re.match(r"([\d,.]+)\s*g/peça", g)
        if m:
            v = float(m.group(1).replace(",", ".")); tot = f"{v * n_porcao:g}".replace(".", ",")
            return f'<span class="g">{esc(m.group(1))} g<small>por peça<br>{tot} g na porção</small></span>'
        m = re.match(r"([\d,.]+)\s*g na porção", g)
        if m:
            v = float(m.group(1).replace(",", ".")); cada = f"{v / n_porcao:g}".replace(".", ",")
            return f'<span class="g">{esc(m.group(1))} g<small>na porção<br>{cada} g por peça</small></span>'
    return f'<span class="g">{esc(g.replace("/peça", " por peça"))}</span>'


def bloco_ing(ings, numerar=False, n_porcao=0):
    h = f'<div class="ings{" col" if numerar else ""}" style="grid-template-rows: repeat({(len(ings) + 1) // 2}, auto)">'
    for k, i in enumerate(ings):
        ph = f'<img src="{IMG[i["img"]]}">' if i["img"] in IMG else f'<span>{esc(i["nome"][0])}</span>'
        g = peso_html(i["g"], n_porcao)
        h += f'<div class="ing"><div class="ph">{ph}</div><div class="nm">{f'<i class="num">{k+1}</i>' if numerar else ''}{esc(i["nome"])}</div>{g}</div>'
    return h + "</div>"


def pg_capa():
    return (f'<div class="pg capa"><img src="{LOGO_SRC}"><div class="t1">MANUAL DE</div>'
            f'<div class="t2">MONTAGEM</div><div class="t3">TILI SUSHI</div><div class="faixa"></div>'
            f'<div class="t4">Ficha de montagem por item · Porto Seguro – BA<br>Cardápio do ALIV, loja 155 · nov/2026</div></div>')


def pg_orient(n):
    return (f'<div class="pg">{topo("Orientações")}<div class="corpo txt"><h1>Como usar</h1>'
            f'<h2>Cada página é um item</h2>'
            f'<p><b>Ingredientes:</b> o que vai no item, com a gramatura ao lado.</p>'
            f'<p><b>Ordem de montagem:</b> siga os números, do 1 ao último.</p>'
            f'<p><b>Corte</b> e <b>Apresentação</b>: como cortar e como o item vai para a embalagem ou prato.</p>'
            f'<h2>Gramatura em branco</h2>'
            f'<p>Onde aparece <span style="color:#999">___ g</span>, a gramatura ainda não está cadastrada na ficha técnica do ALIV. '
            f'Pese uma vez, anote à caneta e passe para o Emerson atualizar.</p>'
            f'<h2>Padrão da casa</h2>'
            f'<p>Mãos e faca sempre úmidas. Arroz temperado com o <b>Molho Su</b> da casa (página seguinte), '
            f'em temperatura ambiente. Peixe sempre gelado até a hora de montar.</p>'
            f'</div>{rodape(n)}</div>')


def pg_base(b, n):
    h = '<div class="ings">' + "".join(
        f'<div class="ing"><div class="ph">' + (f'<img src="{IMG[ilus(a)]}">' if ilus(a) in IMG else f'<span>{esc(a[0])}</span>') +
        f'</div><div class="nm">{esc(a)}</div><span class="g">{esc(q)}</span></div>' for a, q in b["ingredientes"]) + "</div>"
    return (f'<div class="pg">{topo("Base da casa")}<div class="corpo"><h1>{esc(b["titulo"])}</h1>'
            f'<div class="sub">{b["sub"]}</div><h2>Ingredientes</h2>{h}<h2>Modo de preparo</h2><ol>'
            + "".join(f"<li>{esc(x)}</li>" for x in b["passos"]) + "</ol>"
            + (f'<div class="dupla" style="grid-template-columns:1fr"><div class="box"><b>{esc(b.get("obs_titulo", "RENDIMENTO" if "Rende" in b["sub"] or "rendem" in b["sub"] else "PROPORÇÃO"))}</b>{esc(b["obs"])}</div></div>' if b.get("obs") else "")
            + f'</div>{rodape(n)}</div>')


def pg_su(n):
    itens = [("Tempero para sushi", "5 litros"), ("Vinagre de arroz", "5 litros"),
             ("Suco de laranja coado", "1 litro"), ("Saquê", "1 litro"), ("Açúcar", "10 quilos"),
             ("Sal", "100 gramas"), ("Ajinomoto", "50 gramas"), ("Kombu", "1 folha")]
    h = '<div class="ings">' + "".join(
        f'<div class="ing"><div class="ph"><span>{esc(a[0][0])}</span></div><div class="nm">{esc(a)}</div>'
        f'<span class="g">{esc(b)}</span></div>' for a, b in itens) + "</div>"
    return (f'<div class="pg">{topo("Base da casa")}<div class="corpo"><h1>Molho Su</h1>'
            f'<div class="sub">Tempero do arroz <b>da casa</b></div>'
            f'<h2>Ingredientes</h2>{h}<h2>Modo de preparo</h2><ol>'
            f'<li>Colocar todos os ingredientes na panela, com a folha de kombu.</li>'
            f'<li>Aquecer em fogo baixo, mexendo, <b>só até o açúcar e o sal dissolverem</b>.</li>'
            f'<li><b style="color:{VERM}">Não deixar ferver.</b></li>'
            f'<li>Desligar o fogo e retirar a kombu.</li>'
            f'<li>Deixar esfriar completamente.</li>'
            f'<li>Guardar em recipiente bem fechado.</li></ol>'
            f'</div>{rodape(n)}</div>')


_CP = Path(__file__).resolve().parent.parent / "custos_aliv.json"
CUSTOS = json.loads(_CP.read_text()) if _CP.exists() else {}
PRECOS = {p["name"]: p.get("price") for c in full["categories"] for p in c["products"]}


def falta_custo(it):
    """Avisa quando o custo está parcial: ingrediente sem peso ou sem preço no estoque."""
    sem_preco = [x.lower() for x in GRAM.get("sem_custo", [])]
    f = [i["nome"].lower() for i in it.get("ings", []) if not i["g"]]
    f += [f"preço do {x}" for x in sem_preco if any(x in i["nome"].lower() for i in it.get("ings", []) if i["g"])]
    return (" · custo parcial, falta: " + ", ".join(f)) if f else ""


def aviso_custo(it):
    nome = it["name"]
    cands = [k for k in CUSTOS if k == nome or k.startswith(nome + " (") or re.sub(r"\s*\(.*?\)", "", k).strip() == nome]
    if not cands or not CUSTOS[cands[0]]:
        return None
    k = cands[0]; c = CUSTOS[k]; pr = PRECOS.get(k)
    m = re.search(r"\(\s*0?(\d+)\s*un\s*\)", k, re.I)
    if it.get("cat") in ("Niguiri", "Joy") and m and int(m.group(1)) > 1:
        n = int(m.group(1))
        txt = f"Custo no ALIV: R$ {c/n:.2f} por peça · R$ {c:.2f} na porção de {n}".replace(".", ",")
        if pr: txt += f" · preço da porção R$ {pr:.2f} · CMV {100*c/pr:.0f}%".replace(".", ",")
        return txt + falta_custo(it)
    txt = f"Ficha técnica no ALIV · custo R$ {c:.2f}".replace(".", ",")
    if pr: txt += f" · preço R$ {pr:.2f} · CMV {100*c/pr:.0f}%".replace(".", ",")
    return txt


def pg_item(it, n):
    nome, pecas = limpa_nome(it["name"])
    cat = it["cat"]
    if pecas is None and cat == "Temaki":
        pecas = 1
    ings = it["ings"]
    st, corte, prato = passos(cat, nome, ings, it["desc"], pecas)
    no_topo = [i["nome"].lower() for i in ings if i.get("topo")]
    if no_topo and cat != "Joy":
        st = st + [f"Depois de cortar, finalizar cada peça com {' e '.join(no_topo)} no topo."]
    unid = it.get("unid") or (f"{pecas:02d} {'peça' if pecas == 1 else 'peças'}" if pecas else "porção")
    aviso = it.get("aviso") or aviso_custo(it) or "Ficha técnica no ALIV: vazia — gramaturas a confirmar"
    peso = it.get("peso") or '<span style="color:#999">___ g</span>'
    return (f'<div class="pg">{topo(cat)}<div class="corpo"><h1>{esc(nome)}</h1>'
            + (f'<div class="sub"><b>Porção de {unid}</b> · gramatura de <b>cada peça</b></div>' if cat in ("Niguiri", "Joy") and pecas and pecas > 1
               else f'<div class="sub"><b>{unid}</b> · gramatura de <b>cada peça</b></div>' if cat in ("Niguiri", "Joy")
               else f'<div class="sub"><b>{unid}</b> · Peso final: {peso}</div>') +
            f''
            f'<div class="aviso">{esc(aviso)}</div>'
            f'<h2>Ingredientes</h2>{bloco_ing(ings, cat == "Poke", (pecas or 0) if cat in ("Niguiri", "Joy") and it.get("tipo") != "derivado" else 0) if ings else "<p style=font-size:14pt>Sem descrição no cardápio.</p>"}'
            f'<h2>Ordem de montagem</h2><ol>' + "".join(f"<li>{esc(s)}</li>" for s in st) +
            f'</ol><div class="dupla"><div class="box"><b>CORTE</b>{esc(corte)}</div>'
            f'<div class="box"><b>APRESENTAÇÃO</b>{esc(prato)}</div></div>'
            f'</div>{rodape(n)}</div>')


def pg_poke_monte(it, n):
    regras = "".join(
        f'<div class="ing" style="align-items:flex-start;min-height:0;padding:1.5mm 0"><div class="nm" style="flex:none;width:52mm">'
        f'<b style="color:{VERM}">{esc(r["name"])}</b></div><div style="font:400 12pt/1.4 Inter">'
        f'{esc(", ".join(re.sub(r" \(dobro de salmão\)$", "", i["name"]) for i in r["items"] if i["name"] not in GRAM.get("tirar_opcao_poke", [])))}</div></div>'
        for r in it["regras"] if "Potencialize" not in r["name"])
    return (f'<div class="pg">{topo("Poke")}<div class="corpo"><h1>{esc(it["name"])}</h1>'
            f'<div class="sub"><b>Monte o seu</b> · {esc(it["desc"])}</div>'
            f'<div class="aviso">Sem ficha técnica no ALIV — gramatura de cada porção a definir</div>'
            f'<h2>Ordem de montagem</h2><ol><li>Conferir na comanda tudo o que o cliente escolheu.</li>'
            f'<li>Base escolhida no fundo do bowl.</li><li>Acompanhamentos em faixas, sem misturar.</li>'
            f'<li>Proteína no centro, por cima.</li><li>Molhos em potinhos separados; fechamento por cima.</li></ol>'
            f'<h2>Opções cadastradas no ALIV</h2>{regras}'
            f'</div>{rodape(n)}</div>')


def pg_combo(it, n):
    linhas = "".join(
        f'<div class="ing" style="min-height:13mm"><span class="g" style="width:16mm;font-size:20pt">{q}</span>'
        f'<div class="nm">{esc(nm)}</div></div>' for q, nm in it["pecas"])
    total = sum(int(q) for q, _ in it["pecas"])
    return (f'<div class="pg">{topo(it["cat"])}<div class="corpo"><h1>{esc(it["name"])}</h1>'
            f'<div class="sub"><b>{total} peças</b> na embalagem</div>'
            f'<div class="aviso">Composição conforme a descrição do cardápio no ALIV</div>'
            f'<h2>Composição</h2><div class="ings" style="grid-template-columns:1fr">{linhas}</div>'
            f'<h2>Montagem da embalagem</h2><ol>'
            f'<li>Conferir a comanda e o total de {total} peças.</li>'
            f'<li>Montar cada tipo de peça conforme a página do item neste manual.</li>'
            f'<li>Arrumar por tipo, em fileiras: sashimi, niguiri, uramaki/hot/hossomaki e joy por último (mais frágil).</li>'
            f'<li>Conferir acompanhamentos (shoyu, gengibre, wasabi) e fechar a embalagem.</li></ol>'
            f'</div>{rodape(n)}</div>')


def problemas(it):
    nome, pecas = limpa_nome(it["name"])
    prob = list(it.get("obs", []))
    if it["tipo"] == "combo":
        return prob
    if it["tipo"] == "poke":
        return ["sem ficha técnica; gramaturas das porções não cadastradas"]
    if it["tipo"] == "derivado":
        prob.insert(0, "sem cadastro próprio no ALIV (só aparece dentro de combo)")
    elif not aviso_custo(it):
        prob.insert(0, "ficha técnica vazia no ALIV")
    if not it["desc"]:
        prob.append("sem descrição no cardápio")
    elif not any(i["g"] for i in it["ings"]):
        prob.append("sem gramatura")
    elif not all(i["g"] for i in it["ings"]):
        prob.append("gramatura parcial")
    if it["name"].startswith("Hosso Atum"):
        prob.append("cadastrado também na categoria Uramaki")
    if "salad" in (it["desc"] or ""):
        prob.append("descrição diz 'salad' (lido como salmão grelhado)")
    if "gralhado" in (it["desc"] or ""):
        prob.append("erro de digitação 'gralhado'")
    if it["cat"] == "Uramaki" and pecas == 1 and it["name"] not in GRAM.get("pecas", {}):
        prob.append("nome diz 01 Un (confirmar nº de peças)")
    return prob


def pgs_pendencias(n0):
    L = [(it["cat"], limpa_nome(it["name"])[0], "; ".join(p)) for it in ITENS if (p := problemas(it))]
    L += [("Inativo", limpa_nome(nm)[0], "inativo no cardápio — fora do manual") for nm in INATIVOS]
    out = []; por = 24
    for k in range(0, len(L), por):
        rows = "".join(f"<tr><td>{esc(c)}</td><td><b>{esc(nm)}</b></td><td>{esc(p)}</td></tr>" for c, nm, p in L[k:k + por])
        cab = ('<h1>Itens sem ficha ou incompletos</h1><div class="sub">O que ainda falta para a ficha ficar '
               '<b>completa</b> no manual e no ALIV (loja 155)</div>') if k == 0 else "<h1>Pendências (cont.)</h1>"
        out.append(f'<div class="pg">{topo("Pendências")}<div class="corpo">{cab}<table class="lista" style="width:100%;margin-top:5mm;border-collapse:collapse">'
                   f'<tr><th>Categoria</th><th>Item</th><th>O que falta</th></tr>{rows}</table></div>{rodape(n0 + len(out))}</div>')
    return out


# ------------------------------------------------------------------ montar
def ing_manual(*nomes):
    return [{"nome": x, "g": None, "img": ilus(x)} for x in nomes]


ITENS, INATIVOS = [], []
for pid, v in rec.items():
    if not v["active"]:
        INATIVOS.append(v["name"]); continue
    if v["cat"] == "Poke":
        continue  # Poke / Mini Poke ativos são o "Monte seu Poke" (combos), tratados abaixo
    v["tipo"] = "item"; v["ings"] = ingredientes(v["desc"])
    if v["cat"] == "Hot Roll" or v["name"].startswith("Temaki Hot"):
        v["ings"].append({"nome": "Farinha panko (empanar)", "g": None, "img": None})
    if v["cat"] == "Sashimi":
        v["ings"] = ing_manual("Salmão"); v["obs"] = ["peixe não informado; combos citam sashimi de salmão"]
    ITENS.append(v)

COMBO_TXT = "Peça usada nos combinados — sem cadastro próprio no ALIV; ingredientes da descrição do combo"
DERIV = [  # (categoria, nome, descrição usada, onde aparece, observação)
    ("Hot Roll", "Hot Kuruba", "alga, arroz, cream cheese e crispy de couve", "Combo Hot 24+24", None),
    ("Hot Roll", "Hot Capão", "alga, arroz, cream cheese e alho poró", "Combo Hot 24+24", "confirmar se leva salmão (temaki capão leva)"),
    ("Hot Roll", "Hot Tayo", "alga, arroz, cream cheese e batata doce", "Combo Hot 24+24", None),
    ("Uramaki", "Ura Eby Fry c/ lâmina e alho poró", "arroz, gergelim, camarão empanado, lâmina de salmão e alho poró", "Especial Pack", None),
    ("Uramaki", "Ura Salad", None, "Combinado econômico", "receita não descrita"),
    ("Hossomaki", "Hosso Kapa", "alga, arroz e pepino", "Combinado econômico", None),
    ("Hossomaki", "Hosso Variado", None, "Combinado econômico", "sabores não definidos"),
    ("Niguiri", "Niguiri Salmão Selado c/ alho poró", "arroz, lâmina de salmão selado e alho poró", "Especial Pack", None),
    ("Gunkan", "Gunkan Cebolinha", "alga, arroz e cebolinha", "Combinado Tili Salmão 24", "confirmar se leva salmão"),
    ("Gunkan", "Gunkan Alho Poró", "alga, arroz e alho poró", "Combinado Tili Salmão 24", "confirmar se leva salmão"),
    ("Gunkan", "Gunkan Bamboo", None, "Combinado Tili salmão 48", "receita não descrita"),
    ("Gunkan", "Gunkan Capão", "alga, arroz, salmão em cubos, cream cheese e alho poró", "Combinado Tili salmão 48", "ingredientes do temaki capão"),
    ("Gunkan", "Gunkan Salmão c/ cebolinha", "alga, arroz, salmão em cubos e cebolinha", "Especial Pack", None),
    ("Gunkan", "Gunkan Roast c/ alho poró", "alga, roast e alho poró", "Pack sem Arroz", "sem arroz: confirmar a base"),
    ("Gunkan", "Gunkan Salmão Selado c/ alho poró", "alga, salmão selado e alho poró", "Pack sem Arroz", "sem arroz: confirmar a base"),
]
for cat, nome, desc, onde, obs in DERIV:
    ITENS.append({"cat": cat, "name": nome, "active": True, "desc": desc, "tipo": "derivado",
                  "ings": ingredientes(desc) + (ing_manual("Farinha panko (empanar)") if cat == "Hot Roll" else []),
                  "aviso": f"{COMBO_TXT} ({onde})", "unid": "Peça de combo", "obs": [f"aparece em: {onde}"] + ([obs] if obs else [])})

PRATOS = {  # id: (ingredientes, observação, peso)
    32379: (["Arroz de sushi", "Peixe grelhado", "Cream cheese", "Cebolinha", "Gergelim"], None, "30 g (cardápio)"),
    14358: (["Pepino japonês", "Molho do sunomono"], None, None),
    12155: (["Peixe em cubos", "Limão", "Sal"], "descrição errada no ALIV ('PEÇA DE SUSHI'); receita a cadastrar", None),
    14325: (["Macarrão de yakisoba", "Frango", "Legumes", "Molho yakisoba da casa"], None, "600 g"),
    14328: (["Macarrão de yakisoba", "Camarão", "Legumes", "Molho yakisoba da casa"], None, "600 g"),
    14329: (["Macarrão de yakisoba", "Camarão", "Filé", "Frango", "Legumes", "Molho yakisoba da casa"], None, "600 g"),
    14326: (["Macarrão de yakisoba", "Filé", "Legumes", "Molho yakisoba da casa"], None, "600 g"),
}
_G = json.loads((Path(__file__).resolve().parent.parent / "gramaturas_sushi.json").read_text())
INCLUIR = set(_G.get("incluir_inativos", []))
prods = {p["id"]: p for c in full["categories"] for p in c["products"]}
for pid, (ings, obs, peso) in PRATOS.items():
    p = prods[pid]; fd = p.get("full_data") or {}
    if not p.get("is_active") and pid not in INCLUIR:
        if p["name"] not in INATIVOS: INATIVOS.append(p["name"])
        continue
    nome = re.sub(r"\s*\(600g\)", "", p["name"]).title() if p["name"].isupper() else re.sub(r"\s*\(600g\)", "", p["name"])
    ITENS.append({"cat": "Pratos", "name": nome, "active": True, "desc": fd.get("description"), "tipo": "item",
                  "ings": ing_manual(*ings), "peso": peso, "unid": "porção", "obs": [obs] if obs else []})


for c in full["categories"]:
    if c["id"] not in (937, 938):
        continue
    for p in c["products"]:
        fd = p.get("full_data") or {}
        if not p.get("is_active"):
            INATIVOS.append(p["name"]); continue
        desc = (fd.get("description") or "").replace("sashumi", "sashimi")
        pecas = [(m.group(1).lstrip("0") or "0", m.group(2).strip()) for parte in desc.split(",")
                 if (m := re.match(r"\s*(\d+)\s+(.+)", parte))]
        obs = []
        if "sashumi" in (fd.get("description") or ""): obs.append("erro de digitação 'sashumi'")
        if ", ," in (fd.get("description") or ""): obs.append("vírgula sobrando na descrição")
        if re.search(r"\d+ (uramaki|niguiri|joy|hot|sashimi)\b(?! \w)", desc): obs.append("sabores de algumas peças não especificados")
        ITENS.append({"cat": "Combinados" if c["id"] == 937 else "Packs", "name": p["name"], "active": True,
                      "desc": desc, "tipo": "combo", "pecas": pecas, "obs": obs})

for cb in full["combos"]:
    if cb.get("is_active") and "Poke" in cb["name"]:
        ITENS.append({"cat": "Poke", "name": cb["name"], "active": True, "desc": cb["description"], "tipo": "poke",
                      "regras": cb["full_data"]["config"]["flexible_rules"]})

for it in ITENS:
    if it["cat"] == "Uramaki" and it.get("ings") and not any("alga" in i["nome"].lower() for i in it["ings"]):
        it["ings"].insert(0, {"nome": "Alga", "g": None, "img": "nori"})

GRAM = json.loads((Path(__file__).resolve().parent.parent / "gramaturas_sushi.json").read_text()) \
    if (Path(__file__).resolve().parent.parent / "gramaturas_sushi.json").exists() else {"regras": [], "itens": {}}
for nv in GRAM.get("novos", []):
    ITENS.append({"cat": nv["categoria"], "name": nv["nome"], "active": True, "desc": None, "tipo": "item",
                  "ings": [{"nome": n, "g": g, "img": ilus(n)} for n, g in nv["ingredientes"]],
                  "aviso": "Item novo da casa — ainda não cadastrado no ALIV", "obs": ["não cadastrado no ALIV"]})
for it in ITENS:
    for r in GRAM.get("tirar_ingrediente", []):
        if "ings" in it and ("*" in r["categorias"] or it["cat"] in r["categorias"]):
            it["ings"] = [i for i in it["ings"] if r["ingrediente"].lower() not in i["nome"].lower()]
    if it["name"] in GRAM.get("ingredientes", {}):
        it["ings"] = [{"nome": n, "g": g, "img": ilus(n)} for n, g in GRAM["ingredientes"][it["name"]]]
        it.setdefault("obs", []).append("ingredientes informados pelo Emerson (ALIV sem descrição)")
    for extra in GRAM.get("adicionar", {}).get(it["name"], []):
        if not any(extra["nome"].lower() in i["nome"].lower() for i in it["ings"]):
            pos = (len(it["ings"]) if any(w in extra["nome"].lower() for w in ("vasilha", "embalagem"))
                   else 1 if it["ings"] and "alga" in it["ings"][0]["nome"].lower() else 0)
            it["ings"].insert(pos, {"nome": extra["nome"], "g": extra.get("g"), "img": ilus(extra["nome"])})
    if it["name"] in GRAM.get("pecas", {}):
        it["unid"] = f"{GRAM['pecas'][it['name']]:02d} peças"
    if it["name"] in GRAM.get("avisos", {}):
        it["aviso"] = GRAM["avisos"][it["name"]]
    if it["name"] in GRAM.get("unid", {}):
        it["unid"] = GRAM["unid"][it["name"]]
    if it["name"] in GRAM.get("peso_final", {}):
        it["peso"] = GRAM["peso_final"][it["name"]]
    for i in it.get("ings", []):
        nm = i["nome"].lower()
        for r in GRAM.get("regras", []):
            if ("*" in r["categorias"] or it["cat"] in r["categorias"]) and r["ingrediente"].lower() in nm and not any(x in nm for x in r.get("exceto", [])):
                i["g"] = r["g"]
        if any(t.lower() in nm for t in GRAM.get("topo", {}).get(it["name"], [])):
            i["topo"] = True
        for ing, g in (GRAM.get("itens", {}).get(it["name"]) or {}).items():
            if ing.lower() in nm:
                i["g"] = g

# Espelho: o item de atum copia as gramaturas do item de salmão equivalente
POR_NOME = {it["name"]: it for it in ITENS}
for alvo, origem in GRAM.get("espelho", {}).items():
    a, o = POR_NOME.get(alvo), POR_NOME.get(origem)
    if not a or not o:
        continue
    for i in a.get("ings", []):
        pal = lambda s: set(s.lower().replace("atum", "salmão").split()) - {"de", "em", "c/", "com"}
        for j in o["ings"]:
            if j["g"] and pal(i["nome"]) == pal(j["nome"]):
                i["g"] = j["g"]
                break

REMOVER = set(GRAM.get("remover", []))
ITENS[:] = [it for it in ITENS if it["name"] not in REMOVER and it["cat"] not in GRAM.get("remover_categorias", [])]

ITENS.sort(key=lambda v: (ORDEM.index(v["cat"]), v["tipo"] == "derivado", v["name"]))

pages = [pg_capa(), pg_orient(2), pg_su(3)]
for b in GRAM.get("bases", []):
    pages.append(pg_base(b, len(pages) + 1))
for it in ITENS:
    n = len(pages) + 1
    f = {"combo": pg_combo, "poke": pg_poke_monte}.get(it["tipo"], pg_item)
    pages.append(f(it, n))
pages += pgs_pendencias(len(pages) + 1)

if PREVIEW:
    alvo = ["Gunkan Capão", "Hot Kuruba", "Acarajapa", "Yakisoba de Frango", "Monte seu Poke", "Combinado Salmão 25 Peças", "Especial Pack (23 peças)"]
    want = [ITENS.index(next(it for it in ITENS if it["name"].startswith(a))) + 3 + len(GRAM.get('bases', [])) for a in alvo]
    want += [len(pages) - 2, len(pages) - 1]
    pages = [pages[i] for i in want]

doc = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(pages)}</body></html>"
OUT.with_suffix(".html").write_text(doc, encoding="utf-8")
print(f"{len(ITENS)} itens, {len(INATIVOS)} inativos fora, {len(pages)} páginas → {OUT.with_suffix('.html')}")
