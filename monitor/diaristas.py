#!/usr/bin/env python3
"""Relatório diário dos motoboys DIARISTAS da Tili — só leitura no ALIV.

Para o dia operacional D (turnos iniciados entre 10:00 de D e 10:00 de D+1,
incluindo as entregas da virada), lista os diaristas (motoboys sem "CNPJ" no
nome, fora os logins de gerente), com entrada/saída do turno, entregas da
Pizzaria e do Sushi, diária gravada, fechamento do turno no ALIV e cálculo
(diária + R$ 2 por entrega). Gera:

  monitor/diaristas/AAAA-MM-DD/diaristas_DD-MM.pdf   (resumo + 1 página por motoboy com recibo)
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
PEDIDO_ATE_H = 6             # pedidos criados até 06:00 de D+1 ainda são do dia D
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
        """Total a pagar = fechamento do ALIV (+ a correção da diária, se houve).
        Sem fechamento, vale o cálculo."""
        if self.fechamento is None:
            return self.calculado
        extra = self.diaria - (self.diaria_gravada or 0.0) if self.corrigida else 0.0
        return self.fechamento + extra

    @property
    def divergente(self) -> bool:
        return self.fechamento is not None and abs(self.total - self.calculado) > 0.009


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
    padrao = diaria_padrao(dia)
    if x.diaria_gravada is None:
        x.diaria = padrao
        x.avisos.append(f"diária não gravada no ALIV — usada a padrão {brl(padrao)}")
    elif dia.weekday() >= 5 and abs(x.diaria_gravada - DIARIA_SEMANA) < 0.01:
        x.diaria, x.corrigida = DIARIA_FDS, True
        x.avisos.append(f"CORRIGIDO: ALIV gravou {brl(x.diaria_gravada)} no fim de semana → {brl(DIARIA_FDS)}")
    else:
        x.diaria = x.diaria_gravada
        if abs(x.diaria_gravada - padrao) > 0.009:
            x.avisos.append(f"diária gravada {brl(x.diaria_gravada)} diferente da padrão {brl(padrao)}")
    fech = [t.fechamento for t in x.turnos if t.fechamento is not None]
    x.fechamento = sum(fech) if fech else None
    if any(t.aberto for t in x.turnos):
        x.avisos.append("turno ainda aberto no ALIV na hora da rodada")
    if x.fechamento is None:
        x.avisos.append("sem fechamento do turno no ALIV — total pelo cálculo")
    if not x.turnos:
        x.avisos.append("turno não encontrado no ALIV (só entregas)")
    if x.divergente:
        x.avisos.append(f"DIVERGÊNCIA: fechamento ALIV {brl(x.total)} × cálculo {brl(x.calculado)}")


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
def gerar_pdf(dia: date, ds: list[Diarista], destino: Path, gerado: datetime) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    verm, dour, preto = (colors.HexColor(c) for c in (VERMELHO, DOURADO, PRETO))
    cinza = colors.HexColor("#F4F1EA")
    ss = getSampleStyleSheet()
    st = {
        "h1": ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18,
                             textColor=preto, spaceAfter=2, alignment=0),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=13,
                             textColor=verm, spaceBefore=6, spaceAfter=4),
        "p": ParagraphStyle("p", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5,
                            textColor=preto, leading=13),
        "sm": ParagraphStyle("sm", parent=ss["Normal"], fontName="Helvetica", fontSize=8,
                             textColor=colors.HexColor("#555555"), leading=10),
        "av": ParagraphStyle("av", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=9,
                             textColor=verm, leading=12),
        "c": ParagraphStyle("c", parent=ss["Normal"], fontName="Helvetica", fontSize=8.5,
                            alignment=TA_CENTER, leading=10),
    }
    titulo = f"Diaristas — {dia:%d/%m/%Y} ({DIAS_SEMANA[dia.weekday()]})"

    def cabecalho(canvas, doc):
        w, h = A4
        canvas.saveState()
        canvas.setFillColor(verm)
        canvas.rect(0, h - 22 * mm, w, 22 * mm, stroke=0, fill=1)
        canvas.setFillColor(dour)
        canvas.rect(0, h - 23.5 * mm, w, 1.5 * mm, stroke=0, fill=1)
        # marca: círculo dourado com "T" (logo) + nome
        canvas.setFillColor(dour)
        canvas.circle(20 * mm, h - 11 * mm, 7 * mm, stroke=0, fill=1)
        canvas.setFillColor(preto)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawCentredString(20 * mm, h - 13.5 * mm, "T")
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(30 * mm, h - 10 * mm, "TILI PIZZARIA")
        canvas.setFont("Helvetica", 9)
        canvas.drawString(30 * mm, h - 15.5 * mm, "Pizzaria + Sushi & Poke · Porto Seguro-BA · WhatsApp (73) 99917-9941")
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawRightString(w - 12 * mm, h - 12.5 * mm, f"Diaristas {dia:%d/%m/%Y}")
        canvas.setFillColor(preto)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(12 * mm, 8 * mm, f"Gerado em {gerado:%d/%m/%Y %H:%M} a partir do ALIV (só leitura)")
        canvas.drawRightString(w - 12 * mm, 8 * mm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(destino), pagesize=A4, title=titulo, author="Tili Pizzaria",
                            leftMargin=14 * mm, rightMargin=14 * mm, topMargin=30 * mm, bottomMargin=16 * mm)
    base = [("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("TEXTCOLOR", (0, 0), (-1, -1), preto), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    head = [("BACKGROUND", (0, 0), (-1, 0), preto), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]

    el = [Paragraph(titulo, st["h1"]),
          Paragraph(f"Resumo para pagar · diária {brl(diaria_padrao(dia))} · "
                    f"R$ 2,00 por entrega da Pizzaria + R$ 2,00 por entrega do Sushi", st["p"]),
          Spacer(1, 5 * mm)]
    linhas = [["Motoboy", "Pizzaria", "Sushi", "Diária", "Total a pagar"]]
    for x in ds:
        marca = " *" if x.divergente or x.corrigida else ""
        linhas.append([Paragraph(x.nome, st["p"]), str(len(x.pizzaria)), str(len(x.sushi)),
                       brl(x.diaria) + (" (corr.)" if x.corrigida else ""), brl(x.total) + marca])
    linhas.append(["TOTAL", str(sum(len(x.pizzaria) for x in ds)), str(sum(len(x.sushi) for x in ds)),
                   brl(sum(x.diaria for x in ds)), brl(sum(x.total for x in ds))])
    t = Table(linhas, colWidths=[72 * mm, 22 * mm, 20 * mm, 30 * mm, 38 * mm], repeatRows=1)
    zebra = [("BACKGROUND", (0, i), (-1, i), cinza) for i in range(2, len(linhas) - 1, 2)]
    t.setStyle(TableStyle(base + head + zebra + [
        ("ALIGN", (1, 0), (-1, -1), "CENTER"), ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), dour), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#CCCCCC")),
        ("BOX", (0, 0), (-1, -1), 0.8, preto)]))
    el.append(t)
    avisos = [(x.nome, a) for x in ds for a in x.avisos]
    if avisos:
        el += [Spacer(1, 5 * mm), Paragraph("Atenção", st["h2"])]
        el += [Paragraph(f"• <b>{n}</b>: {a}", st["av" if a.startswith(("CORRIGIDO", "DIVERG")) else "p"])
               for n, a in avisos]
    el += [Spacer(1, 4 * mm), Paragraph(
        "* Total a pagar = fechamento do turno no ALIV (com a correção da diária de fim de semana, "
        "se houver). Divergência = fechamento diferente de diária + entregas × R$ 2,00.", st["sm"])]

    for x in ds:
        el.append(PageBreak())
        el += [Paragraph(x.nome, st["h1"]), Paragraph(titulo, st["p"]), Spacer(1, 3 * mm)]
        turnos = "<br/>".join(f"Entrada {fmt_h(t.inicio)} · Saída {fmt_h(t.fim) if t.fim else 'em aberto'}"
                              for t in x.turnos) or "não encontrado no ALIV"
        info = [
            ["Turno", Paragraph(turnos, st["p"])],
            ["Diária", Paragraph(
                f"{brl(x.diaria)}" + (f" — <font color='{VERMELHO}'><b>corrigida</b></font> "
                                      f"(ALIV gravou {brl(x.diaria_gravada)})" if x.corrigida else "")
                + ("" if x.diaria_gravada is not None or x.corrigida else " (padrão — não gravada no ALIV)"),
                st["p"])],
            ["Entregas Pizzaria", f"{len(x.pizzaria)} × {brl(POR_ENTREGA_PIZZARIA)} = "
                                  f"{brl(len(x.pizzaria) * POR_ENTREGA_PIZZARIA)}"],
            ["Entregas Sushi", f"{len(x.sushi)} × {brl(POR_ENTREGA_SUSHI)} = {brl(len(x.sushi) * POR_ENTREGA_SUSHI)}"],
            ["Cálculo", f"{brl(x.diaria)} + {brl(x.taxas)} = {brl(x.calculado)}"],
            ["Fechamento ALIV", brl(x.fechamento) if x.fechamento is not None else "sem fechamento"],
            ["TOTAL A PAGAR", brl(x.total) + ("  (DIVERGÊNCIA)" if x.divergente else "")],
        ]
        ti = Table(info, colWidths=[42 * mm, 140 * mm])
        ti.setStyle(TableStyle(base + [
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("BACKGROUND", (0, 0), (0, -2), cinza),
            ("BACKGROUND", (0, -1), (-1, -1), verm), ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, -1), (-1, -1), 11),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#CCCCCC")),
            ("BOX", (0, 0), (-1, -1), 0.8, preto)]))
        el.append(ti)
        for a in x.avisos:
            el.append(Paragraph(f"! {a}", st["av"]))

        for nome, peds in (("Pedidos entregues — Pizzaria", x.pizzaria), ("Pedidos entregues — Sushi", x.sushi)):
            el.append(Paragraph(f"{nome} ({len(peds)})", st["h2"]))
            if not peds:
                el.append(Paragraph("nenhum", st["p"]))
                continue
            cel = [Paragraph(f"<b>{p['codigo']}</b><br/><font size=7>{p['hora']}</font>", st["c"])
                   for p in sorted(peds, key=lambda p: p["hora"] if p["hora"] >= "06:00" else "z" + p["hora"])]
            ncol = 6
            cel += [""] * (-len(cel) % ncol)
            grade = Table([cel[i:i + ncol] for i in range(0, len(cel), ncol)], colWidths=[30.3 * mm] * ncol)
            grade.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BBBBBB")),
                                       ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                       ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            el.append(grade)

        recibo = Table([
            [Paragraph("<b>RECIBO</b>", ParagraphStyle("r", parent=st["p"], fontSize=12, textColor=verm))],
            [Paragraph(f"Recebi da <b>Tili Pizzaria</b> (SO DELIVERY PIZZARIA E RESTAURANTE LTDA) a quantia de "
                       f"<b>{brl(x.total)}</b>, referente à diária e às entregas do dia "
                       f"<b>{dia:%d/%m/%Y}</b> ({x.entregas} entregas).", st["p"])],
            [Paragraph("Forma de pagamento:&nbsp;&nbsp;&nbsp;(&nbsp;&nbsp;&nbsp;) Pix"
                       "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(&nbsp;&nbsp;&nbsp;) Dinheiro", st["p"])],
            [Paragraph("Data: ____/____/________", st["p"])],
            [Spacer(1, 8 * mm)],
            [Paragraph("_____________________________________________<br/>"
                       f"Assinatura — {x.nome}", st["p"])],
        ], colWidths=[182 * mm])
        recibo.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, dour),
                                    ("BACKGROUND", (0, 0), (-1, 0), cinza),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
        el += [Spacer(1, 6 * mm), KeepTogether(recibo)]

    doc.build(el, onFirstPage=cabecalho, onLaterPages=cabecalho)
    return destino


# ---------------------------------------------------------------- envio
def enviar(api: Aliv, texto: str, pdf: Path | None) -> list[str]:
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
        try:
            api.enviar_whatsapp(fone, f"Relatório diaristas {pdf.stem.split('_')[-1]}", arquivo=pdf)
            print(f"WHATSAPP {var}: PDF enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            falhas.append(f"{var}: PDF não enviado — {e}")
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
