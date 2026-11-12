#!/usr/bin/env python3
"""Quarta Maluca 11/11/2026 - OPERACAO E COMPORTAMENTO DE CONSUMO.

Uso (somente leitura, so arquivos locais):
  python3 -I operacao.py <pedidos_da_noite.json> [pedidos_de_quartas_anteriores.json ...] [--json saida.json]

O 1o arquivo e a noite analisada. Os demais (opcionais) servem so de referencia
para "preco padrao" e para o contexto de lancamento (quem lancou, promo fora do salao).
Nao imprime CPF, CNPJ, chave de nota, telefone nem nome de cliente.
"""
import collections
import json
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

BA = timezone(timedelta(hours=-3))

# ---- regras de custo do BRIEF (usadas so para a faixa de incerteza e margem de bebida)
CUSTO_ROLO = {"otimista": 0.45, "central": 0.60, "pessimista": 0.72}
CUSTO_JOYNIG = {"otimista": 0.97, "central": 1.41, "pessimista": 1.85}
CUSTO_REFRI_PCT = 0.35
TAXA_CARTAO = 0.02
COMISSAO_IFOOD = 0.25

CATS_BEBIDA = {"Bebidas", "Cervejas"}
CAT_SOBREMESA = "Picolés & Sorvetes"
CAT_PROMO = "Promoção do Dia"
RE_BEBIDA_TITULO = re.compile(r"coca|guaran|fanta|sprite|água|agua|suco|heineken|corona|stella|cerveja|refrigerante|h2o", re.I)
RE_UNIT = re.compile(r"\((1 pe[çc]a|unidade)\)", re.I)


def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(a, b):
    return 0.0 if not b else 100.0 * a / b


def perc(xs, p):
    """Percentil com interpolacao linear (igual ao padrao do numpy)."""
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def carrega(caminho):
    d = json.load(open(caminho, encoding="utf-8"))
    if isinstance(d, dict):
        d = d.get("orders") or d.get("data") or []
    for o in d:
        it = o.get("items_json")
        if isinstance(it, str):
            try:
                it = json.loads(it)
            except Exception:
                it = []
        o["_itens"] = it or []
        o["_dt"] = datetime.strptime(o["created_at"], "%d/%m/%Y %H:%M").replace(tzinfo=BA)
        o["_canal"] = canal(o)
        o["_cancelado"] = "CANCEL" in str(o.get("status") or "").upper()
    return d


def canal(o):
    ps = o.get("platform_slug")
    if ps == "pdv":
        return "pdv_delivery" if o.get("delivery_type") == "delivery" else "salao"
    return ps or "?"


def q(i):
    return float(i.get("quantity") or 0)


def pr(i):
    return float(i.get("price") or 0)


def tipo_peca(i):
    """Classifica a linha como peca avulsa (pelo PRECO, como manda o BRIEF) ou None."""
    t = (i.get("title") or "").strip()
    tu = t.upper()
    p = round(pr(i), 2)
    if tu in ("QUARTA MALUCA", "PEÇA SUSHI", "PECA SUSHI"):
        if p == 1.99:
            return "rolo_1_99"
        if p == 2.99:
            return "joy_niguiri_2_99"
        return "generico_outro_preco"
    if tu == "SUNOMONO" and p == 2.99:
        return "joy_niguiri_2_99"
    if tu == "ACARAJAPA":
        return "acarajapa"
    if tu == "SASHIMI":
        return "sashimi"
    if RE_UNIT.search(t):
        return "unidade_especifica"
    return None


def generico(i):
    """Produto em que nao da para saber a peca."""
    tu = (i.get("title") or "").strip().upper()
    return tu in ("QUARTA MALUCA", "PEÇA SUSHI", "PECA SUSHI") or (tu == "SUNOMONO" and round(pr(i), 2) == 2.99)


def eh_bebida(i):
    c = i.get("category_name")
    if c:
        return c in CATS_BEBIDA
    return bool(RE_BEBIDA_TITULO.search(i.get("title") or ""))


def hora_item(i, o):
    lab = i.get("launched_at_label")
    if lab and re.match(r"^\d\d:\d\d$", lab):
        return lab
    return o["created_at"][11:16]


RE_PAG = re.compile(
    r"^(?P<nome>.+?)(?:\s*\(Troco -> R\$ (?P<troco_d>[\d.]+)\))?(?::\s*(?P<val>[\d.]+))?(?:\s*\(Troco: (?P<troco>[\d.]+)\))?$"
)


def grupo_pag(nome):
    n = nome.lower()
    if n.startswith("ifood online"):
        return "iFood online"
    if "crédito" in n or "credito" in n:
        return "Cartão crédito"
    if "débito" in n or "debito" in n:
        return "Cartão débito"
    if n.startswith("pix"):
        return "Pix"
    if n.startswith("dinheiro"):
        return "Dinheiro"
    if "ticket" in n or "alelo" in n or "vr " in n or "refei" in n or "sodexo" in n:
        return "Vale-refeição"
    return "Outros (" + nome + ")"


def parse_pagamento(o):
    """Devolve lista de (grupo, nome, valor_liquido, troco_em_nao_dinheiro)."""
    s = (o.get("payment_method") or "").strip()
    partes = [x.strip() for x in s.split("|") if x.strip()]
    out = []
    for part in partes:
        m = RE_PAG.match(part)
        if not m:
            out.append(["Outros (" + part + ")", part, None, 0.0])
            continue
        nome = m.group("nome").strip()
        val = float(m.group("val")) if m.group("val") else None
        troco = float(m.group("troco")) if m.group("troco") else 0.0
        # "Dinheiro (Troco -> R$ X): V" -> V ja e o valor liquido (conferido contra o total).
        # "Metodo: V (Troco: X)"         -> liquido = V - X.
        liq = None if val is None else val - troco
        out.append([grupo_pag(nome), nome, liq, troco if not nome.lower().startswith("dinheiro") else 0.0])
    sem_valor = [x for x in out if x[2] is None]
    conhecido = sum(x[2] for x in out if x[2] is not None)
    if len(sem_valor) == 1:
        sem_valor[0][2] = float(o["total"]) - conhecido
    elif len(sem_valor) > 1:
        for x in sem_valor:
            x[2] = (float(o["total"]) - conhecido) / len(sem_valor)
    if not out:
        out.append(["Sem forma informada", "", float(o["total"]), 0.0])
    return out


