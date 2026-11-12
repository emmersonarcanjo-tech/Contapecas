#!/usr/bin/env python3
"""Comparativo da Quarta Maluca: 11/11/2026 x quartas anteriores (Tili Sushi, loja 155).

Uso (somente leitura, somente arquivos locais):
    python3 -I comparativo.py [--json SAIDA.json] pedidos_AAAA-MM-DD.json [pedidos_...json ...]

Regras (do BRIEF.md):
- Receita: só pedidos cujo status NÃO contém "CANCEL". Cancelados contados à parte.
- Canal: Salão = platform_slug "pdv" e delivery_type != "delivery"; PDV delivery = "pdv" + "delivery"; App; iFood.
- Peças genéricas ("QUARTA MALUCA", "PEÇA SUSHI", "Sunomono") classificadas pelo PREÇO:
    R$ 1,99 -> peça de rolo; R$ 2,99 -> Joy/niguiri.
- "Acarajapa" e "Sashimi" são peças avulsas próprias.
- "X (1 peça)" e "X (unidade)" = peça avulsa nomeada (1 peça do item).
- Bebidas = categorias "Bebidas" e "Cervejas" (+ itens sem categoria cujo nome é de bebida, caso do iFood).
- Cardápio normal = todo o resto (fora peças avulsas e bebidas); inclui sobremesas e CEVICHE.
- Receita de item = price * quantity (bruta, antes de desconto, sem taxa de entrega/serviço).
"""
import collections
import json
import re
import statistics
import sys
from pathlib import Path

GENERICAS = {"QUARTA MALUCA", "PEÇA SUSHI", "PECA SUSHI", "SUNOMONO"}
IDS_GENERICAS = {"12154", "11736", "14358"}
RE_NOMEADA = re.compile(r"\((1 pe[çc]a|unidade)\)\s*$", re.I)
RE_BEBIDA = re.compile(
    r"coca[- ]?cola|guaran[áa]|\bsuco\b|[áa]gua mineral|\bágua\b|heineken|stella artois|corona|l[äa]ut|cerveja|"
    r"refrigerante|fanta|sprite|schweppes|\bh2o", re.I)
RE_CERVEJA = re.compile(r"heineken|stella artois|corona|l[äa]ut|cerveja", re.I)
CANAIS = ["Salão", "App", "iFood", "PDV delivery"]
GRUPOS_PECA = ["rolo_1_99", "joy_niguiri_2_99", "generica_outro_preco", "acarajapa", "sashimi", "peca_nomeada"]
# custo por peça (BRIEF, regras 2, 3 e 4): (otimista, central, pessimista)
CUSTO_PECA = {
    "rolo_1_99": (0.45, 0.60, 0.72),
    "joy_niguiri_2_99": (0.97, 1.41, 1.85),
    "acarajapa": (0.94, 0.94, 0.94),
    "sashimi": (1.44, 1.44, 1.44),
}


def num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def itens(p):
    it = p.get("items_json")
    if isinstance(it, str):
        try:
            it = json.loads(it)
        except ValueError:
            it = []
    return it or []


def cancelado(p):
    return "CANCEL" in str(p.get("status") or "").upper()


def canal(p):
    slug = str(p.get("platform_slug") or "").lower()
    dt = str(p.get("delivery_type") or "").lower()
    if slug == "pdv":
        return "PDV delivery" if dt == "delivery" else "Salão"
    if slug == "app":
        return "App"
    if slug == "ifood":
        return "iFood"
    return "Outro(" + slug + ")"


def classifica(i):
    """Devolve (grupo, subgrupo)."""
    t = str(i.get("title") or i.get("name") or "").strip()
    tu = t.upper()
    preco = round(num(i.get("price")), 2)
    cat = i.get("category_name")
    pid = str(i.get("product_id") if i.get("product_id") is not None else i.get("id"))
    if tu in GENERICAS or (pid in IDS_GENERICAS and tu in GENERICAS):
        if abs(preco - 1.99) < 0.005:
            return "rolo_1_99", tu
        if abs(preco - 2.99) < 0.005:
            return "joy_niguiri_2_99", tu
        return "generica_outro_preco", tu
    if tu == "ACARAJAPA":
        return "acarajapa", tu
    if tu == "SASHIMI":
        return "sashimi", tu
    if RE_NOMEADA.search(t):
        return "peca_nomeada", t
    if cat in ("Bebidas", "Cervejas") or (cat in (None, "") and RE_BEBIDA.search(t)):
        return "bebida", ("cerveja" if (cat == "Cervejas" or RE_CERVEJA.search(t)) else "sem_alcool")
    if cat == "Picolés & Sorvetes":
        return "cardapio", "sobremesa"
    if tu == "CEVICHE":
        return "cardapio", "ceviche_promo"
    return "cardapio", "normal"


