#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auditoria das fichas gravadas no ALIV (aliv_fichas.json).

Recalcula DO ZERO, a partir do que o dono informou POR UNIDADE (BRIEF.md)
e das regras de custo, e compara com o que esta gravado no ALIV.

Uso: python3 -I auditoria_fichas.py <caminho/aliv_fichas.json>
Somente leitura. Nao acessa rede.
"""
import json
import re
import sys
import unicodedata
from collections import OrderedDict

# --------------------------------------------------------------------------
# 1) O QUE O DONO INFORMOU (POR UNIDADE) -- transcrito do BRIEF, nao do ALIV
# --------------------------------------------------------------------------
REND_SALMAO = 0.7197      # 45,992 kg limpos de 63,908 kg
REND_ATUM = 0.60          # perda de 40%
G_MACO_CEBOLINHA = 100.0  # maco de 100 g
G_PACOTE_KANI = 250.0     # pacote de 250 g

# ids do estoque do ALIV (chave de comparacao das linhas)
ID = {
    "alga": 9443, "alho_poro": 24150, "arroz": 23639, "atum": 24147,
    "cebolinha": 23642, "cream_cheese": 23907, "panko": 23882,
    "gergelim": 23641, "kani": 23871, "salmao": 23889, "skin": 24151,
}
NOME_ID = {v: k for k, v in ID.items()}

# custo do estoque segundo o BRIEF (confere contra o json)
CUSTO_BRIEF = {
    "salmao": 51.90, "atum": 25.00, "arroz": 5.35, "cream_cheese": 51.395,
    "gergelim": 40.0, "cebolinha": 6.00, "kani": 8.00, "skin": 0.0,
    "alho_poro": 0.0,
}

PECAS = {"niguiri": 4, "joy": 2}

# gramas LIMPOS por unidade, por termo da descricao do produto
# (chave = como o termo aparece na descricao, ja normalizado)
REGRAS = {
    "niguiri": [
        (r"^arroz$", "arroz", 20.0),
        (r"^lamina de salmao", "salmao", 12.0),   # salmao, selado, selado c/ geleia
        (r"^lamina de atum", "atum", 12.0),
        (r"^lamina de kani", "kani", 16.0),
        (r"^neta skin", "skin", 10.0),
    ],
    "joy": [
        (r"^arroz$", "arroz", 12.0),
        (r"^lamina de salmao", "salmao", 14.0),
        (r"^lamina de atum", "atum", 14.0),
        (r"^tataki de salmao", "salmao", 7.0),    # inclui "c/ alho poro" e "selado c/ geleia"
        (r"^tataki de atum", "atum", 7.0),
        (r"^cream cheese$", "cream_cheese", 4.0),
        (r"^cebolinha$", "cebolinha", 1.0),
        (r"^alho poro$", "alho_poro", 1.0),
        # dono: "1 grama ... por ficha" -> lancado 1 g na PORCAO de 2 = 0,5 g/un (ponto em aberto)
        (r"^gergelim$", "gergelim", 0.5),
    ],
}
# termos da descricao cujo peso NAO foi informado pelo dono
NAO_INFORMADO = [r"^camarao", r"^limao$", r"^tare$", r"^alga$", r"^tataki de shimeji"]

TOL_Q_REL = 0.01
TOL_Q_ABS = 0.0002
TOL_RS = 0.01


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def qtd_estoque(ing, g_limpo):
    """gramas limpos por unidade -> quantidade na unidade do estoque do ALIV"""
    if ing == "salmao":
        return g_limpo / REND_SALMAO / 1000.0
    if ing == "atum":
        return g_limpo / REND_ATUM / 1000.0
    if ing == "cebolinha":
        return g_limpo / G_MACO_CEBOLINHA
    if ing == "kani":
        return g_limpo / G_PACOTE_KANI
    return g_limpo / 1000.0   # arroz, cream cheese, gergelim, skin, alho-poro (KG)


def termos(descricao):
    d = norm(descricao)
    partes = re.split(r"\s*,\s*|\s+e\s+", d)
    return [p.strip() for p in partes if p.strip()]


def ficha_unidade_esperada(familia, descricao):
    """Retorna (OrderedDict ing -> qtd estoque por unidade, gramas limpos, nao_informados, notas)"""
    q = OrderedDict()
    g = OrderedDict()
    faltam, notas = [], []
    for t in termos(descricao):
        achou = False
        for rx, ing, gramas in REGRAS[familia]:
            if re.search(rx, t):
                q[ing] = q.get(ing, 0.0) + qtd_estoque(ing, gramas)
                g[ing] = g.get(ing, 0.0) + gramas
                achou = True
                if "alho poro" in t and ing != "alho_poro":
                    notas.append("alho-poro dentro do tataki (sem peso separado informado)")
                if "geleia" in t:
                    notas.append("geleia de pimenta sem peso informado")
                break
        if not achou:
            if any(re.search(rx, t) for rx in NAO_INFORMADO):
                faltam.append(t)
            else:
                faltam.append(t + " (termo sem regra)")
    return q, g, faltam, notas


def dentro_tol_q(esp, enc):
    return abs(esp - enc) <= max(TOL_Q_REL * abs(esp), TOL_Q_ABS)


def main():
    caminho = sys.argv[1]
    dados = json.load(open(caminho, encoding="utf-8"))
    estoque = {e["id"]: e for e in dados["estoque"]}
    custo = {i: e["custo_por_unidade"] for i, e in estoque.items()}
    produtos = dados["produtos"]

    conferencias = 0
    erros = []          # divergencias
    obs = []            # pontos em aberto
    linhas_rel = []     # relatorio humano

    def reg_erro(onde, esperado, encontrado, explicacao, impacto=None):
        erros.append(OrderedDict(onde=onde, esperado=esperado, encontrado=encontrado,
                                 explicacao=explicacao, impacto_reais=impacto))

    # ---------------------------------------------------------------- estoque
    linhas_rel.append("== 0. CUSTO DO ESTOQUE (json x BRIEF) ==")
    for ing, c_brief in CUSTO_BRIEF.items():
        c_json = custo[ID[ing]]
        conferencias += 1
        ok = abs(c_json - c_brief) < 1e-9
        linhas_rel.append("  %-13s BRIEF %.4f | ALIV %.4f | %s" % (ing, c_brief, c_json, "ok" if ok else "DIVERGE"))
        if not ok:
            reg_erro("Estoque: " + ing, "R$ %.4f" % c_brief, "R$ %.4f" % c_json,
                     "custo do estoque no ALIV difere do informado no BRIEF")
    for i, e in estoque.items():
        if e["custo_por_unidade"] == 0:
            obs.append("Estoque com custo ZERO: %s (id %d, unidade %s)." % (e["nome"], i, e["unidade"]))

    # ------------------------------------------------- separa os produtos
    porcoes, pecas, outros = {}, {}, {}
    for p in produtos:
        n = norm(p["nome"])
        m = re.match(r"^(niguiri|joy) (.*?) \( 0([24]) un \)$", n)
        m1 = re.match(r"^(niguiri|joy) (.*?) \(1 peca\)$", n)
        if m:
            porcoes[(m.group(1), m.group(2))] = p
        elif m1:
            pecas[(m1.group(1), m1.group(2))] = p
        else:
            outros[n] = p

    tabela = []
    resumo5 = []   # classificacao por linha (pergunta 5)

    def compara_ficha(rotulo, p, esperado_q, fator, n_pecas):
        """compara ficha do ALIV (produto p) com esperado_q * fator. Devolve custo esperado."""
        nonlocal conferencias
        ficha = {l["ingrediente_id"]: l for l in p.get("ficha", [])}
        custo_esp_total = 0.0
        for ing, q_un in esperado_q.items():
            iid = ID[ing]
            q_esp = q_un * fator
            c_esp = q_esp * custo[iid]
            custo_esp_total += c_esp
            l = ficha.pop(iid, None)
            conferencias += 1
            if l is None:
                imp = c_esp / fator   # R$ por unidade vendida
                reg_erro("%s - %s" % (rotulo, estoque[iid]["nome"]),
                         "%.6f %s" % (q_esp, estoque[iid]["unidade"]), "linha ausente",
                         "ingrediente informado pelo dono nao esta na ficha", round(imp, 4))
                linhas_rel.append("    %-12s esp %.6f | ALIV AUSENTE" % (ing, q_esp))
                continue
            q_enc = l["quantidade"]
            razao = q_enc / q_un if q_un else float("nan")
            okq = dentro_tol_q(q_esp, q_enc)
            # custo da linha
            conferencias += 1
            okc = abs(c_esp - l["custo_linha"]) <= TOL_RS
            # consistencia interna: custo_linha = quantidade ALIV x custo estoque
            conferencias += 1
            oki = abs(q_enc * custo[iid] - l["custo_linha"]) <= 0.0002
            linhas_rel.append("    %-12s qtd esp %.6f | ALIV %.6f | razao ALIV/unidade %.3f (deve ser %d) | custo esp %.4f | ALIV %.4f | %s%s%s"
                              % (ing, q_esp, q_enc, razao, fator, c_esp, l["custo_linha"],
                                 "ok" if okq else "QTD DIVERGE", "" if okc else " CUSTO DIVERGE",
                                 "" if oki else " CUSTO_LINHA != QTD x ESTOQUE"))
            # classificacao da pergunta 5
            if abs(razao - fator) <= 0.01 * fator + 1e-9:
                cls = "correto"
            elif fator > 1 and abs(razao - 1) <= 0.02:
                cls = "UNIDADE USADA COMO PORCAO"
            elif abs(razao - fator * n_pecas) <= 0.02 * fator * n_pecas or abs(razao - 2 * fator) <= 0.02 * fator:
                cls = "MULTIPLICADO A MAIS"
            else:
                cls = "outro"
            resumo5.append((rotulo, ing, razao, fator, cls))
            if not okq:
                imp = (q_enc - q_esp) * custo[iid] / fator
                reg_erro("%s - %s" % (rotulo, estoque[iid]["nome"]),
                         "%.6f %s" % (q_esp, estoque[iid]["unidade"]),
                         "%.6f %s" % (q_enc, estoque[iid]["unidade"]),
                         "quantidade fora da tolerancia (razao ALIV/unidade = %.3f, deveria ser %d) -> %s" % (razao, fator, cls),
                         round(imp, 4))
            elif not okc:
                reg_erro("%s - %s (custo da linha)" % (rotulo, estoque[iid]["nome"]),
                         "R$ %.4f" % c_esp, "R$ %.4f" % l["custo_linha"],
                         "custo da linha fora da tolerancia de R$ 0,01", round((l["custo_linha"] - c_esp) / fator, 4))
            if not oki:
                reg_erro("%s - %s (consistencia)" % (rotulo, estoque[iid]["nome"]),
                         "R$ %.4f" % (q_enc * custo[iid]), "R$ %.4f" % l["custo_linha"],
                         "custo_linha nao bate com quantidade x custo do estoque")
        # linhas a mais no ALIV
        for iid, l in ficha.items():
            conferencias += 1
            reg_erro("%s - %s" % (rotulo, l["ingrediente"]), "sem linha (dono nao informou)",
                     "%.6f %s" % (l["quantidade"], l["unidade"]),
                     "linha na ficha sem gramatura informada pelo dono",
                     round(l["custo_linha"] / fator, 4))
            linhas_rel.append("    LINHA A MAIS no ALIV: %s %.6f" % (l["ingrediente"], l["quantidade"]))
        # custo total
        conferencias += 1
        soma_linhas = sum(l["custo_linha"] for l in p.get("ficha", []))
        okt = abs(custo_esp_total - p["custo_total"]) <= TOL_RS
        conferencias += 1
        oks = abs(soma_linhas - p["custo_total"]) <= 0.0002
        linhas_rel.append("    CUSTO TOTAL esp %.4f | ALIV %.4f | dif %+.4f | %s%s"
                          % (custo_esp_total, p["custo_total"], p["custo_total"] - custo_esp_total,
                             "ok" if okt else "DIVERGE", "" if oks else " (custo_total != soma das linhas)"))
        if not okt:
            reg_erro("%s (custo total)" % rotulo, "R$ %.4f" % custo_esp_total, "R$ %.4f" % p["custo_total"],
                     "custo total fora da tolerancia de R$ 0,01",
                     round((p["custo_total"] - custo_esp_total) / fator, 4))
        if not oks:
            reg_erro("%s (soma)" % rotulo, "R$ %.4f" % soma_linhas, "R$ %.4f" % p["custo_total"],
                     "custo_total nao e a soma das linhas")
        return custo_esp_total

    # ------------------------------------- 1/2/3: niguiri e Joy
    linhas_rel.append("")
    linhas_rel.append("== 1/2. NIGUIRI E JOY: unidade x porcao (esperado x ALIV) ==")
    for chave in sorted(porcoes.keys()):
        familia, base = chave
        n = PECAS[familia]
        pp = porcoes[chave]
        p1 = pecas.get(chave)
        q_un, g_un, faltam, notas = ficha_unidade_esperada(familia, pp["descricao"])
        linhas_rel.append("")
        linhas_rel.append("-- %s | porcao de %d | ativo=%s | preco R$ %.2f" % (pp["nome"], n, pp["ativo"], pp["preco"]))
        linhas_rel.append("   descricao: %s" % pp["descricao"])
        linhas_rel.append("   informado por unidade (g limpos): %s" % ", ".join("%s %g g" % (k, v) for k, v in g_un.items()))
        if faltam:
            linhas_rel.append("   NAO informado: %s" % ", ".join(faltam))
        custo_un_esp = sum(q * custo[ID[i]] for i, q in q_un.items())
        custo_porc_esp = custo_un_esp * n

        if not pp.get("ficha"):
            linhas_rel.append("   SEM FICHA no ALIV (custo_total %.4f)" % pp["custo_total"])
            obs.append("%s: produto %s, SEM ficha no ALIV (custo R$ 0,00). Pelo que o dono informou (sem o que falta: %s) "
                       "daria R$ %.4f por unidade / R$ %.4f na porcao."
                       % (pp["nome"], "ativo" if pp["ativo"] else "INATIVO", ", ".join(faltam) or "-", custo_un_esp, custo_porc_esp))
            tabela.append(OrderedDict(produto=pp["nome"], custo_unidade_esperado=round(custo_un_esp, 4),
                                      custo_unidade_aliv=None, custo_porcao_esperado=round(custo_porc_esp, 4),
                                      custo_porcao_aliv=pp["custo_total"]))
            continue

        linhas_rel.append("   PORCAO (unidade x %d):" % n)
        compara_ficha(pp["nome"], pp, q_un, n, n)
        custo_un_aliv = None
        if p1 is None:
            linhas_rel.append("   SEM produto '(1 peca)' no ALIV")
            obs.append("%s: nao existe produto '(1 peca)' correspondente." % pp["nome"])
        else:
            linhas_rel.append("   1 PECA (%s):" % p1["nome"])
            compara_ficha(p1["nome"], p1, q_un, 1, n)
            custo_un_aliv = p1["custo_total"]
            # 3) (1 peca) = porcao / n exatamente
            fp = {l["ingrediente_id"]: l for l in pp["ficha"]}
            f1 = {l["ingrediente_id"]: l for l in p1["ficha"]}
            conferencias += 1
            if set(fp) != set(f1):
                reg_erro("%s x %s" % (p1["nome"], pp["nome"]), "mesmos ingredientes",
                         "ingredientes diferentes: %s" % sorted(set(fp) ^ set(f1)),
                         "(1 peca) nao tem os mesmos ingredientes da porcao")
            maxdq = 0.0
            for iid in set(fp) & set(f1):
                conferencias += 1
                dq = abs(f1[iid]["quantidade"] - fp[iid]["quantidade"] / n)
                maxdq = max(maxdq, dq)
                if dq > 1e-6:
                    reg_erro("%s - %s" % (p1["nome"], f1[iid]["ingrediente"]),
                             "%.6f (porcao / %d)" % (fp[iid]["quantidade"] / n, n), "%.6f" % f1[iid]["quantidade"],
                             "(1 peca) nao e exatamente a porcao dividida",
                             round((f1[iid]["quantidade"] - fp[iid]["quantidade"] / n) * custo[iid], 4))
            conferencias += 1
            dc = abs(p1["custo_total"] - pp["custo_total"] / n)
            if dc > 0.0001:
                reg_erro("%s (custo)" % p1["nome"], "R$ %.4f (porcao / %d)" % (pp["custo_total"] / n, n),
                         "R$ %.4f" % p1["custo_total"], "custo da peca nao e o da porcao dividido",
                         round(p1["custo_total"] - pp["custo_total"] / n, 4))
            linhas_rel.append("   3) (1 peca) = porcao / %d ? maior dif. de quantidade %.7f | custo porcao/%d = %.5f x peca %.4f | %s"
                              % (n, maxdq, n, pp["custo_total"] / n, p1["custo_total"],
                                 "ok" if (maxdq <= 1e-6 and dc <= 0.0001) else "DIVERGE"))
        # razao de custo porcao / unidade (pergunta 5)
        conferencias += 1
        rz = pp["custo_total"] / custo_un_esp if custo_un_esp else float("nan")
        linhas_rel.append("   5) custo porcao ALIV / custo de 1 unidade esperado = %.3f (deve ser %d)" % (rz, n))
        tabela.append(OrderedDict(produto=pp["nome"], custo_unidade_esperado=round(custo_un_esp, 4),
                                  custo_unidade_aliv=custo_un_aliv, custo_porcao_esperado=round(custo_porc_esp, 4),
                                  custo_porcao_aliv=pp["custo_total"], razao_porcao_sobre_unidade=round(rz, 3),
                                  pecas=n))
        if faltam:
            obs.append("%s: ficha incompleta - sem peso informado para: %s. Custo real e MAIOR que o do ALIV."
                       % (pp["nome"], ", ".join(faltam)))
        for nt in sorted(set(notas)):
            obs.append("%s: %s." % (pp["nome"], nt))
        zeros = [estoque[ID[i]]["nome"] for i in q_un if custo[ID[i]] == 0]
        if zeros:
            obs.append("%s: leva %s, que esta com custo ZERO no estoque -> custo subestimado."
                       % (pp["nome"], ", ".join(zeros)))

    # pecas sem porcao correspondente
    for chave, p1 in pecas.items():
        if chave not in porcoes:
            obs.append("%s: produto de 1 peca sem porcao correspondente no arquivo." % p1["nome"])

    # ------------------------------------- 4: combinados
    linhas_rel.append("")
    linhas_rel.append("== 4. COMBINADOS (soma das pecas da descricao) ==")

    def por_peca(nome_norm, div):
        p = outros.get(nome_norm) or next(v for k, v in list(porcoes.items()) if False)
        return {l["ingrediente_id"]: l["quantidade"] / div for l in p["ficha"]}

    sashimi = outros["sashimi"]
    ura = outros["ura fila ( 10 un )"]
    hot = outros["hot fila ( 10 un )"]
    nig = porcoes[("niguiri", "salmao")]
    joyf = porcoes[("joy", "fila")]

    def dic(p, div):
        return {l["ingrediente_id"]: l["quantidade"] / div for l in p["ficha"]}

    # (a) fichas por peca ATUAIS do ALIV
    PECA_ALIV = {
        "sashimi": dic(sashimi, 1), "uramaki": dic(ura, 10), "niguiri": dic(nig, 4),
        "joy": dic(joyf, 2), "hot": dic(hot, 10),
    }
    # (b) do zero: sashimi/niguiri/joy pelas gramaturas do dono (sem arredondar); ura/hot do ALIV
    q_nig, _, _, _ = ficha_unidade_esperada("niguiri", nig["descricao"])
    q_joy, _, _, _ = ficha_unidade_esperada("joy", joyf["descricao"])
    PECA_ZERO = {
        "sashimi": {ID["salmao"]: qtd_estoque("salmao", 20.0)},
        "uramaki": dic(ura, 10),
        "niguiri": {ID[k]: v for k, v in q_nig.items()},
        "joy": {ID[k]: v for k, v in q_joy.items()},
        "hot": dic(hot, 10),
    }
    # confere a propria ficha do Sashimi (1 peca de 20 g limpos)
    linhas_rel.append("-- Sashimi (1 peca, 20 g limpos)")
    compara_ficha("Sashimi", sashimi, OrderedDict(salmao=qtd_estoque("salmao", 20.0)), 1, 1)

    def tipo(palavra):
        w = norm(palavra)
        if w.startswith("sash"):
            return "sashimi"
        if w.startswith("uramaki") or w.startswith("ura"):
            return "uramaki"
        if w.startswith("niguiri"):
            return "niguiri"
        if w.startswith("joy"):
            return "joy"
        if w.startswith("hot"):
            return "hot"
        return None

    combos_res = []
    for n_norm, p in outros.items():
        if not n_norm.startswith("combinado"):
            continue
        itens = []
        for qtd, palavra in re.findall(r"(\d+)\s+([^\W\d_]+)", p["descricao"], flags=re.UNICODE):
            t = tipo(palavra)
            if t is None:
                reg_erro(p["nome"], "peca reconhecida", palavra, "termo da descricao do combinado nao reconhecido")
                continue
            itens.append((int(qtd), t))
        total_pecas = sum(q for q, _ in itens)
        n_nome = int(re.search(r"(\d+) pecas", n_norm).group(1))
        conferencias += 1
        linhas_rel.append("")
        linhas_rel.append("-- %s | descricao: %s" % (p["nome"], p["descricao"]))
        linhas_rel.append("   pecas lidas: %s = %d (nome diz %d) %s"
                          % (" + ".join("%d %s" % it for it in itens), total_pecas, n_nome,
                             "ok" if total_pecas == n_nome else "DIVERGE"))
        if total_pecas != n_nome:
            reg_erro(p["nome"], "%d pecas" % n_nome, "%d pecas na descricao" % total_pecas,
                     "soma das pecas da descricao difere do nome")
        ficha = {l["ingrediente_id"]: l for l in p["ficha"]}
        res = {}
        for rot, base in (("ALIV-pecas-atuais", PECA_ALIV), ("do-zero", PECA_ZERO)):
            soma = {}
            for q, t in itens:
                for iid, v in base[t].items():
                    soma[iid] = soma.get(iid, 0.0) + q * v
            ctot = sum(v * custo[iid] for iid, v in soma.items())
            res[rot] = (soma, ctot)
        soma_a, ctot_a = res["ALIV-pecas-atuais"]
        soma_z, ctot_z = res["do-zero"]
        for iid in sorted(set(soma_a) | set(ficha)):
            conferencias += 1
            esp = soma_a.get(iid)
            l = ficha.get(iid)
            nome_i = estoque[iid]["nome"]
            if esp is None:
                reg_erro("%s - %s" % (p["nome"], nome_i), "sem linha", "%.6f" % l["quantidade"],
                         "linha no combinado que nao vem de nenhuma peca da descricao", round(l["custo_linha"], 4))
                continue
            if l is None:
                reg_erro("%s - %s" % (p["nome"], nome_i), "%.6f" % esp, "linha ausente",
                         "ingrediente das pecas nao esta na ficha do combinado", round(esp * custo[iid], 4))
                continue
            okq = dentro_tol_q(esp, l["quantidade"])
            conferencias += 1
            okc = abs(esp * custo[iid] - l["custo_linha"]) <= TOL_RS
            linhas_rel.append("    %-12s soma pecas ALIV %.6f | do zero %.6f | combinado ALIV %.6f | custo esp %.4f | ALIV %.4f | %s%s"
                              % (NOME_ID.get(iid, str(iid)), esp, soma_z.get(iid, 0.0), l["quantidade"],
                                 esp * custo[iid], l["custo_linha"], "ok" if okq else "QTD DIVERGE",
                                 "" if okc else " CUSTO DIVERGE"))
            if not okq:
                reg_erro("%s - %s" % (p["nome"], nome_i), "%.6f" % esp, "%.6f" % l["quantidade"],
                         "quantidade do combinado difere da soma das pecas",
                         round((l["quantidade"] - esp) * custo[iid], 4))
            elif not okc:
                reg_erro("%s - %s (custo)" % (p["nome"], nome_i), "R$ %.4f" % (esp * custo[iid]),
                         "R$ %.4f" % l["custo_linha"], "custo da linha do combinado fora da tolerancia",
                         round(l["custo_linha"] - esp * custo[iid], 4))
        conferencias += 2
        okt = abs(ctot_a - p["custo_total"]) <= TOL_RS
        soma_l = sum(l["custo_linha"] for l in p["ficha"])
        oks = abs(soma_l - p["custo_total"]) <= 0.0002
        linhas_rel.append("    CUSTO TOTAL: soma pecas ALIV %.4f | do zero (gramaturas do dono) %.4f | combinado ALIV %.4f | dif %+.4f / %+.4f | %s%s"
                          % (ctot_a, ctot_z, p["custo_total"], p["custo_total"] - ctot_a, p["custo_total"] - ctot_z,
                             "ok" if okt else "DIVERGE", "" if oks else " (custo_total != soma das linhas)"))
        if not okt:
            reg_erro("%s (custo total)" % p["nome"], "R$ %.4f" % ctot_a, "R$ %.4f" % p["custo_total"],
                     "custo do combinado difere da soma das pecas atuais", round(p["custo_total"] - ctot_a, 4))
        if not oks:
            reg_erro("%s (soma)" % p["nome"], "R$ %.4f" % soma_l, "R$ %.4f" % p["custo_total"],
                     "custo_total do combinado nao e a soma das linhas")
        combos_res.append(OrderedDict(produto=p["nome"], pecas=total_pecas, preco=p["preco"],
                                      custo_aliv=p["custo_total"], custo_soma_pecas_aliv=round(ctot_a, 4),
                                      custo_do_zero=round(ctot_z, 4),
                                      dif_aliv_menos_do_zero=round(p["custo_total"] - ctot_z, 4)))

    # ------------------------------------- outros produtos sem ficha
    for n_norm, p in outros.items():
        if not p.get("ficha"):
            obs.append("%s: %s, SEM ficha no ALIV (custo_total R$ %.2f, preco R$ %.2f)."
                       % (p["nome"], "ativo" if p["ativo"] else "INATIVO", p["custo_total"], p["preco"]))

    # ------------------------------------- 5: resposta objetiva
    linhas_rel.append("")
    linhas_rel.append("== 5. GRAMATURA DA UNIDADE USADA COMO PORCAO, OU MULTIPLICADA A MAIS? ==")
    cont = {}
    for rot, ing, razao, fator, cls in resumo5:
        cont[cls] = cont.get(cls, 0) + 1
        if cls != "correto":
            linhas_rel.append("   %s | %s | razao %.3f (deveria %d) -> %s" % (rot, ing, razao, fator, cls))
    linhas_rel.append("   linhas classificadas: %s" % json.dumps(cont, ensure_ascii=False))
    linhas_rel.append("   cenarios (custo da PORCAO): ALIV x certo (unidade x n) x errado-A (gramatura = porcao inteira) x errado-B (multiplicado 2x a mais)")
    for t in tabela:
        if t.get("custo_unidade_aliv") is None and not t.get("razao_porcao_sobre_unidade"):
            continue
        n = t["pecas"]
        linhas_rel.append("   %-55s ALIV %.4f | certo %.4f | errado-A %.4f | errado-B %.4f | razao %.3f"
                          % (t["produto"], t["custo_porcao_aliv"], t["custo_porcao_esperado"],
                             t["custo_unidade_esperado"], t["custo_porcao_esperado"] * 2,
                             t["razao_porcao_sobre_unidade"]))

    # gergelim: ponto em aberto (1 g na porcao x 1 g por unidade)
    linhas_rel.append("")
    linhas_rel.append("== PONTO EM ABERTO: gergelim do Joy ==")
    c_g = custo[ID["gergelim"]]
    for chave, pp in sorted(porcoes.items()):
        l = next((x for x in pp.get("ficha", []) if x["ingrediente_id"] == ID["gergelim"]), None)
        if l:
            n = PECAS[chave[0]]
            g_porc = l["quantidade"] * 1000
            dif_un = (1.0 - g_porc / n) / 1000.0 * c_g
            linhas_rel.append("   %s: gergelim no ALIV %.1f g na porcao = %.2f g por unidade. Se o 1 g for POR UNIDADE: +R$ %.4f por unidade, +R$ %.4f na porcao (custo iria de %.4f para %.4f)."
                              % (pp["nome"], g_porc, g_porc / n, dif_un, dif_un * n, pp["custo_total"], pp["custo_total"] + dif_un * n))
            obs.append("%s: gergelim lancado %.1f g na PORCAO (%.2f g por unidade). E a UNICA linha em que um valor ditado foi tratado como da porcao inteira. "
                       "Se o 1 g for por unidade, faltam R$ %.4f por unidade (R$ %.4f na porcao: de R$ %.4f para R$ %.4f)."
                       % (pp["nome"], g_porc, g_porc / n, dif_un, dif_un * n, pp["custo_total"], pp["custo_total"] + dif_un * n))

    # Joy especial Tili sem arroz
    jet = porcoes.get(("joy", "especial tili"))
    if jet and not any(l["ingrediente_id"] == ID["arroz"] for l in jet["ficha"]):
        c_arroz = qtd_estoque("arroz", 12.0) * custo[ID["arroz"]]
        obs.append("%s: a descricao e a ficha NAO tem arroz. Se a peca levar os 12 g de arroz dos outros Joy, faltam R$ %.4f por unidade (R$ %.4f na porcao)."
                   % (jet["nome"], c_arroz, c_arroz * 2))
        linhas_rel.append("   Joy especial Tili sem arroz: +R$ %.4f/un se levar 12 g" % c_arroz)

    print("\n".join(linhas_rel))
    print()
    print("== RESULTADO (JSON) ==")
    saida = OrderedDict(
        produtos_no_arquivo=len(produtos),
        porcoes_niguiri_joy=len(porcoes),
        produtos_1_peca_niguiri_joy=len(pecas),
        combinados=len(combos_res),
        conferencias=conferencias,
        n_erros=len(erros),
        erros=erros,
        tabela=tabela,
        combinados_res=combos_res,
        classificacao_linhas=cont,
        observacoes=obs,
    )
    print(json.dumps(saida, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
