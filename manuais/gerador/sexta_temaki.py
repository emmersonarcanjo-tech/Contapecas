"""Sexta do Temaki automática no ALIV (pedido do Emerson em 13/11/2026), sem trocar preço toda sexta.

Como fica:
  - Para cada temaki normal existe um produto "da sexta" a R$ 24,90, na categoria SEXTA DO TEMAKI NA TILI, com disponibilidade
    só na sexta (00:00–23:59), a mesma ficha técnica, a mesma foto e o "preço de" igual ao preço normal.
  - Os temakis normais ficam disponíveis todos os dias MENOS sexta (somem sozinhos na sexta e voltam no sábado).
  - Os 4 temakis que entravam na categoria da sexta saem dela e voltam a ter o preço do QR de indicação certo (preço + 10%).
Usa só o recurso de Disponibilidade do próprio ALIV (o mesmo da Quarta Maluca). Não mexe em iFood.

  python3 sexta_temaki.py                 mostra o que faria (dry-run) e grava o plano em JSON (2º argumento opcional)
  python3 sexta_temaki.py --gravar        cria os produtos da sexta e ajusta os normais; para no primeiro problema
  python3 sexta_temaki.py --desfazer [--gravar]   normais voltam a aparecer todos os dias (e à categoria da sexta) e os da sexta são desativados
"""
import sys, os, json, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR, DESFAZER = "--gravar" in sys.argv, "--desfazer" in sys.argv
PLANO = next((a for a in sys.argv[1:] if a.endswith(".json")), None)
PRECO, CAT_SEXTA, SUFIXO = 24.90, 1006, " (Sexta)"
NORMAIS = [11688, 11689, 11686, 11683, 11679, 11676, 11684, 11677, 11678]   # Atum, Hot, Salmão grelhado, Salmão, Capão, Tailandês, Filadélfia, Camarão Cozido, Camarão Empanado
SEXTA = [{"start": "00:00", "end": "23:59", "days": [4]}]                     # 0=segunda ... 4=sexta ... 6=domingo
MENOS_SEXTA = [{"start": "00:00", "end": "23:59", "days": [0, 1, 2, 3, 5, 6]}]
COPIA = "/workspace/Contapecas/manuais/aliv_backup/temakis_antes_da_sexta_automatica_2026-11-13.json"
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
b = lambda v: "true" if v else "false"

def parar(msg): print("PAREI:", msg); sys.exit(1)
def enviar(f):
    st, r = api._send(f())
    if st == 401: api.login(); st, r = api._send(f())
    return st, r
def multipart(campos, path):
    def f():
        bd = uuid.uuid4().hex
        corpo = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in campos.items()) + f"--{bd}--\r\n"
        return urllib.request.Request(BASE_URL + path, data=corpo.encode(), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"})
    return enviar(f)
def post(path, data):
    return enviar(lambda: urllib.request.Request(BASE_URL + path, data=urllib.parse.urlencode(data).encode(), method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}))
def cardapio():
    out = {}
    for c in api.get("/admin/api/menu/full_data")["categories"]:
        for p in c["products"]: out.setdefault(p["id"], p)
    return out
def ficha(pid): return api.get(f"/admin/menu/product/{pid}/recipes")
def custo(l): return sum(x["total_cost"] for x in l)
def nome_sexta(nome): return nome.replace(" ( 01 Un )", "").strip() + SUFIXO

def campos_de(p, **troca):
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
    c.update(troca); return c

def conferir_mudanca(antes, depois, esperado):
    a, d = antes["full_data"], depois["full_data"]
    mudou = {k for k in set(a) | set(d) if a.get(k) != d.get(k)}
    fora = sorted(mudou - set(esperado))
    if fora or antes["is_active"] != depois["is_active"] or antes["price"] != depois["price"]:
        parar(f"{a['name']}: mudou o que não devia: {fora} | ativo {antes['is_active']}->{depois['is_active']} | preço {antes['price']}->{depois['price']}")

