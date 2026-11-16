#!/usr/bin/env python3
"""Fichas técnicas pendentes — Tili Pizzaria (inclui lanches/hambúrguer) e Tili Sushi. SÓ LEITURA no ALIV.

Pedido do Emerson (16/11/2026): lista do que falta de ficha técnica nas duas lojas, na ordem do
que mais vende, para o custo da comida (CMV) sair certo. Sem ficha, o ALIV conta custo ZERO.

Lê (GET): cardápio (/admin/api/menu/full_data), ficha de cada produto/tamanho
(/admin/menu/product/{id}/recipes), ficha dos adicionais (/admin/menu/addon/{id}/recipe_matrix) e
o relatório de Produtos Vendidos (/admin/api/reports/products) dos últimos --dias dias.

Gera um PDF deitado (bom para iPad) com, por loja:
  1. produtos ativos SEM ficha (ordem: R$ vendido + uso em combos);
  2. fichas incompletas (falta em algum tamanho, item com quantidade zero, insumo sem custo);
  3. fichas suspeitas (custo da ficha menor que 10% ou maior que 60% do preço);
  4. adicionais e bordas sem ficha;
  5. itens vendidos sem custo que não estão no cardápio ativo.

Uso: fichas_pendentes.py [--dias 107] [--saida PASTA] [--whatsapp]
Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contagem  # noqa: E402
from monitor import TZ, Aliv, AlivError, brl  # noqa: E402

LOJAS = [("Tili Pizzaria (pizzas, lanches/hambúrguer, bebidas)", "ALIV_USER", "ALIV_PASS"),
         ("Tili Sushi & Poke", "ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")]
CMV_BAIXO, CMV_ALTO = 10.0, 60.0


def n(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def precos(menu: dict) -> dict:
    """id do produto → {tamanho|'Único': preço}."""
    tam = {s["id"]: s["name"] for s in menu.get("sizes", [])}
    out = {}
    for c in menu.get("categories", []):
        for p in c.get("products", []):
            sp = {tam.get(s.get("size_id"), "Único"): float(s.get("price") or 0) for s in p.get("size_prices") or []
                  if s.get("size_id")}
            out[p["id"]] = sp or {"Único": float(p.get("price") or 0)}
    return out


def analisar_loja(api: Aliv, ini: str, fim: str) -> dict:
    dados = contagem.coletar(api)
    menu = api.get("/admin/api/menu/full_data")
    rel = api.get("/admin/api/reports/products", {"start": ini, "end": fim})
    vend = defaultdict(lambda: [0.0, 0.0, 0.0])          # nome → [qtd, R$, custo]
    em_combo = Counter()
    for x in rel.get("report_data", []):
        v = vend[n(x["name"])]
        v[0] += x.get("qty") or 0
        v[1] += x.get("total") or 0
        v[2] += (x.get("avg_cost") or 0) * (x.get("qty") or 0)
        for c in x.get("compositions") or []:
            for l in c.get("lines") or []:
                if l.get("product_id"):
                    em_combo[str(l["product_id"])] += (c.get("qty") or 0) * (l.get("qty") or 1)
    pr = precos(menu)
    sem, incompletas, suspeitas = [], [], []
    for p in dados["produtos"]:
        v = vend.get(n(p["nome"]), [0, 0, 0])
        base = {"nome": p["nome"], "cat": p["categoria"], "qtd": v[0], "rs": v[1], "combo": em_combo.get(str(p["id"]), 0)}
        com = {k: its for k, its in p["fichas"].items() if its}
        vazias = [k for k, its in p["fichas"].items() if not its]
        if not com:
            sem.append(base)
            continue
        motivos = []
        if vazias:
            motivos.append("sem ficha no tamanho " + ", ".join(vazias))
        zero_q = sorted({i["nome"] or "?" for its in com.values() for i in its if not float(i.get("quantidade") or 0)})
        zero_c = sorted({i["nome"] or "?" for its in com.values() for i in its
                         if float(i.get("quantidade") or 0) and not float(i.get("custo") or 0)})
        if zero_q:
            motivos.append("quantidade zero: " + ", ".join(zero_q[:4]))
        if zero_c:
            motivos.append("insumo sem custo: " + ", ".join(zero_c[:4]))
        if motivos:
            incompletas.append({**base, "motivo": "; ".join(motivos)})
        for k, its in com.items():
            preco = pr.get(p["id"], {}).get(k) or 0
            custo = sum(float(i.get("custo") or 0) for i in its)
            if preco > 0 and custo > 0:
                pct = 100 * custo / preco
                if pct < CMV_BAIXO or pct > CMV_ALTO:
                    suspeitas.append({**base, "tam": k, "preco": preco, "custo": custo, "pct": pct,
                                      "motivo": "custo baixo demais (ficha incompleta?)" if pct < CMV_BAIXO
                                      else "custo alto demais (quantidade ou unidade errada? preço baixo?)"})
    def unicos(lista: list[dict], extra: str = "") -> list[dict]:
        """O mesmo produto pode estar em duas categorias (ex.: Promoção do Dia): junta numa linha."""
        vistos: dict = {}
        for x in lista:
            k = (n(x["nome"]), x.get(extra))
            if k in vistos:
                if x["cat"] not in vistos[k]["cat"]:
                    vistos[k]["cat"] += " / " + x["cat"]
                vistos[k]["combo"] = max(vistos[k]["combo"], x["combo"])
            else:
                vistos[k] = dict(x)
        return list(vistos.values())

    sem, incompletas, suspeitas = unicos(sem), unicos(incompletas), unicos(suspeitas, "tam")
    chave = lambda x: -(x["rs"] + x["combo"] * 5)  # noqa: E731
    sem.sort(key=chave)
    incompletas.sort(key=chave)
    suspeitas.sort(key=chave)
    ext_v = {n(x["name"]): x for x in rel.get("extras_data", []) + rel.get("edges_data", [])}
    cat_adic = {e["id"]: ", ".join(sorted({str(pc.get("category_name") or "") for pc in e.get("prices") or []} - {""}))
                for e in menu.get("extras", [])}
    adic = []
    for a in dados["adicionais"]:
        if not a["ingredientes"]:
            x = ext_v.get(n(a["nome"]), {})
            adic.append({"nome": a["nome"], "cat": cat_adic.get(a["id"], ""), "qtd": x.get("qty") or 0, "rs": x.get("total") or 0})
    adic.sort(key=lambda x: (x["cat"], -x["rs"], x["nome"]))
    ativos = {n(p["nome"]) for p in dados["produtos"]} | {n(c["name"]) for c in menu.get("combos", [])}
    fora = sorted(({"nome": k, "qtd": v[0], "rs": v[1]} for k, v in vend.items()
                   if v[2] == 0 and v[1] >= 300 and k not in ativos), key=lambda x: -x["rs"])
    total = sum(v[1] for v in vend.values())
    sem_custo = sum(v[1] for v in vend.values() if v[2] == 0)
    return {"ativos": len(dados["produtos"]), "sem": sem, "incompletas": incompletas, "suspeitas": suspeitas,
            "adicionais": adic, "fora": fora, "vendas": total, "vendas_sem_custo": sem_custo,
            "n_adicionais": len(dados["adicionais"])}


E = html.escape
num = lambda v: f"{v:,.0f}".replace(",", ".")  # noqa: E731


def tabela(cab: list[str], linhas: list[list[str]], alinhar: str = "") -> str:
    th = "".join(f"<th>{E(c)}</th>" for c in cab)
    tr = "".join("<tr>" + "".join(f'<td class="{"r" if alinhar[i:i + 1] == "r" else ""}">{c}</td>'
                                  for i, c in enumerate(l)) + "</tr>" for l in linhas)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def html_relatorio(R: list[tuple[str, dict]], ini: str, fim: str, agora: datetime) -> str:
    logo = contagem._logo()
    partes = []
    for nome, a in R:
        pct = 100 * a["vendas_sem_custo"] / a["vendas"] if a["vendas"] else 0
        s = [f'<div class="loja{"" if partes else " primeira"}"><h2>{E(nome)}</h2>'
             f'<div class="kpis"><div><b>{len(a["sem"])}</b>produtos sem ficha<br>(de {a["ativos"]} ativos)</div>'
             f'<div><b>{len(a["incompletas"])}</b>fichas incompletas</div>'
             f'<div><b>{len(a["suspeitas"])}</b>fichas suspeitas</div>'
             f'<div><b>{len(a["adicionais"])}</b>adicionais/bordas sem ficha<br>(de {a["n_adicionais"]})</div>'
             f'<div class="alerta"><b>{pct:.0f}%</b>das vendas com custo ZERO<br>({brl(a["vendas_sem_custo"])} de {brl(a["vendas"])})</div></div>']
        if a["sem"]:
            s.append("<h3>1 · Produtos ativos SEM ficha técnica — comece pelos de cima</h3>")
            s.append(tabela(["#", "Produto", "Categoria", "Vendeu (qtd)", "Vendeu (R$)", "Usado em combos", "Feito ✓"],
                            [[str(i), E(x["nome"]), E(x["cat"]), num(x["qtd"]), brl(x["rs"]), num(x["combo"]) if x["combo"] else "—", "☐"]
                             for i, x in enumerate(a["sem"], 1)], "r__rrr_"))
        if a["incompletas"]:
            s.append("<h3>2 · Fichas incompletas</h3>")
            s.append(tabela(["Produto", "Categoria", "Vendeu (R$)", "O que falta", "Feito ✓"],
                            [[E(x["nome"]), E(x["cat"]), brl(x["rs"]), E(x["motivo"]), "☐"] for x in a["incompletas"]], "__r__"))
        if a["suspeitas"]:
            s.append(f"<h3>3 · Fichas suspeitas (custo menor que {CMV_BAIXO:.0f}% ou maior que {CMV_ALTO:.0f}% do preço) — conferir</h3>")
            s.append(tabela(["Produto", "Tamanho", "Preço", "Custo da ficha", "% do preço", "Vendeu (R$)", "Por quê"],
                            [[E(x["nome"]), E(x["tam"]), brl(x["preco"]), brl(x["custo"]), f'{x["pct"]:.0f}%', brl(x["rs"]), E(x["motivo"])]
                             for x in a["suspeitas"]], "__rrrr_"))
        if a["adicionais"]:
            s.append("<h3>4 · Adicionais e bordas sem ficha</h3>")
            por_cat: dict = {}
            for x in a["adicionais"]:
                por_cat.setdefault(x.get("cat") or "Outros", []).append(x)
            for cat, xs in por_cat.items():
                s.append(f'<div class="chips"><b>{E(cat)}:</b> ' + "".join(f'<span>{E(x["nome"])}</span>' for x in xs) + "</div>")
        if a["fora"]:
            s.append("<h3>5 · Vendidos sem custo e fora do cardápio ativo (conferir se ainda existem)</h3>")
            s.append('<div class="chips">' + "".join(f'<span>{E(x["nome"])} · {brl(x["rs"])}</span>' for x in a["fora"]) + "</div>")
        s.append("</div>")
        partes.append("".join(s))
    d = lambda x: datetime.fromisoformat(x).strftime("%d/%m")  # noqa: E731
    return f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><style>
@page {{ size: A4 landscape; margin: 9mm; }}
* {{ box-sizing: border-box; }} body {{ font-family: Arial, Helvetica, sans-serif; color: #1c1c1c; font-size: 11.5px; margin: 0; }}
.topo {{ display: flex; align-items: center; gap: 12px; border-bottom: 3px solid #d62828; padding-bottom: 8px; }}
.topo img {{ height: 46px; border-radius: 8px; }} .topo .t {{ font-size: 21px; font-weight: 800; color: #d62828; }}
.topo .s {{ color: #555; font-size: 12px; }}
.como {{ background: #fff7e6; border: 1px solid #f0c36d; border-radius: 8px; padding: 8px 10px; margin: 8px 0; font-size: 12px; }}
.loja {{ page-break-before: always; }} .loja.primeira {{ page-break-before: auto; }}
h2 {{ background: #d62828; color: #fff; padding: 7px 10px; border-radius: 8px; font-size: 16px; margin: 10px 0 8px; }}
h3 {{ font-size: 13px; margin: 12px 0 5px; color: #9d1c1c; }}
.kpis {{ display: flex; gap: 8px; }} .kpis div {{ flex: 1; border: 1px solid #ddd; border-radius: 8px; padding: 7px; text-align: center; font-size: 11px; color: #444; }}
.kpis b {{ display: block; font-size: 22px; color: #1c1c1c; }} .kpis .alerta {{ background: #fdecea; border-color: #d62828; }} .kpis .alerta b {{ color: #d62828; }}
table {{ width: 100%; border-collapse: collapse; }} th {{ background: #f1f1f1; text-align: left; padding: 5px 6px; font-size: 11px; border-bottom: 2px solid #ccc; }}
td {{ padding: 4.5px 6px; border-bottom: 1px solid #e6e6e6; vertical-align: top; }} td.r {{ text-align: right; white-space: nowrap; }}
tr {{ page-break-inside: avoid; }} thead {{ display: table-header-group; }}
.chips span {{ display: inline-block; border: 1px solid #ccc; border-radius: 12px; padding: 3px 9px; margin: 2px 3px 2px 0; font-size: 11px; }}
</style></head><body>
<div class="topo">{f'<img src="{logo}">' if logo else ''}<div><div class="t">Fichas técnicas pendentes</div>
<div class="s">Tili Pizzaria e Tili Sushi · vendas de {d(ini)} a {d(fim)} · gerado em {agora:%d/%m/%Y %H:%M}</div></div></div>
<div class="como"><b>Por que importa:</b> produto sem ficha técnica entra no ALIV com custo <b>zero</b>. O estoque não baixa e o custo
da comida (CMV) sai errado. <b>Onde fazer:</b> ALIV → Estoque → <b>Fichas e Produção</b> (produto → insumos e quantidades de cada tamanho).
<b>Ordem:</b> de cima para baixo — os primeiros de cada lista são os que mais vendem.</div>
{''.join(partes)}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Fichas técnicas pendentes (Pizzaria e Sushi)")
    ap.add_argument("--dias", type=int, default=107, help="período de vendas para ordenar (padrão 107 dias)")
    ap.add_argument("--saida", help="pasta do PDF (padrão: temporária)")
    ap.add_argument("--whatsapp", action="store_true")
    a = ap.parse_args()
    agora = datetime.now(TZ)
    fim, ini = agora.date().isoformat(), (agora.date() - timedelta(days=a.dias)).isoformat()
    R, api1 = [], None
    for nome, u, p in LOJAS:
        if not os.environ.get(u):
            continue
        api = Aliv(os.environ[u], os.environ[p])
        api.timeout = 180
        try:
            api.login()
            R.append((nome, analisar_loja(api, ini, fim)))
        except (AlivError, OSError) as e:
            print(f"Tili — Fichas pendentes — ERRO no ALIV ({nome})\n\n{e}")
            return 1
        api1 = api1 or api
    pasta = Path(a.saida) if a.saida else Path(tempfile.mkdtemp())
    pasta.mkdir(parents=True, exist_ok=True)
    pdf = pasta / f"Fichas_pendentes_Tili_{agora:%Y-%m-%d}.pdf"
    from diaristas import html_para_pdf
    html_para_pdf(html_relatorio(R, ini, fim, agora), pdf)
    (pasta / "fichas_pendentes.json").write_text(json.dumps(dict(R), ensure_ascii=False, indent=1), encoding="utf-8")
    linhas = ["*Tili — Fichas técnicas pendentes*"]
    for nome, x in R:
        pct = 100 * x["vendas_sem_custo"] / x["vendas"] if x["vendas"] else 0
        linhas.append(f"{nome.split(' (')[0]}: {len(x['sem'])} sem ficha, {len(x['incompletas'])} incompletas, "
                      f"{len(x['suspeitas'])} suspeitas, {len(x['adicionais'])} adicionais sem ficha · "
                      f"{pct:.0f}% das vendas com custo zero")
        if x["sem"]:
            linhas.append("  Primeiro: " + ", ".join(f"{s['nome']} ({brl(s['rs'])})" for s in x["sem"][:5]))
    texto = "\n".join(linhas)
    print(texto)
    print(f"PDF: {pdf}")
    if a.whatsapp:
        try:
            fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
            api1.enviar_whatsapp(fone, texto[:3800])
            api1.enviar_whatsapp(fone, "Lista de fichas técnicas pendentes (PDF)", arquivo=pdf)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
