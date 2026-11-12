"""Combinados x preços por peça da Quarta Maluca: quanto as mesmas peças custariam avulsas (preço de hoje e preço do PDF).
Uso: python3 -I combos_quarta.py <full_data.json do ALIV> [saida.html]   — custos em manuais/custos_aliv.json. Não acessa o ALIV."""
import json, re, sys, base64, html
from pathlib import Path
R = Path(__file__).resolve().parents[2]
full = json.load(open(sys.argv[1])); C = json.loads((R / "manuais/custos_aliv.json").read_text())
LOGO = "data:image/png;base64," + base64.b64encode((R / "monitor/assets/logo_tili.png").read_bytes()).decode()
IMP = 0.11
HOJE = {"sashimi": 4.99, "uramaki": 1.99, "hot": 1.99, "niguiri": 2.99, "joy": 2.99}
PDF = {"sashimi": 4.99, "uramaki": 1.99, "hot": 1.99, "niguiri": 3.49, "joy": 4.99}
IDS = [11697, 11698, 11699, 11700, 11701, 11702, 11703, 11704]
prods = {p["id"]: p for c in full["categories"] for p in c["products"]}
brl = lambda v: f"R$ {v:.2f}".replace(".", ",")
linhas = []; dados = []
for i in IDS:
    p = prods[i]; desc = (p["full_data"].get("description") or "").lower().replace("sashumi", "sashimi")
    comp = {}
    for q, nome in re.findall(r"(\d+)\s+([a-zà-ú ]+)", desc):
        k = next(k for k in HOJE if k in nome); comp[k] = comp.get(k, 0) + int(q)
    custo = C[p["name"]]; preco = p["price"]
    s_hoje = sum(n * HOJE[k] for k, n in comp.items()); s_pdf = sum(n * PDF[k] for k, n in comp.items())
    sobra = lambda v: v - custo - IMP * v
    dados.append({"nome": p["name"], "comp": comp, "custo": custo, "combo": preco, "quarta_hoje": round(s_hoje, 2), "quarta_pdf": round(s_pdf, 2),
                  "sobra_combo": round(sobra(preco), 2), "sobra_hoje": round(sobra(s_hoje), 2), "sobra_pdf": round(sobra(s_pdf), 2)})
for d in dados:
    comp = ", ".join(f"{n} {k}" for k, n in d["comp"].items())
    print(f'{d["nome"]:27}| {comp:52}| custo {d["custo"]:6.2f} | combo {d["combo"]:7.2f} sobra {d["sobra_combo"]:7.2f} cmv {100*d["custo"]/d["combo"]:3.0f}% '
          f'| quarta hoje {d["quarta_hoje"]:7.2f} sobra {d["sobra_hoje"]:7.2f} cmv {100*d["custo"]/d["quarta_hoje"]:3.0f}% '
          f'| quarta PDF {d["quarta_pdf"]:7.2f} sobra {d["sobra_pdf"]:7.2f} cmv {100*d["custo"]/d["quarta_pdf"]:3.0f}%')
if len(sys.argv) > 2:
    def cor(c): return "#1E7D32" if c <= 35 else "#B7791F" if c <= 40 else "#C8102E"
    rows = ""
    for d in dados:
        comp = " · ".join(f"{n} {k}" for k, n in d["comp"].items())
        dif = d["quarta_pdf"] - d["combo"]
        quem = "combo mais barato" if dif > 0.005 else "avulso mais barato"
        cel = lambda v: f"<td><b>{brl(v)}</b><br><span style='color:{cor(100*d['custo']/v)};font-weight:800'>CMV {100*d['custo']/v:.0f}%</span> · sobra {brl(v - d['custo'] - IMP*v)}</td>"
        rows += (f"<tr><td><b>{html.escape(d['nome'])}</b><br><span class='c'>{html.escape(comp)}</span></td><td>{brl(d['custo'])}</td>"
                 f"{cel(d['combo'])}{cel(d['quarta_hoje'])}{cel(d['quarta_pdf'])}"
                 f"<td><b style='color:{'#1E7D32' if dif>0 else '#C8102E'}'>{'+' if dif>0 else '−'}{brl(abs(dif))}</b><br><span class='c'>{quem}</span></td></tr>")
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page{{size:A4 landscape;margin:0}}*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,'DejaVu Sans',sans-serif;color:#1A1A1A;background:#fff}}
.pg{{width:297mm;height:210mm;overflow:hidden;border:3.5mm solid #1A1A1A;outline:1.2mm solid #D4A017;outline-offset:-6mm}}
.top{{background:#1A1A1A;height:22mm;display:flex;align-items:center;justify-content:space-between;padding:0 12mm;border-bottom:2.2mm solid #C8102E}}
.top img{{height:15mm;background:#fff;border-radius:2mm;padding:1mm}}.top .t{{color:#D4A017;font:800 14pt 'Inter Display',Inter;letter-spacing:4px}}
.corpo{{padding:5mm 12mm 0;zoom:.86}}h1{{font:900 21pt 'Inter Display',Inter;color:#C8102E}}
.intro{{font:500 10.5pt/1.4 Inter;margin:1.5mm 0 3mm}}
table{{width:100%;border-collapse:collapse}}th{{background:#1A1A1A;color:#D4A017;font:700 9.5pt Inter;text-align:left;padding:1.8mm 2mm;vertical-align:bottom}}
td{{font:400 10pt/1.3 Inter;padding:1.7mm 2mm;border-bottom:.3mm solid #ddd;vertical-align:top}}.c{{font-size:8.5pt;color:#555}}
.nota{{font:400 9pt/1.45 Inter;color:#444;border-top:.4mm solid #D4A017;padding-top:2mm;margin-top:3mm}}
</style></head><body><div class="pg"><div class="top"><img src="{LOGO}"><div class="t">COMBINADOS × QUARTA MALUCA · TILI SUSHI</div></div>
<div class="corpo"><h1>As mesmas peças, compradas avulsas na quarta</h1>
<div class="intro">Para cada combinado: o preço do combo, quanto o cliente pagaria pelas mesmas peças avulsas na Quarta Maluca com os preços de hoje (rolo R$ 1,99 · Joy e niguiri R$ 2,99 · sashimi R$ 4,99) e com os preços do PDF (rolo R$ 1,99 · niguiri R$ 3,49 · Joy R$ 4,99 · sashimi R$ 4,99). Custo pela ficha do ALIV em 12/11/2026. Sobra = preço − custo − 11% de imposto.</div>
<table><tr><th style="width:27%">Combinado</th><th>Custo</th><th>Preço do combo</th><th>Avulso na quarta<br>(preços de hoje)</th><th>Avulso na quarta<br>(preços do PDF)</th><th>PDF menos combo</th></tr>{rows}</table>
<div class="nota">Composição conforme a descrição do combinado no ALIV; uramaki = Uramaki Fila, niguiri = Niguiri Salmão, joy = Joy Fila, hot = Hot Fila. O sashimi não está no PDF de preços; usei os R$ 4,99 que já são cobrados na quarta. CMV: verde até 35% · amarelo até 40% · vermelho acima de 40%. Não inclui embalagem, shoyu e gengibre.</div>
</div></div></body></html>"""
    Path(sys.argv[2]).write_text(doc, encoding="utf-8")
