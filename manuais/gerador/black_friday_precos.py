"""Preços da Black Friday no salão, SÓ no dia (pedido do Emerson em 27/11/2026): Temaki Hot a R$ 19,90 e peças do buffet
"como na Quarta Maluca" (a partir de R$ 1,99). Não mexe em iFood.

O que faz, cada parte com o seu "voltar":
  hot      promoção própria do ALIV "Black Friday - Temaki Hot", preço final R$ 19,90, só na data (começa e termina no mesmo dia),
           só nos canais do salão (PDV, garçom e totem). Acaba sozinha à meia-noite; o "voltar" só desliga.
           Se a "Sexta do Temaki" (R$ 24,90) ganhar da nova no PDV, tira o Temaki Hot dela só hoje (o "voltar" recoloca).
  pecas    faz a sexta valer como quarta para as peças do buffet:
           - produto "QUARTA MALUCA" (R$ 1,99) aparece no PDV também na sexta;
           - totem: categoria "Buffet por peça (totem) — quarta" (R$ 1,99) aparece na sexta e a "— dias normais" (R$ 2,99) some na sexta.
           O "voltar" devolve as regras de dia da semana ao que eram (obrigatório no dia seguinte, senão toda sexta fica assim).

  python3 black_friday_precos.py hot|pecas            mostra o que faria (dry-run)
  python3 black_friday_precos.py hot|pecas --gravar   grava, relê e confere; guarda o "antes" em manuais/aliv_backup
  python3 black_friday_precos.py voltar [--gravar]    desfaz tudo o que o "antes" registrou
"""
import sys, os, json, uuid, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
args = [a for a in sys.argv[1:] if a != "--gravar"]; GRAVAR = "--gravar" in sys.argv[1:]
if len(args) != 1 or args[0] not in ("hot", "pecas", "voltar"): print(__doc__); sys.exit(2)
ACAO = args[0]
HOJE = datetime.now(ZoneInfo("America/Bahia")); DIA = HOJE.weekday()          # 0=segunda ... 4=sexta
DATA = os.environ.get("BLACK_DATA", "2026-11-27")                             # o dia da promoção
BK = f"/workspace/Contapecas/manuais/aliv_backup/black_friday_precos_{DATA}.json"
HOT, PRECO_HOT, NOME_HOT, SEXTA_TEMAKI = 11689, 19.90, "Black Friday - Temaki Hot", 618
PROD_QUARTA, CAT_QUARTA, CAT_NORMAL, QUARTA = 12154, 2833, 2832, 2
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
b = lambda v: "true" if v else "false"
def parar(m): print("PAREI:", m); sys.exit(1)
def bk_ler(): return json.load(open(BK, encoding="utf-8")) if os.path.exists(BK) else {}
def bk_gravar(d): json.dump(d, open(BK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def multipart(pares, path, metodo="POST"):
    def f():
        bd = uuid.uuid4().hex
        corpo = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in pares) + f"--{bd}--\r\n"
        return urllib.request.Request(BASE_URL + path, data=corpo.encode(), method=metodo, headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"})
    st, r = api._send(f())
    if st == 401: api.login(); st, r = api._send(f())
    return st, r
def cardapio():
    out = {}
    for c in api.get("/admin/api/menu/full_data")["categories"]:
        for p in c["products"]: out.setdefault(p["id"], p)
    return out
def pdv(): return {p["id"]: p for p in api.get("/admin/api/pdv/data")["products"]}
def promos(): return api.get("/admin/api/promotions/data").get("promotions", [])
def categorias():
    r = api.get("/admin/api/categories"); return {c["id"]: c for c in (r.get("categories", r) if isinstance(r, dict) else r)}

def salvar_promo(p):
    """p: dicionário da promoção como a lista devolve (com ou sem id)."""
    pares = ([("promo_id", p["id"])] if p.get("id") else []) + [("name", p["name"]), ("promo_type", p["promo_type"]), ("value", f"{float(p['value']):.2f}"),
            ("usage_limit", str(p.get("usage_limit") or 0)), ("start_date", p["start_date"]), ("end_date", p["end_date"]), ("target_type", p["target_type"])] + [
            ("days[]", str(d)) for d in p.get("days") or []] + [("prod_ids[]", str(i)) for i in p.get("target_ids") or []] + [
            ("show_in_kiosk", b(p.get("show_in_kiosk"))), ("show_in_pdv", b(p.get("show_in_pdv"))), ("show_in_waiter", b(p.get("show_in_waiter"))),
            ("show_in_delivery", b(p.get("show_in_delivery"))), ("show_in_ia", b(p.get("show_in_ia"))), ("payment_condition", p.get("payment_condition") or ""),
            ("menu_ids_json", json.dumps(p.get("menu_ids") or []))]
    if p.get("start_time"): pares.append(("start_time", p["start_time"]))
    if p.get("end_time"): pares.append(("end_time", p["end_time"]))
    st, r = multipart(pares, "/admin/promotions/save")
    if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar(f"promoção '{p['name']}' não foi salva ({st} {str(r)[:160]})")
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
def regras_produto(pid, regras):
    p = cardapio()[pid]; fd = p["full_data"]
    st, r = multipart(campos_produto(p, schedule_rules_json=json.dumps(regras)), "/admin/menu/product/save")
    if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar(f"{p['name']}: não salvou ({st} {str(r)[:160]})")
    d = cardapio()[pid]; n = d["full_data"]; fora = sorted(k for k in set(fd) | set(n) if fd.get(k) != n.get(k) and k != "schedule_rules")
    if n.get("schedule_rules") != regras or fora or p["is_active"] != d["is_active"] or p["price"] != d["price"]: parar(f"{p['name']}: não ficou como o plano (regras {n.get('schedule_rules')}, mudou também {fora})")
    print(f"   produto {pid} '{p['name']}': dias {dias(fd.get('schedule_rules'))} -> {dias(regras)} | resto igual")
def campos_categoria(c):
    s = b; f = [("name", c["name"]), ("order_index", str(c.get("order_index") or 0))]
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
def regras_categoria(cid, regras):
    antes = categorias()[cid]; novo = dict(antes, schedule_rules=regras)
    st, r = multipart(campos_categoria(novo), f"/admin/api/categories/{cid}", metodo="PUT")
    if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar(f"categoria {cid}: não salvou ({st} {str(r)[:160]})")
    depois = categorias()[cid]; fora = sorted(k for k in set(antes) | set(depois) if antes.get(k) != depois.get(k) and k != "schedule_rules")
    if depois.get("schedule_rules") != regras or fora: parar(f"categoria {cid}: não ficou como o plano (regras {depois.get('schedule_rules')}, mudou também {fora})")
    print(f"   categoria {cid} '{antes['name']}': dias {dias(antes.get('schedule_rules'))} -> {dias(regras)} | resto igual")
def dias(regras): return sorted({d for r in regras or [] for d in r.get("days") or []}) if regras else "todos"
def com_dia(regras, d): return [dict(r, days=sorted(set(r.get("days") or []) | {d})) for r in regras]
def sem_dia(regras, d): return [dict(r, days=sorted(set(r.get("days") or []) - {d})) for r in regras]

print(f"agora: {HOJE:%a %d/%m/%Y %H:%M} (Bahia) | dia da promoção: {DATA} | ação: {ACAO} | {'GRAVAR' if GRAVAR else 'dry-run'}")
if ACAO == "hot":
    card = cardapio(); p = card[HOT]; v = pdv().get(HOT); ps = promos()
    nova = next((x for x in ps if x.get("name") == NOME_HOT), None); sexta = next((x for x in ps if x.get("id") == SEXTA_TEMAKI), None)
    print(f"Temaki Hot: cadastro R$ {p['price']:.2f} | no PDV agora R$ {v['price'] if v else None} | promoção nova: {'já existe id ' + str(nova['id']) if nova else 'não existe'} | Sexta do Temaki tem o Hot: {HOT in (sexta or {}).get('target_ids', [])}")
    plano = {"name": NOME_HOT, "promo_type": "fixed_price", "value": PRECO_HOT, "usage_limit": 0, "start_date": DATA, "end_date": DATA, "target_type": "product",
             "days": [datetime.fromisoformat(DATA).weekday()], "target_ids": [HOT], "show_in_kiosk": True, "show_in_pdv": True, "show_in_waiter": True,
             "show_in_delivery": False, "show_in_ia": False, "payment_condition": "", "menu_ids": []}
    print("faria: criar/atualizar a promoção", json.dumps(plano, ensure_ascii=False))
    if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
    d = bk_ler(); d.setdefault("hot", {"sexta_do_temaki_antes": sexta, "quando": HOJE.isoformat(timespec="minutes")}); bk_gravar(d)
    if nova: plano["id"] = nova["id"]
    salvar_promo(plano); nova = next((x for x in promos() if x.get("name") == NOME_HOT), None)
    if not nova: parar("a promoção nova não apareceu na lista")
    if nova.get("is_active") is False: multipart([], f"/admin/promotions/{nova['id']}/toggle"); nova = next(x for x in promos() if x.get("id") == nova["id"])
    print("   promoção gravada:", json.dumps({k: nova.get(k) for k in ("id", "name", "promo_type", "value", "start_date", "end_date", "days", "target_ids", "is_active", "show_in_pdv", "show_in_waiter", "show_in_kiosk", "show_in_delivery", "show_in_ia")}, ensure_ascii=False))
    d = bk_ler(); d["hot"]["promo_nova_id"] = nova["id"]; bk_gravar(d)
    v = pdv().get(HOT); print(f"   PDV agora: Temaki Hot R$ {v['price']} (original {v.get('original_price')})")
    if datetime.fromisoformat(DATA).date() != HOJE.date(): print("   hoje não é o dia da promoção: o preço só aparece no dia"); sys.exit()
    if abs(v["price"] - PRECO_HOT) > 0.001:
        print("   a Sexta do Temaki ganhou da promoção nova: tirando o Temaki Hot dela só hoje")
        s2 = dict(sexta, target_ids=[i for i in sexta["target_ids"] if i != HOT]); salvar_promo(s2)
        d = bk_ler(); d["hot"]["tirou_hot_da_sexta"] = True; bk_gravar(d)
        s3 = next(x for x in promos() if x.get("id") == SEXTA_TEMAKI)
        fora = sorted(k for k in set(sexta) | set(s3) if sexta.get(k) != s3.get(k) and k != "target_ids")
        if sorted(s3["target_ids"]) != sorted(s2["target_ids"]) or fora: parar(f"Sexta do Temaki não ficou como o plano: {s3.get('target_ids')} {fora}")
        v = pdv().get(HOT); print(f"   PDV agora: Temaki Hot R$ {v['price']} (original {v.get('original_price')})")
        if abs(v["price"] - PRECO_HOT) > 0.001: parar("o Temaki Hot ainda não está a R$ 19,90 no PDV")
    outros = {i: pdv().get(i, {}).get("price") for i in sexta["target_ids"] if i != HOT}
    print("   demais temakis no PDV:", outros); print("modo: GRAVAR | ok")
elif ACAO == "pecas":
    card = cardapio(); cats = categorias(); p = card[PROD_QUARTA]; rq, rn, rp = cats[CAT_QUARTA].get("schedule_rules") or [], cats[CAT_NORMAL].get("schedule_rules") or [], p["full_data"].get("schedule_rules") or []
    alvo = datetime.fromisoformat(DATA).weekday()
    print(f"produto {PROD_QUARTA} '{p['name']}' R$ {p['price']:.2f}: dias {dias(rp)} -> {dias(com_dia(rp, alvo))} | no PDV agora: {PROD_QUARTA in pdv()}")
    print(f"categoria {CAT_QUARTA} '{cats[CAT_QUARTA]['name']}': dias {dias(rq)} -> {dias(com_dia(rq, alvo))}")
    print(f"categoria {CAT_NORMAL} '{cats[CAT_NORMAL]['name']}': dias {dias(rn)} -> {dias(sem_dia(rn, alvo))}")
    if not (rp and rq and rn): parar("alguma regra de dia está vazia; não é o cenário esperado")
    if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
    d = bk_ler(); d.setdefault("pecas", {"produto": {str(PROD_QUARTA): rp}, "categorias": {str(CAT_QUARTA): rq, str(CAT_NORMAL): rn}, "quando": HOJE.isoformat(timespec="minutes")}); bk_gravar(d)
    regras_produto(PROD_QUARTA, com_dia(rp, alvo)); regras_categoria(CAT_QUARTA, com_dia(rq, alvo)); regras_categoria(CAT_NORMAL, sem_dia(rn, alvo))
    v = pdv().get(PROD_QUARTA); print(f"   PDV agora: '{p['name']}' {'aparece a R$ ' + str(v['price']) if v else 'NÃO aparece'}")
    if alvo == DIA and not v: parar("o item de R$ 1,99 não apareceu no PDV")
    print("modo: GRAVAR | ok")
else:
    d = bk_ler()
    if not d: parar(f"não achei o registro {BK}")
    print("registro:", json.dumps({k: (list(v.keys()) if isinstance(v, dict) else v) for k, v in d.items()}, ensure_ascii=False))
    if "pecas" in d:
        card = cardapio(); cats = categorias()
        for pid, r in d["pecas"]["produto"].items(): print(f"   produto {pid}: dias {dias(card[int(pid)]['full_data'].get('schedule_rules'))} -> {dias(r)}")
        for cid, r in d["pecas"]["categorias"].items(): print(f"   categoria {cid}: dias {dias(cats[int(cid)].get('schedule_rules'))} -> {dias(r)}")
    if "hot" in d:
        ps = promos(); nova = next((x for x in ps if x.get("id") == d["hot"].get("promo_nova_id")), None); sexta = next(x for x in ps if x.get("id") == SEXTA_TEMAKI)
        print(f"   promoção nova: {'ligada' if nova and nova.get('is_active') else 'desligada ou não existe'} -> desligada | Sexta do Temaki com o Hot: {HOT in sexta['target_ids']} -> True")
    if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
    if "pecas" in d:
        for pid, r in d["pecas"]["produto"].items():
            if cardapio()[int(pid)]["full_data"].get("schedule_rules") != r: regras_produto(int(pid), r)
        for cid, r in d["pecas"]["categorias"].items():
            if categorias()[int(cid)].get("schedule_rules") != r: regras_categoria(int(cid), r)
    if "hot" in d:
        ps = promos(); nova = next((x for x in ps if x.get("id") == d["hot"].get("promo_nova_id")), None)
        if nova and nova.get("is_active"): multipart([], f"/admin/promotions/{nova['id']}/toggle"); print("   promoção nova desligada:", next(x for x in promos() if x.get("id") == nova["id"]).get("is_active") is False)
        sexta = next(x for x in ps if x.get("id") == SEXTA_TEMAKI); antes = d["hot"].get("sexta_do_temaki_antes") or {}
        if sorted(sexta["target_ids"]) != sorted(antes.get("target_ids") or sexta["target_ids"]):
            salvar_promo(dict(sexta, target_ids=antes["target_ids"])); s3 = next(x for x in promos() if x.get("id") == SEXTA_TEMAKI)
            print("   Sexta do Temaki de volta com os 9:", sorted(s3["target_ids"]) == sorted(antes["target_ids"]), "| ligada:", s3.get("is_active"))
    print("modo: GRAVAR | ok")
