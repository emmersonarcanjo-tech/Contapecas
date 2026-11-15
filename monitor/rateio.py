#!/usr/bin/env python3
"""Rateio mensal dos custos compartilhados Pizzaria × Sushi (Tili).

Regra do Emerson (15/11/2026): cada despesa fica na loja que usa. O que as duas lojas usam
e está pago/lançado na Pizzaria é dividido assim:
  - motoboys (diaristas e prestadores): pelo nº de entregas de cada loja no mês, sem contar
    as entregas lançadas no login do Josué ou do Thiago Camilo (só registram terceirizados);
    custo = entregas + diárias que o ALIV creditou aos motoboys no mês;
  - gerentes (Josué = gerente geral, Thiago Camilo = logística): salário da Folha do ALIV
    + FGTS 8% + vale alimentação/refeição R$ 600 cada + "Despesa extra gerencial" do mês;
  - administrativo: Contador, Advogada, Assistente administrativo, Marketing e Sistema ALIV
    (contas da Pizzaria com vencimento no mês) — pelo % do faturamento de cada loja.
Faturamento e entregas vêm do mesmo levantamento do fechamento semanal (dia 16:00–04:00).

Uso: rateio.py [--mes AAAA-MM] [--whatsapp]     (padrão: mês passado; só calcula e mostra)
Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import calendar
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fechamento_semanal import AlivSemanal, agregar, coletar_dias  # noqa: E402
from monitor import TZ, AlivError, brl  # noqa: E402

GERENTE_LOGIN = re.compile(r"thiago|camilo|josu[eé]|ruas", re.I)
FGTS = 0.08
VA_VR = 600.0
ADMIN = ("contador", "advogada", "assistente administrativo", "marketing", "sistema aliv", "aliv")
COMPLEMENTO = "despesa extra gerencial"


def contas_do_mes(api, ini: date, fim: date) -> list[dict]:
    b = api.get("/admin/finance/bills", {"bill_type": "payable", "status": "all"})
    b = b if isinstance(b, list) else b.get("bills", [])
    return [x for x in b if ini.isoformat() <= str(x.get("due_date", ""))[:10] <= fim.isoformat()]


def custo_motoboys(api, ini: date, fim: date) -> float:
    tot = 0.0
    for r in api.get("/admin/api/finance/payroll/list").get("rows", []):
        if r.get("role") != "driver" or GERENTE_LOGIN.search(r.get("name", "")):
            continue
        h = api.get(f"/admin/api/finance/driver/{r['id']}/history-audit",
                    {"start": ini.isoformat(), "end": (fim + timedelta(days=1)).isoformat()}).get("history") or []
        tot += sum(float(x.get("value") or 0) for x in h if x.get("type") in ("ENTREGA", "DIÁRIA/VALE"))
    return round(tot, 2)


def calcular(apis: dict, mes: date, agora: datetime) -> dict:
    ini = mes.replace(day=1)
    fim = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
    dias = [ini + timedelta(days=i) for i in range((fim - ini).days + 1)]
    A = agregar(coletar_dias(apis, dias, agora, True))
    if not A.get("sushi"):
        raise AlivError("sem dados do Sushi no mês — não dá para dividir")
    vp, vs = A["piz"]["vendas"], A["sushi"]["vendas"]
    ep, es = A["piz"]["entregas"], A["sushi"]["entregas"]
    pct_fat = vs / (vp + vs) if vp + vs else 0.0
    pct_ent = es / (ep + es) if ep + es else 0.0
    api = apis["piz"]
    itens = []                                   # (grupo, descrição, custo total, % Sushi)
    itens.append(("Motoboys", "Entregas + diárias dos motoboys", custo_motoboys(api, ini, fim), pct_ent))
    for r in api.get("/admin/api/finance/payroll/list").get("rows", []):
        if r.get("role") == "manager" and r.get("is_registered"):
            sal = float(r.get("salary_base") or 0)
            itens.append(("Gerentes", f"{r['name'].split()[0]} — salário + FGTS + VA/VR",
                          round(sal * (1 + FGTS) + VA_VR, 2), pct_fat))
    for x in contas_do_mes(api, ini, fim):
        d = str(x.get("description") or "")
        dl = d.lower()
        if dl.startswith(COMPLEMENTO):
            itens.append(("Gerentes", d[:60], float(x["amount"]), pct_fat))
        elif any(dl.startswith(k) for k in ADMIN):
            itens.append(("Administrativo", d[:60], float(x["amount"]), pct_fat))
    total_sushi = round(sum(v * p for _, _, v, p in itens), 2)
    return {"mes": ini, "vendas": (vp, vs), "entregas": (ep, es), "pct_fat": pct_fat, "pct_ent": pct_ent,
            "itens": itens, "sushi": total_sushi, "lucro_piz": A["piz"]["l"]["lucro"],
            "lucro_sushi": A["sushi"]["l"]["lucro"]}


def texto(R: dict) -> str:
    vp, vs = R["vendas"]
    ep, es = R["entregas"]
    L = [f"*Tili — Rateio Pizzaria × Sushi* {R['mes']:%m/%Y}",
         f"Faturamento: Pizzaria {brl(vp)} · Sushi {brl(vs)} → Sushi {R['pct_fat']:.1%}",
         f"Entregas (sem gerentes): Pizzaria {ep} · Sushi {es} → Sushi {R['pct_ent']:.1%}", ""]
    grupos: dict[str, list] = {}
    for g, d, v, p in R["itens"]:
        grupos.setdefault(g, []).append((d, v, p))
    for g, xs in grupos.items():
        L.append(f"*{g}*: total {brl(sum(v for _, v, _ in xs))} → Sushi {brl(sum(v * p for _, v, p in xs))}")
        L += [f"  • {d}: {brl(v)} × {p:.1%} = {brl(v * p)}" for d, v, p in xs]
    L += ["", f"*Parte do Sushi: {brl(R['sushi'])}* (sai da Pizzaria e entra no Sushi)"]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Rateio mensal Pizzaria × Sushi (só calcula)")
    ap.add_argument("--mes", help="AAAA-MM (padrão: mês passado)")
    ap.add_argument("--whatsapp", action="store_true")
    a = ap.parse_args()
    agora = datetime.now(TZ).replace(second=0, microsecond=0)
    mes = (date.fromisoformat(a.mes + "-01") if a.mes else (agora.date().replace(day=1) - timedelta(days=1)))
    apis = {"piz": AlivSemanal(os.environ["ALIV_USER"], os.environ["ALIV_PASS"]),
            "sushi": AlivSemanal(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"])}
    try:
        for x in apis.values():
            x.login()
        R = calcular(apis, mes, agora)
    except (AlivError, OSError) as e:
        print(f"Tili — Rateio — ERRO no ALIV\n\n{e}")
        return 1
    t = texto(R)
    print(t)
    if a.whatsapp:
        try:
            apis["piz"].enviar_whatsapp(re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", "")), t[:3800])
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
