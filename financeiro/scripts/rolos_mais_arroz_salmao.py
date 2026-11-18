"""Simulação: aumentar o arroz e o salmão de cada rolo de Hossomaki, Hot Roll e Uramaki (pedido do Emerson em 17/11/2026).
Custo de hoje = ficha técnica do ALIV (somente leitura; nada é gravado). Custo novo = ficha + gramas a mais.
  - arroz: pelo custo do arroz pronto na ficha;
  - salmão cru: as fichas guardam o peso bruto (limpo ÷ rendimento medido das caixas), então 20 g limpos = 20 ÷ 0,7134 g brutos;
  - salmão grelhado: pelo custo do "Peixe grelhado", com o hondashi na mesma proporção.
Rolo sem salmão recebe só o arroz. Rolo sem ficha não entra.
Uso: python3 rolos_mais_arroz_salmao.py [g de arroz, padrão 20] [g de salmão, padrão 20] [vendas_do_mes.json] [saida.json]
"""
import sys, os, json, ast, collections
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
G_ARROZ = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
G_SALMAO = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
VENDAS = sys.argv[3] if len(sys.argv) > 3 else None
SAIDA = sys.argv[4] if len(sys.argv) > 4 else None
ARROZ, SALMAO, GRELHADO, HONDASHI = 23639, 23889, 23638, 23640
REND = 86.918 / 121.844          # rendimento das 4 primeiras caixas, o que está gravado nas fichas (71,3%)
CATS = ("Hossomaki", "Hot Roll", "Uramaki")
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
full = api.get("/admin/api/menu/full_data"); out = []; vistos = set()
for c in full["categories"]:
    if c["name"] not in CATS: continue
    for p in c["products"]:
        if p["id"] in vistos or p["full_data"].get("category_id") != c["id"] or not p["is_active"]: continue
        vistos.add(p["id"]); f = api.get(f"/admin/menu/product/{p['id']}/recipes")
        x = {"id": p["id"], "nome": p["name"], "categoria": c["name"], "preco": p["price"], "custo": sum(l["total_cost"] for l in f), "linhas": len(f)}
        L = {l["ingredient_id"]: l for l in f}
        x["arroz_g"] = round(1000 * L[ARROZ]["quantity"]) if ARROZ in L else None
        d_arroz = L[ARROZ]["total_cost"] / L[ARROZ]["quantity"] * G_ARROZ / 1000 if ARROZ in L else 0.0
        d_salmao = 0.0; x["salmao"] = "—"; x["salmao_g"] = None
        if SALMAO in L:
            l = L[SALMAO]; x["salmao"] = "cru"; x["salmao_g"] = round(1000 * l["quantity"] * REND)
            d_salmao = l["total_cost"] / l["quantity"] * (G_SALMAO / 1000) / REND
        elif GRELHADO in L:
            l = L[GRELHADO]; x["salmao"] = "grelhado"; x["salmao_g"] = round(1000 * l["quantity"]); fator = (G_SALMAO / 1000) / l["quantity"]
            d_salmao = l["total_cost"] * fator + (L[HONDASHI]["total_cost"] * fator if HONDASHI in L else 0.0)
        x.update(d_arroz=d_arroz, d_salmao=d_salmao, novo=x["custo"] + d_arroz + d_salmao)
        out.append(x)
qtd = collections.Counter()
if VENDAS:
    for o in json.load(open(VENDAS)):
        if "CANCEL" in str(o.get("status", "")).upper(): continue
        it = o.get("items_json") or []
        if isinstance(it, str):
            try: it = ast.literal_eval(it)
            except Exception:
                try: it = json.loads(it)
                except Exception: it = []
        for i in it:
            if isinstance(i, dict): qtd[i.get("id") or i.get("product_id")] += float(i.get("quantity") or 1)
print(f"simulação: +{G_ARROZ:.0f} g de arroz e +{G_SALMAO:.0f} g de salmão por rolo | vendas: {VENDAS or 'não informado'}")
print(f"{'rolo':32s} {'preço':>6s} {'arroz':>9s} {'salmão':>14s} {'custo hoje':>10s} {'custo novo':>10s} {'dif':>6s} {'CMV hoje':>8s} {'CMV novo':>8s} {'vend/mês':>8s} {'a mais/mês':>10s}")
tot = collections.Counter()
for cat in CATS:
    print(f"-- {cat}")
    for x in sorted((x for x in out if x["categoria"] == cat), key=lambda x: (x["salmao"] == "—", x["nome"])):
        n = qtd.get(x["id"], 0)
        if not x["linhas"]: print(f"{x['nome'][:32]:32s} {x['preco']:6.2f}   sem ficha no ALIV — não dá para simular   {n:8.0f}"); tot["sem_ficha"] += n; continue
        dif = x["novo"] - x["custo"]; tot["mes"] += n * dif; tot["n"] += n; tot["com_salmao" if x["salmao"] != "—" else "sem_salmao"] += n * dif
        ar = f"{x['arroz_g']}→{x['arroz_g'] + G_ARROZ:.0f}" if x["arroz_g"] else "—"
        sa = f"{x['salmao_g']}→{x['salmao_g'] + G_SALMAO:.0f} {x['salmao']}" if x["salmao_g"] else "sem salmão"
        print(f"{x['nome'][:32]:32s} {x['preco']:6.2f} {ar:>9s} {sa:>14s} {x['custo']:10.2f} {x['novo']:10.2f} {dif:6.2f} {100*x['custo']/x['preco']:7.1f}% {100*x['novo']/x['preco']:7.1f}% {n:8.0f} {n*dif:10.2f}")
ex = next((x for x in out if x["salmao"] == "cru"), None); eg = next((x for x in out if x["salmao"] == "grelhado"), None)
ea = next((x for x in out if x["d_arroz"]), None)
print(f"\ncusto a mais por rolo: arroz R$ {ea['d_arroz'] if ea else 0:.3f} | salmão cru R$ {ex['d_salmao'] if ex else 0:.3f} | salmão grelhado R$ {eg['d_salmao'] if eg else 0:.3f}")
if VENDAS: print(f"vendidos como rolo no mês: {tot['n']:.0f} (+ {tot['sem_ficha']:.0f} de rolos sem ficha) | custo a mais no mês: R$ {tot['mes']:.2f} (com salmão R$ {tot['com_salmao']:.2f}; só arroz R$ {tot['sem_salmao']:.2f})")
if SAIDA: json.dump({"g_arroz": G_ARROZ, "g_salmao": G_SALMAO, "produtos": out, "vendas": {str(k): v for k, v in qtd.items() if k in vistos}}, open(SAIDA, "w"), ensure_ascii=False, indent=1)
