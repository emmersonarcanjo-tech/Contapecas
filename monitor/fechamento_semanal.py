#!/usr/bin/env python3
"""Fechamento semanal da Tili — Pizzaria (loja 150) + Sushi (loja 155), só leitura no ALIV.

Roda toda segunda às 09:00 (America/Bahia) e fecha a semana que terminou (segunda a
domingo). Dia operacional = 16:00 até 04:00 do dia seguinte (o mesmo turno do monitor.py).

Reaproveita do monitor.py o login das duas lojas, a coleta de pedidos (pedidos_do_turno),
os cálculos (calcular, calcular_sushi, lucro, custo de motoboy) e o envio por WhatsApp;
do previsao_motoboys.py, a contagem de entregas acima de 45 min e os feriados; do
painel.py, o estilo e o Chromium que fotografa o painel.

Conteúdo, por loja e consolidado: pedidos, vendas, ticket, cancelamentos; canais (App,
iFood por loja, PDV delivery, Salão); peças do Sushi; descontos da loja e do iFood e custo
iFood; motoboys (turnos, entregas, custo com diárias e por entrega, entregas por motoboy);
tempos médios de preparo, rua e vida e entregas acima de 45 min; lucro ESTIMADO (mesma
fórmula do monitor); melhor e pior dia. Compara com a semana anterior e com a mesma semana
do mês passado (4 semanas antes, mesmos dias da semana). Fecha o mês até o domingo, com
projeção linear. Três destaques no topo: melhorou, piorou e recomendação.

Saídas: painel PNG do iPad (2360×1640), texto resumido e o
relatório completo em monitor/semanal/AAAA-MM-DD.md (data = segunda da semana). O commit
fica a cargo da Rotina. Cache dos dias fechados em monitor/semanal/dias/ (só números e
apelido do motoboy como aparece no pedido; dígitos são removidos — nunca CPF/CNPJ).

Uso:
  python3 monitor/fechamento_semanal.py                       # semana passada, sem enviar
  python3 monitor/fechamento_semanal.py --semana 2026-10-27   # qualquer dia da semana
  python3 monitor/fechamento_semanal.py --whatsapp            # envia para WHATSAPP_EMERSON

Códigos de saída: 0 ok · 1 erro no ALIV · 2 faltam ALIV_USER/ALIV_PASS ·
3 relatório ok, mas o WhatsApp não aceitou (a Rotina manda por e-mail).
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import (CARTAO, CMV, DIARIA_FDS, DIARIA_SEMANA, IMPOSTO, META_CANCEL,  # noqa: E402
                     META_CUSTO_IFOOD, META_ENTREGA, META_PREPARO, META_TICKET, POR_ENTREGA,
                     STATUS_FINALIZADO, TZ, Aliv, AlivError, brl, calcular, calcular_sushi,
                     canal_sushi, janela_turno, lista_pedidos, lucro, monitor_tempos, num, pct, pedidos_do_turno,
                     resumo, status_de)
from previsao_motoboys import DIAS, DIAS_CURTO, LIMITE_MIN, conta_atrasos, eh_gerente, feriados  # noqa: E402

PASTA = Path(__file__).resolve().parent / "semanal"
CACHE = PASTA / "dias"
VERSAO_CACHE = 1
LOJAS = (("piz", "Pizzaria"), ("sushi", "Sushi"))
SOMAS = ("pedidos", "cancelados", "vendas", "receita", "desc_loja", "desc_plataforma", "desc_manual",
         "comissao_ifood", "desc_loja_ifood", "receita_ifood", "proprios", "entregas_delivery",
         "pecas", "temakis", "atrasos")


# -------------------------------------------------------------------- coleta
class AlivSemanal(Aliv):
    """O mesmo cliente do monitor, com a paginação do audit mais econômica: 200 pedidos por
    página e para quando a página só repete pedidos já vistos. (O ALIV não devolve página
    vazia no fim; sem isso o pedidos_do_turno do monitor vai até a página 200, ~400 GETs/dia.)"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._vistos: dict = {}
        self._trava = threading.Lock()

    def get(self, path: str, params: dict | None = None):
        if path != "/admin/api/orders/audit" or not params:
            return super().get(path, params)
        params = {**params, "limit": 200}
        chave = (threading.get_ident(), params.get("start_date"), params.get("end_date"))
        resp = super().get(path, params)
        ids = {o.get("id") for o in lista_pedidos(resp) if isinstance(o, dict)}
        with self._trava:
            vistos = set() if int(params.get("page", 1)) == 1 else self._vistos.get(chave, set())
            novo = bool(ids - vistos)
            self._vistos[chave] = vistos | ids
        return resp if novo else {"orders": []}


