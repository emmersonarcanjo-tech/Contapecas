"""Pedidos do Sushi (loja 155) de um turno de quarta (16:00–08:00). Só leitura (GET)."""
import sys, os, json
from datetime import date, datetime, timedelta
from collections import Counter
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, pedidos_do_turno, itens_do_pedido, canal_sushi, TZ
dia = date.fromisoformat(sys.argv[1]); out = sys.argv[2]
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
agora = datetime.now(TZ)
ate = min(agora, datetime(dia.year, dia.month, dia.day, 8, tzinfo=TZ) + timedelta(days=1))
ped = pedidos_do_turno(api, dia, ate)
for p in ped: p["_dia"] = dia.isoformat()
json.dump(ped, open(out, "w"), ensure_ascii=False, indent=1, default=str)
print("lido em", agora.strftime("%d/%m %H:%M"), "| pedidos:", len(ped))
c = Counter(); can = Counter(); abertos = 0
for p in ped:
    st = str(p.get("status"))
    can[(canal_sushi(p), st)] += 1
    for i in itens_do_pedido(p):
        c[(i.get("title") or i.get("name"), i.get("price"))] += i.get("quantity") or 1
print(dict(can))
for (t, pr), q in c.most_common(70): print(q, "x", t, "|", pr)
