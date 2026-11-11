"""Troca a ficha da Acarajapa (32379) pela receita do Emerson (11/11/2026): 3 kg arroz, 1 kg tilápia crua (≈ 0,7 kg grelhada),
50 g cebolinha, 30 g hondashi, 20 g sriracha, 30 g gergelim → ≈ 3,83 kg → 127,67 bolinhos de 30 g. Sem cream cheese."""
import sys, os, json, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
PID, N = 32379, 3830 / 30
ALVO = {23639: 3.0 / N, 24165: 1.0 / N, 23642: 0.5 / N, 23640: (30 / 500) / N, 23898: (20 / 500) / N, 23641: 0.030 / N}
def send(path, method, data=None, multipart=False):
    if multipart:
        b = uuid.uuid4().hex
        body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in data.items()) + f"--{b}--\r\n"
        h = {"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"}; body = body.encode()
    else:
        body = urllib.parse.urlencode(data).encode() if data else None
        h = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}
    return api._send(urllib.request.Request(BASE_URL + path, data=body, method=method, headers=h))
antes = api.get(f"/admin/menu/product/{PID}/recipes")
json.dump(antes, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
atuais = {r["ingredient_id"]: r for r in antes}
for iid, r in atuais.items():
    if iid not in ALVO:
        print("remove", r["ingredient_raw_name"], send(f"/admin/menu/recipe/{r['id']}", "DELETE")[0])
    else:
        print("ajusta", r["ingredient_raw_name"], r["quantity"], "->", round(ALVO[iid], 6),
              send(f"/admin/menu/recipe/{r['id']}/update_quantity", "POST", {"quantity": f"{ALVO[iid]:.6f}"}, multipart=True)[0])
for iid, q in ALVO.items():
    if iid not in atuais:
        print("inclui", iid, round(q, 6), send("/admin/menu/recipe/save", "POST", {"product_id": PID, "ingredient_id": iid, "quantity": f"{q:.6f}"})[0])
depois = api.get(f"/admin/menu/product/{PID}/recipes")
for x in depois: print("  ", x["ingredient_raw_name"], x["quantity"], round(x["total_cost"], 4))
print("linhas", len(depois), "custo", round(sum(x["total_cost"] for x in depois), 3))
