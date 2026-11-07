#!/usr/bin/env python3
"""Relatório diário dos motoboys DIARISTAS da Tili — só leitura no ALIV.

Para o dia operacional D (turnos iniciados entre 10:00 de D e 10:00 de D+1,
incluindo as entregas da virada), lista os diaristas (motoboys sem "CNPJ" no
nome, fora os logins de gerente), com entrada/saída do turno, entregas da
Pizzaria e do Sushi, diária gravada, fechamento do turno no ALIV e cálculo
(diária + R$ 2 por entrega). Gera:

  monitor/diaristas/AAAA-MM-DD/diaristas_DD-MM.pdf   (resumo + 1 página por motoboy com recibo,
  no mesmo layout do relatório semanal dos prestadores: HTML impresso pelo Chromium headless)
  lista em texto "nome — entregas — valor" (sai no stdout e vai no WhatsApp)

Reaproveita o login e o envio por WhatsApp do monitor.py. O commit do PDF fica
a cargo da Rotina (ver README).

Uso:
  python3 monitor/diaristas.py                    # dia operacional que acabou de fechar
  python3 monitor/diaristas.py --data 2026-11-06  # dia específico
  python3 monitor/diaristas.py --data 2026-11-06 --dry-run   # não envia nada

Códigos de saída:
  0 ok (enviado; ou dry-run; ou dia sem diarista, com aviso)
  1 erro de login/ALIV (o motivo sai no stdout; a Rotina manda e-mail de erro)
  2 faltam variáveis ALIV_USER / ALIV_PASS
  3 relatório gerado, mas o WhatsApp não aceitou o PDF ou a lista
    (a Rotina manda a lista e o PDF por e-mail)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import Aliv, AlivError, TZ, brl, num, parse_dt  # noqa: E402

PASTA = Path(__file__).resolve().parent / "diaristas"

# ---------------------------------------------------------------- parâmetros
INICIO_DIA_H = 10            # dia operacional D: turnos iniciados de 10:00 de D...
FIM_DIA_H = 10               # ...até 10:00 de D+1 (ou a hora da rodada, se antes)
PEDIDO_ATE_H = 8             # pedidos criados até 08:00 de D+1 ainda são do dia D (turno 16h–08h)
DIARIA_SEMANA = 100.0        # seg a sex
DIARIA_FDS = 120.0           # sáb e dom
POR_ENTREGA_PIZZARIA = 2.0
POR_ENTREGA_SUSHI = 2.0
GERENTES = {"thiago camilo", "josue ruas"}   # logins de gerente: nunca entram
RE_CNPJ = re.compile(r"\bCNPJ\b", re.I)

VERMELHO, DOURADO, PRETO = "#C8102E", "#D4A017", "#1A1A1A"
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


# ---------------------------------------------------------------- modelo
@dataclass
class Turno:
    inicio: datetime | None
    fim: datetime | None
    fechamento: float | None          # soma dos pagamentos do turno (payouts)
    aberto: bool = False
    pagamentos: list = field(default_factory=list)


@dataclass
class Diarista:
    id: int
    nome: str
    turnos: list[Turno] = field(default_factory=list)
    pizzaria: list[dict] = field(default_factory=list)   # {id, codigo, hora}
    sushi: list[dict] = field(default_factory=list)
    diaria_gravada: float | None = None
    diaria: float = 0.0
    corrigida: bool = False
    fechamento: float | None = None
    avisos: list[str] = field(default_factory=list)

    @property
    def entregas(self) -> int:
        return len(self.pizzaria) + len(self.sushi)

    @property
    def taxas(self) -> float:
        return len(self.pizzaria) * POR_ENTREGA_PIZZARIA + len(self.sushi) * POR_ENTREGA_SUSHI

    @property
    def calculado(self) -> float:
        return self.diaria + self.taxas

    @property
    def total(self) -> float:
        """Total a pagar = diária + R$ 2 por entrega (Pizzaria e Sushi). O fechamento do ALIV é só conferência."""
        return self.calculado

    @property
    def divergente(self) -> bool:
        return self.fechamento is not None and abs(self.fechamento - self.calculado) > 0.009


# ---------------------------------------------------------------- utilidades
def normaliza(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def eh_diarista(nome: str) -> bool:
    return bool(nome) and not RE_CNPJ.search(nome) and normaliza(nome) not in GERENTES


def diaria_padrao(dia: date) -> float:
    return DIARIA_FDS if dia.weekday() >= 5 else DIARIA_SEMANA


def dia_operacional(agora: datetime) -> date:
    """Antes das 10:00 o relatório é do dia anterior (rodada das 00:15 ou atrasada)."""
    return (agora - timedelta(days=1)).date() if agora.hour < INICIO_DIA_H else agora.date()


def janela(dia: date, agora: datetime) -> tuple[datetime, datetime]:
    ini = datetime.combine(dia, dtime(INICIO_DIA_H), TZ)
    fim = datetime.combine(dia + timedelta(days=1), dtime(FIM_DIA_H), TZ)
    return ini, min(fim, agora)


def lista(resp, *chaves) -> list:
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in chaves:
            if isinstance(resp.get(k), list):
                return resp[k]
    return []


def dm(d: date) -> str:
    return f"{d:%d/%m}"


# ---------------------------------------------------------------- coleta
def coletar(api: Aliv, dia: date, agora: datetime) -> list[Diarista]:
    ini, fim = janela(dia, agora)
    p_dia = {"start": f"{dia}", "end": f"{dia + timedelta(days=1)}"}
    p_2dias = {"start": f"{dia}", "end": f"{dia + timedelta(days=2)}"}

    # Candidatos: todos os motoboys do drivers-live + quem aparece no relatório do dia.
    live = {int(d["id"]): d for d in lista(api.get("/admin/api/finance/drivers-live"), "drivers", "data")
            if isinstance(d, dict) and d.get("id") is not None}
    rel = api.get("/admin/api/finance/drivers-report",
                  {**p_dia, "tipo": "entrega,financeiro", "date_basis": "delivery"})
    nomes = {i: d.get("name", "") for i, d in live.items()}
    for r in lista(rel, "rows"):
        if r.get("id") is not None:
            nomes.setdefault(int(r["id"]), r.get("name", ""))
    candidatos = {i: n for i, n in nomes.items() if eh_diarista(n)}

    def turnos_de(did: int) -> tuple[int, list[Turno], dict]:
        resp = api.get(f"/admin/api/finance/driver/{did}/payouts", p_dia)
        turnos, fee_ids = [], {}
        for g in lista(resp, "groups"):
            t_ini = parse_dt(g.get("session_start"), dia.year)
            if t_ini is None or not (ini <= t_ini < fim):
                continue
            t_fim = parse_dt(g.get("session_end"), dia.year)
            if t_fim and t_ini and t_fim < t_ini:          # virada de ano em "dd/mm"
                t_fim = t_fim.replace(year=t_fim.year + 1)
            pags = lista(g, "payments")
            turnos.append(Turno(t_ini, t_fim, num(g.get("total_paid")) if pags else None,
                                aberto=t_fim is None, pagamentos=pags))
            for e in lista(g, "deliveries"):
                if e.get("order_id") is not None:
                    fee_ids[int(e["order_id"])] = e
        return did, turnos, fee_ids

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(turnos_de, candidatos))

    diaristas = []
    for did, turnos, fee_ids in res:
        d = live.get(did, {})
        ts = num(d.get("start_ts"))
        online = str(d.get("status", "")).lower() == "online" and 0 < ts < 9e9
        t_live = datetime.fromtimestamp(ts, TZ) if online else None
        if online and ini <= t_live < fim and not any(t.aberto for t in turnos):
            turnos.append(Turno(t_live, None, num(d.get("final_pay")) or None, aberto=True))
        x = Diarista(did, candidatos[did].strip(), sorted(turnos, key=lambda t: t.inicio))
        x._fee_ids = fee_ids  # type: ignore[attr-defined]
        diaristas.append(x)

    # Pedidos entregues (Pizzaria + Sushi) e classificação por loja.
    lim_pedido = datetime.combine(dia + timedelta(days=1), dtime(PEDIDO_ATE_H), TZ)

    def pedidos_de(x: Diarista) -> Diarista:
        resp = api.get("/admin/api/finance/drivers-report/orders",
                       {"driver_id": x.id, **p_2dias, "date_basis": "delivery"})
        for o in lista(resp, "orders"):
            criado = parse_dt(o.get("date"), dia.year)
            if criado is None or not (ini <= criado < lim_pedido):
                continue
            if str(o.get("status", "")).upper().startswith("CANCEL"):
                continue
            oid = int(o["id"])
            codigo = o.get("wabiz_id") or o.get("code")
            loja = "pizzaria" if oid in x._fee_ids else None  # type: ignore[attr-defined]
            if loja is None or not codigo:
                try:
                    det = api.get(f"/admin/api/orders/{oid}")
                    det = det.get("order", det) if isinstance(det, dict) else {}
                    loja, codigo = "pizzaria", codigo or det.get("wabiz_id")
                except AlivError as e:
                    if "404" not in str(e):
                        raise
                    loja = "sushi"        # o login da Pizzaria não enxerga pedido do Sushi
            item = {"id": oid, "codigo": codigo or f"#{oid}", "hora": criado.strftime("%H:%M")}
            (x.pizzaria if loja == "pizzaria" else x.sushi).append(item)
        return x

    # Só busca pedidos de quem trabalhou: tem turno no dia ou aparece no relatório.
    no_rel = {int(r["id"]) for r in lista(rel, "rows") if r.get("id") is not None}
    diaristas = [x for x in diaristas if x.turnos or x.id in no_rel]
    with ThreadPoolExecutor(6) as ex:
        diaristas = list(ex.map(pedidos_de, diaristas))
    diaristas = [x for x in diaristas if x.turnos or x.entregas]

    # Diária gravada (history-audit: tipo "DIÁRIA/...", descrição com "diária").
    for x in diaristas:
        hist = lista(api.get(f"/admin/api/finance/driver/{x.id}/history-audit", p_dia), "history")
        t0 = (x.turnos[0].inicio if x.turnos else ini) - timedelta(hours=1)
        fins = [t.fim for t in x.turnos if t.fim]
        t1 = (max(fins) + timedelta(hours=3)) if fins and not any(t.aberto for t in x.turnos) \
            else datetime.combine(dia + timedelta(days=1), dtime(FIM_DIA_H), TZ)
        valores = []
        for h in hist:
            if "DIARIA" not in normaliza(h.get("type", "")).upper() or "diaria" not in normaliza(h.get("desc", "")):
                continue
            quando = parse_dt(h.get("sort_date"), dia.year)
            if quando and t0 <= quando <= t1 and h.get("is_credit", True):
                valores.append(num(h.get("value")))
        x.diaria_gravada = sum(valores) if valores else None
        aplicar_regras(x, dia)
    return sorted(diaristas, key=lambda x: normaliza(x.nome))


def aplicar_regras(x: Diarista, dia: date) -> None:
    """Diária = a gravada no ALIV, acatada como está (ex.: R$ 50 combinado por atraso). Só quando vier zerada
    ou não gravada e o motoboy tiver feito entregas, usa a padrão (R$ 100 seg–sex, R$ 120 sáb–dom).
    Entrega = R$ 2 cada. Os avisos ficam só na conferência (mensagem/terminal), nunca no PDF do motoboy."""
    padrao = diaria_padrao(dia)
    if (x.diaria_gravada or 0.0) > 0.009:
        x.diaria = x.diaria_gravada
    elif x.entregas:
        x.diaria, x.corrigida = padrao, True
        x.avisos.append(f"CORRIGIDO: diária {'zerada' if x.diaria_gravada is not None else 'não gravada'} no ALIV "
                        f"com {x.entregas} entregas → {brl(padrao)}")
    else:
        x.diaria = 0.0
    fech = [t.fechamento for t in x.turnos if t.fechamento is not None]
    x.fechamento = sum(fech) if fech else None
    if any(t.aberto for t in x.turnos):
        x.avisos.append("turno ainda aberto no ALIV na hora da rodada — pago pelo cálculo")
    if not x.turnos:
        x.avisos.append("turno não encontrado no ALIV (só entregas)")
    if x.divergente:
        x.avisos.append(f"DIVERGÊNCIA: fechamento ALIV {brl(x.fechamento)} × pago {brl(x.total)}")


# ---------------------------------------------------------------- saída texto
def lista_whatsapp(dia: date, ds: list[Diarista]) -> str:
    linhas = [f"*Tili — Diaristas {dm(dia)} ({DIAS_SEMANA[dia.weekday()]})*", ""]
    for x in ds:
        marca = " ⚠️" if x.divergente or x.corrigida else ""
        linhas.append(f"{x.nome} — {x.entregas} entregas — {brl(x.total)}{marca}")
    linhas += ["", f"*Total: {brl(sum(x.total for x in ds))}* ({len(ds)} diarista"
               f"{'s' if len(ds) != 1 else ''}, {sum(x.entregas for x in ds)} entregas)"]
    avisos = [f"• {x.nome.split()[0]}: {a}" for x in ds for a in x.avisos
              if a.startswith(("CORRIGIDO", "DIVERGÊNCIA"))]
    if avisos:
        linhas += ["", *avisos]
    return "\n".join(linhas)


def resumo_texto(dia: date, ds: list[Diarista]) -> str:
    out = []
    for x in ds:
        turnos = "; ".join(f"{fmt_h(t.inicio)}–{fmt_h(t.fim) if t.fim else 'aberto'}" for t in x.turnos) or "—"
        out.append(f"- {x.nome}: turno {turnos} · Pizzaria {len(x.pizzaria)} · Sushi {len(x.sushi)} · "
                   f"diária {brl(x.diaria)} (gravada {brl(x.diaria_gravada) if x.diaria_gravada is not None else '—'}) · "
                   f"cálculo {brl(x.calculado)} · fechamento ALIV "
                   f"{brl(x.fechamento) if x.fechamento is not None else '—'} · A PAGAR {brl(x.total)}")
        out += [f"    ! {a}" for a in x.avisos]
    return "\n".join(out)


def fmt_h(d: datetime | None) -> str:
    return d.strftime("%d/%m %H:%M") if d else "—"


# ---------------------------------------------------------------- PDF
# Mesmo layout do relatório semanal dos prestadores: HTML impresso pelo Chromium headless.
EMPRESA = "SO DELIVERY PIZZARIA E RESTAURANTE LTDA"
CNPJ_EMPRESA = "53.032.203/0002-07"
LOGO = Path(__file__).resolve().parent / "assets" / "logo_tili.png"
DIAS_CURTO = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
CHROME = [os.environ.get("DIARISTAS_CHROME", ""),   # headless-shell primeiro: o Chrome completo trava no --headless
          *sorted(map(str, Path("/opt/pw-browsers").glob("chromium_headless_shell-*/*/chrome-headless-shell")),
                  reverse=True),
          "chrome-headless-shell", "/opt/pw-browsers/chromium", "google-chrome", "chromium"]

CSS = """
@page { size: A4; margin: 0 }
* { box-sizing: border-box; margin: 0; padding: 0 }
body { font-family: "Liberation Sans", Arial, Helvetica, sans-serif; color: #1A1A1A; font-size: 9.5pt;
       -webkit-print-color-adjust: exact; print-color-adjust: exact }
