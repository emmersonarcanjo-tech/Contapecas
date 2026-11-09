#!/usr/bin/env python3
"""Folha de Contagem física do estoque — Tili Pizzaria (loja 150). SÓ LEITURA no ALIV.

Lê:
  GET /admin/inventory/api/ingredients               insumos (saldo, unidade, fator)
  GET /admin/api/menu/full_data                      cardápio (produtos ativos, tamanhos, adicionais)
  GET /admin/menu/product/{id}/recipes?size_id=      ficha técnica de cada produto/tamanho
  GET /admin/menu/addon/{id}/recipe_matrix           ficha dos adicionais (bordas, extras)

Gera em manuais/:
  Folha_de_Contagem_Tili_Pizzaria.pdf   A4, letra grande, linhas altas para escrever à mão
     Parte 1  contagem por área física (em uso primeiro, depois A-Z)
     Parte 2  insumos fora de qualquer ficha e com saldo negativo (decidir: contar ou zerar)
     Parte 3  pizzas e lanches ativos sem ficha ou com ficha incompleta
  Folha_de_Contagem_Tili_Pizzaria.xlsx  mesmas linhas da Parte 1, para digitar a contagem
     (o monitor/contagem_lancar.py lê essa planilha e lança na conferência do ALIV)

Uso:
  python3 monitor/contagem.py                 # coleta no ALIV e gera PDF + planilha
  python3 monitor/contagem.py --cache ARQ     # usa/grava os dados coletados em ARQ (JSON)

Códigos de saída: 0 ok · 1 erro no ALIV · 2 faltam ALIV_USER/ALIV_PASS.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import Aliv, AlivError  # noqa: E402

TZ = ZoneInfo("America/Bahia")
RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "manuais"
NOME = "Folha_de_Contagem_Tili_Pizzaria"
TITULO = "Folha de Contagem — Tili Pizzaria"

# Categorias do cardápio que entram na Parte 3 (pizzas e lanches).
CAT_PIZZA = ("pizza",)
CAT_LANCHE = ("lanche", "burguer", "porc")

# --------------------------------------------------------------- áreas físicas
AREAS = ["Freezer", "Câmara / Geladeira", "Estoque seco", "Bebidas", "Embalagens", "Limpeza"]
OUTROS = "Utensílios, equipamentos e manutenção"


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def _tem(n: str, *chaves: str) -> bool:
    return any(re.search(r"(?<![a-z])" + k, n) for k in chaves)


# A ordem importa: a primeira regra que bater define a área.
REGRAS = [
    (OUTROS, ("prateleira", "abracadeira", "acendedor", "aguarr", "algicida", "barrilha", "clarificante",
              "cloro gran", "bandeja retangular", "bandeja servir", "kit 10 bandeja", "kit com 10 bandeja",
              "kit 12 cuba", "barra magnetic", "barramento", "batedor", "broca", "bucha", "cabo ", "caixa de luz",
              "caixa gordura", "caixa p/guardar", "campainha", "cap esg", "capacitor", "cervejeira", "chaira",
              "cola adesivo", "cola instant", "condulete", "conector", "conjunto de 5", "container de lixo",
              "controle de vel", "cor ulres", "curva branca", "disj", "dispenser", "display de mesa", "dps ", "emenda p",
              "espatula", "esteira", "estante", "exaustor", "extrator", "faca ", "filtro agua", "fita ", "fogao",
              "folheto", "adesivo tap", "freezer ", "frigideira", "fritad", "fusivel", "gas macarico", "ge vr",
              "grampo", "haste", "hp 256", "lamp ", "lixa ", "lixeira", "lum ", "macarico", "maquina de gelo",
              "mesa ", "mesa de", "modulo tomada", "moedor", "mouse", "multi cortador", "nipel", "onu 1075",
              "painel back", "panela", "passador", "pedra", "pegador", "pendente", "pia ", "pinca", "plug",
              "point pro", "porta condimento", "processador", "rabicho", "ralo ", "saco de confeitar", "serra copo",
              "snow mao", "softworks", "sumup", "tabua", "tigelas", "tomada", "torn prime", "tram ", "te lr",
              "trincha", "tubo ", "tv ", "unid cond", "unid evap", "vaso grego", "verniz", "ww kit", "selador",
              "cera acril", "mop ")),
    ("Limpeza", ("agua sanit", "sanitaria", "clorito", "hipoclorito", "deterg", "det liquido", "desinf",
                 "limp m uso", "sabao", "sabonete", "esponja", "pano ", "papel hig", "papel toalha", "toalha de papel",
                 "saco p/ lixo", "alcool 70", "gel hig", "inset", "maximoom", "foaming", "luva", "touca",
                 "escova sanit", "sh inf", "sab l inf", "abs hig")),
    ("Embalagens", ("caixa p/ pizza", "bobina", "bob termica", "sacola", "saco sos", "papel acoplado", "pote",
                    "tampa", "embalagem", "emb. oriental", "garrafa pet", "ctp ", "canudo", "guardanapo",
                    "guard sache", "kit sache", "talher", "hashi", "etiqueta", "filme pvc", "colher 928",
                    "marmitex", "tp 100", "bandeja pequena", "berco para", "mesinha para pizza")),
    ("Freezer", ("picole", "sorvete", "paleta cx", "cone cx", "cong", "iqf", "batata 7mm", "batata 9mm",
                 "batata palito", "batata congelada", "hamb", "carne de hamburguer", "carne moida formatada",
                 "camarao", "kani", "vg ", "coxa/", "frango congelado", "file de peito ind", "file meio peito",
                 "massa rolinho", "lombo de atum")),
    ("Estoque seco", ("pimenta calabresa", "cebola")),
    ("Bebidas", ("refrig", "coca[ -]", "cc sem acucar", "guarana", "pepsi", "schweppes", "sprite", "cerveja",
                 "stella", "corona", "heineken", "am crys", "agua mineral", "suco", "jesus lt")),
    ("Câmara / Geladeira", ("queijo", "mussarela", "muss", "parmes", "provolone", "coalho", "requeijao",
                            "cream cheese", "polengui", "presunto", "lombinho", "lombo", "bacon", "ling",
                            "calabresa", "carne de sol", "carne seca", "coxao", "file de peito", "peito de frango",
                            "manteiga", "ovo", "alface", "tomate fresco", "tomate b6", "pimentao", "cenoura",
                            "repolho", "pepino", "manjericao", "coentro", "cebolinha", "limao", "morango", "maracuja",
                            "gengibre$", "salmao", "atum$", "massa pizza", "pao de brioche", "cha de fora")),
]


def area_de(nome: str, categoria: str) -> str:
    n = norm(nome)
    for area, chaves in REGRAS:
        if _tem(n, *chaves):
            return area
    if norm(categoria).startswith("bebidas"):
        return "Bebidas"
    if norm(categoria).startswith("produtos de limpeza"):
        return "Limpeza"
    return "Estoque seco"


# --------------------------------------------------------------- coleta
def _lista(r, chave):
    return r.get(chave, []) if isinstance(r, dict) else (r or [])


def coletar(api: Aliv) -> dict:
    ins = _lista(api.get("/admin/inventory/api/ingredients"), "ingredients")
    menu = api.get("/admin/api/menu/full_data")
    tamanhos = {s["id"]: s["name"] for s in menu.get("sizes", [])}

    produtos = []
    for c in menu.get("categories", []):
        for p in c.get("products", []):
            if not p.get("is_active"):
                continue
            sizes = [s["size_id"] for s in p.get("size_prices") or [] if s.get("size_id")]
            produtos.append({"id": p["id"], "nome": p["name"], "categoria": c["name"], "pizza": bool(p.get("is_pizza")),
                             "tamanhos": sizes, "fichas": {}})

    tarefas = [(p, s) for p in produtos for s in (p["tamanhos"] or [None])]

    def ficha(t):
        p, s = t
        q = f"?size_id={s}" if s else ""
        return p, s, api.get(f"/admin/menu/product/{p['id']}/recipes{q}") or []

    with ThreadPoolExecutor(max_workers=6) as ex:
        for p, s, itens in ex.map(ficha, tarefas):
            p["fichas"][tamanhos.get(s, "Único") if s else "Único"] = [
                {"ingredient_id": i.get("ingredient_id"), "nome": i.get("ingredient_name") or i.get("ingredient_raw_name"),
                 "quantidade": i.get("quantity"), "unidade": i.get("ingredient_unit"), "custo": i.get("total_cost")}
                for i in itens]

    adicionais = [a for a in menu.get("extras", []) if a.get("is_active")]

    def matriz(a):
        return a, api.get(f"/admin/menu/addon/{a['id']}/recipe_matrix") or []

    add_out = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for a, m in ex.map(matriz, adicionais):
            ids = sorted({int(x) for bloco in m for row in bloco.get("rows", [])
                          for x in [row.get("ingredient_id")] if x})
            add_out.append({"id": a["id"], "nome": a["name"], "ingredientes": ids})

    # Sub-receitas (ex.: massa produzida): componentes vêm em recipe_base_ids.
    subs = {str(x["id"]): sorted(int(i) for i in x.get("recipe_base_ids") or []) for x in ins if x.get("recipe_base_ids")}

    return {"gerado": datetime.now(TZ).isoformat(timespec="minutes"), "insumos": ins, "produtos": produtos,
            "adicionais": add_out, "subreceitas": subs}


# --------------------------------------------------------------- análise
def nome_exib(x: dict) -> str:
    return (x.get("display_name") or x.get("name") or "").strip()


def fmt_num(v) -> str:
    v = float(v or 0)
    s = f"{v:,.3f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def analisar(dados: dict) -> dict:
    ins = {int(x["id"]): x for x in dados["insumos"]}
    uso: dict[int, set] = {}
    for p in dados["produtos"]:
        for itens in p["fichas"].values():
            for i in itens:
                if i.get("ingredient_id"):
                    uso.setdefault(int(i["ingredient_id"]), set()).add(p["nome"])
    for a in dados["adicionais"]:
        for i in a["ingredientes"]:
            uso.setdefault(int(i), set()).add(f"Adicional {a['nome']}")
    # componentes de sub-receitas que estão em uso também estão em uso
    for _ in range(3):
        for pai, filhos in dados["subreceitas"].items():
            if int(pai) in uso:
                for f in filhos:
                    uso.setdefault(int(f), set()).add(f"Sub-receita {nome_exib(ins.get(int(pai), {}))}")

    linhas, outros = [], []
    for i, x in ins.items():
        if x.get("is_paused"):
            continue
        area = area_de(x.get("name"), x.get("category_name"))
        conv = float(x.get("conversion_factor") or 1)
        un, uu = x.get("unit") or "UN", x.get("usage_unit") or x.get("unit") or "UN"
        ln = {"id": i, "nome": nome_exib(x), "nome_aliv": x.get("name"), "area": area, "em_uso": i in uso,
              "usado_em": sorted(uso.get(i, [])), "unidade": un, "unidade_ficha": uu, "conv": conv,
              "equivale": f"1 {un} = {fmt_num(conv)} {uu}" if (uu != un or conv != 1) else "—",
              "saldo": float(x.get("current") or 0), "custo": float(x.get("cost") or 0),
              "categoria": x.get("category_name")}
        (outros if area == OUTROS else linhas).append(ln)

    ordem = {a: k for k, a in enumerate(AREAS)}
    linhas.sort(key=lambda l: (ordem[l["area"]], not l["em_uso"], norm(l["nome"])))
    outros.sort(key=lambda l: norm(l["nome"]))

    sem_ficha = sorted([l for l in linhas + outros if not l["em_uso"]], key=lambda l: (l["area"] == OUTROS, ordem.get(l["area"], 99), norm(l["nome"])))
    negativos = sorted([l for l in linhas + outros if l["saldo"] < 0], key=lambda l: l["saldo"])

    # Parte 3: pizzas e lanches ativos sem ficha / ficha incompleta
    problemas = []
    for p in dados["produtos"]:
        cat = norm(p["categoria"])
        if not (p["pizza"] or any(k in cat for k in CAT_PIZZA + CAT_LANCHE)):
            continue
        tipo = "Pizza" if (p["pizza"] or "pizza" in cat) else "Lanche"
        motivos = []
        fichas = p["fichas"]
        vazias = [t for t, it in fichas.items() if not it]
        if fichas and len(vazias) == len(fichas):
            motivos.append("sem ficha técnica")
        else:
            if vazias:
                motivos.append("sem ficha no tamanho " + ", ".join(vazias))
            for t, it in fichas.items():
                if not it:
                    continue
                nomes = " ".join(norm(i["nome"]) for i in it)
                suf = f" ({t})" if t != "Único" else ""
                if tipo == "Pizza" and "massa" not in nomes:
                    motivos.append("sem massa" + suf)
                if tipo == "Lanche" and "pao" not in nomes and "batata" not in norm(p["nome"]):
                    motivos.append("sem pão" + suf)
                if tipo == "Lanche" and "batata" in norm(p["nome"]) and "batata" not in nomes:
                    motivos.append("sem batata" + suf)
                if not re.search(r"caixa|embalag|papel acoplado|saco|sacola|bobina", nomes):
                    motivos.append("sem embalagem" + suf)
                if len(it) < 3:
                    motivos.append(f"só {len(it)} item(ns){suf}")
                zero = [i["nome"] for i in it if not float(i.get("quantidade") or 0)]
                if zero:
                    motivos.append(f"quantidade zero: {', '.join(zero)}{suf}")
                pausados = [i["nome"] for i in it if i.get("ingredient_id") and int(i["ingredient_id"]) not in ins]
                if pausados:
                    motivos.append(f"insumo inexistente: {', '.join(pausados)}{suf}")
                sem_custo = [i["nome"] for i in it if i.get("ingredient_id") and int(i["ingredient_id"]) in ins
                             and not float(ins[int(i["ingredient_id"])].get("cost") or 0)]
                if sem_custo:
                    motivos.append(f"insumo sem custo: {', '.join(sem_custo)}{suf}")
        if motivos:
            # junta motivos iguais de tamanhos diferentes
            vistos, final = {}, []
            for m in motivos:
                base, _, tam = m.partition(" (")
                vistos.setdefault(base, []).append(tam.rstrip(")") if tam else "")
            for base, tams in vistos.items():
                tams = [t for t in tams if t]
                final.append(base + (f" ({', '.join(tams)})" if tams and len(tams) < len(p["fichas"]) else ""))
            problemas.append({"tipo": tipo, "nome": p["nome"], "categoria": p["categoria"], "motivos": final})
    problemas.sort(key=lambda x: (x["tipo"], norm(x["nome"])))

    return {"linhas": linhas, "outros": outros, "sem_ficha": sem_ficha, "negativos": negativos,
            "problemas": problemas, "n_uso": len(uso), "gerado": dados["gerado"]}


# --------------------------------------------------------------- PDF
CSS = """
@page { size: A4; margin: 10mm 10mm 12mm }
* { box-sizing: border-box; margin: 0; padding: 0 }
body { font-family: "Liberation Sans", Arial, Helvetica, sans-serif; color: #1A1A1A; font-size: 12pt;
       -webkit-print-color-adjust: exact; print-color-adjust: exact }
