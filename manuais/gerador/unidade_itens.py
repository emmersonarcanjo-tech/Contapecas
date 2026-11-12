"""Ficha técnica por UNIDADE no ALIV (pedido do Emerson em 12/11/2026).

Cada tipo de niguiri/Joy vira um item produzido no estoque — "Niguiri Salmão (unidade)" — com a receita de 1 peça,
rendimento 1 UN e auto-baixa nos ingredientes (a venda baixa arroz, salmão etc., não o item). Os produtos do cardápio
passam a ter uma linha só: N unidades desse item (porção de 4 → 4 UN; porção de 2 → 2 UN; "(1 peça)" → 1 UN).
Nome, preço e descrição dos produtos NÃO mudam.

Uso (sem --gravar só mostra o que faria):
  python3 unidade_itens.py plano_unidade.json itens    <tipo|todos> [--gravar]   cria/confere os itens (não mexe em produto)
  python3 unidade_itens.py plano_unidade.json ligar    <tipo|todos> [--gravar] [--so-peca|--so-porcao]
  python3 unidade_itens.py plano_unidade.json desfazer <tipo|todos> [--gravar] [--so-peca|--so-porcao]
O plano (unidade_plano.py) guarda as linhas originais de cada produto; ele é a cópia de segurança.
Depois de um "desfazer", gere o plano de novo antes de ligar outra vez (os números das linhas mudam).

O script PARA no primeiro problema e diz em que produto parou. "ligar" inclui a linha do item, confere, e só então apaga
as linhas antigas; "desfazer" recria as linhas originais, confere, e só então apaga a linha do item.

SITUAÇÃO EM 12/11/2026: só o Niguiri Salmão está ligado (piloto). Antes de expandir para os outros tipos:
  1. ver numa venda real que o estoque baixa arroz e salmão (auto-baixa) e não o item — a prévia de saída manual do ALIV
     mostrou a baixa no próprio item "Niguiri Salmão (unidade)";
  2. os Joy ficam sem o "retirar cebolinha/cream cheese" do cliente (a ficha vira 1 linha) — o Emerson aceitou em 12/11;
  3. scripts que leem a ficha do produto precisam abrir o item (combos_fichas.py já abre; o do rendimento do salmão só avisa);
  4. rodar com a loja fechada (abre às 18h), nunca em terça à noite ou quarta.
Os itens criados não podem ser apagados por script (o ALIV pede a senha do dono).
"""
import sys, os, json, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL

CATEGORIA = "Receitas e Produção"          # a aba "Fichas e Produção" do ALIV mostra por padrão categorias com "receita"/"produção"
UN = 466
plano_p, passo, alvo = sys.argv[1], sys.argv[2], sys.argv[3]
GRAVAR = "--gravar" in sys.argv
SO_PECA, SO_PORCAO = "--so-peca" in sys.argv, "--so-porcao" in sys.argv
plano = json.load(open(plano_p))
tipos = [x for x in plano if alvo == "todos" or x["tipo"] == alvo]
assert tipos, f"tipo não encontrado: {alvo}"
assert passo in ("itens", "ligar", "desfazer"), passo
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()


class Parar(Exception):
    pass


def enviar(fabrica):
    st, r = api._send(fabrica())
    if st == 401:                              # sessão caiu: entra de novo e repete uma vez
        api.login(); st, r = api._send(fabrica())
    return st, r


def post(path, data):
    return enviar(lambda: urllib.request.Request(BASE_URL + path, data=urllib.parse.urlencode(data).encode(), method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}))


def delete(path):
    return enviar(lambda: urllib.request.Request(BASE_URL + path, method="DELETE", headers={"Accept": "application/json"}))


def estoque():
    return api.get("/admin/inventory/api/ingredients")


def ficha_produto(pid):
    return api.get(f"/admin/menu/product/{pid}/recipes")


def custo(linhas):
    return sum(l["total_cost"] for l in linhas)


def ativos():
    return {p["id"]: p["is_active"] for c in api.get("/admin/api/menu/full_data")["categories"] for p in c["products"]}


def produtos_do_tipo(x):
    pares = []
    if not SO_PORCAO: pares.append((x["produto_peca"], 1))
    if not SO_PECA: pares.append((x["produto_porcao"], x["pecas_na_porcao"]))
    return pares