.pagina { width: 210mm; height: 297mm; padding: 13mm 14mm 10mm; display: flex; flex-direction: column;
          page-break-after: always; overflow: hidden }
.pagina:last-child { page-break-after: auto }
.pagina { padding-bottom: 14mm }
.pagina.mot { padding-bottom: 62mm }
/* papel timbrado: marca d'água + faixa da marca no rodapé de todas as páginas */
.pagina { position: relative }
.pagina > * { position: relative; z-index: 1 }
.pagina > .dagua { position: absolute; z-index: 0; left: 50%; top: 52%; width: 120mm; height: 120mm;
                   transform: translate(-50%, -50%); object-fit: contain; opacity: .06 }
.pagina > .timbre { position: absolute; z-index: 1; left: 0; right: 0; bottom: 0; height: 9mm; background: #1A1A1A;
                    color: #fff; font-size: 6.8pt; display: flex; align-items: center; justify-content: center;
                    gap: 3mm; letter-spacing: .3px; border-top: 1.4mm solid #C8102E }
.pagina > .timbre::before { content: ""; position: absolute; left: 0; right: 0; top: -2.2mm; height: .8mm; background: #D4A017 }
.pagina > .timbre b { color: #D4A017 }
   /* recibo na mesma altura do relatório semanal */
.topo { display: flex; align-items: center; gap: 3mm; padding-bottom: 3mm; border-bottom: 2px solid #C8102E }
.topo img { width: 16mm; height: 16mm; object-fit: contain; mix-blend-mode: multiply }
.topo .marca { flex: 1; line-height: 1.25 }
.topo .nome { color: #C8102E; font-weight: bold; font-size: 15pt; line-height: 1.05 }
.topo .emp { font-weight: bold; font-size: 7.5pt }
.topo .rel { font-weight: bold; font-size: 8.5pt; color: #333 }
.topo .per { font-size: 7.5pt; color: #777 }
.topo .dir { text-align: right; font-size: 7.5pt; color: #777; line-height: 1.35 }
.topo .dir b { color: #1A1A1A }
h1 { font-size: 13.5pt; margin: 4mm 0 1mm; display: flex; align-items: center; gap: 2.5mm }
.tag { background: #1A1A1A; color: #fff; font-size: 6.8pt; font-weight: normal; letter-spacing: .6px;
       padding: .6mm 2mm; border-radius: 1.2mm }
.tag.ouro { background: #D4A017; color: #1A1A1A }
.sub { font-size: 7.5pt; color: #777; margin-bottom: 2.5mm }
.sub b { color: #333 }
.cards { display: flex; gap: 2mm; margin: 1mm 0 3mm }
.card { flex: 1; border: 1px solid #ddd; border-radius: 2mm; padding: 2mm 2.5mm; background: #fafafa }
.card .r { font-size: 6.5pt; color: #777; letter-spacing: .4px }
.card .v { font-size: 13pt; font-weight: bold; margin-top: .5mm }
.card.total { background: #C8102E; border-color: #C8102E; color: #fff }
.card.total .r { color: #fde }
.sec { color: #C8102E; font-weight: bold; font-size: 7.5pt; letter-spacing: .3px; margin: 2mm 0 1mm;
       padding-bottom: .8mm; border-bottom: 1px solid #ddd }
table { width: 100%; border-collapse: collapse; font-size: 8pt }
th { background: #1A1A1A; color: #fff; font-size: 7pt; letter-spacing: .4px; text-align: left; padding: 1.5mm 1.5mm }
td { padding: 1.6mm 1.5mm; border-bottom: 1px solid #e6e6e6; vertical-align: top }
.n { text-align: right; white-space: nowrap }
.c { text-align: center }
.cin { color: #888 }
.pq { font-size: 6.5pt; color: #888 }
tr.tot td { border-top: 2px solid #1A1A1A; border-bottom: none; font-weight: bold; background: #f3f3f3 }
tr.tot td.ver { color: #C8102E }
td b { font-weight: bold }
.nota { font-size: 6.5pt; color: #888; margin-top: 2mm; line-height: 1.35 }
.av { font-size: 7.5pt; margin: 1mm 0; padding: 1.5mm 2mm; border-left: 3px solid #D4A017; background: #fff8e5 }
.av.f { border-color: #C8102E; background: #fdecee; color: #8a0c20; font-weight: bold }
.cod { font-size: 7pt; line-height: 1.45; margin-bottom: 1mm }
.cod b { font-size: 7pt }
.cod code { font-family: "Liberation Mono", "Courier New", monospace; font-size: 6.6pt; color: #555 }
.espaco { flex: 1 }
.recibo { border: 1px dashed #999; border-radius: 2mm; padding: 2.5mm 3mm; font-size: 7.5pt; line-height: 1.4 }
.recibo .t { font-weight: bold; font-size: 7.5pt; margin-bottom: .8mm }
.recibo .g { font-weight: bold; font-size: 9.5pt }
.recibo .linha { margin-top: 1.5mm }
.ass { display: flex; gap: 6mm; margin-top: 9mm }
.ass div { flex: 1; border-top: 1px solid #1A1A1A; text-align: center; font-size: 7pt; color: #555; padding-top: 1mm }
.rod { font-size: 6pt; color: #888; margin-top: 2mm; line-height: 1.4 }
"""


def _esc(s) -> str:
    import html
    return html.escape(str(s))


def _logo_src() -> str:
    import base64
    leve = LOGO.with_suffix(".jpg")          # versão JPEG leve para o PDF (a PNG fica como original)
    if leve.exists():
        return "data:image/jpeg;base64," + base64.b64encode(leve.read_bytes()).decode()
    return "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode() if LOGO.exists() else ""


def _ordem(p: dict) -> str:
    return p["hora"] if p["hora"] >= "06:00" else "z" + p["hora"]    # virada vai para o fim


def _turno_txt(x: Diarista) -> str:
    return "<br>".join(f"{t.inicio:%H:%M} – {t.fim:%H:%M}" if t.fim else f"{t.inicio:%H:%M} – em aberto"
                       for t in x.turnos) or "—"


def html_relatorio(dia: date, ds: list[Diarista], gerado: datetime) -> str:
    logo = _logo_src()
    dia_txt = f"{dia:%d/%m/%Y} ({DIAS_CURTO[dia.weekday()]})"

    timbre = (f'<img class="dagua" src="{logo}">' if logo else '') + (
        f'<div class="timbre"><b>TILI</b>&nbsp;Pizza · Burguer · Sushi &nbsp;·&nbsp; {EMPRESA} · CNPJ {CNPJ_EMPRESA}'
        f' &nbsp;·&nbsp; Porto Seguro-BA &nbsp;·&nbsp; WhatsApp&nbsp;<b>(73) 99917-9941</b></div>')

    def topo(relatorio: str) -> str:
        return timbre + f"""<div class="topo">{f'<img src="{logo}">' if logo else ''}
<div class="marca"><div class="nome">TILI PIZZARIA</div>
<div class="emp">{EMPRESA} · CNPJ {CNPJ_EMPRESA} · Porto Seguro-BA</div>
<div class="rel">{relatorio}</div><div class="per">Dia operacional: {dia_txt}</div></div>
<div class="dir">Fechamento: <b>{DIAS_SEMANA[(dia + timedelta(days=1)).weekday()]}-feira {dia + timedelta(days=1):%d/%m/%Y}</b><br>
Gerado em {gerado:%d/%m/%Y %H:%M}<br>Fonte: ALIV Hub · Turno Motoboys</div></div>""".replace(
            "sábado-feira", "sábado").replace("domingo-feira", "domingo")

    rodape = (f"Diária: {brl(DIARIA_SEMANA)} (seg–sex) e {brl(DIARIA_FDS)} (sáb/dom) · Taxas: "
              f"{brl(POR_ENTREGA_PIZZARIA)} por entrega da Tili Pizzaria · Entregas Sushi: entregas feitas para a "
              f"Tili Sushi &amp; Poke ({brl(POR_ENTREGA_SUSHI)} cada), pagas junto no fechamento do turno · "
              "Virada 00h: entregas concluídas depois da meia-noite contam no dia operacional anterior. "
              "Total = diária + R$ 2,00 por entrega. Conferência de divergências em até 48 h após o recebimento.")

    # ---- página 1: resumo
    linhas = []
    for i, x in enumerate(ds, 1):
        marca = aviso = ""
        linhas.append(f"""<tr><td class="cin">{i}</td><td><b>{_esc(x.nome)}</b><div class="pq">Motoboy diarista</div></td>
<td class="cin">{_turno_txt(x)}</td><td class="n">{len(x.pizzaria)}</td>
<td class="n">{len(x.sushi) or '—'}</td><td class="n">{brl(x.diaria)}{marca}</td>
<td class="n"><b>{brl(x.total)}</b>{aviso}</td><td class="c cin">( ) Pix &nbsp;( ) Din.</td></tr>""")
    tot = sum(x.total for x in ds)
    linhas.append(f"""<tr class="tot"><td></td><td>TOTAL</td><td></td><td class="n">{sum(len(x.pizzaria) for x in ds)}</td>
<td class="n">{sum(len(x.sushi) for x in ds)}</td><td class="n">{brl(sum(x.diaria for x in ds))}</td>
<td class="n ver">{brl(tot)}</td><td></td></tr>""")
    avisos = "".join(f'<div class="av{" f" if a.startswith(("CORRIGIDO", "DIVERG")) else ""}"><b>{_esc(x.nome)}</b>: {_esc(a)}</div>'
                     for x in ds for a in x.avisos)
    paginas = [f"""<div class="pagina">{topo("Resumo · Motoboys diaristas (entregas)")}
<h1>Resumo para pagamento <span class="tag">{len(ds)} DIARISTA{'S' if len(ds) != 1 else ''}</span></h1>
<div class="cards"><div class="card"><div class="r">DIARISTAS</div><div class="v">{len(ds)}</div></div>
<div class="card"><div class="r">ENTREGAS PIZZARIA</div><div class="v">{sum(len(x.pizzaria) for x in ds)}</div></div>
<div class="card"><div class="r">ENTREGAS SUSHI</div><div class="v">{sum(len(x.sushi) for x in ds)}</div></div>
<div class="card total"><div class="r">TOTAL A PAGAR</div><div class="v">{brl(tot)}</div></div></div>
<table><tr><th>#</th><th>MOTOBOY DIARISTA</th><th>TURNO</th><th class="n">PIZZARIA</th><th class="n">SUSHI</th>
<th class="n">DIÁRIA</th><th class="n">A PAGAR</th><th class="c">PAGO ✓</th></tr>{''.join(linhas)}</table>
<div class="nota">Valores = diária do turno + {brl(POR_ENTREGA_PIZZARIA)} por entrega da pizzaria
+ {brl(POR_ENTREGA_SUSHI)} por entrega do sushi. Diaristas = motoboys sem CNPJ; prestadores com CNPJ ficam no relatório semanal.
Motoboys sem turno no dia não aparecem.</div>
</div>"""]

    # ---- uma página por diarista
    for x in ds:
        turno = "; ".join(f"{fmt_h(t.inicio)} – {fmt_h(t.fim) if t.fim else 'em aberto'}" for t in x.turnos) or "não encontrado"
        sushi_txt = f"{len(x.sushi)} <span class='cin'>({brl(len(x.sushi) * POR_ENTREGA_SUSHI)})</span>" if x.sushi else "—"
        diaria_txt = brl(x.diaria)
        linhas = f"""<tr><td><b>{dia:%d/%m}</b> <span class="cin">{DIAS_CURTO[dia.weekday()]}</span></td>
<td class="cin">{_turno_txt(x)}</td><td class="n">{len(x.pizzaria)}</td><td class="n">{diaria_txt}</td>
<td class="n">{brl(len(x.pizzaria) * POR_ENTREGA_PIZZARIA)}</td><td class="n">{sushi_txt}</td>
<td class="n"><b>{brl(x.calculado)}</b></td></tr>"""
        linhas += f"""<tr class="tot"><td>TOTAL A PAGAR</td><td></td><td class="n">{len(x.pizzaria)}</td><td class="n">{brl(x.diaria)}</td>
<td class="n">{brl(len(x.pizzaria) * POR_ENTREGA_PIZZARIA)}</td><td class="n">{len(x.sushi)} <span class="cin">({brl(len(x.sushi) * POR_ENTREGA_SUSHI)})</span></td>
<td class="n ver">{brl(x.total)}</td></tr>"""
        avisos = "".join(f'<div class="av{" f" if a.startswith(("CORRIGIDO", "DIVERG")) else ""}">{_esc(a)}</div>' for a in x.avisos)
        codigos = ""
        for rotulo, peds in (("Pizzaria", x.pizzaria), ("Sushi", x.sushi)):
            cods = ", ".join(_esc(p["codigo"]) for p in sorted(peds, key=_ordem)) or "—"
            codigos += f'<div class="cod"><b>{dia:%d/%m} ({DIAS_CURTO[dia.weekday()]}) · {rotulo} · {len(peds)} entregas:</b> <code>{cods}</code></div>'
        paginas.append(f"""<div class="pagina mot">{topo("Relatório diário de entregas · Motoboy diarista")}
<h1>{_esc(x.nome)} <span class="tag">DIARISTA</span></h1>
<div class="sub">Dia {dia_txt} · Turno: <b>{turno}</b></div>
<div class="cards"><div class="card"><div class="r">ENTREGAS PIZZARIA</div><div class="v">{len(x.pizzaria)}</div></div>
<div class="card"><div class="r">ENTREGAS SUSHI</div><div class="v">{len(x.sushi)}</div></div>
<div class="card"><div class="r">DIÁRIA</div><div class="v">{brl(x.diaria)}</div></div>
<div class="card total"><div class="r">TOTAL A PAGAR</div><div class="v">{brl(x.total)}</div></div></div>
<div class="sec">TURNO DO DIA</div>
<table><tr><th>DATA</th><th>TURNO</th><th class="n">ENTREGAS</th><th class="n">DIÁRIA</th><th class="n">TAXAS R$ 2</th>
<th class="n">ENTREGAS SUSHI</th><th class="n">TOTAL DO DIA</th></tr>{linhas}</table>
<div class="sec" style="margin-top:3mm">ENTREGAS REALIZADAS (CÓDIGO DO PEDIDO)</div>{codigos}
<div class="espaco"></div>
<div class="recibo"><div class="t">RECIBO DE DIÁRIA E ENTREGAS</div>
<span class="g">{_esc(x.nome)}</span> declara ter recebido de <span class="g">{EMPRESA}</span> (Tili Pizzaria), CNPJ
<span class="g">{CNPJ_EMPRESA}</span> a importância de <span class="g">{brl(x.total)}</span> referente à diária e às
entregas do dia {dia_txt} ({x.entregas} entregas), conforme discriminado acima.
<div class="linha">Pagamento via &nbsp;( &nbsp;&nbsp;) <b>Pix</b> &nbsp;&nbsp;( &nbsp;&nbsp;) <b>Dinheiro</b> &nbsp;·&nbsp; Pago em ____/____/______</div></div>
<div class="ass"><div>Assinatura do motoboy — {_esc(x.nome)}</div><div>Tili Pizzaria — responsável</div></div>
<div class="rod">{rodape}</div></div>""")

    return f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<title>Diaristas {dia:%d-%m-%Y}</title><style>{CSS}</style></head><body>{''.join(paginas)}</body></html>"""


def html_para_pdf(html: str, destino: Path) -> Path:
    """Imprime o HTML em PDF A4 com o Chromium headless (também usado por prestadores.py)."""
    import shutil
    import subprocess
    import tempfile
    chrome = next((c for c in (shutil.which(c) or (c if c and Path(c).exists() else None) for c in CHROME) if c), None)
    if not chrome:
        raise RuntimeError("Chromium não encontrado (defina DIARISTAS_CHROME)")
    destino.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "relatorio.html"
        html_path.write_text(html, encoding="utf-8")
        subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={tmp}/perfil", f"--print-to-pdf={destino}", html_path.as_uri()],
                       check=False, capture_output=True, timeout=90)
    if not destino.exists() or destino.stat().st_size < 1000:
        raise RuntimeError("Chromium não gerou o PDF")
    return destino


def gerar_pdf(dia: date, ds: list[Diarista], destino: Path, gerado: datetime) -> Path:
    return html_para_pdf(html_relatorio(dia, ds, gerado), destino)


# ---------------------------------------------------------------- envio
def enviar(api: Aliv, texto: str, pdf: Path | None, legenda: str | None = None,
           extras: list | tuple = ()) -> list[str]:
    """Envia lista (+PDF) para WHATSAPP_EMERSON e WHATSAPP_ADMIN. Devolve as falhas."""
    falhas = []
    fones = [(v, re.sub(r"\D", "", os.environ.get(v, ""))) for v in ("WHATSAPP_EMERSON", "WHATSAPP_ADMIN")]
    for var, fone in fones:
        if not fone:
            falhas.append(f"{var}: variável não definida")
            continue
        try:
            api.enviar_whatsapp(fone, texto)
            print(f"WHATSAPP {var}: lista enviada.", file=sys.stderr)
        except (AlivError, OSError) as e:
            falhas.append(f"{var}: lista não enviada — {e}")
            continue
        if pdf is None:
            continue
        for arq, leg in [(pdf, legenda or f"Relatório diaristas {pdf.stem.split('_')[-1]}"), *extras]:
            try:
                api.enviar_whatsapp(fone, leg, arquivo=arq)
                print(f"WHATSAPP {var}: {arq.name} enviado.", file=sys.stderr)
            except (AlivError, OSError) as e:
                falhas.append(f"{var}: {arq.name} não enviado — {e}")
    return falhas


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Relatório diário dos motoboys diaristas (ALIV, só leitura)")
    ap.add_argument("--data", help="dia operacional AAAA-MM-DD (padrão: o que acabou de fechar)")
    ap.add_argument("--dry-run", action="store_true", help="gera PDF e lista, mas não envia nada")
    ap.add_argument("--agora", help="simula o horário da rodada (AAAA-MM-DDTHH:MM), fuso America/Bahia")
    ap.add_argument("--raw", metavar="PASTA", help="salva as respostas cruas do ALIV (diagnóstico)")
    args = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: defina ALIV_USER e ALIV_PASS nas variáveis de ambiente.", file=sys.stderr)
        return 2

    agora = (datetime.fromisoformat(args.agora).replace(tzinfo=TZ) if args.agora
             else datetime.now(TZ)).replace(second=0, microsecond=0)
    dia = date.fromisoformat(args.data) if args.data else dia_operacional(agora)
    api = Aliv(user, pwd, raw_dir=Path(args.raw) if args.raw else None)

    try:
        api.login()
        ds = coletar(api, dia, agora)
    except (AlivError, OSError) as e:
        print(f"Tili Diaristas {dm(dia)} — ERRO no ALIV\n\n{e}")
        return 1

    if not ds:
        texto = f"*Tili — Diaristas {dm(dia)} ({DIAS_SEMANA[dia.weekday()]})*\n\nNenhum diarista trabalhou neste dia."
        print(f"Tili Diaristas {dm(dia)} — sem diaristas\n\n{texto}")
        if args.dry_run:
            print("\nDRY-RUN: nada enviado.", file=sys.stderr)
            return 0
        return 3 if enviar(api, texto, None) else 0

    pasta = PASTA / f"{dia}"
    pasta.mkdir(parents=True, exist_ok=True)
    pdf = gerar_pdf(dia, ds, pasta / f"diaristas_{dia:%d-%m}.pdf", datetime.now(TZ))
    texto = lista_whatsapp(dia, ds)
    print(f"Tili Diaristas {dm(dia)} — {len(ds)} diarista(s) — {brl(sum(x.total for x in ds))}\n")
    print(texto)
    print("\nDETALHE\n" + resumo_texto(dia, ds))
    print(f"\nPDF: {pdf.relative_to(PASTA.parent.parent)}")
    if args.dry_run:
        print("\nDRY-RUN: nada enviado.", file=sys.stderr)
        return 0
    falhas = enviar(api, texto, pdf)
    for f in falhas:
        print(f"WHATSAPP: {f}", file=sys.stderr)
    return 3 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