def limpa_motoboy(nome) -> str:
    """Apelido do motoboy como vem no pedido, sem números (o ALIV às vezes traz CNPJ no nome)."""
    s = re.sub(r"(?i)cnpj|cpf|mei", " ", str(nome or ""))
    s = re.sub(r"[\d./\-–—:]+", " ", s)
    return " ".join(s.split())[:40]


def coletar_loja(api: Aliv, d: date, sushi: bool) -> dict:
    ini, fim = janela_turno(d)
    peds = pedidos_do_turno(api, d, fim)
    r = (calcular_sushi if sushi else calcular)(peds, fim)
    L = {k: r.get(k, 0) for k in SOMAS if k in r}
    L["pedidos"], L["cancelados"] = r["pedidos"], r["cancelados"]
    L["canais"], L["ifood_lojas"], L["motoboys"] = {}, {}, {}
    for k, (n, v) in r["por_loja_ifood"].items():
        L["ifood_lojas"][re.sub(r"^Tili\s*", "", k) or k] = [n, round(v, 2)]
    pecas_canal = {k: v[2] for k, v in r.get("por_canal_sushi", {}).items()}
    for p in peds:
        st = status_de(p)
        if st.startswith("CANCELADO") or st == "AGUARDANDO_PAGAMENTO":
            continue
        c = L["canais"].setdefault(canal_sushi(p), [0, 0.0, 0])
        c[0] += 1
        c[1] = round(c[1] + num(p.get("total_value")), 2)
        if (str(p.get("delivery_type") or "").lower() == "delivery" and st in STATUS_FINALIZADO
                and not p.get("is_partner_delivery")):
            m = limpa_motoboy(p.get("driver") or p.get("driver_name"))
            if m and m.lower() != "sem motoboy" and not eh_gerente(m):
                L["motoboys"][m] = L["motoboys"].get(m, 0) + 1
    for k, pc in pecas_canal.items():
        if k in L["canais"]:
            L["canais"][k][2] = pc
    ops = monitor_tempos(api, ini, fim)
    L["tempos"] = {k: [num(resumo(ops, ch).get("avg_min")), int(num(resumo(ops, ch).get("n")))]
                   for k, ch in (("prod", "prod_delivery"), ("rua", "street"), ("vida", "life_delivery"))}
    vida = resumo(ops, "life_delivery")
    L["atrasos"] = conta_atrasos(api, ini, fim, vida) if vida.get("n") else 0
    for k in ("vendas", "receita", "desc_loja", "desc_plataforma", "desc_manual", "comissao_ifood",
              "desc_loja_ifood", "receita_ifood", "proprios"):
        L[k] = round(float(L.get(k, 0)), 2)
    return L


def coletar_dia(apis: dict, d: date, agora: datetime, usar_cache: bool = True) -> dict:
    arq = CACHE / f"{d.isoformat()}.json"
    if usar_cache:
        try:
            x = json.loads(arq.read_text(encoding="utf-8"))
            if x.get("v") == VERSAO_CACHE and all(x["lojas"].get(k) is not None for k in apis):
                return x
        except (OSError, ValueError, KeyError):
            pass
    x = {"v": VERSAO_CACHE, "dia": d.isoformat(), "lojas": {}}
    for k, api in apis.items():
        try:
            x["lojas"][k] = coletar_loja(api, d, k == "sushi")
        except (AlivError, OSError) as e:
            if k == "piz":
                raise
            print(f"aviso: Sushi {d:%d/%m} falhou: {e}", file=sys.stderr)
            x["lojas"][k] = None
    fechado = janela_turno(d)[1] + timedelta(hours=1) <= agora
    if fechado and all(v is not None for v in x["lojas"].values()):
        CACHE.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"coletado {d:%d/%m}", file=sys.stderr)
    return x


def coletar_dias(apis: dict, dias: list[date], agora: datetime, usar_cache: bool) -> dict[date, dict]:
    with ThreadPoolExecutor(3) as ex:
        return dict(zip(dias, ex.map(lambda d: coletar_dia(apis, d, agora, usar_cache), dias)))


# ------------------------------------------------------------------ agregação
def diaria(d: date) -> float:
    return DIARIA_FDS if d.weekday() >= 5 else DIARIA_SEMANA


