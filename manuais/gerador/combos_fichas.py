"""Fichas dos combinados = soma dos ingredientes das peças (fichas por peça já no ALIV). Autorizado pelo Emerson 11/11/2026."""
import sys, os, json, re, urllib.parse, urllib.request
from collections import defaultdict
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
DRY = "--dry" in sys.argv
PECA = {"sashimi": (30757, 1), "uramaki": (11660, 10), "niguiri": (11646, 4), "joy": (11632, 2), "hot": (11672, 10)}
por_peca = {}
for k, (pid, n) in PECA.items():
    por_peca[k] = {r["ingredient_id"]: r["quantity"] / n for r in api.get(f"/admin/menu/product/{pid}/recipes")}
full = api.get("/admin/api/menu/full_data")
prods = {p["id"]: p for c in full["categories"] for p in c["products"]}
COMBOS = [11697, 11698, 11699, 11700, 11701, 11702, 11703, 11704]
out = []
for cid in COMBOS:
    p = prods[cid]; desc = (p["full_data"].get("description") or "").lower().replace("sashumi", "sashimi")
    soma = defaultdict(float); comp = []
    for q, nome in re.findall(r"(\d+)\s+([a-zà-ú ]+)", desc):
        k = next((k for k in PECA if k in nome), None)
        if not k: print("??", cid, nome); continue
        comp.append(f"{q} {k}")
        for iid, qq in por_peca[k].items(): soma[iid] += int(q) * qq
    atuais = {r["ingredient_id"] for r in api.get(f"/admin/menu/product/{cid}/recipes")}
    for iid, q in soma.items():
        if iid in atuais: print("já existe", cid, iid); continue
        if DRY: continue
        req = urllib.request.Request(BASE_URL + "/admin/menu/recipe/save", method="POST",
            data=urllib.parse.urlencode({"product_id": cid, "ingredient_id": iid, "quantity": f"{q:.4f}"}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"})
        st, _ = api._send(req)
        if st != 200: print("ERRO", cid, iid, st)
    r = api.get(f"/admin/menu/product/{cid}/recipes")
    custo = sum(x["total_cost"] for x in r)
    out.append((p["name"], ", ".join(comp), len(r), round(custo, 2), p["price"]))
    print(f"{p['name']:28} | {', '.join(comp):45} | linhas {len(r)} | custo {custo:.2f} | preço {p['price']}")
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
