#!/usr/bin/env python3
"""Quarta Maluca 11/11/2026 - simulacao de precos e oportunidades (agents/precos).

Uso (somente leitura, so arquivos locais):
  python3 -I simula_precos.py <pedidos_2026-11-11.json> <custo_por_peca.json> <inventory.json> \
      <custos_aliv.json> <saida.json> [pedidos de quartas anteriores ...]

"Sobra" = receita - custo de ingredientes - imposto (11% da receita).
Elasticidade (queda/aumento de volume) e HIPOTESE, nao dado.
"""
import json
import re
import sys
import unicodedata

IMP = 0.11
P_ROLO = 1.99
P_N2 = 2.99
C_ROLO = {"otimista": 0.45, "central": 0.60, "pessimista": 0.72}
MIXES = (0.25, 0.50, 0.75)  # participacao do Joy nas pecas de 2,99
QUEDAS_JOY = (0.0, 0.15, 0.30, 0.50)
QUEDAS_NIG = (0.0, 0.10)
ROLOS_BARATOS = (
    "Hossomaki Camarão Empanado",
    "Hossomaki Atum",
    "Hossomaki Salmão Grelhado",
    "Hossomaki Camarão Cozido",
    "Uramaki Salmão Grelhado",
)
P_ROLO_BARATO = 1.49
FRACOES = (0.20, 0.40, 0.60)
AUMENTOS = (0.0, 0.20, 0.40)
CUSTO_PCT_ESTIMADO = 0.35
CUSTO_FIXO_DIA = 1896.96
CAT_BEBIDA = ("Bebidas", "Cervejas")
PALAVRAS_BEBIDA = ("coca", "guaran", "suco", "água", "agua", "heineken", "corona", "stella", "cerveja", "fanta", "sprite")


def r2(x):
    return round(x + 0.0, 2)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def itens(o):
    it = o.get("items_json") or []
    if isinstance(it, str):
        it = json.loads(it)
    return it


def valido(o):
    return "CANCEL" not in str(o.get("status", "")).upper()


def eh_salao(o):
    return o.get("platform_slug") == "pdv" and o.get("delivery_type") != "delivery"


def qtd(i):
    return float(i.get("quantity") or 0)


def preco(i):
    return float(i.get("price") or 0)


def eh_peca_rolo(i):
    return i.get("title") in ("QUARTA MALUCA", "PEÇA SUSHI") and abs(preco(i) - 1.99) < 0.005


def eh_peca_n2(i):
    return i.get("title") in ("PEÇA SUSHI", "Sunomono") and abs(preco(i) - 2.99) < 0.005


def eh_bebida(i):
    cat = i.get("category_name")
    if cat in CAT_BEBIDA:
        return True
    if cat is None:
        t = str(i.get("title", "")).lower()
        return any(p in t for p in PALAVRAS_BEBIDA)
    return False


def eh_cerveja(i):
    if i.get("category_name") == "Cervejas":
        return True
    t = str(i.get("title", "")).lower()
    return any(p in t for p in ("heineken", "corona", "stella", "cerveja"))


def sobra(receita, custo):
    return receita - custo - IMP * receita


def margem_peca(p, c):
    return p * (1 - IMP) - c


def custo_cerveja(titulo, estoque):
    """Casa 'Heineken 330ml' com 'Cerveja Heineken Long Neck 330ml' do estoque."""
    alvo = norm(titulo)
    for g in estoque:
        nome = norm(g["name"])
        if not nome.startswith("cerveja"):
            continue
        limpo = nome.replace("cerveja ", "").replace("long neck ", "")
        if limpo == alvo and str(g.get("unit")) == "UN" and float(g.get("cost") or 0) > 0:
            return float(g["cost"])
    return None


def resumo_noite(pedidos):
    ok = [o for o in pedidos if valido(o)]
    salao = [o for o in ok if eh_salao(o)]
    n1 = sum(qtd(i) for o in ok for i in itens(o) if eh_peca_rolo(i))
    n2 = sum(qtd(i) for o in ok for i in itens(o) if eh_peca_n2(i))
    n1_fora = sum(qtd(i) for o in ok if not eh_salao(o) for i in itens(o) if eh_peca_rolo(i))
    n2_fora = sum(qtd(i) for o in ok if not eh_salao(o) for i in itens(o) if eh_peca_n2(i))
    com_beb = [o for o in salao if any(eh_bebida(i) for i in itens(o))]
    un_beb = sum(qtd(i) for o in salao for i in itens(o) if eh_bebida(i))
    rec_beb = sum(qtd(i) * preco(i) for o in salao for i in itens(o) if eh_bebida(i))
    return {
        "pedidos": len(pedidos),
        "validos": len(ok),
        "cancelados": len(pedidos) - len(ok),
        "salao": len(salao),
        "receita_salao": sum(float(o.get("total") or 0) for o in salao),
        "desconto_salao": sum(float(o.get("discount") or 0) for o in salao),
        "n1": n1,
        "n2": n2,
        "n1_fora_salao": n1_fora,
        "n2_fora_salao": n2_fora,
        "salao_com_bebida": len(com_beb),
        "unidades_bebida": un_beb,
        "receita_bebida": rec_beb,
    }