def _soma_em(a: dict, L: dict) -> None:
    for k in SOMAS:
        a[k] = a.get(k, 0) + L.get(k, 0)
    for chave in ("canais", "ifood_lojas"):
        for nome, vals in L.get(chave, {}).items():
            c = a[chave].setdefault(nome, [0] * len(vals))
            for i, v in enumerate(vals):
                c[i] += v
    for nome, n in L.get("motoboys", {}).items():
        a["motoboys"][nome] = a["motoboys"].get(nome, 0) + n
    for k, (avg, n) in L.get("tempos", {}).items():
        t = a["tempos"].setdefault(k, [0.0, 0])
        t[0] += avg * n
        t[1] += n


def _novo() -> dict:
    return {"canais": {}, "ifood_lojas": {}, "motoboys": {}, "tempos": {}, "custo_moto": 0.0,
            "turnos": 0, "diarias": 0.0}


def _deriva(a: dict) -> dict:
    a["total"] = a["pedidos"] + a["cancelados"]
    a["ticket"] = a["vendas"] / a["pedidos"] if a["pedidos"] else 0.0
    a["taxa_cancel"] = a["cancelados"] / a["total"] if a["total"] else 0.0
    a["custo_ifood"] = ((a["comissao_ifood"] + a["desc_loja_ifood"]) / a["receita_ifood"]
                        if a["receita_ifood"] else 0.0)
    a["tempo"] = {k: (s / n if n else 0.0, n) for k, (s, n) in a["tempos"].items()}
    nv = a["tempo"].get("vida", (0, 0))[1]
    a["pct_atraso"] = a["atrasos"] / nv if nv else 0.0
    a["entregas"] = sum(a["motoboys"].values())
    a["custo_entrega"] = a["custo_moto"] / a["entregas"] if a["entregas"] else 0.0
    a["l"] = lucro({"receita": a["receita"], "comissao_ifood": a["comissao_ifood"],
                    "proprios": a["proprios"]}, a["custo_moto"])
    return a


def agregar(dias: dict[date, dict]) -> dict:
    """{'piz': agg, 'sushi': agg|None, 'tot': agg, 'por_dia': [...], 'turnos': {...}}."""
    out = {k: _novo() for k in ("piz", "sushi", "tot")}
    tem_sushi = all(x["lojas"].get("sushi") for x in dias.values()) and bool(dias)
    por_dia, turnos_moto = [], {}
    for d, x in sorted(dias.items()):
        lojas = {k: x["lojas"].get(k) for k, _ in LOJAS}
        motos = set()
        for L in lojas.values():
            if L:
                motos.update(L["motoboys"])
        for m in motos:
            turnos_moto[m] = turnos_moto.get(m, 0) + 1
        diarias = len(motos) * diaria(d)
        ent_dia = sum(sum(L["motoboys"].values()) for L in lojas.values() if L) or 0
        dia_tot = _novo()
        for k, L in lojas.items():
            if not L:
                continue
            ent = sum(L["motoboys"].values())
            custo = (diarias * ent / ent_dia if ent_dia else 0.0) + ent * POR_ENTREGA
            for alvo in (out[k], out["tot"], dia_tot):
                _soma_em(alvo, L)
                alvo["custo_moto"] += custo
        for alvo in (out["tot"], dia_tot):
            alvo["turnos"] += len(motos)
            alvo["diarias"] += diarias
        _deriva(dia_tot)
        por_dia.append({"dia": d, "pedidos": dia_tot["pedidos"], "vendas": dia_tot["vendas"],
                        "lucro": dia_tot["l"]["lucro"], "turnos": len(motos),
                        "entregas": dia_tot["entregas"], "atrasos": dia_tot["atrasos"],
                        "vida": dia_tot["tempo"].get("vida", (0, 0))[0],
                        "piz": (lojas["piz"] or {}).get("vendas", 0.0),
                        "sushi": (lojas.get("sushi") or {}).get("vendas", 0.0)})
    for k in out:
        _deriva(out[k])
    if not tem_sushi:
        out["sushi"] = None
    out["por_dia"] = por_dia
    out["turnos_moto"] = turnos_moto
    out["dias"] = len(dias)
    return out


# ------------------------------------------------------------- comparações
def variacao(a: float, b: float) -> float | None:
    return (a - b) / b if b else None


