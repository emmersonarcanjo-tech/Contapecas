"""Peso bruto = limpo / rendimento, para o ingrediente ING. Autorizado pelo Emerson 10/11/2026."""
import sys, os, json, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
SALMAO, RENDIMENTO = int(os.environ["ING"]), float(os.environ["REND"])
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
def post_form(path, data):
    req = urllib.request.Request(BASE_URL + path, data=urllib.parse.urlencode(data).encode(), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"})
    return api._send(req)
def post_multi(path, data):
    b = uuid.uuid4().hex
    body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in data.items()) + f"--{b}--\r\n"
    req = urllib.request.Request(BASE_URL + path, data=body.encode(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"})
    return api._send(req)
modo, pids = sys.argv[1], [int(x) for x in sys.argv[2:]]
if modo == "custo":
    print(post_form("/admin/inventory/ingredient/quick-update", {"ing_id": SALMAO, "field": "cost", "value": "51.90"}))
    sys.exit()
for pid in pids:
    for r in api.get(f"/admin/menu/product/{pid}/recipes"):
        if r["ingredient_id"] != SALMAO: continue
        novo = round(r["quantity"] / RENDIMENTO, 4)
        if modo == "dry": print("DRY", pid, r["id"], r["quantity"], "->", novo); continue
        st, resp = post_multi(f"/admin/menu/recipe/{r['id']}/update_quantity", {"quantity": f"{novo}"})
        print(st, pid, r["id"], r["quantity"], "->", novo, str(resp)[:100])