def grade(n2, c_joy, c_nig, p_nig, p_joy, extra_salao):
    """Grade mix x queda Joy x queda niguiri para uma tabela (p_nig, p_joy)."""
    linhas, equil = [], []
    for mix in MIXES:
        joy, nig = n2 * mix, n2 * (1 - mix)
        rec0 = n2 * P_N2
        cus0 = joy * c_joy + nig * c_nig
        s0 = sobra(rec0, cus0)
        mj0, mg0 = margem_peca(P_N2, c_joy), margem_peca(P_N2, c_nig)
        mj1, mg1 = margem_peca(p_joy, c_joy), margem_peca(p_nig, c_nig)
        for qn in QUEDAS_NIG:
            for qj in QUEDAS_JOY:
                j1, g1 = joy * (1 - qj), nig * (1 - qn)
                rec1 = j1 * p_joy + g1 * p_nig
                cus1 = j1 * c_joy + g1 * c_nig
                s1 = sobra(rec1, cus1)
                linhas.append({
                    "mix_joy": mix, "queda_joy": qj, "queda_niguiri": qn,
                    "pecas_joy": j1, "pecas_niguiri": g1,
                    "receita": rec1, "custo": cus1, "sobra": s1,
                    "receita_real": rec0, "sobra_real": s0,
                    "dif_receita": rec1 - rec0, "dif_sobra": s1 - s0,
                    "dif_sobra_pct": (s1 - s0) / s0,
                })
        s_sem_queda = joy * mj1 + nig * mg1
        e = {
            "mix_joy": mix,
            "sobra_real": s0,
            "sobra_nova_sem_queda": s_sem_queda,
            "ganho_sem_queda_parte_joy": joy * (mj1 - mj0),
            "ganho_sem_queda_parte_niguiri": nig * (mg1 - mg0),
            # so o Joy (ignora o ganho do niguiri): queda que zera o ganho do proprio Joy
            "equilibrio_joy_isolado": 1 - mj0 / mj1,
            # so o niguiri
            "equilibrio_niguiri_isolado": 1 - mg0 / mg1,
            # grupo todo, com o niguiri caindo 0% ou 10%: quanto o Joy pode cair
            "equilibrio_joy_grupo_nig_0": 1 - (s0 - nig * mg1) / (joy * mj1),
            "equilibrio_joy_grupo_nig_10": 1 - (s0 - nig * 0.90 * mg1) / (joy * mj1),
            # Joy e niguiri caindo o MESMO percentual
            "equilibrio_queda_igual": 1 - s0 / s_sem_queda,
            # movimento do salao inteiro caindo (rolos, bebidas e o resto junto)
            "equilibrio_movimento_salao": 1 - (extra_salao + s0) / (extra_salao + s_sem_queda),
        }
        equil.append(e)
    return linhas, equil


def imprime_grade(titulo, linhas, equil):
    print()
    print(titulo)
    print(f"{'mix Joy':>8} {'q.Joy':>6} {'q.nig':>6} {'receita':>10} {'custo':>9} {'sobra':>9} {'dif.sobra':>10} {'dif.%':>7}")
    for l in linhas:
        print(f"{l['mix_joy']*100:7.0f}% {-l['queda_joy']*100:5.0f}% {-l['queda_niguiri']*100:5.0f}% "
              f"{l['receita']:10.2f} {l['custo']:9.2f} {l['sobra']:9.2f} {l['dif_sobra']:+10.2f} {l['dif_sobra_pct']*100:+6.1f}%")
    print("  Ponto de equilibrio (queda maxima de volume para a sobra ficar igual a de hoje):")
    print(f"   niguiri isolado (so o aumento do niguiri): {equil[0]['equilibrio_niguiri_isolado']*100:.1f}%")
    for e in equil:
        print(f"   mix {e['mix_joy']*100:.0f}% Joy, sem queda: ganho que vem do Joy {e['ganho_sem_queda_parte_joy']:+.2f} | "
              f"do niguiri {e['ganho_sem_queda_parte_niguiri']:+.2f}")
    for e in equil:
        print(f"   mix {e['mix_joy']*100:.0f}% Joy: Joy isolado {e['equilibrio_joy_isolado']*100:.1f}% | "
              f"Joy no grupo (niguiri 0%) {e['equilibrio_joy_grupo_nig_0']*100:.1f}% | "
              f"Joy no grupo (niguiri -10%) {e['equilibrio_joy_grupo_nig_10']*100:.1f}% | "
              f"Joy e niguiri caindo igual {e['equilibrio_queda_igual']*100:.1f}% | "
              f"movimento do salao inteiro {e['equilibrio_movimento_salao']*100:.1f}%")


