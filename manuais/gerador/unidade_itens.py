"""Ficha técnica por UNIDADE no ALIV (pedido do Emerson em 12/11/2026).

Cada tipo de niguiri/Joy vira um item produzido no estoque — "Niguiri Salmão (unidade)" — com a receita de 1 peça,
rendimento 1 UN e auto-baixa nos ingredientes (a venda baixa arroz, salmão etc., não o item). Os produtos do cardápio
passam a ter uma linha só: N unidades desse item (porção de 4 → 4 UN; porção de 2 → 2 UN; "(1 peça)" → 1 UN).
Nome, preço e descrição dos produtos NÃO mudam.

Uso (sem --gravar só mostra o que faria):
  python3 unidade_itens.py plano_unidade.json itens  <tipo|todos> [--gravar]   cria/atualiza os itens (não mexe em produto)
  python3 unidade_itens.py plano_unidade.json ligar  <tipo|todos> [--gravar]   troca a ficha dos produtos pelo item
  python3 unidade_itens.py plano_unidade.json desfazer <tipo|todos> [--gravar] volta os produtos às linhas originais do plano
O plano (unidade_plano.py) guarda as linhas originais de cada produto; ele é a cópia de segurança.
"""
import sys, os, json, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL

CATEGORIA = "Receitas e Produção"          # a aba "Fichas e Produção" do ALIV mostra por padrão categorias com "receita"/"produção"
UN = 466
plano_p, passo, alvo = sys.argv[1], sys.argv[2], sys.argv[3]
GRAVAR = "--gravar" in sys.argv
plano = json.load(open(plano_p))
tipos = [x for x in plano if alvo == "todos" or x["tipo"] == alvo]
assert tipos, f"tipo não encontrado: {alvo}"
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()


