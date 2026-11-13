"""Fecha a ficha de um produto para o cliente NÃO poder retirar ingredientes (pedido do Emerson em 13/11/2026).

No ALIV, cada ingrediente da ficha do produto aparece para o cliente como "Retirar ingredientes". Para tirar essa opção só
de um produto, a ficha vira um item produzido — "<produto> (ficha)" — com a mesma receita, rendimento 1 UN, auto-baixa nos
ingredientes (a venda continua baixando arroz, salmão etc.; comprovado na venda #347237 de 12/11) e "cliente pode retirar"
desligado. O produto fica com uma linha só: 1 UN desse item. Custo, preço e status não mudam.

  python3 ficha_fechada.py <id do produto> [--gravar]
  python3 ficha_fechada.py <id do produto> --desfazer [--gravar]     volta as linhas originais (cópia em manuais/aliv_backup)
Para no primeiro problema. Sem --gravar só mostra o que faria."""
import sys, os, json, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR, DESFAZER = "--gravar" in sys.argv, "--desfazer" in sys.argv
pid = int(sys.argv[1]); CATEGORIA, UN = "Receitas e Produção", 466
COPIA = f"/workspace/Contapecas/manuais/aliv_backup/ficha_{pid}_antes_de_fechar.json"
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()

def enviar(f):
    st, r = api._send(f())
    if st == 401: api.login(); st, r = api._send(f())
    return st, r
def post(path, data):
    return enviar(lambda: urllib.request.Request(BASE_URL + path, data=urllib.parse.urlencode(data).encode(), method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}))
def delete(path): return enviar(lambda: urllib.request.Request(BASE_URL + path, method="DELETE", headers={"Accept": "application/json"}))
def estoque(): return api.get("/admin/inventory/api/ingredients")
def ficha(): return api.get(f"/admin/menu/product/{pid}/recipes")
def custo(l): return sum(x["total_cost"] for x in l)
def produto():
    for c in api.get("/admin/api/menu/full_data")["categories"]:
        for p in c["products"]:
            if p["id"] == pid: return p
def retiraveis():
    return [i.get("name") for p in api.get("/admin/api/pdv/data")["products"] if p["id"] == pid for i in (p.get("ingredients") or [])]
def parar(msg): print("PAREI:", msg); sys.exit(1)

p = produto(); nome_item = f"{p['name']} (ficha)"
inv = estoque(); item = next((i for i in inv["ingredients"] if i["name"] == nome_item), None)
atual = ficha(); fechada = bool(item) and len(atual) == 1 and atual[0]["ingredient_id"] == item["id"]
print(f"produto {pid} {p['name']} | ativo {p['is_active']} | ficha: {len(atual)} linha(s), custo R$ {custo(atual):.4f} | fechada: {fechada} | cliente pode retirar hoje: {retiraveis()}")

if DESFAZER:
    if not fechada: parar("a ficha não está fechada; nada a desfazer")
    orig = json.load(open(COPIA))["linhas"]
    if not GRAVAR: print("voltaria às", len(orig), "linhas originais"); sys.exit()
    for l in orig:
        st, r = post("/admin/menu/recipe/save", {"product_id": pid, "ingredient_id": l["ingredient_id"], "quantity": f"{l['quantity']:.6f}"})
        if st != 200: parar(f"não recriou a linha {l['ingrediente']} ({st}); linha do item mantida")
    meio = {l["ingredient_id"]: l["quantity"] for l in ficha()}
    if any(abs(meio.get(l["ingredient_id"], -1) - l["quantity"]) > 1e-6 for l in orig): parar("linhas originais não conferem; linha do item mantida")
    st, r = delete(f"/admin/menu/recipe/{atual[0]['id']}")
    if st != 200: parar(f"não apagou a linha do item ({st}) — FICHA EM DOBRO")
    d = ficha(); print(f"desfeito: {len(d)} linhas, custo R$ {custo(d):.4f} | cliente pode retirar: {retiraveis()}"); sys.exit()

if fechada:
    print("já está fechada: nada a fazer"); sys.exit()