# (chave, rótulo, getter, formato, maior é melhor?, é percentual?)
METRICAS = [
    ("vendas", "Vendas", lambda a: a["vendas"], brl, True, False),
    ("pedidos", "Pedidos", lambda a: a["pedidos"], lambda v: f"{v:.0f}", True, False),
    ("ticket", "Ticket médio", lambda a: a["ticket"], brl, True, False),
    ("cancel", "Cancelamento", lambda a: a["taxa_cancel"], pct, False, True),
    ("lucro", "Lucro estimado", lambda a: a["l"]["lucro"], brl, True, False),
    ("custo_ifood", "Custo iFood (Pizzaria)", None, pct, False, True),
    ("vida", "Vida da entrega", lambda a: a["tempo"].get("vida", (0, 0))[0], lambda v: f"{v:.0f} min", False, False),
    ("atraso", "Entregas > 45 min", lambda a: a["pct_atraso"], pct, False, True),
    ("custo_entrega", "Custo por entrega", lambda a: a["custo_entrega"], brl, False, False),
]


def valor(sem: dict, chave: str) -> float:
    for k, _, g, *_ in METRICAS:
        if k == chave:
            return sem["piz"]["custo_ifood"] if k == "custo_ifood" else g(sem["tot"])
    raise KeyError(chave)


def destaques(cur: dict, ant: dict, mtd: dict | None) -> tuple[str, str, str]:
    """(melhorou, piorou, recomendação) — comparando com a semana anterior."""
    mov = []
    for k, rot, g, fmt, maior_melhor, eh_pct in METRICAS:
        a, b = valor(cur, k), valor(ant, k)
        if eh_pct:
            delta, forca = a - b, (a - b) * 5        # 1 ponto percentual ≈ 5% de variação
        else:
            v = variacao(a, b)
            if v is None:
                continue
            delta, forca = a - b, v
        bom = forca if maior_melhor else -forca
        if abs(forca) < 0.005:
            continue
        if eh_pct:
            txt = f"{rot} {'subiu' if delta > 0 else 'caiu'} de {fmt(b)} para {fmt(a)}"
        else:
            txt = f"{rot} {'subiu' if delta > 0 else 'caiu'} {pct(abs(forca))} ({fmt(a)} vs {fmt(b)})"
        mov.append((bom, txt))
    mov.sort()
    melhor = mov[-1][1] if mov and mov[-1][0] > 0 else "Nenhum indicador melhorou de forma relevante."
    pior = mov[0][1] if mov and mov[0][0] < 0 else "Nenhum indicador piorou de forma relevante."
    return melhor, pior, recomendacao(cur)


def no_dia(d: date) -> str:
    """'na terça 27/10', 'no domingo 01/11'."""
    return f"{'no' if d.weekday() >= 5 else 'na'} {DIAS[d.weekday()]} {d:%d/%m}"


def recomendacao(c: dict) -> str:
    t, p, dias = c["tot"], c["piz"], c["por_dia"]
    if t["pct_atraso"] > 0.10 and dias:
        d = max(dias, key=lambda x: (x["atrasos"], x["vida"]))
        return (f"{t['atrasos']} entregas passaram de 45 min ({pct(t['pct_atraso'])}), mais {no_dia(d['dia'])} "
                f"({d['atrasos']}). Chame +1 motoboy nesse dia e "
                f"confira o preparo no pico.")
    if p["custo_ifood"] > META_CUSTO_IFOOD:
        return (f"Custo iFood da Pizzaria em {pct(p['custo_ifood'])} (meta até 25%). Revise os cupons "
                f"pagos pela loja no iFood ({brl(p['desc_loja_ifood'])} na semana).")
    if t["taxa_cancel"] > META_CANCEL:
        return (f"Cancelamento em {pct(t['taxa_cancel'])} ({t['cancelados']} pedidos). Veja os motivos "
                f"no ALIV e ataque o mais comum.")
    if p["pedidos"] and p["ticket"] < META_TICKET:
        return (f"Ticket da Pizzaria em {brl(p['ticket'])}, abaixo da meta de {brl(META_TICKET)}. "
                f"Ofereça bebida, borda ou combo em todo pedido do App e do WhatsApp.")
    prep = p["tempo"].get("prod", (0, 0))[0]
    if prep > META_PREPARO:
        return f"Preparo médio da Pizzaria em {prep:.0f} min (meta {META_PREPARO:.0f}). Reforce a cozinha no pico."
    if dias:
        d = min(dias, key=lambda x: x["vendas"])
        return (f"{DIAS[d['dia'].weekday()].capitalize()} foi o dia mais fraco ({brl(d['vendas'])}). "
                f"Faça uma promoção nesse dia e divulgue no Instagram e WhatsApp.")
    return "Manter o ritmo."


