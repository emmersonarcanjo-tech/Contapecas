#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resultado financeiro de uma noite de Quarta Maluca (Tili Sushi).

Uso (somente leitura, somente arquivos locais):
    python3 -I resultado.py <pedidos_AAAA-MM-DD.json> <custos_aliv.json> <inventory.json> [--json]

Segue as regras de custo do BRIEF.md (regras 1 a 9). Nao acessa rede.
Nao imprime dados pessoais nem chaves fiscais: so numeros agregados e nomes de produto.
"""
import json
import re
import sys
import unicodedata
from collections import OrderedDict, defaultdict
from decimal import Decimal, ROUND_HALF_UP

# ----------------------------------------------------------------------------
# Regras do BRIEF
# ----------------------------------------------------------------------------
CENARIOS = ("otimista", "central", "pessimista")
CUSTO_ROLO_199 = {"otimista": Decimal("0.45"), "central": Decimal("0.60"), "pessimista": Decimal("0.72")}
CUSTO_JOYNIG_299 = {"otimista": Decimal("0.97"), "central": Decimal("1.41"), "pessimista": Decimal("1.85")}
CUSTO_ACARAJAPA = Decimal("0.94")
CUSTO_SASHIMI = Decimal("1.44")
EST_SEM_FICHA = Decimal("0.35")
ALIQ_IMPOSTO = Decimal("0.11")
ALIQ_IFOOD = Decimal("0.25")
ALIQ_CARTAO = Decimal("0.02")
MOTOBOY_POR_ENTREGA = Decimal("2.00")
FIXO_DIA = Decimal("1896.96")

TITULOS_PROMO = {"quarta maluca", "peca sushi", "sunomono"}
PALAVRAS_BEBIDA = ("coca", "guarana", "pepsi", "fanta", "sprite", "schweppes", "suco", "agua",
                   "cerveja", "heineken", "corona", "stella", "refrigerante", "h2o", "energetico",
                   "red bull", "budweiser", "spaten", "original 600", "belga")
PALAVRAS_SORVETE = ("picole", "sorvete", "paleta", "cone recheado", "bombom de sorvete")

GRUPOS = OrderedDict([
    ("a", "(a) Pecas de rolo a R$ 1,99"),
    ("b", "(b) Pecas Joy/niguiri a R$ 2,99 (PECA SUSHI + Sunomono)"),
    ("c", "(c) Acarajapa"),
    ("d", "(d) Sashimi e pecas (unidade)"),
    ("e", "(e) Cardapio normal com ficha"),
    ("f", "(f) Itens sem ficha (estimado 35%)"),
    ("g", "(g) Bebidas"),
    ("h", "(h) Sorvetes/picoles"),
])
PROMO = ("a", "b", "c", "d")


def D(x):
    if x is None or x == "":
        return Decimal("0")
    return Decimal(str(x))


def r2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fq(q):
    """Quantidade sem notacao cientifica: inteiro quando for inteiro."""
    q = D(q)
    if q == q.to_integral_value():
        return str(int(q))
    return str(q.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def pct(parte, todo):
    if not todo:
        return Decimal("0")
    return (D(parte) / D(todo) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def sem_acento(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def norm_nome(s):
    """Nome sem acento, sem parenteses, 'filadelfia' -> 'fila', espacos unicos."""
    s = sem_acento(s).lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("filadelfia", "fila")
    return re.sub(r"\s+", " ", s).strip()


def tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", sem_acento(s).lower()) if t]


def canal(p):
    slug = (p.get("platform_slug") or "").lower()
    tipo = (p.get("delivery_type") or "").lower()
    if slug == "pdv":
        return "PDV delivery" if tipo == "delivery" else "Salao"
    if slug == "app":
        return "App"
    if slug == "ifood":
        return "iFood"
    return slug or "?"


def itens_do_pedido(p):
    it = p.get("items_json")
    if isinstance(it, str):
        try:
            it = json.loads(it)
        except ValueError:
            it = []
    return it or []


# ----------------------------------------------------------------------------
# Casamento de custos
# ----------------------------------------------------------------------------
class Custos:
    def __init__(self, custos_aliv, inventory):
        self.exato = {k: D(v) for k, v in custos_aliv.items()}
        self.norm = {}
        for k, v in custos_aliv.items():
            self.norm.setdefault(norm_nome(k), (k, D(v)))
        self.inv = []
        for g in inventory.get("ingredients", []):
            self.inv.append({
                "name": g.get("name") or "",
                "unit": (g.get("unit") or "").upper(),
                "cost": D(g.get("cost")),
                "tok": set(tokens(g.get("name") or "")),
            })

    def ficha(self, titulo):
        """Devolve (custo, nome_casado) ou (None, None). Custo zero = sem ficha."""
        if titulo in self.exato and self.exato[titulo] > 0:
            return self.exato[titulo], titulo
        n = norm_nome(titulo)
        if n in self.norm and self.norm[n][1] > 0:
            return self.norm[n][1], self.norm[n][0]
        return None, None

    def estoque(self, titulo, aproximado=False):
        """Custo unitario no estoque (unidade UN, custo > 0). Devolve (custo, nome, tipo)."""
        tk = set(tokens(titulo))
        if not tk:
            return None, None, None
        cands = [g for g in self.inv if g["unit"] == "UN" and tk <= g["tok"]]
        if cands:
            cands.sort(key=lambda g: (len(g["tok"]), g["name"]))
            g = cands[0]
            if g["cost"] > 0:
                return g["cost"], g["name"], "estoque"
            return None, g["name"], "estoque_custo_zero"
        if aproximado:
            fortes = {t for t in tk if len(t) >= 5}
            cands = [g for g in self.inv if g["unit"] == "UN" and g["cost"] > 0 and fortes & g["tok"]
                     and any(w in sem_acento(g["name"]).lower() for w in PALAVRAS_SORVETE)]
            if len(cands) == 1:
                return cands[0]["cost"], cands[0]["name"], "estoque_aproximado"
        return None, None, None


def classifica(item, custos):
    """Devolve dict: grupo, receita, qtd, cmv por cenario, origem do custo."""
    titulo = (item.get("title") or item.get("name") or "").strip()
    preco = D(item.get("price"))
    qtd = D(item.get("quantity"))
    receita = preco * qtd
    cat = sem_acento(item.get("category_name") or "").lower()
    tn = sem_acento(titulo).lower()
    out = {"titulo": titulo, "preco": preco, "qtd": qtd, "receita": receita, "estimado": False}

    def fixo(grupo, custo_unit, origem):
        out.update(grupo=grupo, origem=origem, cmv={c: custo_unit * qtd for c in CENARIOS})
        return out

    # --- promocao lancada por botao generico: classifica pelo PRECO
    if tn in TITULOS_PROMO:
        if abs(preco - Decimal("1.99")) < Decimal("0.005"):
            out.update(grupo="a", origem="cenario rolo 1,99",
                       cmv={c: CUSTO_ROLO_199[c] * qtd for c in CENARIOS})
            return out
        if abs(preco - Decimal("2.99")) < Decimal("0.005"):
            out.update(grupo="b", origem="cenario Joy/niguiri 2,99",
                       cmv={c: CUSTO_JOYNIG_299[c] * qtd for c in CENARIOS})
            return out
        if tn in ("quarta maluca", "peca sushi"):
            # preco fora do padrao: abaixo de 2,50 trata como rolo, senao como Joy/niguiri
            if preco < Decimal("2.50"):
                out.update(grupo="a", origem="cenario rolo (preco fora do padrao)",
                           cmv={c: CUSTO_ROLO_199[c] * qtd for c in CENARIOS})
            else:
                out.update(grupo="b", origem="cenario Joy/niguiri (preco fora do padrao)",
                           cmv={c: CUSTO_JOYNIG_299[c] * qtd for c in CENARIOS})
            out["preco_fora_padrao"] = True
            return out
    if tn == "acarajapa":
        return fixo("c", CUSTO_ACARAJAPA, "ficha Acarajapa 0,94")
    if tn == "sashimi":
        return fixo("d", CUSTO_SASHIMI, "ficha Sashimi 1,44")
    if "(unidade)" in tn:
        custo, nome = custos.ficha(titulo)
        if custo is not None:
            div = Decimal("2") if tn.startswith("joy") else Decimal("4")
            return fixo("d", custo / div, "ficha %s / %s" % (nome, div))
        out["estimado"] = True
        return fixo("d", preco * EST_SEM_FICHA, "estimado 35% (unidade sem ficha)")

    # --- bebidas
    eh_bebida = cat in ("bebidas", "cervejas") or (not cat and any(w in tn for w in PALAVRAS_BEBIDA))
    if eh_bebida:
        custo, nome, tipo = custos.estoque(titulo)
        if custo is not None:
            return fixo("g", custo, "estoque: %s" % nome)
        out["estimado"] = True
        return fixo("g", preco * EST_SEM_FICHA, "estimado 35% (bebida com custo zero/sem cadastro)")

    # --- sorvetes / picoles
    if "picol" in cat or "sorvet" in cat or (not cat and any(w in tn for w in PALAVRAS_SORVETE)):
        custo, nome, tipo = custos.estoque(titulo, aproximado=True)
        if custo is not None:
            return fixo("h", custo, "%s: %s" % (tipo, nome))
        out["estimado"] = True
        return fixo("h", preco * EST_SEM_FICHA, "estimado 35% (sem cadastro no estoque)")

    # --- cardapio normal
    custo, nome = custos.ficha(titulo)
    if custo is not None:
        return fixo("e", custo, "ficha: %s" % nome)
    out["estimado"] = True
    return fixo("f", preco * EST_SEM_FICHA, "estimado 35% (sem ficha)")


# ----------------------------------------------------------------------------
# Pagamentos (so para transparencia da taxa de cartao)
# ----------------------------------------------------------------------------
RE_PAG = re.compile(r"^(?P<nome>.+?)(?: \(Troco -> R\$ (?P<t1>[\d.]+)\))?(?:: (?P<v>[\d.]+))?(?: \(Troco: (?P<t2>[\d.]+)\))?$")


def tipo_pagamento(nome):
    n = sem_acento(nome).lower()
    if n.startswith("ifood"):
        return "iFood online"
    if "pix" in n:
        return "Pix"
    if "dinheiro" in n:
        return "Dinheiro"
    if "credito" in n:
        return "Cartao credito"
    if "debito" in n:
        return "Cartao debito"
    if any(w in n for w in ("alelo", "ticket", "vr ", "refeicao", "alimentacao", "sodexo", "pluxee")):
        return "Vale refeicao"
    return "Outros"


def pagamentos(p):
    txt = (p.get("payment_method") or "").strip()
    total = D(p.get("total"))
    partes = [x.strip() for x in txt.split(" | ") if x.strip()]
    res = []
    for parte in partes:
        m = RE_PAG.match(parte)
        if not m:
            res.append((tipo_pagamento(parte), None))
            continue
        v = m.group("v")
        liquido = None if v is None else D(v) - D(m.group("t2") or 0)
        res.append((tipo_pagamento(m.group("nome")), liquido))
    if len(res) == 1 and res[0][1] is None:
        res = [(res[0][0], total)]
    soma = sum((v for _, v in res if v is not None), Decimal("0"))
    ok = all(v is not None for _, v in res) and abs(soma - total) < Decimal("0.011")
    if not ok:
        res = [("Nao identificado", total)]
    return res, ok


# ----------------------------------------------------------------------------
def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if len(args) != 3:
        print(__doc__)
        return 2
    pedidos = json.load(open(args[0], encoding="utf-8"))
    custos = Custos(json.load(open(args[1], encoding="utf-8")), json.load(open(args[2], encoding="utf-8")))

    validos = [p for p in pedidos if "CANCEL" not in (p.get("status") or "").upper()]
    cancelados = [p for p in pedidos if "CANCEL" in (p.get("status") or "").upper()]
    Z = Decimal("0")

    # ---------------- 1. faturamento e conferencia
    fat = sum((D(p.get("total")) for p in validos), Z)
    por_canal = OrderedDict((c, {"n": 0, "total": Z, "itens": Z, "entrega": Z, "servico": Z, "desconto": Z,
                                 "cmv": {c2: Z for c2 in CENARIOS}, "entregas": 0})
                            for c in ("Salao", "PDV delivery", "App", "iFood"))
    soma_itens = soma_entrega = soma_servico = soma_desc = Z
    divergentes = 0
    desc_loja = desc_plataforma = desc_outros = Z
    grupos = OrderedDict((g, {"receita": Z, "qtd": Z, "cmv": {c: Z for c in CENARIOS}, "estimado": Z,
                              "por_canal": defaultdict(lambda: Decimal("0"))}) for g in GRUPOS)
    linhas = defaultdict(lambda: {"qtd": Z, "receita": Z, "cmv_central": Z, "grupo": "", "origem": "", "estimado": False})
    fora_padrao = Z
    pag = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    pag_nao_ident = 0
    n_entregas = 0
    salao_com_promo = salao_com_bebida = salao_promo_sem_bebida = 0
    primeira = ultima = None

    for p in validos:
        c = canal(p)
        pc = por_canal.setdefault(c, {"n": 0, "total": Z, "itens": Z, "entrega": Z, "servico": Z, "desconto": Z,
                                      "cmv": {c2: Z for c2 in CENARIOS}, "entregas": 0})
        tot = D(p.get("total"))
        ent = D(p.get("delivery_fee"))
        srv = D(p.get("service_fee"))
        dsc = D(p.get("discount"))
        si = Z
        tem = set()
        for it in itens_do_pedido(p):
            k = classifica(it, custos)
            tem.add(k["grupo"])
            si += k["receita"]
            g = grupos[k["grupo"]]
            g["receita"] += k["receita"]
            g["qtd"] += k["qtd"]
            g["por_canal"][c] += k["receita"]
            for cen in CENARIOS:
                g["cmv"][cen] += k["cmv"][cen]
                pc["cmv"][cen] += k["cmv"][cen]
            if k["estimado"]:
                g["estimado"] += k["receita"]
            if k.get("preco_fora_padrao"):
                fora_padrao += k["receita"]
            ln = linhas[(k["grupo"], k["titulo"], str(k["preco"]))]
            ln["qtd"] += k["qtd"]
            ln["receita"] += k["receita"]
            ln["cmv_central"] += k["cmv"]["central"]
            ln["grupo"] = k["grupo"]
            ln["origem"] = k["origem"]
            ln["estimado"] = k["estimado"]
        if abs(si + ent + srv - dsc - tot) > Decimal("0.011"):
            divergentes += 1
        if c == "Salao":
            salao_com_promo += 1 if tem & set(PROMO) else 0
            salao_com_bebida += 1 if "g" in tem else 0
            salao_promo_sem_bebida += 1 if (tem & set(PROMO)) and "g" not in tem else 0
        soma_itens += si
        soma_entrega += ent
        soma_servico += srv
        soma_desc += dsc
        pc["n"] += 1
        pc["total"] += tot
        pc["itens"] += si
        pc["entrega"] += ent
        pc["servico"] += srv
        pc["desconto"] += dsc
        if (p.get("delivery_type") or "").lower() == "delivery":
            n_entregas += 1
            pc["entregas"] += 1
        for o in (p.get("discount_origins") or []):
            if not isinstance(o, dict):
                continue
            kind = (o.get("kind") or "").lower()
            if kind == "loja":
                desc_loja += D(o.get("value"))
            elif kind == "plataforma":
                desc_plataforma += D(o.get("value"))
            else:
                desc_outros += D(o.get("value"))
        ps, ok = pagamentos(p)
        if not ok:
            pag_nao_ident += 1
        for tipo, v in ps:
            pag[c][tipo] += v
        cr = p.get("_criado") or ""
        if cr:
            primeira = cr if primeira is None or cr < primeira else primeira
            ultima = cr if ultima is None or cr > ultima else ultima

    taxas = soma_entrega + soma_servico
    calc = soma_itens + taxas - soma_desc
    dif = fat - calc

    # ---------------- 3. CMV
    cmv = {cen: sum((g["cmv"][cen] for g in grupos.values()), Z) for cen in CENARIOS}

    # ---------------- 4. deducoes
    fat_salao = por_canal["Salao"]["total"]
    fat_app = por_canal["App"]["total"]
    fat_ifood = por_canal["iFood"]["total"]
    fat_pdvdel = por_canal["PDV delivery"]["total"]
    impostos = fat * ALIQ_IMPOSTO
    com_ifood = fat_ifood * ALIQ_IFOOD
    tx_cartao = (fat_salao + fat_app) * ALIQ_CARTAO
    motoboy = MOTOBOY_POR_ENTREGA * n_entregas
    deducoes = impostos + com_ifood + tx_cartao + motoboy

    # ---------------- 5. margem
    mc = {cen: fat - cmv[cen] - deducoes for cen in CENARIOS}
    res = {cen: mc[cen] - FIXO_DIA for cen in CENARIOS}

    # ---------------- 6. recorte promocao
    rec_promo = sum((grupos[g]["receita"] for g in PROMO), Z)
    pecas_promo = sum((grupos[g]["qtd"] for g in PROMO), Z)
    cmv_promo = {cen: sum((grupos[g]["cmv"][cen] for g in PROMO), Z) for cen in CENARIOS}
    imp_promo = rec_promo * ALIQ_IMPOSTO
    sobra_promo = {cen: rec_promo - cmv_promo[cen] - imp_promo for cen in CENARIOS}
    rec_promo_salao = sum((grupos[g]["por_canal"]["Salao"] for g in PROMO), Z)
    rec_promo_app = sum((grupos[g]["por_canal"]["App"] for g in PROMO), Z)
    cartao_promo = (rec_promo_salao + rec_promo_app) * ALIQ_CARTAO
    sobra_promo_cartao = {cen: sobra_promo[cen] - cartao_promo for cen in CENARIOS}

    # ---------------- 7. estimado 35%
    rec_est = sum((g["estimado"] for g in grupos.values()), Z)
    rec_cenario = grupos["a"]["receita"] + grupos["b"]["receita"]
    cmv_est = sum((ln["cmv_central"] for ln in linhas.values() if ln["estimado"]), Z)

    # ---------------- resultado por canal (cenario a cenario)
    canal_res = OrderedDict()
    for c, pc in por_canal.items():
        t = pc["total"]
        imp = t * ALIQ_IMPOSTO
        ifd = t * ALIQ_IFOOD if c == "iFood" else Z
        crt = t * ALIQ_CARTAO if c in ("Salao", "App") else Z
        mot = MOTOBOY_POR_ENTREGA * pc["entregas"]
        canal_res[c] = {"imp": imp, "ifood": ifd, "cartao": crt, "motoboy": mot,
                        "mc": {cen: t - pc["cmv"][cen] - imp - ifd - crt - mot for cen in CENARIOS}}

    # ============================ RELATORIO ============================
    P = print
    P("=" * 78)
    P("RESULTADO FINANCEIRO —", args[0].rsplit("/", 1)[-1])
    P("=" * 78)
    P("Pedidos no arquivo: %d | validos: %d | cancelados: %d" % (len(pedidos), len(validos), len(cancelados)))
    P("Primeiro pedido: %s | ultimo: %s" % (primeira, ultima))
    P("")
    P("1) FATURAMENTO")
    P("   Faturamento total (soma de total)........ R$ %10s" % r2(fat))
    for c, pc in por_canal.items():
        P("   %-13s %4d pedidos  R$ %10s  (%5s%%)  ticket medio R$ %s" % (
            c, pc["n"], r2(pc["total"]), pct(pc["total"], fat), r2(pc["total"] / pc["n"]) if pc["n"] else "-"))
    P("   Conferencia: itens R$ %s + entrega R$ %s + servico R$ %s - descontos R$ %s = R$ %s" % (
        r2(soma_itens), r2(soma_entrega), r2(soma_servico), r2(soma_desc), r2(calc)))
    P("   Diferenca para a soma de total: R$ %s | pedidos que nao fecham: %d" % (r2(dif), divergentes))
    for c, pc in por_canal.items():
        if pc["entrega"] or pc["servico"] or pc["desconto"]:
            P("     %-13s itens R$ %s | entrega R$ %s | servico R$ %s | descontos R$ %s" % (
                c, r2(pc["itens"]), r2(pc["entrega"]), r2(pc["servico"]), r2(pc["desconto"])))
    P("   Descontos por origem: loja R$ %s | plataforma (iFood reembolsa) R$ %s | outros R$ %s" % (
        r2(desc_loja), r2(desc_plataforma), r2(desc_outros)))
    P("")
    P("2) e 3) RECEITA, QUANTIDADE E CMV POR GRUPO")
    P("   %-58s %8s %10s %9s %9s %9s" % ("grupo", "qtd", "receita", "cmv otim", "cmv centr", "cmv pess"))
    for gk, nome in GRUPOS.items():
        g = grupos[gk]
        P("   %-58s %8s %10s %9s %9s %9s" % (nome, fq(g["qtd"]),
                                            r2(g["receita"]), r2(g["cmv"]["otimista"]), r2(g["cmv"]["central"]), r2(g["cmv"]["pessimista"])))
    P("   %-58s %8s %10s" % ("(i) Taxas de entrega + servico", "", r2(taxas)))
    P("   %-58s %8s %10s" % ("(-) Descontos", "", r2(-soma_desc)))
    P("   %-58s %8s %10s %9s %9s %9s" % ("TOTAL", "", r2(fat), r2(cmv["otimista"]), r2(cmv["central"]), r2(cmv["pessimista"])))
    P("   CMV %% do faturamento: otimista %s%% | central %s%% | pessimista %s%%" % (
        pct(cmv["otimista"], fat), pct(cmv["central"], fat), pct(cmv["pessimista"], fat)))
    P("")
    P("   Detalhe por item (cmv no cenario central):")
    for (gk, tit, pr), ln in sorted(linhas.items(), key=lambda kv: (kv[0][0], -kv[1]["receita"])):
        P("     [%s] %-52s x%-6s @%7s rec %9s cmv %8s  %s" % (
            gk, tit[:52], fq(ln["qtd"]), pr,
            r2(ln["receita"]), r2(ln["cmv_central"]), ln["origem"]))
    if fora_padrao:
        P("   ATENCAO: R$ %s em botoes de promocao com preco diferente de 1,99/2,99." % r2(fora_padrao))
    P("")
    P("4) DEDUCOES")
    P("   Impostos 11%% do faturamento.............. R$ %10s" % r2(impostos))
    P("   Comissao iFood 25%% de R$ %s......... R$ %10s" % (r2(fat_ifood), r2(com_ifood)))
    P("   Taxa de cartao 2%% de salao+app (R$ %s) R$ %10s" % (r2(fat_salao + fat_app), r2(tx_cartao)))
    P("   Motoboy R$ 2 x %d entregas................ R$ %10s" % (n_entregas, r2(motoboy)))
    P("   Total das deducoes....................... R$ %10s" % r2(deducoes))
    P("")
    P("5) MARGEM DE CONTRIBUICAO E RESULTADO APOS CUSTO FIXO (R$ %s/dia)" % r2(FIXO_DIA))
    for cen in CENARIOS:
        P("   %-10s CMV R$ %9s | margem R$ %9s (%5s%% do fat.) | apos fixo R$ %9s (%5s%%)" % (
            cen, r2(cmv[cen]), r2(mc[cen]), pct(mc[cen], fat), r2(res[cen]), pct(res[cen], fat)))
    P("")
    P("6) RECORTE DA PROMOCAO (grupos a+b+c+d)")
    P("   Receita R$ %s (%s%% do faturamento) | %s pecas | imposto 11%% R$ %s" % (
        r2(rec_promo), pct(rec_promo, fat), fq(pecas_promo), r2(imp_promo)))
    P("   Receita da promocao por canal: " + " | ".join(
        "%s R$ %s" % (c, r2(sum((grupos[g]["por_canal"][c] for g in PROMO), Z))) for c in por_canal))
    for cen in CENARIOS:
        P("   %-10s CMV R$ %9s (%5s%%) | sobra R$ %9s (%5s%%) | sobra apos cartao 2%% (R$ %s) R$ %9s" % (
            cen, r2(cmv_promo[cen]), pct(cmv_promo[cen], rec_promo), r2(sobra_promo[cen]), pct(sobra_promo[cen], rec_promo),
            r2(cartao_promo), r2(sobra_promo_cartao[cen])))
    for cen in CENARIOS:
        P("   %-10s a promocao responde por %s%% da margem de contribuicao da noite (sobra apos cartao / margem total)" % (
            cen, pct(sobra_promo_cartao[cen], mc[cen])))
    P("   Fora da promocao (resto da noite): receita R$ %s" % r2(fat - rec_promo))
    for cen in CENARIOS:
        P("     %-10s margem do resto = margem total - sobra da promo apos cartao = R$ %s" % (
            cen, r2(mc[cen] - sobra_promo_cartao[cen])))
    P("")
    P("7) TRANSPARENCIA DO CUSTO")
    P("   Receita com custo estimado 35%%: R$ %s (%s%% do faturamento; %s%% da receita de itens) | CMV estimado R$ %s" % (
        r2(rec_est), pct(rec_est, fat), pct(rec_est, soma_itens), r2(cmv_est)))
    for gk in GRUPOS:
        if grupos[gk]["estimado"]:
            P("     %s: R$ %s" % (GRUPOS[gk], r2(grupos[gk]["estimado"])))
    P("   Receita com custo por cenario (mix desconhecido, grupos a+b): R$ %s (%s%% do faturamento)" % (
        r2(rec_cenario), pct(rec_cenario, fat)))
    rec_ficha = soma_itens - rec_est - rec_cenario
    P("   Receita com custo de ficha/estoque: R$ %s (%s%% do faturamento)" % (r2(rec_ficha), pct(rec_ficha, fat)))
    P("")
    P("EXTRAS")
    P("   Resultado por canal:")
    for c, cr in canal_res.items():
        pc = por_canal[c]
        P("     %-13s fat R$ %9s | CMV central R$ %8s | imp R$ %7s | iFood R$ %7s | cartao R$ %7s | motoboy R$ %6s" % (
            c, r2(pc["total"]), r2(pc["cmv"]["central"]), r2(cr["imp"]), r2(cr["ifood"]), r2(cr["cartao"]), r2(cr["motoboy"])))
        P("     %-13s margem: otimista R$ %s | central R$ %s (%s%%) | pessimista R$ %s" % (
            "", r2(cr["mc"]["otimista"]), r2(cr["mc"]["central"]), pct(cr["mc"]["central"], pc["total"]), r2(cr["mc"]["pessimista"])))
    P("   Sobra por peca (preco - custo - 11% imposto - 2% cartao) e custo como % do preco:")
    for nome_p, preco_p, tab in (("rolo 1,99", Decimal("1.99"), CUSTO_ROLO_199), ("Joy/niguiri 2,99", Decimal("2.99"), CUSTO_JOYNIG_299)):
        P("     %-17s " % nome_p + " | ".join("%s R$ %s (custo %s%% do preco)" % (
            cen, r2(preco_p * (1 - ALIQ_IMPOSTO - ALIQ_CARTAO) - tab[cen]), pct(tab[cen], preco_p)) for cen in CENARIOS))
    P("     Acarajapa 2,99    R$ %s (custo %s%%) | Sashimi 4,99 R$ %s (custo %s%%)" % (
        r2(Decimal("2.99") * (1 - ALIQ_IMPOSTO - ALIQ_CARTAO) - CUSTO_ACARAJAPA), pct(CUSTO_ACARAJAPA, Decimal("2.99")),
        r2(Decimal("4.99") * (1 - ALIQ_IMPOSTO - ALIQ_CARTAO) - CUSTO_SASHIMI), pct(CUSTO_SASHIMI, Decimal("4.99"))))
    for gk in ("a", "b"):
        P("     Grupo (%s): CMV %% da receita do grupo: " % gk + " | ".join(
            "%s %s%%" % (cen, pct(grupos[gk]["cmv"][cen], grupos[gk]["receita"])) for cen in CENARIOS)
          + " | sobra do grupo apos 11% e 2%: " + " | ".join(
            "%s R$ %s" % (cen, r2(grupos[gk]["receita"] * (1 - ALIQ_IMPOSTO - ALIQ_CARTAO) - grupos[gk]["cmv"][cen])) for cen in CENARIOS))
    qa, qb = grupos["a"]["qtd"], grupos["b"]["qtd"]
    liq = 1 - ALIQ_IMPOSTO - ALIQ_CARTAO
    P("   Sensibilidades (mesmo volume desta noite):")
    P("     cada R$ 0,10 no custo da peca de rolo = R$ %s | cada R$ 0,10 no custo da peca Joy/niguiri = R$ %s" % (
        r2(qa * Decimal("0.10")), r2(qb * Decimal("0.10"))))
    P("     faixa otimista->pessimista: rolo R$ %s | Joy/niguiri R$ %s | total R$ %s" % (
        r2(grupos["a"]["cmv"]["pessimista"] - grupos["a"]["cmv"]["otimista"]),
        r2(grupos["b"]["cmv"]["pessimista"] - grupos["b"]["cmv"]["otimista"]),
        r2(cmv["pessimista"] - cmv["otimista"])))
    P("     +R$ 0,50 na peca de 2,99 (liquido de 13%%) = R$ %s | +R$ 1,00 = R$ %s | +R$ 0,10 na peca de 1,99 = R$ %s" % (
        r2(qb * Decimal("0.50") * liq), r2(qb * Decimal("1.00") * liq), r2(qa * Decimal("0.10") * liq)))
    P("   Custo fixo do dia: R$ %s = %s%% do faturamento | margem central cobre %sx o fixo" % (
        r2(FIXO_DIA), pct(FIXO_DIA, fat), (mc["central"] / FIXO_DIA).quantize(Decimal("0.01"))))
    pecas_fixo = {cen: FIXO_DIA / ((sobra_promo_cartao[cen]) / pecas_promo) if pecas_promo and sobra_promo_cartao[cen] > 0 else None for cen in CENARIOS}
    P("   Sobra media por peca da promo apos cartao: " + " | ".join(
        "%s R$ %s" % (cen, (sobra_promo_cartao[cen] / pecas_promo).quantize(Decimal("0.001")) if pecas_promo else "-") for cen in CENARIOS))
    P("   Pecas de promo para pagar sozinhas o fixo do dia: " + " | ".join(
        "%s %s" % (cen, pecas_fixo[cen].quantize(Decimal("1")) if pecas_fixo[cen] else "-") for cen in CENARIOS))
    P("   iFood: subtotal itens R$ %s | descontos R$ %s (%s%% do subtotal) | loja banca R$ %s | iFood banca R$ %s | taxa de servico (vai p/ iFood) R$ %s" % (
        r2(por_canal["iFood"]["itens"]), r2(por_canal["iFood"]["desconto"]), pct(por_canal["iFood"]["desconto"], por_canal["iFood"]["itens"]),
        r2(desc_loja), r2(desc_plataforma), r2(por_canal["iFood"]["servico"])))
    ifd = por_canal["iFood"]
    ifood_real = ifd["total"] - ifd["servico"] + desc_plataforma
    P("   iFood, outra leitura: total cobrado do cliente R$ %s - taxa de servico R$ %s + desconto que o iFood reembolsa R$ %s = R$ %s (R$ %s a mais que o total)" % (
        r2(ifd["total"]), r2(ifd["servico"]), r2(desc_plataforma), r2(ifood_real), r2(ifood_real - ifd["total"])))
    if ifd["n"]:
        P("   iFood: desconto bancado pela loja por pedido R$ %s | %s%% do subtotal de itens" % (
            r2(desc_loja / ifd["n"]), pct(desc_loja, ifd["itens"])))
    if ifd["itens"]:
        P("   iFood: desconto da loja + comissao 25%% = R$ %s = %s%% do subtotal de itens (%s%% do total cobrado)" % (
            r2(desc_loja + com_ifood), pct(desc_loja + com_ifood, ifd["itens"]), pct(desc_loja + com_ifood, ifd["total"])))
        if por_canal["App"]["total"]:
            mg_app = canal_res["App"]["mc"]["central"] / por_canal["App"]["total"]
            mg_ifd = canal_res["iFood"]["mc"]["central"] / ifd["total"]
            P("   iFood x App: margem por R$ 100 vendidos: iFood R$ %s | App R$ %s | diferenca R$ %s" % (
                r2(mg_ifd * 100), r2(mg_app * 100), r2((mg_app - mg_ifd) * 100)))
            P("   Se o total do iFood (R$ %s) rendesse a margem %% do App: R$ %s em vez de R$ %s (+R$ %s)" % (
                r2(ifd["total"]), r2(ifd["total"] * mg_app), r2(canal_res["iFood"]["mc"]["central"]),
                r2(ifd["total"] * mg_app - canal_res["iFood"]["mc"]["central"])))
    P("   Receita de itens por grupo x canal:")
    for gk, nome in GRUPOS.items():
        P("     %-58s " % nome + " | ".join("%s R$ %s" % (c, r2(grupos[gk]["por_canal"][c])) for c in por_canal))
    ns = por_canal["Salao"]["n"]
    if ns:
        beb_salao = grupos["g"]["por_canal"]["Salao"]
        P("   Salao: %d pedidos | com peca da promo: %d | com bebida: %d (%s%%) | com promo e sem bebida: %d" % (
            ns, salao_com_promo, salao_com_bebida, pct(salao_com_bebida, ns), salao_promo_sem_bebida))
        P("   Salao: pecas de promo por pedido %s | bebida por pedido R$ %s | bebidas = %s%% do faturamento do salao" % (
            (sum((grupos[g]["qtd"] for g in PROMO), Z) / ns).quantize(Decimal("0.1")), r2(beb_salao / ns), pct(beb_salao, por_canal["Salao"]["total"])))
        cmv_beb = grupos["g"]["cmv"]["central"]
        rec_beb = grupos["g"]["receita"]
        if rec_beb:
            marg_beb = (rec_beb * (1 - ALIQ_IMPOSTO - ALIQ_CARTAO) - cmv_beb) / rec_beb
            P("   Bebidas: receita R$ %s | CMV R$ %s (%s%%) | sobra apos 11%% e 2%%: R$ %s (%s%%)" % (
                r2(rec_beb), r2(cmv_beb), pct(cmv_beb, rec_beb), r2(rec_beb * (1 - ALIQ_IMPOSTO - ALIQ_CARTAO) - cmv_beb), pct(marg_beb, 1)))
            lata = Decimal("6.00") * (1 - EST_SEM_FICHA - ALIQ_IMPOSTO - ALIQ_CARTAO)
            P("   Sobra de 1 refrigerante lata de R$ 6,00 (custo 35%%, imposto 11%%, cartao 2%%): R$ %s | a cada 10 latas a mais R$ %s | metade dos %d pedidos sem bebida: R$ %s" % (
                r2(lata), r2(lata * 10), salao_promo_sem_bebida, r2(lata * salao_promo_sem_bebida / 2)))
            P("   Se cada pedido do salao com promo e sem bebida levasse 1 refrigerante lata de R$ 6,00: +R$ %s de venda, +R$ %s de sobra (custo estimado 35%%, imposto 11%%, cartao 2%%)" % (
                r2(Decimal("6.00") * salao_promo_sem_bebida),
                r2(Decimal("6.00") * salao_promo_sem_bebida * (1 - EST_SEM_FICHA - ALIQ_IMPOSTO - ALIQ_CARTAO))))
    P("   Formas de pagamento por canal (liquido de troco; pedidos nao identificados: %d):" % pag_nao_ident)
    for c in por_canal:
        if pag[c]:
            P("     %-13s " % c + " | ".join("%s R$ %s" % (t, r2(v)) for t, v in sorted(pag[c].items(), key=lambda kv: -kv[1])))
    maq = sum((pag[c][t] for c in ("Salao", "App", "PDV delivery") for t in ("Cartao credito", "Cartao debito", "Vale refeicao")), Z)
    P("   Se a taxa de 2%% incidisse so sobre credito+debito+vale (R$ %s): R$ %s (regra do BRIEF: R$ %s; diferenca R$ %s)" % (
        r2(maq), r2(maq * ALIQ_CARTAO), r2(tx_cartao), r2(tx_cartao - maq * ALIQ_CARTAO)))
    P("   Distancia entre cenarios na margem: otimista - central R$ %s | central - pessimista R$ %s | otimista - pessimista R$ %s (%s%% da margem central)" % (
        r2(mc["otimista"] - mc["central"]), r2(mc["central"] - mc["pessimista"]), r2(mc["otimista"] - mc["pessimista"]),
        pct(mc["otimista"] - mc["pessimista"], mc["central"])))
    P("   Fora da promocao: margem R$ %s = %s%% da receita fora da promocao (R$ %s)" % (
        r2(mc["central"] - sobra_promo_cartao["central"]), pct(mc["central"] - sobra_promo_cartao["central"], fat - rec_promo), r2(fat - rec_promo)))
    P("   Delivery (App + iFood + PDV delivery): faturamento R$ %s (%s%%) | margem central R$ %s" % (
        r2(fat - fat_salao), pct(fat - fat_salao, fat),
        r2(sum((canal_res[c]["mc"]["central"] for c in canal_res if c != "Salao"), Z))))

    if "--json" in flags:
        out = OrderedDict()
        out["arquivo"] = args[0].rsplit("/", 1)[-1]
        out["pedidos_validos"] = len(validos)
        out["pedidos_cancelados"] = len(cancelados)
        out["faturamento"] = str(r2(fat))
        for c, pc in por_canal.items():
            out["fat_" + c] = str(r2(pc["total"]))
            out["n_" + c] = pc["n"]
        for gk in GRUPOS:
            out["rec_" + gk] = str(r2(grupos[gk]["receita"]))
            out["qtd_" + gk] = str(grupos[gk]["qtd"])
            for cen in CENARIOS:
                out["cmv_%s_%s" % (gk, cen)] = str(r2(grupos[gk]["cmv"][cen]))
        out["taxas"] = str(r2(taxas))
        out["descontos"] = str(r2(soma_desc))
        out["impostos"] = str(r2(impostos))
        out["ifood"] = str(r2(com_ifood))
        out["cartao"] = str(r2(tx_cartao))
        out["motoboy"] = str(r2(motoboy))
        for cen in CENARIOS:
            out["cmv_total_" + cen] = str(r2(cmv[cen]))
            out["mc_" + cen] = str(r2(mc[cen]))
            out["mc_pct_" + cen] = str(pct(mc[cen], fat))
            out["resultado_apos_fixo_" + cen] = str(r2(res[cen]))
            out["promo_cmv_" + cen] = str(r2(cmv_promo[cen]))
            out["promo_sobra_" + cen] = str(r2(sobra_promo[cen]))
            out["promo_sobra_apos_cartao_" + cen] = str(r2(sobra_promo_cartao[cen]))
        out["promo_pecas"] = fq(pecas_promo)
        out["promo_receita"] = str(r2(rec_promo))
        out["promo_imposto"] = str(r2(imp_promo))
        out["receita_estimada_35"] = str(r2(rec_est))
        out["receita_estimada_35_pct_fat"] = str(pct(rec_est, fat))
        P("")
        P("JSON " + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