def item_pronto(item, x):
    d = api.get(f"/admin/inventory/ingredient/{item['id']}/details"); rec = api.get(f"/admin/inventory/ingredient/{item['id']}/recipe")
    ok = (abs(d["cost"] - x["custo_unidade"]) < 0.0003 and d["auto_explode"] is True and abs(d["final_yield"] - 1) < 1e-9
          and d.get("cliente_pode_retirar") is False and len(rec) == len(x["linhas"]))
    return ok, d, rec


def passo_itens():
    inv = estoque()
    cat = next((c["id"] for c in inv["categories"] if c["name"].lower() == CATEGORIA.lower()), None)
    if cat is None and GRAVAR:
        st, r = post("/admin/inventory/aux/save", {"type": "category", "name": CATEGORIA})
        if st != 200: raise Parar(f"não criou a categoria: {st} {str(r)[:120]}")
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
            if st != 200: raise Parar(f"{nome}: não criou o item ({st} {str(r)[:120]})")
            item = next((i for i in estoque()["ingredients"] if i["name"] == nome), None)
            if item is None: raise Parar(f"{nome}: item não apareceu no estoque depois de criar")
        iid = item["id"]
        if GRAVAR and cat and item.get("category_id") != cat:
            post("/admin/inventory/ingredients/bulk-set-category", {"ingredient_ids": str(iid), "category_id": str(cat)})
        rec = api.get(f"/admin/inventory/ingredient/{iid}/recipe")
        if not rec and GRAVAR:
            for l in x["linhas"]:
                st, r = post("/admin/inventory/recipe/save", {"parent_id": iid, "child_id": l["ingredient_id"], "quantity": l["quantity"]})
                if st != 200: raise Parar(f"{nome}: não gravou a linha {l['ingrediente']} ({st})")
        elif rec and len(rec) != len(x["linhas"]):
            raise Parar(f"{nome}: a receita já existe com {len(rec)} linhas (o plano tem {len(x['linhas'])})")
        if GRAVAR:
            for campo, valor in (("final_yield", 1), ("auto_explode", "true"), ("cliente_pode_retirar", "false")):
                st, r = post("/admin/inventory/ingredient/quick-update", {"ing_id": iid, "field": campo, "value": valor})
                if st != 200: raise Parar(f"{nome}: não gravou {campo} ({st})")
        ok, d, rec = item_pronto({"id": iid}, x)
        print(f"{'OK  ' if ok else 'FALTA'} item {iid} {nome[:46]:46s} custo ALIV R$ {d['cost']:.4f} (plano {x['custo_unidade']:.4f}) | linhas {len(rec)} | "
              f"auto-baixa {d['auto_explode']} | rendimento {d['final_yield']} | cliente pode retirar {d.get('cliente_pode_retirar')}")
        if GRAVAR and not ok: raise Parar(f"{nome}: item não ficou como o plano")


def passo_ligar():
    inv = {i["name"]: i for i in estoque()["ingredients"]}
    antes = ativos()
    for x in tipos:
        item = inv.get(x["item"])
        if not item: raise Parar(f"{x['item']}: item não existe; rode o passo itens")
        ok, d, _ = item_pronto(item, x)
        if not ok: raise Parar(f"{x['item']}: item não está pronto ({d})")
        for prod, n in produtos_do_tipo(x):
            atual = ficha_produto(prod["id"]); esperado = n * x["custo_unidade"]
            if len(atual) == 1 and atual[0]["ingredient_id"] == item["id"] and abs(atual[0]["quantity"] - n) < 1e-9:
                print(f"já ligado  {prod['nome'][:44]:44s} {n} UN = R$ {custo(atual):.4f}"); continue
            if sorted(l["id"] for l in atual) != sorted(prod["recipe_ids"]):
                raise Parar(f"{prod['nome']}: a ficha mudou desde o plano (linhas {[l['id'] for l in atual]}); não mexi")
            if not GRAVAR:
                print(f"ligaria    {prod['nome'][:44]:44s} {len(atual)} linhas (R$ {custo(atual):.4f}) -> {n} UN de {x['item']} (R$ {esperado:.4f})"); continue
            st, r = post("/admin/menu/recipe/save", {"product_id": prod["id"], "ingredient_id": item["id"], "quantity": n})
            if st != 200: raise Parar(f"{prod['nome']}: não incluiu a linha do item ({st} {str(r)[:120]}); ficha antiga intacta")
            if not any(l["ingredient_id"] == item["id"] and abs(l["quantity"] - n) < 1e-9 for l in ficha_produto(prod["id"])):
                raise Parar(f"{prod['nome']}: a linha do item não apareceu; ficha antiga intacta")
            for rid in prod["recipe_ids"]:
                st, r = delete(f"/admin/menu/recipe/{rid}")
                if st != 200: raise Parar(f"{prod['nome']}: não apagou a linha antiga {rid} ({st}) — FICHA EM DOBRO, rode o desfazer deste tipo")
            depois = ficha_produto(prod["id"])
            if not (len(depois) == 1 and depois[0]["ingredient_id"] == item["id"] and abs(custo(depois) - esperado) < 0.001):
                raise Parar(f"{prod['nome']}: conferência falhou {[(l['ingredient_id'], l['quantity'], l['total_cost']) for l in depois]}")
            print(f"OK   ligado {prod['nome'][:44]:44s} {n} UN = R$ {custo(depois):.4f} (antes R$ {custo(atual):.4f})")
    if GRAVAR:
        depois = ativos(); ids = [p["id"] for x in tipos for p, _ in produtos_do_tipo(x)]
        mudou = [i for i in ids if antes.get(i) != depois.get(i)]
        if mudou: raise Parar(f"produtos que mudaram de ativo/pausado: {mudou}")
        print("produtos ativos: igual a antes (", sum(1 for i in ids if depois.get(i)), "de", len(ids), "ativos )")