.capa { page-break-after: always; display: flex; flex-direction: column; min-height: 265mm }
.topo { display: flex; align-items: center; gap: 4mm; padding-bottom: 3mm; border-bottom: 3px solid #C8102E }
.topo img { width: 22mm; height: 22mm; object-fit: contain; mix-blend-mode: multiply }
.topo .nome { color: #C8102E; font-weight: bold; font-size: 22pt; line-height: 1.05 }
.topo .sub { font-size: 10pt; color: #555 }
.faixa { height: 2mm; background: #D4A017; margin-top: 1mm }
h1 { font-size: 20pt; margin: 6mm 0 2mm; color: #1A1A1A }
h2 { font-size: 17pt; margin: 0 0 2mm; padding: 2mm 3mm; background: #C8102E; color: #fff; border-radius: 1.5mm;
     break-after: avoid; page-break-after: avoid }
h2 .q { float: right; font-size: 11pt; font-weight: normal; margin-top: 1.5mm }
h3 { font-size: 13pt; margin: 4mm 0 1.5mm; color: #C8102E; border-bottom: 2px solid #D4A017; padding-bottom: 1mm;
     break-after: avoid; page-break-after: avoid }
.parte { page-break-before: always }
.area { page-break-before: always }
.instr { font-size: 12pt; line-height: 1.5; margin: 3mm 0 }
.instr li { margin-left: 6mm; margin-bottom: 1.5mm }
.resumo { display: flex; flex-wrap: wrap; gap: 3mm; margin: 4mm 0 }
.resumo div { flex: 1 1 30%; border: 2px solid #1A1A1A; border-radius: 2mm; padding: 3mm; font-size: 10pt }
.resumo b { display: block; font-size: 20pt; color: #C8102E }
.ass { display: flex; gap: 8mm; margin-top: auto; padding-top: 10mm }
.ass div { flex: 1; border-top: 1.5px solid #1A1A1A; text-align: center; font-size: 10pt; padding-top: 1.5mm }
table { width: 100%; border-collapse: collapse; }
thead { display: table-header-group }
tr { page-break-inside: avoid; break-inside: avoid }
th { background: #1A1A1A; color: #fff; font-size: 10pt; text-align: left; padding: 2mm; border: 1px solid #1A1A1A }
td { border: 1px solid #888; padding: 1.5mm 2mm; vertical-align: middle }
.contagem td { height: 14mm; font-size: 12pt }
.contagem td.nm { font-weight: bold; line-height: 1.15 }
.contagem td.nm small { display: block; font-weight: normal; font-size: 8.5pt; color: #666 }
.contagem td.un { text-align: center; font-weight: bold; font-size: 14pt; width: 15mm }
.contagem td.fat { font-size: 9.5pt; width: 24mm; color: #333 }
.contagem td.qtd { width: 32mm; background: #fffdf3 }
.contagem td.obs { width: 38mm }
.contagem td.st { width: 7mm; text-align: center; font-size: 10pt; color: #fff; background: #2e7d32 }
.contagem tr.fora td.st { background: #bbb }
.sep td { background: #f3e3a8; font-weight: bold; font-size: 11pt; height: auto; padding: 1.5mm 2mm }
.lista td { font-size: 11pt; height: 11mm }
.lista td.n { text-align: right; white-space: nowrap }
.lista td.neg { color: #C8102E; font-weight: bold }
.lista td.box { width: 22mm; font-size: 11pt; white-space: nowrap }
.lista td small { color: #666; font-size: 8.5pt }
.nota { font-size: 9.5pt; color: #555; margin: 2mm 0 3mm; line-height: 1.4 }
"""


def _esc(s) -> str:
    import html
    return html.escape(str(s))


def _logo() -> str:
    import base64
    for f, t in ((RAIZ / "monitor/assets/logo_tili.jpg", "jpeg"), (RAIZ / "monitor/assets/logo_tili.png", "png")):
        if f.exists():
            return f"data:image/{t};base64," + base64.b64encode(f.read_bytes()).decode()
    return ""


def html_folha(a: dict) -> str:
    logo = _logo()
    gerado = datetime.fromisoformat(a["gerado"])
    por_area = {ar: [l for l in a["linhas"] if l["area"] == ar] for ar in AREAS}
    topo = (f'<div class="topo">{f"<img src={chr(34)}{logo}{chr(34)}>" if logo else ""}<div>'
            f'<div class="nome">TILI PIZZARIA</div><div class="sub">{_esc(TITULO)} · loja 150 · '
            f'dados do ALIV em {gerado:%d/%m/%Y %H:%M}<br>Porto Seguro-BA · WhatsApp (73) 99917-9941</div></div></div>'
            '<div class="faixa"></div>')
    n_area = "".join(f"<div>{_esc(ar)}<b>{len(ls)}</b>{sum(l['em_uso'] for l in ls)} em uso</div>"
                     for ar, ls in por_area.items())
    capa = f"""<div class="capa">{topo}
<h1>{_esc(TITULO)}</h1>
<div class="instr">Data da contagem: ____/____/______ &nbsp;&nbsp; Início: ____:____ &nbsp;&nbsp; Fim: ____:____</div>
<div class="resumo">{n_area}</div>
<ul class="instr">
<li><b>Conte na unidade da coluna UNID.</b> (a mesma da compra: caixa, fardo, quilo ou unidade). Caixa aberta: escreva a fração (ex.: 2,5) ou anote em OBS.</li>
<li><b>FATOR</b> mostra quanto 1 unidade de contagem vale na ficha do ALIV (ex.: 1 KG = 1.000 G). Não precisa converter.</li>
<li>Não achou o item: escreva <b>0</b>. Item sem linha: anote no fim da área.</li>
<li>Na coluna ✓, <b>verde = em uso nas fichas</b>; cinza = fora das fichas (ver Parte 2).</li>
<li>Depois, digite os números na planilha <b>{NOME}.xlsx</b> e mande lançar no ALIV.</li>
</ul>
<div class="nota">Parte 1: contagem por área ({len(a['linhas'])} itens). Parte 2: {len(a['sem_ficha'])} insumos fora das fichas
e {len(a['negativos'])} com saldo negativo — decidir se conta ou zera. Parte 3: {len(a['problemas'])} pizzas/lanches
sem ficha ou com ficha incompleta. {len(a['outros'])} itens de utensílio/equipamento/manutenção ficaram fora da contagem (Parte 2).</div>
<div class="ass"><div>Contado por</div><div>Conferido por</div><div>Emerson</div></div></div>"""

    # Parte 1
    p1 = []
    for ar, ls in por_area.items():
        if not ls:
            continue
        rows, mudou = [], None
        for l in ls:
            if l["em_uso"] != mudou:
                rows.append(f'<tr class="sep"><td colspan="6">{"EM USO NAS FICHAS" if l["em_uso"] else "FORA DAS FICHAS"}</td></tr>')
                mudou = l["em_uso"]
            sub = f"<small>ALIV: {_esc(l['nome_aliv'])}</small>" if norm(l["nome_aliv"]) != norm(l["nome"]) else ""
            rows.append(f'<tr class="{"" if l["em_uso"] else "fora"}"><td class="st">{"✓" if l["em_uso"] else "–"}</td>'
                        f'<td class="nm">{_esc(l["nome"])}{sub}</td><td class="un">{_esc(l["unidade"])}</td>'
                        f'<td class="fat">{_esc(l["equivale"])}</td><td class="qtd"></td><td class="obs"></td></tr>')
        p1.append(f"""<div class="area">{topo}<h2>{_esc(ar)}<span class="q">{len(ls)} itens · Contado por: ______________</span></h2>
<table class="contagem"><thead><tr><th>✓</th><th>INSUMO</th><th>UNID.</th><th>FATOR</th><th>QUANTIDADE</th><th>OBSERVAÇÃO</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>""")

    # Parte 2
    def lin2(l, extra=""):
        uso = "" if l["area"] != OUTROS else " · não é insumo de cozinha"
        return (f'<tr><td>{_esc(l["nome"])}<br><small>{_esc(l["area"])}{uso}{extra}</small></td>'
                f'<td class="n">{_esc(l["unidade"])}</td><td class="n {"neg" if l["saldo"] < 0 else ""}">{fmt_num(l["saldo"])}</td>'
                f'<td class="box">☐ contar</td><td class="box">☐ zerar</td></tr>')
    cab2 = '<thead><tr><th>INSUMO</th><th>UNID.</th><th>SALDO ALIV</th><th colspan="2">DECISÃO</th></tr></thead>'
    neg = "".join(lin2(l, " · em uso nas fichas" if l["em_uso"] else "") for l in a["negativos"])
    sf = "".join(lin2(l) for l in a["sem_ficha"])
    p2 = f"""<div class="parte">{topo}<h2>Parte 2 — Decidir: contar ou zerar</h2>
<div class="nota">Saldo = o que o ALIV acha que tem hoje. Marque uma opção por linha. “Zerar” = lançar 0 na conferência.
Itens de utensílio/equipamento não deveriam ser insumo: o ideal é pausar no ALIV.</div>
<h3>2A · Saldo negativo ({len(a['negativos'])})</h3><table class="lista">{cab2}<tbody>{neg or '<tr><td colspan=5>Nenhum.</td></tr>'}</tbody></table>
<h3>2B · No ALIV, mas fora de todas as fichas ({len(a['sem_ficha'])})</h3><table class="lista">{cab2}<tbody>{sf}</tbody></table></div>"""

    # Parte 3
    linhas3 = "".join(f'<tr><td><b>{_esc(p["nome"])}</b><br><small>{_esc(p["tipo"])} · {_esc(p["categoria"])}</small></td>'
                      f'<td>{"<br>".join(_esc(m) for m in p["motivos"])}</td><td class="box">☐ corrigido</td></tr>'
                      for p in a["problemas"])
    p3 = f"""<div class="parte">{topo}<h2>Parte 3 — Pizzas e lanches sem ficha ou com ficha incompleta</h2>
<div class="nota">Regras: ficha vazia em algum tamanho; pizza sem massa; lanche sem pão; sem embalagem; menos de 3 itens;
item com quantidade zero; insumo da ficha sem custo no ALIV. Ficha incompleta faz o estoque e o CMV saírem errados.</div>
<table class="lista"><thead><tr><th>PRODUTO</th><th>O QUE FALTA</th><th>OK</th></tr></thead>
<tbody>{linhas3 or '<tr><td colspan=3>Nenhum problema encontrado.</td></tr>'}</tbody></table></div>"""

    return (f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><title>{_esc(TITULO)}</title>'
            f'<style>{CSS}</style></head><body>{capa}{"".join(p1)}{p2}{p3}</body></html>')


def gerar_pdf(a: dict, destino: Path) -> Path:
    from diaristas import html_para_pdf
    return html_para_pdf(html_folha(a), destino)


# --------------------------------------------------------------- planilha
COLUNAS = ["ID ALIV", "Área", "Em uso", "Insumo", "Unid. contagem", "Fator p/ estoque ALIV", "Unid. estoque ALIV",
           "Equivale (ficha)", "Quantidade contada", "Observação"]


def gerar_xlsx(a: dict, destino: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "Contagem"
    vermelho, ouro, preto = "C8102E", "D4A017", "1A1A1A"
    ws.append([TITULO + f" · dados do ALIV em {datetime.fromisoformat(a['gerado']):%d/%m/%Y %H:%M}"])
    ws.append(["Digite só a coluna QUANTIDADE CONTADA (na unidade de contagem). Em branco = não contado (não é lançado). "
               "0 = contado e zerado. Fator: quantas unidades de estoque do ALIV vale 1 unidade de contagem (padrão 1)."])
    ws.append(COLUNAS)
    ws["A1"].font = Font(bold=True, size=14, color=vermelho)
    ws["A2"].font = Font(italic=True, size=9)
    fino = Side(style="thin", color="999999")
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=preto)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    amarelo = PatternFill("solid", fgColor="FFF6D6")
    for l in a["linhas"]:
        ws.append([l["id"], l["area"], "sim" if l["em_uso"] else "não", l["nome"], l["unidade"], 1, l["unidade"],
                   l["equivale"], None, None])
        r = ws.max_row
        ws.cell(r, 9).fill = amarelo
        for c in ws[r]:
            c.border = Border(top=fino, bottom=fino, left=fino, right=fino)
    larg = [9, 18, 8, 48, 10, 11, 10, 20, 14, 30]
    for i, w in enumerate(larg, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "E4"
    ws.auto_filter.ref = f"A3:J{ws.max_row}"
    dv = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=True,
                        showErrorMessage=True, errorTitle="Quantidade", error="Digite um número maior ou igual a 0.")
    ws.add_data_validation(dv)
    dv.add(f"I4:I{ws.max_row}")
    ws.row_dimensions[3].height = 30
    ws.sheet_properties.tabColor = ouro

    # abas de apoio (não são lidas pelo lançador)
    w2 = wb.create_sheet("Decidir (Parte 2)")
    w2.append(["ID ALIV", "Insumo", "Área", "Em uso", "Unid.", "Saldo ALIV", "Motivo", "Decisão (contar/zerar)"])
    vistos = set()
    for l in a["negativos"] + a["sem_ficha"]:
        if l["id"] in vistos:
            continue
        vistos.add(l["id"])
        mot = "saldo negativo" if l["saldo"] < 0 else "fora das fichas"
        if l["saldo"] < 0 and not l["em_uso"]:
            mot = "saldo negativo e fora das fichas"
        w2.append([l["id"], l["nome"], l["area"], "sim" if l["em_uso"] else "não", l["unidade"], l["saldo"], mot, None])
    w3 = wb.create_sheet("Fichas (Parte 3)")
    w3.append(["Tipo", "Produto", "Categoria", "O que falta"])
    for p in a["problemas"]:
        w3.append([p["tipo"], p["nome"], p["categoria"], "; ".join(p["motivos"])])
    for w in (w2, w3):
        for c in w[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=vermelho)
        for col, wd in zip("ABCDEFGH", (9, 48, 20, 8, 8, 12, 30, 22)):
            w.column_dimensions[col].width = wd
    destino.unlink(missing_ok=True)
    wb.save(destino)
    return destino


# --------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, help="JSON com os dados coletados (lê se existir, grava se não)")
    ap.add_argument("--saida", type=Path, default=SAIDA)
    args = ap.parse_args()

    if args.cache and args.cache.exists():
        dados = json.loads(args.cache.read_text())
    else:
        if not os.environ.get("ALIV_USER") or not os.environ.get("ALIV_PASS"):
            print("Faltam ALIV_USER/ALIV_PASS.")
            return 2
        try:
            dados = coletar(Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"], timeout=60))
        except AlivError as e:
            print(f"Erro no ALIV: {e}")
            return 1
        if args.cache:
            args.cache.parent.mkdir(parents=True, exist_ok=True)
            args.cache.write_text(json.dumps(dados, ensure_ascii=False))

    a = analisar(dados)
    args.saida.mkdir(parents=True, exist_ok=True)
    pdf = gerar_pdf(a, args.saida / f"{NOME}.pdf")
    xlsx = gerar_xlsx(a, args.saida / f"{NOME}.xlsx")
    print(f"PDF: {pdf}\nPlanilha: {xlsx}")
    print(f"Contagem: {len(a['linhas'])} itens ({sum(l['em_uso'] for l in a['linhas'])} em uso) · "
          + " · ".join(f"{ar} {sum(l['area'] == ar for l in a['linhas'])}" for ar in AREAS))
    print(f"Parte 2: {len(a['sem_ficha'])} fora das fichas · {len(a['negativos'])} negativos · "
          f"{len(a['outros'])} utensílios/equipamentos")
    print(f"Parte 3: {len(a['problemas'])} pizzas/lanches com ficha faltando ou incompleta")
    return 0


if __name__ == "__main__":
    sys.exit(main())
