"""Acarajapa (32379) com recheio: 3 kg arroz, 1 kg tilápia grelhada (≈1,43 kg crua), 1 kg salmão limpo (÷0,7247 inteiro),
400 g cream cheese, 50 g cebolinha, 30 g hondashi, 20 g sriracha, 30 g gergelim → 5,53 kg → 184,3 bolinhos de 30 g."""
import sys, os, json, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
PID, N = 32379, 5530 / 30
ALVO = {23639: 3.0 / N, 24165: (1 / 0.70) / N, 23889: (1 / (25.330 / 34.954)) / N, 23907: 0.4 / N,
        23642: 0.5 / N, 23640: (30 / 500) / N, 23898: (20 / 500) / N, 23641: 0.030 / N}
def send(path, method, data, multipart=False):
    if multipart:
        b = uuid.uuid4().hex
        body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in data.items()) + f"--{b}--\r\n"
        h = {"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"}; body = body.encode()
    else:
        body = urllib.parse.urlencode(data).encode(); h = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}
    return api._send(urllib.request.Request(BASE_URL + path, data=body, method=method, headers=h))
antes = api.get(f"/admin/menu/product/{PID}/recipes"); json.dump(antes, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
atuais = {r["ingredient_id"]: r for r in antes}
for iid, r in atuais.items():
    if iid in ALVO: print("ajusta", r["ingredient_raw_name"], send(f"/admin/menu/recipe/{r['id']}/update_quantity", "POST", {"quantity": f"{ALVO[iid]:.6f}"}, True)[0])
    else: print("remove", r["ingredient_raw_name"], send(f"/admin/menu/recipe/{r['id']}", "DELETE", None)[0])
for iid, q in ALVO.items():
    if iid not in atuais: print("inclui", iid, send("/admin/menu/recipe/save", "POST", {"product_id": PID, "ingredient_id": iid, "quantity": f"{q:.6f}"})[0])
d = api.get(f"/admin/menu/product/{PID}/recipes")
for x in d: print("  ", x["ingredient_raw_name"], x["quantity"], round(x["total_cost"], 4))
print("linhas", len(d), "custo/bolinho", round(sum(x["total_cost"] for x in d), 3))