def projecao(mtd: dict, dias_passados: int, dias_mes: int) -> dict:
    f = dias_mes / dias_passados if dias_passados else 0
    return {"vendas": mtd["tot"]["vendas"] * f, "pedidos": mtd["tot"]["pedidos"] * f,
            "lucro": mtd["tot"]["l"]["lucro"] * f}


# ------------------------------------------------------------------- texto
def seta(a: float, b: float, maior_melhor: bool = True, eh_pct: bool = False) -> str:
    if eh_pct:
        d = a - b
        if abs(d) < 0.0005:
            return "= 0,0 p.p."
        return f"{'▲' if d > 0 else '▼'} {abs(d) * 100:.1f} p.p.".replace(".", ",", 1)
    v = variacao(a, b)
    if v is None:
        return "—"
    return f"{'▲' if v >= 0 else '▼'} {pct(abs(v))}"


def nome_dia(d: date) -> str:
    fer = feriados(d.year)
    return f"{DIAS_CURTO[d.weekday()]} {d:%d/%m}" + (f" ({fer[d]})" if d in fer else "")


def texto_resumo(R: dict) -> str:
    seg, dom, c, a, m = R["seg"], R["dom"], R["cur"], R["ant"], R["mes"]
    t = c["tot"]
    L = [f"*Fechamento semanal Tili — {seg:%d/%m} a {dom:%d/%m}*", ""]
    L.append(f"✅ Melhorou: {R['dest'][0]}")
    L.append(f"⚠️ Piorou: {R['dest'][1]}")
    L.append(f"💡 Recomendação: {R['dest'][2]}")
    L.append("")
    L.append(f"*Consolidado:* {t['pedidos']} pedidos · {brl(t['vendas'])} · ticket {brl(t['ticket'])}")
    L.append(f"vs semana anterior: vendas {seta(t['vendas'], a['tot']['vendas'])} · "
             f"pedidos {seta(t['pedidos'], a['tot']['pedidos'])}")
    L.append(f"vs mesma semana do mês passado: vendas {seta(t['vendas'], m['tot']['vendas'])}")
    for k, rot in LOJAS:
        x = c[k]
        if not x:
            continue
        extra = f" · {x['pecas']} peças" if k == "sushi" else ""
        L.append(f"• {rot}: {x['pedidos']} ped. · {brl(x['vendas'])} · ticket {brl(x['ticket'])} · "
                 f"cancel. {pct(x['taxa_cancel'])}{extra}")
    L.append(f"Motoboys: {t['turnos']} turnos · {t['entregas']} entregas · {brl(t['custo_moto'])} "
             f"({brl(t['custo_entrega'])}/entrega) · {t['atrasos']} acima de 45 min")
    L.append(f"Lucro *estimado*: {brl(t['l']['lucro'])} ({pct(t['l']['margem'])})")
    b, w = R["melhor"], R["pior"]
    L.append(f"Melhor dia: {nome_dia(b['dia'])} {brl(b['vendas'])} · pior: {nome_dia(w['dia'])} {brl(w['vendas'])}")
    mt, pj = R["mtd"]["tot"], R["proj"]
    L.append(f"{R['mes_nome']} até {dom:%d/%m}: {brl(mt['vendas'])} · projeção {brl(pj['vendas'])}")
    L.append("")
    L.append("Lucro é estimativa (CMV 26,5%, imposto 9,45%, iFood 12,8%, cartão 1,6%, motoboys).")
    return "\n".join(L)


def _tabela(cab: list[str], linhas: list[list[str]]) -> list[str]:
    return (["| " + " | ".join(cab) + " |", "|" + "|".join("---" for _ in cab) + "|"]
            + ["| " + " | ".join(map(str, ln)) + " |" for ln in linhas])


