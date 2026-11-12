"""Ficha técnica por UNIDADE de niguiri e Joy: produtos "(1 peça)" recebem a ficha da porção dividida pelo nº de peças
(niguiri ÷ 4, Joy ÷ 2). Pedido do Emerson em 12/11/2026. Uso: python3 unidade_fichas.py [--dry]"""
import sys, os, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
DRY = "--dry" in sys.argv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
PARES = [  # (produto de 1 peça, porção de origem, peças da porção)
    (30114, 11650, 4), (30115, 11645, 4), (30116, 11646, 4), (30117, 11648, 4), (30118, 11649, 4), (30119, 11647, 4),
    (30120, 11632, 2), (30121, 11637, 2), (30122, 11640, 2), (30123, 11641, 2), (30124, 11631, 2), (30125, 11635, 2),
    (30126, 11636, 2), (30127, 11639, 2), (30128, 11638, 2)]
nomes = {p["id"]: p["name"] for c in api.get("/admin/api/menu/full_data")["categories"] for p in c["products"]}
def post(path, data, multipart=False):
    if multipart:
        b = uuid.uuid4().hex
        body = ("".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in data.items()) + f"--{b}--\r\n").encode()
        h = {"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"}
    else:
        body = urllib.parse.urlencode(data).encode(); h = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}
    return api._send(urllib.request.Request(BASE_URL + path, data=body, method="POST", headers=h))
erros = 0
for uid, pid, n in PARES:
    origem = api.get(f"/admin/menu/product/{pid}/recipes")
    atuais = {r["ingredient_id"]: r for r in api.get(f"/admin/menu/product/{uid}/recipes")}
    for r in origem:
        q = round(r["quantity"] / n, 6)
        if DRY: continue
        if r["ingredient_id"] in atuais:
            st, _ = post(f"/admin/menu/recipe/{atuais[r['ingredient_id']]['id']}/update_quantity", {"quantity": f"{q:.6f}"}, True)
        else:
            st, _ = post("/admin/menu/recipe/save", {"product_id": uid, "ingredient_id": r["ingredient_id"], "quantity": f"{q:.6f}"})
        if st != 200: erros += 1; print("ERRO", uid, r["ingredient_id"], st)
    d = api.get(f"/admin/menu/product/{uid}/recipes")
    co = sum(x["total_cost"] for x in origem)
    linhas = "; ".join(f"{x['ingredient_raw_name'][:18]} {x['quantity']}" for x in (d if not DRY else []))
    print(f"{nomes.get(uid, uid)[:46]:46} ← {nomes.get(pid, pid)[:30]:30} ÷{n} | porção {co:.2f} → esperado {co/n:.3f} | gravado {sum(x['total_cost'] for x in d):.3f} ({len(d)} linhas) {linhas}")
print("erros:", erros)
