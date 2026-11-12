"""PDF 'Quarta Maluca — preços sugeridos por peça' a partir de manuais/custos_aliv.json (custos das fichas no ALIV)."""
import json, sys, base64, html
from pathlib import Path
R = Path(__file__).resolve().parents[2]
C = json.loads((R / "manuais/custos_aliv.json").read_text())
LOGO = "data:image/png;base64," + base64.b64encode((R / "monitor/assets/logo_tili.png").read_bytes()).decode()
IMP = 0.11
def c(nome, pecas):
    k = next(k for k in C if k.startswith(nome)); return C[k] / pecas
FAIXAS = [
 ("R$ 1,99", 1.99, "Todos os rolos: hossomaki, uramaki e hot", [
   ("Hossomaki Camarão Empanado", c("Hosso Camarão Empanado", 10)), ("Uramaki Salmão Grelhado", c("Ura Salmão Grelhado", 10)),
   ("Hossomaki Salmão Grelhado", c("Hosso Salmão grelhado", 10)), ("Hossomaki Atum", c("Hosso Atum", 10)),
   ("Hossomaki Camarão Cozido", c("Hosso Camarão Cozido", 10)),
   ("Uramaki Camarão Cozido", c("Ura Camarão Cozido", 10)), ("Uramaki Filadélfia", c("Ura Fila", 10)), ("Uramaki Salmão", c("Ura Salmão (", 10)),
   ("Hossomaki Filadélfia", c("Hosso Fila", 10)), ("Hossomaki Salmão", c("Hosso Salmão (", 10)), ("Hot Camarão", c("Hot Camarão", 10)),
   ("Hot Filadélfia", c("Hot Fila", 10)), ("Uramaki Camarão Empanado", c("Ura Camarão Empanado", 10)),
   ("Hot Salmão c/ Camarão", c("Hot Salmão c/ Camarão", 10)), ("Uramaki Camarão Especial", c("Ura Camarão Especial", 10))]),
 ("R$ 3,49", 3.49, "Niguiri", [
   ("Niguiri Salmão", c("Niguiri Salmão (", 4)), ("Niguiri Salmão Selado", c("Niguiri Salmão Selado (", 4)),
   ("Niguiri Selado c/ Geleia de Pimenta", c("Niguiri Salmão Selado c/ Geleia", 4)), ("Niguiri Kani", c("Niguiri Kani", 4)),
   ("Niguiri Atum", c("Niguiri Atum", 4))]),
 ("R$ 4,99", 4.99, "Joy", [
   ("Joy Tili", c("Joy Tili", 2)), ("Joy Filadélfia", c("Joy Fila", 2)), ("Joy Capão*", c("Joy Capão", 2)),
   ("Joy Alho Poró", c("Joy Alho Poró", 2)), ("Joy Selado c/ Geleia", c("Joy Selado", 2)), ("Joy Atum", c("Joy Atum", 2))]),
]
brl = lambda v: f"R$ {v:.2f}".replace(".", ",")
blocos = ""
for titulo, preco, sub, itens in FAIXAS:
    linhas = ""
    for nome, cu in sorted(itens, key=lambda x: x[1]):
        sobra = preco - cu - IMP * preco; cmv = 100 * cu / preco
        cor = "#1E7D32" if cmv <= 35 else "#B7791F" if cmv <= 40 else "#C8102E"
        linhas += (f"<tr><td>{html.escape(nome)}</td><td>{brl(cu)}</td><td>{brl(IMP*preco)}</td>"
                   f"<td><b>{brl(sobra)}</b></td><td style='color:{cor};font-weight:800'>{cmv:.0f}%</td></tr>")
    blocos += (f"<section><div class='faixa'><span class='preco'>{titulo}</span><span class='sub'>{html.escape(sub)}</span></div>"
               f"<table><tr><th>Peça</th><th>Custo/peça</th><th>Imposto 11%</th><th>Sobra/peça</th><th>CMV</th></tr>{linhas}</table></section>")
doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page{{size:A4;margin:0}}*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,'DejaVu Sans',sans-serif;color:#1A1A1A;background:#fff}}
.pg{{width:210mm;height:297mm;overflow:hidden;border:3.5mm solid #1A1A1A;outline:1.2mm solid #D4A017;outline-offset:-6mm;padding:0 0 10mm}}
.top{{background:#1A1A1A;height:24mm;display:flex;align-items:center;justify-content:space-between;padding:0 12mm;border-bottom:2.2mm solid #C8102E}}
.top img{{height:17mm;background:#fff;border-radius:2mm;padding:1mm}}.top .t{{color:#D4A017;font:800 15pt 'Inter Display',Inter;letter-spacing:4px}}
.corpo{{padding:6mm 13mm 0;zoom:.69}}h1{{font:900 25pt 'Inter Display',Inter;color:#C8102E}}
.intro{{font:500 11.5pt/1.4 Inter;margin:2mm 0 4mm}}
section{{margin-bottom:5mm;break-inside:avoid}}.faixa{{display:flex;align-items:baseline;gap:4mm;border-bottom:.8mm solid #D4A017;padding-bottom:1mm;margin-bottom:1.5mm}}
.preco{{font:900 19pt 'Inter Display',Inter;color:#C8102E}}.sub{{font:700 11.5pt Inter;letter-spacing:1px;text-transform:uppercase}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}}th:first-child{{width:44%}}th{{background:#1A1A1A;color:#D4A017;font:700 10pt Inter;text-align:left;padding:1.6mm 2mm}}
td{{font:400 11pt Inter;padding:1.5mm 2mm;border-bottom:.3mm solid #ddd}}th:not(:first-child),td:not(:first-child){{text-align:right}}
.nota{{font:400 9.5pt/1.45 Inter;color:#444;border-top:.4mm solid #D4A017;padding-top:2mm;margin-top:2mm}}
.leg span{{font-weight:800}}
</style></head><body><div class="pg"><div class="top"><img src="{LOGO}"><div class="t">QUARTA MALUCA · TILI SUSHI</div></div>
<div class="corpo"><h1>Preço sugerido por peça</h1>
<div class="intro">Custo de ingredientes pelas fichas técnicas do ALIV em 12/11/2026 (salmão com rendimento medido de 71,3% em 4 caixas, atum com 40% de perda). Custo por peça = ficha da porção ÷ nº de peças (rolo ÷ 10, niguiri ÷ 4, Joy ÷ 2). Sobra = preço − custo − 11% de imposto, antes de equipe e custos fixos.</div>
{blocos}
<div class="nota leg">CMV: <span style="color:#1E7D32">verde até 35%</span> · <span style="color:#B7791F">amarelo até 40%</span> · <span style="color:#C8102E">vermelho acima de 40%</span>.<br>
* Joy Capão: alho-poró ainda com custo zero no estoque. Fora da lista até ter preço: Uramaki Skin, Niguiri Skin e Hossomaki Morango c/ Nutella (skin, morango e Nutella sem custo) e Joy Camarão (peso do camarão não informado).<br>
<b>Rolo a R$ 1,49 não compensa:</b> pela quarta de 11/11, baixar 40% das peças de R$ 1,99 para R$ 1,49 tira cerca de R$ 413 por noite mesmo vendendo 20% a mais; só empata se essas peças venderem 48% a mais. Por isso todos os rolos ficam a R$ 1,99.<br>
<b>Joy e niguiri:</b> com o volume de 11/11 (1.152 peças), a tabela nova rende cerca de R$ 700 a mais por quarta se o Joy vender 30% menos; com o Joy a R$ 3,99, cerca de R$ 490. Acompanhar o movimento do salão por 4 quartas.<br>
Lançar cada peça em botão separado no PDV (rolo, niguiri, Joy) para o ALIV mostrar quanto sai de cada uma.</div>
</div></div></body></html>"""
out = R / "financeiro/quarta_maluca_precos_sugeridos.html"; out.write_text(doc, encoding="utf-8"); print(out)