def main():
    ped_path, cpp_path, inv_path, custos_path, out_path = sys.argv[1:6]
    hist_paths = sys.argv[6:]
    pedidos = json.load(open(ped_path, encoding="utf-8"))
    cpp = json.load(open(cpp_path, encoding="utf-8"))
    estoque = json.load(open(inv_path, encoding="utf-8"))["ingredients"]
    custos = json.load(open(custos_path, encoding="utf-8"))
    R = {}

    # ---------------------------------------------------------------- volume real
    base = resumo_noite(pedidos)
    n1, n2 = base["n1"], base["n2"]
    c_joy = cpp["joy"]["Joy Fila"]
    c_nig = cpp["niguiri"]["Niguiri Salmão"]
    c_barato = sum(cpp["rolos_1_99"][n] for n in ROLOS_BARATOS) / len(ROLOS_BARATOS)
    caros = [v for k, v in cpp["rolos_1_99"].items() if k not in ROLOS_BARATOS]
    c_caro = sum(caros) / len(caros)
    R["base"] = dict(base, custo_joy=c_joy, custo_niguiri=c_nig, custo_rolo_barato_medio=c_barato,
                     custo_rolo_caro_medio=c_caro)
    print("== VOLUME REAL 11/11/2026 ==")
    print(f"pedidos {base['pedidos']} | validos {base['validos']} | cancelados {base['cancelados']} | salao {base['salao']}")
    print(f"receita salao R$ {base['receita_salao']:.2f} | descontos no salao R$ {base['desconto_salao']:.2f}")
    print(f"N1 (pecas de rolo a 1,99) = {n1:.0f} (fora do salao: {base['n1_fora_salao']:.0f})")
    print(f"N2 (pecas Joy/niguiri a 2,99, PECA SUSHI + Sunomono) = {n2:.0f} (fora do salao: {base['n2_fora_salao']:.0f})")
    print(f"custo/peca: Joy Fila {c_joy:.4f} | niguiri salmao {c_nig:.4f} | 5 rolos baratos (media) {c_barato:.4f} | 10 rolos caros (media) {c_caro:.4f}")

    # ------------------------------------------------------- margem por peca
    print("\n== SOBRA POR PECA (preco x 0,89 - custo) ==")
    mp = {
        "rolo 1,99 custo 0,45": margem_peca(1.99, 0.45),
        "rolo 1,99 custo 0,60 (central)": margem_peca(1.99, 0.60),
        "rolo 1,99 custo 0,72": margem_peca(1.99, 0.72),
        "rolo barato a 1,99": margem_peca(1.99, c_barato),
        "rolo barato a 1,49": margem_peca(1.49, c_barato),
        "rolo caro (media dos 10) a 1,99": margem_peca(1.99, c_caro),
        "niguiri salmao a 2,99": margem_peca(2.99, c_nig),
        "niguiri salmao a 3,49": margem_peca(3.49, c_nig),
        "Joy Fila a 2,99": margem_peca(2.99, c_joy),
        "Joy Fila a 3,99": margem_peca(3.99, c_joy),
        "Joy Fila a 4,99": margem_peca(4.99, c_joy),
    }
    for k, v in mp.items():
        print(f"  {k:34s} R$ {v:.4f}")
    R["sobra_por_peca"] = mp

    # ------------------------------------------------- 1. situacao real
    print("\n== 1. SITUACAO REAL (precos atuais) ==")
    real = {"n1": {}, "n2": {}, "total": {}}
    rec1 = n1 * P_ROLO
    for nome, c in C_ROLO.items():
        cus = n1 * c
        real["n1"][nome] = {"pecas": n1, "receita": rec1, "custo": cus, "imposto": IMP * rec1,
                            "sobra": sobra(rec1, cus), "sobra_pct": sobra(rec1, cus) / rec1}
        print(f"N1 rolos custo {nome} ({c:.2f}): receita {rec1:.2f} | custo {cus:.2f} | imposto {IMP*rec1:.2f} | sobra {sobra(rec1, cus):.2f} ({sobra(rec1, cus)/rec1*100:.1f}%)")
    rec2 = n2 * P_N2
    for mix in MIXES:
        joy, nig = n2 * mix, n2 * (1 - mix)
        cus = joy * c_joy + nig * c_nig
        s = sobra(rec2, cus)
        real["n2"][f"{int(mix*100)}"] = {"pecas_joy": joy, "pecas_niguiri": nig, "receita": rec2, "custo": cus,
                                          "custo_por_peca": cus / n2, "imposto": IMP * rec2, "sobra": s,
                                          "sobra_pct": s / rec2,
                                          "sobra_so_joy": joy * margem_peca(P_N2, c_joy),
                                          "sobra_so_niguiri": nig * margem_peca(P_N2, c_nig)}
        tot_rec, tot_cus = rec1 + rec2, n1 * C_ROLO["central"] + cus
        real["total"][f"{int(mix*100)}"] = {"receita": tot_rec, "custo": tot_cus, "sobra": sobra(tot_rec, tot_cus)}
        print(f"N2 mix {mix*100:.0f}% Joy ({joy:.0f} Joy + {nig:.0f} niguiri): receita {rec2:.2f} | custo {cus:.2f} ({cus/n2:.3f}/peca) | "
              f"imposto {IMP*rec2:.2f} | sobra {s:.2f} ({s/rec2*100:.1f}%) | N1 central + N2: receita {tot_rec:.2f}, sobra {sobra(tot_rec, tot_cus):.2f}")
    R["real"] = real

    # --------------------- sobra do resto do salao (para o teste de movimento)
    outros_rec = outros_cus = outros_est = 0.0
    for o in pedidos:
        if not (valido(o) and eh_salao(o)):
            continue
        for i in itens(o):
            if eh_peca_rolo(i) or eh_peca_n2(i):
                continue
            q, p, t = qtd(i), preco(i), str(i.get("title", ""))
            rec = q * p
            if t == "Acarajapa":
                c = q * cpp["acarajapa"]
            elif t == "Sashimi":
                c = q * cpp["sashimi"]
            elif t in custos and custos[t] > 0:
                c = q * custos[t]
            elif eh_cerveja(i) and custo_cerveja(t, estoque) is not None:
                c = q * custo_cerveja(t, estoque)
            else:
                c = rec * CUSTO_PCT_ESTIMADO
                outros_est += rec
            outros_rec += rec
            outros_cus += c
    outros_sobra = sobra(outros_rec, outros_cus)
    extra_salao = sobra(rec1, n1 * C_ROLO["central"]) + outros_sobra
    R["outros_salao"] = {"receita": outros_rec, "custo": outros_cus, "sobra": outros_sobra,
                         "receita_em_estimativa_35pct": outros_est}
    print(f"Resto do salao (acarajapa, sashimi, bebidas, temaki, picole): receita {outros_rec:.2f} | custo {outros_cus:.2f} | sobra {outros_sobra:.2f} | "
          f"receita com custo estimado em 35%: {outros_est:.2f}")
    print(f"Conferencia: N1 + N2 + resto = {rec1 + rec2 + outros_rec:.2f} (receita do salao {base['receita_salao']:.2f})")

    # ------------------------------------------------- 2 e 3. tabelas novas
    print("\n== 2. TABELA SUGERIDA: niguiri 3,49 e Joy 4,99 ==")
    l_a, e_a = grade(n2, c_joy, c_nig, 3.49, 4.99, extra_salao)
    imprime_grade("Grade (diferenca contra a situacao real do mesmo mix)", l_a, e_a)
    R["tabela_349_499"] = {"linhas": l_a, "equilibrio": e_a}

    print("\n== 3. ALTERNATIVA INTERMEDIARIA: niguiri 3,49 e Joy 3,99 ==")
    l_b, e_b = grade(n2, c_joy, c_nig, 3.49, 3.99, extra_salao)
    imprime_grade("Grade (diferenca contra a situacao real do mesmo mix)", l_b, e_b)
    R["tabela_349_399"] = {"linhas": l_b, "equilibrio": e_b}

    # A (Joy 4,99) x B (Joy 3,99): ate que queda do Joy a 4,99 a tabela A ainda rende mais que a B
    mja, mjb = margem_peca(4.99, c_joy), margem_peca(3.99, c_joy)
    indif = {f"queda_B_{int(y*100)}": 1 - (1 - y) * mjb / mja for y in (0.0, 0.15, 0.30)}
    R["indiferenca_A_x_B"] = indif
    print("\nJoy a 4,99 rende mais que Joy a 3,99 enquanto a queda do Joy a 4,99 ficar abaixo de: "
          + " | ".join(f"{v*100:.1f}% (se a 3,99 cair {k.split('_')[-1]}%)" for k, v in indif.items()))

    # efeito de troca: Joy perdido que vira outra peca
    troca = {
        "joy_2_99_vira_rolo_1_99_central": margem_peca(1.99, 0.60) - margem_peca(2.99, c_joy),
        "joy_2_99_vira_niguiri_3_49": margem_peca(3.49, c_nig) - margem_peca(2.99, c_joy),
        "joy_4_99_para_empatar_com_niguiri_3_49": (margem_peca(3.49, c_nig) + c_joy) / (1 - IMP),
        "joy_preco_para_empatar_com_rolo_1_99": (margem_peca(1.99, 0.60) + c_joy) / (1 - IMP),
    }
    R["troca"] = troca
    print("\nTrocas (por peca): Joy de 2,99 que vira rolo de 1,99 muda a sobra em "
          f"{troca['joy_2_99_vira_rolo_1_99_central']:+.4f}; que vira niguiri de 3,49: {troca['joy_2_99_vira_niguiri_3_49']:+.4f}")
    print(f"Preco do Joy que da a mesma sobra de um rolo de 1,99 (custo 0,60): R$ {troca['joy_preco_para_empatar_com_rolo_1_99']:.2f}; "
          f"de um niguiri a 3,49: R$ {troca['joy_4_99_para_empatar_com_niguiri_3_49']:.2f}")

    # ------------------------------------------------- 4. rolos a 1,49
    print("\n== 4. ROLOS BARATOS A 1,49 ==")
    m199, m149 = margem_peca(P_ROLO, c_barato), margem_peca(P_ROLO_BARATO, c_barato)
    equil_rolo = m199 / m149 - 1
    equil_rolo_receita = P_ROLO / P_ROLO_BARATO - 1
    rolos = []
    print(f"custo medio dos 5 rolos baratos: {c_barato:.4f} | sobra/peca a 1,99: {m199:.4f} | a 1,49: {m149:.4f}")
    print(f"{'fracao':>7} {'aumento':>8} {'pecas hoje':>11} {'pecas novas':>12} {'dif.receita':>12} {'dif.sobra':>10} {'custo resto':>12}")
    for f in FRACOES:
        n = n1 * f
        resto = (C_ROLO["central"] - f * c_barato) / (1 - f)  # custo implicito das demais pecas
        for g in AUMENTOS:
            d_rec = n * (1 + g) * P_ROLO_BARATO - n * P_ROLO
            d_sob = n * ((1 + g) * m149 - m199)
            rolos.append({"fracao": f, "aumento_volume": g, "pecas_hoje": n, "pecas_novas": n * (1 + g),
                          "dif_receita": d_rec, "dif_sobra": d_sob, "custo_implicito_demais_pecas": resto})
            print(f"{f*100:6.0f}% {g*100:+7.0f}% {n:11.0f} {n*(1+g):12.0f} {d_rec:+12.2f} {d_sob:+10.2f} {resto:12.3f}")
    # se o volume extra vier de quem trocaria um rolo caro (canibalizacao)
    perda_troca = margem_peca(P_ROLO, c_caro) - m149
    R["rolos_149"] = {"linhas": rolos, "equilibrio_aumento_volume_sobra": equil_rolo,
                      "equilibrio_aumento_volume_receita": equil_rolo_receita,
                      "sobra_peca_199": m199, "sobra_peca_149": m149,
                      "perda_por_peca_se_cliente_troca_rolo_caro_por_barato": perda_troca,
                      "fracao_maxima_coerente_com_custo_central":
                          (max(cpp["rolos_1_99"].values()) - C_ROLO["central"]) / (max(cpp["rolos_1_99"].values()) - c_barato)}
    print(f"Ponto de equilibrio: o volume dessas pecas precisa subir {equil_rolo*100:.1f}% para a SOBRA empatar "
          f"({equil_rolo_receita*100:.1f}% para a RECEITA empatar).")
    print(f"Se o cliente so troca um rolo caro de 1,99 por um barato de 1,49: perde R$ {perda_troca:.4f} por peca trocada.")
    print(f"Fracao maxima de rolos baratos coerente com custo medio 0,60: {R['rolos_149']['fracao_maxima_coerente_com_custo_central']*100:.1f}%")
    cb = [cpp["rolos_1_99"][n] for n in ROLOS_BARATOS]
    eq_min = margem_peca(P_ROLO, min(cb)) / margem_peca(P_ROLO_BARATO, min(cb)) - 1
    eq_max = margem_peca(P_ROLO, max(cb)) / margem_peca(P_ROLO_BARATO, max(cb)) - 1
    R["rolos_149"]["equilibrio_rolo_mais_barato"] = eq_min
    R["rolos_149"]["equilibrio_rolo_mais_caro_dos_5"] = eq_max
    print(f"Equilibrio por rolo: do mais barato ({min(cb):.3f}) +{eq_min*100:.1f}% ao mais caro dos 5 ({max(cb):.3f}) +{eq_max*100:.1f}%")

    # ------------------------------------------------- 5. bebidas
    print("\n== 5. BEBIDAS NO SALAO ==")
    salao = [o for o in pedidos if valido(o) and eh_salao(o)]
    com_beb = [o for o in salao if any(eh_bebida(i) for i in itens(o))]
    com_pecas = [o for o in salao if any(eh_peca_rolo(i) or eh_peca_n2(i) for i in itens(o))]
    com_pecas_e_beb = [o for o in com_pecas if any(eh_bebida(i) for i in itens(o))]
    so_beb = [o for o in salao if itens(o) and all(eh_bebida(i) for i in itens(o))]
    un_tot = un_sem = rec_tot = rec_sem = cus_tot = 0.0
    por_titulo = {}
    for o in salao:
        for i in itens(o):
            if not eh_bebida(i):
                continue
            q, p, t = qtd(i), preco(i), str(i.get("title"))
            un_tot += q
            rec_tot += q * p
            if eh_cerveja(i):
                c = custo_cerveja(t, estoque)
                cus_tot += q * (c if c is not None else p * CUSTO_PCT_ESTIMADO)
            else:
                un_sem += q
                rec_sem += q * p
                cus_tot += q * p * CUSTO_PCT_ESTIMADO
            a = por_titulo.setdefault(t, [0.0, 0.0])
            a[0] += q
            a[1] += q * p
    pct_beb = len(com_beb) / len(salao)
    rec_media_pedido = rec_tot / len(com_beb)
    p_medio_todas = rec_tot / un_tot
    p_medio_sem_alcool = rec_sem / un_sem
    mais_vendida = max(por_titulo.items(), key=lambda kv: kv[1][0])
    p_lata = mais_vendida[1][1] / mais_vendida[1][0]
    print(f"pedidos de salao: {len(salao)} | com bebida: {len(com_beb)} ({pct_beb*100:.1f}%) | so bebida (sem peca): {len(so_beb)}")
    print(f"pedidos com pecas: {len(com_pecas)} | desses, com bebida no mesmo pedido: {len(com_pecas_e_beb)} ({len(com_pecas_e_beb)/len(com_pecas)*100:.1f}%)")
    print(f"unidades de bebida: {un_tot:.0f} (sem alcool {un_sem:.0f}, cerveja {un_tot-un_sem:.0f}) | receita bebida {rec_tot:.2f} | custo {cus_tot:.2f} | sobra {sobra(rec_tot, cus_tot):.2f}")
    print(f"receita media de bebida por pedido com bebida: {rec_media_pedido:.2f} | unidades por pedido com bebida: {un_tot/len(com_beb):.2f} | bebidas por pedido de salao: {un_tot/len(salao):.3f}")
    print(f"preco medio por bebida: todas {p_medio_todas:.2f} | sem alcool {p_medio_sem_alcool:.2f} | mais vendida: {mais_vendida[0]} ({mais_vendida[1][0]:.0f} un a {p_lata:.2f})")
    beb = {"salao": len(salao), "com_bebida": len(com_beb), "pct_com_bebida": pct_beb, "so_bebida": len(so_beb),
           "com_pecas": len(com_pecas), "com_pecas_e_bebida": len(com_pecas_e_beb),
           "pct_com_pecas_e_bebida": len(com_pecas_e_beb) / len(com_pecas),
           "unidades": un_tot, "unidades_sem_alcool": un_sem, "receita": rec_tot, "custo": cus_tot,
           "sobra": sobra(rec_tot, cus_tot), "receita_media_por_pedido_com_bebida": rec_media_pedido,
           "unidades_por_pedido_com_bebida": un_tot / len(com_beb), "preco_medio_todas": p_medio_todas,
           "preco_medio_sem_alcool": p_medio_sem_alcool, "mais_vendida": mais_vendida[0], "preco_mais_vendida": p_lata,
           "participacao_bebida_na_receita_salao": rec_tot / base["receita_salao"], "ganhos": []}
    for pp in (0.10, 0.20):
        extra = len(salao) * pp
        for rotulo, p in (("preco medio sem alcool", p_medio_sem_alcool), ("preco medio de todas", p_medio_todas),
                          ("lata mais vendida", p_lata)):
            rec = extra * p
            cus = rec * CUSTO_PCT_ESTIMADO
            g = {"pontos": pp, "base_preco": rotulo, "preco": p, "bebidas_a_mais": extra, "receita": rec,
                 "custo": cus, "sobra": sobra(rec, cus)}
            beb["ganhos"].append(g)
            print(f"+{pp*100:.0f} p.p. ({extra:.1f} bebidas a mais) a {p:.2f} ({rotulo}): receita +{rec:.2f} | custo {cus:.2f} | sobra +{sobra(rec, cus):.2f}")
    R["bebidas"] = beb

    # historico das quartas (contexto: taxa de bebida e peso das pecas de 2,99)
    print("\n== CONTEXTO: quartas anteriores (mesmas regras) ==")
    hist = []
    for path in list(hist_paths) + [ped_path]:
        b = resumo_noite(json.load(open(path, encoding="utf-8")))
        nome = re.search(r"(\d{4}-\d{2}-\d{2})", path).group(1)
        h = {"data": nome, "salao": b["salao"], "n1": b["n1"], "n2": b["n2"],
             "peso_n2_nas_pecas": b["n2"] / (b["n1"] + b["n2"]),
             "pct_salao_com_bebida": b["salao_com_bebida"] / b["salao"],
             "bebidas_por_pedido": b["unidades_bebida"] / b["salao"],
             "receita_bebida": b["receita_bebida"], "unidades_bebida": b["unidades_bebida"]}
        hist.append(h)
        print(f"{nome}: salao {b['salao']} | N1 {b['n1']:.0f} | N2 {b['n2']:.0f} ({h['peso_n2_nas_pecas']*100:.1f}% das pecas) | "
              f"pedidos com bebida {b['salao_com_bebida']} ({h['pct_salao_com_bebida']*100:.1f}%) | bebidas {b['unidades_bebida']:.0f} "
              f"({h['bebidas_por_pedido']:.3f}/pedido) | receita bebida {b['receita_bebida']:.2f}")
    ant = hist[:-1]
    if ant:
        media_pct = sum(h["pct_salao_com_bebida"] for h in ant) / len(ant)
        media_peso = sum(h["peso_n2_nas_pecas"] for h in ant) / len(ant)
        R["historico_media_pct_bebida_anteriores"] = media_pct
        R["historico_media_peso_n2_anteriores"] = media_peso
        print(f"media das {len(ant)} quartas anteriores: {media_pct*100:.1f}% dos pedidos de salao com bebida | N2 = {media_peso*100:.1f}% das pecas")
    R["historico"] = hist
    if ant:
        ped_falta = (media_pct - pct_beb) * len(salao)
        rec_falta = ped_falta * rec_media_pedido
        sob_falta = rec_falta * (1 - CUSTO_PCT_ESTIMADO - IMP)
        R["bebidas"]["volta_a_media_historica"] = {"pontos": media_pct - pct_beb, "pedidos": ped_falta,
                                                   "receita": rec_falta, "sobra": sob_falta}
        print(f"Voltar a media anterior de bebida ({(media_pct-pct_beb)*100:+.1f} p.p. = {ped_falta:.1f} pedidos x R$ {rec_media_pedido:.2f}): "
              f"receita +{rec_falta:.2f} | sobra +{sob_falta:.2f} (custo 35%)")

    # ------------------------------------------------- 6. projecao mensal
    print("\n== 6. PROJECAO MENSAL (4 quartas) ==")

    def pega(linhas, mix, qj, qn):
        for l in linhas:
            if abs(l["mix_joy"] - mix) < 1e-9 and abs(l["queda_joy"] - qj) < 1e-9 and abs(l["queda_niguiri"] - qn) < 1e-9:
                return l
        raise KeyError((mix, qj, qn))

    proj = []
    cenarios = (
        ("A. niguiri 3,49 + Joy 4,99 | sem queda", l_a, 0.0, 0.0),
        ("A. niguiri 3,49 + Joy 4,99 | prudente (Joy -30%, niguiri -10%)", l_a, 0.30, 0.10),
        ("A. niguiri 3,49 + Joy 4,99 | ruim (Joy -50%, niguiri -10%)", l_a, 0.50, 0.10),
        ("B. niguiri 3,49 + Joy 3,99 | sem queda", l_b, 0.0, 0.0),
        ("B. niguiri 3,49 + Joy 3,99 | prudente (Joy -15%, niguiri -10%)", l_b, 0.15, 0.10),
        ("B. niguiri 3,49 + Joy 3,99 | ruim (Joy -30%, niguiri -10%)", l_b, 0.30, 0.10),
    )
    for nome, linhas, qj, qn in cenarios:
        v = {m: pega(linhas, m, qj, qn)["dif_sobra"] for m in MIXES}
        p = {"cenario": nome, "por_quarta_mix25": v[0.25], "por_quarta_mix50": v[0.50], "por_quarta_mix75": v[0.75],
             "mes_mix25": 4 * v[0.25], "mes_mix50": 4 * v[0.50], "mes_mix75": 4 * v[0.75]}
        proj.append(p)
        print(f"{nome}: por quarta {v[0.25]:+.2f} / {v[0.50]:+.2f} / {v[0.75]:+.2f} (mix 25/50/75% Joy) | "
              f"por mes {4*v[0.25]:+.2f} / {4*v[0.50]:+.2f} / {4*v[0.75]:+.2f}")
    g10 = next(g for g in beb["ganhos"] if g["pontos"] == 0.10 and g["base_preco"] == "preco medio sem alcool")
    g20 = next(g for g in beb["ganhos"] if g["pontos"] == 0.20 and g["base_preco"] == "preco medio sem alcool")
    g10_lata = next(g for g in beb["ganhos"] if g["pontos"] == 0.10 and g["base_preco"] == "lata mais vendida")
    print(f"C. bebidas +10 p.p.: por quarta +{g10['sobra']:.2f} (lata: +{g10_lata['sobra']:.2f}) | por mes +{4*g10['sobra']:.2f} (lata: +{4*g10_lata['sobra']:.2f})")
    print(f"C. bebidas +20 p.p.: por quarta +{g20['sobra']:.2f} | por mes +{4*g20['sobra']:.2f}")
    pior_rolo = min(rolos, key=lambda x: x["dif_sobra"])
    melhor_rolo = max(rolos, key=lambda x: x["dif_sobra"])
    rolo_40_20 = next(x for x in rolos if abs(x["fracao"] - 0.40) < 1e-9 and abs(x["aumento_volume"] - 0.20) < 1e-9)
    print(f"(nao recomendado) rolos a 1,49: fracao 40% com +20% de volume: por quarta {rolo_40_20['dif_sobra']:+.2f} | por mes {4*rolo_40_20['dif_sobra']:+.2f}; "
          f"melhor caso da grade {melhor_rolo['dif_sobra']:+.2f}, pior {pior_rolo['dif_sobra']:+.2f} por quarta")
    a_prud = pega(l_a, 0.50, 0.30, 0.10)["dif_sobra"]
    b_prud = pega(l_b, 0.50, 0.15, 0.10)["dif_sobra"]
    comb_a = a_prud + g10["sobra"]
    comb_b = b_prud + g10["sobra"]
    print(f"Pacote prudente A + C (mix 50%): por quarta +{comb_a:.2f} | por mes +{4*comb_a:.2f} | equivale a {comb_a/CUSTO_FIXO_DIA*100:.1f}% do custo fixo de um dia")
    print(f"Pacote prudente B + C (mix 50%): por quarta +{comb_b:.2f} | por mes +{4*comb_b:.2f} | equivale a {comb_b/CUSTO_FIXO_DIA*100:.1f}% do custo fixo de um dia")
    completa = {}
    for f in (0.20, 0.40):
        rl = next(x for x in rolos if abs(x["fracao"] - f) < 1e-9 and abs(x["aumento_volume"] - 0.20) < 1e-9)
        completa[f"f{int(f*100)}_g20"] = a_prud + rl["dif_sobra"]
        print(f"Tabela completa (A prudente, mix 50% + rolos baratos a 1,49 em {f*100:.0f}% das pecas com +20% de volume): "
              f"por quarta {a_prud + rl['dif_sobra']:+.2f} | por mes {4*(a_prud + rl['dif_sobra']):+.2f}")
    la = pega(l_a, 0.50, 0.30, 0.10)
    lb = pega(l_b, 0.50, 0.15, 0.10)
    cartao = {"A_prudente": 0.02 * la["dif_receita"], "B_prudente": 0.02 * lb["dif_receita"],
              "bebidas_10pp": 0.02 * g10["receita"]}
    print(f"Taxa de cartao (2%) sobre a receita a mais, NAO descontada da sobra: A prudente {cartao['A_prudente']:.2f} "
          f"(receita {la['dif_receita']:+.2f}) | B prudente {cartao['B_prudente']:.2f} (receita {lb['dif_receita']:+.2f}) | "
          f"bebidas +10 p.p. {cartao['bebidas_10pp']:.2f}")
    R["tabela_completa_com_rolos_149"] = completa
    R["taxa_cartao_nao_descontada"] = cartao
    R["projecao"] = {"cenarios": proj,
                     "bebidas_10pp_quarta": g10["sobra"], "bebidas_10pp_mes": 4 * g10["sobra"],
                     "bebidas_10pp_quarta_lata": g10_lata["sobra"], "bebidas_10pp_mes_lata": 4 * g10_lata["sobra"],
                     "bebidas_20pp_quarta": g20["sobra"], "bebidas_20pp_mes": 4 * g20["sobra"],
                     "rolo_149_f40_g20_quarta": rolo_40_20["dif_sobra"], "rolo_149_f40_g20_mes": 4 * rolo_40_20["dif_sobra"],
                     "rolo_149_melhor_quarta": melhor_rolo["dif_sobra"], "rolo_149_pior_quarta": pior_rolo["dif_sobra"],
                     "pacote_A_C_quarta": comb_a, "pacote_A_C_mes": 4 * comb_a,
                     "pacote_B_C_quarta": comb_b, "pacote_B_C_mes": 4 * comb_b,
                     "pacote_A_C_pct_custo_fixo_dia": comb_a / CUSTO_FIXO_DIA,
                     "pacote_B_C_pct_custo_fixo_dia": comb_b / CUSTO_FIXO_DIA}

    def arredonda(x):
        if isinstance(x, float):
            return round(x, 4)
        if isinstance(x, dict):
            return {k: arredonda(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [arredonda(v) for v in x]
        return x

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(arredonda(R), fh, ensure_ascii=False, indent=1)
    print(f"\nresultado gravado em {out_path}")


if __name__ == "__main__":
    main()
