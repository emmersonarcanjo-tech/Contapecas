"""Plano (sem gravar): um item 'unidade' por tipo de niguiri/Joy, a partir da ficha atual do produto '(1 peça)';
confere se a porção atual é exatamente N × a unidade."""
import sys, json, re
fichas = json.load(open(sys.argv[1]))
def chave(nome):
    n = re.sub(r"\(.*?\)|\( 0.*$", "", nome).strip().lower()
    return re.sub(r"\s+", " ", n)
porcao, peca = {}, {}
for f in fichas:
    if not f["ficha"]: continue
    (peca if "(1 peça)" in f["produto"] else porcao)[chave(f["produto"])] = f
plano = []
for k in sorted(peca):
    u = peca[k]; p = porcao.get(k)
    n = 4 if k.startswith("niguiri") else 2
    linhas = [{"ingredient_id": l["ingredient_id"], "ingrediente": l["ingrediente"], "unidade": l["unidade"], "quantity": l["quantity"], "custo": l["total_cost"]} for l in u["ficha"]]
    dif = []
    if p:
        pu = {l["ingredient_id"]: l["quantity"] for l in p["ficha"]}; uu = {l["ingredient_id"]: l["quantity"] for l in u["ficha"]}
        for i in sorted(set(pu) | set(uu)):
            if abs(pu.get(i, 0) - n * uu.get(i, 0)) > 1e-6: dif.append((i, pu.get(i), uu.get(i)))
    nome_item = re.sub(r"\s*\(1 peça\)", "", u["produto"]).strip() + " (unidade)"
    plano.append({"tipo": k, "item": nome_item, "pecas_na_porcao": n, "linhas": linhas, "custo_unidade": u["custo_total"],
                  "produto_peca": {"id": u["product_id"], "nome": u["produto"], "preco": u["preco"], "recipe_ids": [l["recipe_id"] for l in u["ficha"]]},
                  "produto_porcao": p and {"id": p["product_id"], "nome": p["produto"], "preco": p["preco"], "custo": p["custo_total"], "recipe_ids": [l["recipe_id"] for l in p["ficha"]]},
                  "porcao_difere_de_n_vezes": dif})
json.dump(plano, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
for x in plano:
    p = x["produto_porcao"]
    print(f"{x['item'][:48]:48s} R$ {x['custo_unidade']:.4f}/un | porção {p['nome'][:34] if p else '—':34s} {x['pecas_na_porcao']}× = {x['pecas_na_porcao']*x['custo_unidade']:.4f} (hoje {p['custo'] if p else '—'}) | difere: {x['porcao_difere_de_n_vezes'] or 'não'}")
    for l in x["linhas"]: print(f"      {l['ingrediente'][:40]:40s} {l['quantity']:.6f} {l['unidade']} R$ {l['custo']:.4f}")
print(len(plano), "tipos | sem par de porção:", [x["item"] for x in plano if not x["produto_porcao"]], "| porções sem peça:", sorted(set(porcao) - set(peca)))
