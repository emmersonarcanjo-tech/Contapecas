#!/usr/bin/env python3
"""Baixa semanal dos motoboys (diaristas e prestadores) na folha do ALIV.

Regra do Emerson (15/11/2026): toda segunda às 17:00 dá baixa no saldo de cada
motoboy referente aos turnos ATÉ o domingo anterior (dia operacional = horário − 6 h,
o mesmo corte dos relatórios). O que foi ganho depois do domingo fica adiado para a
próxima baixa (campo "defer_amount", igual ao botão Adiar da tela de Folha).

- valor = saldo do ALIV (os fechamentos de turno), sem as correções do relatório
  de prestadores;
- registra como Pix, origem "none": não tira de caixa nem de banco (o Emerson paga
  pelo banco dele);
- motoboy com saldo do período ≤ 0 (já pago) fica de fora.

Uso: baixa_motoboys.py [--ate AAAA-MM-DD] [--confirmar] [--whatsapp]
Sem --ate: domingo passado. Sem --confirmar só mostra (nada é lançado).
Saída: 0 ok, 1 erro no ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, TZ, Aliv, AlivError, brl  # noqa: E402

PRESTADOR = re.compile(r"CNPJ|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\sC$")


def data_hist(txt: str, hoje: date) -> datetime:
    """'08/11 23:59' (sem ano) → datetime, no ano que deixa a data até hoje."""
    dt = datetime.strptime(f"{txt}/{hoje.year}", "%d/%m %H:%M/%Y")
    return dt.replace(year=hoje.year - 1) if dt.date() > hoje + timedelta(days=1) else dt


def pagar(api: Aliv, emp_id: int, valor: float, adiar: float, dia: date, nota: str) -> tuple[bool, str]:
    campos = {"employee_id": emp_id, "amount_to_pay": f"{valor:.2f}", "payment_date": dia.isoformat(),
              "faltas_valor_total": "0", "bonus_valor": "0", "notes": nota, "payment_method": "Pix",
              "origin": "none",
              "payment_splits": json.dumps([{"method": "Pix", "amount": valor, "origin": "none",
                                             "bank_account_id": None}])}
    if adiar > 0.01:
        campos["defer_amount"] = f"{adiar:.2f}"
    b = uuid.uuid4().hex
    body = "".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                   for k, v in campos.items()) + f"--{b}--\r\n"
    req = urllib.request.Request(BASE_URL + "/admin/finance/payroll/pay", data=body.encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}",
                                          "Accept": "application/json"})
    st, d = api._send(req)
    ok = st == 200 and isinstance(d, dict) and d.get("success") is not False
    return ok, (d.get("message") if isinstance(d, dict) else str(d))[:160] if d else f"HTTP {st}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Baixa semanal dos motoboys na folha do ALIV")
    ap.add_argument("--ate", help="último dia operacional a pagar (padrão: domingo passado)")
    ap.add_argument("--confirmar", action="store_true", help="dá a baixa de verdade (sem isso, só mostra)")
    ap.add_argument("--whatsapp", action="store_true", help="manda o resumo para WHATSAPP_EMERSON")
    a = ap.parse_args()

    hoje = datetime.now(TZ).date()
    ate = date.fromisoformat(a.ate) if a.ate else hoje - timedelta(days=hoje.weekday() + 1)
    u, p = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not u or not p:
        print("ERRO: defina ALIV_USER e ALIV_PASS", file=sys.stderr)
        return 2
    api = Aliv(u, p)
    linhas, total, erros, n = [], 0.0, 0, 0
    try:
        api.login()
        rows = [r for r in api.get("/admin/api/finance/payroll/list").get("rows", [])
                if r.get("role") == "driver" and float(r.get("saldo") or 0) > 0.009]
        for r in sorted(rows, key=lambda x: x["name"].lower()):
            # "liquido" é o que a tela de Folha deixa pagar (saldo − vales); é a base da baixa
            saldo = round(float(r.get("liquido") or 0), 2)
            if saldo <= 0.009:
                linhas.append(f"⚠️ {r['name'][:40]}: saldo {brl(float(r['saldo']))} mas líquido zerado "
                              f"no ALIV (vales/cadastro) — não dei baixa, conferir na Folha")
                continue
            hist = api.get(f"/admin/api/finance/driver/{r['id']}/history-audit",
                           {"start": (ate - timedelta(days=45)).isoformat(),
                            "end": (hoje + timedelta(days=1)).isoformat()}).get("history") or []
            depois = round(sum(float(x.get("value") or 0) for x in hist if x.get("type") == "BONUS"
                               and (data_hist(x["date"], hoje) - timedelta(hours=6)).date() > ate), 2)
            valor = round(saldo - depois, 2)
            if valor <= 0.009:
                continue
            tipo = "prestador" if PRESTADOR.search(r["name"]) else "diarista"
            nome = re.sub(r"\s*CNPJ.*$|\s+[DC]$", "", r["name"]).strip()
            txt = f"{nome} ({tipo}) — {brl(valor)}" + (f" · fica {brl(depois)} p/ próxima" if depois > 0.009 else "")
            if not a.confirmar:
                linhas.append("(teste) " + txt)
                total += valor
                n += 1
                continue
            ok, msg = pagar(api, r["id"], valor, max(0.0, round(saldo - valor, 2)), hoje,
                            f"Baixa motoboys até {ate:%d/%m} (Rotina Tili)")
            if ok:
                linhas.append("✓ " + txt)
                total += valor
                n += 1
            else:
                linhas.append(f"✗ {txt}: {msg}")
                erros += 1
    except (AlivError, OSError) as e:
        print(f"Tili — Baixa motoboys — ERRO no ALIV\n\n{e}")
        return 1

    cab = (f"*Tili — Baixa motoboys* até {ate:%d/%m}: {n} motoboy(s), {brl(total)} (Pix)"
           + ("" if a.confirmar else " — TESTE, nada lançado") + (f" · {erros} erro(s)" if erros else ""))
    texto = cab + ("\n" + "\n".join(linhas) if linhas else "\nNinguém com saldo em aberto nesse período.")
    print(texto)
    if a.whatsapp:
        fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
        try:
            api.enviar_whatsapp(fone, texto[:3800])
            print("WHATSAPP: enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
