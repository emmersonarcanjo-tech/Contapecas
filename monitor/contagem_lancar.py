#!/usr/bin/env python3
"""Lança a contagem física (planilha preenchida) na Conferência de Estoque do ALIV — loja 150.

SÓ RODA COM O COMANDO DO EMERSON. Sem --confirmar é dry-run: lê a planilha e o ALIV, mostra o que
seria lançado e não grava nada.

Planilha: a gerada por monitor/contagem.py (manuais/Folha_de_Contagem_Tili_Pizzaria.xlsx).
  Aba "Contagem": coluna "Quantidade contada" (na unidade de contagem). Em branco = não lança.
    Quantidade enviada ao ALIV = contada × "Fator p/ estoque ALIV" (padrão 1), na unidade de estoque.
  Aba "Decidir (Parte 2)": "zerar" na coluna Decisão lança 0 (se o item não tiver contagem na aba Contagem).

API da conferência (a mesma da tela Estoque → Conferência):
  GET  /admin/inventory/check/current        sessão aberta e itens (id do item ↔ ingredient_id)
  POST /admin/inventory/check/start          abre a conferência (só com --confirmar e se não houver uma aberta)
  POST /admin/inventory/check/update-item    item_id, quantity, operation
       - zera:   operation=set, quantity=0     (botão "zerar" da tela)
       - conta:  operation=add, quantity=N     (botão "+" da tela)
    Para gravar o número exato, zera e soma. Item que já tem contagem na sessão só é regravado com --sobrescrever.

NÃO finaliza a conferência: o ajuste do estoque é feito pelo Emerson na tela (responsável + senha).

Uso:
  python3 monitor/contagem_lancar.py manuais/Folha_de_Contagem_Tili_Pizzaria.xlsx              # dry-run
  python3 monitor/contagem_lancar.py manuais/Folha_de_Contagem_Tili_Pizzaria.xlsx --confirmar  # lança

Códigos de saída: 0 ok · 1 erro no ALIV · 2 faltam variáveis ou planilha inválida · 3 lançou com falhas.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, Aliv, AlivError  # noqa: E402


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def numero(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(" ", "")
    if "," in t:                      # 1.234,5 → 1234.5
        t = t.replace(".", "").replace(",", ".")
    return float(t)


def fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


# --------------------------------------------------------------- planilha
def ler_planilha(arq: Path) -> tuple[list[dict], list[str]]:
    from openpyxl import load_workbook
    wb = load_workbook(arq, data_only=True)
    # aba "Contagem"; se veio do Google Planilhas com outro nome, usa a 1ª aba
    ws = wb["Contagem"] if "Contagem" in wb.sheetnames else wb.worksheets[0]
    cab, ini = None, None
    for r in range(1, 11):
        vals = [norm(c.value) for c in ws[r]]
        if "id aliv" in vals and "quantidade contada" in vals:
            cab, ini = {v: i for i, v in enumerate(vals) if v}, r + 1
            break
    if not cab:
        raise ValueError("cabeçalho da aba 'Contagem' não encontrado (ID ALIV / Quantidade contada)")

    itens, erros = {}, []
    for r, row in enumerate(ws.iter_rows(min_row=ini, values_only=True), ini):
        def col(nome):
            i = cab.get(nome)
            return row[i] if i is not None and i < len(row) else None
        if col("id aliv") in (None, ""):
            continue
        try:
            iid = int(col("id aliv"))
            q = numero(col("quantidade contada"))
            fator = numero(col("fator p/ estoque aliv"))
        except (TypeError, ValueError):
            erros.append(f"linha {r}: número inválido ({col('insumo')})")
            continue
        if q is None:
            continue
        fator = 1.0 if fator is None else fator
        if q < 0 or fator <= 0:
            erros.append(f"linha {r}: quantidade/fator negativo ou zero ({col('insumo')})")
            continue
        if iid in itens:
            erros.append(f"linha {r}: insumo {iid} repetido — somei as duas linhas")
            itens[iid]["quantidade"] += q * fator
            continue
        itens[iid] = {"id": iid, "nome": col("insumo"), "contado": q, "fator": fator, "quantidade": q * fator,
                      "unidade": col("unid. estoque aliv") or col("unid. contagem"), "origem": f"linha {r}",
                      "obs": col("observacao")}

    if "Decidir (Parte 2)" in wb.sheetnames:
        w2 = wb["Decidir (Parte 2)"]
        cab2 = {norm(c.value): i for i, c in enumerate(w2[1]) if c.value}
        idec = next((i for k, i in cab2.items() if k.startswith("decisao")), None)
        if idec is not None and "id aliv" in cab2:
            for r, row in enumerate(w2.iter_rows(min_row=2, values_only=True), 2):
                if row[cab2["id aliv"]] in (None, "") or norm(row[idec]) != "zerar":
                    continue
                iid = int(row[cab2["id aliv"]])
                if iid not in itens:
                    itens[iid] = {"id": iid, "nome": row[cab2.get("insumo", 1)], "contado": 0.0, "fator": 1.0,
                                  "quantidade": 0.0, "unidade": row[cab2.get("unid.", 4)],
                                  "origem": f"Decidir linha {r} (zerar)", "obs": None}
    return list(itens.values()), erros


# --------------------------------------------------------------- ALIV
def post_form(api: Aliv, path: str, campos: dict) -> tuple[int, dict]:
    body = urllib.parse.urlencode({k: str(v) for k, v in campos.items()}).encode()
    req = urllib.request.Request(BASE_URL + path, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                                          "Accept": "application/json"})
    st, data = api._send(req)
    if st == 401:
        api.login()
        st, data = api._send(req)
    return st, data


def sessao(api: Aliv) -> dict:
    r = api.get("/admin/inventory/check/current") or {}
    return r if isinstance(r, dict) else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Lança a contagem física na Conferência do ALIV (dry-run por padrão).")
    ap.add_argument("planilha", type=Path)
    ap.add_argument("--confirmar", action="store_true", help="grava no ALIV (sem isto, só mostra)")
    ap.add_argument("--sobrescrever", action="store_true", help="regrava itens que já têm contagem na sessão aberta")
    ap.add_argument("--json", type=Path, help="grava o resultado em JSON (para a Rotina/registro)")
    args = ap.parse_args()

    if not args.planilha.exists():
        print(f"Planilha não encontrada: {args.planilha}")
        return 2
    try:
        itens, erros = ler_planilha(args.planilha)
    except Exception as e:  # noqa: BLE001
        print(f"Planilha inválida: {e}")
        return 2
    if not os.environ.get("ALIV_USER") or not os.environ.get("ALIV_PASS"):
        print("Faltam ALIV_USER/ALIV_PASS.")
        return 2

    modo = "LANÇAMENTO" if args.confirmar else "DRY-RUN (nada é gravado)"
    print(f"Contagem física → Conferência do ALIV · Tili Pizzaria · {modo}")
    print(f"Planilha: {args.planilha.name} · {len(itens)} itens com quantidade")
    for e in erros:
        print(f"  ! {e}")

    try:
        api = Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"], timeout=60)
        r = api.get("/admin/inventory/api/ingredients")
        ins = {int(x["id"]): x for x in (r.get("ingredients", []) if isinstance(r, dict) else r or [])}
        s = sessao(api)
    except AlivError as e:
        print(f"Erro no ALIV: {e}")
        return 1

    ok, recusados = [], []
    for it in itens:
        x = ins.get(it["id"])
        if not x:
            recusados.append((it, "não existe mais no ALIV"))
        elif x.get("is_paused"):
            recusados.append((it, "insumo pausado no ALIV"))
        elif it["nome"] and norm(it["nome"]) not in {norm(x.get("display_name")), norm(x.get("name"))}:
            recusados.append((it, f"nome não bate com o ALIV ({x.get('display_name') or x.get('name')})"))
        elif it["unidade"] and norm(it["unidade"]) != norm(x.get("unit")):
            recusados.append((it, f"unidade mudou no ALIV ({it['unidade']} → {x.get('unit')}); gere a planilha de novo"))
        else:
            it["unidade"] = x.get("unit")
            ok.append(it)

    aberta = bool(s.get("session"))
    por_ing = {int(i["ingredient_id"]): i for i in s.get("items") or [] if i.get("ingredient_id")}
    if aberta:
        ses = s["session"]
        print(f"Conferência aberta no ALIV: nº {ses.get('id')} de {ses.get('created_at')} "
              f"({len(por_ing)} itens, {sum(1 for i in por_ing.values() if i.get('is_checked'))} já contados)")
    else:
        print("Nenhuma conferência aberta no ALIV — " + ("vou abrir uma." if args.confirmar else "com --confirmar, abre uma."))

    print(f"\nA lançar ({len(ok)}):")
    for it in sorted(ok, key=lambda i: norm(i["nome"])):
        conv = f" ({fmt(it['contado'])} × {fmt(it['fator'])})" if it["fator"] != 1 else ""
        ja = por_ing.get(it["id"])
        aviso = ""
        if ja and ja.get("is_checked"):
            aviso = f" · já contado {fmt(float(ja.get('counted_stock') or 0))}" + ("" if args.sobrescrever else " → PULA")
        elif aberta and not ja:
            aviso = " · fora da conferência"
        print(f"  {it['id']:>6} {str(it['nome'])[:45]:45} {fmt(it['quantidade']):>10} {it['unidade']}{conv}{aviso}")
    if recusados:
        print(f"\nNão lançados ({len(recusados)}):")
        for it, mot in recusados:
            print(f"  {it['id']:>6} {str(it['nome'])[:45]:45} {mot}")

    resultado = {"modo": "confirmar" if args.confirmar else "dry-run", "lancados": [], "falhas": [],
                 "pulados": [], "recusados": [{"id": i["id"], "nome": i["nome"], "motivo": m} for i, m in recusados]}

    if args.confirmar and erros:
        print("\nA planilha tem linhas com erro (acima). Corrija e rode de novo — nada foi lançado.")
        return 2
    if args.confirmar and ok:
        if not aberta:
            st, d = post_form(api, "/admin/inventory/check/start", {})
            if st != 200:
                print(f"\nFalha ao abrir a conferência (HTTP {st}): {str(d)[:200]}")
                return 1
            s = sessao(api)
            if not s.get("session"):
                print("\nO ALIV não abriu a conferência.")
                return 1
            por_ing = {int(i["ingredient_id"]): i for i in s.get("items") or [] if i.get("ingredient_id")}
            print(f"\nConferência nº {s['session'].get('id')} aberta.")
        for it in ok:
            item = por_ing.get(it["id"])
            if not item:
                resultado["falhas"].append({"id": it["id"], "nome": it["nome"], "motivo": "fora da conferência do ALIV"})
                continue
            if item.get("is_checked") and not args.sobrescrever:
                resultado["pulados"].append({"id": it["id"], "nome": it["nome"], "ja_contado": item.get("counted_stock")})
                continue
            st, d = post_form(api, "/admin/inventory/check/update-item",
                              {"item_id": item["id"], "quantity": 0, "operation": "set", "remove_index": -1})
            if st == 200 and it["quantidade"] > 0:
                st, d = post_form(api, "/admin/inventory/check/update-item",
                                  {"item_id": item["id"], "quantity": round(it["quantidade"], 4), "operation": "add",
                                   "remove_index": -1})
            total = d.get("new_total") if isinstance(d, dict) else None
            if st == 200 and total is not None and abs(float(total) - it["quantidade"]) < 1e-6:
                resultado["lancados"].append({"id": it["id"], "nome": it["nome"], "quantidade": it["quantidade"]})
            else:
                resultado["falhas"].append({"id": it["id"], "nome": it["nome"],
                                            "motivo": f"HTTP {st}: total {total} — {str(d)[:120]}"})
        print(f"\nLançados: {len(resultado['lancados'])} · pulados (já contados): {len(resultado['pulados'])} · "
              f"falhas: {len(resultado['falhas'])}")
        for f in resultado["falhas"]:
            print(f"  FALHA {f['id']} {f['nome']}: {f['motivo']}")
        print("A conferência continua ABERTA. Para ajustar o estoque: ALIV → Estoque → Conferência → Finalizar.")
    elif not args.confirmar:
        print("\nDry-run: nada foi gravado. Para lançar, rode de novo com --confirmar (só com ok do Emerson).")

    if args.json:
        args.json.write_text(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 3 if resultado["falhas"] else 0


if __name__ == "__main__":
    sys.exit(main())
