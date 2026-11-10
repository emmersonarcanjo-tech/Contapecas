"""Grava no ALIV (loja 155, Tili Sushi) — autorizado pelo Emerson na sessão de 10/11/2026.
Passo 'itens': cria os itens de estoque que faltam (custo 0, KG). Idempotente pelo nome.
Passo 'fichas <ids|todos>': grava as linhas de ficha técnica via /admin/menu/recipe/save.
Uso: python3 gravar_aliv.py <proposta.json> <inventory.json> <recipes.json> itens|fichas [ids...] [--dry]
"""
import sys, os, json, re, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL

prop_p, inv_p, rec_p, passo = sys.argv[1:5]
args = [a for a in sys.argv[5:] if a != "--dry"]
DRY = "--dry" in sys.argv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()

NOVOS = [("Atum", 575), ("Morango", 584), ("Nutella", 584), ("Alho-poró", 584),
         ("Skin de salmão", 575), ("Pepino japonês", 584), ("Limão", 584)]


def post(path, data: dict | list):
    body = urllib.parse.urlencode(data, doseq=True).encode()
    req = urllib.request.Request(BASE_URL + path, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                                          "Accept": "application/json"})
    st, resp = api._send(req)
    if st == 401:
        api.login(); st, resp = api._send(req)
    return st, resp


def inventario():
    r = api.get("/admin/inventory/api/ingredients")
    return r.get("ingredients", []) if isinstance(r, dict) else r


if passo == "itens":
    atuais = {x["name"].lower(): x["id"] for x in inventario()}
    for nome, cat in NOVOS:
        if nome.lower() in atuais:
            print("já existe:", nome, atuais[nome.lower()]); continue
        dados = {"name": nome, "category_id": cat, "unit_id": 678, "usage_unit_id": 678, "cost": 0,
                 "min_stock": 0, "max_stock": 0, "current_stock": 0, "conversion_factor": 1,
                 "is_available_for_sale": "false", "final_yield": 0, "counts_in_cmv": "true",
                 "show_in_digital_check": "true", "associated_base_ingredient_id": ""}
        if DRY:
            print("DRY criaria:", nome); continue
        st, resp = post("/admin/inventory/ingredient/save", dados)
        print(nome, "→", st, str(resp)[:200])
    json.dump(inventario(), open(inv_p.replace(".json", "_novo.json"), "w"), ensure_ascii=False, indent=1)
    sys.exit()

# ---------------------------------------------------------------- fichas
prop = json.load(open(prop_p)); rec = json.load(open(rec_p))


def titulo_aliv(nome):
    base = re.sub(r"\s*\(.*?\)\s*", " ", nome).strip()
    return base.replace("Hosso ", "Hossomaki ").replace("Ura ", "Uramaki ")


por_titulo = {titulo_aliv(v["name"]): int(k) for k, v in rec.items() if v["active"]}
alvo = None if not args or args == ["todos"] else {int(a) for a in args}
for o in prop:
    pid = por_titulo.get(o["titulo"])
    if pid is None:
        print("SEM PRODUTO NO ALIV (pulado):", o["titulo"]); continue
    if alvo is not None and pid not in alvo:
        continue
    # junta linhas do mesmo item de estoque (ex.: lâmina + tataki de salmão)
    soma = {}
    for n, iid, _, uso, un, _c in o["linhas"]:
        soma[iid] = soma.get(iid, 0) + uso
    for iid, q in soma.items():
        if DRY:
            print(f"DRY {o['titulo']} ({pid}) ← {iid} {q:.4f}"); continue
        st, resp = post("/admin/menu/recipe/save", {"product_id": pid, "ingredient_id": iid, "quantity": f"{q:.4f}"})
        ok = st == 200 and not (isinstance(resp, dict) and resp.get("success") is False)
        print(("OK " if ok else "ERRO ") + f"{o['titulo']} ({pid}) ← {iid} {q:.4f} | {st} {str(resp)[:120] if not ok else ''}")
