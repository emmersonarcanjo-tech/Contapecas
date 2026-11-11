"""Salmão: rendimento medido 72,47% (caixa 11/11/2026). Ajusta linhas de salmão (23889) de 0,70 para 0,7247. Autorizado pelo Emerson."""
import sys, os, json, uuid, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
SAL, VELHO, NOVO = 23889, 0.70, 25.330 / 34.954
conf = json.load(open(sys.argv[1])); pids = sorted({x[2] for x in conf})
log = []
for pid in pids:
    for r in api.get(f"/admin/menu/product/{pid}/recipes"):
        if r["ingredient_id"] != SAL: continue
        q = round(r["quantity"] * VELHO / NOVO, 4); b = uuid.uuid4().hex
        body = f'--{b}\r\nContent-Disposition: form-data; name="quantity"\r\n\r\n{q}\r\n--{b}--\r\n'.encode()
        st, _ = api._send(urllib.request.Request(BASE_URL + f"/admin/menu/recipe/{r['id']}/update_quantity", data=body, method="POST",
                          headers={"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"}))
        log.append((pid, r["quantity"], q, st))
json.dump(log, open(sys.argv[2], "w"))
print("linhas", len(log), "erros", [x for x in log if x[3] != 200])
for pid, nome in ((11660, "Uramaki Fila"), (11669, "Hosso Salmão"), (11646, "Niguiri Salmão"), (11632, "Joy Fila"), (30757, "Sashimi"), (11684, "Temaki Filadélfia")):
    r = api.get(f"/admin/menu/product/{pid}/recipes")
    print(nome, round(sum(x["total_cost"] for x in r), 2), [x["quantity"] for x in r if x["ingredient_id"] == SAL])
