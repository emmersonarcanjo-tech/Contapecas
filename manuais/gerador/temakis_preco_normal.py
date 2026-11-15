"""Volta ao preço normal os temakis que alguém trocou à mão para o preço da sexta (pedido do Emerson em 14/11/2026).

Na Sexta do Temaki o preço de R$ 24,90 vem sozinho da promoção do ALIV; o preço de cadastro NÃO deve ser trocado.
Em 13/11 alguém pôs 4 temakis a R$ 24,99 no cadastro, e eles continuaram assim no sábado.
Este script muda só o campo "preço" desses produtos; ficha, descrição, canais, categoria e pausa ficam como estão.

  python3 temakis_preco_normal.py            mostra o que faria (dry-run)
  python3 temakis_preco_normal.py --gravar   grava, relê e confere cada produto
"""
import sys, os, json, uuid, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR = "--gravar" in sys.argv[1:]
# preço normal lido do cadastro em 13/11/2026 às 14:40, antes da troca manual
NORMAL = {11683: 35.90, 11684: 35.90, 11689: 33.90, 11686: 32.99}
BACKUP = "/workspace/Contapecas/manuais/aliv_backup/temakis_preco_normal_%s.json" % datetime.now(ZoneInfo("America/Bahia")).strftime("%Y-%m-%d")
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
b = lambda v: "true" if v else "false"

def parar(msg): print("PAREI:", msg); sys.exit(1)
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
    """Todos os campos do produto como a tela do ALIV envia; `troca` muda só o que foi pedido."""
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
def fichas(pid):
    return sorted((l["ingredient_id"], l["quantity"]) for l in api.get(f"/admin/menu/product/{pid}/recipes"))

card = cardapio(); fazer = []; registro = []
for pid, normal in NORMAL.items():
    p = card.get(pid)
    if not p: parar(f"produto {pid} não está no cardápio")
    canais = p["full_data"].get("channel_prices") or {}
    estado = "já está no normal" if abs(p["price"] - normal) < 0.005 else f"-> R$ {normal:.2f}"
    print(f"{p['name'][:34]:34s} hoje R$ {p['price']:.2f} | ativo {p['is_active']} | canais {canais} | {estado}")
    if abs(p["price"] - normal) >= 0.005: fazer.append((pid, normal))
if not GRAVAR:
    print(f"faria: {len(fazer)} produto(s) de volta ao preço normal | modo: dry-run (nada gravado)"); sys.exit()
for pid, normal in fazer:
    p = card[pid]; fd = p["full_data"]; ficha_antes = fichas(pid)
    st, r = multipart(campos_produto(p, price=f"{normal:.2f}"), "/admin/menu/product/save")
    if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar(f"{p['name']}: não salvou ({st} {str(r)[:160]})")
    d = cardapio()[pid]; n = d["full_data"]
    fora = sorted(k for k in set(fd) | set(n) if fd.get(k) != n.get(k) and k != "price")
    if abs(d["price"] - normal) > 0.005 or abs(float(n.get("price")) - normal) > 0.005: parar(f"{p['name']}: preço ficou R$ {d['price']}")
    if fora or p["is_active"] != d["is_active"] or fichas(pid) != ficha_antes: parar(f"{p['name']}: mudou o que não devia: {fora} ativo {p['is_active']}->{d['is_active']}")
    registro.append({"product_id": pid, "nome": p["name"], "preco_antes": p["price"], "preco_depois": d["price"], "ativo": d["is_active"]})
    print(f"   gravado {p['name'][:34]:34s} R$ {p['price']:.2f} -> R$ {d['price']:.2f} | resto igual, ficha igual")
if registro: json.dump({"quando": datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes"), "motivo": "preço trocado à mão na sexta 13/11; volta ao normal a pedido do Emerson", "produtos": registro}, open(BACKUP, "w"), ensure_ascii=False, indent=1)
print("modo: GRAVAR | ok |", len(registro), "produto(s)")
