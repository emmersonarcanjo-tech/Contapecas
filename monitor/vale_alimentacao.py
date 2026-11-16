#!/usr/bin/env python3
"""Vale alimentação/refeição dos CLT (Pizzaria e Sushi) — conta do mês no ALIV.

Regra do Emerson (16/11/2026): R$ 600 por funcionário com carteira (VR 200 + VA 400), pago
no dia 30 pelo mês trabalhado (1 a 30); quem não completou o mês recebe proporcional
(R$ 600 × dias ÷ 30, contando da entrada). Cada funcionário na loja onde trabalha.
Pago por cartão de benefício (Alelo; a partir de 11/2026 iFood Benefícios) — a conta fica
EM ABERTO (boleto), a baixa vem do comprovante. Gerentes entram na loja deles (Pizzaria) e
são divididos pelo rateio mensal.

Faltas injustificadas (Emerson, 16/11/2026): R$ 20 por falta (600 ÷ 30), descontadas no vale
do MÊS SEGUINTE. Vêm do fechamento de ponto do Flit (Rotina do dia 1, no computador), que grava
monitor/vale/faltas/AAAA-MM.json = {"Nome Completo": nº de faltas injustificadas do mês}.
Sem o arquivo do mês anterior, o vale sai sem desconto e o resumo avisa.

Uso: vale_alimentacao.py [--mes AAAA-MM] [--confirmar] [--whatsapp]
Ajusta a conta "Vale alimentação…" do mês (valor e vencimento no dia 30) ou cria uma nova.
Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import calendar
import json
import unicodedata
import os
import re
import sys
import urllib.request
import uuid
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, TZ, Aliv, AlivError, brl  # noqa: E402

VALOR_MES = 600.0
LOJAS = [("Pizzaria", "ALIV_USER", "ALIV_PASS"), ("Sushi", "ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")]
FALTAS = Path(__file__).resolve().parent / "vale" / "faltas"
POR_FALTA = VALOR_MES / 30
ADMISSAO_REAL = {"tamile de jesus santos": "2026-08-11"}   # ALIV do Sushi usa 01/11 (gerencial)


def form(api, path, c):
    k = uuid.uuid4().hex
    body = "".join(f'--{k}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'
                   for n, v in c.items()) + f"--{k}--\r\n"
    return api._send(urllib.request.Request(BASE_URL + path, data=body.encode(), method="POST",
                                            headers={"Content-Type": f"multipart/form-data; boundary={k}",
                                                     "Accept": "application/json"}))


def _n(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower().split()
    return f"{s[0]} {s[-1]}" if s else ""


def faltas_mes_anterior(ini: date) -> dict | None:
    ant = (ini.replace(day=1) - __import__("datetime").timedelta(days=1))
    try:
        d = json.loads((FALTAS / f"{ant:%Y-%m}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {_n(k): int(v) for k, v in d.items() if int(v or 0) > 0}


def calcular(api, ini: date, fim: date, faltas: dict | None = None) -> tuple[float, list[str]]:
    tot, parciais = 0.0, []
    for r in api.get("/admin/api/finance/payroll/list").get("rows", []):
        if not r.get("is_registered") or r.get("role") in ("driver", "owner"):
            continue
        h = date.fromisoformat(ADMISSAO_REAL.get(r["name"].lower()) or str(r.get("hired_at") or "2000-01-01")[:10])
        if h > fim:
            continue
        dias = 30 if h <= ini else max(0, 30 - h.day + 1)
        f = (faltas or {}).get(_n(r["name"]), 0)
        v = round(max(0.0, VALOR_MES * dias / 30 - f * POR_FALTA), 2)
        tot += v
        if dias < 30 or f:
            parciais.append(f"{r['name'].split()[0]} {dias} dias" + (f" − {f} falta(s)" if f else "") + f" = {brl(v)}")
    return round(tot, 2), parciais


def main() -> int:
    ap = argparse.ArgumentParser(description="Vale alimentação/refeição do mês no ALIV")
    ap.add_argument("--mes", help="AAAA-MM (padrão: mês atual)")
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--whatsapp", action="store_true")
    a = ap.parse_args()
    hoje = datetime.now(TZ).date()
    ini = date.fromisoformat(a.mes + "-01") if a.mes else hoje.replace(day=1)
    ult = calendar.monthrange(ini.year, ini.month)[1]
    fim, venc = ini.replace(day=ult), ini.replace(day=min(30, ult))
    linhas, api = [], None
    faltas = faltas_mes_anterior(ini)
    if faltas is None:
        linhas.append("⚠️ Sem a lista de faltas do mês passado (fechamento de ponto) — vale sem desconto de faltas.")
    for loja, u, p in LOJAS:
        api = Aliv(os.environ[u], os.environ[p])
        try:
            api.login()
            v, parciais = calcular(api, ini, fim, faltas)
            b = api.get("/admin/finance/bills", {"bill_type": "payable", "status": "all"})
            b = b if isinstance(b, list) else b.get("bills", [])
            conta = next((x for x in b if str(x.get("description", "")).lower().startswith("vale alimenta")
                          and str(x.get("due_date", ""))[:7] == ini.isoformat()[:7] and not x.get("paid_at")), None)
            txt = f"{loja}: {brl(v)}" + (f" (ajustes: {', '.join(parciais)})" if parciais else "")
            if a.confirmar:
                if conta:
                    c = {"bill_id": conta["id"], "description": conta["description"],
                         "payment_method": conta.get("payment_method") or "Boleto via DDA",
                         "category_id": conta["category_id"], "document_number": conta.get("document_number") or "",
                         "is_recurring": "true" if conta.get("is_recurring") else "false"}
                    if conta.get("is_recurring"):
                        c["recurrence"] = conta.get("recurrence") or "mensal"
                else:
                    cats = {x["name"]: x["id"] for x in api.get("/admin/finance/categories")}
                    c = {"description": f"Vale alimentação/refeição — {ini:%m/%Y}", "payment_method": "Boleto via DDA",
                         "category_id": cats.get("Benefícios") or "", "is_recurring": "false"}
                c.update({"bill_type": "payable", "amount": f"{v:.2f}", "due_date": venc.isoformat(), "installments": "1"})
                st, d = form(api, "/admin/finance/bills/save", c)
                txt = ("✓ " if st == 200 and isinstance(d, dict) and d.get("success") else f"✗ ({str(d)[:80]}) ") + txt
            linhas.append(txt)
        except (AlivError, OSError) as e:
            print(f"Tili — Vale alimentação — ERRO no ALIV ({loja})\n\n{e}")
            return 1
    texto = (f"*Tili — Vale alimentação/refeição {ini:%m/%Y}* (vence {venc:%d/%m}, em aberto)"
             + ("" if a.confirmar else " — TESTE, nada lançado") + "\n" + "\n".join(linhas))
    print(texto)
    if a.whatsapp:
        try:
            api.enviar_whatsapp(re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", "")), texto[:3800])
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