def data_do_arquivo(path):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", Path(path).name)
    return f"{m.group(3)}/{m.group(2)}", f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def analisa(path):
    pedidos = json.loads(Path(path).read_text(encoding="utf-8"))
    rot, iso = data_do_arquivo(path)
    r = collections.OrderedDict()
    r["data"] = rot
    r["iso"] = iso
    validos = [p for p in pedidos if not cancelado(p)]
    canc = [p for p in pedidos if cancelado(p)]
    r["pedidos_no_arquivo"] = len(pedidos)
    r["pedidos"] = len(validos)
    r["cancelados"] = len(canc)
    r["cancelados_valor"] = sum(num(p.get("total")) for p in canc)
    r["faturamento"] = sum(num(p.get("total")) for p in validos)
    r["ticket_medio"] = r["faturamento"] / len(validos) if validos else 0.0
    r["subtotal_itens"] = sum(num(p.get("subtotal")) for p in validos)
    r["descontos"] = sum(num(p.get("discount")) for p in validos)
    r["taxa_entrega"] = sum(num(p.get("delivery_fee")) for p in validos)
    r["taxa_servico"] = sum(num(p.get("service_fee")) for p in validos)
    r["primeiro_pedido"] = min((p.get("_criado") or "") for p in pedidos)[11:16]
    ult = max((p.get("_criado") or "") for p in pedidos)
    r["ultimo_pedido"] = ult[5:10] + " " + ult[11:16]

    # por canal
    for c in CANAIS:
        ps = [p for p in validos if canal(p) == c]
        r[f"fat_{c}"] = sum(num(p.get("total")) for p in ps)
        r[f"ped_{c}"] = len(ps)
        r[f"ticket_{c}"] = (r[f"fat_{c}"] / len(ps)) if ps else 0.0
    outros = [p for p in validos if canal(p) not in CANAIS]
    r["ped_outros_canais"] = len(outros)
    r["ped_delivery"] = sum(1 for p in validos if str(p.get("delivery_type") or "").lower() == "delivery")

    # itens
    qtd = collections.Counter()
    rec = collections.Counter()
    qtd_sal = collections.Counter()
    rec_sal = collections.Counter()
    sub = collections.Counter()       # (grupo, subgrupo) -> receita
    subq = collections.Counter()
    botao_299 = collections.Counter()  # qual botão lançou as peças a 2,99
    botao_199 = collections.Counter()
    card_canal = collections.Counter()
    beb_canal = collections.Counter()
    auditoria = collections.defaultdict(set)
    soma_itens = 0.0
    salao = [p for p in validos if canal(p) == "Salão"]
    pecas_por_pedido = []
    pecas199_por_pedido = []
    pecas299_por_pedido = []
    salao_com_bebida = 0
    salao_com_peca = 0
    salao_so_peca = 0
    por_hora = collections.OrderedDict()
    for p in validos:
        c = canal(p)
        n_pecas = n199 = n299 = 0.0
        tem_bebida = False
        tem_outro = False
        for i in itens(p):
            g, s = classifica(i)
            q = num(i.get("quantity"))
            v = q * num(i.get("price"))
            soma_itens += v
            qtd[g] += q
            rec[g] += v
            sub[(g, s)] += v
            subq[(g, s)] += q
            auditoria[g].add(str(i.get("title") or ""))
            if g == "joy_niguiri_2_99":
                botao_299[s] += q
            if g == "rolo_1_99":
                botao_199[s] += q
            if g == "cardapio":
                card_canal[c] += v
            if g == "bebida":
                beb_canal[c] += v
            if c == "Salão":
                qtd_sal[g] += q
                rec_sal[g] += v
                if g in GRUPOS_PECA:
                    n_pecas += q
                    if g == "rolo_1_99":
                        n199 += q
                    if g == "joy_niguiri_2_99":
                        n299 += q
                elif g == "bebida":
                    tem_bebida = True
                else:
                    tem_outro = True
        if c == "Salão":
            pecas_por_pedido.append(n_pecas)
            pecas199_por_pedido.append(n199)
            pecas299_por_pedido.append(n299)
            salao_com_bebida += 1 if tem_bebida else 0
            salao_com_peca += 1 if n_pecas > 0 else 0
            salao_so_peca += 1 if (n_pecas > 0 and not tem_bebida and not tem_outro) else 0
            h = (p.get("_criado") or "")[11:13]
            d = por_hora.setdefault(h, {"pedidos": 0, "faturamento": 0.0, "pecas": 0.0})
            d["pedidos"] += 1
            d["faturamento"] += num(p.get("total"))
            d["pecas"] += n_pecas

    r["soma_itens"] = soma_itens
    r["conferencia_itens_x_subtotal"] = soma_itens - r["subtotal_itens"]
    r["conferencia_total"] = r["subtotal_itens"] - r["descontos"] + r["taxa_entrega"] + r["taxa_servico"] - r["faturamento"]

    # peças (todos os canais)
    r["pecas_1_99_qtd"] = qtd["rolo_1_99"]
    r["pecas_1_99_receita"] = rec["rolo_1_99"]
    r["pecas_2_99_qtd"] = qtd["joy_niguiri_2_99"]
    r["pecas_2_99_receita"] = rec["joy_niguiri_2_99"]
    r["pecas_2_99_botao_peca_sushi"] = botao_299["PEÇA SUSHI"] + botao_299["PECA SUSHI"]
    r["pecas_2_99_botao_sunomono"] = botao_299["SUNOMONO"]
    r["pecas_2_99_botao_quarta_maluca"] = botao_299["QUARTA MALUCA"]
    r["pecas_1_99_botao_quarta_maluca"] = botao_199["QUARTA MALUCA"]
    r["pecas_1_99_botao_peca_sushi"] = botao_199["PEÇA SUSHI"] + botao_199["PECA SUSHI"]
    r["pecas_1_99_botao_sunomono"] = botao_199["SUNOMONO"]
    r["genericas_outro_preco_qtd"] = qtd["generica_outro_preco"]
    r["acarajapa_qtd"] = qtd["acarajapa"]
    r["acarajapa_receita"] = rec["acarajapa"]
    r["sashimi_qtd"] = qtd["sashimi"]
    r["sashimi_receita"] = rec["sashimi"]
    r["pecas_nomeadas_qtd"] = qtd["peca_nomeada"]
    r["pecas_nomeadas_receita"] = rec["peca_nomeada"]
    r["pecas_avulsas_qtd"] = sum(qtd[g] for g in GRUPOS_PECA)
    r["pecas_avulsas_receita"] = sum(rec[g] for g in GRUPOS_PECA)
    r["preco_medio_peca"] = r["pecas_avulsas_receita"] / r["pecas_avulsas_qtd"] if r["pecas_avulsas_qtd"] else 0.0
    gen = qtd["rolo_1_99"] + qtd["joy_niguiri_2_99"]
    r["pct_pecas_2_99_sobre_genericas"] = 100.0 * qtd["joy_niguiri_2_99"] / gen if gen else 0.0

    # salão
    r["salao_pecas_avulsas_qtd"] = sum(qtd_sal[g] for g in GRUPOS_PECA)
    r["salao_pecas_avulsas_receita"] = sum(rec_sal[g] for g in GRUPOS_PECA)
    r["salao_pecas_1_99_qtd"] = qtd_sal["rolo_1_99"]
    r["salao_pecas_2_99_qtd"] = qtd_sal["joy_niguiri_2_99"]
    r["salao_acarajapa_qtd"] = qtd_sal["acarajapa"]
    r["salao_sashimi_qtd"] = qtd_sal["sashimi"]
    n_sal = len(salao)
    r["pecas_por_pedido_salao"] = (sum(pecas_por_pedido) / n_sal) if n_sal else 0.0
    r["pecas_1_99_por_pedido_salao"] = (sum(pecas199_por_pedido) / n_sal) if n_sal else 0.0
    r["pecas_2_99_por_pedido_salao"] = (sum(pecas299_por_pedido) / n_sal) if n_sal else 0.0
    r["pecas_por_pedido_salao_mediana"] = statistics.median(pecas_por_pedido) if pecas_por_pedido else 0.0
    r["salao_pedidos_com_peca"] = salao_com_peca
    r["salao_pedidos_sem_peca"] = n_sal - salao_com_peca
    r["salao_pedidos_so_peca"] = salao_so_peca
    r["salao_pedidos_ate_10_pecas"] = sum(1 for x in pecas_por_pedido if 0 < x <= 10)
    r["salao_pedidos_11_a_20_pecas"] = sum(1 for x in pecas_por_pedido if 10 < x <= 20)
    r["salao_pedidos_21_a_30_pecas"] = sum(1 for x in pecas_por_pedido if 20 < x <= 30)
    r["salao_pedidos_31_a_50_pecas"] = sum(1 for x in pecas_por_pedido if 30 < x <= 50)
    r["salao_pedidos_mais_de_50_pecas"] = sum(1 for x in pecas_por_pedido if x > 50)
    r["salao_pedidos_com_peca_2_99"] = sum(1 for x in pecas299_por_pedido if x > 0)
    r["pct_salao_com_peca_2_99"] = 100.0 * r["salao_pedidos_com_peca_2_99"] / n_sal if n_sal else 0.0

    # bebidas
    r["bebidas_receita"] = rec["bebida"]
    r["bebidas_qtd"] = qtd["bebida"]
    r["bebidas_receita_salao"] = rec_sal["bebida"]
    r["bebidas_qtd_salao"] = qtd_sal["bebida"]
    r["bebidas_receita_cerveja"] = sub[("bebida", "cerveja")]
    r["bebidas_qtd_cerveja"] = subq[("bebida", "cerveja")]
    r["bebidas_receita_sem_alcool"] = sub[("bebida", "sem_alcool")]
    r["bebidas_qtd_sem_alcool"] = subq[("bebida", "sem_alcool")]
    r["salao_pedidos_com_bebida"] = salao_com_bebida
    r["pct_salao_com_bebida"] = 100.0 * salao_com_bebida / n_sal if n_sal else 0.0
    r["bebida_por_pedido_salao_reais"] = rec_sal["bebida"] / n_sal if n_sal else 0.0

    # cardápio normal
    r["cardapio_receita"] = rec["cardapio"]
    r["cardapio_qtd"] = qtd["cardapio"]
    for c in CANAIS:
        r[f"cardapio_receita_{c}"] = card_canal[c]
    r["cardapio_sobremesa_receita"] = sub[("cardapio", "sobremesa")]
    r["cardapio_ceviche_receita"] = sub[("cardapio", "ceviche_promo")]
    r["conferencia_grupos_x_itens"] = r["pecas_avulsas_receita"] + r["bebidas_receita"] + r["cardapio_receita"] - soma_itens

    # margem bruta estimada das peças genéricas + acarajapa + sashimi (custos do BRIEF)
    for idx, cen in enumerate(("otimista", "central", "pessimista")):
        custo = sum(qtd[g] * CUSTO_PECA[g][idx] for g in CUSTO_PECA)
        receita = sum(rec[g] for g in CUSTO_PECA)
        r[f"pecas_custo_{cen}"] = custo
        r[f"pecas_margem_{cen}"] = receita - custo
        r[f"pecas_margem_pct_{cen}"] = 100.0 * (receita - custo) / receita if receita else 0.0

    # blocos de hora no salão (hora de abertura do pedido)
    for nome, teste in (("18_21h", lambda h: 12 <= int(h) <= 21), ("22h_em_diante", lambda h: int(h) >= 22 or int(h) < 12)):
        ped_b = sum(v["pedidos"] for h, v in por_hora.items() if teste(h))
        fat_b = sum(v["faturamento"] for h, v in por_hora.items() if teste(h))
        pec_b = sum(v["pecas"] for h, v in por_hora.items() if teste(h))
        r[f"salao_{nome}_pedidos"] = ped_b
        r[f"salao_{nome}_faturamento"] = fat_b
        r[f"salao_{nome}_pecas"] = pec_b
        r[f"salao_{nome}_ticket"] = fat_b / ped_b if ped_b else 0.0
        r[f"salao_{nome}_pecas_por_pedido"] = pec_b / ped_b if ped_b else 0.0

    # produtos-chave no salão: quantidade, receita e hora da 1ª e da última venda
    chaves = collections.OrderedDict([
        ("suco_laranja", lambda t: t.lower().startswith("suco de laranja")),
        ("coca_original_1l", lambda t: t.lower() == "coca-cola original 1l"),
        ("coca_lata_350", lambda t: t.lower() in ("coca-cola original lata 350ml", "coca-cola zero açúcar 350ml")),
        ("cerveja", lambda t: bool(RE_CERVEJA.search(t))),
        ("sashimi", lambda t: t.upper() == "SASHIMI"),
        ("acarajapa", lambda t: t.upper() == "ACARAJAPA"),
    ])
    pk = {k: {"qtd": 0.0, "receita": 0.0, "horas": []} for k in chaves}
    operador = collections.defaultdict(lambda: collections.Counter())
    for p in salao:
        for i in itens(p):
            t = str(i.get("title") or "").strip()
            q = num(i.get("quantity"))
            hora = i.get("launched_at_label") or (p.get("_criado") or "")[11:16]
            for k, teste in chaves.items():
                if teste(t):
                    pk[k]["qtd"] += q
                    pk[k]["receita"] += q * num(i.get("price"))
                    pk[k]["horas"].append(hora)
            g, _ = classifica(i)
            if g in ("rolo_1_99", "joy_niguiri_2_99"):
                operador[str(i.get("added_by_user_name"))][g] += q
    ordem_hora = lambda h: (h < "12:00", h)
    for k, v in pk.items():
        hs = sorted(v["horas"], key=ordem_hora)
        r[f"salao_{k}_qtd"] = v["qtd"]
        r[f"salao_{k}_receita"] = v["receita"]
        r[f"salao_{k}_primeira_venda"] = hs[0] if hs else "-"
        r[f"salao_{k}_ultima_venda"] = hs[-1] if hs else "-"
    r["_operador"] = {k: {"pecas_1_99": v["rolo_1_99"], "pecas_2_99": v["joy_niguiri_2_99"],
                          "pct_2_99": 100.0 * v["joy_niguiri_2_99"] / (v["rolo_1_99"] + v["joy_niguiri_2_99"]) if (v["rolo_1_99"] + v["joy_niguiri_2_99"]) else 0.0}
                      for k, v in operador.items()}

    # descontos por origem
    desc = collections.Counter()
    desc_n = collections.Counter()
    for p in validos:
        d = num(p.get("discount"))
        if not d:
            continue
        orig = p.get("discount_origins")
        if isinstance(orig, str):
            try:
                orig = json.loads(orig)
            except ValueError:
                orig = []
        if not orig:
            desc[(canal(p), "sem origem")] += d
            desc_n[(canal(p), "sem origem")] += 1
        for o in orig or []:
            desc[(canal(p), str(o.get("kind")))] += num(o.get("value"))
            desc_n[(canal(p), str(o.get("kind")))] += 1
    r["desconto_ifood_loja"] = desc[("iFood", "loja")]
    r["desconto_ifood_loja_pedidos"] = desc_n[("iFood", "loja")]
    r["desconto_ifood_plataforma"] = desc[("iFood", "plataforma")]
    r["desconto_outros"] = r["descontos"] - desc[("iFood", "loja")] - desc[("iFood", "plataforma")]
    ifood = [p for p in validos if canal(p) == "iFood"]
    r["ifood_subtotal"] = sum(num(p.get("subtotal")) for p in ifood)
    r["pct_desconto_loja_sobre_subtotal_ifood"] = 100.0 * r["desconto_ifood_loja"] / r["ifood_subtotal"] if r["ifood_subtotal"] else 0.0
    r["ifood_comissao_estimada_25pct"] = 0.25 * r["fat_iFood"]

    r["_por_hora_salao"] = por_hora
    r["_auditoria"] = {g: sorted(v) for g, v in auditoria.items()}
    return r


