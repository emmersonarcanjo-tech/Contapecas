#!/usr/bin/env python3
"""Custos das fichas técnicas para o app Monta Oferta — Tili Pizzaria (loja 150). SÓ LEITURA no ALIV.

Pedido do Emerson (21/11/2026): lista com o custo de cada produto do cardápio ativo (pizzas por
tamanho, lanches, porções, bebidas e bordas) para o app Monta Oferta montar ofertas com margem.

Lê (GET): cardápio (/admin/api/menu/full_data), ficha de cada produto/tamanho
(/admin/menu/product/{id}/recipes), custo atual dos insumos (/admin/inventory/api/ingredients) e,
só para o resumo na tela, os Produtos Vendidos (/admin/api/reports/products) dos últimos --dias dias.

Custo da ficha = soma de quantidade × custo atual de cada insumo (na unidade de uso da ficha).

Grava monitor/fichas/produtos.json: {"gerado_em", "loja", "produtos": [um item por produto e tamanho]}.
Não grava CNPJ, CPF, senha, fornecedor nem nome de insumo.

Uso: fichas_custos.py [--dias 30] [--saida ARQUIVO] [--detalhe "nome do produto"]
Saída: 0 ok, 1 erro ALIV.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import TZ, Aliv, AlivError, brl  # noqa: E402

SAIDA = Path(__file__).resolve().parent / "fichas" / "produtos.json"
TAMANHOS = {268: "P", 269: "M", 270: "G"}
# Bebida e revenda: o custo é o do insumo comprado (nota), não há ficha de preparo.
CATEGORIAS_NOTA = ("bebida", "revenda")
# Insumos que toda pizza/lanche leva: ficha só com eles está sem o ingrediente principal.
BASE = ("massa", "molho de tomate", "mussarela", "oregano", "azeitona", "creme de leite", "caixa", "embalagem",
        "sache", "mesinha", "pao", "papel", "guardanapo", "maionese")
# Produtos em que a base já é o produto inteiro.
SO_BASE_OK = ("mussarela",)


def n(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip().replace("mucarela", "mussarela")


def custo_unitario(ins: dict | None, unidade_ficha: str) -> float:
    """Custo atual do insumo na unidade usada na ficha (ex.: compra em KG, ficha em G → ÷ 1000)."""
    if not ins:
        return 0.0
    custo = float(ins.get("cost") or 0)
    fator = float(ins.get("conversion_factor") or 1) or 1
    if fator != 1 and n(unidade_ficha) == n(ins.get("usage_unit")) and n(unidade_ficha) != n(ins.get("unit")):
        return custo / fator
    return custo


def coletar(api: Aliv) -> tuple[list[dict], dict]:
    r = api.get("/admin/inventory/api/ingredients")
    insumos = {i["id"]: i for i in (r.get("ingredients", []) if isinstance(r, dict) else r or [])}
    menu = api.get("/admin/api/menu/full_data")
    tarefas = []
    for c in menu.get("categories", []):
        for p in c.get("products", []):
            if not p.get("is_active"):
                continue
            tams = [s for s in p.get("size_prices") or [] if s.get("size_id")]
            for s in tams or [None]:
                tarefas.append({"id": p["id"], "nome": p["name"], "categoria": c["name"],
                                "size_id": s["size_id"] if s else None,
                                "preco": float((s or p).get("price") or 0)})

    def ficha(t):
        q = f"?size_id={t['size_id']}" if t["size_id"] else ""
        return t, api.get(f"/admin/menu/product/{t['id']}/recipes{q}") or []

    with ThreadPoolExecutor(max_workers=6) as ex:
        for t, itens in ex.map(ficha, tarefas):
            t["itens"] = [{"nome": i.get("ingredient_name") or i.get("ingredient_raw_name") or "?",
                           "quantidade": float(i.get("quantity") or 0), "unidade": i.get("ingredient_unit") or "",
                           "custo_un": custo_unitario(insumos.get(i.get("ingredient_id")), i.get("ingredient_unit") or "")}
                          for i in itens]
    return tarefas, insumos


def montar(tarefas: list[dict]) -> list[dict]:
    # Primeira palavra dos insumos usados nas fichas (banana, bacon, frango…): se está no nome do
    # produto e não está na ficha dele, falta o ingrediente principal.
    palavras = {n(i["nome"]).split(" ")[0] for t in tarefas for i in t["itens"]} - {""}
    palavras = {p for p in palavras if len(p) >= 4 and not any(p.startswith(b) for b in BASE)}
    out = []
    for t in tarefas:
        itens = t["itens"]
        nota = any(k in n(t["categoria"]) for k in CATEGORIAS_NOTA)
        custo = sum(i["quantidade"] * i["custo_un"] for i in itens)
        motivos = []
        if itens:
            if any(i["quantidade"] <= 0 or i["custo_un"] <= 0 for i in itens):
                motivos.append("insumo com custo ou quantidade zero")
            nomes = [n(i["nome"]) for i in itens]
            nome_prod = n(t["nome"])
            if not nota:
                so_base = all(any(x.startswith(b) for b in BASE) for x in nomes)
                if so_base and not any(k in nome_prod for k in SO_BASE_OK):
                    motivos.append("só a base")
                faltam = [p for p in palavras if re.search(rf"\b{re.escape(p)}\b", nome_prod)
                          and not any(p in x for x in nomes)]
                if faltam:
                    motivos.append("falta " + ", ".join(sorted(faltam)))
        out.append({"id": t["id"], "nome": t["nome"], "categoria": t["categoria"],
                    "tamanho": TAMANHOS.get(t["size_id"], ""), "custo": round(custo, 2),
                    "tipo": "nota" if nota else "ficha", "preco_cardapio": round(t["preco"], 2),
                    "sem_ficha": not itens, "incompleta": bool(motivos), "_motivo": "; ".join(motivos)})
    return out


def vendas(api: Aliv, dias: int) -> dict:
    """nome normalizado → quantidade vendida nos últimos `dias` dias (só para o resumo)."""
    fim = datetime.now(TZ).date()
    rel = api.get("/admin/api/reports/products", {"start": (fim - timedelta(days=dias)).isoformat(), "end": fim.isoformat()})
    v: dict = {}
    for x in rel.get("report_data", []):
        v[n(x["name"])] = v.get(n(x["name"]), 0) + (x.get("qty") or 0)
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description="Custos das fichas para o app Monta Oferta (só leitura).")
    ap.add_argument("--dias", type=int, default=30, help="dias de vendas para o resumo")
    ap.add_argument("--saida", type=Path, default=SAIDA)
    ap.add_argument("--detalhe", help="mostra a conta da ficha dos produtos com este nome")
    a = ap.parse_args()
    try:
        api = Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"])
        tarefas, _ = coletar(api)
        vend = vendas(api, a.dias)
    except (AlivError, KeyError) as e:
        print(f"ERRO ALIV: {e}", file=sys.stderr)
        return 1
    if a.detalhe:
        for t in tarefas:
            if n(a.detalhe) == n(t["nome"]):
                print(f"\n{t['nome']} {TAMANHOS.get(t['size_id'], '')} — preço {brl(t['preco'])}")
                for i in t["itens"]:
                    print(f"  {i['nome']:<32} {i['quantidade']:>8g} {i['unidade']:<3} × {i['custo_un']:>9.4f} = "
                          f"{i['quantidade'] * i['custo_un']:>7.4f}")
                print(f"  {'TOTAL':<32} {sum(i['quantidade'] * i['custo_un'] for i in t['itens']):>33.2f}")
    itens = montar(tarefas)
    a.saida.parent.mkdir(parents=True, exist_ok=True)
    doc = {"gerado_em": datetime.now(TZ).isoformat(timespec="minutes"), "loja": "Tili Pizzaria",
           "produtos": [{k: v for k, v in x.items() if not k.startswith("_")} for x in itens]}
    a.saida.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    produtos = {x["id"] for x in itens}
    pend = {x["id"] for x in itens if x["sem_ficha"] or x["incompleta"]}
    sem_custo: dict = {}
    for x in itens:
        if x["custo"] <= 0:
            sem_custo[x["nome"]] = vend.get(n(x["nome"]), 0)
    top = sorted(sem_custo.items(), key=lambda kv: -kv[1])[:5]
    for x in itens:
        if x["incompleta"]:
            print(f"incompleta: {x['nome']} {x['tamanho']} — {x['_motivo']}")
    print(f"\nGravado {a.saida} ({len(itens)} linhas)")
    print(f"Produtos: {len(produtos)} ({len(itens)} linhas, contando os tamanhos das pizzas).")
    print(f"Sem ficha ou incompletos: {len(pend)} (sem ficha: {len({x['id'] for x in itens if x['sem_ficha']})}; "
          f"incompletos: {len({x['id'] for x in itens if x['incompleta']})}).")
    print(f"Mais vendidos sem custo ({a.dias} dias): " + "; ".join(f"{k} ({v:g})" for k, v in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
