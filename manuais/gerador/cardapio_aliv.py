"""Cardápio do ALIV: criar categoria (copiando a configuração de outra) e salvar produto mudando só o que foi pedido.

  python3 cardapio_aliv.py categoria "<nome>" --modelo <id da categoria modelo> [--primeira] [--gravar]
  python3 cardapio_aliv.py produto <id> [--categoria <id>] [--imagem <arquivo>] [--gravar]
Sem --gravar só mostra o que faria. O produto é regravado com TODOS os campos atuais (a tela do ALIV faz igual) e, depois,
relido: o script acusa qualquer campo que tenha mudado sem ser pedido. Não mexe em iFood."""
import sys, os, json, uuid, mimetypes, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR = "--gravar" in sys.argv
def arg(nome, padrao=None):
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else padrao
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
b = lambda v: "true" if v else "false"

def multipart(campos, arquivo=None, metodo="POST", path=""):
    bd = uuid.uuid4().hex; corpo = b""
    for k, v in campos.items():
        corpo += f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    if arquivo:
        nome_campo, caminho = arquivo; tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
        corpo += f'--{bd}\r\nContent-Disposition: form-data; name="{nome_campo}"; filename="{os.path.basename(caminho)}"\r\nContent-Type: {tipo}\r\n\r\n'.encode()
        corpo += open(caminho, "rb").read() + b"\r\n"
    corpo += f"--{bd}--\r\n".encode()
    return api._send(urllib.request.Request(BASE_URL + path, data=corpo, method=metodo,
                     headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))

def categorias():
    r = api.get("/admin/api/categories"); return r.get("categories", r) if isinstance(r, dict) else r

def produto(pid):
    for c in api.get("/admin/api/menu/full_data")["categories"]:
        for p in c["products"]:
            if p["id"] == pid: return p

if sys.argv[1] == "categoria":
    nome = sys.argv[2]; cats = categorias(); mod = next(c for c in cats if c["id"] == int(arg("--modelo")))
    ja = next((c for c in cats if c["name"].strip().lower() == nome.strip().lower()), None)
    if ja: print("categoria já existe:", ja["id"], ja["name"], "| ativa:", ja["is_active"], "| ordem:", ja["order_index"])
    campos = {"name": nome, "order_index": 0, "allow_employee_discount": b(mod["allow_employee_discount"]), "print_separate_ticket": b(mod["print_separate_ticket"]),
              "print_highlight": b(mod.get("print_highlight")), "show_in_kiosk": b(mod["show_in_kiosk"]), "show_in_pdv": b(mod["show_in_pdv"]), "show_in_waiter": b(mod["show_in_waiter"]),
              "show_in_ia": b(mod["show_in_ia"]), "show_in_delivery": b(mod["show_in_delivery"]), "menu_ids_json": json.dumps(mod.get("menu_ids") or []),
              "show_in_orders_board": b(mod.get("show_in_orders_board")), "show_in_print_menu": b(mod.get("show_in_print_menu", True)), "is_checkout_offer": "false", "schedule_rules": "[]"}
    if mod.get("sector_id") is not None: campos["sector_id"] = mod["sector_id"]
    for k in ("ncm", "cfop", "uom", "cest"):
        if mod.get(k): campos[k] = mod[k]
    print("criaria" if not ja else "manteria", "categoria:", campos)
    if GRAVAR and not ja:
        st, r = multipart(campos, path="/admin/api/categories"); print("criar categoria:", st, str(r)[:200])
        if st != 200: raise SystemExit("PAREI: não criou a categoria")
        cats = categorias(); ja = next((c for c in cats if c["name"].strip().lower() == nome.strip().lower()), None)
        if not ja: raise SystemExit("PAREI: categoria não apareceu")
    if GRAVAR and "--primeira" in sys.argv and ja:
        ordem = [ja["id"]] + [c["id"] for c in sorted(cats, key=lambda c: (c["order_index"], c["id"])) if c["id"] != ja["id"]]
        st, r = multipart({"cat_ids": ",".join(map(str, ordem))}, path="/admin/api/categories/reorder"); print("reordenar:", st, str(r)[:120])
    for c in sorted(categorias(), key=lambda c: (c["order_index"], c["id"])):
        print(f"   ordem {c['order_index']:3d} | id {c['id']:5d} | ativa {str(c['is_active']):5s} | {c['name']}")

