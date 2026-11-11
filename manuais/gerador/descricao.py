"""Troca só a descrição de um produto no ALIV, reenviando todos os outros campos como estão. Confere antes/depois."""
import sys, os, json, uuid, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
def produto(pid):
    full = api.get("/admin/api/menu/full_data")
    for c in full["categories"]:
        for p in c["products"]:
            if p["id"] == pid: return p
pid, nova = int(sys.argv[1]), sys.argv[2]
SEM_AUTOPAUSA = "--sem-autopausa" in sys.argv
p = produto(pid); fd = p["full_data"]; cfg = fd.get("config") or {}
if nova == "=": nova = fd.get("description") or ""
json.dump(p, open(f"{sys.argv[3]}/produto_{pid}_antes.json", "w"), ensure_ascii=False, indent=1)
b = lambda v: "true" if v else "false"
campos = {"prod_id": pid, "name": fd["name"], "description": nova, "category_id": fd["category_id"], "price": fd["price"],
    "price_in_points": fd.get("price_in_points") or 0, "channel_prices_json": json.dumps(fd.get("channel_prices") or {}),
    "compare_at_price": fd.get("compare_at_price") or 0, "allows_flavors": b(fd.get("allows_flavors")), "max_flavors": fd.get("max_flavors") or 1,
    "is_pizza": b(fd.get("is_pizza")), "auto_disable_on_stock_zero": "false" if SEM_AUTOPAUSA else b(fd.get("auto_disable_on_stock_zero")), "sold_by_weight": b(fd.get("sold_by_weight")),
    "kitchen_alert_active": b(fd.get("kitchen_alert_active")), "kitchen_alert_text": fd.get("kitchen_alert_text") or "",
    "show_in_kiosk": b(fd.get("show_in_kiosk")), "show_in_pdv": b(fd.get("show_in_pdv")), "show_in_waiter": b(fd.get("show_in_waiter")),
    "show_in_ia": b(fd.get("show_in_ia")), "show_in_delivery": b(fd.get("show_in_delivery")), "show_in_print_menu": b(fd.get("show_in_print_menu", True)),
    "menu_ids_json": json.dumps(fd.get("menu_ids") or []), "schedule_rules_json": json.dumps(fd.get("schedule_rules") or []),
    "size_prices_json": json.dumps(fd.get("size_prices") or []),
    "config_json": json.dumps({"additional_categories": cfg.get("additional_categories") or [], "allowed_addons": cfg.get("allowed_addons") or [],
                               "blocked_addons": cfg.get("blocked_addons") or []})}
for k in ("detailed_description", "preparation_method", "barcode", "ncm", "cfop", "uom", "cest"):
    if fd.get(k) is not None: campos[k] = fd[k]
if p.get("external_code") is not None: campos["external_code"] = p["external_code"]
if fd.get("image_bank_id") is not None: campos["image_bank_id"] = fd["image_bank_id"]
elif fd.get("image_url"): campos["image_url"] = fd["image_url"]
bd = uuid.uuid4().hex
body = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in campos.items()) + f"--{bd}--\r\n"
st, resp = api._send(urllib.request.Request(BASE_URL + "/admin/menu/product/save", data=body.encode(), method="POST",
                     headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))
print("save:", st, str(resp)[:150])
d = produto(pid); json.dump(d, open(f"{sys.argv[3]}/produto_{pid}_depois.json", "w"), ensure_ascii=False, indent=1)
def plano(x, pre=""):
    out = {}
    for k, v in (x.items() if isinstance(x, dict) else []):
        if isinstance(v, dict): out.update(plano(v, pre + k + "."))
        else: out[pre + k] = v
    return out
a, z = plano(p), plano(d)
dif = {k: (a.get(k), z.get(k)) for k in set(a) | set(z) if a.get(k) != z.get(k)}
print("campos que mudaram:", json.dumps(dif, ensure_ascii=False)[:800])
