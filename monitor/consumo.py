#!/usr/bin/env python3
"""Alerta de limite de consumo dos funcionários — Tili Pizzaria (ALIV loja 150).

Regra do Emerson (26/10/2026): R$ 200,00 por funcionário por CICLO.
Ciclo = dia 26 de um mês até dia 25 do mês seguinte (zera no dia 26).
  - "perto"    = consumo do ciclo >= R$ 160,00
  - "estourou" = consumo do ciclo >= R$ 200,00
Consumo = lançamentos CONSUMO na carteira do funcionário
        + pedidos pagos como "Fiado / Carteira" no nome do funcionário
          (sem contar de novo o pedido que já virou CONSUMO na carteira).
Fora da conta: motoboys (driver) e donos (owner).

Só leitura no ALIV. Com --whatsapp manda UMA mensagem para WHATSAPP_EMERSON e
WHATSAPP_ADMIN pelo WhatsApp da loja, e só se alguém estiver perto ou estourado.
Sem --whatsapp só imprime (dry-run).

Códigos de saída: 0 ok · 1 erro no ALIV · 2 faltam ALIV_USER/ALIV_PASS · 3 WhatsApp falhou.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import date, datetime

from monitor import TZ, Aliv, AlivError, brl

LIMITE = 200.0
AVISO = 160.0
FONES = ("WHATSAPP_EMERSON", "WHATSAPP_ADMIN")
RE_FIADO = re.compile(r"Fiado[^:]*:\s*([\d.,]+)", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def valor_br(s: str) -> float:
    s = s.strip(".,")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def ciclo(hoje: date) -> tuple[date, date]:
    if hoje.day >= 26:
        ini = date(hoje.year, hoje.month, 26)
    else:
        a, m = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
        ini = date(a, m, 26)
    a, m = (ini.year, ini.month + 1) if ini.month < 12 else (ini.year + 1, 1)
    return ini, date(a, m, 25)


def calcular(api: Aliv, hoje: date) -> dict:
    ini, fim = ciclo(hoje)
    INI, HOJE = ini.isoformat(), hoje.isoformat()

    folha = api.get("/admin/api/finance/payroll/list", {"competence": hoje.strftime("%Y-%m")})
    func = [r for r in folha.get("rows", []) if r.get("role") not in ("driver", "owner")]

    total, ja_na_carteira = {}, set()
    for f in func:
        a = api.get(f"/admin/api/finance/driver/{f['id']}/history-audit", {"start": INI, "end": HOJE})
        c = 0.0
        for x in a.get("history", []):
            if x.get("type") != "CONSUMO":
                continue
            c += abs(float(x.get("value") or 0))
            if x.get("related_order_id"):
                ja_na_carteira.add(str(x["related_order_id"]))
        total[f["id"]] = {"nome": f.get("name", "?"), "carteira": c, "fiado": 0.0}

    pedidos, page, more = [], 1, True
    while more and page < 60:
        r = api.get("/admin/api/orders/audit", {"start_date": INI, "end_date": HOJE,
                                                "platform": "all", "page": page})
        pedidos += r.get("orders", [])
        more, page = bool(r.get("has_more")), page + 1

    nomes = [(f["id"], norm(f.get("name"))) for f in func]
    for o in pedidos:
        if re.search(r"CANCEL", str(o.get("status") or ""), re.I):
            continue
        if str(o.get("id")) in ja_na_carteira:
            continue
        m = RE_FIADO.search(str(o.get("payment") or ""))
        if not m:
            continue
        cli = norm(o.get("customer"))
        for fid, nf in nomes:
            if cli == nf or (" " not in cli and cli == nf.split(" ")[0]):
                total[fid]["fiado"] += valor_br(m.group(1))
                break

    lista = sorted(({**t, "soma": round(t["carteira"] + t["fiado"], 2)} for t in total.values()),
                   key=lambda t: -t["soma"])
    return {"ini": ini, "fim": fim, "todos": lista,
            "estourou": [t for t in lista if t["soma"] >= LIMITE],
            "perto": [t for t in lista if AVISO <= t["soma"] < LIMITE]}


def mensagem(r: dict, hoje: date) -> str | None:
    if not (r["estourou"] or r["perto"]):
        return None
    d = lambda x: x.strftime("%d/%m")
    linhas = [f"⚠️ Limite de consumo (R$ {LIMITE:.0f} de {d(r['ini'])} a {d(r['fim'])}) — {d(hoje)}"]
    linhas += [f"• {t['nome']} — {brl(t['soma'])} (estourou)" for t in r["estourou"]]
    linhas += [f"• {t['nome']} — {brl(t['soma'])} (perto)" for t in r["perto"]]
    linhas.append("Caixa: não lançar mais consumo para quem estourou neste ciclo.")
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Alerta de limite de consumo dos funcionários (ALIV, só leitura)")
    ap.add_argument("--hoje", help="simula a data (AAAA-MM-DD)")
    ap.add_argument("--whatsapp", action="store_true", help="envia o alerta (sem isso, só mostra)")
    a = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: faltam ALIV_USER/ALIV_PASS.", file=sys.stderr)
        return 2
    hoje = date.fromisoformat(a.hoje) if a.hoje else datetime.now(TZ).date()
    api = Aliv(user, pwd)
    try:
        r = calcular(api, hoje)
    except (AlivError, OSError) as e:
        print(f"ERRO ALIV: {e}", file=sys.stderr)
        return 1

    print(f"Ciclo {r['ini']:%d/%m} a {r['fim']:%d/%m} — {len(r['todos'])} funcionários")
    for t in r["todos"]:
        if t["soma"] > 0:
            print(f"  {t['nome']}: {brl(t['soma'])} (carteira {brl(t['carteira'])} + fiado {brl(t['fiado'])})")
    msg = mensagem(r, hoje)
    if not msg:
        print("Ninguém perto do limite — nada enviado.")
        return 0
    print("\n" + msg)
    if not a.whatsapp:
        print("\n(dry-run: WhatsApp não enviado)")
        return 0

    falhas = 0
    for var in FONES:
        fone = re.sub(r"\D", "", os.environ.get(var, ""))
        if not fone:
            print(f"WHATSAPP {var}: variável não definida", file=sys.stderr)
            falhas += 1
            continue
        try:
            api.enviar_whatsapp(fone, msg)
            print(f"WHATSAPP {var}: enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP {var}: falhou — {e}", file=sys.stderr)
            falhas += 1
    return 3 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
