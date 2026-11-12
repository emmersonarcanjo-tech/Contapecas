import sys, os, json
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
full = api.get("/admin/api/menu/full_data"); out = {}
for c in full["categories"]:
    if c["id"] in (939, 1231, 1232, 1161, 2331): continue
    for p in c["products"]:
        if p["name"] in out: continue
        r = api.get(f"/admin/menu/product/{p['id']}/recipes")
        if r: out[p["name"]] = round(sum(x["total_cost"] for x in r), 4)
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1); print(len(out))