def passo_desfazer():
    pasta = os.path.dirname(os.path.abspath(plano_p))
    arq = next(os.path.join(pasta, n) for n in ("fichas_niguiri_joy.json", "fichas_niguiri_joy_antes_unidade_2026-11-12.json") if os.path.exists(os.path.join(pasta, n)))
    orig = {f["product_id"]: f for f in json.load(open(arq))}
    inv = {i["name"]: i for i in estoque()["ingredients"]}
    for x in tipos:
        item = inv.get(x["item"]); iid = item["id"] if item else None
        for prod, _ in produtos_do_tipo(x):
            atual = ficha_produto(prod["id"]); o = orig[prod["id"]]
            if not any(l["ingredient_id"] == iid for l in atual):
                print("não está ligado ao item:", prod["nome"]); continue
            if not GRAVAR:
                print("voltaria ao original:", prod["nome"], len(o["ficha"]), "linhas, R$", o["custo_total"]); continue
            tem = {l["ingredient_id"] for l in atual}
            for l in o["ficha"]:
                if l["ingredient_id"] in tem: continue
                st, r = post("/admin/menu/recipe/save", {"product_id": prod["id"], "ingredient_id": l["ingredient_id"], "quantity": l["quantity"]})
                if st != 200: raise Parar(f"{prod['nome']}: não recriou a linha {l['ingrediente']} ({st}); linha do item mantida")
            meio = {l["ingredient_id"]: l["quantity"] for l in ficha_produto(prod["id"])}
            if any(abs(meio.get(l["ingredient_id"], -1) - l["quantity"]) > 1e-9 for l in o["ficha"]):
                raise Parar(f"{prod['nome']}: as linhas originais não conferem; linha do item mantida")
            for l in atual:
                if l["ingredient_id"] != iid: continue
                st, r = delete(f"/admin/menu/recipe/{l['id']}")
                if st != 200: raise Parar(f"{prod['nome']}: não apagou a linha do item {l['id']} ({st}) — FICHA EM DOBRO")
            depois = ficha_produto(prod["id"])
            if abs(custo(depois) - o["custo_total"]) > 0.001 or len(depois) != len(o["ficha"]):
                raise Parar(f"{prod['nome']}: depois de desfazer o custo é R$ {custo(depois):.4f} (original R$ {o['custo_total']:.4f})")
            print(f"desfeito {prod['nome'][:44]:44s} R$ {custo(depois):.4f} (original R$ {o['custo_total']:.4f}) {len(depois)} linhas")


try:
    {"itens": passo_itens, "ligar": passo_ligar, "desfazer": passo_desfazer}[passo]()
    print("modo:", "GRAVAR" if GRAVAR else "dry-run", "| problemas: nenhum")
except Parar as e:
    print("PAREI:", e); print("modo:", "GRAVAR" if GRAVAR else "dry-run", "| problemas: 1")
    sys.exit(1)
