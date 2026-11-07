#!/usr/bin/env python3
"""Relatório SEMANAL dos prestadores MEI (motoboys com CNPJ) da Tili — só leitura no ALIV.

Semana de segunda a domingo (dia operacional = hora − 6h: o que passa da meia-noite
conta no dia anterior). Reaproveita login, WhatsApp, layout e PDF do diaristas.py.

Para cada prestador e cada dia: turno, fechamento gravado no ALIV, diária, entregas da
Pizzaria (códigos e taxa gravada) e entregas do Sushi (pela diferença no fechamento).
Correções aplicadas (todas listadas no PDF e na mensagem final):
  - diária R$ 100 de segunda a sexta e R$ 120 sábado e domingo;
  - entrega sempre R$ 2,00 (corrige 0; 6,99; 7; 40...);
  - fechamento abaixo de diária + R$ 2 por entrega: completa a diferença;
  - nome colado ("AdrianoSantos" → "Adriano Santos").
Alertas: turno de domingo aberto (espera 10 min e tenta de novo), cadastro duplicado
(entra duas vezes), entrega gravada a R$ 0.

Saída:
  monitor/prestadores/AAAA-MM-DD/Prestadores_semana_DD-MM_a_DD-MM_COMPLETO.pdf
  monitor/prestadores/AAAA-MM-DD/individuais/<Nome>.pdf   (1 por prestador)
  mensagem final (stdout e WhatsApp)

Uso:
  python3 monitor/prestadores.py                          # semana que fechou (seg a dom anterior)
  python3 monitor/prestadores.py --semana 2026-10-27 --dry-run   # semana que contém a data

Códigos de saída: 0 ok · 1 erro de login/ALIV · 2 faltam variáveis · 3 WhatsApp falhou.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diaristas import (CNPJ_EMPRESA, CSS, DIARIA_FDS, DIARIA_SEMANA, DIAS_CURTO, DIAS_SEMANA,  # noqa: E402
                       EMPRESA, _esc, _logo_src, enviar, html_para_pdf, lista, normaliza)
from monitor import Aliv, AlivError, TZ, brl, num, parse_dt  # noqa: E402

BASE = Path(__file__).resolve().parent
PASTA = BASE / "prestadores"
PIX_ARQ = BASE / "assets" / "pix_prestadores.json"   # {"<CNPJ só dígitos>": "chave"}; sem entrada = CNPJ

# ---------------------------------------------------------------- parâmetros
VIRADA_H = 6                 # dia operacional = hora − 6h
POR_ENTREGA = 2.0            # Pizzaria e Sushi
GERENTES = [{"thiago", "camilo"}, {"josue", "ruas"}]   # logins de gerente: nunca entram
RE_CNPJ = re.compile(r"\bCNPJ\b\.?", re.I)
ESPERA_DOMINGO_S = 600       # turno de domingo aberto: espera 10 min e tenta de novo


# ---------------------------------------------------------------- modelo
@dataclass
class Dia:
    data: date
    turnos: list = field(default_factory=list)        # [(inicio, fim|None)]
    fechamento: float = 0.0                           # soma dos fechamentos gravados no ALIV
    tem_fechamento: bool = False
    diaria_gravada: float | None = None
    extras: list = field(default_factory=list)        # [(descrição, valor)] ajustes manuais somados ao fechamento
    pizzaria: list = field(default_factory=list)      # [{id, codigo, hora, taxa}]
    sushi_pedidos: list = field(default_factory=list)
    sushi: int = 0
    diaria: float = 0.0
    correto: float = 0.0
    correcoes: list = field(default_factory=list)     # [(texto, delta)]
    avisos: list = field(default_factory=list)

    @property
    def aberto(self) -> bool:
        return any(f is None for _, f in self.turnos)

    @property
    def extra(self) -> float:
        return sum(v for _, v in self.extras)


@dataclass
class Prestador:
    id: int
    nome_aliv: str
    nome: str
    cnpj: str
    pix: str
    dias: dict = field(default_factory=dict)          # date -> Dia
    correcoes: list = field(default_factory=list)     # [(texto, delta)] fora dos dias (ex.: nome)
    avisos: list = field(default_factory=list)

    def dias_trab(self) -> list[Dia]:
        return [self.dias[d] for d in sorted(self.dias)]

    @property
    def pizzaria(self) -> int:
        return sum(len(d.pizzaria) for d in self.dias.values())

    @property
    def sushi(self) -> int:
        return sum(d.sushi for d in self.dias.values())

    @property
    def total(self) -> float:
        return round(sum(d.correto for d in self.dias.values()), 2)

    @property
    def total_aliv(self) -> float:
        return round(sum(d.fechamento for d in self.dias.values()), 2)

    @property
    def todas_correcoes(self) -> list:
        return self.correcoes + [c for d in self.dias_trab() for c in d.correcoes]


# ---------------------------------------------------------------- utilidades
def dia_op(dt: datetime) -> date:
    return (dt - timedelta(hours=VIRADA_H)).date()


def diaria_padrao(d: date) -> float:
    return DIARIA_FDS if d.weekday() >= 5 else DIARIA_SEMANA


def semana_de(ref: date) -> date:
    return ref - timedelta(days=ref.weekday())


def semana_fechada(agora: datetime) -> date:
    """Segunda da última semana completa (seg a dom) antes de hoje."""
    return semana_de(agora.date()) - timedelta(days=7)


def fmt_cnpj(dig: str) -> str:
    return f"{dig[:2]}.{dig[2:5]}.{dig[5:8]}/{dig[8:12]}-{dig[12:]}" if len(dig) == 14 else dig


def separa_nome(nome: str) -> str:
    """'AdrianoSantos de Assis' → 'Adriano Santos de Assis'."""
    return re.sub(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Þ])", " ", nome)


def eh_gerente(nome: str) -> bool:
    toks = set(normaliza(RE_CNPJ.split(nome)[0]).split())
    return any(g <= toks and len(toks) <= len(g) + 1 for g in GERENTES)


def eh_prestador(nome: str) -> bool:
    return bool(nome) and bool(RE_CNPJ.search(nome)) and not eh_gerente(nome)


def dados_nome(nome_aliv: str) -> tuple[str, str]:
    """Separa nome e CNPJ (só dígitos) do nome cadastrado no ALIV."""
    partes = RE_CNPJ.split(nome_aliv, maxsplit=1)
    base = re.sub(r"[\s.\-–—]+$", "", partes[0]).strip()
    dig = re.sub(r"\D", "", partes[1])[:14] if len(partes) > 1 else ""
    return base, dig


def carrega_pix() -> dict:
    try:
        return {re.sub(r"\D", "", k): v for k, v in json.loads(PIX_ARQ.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError):
        return {}


def dm(d: date) -> str:
    return f"{d:%d/%m}"


# ---------------------------------------------------------------- coleta
def coletar(api: Aliv, seg: date, agora: datetime) -> list[Prestador]:
    dom = seg + timedelta(days=6)
    semana = {seg + timedelta(days=i) for i in range(7)}
    p_sem = {"start": f"{seg}", "end": f"{dom + timedelta(days=1)}"}          # payouts / history
    p_ped = {"start": f"{seg}", "end": f"{dom + timedelta(days=2)}"}          # pedidos (end exclusivo)

    live = {int(d["id"]): d for d in lista(api.get("/admin/api/finance/drivers-live"), "drivers", "data")
            if isinstance(d, dict) and d.get("id") is not None}
    rel = api.get("/admin/api/finance/drivers-report",
                  {"start": f"{seg}", "end": f"{dom + timedelta(days=1)}",
                   "tipo": "entrega,financeiro", "date_basis": "delivery"})
    nomes = {i: d.get("name", "") for i, d in live.items()}
    for r in lista(rel, "rows"):
        if r.get("id") is not None:
            nomes.setdefault(int(r["id"]), r.get("name", ""))
    pix = carrega_pix()
    prest = []
    for i, n in nomes.items():
        if not eh_prestador(n):
            continue
        base, dig = dados_nome(n.strip())
        nome = separa_nome(base)
        p = Prestador(i, n.strip(), nome, dig, pix.get(dig) or fmt_cnpj(dig))
        if nome != base:
            p.correcoes.append((f"nome separado: \"{base}\" → \"{nome}\"", 0.0))
        prest.append(p)

    def um(p: Prestador) -> Prestador:
        def dia(d: date) -> Dia:
            return p.dias.setdefault(d, Dia(d))

        # Turnos e fechamentos (payouts). As deliveries do grupo são só da Pizzaria.
        fee_ids = set()
        for g in lista(api.get(f"/admin/api/finance/driver/{p.id}/payouts", p_sem), "groups"):
            ini = parse_dt(g.get("session_start"), seg.year)
            if ini is None or dia_op(ini) not in semana:
                continue
            fim = parse_dt(g.get("session_end"), seg.year)
            x = dia(dia_op(ini))
            x.turnos.append((ini, fim))
            if lista(g, "payments"):
                x.fechamento += num(g.get("total_paid"))
                x.tem_fechamento = True
            fee_ids |= {int(e["order_id"]) for e in lista(g, "deliveries") if e.get("order_id") is not None}
        d_live = live.get(p.id, {})
        ts = num(d_live.get("start_ts"))
        if str(d_live.get("status", "")).lower() == "online" and 0 < ts < 9e9:
            ini = datetime.fromtimestamp(ts, TZ)
            if dia_op(ini) in semana and not any(f is None for _, f in dia(dia_op(ini)).turnos):
                dia(dia_op(ini)).turnos.append((ini, None))

        # Diária gravada e ajustes manuais (history-audit, tipo "DIÁRIA/VALE").
        for h in lista(api.get(f"/admin/api/finance/driver/{p.id}/history-audit", p_sem), "history"):
            if "DIARIA" not in normaliza(h.get("type", "")).upper() or not h.get("is_credit", True):
                continue
            quando = parse_dt(h.get("sort_date"), seg.year)
            if quando is None or dia_op(quando) not in semana:
                continue
            x = dia(dia_op(quando))
            if normaliza(h.get("desc", "")).startswith("diaria"):
                x.diaria_gravada = (x.diaria_gravada or 0.0) + num(h.get("value"))
            else:
                x.extras.append((h.get("desc", "ajuste"), num(h.get("value"))))

        # Pedidos entregues: Pizzaria (está no payouts ou abre no login da Pizzaria) × Sushi (404).
        resp = api.get("/admin/api/finance/drivers-report/orders",
                       {"driver_id": p.id, **p_ped, "date_basis": "delivery"})
        for o in lista(resp, "orders"):
            criado = parse_dt(o.get("date"), seg.year)
            if criado is None or dia_op(criado) not in semana or str(o.get("status", "")).upper().startswith("CANCEL"):
                continue
            oid = int(o["id"])
            loja = "pizzaria" if oid in fee_ids else None
            if loja is None:
                try:
                    api.get(f"/admin/api/orders/{oid}")
                    loja = "pizzaria"
                except AlivError as e:
                    if "404" not in str(e):
                        raise
                    loja = "sushi"
            item = {"id": oid, "codigo": o.get("wabiz_id") or f"#{oid}", "hora": criado.strftime("%H:%M"),
                    "ordem": criado, "taxa": num(o.get("taxa"))}
            x = dia(dia_op(criado))
            (x.pizzaria if loja == "pizzaria" else x.sushi_pedidos).append(item)
        for x in p.dias.values():
            x.pizzaria.sort(key=lambda i: i["ordem"])
            x.sushi_pedidos.sort(key=lambda i: i["ordem"])
            calcula_dia(x)
        p.dias = {d: x for d, x in p.dias.items() if x.turnos or x.pizzaria or x.fechamento}
        return p

    with ThreadPoolExecutor(4) as ex:
        prest = list(ex.map(um, prest))
    prest = [p for p in prest if p.dias]

    marca_duplicados(prest)
    return sorted(prest, key=lambda p: normaliza(p.nome))


def marca_duplicados(prest: list[Prestador]) -> None:
    """Cadastro duplicado: mesmo CNPJ ou mesmo nome em mais de um id (entra duas vezes)."""
    for chave in (lambda p: p.cnpj, lambda p: normaliza(p.nome)):
        grupos: dict = {}
        for p in prest:
            if chave(p):
                grupos.setdefault(chave(p), []).append(p)
        for g in grupos.values():
            if len(g) > 1:
                ids = ", ".join(str(p.id) for p in g)
                for p in g:
                    a = f"CADASTRO DUPLICADO no ALIV (ids {ids}) — entra uma vez por cadastro, conferir"
                    if a not in p.avisos:
                        p.avisos.append(a)


def calcula_dia(x: Dia) -> None:
    """Aplica as regras de pagamento do dia e registra as correções."""
    padrao = diaria_padrao(x.data)
    x.diaria = padrao
    d = f"{dm(x.data)} ({DIAS_CURTO[x.data.weekday()]})"
    taxas_grav = sum(i["taxa"] for i in x.pizzaria)
    dg = x.diaria_gravada if x.diaria_gravada is not None else padrao

    # Entregas do Sushi = diferença do fechamento ÷ R$ 2.
    if x.tem_fechamento and not x.aberto:
        bruto = (x.fechamento - dg - taxas_grav - x.extra) / POR_ENTREGA
        x.sushi = max(0, math.floor(bruto + 0.5))
        if bruto > 0 and abs(bruto - math.floor(bruto + 0.5)) > 0.01:
            x.avisos.append(f"{d}: R$ {abs(bruto - math.floor(bruto + 0.5)) * POR_ENTREGA:.2f} do fechamento sem explicação "
                            "(não fecha com entregas de R$ 2)".replace(".", ","))
        if x.sushi != len(x.sushi_pedidos):
            x.avisos.append(f"{d}: Sushi pelo fechamento = {x.sushi}; pedidos do Sushi achados no ALIV = "
                            f"{len(x.sushi_pedidos)}")
    else:
        x.sushi = len(x.sushi_pedidos)
        x.avisos.append(f"{d}: turno sem fechamento no ALIV — Sushi pelos pedidos ({x.sushi}) e total calculado")

    for i in x.pizzaria:
        if abs(i["taxa"] - POR_ENTREGA) > 0.009:
            x.correcoes.append((f"{d} {i['codigo']}: entrega gravada {brl(i['taxa'])} → {brl(POR_ENTREGA)}",
                                POR_ENTREGA - i["taxa"]))
    if x.diaria_gravada is not None and abs(x.diaria_gravada - padrao) > 0.009:
        x.correcoes.append((f"{d}: diária gravada {brl(x.diaria_gravada)} → {brl(padrao)}", padrao - x.diaria_gravada))
    elif x.diaria_gravada is None and x.turnos:
        x.avisos.append(f"{d}: diária não achada no histórico — usada a padrão {brl(padrao)}")

    x.correto = round(padrao + POR_ENTREGA * (len(x.pizzaria) + x.sushi) + x.extra, 2)
    if x.tem_fechamento:
        explicado = sum(v for _, v in x.correcoes)
        resto = round(x.correto - x.fechamento - explicado, 2)
        if resto > 0.009:
            x.correcoes.append((f"{d}: fechamento {brl(x.fechamento)} abaixo de diária + R$ 2/entrega — "
                                f"completada a diferença", resto))
        elif resto < -0.009:
            x.correcoes.append((f"{d}: fechamento {brl(x.fechamento)} acima do devido — ajustado", resto))


# ---------------------------------------------------------------- texto
def sinal(v: float) -> str:
    return ("+" if v >= 0 else "−") + brl(abs(v))


def alertas(ps: list[Prestador]) -> list[str]:
    out = []
    for p in ps:
        for x in p.dias_trab():
            if x.aberto:
                out.append(f"Turno ABERTO: {p.nome} — {dm(x.data)} ({DIAS_CURTO[x.data.weekday()]})")
            for i in x.pizzaria:
                if i["taxa"] < 0.009:
                    out.append(f"Entrega a R$ 0: {p.nome} — {dm(x.data)} {i['codigo']}")
            if x.diaria_gravada is not None and x.diaria_gravada < x.diaria - 0.009:
                out.append(f"Diária gravada {brl(x.diaria_gravada)} (menor que a padrão) corrigida para {brl(x.diaria)}: "
                           f"{p.nome} — {dm(x.data)} — confirmar")
            for desc, v in x.extras:
                out.append(f"Ajuste manual somado ao fechamento (mantido): {p.nome} — {dm(x.data)} {brl(v)} — {desc[:70]}")
        for a in p.avisos:
            if a.startswith("CADASTRO DUPLICADO"):
                ids = re.search(r"\(ids ([^)]*)\)", a)
                out.append(f"Cadastro duplicado no ALIV (ids {ids.group(1) if ids else p.id}): {p.nome} — "
                           f"entra {brl(p.total)} por este cadastro (id {p.id}), conferir")
    return out


def mensagem(seg: date, ps: list[Prestador]) -> str:
    dom = seg + timedelta(days=6)
    tot, tot_aliv = sum(p.total for p in ps), sum(p.total_aliv for p in ps)
    linhas = [f"*Tili — Prestadores (MEI) semana {dm(seg)} a {dm(dom)}*", ""]
    for p in ps:
        marca = " ⚠️" if any(a.startswith("CADASTRO") for a in p.avisos) else ""
        n = len(p.dias)
        linhas.append(f"{p.nome} — {n} dia{'s' if n != 1 else ''} — {p.pizzaria + p.sushi} entregas — {brl(p.total)}{marca}")
    linhas += ["", f"*Total da semana: {brl(tot)}* ({len(ps)} prestadores, "
                   f"{sum(len(p.dias) for p in ps)} turnos, {sum(p.pizzaria + p.sushi for p in ps)} entregas)",
               f"Fechamentos no ALIV: {brl(tot_aliv)} · correções: {sinal(tot - tot_aliv)}"]
    corr = [(p, t, v) for p in ps for t, v in p.todas_correcoes]
    if corr:
        linhas += ["", f"*Correções ({len(corr)})*"]
        linhas += [f"• {p.nome.split()[0]}: {t}" + (f" ({sinal(v)})" if abs(v) > 0.009 else "") for p, t, v in corr]
    al = alertas(ps)
    if al:
        linhas += ["", "*Alertas*", *[f"• {a}" for a in al]]
    return "\n".join(linhas)


def detalhe(ps: list[Prestador]) -> str:
    out = []
    for p in ps:
        out.append(f"- {p.nome} (id {p.id}, CNPJ {fmt_cnpj(p.cnpj)}): ALIV {brl(p.total_aliv)} → A PAGAR {brl(p.total)}")
        for x in p.dias_trab():
            t = ", ".join(f"{i:%H:%M}–{f:%H:%M}" if f else f"{i:%H:%M}–aberto" for i, f in x.turnos) or "—"
            out.append(f"    {dm(x.data)} {t} · fech {brl(x.fechamento)} · diária grav "
                       f"{brl(x.diaria_gravada) if x.diaria_gravada is not None else '—'} · Pizzaria {len(x.pizzaria)} · "
                       f"Sushi {x.sushi} (pedidos {len(x.sushi_pedidos)}) · extras {brl(x.extra)} · devido {brl(x.correto)}")
        out += [f"    ! {a}" for a in p.avisos + [a for x in p.dias_trab() for a in x.avisos]]
    return "\n".join(out)


# ---------------------------------------------------------------- PDF (mesmo layout do semanal)
CSS_P = CSS + """
.pagina.prest { padding-bottom: 14mm }
.pagina.prest .espaco { flex: 1; max-height: 80mm }
.corr { font-size: 7.3pt; line-height: 1.45; margin: .3mm 0 }
.corr .v { font-weight: bold; color: #C8102E }
table.res td { padding: 1.1mm 1.3mm; font-size: 7.6pt }
table.res th { white-space: nowrap; padding: 1.3mm }
table.res td b { white-space: nowrap }
"""


def _topo(seg: date, gerado: datetime, relatorio: str, logo: str) -> str:
    dom = seg + timedelta(days=6)
    fech = dom + timedelta(days=1)
    timbre = (f'<img class="dagua" src="{logo}">' if logo else '') + (
        f'<div class="timbre"><b>TILI</b>&nbsp;Pizza · Burguer · Sushi &nbsp;·&nbsp; {EMPRESA} · CNPJ {CNPJ_EMPRESA}'
        f' &nbsp;·&nbsp; Porto Seguro-BA &nbsp;·&nbsp; WhatsApp&nbsp;<b>(73) 99917-9941</b></div>')
    return timbre + f"""<div class="topo">{f'<img src="{logo}">' if logo else ''}
<div class="marca"><div class="nome">TILI PIZZARIA</div>
<div class="emp">{EMPRESA} · CNPJ {CNPJ_EMPRESA}</div>
<div class="rel">{relatorio}</div>
<div class="per">Período: {seg:%d/%m/%Y} ({DIAS_CURTO[0]}) a {dom:%d/%m/%Y} ({DIAS_CURTO[6]})</div></div>
<div class="dir">Fechamento: <b>segunda-feira {fech:%d/%m/%Y}</b><br>
Gerado em {gerado:%d/%m/%Y %H:%M}<br>Fonte: ALIV Hub · Turno Motoboys</div></div>"""


def _rodape() -> str:
    return (f"Diária: {brl(DIARIA_SEMANA)} (seg–sex) e {brl(DIARIA_FDS)} (sáb/dom) · Taxas: {brl(POR_ENTREGA)} por "
            f"entrega da Tili Pizzaria · Entregas Sushi: entregas feitas para a Tili Sushi &amp; Poke ({brl(POR_ENTREGA)} "
            "cada), pagas junto no fechamento do turno · Virada 00h: entregas concluídas depois da meia-noite contam no "
            "dia anterior. Total = fechamento do turno no ALIV Hub com as correções listadas. Conferência de divergências "
            "em até 48 h após o recebimento. Prestador de serviço autônomo (MEI) — sem vínculo empregatício.")


def pagina_resumo(seg: date, ps: list[Prestador], gerado: datetime, logo: str) -> str:
    tot = sum(p.total for p in ps)
    tot_aliv = sum(p.total_aliv for p in ps)
    linhas = []
    for i, p in enumerate(ps, 1):
        dias = " ".join(DIAS_CURTO[d.weekday()] for d in sorted(p.dias))
        dup = ' <span class="pq" style="color:#C8102E">duplicado</span>' if any(
            a.startswith("CADASTRO") for a in p.avisos) else ""
        linhas.append(f"""<tr><td class="cin">{i}</td><td><b>{_esc(p.nome)}</b>{dup}<div class="pq">CNPJ {fmt_cnpj(p.cnpj)}</div></td>
<td class="c">{len(p.dias)}</td><td class="cin">{dias}</td><td class="n">{p.pizzaria}</td><td class="n">{p.sushi or '—'}</td>
<td class="n"><b>{brl(p.total)}</b></td><td style="font-size:7pt">{_esc(p.pix)}</td><td class="c cin">☐</td></tr>""")
    linhas.append(f"""<tr class="tot"><td></td><td>TOTAL</td><td class="c">{sum(len(p.dias) for p in ps)}</td><td></td>
<td class="n">{sum(p.pizzaria for p in ps)}</td><td class="n">{sum(p.sushi for p in ps)}</td>
<td class="n ver">{brl(tot)}</td><td></td><td></td></tr>""")
    n_al, n_corr = len(alertas(ps)), sum(len(p.todas_correcoes) for p in ps)
    al_html = (f'<div class="av f">{n_corr} correções e {n_al} alertas nesta semana — ver a página seguinte.</div>'
               if n_al or n_corr else "")
    return f"""<div class="pagina">{_topo(seg, gerado, "Resumo · Prestadores de serviço (entregas)", logo)}
<h1>Resumo para pagamento <span class="tag">{len(ps)} PRESTADORES</span></h1>
<div class="cards"><div class="card"><div class="r">TURNOS</div><div class="v">{sum(len(p.dias) for p in ps)}</div></div>
<div class="card"><div class="r">ENTREGAS (PIZZARIA + SUSHI)</div><div class="v">{sum(p.pizzaria + p.sushi for p in ps)}</div></div>
<div class="card"><div class="r">CORREÇÕES × ALIV</div><div class="v">{sinal(tot - tot_aliv)}</div></div>
<div class="card total"><div class="r">TOTAL A PAGAR</div><div class="v">{brl(tot)}</div></div></div>
<table class="res"><tr><th>#</th><th>PRESTADOR DE SERVIÇO</th><th class="c">DIAS</th><th>DIAS TRABALHADOS</th><th class="n">ENTREGAS</th>
<th class="n">SUSHI</th><th class="n">A PAGAR</th><th>CHAVE PIX</th><th class="c">PAGO ✓</th></tr>{''.join(linhas)}</table>
<div class="nota">Valores = fechamentos de turno registrados no ALIV Hub ({brl(tot_aliv)}) com as correções da semana
(diária {brl(DIARIA_SEMANA)}/{brl(DIARIA_FDS)}, entrega sempre {brl(POR_ENTREGA)}, complemento quando o fechamento ficou abaixo).
Entregas = Pizzaria; Sushi pela diferença no fechamento. Motoboys sem turno no período não aparecem.</div>
{al_html}</div>"""


def pagina_correcoes(seg: date, ps: list[Prestador], gerado: datetime, logo: str) -> str:
    corr = [(p, t, v) for p in ps for t, v in p.todas_correcoes]
    al = alertas(ps)
    tot, tot_aliv = sum(p.total for p in ps), sum(p.total_aliv for p in ps)
    linhas = "".join(f"<tr><td><b>{_esc(p.nome)}</b></td><td>{_esc(t)}</td><td class='n'>"
                     f"{sinal(v) if abs(v) > 0.009 else '—'}</td></tr>" for p, t, v in corr)
    return f"""<div class="pagina">{_topo(seg, gerado, "Correções e alertas · Prestadores de serviço", logo)}
<h1>Correções e alertas da semana</h1>
<div class="sub">Fechamentos no ALIV <b>{brl(tot_aliv)}</b> → total a pagar <b>{brl(tot)}</b> ({sinal(tot - tot_aliv)})</div>
<div class="sec">ALERTAS ({len(al)})</div>{''.join(f'<div class="av f">{_esc(a)}</div>' for a in al) or '<div class="cin">nenhum</div>'}
<div class="sec" style="margin-top:3mm">CORREÇÕES ({len(corr)})</div>
<table class="res"><tr><th>PRESTADOR</th><th>CORREÇÃO</th><th class="n">VALOR</th></tr>{linhas}</table></div>"""


def pagina_prestador(seg: date, p: Prestador, gerado: datetime, logo: str) -> str:
    dom = seg + timedelta(days=6)
    linhas = ""
    for x in p.dias_trab():
        turno = "<br>".join(f"{i:%H:%M} – {f:%H:%M}" if f else f"{i:%H:%M} – em aberto" for i, f in x.turnos) or "—"
        sushi = f"{x.sushi} <span class='cin'>({brl(x.sushi * POR_ENTREGA)})</span>" if x.sushi else "—"
        extra = f"<div class='pq'>+ ajuste {brl(x.extra)}</div>" if x.extra else ""
        linhas += f"""<tr><td><b>{dm(x.data)}</b> <span class="cin">{DIAS_CURTO[x.data.weekday()]}</span></td>
<td class="cin">{turno}</td><td class="n">{len(x.pizzaria)}</td><td class="n">{brl(x.diaria)}</td>
<td class="n">{brl(len(x.pizzaria) * POR_ENTREGA)}</td><td class="n">{sushi}</td><td class="n"><b>{brl(x.correto)}</b>{extra}</td></tr>"""
    linhas += f"""<tr class="tot"><td>TOTAL</td><td></td><td class="n">{p.pizzaria}</td>
<td class="n">{brl(sum(x.diaria for x in p.dias.values()))}</td><td class="n">{brl(p.pizzaria * POR_ENTREGA)}</td>
<td class="n">{p.sushi} <span class="cin">({brl(p.sushi * POR_ENTREGA)})</span></td><td class="n ver">{brl(p.total)}</td></tr>"""
    corr = p.todas_correcoes
    corr_html = ""
    if corr:
        corr_html = (f'<div class="sec" style="margin-top:3mm">CORREÇÕES (ALIV {brl(p.total_aliv)} → {brl(p.total)})</div>' +
                     "".join(f'<div class="corr">• {_esc(t)}' + (f' <span class="v">{sinal(v)}</span>' if abs(v) > 0.009 else "")
                             + "</div>" for t, v in corr))
    avisos = "".join(f'<div class="av{" f" if a.startswith("CADASTRO") else ""}">{_esc(a)}</div>'
                     for a in p.avisos + [a for x in p.dias_trab() for a in x.avisos if "turno sem fechamento" in a
                                          or "sem explicação" in a])
    codigos = ""
    for x in p.dias_trab():
        cods = ", ".join(_esc(i["codigo"]) for i in x.pizzaria) or "—"
        sus = (f" · <b>Sushi:</b> <code>{', '.join(_esc(i['codigo']) for i in x.sushi_pedidos)}</code>"
               if x.sushi_pedidos else "")
        codigos += (f'<div class="cod"><b>{dm(x.data)} ({DIAS_CURTO[x.data.weekday()]}) · {len(x.pizzaria)} entregas:</b> '
                    f'<code>{cods}</code>{sus}</div>')
    pix_rot = "CNPJ" if re.sub(r"\D", "", p.pix) == p.cnpj else ("e-mail" if "@" in p.pix else "chave")
    return f"""<div class="pagina prest">{_topo(seg, gerado, "Relatório semanal de entregas · Prestador de serviço", logo)}
<h1>{_esc(p.nome)} <span class="tag">PRESTADOR DE SERVIÇO</span></h1>
<div class="sub">CNPJ {fmt_cnpj(p.cnpj)} · Chave Pix ({pix_rot}): <b>{_esc(p.pix)}</b></div>
<div class="cards"><div class="card"><div class="r">DIAS TRABALHADOS</div><div class="v">{len(p.dias)}</div></div>
<div class="card"><div class="r">ENTREGAS NO PERÍODO</div><div class="v">{p.pizzaria}</div></div>
<div class="card"><div class="r">ENTREGAS SUSHI</div><div class="v">{p.sushi}</div></div>
<div class="card total"><div class="r">TOTAL A PAGAR</div><div class="v">{brl(p.total)}</div></div></div>
<div class="sec">TURNOS DO PERÍODO</div>
<table><tr><th>DATA</th><th>TURNO</th><th class="n">ENTREGAS</th><th class="n">DIÁRIA</th><th class="n">TAXAS R$ 2</th>
<th class="n">ENTREGAS SUSHI</th><th class="n">TOTAL DO DIA</th></tr>{linhas}</table>
{avisos}{corr_html}
<div class="sec" style="margin-top:3mm">ENTREGAS REALIZADAS (CÓDIGO DO PEDIDO)</div>{codigos}
<div class="espaco"></div>
<div class="recibo"><div class="t">RECIBO DE PRESTAÇÃO DE SERVIÇOS DE ENTREGA</div>
<span class="g">{_esc(p.nome)}</span> — CNPJ {fmt_cnpj(p.cnpj)} declara ter recebido de <span class="g">{EMPRESA}</span>
(Tili Pizzaria), CNPJ <span class="g">{CNPJ_EMPRESA}</span> a importância de <span class="g">{brl(p.total)}</span> referente
aos serviços de entrega prestados no período de {dm(seg)} a {dom:%d/%m/%Y}, conforme discriminado acima.
<div class="linha">Pagamento via <b>Pix</b> — chave {pix_rot}: <span class="g">{_esc(p.pix)}</span> &nbsp;·&nbsp; Pago em ____/____/______</div>
<div class="linha" style="font-size:7pt;color:#555">Prestação de serviço autônomo (MEI), sem vínculo empregatício.</div></div>
<div class="ass"><div>Assinatura do prestador de serviço</div><div>Tili Pizzaria — responsável</div></div>
<div class="rod">{_rodape()}</div></div>"""


def _doc(titulo: str, paginas: list[str]) -> str:
    return (f'<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><title>{_esc(titulo)}</title>'
            f'<style>{CSS_P}</style></head><body>{"".join(paginas)}</body></html>')


def gerar_pdfs(seg: date, ps: list[Prestador], pasta: Path, gerado: datetime) -> tuple[Path, list[Path]]:
    logo = _logo_src()
    dom = seg + timedelta(days=6)
    nome = f"Prestadores_semana_{seg:%d-%m}_a_{dom:%d-%m}"
    paginas = {p.id: pagina_prestador(seg, p, gerado, logo) for p in ps}
    completo = html_para_pdf(_doc(nome, [pagina_resumo(seg, ps, gerado, logo), pagina_correcoes(seg, ps, gerado, logo),
                                         *paginas.values()]),
                             pasta / f"{nome}_COMPLETO.pdf")
    ind_dir = pasta / "individuais"
    ind_dir.mkdir(parents=True, exist_ok=True)
    for f in ind_dir.glob("*.pdf"):
        f.unlink()
    indiv = []
    for p in ps:
        arq = re.sub(r"[^A-Za-z0-9]+", "_", normaliza(p.nome).title()).strip("_")
        if sum(1 for q in ps if normaliza(q.nome) == normaliza(p.nome)) > 1:
            arq += f"_id{p.id}"
        indiv.append(html_para_pdf(_doc(p.nome, [paginas[p.id]]), ind_dir / f"{arq}_{seg:%d-%m}_a_{dom:%d-%m}.pdf"))
    return completo, indiv


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Relatório semanal dos prestadores MEI (ALIV, só leitura)")
    ap.add_argument("--semana", help="qualquer data da semana (AAAA-MM-DD); padrão: a semana seg–dom que fechou")
    ap.add_argument("--dry-run", action="store_true", help="gera PDFs e mensagem, mas não envia nada")
    ap.add_argument("--sem-espera", action="store_true", help="não espera 10 min se o turno de domingo estiver aberto")
    ap.add_argument("--raw", metavar="PASTA", help="salva as respostas cruas do ALIV (diagnóstico)")
    args = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: defina ALIV_USER e ALIV_PASS nas variáveis de ambiente.", file=sys.stderr)
        return 2
    agora = datetime.now(TZ).replace(second=0, microsecond=0)
    seg = semana_de(date.fromisoformat(args.semana)) if args.semana else semana_fechada(agora)
    dom = seg + timedelta(days=6)
    api = Aliv(user, pwd, raw_dir=Path(args.raw) if args.raw else None)

    try:
        api.login()
        ps = coletar(api, seg, agora)
        domingo_aberto = [p for p in ps if dom in p.dias and p.dias[dom].aberto]
        if domingo_aberto and not args.sem_espera:
            print(f"Turno de domingo aberto ({', '.join(p.nome for p in domingo_aberto)}): "
                  f"esperando {ESPERA_DOMINGO_S // 60} min…", file=sys.stderr)
            time.sleep(ESPERA_DOMINGO_S)
            ps = coletar(api, seg, datetime.now(TZ))
    except (AlivError, OSError) as e:
        print(f"Tili Prestadores {dm(seg)} a {dm(dom)} — ERRO no ALIV\n\n{e}")
        return 1

    if not ps:
        texto = f"*Tili — Prestadores (MEI) semana {dm(seg)} a {dm(dom)}*\n\nNenhum prestador trabalhou na semana."
        print(f"Tili Prestadores {dm(seg)} a {dm(dom)} — sem prestadores\n\n{texto}")
        return 0 if args.dry_run else (3 if enviar(api, texto, None) else 0)

    pasta = PASTA / f"{seg}"
    pasta.mkdir(parents=True, exist_ok=True)
    completo, indiv = gerar_pdfs(seg, ps, pasta, datetime.now(TZ))
    texto = mensagem(seg, ps)
    print(f"Tili Prestadores {dm(seg)} a {dm(dom)} — {len(ps)} prestadores — {brl(sum(p.total for p in ps))}\n")
    print(texto)
    print("\nDETALHE\n" + detalhe(ps))
    print(f"\nPDF: {completo.relative_to(BASE.parent)}")
    print(f"PDFs individuais: {len(indiv)} em {(pasta / 'individuais').relative_to(BASE.parent)}")
    if args.dry_run:
        print("\nDRY-RUN: nada enviado.", file=sys.stderr)
        return 0
    falhas = enviar(api, texto, completo, legenda=f"Prestadores semana {dm(seg)} a {dm(dom)} — PDF completo")
    for f in falhas:
        print(f"WHATSAPP: {f}", file=sys.stderr)
    return 3 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
