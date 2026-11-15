"""Mostra ou esconde uma categoria do cardápio do ALIV em UM canal (PDV, garçom, totem, delivery ou IA), sem mexer no resto.

Pedido do Emerson em 14/11/2026: esconder a categoria "SEXTA DO TEMAKI NA TILI" só do PDV. O PDV do ALIV lista o produto
apenas na categoria principal (Temaki) e ignora a categoria extra, então ela aparecia vazia para a equipe.
Os temakis continuam na categoria Temaki e o preço da sexta continua vindo da promoção.

  python3 categoria_canal.py <id da categoria> <pdv|waiter|kiosk|delivery|ia> <sim|nao>            mostra o que faria
  python3 categoria_canal.py <id da categoria> <pdv|waiter|kiosk|delivery|ia> <sim|nao> --gravar   grava, relê e confere
A categoria é regravada com TODOS os campos atuais (a tela do ALIV faz igual). Não mexe em iFood.
"""
import sys, os, json, uuid, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
args = [a for a in sys.argv[1:] if a != "--gravar"]; GRAVAR = "--gravar" in sys.argv[1:]
if len(args) != 3 or args[1] not in ("pdv", "waiter", "kiosk", "delivery", "ia") or args[2] not in ("sim", "nao"): print(__doc__); sys.exit(2)
CAT, CAMPO, NOVO = int(args[0]), "show_in_" + args[1], args[2] == "sim"
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
s = lambda v: "true" if v else "false"

def categoria():
    r = api.get("/admin/api/categories"); cats = r.get("categories", r) if isinstance(r, dict) else r
    return next((c for c in cats if c["id"] == CAT), None)
def produtos_da_categoria():
    return sorted(p["id"] for c in api.get("/admin/api/menu/full_data")["categories"] if c["id"] == CAT for p in c["products"])
def pdv():
    d = api.get("/admin/api/pdv/data"); return {c["id"] for c in d["categories"]}, {p["id"]: p for p in d["products"]}
def campos(c):
    """Os campos que a tela do ALIV envia ao salvar a categoria (os vazios não vão, como na tela)."""
    f = [("name", c["name"]), ("order_index", str(c.get("order_index") or 0))]
    if c.get("sector_id") is not None: f.append(("sector_id", str(c["sector_id"])))
    if c.get("target_printer") is not None: f.append(("target_printer", c["target_printer"]))
    f += [("allow_employee_discount", s(c["allow_employee_discount"])), ("print_separate_ticket", s(c["print_separate_ticket"]))]
    if c.get("print_highlight") is not None: f.append(("print_highlight", s(c["print_highlight"])))
    f += [("show_in_kiosk", s(c["show_in_kiosk"])), ("show_in_pdv", s(c["show_in_pdv"])), ("show_in_waiter", s(c["show_in_waiter"]))]
    if c.get("show_in_ia") is not None: f.append(("show_in_ia", s(c["show_in_ia"])))
    f += [("show_in_delivery", s(c["show_in_delivery"])), ("menu_ids_json", json.dumps(c.get("menu_ids") or [])),
          ("show_in_orders_board", s(c.get("show_in_orders_board"))), ("show_in_print_menu", s(c.get("show_in_print_menu") is not False)),
          ("is_checkout_offer", s(c.get("is_checkout_offer"))), ("schedule_rules", json.dumps(c.get("schedule_rules") or []))]
    for k in ("ncm", "cfop", "uom", "cest", "icms_cst", "ibs_cbs_cst", "ibs_cbs_class_trib", "icms_origem", "icms_aliquota", "pis_cst", "pis_aliquota", "cofins_cst", "cofins_aliquota", "cbenef"):
        if c.get(k) is not None: f.append((k, str(c[k])))
    if c.get("image_bank_id") is not None: f.append(("image_bank_id", str(c["image_bank_id"])))
    elif c.get("image_url") is not None: f.append(("image_url", c["image_url"]))
    return f

antes = categoria()
if not antes: print("PAREI: categoria", CAT, "não existe"); sys.exit(1)
prods_antes = produtos_da_categoria(); cats_pdv, prods_pdv = pdv()
print(f"categoria {CAT} '{antes['name']}' | ativa {antes['is_active']} | regra de horário {antes.get('schedule_rules')}")
print("   aparece em:", {k[8:]: antes[k] for k in ("show_in_pdv", "show_in_waiter", "show_in_kiosk", "show_in_delivery", "show_in_ia")})
print(f"   produtos ligados a ela no cardápio: {len(prods_antes)} | hoje está na lista de categorias do PDV: {CAT in cats_pdv}")
if antes[CAMPO] == NOVO: print(f"{CAMPO} já está {NOVO}: nada a fazer"); sys.exit()
print(f"faria: {CAMPO} {antes[CAMPO]} -> {NOVO} (só isso)")
if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()

novo = dict(antes); novo[CAMPO] = NOVO
bd = uuid.uuid4().hex
corpo = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in campos(novo)) + f"--{bd}--\r\n"
st, r = api._send(urllib.request.Request(BASE_URL + f"/admin/api/categories/{CAT}", data=corpo.encode(), method="PUT",
                  headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))
print("salvar categoria:", st, str(r)[:160])
if st != 200 or (isinstance(r, dict) and r.get("success") is False): print("PAREI: não salvou"); sys.exit(1)
depois = categoria(); fora = sorted(k for k in set(antes) | set(depois) if antes.get(k) != depois.get(k) and k != CAMPO)
prods_depois = produtos_da_categoria(); cats_pdv2, prods_pdv2 = pdv()
print(f"   relido: {CAMPO} = {depois[CAMPO]} | outros campos que mudaram: {fora or 'nenhum'}")
print(f"   produtos ligados à categoria: {len(prods_antes)} -> {len(prods_depois)} | na lista do PDV agora: {CAT in cats_pdv2}")
print(f"   produtos no PDV: {len(prods_pdv)} -> {len(prods_pdv2)} | os da categoria que estavam no PDV continuam: {all(i in prods_pdv2 for i in prods_antes if i in prods_pdv)}")
json.dump({"quando": datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes"), "categoria": CAT, "campo": CAMPO, "antes": antes, "depois": depois},
          open(f"/workspace/Contapecas/manuais/aliv_backup/categoria_{CAT}_{args[1]}_{datetime.now(ZoneInfo('America/Bahia')):%Y-%m-%d}.json", "w"), ensure_ascii=False, indent=1)
if depois[CAMPO] != NOVO or fora or prods_depois != prods_antes or len(prods_pdv2) != len(prods_pdv): print("PAREI: o resultado não ficou como o plano — conferir"); sys.exit(1)
print("modo: GRAVAR | ok")
