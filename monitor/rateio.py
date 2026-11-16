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

  - plano odontológico: R$ 21,90 por CLT do Sushi com mais de 3 meses de casa (direito após a
    experiência; a empresa paga só o titular, dependentes são do funcionário).
Lançamento (--confirmar), sem mexer em banco/caixa:
  - Sushi: despesa "Rateio de custos da Pizzaria MM/AAAA" (paga, origem nenhuma);
  - Pizzaria: entrada "Reembolso do rateio — Sushi MM/AAAA" (recebida, origem nenhuma).
Não lança de novo se já existir a conta com a mesma descrição.

Uso: rateio.py [--mes AAAA-MM] [--confirmar] [--whatsapp]     (padrão: mês passado)
Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import urllib.request
import uuid
import calendar
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fechamento_semanal import AlivSemanal, agregar, coletar_dias  # noqa: E402
from monitor import BASE_URL, TZ, AlivError, brl  # noqa: E402

GERENTE_LOGIN = re.compile(r"thiago|camilo|josu[eé]|ruas", re.I)
FGTS = 0.08
VA_VR = 600.0
ADMIN = ("contador", "advogada", "assistente administrativo", "marketing", "sistema aliv", "aliv")
COMPLEMENTO = "despesa extra gerencial"
ODONTO = "plano odontol"
ODONTO_TITULAR = 21.90      # por funcionário CLT com +3 meses; a empresa paga só o titular
# admissão real (carteira) quando o cadastro do ALIV usa outra data (Tamile: Sushi desde 01/11 no ALIV)
ADMISSAO_REAL = {"tamile de jesus santos": "2026-08-11"}
CAT_SUSHI = "Rateio de custos da Pizzaria"
CAT_PIZ = "Reembolso de rateio (Sushi)"


def clt_odonto(api, fim: date) -> int:
    """CLT ativos com mais de 3 meses de casa no fim do mês."""
    n = 0
    for u in api.get("/admin/api/users/data")["users"]:
        if not (u.get("is_registered") and u.get("is_active")) or u.get("role") in ("driver", "owner"):
            continue
        adm = ADMISSAO_REAL.get(str(u.get("full_name", "")).lower()) or u.get("hired_at")
        if adm and date.fromisoformat(str(adm)[:10]) + timedelta(days=90) <= fim:
            n += 1
    return n


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
        elif dl.startswith(ODONTO):
            # Emerson (16/11/2026): a empresa paga R$ 21,90 só do titular (dependentes: o funcionário)
            os_ = clt_odonto(apis["sushi"], fim)
            itens.append(("Benefícios", f"Plano odontológico — {os_} CLT do Sushi com +3 meses × R$ 21,90",
                          round(ODONTO_TITULAR * os_, 2), 1.0))
        elif any(dl.startswith(k) for k in ADMIN):
            itens.append(("Administrativo", d[:60], float(x["amount"]), pct_fat))
    total_sushi = round(sum(v * p for _, _, v, p in itens), 2)
    return {"mes": ini, "vendas": (vp, vs), "entregas": (ep, es), "pct_fat": pct_fat, "pct_ent": pct_ent,
            "itens": itens, "sushi": total_sushi, "lucro_piz": A["piz"]["l"]["lucro"],
            "lucro_sushi": A["sushi"]["l"]["lucro"]}


def _form(api, path: str, c: dict):
    k = uuid.uuid4().hex
    body = "".join(f'--{k}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'
                   for n, v in c.items()) + f"--{k}--\r\n"
    return api._send(urllib.request.Request(BASE_URL + path, data=body.encode(), method="POST",
                                            headers={"Content-Type": f"multipart/form-data; boundary={k}",
                                                     "Accept": "application/json"}))


def _categoria(api, nome: str) -> int:
    cats = {c["name"]: c["id"] for c in api.get("/admin/finance/categories")}
    if nome not in cats:
        _form(api, "/admin/finance/categories", {"name": nome})
        cats = {c["name"]: c["id"] for c in api.get("/admin/finance/categories")}
    return cats[nome]


def lancar(api, tipo: str, desc: str, valor: float, dia: date, cat: str) -> str:
    b = api.get("/admin/finance/bills", {"bill_type": tipo, "status": "all"})
    b = b if isinstance(b, list) else b.get("bills", [])
    if any(str(x.get("description")) == desc for x in b):
        return "já lançado"
    st, d = _form(api, "/admin/finance/bills/save", {
        "bill_type": tipo, "description": desc, "amount": f"{valor:.2f}", "due_date": dia.isoformat(),
        "payment_method": "Transferência interna", "category_id": _categoria(api, cat), "is_recurring": "false",
        "installments": "1", "pay_on_create": "true", "payment_origin": "none", "payment_date": dia.isoformat()})
    return "✓" if st == 200 and isinstance(d, dict) and d.get("success") else f"ERRO {str(d)[:120]}"


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
    ap.add_argument("--confirmar", action="store_true", help="lança no ALIV (Sushi e Pizzaria)")
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
    if a.confirmar and R["sushi"] > 0.009:
        fim = R["mes"].replace(day=calendar.monthrange(R["mes"].year, R["mes"].month)[1])
        try:
            r1 = lancar(apis["sushi"], "payable", f"Rateio de custos da Pizzaria {R['mes']:%m/%Y}", R["sushi"], fim, CAT_SUSHI)
            r2 = lancar(apis["piz"], "receivable", f"Reembolso do rateio — Sushi {R['mes']:%m/%Y}", R["sushi"], fim, CAT_PIZ)
        except (AlivError, OSError) as e:
            print(f"Tili — Rateio — ERRO ao lançar no ALIV\n\n{e}")
            return 1
        t += f"\nALIV: Sushi (despesa) {r1} · Pizzaria (reembolso) {r2} — sem mexer em banco"
    elif not a.confirmar:
        t += "\n(teste — nada lançado)"
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
