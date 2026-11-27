"""Site (App Delivery do ALIV) só com o aviso do dia — pedido do Emerson em 27/11/2026 (Black Friday só no salão):
"cria um card em Destaques com o cartaz da Black, 'não tem delivery, somente no salão', e desativa todos os outros,
para o cliente ver o que está acontecendo quando entrar".

O que faz (só no canal "App Delivery"; PDV, garçom, totem e IA NÃO mudam; nada é pausado nem apagado):
  1. cria (ou reaproveita) a categoria do aviso, visível só no App Delivery, em primeiro lugar;
  2. cria (ou reaproveita) o card do aviso nessa categoria, com a imagem, preço R$ 0,00, marcado como destaque;
  3. esconde do App Delivery todas as outras categorias que estavam visíveis lá (guarda a lista para voltar).
Como só sobra um card de R$ 0,00 e o pedido mínimo do site é maior que isso, ninguém consegue fechar pedido pelo site.

  python3 site_so_black.py aplicar <imagem.jpg> [--gravar]
  python3 site_so_black.py voltar [--gravar]        mostra de novo as categorias e esconde a do aviso
Sem --gravar só mostra o que faria.
"""
import sys, os, json, uuid, mimetypes, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
args = [a for a in sys.argv[1:] if a != "--gravar"]; GRAVAR = "--gravar" in sys.argv[1:]
if not args or args[0] not in ("aplicar", "voltar") or (args[0] == "aplicar" and len(args) != 2): print(__doc__); sys.exit(2)
ACAO = args[0]
CAT_NOME = "🖤 HOJE: BLACK FRIDAY SÓ NO SALÃO (sem delivery)"
PROD_NOME = "HOJE: SÓ NO SALÃO, SEM DELIVERY"
PROD_DESC = ("Hoje, sexta 27/11, não temos delivery nem retirada. Vem comer com a gente no salão: Temaki Hot R$ 19,90, "
             "demais temakis R$ 24,90 e peças no buffet a partir de R$ 1,99 cada, enquanto durar o estoque.")