card = cardapio(); plano = []
for pid in NORMAIS:
    p = card.get(pid)
    if not p: parar(f"temaki {pid} não está no cardápio")
    fd = p["full_data"]; cfg = fd.get("config") or {}; f = ficha(pid)
    if not f: parar(f"{p['name']}: sem ficha técnica")
    ns = nome_sexta(p["name"]); irmao = next((q for q in card.values() if q["name"] == ns), None)
    adic = [x for x in (cfg.get("additional_categories") or []) if x != CAT_SEXTA]
    canais = dict(fd.get("channel_prices") or {})
    if "indicacao" in canais: canais["indicacao"] = round(p["price"] * 1.10, 2)
    plano.append({"id": pid, "nome": p["name"], "preco": p["price"], "ativo": p["is_active"], "custo": round(custo(f), 4),
                  "ficha": [{"ingredient_id": l["ingredient_id"], "ingrediente": l["ingredient_raw_name"], "quantity": l["quantity"]} for l in f],
                  "regras_hoje": fd.get("schedule_rules") or [], "adicionais_hoje": cfg.get("additional_categories") or [], "adicionais_novo": adic,
                  "canais_hoje": fd.get("channel_prices") or {}, "canais_novo": canais,
                  "sexta": {"nome": ns, "id": irmao["id"] if irmao else None, "preco": PRECO, "preco_de": p["price"], "indicacao": round(PRECO * 1.10, 2)}})
print(f"{'temaki normal':36s} {'preço':>6s} {'custo':>6s} | produto da sexta (R$ {PRECO:.2f})            | normal: disponibilidade / categoria extra / QR indicação")
for x in plano:
    print(f"{x['nome'][:36]:36s} {x['preco']:6.2f} {x['custo']:6.2f} | {x['sexta']['nome'][:34]:34s} {'já existe ' + str(x['sexta']['id']) if x['sexta']['id'] else 'criar':>14s} | "
          f"{'já ok' if x['regras_hoje'] == MENOS_SEXTA else 'todos os dias -> menos sexta'} / {x['adicionais_hoje']} -> {x['adicionais_novo']} / {x['canais_hoje'].get('indicacao')} -> {x['canais_novo'].get('indicacao')}")
if PLANO: json.dump(plano, open(PLANO, "w"), ensure_ascii=False, indent=1)

if DESFAZER:
    if not os.path.exists(COPIA): parar("não achei a cópia de segurança")
    orig = {x["id"]: x for x in json.load(open(COPIA))}
    for x in plano:
        o = orig[x["id"]]
        print("voltaria" if not GRAVAR else "voltando", x["nome"], "-> todos os dias, categorias", o["adicionais_hoje"], "| QR", o["canais_hoje"].get("indicacao"), "| e desativaria", x["sexta"]["nome"])
        if not GRAVAR: continue
        p = card[x["id"]]
        st, r = multipart(campos_de(p, schedule_rules_json=json.dumps(o["regras_hoje"]), channel_prices_json=json.dumps(o["canais_hoje"]),
                  config_json=json.dumps({"additional_categories": o["adicionais_hoje"], "allowed_addons": (p["full_data"].get("config") or {}).get("allowed_addons") or [], "blocked_addons": (p["full_data"].get("config") or {}).get("blocked_addons") or []})), "/admin/menu/product/save")
        if st != 200: parar(f"{x['nome']}: não salvou ({st})")
        s = card.get(x["sexta"]["id"]) if x["sexta"]["id"] else None
        if s and s["is_active"]:
            st, r = enviar(lambda: urllib.request.Request(BASE_URL + f"/admin/menu/product/{s['id']}/toggle-status", method="POST", headers={"Accept": "application/json"}))
            if st != 200: parar(f"{s['name']}: não desativou ({st})")
    print("modo:", "GRAVAR" if GRAVAR else "dry-run"); sys.exit()

if not GRAVAR:
    print("modo: dry-run (nada gravado)"); sys.exit()
if not os.path.exists(COPIA):
    json.dump(plano, open(COPIA, "w"), ensure_ascii=False, indent=1)

