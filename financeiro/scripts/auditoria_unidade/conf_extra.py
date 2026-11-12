#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Conferencias extras (independentes do script principal), so leitura:
 A) Recalculo independente de cada porcao/peca de niguiri e Joy: soma(qtd x custo estoque)
    do ALIV dividido pelo custo de 1 unidade escrito "na mao" (formula direta).
 B) Combinados sob 3 hipoteses: H0 = pecas por unidade (certo);
    H1 = cada niguiri/joy do combinado contado com a ficha da PORCAO inteira (4x / 2x a mais);
    H2 = cada niguiri/joy contado com a unidade dividida de novo (1/4 e 1/2 = gramatura tratada como porcao).
 C) Ura Fila e Hot Fila (base dos combinados) x regras de rolo do gramaturas_sushi.json.

Uso: python3 -I conf_extra.py <aliv_fichas.json> <gramaturas_sushi.json>
"""
import json
import re
import sys
import unicodedata

R_SALMAO, R_ATUM = 0.7197, 0.60
SALMAO, ATUM, ARROZ, CC, GERG, CEB, KANI, SKIN, ALHO, ALGA, PANKO = (
    23889, 24147, 23639, 23907, 23641, 23642, 23871, 24151, 24150, 9443, 23882)


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().lower()


def main():
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    gram = json.load(open(sys.argv[2], encoding="utf-8"))
    c = {e["id"]: e["custo_por_unidade"] for e in d["estoque"]}
    P = {norm(p["nome"]): p for p in d["produtos"]}

    kg_salmao_limpo = c[SALMAO] / R_SALMAO
    kg_atum_limpo = c[ATUM] / R_ATUM
    print("custo do kg LIMPO: salmao R$ %.4f | atum R$ %.4f" % (kg_salmao_limpo, kg_atum_limpo))

    # ---------------- A) custo de 1 unidade escrito na mao (R$), g limpos x R$/kg limpo
    arroz_g = c[ARROZ] / 1000
    cc_g = c[CC] / 1000
    gerg_g = c[GERG] / 1000
    ceb_g = c[CEB] / 100
    kani_g = c[KANI] / 250
    sal_g = kg_salmao_limpo / 1000
    atu_g = kg_atum_limpo / 1000
    UN = {
        "niguiri salmao": 20 * arroz_g + 12 * sal_g,
        "niguiri salmao selado": 20 * arroz_g + 12 * sal_g,
        "niguiri salmao selado c/ geleia de pimenta": 20 * arroz_g + 12 * sal_g,
        "niguiri atum": 20 * arroz_g + 12 * atu_g,
        "niguiri kani": 20 * arroz_g + 16 * kani_g,
        "niguiri skin": 20 * arroz_g + 10 * 0.0,
        "joy fila": 12 * arroz_g + (14 + 7) * sal_g + 4 * cc_g + 1 * ceb_g,
        "joy tili": 12 * arroz_g + (14 + 7) * sal_g + 4 * cc_g + 1 * ceb_g + 0.5 * gerg_g,
        "joy capao": 12 * arroz_g + (14 + 7) * sal_g + 4 * cc_g + 1 * 0.0,
        "joy alho poro": 12 * arroz_g + (14 + 7) * sal_g,
        "joy selado c/ geleia": 12 * arroz_g + (14 + 7) * sal_g,
        "joy atum": 12 * arroz_g + (14 + 7) * atu_g + 4 * cc_g + 1 * ceb_g,
        "joy camarao": 12 * arroz_g + 14 * sal_g + 4 * cc_g + 1 * ceb_g + 0.5 * gerg_g,
        "joy camarao s/ arroz": 14 * sal_g,
        "joy especial tili": (14 + 7) * sal_g + 4 * cc_g,
    }
    print()
    print("A) razao do custo gravado no ALIV sobre o custo de 1 unidade (formula direta)")
    print("   %-45s %9s %9s %7s %9s %7s" % ("produto", "1un esp", "porcao", "razao", "1 peca", "razao"))
    pior = 0.0
    for base, cu in sorted(UN.items()):
        n = 4 if base.startswith("niguiri") else 2
        pp = P[norm("%s ( 0%d un )" % (base, n))]
        p1 = P[norm("%s (1 peca)" % base)]
        soma_p = sum(l["quantidade"] * c[l["ingrediente_id"]] for l in pp["ficha"])
        soma_1 = sum(l["quantidade"] * c[l["ingrediente_id"]] for l in p1["ficha"])
        rp, r1 = soma_p / cu, soma_1 / cu
        pior = max(pior, abs(rp - n) / n, abs(r1 - 1))
        print("   %-45s %9.4f %9.4f %7.3f %9.4f %7.3f" % (base, cu, pp["custo_total"], rp, p1["custo_total"], r1))
    print("   maior desvio relativo da razao esperada (n na porcao, 1 na peca): %.4f%%" % (pior * 100))

    # ---------------- B) combinados sob 3 hipoteses
    def dic(p, div):
        return {l["ingrediente_id"]: l["quantidade"] / div for l in p["ficha"]}

    sash = dic(P["sashimi"], 1)
    ura = dic(P["ura fila ( 10 un )"], 10)
    hot = dic(P["hot fila ( 10 un )"], 10)
    nig_porc = dic(P["niguiri salmao ( 04 un )"], 1)
    joy_porc = dic(P["joy fila ( 02 un )"], 1)

    def custo(q):
        return sum(v * c[i] for i, v in q.items())

    def esc(q, k):
        return {i: v * k for i, v in q.items()}

    hip = {
        "H0 certo (por unidade)": {"niguiri": esc(nig_porc, 1 / 4), "joy": esc(joy_porc, 1 / 2)},
        "H1 porcao inteira por peca": {"niguiri": nig_porc, "joy": joy_porc},
        "H2 unidade dividida de novo": {"niguiri": esc(nig_porc, 1 / 16), "joy": esc(joy_porc, 1 / 4)},
    }
    print()
    print("B) combinados: custo gravado x hipoteses")
    print("   %-28s %9s %9s %9s %9s  %s" % ("combinado", "ALIV", "H0", "H1", "H2", "bate com"))
    for nome, p in P.items():
        if not nome.startswith("combinado"):
            continue
        itens = [(int(q), norm(w)) for q, w in re.findall(r"(\d+)\s+([^\W\d_]+)", p["descricao"], flags=re.UNICODE)]
        res = {}
        for h, base in hip.items():
            tot = 0.0
            for q, w in itens:
                if w.startswith("sash"):
                    tot += q * custo(sash)
                elif w.startswith("ura"):
                    tot += q * custo(ura)
                elif w.startswith("hot"):
                    tot += q * custo(hot)
                elif w.startswith("niguiri"):
                    tot += q * custo(base["niguiri"])
                elif w.startswith("joy"):
                    tot += q * custo(base["joy"])
                else:
                    raise SystemExit("termo nao reconhecido: " + w)
            res[h] = tot
        bate = [h for h, v in res.items() if abs(v - p["custo_total"]) <= 0.01]
        v = list(res.values())
        print("   %-28s %9.4f %9.4f %9.4f %9.4f  %s" % (p["nome"], p["custo_total"], v[0], v[1], v[2], ", ".join(bate) or "NENHUMA"))

    # ---------------- C) Ura Fila / Hot Fila x regras de rolo (gramaturas_sushi.json)
    def g(txt):
        m = re.match(r"\s*([\d.,]+)\s*g", txt)
        return float(m.group(1).replace(",", ".")) if m else None

    def regra(cat, ing):
        vals = [r["g"] for r in gram["regras"] if (cat in r["categorias"]) and norm(r["ingrediente"]) == ing]
        return vals[-1] if vals else None

    print()
    print("C) rolos base dos combinados x gramaturas_sushi.json (por rolo de 10)")
    it_ura = gram["itens"]["Ura Fila ( 10 Un )"]
    esp_ura = {
        ARROZ: g(regra("Uramaki", "arroz")) / 1000,
        SALMAO: g(it_ura["salmão"]) / R_SALMAO / 1000,
        CC: g(it_ura["cream cheese"]) / 1000,
        GERG: g(it_ura["gergelim"]) / 1000,
        CEB: g(it_ura["cebolinha"]) / 100,
        ALGA: 0.5 if "½" in regra("Uramaki", "alga") else None,
    }
    esp_hot = {
        ARROZ: g(regra("Hot Roll", "arroz")) / 1000,
        SALMAO: g(regra("Hot Roll", "salmao")) / R_SALMAO / 1000,
        CC: g(regra("Hot Roll", "cream cheese")) / 1000,
        ALGA: 1.0 if regra("Hot Roll", "alga").startswith("1") else None,
        PANKO: 20.0 / 1000,   # regra geral "panko 20 g"; estoque em pacote de 1 kg
    }
    for nome, esp in (("ura fila ( 10 un )", esp_ura), ("hot fila ( 10 un )", esp_hot)):
        p = P[nome]
        f = {l["ingrediente_id"]: l for l in p["ficha"]}
        print("   %s (custo ALIV %.4f)" % (p["nome"], p["custo_total"]))
        for i in sorted(set(f) | set(esp)):
            e = esp.get(i)
            a = f[i]["quantidade"] if i in f else None
            ok = (e is not None and a is not None and abs(e - a) <= max(0.01 * e, 0.0002))
            print("      %-45s esp %s | ALIV %s | %s" % (
                f[i]["ingrediente"] if i in f else i,
                "%.6f" % e if e is not None else "-", "%.6f" % a if a is not None else "AUSENTE",
                "ok" if ok else "VERIFICAR"))
        print("      custo esperado %.4f" % sum(v * c[i] for i, v in esp.items() if v is not None))


if __name__ == "__main__":
    main()
