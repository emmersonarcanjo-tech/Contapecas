#!/usr/bin/env python3
"""Fechamento de ponto mensal da Tili na nuvem (Flit Gestor → planilha + faltas para o vale).

Regra do Emerson (16/11/2026): o ponto fecha junto com a folha, com data fixa:
  período do dia 26 do mês anterior ao dia 25 do mês; Rotina todo dia 26 às 08:00
  (o turno do dia 25 termina depois da meia-noite), mesmo em sábado/domingo/feriado.
Passos (só leitura no Flit):
  1. exporta a "Apuração de jornadas" do período (flit_apuracao.js, login FLIT_USER/FLIT_PASS);
  2. roda o motor auditoria_ponto.py (modo mensal) → planilha de fechamento;
  3. calcula as faltas injustificadas: dias com horário previsto e sem marcação, menos 1 folga
     por semana (as folgas não estão lançadas no Flit); Folga/Férias/Feriado/Atestado lançados
     no Flit não contam;
  4. grava monitor/vale/faltas/AAAA-MM.json (o vale alimentação do dia 30 desconta R$ 20/falta);
  5. manda resumo + planilha para o Emerson pelo WhatsApp.

Uso: fechamento_ponto.py [--fim AAAA-MM-DD] [--whatsapp] [--sem-faltas]
     (padrão: fim = dia 25 do mês atual; início = dia 26 do mês anterior)
Saída: 0 ok, 1 erro no Flit/ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent))
import auditoria_ponto as motor  # noqa: E402
from monitor import TZ, Aliv, AlivError  # noqa: E402

ADMISSAO_REAL = {"tamile santos": "2026-08-11"}   # no ALIV do Sushi a data é 01/11 (gerencial)
FALTAS_DIR = AQUI.parent / "vale" / "faltas"
SAIDA_DIR = AQUI / "mensal"


def periodo(fim: date) -> tuple[date, date]:
    ini = (fim.replace(day=1) - timedelta(days=1)).replace(day=26)
    return ini, fim


def admitidos_no_periodo(ini: date) -> set[str]:
    """Primeiro+último nome de quem entrou no período (cadastro do ALIV das duas lojas)."""
    out = set()
    for u, p in (("ALIV_USER", "ALIV_PASS"), ("ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")):
        try:
            api = Aliv(os.environ[u], os.environ[p])
            api.login()
            for x in api.get("/admin/api/users/data")["users"]:
                h = str(x.get("hired_at") or "")[:10]
                h = ADMISSAO_REAL.get(_n(x["full_name"]), h)
                if x.get("is_registered") and h and date.fromisoformat(h) >= ini:
                    out.add(_n(x["full_name"]))
        except (AlivError, OSError, KeyError, ValueError):
            pass
    return out


def _n(s: str) -> str:
    import unicodedata
    p = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower().split()
    return f"{p[0]} {p[-1]}" if p else ""


def faltas_injustificadas(dados: list[dict], ini: date, fim: date, novos: set[str] | None = None) -> dict[str, dict]:
    """{nome: {"faltas": n, "sem_marcacao": [datas], "folgas_descontadas": k}}
    Quem entrou no período (novos): os dias antes da 1ª batida no Flit não contam."""
    por = defaultdict(list)
    for d in dados:
        if ini <= d["data"] <= fim:
            por[d["nome"]].append(d)
    out = {}
    for nome, dias in por.items():
        if not any(d["marcacoes"] for d in dias):
            # nenhuma batida no período inteiro: ainda não usa o Flit (recém-admitido) ou já saiu
            out[nome] = {"faltas": 0, "sem_marcacao": [], "folgas_descontadas": 0, "sem_batida": True}
            continue
        if _n(nome) in (novos or set()):
            primeira = min(d["data"] for d in dias if d["marcacoes"])
            dias = [d for d in dias if d["data"] >= primeira]
        semanas = defaultdict(lambda: {"dias": 0, "falta": []})
        for d in dias:
            cls, _ = motor.analisar_dia(d)
            k = d["data"].isocalendar()[:2]
            semanas[k]["dias"] += 1
            if cls == "FALTA":
                semanas[k]["falta"].append(d["data"])
        total, folgas, datas = 0, 0, []
        for s in semanas.values():
            livre = 1 if s["dias"] >= 4 else 0         # 1 folga por semana (semana cheia no período)
            total += max(0, len(s["falta"]) - livre)
            folgas += min(livre, len(s["falta"]))
            datas += s["falta"]
        out[nome] = {"faltas": total, "sem_marcacao": sorted(datas), "folgas_descontadas": folgas}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fechamento de ponto mensal (Flit) na nuvem")
    ap.add_argument("--fim", help="último dia do período (padrão: dia 25 deste mês)")
    ap.add_argument("--whatsapp", action="store_true")
    ap.add_argument("--sem-faltas", action="store_true", help="não grava o arquivo de faltas (teste)")
    a = ap.parse_args()
    hoje = datetime.now(TZ).date()
    fim = date.fromisoformat(a.fim) if a.fim else hoje.replace(day=25)
    ini, fim = periodo(fim)
    br = lambda d: d.strftime("%d/%m/%Y")  # noqa: E731
    tmp = Path(tempfile.mkdtemp())
    js = tmp / "apuracao.json"
    r = subprocess.run(["node", str(AQUI / "flit_apuracao.js"), br(ini), br(fim), str(js)],
                       capture_output=True, text=True, timeout=600, cwd=str(AQUI))
    if r.returncode or not js.exists():
        print(f"Tili — Fechamento de ponto — ERRO no Flit\n\n{(r.stderr or r.stdout)[-600:]}")
        return 1
    dados = motor.ler_apuracao(str(js))
    SAIDA_DIR.mkdir(parents=True, exist_ok=True)
    xlsx = tmp / f"Fechamento_Ponto_{fim:%Y-%m}.xlsx"
    resumo, alertas, detalhe = motor.consolidar(dados, ini, fim, "mensal")
    motor.gerar_excel(str(xlsx), "mensal", ini, fim, resumo, alertas, detalhe, "Flit (nuvem)")
    txt_motor = motor.resumo_texto("mensal", ini, fim, resumo, alertas)

    F = faltas_injustificadas(dados, ini, fim, admitidos_no_periodo(ini))
    com_falta = {n: v for n, v in F.items() if v["faltas"] > 0}
    sem_batida = sorted(n for n, v in F.items() if v.get("sem_batida"))
    if not a.sem_faltas:
        FALTAS_DIR.mkdir(parents=True, exist_ok=True)
        (FALTAS_DIR / f"{fim:%Y-%m}.json").write_text(
            json.dumps({n: v["faltas"] for n, v in sorted(com_falta.items())}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    linhas = [f"*Tili — Fechamento de ponto* {ini:%d/%m} a {fim:%d/%m}", txt_motor.strip(), "",
              f"*Faltas injustificadas* (desconto de R$ 20 cada no vale alimentação do dia 30): "
              + (str(sum(v['faltas'] for v in com_falta.values())) if com_falta else "nenhuma")]
    for n, v in sorted(com_falta.items()):
        linhas.append(f"• {n.title()}: {v['faltas']} (dias sem marcação: "
                      + ", ".join(d.strftime("%d/%m") for d in v["sem_marcacao"])
                      + f"; {v['folgas_descontadas']} contado(s) como folga)")
    if sem_batida:
        linhas.append("Sem nenhuma batida no período (não contei falta — conferir se usa o Flit ou se saiu): "
                      + ", ".join(n.title() for n in sem_batida))
    linhas.append("Quem saiu da empresa não tem desconto (o vale só considera quem está ativo no ALIV).")
    linhas.append("Regra: 1 dia sem marcação por semana = folga. Se alguma falta foi justificada (atestado, folga extra), "
                  "lance no Flit ou me avise antes do dia 30.")
    texto = "\n".join(linhas)
    print(texto)
    print(f"\nPlanilha: {xlsx}")
    if a.whatsapp:
        try:
            api = Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"])
            api.login()
            fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
            api.enviar_whatsapp(fone, texto[:3800])
            api.enviar_whatsapp(fone, f"Planilha do fechamento de ponto {ini:%d/%m} a {fim:%d/%m}", arquivo=xlsx)
        except (AlivError, OSError, KeyError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
