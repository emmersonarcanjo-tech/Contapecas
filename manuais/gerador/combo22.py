"""Cadastra no ALIV o "Combo 22 Peças" (aprovado pelo Emerson em 12/11/2026): R$ 59,90, categoria Combos, com ficha técnica.
4 niguiri salmão, 2 Joy Fila, 4 hossomaki Fila, 4 hossomaki salmão grelhado, 4 uramaki Fila, 4 uramaki salmão grelhado.
A ficha é a soma dos ingredientes das peças (fichas dos produtos no ALIV); itens produzidos "(unidade)" são abertos na receita.
Os campos de exibição e fiscais (NCM, CFOP, unidade) copiam o Combinado Salmão 15 Peças. Não mexe em iFood.
Uso: python3 combo22.py [--gravar]   (sem --gravar só mostra)"""
import sys, os, json, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR = "--gravar" in sys.argv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
NOME, PRECO, MODELO = "Combo 22 Peças", 59.90, 11697
DESCRICAO = "4 niguiri salmão, 2 Joy Fila, 4 hossomaki Fila, 4 hossomaki salmão grelhado, 4 uramaki Fila, 4 uramaki salmão grelhado"
PECAS = [(11646, 4, 4, "niguiri salmão"), (11632, 2, 2, "Joy Fila"), (11664, 4, 10, "hossomaki Fila"), (11667, 4, 10, "hossomaki salmão grelhado"),
         (11660, 4, 10, "uramaki Fila"), (11651, 4, 10, "uramaki salmão grelhado")]            # (produto, peças no combo, peças do produto, nome)

inv = api.get("/admin/inventory/api/ingredients")["ingredients"]
ING = {i["id"]: i for i in inv}; ITEM = {i["id"]: i for i in inv if i.get("is_recipe")}
ID_POR_NOME = {}
for i in inv:
    ID_POR_NOME[i["name"]] = i["id"]
    if i.get("display_name"): ID_POR_NOME.setdefault(i["display_name"], i["id"])

def ficha(pid): return api.get(f"/admin/menu/product/{pid}/recipes")
def linhas_diretas(pid):
    out = {}
    for r in ficha(pid):
        if r["ingredient_id"] in ITEM:
            rend = ITEM[r["ingredient_id"]].get("final_yield") or 1
            for l in api.get(f"/admin/inventory/ingredient/{r['ingredient_id']}/recipe"):
                cid = ID_POR_NOME.get(l["child_name"])
                if cid is None: raise SystemExit(f"não achei o insumo '{l['child_name']}'")
                out[cid] = out.get(cid, 0) + r["quantity"] * l["qty"] / rend
        else:
            out[r["ingredient_id"]] = out.get(r["ingredient_id"], 0) + r["quantity"]
    return out

soma = {}; custo_pecas = 0
for pid, n, total, nome in PECAS:
    c = 0
    for iid, q in linhas_diretas(pid).items():
        qq = q * n / total; soma[iid] = soma.get(iid, 0) + qq; c += qq * ING[iid]["cost"] / (ING[iid].get("conversion_factor") or 1)
    custo_pecas += c
    print(f"  {n} {nome:28s} R$ {c:.4f}")
alvo = {iid: round(q, 6) for iid, q in soma.items()}
esperado = sum(q * ING[iid]["cost"] / (ING[iid].get("conversion_factor") or 1) for iid, q in alvo.items())
print(f"custo esperado da ficha: R$ {esperado:.4f} (soma das peças R$ {custo_pecas:.4f}) | {len(alvo)} ingredientes")
for iid, q in sorted(alvo.items(), key=lambda x: -x[1] * ING[x[0]]["cost"]):
    print(f"     {ING[iid]['name'][:44]:44s} {q:.6f} {ING[iid]['unit']}  R$ {q*ING[iid]['cost']:.4f}")

def produtos():
    return {p["id"]: (p, c) for c in api.get("/admin/api/menu/full_data")["categories"] for p in c["products"]}
todos = produtos(); mod = todos[MODELO][0]["full_data"]
existente = next((p for p, _ in todos.values() if p["name"] == NOME), None)
b = lambda v: "true" if v else "false"
campos = {"name": NOME, "description": DESCRICAO, "category_id": mod["category_id"], "price": f"{PRECO:.2f}", "price_in_points": 0,
          "channel_prices_json": json.dumps({"indicacao": round(PRECO * 1.10, 2)}), "allows_flavors": "false", "max_flavors": 1, "is_pizza": "false",
          "auto_disable_on_stock_zero": "false", "sold_by_weight": "false", "kitchen_alert_active": "false", "kitchen_alert_text": "",
          "ncm": mod.get("ncm") or "", "cfop": mod.get("cfop") or "", "uom": mod.get("uom") or "",
          "show_in_kiosk": b(mod.get("show_in_kiosk")), "show_in_pdv": b(mod.get("show_in_pdv")), "show_in_waiter": b(mod.get("show_in_waiter")),
          "show_in_ia": b(mod.get("show_in_ia")), "show_in_delivery": b(mod.get("show_in_delivery")), "show_in_print_menu": b(mod.get("show_in_print_menu", True)),
          "menu_ids_json": json.dumps(mod.get("menu_ids") or []), "schedule_rules_json": "[]", "size_prices_json": "[]",
          "config_json": json.dumps({"additional_categories": [], "allowed_addons": [], "blocked_addons": []})}
print("produto:", "JÁ EXISTE id " + str(existente["id"]) if existente else "novo", "|", {k: campos[k] for k in ("name", "price", "category_id", "channel_prices_json", "ncm", "cfop", "uom", "show_in_pdv", "show_in_delivery", "show_in_kiosk", "show_in_waiter", "show_in_ia")})
if not GRAVAR:
    print("modo: dry-run (nada gravado)"); sys.exit()
if not existente:
    bd = uuid.uuid4().hex
    body = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in campos.items()) + f"--{bd}--\r\n"
    st, r = api._send(urllib.request.Request(BASE_URL + "/admin/menu/product/save", data=body.encode(), method="POST",
                      headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))
    print("criar produto:", st, str(r)[:200])
    if st != 200: raise SystemExit("PAREI: não criou o produto")
    existente = next((p for p, _ in produtos().values() if p["name"] == NOME), None)
    if not existente: raise SystemExit("PAREI: produto não apareceu no cardápio")
pid = existente["id"]; atuais = {l["ingredient_id"]: l for l in ficha(pid)}
for iid, q in alvo.items():
    if iid in atuais: continue
    st, r = api._send(urllib.request.Request(BASE_URL + "/admin/menu/recipe/save", method="POST",
        data=urllib.parse.urlencode({"product_id": pid, "ingredient_id": iid, "quantity": f"{q:.6f}"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}))
    if st != 200: raise SystemExit(f"PAREI: não gravou a linha {ING[iid]['name']} ({st})")
f = ficha(pid); tot = sum(l["total_cost"] for l in f)
dif = [(ING[i]["name"], alvo[i], atuais_q) for i, atuais_q in ((l["ingredient_id"], l["quantity"]) for l in f) if abs(alvo.get(i, -1) - atuais_q) > 1e-6]
print(f"produto {pid}: ficha com {len(f)} linhas, custo R$ {tot:.4f} (esperado R$ {esperado:.4f}) | linhas diferentes do plano: {dif or 'nenhuma'}")
if len(f) != len(alvo) or abs(tot - esperado) > 0.005 or dif: raise SystemExit("PAREI: ficha não confere")
print("modo: GRAVAR | ok")
