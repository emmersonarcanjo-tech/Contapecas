"""Preço por peça de niguiri (R$ 3,49) e Joy (R$ 4,99) no ALIV — pedido do Emerson em 27/11/2026 ("fazer essa alteração no sistema").
É o preço sugerido no estudo de 12/11 (financeiro/Quarta Maluca - precos sugeridos.pdf). Vale como preço normal, não só hoje.

Onde muda:
  - totem do buffet: "Nigiri (peça buffet)" 3,99 -> 3,49 ("Joy (peça buffet)" já está a 4,99);
  - caixa (PDV): botões "PEÇA NIGUIRI" (-> 3,49) e "PEÇA JOY" (-> 4,99), que estavam desligados, passam a aparecer;
  - botões de quarta "QUARTA NIGUIRI" / "QUARTA JOY": só o preço (continuam desligados);
  - peças por sabor da Quarta Maluca "Niguiri ... (1 peça)" -> 3,49 e "Joy ... (1 peça)" -> 4,99
    (menos Niguiri Skin, Joy Camarão e Joy Camarão s/ Arroz, que não entraram no estudo e ficam como estão).
O preço do QR de indicação acompanha (preço + 10%) onde existe. Ficha, canais, dias e o resto ficam como estão.

  python3 precos_niguiri_joy.py            mostra o que faria (dry-run)
  python3 precos_niguiri_joy.py --gravar   guarda o "antes", grava, relê e confere cada produto
"""
import sys, os, json, uuid, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR = "--gravar" in sys.argv[1:]
NIG, JOY = 3.49, 4.99
PRECOS = {35078: NIG, 35079: JOY, 34551: NIG, 34552: JOY, 34557: NIG, 34558: JOY}
PRECOS.update({i: NIG for i in (30114, 30116, 30117, 30118, 30119)}); PRECOS.update({i: JOY for i in range(30120, 30127)})
# Ficam como estavam, porque não entraram no estudo: Niguiri Skin (1 peça) 2,49, Joy Camarão (1 peça) 5,99 e Joy Camarão s/ Arroz (1 peça) 6,99.
ATIVAR = [34551, 34552]
BK = f"/workspace/Contapecas/manuais/aliv_backup/precos_niguiri_joy_antes_{datetime.now(ZoneInfo('America/Bahia')):%Y-%m-%d}.json"
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
    muda = abs(p["price"] - novo) > 0.005 or nc != canais; ativa = pid in ATIVAR and not p["is_active"]
    print(f"{pid:6d} {p['name'][:34]:34s} R$ {p['price']:.2f} -> {novo:.2f} | QR {canais.get('indicacao')} -> {nc.get('indicacao')} | ativo {p['is_active']}{' -> True' if ativa else ''} | {'muda' if muda or ativa else 'já está'}")
    if muda or ativa: fazer.append((pid, novo, nc, muda, ativa))
if not GRAVAR: print(f"faria: {len(fazer)} produto(s) | modo: dry-run (nada gravado)"); sys.exit()
if not os.path.exists(BK):
    json.dump({"quando": datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes"), "produtos": {str(i): {"nome": card[i]["name"], "preco": card[i]["price"], "canais": card[i]["full_data"].get("channel_prices") or {}, "ativo": card[i]["is_active"]} for i in PRECOS}},
              open(BK, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print("antes guardado em", BK)
for pid, novo, nc, muda, ativa in fazer:
    p = card[pid]; fd = p["full_data"]
    if muda:
        st, r = multipart(campos_produto(p, price=f"{novo:.2f}", channel_prices_json=json.dumps(nc)), "/admin/menu/product/save")
        if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar(f"{p['name']}: não salvou ({st} {str(r)[:120]})")
        d = cardapio()[pid]; n = d["full_data"]; fora = sorted(k for k in set(fd) | set(n) if fd.get(k) != n.get(k) and k not in ("price", "channel_prices"))
        if abs(d["price"] - novo) > 0.005 or (n.get("channel_prices") or {}) != nc or fora or d["is_active"] != p["is_active"]: parar(f"{p['name']}: não ficou como o plano (preço {d['price']}, mudou também {fora})")
    if ativa:
        st, r = multipart([], f"/admin/menu/product/{pid}/toggle-status")
        d = cardapio()[pid]
        if st != 200 or not d["is_active"]: parar(f"{p['name']}: não ligou ({st} {str(r)[:120]})")
    d = cardapio()[pid]; print(f"   ok {pid} {d['name'][:34]:34s} R$ {p['price']:.2f} -> {d['price']:.2f} | ativo {d['is_active']}")
print("modo: GRAVAR | ok |", len(fazer), "produto(s)")
