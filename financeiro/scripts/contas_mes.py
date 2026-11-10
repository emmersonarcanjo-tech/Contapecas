import sys, os, json
from collections import defaultdict
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
r = api.get("/admin/finance/bills", {"status": "all", "bill_type": "payable", "start_date": "2026-10-01", "end_date": "2026-10-31"}) or []
lst = r if isinstance(r, list) else (r.get("bills") or r.get("rows") or r.get("data") or [])
json.dump(r, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=str)
print(len(lst)); print(json.dumps(lst[0], ensure_ascii=False)[:600] if lst else r if not isinstance(r, list) else "")
tot = defaultdict(float)
for b in lst:
    tot[b.get("category_name") or b.get("category") or "?"] += float(b.get("amount") or b.get("value") or 0)
for k, v in sorted(tot.items(), key=lambda x: -x[1]): print(f"{v:10.2f}  {k}")
print("TOTAL", round(sum(tot.values()), 2))
