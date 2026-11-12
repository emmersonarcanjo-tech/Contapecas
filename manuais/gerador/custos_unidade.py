"""Lê do ALIV (somente leitura) o custo de 1 unidade de cada niguiri/Joy, linha por linha, e grava manuais/custos_unidade.json.
Se o produto "(1 peça)" já aponta para o item produzido "X (unidade)", lê a receita do item; senão, lê as linhas do produto.
Uso: python3 custos_unidade.py <plano_unidade.json> <saida.json>"""
import sys, os, json
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
plano = json.load(open(sys.argv[1]))
inv = {i["id"]: i for i in api.get("/admin/inventory/api/ingredients")["ingredients"]}
por_nome = {i["name"]: i for i in inv.values()}
out = {}
for x in plano:
    peca = api.get(f"/admin/menu/product/{x['produto_peca']['id']}/recipes")
    porcao = api.get(f"/admin/menu/product/{x['produto_porcao']['id']}/recipes")
    item = por_nome.get(x["item"]); ligado = bool(item) and len(peca) == 1 and peca[0]["ingredient_id"] == item["id"]
    if ligado:
        linhas = [{"ingrediente": l["child_name"], "quantidade": l["qty"], "unidade": l["unit"], "custo": round(l["qty"] * l["unit_cost"] / (l.get("factor") or 1), 6)}
                  for l in api.get(f"/admin/inventory/ingredient/{item['id']}/recipe")]
    else:
        linhas = [{"ingrediente": l.get("ingredient_raw_name") or l.get("ingredient_name"), "quantidade": l["quantity"], "unidade": l.get("ingredient_unit"), "custo": round(l["total_cost"], 6)} for l in peca]
    out[x["produto_porcao"]["nome"]] = {"n": x["pecas_na_porcao"], "item_aliv": x["item"] if ligado else None, "por_unidade_no_aliv": ligado,
        "custo_unidade": round(sum(l["total_cost"] for l in peca), 6), "custo_porcao": round(sum(l["total_cost"] for l in porcao), 6),
        "preco_porcao": x["produto_porcao"]["preco"], "preco_peca": x["produto_peca"]["preco"], "linhas": linhas}
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
for k, v in out.items():
    s = sum(l["custo"] for l in v["linhas"])
    print(f"{k[:44]:44s} un R$ {v['custo_unidade']:.4f} (soma linhas {s:.4f}) | porção {v['n']}× R$ {v['custo_porcao']:.4f} | por unidade no ALIV: {v['por_unidade_no_aliv']}")
