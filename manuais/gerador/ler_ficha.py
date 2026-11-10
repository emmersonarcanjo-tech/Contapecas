import sys, os, json
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
for pid in sys.argv[1:]:
    r = api.get(f"/admin/menu/product/{pid}/recipes")
    print(pid, json.dumps(r, ensure_ascii=False))
