"""Muda o preço de cadastro de produtos no ALIV (e o do QR de indicação, preço + 10%, onde existir). Só o preço muda.

  python3 preco_produto.py 30757=5.99 35080=5.99            mostra o que faria (dry-run)
  python3 preco_produto.py 30757=5.99 35080=5.99 --gravar   guarda o "antes", grava, relê e confere cada produto
Usar só com pedido do Emerson. Para a promoção de sexta dos temakis NÃO se troca preço de cadastro (ver sexta_temaki.py).
"""
import sys, os, json, uuid, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR = "--gravar" in sys.argv[1:]
try: PRECOS = {int(a.split("=")[0]): float(a.split("=")[1].replace(",", ".")) for a in sys.argv[1:] if a != "--gravar"}
except Exception: print(__doc__); sys.exit(2)
if not PRECOS: print(__doc__); sys.exit(2)
BK = f"/workspace/Contapecas/manuais/aliv_backup/preco_produto_antes_{datetime.now(ZoneInfo('America/Bahia')):%Y-%m-%d_%H%M}.json"
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login(); api.timeout = max(getattr(api, "timeout", 0) or 0, 120)
b = lambda v: "true" if v else "false"
def parar(m): print("PAREI:", m); sys.exit(1)
def multipart(pares, path):
    def f():
        bd = uuid.uuid4().hex
        corpo = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in pares) + f"--{bd}--\r\n"
        return urllib.request.Request(BASE_URL + path, data=corpo.encode(), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"})
    st, r = api._send(f())
    if st == 401: api.login(); st, r = api._send(f())
    return st, r
def cardapio():
    out = {}
    for c in api.get("/admin/api/menu/full_data")["categories"]:
        for p in c["products"]: out.setdefault(p["id"], p)
    return out
def campos_produto(p, **troca):
    fd = p["full_data"]; cfg = fd.get("config") or {}
    c = {"prod_id": p["id"], "name": fd["name"], "description": fd.get("description") or "", "category_id": fd["category_id"], "price": fd["price"],
         "price_in_points": fd.get("price_in_points") or 0, "channel_prices_json": json.dumps(fd.get("channel_prices") or {}),
         "compare_at_price": fd.get("compare_at_price") or 0, "allows_flavors": b(fd.get("allows_flavors")), "max_flavors": fd.get("max_flavors") or 1,
         "is_pizza": b(fd.get("is_pizza")), "auto_disable_on_stock_zero": b(fd.get("auto_disable_on_stock_zero")), "sold_by_weight": b(fd.get("sold_by_weight")),
         "kitchen_alert_active": b(fd.get("kitchen_alert_active")), "kitchen_alert_text": fd.get("kitchen_alert_text") or "",
         "show_in_kiosk": b(fd.get("show_in_kiosk")), "show_in_pdv": b(fd.get("show_in_pdv")), "show_in_waiter": b(fd.get("show_in_waiter")),
         "show_in_ia": b(fd.get("show_in_ia")), "show_in_delivery": b(fd.get("show_in_delivery")), "show_in_print_menu": b(fd.get("show_in_print_menu", True)),
         "menu_ids_json": json.dumps(fd.get("menu_ids") or []), "schedule_rules_json": json.dumps(fd.get("schedule_rules") or []),
         "pausa_horario_ligada": b((fd.get("pausa_horario") or {}).get("ligada")), "size_prices_json": json.dumps(fd.get("size_prices") or []),
         "config_json": json.dumps({"additional_categories": cfg.get("additional_categories") or [], "allowed_addons": cfg.get("allowed_addons") or [], "blocked_addons": cfg.get("blocked_addons") or []})}
    for k in ("detailed_description", "preparation_method", "barcode", "ncm", "cfop", "uom", "cest"):
        if fd.get(k) is not None: c[k] = fd[k]
    if p.get("external_code") is not None: c["external_code"] = p["external_code"]
    if fd.get("image_bank_id") is not None: c["image_bank_id"] = fd["image_bank_id"]
    elif fd.get("image_url"): c["image_url"] = fd["image_url"]
    c.update(troca); return list(c.items())
card = cardapio(); fazer = []
for pid, novo in PRECOS.items():
    p = card.get(pid)
    if not p: parar(f"produto {pid} não existe")
    canais = dict(p["full_data"].get("channel_prices") or {}); nc = dict(canais, indicacao=round(novo * 1.10, 2)) if "indicacao" in canais else canais
    muda = abs(p["price"] - novo) > 0.005 or nc != canais
    print(f"{pid:6d} {p['name'][:34]:34s} R$ {p['price']:.2f} -> {novo:.2f} | QR {canais.get('indicacao')} -> {nc.get('indicacao')} | ativo {p['is_active']} | {'muda' if muda else 'já está'}")
    if muda: fazer.append((pid, novo, nc))
if not GRAVAR: print(f"faria: {len(fazer)} produto(s) | modo: dry-run (nada gravado)"); sys.exit()
if fazer:
    json.dump({"quando": datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes"), "produtos": {str(i): {"nome": card[i]["name"], "preco": card[i]["price"], "canais": card[i]["full_data"].get("channel_prices") or {}} for i, _, _ in fazer}},
              open(BK, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print("antes guardado em", BK)
for pid, novo, nc in fazer:
    p = card[pid]; fd = p["full_data"]
    st, r = multipart(campos_produto(p, price=f"{novo:.2f}", channel_prices_json=json.dumps(nc)), "/admin/menu/product/save")
    if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar(f"{p['name']}: não salvou ({st} {str(r)[:120]})")
    d = cardapio()[pid]; n = d["full_data"]; fora = sorted(k for k in set(fd) | set(n) if fd.get(k) != n.get(k) and k not in ("price", "channel_prices"))
    if abs(d["price"] - novo) > 0.005 or (n.get("channel_prices") or {}) != nc or fora or d["is_active"] != p["is_active"]: parar(f"{p['name']}: não ficou como o plano (preço {d['price']}, mudou também {fora})")
    print(f"   ok {pid} {d['name'][:34]:34s} R$ {p['price']:.2f} -> {d['price']:.2f} | resto igual")
print("modo: GRAVAR | ok |", len(fazer), "produto(s)")