def brl(v):
    s = f"{v:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


METRICAS = [
    # (chave, rótulo, unidade, tipo) tipo: R = reais, N = número, P = percentual, D = decimal
    ("faturamento", "Faturamento (pedidos não cancelados)", "R$", "R"),
    ("pedidos", "Pedidos (não cancelados)", "pedidos", "N"),
    ("cancelados", "Cancelados", "pedidos", "N"),
    ("cancelados_valor", "Valor dos cancelados", "R$", "R"),
    ("ticket_medio", "Ticket médio", "R$", "R"),
    ("fat_Salão", "Faturamento Salão", "R$", "R"),
    ("ped_Salão", "Pedidos Salão", "pedidos", "N"),
    ("ticket_Salão", "Ticket médio Salão", "R$", "R"),
    ("fat_App", "Faturamento App", "R$", "R"),
    ("ped_App", "Pedidos App", "pedidos", "N"),
    ("fat_iFood", "Faturamento iFood", "R$", "R"),
    ("ped_iFood", "Pedidos iFood", "pedidos", "N"),
    ("fat_PDV delivery", "Faturamento PDV delivery", "R$", "R"),
    ("ped_PDV delivery", "Pedidos PDV delivery", "pedidos", "N"),
    ("descontos", "Descontos concedidos", "R$", "R"),
    ("taxa_entrega", "Taxas de entrega cobradas", "R$", "R"),
    ("pecas_1_99_qtd", "Peças a R$ 1,99 (qtd)", "peças", "N"),
    ("pecas_1_99_receita", "Peças a R$ 1,99 (receita)", "R$", "R"),
    ("pecas_2_99_qtd", "Peças a R$ 2,99 Joy/niguiri (qtd)", "peças", "N"),
    ("pecas_2_99_receita", "Peças a R$ 2,99 Joy/niguiri (receita)", "R$", "R"),
    ("pct_pecas_2_99_sobre_genericas", "% das peças genéricas que são de R$ 2,99", "%", "P"),
    ("acarajapa_qtd", "Acarajapa (qtd)", "peças", "N"),
    ("acarajapa_receita", "Acarajapa (receita)", "R$", "R"),
    ("sashimi_qtd", "Sashimi (qtd)", "peças", "N"),
    ("sashimi_receita", "Sashimi (receita)", "R$", "R"),
    ("pecas_nomeadas_qtd", "Peças nomeadas '(1 peça)'/'(unidade)' (qtd)", "peças", "N"),
    ("pecas_nomeadas_receita", "Peças nomeadas (receita)", "R$", "R"),
    ("pecas_avulsas_qtd", "Total de peças avulsas (qtd, todos os canais)", "peças", "N"),
    ("pecas_avulsas_receita", "Total de peças avulsas (receita)", "R$", "R"),
    ("preco_medio_peca", "Preço médio por peça avulsa", "R$", "R"),
    ("salao_pecas_avulsas_qtd", "Peças avulsas no salão (qtd)", "peças", "N"),
    ("pecas_por_pedido_salao", "Peças avulsas por pedido de salão (média)", "peças/pedido", "D"),
    ("pecas_1_99_por_pedido_salao", "Peças de R$ 1,99 por pedido de salão", "peças/pedido", "D"),
    ("pecas_2_99_por_pedido_salao", "Peças de R$ 2,99 por pedido de salão", "peças/pedido", "D"),
    ("pecas_por_pedido_salao_mediana", "Peças avulsas por pedido de salão (mediana)", "peças/pedido", "D"),
    ("pct_salao_com_peca_2_99", "% dos pedidos de salão com peça de R$ 2,99", "%", "P"),
    ("bebidas_receita", "Bebidas (receita, todos os canais)", "R$", "R"),
    ("bebidas_receita_salao", "Bebidas (receita, salão)", "R$", "R"),
    ("bebidas_qtd_salao", "Bebidas (qtd, salão)", "un", "N"),
    ("bebidas_receita_cerveja", "Cervejas (receita)", "R$", "R"),
    ("bebidas_receita_sem_alcool", "Bebidas sem álcool (receita)", "R$", "R"),
    ("salao_pedidos_com_bebida", "Pedidos de salão com bebida", "pedidos", "N"),
    ("pct_salao_com_bebida", "% dos pedidos de salão com pelo menos uma bebida", "%", "P"),
    ("bebida_por_pedido_salao_reais", "Bebida por pedido de salão", "R$", "R"),
    ("cardapio_receita", "Cardápio normal (receita, fora peças e bebidas)", "R$", "R"),
    ("cardapio_receita_Salão", "Cardápio normal no salão", "R$", "R"),
    ("cardapio_receita_App", "Cardápio normal no App", "R$", "R"),
    ("cardapio_receita_iFood", "Cardápio normal no iFood", "R$", "R"),
    ("cardapio_receita_PDV delivery", "Cardápio normal no PDV delivery", "R$", "R"),
    ("salao_18_21h_pedidos", "Salão 18h-21h: pedidos", "pedidos", "N"),
    ("salao_18_21h_faturamento", "Salão 18h-21h: faturamento", "R$", "R"),
    ("salao_18_21h_pecas_por_pedido", "Salão 18h-21h: peças por pedido", "peças/pedido", "D"),
    ("salao_22h_em_diante_pedidos", "Salão 22h em diante: pedidos", "pedidos", "N"),
    ("salao_22h_em_diante_faturamento", "Salão 22h em diante: faturamento", "R$", "R"),
    ("salao_22h_em_diante_ticket", "Salão 22h em diante: ticket médio", "R$", "R"),
    ("salao_22h_em_diante_pecas_por_pedido", "Salão 22h em diante: peças por pedido", "peças/pedido", "D"),
    ("salao_suco_laranja_qtd", "Salão: suco de laranja (qtd)", "un", "N"),
    ("salao_suco_laranja_receita", "Salão: suco de laranja (receita)", "R$", "R"),
    ("salao_coca_original_1l_qtd", "Salão: Coca-Cola Original 1L (qtd)", "un", "N"),
    ("salao_coca_original_1l_receita", "Salão: Coca-Cola Original 1L (receita)", "R$", "R"),
    ("salao_coca_lata_350_qtd", "Salão: Coca lata 350ml normal+zero (qtd)", "un", "N"),
    ("salao_cerveja_qtd", "Salão: cervejas (qtd)", "un", "N"),
    ("salao_sashimi_qtd", "Salão: sashimi (qtd)", "peças", "N"),
    ("salao_sashimi_receita", "Salão: sashimi (receita)", "R$", "R"),
    ("desconto_ifood_loja", "Desconto da loja no iFood", "R$", "R"),
    ("desconto_ifood_plataforma", "Campanha iFood (reembolsada no acerto)", "R$", "R"),
    ("pct_desconto_loja_sobre_subtotal_ifood", "Desconto da loja / subtotal iFood", "%", "P"),
    ("ifood_comissao_estimada_25pct", "Comissão iFood estimada (25% do total)", "R$", "R"),
    ("pecas_custo_central", "Custo estimado das peças (cenário central)", "R$", "R"),
    ("pecas_margem_central", "Margem bruta estimada das peças (central)", "R$", "R"),
    ("pecas_margem_pct_central", "Margem bruta % das peças (central)", "%", "P"),
    ("pecas_margem_otimista", "Margem bruta estimada das peças (otimista)", "R$", "R"),
    ("pecas_margem_pessimista", "Margem bruta estimada das peças (pessimista)", "R$", "R"),
]


