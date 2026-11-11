"""Salmão: ajusta fichas do rendimento da caixa 1 (72,47%) para a média das 2 caixas (71,97%). Autorizado pelo Emerson."""
import sys, os, json, uuid, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
SAL, VELHO, NOVO = 23889, 25.330 / 34.954, (25.330 + 20.662) / (34.954 + 28.954)
nomes = json.load(open("/workspace/Contapecas/manuais/custos_aliv.json"))
full = api.get("/admin/api/menu/full_data")
pids = sorted({p["id"] for c in full["categories"] for p in c["products"] if p["name"] in nomes})
log = []
for pid in pids:
    for r in api.get(f"/admin/menu/product/{pid}/recipes"):
        if r["ingredient_id"] != SAL: continue
        q = round(r["quantity"] * VELHO / NOVO, 4); b = uuid.uuid4().hex
        body = f'--{b}\r\nContent-Disposition: form-data; name="quantity"\r\n\r\n{q}\r\n--{b}--\r\n'.encode()
        st, _ = api._send(urllib.request.Request(BASE_URL + f"/admin/menu/recipe/{r['id']}/update_quantity", data=body, method="POST",
                          headers={"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"}))
        log.append((pid, r["quantity"], q, st))
print("rendimento médio", round(NOVO, 4), "linhas", len(log), "erros", [x for x in log if x[3] != 200])
