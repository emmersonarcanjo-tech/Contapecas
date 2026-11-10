import sys, os, json, re, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
def post(path, data):
    req = urllib.request.Request(BASE_URL + path, data=urllib.parse.urlencode(data).encode(), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"})
    return api._send(req)
print("custo:", post("/admin/inventory/ingredient/quick-update", {"ing_id": 23642, "field": "cost", "value": "6"}))
x = [i for i in api.get("/admin/inventory/api/ingredients")["ingredients"] if i["id"] == 23642][0]
print("conferido:", x["name"], x["cost"], x["unit"])
prop = json.load(open(sys.argv[1])); rec = json.load(open(sys.argv[2]))
t = lambda n: re.sub(r"\s*\(.*?\)\s*", " ", n).strip().replace("Hosso ", "Hossomaki ").replace("Ura ", "Uramaki ")
m = {t(v["name"]): int(k) for k, v in rec.items() if v["active"]}
for o in prop:
    pid = m.get(o["titulo"])
    for l in o["linhas"]:
        if pid and l[1] == 23642:
            st, r = post("/admin/menu/recipe/save", {"product_id": pid, "ingredient_id": 23642, "quantity": f"{l[3]:.4f}"})
            print(st, o["titulo"], l[3])
