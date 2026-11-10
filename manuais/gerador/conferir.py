import sys, os, json, re
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
prop = json.load(open(sys.argv[1])); rec = json.load(open(sys.argv[2]))
full = json.load(open(sys.argv[3]))
preco = {p["id"]: p.get("price") for c in full["categories"] for p in c["products"]}
t = lambda n: re.sub(r"\s*\(.*?\)\s*", " ", n).strip().replace("Hosso ", "Hossomaki ").replace("Ura ", "Uramaki ")
m = {t(v["name"]): int(k) for k, v in rec.items() if v["active"]}
res = []
for o in prop:
    pid = m.get(o["titulo"])
    if not pid: continue
    r = api.get(f"/admin/menu/product/{pid}/recipes")
    custo = sum(x["total_cost"] for x in r); dup = len(r) != len({x["ingredient_id"] for x in r})
    res.append((o["cat"], o["titulo"], pid, len(r), round(custo, 2), o["custo"], preco.get(pid), dup, o["faltas"]))
json.dump(res, open(sys.argv[4], "w"), ensure_ascii=False, indent=1)
for x in res:
    flag = "" if abs(x[4] - x[5]) < 0.02 and not x[7] else "  <<< DIFERENTE" + (" DUPLICADO" if x[7] else "")
    print(f"{x[0]:9} {x[1][:36]:36} linhas {x[3]}  ALIV R$ {x[4]:5.2f}  calc R$ {x[5]:5.2f}  preço R$ {x[6]}{flag}")
