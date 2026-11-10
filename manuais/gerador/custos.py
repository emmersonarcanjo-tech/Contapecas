"""Lê o HTML do manual (gramaturas já aplicadas) + estoque do ALIV e calcula a ficha proposta. Não grava nada."""
import re, sys, json, html as H
h = open(sys.argv[1]).read(); _i = json.load(open(sys.argv[2])); inv = {x["id"]: x for x in (_i["ingredients"] if isinstance(_i, dict) else _i)}
rec = json.load(open(sys.argv[3]))
# nome no manual -> (id estoque, gramas por unidade de uso do estoque [None = unidade direta em folhas])
MAP = [("tataki de salmão", 23889, 1000), ("atum", 24147, 1000), ("morango", 24148, 1000), ("nutella", 24149, 1000),
       ("skin", 24151, 1000), ("pepino", 24152, 1000), ("limão", 24153, 1000), ("alho poró", 24150, 1000), ("lâmina de salmão", 23889, 1000), ("salmão grelhado", 23638, 1000),
       ("salmão", 23889, 1000), ("camarão", 23917, 1000), ("cream cheese", 23907, 1000), ("arroz", 23639, 1000),
       ("gergelim", 23641, 1000), ("kani", 23871, 250), ("panko", 23882, 1000), ("geleia de pimenta", 23900, 1000),
       ("tarê", 9433, 5000), ("cebolinha", 23642, 100), ("alga", 9443, "folha"), ("nori", 9443, "folha")]
def mapear(n):
    n = n.lower()
    for k, i, f in MAP:
        if k in n: return i, f
    return None, None
def qtd(g):
    g = g.strip()
    if "folha" in g: return ("folha", 0.5 if "½" in g else float(g.split()[0].replace(",", ".")))
    m = re.match(r"([\d,.]+)\s*g(/peça)?", g)
    return ("g", float(m.group(1).replace(",", ".")), bool(m.group(2))) if m else None
nome_id = {}
for k, v in rec.items():
    nome_id[v["name"]] = int(k)
out = []
for p in h.split('<div class="pg">'):
    cat = re.search(r'class="cat">([^<]+)<', p); t = re.search(r'<h1>([^<]+)', p)
    if not cat or not t or cat.group(1) in ("Orientações", "Base da casa", "Pendências", "Combinados", "Packs", "Poke", "Pratos"): continue
    titulo = H.unescape(t.group(1)); sub = re.search(r'class="sub"><b>(\d+)', p); pecas = int(sub.group(1)) if sub else 1
    linhas, custo, faltas = [], 0.0, []
    for n, g in re.findall(r'class="nm">(?:<i[^>]*>\d+</i>)?([^<]+)</div><span class="g[^"]*">([^<]+)', p):
        n = H.unescape(n); q = qtd(g) if "___" not in g else None
        iid, f = mapear(n)
        if q is None: faltas.append(f"{n} (sem peso)"); continue
        if iid is None: faltas.append(f"{n} (sem item no estoque)"); continue
        if q[0] == "folha": uso = q[1]
        else:
            gramas = q[1] * (pecas if q[2] else 1)
            if f is None: faltas.append(f"{n} (maço sem peso)"); continue
            uso = gramas / f
        c = uso * inv[iid]["cost"]; custo += c
        linhas.append((n, iid, inv[iid]["name"], round(uso, 4), inv[iid]["usage_unit"], round(c, 2)))
    out.append({"cat": cat.group(1), "titulo": titulo, "pecas": pecas, "linhas": linhas, "custo": round(custo, 2), "faltas": faltas})
json.dump(out, open(sys.argv[4], "w"), ensure_ascii=False, indent=1)
for o in out: print(f'{o["cat"]:10} {o["titulo"][:38]:38} R$ {o["custo"]:6.2f}  faltas: {"; ".join(o["faltas"])}')