for x in plano:
    p = card[x["id"]]; fd = p["full_data"]
    # 1) produto da sexta
    if x["sexta"]["id"] is None:
        c = campos_de(p, name=x["sexta"]["nome"], category_id=CAT_SEXTA, price=f"{PRECO:.2f}", compare_at_price=f"{p['price']:.2f}",
                      channel_prices_json=json.dumps({"indicacao": x["sexta"]["indicacao"]}), schedule_rules_json=json.dumps(SEXTA), pausa_horario_ligada="false",
                      config_json=json.dumps({"additional_categories": [], "allowed_addons": (fd.get("config") or {}).get("allowed_addons") or [], "blocked_addons": (fd.get("config") or {}).get("blocked_addons") or []}))
        c.pop("prod_id"); c.pop("external_code", None); c.pop("barcode", None)
        st, r = multipart(c, "/admin/menu/product/save")
        if st != 200: parar(f"{x['sexta']['nome']}: não criou ({st} {str(r)[:120]})")
        card = cardapio(); s = next((q for q in card.values() if q["name"] == x["sexta"]["nome"]), None)
        if not s: parar(f"{x['sexta']['nome']}: não apareceu no cardápio")
        x["sexta"]["id"] = s["id"]
    sid = x["sexta"]["id"]; tem = {l["ingredient_id"] for l in ficha(sid)}
    for l in x["ficha"]:
        if l["ingredient_id"] in tem: continue
        st, r = post("/admin/menu/recipe/save", {"product_id": sid, "ingredient_id": l["ingredient_id"], "quantity": f"{l['quantity']:.6f}"})
        if st != 200: parar(f"{x['sexta']['nome']}: não gravou a linha {l['ingrediente']} ({st})")
    s = cardapio()[sid]; sf = s["full_data"]; fs = ficha(sid)
    if not (abs(s["price"] - PRECO) < 0.001 and sf["category_id"] == CAT_SEXTA and sf.get("schedule_rules") == SEXTA and abs(custo(fs) - x["custo"]) < 0.001
            and len(fs) == len(x["ficha"]) and s["channel_prices"].get("indicacao") == x["sexta"]["indicacao"] and s["is_active"]):
        parar(f"{x['sexta']['nome']}: não ficou como o plano (preço {s['price']}, categoria {sf['category_id']}, regras {sf.get('schedule_rules')}, custo {custo(fs):.4f}, ativo {s['is_active']})")
    # 2) temaki normal: todos os dias menos sexta, fora da categoria da sexta, QR de indicação certo
    if not (fd.get("schedule_rules") == MENOS_SEXTA and x["adicionais_hoje"] == x["adicionais_novo"] and x["canais_hoje"] == x["canais_novo"]):
        st, r = multipart(campos_de(p, schedule_rules_json=json.dumps(MENOS_SEXTA), channel_prices_json=json.dumps(x["canais_novo"]),
                  config_json=json.dumps({"additional_categories": x["adicionais_novo"], "allowed_addons": (fd.get("config") or {}).get("allowed_addons") or [], "blocked_addons": (fd.get("config") or {}).get("blocked_addons") or []})), "/admin/menu/product/save")
        if st != 200: parar(f"{x['nome']}: não salvou ({st} {str(r)[:120]})")
        d = cardapio()[x["id"]]
        conferir_mudanca(p, d, {"schedule_rules", "channel_prices", "config", "pausa_horario"})
        if d["full_data"].get("schedule_rules") != MENOS_SEXTA: parar(f"{x['nome']}: a disponibilidade não gravou")
        if abs(custo(ficha(x["id"])) - x["custo"]) > 0.001: parar(f"{x['nome']}: o custo da ficha mudou")
    print(f"ok {x['nome'][:34]:34s} -> menos sexta | {x['sexta']['nome'][:30]:30s} id {sid} R$ {PRECO:.2f} (de R$ {p['price']:.2f}) custo R$ {custo(fs):.4f} só na sexta")
print("modo: GRAVAR | ok")