def fmt(v, tipo):
    if tipo == "R":
        return brl(v)
    if tipo == "N":
        return f"{v:,.0f}".replace(",", ".")
    if tipo == "P":
        return f"{v:.1f}%".replace(".", ",")
    return f"{v:.2f}".replace(".", ",")


def inclinacao(vals):
    n = len(vals)
    xm = (n - 1) / 2.0
    ym = sum(vals) / n
    den = sum((x - xm) ** 2 for x in range(n))
    return sum((x - xm) * (y - ym) for x, y in enumerate(vals)) / den if den else 0.0


def main(argv):
    saida_json = None
    args = list(argv)
    if "--json" in args:
        k = args.index("--json")
        saida_json = args[k + 1]
        del args[k:k + 2]
    if not args:
        print(__doc__)
        return 2
    dias = sorted((analisa(a) for a in args), key=lambda r: r["iso"])
    por_data = {d["data"]: d for d in dias}
    datas = [d["data"] for d in dias]
    alvo = "11/11"
    ant = "04/11"
    outubro = [d for d in datas if d.endswith("/10")]

    print("=" * 118)
    print("COMPARATIVO QUARTA MALUCA — Tili Sushi (loja 155) — datas:", ", ".join(datas))
    print("=" * 118)
    print("\n[1] Conferências (devem ser 0,00)")
    for d in dias:
        print(f"  {d['data']}: arquivo={d['pedidos_no_arquivo']} pedidos | 1º {d['primeiro_pedido']} | último {d['ultimo_pedido']} | "
              f"itens x subtotal={d['conferencia_itens_x_subtotal']:.2f} | subtotal-desc+entrega+serviço-total={d['conferencia_total']:.2f} | "
              f"grupos x itens={d['conferencia_grupos_x_itens']:.2f} | outros canais={d['ped_outros_canais']} | genéricas a outro preço={d['genericas_outro_preco_qtd']:.0f}")

    print("\n[2] Valores por data")
    cab = f"{'Métrica':58s}" + "".join(f"{x:>12s}" for x in datas)
    print(cab)
    print("-" * len(cab))
    for chave, rot, uni, tipo in METRICAS:
        print(f"{(rot + ' [' + uni + ']')[:58]:58s}" + "".join(f"{fmt(por_data[x][chave], tipo):>12s}" for x in datas))

    print("\n[3] Como as peças foram lançadas (botão usado) — qtd")
    for chave in ("pecas_1_99_botao_quarta_maluca", "pecas_1_99_botao_peca_sushi", "pecas_1_99_botao_sunomono",
                  "pecas_2_99_botao_peca_sushi", "pecas_2_99_botao_sunomono", "pecas_2_99_botao_quarta_maluca"):
        print(f"{chave:58s}" + "".join(f"{por_data[x][chave]:>12.0f}" for x in datas))

    print("\n[4] Salão — tamanho dos pedidos (nº de pedidos por faixa de peças avulsas)")
    for chave in ("salao_pedidos_sem_peca", "salao_pedidos_ate_10_pecas", "salao_pedidos_11_a_20_pecas", "salao_pedidos_21_a_30_pecas",
                  "salao_pedidos_31_a_50_pecas", "salao_pedidos_mais_de_50_pecas", "salao_pedidos_so_peca"):
        print(f"{chave:58s}" + "".join(f"{por_data[x][chave]:>12.0f}" for x in datas))

    print("\n[5] Salão por hora de abertura do pedido (pedidos | faturamento | peças)")
    horas = sorted({h for d in dias for h in d["_por_hora_salao"]}, key=lambda h: (int(h) < 12, int(h)))
    for h in horas:
        linha = f"  {h}h "
        for x in datas:
            v = por_data[x]["_por_hora_salao"].get(h)
            linha += (f"| {x}: {v['pedidos']:3d} ped R$ {brl(v['faturamento']):>9s} {v['pecas']:5.0f} pç " if v else f"| {x}:   0 ped R$ {'0,00':>9s}     0 pç ")
        print(linha)

    print(f"\n[5b] Salão por hora: {alvo} x {ant} (Δ pedidos | Δ faturamento | peças por pedido {alvo} x {ant} | ticket {alvo} x {ant})")
    for h in horas:
        a = por_data[alvo]["_por_hora_salao"].get(h, {"pedidos": 0, "faturamento": 0.0, "pecas": 0.0})
        b = por_data[ant]["_por_hora_salao"].get(h, {"pedidos": 0, "faturamento": 0.0, "pecas": 0.0})
        ppa = a["pecas"] / a["pedidos"] if a["pedidos"] else 0.0
        ppb = b["pecas"] / b["pedidos"] if b["pedidos"] else 0.0
        ta = a["faturamento"] / a["pedidos"] if a["pedidos"] else 0.0
        tb = b["faturamento"] / b["pedidos"] if b["pedidos"] else 0.0
        print(f"  {h}h: Δ pedidos {a['pedidos'] - b['pedidos']:+4d} | Δ faturamento {brl(a['faturamento'] - b['faturamento']):>10s} | peças/pedido {ppa:5.2f} x {ppb:5.2f} | ticket {brl(ta)} x {brl(tb)}")
    print("  peças por pedido às 22h, por data: " + " | ".join(
        f"{x}: {(por_data[x]['_por_hora_salao'].get('22', {'pecas': 0, 'pedidos': 0})['pecas'] / max(1, por_data[x]['_por_hora_salao'].get('22', {'pedidos': 0})['pedidos'])):.2f}" for x in datas))

    # comparações
    comp = collections.OrderedDict()
    print(f"\n[6] {alvo} x {ant} e x média das quartas de outubro ({', '.join(outubro)})")
    cab = f"{'Métrica':52s}{alvo:>11s}{ant:>11s}{'Δ':>11s}{'Δ%':>8s}{'média out':>12s}{'Δ':>11s}{'Δ%':>8s}"
    print(cab)
    print("-" * len(cab))
    for chave, rot, uni, tipo in METRICAS:
        a = por_data[alvo][chave]
        b = por_data[ant][chave]
        m = sum(por_data[x][chave] for x in outubro) / len(outubro)
        d1 = a - b
        d2 = a - m
        p1 = (100.0 * d1 / b) if b else None
        p2 = (100.0 * d2 / m) if m else None
        comp[chave] = {"rotulo": rot, "unidade": uni, "valor_11_11": a, "valor_04_11": b, "delta_vs_04_11": d1, "delta_pct_vs_04_11": p1,
                       "media_outubro": m, "delta_vs_media_outubro": d2, "delta_pct_vs_media_outubro": p2}
        fp = lambda p: (f"{p:+.1f}%".replace(".", ",") if p is not None else "n/d")
        fd = lambda v: ("+" if v >= 0 else "-") + fmt(abs(v), tipo if tipo != "P" else "D") + (" pp" if tipo == "P" else "")
        print(f"{rot[:52]:52s}{fmt(a, tipo):>11s}{fmt(b, tipo):>11s}{fd(d1):>11s}{fp(p1):>8s}{fmt(m, tipo):>12s}{fd(d2):>11s}{fp(p2):>8s}")

    # tendências
    tend = collections.OrderedDict()
    print("\n[7] Tendência nas 6 quartas (inclinação = variação média por semana, mínimos quadrados)")
    for chave, rot, uni, tipo in METRICAS:
        vals = [por_data[x][chave] for x in datas]
        inc = inclinacao(vals)
        media = sum(vals) / len(vals)
        quedas = sum(1 for k in range(1, len(vals)) if vals[k] < vals[k - 1])
        altas = sum(1 for k in range(1, len(vals)) if vals[k] > vals[k - 1])
        rel = (100.0 * inc / media) if media else 0.0
        if abs(rel) < 2.0:
            direcao = "estável"
        elif inc > 0:
            direcao = "subindo"
        else:
            direcao = "caindo"
        posicao = sorted(vals).index(vals[-1]) + 1
        tend[chave] = {"rotulo": rot, "inclinacao_por_semana": inc, "inclinacao_pct_da_media": rel, "direcao": direcao,
                       "quedas": quedas, "altas": altas, "posicao_11_11_do_menor_ao_maior": posicao,
                       "primeira": vals[0], "ultima": vals[-1]}
        print(f"{rot[:52]:52s} {direcao:8s} {('+' if inc >= 0 else '-') + fmt(abs(inc), tipo if tipo != 'P' else 'D'):>11s}/sem ({rel:+5.1f}% da média) | "
              f"quedas {quedas} altas {altas} | 11/11 é o {posicao}º menor de {len(vals)}")

    # decomposições
    print(f"\n[8] Decomposição da variação do faturamento do salão ({alvo} x base)")
    dec = collections.OrderedDict()
    A = por_data[alvo]
    bases = [(ant, por_data[ant]["ped_Salão"], por_data[ant]["ticket_Salão"], por_data[ant]["fat_Salão"]),
             ("média out", sum(por_data[x]["ped_Salão"] for x in outubro) / len(outubro), None, sum(por_data[x]["fat_Salão"] for x in outubro) / len(outubro))]
    for nome, pb, tb, fb in bases:
        if tb is None:
            tb = fb / pb  # ticket da base agregada
        ef_ped = (A["ped_Salão"] - pb) * tb
        ef_tic = (A["ticket_Salão"] - tb) * A["ped_Salão"]
        dec[nome] = {"delta_faturamento_salao": A["fat_Salão"] - fb, "efeito_numero_de_pedidos": ef_ped, "efeito_ticket": ef_tic,
                     "pedidos_base": pb, "ticket_base": tb}
        print(f"  x {nome}: Δ fat. salão = {brl(A['fat_Salão'] - fb)} = efeito nº de pedidos {brl(ef_ped)} ({A['ped_Salão']} x {pb:.1f} pedidos, ticket base {brl(tb)}) "
              f"+ efeito ticket {brl(ef_tic)} (ticket {brl(A['ticket_Salão'])} x {brl(tb)})")

    print(f"\n[9] Decomposição da variação da receita de itens ({alvo} x base), por grupo")
    dec_grupo = collections.OrderedDict()
    grupos = [("pecas_1_99_receita", "Peças 1,99"), ("pecas_2_99_receita", "Peças 2,99"), ("acarajapa_receita", "Acarajapa"),
              ("sashimi_receita", "Sashimi"), ("pecas_nomeadas_receita", "Peças nomeadas"), ("bebidas_receita", "Bebidas"),
              ("cardapio_receita", "Cardápio normal")]
    for nome, f_base in ((ant, lambda k: por_data[ant][k]), ("média out", lambda k: sum(por_data[x][k] for x in outubro) / len(outubro))):
        tot = 0.0
        dec_grupo[nome] = collections.OrderedDict()
        print(f"  x {nome}:")
        for k, rot in grupos:
            dlt = A[k] - f_base(k)
            tot += dlt
            dec_grupo[nome][rot] = dlt
            print(f"     {rot:18s} {brl(dlt):>12s}")
        outros = (A["taxa_entrega"] + A["taxa_servico"] - A["descontos"]) - (f_base("taxa_entrega") + f_base("taxa_servico") - f_base("descontos"))
        dec_grupo[nome]["Taxas - descontos"] = outros
        print(f"     {'Taxas - descontos':18s} {brl(outros):>12s}")
        print(f"     {'SOMA':18s} {brl(tot + outros):>12s}  (Δ faturamento = {brl(A['faturamento'] - f_base('faturamento'))})")
        dec_grupo[nome]["SOMA"] = tot + outros

    print("\n[11] Produtos-chave no salão: hora da 1ª e da última venda")
    for k in ("suco_laranja", "coca_original_1l", "coca_lata_350", "cerveja", "sashimi", "acarajapa"):
        print(f"  {k:18s} " + " | ".join(f"{x}: {por_data[x]['salao_' + k + '_qtd']:.0f} un, {por_data[x]['salao_' + k + '_primeira_venda']}-{por_data[x]['salao_' + k + '_ultima_venda']}" for x in datas))

    print("\n[12] Quem lançou as peças genéricas no salão (usuário do PDV) e % lançado a R$ 2,99")
    for x in datas:
        print(f"  {x}: " + " | ".join(f"{k}: 1,99={v['pecas_1_99']:.0f} 2,99={v['pecas_2_99']:.0f} ({v['pct_2_99']:.1f}% a 2,99)" for k, v in sorted(por_data[x]["_operador"].items())))

    print("\n[13] Potenciais simples (11/11 se repetisse o padrão de 04/11 ou da média de outubro)")
    pot = collections.OrderedDict()
    m_out = lambda k: sum(por_data[x][k] for x in outubro) / len(outubro)
    pot["bebida_salao_no_nivel_04_11"] = (por_data[ant]["bebida_por_pedido_salao_reais"] - A["bebida_por_pedido_salao_reais"]) * A["ped_Salão"]
    pot["bebida_salao_no_nivel_media_out"] = (m_out("bebida_por_pedido_salao_reais") - A["bebida_por_pedido_salao_reais"]) * A["ped_Salão"]
    pot["sashimi_pecas_a_menos_vs_04_11"] = por_data[ant]["sashimi_qtd"] - A["sashimi_qtd"]
    pot["sashimi_margem_perdida_vs_04_11"] = (por_data[ant]["sashimi_qtd"] - A["sashimi_qtd"]) * (4.99 - CUSTO_PECA["sashimi"][1])
    pot["suco_coca1l_sashimi_receita_a_menos_vs_04_11"] = sum(por_data[ant][k] - A[k] for k in ("salao_suco_laranja_receita", "salao_coca_original_1l_receita", "salao_sashimi_receita"))
    pot["salao_22h_faturamento_a_menos_vs_04_11"] = por_data[ant]["salao_22h_em_diante_faturamento"] - A["salao_22h_em_diante_faturamento"]
    pot["salao_18_21h_faturamento_a_menos_vs_04_11"] = por_data[ant]["salao_18_21h_faturamento"] - A["salao_18_21h_faturamento"]
    pot["salao_22h_faturamento_a_menos_vs_media_out"] = m_out("salao_22h_em_diante_faturamento") - A["salao_22h_em_diante_faturamento"]
    pot["salao_18_21h_faturamento_a_menos_vs_media_out"] = m_out("salao_18_21h_faturamento") - A["salao_18_21h_faturamento"]
    pot["margem_por_peca_1_99_central"] = 1.99 - CUSTO_PECA["rolo_1_99"][1]
    pot["margem_por_peca_2_99_central"] = 2.99 - CUSTO_PECA["joy_niguiri_2_99"][1]
    pot["margem_pct_peca_1_99_central"] = 100.0 * (1.99 - CUSTO_PECA["rolo_1_99"][1]) / 1.99
    pot["margem_pct_peca_2_99_central"] = 100.0 * (2.99 - CUSTO_PECA["joy_niguiri_2_99"][1]) / 2.99
    pot["margem_pct_peca_2_99_pessimista"] = 100.0 * (2.99 - CUSTO_PECA["joy_niguiri_2_99"][2]) / 2.99
    pot["ifood_desconto_loja_mais_comissao_11_11"] = A["desconto_ifood_loja"] + A["ifood_comissao_estimada_25pct"]
    pot["ifood_desconto_loja_mais_comissao_pct_do_subtotal_11_11"] = 100.0 * (A["desconto_ifood_loja"] + A["ifood_comissao_estimada_25pct"]) / A["ifood_subtotal"] if A["ifood_subtotal"] else 0.0
    pot["queda_fat_07_10_a_11_11"] = A["faturamento"] - por_data[datas[0]]["faturamento"]
    pot["queda_fat_07_10_a_11_11_pct"] = 100.0 * (A["faturamento"] - por_data[datas[0]]["faturamento"]) / por_data[datas[0]]["faturamento"]
    pot["media_ticket_salao_ultimas_3"] = sum(por_data[x]["ticket_Salão"] for x in datas[-3:]) / 3
    pot["media_ticket_salao_primeiras_3"] = sum(por_data[x]["ticket_Salão"] for x in datas[:3]) / 3
    pot["media_pecas_por_pedido_ultimas_3"] = sum(por_data[x]["pecas_por_pedido_salao"] for x in datas[-3:]) / 3
    pot["media_pecas_por_pedido_primeiras_3"] = sum(por_data[x]["pecas_por_pedido_salao"] for x in datas[:3]) / 3
    d_salao_ant = A["fat_Salão"] - por_data[ant]["fat_Salão"]
    pot["pct_da_queda_do_salao_vs_04_11_que_veio_apos_22h"] = 100.0 * (A["salao_22h_em_diante_faturamento"] - por_data[ant]["salao_22h_em_diante_faturamento"]) / d_salao_ant if d_salao_ant else 0.0
    fora = lambda d: d["fat_App"] + d["fat_iFood"] + d["fat_PDV delivery"]
    pot["fora_do_salao_11_11"] = fora(A)
    pot["fora_do_salao_04_11"] = fora(por_data[ant])
    pot["fora_do_salao_media_out"] = sum(fora(por_data[x]) for x in outubro) / len(outubro)
    pot["fora_do_salao_delta_vs_04_11"] = fora(A) - fora(por_data[ant])
    pot["fora_do_salao_delta_vs_media_out"] = fora(A) - pot["fora_do_salao_media_out"]
    pot["pct_salao_no_faturamento_11_11"] = 100.0 * A["fat_Salão"] / A["faturamento"]
    pot["pct_salao_no_faturamento_04_11"] = 100.0 * por_data[ant]["fat_Salão"] / por_data[ant]["faturamento"]
    pot["suco_e_coca1l_receita_a_menos_vs_04_11"] = sum(por_data[ant][k] - A[k] for k in ("salao_suco_laranja_receita", "salao_coca_original_1l_receita"))
    pot["suco_e_coca1l_receita_a_menos_vs_media_out"] = sum(m_out(k) - A[k] for k in ("salao_suco_laranja_receita", "salao_coca_original_1l_receita"))
    pot["bebidas_salao_receita_a_menos_vs_04_11"] = por_data[ant]["bebidas_receita_salao"] - A["bebidas_receita_salao"]
    pot["margem_por_peca_1_99_pessimista"] = 1.99 - CUSTO_PECA["rolo_1_99"][2]
    pot["margem_por_peca_2_99_pessimista"] = 2.99 - CUSTO_PECA["joy_niguiri_2_99"][2]
    pot["margem_por_peca_1_99_otimista"] = 1.99 - CUSTO_PECA["rolo_1_99"][0]
    pot["margem_por_peca_2_99_otimista"] = 2.99 - CUSTO_PECA["joy_niguiri_2_99"][0]
    pot["margem_por_peca_sashimi"] = 4.99 - CUSTO_PECA["sashimi"][1]
    pot["margem_por_peca_acarajapa"] = 2.99 - CUSTO_PECA["acarajapa"][1]
    for x in datas:
        d = por_data[x]
        pot[f"salao_pedidos_mais_de_30_pecas_{x}"] = d["salao_pedidos_31_a_50_pecas"] + d["salao_pedidos_mais_de_50_pecas"]
        pot[f"salao_pedidos_ate_10_pecas_{x}"] = d["salao_pedidos_ate_10_pecas"]
        pot[f"pct_salao_no_faturamento_{x}"] = 100.0 * d["fat_Salão"] / d["faturamento"]
    # se a fatia de peças a 2,99 de 04/11 fosse igual à de 11/11 (sensibilidade do lançamento): cada peça vale R$ 1,00 de diferença
    gen_ant = por_data[ant]["pecas_1_99_qtd"] + por_data[ant]["pecas_2_99_qtd"]
    pot["pecas_04_11_que_mudariam_de_preco_com_a_fatia_de_11_11"] = gen_ant * (A["pct_pecas_2_99_sobre_genericas"] - por_data[ant]["pct_pecas_2_99_sobre_genericas"]) / 100.0
    pot["pontos_pct_fatia_2_99_11_11_menos_04_11"] = A["pct_pecas_2_99_sobre_genericas"] - por_data[ant]["pct_pecas_2_99_sobre_genericas"]
    if "28/10" in por_data:
        pot["faturamento_11_11_menos_28_10"] = A["faturamento"] - por_data["28/10"]["faturamento"]
        pot["faturamento_11_11_vs_28_10_pct"] = 100.0 * (A["faturamento"] - por_data["28/10"]["faturamento"]) / por_data["28/10"]["faturamento"]
        pot["fat_salao_11_11_menos_28_10"] = A["fat_Salão"] - por_data["28/10"]["fat_Salão"]
    pot["fat_salao_07_10_a_11_11_pct"] = 100.0 * (A["fat_Salão"] - por_data[datas[0]]["fat_Salão"]) / por_data[datas[0]]["fat_Salão"]
    pot["fat_app_07_10_a_11_11"] = A["fat_App"] - por_data[datas[0]]["fat_App"]
    pot["pecas_1_99_07_10_a_11_11_pct"] = 100.0 * (A["pecas_1_99_qtd"] - por_data[datas[0]]["pecas_1_99_qtd"]) / por_data[datas[0]]["pecas_1_99_qtd"]
    pot["app_pecas_nomeadas_receita_07_10"] = por_data[datas[0]]["pecas_nomeadas_receita"]
    for k, v in pot.items():
        print(f"  {k:58s} {v:12.2f}")

    print("\n[10] Auditoria da classificação (títulos por grupo, todas as datas)")
    aud = collections.defaultdict(set)
    for d in dias:
        for g, ts in d["_auditoria"].items():
            aud[g].update(ts)
    for g in sorted(aud):
        print(f"  {g} ({len(aud[g])}): " + "; ".join(sorted(aud[g])))

    if saida_json:
        out = {"datas": datas, "por_data": {d["data"]: {k: v for k, v in d.items() if k != "_auditoria"} for d in dias},
               "comparacao_11_11": comp, "tendencia": tend, "decomposicao_salao": dec, "decomposicao_grupos": dec_grupo, "potenciais": pot}
        Path(saida_json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print("\nJSON gravado em", saida_json)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
