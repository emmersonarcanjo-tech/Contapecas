"""Simulação: todos os temakis vendidos a um preço único. Custo = ficha técnica do ALIV (somente leitura).
Sobra = preço − ingredientes − 11% de imposto; no iFood desconta também 25% de comissão (estimativa).
Uso: python3 temakis_preco.py [preço, padrão 24.90] [saida.json]"""
import sys, os, json
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv
PRECO = float(sys.argv[1]) if len(sys.argv) > 1 else 24.90
IMP, IFOOD = 0.11, 0.25
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
inv = {i["id"]: i for i in api.get("/admin/inventory/api/ingredients")["ingredients"]}
full = api.get("/admin/api/menu/full_data"); vistos = set(); out = []
for c in full["categories"]:
    for p in c["products"]:
        if p["id"] in vistos or "temaki" not in p["name"].lower(): continue
        vistos.add(p["id"])
        f = api.get(f"/admin/menu/product/{p['id']}/recipes")
        custo = sum(l["total_cost"] for l in f)
        sem_preco = [l["ingredient_raw_name"] for l in f if (inv.get(l["ingredient_id"], {}).get("cost") or 0) == 0]
        out.append({"id": p["id"], "nome": p["name"], "categoria": c["name"], "ativo": p["is_active"], "preco_hoje": p["price"], "linhas": len(f), "custo": round(custo, 4),
                    "sem_preco": sem_preco, "ficha": [(l["ingredient_raw_name"], l["quantity"], l["ingredient_unit"], round(l["total_cost"], 4)) for l in f]})
out.sort(key=lambda x: (not x["ativo"], x["linhas"] == 0, x["custo"]))
print(f"preço simulado R$ {PRECO:.2f} | imposto {IMP:.0%} = R$ {PRECO*IMP:.2f} | comissão iFood {IFOOD:.0%} = R$ {PRECO*IFOOD:.2f}")
print(f"{'temaki':38s} {'ativo':5s} {'hoje':>7s} {'custo':>7s} {'CMV':>6s} {'sobra':>7s} {'iFood':>7s}  obs")
for x in out:
    if x["linhas"] == 0:
        print(f"{x['nome'][:38]:38s} {str(x['ativo']):5s} {x['preco_hoje']:7.2f} {'—':>7s} {'—':>6s} {'—':>7s} {'—':>7s}  sem ficha"); continue
    s = PRECO - x["custo"] - PRECO * IMP
    print(f"{x['nome'][:38]:38s} {str(x['ativo']):5s} {x['preco_hoje']:7.2f} {x['custo']:7.2f} {100*x['custo']/PRECO:5.1f}% {s:7.2f} {s - PRECO*IFOOD:7.2f}  {'sem preço: ' + ', '.join(x['sem_preco']) if x['sem_preco'] else ''}")
com = [x for x in out if x["linhas"] and x["ativo"]]
print(f"\nativos com ficha: {len(com)} | custo de R$ {min(x['custo'] for x in com):.2f} a R$ {max(x['custo'] for x in com):.2f} | média simples R$ {sum(x['custo'] for x in com)/len(com):.2f}")
print(f"sobra média (balcão/app) R$ {sum(PRECO - x['custo'] - PRECO*IMP for x in com)/len(com):.2f} | iFood R$ {sum(PRECO - x['custo'] - PRECO*(IMP+IFOOD) for x in com)/len(com):.2f}")
print(f"preço médio de hoje dos ativos com ficha: R$ {sum(x['preco_hoje'] for x in com)/len(com):.2f}")
if len(sys.argv) > 2: json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
