#!/usr/bin/env python3
"""Curva ABC dos sabores de pizza — Tili Pizzaria (ALIV loja 150). SÓ LEITURA no ALIV.

Pedido do Emerson (20/11/2026): pizzas vendidas por sabor nos últimos 90 dias, com meio a meio = 0,5
para cada sabor, separadas por tamanho e por canal (iFood, cardápio próprio, balcão/WhatsApp no PDV);
o dia 10/10 (aniversário, pizza em dobro) fica à parte, fora do ranking. Para cada sabor: quantidade,
faturamento, % do total, % acumulado (curva ABC) e, com ficha técnica, custo e margem por pizza.
Também: insumos que só existem por causa de 1 ou 2 sabores fracos, cardápio enxuto (MANTER, CORTAR,
JUNTAR) e sabores sem ficha.

Lê (GET): pedidos (/admin/api/orders/audit + /admin/api/orders/{id}), cardápio, fichas e estoque.
Os pedidos ficam guardados em --cache (um JSON por data; contém dados de clientes: NÃO versionar).

Como conta:
- Dia operacional = 06:00 até 05:59 do dia seguinte (a loja abre às 16:00 e fecha de madrugada).
- Pedido cancelado não entra.
- Faturamento da pizza = preço do item no pedido (iFood = preço de vitrine, antes de comissão e
  cupom). Em combo com bebida, o valor do item é dividido entre pizzas e bebida pela proporção
  dos preços de cardápio. Borda paga fica com a pizza. Dentro da pizza, cada sabor leva a sua fração.
- Custo = ficha técnica do ALIV no tamanho (× fração). Sem ficha, fica em branco.

Uso: cardapio_abc.py [--dias 90] [--cache PASTA] [--saida monitor/cardapio] [--whatsapp]
Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contagem  # noqa: E402
from fichas_pendentes import precos  # noqa: E402
from monitor import TZ, Aliv, AlivError  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ANIVERSARIO = date(2026, 10, 10)
VERMELHO, OURO, PRETO = "#C8102E", "#D4A017", "#1A1A1A"
TAMS = ["Grande", "Média", "Pequena"]
CANAIS = ["iFood", "Cardápio próprio", "Balcão/WhatsApp (PDV)"]
# bebida que vem no combo → preço de cardápio (só para dividir o valor do combo)
BEBIDAS = [(r"2 ?l\b|2 litros", 18.0), (r"1[,.]5 ?l", 16.0), (r"suco.*1 ?l|1 ?l.*suco|suco de laranja 1", 24.0),
           (r"1 ?l\b", 12.0), (r"lata|350 ?ml", 6.99), (r"300 ?ml", 7.0)]
# insumos de base (estão em quase toda pizza): não entram na análise de insumo exclusivo
BASE = ("massa", "molho de tomate", "mussarela", "mucarela", "oregano", "azeitona", "caixa", "embalagem",
        "sache", "mesinha", "farinha", "fermento", "oleo", "sal ", "acucar")
# sabores sem ficha: insumo provável pelo nome (para o item 3)
PROVAVEL = {"Romeu e Julieta": ["GOIABADA"], "Chocolate com Serenata de Amor": ["SERENATA DE AMOR"],
            "Confete": ["CONFETE"], "Marshmallows": ["MARSHMALLOW"], "Peito de Peru Especial": ["PEITO DE PERU"],
            "Peito de Peru Tropical": ["PEITO DE PERU", "ABACAXI"], "Banana Com Canela": ["BANANA PRATA", "CANELA"],
            "Chocolate com Banana": ["BANANA PRATA"], "Chocolate com Morango": ["MORANGO"],
            "Nutella com Morango": ["NUTELLA", "MORANGO"], "Palmito": ["PALMITO"], "Brócolis": ["BRÓCOLIS"]}

ALIAS = {
    "frango ao catupiry": "Frango com Catupiry Original", "frango catupiry": "Frango com Catupiry Original",
    "frango com catupiry": "Frango com Catupiry Original", "marguerita": "Margherita", "margarita": "Margherita",
    "mussarela": "Muçarela", "mucarela": "Muçarela", "calabresa catupiry": "Calabresa com Catupiry Original",
    "calabresa com catupiry": "Calabresa com Catupiry Original", "choco": "Chocolate",
    "lombinho": "Lombinho Canadense", "presunto com catupiry": "Presunto com Catupiry Original",
    "frango champignon": "Frango com Champignon e Catupiry Original",
    "frango com champignon": "Frango com Champignon e Catupiry Original", "quatro queijos": "4 Queijos",
    "tres queijos": "3 Queijos", "black calabresa": "Calabresa",
    "serenata de amor": "Chocolate com Serenata de Amor", "banana comcanela": "Banana Com Canela", "banana con canela": "Banana Com Canela",
}
NAO_SABOR = ("borda", "coca", "suco", "guarana", "refrigerante", "fanta", "pepsi", "agua", "massa", "sprite", "kuat")


def n(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ]", " ", s.lower())).strip()


def parse_dt(s) -> datetime | None:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4}) (?:às )?(\d{2}):(\d{2})", str(s or ""))
    return datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4]), int(m[5])) if m else None


# ------------------------------------------------------------------ coleta
def baixar(api: Aliv, ini: date, fim: date, cache: Path) -> None:
    """Baixa lista + detalhe dos pedidos de cada data (calendário) e guarda em cache/AAAA-MM-DD.json."""
    cache.mkdir(parents=True, exist_ok=True)
    hoje = datetime.now(TZ).date()
    d = ini
    while d <= fim:
        arq = cache / f"{d}.json"
        if not arq.exists() or d >= hoje - timedelta(days=1):
            brutos: dict = {}
            for page in range(1, 300):
                r = api.get("/admin/api/orders/audit", {"start_date": d.isoformat(), "end_date": d.isoformat(),
                                                         "page": page})
                lote = r.get("orders") if isinstance(r, dict) else r
                if not lote:
                    break
                for o in lote:
                    brutos.setdefault(o["id"], o)

            def det(i):
                try:
                    x = api.get(f"/admin/api/orders/{i}")
                    return x["order"] if isinstance(x, dict) and isinstance(x.get("order"), dict) else x
                except AlivError as e:
                    return {"_erro": str(e)}
            with ThreadPoolExecutor(8) as ex:
                dets = list(ex.map(det, brutos))
            tmp = arq.with_suffix(".tmp")
            tmp.write_text(json.dumps([{"lista": o, "det": x} for o, x in zip(brutos.values(), dets)],
                                      ensure_ascii=False))
            tmp.rename(arq)
            print(d, len(brutos), "pedidos", flush=True)
        d += timedelta(days=1)


# ------------------------------------------------------------------ leitura dos sabores
class Leitor:
    def __init__(self, fichas: dict, menu: dict):
        self.sabores = {p["id"]: p["nome"] for p in fichas["produtos"] if p["pizza"]}
        self.tam = {str(s["id"]): s["name"].split()[0] for s in menu["sizes"]}
        self.nomes = sorted([(n(v), v) for v in self.sabores.values()] + list(ALIAS.items()), key=lambda x: -len(x[0]))
        pr = precos(menu)
        self.preco = {self.sabores[i]: {k.split()[0]: v for k, v in pr.get(i, {}).items()} for i in self.sabores}
        self.nao_achados: Counter = Counter()

    def sabor(self, txt) -> str | None:
        t = " " + n(txt) + " "
        if any(w in t for w in NAO_SABOR) and not re.search(r"pizza|1/2", t):
            return None
        for k, v in self.nomes:
            if " " + k + " " in t:
                return v
        return None

    def todos(self, txt) -> list[str]:
        t = " " + n(txt) + " "
        achados = []
        for k, v in self.nomes:
            i = t.find(" " + k + " ")
            if i >= 0:
                achados.append((i, v))
                t = t[:i] + " " + "#" * len(k) + " " + t[i + len(k) + 2:]
        return [v for _, v in sorted(achados)]

    @staticmethod
    def tamanho(txt, padrao=None):
        t = " " + n(txt) + " "
        if re.search(r" (g|8 fatias|8 pedacos|35cm) ", t) or "grande" in t:
            return "Grande"
        if re.search(r" (m|6 fatias|6 pedacos|30cm) ", t) or "media" in t:
            return "Média"
        if re.search(r" (p|4 fatias|4 pedacos|25cm) ", t) or "pequena" in t:
            return "Pequena"
        return padrao

    def pizzas(self, i: dict, plat: str) -> list[tuple[str, list[tuple[str, float]]]]:
        """Item do pedido → [(tamanho, [(sabor, fração)])]."""
        ti = i.get("title") or i.get("name") or ""
        tam_item = self.tamanho(ti)
        parts = i.get("parts") or []
        if parts and not any(self.sabor(p.get("name")) for p in parts):
            parts = []
        cd = i.get("combo_data") or []
        out = []
        if parts:
            metades = [p for p in parts if re.match(r"\s*1/2", p.get("name") or "")]
            multi = re.search(r"(\d+)\s*pizzas", n(ti)) or "combo" in n(ti) or "familia" in n(ti)
            if metades and len(metades) == len(parts):
                for k in range(0, len(parts), 2):
                    g = parts[k:k + 2]
                    out.append((self.tamanho(g[0]["name"], tam_item), [(p["name"], 1 / len(g)) for p in g]))
            elif multi and len(parts) > 1:
                out += [(self.tamanho(p["name"], tam_item), [(p["name"], 1.0)]) for p in parts]
            else:
                out.append((tam_item or self.tamanho(parts[0]["name"]), [(p["name"], 1 / len(parts)) for p in parts]))
        elif cd:
            for g in cd:
                its = [it for it in g.get("items") or [] if it.get("id") in self.sabores or self.sabor(it.get("name"))]
                if not its:
                    continue
                gn = n(g.get("name"))
                if gn == "sabores" or "pizza" in gn:
                    tot = sum(float(it.get("qty") or 1) for it in its)
                    tm = (self.tam.get(str(its[0].get("size_id"))) or self.tamanho(its[0]["name"])
                          or self.tamanho(g.get("name")) or tam_item)
                    out.append((tm, [(self.sabores.get(it.get("id"), it["name"]), float(it.get("qty") or 1) / tot)
                                     for it in its]))
                else:   # "Escolha um item", "Itens do Combo": cada sabor é uma pizza inteira
                    for it in its:
                        for _ in range(int(float(it.get("qty") or 1))):
                            out.append((self.tamanho(it["name"], tam_item or "Grande"),
                                        [(self.sabores.get(it.get("id"), it["name"]), 1.0)]))
        elif self.sabor(ti) and (re.search(r"pizza|promocao", n(ti)) or n(ti) == n(self.sabor(ti))):
            for seg in ti.split("+"):     # combo do iFood só com título
                fl = self.todos(seg)
                if fl:
                    m = re.search(r"(\d+)\s*pizzas", n(seg))
                    for _ in range(int(m[1]) if m else 1):
                        out.append((self.tamanho(seg, "Grande"), [(f, 1 / len(fl)) for f in fl]))
        res = []
        for tm, sb in out:
            lst = []
            for nome, fr in sb:
                s = nome if nome in self.preco else self.sabor(nome)
                if not s:
                    self.nao_achados[(plat, ti, nome)] += 1
                    continue
                lst.append((s, fr))
            if lst:
                tot = sum(fr for _, fr in lst)
                res.append((tm or "Grande", [(s, fr / tot) for s, fr in lst]))
        return res

    def valor_ref(self, tam: str, sb: list) -> float:
        return sum(fr * (self.preco.get(s, {}).get(tam) or 70.0) for s, fr in sb)


def bebida_ref(i: dict) -> float:
    txt = n(i.get("title") or "") + " " + " ".join(n(it.get("name")) for g in i.get("combo_data") or []
                                                   for it in g.get("items") or [] if re.search(
                                                       r"coca|suco|refri|guarana|fanta|pepsi", n(it.get("name"))))
    if not re.search(r"coca|suco|refri|guarana|fanta|pepsi", txt):
        return 0.0
    for rx, v in BEBIDAS:
        if re.search(rx, txt):
            return v
    return 12.0


def linhas_de_pizza(cache: Path, ini: date, fim: date, leitor: Leitor) -> list[dict]:
    """Uma linha por sabor de cada pizza vendida no dia operacional ini..fim (inclusive)."""
    out, vistos = [], set()
    for arq in sorted(cache.glob("*.json")):
        try:
            d0 = date.fromisoformat(arq.stem)
        except ValueError:
            continue
        if d0 < ini or d0 > fim + timedelta(days=1):
            continue
        for x in json.loads(arq.read_text()):
            d = x["det"]
            if "_erro" in d or d.get("id") in vistos or str(d.get("status") or "").upper().startswith("CANCEL"):
                continue
            vistos.add(d.get("id"))
            cr = parse_dt(d.get("created_at_fmt") or x["lista"].get("created_at"))
            if not cr:
                continue
            dia = (cr - timedelta(hours=6)).date()
            if not ini <= dia <= fim:
                continue
            plat = d.get("platform_slug")
            canal = {"ifood": "iFood", "app": "Cardápio próprio"}.get(plat, "Balcão/WhatsApp (PDV)")
            for i in d.get("items_json") or []:
                pz = leitor.pizzas(i, plat)
                if not pz:
                    continue
                q = float(i.get("quantity") or 1)
                rs = float(i.get("price") or 0) * q
                refs = [leitor.valor_ref(tm, sb) for tm, sb in pz]
                beb = bebida_ref(i)
                for (tm, sb), ref in zip(pz, refs):
                    rs_pz = rs * ref / (sum(refs) + beb) if sum(refs) + beb else 0
                    for s, fr in sb:
                        out.append({"pedido": d["id"], "dia": dia, "canal": canal, "tam": tm, "sabor": s,
                                    "qtd": fr * q, "rs": rs_pz * fr, "item": i.get("title") or i.get("name")})
    return out


# ------------------------------------------------------------------ análise
def custos(fichas: dict) -> tuple[dict, dict]:
    """sabor → {tam: custo da ficha}, sabor → {tam: [insumos]} (só sabores com ficha)."""
    c, its = {}, {}
    for p in fichas["produtos"]:
        if not p["pizza"]:
            continue
        for k, v in p["fichas"].items():
            if v:
                c.setdefault(p["nome"], {})[k.split()[0]] = sum(float(i.get("custo") or 0) for i in v)
                its.setdefault(p["nome"], {})[k.split()[0]] = v
    return c, its


def analisar(L: list[dict], fichas: dict, leitor: Leitor) -> dict:
    custo, itens_ficha = custos(fichas)
    # ficha só com massa/molho/queijo/caixa: falta o recheio → custo e margem não valem
    incompletas = {s for s, pt in itens_ficha.items() if n(s) != "mucarela" and not any(not any(b in " " + n(i["nome"]) + " " for b in BASE) and n(i["nome"]) != "mussarela"
                              for v in pt.values() for i in v)}
    rank = [x for x in L if x["dia"] != ANIVERSARIO]
    aniv = [x for x in L if x["dia"] == ANIVERSARIO]
    dias = sorted({x["dia"] for x in L})
    ag = defaultdict(lambda: {"qtd": 0.0, "rs": 0.0, "custo": 0.0, "qtd_c": 0.0,
                              "tam": Counter(), "canal": Counter(), "canal_rs": Counter(), "tam_rs": Counter()})
    for x in rank:
        a = ag[x["sabor"]]
        a["qtd"] += x["qtd"]
        a["rs"] += x["rs"]
        a["tam"][x["tam"]] += x["qtd"]
        a["tam_rs"][x["tam"]] += x["rs"]
        a["canal"][x["canal"]] += x["qtd"]
        a["canal_rs"][x["canal"]] += x["rs"]
        cu = custo.get(x["sabor"], {}).get(x["tam"])
        if cu:
            a["custo"] += cu * x["qtd"]
            a["qtd_c"] += x["qtd"]
    for s in leitor.preco:              # sabores do cardápio que não venderam
        ag[s]
    total = sum(a["rs"] for a in ag.values())
    lista = sorted(({"sabor": s, **a} for s, a in ag.items()), key=lambda r: (-r["rs"], -r["qtd"], r["sabor"]))
    acum = 0.0
    for i, r in enumerate(lista, 1):
        r["pos"] = i
        r["pct"] = 100 * r["rs"] / total if total else 0
        acum += r["pct"]
        r["acum"] = acum
        r["classe"] = "A" if acum - r["pct"] < 80 else ("B" if acum - r["pct"] < 95 else "C")
        r["preco_medio"] = r["rs"] / r["qtd"] if r["qtd"] else 0
        r["tem_ficha"] = r["sabor"] in custo and r["sabor"] not in incompletas
        r["ficha"] = "completa" if r["tem_ficha"] else ("só a base" if r["sabor"] in incompletas else "sem ficha")
        if r["qtd_c"] and r["tem_ficha"]:
            cpp = r["custo"] / r["qtd_c"]
            rs_c = sum(x["rs"] for x in rank if x["sabor"] == r["sabor"] and custo.get(r["sabor"], {}).get(x["tam"]))
            ppp = rs_c / r["qtd_c"]
            r["custo_pizza"], r["margem_pizza"] = cpp, ppp - cpp
            r["margem_pct"] = 100 * (ppp - cpp) / ppp if ppp else 0
        else:
            g = custo.get(r["sabor"], {}).get("Grande") if r["tem_ficha"] else None
            r["custo_pizza"] = g
            r["margem_pizza"] = (leitor.preco[r["sabor"]].get("Grande", 0) - g) if g else None
            r["margem_pct"] = None
        r["por_dia"] = r["qtd"] / max(1, len([d for d in dias if d != ANIVERSARIO]))
        r["por_semana"] = 7 * r["por_dia"]

    # insumos: quem usa cada insumo (fichas de pizza + o resto do cardápio)
    nome_ins = {str(i["id"]): i.get("name") for i in fichas["insumos"]}
    usa_pizza = defaultdict(set)
    for s, por_tam in itens_ficha.items():
        for v in por_tam.values():
            for i in v:
                usa_pizza[str(i["ingredient_id"])].add(s)
    usa_outros = defaultdict(set)
    for p in fichas["produtos"]:
        if not p["pizza"]:
            for v in p["fichas"].values():
                for i in v:
                    usa_outros[str(i["ingredient_id"])].add(p["nome"])
    for a in fichas["adicionais"]:
        for iid in a["ingredientes"]:
            usa_outros[str(iid)].add("adicional " + a["nome"])
    classe = {r["sabor"]: r for r in lista}
    for r in lista:
        r["fraco"] = r["classe"] == "C" or r["por_dia"] < 0.3
    insumos = []
    for iid, ss in usa_pizza.items():
        nome = nome_ins.get(iid) or next((i["nome"] for v in itens_ficha[next(iter(ss))].values() for i in v
                                          if str(i["ingredient_id"]) == iid), iid)
        if any(b in " " + n(nome) + " " for b in BASE) or len(ss) > 2:
            continue
        fracos = [s for s in ss if classe[s]["fraco"]]
        if fracos and len(fracos) == len(ss):
            insumos.append({"insumo": nome, "sabores": sorted(ss), "rs": sum(classe[s]["rs"] for s in ss),
                            "qtd": sum(classe[s]["qtd"] for s in ss), "outros": sorted(usa_outros.get(iid, [])),
                            "fonte": "ficha"})
    for s, ins in PROVAVEL.items():
        if s in classe and classe[s]["fraco"]:
            for nm in ins:
                if not any(nm.lower() in x["insumo"].lower() for x in insumos):
                    outros = [x for x, ps in PROVAVEL.items() if nm in ps and x != s]
                    ss = sorted({s, *outros})
                    if len(ss) <= 2 and all(classe.get(o, {}).get("fraco") for o in ss):
                        insumos.append({"insumo": nm.title(), "sabores": ss, "rs": sum(classe[o]["rs"] for o in ss),
                                        "qtd": sum(classe[o]["qtd"] for o in ss), "outros": [], "fonte": "sem ficha (pelo nome)"})
    insumos.sort(key=lambda x: x["rs"])

    def resumo(lin):
        c = defaultdict(lambda: [0.0, 0.0])
        for x in lin:
            c[(x["canal"], x["tam"])][0] += x["qtd"]
            c[(x["canal"], x["tam"])][1] += x["rs"]
        return c
    aniv_s = defaultdict(lambda: [0.0, 0.0])
    for x in aniv:
        aniv_s[x["sabor"]][0] += x["qtd"]
        aniv_s[x["sabor"]][1] += x["rs"]
    pizzas_aniv = len({(x["pedido"], x["item"]) for x in aniv})
    return {"lista": lista, "total": total, "pizzas": sum(r["qtd"] for r in lista), "dias": dias,
            "por_canal_tam": resumo(rank), "aniv": sorted(aniv_s.items(), key=lambda kv: -kv[1][0]),
            "aniv_qtd": sum(v[0] for v in aniv_s.values()), "aniv_rs": sum(v[1] for v in aniv_s.values()),
            "aniv_itens": pizzas_aniv, "insumos": insumos,
            "sem_ficha": [r for r in lista if not r["tem_ficha"]], "nao_achados": leitor.nao_achados,
            "n_dias": len([d for d in dias if d != ANIVERSARIO])}


# ------------------------------------------------------------------ sugestão (regras + revisão)
JUNTAR = [   # (sabores parecidos, motivo) — fica o que mais vende no grupo
    (["Baiana", "Baiana Especial", "Baiana Premium"], "Especial e Premium têm a mesma ficha (calabresa, pimenta, ovo, bacon)"),
    (["Frango", "Frango Especial", "Frango Apimentado"], "o mesmo frango; Especial = + Catupiry, Apimentado = + pimenta"),
    (["Mista", "Presunto", "Bauru", "Presunto Especial", "Presunto com Catupiry Original"], "presunto e queijo em 5 versões"),
    (["Lombinho Canadense", "Lombinho Especial"], "o mesmo lombinho; a Especial leva ervilha, ovo e pimentão"),
    (["4 Queijos", "3 Queijos"], "queijos parecidos; a 3 Queijos é a única que usa cheddar cremoso fora do Frango c/ Cheddar"),
    (["Nutella com Morango", "Chocolate com Morango"], "o mesmo morango fresco, que estraga rápido"),
    (["Chocolate com Banana", "Banana Com Canela"], "a mesma banana prata"),
    (["Vegetariana", "Palmito", "Brócolis", "Italiana"], "vegetais parecidos; nenhuma vende bem sozinha"),
]


def sugestao(a: dict) -> dict:
    por = {r["sabor"]: r for r in a["lista"]}
    juntar, sai_todos, nos_grupos = [], set(), set()
    for grupo, motivo in JUNTAR:
        g = sorted((s for s in grupo if s in por), key=lambda s: -por[s]["rs"])
        if len(g) < 2:
            continue
        fica, sai = g[0], g[1:]
        juntar.append({"grupo": g, "fica": fica, "sai": sai, "motivo": motivo,
                       "rs_sai": sum(por[s]["rs"] for s in sai), "qtd_sai": sum(por[s]["qtd"] for s in sai)})
        sai_todos.update(sai)
        nos_grupos.update(g)
    cortar = [r for r in a["lista"] if r["classe"] == "C" and r["sabor"] not in nos_grupos]
    manter = [r for r in a["lista"] if r["sabor"] not in sai_todos and r not in cortar]
    for r in cortar:
        mot = f"{nf(r['qtd'], 0)} pizzas em {a['n_dias']} dias ({nf(r['por_semana'], 1)}/semana)"
        if not r["tem_ficha"]:
            mot += "; " + r["ficha"]
        r["motivo"] = mot
    for r in manter:
        r["motivo"] = (f"classe {r['classe']}: {nf(r['pct'], 1)}% do faturamento, {nf(r['por_semana'], 0)} pizzas/semana")
    return {"manter": manter, "cortar": cortar, "juntar": juntar,
            "rs_cortar": sum(r["rs"] for r in cortar),
            "rs_juntar": sum(j["rs_sai"] for j in juntar),
            "pct_cortar": 100 * sum(r["rs"] for r in cortar) / a["total"] if a["total"] else 0,
            "pct_juntar": 100 * sum(j["rs_sai"] for j in juntar) / a["total"] if a["total"] else 0}


# ------------------------------------------------------------------ saída
E = html.escape


def rs(v, casas=0) -> str:
    return ("R$ " + f"{v:,.{casas}f}").replace(",", "X").replace(".", ",").replace("X", ".")


def nf(v, casas=0) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def html_pdf(a: dict, sg: dict, ini: date, fim: date, agora: datetime) -> str:
    logo = contagem._logo()
    lista = a["lista"]
    metade = (len(lista) + 1) // 2

    def tabela(rows):
        tr = []
        for r in rows:
            cor = {"A": VERMELHO, "B": OURO, "C": "#888"}[r["classe"]]
            mg = (rs(r["margem_pizza"]) if r.get("margem_pizza") is not None and r["tem_ficha"] else r["ficha"])
            tr.append(f"<tr><td class=n>{r['pos']}</td><td><b class=cl style='background:{cor}'>{r['classe']}</b> "
                      f"{E(r['sabor'])}</td><td class=n>{nf(r['qtd'], 1 if r['qtd'] % 1 else 0)}</td>"
                      f"<td class=n>{nf(r['rs'] / 1000, 1)}</td><td class=n>{nf(r['pct'], 1)}%</td>"
                      f"<td class=n>{nf(r['acum'], 0)}%</td><td class=n>{mg}</td></tr>")
        return ("<table class=rk><tr><th>#</th><th>Sabor</th><th>Pizzas</th><th>R$ mil</th><th>%</th><th>Acum.</th>"
                "<th>Margem/pizza</th></tr>" + "".join(tr) + "</table>")

    pct_canal = Counter()
    pct_tam = Counter()
    for (c, t), (q, v) in a["por_canal_tam"].items():
        pct_canal[c] += v
        pct_tam[t] += q
    qtot = sum(pct_tam.values())
    canais = " · ".join(f"<b>{E(c)}</b> {nf(100 * pct_canal[c] / a['total'], 0)}%" for c in CANAIS)
    tams = " · ".join(f"<b>{t}</b> {nf(100 * pct_tam[t] / qtot, 0)}%" for t in TAMS)
    cel = a["por_canal_tam"]
    tab_ct = ("<table class=rk><tr><th>Canal</th>" + "".join(f"<th class=n>{t}</th>" for t in TAMS) +
              "<th class=n>Total</th><th class=n>R$ mil</th></tr>" + "".join(
                  f"<tr><td>{E(c)}</td>" + "".join(f"<td class=n>{nf(cel.get((c, t), [0, 0])[0], 0)}</td>" for t in TAMS) +
                  f"<td class=n><b>{nf(sum(cel.get((c, t), [0, 0])[0] for t in TAMS), 0)}</b></td>"
                  f"<td class=n>{nf(sum(cel.get((c, t), [0, 0])[1] for t in TAMS) / 1000, 1)}</td></tr>" for c in CANAIS) +
              "</table>")
    nA = sum(1 for r in lista if r["classe"] == "A")
    nC = sum(1 for r in lista if r["classe"] == "C")
    corta = "".join(f"<li><b>{E(r['sabor'])}</b> — {E(r['motivo'])}</li>" for r in sg["cortar"])
    junta = "".join(f"<li>Fica <b>{E(j['fica'])}</b>; sai {', '.join(E(s) for s in j['sai'])} "
                    f"({nf(j['qtd_sai'], 0)} pizzas) — {E(j['motivo'])}</li>" for j in sg["juntar"])
    mant = ", ".join(E(r["sabor"]) for r in sg["manter"])
    ins = "".join(f"<li><b>{E(x['insumo'])}</b> — só {', '.join(E(s) for s in x['sabores'])} "
                  f"({nf(x['qtd'], 0)} pizzas){' · também em ' + E(', '.join(x['outros'][:2])) if x['outros'] else ''}"
                  f"{' <i>(pelo nome)</i>' if x['fonte'] != 'ficha' else ''}</li>" for x in a["insumos"])
    semf = ", ".join(f"{E(r['sabor'])} ({nf(r['qtd'], 0)}{'; só a base' if r['ficha'] == 'só a base' else ''})"
                     for r in a["sem_ficha"])
    aniv = ", ".join(f"{E(s)} {nf(q, 0)}" for s, (q, v) in a["aniv"][:8])
    return f"""<!doctype html><html><head><meta charset=utf-8><style>
