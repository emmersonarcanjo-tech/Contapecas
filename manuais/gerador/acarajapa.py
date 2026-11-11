"""Ficha da Acarajapa (produto 32379) por unidade de 30 g, a partir da receita de 4,13 kg. Autorizado pelo Emerson."""
import sys, os, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
f = 30 / 4130  # fração da receita por bolinho
LINHAS = [(23639, 3.0 * f), (23638, 1.0 * f), (23642, 0.5 * f), (23640, 30 / 500 * f), (23641, 0.030 * f)]
atuais = {r["ingredient_id"] for r in api.get("/admin/menu/product/32379/recipes")}
for iid, q in LINHAS:
    if iid in atuais: print("já existe", iid); continue
    req = urllib.request.Request(BASE_URL + "/admin/menu/recipe/save", method="POST",
        data=urllib.parse.urlencode({"product_id": 32379, "ingredient_id": iid, "quantity": f"{q:.6f}"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"})
    print(iid, round(q, 6), api._send(req)[0])
r = api.get("/admin/menu/product/32379/recipes")
for x in r: print(" ", x["ingredient_raw_name"], x["quantity"], round(x["total_cost"], 4))
print("linhas", len(r), "custo", round(sum(x["total_cost"] for x in r), 2))
