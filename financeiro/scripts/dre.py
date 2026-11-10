"""DRE estimada do Sushi a partir dos pedidos (json), fichas do ALIV e estoque. Não grava nada.
Uso: python3 -I dre.py <pedidos.json> <conferencia.json> <inventory_novo.json> <saida.json>
"""
import sys, json, re, unicodedata
from collections import defaultdict

ped = json.load(open(sys.argv[1])); conf = json.load(open(sys.argv[2]))
inv = json.load(open(sys.argv[3])); inv = inv["ingredients"] if isinstance(inv, dict) else inv

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

custo_ficha = {x[2]: x[4] for x in conf}            # produto_id -> custo (ALIV)
estoque = {norm(x["name"]): x for x in inv}

# custo por peça (ingredientes), das fichas gravadas
PECA = {"rolo": 0.62, "joy_niguiri": 1.30, "avulsa": 0.85, "sashimi": 1.48, "niguiri": 0.85, "joy": 1.75,
        "uramaki": 0.60, "hot": 0.65, "hosso": 0.55, "gunkan": 0.85, "acarajapa": 0.80}
# % de custo estimado para pratos sem ficha
PCT_SEM_FICHA = 0.35

def custo_combo(desc_or_title):
    t = norm(desc_or_title); tot = 0.0; achou = False
    for q, nome in re.findall(r"(\d+)\s+([a-z ]+?)(?=\d|$)", t):
        q = int(q); n = nome
        k = ("sashimi" if "sash" in n else "niguiri" if "niguiri" in n else "joy" if "joy" in n else
             "hot" if "hot" in n else "gunkan" if "gunk" in n else "hosso" if "hosso" in n else "uramaki")
        tot += q * PECA[k]; achou = True
    return tot if achou else None

COMBOS = {}  # titulo normalizado -> descrição (preenchido pelo full_data, se passado)
if len(sys.argv) > 5:
    full = json.load(open(sys.argv[5]))
    for c in full["categories"]:
        for p in c["products"]:
            d = (p.get("full_data") or {}).get("description")
            if d and re.search(r"\d+\s+\w", d): COMBOS[norm(p["name"])] = d

TITULO_PID = {}
if len(sys.argv) > 5:
    for c in full["categories"]:
        for pp in c["products"]:
            TITULO_PID.setdefault(norm(re.sub(r"\(.*?\)", "", pp["name"])), pp["id"])
TITULO_PID.update({"joy salmao c cream cheese": 11632, "hot filadelfia": 11672, "ura filadelfia": 11660, "uramaki filadelfia": 11660,
                   "hosso filadelfia": 11664, "hossomaki filadelfia": 11664})

def itens(p):
    it = p.get("items_json") or p.get("items") or []
    if isinstance(it, str):
        try: it = json.loads(it)
        except ValueError: return []
    return [i for i in it if isinstance(i, dict)]

linhas = defaultdict(lambda: {"qtd": 0.0, "receita": 0.0, "custo": 0.0, "origem": ""})
fat_total = canc = 0.0; canais = defaultdict(float); taxa_entrega = 0.0; desc_total = 0.0
for p in ped:
    st = str(p.get("status") or "").upper()
    if "CANCEL" in st:
        canc += 1; continue
    tot = float(p.get("total") or p.get("total_value") or 0)
    fat_total += tot
    canais[str(p.get("platform_slug") or "?").lower()] += tot
    taxa_entrega += float(p.get("delivery_fee") or 0)
    for i in itens(p):
        t = i.get("title") or i.get("name") or "?"; nt = norm(t)
        q = float(i.get("quantity") or 1); pr = float(i.get("price") or 0); pid = i.get("product_id") or i.get("id")
        if "joy" in nt and "unidade" in nt:
            L = linhas[t]; L["qtd"] += q; L["receita"] += q * pr; L["custo"] += q * custo_ficha.get(11632, 3.77) / 2; L["origem"] = "ficha ALIV (1 peça)"
            continue
        if pid not in custo_ficha:
            pid = TITULO_PID.get(norm(re.sub(r"\(.*?\)", "", t)), pid)
        L = linhas[t]; L["qtd"] += q; L["receita"] += q * pr
        if pid in custo_ficha:
            c, o = custo_ficha[pid], "ficha ALIV"
        elif nt == "quarta maluca":
            c, o = PECA["rolo"], "média rolos/peça"
        elif nt in ("peca sushi", "sunomono") and pr <= 3.0:
            from datetime import date as _d
            qua = _d.fromisoformat(p["_dia"]).weekday() == 2 if p.get("_dia") else True
            if pr < 2.5: c, o = PECA["rolo"], "média rolos/peça"
            elif qua: c, o = PECA["joy_niguiri"], "quarta: joy+niguiri"
            else: c, o = PECA["avulsa"], "peça avulsa 2,99 (mix)"
        elif nt.startswith("acarajapa"):
            c, o = PECA["acarajapa"], "estimado"
        elif nt in estoque and estoque[nt].get("cost"):
            c, o = float(estoque[nt]["cost"]), "custo do estoque"
        elif nt in COMBOS and custo_combo(COMBOS[nt]) is not None:
            c, o = custo_combo(COMBOS[nt]), "composição do combo"
        elif re.search(r"\(\s*1\s*pe", t.lower()):
            base = nt.split()[0]
            c, o = PECA.get({"ura": "uramaki", "hosso": "hosso", "hot": "hot", "niguiri": "niguiri", "joy": "joy"}.get(base, "rolo"), 0.62), "peça avulsa"
        else:
            # bebida/sorvete com nome parecido no estoque
            tok = set(nt.split())
            cand = [v for k, v in estoque.items() if k and v.get("cost") and v.get("unit") in ("UN", "KG")
                    and nt and (nt in k or (len(tok) >= 2 and tok <= set(k.split())))]
            if cand and len(nt) > 4:
                c, o = float(cand[0]["cost"]), f"estoque ≈ {cand[0]['name']}"
            else:
                c, o = pr * PCT_SEM_FICHA, f"estimado {int(PCT_SEM_FICHA*100)}%"
        L["custo"] += q * c; L["origem"] = o

itens_receita = sum(v["receita"] for v in linhas.values())
cmv = sum(v["custo"] for v in linhas.values())
por_origem = defaultdict(lambda: [0.0, 0.0])
for v in linhas.values():
    k = v["origem"].split(" ≈")[0]; por_origem[k][0] += v["receita"]; por_origem[k][1] += v["custo"]
res = {"pedidos": len(ped), "cancelados": canc, "faturamento": round(fat_total, 2), "itens_receita": round(itens_receita, 2),
       "taxa_entrega": round(taxa_entrega, 2), "canais": {k: round(v, 2) for k, v in canais.items()},
       "cmv": round(cmv, 2), "por_origem": {k: [round(a, 2), round(b, 2)] for k, (a, b) in por_origem.items()},
       "top": sorted(((k, round(v["qtd"]), round(v["receita"], 2), round(v["custo"], 2), v["origem"]) for k, v in linhas.items()),
                     key=lambda x: -x[2])[:40]}
json.dump(res, open(sys.argv[4], "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "top"}, ensure_ascii=False, indent=1))
for x in res["top"][:25]: print(x)