def relatorio_md(R: dict) -> str:
    seg, dom, c, a, m = R["seg"], R["dom"], R["cur"], R["ant"], R["mes"]
    L = [f"# Fechamento semanal Tili — {seg:%d/%m/%Y} a {dom:%d/%m/%Y}", "",
         f"Dia operacional 16:00–04:00 · gerado em {R['gerado']:%d/%m/%Y %H:%M} (America/Bahia) · "
         "dados do ALIV (só leitura). **Lucro é estimativa.**", "",
         "## Destaques", "",
         f"- **Melhorou:** {R['dest'][0]}", f"- **Piorou:** {R['dest'][1]}",
         f"- **Recomendação:** {R['dest'][2]}", ""]
    L += ["## Resumo por loja", ""]
    cols = [("piz", "Pizzaria"), ("sushi", "Sushi"), ("tot", "Consolidado")]
    cols = [(k, r) for k, r in cols if c[k]]
    def lin(rot, f):
        return [rot] + [f(c[k]) for k, _ in cols]
    L += _tabela([""] + [r for _, r in cols], [
        lin("Pedidos", lambda x: x["pedidos"]),
        lin("Vendas", lambda x: brl(x["vendas"])),
        lin("Ticket médio", lambda x: brl(x["ticket"])),
        lin("Cancelados", lambda x: f"{x['cancelados']} ({pct(x['taxa_cancel'])})"),
        lin("Desconto loja", lambda x: brl(x["desc_loja"])),
        lin("Desconto iFood (bancado pelo iFood)", lambda x: brl(x["desc_plataforma"])),
        lin("Custo iFood (comissão + desc. loja ÷ receita iFood)", lambda x: pct(x["custo_ifood"])),
        lin("Entregas (motoboys próprios)", lambda x: x["entregas"]),
        lin("Custo motoboys", lambda x: brl(x["custo_moto"])),
        lin("Preparo médio delivery", lambda x: f"{x['tempo'].get('prod', (0, 0))[0]:.0f} min"),
        lin("Rua média", lambda x: f"{x['tempo'].get('rua', (0, 0))[0]:.0f} min"),
        lin("Vida média delivery", lambda x: f"{x['tempo'].get('vida', (0, 0))[0]:.0f} min"),
        lin("Entregas > 45 min", lambda x: f"{x['atrasos']} ({pct(x['pct_atraso'])})"),
        lin("Lucro estimado", lambda x: f"{brl(x['l']['lucro'])} ({pct(x['l']['margem'])})"),
    ])
    if c["sushi"]:
        L += ["", f"Sushi: **{c['sushi']['pecas']} peças**" + (f" + {c['sushi']['temakis']} temakis" if c["sushi"]["temakis"] else "")]
    L += ["", "## Vendas por canal", ""]
    for k, rot in LOJAS:
        x = c[k]
        if not x:
            continue
        linhas = [[n, v[0], brl(v[1])] + ([v[2]] if k == "sushi" else [])
                  for n, v in sorted(x["canais"].items(), key=lambda i: -i[1][1])]
        L += [f"**{rot}**", ""] + _tabela(["Canal", "Pedidos", "Vendas"] + (["Peças"] if k == "sushi" else []), linhas)
        if x["ifood_lojas"]:
            L += ["", f"iFood por loja ({rot}):", ""] + _tabela(["Loja iFood", "Pedidos", "Vendas"], [
                [n, v[0], brl(v[1])] for n, v in sorted(x["ifood_lojas"].items(), key=lambda i: -i[1][1])])
        L.append("")
    t = c["tot"]
    L += ["## Motoboys (Pizzaria + Sushi)", "",
          f"- Turnos: **{t['turnos']}** · entregas: **{t['entregas']}** · média {t['entregas'] / t['turnos']:.1f} por turno" if t["turnos"] else "- Sem turnos",
          f"- Custo estimado: **{brl(t['custo_moto'])}** = diárias {brl(t['diarias'])} + {t['entregas']} × {brl(POR_ENTREGA)}",
          f"- Custo por entrega: **{brl(t['custo_entrega'])}**", ""]
    L += _tabela(["Motoboy", "Turnos", "Entregas", "Por turno"], [
        [n, c["turnos_moto"].get(n, 0), e, f"{e / max(c['turnos_moto'].get(n, 1), 1):.1f}"]
        for n, e in sorted(t["motoboys"].items(), key=lambda i: -i[1])])
    L += ["", "## Dia a dia (consolidado)", ""]
    L += _tabela(["Dia", "Pedidos", "Vendas", "Pizzaria", "Sushi", "Lucro est.", "Turnos", "Entregas", "> 45 min", "Vida"], [
        [nome_dia(d["dia"]) + (" 🏆" if d is R["melhor"] else " ⬇️" if d is R["pior"] else ""),
         d["pedidos"], brl(d["vendas"]), brl(d["piz"]), brl(d["sushi"]), brl(d["lucro"]), d["turnos"],
         d["entregas"], d["atrasos"], f"{d['vida']:.0f} min"] for d in c["por_dia"]])
    L += ["", f"Melhor dia: **{nome_dia(R['melhor']['dia'])}** ({brl(R['melhor']['vendas'])}) · "
              f"pior dia: **{nome_dia(R['pior']['dia'])}** ({brl(R['pior']['vendas'])})", ""]
    L += ["## Comparações", "",
          f"Semana anterior: {R['ant_seg']:%d/%m} a {R['ant_seg'] + timedelta(days=6):%d/%m} · "
          f"mesma semana do mês passado: {R['mes_seg']:%d/%m} a {R['mes_seg'] + timedelta(days=6):%d/%m} "
          "(4 semanas antes, mesmos dias da semana).", ""]
    for k, rot in (("tot", "Consolidado"),) + LOJAS:
        if not c[k] or not a[k] or not m[k]:
            continue
        linhas = []
        for chave, nome, g, fmt, mm, ep in METRICAS:
            if chave == "custo_ifood":
                continue
            x, y, z = g(c[k]), g(a[k]), g(m[k])
            linhas.append([nome, fmt(x), fmt(y), seta(x, y, mm, ep), fmt(z), seta(x, z, mm, ep)])
        L += [f"**{rot}**", ""] + _tabela(["", "Semana", "Sem. anterior", "Var.", "Mês passado", "Var."], linhas) + [""]
    mt, pj = R["mtd"], R["proj"]
    L += [f"## {R['mes_nome']} até {dom:%d/%m} ({R['dias_mtd']} de {R['dias_mes']} dias)", ""]
    L += _tabela(["", "Acumulado", "Projeção fim do mês"], [
        ["Vendas consolidadas", brl(mt["tot"]["vendas"]), brl(pj["vendas"])],
        ["Pedidos", mt["tot"]["pedidos"], f"{pj['pedidos']:.0f}"],
        ["Lucro estimado", brl(mt["tot"]["l"]["lucro"]), brl(pj["lucro"])],
        ["Pizzaria vendas", brl(mt["piz"]["vendas"]), ""],
    ] + ([["Sushi vendas", brl(mt["sushi"]["vendas"]), ""]] if mt["sushi"] else []))
    L += ["", "Projeção simples: média diária do mês até agora × dias do mês.", "",
          "## Como o lucro é estimado", "",
          f"Receita − CMV {pct(CMV)} − imposto {pct(IMPOSTO)} − comissão iFood 12,8% − cartão {pct(CARTAO)} "
          f"nos pedidos próprios − motoboys (diária R$ {DIARIA_SEMANA:.0f} seg–sex / R$ {DIARIA_FDS:.0f} "
          f"sáb–dom por motoboy que trabalhou + {brl(POR_ENTREGA)} por entrega; dividido entre as lojas "
          "pelas entregas). Mesma fórmula do monitor. **É estimativa, não é o resultado contábil.**", ""]
    return "\n".join(L)