elif sys.argv[1] == "produto":
    pid = int(sys.argv[2]); p = produto(pid); fd = p["full_data"]; cfg = fd.get("config") or {}
    nova_cat = arg("--categoria"); img = arg("--imagem")
    campos = {"prod_id": pid, "name": fd["name"], "description": fd.get("description") or "", "category_id": int(nova_cat) if nova_cat else fd["category_id"], "price": fd["price"],
        "price_in_points": fd.get("price_in_points") or 0, "channel_prices_json": json.dumps(fd.get("channel_prices") or {}),
        "compare_at_price": fd.get("compare_at_price") or 0, "allows_flavors": b(fd.get("allows_flavors")), "max_flavors": fd.get("max_flavors") or 1,
        "is_pizza": b(fd.get("is_pizza")), "auto_disable_on_stock_zero": b(fd.get("auto_disable_on_stock_zero")), "sold_by_weight": b(fd.get("sold_by_weight")),
        "kitchen_alert_active": b(fd.get("kitchen_alert_active")), "kitchen_alert_text": fd.get("kitchen_alert_text") or "",
        "show_in_kiosk": b(fd.get("show_in_kiosk")), "show_in_pdv": b(fd.get("show_in_pdv")), "show_in_waiter": b(fd.get("show_in_waiter")),
        "show_in_ia": b(fd.get("show_in_ia")), "show_in_delivery": b(fd.get("show_in_delivery")), "show_in_print_menu": b(fd.get("show_in_print_menu", True)),
        "menu_ids_json": json.dumps(fd.get("menu_ids") or []), "schedule_rules_json": json.dumps(fd.get("schedule_rules") or []),
        "size_prices_json": json.dumps(fd.get("size_prices") or []),
        "config_json": json.dumps({"additional_categories": cfg.get("additional_categories") or [], "allowed_addons": cfg.get("allowed_addons") or [], "blocked_addons": cfg.get("blocked_addons") or []})}
    for k in ("detailed_description", "preparation_method", "barcode", "ncm", "cfop", "uom", "cest"):
        if fd.get(k) is not None: campos[k] = fd[k]
    if p.get("external_code") is not None: campos["external_code"] = p["external_code"]
    if not img:
        if fd.get("image_bank_id") is not None: campos["image_bank_id"] = fd["image_bank_id"]
        elif fd.get("image_url"): campos["image_url"] = fd["image_url"]
    print(f"produto {pid} {fd['name']} | categoria {fd['category_id']} -> {campos['category_id']} | imagem: {'nova: ' + img if img else 'mantém ' + str(fd.get('image_url'))}")
    if not GRAVAR:
        print("modo: dry-run (nada gravado)"); sys.exit()
    st, r = multipart(campos, ("image_file", img) if img else None, path="/admin/menu/product/save"); print("salvar produto:", st, str(r)[:200])
    if st != 200: raise SystemExit("PAREI: não salvou o produto")
    d = produto(pid); fd2 = d["full_data"]; esperado_mudar = {"category_id"} if nova_cat else set()
    if img: esperado_mudar |= {"image_url", "image_bank_id", "image_bank_name"}
    mudou = {k: (fd.get(k), fd2.get(k)) for k in set(fd) | set(fd2) if fd.get(k) != fd2.get(k)}
    print("campos que mudaram:", {k: v for k, v in mudou.items()})
    fora = [k for k in mudou if k not in esperado_mudar]
    print("ativo:", p["is_active"], "->", d["is_active"], "| preço:", p["price"], "->", d["price"], "| mudou sem pedir:", fora or "nada")
    if fora or p["is_active"] != d["is_active"] or p["price"] != d["price"]: raise SystemExit("PAREI: conferir o produto")
    print("modo: GRAVAR | ok")