MODELO = 935                                                                   # categoria Temaki: copia NCM/CFOP/unidade
BK = "/workspace/Contapecas/manuais/aliv_backup/site_so_black_2026-11-27.json"
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login(); api.timeout = max(getattr(api, "timeout", 0) or 0, 120)
b = lambda v: "true" if v else "false"
def parar(m): print("PAREI:", m); sys.exit(1)
def falhou(st, r): return st != 200 or (isinstance(r, dict) and r.get("success") is False)
def multipart(pares, path, metodo="POST", arquivo=None):
    def f():
        bd = uuid.uuid4().hex; corpo = b""
        for k, v in pares: corpo += f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        if arquivo:
            campo, caminho = arquivo; tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
            corpo += f'--{bd}\r\nContent-Disposition: form-data; name="{campo}"; filename="{os.path.basename(caminho)}"\r\nContent-Type: {tipo}\r\n\r\n'.encode() + open(caminho, "rb").read() + b"\r\n"
        corpo += f"--{bd}--\r\n".encode()
        return urllib.request.Request(BASE_URL + path, data=corpo, method=metodo, headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"})
    st, r = api._send(f())
    if st == 401: api.login(); st, r = api._send(f())
    return st, r
def categorias():
    r = api.get("/admin/api/categories"); return {c["id"]: c for c in (r.get("categories", r) if isinstance(r, dict) else r)}
def produtos():
    out = {}
    for c in api.get("/admin/api/menu/full_data")["categories"]:
        for p in c["products"]: out.setdefault(p["id"], p)
    return out
def campos_categoria(c):
    f = [("name", c["name"]), ("order_index", str(c.get("order_index") or 0))]
    if c.get("sector_id") is not None: f.append(("sector_id", str(c["sector_id"])))
    if c.get("target_printer") is not None: f.append(("target_printer", c["target_printer"]))
    f += [("allow_employee_discount", b(c["allow_employee_discount"])), ("print_separate_ticket", b(c["print_separate_ticket"]))]
    if c.get("print_highlight") is not None: f.append(("print_highlight", b(c["print_highlight"])))
    f += [("show_in_kiosk", b(c["show_in_kiosk"])), ("show_in_pdv", b(c["show_in_pdv"])), ("show_in_waiter", b(c["show_in_waiter"]))]
    if c.get("show_in_ia") is not None: f.append(("show_in_ia", b(c["show_in_ia"])))
    f += [("show_in_delivery", b(c["show_in_delivery"])), ("menu_ids_json", json.dumps(c.get("menu_ids") or [])),
          ("show_in_orders_board", b(c.get("show_in_orders_board"))), ("show_in_print_menu", b(c.get("show_in_print_menu") is not False)),
          ("is_checkout_offer", b(c.get("is_checkout_offer"))), ("schedule_rules", json.dumps(c.get("schedule_rules") or []))]
    for k in ("ncm", "cfop", "uom", "cest", "icms_cst", "ibs_cbs_cst", "ibs_cbs_class_trib", "icms_origem", "icms_aliquota", "pis_cst", "pis_aliquota", "cofins_cst", "cofins_aliquota", "cbenef"):
        if c.get(k) is not None: f.append((k, str(c[k])))
    if c.get("image_bank_id") is not None: f.append(("image_bank_id", str(c["image_bank_id"])))
    elif c.get("image_url") is not None: f.append(("image_url", c["image_url"]))
    return f
def delivery(cid, mostra):
    """Liga ou desliga a categoria só no App Delivery e confere que nada mais mudou."""
    antes = categorias()[cid]
    if antes["show_in_delivery"] == mostra: return
    st, r = multipart(campos_categoria(dict(antes, show_in_delivery=mostra)), f"/admin/api/categories/{cid}", metodo="PUT")
    if falhou(st, r): parar(f"categoria {cid} '{antes['name']}': não salvou ({st} {str(r)[:120]})")
    dep = categorias()[cid]; fora = sorted(k for k in set(antes) | set(dep) if antes.get(k) != dep.get(k) and k != "show_in_delivery")
    if dep["show_in_delivery"] != mostra or fora: parar(f"categoria {cid} '{antes['name']}': não ficou como o plano (mudou também {fora})")
    print(f"   categoria {cid} '{antes['name'][:38]}': App Delivery {antes['show_in_delivery']} -> {mostra} | resto igual")

cats = categorias(); aviso = next((c for c in cats.values() if c["name"] == CAT_NOME), None)
print("agora:", datetime.now(ZoneInfo("America/Bahia")).strftime("%a %d/%m/%Y %H:%M"), "| ação:", ACAO, "|", "GRAVAR" if GRAVAR else "dry-run")
if ACAO == "aplicar":
    img = os.path.abspath(args[1])
    if not os.path.exists(img): parar("imagem não encontrada")
    esconder = [c for c in sorted(cats.values(), key=lambda c: (c["order_index"], c["id"])) if c["show_in_delivery"] and c["name"] != CAT_NOME]
    card = next((p for p in produtos().values() if p["name"] == PROD_NOME), None)
    print("categoria do aviso:", f"já existe (id {aviso['id']})" if aviso else "criar", "| card:", f"já existe (id {card['id']})" if card else "criar", "| imagem:", os.path.basename(img))
    print(f"esconder do App Delivery ({len(esconder)}):", ", ".join(f"{c['id']} {c['name'][:22]}" for c in esconder))
    if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
    d = json.load(open(BK, encoding="utf-8")) if os.path.exists(BK) else {}
    d.setdefault("quando", datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes")); d.setdefault("escondidas", [c["id"] for c in esconder])
    json.dump(d, open(BK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 1) categoria do aviso
    if not aviso:
        mod = cats[MODELO]
        pares = [("name", CAT_NOME), ("order_index", "0"), ("allow_employee_discount", "false"), ("print_separate_ticket", "false"), ("print_highlight", "false"),
                 ("show_in_kiosk", "false"), ("show_in_pdv", "false"), ("show_in_waiter", "false"), ("show_in_ia", "false"), ("show_in_delivery", "true"),
                 ("menu_ids_json", "[]"), ("show_in_orders_board", "false"), ("show_in_print_menu", "false"), ("is_checkout_offer", "false"), ("schedule_rules", "[]")]
        for k in ("ncm", "cfop", "uom"):
            if mod.get(k): pares.append((k, mod[k]))
        st, r = multipart(pares, "/admin/api/categories"); print("criar categoria:", st, str(r)[:160])
        if falhou(st, r): parar("não criou a categoria do aviso")
        cats = categorias(); aviso = next((c for c in cats.values() if c["name"] == CAT_NOME), None)
        if not aviso: parar("a categoria do aviso não apareceu")
        ordem = [aviso["id"]] + [c["id"] for c in sorted(cats.values(), key=lambda c: (c["order_index"], c["id"])) if c["id"] != aviso["id"]]
        st, r = multipart([("cat_ids", ",".join(map(str, ordem)))], "/admin/api/categories/reorder"); print("pôr em primeiro:", st, str(r)[:100])
    else: delivery(aviso["id"], True)
    d["categoria_aviso"] = aviso["id"]; json.dump(d, open(BK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 2) card do aviso
    if not card:
        mod = cats[MODELO]
        pares = [("name", PROD_NOME), ("description", PROD_DESC), ("category_id", str(aviso["id"])), ("price", "0.00"), ("price_in_points", "0"), ("channel_prices_json", "{}"),
                 ("allows_flavors", "false"), ("max_flavors", "1"), ("is_pizza", "false"), ("auto_disable_on_stock_zero", "false"), ("sold_by_weight", "false"),
                 ("kitchen_alert_active", "false"), ("kitchen_alert_text", ""), ("ncm", mod.get("ncm") or ""), ("cfop", mod.get("cfop") or ""), ("uom", mod.get("uom") or ""),
                 ("show_in_kiosk", "false"), ("show_in_pdv", "false"), ("show_in_waiter", "false"), ("show_in_ia", "false"), ("show_in_delivery", "true"), ("show_in_print_menu", "false"),
                 ("menu_ids_json", "[]"), ("schedule_rules_json", "[]"), ("size_prices_json", "[]"), ("config_json", json.dumps({"additional_categories": [], "allowed_addons": [], "blocked_addons": []}))]
        st, r = multipart(pares, "/admin/menu/product/save", arquivo=("image_file", img)); print("criar card:", st, str(r)[:160])
        if falhou(st, r): parar("não criou o card do aviso")
        card = next((p for p in produtos().values() if p["name"] == PROD_NOME), None)
        if not card: parar("o card não apareceu no cardápio")
    fd = card["full_data"]; print(f"   card id {card['id']} | ativo {card['is_active']} | preço {card['price']} | imagem {'ok' if fd.get('image_url') else 'SEM IMAGEM'} | destaque {fd.get('is_highlighted')} | canais: delivery {fd.get('show_in_delivery')}, pdv {fd.get('show_in_pdv')}, totem {fd.get('show_in_kiosk')}, garçom {fd.get('show_in_waiter')}, ia {fd.get('show_in_ia')}")
    if not fd.get("is_highlighted"):
        st, r = multipart([], f"/admin/menu/product/{card['id']}/toggle-highlight"); print("marcar como destaque:", st, str(r)[:100])
        card = produtos()[card["id"]]
        if not card["full_data"].get("is_highlighted"): parar("o card não ficou como destaque")
    d["card"] = card["id"]; json.dump(d, open(BK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 3) esconder as outras categorias do App Delivery
    for c in esconder: delivery(c["id"], False)
    cats = categorias(); visiveis = [c["name"] for c in cats.values() if c["show_in_delivery"] and c["is_active"]]
    print("visíveis no App Delivery agora:", visiveis)
    if visiveis != [CAT_NOME]: parar("sobrou categoria visível no App Delivery")
    print("modo: GRAVAR | ok")
else:
    if not os.path.exists(BK): parar(f"não achei o registro {BK}")
    d = json.load(open(BK, encoding="utf-8"))
    print(f"voltariam a aparecer no App Delivery ({len(d['escondidas'])}):", ", ".join(f"{i} {cats[i]['name'][:22]}" for i in d["escondidas"] if i in cats), "| categoria do aviso", d.get("categoria_aviso"), "sairia do App Delivery")
    if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
    for i in d["escondidas"]:
        if i in cats: delivery(i, True)
    if d.get("categoria_aviso") in cats: delivery(d["categoria_aviso"], False)
    cats = categorias(); falta = [i for i in d["escondidas"] if i in cats and not cats[i]["show_in_delivery"]]
    print("visíveis no App Delivery agora:", len([c for c in cats.values() if c["show_in_delivery"] and c["is_active"]]), "| faltou voltar:", falta or "nenhuma")
    if falta: parar("alguma categoria não voltou")
    print("modo: GRAVAR | ok")