# --------------------------------------------------------------------- main
def semana_alvo(ref: date | None, hoje: date) -> date:
    if ref:
        return ref - timedelta(days=ref.weekday())
    return hoje - timedelta(days=hoje.weekday()) - timedelta(days=7)


def montar(apis: dict, seg: date, agora: datetime, usar_cache: bool = True) -> dict:
    dom = seg + timedelta(days=6)
    ant_seg, mes_seg = seg - timedelta(days=7), seg - timedelta(days=28)
    ini_mes = dom.replace(day=1)
    semana = [seg + timedelta(days=i) for i in range(7)]
    todos = sorted(set(semana) | {ant_seg + timedelta(days=i) for i in range(7)}
                   | {mes_seg + timedelta(days=i) for i in range(7)}
                   | {ini_mes + timedelta(days=i) for i in range((dom - ini_mes).days + 1)})
    D = coletar_dias(apis, todos, agora, usar_cache)
    pega = lambda ini, n: agregar({ini + timedelta(days=i): D[ini + timedelta(days=i)] for i in range(n)})
    cur = pega(seg, 7)
    R = {"seg": seg, "dom": dom, "gerado": agora, "cur": cur, "ant": pega(ant_seg, 7),
         "mes": pega(mes_seg, 7), "ant_seg": ant_seg, "mes_seg": mes_seg,
         "mtd": pega(ini_mes, (dom - ini_mes).days + 1), "dias_mtd": (dom - ini_mes).days + 1,
         "dias_mes": calendar.monthrange(dom.year, dom.month)[1],
         "mes_nome": ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
                      "Setembro", "Outubro", "Novembro", "Dezembro"][dom.month - 1]}
    R["proj"] = projecao(R["mtd"], R["dias_mtd"], R["dias_mes"])
    R["melhor"] = max(cur["por_dia"], key=lambda d: d["vendas"])
    R["pior"] = min(cur["por_dia"], key=lambda d: d["vendas"])
    R["dest"] = destaques(cur, R["ant"], R["mtd"])
    return R