def main():
    args = sys.argv[1:]
    saida_json = None
    if "--json" in args:
        k = args.index("--json")
        saida_json = args[k + 1]
        args = args[:k] + args[k + 2:]
    if not args:
        print(__doc__)
        sys.exit(2)
    arq = args[0]
    refs = args[1:]
    todos = carrega(arq)
    R = {}  # resultados para o JSON

    canc = [o for o in todos if o["_cancelado"]]
    ok = [o for o in todos if not o["_cancelado"]]
    salao = [o for o in ok if o["_canal"] == "salao"]
    fat_total = sum(o["total"] for o in ok)
    fat_salao = sum(o["total"] for o in salao)

    print("=" * 100)
    print("0. BASE")
    print("=" * 100)
    print(f"arquivo: {arq.split('/')[-1]} | pedidos no arquivo: {len(todos)} | validos: {len(ok)} | cancelados: {len(canc)}")
    por_canal = collections.OrderedDict()
    for c in ("salao", "pdv_delivery", "app", "ifood"):
        os_ = [o for o in ok if o["_canal"] == c]
        por_canal[c] = {"pedidos": len(os_), "faturamento": round(sum(o["total"] for o in os_), 2)}
        print(f"  {c:13s} pedidos {len(os_):4d}  faturamento {brl(sum(o['total'] for o in os_)):>14s}  ({pct(sum(o['total'] for o in os_), fat_total):5.1f}%)")
    print(f"  {'TOTAL':13s} pedidos {len(ok):4d}  faturamento {brl(fat_total):>14s}")
    print(f"  primeiro pedido: {min(o['_dt'] for o in ok).strftime('%d/%m %H:%M')} | ultimo: {max(o['_dt'] for o in ok).strftime('%d/%m %H:%M')}")
    # conferencia: total = subtotal + entrega + servico - desconto ; subtotal = soma dos itens
    n_formula = sum(1 for o in ok if abs(o["subtotal"] + o["delivery_fee"] + o["service_fee"] - o["discount"] - o["total"]) > 0.02)
    n_itens = sum(1 for o in ok if abs(sum(q(i) * pr(i) for i in o["_itens"]) - o["subtotal"]) > 0.02)
    print(f"  conferencia: pedidos em que total != subtotal+entrega+servico-desconto: {n_formula} | subtotal != soma dos itens: {n_itens}")
    R["base"] = {"pedidos_arquivo": len(todos), "validos": len(ok), "cancelados": len(canc), "faturamento_total": round(fat_total, 2),
                 "por_canal": por_canal, "primeiro": min(o["_dt"] for o in ok).strftime("%H:%M"), "ultimo": max(o["_dt"] for o in ok).strftime("%H:%M")}

    # ------------------------------------------------------------------ 1. CURVA POR HORA
    print()
    print("=" * 100)
    print("1. CURVA POR HORA (hora da Bahia)")
    print("=" * 100)
    horas = sorted({o["created_at"][11:13] for o in ok} | {hora_item(i, o)[:2] for o in ok for i in o["_itens"]})
    H = {h: {"pedidos": 0, "pedidos_salao": 0, "fat": 0.0, "fat_salao": 0.0, "pecas": 0.0, "rolo_1_99": 0.0, "joy_niguiri_2_99": 0.0,
             "acarajapa": 0.0, "sashimi": 0.0, "unidade_especifica": 0.0, "bebida_ped": 0, "pecas_salao": 0.0} for h in horas}
    for o in ok:
        h = o["created_at"][11:13]
        H[h]["pedidos"] += 1
        H[h]["fat"] += o["total"]
        if o["_canal"] == "salao":
            H[h]["pedidos_salao"] += 1
            H[h]["fat_salao"] += o["total"]
            if any(eh_bebida(i) for i in o["_itens"]):
                H[h]["bebida_ped"] += 1
        for i in o["_itens"]:
            tp = tipo_peca(i)
            if tp and tp != "generico_outro_preco":
                hi = hora_item(i, o)[:2]
                H[hi]["pecas"] += q(i)
                H[hi][tp] += q(i)
                if o["_canal"] == "salao":
                    H[hi]["pecas_salao"] += q(i)
    tot_ped = sum(v["pedidos"] for v in H.values())
    tot_pec = sum(v["pecas"] for v in H.values())
    tot_fat = sum(v["fat"] for v in H.values())
    print("hora | pedidos (%)  | salao | pecas avulsas (%) [rolo1,99 / joy-nig2,99 / acarajapa / sashimi / unid] | faturamento (%) | fat salao | ticket salao | pecas/ped salao | %ped salao c/ bebida")
    for h in horas:
        v = H[h]
        print(f" {h}h | {v['pedidos']:3d} ({pct(v['pedidos'], tot_ped):4.1f}%) | {v['pedidos_salao']:3d}   | {v['pecas']:6.0f} ({pct(v['pecas'], tot_pec):4.1f}%) "
              f"[{v['rolo_1_99']:.0f} / {v['joy_niguiri_2_99']:.0f} / {v['acarajapa']:.0f} / {v['sashimi']:.0f} / {v['unidade_especifica']:.0f}] | "
              f"{brl(v['fat']):>13s} ({pct(v['fat'], tot_fat):4.1f}%) | {brl(v['fat_salao']):>12s} | "
              f"{brl(v['fat_salao'] / v['pedidos_salao']) if v['pedidos_salao'] else '-':>9s} | "
              f"{(v['pecas_salao'] / v['pedidos_salao']) if v['pedidos_salao'] else 0:5.1f} | {pct(v['bebida_ped'], v['pedidos_salao']):4.1f}%")
    print(f" tot | {tot_ped:3d}          | {len(salao):3d}   | {tot_pec:6.0f}        | {brl(tot_fat)}")

    def pico(chave):
        h = max(horas, key=lambda x: H[x][chave])
        return h, H[h][chave]

    def top2(chave, total):
        hs = sorted(horas, key=lambda x: -H[x][chave])[:2]
        s = sum(H[x][chave] for x in hs)
        return sorted(hs), s, pct(s, total)

    def janela2(chave, total):
        best = None
        for a in range(len(horas) - 1):
            if int(horas[a + 1]) - int(horas[a]) != 1:
                continue
            s = H[horas[a]][chave] + H[horas[a + 1]][chave]
            if best is None or s > best[1]:
                best = ((horas[a], horas[a + 1]), s)
        return best[0], best[1], pct(best[1], total)

    R["curva"] = {"por_hora": {h: {k: round(v, 2) for k, v in H[h].items()} for h in horas}}
    for nome, chave, total in (("pedidos", "pedidos", tot_ped), ("pecas avulsas", "pecas", tot_pec), ("faturamento", "fat", tot_fat)):
        hp, vp = pico(chave)
        hs, s2, p2 = top2(chave, total)
        jj, sj, pj = janela2(chave, total)
        print(f"  PICO de {nome}: {hp}h com {vp:,.2f} ({pct(vp, total):.1f}% do total) | 2 horas mais cheias: {hs[0]}h e {hs[1]}h = {s2:,.2f} ({p2:.1f}%) | melhor janela de 2h seguidas: {jj[0]}h-{jj[1]}h = {pj:.1f}%")
        R["curva"]["pico_" + chave] = {"hora": hp, "valor": round(vp, 2), "pct": round(pct(vp, total), 2), "top2_horas": hs, "top2_valor": round(s2, 2), "top2_pct": round(p2, 2),
                                       "janela2h": list(jj), "janela2h_pct": round(pj, 2)}
    # 3 horas centrais
    for chave, total in (("pedidos", tot_ped), ("pecas", tot_pec), ("fat", tot_fat)):
        hs = sorted(horas, key=lambda x: -H[x][chave])[:3]
        s = sum(H[x][chave] for x in hs)
        print(f"  3 horas mais cheias em {chave}: {sorted(hs)} = {pct(s, total):.1f}%")
        R["curva"]["top3_pct_" + chave] = round(pct(s, total), 2)
    # blocos de 30 min e janelas moveis
    b30 = collections.OrderedDict()
    for o in sorted(ok, key=lambda x: x["_dt"]):
        k = o["_dt"].strftime("%H:") + ("00" if o["_dt"].minute < 30 else "30")
        b = b30.setdefault(k, {"pedidos": 0, "salao": 0, "fat": 0.0, "pecas": 0.0})
        b["pedidos"] += 1
        b["fat"] += o["total"]
        if o["_canal"] == "salao":
            b["salao"] += 1
        b["pecas"] += sum(q(i) for i in o["_itens"] if tipo_peca(i))
    print("  blocos de 30 min (pedidos / salao / pecas / faturamento):")
    for k, b in b30.items():
        print(f"    {k}  {b['pedidos']:3d} / {b['salao']:3d} / {b['pecas']:5.0f} / {brl(b['fat'])}")
    R["curva"]["blocos_30min"] = {k: {a: round(v, 2) for a, v in b.items()} for k, b in b30.items()}
    for corte in ("22:00", "22:30", "23:00"):
        hh, mm = int(corte[:2]), int(corte[3:])
        tarde = [o for o in ok if (o["_dt"].hour, o["_dt"].minute) >= (hh, mm)]
        tarde_s = [o for o in tarde if o["_canal"] == "salao"]
        print(f"  depois das {corte}: {len(tarde)} pedidos ({pct(len(tarde), len(ok)):.1f}%), {brl(sum(o['total'] for o in tarde))} ({pct(sum(o['total'] for o in tarde), fat_total):.1f}% da noite) | so salao: {len(tarde_s)} pedidos, {brl(sum(o['total'] for o in tarde_s))}")
        R["curva"]["depois_" + corte.replace(":", "h")] = {"pedidos": len(tarde), "valor": round(sum(o["total"] for o in tarde), 2), "pct_valor": round(pct(sum(o["total"] for o in tarde), fat_total), 2),
                                                          "salao_pedidos": len(tarde_s), "salao_valor": round(sum(o["total"] for o in tarde_s), 2)}
    cedo = [o for o in ok if o["_dt"].hour < 19]
    print(f"  antes das 19h: {len(cedo)} pedidos, {brl(sum(o['total'] for o in cedo))} ({pct(sum(o['total'] for o in cedo), fat_total):.1f}%)")
    pdv = sorted([o for o in ok if o["platform_slug"] == "pdv"], key=lambda x: x["_dt"])

    def janela_movel(lista, minutos, valor=lambda o: 1):
        best = (0, None)
        for a in lista:
            fim = a["_dt"] + timedelta(minutes=minutos)
            s = sum(valor(b) for b in lista if a["_dt"] <= b["_dt"] < fim)
            if s > best[0]:
                best = (s, a["_dt"].strftime("%H:%M"))
        return best

    pecas_ped = lambda o: sum(q(i) for i in o["_itens"] if tipo_peca(i))
    for m in (10, 15, 30, 60):
        n, ini = janela_movel(pdv, m)
        pcs, ini2 = janela_movel(pdv, m, pecas_ped)
        print(f"  caixa (PDV) - maior movimento em {m:2d} min seguidos: {n} pedidos a partir de {ini} (1 pedido a cada {m * 60 / n:.0f} s) | pecas: {pcs:.0f} a partir de {ini2} ({pcs / m:.1f} pecas/min)")
        R["curva"][f"pdv_max_{m}min"] = {"pedidos": n, "inicio": ini, "seg_por_pedido": round(m * 60 / n, 1), "pecas": pcs, "inicio_pecas": ini2, "pecas_por_min": round(pcs / m, 2)}
    # minutos com mais de 1 pedido no caixa
    pm = collections.Counter(o["created_at"][11:16] for o in pdv)
    print(f"  minutos com 3 ou mais pedidos lancados no PDV: {sum(1 for v in pm.values() if v >= 3)} | maximo num mesmo minuto: {max(pm.values())} pedidos")
    R["curva"]["pdv_max_mesmo_minuto"] = max(pm.values())
    R["curva"]["pdv_minutos_3_ou_mais"] = sum(1 for v in pm.values() if v >= 3)
    # diferenca lancamento x criacao
    gaps = []
    multi = 0
    for o in salao:
        labs = set()
        for i in o["_itens"]:
            la = i.get("launched_at")
            labs.add(i.get("launched_at_label"))
            if la:
                gaps.append((datetime.fromisoformat(la).astimezone(BA) - o["_dt"]).total_seconds() / 60)
        if len(labs) > 1:
            multi += 1
    print(f"  salao: diferenca entre criacao do pedido e lancamento dos itens: mediana {statistics.median(gaps):.1f} min, maximo {max(gaps):.1f} min; pedidos com itens lancados em minutos diferentes: {multi}")
    print("    -> o pedido nasce e e pago de uma vez no caixa: a curva e a do movimento no caixa, nao da permanencia na mesa.")
    R["curva"]["salao_gap_lancamento_mediana_min"] = round(statistics.median(gaps), 2)
    R["curva"]["salao_gap_lancamento_max_min"] = round(max(gaps), 2)
    R["curva"]["salao_pedidos_multi_lancamento"] = multi
    # KDS (so informativo): lancamento -> entrada na etapa 1
    kds = collections.defaultdict(dict)
    kds_linhas = collections.Counter()
    for o in ok:
        for i in o["_itens"]:
            tem = bool(i.get("stage_entry_time") and i.get("launched_at"))
            kds_linhas[(o["_canal"], tem)] += 1
            if tem:
                g = (datetime.fromisoformat(i["stage_entry_time"]) - datetime.fromisoformat(i["launched_at"])).total_seconds() / 60
                kds[o["_canal"]][o["id"]] = (max(g, kds[o["_canal"]].get(o["id"], (0,))[0]), o["created_at"][11:16])
    print("  KDS (tempo do lancamento ate o item mudar de etapa na tela da cozinha; so pedidos que tem esse registro):")
    R["curva"]["kds"] = {}
    for c, dd in kds.items():
        xs = sorted(v[0] for v in dd.values())
        pior = max(dd.values())
        tot_l = kds_linhas[(c, True)] + kds_linhas[(c, False)]
        print(f"    {c:13s} pedidos com registro {len(xs):3d} (linhas com registro {kds_linhas[(c, True)]}/{tot_l}) | mediana {statistics.median(xs):.1f} min | p90 {perc(xs, 0.9):.1f} | max {pior[0]:.1f} min (pedido das {pior[1]}) | acima de 30 min: {sum(1 for x in xs if x > 30)}")
        R["curva"]["kds"][c] = {"pedidos": len(xs), "linhas_com_registro": kds_linhas[(c, True)], "linhas": tot_l, "mediana_min": round(statistics.median(xs), 1),
                                "p90_min": round(perc(xs, 0.9), 1), "max_min": round(pior[0], 1), "hora_max": pior[1], "acima_30": sum(1 for x in xs if x > 30)}

    # ------------------------------------------------------------------ 2. PEDIDOS DE SALAO
    print()
    print("=" * 100)
    print("2. PEDIDOS DE SALAO")
    print("=" * 100)
    for o in salao:
        o["_pecas"] = collections.Counter()
        for i in o["_itens"]:
            tp = tipo_peca(i)
            if tp:
                o["_pecas"][tp] += q(i)
        o["_npecas"] = sum(o["_pecas"].values())
        o["_beb_val"] = sum(q(i) * pr(i) for i in o["_itens"] if eh_bebida(i))
        o["_beb_qtd"] = sum(q(i) for i in o["_itens"] if eh_bebida(i))
        o["_sobremesa_val"] = sum(q(i) * pr(i) for i in o["_itens"] if i.get("category_name") == CAT_SOBREMESA)
        o["_promo_val"] = sum(q(i) * pr(i) for i in o["_itens"] if tipo_peca(i))
        o["_outros_val"] = sum(q(i) * pr(i) for i in o["_itens"] if not tipo_peca(i) and not eh_bebida(i) and i.get("category_name") != CAT_SOBREMESA)
    tk = [o["total"] for o in salao]
    print(f"pedidos de salao: {len(salao)} | faturamento {brl(fat_salao)} ({pct(fat_salao, fat_total):.1f}% da noite)")
    print(f"ticket: medio {brl(statistics.mean(tk))} | mediana {brl(statistics.median(tk))} | p25 {brl(perc(tk, .25))} | p75 {brl(perc(tk, .75))} | p90 {brl(perc(tk, .9))} | min {brl(min(tk))} | max {brl(max(tk))}")
    com_pecas = [o for o in salao if o["_npecas"] > 0]
    np_ = [o["_npecas"] for o in com_pecas]
    np_all = [o["_npecas"] for o in salao]
    tot_pecas_salao = sum(np_)
    comp = collections.Counter()
    comp_val = collections.Counter()
    for o in salao:
        for i in o["_itens"]:
            tp = tipo_peca(i)
            if tp:
                comp[tp] += q(i)
                comp_val[tp] += q(i) * pr(i)
    print(f"pecas avulsas no salao: {tot_pecas_salao:.0f} = " + " + ".join(f"{k} {v:.0f} ({brl(comp_val[k])})" for k, v in comp.most_common()))
    print(f"  receita das pecas avulsas: {brl(sum(comp_val.values()))} ({pct(sum(comp_val.values()), fat_salao):.1f}% do salao) | preco medio por peca: {brl(sum(comp_val.values()) / tot_pecas_salao)}")
    print(f"  participacao das pecas de 2,99 (joy/niguiri) nas pecas de sushi (rolo+joy/niguiri): {pct(comp['joy_niguiri_2_99'], comp['joy_niguiri_2_99'] + comp['rolo_1_99']):.1f}%")
    print(f"pecas por pedido (pedidos com pelo menos 1 peca, n={len(com_pecas)}): media {statistics.mean(np_):.1f} | mediana {statistics.median(np_):.0f} | p25 {perc(np_, .25):.0f} | p75 {perc(np_, .75):.0f} | p90 {perc(np_, .9):.1f} | max {max(np_):.0f}")
    print(f"pecas por pedido (todos os {len(salao)} pedidos de salao): media {statistics.mean(np_all):.1f} | mediana {statistics.median(np_all):.0f} | p90 {perc(np_all, .9):.1f}")
    print(f"pedidos de salao sem nenhuma peca avulsa: {len(salao) - len(com_pecas)}")
    faixas = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 30), (31, 40), (41, 60), (61, 999)]
    print("  distribuicao por tamanho (pecas no pedido): pedidos | % pedidos | pecas | faturamento | % fat salao | ticket medio | % com bebida")
    R_faixas = []
    for a, b in faixas:
        os_ = [o for o in com_pecas if a <= o["_npecas"] <= b]
        if not os_:
            continue
        f = sum(o["total"] for o in os_)
        cb = sum(1 for o in os_ if o["_beb_val"] > 0)
        rot = f"{a}-{b}" if b < 999 else f"{a}+"
        print(f"    {rot:>6s} pecas: {len(os_):3d} | {pct(len(os_), len(salao)):5.1f}% | {sum(o['_npecas'] for o in os_):5.0f} | {brl(f):>12s} | {pct(f, fat_salao):5.1f}% | {brl(f / len(os_)):>10s} | {pct(cb, len(os_)):5.1f}%")
        R_faixas.append({"faixa": rot, "pedidos": len(os_), "pct_pedidos": round(pct(len(os_), len(salao)), 1), "pecas": sum(o["_npecas"] for o in os_), "faturamento": round(f, 2),
                         "pct_fat": round(pct(f, fat_salao), 1), "ticket": round(f / len(os_), 2), "pct_bebida": round(pct(cb, len(os_)), 1)})
    fx_t = [(0, 20), (20, 40), (40, 60), (60, 100), (100, 150), (150, 9999)]
    print("  distribuicao por ticket: pedidos | % pedidos | faturamento | % fat salao")
    R_ft = []
    for a, b in fx_t:
        os_ = [o for o in salao if a <= o["total"] < b]
        f = sum(o["total"] for o in os_)
        rot = f"{a}-{b}" if b < 9999 else f"{a}+"
        print(f"    R$ {rot:>8s}: {len(os_):3d} | {pct(len(os_), len(salao)):5.1f}% | {brl(f):>12s} | {pct(f, fat_salao):5.1f}%")
        R_ft.append({"faixa": rot, "pedidos": len(os_), "pct_pedidos": round(pct(len(os_), len(salao)), 1), "faturamento": round(f, 2), "pct_fat": round(pct(f, fat_salao), 1)})
    # concentracao
    ordenado = sorted(salao, key=lambda o: -o["total"])
    n10 = max(1, round(len(salao) * 0.10))
    n20 = max(1, round(len(salao) * 0.20))
    print(f"  concentracao: os {n10} maiores pedidos (10%) somam {brl(sum(o['total'] for o in ordenado[:n10]))} = {pct(sum(o['total'] for o in ordenado[:n10]), fat_salao):.1f}% do salao; os {n20} maiores (20%) = {pct(sum(o['total'] for o in ordenado[:n20]), fat_salao):.1f}%")
    print("  10 maiores pedidos de salao (id | hora | total | pecas [rolo/joy-nig/acarajapa/sashimi] | bebida R$ | pagamento):")
    R_top = []
    for o in ordenado[:10]:
        pg = "+".join(x[0] for x in parse_pagamento(o))
        print(f"    {o['id']} | {o['created_at'][11:16]} | {brl(o['total']):>10s} | {o['_npecas']:.0f} [{o['_pecas']['rolo_1_99']:.0f}/{o['_pecas']['joy_niguiri_2_99']:.0f}/{o['_pecas']['acarajapa']:.0f}/{o['_pecas']['sashimi']:.0f}] | {brl(o['_beb_val'])} | {pg}")
        R_top.append({"id": o["id"], "hora": o["created_at"][11:16], "total": o["total"], "pecas": o["_npecas"], "bebida": round(o["_beb_val"], 2), "pagamento": pg})
    # composicao dos pedidos
    so_rolo = sum(1 for o in com_pecas if o["_pecas"]["rolo_1_99"] > 0 and o["_npecas"] == o["_pecas"]["rolo_1_99"])
    com_299 = sum(1 for o in salao if o["_pecas"]["joy_niguiri_2_99"] > 0)
    com_acar = sum(1 for o in salao if o["_pecas"]["acarajapa"] > 0)
    com_outros = sum(1 for o in salao if o["_outros_val"] > 0)
    outros_val = sum(o["_outros_val"] for o in salao)
    print(f"  composicao: so rolo de 1,99 (sem joy/niguiri/acarajapa/sashimi): {so_rolo} pedidos ({pct(so_rolo, len(salao)):.1f}%) | com joy/niguiri 2,99: {com_299} ({pct(com_299, len(salao)):.1f}%) | com acarajapa: {com_acar} ({pct(com_acar, len(salao)):.1f}%) | com prato fora da promocao (temaki etc.): {com_outros} ({brl(outros_val)})")
    pequenos20 = [o for o in salao if o["total"] < 20]
    pequenos10p = [o for o in com_pecas if o["_npecas"] < 10]
    print(f"  pedidos abaixo de R$ 20,00: {len(pequenos20)} ({pct(len(pequenos20), len(salao)):.1f}%) somando {brl(sum(o['total'] for o in pequenos20))} | pedidos com menos de 10 pecas: {len(pequenos10p)} ({pct(len(pequenos10p), len(salao)):.1f}%) somando {brl(sum(o['total'] for o in pequenos10p))}")
    falta10 = sum(10 - o["_npecas"] for o in pequenos10p)
    print(f"    cenario 'minimo de 10 pecas': faltariam {falta10:.0f} pecas; a 1,99 = {brl(falta10 * 1.99)} de receita a mais (se ninguem desistir)")
    R["salao"] = {"pedidos": len(salao), "faturamento": round(fat_salao, 2), "pct_da_noite": round(pct(fat_salao, fat_total), 2),
                  "ticket_medio": round(statistics.mean(tk), 2), "ticket_mediana": round(statistics.median(tk), 2), "ticket_p25": round(perc(tk, .25), 2),
                  "ticket_p75": round(perc(tk, .75), 2), "ticket_p90": round(perc(tk, .9), 2), "ticket_min": min(tk), "ticket_max": max(tk),
                  "pecas_total": tot_pecas_salao, "pecas_por_tipo": dict(comp), "receita_por_tipo": {k: round(v, 2) for k, v in comp_val.items()},
                  "receita_pecas": round(sum(comp_val.values()), 2), "preco_medio_peca": round(sum(comp_val.values()) / tot_pecas_salao, 4),
                  "pct_pecas_2_99": round(pct(comp["joy_niguiri_2_99"], comp["joy_niguiri_2_99"] + comp["rolo_1_99"]), 2),
                  "pedidos_com_pecas": len(com_pecas), "pecas_media": round(statistics.mean(np_), 2), "pecas_mediana": statistics.median(np_),
                  "pecas_p25": perc(np_, .25), "pecas_p75": perc(np_, .75), "pecas_p90": round(perc(np_, .9), 1), "pecas_max": max(np_),
                  "pecas_media_todos": round(statistics.mean(np_all), 2), "pedidos_sem_pecas": len(salao) - len(com_pecas),
                  "faixas_pecas": R_faixas, "faixas_ticket": R_ft, "top10": R_top,
                  "top10pct_pedidos": n10, "top10pct_fat_pct": round(pct(sum(o["total"] for o in ordenado[:n10]), fat_salao), 2),
                  "top20pct_fat_pct": round(pct(sum(o["total"] for o in ordenado[:n20]), fat_salao), 2),
                  "so_rolo": so_rolo, "com_2_99": com_299, "com_acarajapa": com_acar, "com_outros_pratos": com_outros, "outros_pratos_valor": round(outros_val, 2),
                  "abaixo_20_pedidos": len(pequenos20), "abaixo_20_valor": round(sum(o["total"] for o in pequenos20), 2),
                  "menos_10_pecas_pedidos": len(pequenos10p), "menos_10_pecas_valor": round(sum(o["total"] for o in pequenos10p), 2),
                  "cenario_min10_pecas_faltantes": falta10, "cenario_min10_receita": round(falta10 * 1.99, 2)}

    # ------------------------------------------------------------------ 3. BEBIDAS
    print()
    print("=" * 100)
    print("3. BEBIDAS (categorias Bebidas + Cervejas) - SALAO")
    print("=" * 100)
    com_beb = [o for o in salao if o["_beb_val"] > 0]
    beb_val = sum(o["_beb_val"] for o in salao)
    beb_qtd = sum(o["_beb_qtd"] for o in salao)
    so_promo_sem_beb = [o for o in salao if o["_npecas"] > 0 and o["_beb_val"] == 0 and o["_outros_val"] == 0 and o["_sobremesa_val"] == 0]
    pecas_sem_beb = [o for o in salao if o["_npecas"] > 0 and o["_beb_val"] == 0]
    so_beb = [o for o in salao if o["_beb_val"] > 0 and o["_npecas"] == 0 and o["_outros_val"] == 0 and o["_sobremesa_val"] == 0]
    print(f"pedidos de salao com pelo menos 1 bebida: {len(com_beb)} de {len(salao)} = {pct(len(com_beb), len(salao)):.1f}%")
    print(f"receita de bebida: {brl(beb_val)} ({pct(beb_val, fat_salao):.1f}% do salao) | unidades: {beb_qtd:.0f}")
    print(f"receita de bebida por pedido de salao (todos): {brl(beb_val / len(salao))} | por pedido que levou bebida: {brl(beb_val / len(com_beb))} | unidades por pedido que levou: {beb_qtd / len(com_beb):.2f}")
    print(f"pedidos SO com pecas da promocao e NENHUMA bebida: {len(so_promo_sem_beb)} ({pct(len(so_promo_sem_beb), len(salao)):.1f}% do salao), somando {brl(sum(o['total'] for o in so_promo_sem_beb))} e {sum(o['_npecas'] for o in so_promo_sem_beb):.0f} pecas")
    print(f"pedidos com pecas e sem bebida (com ou sem outro prato): {len(pecas_sem_beb)} | pedidos so de bebida (sem comida): {len(so_beb)} somando {brl(sum(o['total'] for o in so_beb))}")
    # excluindo pedidos so de bebida (provavel 2a ida ao caixa)
    com_comida = [o for o in salao if o["_npecas"] > 0 or o["_outros_val"] > 0]
    cb2 = [o for o in com_comida if o["_beb_val"] > 0]
    print(f"entre os {len(com_comida)} pedidos com comida: {len(cb2)} levaram bebida junto = {pct(len(cb2), len(com_comida)):.1f}%")
    print(f"  se cada pedido 'so de bebida' fosse a 2a ida ao caixa de um cliente que ja tinha comprado pecas, o teto seria {pct(len(cb2) + len(so_beb), len(com_comida)):.1f}% dos pedidos com comida")
    mix = collections.defaultdict(lambda: [0.0, 0.0, None])
    for o in salao:
        for i in o["_itens"]:
            if eh_bebida(i):
                m = mix[i.get("title")]
                m[0] += q(i)
                m[1] += q(i) * pr(i)
                m[2] = i.get("category_name")
    print("  mix de bebidas (unidades | receita | preco):")
    for t, m in sorted(mix.items(), key=lambda kv: -kv[1][1]):
        print(f"    {t:40s} {m[0]:4.0f} | {brl(m[1]):>10s} | {brl(m[1] / m[0])} | {m[2]}")
    cerv = sum(m[1] for m in mix.values() if m[2] == "Cervejas")
    cerv_q = sum(m[0] for m in mix.values() if m[2] == "Cervejas")
    print(f"  cervejas: {cerv_q:.0f} un, {brl(cerv)} | sem alcool: {beb_qtd - cerv_q:.0f} un, {brl(beb_val - cerv)}")
    sobre = sum(o["_sobremesa_val"] for o in salao)
    n_sobre = sum(1 for o in salao if o["_sobremesa_val"] > 0)
    print(f"  sobremesa (picole/sorvete): {n_sobre} pedidos, {brl(sobre)}")
    # pecas por bebida
    print(f"  pecas avulsas vendidas por unidade de bebida: {tot_pecas_salao / beb_qtd:.0f} pecas para cada bebida")
    # cenarios
    tk_beb = beb_val / len(com_beb)
    cen = {}
    for alvo in (30, 40, 50):
        add = max(0.0, alvo / 100 * len(salao) - len(com_beb))
        rec = add * tk_beb
        cen[alvo] = {"pedidos_a_mais": round(add, 1), "receita": round(rec, 2), "margem_65pct": round(rec * (1 - CUSTO_REFRI_PCT), 2)}
        print(f"  cenario: {alvo}% dos pedidos de salao com bebida -> +{add:.0f} pedidos x {brl(tk_beb)} = +{brl(rec)} de receita por quarta; margem bruta (custo 35%, regra do refrigerante) +{brl(rec * (1 - CUSTO_REFRI_PCT))}")
    add10 = 0.10 * len(salao) * tk_beb
    print(f"  cada 10 pontos percentuais a mais de pedidos com bebida = +{brl(add10)} de receita (+{brl(add10 * (1 - CUSTO_REFRI_PCT))} de margem bruta)")
    por_h = collections.defaultdict(lambda: [0, 0])
    for o in salao:
        por_h[o["created_at"][11:13]][0] += 1
        if o["_beb_val"] > 0:
            por_h[o["created_at"][11:13]][1] += 1
    print("  % de pedidos de salao com bebida por hora: " + " | ".join(f"{h}h {v[1]}/{v[0]} = {pct(v[1], v[0]):.1f}%" for h, v in sorted(por_h.items())))
    melhor_h = max((h for h in por_h if por_h[h][0] >= 20), key=lambda h: por_h[h][1] / por_h[h][0])
    taxa_m = por_h[melhor_h][1] / por_h[melhor_h][0]
    add_m = max(0.0, taxa_m * len(salao) - len(com_beb))
    print(f"  cenario: a noite inteira com a taxa da melhor hora ({melhor_h}h = {100 * taxa_m:.1f}%) -> +{add_m:.1f} pedidos com bebida x {brl(tk_beb)} = +{brl(add_m * tk_beb)} de receita (+{brl(add_m * tk_beb * (1 - CUSTO_REFRI_PCT))} de margem a 65%)")
    fora_m = [o for o in salao if o["created_at"][11:13] != melhor_h]
    print(f"    fora das {melhor_h}h: {sum(1 for o in fora_m if o['_beb_val'] > 0)} de {len(fora_m)} pedidos com bebida = {pct(sum(1 for o in fora_m if o['_beb_val'] > 0), len(fora_m)):.1f}%")
    lata = 6.00
    print(f"  cenario simples: 1 lata de R$ 6,00 em cada um dos {len(so_promo_sem_beb)} pedidos so-promocao-sem-bebida = +{brl(len(so_promo_sem_beb) * lata)}; em metade deles = +{brl(len(so_promo_sem_beb) * lata / 2)} (margem 65%: +{brl(len(so_promo_sem_beb) * lata / 2 * 0.65)})")
    R_beb_extra = {"por_hora": {h: {"pedidos": v[0], "com_bebida": v[1], "pct": round(pct(v[1], v[0]), 1)} for h, v in sorted(por_h.items())},
                   "melhor_hora": melhor_h, "melhor_hora_pct": round(100 * taxa_m, 1), "cenario_melhor_hora_pedidos": round(add_m, 1),
                   "cenario_melhor_hora_receita": round(add_m * tk_beb, 2), "cenario_melhor_hora_margem": round(add_m * tk_beb * (1 - CUSTO_REFRI_PCT), 2),
                   "pct_fora_da_melhor_hora": round(pct(sum(1 for o in fora_m if o["_beb_val"] > 0), len(fora_m)), 1)}
    R["bebidas"] = {"pedidos_com_bebida": len(com_beb), "pct_pedidos_com_bebida": round(pct(len(com_beb), len(salao)), 2), "receita": round(beb_val, 2),
                    "pct_receita_salao": round(pct(beb_val, fat_salao), 2), "unidades": beb_qtd, "receita_por_pedido_salao": round(beb_val / len(salao), 2),
                    "receita_por_pedido_com_bebida": round(tk_beb, 2), "so_promo_sem_bebida": len(so_promo_sem_beb),
                    "so_promo_sem_bebida_pct": round(pct(len(so_promo_sem_beb), len(salao)), 2), "so_promo_sem_bebida_valor": round(sum(o["total"] for o in so_promo_sem_beb), 2),
                    "pecas_sem_bebida": len(pecas_sem_beb), "so_bebida": len(so_beb), "so_bebida_valor": round(sum(o["total"] for o in so_beb), 2),
                    "pedidos_com_comida": len(com_comida), "pct_com_comida_e_bebida": round(pct(len(cb2), len(com_comida)), 2),
                    "teto_pct_se_so_bebida_for_2a_ida": round(pct(len(cb2) + len(so_beb), len(com_comida)), 2),
                    "cervejas_un": cerv_q, "cervejas_valor": round(cerv, 2), "sem_alcool_un": beb_qtd - cerv_q, "sem_alcool_valor": round(beb_val - cerv, 2),
                    "sobremesa_pedidos": n_sobre, "sobremesa_valor": round(sobre, 2), "pecas_por_bebida": round(tot_pecas_salao / beb_qtd, 1),
                    "cenarios": cen, "cada_10pp_receita": round(add10, 2), "cada_10pp_margem": round(add10 * (1 - CUSTO_REFRI_PCT), 2),
                    "lata_em_metade_dos_sem_bebida_receita": round(len(so_promo_sem_beb) * lata / 2, 2),
                    "lata_em_metade_dos_sem_bebida_margem": round(len(so_promo_sem_beb) * lata / 2 * 0.65, 2),
                    "mix": {t: {"un": m[0], "receita": round(m[1], 2)} for t, m in mix.items()}}
    R["bebidas"].update(R_beb_extra)

    # ------------------------------------------------------------------ 4. FORMAS DE PAGAMENTO
    print()
    print("=" * 100)
    print("4. FORMAS DE PAGAMENTO (em valor)")
    print("=" * 100)
    pg_all = collections.defaultdict(lambda: [0.0, 0])
    pg_sal = collections.defaultdict(lambda: [0.0, 0])
    pg_det = collections.defaultdict(lambda: [0.0, 0])
    pg_canal = collections.defaultdict(lambda: collections.defaultdict(float))
    divergentes = []
    troco_nao_dinheiro = []
    divididos = 0
    for o in ok:
        partes = parse_pagamento(o)
        soma = sum(x[2] for x in partes)
        if abs(soma - o["total"]) > 0.02:
            divergentes.append((o["id"], o["_canal"], o["total"], round(soma, 2)))
        if len(partes) > 1:
            divididos += 1
        for g, nome, liq, troco in partes:
            pg_all[g][0] += liq
            pg_all[g][1] += 1
            pg_det[nome][0] += liq
            pg_det[nome][1] += 1
            pg_canal[o["_canal"]][g] += liq
            if o["_canal"] == "salao":
                pg_sal[g][0] += liq
                pg_sal[g][1] += 1
            if troco > 0.005:
                troco_nao_dinheiro.append((o["id"], o["_canal"], o["created_at"][11:16], nome, round(liq + troco, 2), troco, o["total"]))
    print("TODOS OS CANAIS: forma | valor | % | lancamentos")
    for g, (v, n) in sorted(pg_all.items(), key=lambda kv: -kv[1][0]):
        print(f"  {g:22s} {brl(v):>14s} | {pct(v, fat_total):5.1f}% | {n}")
    print(f"  soma {brl(sum(v for v, n in pg_all.values()))} (faturamento {brl(fat_total)})")
    print("SO SALAO: forma | valor | % | lancamentos")
    for g, (v, n) in sorted(pg_sal.items(), key=lambda kv: -kv[1][0]):
        print(f"  {g:22s} {brl(v):>14s} | {pct(v, fat_salao):5.1f}% | {n}")
    cart_sal = pg_sal["Cartão crédito"][0] + pg_sal["Cartão débito"][0]
    print(f"  salao: cartao (credito+debito) {brl(cart_sal)} = {pct(cart_sal, fat_salao):.1f}% | Pix {pct(pg_sal['Pix'][0], fat_salao):.1f}% | dinheiro {pct(pg_sal['Dinheiro'][0], fat_salao):.1f}%")
    print("POR CANAL:")
    for c, dd in pg_canal.items():
        print(f"  {c}: " + " | ".join(f"{g} {brl(v)}" for g, v in sorted(dd.items(), key=lambda kv: -kv[1])))
    print("DETALHE (texto original da forma):")
    for nome, (v, n) in sorted(pg_det.items(), key=lambda kv: -kv[1][0]):
        print(f"  {nome:36s} {brl(v):>14s} | {n}")
    print(f"pedidos com pagamento dividido em 2 formas: {divididos} | pedidos em que as formas nao fecham com o total: {len(divergentes)} {divergentes[:5]}")
    print(f"'troco' em forma que nao e dinheiro: {troco_nao_dinheiro}")
    base_regra = fat_salao + por_canal["app"]["faturamento"]
    cart_vale_salao_app = sum(pg_canal[c][g] for c in ("salao", "app") for g in ("Cartão crédito", "Cartão débito", "Vale-refeição"))
    print(f"taxa de cartao pela regra comum (2% sobre salao+app = {brl(base_regra)}): {brl(base_regra * TAXA_CARTAO)}")
    print(f"  so sobre o que passou em cartao/vale no salao+app ({brl(cart_vale_salao_app)}): {brl(cart_vale_salao_app * TAXA_CARTAO)} -> diferenca {brl((base_regra - cart_vale_salao_app) * TAXA_CARTAO)} (Pix e dinheiro normalmente nao pagam essa taxa)")
    R["pagamentos"] = {"todos": {g: {"valor": round(v, 2), "pct": round(pct(v, fat_total), 2), "n": n} for g, (v, n) in pg_all.items()},
                       "salao": {g: {"valor": round(v, 2), "pct": round(pct(v, fat_salao), 2), "n": n} for g, (v, n) in pg_sal.items()},
                       "salao_cartao_valor": round(cart_sal, 2), "salao_cartao_pct": round(pct(cart_sal, fat_salao), 2),
                       "divididos": divididos, "divergentes": len(divergentes), "troco_nao_dinheiro": troco_nao_dinheiro,
                       "taxa_cartao_regra": round(base_regra * TAXA_CARTAO, 2), "base_cartao_vale_salao_app": round(cart_vale_salao_app, 2),
                       "taxa_cartao_so_cartao": round(cart_vale_salao_app * TAXA_CARTAO, 2),
                       "taxa_cartao_diferenca": round((base_regra - cart_vale_salao_app) * TAXA_CARTAO, 2)}

    # ------------------------------------------------------------------ 5. DESCONTOS
    print()
    print("=" * 100)
    print("5. DESCONTOS")
    print("=" * 100)
    com_desc = [o for o in ok if (o.get("discount") or 0) > 0.005]
    soma_desc = sum(o["discount"] for o in com_desc)
    print(f"soma do campo 'discount': {brl(soma_desc)} em {len(com_desc)} pedidos (de {len(ok)})")
    dc = collections.Counter(o["_canal"] for o in com_desc)
    print(f"  por canal: {dict(dc)} | pedidos de salao com desconto: {dc.get('salao', 0)}")
    orig = collections.defaultdict(lambda: [0.0, 0])
    for o in com_desc:
        for x in o.get("discount_origins") or []:
            k = (x.get("kind"), x.get("label"))
            orig[k][0] += float(x.get("value") or 0)
            orig[k][1] += 1
    for (kind, label), (v, n) in sorted(orig.items(), key=lambda kv: -kv[1][0]):
        print(f"  origem '{kind}' - {label}: {brl(v)} em {n} pedidos")
    loja = sum(v for (k, l), (v, n) in orig.items() if k == "loja")
    plat = sum(v for (k, l), (v, n) in orig.items() if k == "plataforma")
    sem_orig = soma_desc - loja - plat
    ifood = [o for o in ok if o["_canal"] == "ifood"]
    if_sub = sum(o["subtotal"] for o in ifood)
    if_tot = sum(o["total"] for o in ifood)
    if_ent = sum(o["delivery_fee"] for o in ifood)
    if_srv = sum(o["service_fee"] for o in ifood)
    print(f"  bancado pela loja: {brl(loja)} | bancado pelo iFood (reembolsado no acerto, segundo o rotulo): {brl(plat)} | sem origem: {brl(sem_orig)}")
    print(f"  iFood: {len(ifood)} pedidos, {sum(1 for o in ifood if o['discount'] > 0)} com desconto | subtotal (cardapio) {brl(if_sub)} | entrega {brl(if_ent)} | taxa de servico {brl(if_srv)} | total {brl(if_tot)}")
    print(f"  desconto da loja = {pct(loja, if_sub):.1f}% do subtotal do iFood; desconto total = {pct(soma_desc, if_sub):.1f}% do subtotal")
    liq_if = if_tot - COMISSAO_IFOOD * if_tot
    print(f"  iFood pela regra comum: total {brl(if_tot)} - comissao 25% {brl(COMISSAO_IFOOD * if_tot)} = {brl(liq_if)} ({pct(liq_if, if_sub):.1f}% do preco de cardapio); com o reembolso da campanha (+{brl(plat)}) = {brl(liq_if + plat)}")
    print("  maiores descontos (id | canal | hora | subtotal | desconto | % do subtotal | loja | iFood | total cobrado | itens):")
    R_desc = []
    for o in sorted(com_desc, key=lambda x: -x["discount"])[:8]:
        lj = sum(float(x.get("value") or 0) for x in (o.get("discount_origins") or []) if x.get("kind") == "loja")
        pf = sum(float(x.get("value") or 0) for x in (o.get("discount_origins") or []) if x.get("kind") == "plataforma")
        itens = ", ".join(f"{q(i):.0f}x {i.get('title')}" for i in o["_itens"])
        print(f"    {o['id']} | {o['_canal']} | {o['created_at'][11:16]} | {brl(o['subtotal'])} | {brl(o['discount'])} | {pct(o['discount'], o['subtotal']):.0f}% | {brl(lj)} | {brl(pf)} | {brl(o['total'])} | {itens}")
        R_desc.append({"id": o["id"], "canal": o["_canal"], "hora": o["created_at"][11:16], "subtotal": round(o["subtotal"], 2), "desconto": o["discount"],
                       "pct": round(pct(o["discount"], o["subtotal"]), 1), "loja": round(lj, 2), "ifood": round(pf, 2), "total": o["total"], "itens": itens})
    R["descontos"] = {"soma": round(soma_desc, 2), "pedidos": len(com_desc), "por_canal": dict(dc), "loja": round(loja, 2), "plataforma": round(plat, 2),
                      "ifood_pedidos": len(ifood), "ifood_subtotal": round(if_sub, 2), "ifood_total": round(if_tot, 2), "ifood_entrega": round(if_ent, 2),
                      "ifood_servico": round(if_srv, 2), "pct_loja_sobre_subtotal": round(pct(loja, if_sub), 2), "pct_total_sobre_subtotal": round(pct(soma_desc, if_sub), 2),
                      "ifood_liquido_regra": round(liq_if, 2), "ifood_liquido_pct_cardapio": round(pct(liq_if, if_sub), 2), "maiores": R_desc}

    # ------------------------------------------------------------------ 6. QUEM LANCOU
    print()
    print("=" * 100)
    print("6. QUEM LANCOU OS ITENS")
    print("=" * 100)
    quem = collections.defaultdict(lambda: {"linhas": 0, "pecas": 0.0, "valor": 0.0, "pedidos": set()})
    for o in ok:
        for i in o["_itens"]:
            if o["_canal"] in ("salao", "pdv_delivery"):
                nome = str(i.get("added_by_user_name"))
            elif o["_canal"] == "app":
                nome = "(cliente no app)"
            else:
                nome = "(integracao iFood)"
            k = (o["_canal"], nome)
            quem[k]["linhas"] += 1
            quem[k]["valor"] += q(i) * pr(i)
            quem[k]["pedidos"].add(o["id"])
            if tipo_peca(i):
                quem[k]["pecas"] += q(i)
    print("canal | usuario que lancou (added_by_user_name) | linhas | pecas avulsas | valor dos itens | pedidos")
    R["quem"] = {"itens": [], "pedidos": []}
    for (c, nome), v in sorted(quem.items(), key=lambda kv: -kv[1]["valor"]):
        print(f"  {c:13s} | {nome:20s} | {v['linhas']:4d} | {v['pecas']:6.0f} | {brl(v['valor']):>14s} | {len(v['pedidos'])}")
        R["quem"]["itens"].append({"canal": c, "usuario": nome, "linhas": v["linhas"], "pecas": v["pecas"], "valor": round(v["valor"], 2), "pedidos": len(v["pedidos"])})
    cb = collections.defaultdict(lambda: [0, 0.0])
    for o in ok:
        cb[(o["_canal"], str(o.get("created_by_name")))][0] += 1
        cb[(o["_canal"], str(o.get("created_by_name")))][1] += o["total"]
    print("canal | quem criou o pedido (created_by_name) | pedidos | valor")
    for (c, nome), (n, v) in sorted(cb.items(), key=lambda kv: -kv[1][1]):
        print(f"  {c:13s} | {nome:20s} | {n:4d} | {brl(v)}")
        R["quem"]["pedidos"].append({"canal": c, "criado_por": nome, "pedidos": n, "valor": round(v, 2)})
    logins_salao = {nome for (c, nome) in quem if c == "salao"}
    print(f"  logins diferentes lancando no salao: {len(logins_salao)} {sorted(logins_salao)} | pedidos com mesa preenchida: {sum(1 for o in ok if o.get('table_number'))} | com comanda: {sum(1 for o in ok if o.get('comanda_number'))} | com atendente (employee_name): {sum(1 for o in ok if o.get('employee_name'))}")
    # itens lancados pelo login da loja em pedidos de app/ifood
    loja_em_ext = [(o["id"], o["_canal"], o["created_at"][11:16], i.get("title")) for o in ok if o["_canal"] in ("app", "ifood") for i in o["_itens"]
                   if str(i.get("added_by_user_name") or "").strip().lower() in {x.lower() for x in logins_salao}]
    print(f"  linhas em pedidos de app/iFood com o mesmo nome do login da loja: {len(loja_em_ext)} em {len({x[0] for x in loja_em_ext})} pedidos")
    R["quem"]["logins_salao"] = sorted(logins_salao)
    R["quem"]["mesa_preenchida"] = sum(1 for o in ok if o.get("table_number"))
    R["quem"]["comanda_preenchida"] = sum(1 for o in ok if o.get("comanda_number"))
    R["quem"]["linhas_login_loja_em_app_ifood"] = len(loja_em_ext)

    # ------------------------------------------------------------------ 7. REGRA DA PROMOCAO
    print()
    print("=" * 100)
    print("7. REGRA DA PROMOCAO (so salao)")
    print("=" * 100)
    fora = collections.defaultdict(lambda: [0.0, 0.0, set()])
    fora_199_299 = [0.0, 0.0]
    fora_promo = [0.0, 0.0]
    for o in ok:
        if o["_canal"] == "salao":
            continue
        for i in o["_itens"]:
            tp = tipo_peca(i)
            p = round(pr(i), 2)
            eh_promo = i.get("category_name") == CAT_PROMO or tp in ("rolo_1_99", "joy_niguiri_2_99", "acarajapa", "sashimi", "generico_outro_preco")
            if eh_promo or tp == "unidade_especifica" or p in (1.99, 2.99):
                k = (o["_canal"], i.get("title"), p, "produto da promocao" if eh_promo else "item de 1 unidade do cardapio do canal")
                fora[k][0] += q(i)
                fora[k][1] += q(i) * p
                fora[k][2].add(o["id"])
                if p in (1.99, 2.99):
                    fora_199_299[0] += q(i)
                    fora_199_299[1] += q(i) * p
                if eh_promo:
                    fora_promo[0] += q(i)
                    fora_promo[1] += q(i) * p
    if not fora:
        print("nenhuma peca avulsa/promocional fora do salao")
    for (c, t, p, tipo), (qt, v, ids) in sorted(fora.items()):
        print(f"  {c:13s} | {t} a {brl(p)} | {qt:.0f} un | {brl(v)} | {tipo} | pedidos {sorted(ids)}")
    print(f"  pecas a 1,99 ou 2,99 fora do salao: {fora_199_299[0]:.0f} un, {brl(fora_199_299[1])} | produtos da categoria 'Promocao do Dia' fora do salao: {fora_promo[0]:.0f} un, {brl(fora_promo[1])}")
    promo_199_299_ext = sum(q(i) for o in ok if o["_canal"] != "salao" for i in o["_itens"] if tipo_peca(i) in ("rolo_1_99", "joy_niguiri_2_99"))
    print(f"  pecas dos botoes da promocao a 1,99/2,99 (QUARTA MALUCA / PECA SUSHI / Sunomono) em App, iFood ou delivery: {promo_199_299_ext:.0f}")
    R["regra_promo"] = {"itens_fora": [{"canal": c, "titulo": t, "preco": p, "tipo": tipo, "un": qt, "valor": round(v, 2), "pedidos": sorted(ids)} for (c, t, p, tipo), (qt, v, ids) in fora.items()],
                        "pecas_1_99_2_99_fora": fora_199_299[0], "valor_1_99_2_99_fora": round(fora_199_299[1], 2),
                        "promo_fora_un": fora_promo[0], "promo_fora_valor": round(fora_promo[1], 2), "botoes_promo_1_99_2_99_fora": promo_199_299_ext}

    # ------------------------------------------------------------------ 8. QUALIDADE DO LANCAMENTO
    print()
    print("=" * 100)
    print("8. QUALIDADE DO LANCAMENTO")
    print("=" * 100)
    gen = collections.defaultdict(lambda: [0.0, 0.0, set()])
    for o in ok:
        for i in o["_itens"]:
            if generico(i):
                k = (o["_canal"], (i.get("title") or "").strip(), round(pr(i), 2))
                gen[k][0] += q(i)
                gen[k][1] += q(i) * pr(i)
                gen[k][2].add(o["id"])
    gen_val = sum(v[1] for v in gen.values())
    gen_qtd = sum(v[0] for v in gen.values())
    for (c, t, p), (qt, v, ids) in sorted(gen.items(), key=lambda kv: -kv[1][1]):
        print(f"  generico: {c} | {t} a {brl(p)} | {qt:.0f} pecas | {brl(v)} | {len(ids)} pedidos")
    print(f"receita em produtos genericos (nao da para saber a peca): {brl(gen_val)} em {gen_qtd:.0f} pecas = {pct(gen_val, fat_salao):.1f}% do salao e {pct(gen_val, fat_total):.1f}% do faturamento da noite")
    unit = collections.defaultdict(lambda: [0.0, 0.0])
    for o in ok:
        for i in o["_itens"]:
            if RE_UNIT.search(i.get("title") or ""):
                unit[(o["_canal"], i.get("title"))][0] += q(i)
                unit[(o["_canal"], i.get("title"))][1] += q(i) * pr(i)
    unit_salao = sum(v[0] for (c, t), v in unit.items() if c == "salao")
    unit_tot = sum(v[0] for v in unit.values())
    print(f"pecas lancadas por produto especifico de 1 peca ('(1 peca)' ou '(unidade)'): salao {unit_salao:.0f} | todos os canais {unit_tot:.0f} {[(c, t, v[0], round(v[1], 2)) for (c, t), v in unit.items()]}")
    ident = comp["acarajapa"] + comp["sashimi"]
    print(f"pecas do salao em que se sabe o que foi vendido (Acarajapa, Sashimi, unidade especifica): {ident + unit_salao:.0f} de {tot_pecas_salao:.0f} = {pct(ident + unit_salao, tot_pecas_salao):.1f}%")
    sun = [(o["id"], o["created_at"][11:16], q(i)) for o in salao for i in o["_itens"] if (i.get("title") or "").strip().upper() == "SUNOMONO"]
    print(f"botao 'Sunomono' usado para lancar joy/niguiri: {sum(x[2] for x in sun):.0f} pecas em {len({x[0] for x in sun})} pedidos, {brl(sum(x[2] for x in sun) * 2.99)} | horarios: {sorted({x[1] for x in sun})}")
    n_rolo = comp["rolo_1_99"]
    n_jn = comp["joy_niguiri_2_99"]
    cmv = {k: n_rolo * CUSTO_ROLO[k] + n_jn * CUSTO_JOYNIG[k] for k in CUSTO_ROLO}
    print(f"incerteza de custo por nao saber a peca (regras 2 e 3 do BRIEF): rolo {n_rolo:.0f} pecas x (0,45 / 0,60 / 0,72) + joy/niguiri {n_jn:.0f} pecas x (0,97 / 1,41 / 1,85)")
    print(f"  custo otimista {brl(cmv['otimista'])} | central {brl(cmv['central'])} | pessimista {brl(cmv['pessimista'])} -> faixa de {brl(cmv['pessimista'] - cmv['otimista'])} ({pct(cmv['pessimista'] - cmv['otimista'], gen_val):.1f}% da receita generica)")
    linhas_salao = sum(len(o["_itens"]) for o in salao)
    maior_linha = max(((q(i), o["id"], i.get("title")) for o in salao for i in o["_itens"]), default=(0, None, None))
    print(f"linhas lancadas no salao: {linhas_salao} ({linhas_salao / len(salao):.2f} por pedido) | maior linha unica: {maior_linha[0]:.0f}x {maior_linha[2]} (pedido {maior_linha[1]})")
    R["qualidade"] = {"generico_valor": round(gen_val, 2), "generico_pecas": gen_qtd, "generico_pct_salao": round(pct(gen_val, fat_salao), 2), "generico_pct_noite": round(pct(gen_val, fat_total), 2),
                      "genericos": [{"canal": c, "titulo": t, "preco": p, "pecas": qt, "valor": round(v, 2), "pedidos": len(ids)} for (c, t, p), (qt, v, ids) in gen.items()],
                      "unidade_especifica_salao": unit_salao, "unidade_especifica_todos": unit_tot,
                      "pecas_identificadas_salao": ident + unit_salao, "pct_pecas_identificadas": round(pct(ident + unit_salao, tot_pecas_salao), 2),
                      "sunomono_pecas": sum(x[2] for x in sun), "sunomono_pedidos": len({x[0] for x in sun}), "sunomono_valor": round(sum(x[2] for x in sun) * 2.99, 2),
                      "custo_otimista": round(cmv["otimista"], 2), "custo_central": round(cmv["central"], 2), "custo_pessimista": round(cmv["pessimista"], 2),
                      "faixa_incerteza_custo": round(cmv["pessimista"] - cmv["otimista"], 2), "linhas_salao": linhas_salao, "maior_linha": maior_linha[0]}

    # ------------------------------------------------------------------ 9. ANOMALIAS
    print()
    print("=" * 100)
    print("9. ANOMALIAS")
    print("=" * 100)
    A = {}
    zer = [(o["id"], o["_canal"]) for o in ok if (o["total"] or 0) <= 0.005]
    sem_itens = [(o["id"], o["_canal"]) for o in ok if not o["_itens"]]
    preco0 = [(o["id"], o["_canal"], i.get("title")) for o in ok for i in o["_itens"] if pr(i) <= 0.005]
    frac = [(o["id"], o["_canal"], i.get("title"), q(i)) for o in ok for i in o["_itens"] if abs(q(i) - round(q(i))) > 1e-9 or q(i) <= 0]
    print(f"pedidos com total zerado: {len(zer)} {zer} | pedidos sem itens: {len(sem_itens)} | itens com preco zero: {len(preco0)} {preco0[:5]} | quantidade fracionada ou <= 0: {len(frac)} {frac[:5]}")
    A.update({"total_zerado": len(zer), "sem_itens": len(sem_itens), "preco_zero": len(preco0), "qtd_fracionada": len(frac), "cancelados": len(canc)})
    print(f"cancelados no arquivo: {len(canc)}")
    # ---- preco padrao
    def grupo_c(c):
        return "pdv/app" if c in ("salao", "pdv_delivery", "app") else c

    TABELA_PROMO = {"QUARTA MALUCA": {1.99}, "PEÇA SUSHI": {1.99, 2.99}, "SUNOMONO": {2.99}, "ACARAJAPA": {2.99}, "SASHIMI": {4.99}}

    def chave_preco(o, i):
        return (grupo_c(o["_canal"]), (i.get("title") or "").strip())

    ref_ok = []
    for r in refs:
        try:
            dr = [o for o in carrega(r) if not o["_cancelado"]]
        except Exception as e:
            print(f"  (referencia {r} nao pode ser lida: {e})")
            continue
        ref_ok.append((r.split("/")[-1], dr))
    ref_ok.sort(key=lambda x: x[0], reverse=True)  # mais recente primeiro
    # (a) botoes da promocao fora da tabela do BRIEF
    fora_tab = [(o["id"], o["_canal"], i.get("title"), pr(i), q(i)) for o in ok for i in o["_itens"]
                if (i.get("title") or "").strip().upper() in TABELA_PROMO and round(pr(i), 2) not in TABELA_PROMO[(i.get("title") or "").strip().upper()]]
    print(f"(a) pecas da promocao com preco fora da tabela (QUARTA MALUCA 1,99 | PECA SUSHI 1,99 ou 2,99 | Sunomono 2,99 | Acarajapa 2,99 | Sashimi 4,99): {len(fora_tab)} {fora_tab[:5]}")
    # (b) mesmo produto com mais de um preco na mesma noite e canal
    var = collections.defaultdict(collections.Counter)
    for o in ok:
        for i in o["_itens"]:
            var[(o["_canal"], (i.get("title") or "").strip())][round(pr(i), 2)] += q(i)
    var2 = {k: dict(v) for k, v in var.items() if len(v) > 1 and k[1].upper() not in TABELA_PROMO}
    print(f"(b) produtos com mais de um preco na mesma noite e no mesmo canal (fora os botoes da promocao): {len(var2)} {var2}")
    # (c) preco da noite x preco mais frequente do mesmo produto na quarta de referencia mais recente em que ele aparece
    ref_preco = {}
    for nome_ref, dr in ref_ok:
        cont = collections.defaultdict(collections.Counter)
        for o in dr:
            for i in o["_itens"]:
                cont[chave_preco(o, i)][round(pr(i), 2)] += q(i)
        for k, c in cont.items():
            ref_preco.setdefault(k, (c.most_common(1)[0][0], nome_ref))
    dif = []
    sem_ref = collections.Counter()
    for o in ok:
        for i in o["_itens"]:
            k = chave_preco(o, i)
            if k[1].upper() in TABELA_PROMO:
                continue
            if k not in ref_preco:
                sem_ref[k] += q(i)
                continue
            padrao, nome_ref = ref_preco[k]
            p = round(pr(i), 2)
            if abs(p - padrao) > 0.005:
                dif.append((o["id"], o["_canal"], o["created_at"][11:16], k[1], p, padrao, round(p / padrao, 3) if padrao else None, q(i), nome_ref))
    print(f"(c) itens com preco diferente do padrao (padrao = preco mais frequente do mesmo produto/canal na quarta anterior mais recente em que foi vendido; {len(ref_ok)} quartas de referencia): {len(dif)} linhas em {len({x[0] for x in dif})} pedidos")
    for x in dif:
        print(f"    pedido {x[0]} | {x[1]} | {x[2]} | {x[3]} | cobrado {brl(x[4])} x padrao {brl(x[5])} (razao {x[6]}) | qtd {x[7]:.0f} | ref {x[8]}")
    dif_val = sum((x[4] - x[5]) * x[7] for x in dif)
    dif_ped = collections.defaultdict(float)
    for x in dif:
        dif_ped[x[0]] += (x[4] - x[5]) * x[7]
    print("    diferenca por pedido (cobrado - padrao): " + " | ".join(f"{k}: {brl(v)}" for k, v in dif_ped.items()))
    A["preco_fora_padrao_por_pedido"] = {str(k): round(v, 2) for k, v in dif_ped.items()}
    print(f"    diferenca somada (cobrado - padrao): {brl(dif_val)} | linhas no salao: {sum(1 for x in dif if x[1] == 'salao')} | produtos sem referencia nas quartas anteriores: {len(sem_ref)} {dict(sem_ref)}")
    # pedidos com TODOS os itens ~10% acima do preco mais frequente
    moda_geral = collections.defaultdict(collections.Counter)
    for _, dr in [("noite", ok)] + ref_ok:
        for o in dr:
            for i in o["_itens"]:
                moda_geral[chave_preco(o, i)][round(pr(i), 2)] += q(i)
    print("    pedidos em que TODOS os itens estao entre 9,5% e 10,5% acima do preco mais frequente (todas as quartas):")
    A_10 = {}
    for nome_ref, dr in [(arq.split("/")[-1], ok)] + ref_ok:
        achou = []
        for o in dr:
            if not o["_itens"] or o["_canal"] not in ("app", "salao", "pdv_delivery"):
                continue
            rz = [pr(i) / moda_geral[chave_preco(o, i)].most_common(1)[0][0] for i in o["_itens"] if moda_geral[chave_preco(o, i)].most_common(1)[0][0]]
            if rz and all(1.095 <= r <= 1.105 for r in rz):
                achou.append((o["id"], o["_canal"], o["created_at"][11:16], round(o["subtotal"], 2), "+".join(x[0] for x in parse_pagamento(o)), len(rz)))
        print(f"      {nome_ref}: {len(achou)} {achou}")
        A_10[nome_ref] = achou
    A["preco_promo_fora_tabela"] = len(fora_tab)
    A["preco_varios_na_noite"] = {f"{k[0]}|{k[1]}": v for k, v in var2.items()}
    A["preco_fora_padrao_linhas"] = len(dif)
    A["preco_fora_padrao_pedidos"] = sorted({x[0] for x in dif})
    A["preco_fora_padrao_diferenca"] = round(dif_val, 2)
    A["preco_fora_padrao_salao"] = sum(1 for x in dif if x[1] == "salao")
    A["preco_fora_padrao_lista"] = [list(x) for x in dif]
    A["pedidos_10pct_acima"] = A_10
    # duplicados
    def assin(o):
        return (o["_canal"], round(o["total"], 2), tuple(sorted(((i.get("title") or ""), round(pr(i), 2), q(i)) for i in o["_itens"])))

    ordenados = sorted(ok, key=lambda o: o["_dt"])
    dups = []
    for a_i, a in enumerate(ordenados):
        for b in ordenados[a_i + 1:]:
            if (b["_dt"] - a["_dt"]).total_seconds() > 5 * 60:
                break
            if assin(a) == assin(b):
                dups.append((a["id"], b["id"], a["_canal"], a["created_at"][11:16], b["created_at"][11:16], a["total"],
                             "+".join(x[0] for x in parse_pagamento(a)), "+".join(x[0] for x in parse_pagamento(b)),
                             ", ".join(f"{q(i):.0f}x {i.get('title')}" for i in a["_itens"])))
    print(f"possiveis pedidos duplicados (mesmo canal, mesmos itens e mesmo total em ate 5 minutos): {len(dups)} pares")
    for x in dups:
        print(f"    {x[0]} ({x[3]}, {x[6]}) e {x[1]} ({x[4]}, {x[7]}) | {x[2]} | {brl(x[5])} | {x[8]}")
    dup_mesma_forma = [x for x in dups if x[6] == x[7]]
    print(f"    destes, com a mesma forma de pagamento: {len(dup_mesma_forma)} pares somando {brl(sum(x[5] for x in dup_mesma_forma))} (valor do 2o pedido de cada par)")
    dup_2min = [x for x in dups if x[3] == x[4] or (datetime.strptime(x[4], '%H:%M') - datetime.strptime(x[3], '%H:%M')).total_seconds() <= 120]
    print(f"    em ate 2 minutos: {len(dup_2min)} pares somando {brl(sum(x[5] for x in dup_2min))}")
    A["duplicados_pares_5min"] = len(dups)
    A["duplicados_pares_5min_valor"] = round(sum(x[5] for x in dups), 2)
    A["duplicados_mesma_forma_pares"] = len(dup_mesma_forma)
    A["duplicados_mesma_forma_valor"] = round(sum(x[5] for x in dup_mesma_forma), 2)
    A["duplicados_2min_pares"] = len(dup_2min)
    A["duplicados_2min_valor"] = round(sum(x[5] for x in dup_2min), 2)
    A["duplicados_lista"] = [list(x) for x in dups]
    # horario
    turno_ini = min(o["_dt"] for o in ok).replace(hour=16, minute=0)
    antes18 = [(o["id"], o["_canal"], o["created_at"][11:16]) for o in ok if o["_dt"].hour < 18 and o["_dt"].date() == turno_ini.date()]
    depois00 = [(o["id"], o["_canal"], o["created_at"][11:16]) for o in ok if o["_dt"].date() > turno_ini.date()]
    fora_turno = [(o["id"], o["created_at"]) for o in ok if not (turno_ini <= o["_dt"] < turno_ini + timedelta(hours=16))]
    depois23 = [o for o in ok if o["_dt"].hour == 23 and o["_dt"].date() == turno_ini.date()]
    gap_gr = []
    for o in ok:
        for i in o["_itens"]:
            la = i.get("launched_at")
            if la:
                g = (datetime.fromisoformat(la).astimezone(BA) - o["_dt"]).total_seconds() / 60
                if abs(g) > 5:
                    gap_gr.append((o["id"], o["_canal"], i.get("title"), round(g, 1)))
    print(f"lancamentos fora do horario: fora do turno 16h-08h: {len(fora_turno)} | antes das 18h: {len(antes18)} {antes18} | depois da meia-noite: {len(depois00)} {depois00} | itens lancados mais de 5 min antes/depois da criacao do pedido: {len(gap_gr)} {gap_gr[:5]}")
    print(f"  pedidos entre 23h e 00h: {len(depois23)} somando {brl(sum(o['total'] for o in depois23))} (ultimo as {max(o['_dt'] for o in ok).strftime('%H:%M')})")
    A.update({"fora_turno": len(fora_turno), "antes_18h": len(antes18), "depois_meia_noite": len(depois00), "itens_gap_maior_5min": len(gap_gr),
              "pedidos_23h": len(depois23), "pedidos_23h_valor": round(sum(o["total"] for o in depois23), 2)})
    # troco em cartao/pix
    print(f"pagamento em cartao/Pix com 'troco' (cobrado a mais que o pedido): {len(troco_nao_dinheiro)}")
    for x in troco_nao_dinheiro:
        print(f"    pedido {x[0]} | {x[1]} | {x[2]} | {x[3]}: cobrado {brl(x[4])}, pedido {brl(x[6])}, 'troco' {brl(x[5])} (= {x[5] / 2.99:.2f} pecas de 2,99 ou {x[5] / 1.99:.2f} de 1,99)")
    A["troco_cartao_pix_pedidos"] = len(troco_nao_dinheiro)
    A["troco_cartao_pix_valor"] = round(sum(x[5] for x in troco_nao_dinheiro), 2)
    # nota fiscal
    fis = collections.defaultdict(lambda: [0, 0.0])
    for o in ok:
        fis[(o["_canal"], str(o.get("fiscal_status")))][0] += 1
        fis[(o["_canal"], str(o.get("fiscal_status")))][1] += o["total"]
    print("situacao da nota (fiscal_status) na hora da leitura (12/11 01:34):")
    for (c, st), (n, v) in sorted(fis.items()):
        print(f"    {c:13s} {st:11s} {n:4d} pedidos {brl(v)}")
    pend = [o for o in ok if str(o.get("fiscal_status")).upper() != "AUTORIZADO"]
    print(f"    sem nota autorizada: {len(pend)} pedidos, {brl(sum(o['total'] for o in pend))} (salao: {sum(1 for o in pend if o['_canal'] == 'salao')} pedidos, {brl(sum(o['total'] for o in pend if o['_canal'] == 'salao'))})")
    ph = collections.Counter(o["created_at"][11:13] for o in pend if o["_canal"] == "salao")
    print(f"    salao pendente por hora: {sorted(ph.items())}")
    A["nota_pendente_pedidos"] = len(pend)
    A["nota_pendente_valor"] = round(sum(o["total"] for o in pend), 2)
    A["nota_pendente_salao_pedidos"] = sum(1 for o in pend if o["_canal"] == "salao")
    A["nota_pendente_salao_valor"] = round(sum(o["total"] for o in pend if o["_canal"] == "salao"), 2)
    # pedido do app com nome igual ao login da loja
    print("pedidos de app/iFood com item lancado em nome igual ao login da loja (conferir se e pedido da casa):")
    vistos = set()
    A["app_login_loja"] = []
    for (oid, c, hh, t) in loja_em_ext:
        if oid in vistos:
            continue
        vistos.add(oid)
        o = next(x for x in ok if x["id"] == oid)
        print(f"    pedido {oid} | {c} | {hh} | {o['delivery_type']} | {brl(o['total'])} | pagamento: {'+'.join(x[0] for x in parse_pagamento(o))} | itens: {', '.join(f'{q(i):.0f}x {i.get(chr(116) + chr(105) + chr(116) + chr(108) + chr(101))} a {pr(i):.2f}' for i in o['_itens'])}")
        A["app_login_loja"].append({"id": oid, "canal": c, "hora": hh, "total": o["total"], "pagamento": "+".join(x[0] for x in parse_pagamento(o))})
        prim = str(o.get("customer_name") or "").strip().split(" ")[0].lower()
        quem_l = {str(i.get("added_by_user_name") or "").strip().lower() for i in o["_itens"]}
        print(f"      -> 1o nome do cliente do pedido igual ao nome de quem lancou: {prim in quem_l} | nota fiscal: {o.get('fiscal_status')}")
    sem_pago = [(o["id"], o["created_at"][11:16], o["total"]) for o in salao if "PAGO" not in str(o.get("notes") or "").upper()]
    arq_nok = [(o["id"], o["_canal"], str((o.get("pagamento_para_arquivar") or {}).get("motivo"))[:60]) for o in ok if isinstance(o.get("pagamento_para_arquivar"), dict) and not o["pagamento_para_arquivar"].get("ok")]
    print(f"pedidos de salao sem a marca 'PEDIDO PAGO' nas notas: {len(sem_pago)} {sem_pago[:5]} | pedidos com 'pagamento_para_arquivar' nao ok: {len(arq_nok)} {arq_nok[:8]}")
    A["salao_sem_marca_pago"] = len(sem_pago)
    A["pagamento_para_arquivar_nao_ok"] = len(arq_nok)
    # observacoes nos itens do salao
    obs = [(o["id"], i.get("title"), i.get("observation")) for o in salao for i in o["_itens"] if (i.get("observation") or "").strip()]
    print(f"itens do salao com observacao digitada: {len(obs)} {obs[:5]}")
    A["itens_salao_com_observacao"] = len(obs)
    R["anomalias"] = A

    # ------------------------------------------------------------------ CONTEXTO: QUARTAS DE REFERENCIA
    if ref_ok:
        print()
        print("=" * 100)
        print("CONTEXTO (quartas de referencia, mesmas regras) - so para os itens 6, 7 e 8")
        print("=" * 100)
        print("arquivo | pedidos salao | logins que lancaram no salao | pecas promo (botoes 1,99/2,99, acarajapa, sashimi) fora do salao | pecas por produto especifico de 1 peca (salao / outros) | 'Sunomono' 2,99 no salao | % pedidos salao c/ bebida")
        R["contexto"] = []
        for nome, dr in [(arq.split("/")[-1], ok)] + ref_ok:
            sal = [o for o in dr if o["_canal"] == "salao"]
            logins = collections.Counter(str(i.get("added_by_user_name")) for o in sal for i in o["_itens"])
            fora_n = sum(q(i) for o in dr if o["_canal"] != "salao" for i in o["_itens"] if tipo_peca(i) in ("rolo_1_99", "joy_niguiri_2_99", "acarajapa", "sashimi", "generico_outro_preco"))
            fora_v = sum(q(i) * pr(i) for o in dr if o["_canal"] != "salao" for i in o["_itens"] if tipo_peca(i) in ("rolo_1_99", "joy_niguiri_2_99", "acarajapa", "sashimi", "generico_outro_preco"))
            us = sum(q(i) for o in sal for i in o["_itens"] if RE_UNIT.search(i.get("title") or ""))
            uo = sum(q(i) for o in dr if o["_canal"] != "salao" for i in o["_itens"] if RE_UNIT.search(i.get("title") or ""))
            sn = sum(q(i) for o in sal for i in o["_itens"] if (i.get("title") or "").strip().upper() == "SUNOMONO" and round(pr(i), 2) == 2.99)
            cbeb = sum(1 for o in sal if any(eh_bebida(i) for i in o["_itens"]))
            print(f"  {nome} | {len(sal)} | {dict(logins)} | {fora_n:.0f} un {brl(fora_v)} | {us:.0f} / {uo:.0f} | {sn:.0f} | {pct(cbeb, len(sal)):.1f}%")
            R["contexto"].append({"arquivo": nome, "pedidos_salao": len(sal), "logins": dict(logins), "promo_fora_un": fora_n, "promo_fora_valor": round(fora_v, 2),
                                  "unidade_especifica_salao": us, "unidade_especifica_outros": uo, "sunomono_2_99": sn, "pct_salao_com_bebida": round(pct(cbeb, len(sal)), 2)})
        ant = [x["pct_salao_com_bebida"] for x in R["contexto"][1:]]
        media_ant = statistics.mean(ant)
        falt = max(0.0, (media_ant - R["bebidas"]["pct_pedidos_com_bebida"]) / 100 * len(salao))
        print(f"  bebida: media das {len(ant)} quartas anteriores = {media_ant:.1f}% dos pedidos de salao (min {min(ant):.1f}%, max {max(ant):.1f}%) x {R['bebidas']['pct_pedidos_com_bebida']:.1f}% em 11/11")
        print(f"    se 11/11 tivesse repetido a media: +{falt:.1f} pedidos com bebida x {brl(R['bebidas']['receita_por_pedido_com_bebida'])} = +{brl(falt * R['bebidas']['receita_por_pedido_com_bebida'])} de receita (+{brl(falt * R['bebidas']['receita_por_pedido_com_bebida'] * (1 - CUSTO_REFRI_PCT))} de margem a 65%)")
        R["bebidas"]["media_quartas_anteriores_pct"] = round(media_ant, 2)
        R["bebidas"]["gap_vs_media_pedidos"] = round(falt, 1)
        R["bebidas"]["gap_vs_media_receita"] = round(falt * R["bebidas"]["receita_por_pedido_com_bebida"], 2)
        R["bebidas"]["gap_vs_media_margem"] = round(falt * R["bebidas"]["receita_por_pedido_com_bebida"] * (1 - CUSTO_REFRI_PCT), 2)

    if saida_json:
        def limpa(x):
            if isinstance(x, dict):
                return {str(k): limpa(v) for k, v in x.items()}
            if isinstance(x, (list, tuple, set)):
                return [limpa(v) for v in x]
            if isinstance(x, float):
                return round(x, 4)
            return x
        json.dump(limpa(R), open(saida_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n(json gravado em {saida_json})")


if __name__ == "__main__":
    main()
