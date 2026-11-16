#!/usr/bin/env python3
"""Lança na Folha do ALIV os pagamentos da equipe CLT (Tili Pizzaria e Tili Sushi).

Cada funcionário fica na Folha da loja onde trabalha (15/11/2026: Djalma, Jamaria,
Luiz Fernando e Tamile passaram para o Sushi), mesmo registrado na outra loja.

Regra do Emerson (15/11/2026): a folha é paga pelo Bradesco; o ALIV precisa
registrar os pagamentos para o DRE sair certo. A Folha do ALIV trabalha em duas
etapas por competência (mês trabalhado):
  - adiantamento (vale de 40% do salário) no dia 20 do próprio mês;
  - saldo do mês no dia 5 do mês seguinte.
Para cada funcionário registrado (CLT), lança TODAS as etapas que já venceram até
--ate (padrão: hoje), com os valores que o próprio ALIV calcula, na data de
vencimento de cada etapa, saindo do BRADESCO (forma "PAGAMENTO DE FOLHA - BRADESCO").

Os valores do ALIV são estimativa (o holerite do contador é a fonte); diferença
de centavos/reais fica no aviso para o Emerson conferir com o holerite.

Uso: folha_clt.py [--ate AAAA-MM-DD] [--confirmar] [--whatsapp]
Sem --confirmar só mostra. Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import uuid
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, TZ, Aliv, AlivError, brl  # noqa: E402

FORMA = "PAGAMENTO DE FOLHA - BRADESCO"
BANCO = "BRADESCO"
ADIC_GERENCIA = 0.40   # adicional de 40% de cargo de gerência (Josué e Thiago)
LOJAS = [("Pizzaria", "ALIV_USER", "ALIV_PASS"), ("Sushi", "ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")]


def linhas_clt(api: Aliv) -> list[dict]:
    return [r for r in api.get("/admin/api/finance/payroll/list").get("rows", [])
            if r.get("is_registered") and r.get("role") not in ("driver", "owner") and r.get("clt")]


def proxima_etapa(r: dict) -> dict | None:
    """(etapa, competência, vencimento, valor) que a tela de Folha ofereceria agora."""
    c = r["clt"]
    e = None
    if c.get("stage") == "pagamento" and (c.get("adiantamento_pago") or 0) <= 0.01 and (c.get("adiantamento") or 0) > 0.01:
        e = {"stage": "adiantamento", "competence": c["competence"],
             "due": f"{c['competence']}-{int(c.get('advance_day') or 20):02d}", "valor": float(c["adiantamento"])}
    elif c.get("stage") in ("pagamento", "adiantamento") and (c.get("a_pagar") or 0) > 0.01:
        e = {"stage": c["stage"], "competence": c["competence"], "due": str(c["due"])[:10],
             "valor": float(c["a_pagar"])}
    if e and e["stage"] == "adiantamento" and r.get("role") == "manager" and r.get("salary_base"):
        # Emerson (15/11/2026): gerente tem salário = base + 40% de gerência; o vale (40%) é só
        # sobre a base, e o adicional de gerência vem no saldo do dia 5.
        e["valor"] = round(float(r["salary_base"]) / (1 + ADIC_GERENCIA) * 0.40, 2)
    if e and e["stage"] == "adiantamento" and r.get("hired_at") and (c.get("next") or {}).get("due"):
        # Emerson (16/11/2026): quem tem menos de 15 dias de casa no dia do vale não recebe
        # adiantamento; recebe tudo no dia 5 (o vale passa para a data do saldo).
        dias = (date.fromisoformat(e["due"]) - date.fromisoformat(str(r["hired_at"])[:10])).days + 1
        if dias < 15:
            e["due"] = str(c["next"]["due"])[:10]
    return e


def pagar(api: Aliv, r: dict, e: dict, banco_id: int) -> tuple[bool, str]:
    v = round(e["valor"], 2)
    campos = {"employee_id": r["id"], "amount_to_pay": f"{v:.2f}", "payment_date": e["due"],
              "faltas_valor_total": "0", "bonus_valor": "0",
              "notes": f"Folha CLT {e['competence']} · {e['stage']} (Rotina Tili, pago pelo Bradesco)",
              "clt_stage": e["stage"], "clt_competence": e["competence"],
              "payment_method": FORMA, "origin": "banco", "bank_account_id": banco_id,
              "payment_splits": json.dumps([{"method": FORMA, "amount": v, "origin": "banco",
                                             "bank_account_id": banco_id}])}
    k = uuid.uuid4().hex
    body = "".join(f'--{k}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{x}\r\n'
                   for n, x in campos.items()) + f"--{k}--\r\n"
    st, d = api._send(urllib.request.Request(BASE_URL + "/admin/finance/payroll/pay", data=body.encode(),
                                             method="POST", headers={"Content-Type": f"multipart/form-data; boundary={k}",
                                                                     "Accept": "application/json"}))
    ok = st == 200 and isinstance(d, dict) and d.get("success") is not False
    return ok, str((d.get("message") if isinstance(d, dict) else d) or f"HTTP {st}")[:150]


def main() -> int:
    ap = argparse.ArgumentParser(description="Lança a folha CLT na Folha do ALIV (Bradesco)")
    ap.add_argument("--ate", help="lança as etapas vencidas até esta data (padrão: hoje)")
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--whatsapp", action="store_true")
    ap.add_argument("--so", type=int, action="append", default=[], help="só estes funcionários (id)")
    a = ap.parse_args()
    ate = date.fromisoformat(a.ate) if a.ate else datetime.now(TZ).date()
    feitos, avisos, total = [], [], 0.0
    api = None
    for loja, u, pw in LOJAS:
        if not os.environ.get(u):
            continue
        api = Aliv(os.environ[u], os.environ[pw])
        try:
            api.login()
            bl = api.get("/admin/api/finance/banking/accounts/list")
            bl = bl if isinstance(bl, list) else bl.get("accounts", [])
            banco_id = next(x["id"] for x in bl if BANCO in str(x.get("name", "")).upper())
            for r in linhas_clt(api):
                if a.so and r["id"] not in a.so:
                    continue
                for _ in range(4):                      # várias etapas atrasadas, uma de cada vez
                    e = proxima_etapa(r)
                    if not e or date.fromisoformat(e["due"]) > ate:
                        break
                    txt = (f"{loja} · {r['name'][:30]} · {'vale' if e['stage'] == 'adiantamento' else 'saldo'} "
                           f"{e['competence'][5:]}/{e['competence'][:4]} · {brl(e['valor'])} em {e['due'][8:]}/{e['due'][5:7]}")
                    if not a.confirmar:
                        feitos.append("(teste) " + txt)
                        total += e["valor"]
                        break
                    ok, msg = pagar(api, r, e, banco_id)
                    if not ok:
                        avisos.append(f"{txt}: ALIV recusou — {msg}")
                        break
                    feitos.append("✓ " + txt)
                    total += e["valor"]
                    r = next((x for x in linhas_clt(api) if x["id"] == r["id"]), None)
                    if not r:
                        break
        except (AlivError, OSError, StopIteration) as e:
            print(f"Tili — Folha CLT — ERRO no ALIV ({loja})\n\n{e}")
            return 1
    if not feitos and not avisos:
        print(f"Tili — Folha CLT: nada vencido até {ate:%d/%m}.")
        return 0
    texto = (f"*Tili — Folha CLT* lançada no ALIV (Bradesco): {len(feitos)} pagamento(s), {brl(total)}"
             + ("" if a.confirmar else " — TESTE, nada lançado")
             + "\n" + "\n".join(feitos)
             + ("\n\n*Conferir:*\n" + "\n".join("• " + x for x in avisos) if avisos else "")
             + "\nValores calculados pelo ALIV — confira com o holerite do contador.")
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