def main() -> int:
    ap = argparse.ArgumentParser(description="Fechamento semanal da Tili (ALIV, só leitura)")
    ap.add_argument("--semana", help="qualquer dia da semana a fechar (AAAA-MM-DD); padrão: a semana passada")
    ap.add_argument("--inicio", help="começa a semana neste dia exato (AAAA-MM-DD), 7 dias; para testes")
    ap.add_argument("--painel", metavar="PASTA", help="pasta para salvar os PNGs (padrão: temporária)")
    ap.add_argument("--sem-painel", action="store_true", help="não gera o painel")
    ap.add_argument("--sem-salvar", action="store_true", help="não grava monitor/semanal/AAAA-MM-DD.md")
    ap.add_argument("--sem-cache", action="store_true", help="ignora o cache dos dias e busca tudo no ALIV")
    ap.add_argument("--whatsapp", action="store_true", help="envia o painel do iPad + texto para WHATSAPP_EMERSON")
    args = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: defina ALIV_USER e ALIV_PASS nas variáveis de ambiente.", file=sys.stderr)
        return 2
    agora = datetime.now(TZ).replace(second=0, microsecond=0)
    seg = (date.fromisoformat(args.inicio) if args.inicio else
           semana_alvo(date.fromisoformat(args.semana) if args.semana else None, agora.date()))
    if janela_turno(seg + timedelta(days=6))[1] > agora:
        print(f"aviso: a semana de {seg:%d/%m} ainda não fechou; números parciais.", file=sys.stderr)

    api = AlivSemanal(user, pwd)
    apis = {"piz": api}
    us, ps = os.environ.get("ALIV_USER_SUSHI"), os.environ.get("ALIV_PASS_SUSHI")
    try:
        api.login()
        if us and ps:
            sushi = AlivSemanal(us, ps)
            try:
                sushi.login()
                apis["sushi"] = sushi
            except (AlivError, OSError) as e:
                print(f"aviso: login do Sushi falhou: {e}", file=sys.stderr)
        R = montar(apis, seg, agora, not args.sem_cache)
    except (AlivError, OSError) as e:
        print(f"Fechamento semanal Tili — ERRO no ALIV\n\n{e}")
        return 1

    texto = texto_resumo(R)
    print(texto)
    if not args.sem_salvar:
        PASTA.mkdir(parents=True, exist_ok=True)
        arq = PASTA / f"{seg.isoformat()}.md"
        arq.write_text(relatorio_md(R), encoding="utf-8")
        print(f"RELATÓRIO: {arq}", file=sys.stderr)

    paineis: list = []
    if not args.sem_painel:
        pasta = Path(args.painel) if args.painel else Path(tempfile.mkdtemp())
        try:
            from painel_semanal import gerar_paineis
            for rot, res in gerar_paineis(R, pasta / f"semanal_{seg.isoformat()}"):
                if isinstance(res, Exception):
                    print(f"PAINEL {rot}: não gerado — {res}", file=sys.stderr)
                else:
                    paineis.append((rot, res))
                    print(f"PAINEL {rot}: {res}", file=sys.stderr)
        except Exception as e:      # o painel nunca derruba o relatório
            print(f"PAINEL: não gerado — {e}", file=sys.stderr)

    if args.whatsapp:
        fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
        if not fone:
            print("WHATSAPP: não enviado — variável WHATSAPP_EMERSON não definida.", file=sys.stderr)
            return 3
        ok = 0
        for rot, arq in paineis:
            try:
                api.enviar_whatsapp(fone, f"Fechamento semanal Tili ({rot}) — {seg:%d/%m} a {R['dom']:%d/%m}", arquivo=arq)
                ok += 1
                print(f"WHATSAPP: painel {rot} enviado.", file=sys.stderr)
            except (AlivError, OSError) as e:
                print(f"WHATSAPP: painel {rot} não enviado — {e}", file=sys.stderr)
        try:
            api.enviar_whatsapp(fone, texto)
            print("WHATSAPP: texto enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: texto não enviado — {e}", file=sys.stderr)
            return 3
        if paineis and not ok:
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