if any(l["ingredient_id"] in {i["id"] for i in inv["ingredients"] if i.get("is_recipe")} for l in atual): parar("a ficha já tem item produzido misturado com ingredientes; conferir à mão")
linhas = [{"recipe_id": l["id"], "ingredient_id": l["ingredient_id"], "ingrediente": l["ingredient_raw_name"], "quantity": l["quantity"], "custo": l["total_cost"]} for l in atual]
custo_antes = custo(atual)
if not GRAVAR:
    print(f"fecharia: criaria o item '{nome_item}' com {len(linhas)} linhas (R$ {custo_antes:.4f}) e o produto ficaria com 1 UN dele"); sys.exit()
if not os.path.exists(COPIA):
    json.dump({"produto": p["name"], "product_id": pid, "linhas": linhas, "custo": custo_antes}, open(COPIA, "w"), ensure_ascii=False, indent=1)
cat = next((c["id"] for c in inv["categories"] if c["name"].lower() == CATEGORIA.lower()), None)
if cat is None: parar(f"categoria de estoque '{CATEGORIA}' não existe")
if item is None:
    st, r = post("/admin/inventory/ingredient/save", {"name": nome_item, "category_id": cat, "unit_id": UN, "usage_unit_id": UN, "cost": 0, "min_stock": 0, "max_stock": 0,
                 "current_stock": 0, "conversion_factor": 1, "is_available_for_sale": "false", "final_yield": 1, "counts_in_cmv": "true", "show_in_digital_check": "false",
                 "associated_base_ingredient_id": ""})
    if st != 200: parar(f"não criou o item ({st} {str(r)[:120]})")
    item = next((i for i in estoque()["ingredients"] if i["name"] == nome_item), None)
    if item is None: parar("item não apareceu no estoque")
iid = item["id"]
if not api.get(f"/admin/inventory/ingredient/{iid}/recipe"):
    for l in linhas:
        st, r = post("/admin/inventory/recipe/save", {"parent_id": iid, "child_id": l["ingredient_id"], "quantity": f"{l['quantity']:.6f}"})
        if st != 200: parar(f"não gravou a linha {l['ingrediente']} no item ({st})")
for campo, valor in (("final_yield", 1), ("auto_explode", "true"), ("cliente_pode_retirar", "false")):
    st, r = post("/admin/inventory/ingredient/quick-update", {"ing_id": iid, "field": campo, "value": valor})
    if st != 200: parar(f"não gravou {campo} no item ({st})")
d = api.get(f"/admin/inventory/ingredient/{iid}/details"); rec = api.get(f"/admin/inventory/ingredient/{iid}/recipe")
print(f"item {iid} '{nome_item}': custo ALIV R$ {d['cost']:.4f} | linhas {len(rec)} | auto-baixa {d['auto_explode']} | rendimento {d['final_yield']} | cliente pode retirar {d.get('cliente_pode_retirar')}")
if not (abs(d["cost"] - custo_antes) < 0.001 and d["auto_explode"] is True and abs(d["final_yield"] - 1) < 1e-9 and d.get("cliente_pode_retirar") is False and len(rec) == len(linhas)):
    parar("o item não ficou igual à ficha do produto; produto NÃO foi alterado")
st, r = post("/admin/menu/recipe/save", {"product_id": pid, "ingredient_id": iid, "quantity": 1})
if st != 200: parar(f"não incluiu a linha do item no produto ({st}); ficha antiga intacta")
if not any(l["ingredient_id"] == iid for l in ficha()): parar("a linha do item não apareceu; ficha antiga intacta")
for l in linhas:
    st, r = delete(f"/admin/menu/recipe/{l['recipe_id']}")
    if st != 200: parar(f"não apagou a linha antiga {l['ingrediente']} ({st}) — FICHA EM DOBRO, rode --desfazer")
f = ficha(); p2 = produto(); ret = retiraveis()
print(f"produto {pid}: {len(f)} linha, custo R$ {custo(f):.4f} (antes R$ {custo_antes:.4f}) | ativo {p['is_active']} -> {p2['is_active']} | cliente pode retirar: {ret or 'nada'}")
if not (len(f) == 1 and abs(custo(f) - custo_antes) < 0.001 and p2["is_active"] == p["is_active"] and not ret): parar("conferência final falhou")
print("modo: GRAVAR | ok")
