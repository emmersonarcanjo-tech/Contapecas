"""Fichas dos yakisobas (sem o molho da casa, receita pendente). Autorizado pelo Emerson 11/11/2026."""
import sys, os, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
MAC, LEG, FRA, CAM, FIL, EMB = 23869, 24168, 24166, 23917, 24167, 24169
BASE = {MAC: 80 / 500, LEG: 0.120, EMB: 1}
FICHAS = {14325: {**BASE, FRA: 0.090}, 14328: {**BASE, CAM: 0.090}, 14329: {**BASE, CAM: 0.030, FIL: 0.030, FRA: 0.030}}
for pid, linhas in FICHAS.items():
    atuais = {r["ingredient_id"] for r in api.get(f"/admin/menu/product/{pid}/recipes")}
    for iid, q in linhas.items():
        if iid in atuais: print("já existe", pid, iid); continue
        req = urllib.request.Request(BASE_URL + "/admin/menu/recipe/save", method="POST",
            data=urllib.parse.urlencode({"product_id": pid, "ingredient_id": iid, "quantity": f"{q:.4f}"}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"})
        print(pid, iid, q, api._send(req)[0])
    r = api.get(f"/admin/menu/product/{pid}/recipes")
    print("  ", pid, [(x["ingredient_raw_name"], x["quantity"], round(x["total_cost"], 2)) for x in r], "TOTAL", round(sum(x["total_cost"] for x in r), 2))