@page {{ size: A4 landscape; margin: 9mm 10mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Arial, Helvetica, sans-serif; color: {PRETO}; font-size: 12.5px; margin: 0; }}
.top {{ display: flex; align-items: center; gap: 12px; border-bottom: 4px solid {VERMELHO}; padding-bottom: 4px; }}
.top img {{ height: 46px; }} h1 {{ font-size: 24px; margin: 0; color: {VERMELHO}; }}
.sub {{ font-size: 13px; }}
.kpi {{ display: flex; gap: 8px; margin: 6px 0; }}
.kpi div {{ flex: 1; background: {PRETO}; color: #fff; border-radius: 6px; padding: 4px 8px; font-size: 12px; }}
.kpi b {{ display: block; font-size: 20px; color: {OURO}; }}
.cols {{ display: flex; gap: 10px; }} .cols > * {{ flex: 1; }}
table.rk {{ border-collapse: collapse; width: 100%; font-size: 12.5px; }}
.rk th {{ background: {VERMELHO}; color: #fff; padding: 3px 4px; text-align: left; }}
.rk td {{ padding: 2.2px 4px; border-bottom: 1px solid #ddd; }}
.n {{ text-align: right; white-space: nowrap; }}
.cl {{ color: #fff; border-radius: 3px; padding: 0 4px; font-size: 11px; }}
.pg2 {{ page-break-before: always; }}
h2 {{ font-size: 17px; margin: 6px 0 3px; padding: 2px 8px; color: #fff; border-radius: 4px; }}
.m {{ background: {PRETO}; }} .c {{ background: {VERMELHO}; }} .j {{ background: {OURO}; color: {PRETO}; }}
ul {{ margin: 2px 0 4px 16px; padding: 0; }} li {{ margin: 1.5px 0; }}
.box {{ border: 2px solid {OURO}; border-radius: 6px; padding: 4px 8px; margin-top: 5px; }}
.big {{ font-size: 15px; }} .nota {{ font-size: 10.5px; color: #555; margin-top: 4px; }}
</style></head><body>
<div class=top>{f'<img src="{logo}">' if logo else ''}<div><h1>Curva ABC dos sabores — Tili Pizzaria</h1>
<div class=sub>Dias {ini:%d/%m} a {fim:%d/%m/%Y} ({len([d for d in a['dias'] if d != ANIVERSARIO])} dias, sem o 10/10) ·
meio a meio = 0,5 por sabor · gerado {agora:%d/%m/%Y %H:%M}</div></div></div>
<div class=kpi><div>Pizzas vendidas<b>{nf(a['pizzas'], 0)}</b></div><div>Faturamento das pizzas<b>{rs(a['total'])}</b></div>
<div>Classe A (80% do R$)<b>{nA} sabores</b></div><div>Classe C (últimos 5%)<b>{nC} sabores</b></div>
<div>Proposta: cortar + juntar<b>{nf(sg['pct_cortar'] + sg['pct_juntar'], 1)}% do R$</b></div></div>
<div class=sub style="margin-bottom:4px">Canal (R$): {canais} &nbsp;|&nbsp; Tamanho (pizzas): {tams}</div>
<div class=cols>{tabela(lista[:metade])}{tabela(lista[metade:])}</div>
<div class=nota>Margem/pizza = preço médio vendido − custo da ficha do ALIV (sem taxa do iFood, embalagem extra e borda).
iFood pelo preço de vitrine. Em combo com bebida, o valor foi dividido pela proporção dos preços do cardápio.</div>

<div class=pg2></div>
<div class=top>{f'<img src="{logo}">' if logo else ''}<div><h1>Cardápio enxuto — sugestão</h1>
<div class=sub>Nada foi alterado no ALIV. Cortados: <b>{rs(sg['rs_cortar'])}</b> ({nf(sg['pct_cortar'], 1)}% do faturamento
de pizza em 90 dias) · sabores que somem ao juntar: <b>{rs(sg['rs_juntar'])}</b> ({nf(sg['pct_juntar'], 1)}%) — a maior
parte migra para o sabor que fica.</div></div></div>
<div class=cols>
<div><h2 class=c>CORTAR ({len(sg['cortar'])})</h2><ul>{corta}</ul>
<h2 class=j>JUNTAR ({len(sg['juntar'])} grupos)</h2><ul>{junta}</ul>
<h2 class=m>Pizzas por canal e tamanho (sem o 10/10)</h2>{tab_ct}</div>
<div><h2 class=m>MANTER ({len(sg['manter'])})</h2><div class=big>{mant}</div>
<h2 class=c>Insumos que só existem por 1–2 sabores fracos</h2><ul>{ins or '<li>nenhum</li>'}</ul>
<h2 class=m>Sem ficha técnica ({len(a['sem_ficha'])})</h2><div>{semf}</div>
<div class=box><b>10/10 — aniversário (pizza em dobro), fora do ranking:</b> {nf(a['aniv_qtd'], 0)} pizzas,
{rs(a['aniv_rs'])}. Mais pedidos: {aniv}.</div></div></div>
</body></html>"""


def gerar_xlsx(a: dict, sg: dict, L: list[dict], destino: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    cab = PatternFill("solid", fgColor=VERMELHO[1:])

    def aba(ws, titulo, linhas):
        ws.append(titulo)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), cab
        for l in linhas:
            ws.append(l)
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = max(10, min(45, max(len(str(c.value or "")) for c in col) + 2))
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Curva ABC"
    aba(ws, ["#", "Sabor", "Classe", "Pizzas", "Faturamento R$", "% do total", "% acumulado", "Pizzas/dia",
             "Preço médio R$", "Custo ficha/pizza R$", "Margem/pizza R$", "Margem %", "Ficha técnica"] +
        [f"Pizzas {t}" for t in TAMS] + [f"Pizzas {c}" for c in CANAIS] + [f"R$ {c}" for c in CANAIS],
        [[r["pos"], r["sabor"], r["classe"], round(r["qtd"], 2), round(r["rs"], 2), round(r["pct"], 2),
          round(r["acum"], 2), round(r["por_dia"], 2), round(r["preco_medio"], 2),
          round(r["custo_pizza"], 2) if r.get("custo_pizza") else None,
          round(r["margem_pizza"], 2) if r.get("margem_pizza") is not None and r["tem_ficha"] else None,
          round(r["margem_pct"], 1) if r.get("margem_pct") is not None else None, r["ficha"]] +
         [round(r["tam"][t], 2) for t in TAMS] + [round(r["canal"][c], 2) for c in CANAIS] +
         [round(r["canal_rs"][c], 2) for c in CANAIS] for r in a["lista"]])
    sab_tc = defaultdict(lambda: [0.0, 0.0])
    for x in L:
        if x["dia"] != ANIVERSARIO:
            sab_tc[(x["sabor"], x["tam"], x["canal"])][0] += x["qtd"]
            sab_tc[(x["sabor"], x["tam"], x["canal"])][1] += x["rs"]
    aba(wb.create_sheet("Sabor x tamanho x canal"), ["Sabor", "Tamanho", "Canal", "Pizzas", "Faturamento R$"],
        [[s, t, c, round(q, 2), round(v, 2)] for (s, t, c), (q, v) in sorted(sab_tc.items(), key=lambda kv: -kv[1][1])])
    aba(wb.create_sheet("Canal x tamanho"), ["Canal", "Tamanho", "Pizzas", "Faturamento R$"],
        [[c, t, round(q, 1), round(v, 2)] for (c, t), (q, v) in sorted(a["por_canal_tam"].items())])
    aba(wb.create_sheet("10-10 aniversário"), ["Sabor", "Pizzas", "Faturamento R$"],
        [[s, round(q, 2), round(v, 2)] for s, (q, v) in a["aniv"]])
    rows = [["MANTER", r["sabor"], r["motivo"], round(r["rs"], 2)] for r in sg["manter"]]
    rows += [["CORTAR", r["sabor"], r["motivo"], round(r["rs"], 2)] for r in sg["cortar"]]
    rows += [["JUNTAR", " + ".join(j["grupo"]) + " → " + j["fica"], j["motivo"], round(j["rs_sai"], 2)] for j in sg["juntar"]]
    rows += [[], ["", "Cortados: % do faturamento", round(sg["pct_cortar"], 2), round(sg["rs_cortar"], 2)],
             ["", "Sabores que saem ao juntar: %", round(sg["pct_juntar"], 2), round(sg["rs_juntar"], 2)]]
    aba(wb.create_sheet("Cardápio enxuto"), ["Lista", "Sabor", "Motivo", "R$ 90 dias (no JUNTAR: dos que saem)"], rows)
    aba(wb.create_sheet("Insumos exclusivos"), ["Insumo", "Sabores que usam", "Pizzas 90 dias", "R$ 90 dias",
                                                 "Também usado em", "Fonte"],
        [[x["insumo"], ", ".join(x["sabores"]), round(x["qtd"], 1), round(x["rs"], 2), ", ".join(x["outros"]),
          x["fonte"]] for x in a["insumos"]])
    aba(wb.create_sheet("Sem ficha"), ["Sabor", "Situação", "Pizzas 90 dias", "R$ 90 dias", "Classe"],
        [[r["sabor"], r["ficha"], round(r["qtd"], 1), round(r["rs"], 2), r["classe"]] for r in a["sem_ficha"]])
    aba(wb.create_sheet("Por dia"), ["Dia", "Canal", "Tamanho", "Sabor", "Pizzas", "R$"],
        [[x["dia"].isoformat(), x["canal"], x["tam"], x["sabor"], round(x["qtd"], 2), round(x["rs"], 2)] for x in L])
    destino.unlink(missing_ok=True)
    wb.save(destino)
    return destino


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--fim", help="último dia operacional (AAAA-MM-DD); padrão: ontem")
    ap.add_argument("--cache", default=os.environ.get("CARDAPIO_CACHE", "/tmp/tili_pedidos"))
    ap.add_argument("--saida", default=str(RAIZ / "monitor/cardapio"))
    ap.add_argument("--sem-baixar", action="store_true", help="usa só o que já está no cache")
    ap.add_argument("--whatsapp", action="store_true", help="manda o PDF para WHATSAPP_EMERSON")
    args = ap.parse_args()
    agora = datetime.now(TZ)
    fim = date.fromisoformat(args.fim) if args.fim else agora.date() - timedelta(days=1)
    ini = fim - timedelta(days=args.dias - 1)
    try:
        api = Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"], timeout=90)
        if not args.sem_baixar:
            baixar(api, ini, fim + timedelta(days=1), Path(args.cache))
        fichas = contagem.coletar(api)
        menu = api.get("/admin/api/menu/full_data")
    except AlivError as e:
        print("Erro ALIV:", e)
        return 1
    leitor = Leitor(fichas, menu)
    L = linhas_de_pizza(Path(args.cache), ini, fim, leitor)
    a = analisar(L, fichas, leitor)
    sg = sugestao(a)
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    base = saida / f"curva_abc_pizzas_{agora:%Y-%m-%d}"
    from diaristas import html_para_pdf
    pdf = html_para_pdf(html_pdf(a, sg, ini, fim, agora), base.with_suffix(".pdf"))
    xlsx = gerar_xlsx(a, sg, L, base.with_suffix(".xlsx"))
    print(f"PDF: {pdf}\nPlanilha: {xlsx}")
    print(f"Pizzas {a['pizzas']:.0f} · R$ {a['total']:.2f} · cortar {sg['pct_cortar']:.1f}% · juntar {sg['pct_juntar']:.1f}%")
    if a["nao_achados"]:
        print("Itens com sabor não reconhecido:", sum(a["nao_achados"].values()))
        for k, v in a["nao_achados"].most_common(15):
            print("  ", v, k)
    if args.whatsapp:
        fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
        if not fone:
            print("Falta WHATSAPP_EMERSON")
            return 3
        try:
            api.enviar_whatsapp(fone, "Curva ABC dos sabores de pizza (90 dias) e sugestão de cardápio enxuto.", pdf)
        except Exception as e:  # noqa: BLE001
            print("WhatsApp falhou:", e)
            return 3
        print("PDF enviado para o Emerson.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
