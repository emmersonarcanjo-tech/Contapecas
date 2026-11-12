"""Leitura (somente GET) de todas as linhas de salmão (ingrediente 23889) nas fichas do ALIV."""
import sys, os, json
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
SAL = 23889
full = api.get("/admin/api/menu/full_data"); out = []; vistos = set(); nprod = 0
for c in full["categories"]:
    for p in c["products"]:
        if p["id"] in vistos: continue
        vistos.add(p["id"]); nprod += 1
        try: rec = api.get(f"/admin/menu/product/{p['id']}/recipes")
        except Exception as e: print("erro", p["id"], e); continue
        if not rec: continue
        tot = round(sum(x["total_cost"] for x in rec), 4)
        for r in rec:
            if r["ingredient_id"] == SAL:
                out.append({"product_id": p["id"], "produto": p["name"], "categoria": c["name"], "preco": p.get("price"),
                            "recipe_id": r["id"], "quantity": r["quantity"], "custo_linha": r["total_cost"], "custo_ficha": tot,
                            "linhas_na_ficha": len(rec)})
ing = [i for i in api.get("/admin/inventory/api/ingredients")["ingredients"] if i["id"] == SAL] if True else []
# Itens produzidos (ficha por unidade) também podem levar salmão: este script NÃO grava neles — só avisa.
itens = []
for i in api.get("/admin/inventory/api/ingredients")["ingredients"]:
    if i.get("is_recipe") and SAL in (i.get("recipe_base_ids") or []):
        rec = api.get(f"/admin/inventory/ingredient/{i['id']}/recipe")
        itens.append({"item_id": i["id"], "item": i["name"], "linhas": [l for l in rec if "salm" in l["child_name"].lower()]})
if itens:
    print("ATENÇÃO:", len(itens), "item(ns) produzido(s) com salmão na receita, fora deste plano (ajustar pela rota recipe-item/{id}/update-qty):")
    for x in itens: print("   ", x["item"], [(l["id"], l["qty"]) for l in x["linhas"]])
json.dump({"linhas": out, "estoque_salmao": ing, "itens_produzidos_com_salmao": itens}, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print("produtos lidos", nprod, "| linhas de salmão", len(out), "| produtos com salmão", len({x["product_id"] for x in out}))
print("estoque:", [(i.get("name"), i.get("cost"), i.get("unit")) for i in ing])
