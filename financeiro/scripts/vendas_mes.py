"""Vendas do Sushi (loja 155) de 01 a 31/10/2026, por turno (16:00–08:00). Só leitura."""
import sys, os, json
from datetime import date, datetime, timedelta
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, pedidos_do_turno, TZ
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
todos = []
d = date(2026, 10, 1)
while d <= date(2026, 10, 31):
    ped = pedidos_do_turno(api, d, datetime(d.year, d.month, d.day, 8, tzinfo=TZ) + timedelta(days=1))
    for p in ped: p["_dia"] = d.isoformat()
    todos += ped
    print(d, len(ped), flush=True)
    d += timedelta(days=1)
json.dump(todos, open(sys.argv[1], "w"), ensure_ascii=False, default=str)
print("total", len(todos))