def post(path, data):
    req = urllib.request.Request(BASE_URL + path, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"})
    return api._send(req)


def delete(path):
    return api._send(urllib.request.Request(BASE_URL + path, method="DELETE", headers={"Accept": "application/json"}))


def estoque():
    return api.get("/admin/inventory/api/ingredients")


def ficha_produto(pid):
    return api.get(f"/admin/menu/product/{pid}/recipes")


def custo(linhas):
    return sum(l["total_cost"] for l in linhas)


problemas = []

if passo == "itens":
    inv = estoque()
    cat = next((c["id"] for c in inv["categories"] if c["name"].lower() == CATEGORIA.lower()), None)
    if cat is None and GRAVAR:
        st, r = post("/admin/inventory/aux/save", {"type": "category", "name": CATEGORIA}); print("criar categoria:", st, str(r)[:120])
        inv = estoque(); cat = next((c["id"] for c in inv["categories"] if c["name"].lower() == CATEGORIA.lower()), None)
    print("categoria", CATEGORIA, "id", cat)
    for x in tipos:
        nome = x["item"]; item = next((i for i in inv["ingredients"] if i["name"] == nome), None)
        if item is None:
            if not GRAVAR:
                print("criaria item:", nome, "R$", x["custo_unidade"]); continue
            st, r = post("/admin/inventory/ingredient/save", {"name": nome, "category_id": cat, "unit_id": UN, "usage_unit_id": UN, "cost": 0,
                         "min_stock": 0, "max_stock": 0, "current_stock": 0, "conversion_factor": 1, "is_available_for_sale": "false",
                         "final_yield": 1, "counts_in_cmv": "true", "show_in_digital_check": "false", "associated_base_ingredient_id": ""})
            if st != 200: problemas.append((nome, "criar", st, str(r)[:120])); continue
            item = next((i for i in estoque()["ingredients"] if i["name"] == nome), None)
        iid = item["id"]
        if GRAVAR and cat and item.get("category_id") != cat:
            post("/admin/inventory/ingredients/bulk-set-category", {"ingredient_ids": str(iid), "category_id": str(cat)})
        rec = api.get(f"/admin/inventory/ingredient/{iid}/recipe")
        if not rec:
            for l in x["linhas"]:
                if not GRAVAR: continue
                st, r = post("/admin/inventory/recipe/save", {"parent_id": iid, "child_id": l["ingredient_id"], "quantity": l["quantity"]})
                if st != 200: problemas.append((nome, "linha", l["ingrediente"], st))
        elif len(rec) != len(x["linhas"]):
            problemas.append((nome, "receita já existe com outro nº de linhas", len(rec), len(x["linhas"]))); continue
        if GRAVAR:
            for campo, valor in (("final_yield", 1), ("auto_explode", "true"), ("cliente_pode_retirar", "false")):
                st, r = post("/admin/inventory/ingredient/quick-update", {"ing_id": iid, "field": campo, "value": valor})
                if st != 200: problemas.append((nome, "quick-update", campo, st))
        d = api.get(f"/admin/inventory/ingredient/{iid}/details"); rec = api.get(f"/admin/inventory/ingredient/{iid}/recipe")
        ok = abs(d["cost"] - x["custo_unidade"]) < 0.0003 and d["auto_explode"] is True and abs(d["final_yield"] - 1) < 1e-9 and len(rec) == len(x["linhas"])
        if not ok: problemas.append((nome, "conferência do item", d["cost"], x["custo_unidade"], d["auto_explode"], d["final_yield"], len(rec)))
        print(f"{'OK ' if ok else 'ERRO'} item {iid} {nome[:46]:46s} custo ALIV R$ {d['cost']:.4f} (plano {x['custo_unidade']:.4f}) | linhas {len(rec)} | auto-baixa {d['auto_explode']} | rendimento {d['final_yield']}")

elif passo == "ligar":
    inv = {i["name"]: i for i in estoque()["ingredients"]}
    for x in tipos:
        item = inv.get(x["item"])
        if not item:
            problemas.append((x["item"], "item não existe; rode o passo itens")); continue
        d = api.get(f"/admin/inventory/ingredient/{item['id']}/details")
        if not (abs(d["cost"] - x["custo_unidade"]) < 0.0003 and d["auto_explode"] is True and abs(d["final_yield"] - 1) < 1e-9):
            problemas.append((x["item"], "item não está pronto", d)); continue
        for prod, n in ((x["produto_peca"], 1), (x["produto_porcao"], x["pecas_na_porcao"])):
            atual = ficha_produto(prod["id"]); esperado = n * x["custo_unidade"]
            ja = len(atual) == 1 and atual[0]["ingredient_id"] == item["id"] and abs(atual[0]["quantity"] - n) < 1e-9
            if ja:
                print(f"já ligado  {prod['nome'][:44]:44s} {n} UN = R$ {custo(atual):.4f}"); continue
            if sorted(l["id"] for l in atual) != sorted(prod["recipe_ids"]):
                problemas.append((prod["nome"], "ficha mudou desde o plano; não mexi", [l["id"] for l in atual])); continue
            if not GRAVAR:
                print(f"ligaria    {prod['nome'][:44]:44s} {len(atual)} linhas (R$ {custo(atual):.4f}) -> {n} UN de {x['item']} (R$ {esperado:.4f})"); continue
            st, r = post("/admin/menu/recipe/save", {"product_id": prod["id"], "ingredient_id": item["id"], "quantity": n})
            if st != 200:
                problemas.append((prod["nome"], "incluir linha", st, str(r)[:120])); continue
            meio = ficha_produto(prod["id"])
            if not any(l["ingredient_id"] == item["id"] and abs(l["quantity"] - n) < 1e-9 for l in meio):
                problemas.append((prod["nome"], "linha nova não apareceu; linhas antigas mantidas")); continue
            for rid in prod["recipe_ids"]:
                st, r = delete(f"/admin/menu/recipe/{rid}")
                if st != 200: problemas.append((prod["nome"], "apagar linha antiga", rid, st))
            depois = ficha_produto(prod["id"])
            ok = len(depois) == 1 and depois[0]["ingredient_id"] == item["id"] and abs(custo(depois) - esperado) < 0.001
            if not ok: problemas.append((prod["nome"], "conferência", [(l["ingredient_id"], l["quantity"], l["total_cost"]) for l in depois]))
            print(f"{'OK  ' if ok else 'ERRO'} ligado {prod['nome'][:44]:44s} {n} UN = R$ {custo(depois):.4f} (antes R$ {custo(atual):.4f})")

elif passo == "desfazer":
    pasta = os.path.dirname(os.path.abspath(plano_p))
    arq = next(os.path.join(pasta, n) for n in ("fichas_niguiri_joy.json", "fichas_niguiri_joy_antes_unidade_2026-11-12.json") if os.path.exists(os.path.join(pasta, n)))
    orig = {f["product_id"]: f for f in json.load(open(arq))}
    for x in tipos:
        for prod in (x["produto_peca"], x["produto_porcao"]):
            atual = ficha_produto(prod["id"]); o = orig[prod["id"]]
            if sorted(l["id"] for l in atual) == sorted(prod["recipe_ids"]):
                print("já está no original:", prod["nome"]); continue
            if not GRAVAR:
                print("voltaria ao original:", prod["nome"], len(o["ficha"]), "linhas"); continue
            for l in o["ficha"]:
                st, r = post("/admin/menu/recipe/save", {"product_id": prod["id"], "ingredient_id": l["ingredient_id"], "quantity": l["quantity"]})
                if st != 200: problemas.append((prod["nome"], "recriar linha", l["ingrediente"], st))
            for l in atual:
                st, r = delete(f"/admin/menu/recipe/{l['id']}")
                if st != 200: problemas.append((prod["nome"], "apagar linha", l["id"], st))
            depois = ficha_produto(prod["id"])
            print(f"desfeito {prod['nome'][:44]:44s} R$ {custo(depois):.4f} (original R$ {o['custo_total']:.4f}) {len(depois)} linhas")

print("modo:", "GRAVAR" if GRAVAR else "dry-run", "| problemas:", problemas or "nenhum")
