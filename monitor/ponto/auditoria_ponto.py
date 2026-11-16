#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auditoria de ponto - Tili Pizzaria (Flit Gestor)
=================================================
Lê o relatório "Apuração de jornadas" exportado do Flit (Relatórios > Relatórios adicionais)
e gera uma planilha Excel com a auditoria (semanal) ou o fechamento (mensal).

Uso:
  python3 auditoria_ponto.py --modo semanal --apuracao "Apuração de jornadas-...xlsx" \
      --inicio 14/09/2026 --fim 20/09/2026 --saida Auditoria_Ponto_2026-09-14_a_2026-09-20.xlsx
  python3 auditoria_ponto.py --modo mensal --apuracao "Apuração de jornadas-...xlsx" \
      --inicio 01/09/2026 --fim 30/09/2026 --saida Fechamento_Ponto_2026-09.xlsx

Regras (parâmetros ajustáveis abaixo em REGRAS):
  - Tolerância de entrada/saída: 10 min (mesma tolerância configurada no Flit)
  - Intervalo mínimo: 60 min (CLT art. 71, jornada > 6h)
  - Interjornada mínima: 11h (CLT art. 66)
  - Sobrecarga diária: > 10h trabalhadas (8h + 2h extras, CLT art. 59)
  - HE diária acima de 2h
  - Sobrecarga semanal: > 44h (aviso) e > 50h (alerta)
  - 7 dias trabalhados na semana sem folga (DSR)
  - Faltas: 1 na semana = provável folga não lançada (aviso); 2 ou mais = alerta
"""
import argparse
import re
import sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

REGRAS = {
    "tolerancia_min": 10,
    "entrada_antecipada_min": 30,
    "intervalo_min": 60,
    "intervalo_alerta_min": 50,
    "intervalo_desloc_min": 60,
    "interjornada_min_h": 11,
    "sobrecarga_dia_h": 10,
    "he_dia_h": 2,
    "semana_aviso_h": 44,
    "semana_alerta_h": 50,
    "faltas_alerta": 2,
}

FONT = "Arial"
GRAV_ORDEM = {"ALERTA": 0, "AVISO": 1, "INFO": 2}


# ----------------------------------------------------------------------------- utilidades
def hm_to_min(s):
    """'07:20' -> 440 ; '-05:27' -> -327 ; '' -> None"""
    if s is None:
        return None
    s = str(s).strip()
    if not s or s == "-":
        return None
    m = re.match(r"^(-?)(\d{1,3}):(\d{2})$", s)
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    return sign * (int(m.group(2)) * 60 + int(m.group(3)))


def min_to_hm(m):
    if m is None:
        return ""
    sign = "-" if m < 0 else ""
    m = abs(int(m))
    return f"{sign}{m // 60:02d}:{m % 60:02d}"


def min_to_excel(m):
    """minutos -> fração de dia (formato [h]:mm no Excel)"""
    if m is None:
        return None
    return m / 1440.0


def parse_times_seq(tokens):
    """Sequência de horários 'HH:MM' de um mesmo turno; corrige virada de meia-noite.
    Retorna lista de minutos desde 00:00 do dia da jornada (pode passar de 1440)."""
    out = []
    prev = None
    for t in tokens:
        v = hm_to_min(t)
        if v is None:
            continue
        if prev is not None and v < prev:
            v += 1440
        out.append(v)
        prev = v
    return out


def fmt_rel(v):
    """minutos relativos ao dia da jornada -> 'HH:MM' (usa +1d se passou da meia-noite)."""
    if v is None:
        return ""
    d = v // 1440
    return min_to_hm(v % 1440) + ("(+1d)" if d else "")


def parse_date(s):
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


DIAS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


# ----------------------------------------------------------------------------- leitura
def _linhas_dict(path):
    """Lista de dicts por nome de coluna. Aceita .xlsx OU .json.
    O .json é uma lista de objetos {"Nome do Funcionário":..., "Data":..., ...} com as mesmas
    colunas da 'Apuração de jornadas' do Flit (capturado na memória da página, sem baixar arquivo)."""
    if path.lower().endswith(".json"):
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [{str(k).strip(): ("" if v is None else str(v)) for k, v in row.items()} for row in data]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not r:
            continue
        out.append({header[i]: ("" if (i >= len(r) or r[i] is None) else str(r[i])) for i in range(len(header))})
    return out


def ler_apuracao(path):
    linhas = _linhas_dict(path)
    obrig = ["Nome do Funcionário", "Data", "Horários previstos", "Marcação 1", "Total horas trab.",
             "Total horas excedentes", "Atraso", "Status jornada"]
    if linhas:
        faltando = [c for c in obrig if c not in linhas[0]]
        if faltando:
            sys.exit(f"Colunas não encontradas no relatório de apuração: {faltando}. Cabeçalho lido: {list(linhas[0].keys())}")

    def g(r, col):
        v = r.get(col, "")
        return "" if v is None else str(v).strip()

    dados = []
    for r in linhas:
        if not g(r, "Nome do Funcionário"):
            continue
        marc = [g(r, f"Marcação {k}") for k in range(1, 6)]
        marc = [m for m in marc if m]
        dados.append({
            "nome": g(r, "Nome do Funcionário"),
            "cpf": g(r, "CPF"),
            "data": parse_date(g(r, "Data")),
            "previsto": g(r, "Horários previstos"),
            "marcacoes": marc,
            "interjornada": hm_to_min(g(r, "Interjornada")),
            "he_intra": hm_to_min(g(r, "HE Intrajornada")),
            "intrajornada": hm_to_min(g(r, "Intrajornada")),
            "h_diurnas": hm_to_min(g(r, "Horas diurnas")),
            "h_noturnas": hm_to_min(g(r, "Horas noturnas")),
            "h_normais": hm_to_min(g(r, "Total horas normais")),
            "he_diurnas": hm_to_min(g(r, "Horas excedentes diurnas")),
            "he_noturnas": hm_to_min(g(r, "Horas excedentes noturnas")),
            "he_total": hm_to_min(g(r, "Total horas excedentes")),
            "h_trab": hm_to_min(g(r, "Total horas trab.")),
            "atraso": hm_to_min(g(r, "Atraso")),
            "status": g(r, "Status jornada"),
        })
    return dados


# ----------------------------------------------------------------------------- análise
def analisar_dia(d):
    """Retorna (classificacao, lista de (gravidade, tipo, detalhe))."""
    R = REGRAS
    achados = []
    # Ocorrência explícita vinda do Flit (folga/férias/feriado/atestado lançados)
    prevraw = d["previsto"].strip()
    if prevraw and not re.search(r"\d", prevraw):
        low = prevraw.lower()
        OCC = {"folga": "Folga", "féria": "Férias", "feria": "Férias", "feriado": "Feriado",
               "atestado": "Atestado", "dsr": "Folga", "descanso": "Folga", "abono": "Abono"}
        occ = next((v for k, v in OCC.items() if k in low), prevraw)
        return occ, achados
    prev = parse_times_seq(d["previsto"].split())
    marc = parse_times_seq(d["marcacoes"])
    n = len(marc)
    status = d["status"].strip().lower()

    if not prev and not marc:
        return "Sem jornada prevista", achados

    if prev and not marc:
        return "FALTA", achados  # a gravidade é decidida no consolidado da semana

    if status and status != "verificado":
        achados.append(("ALERTA", "Jornada pendente/incompleta",
                        f"Status '{d['status']}' - tratar em Frequência > Ajustes de jornadas"))

    if n % 2 == 1:
        achados.append(("ALERTA", "Marcação incompleta",
                        f"{n} marcação(ões): {' - '.join(d['marcacoes'])} (falta entrada ou saída)"))

    if prev and marc:
        ent_prev, sai_prev = prev[0], prev[-1]
        ent = marc[0]
        dif = ent - ent_prev
        if dif > R["tolerancia_min"]:
            achados.append(("AVISO", "Atraso na entrada",
                            f"Entrou {fmt_rel(ent)} (previsto {fmt_rel(ent_prev)}) - {dif} min de atraso"))
        elif dif < -R["entrada_antecipada_min"]:
            achados.append(("INFO", "Entrada antecipada",
                            f"Entrou {fmt_rel(ent)} (previsto {fmt_rel(ent_prev)}) - {-dif} min antes"))

        if n % 2 == 0:
            sai = marc[-1]
            dif_s = sai - sai_prev
            if dif_s < -R["tolerancia_min"]:
                achados.append(("AVISO", "Saída antecipada",
                                f"Saiu {fmt_rel(sai)} (previsto {fmt_rel(sai_prev)}) - {-dif_s} min antes"))
            elif dif_s > R["entrada_antecipada_min"]:
                achados.append(("INFO", "Saída após o horário",
                                f"Saiu {fmt_rel(sai)} (previsto {fmt_rel(sai_prev)}) - {dif_s} min depois (hora extra)"))

        # intervalo
        if len(prev) >= 4 and n >= 4:
            intervalo = marc[2] - marc[1]
            if intervalo < R["intervalo_alerta_min"]:
                achados.append(("ALERTA", "Intervalo menor que 1h",
                                f"Intervalo de {intervalo} min ({fmt_rel(marc[1])}-{fmt_rel(marc[2])}) - CLT exige 1h"))
            elif intervalo < R["intervalo_min"]:
                achados.append(("AVISO", "Intervalo abaixo de 1h",
                                f"Intervalo de {intervalo} min ({fmt_rel(marc[1])}-{fmt_rel(marc[2])}) - faltaram {R['intervalo_min'] - intervalo} min"))
            desloc = marc[1] - prev[1]
            if abs(desloc) > R["intervalo_desloc_min"]:
                achados.append(("INFO", "Intervalo fora do horário previsto",
                                f"Intervalo {fmt_rel(marc[1])}-{fmt_rel(marc[2])} (previsto {fmt_rel(prev[1])}-{fmt_rel(prev[2])})"))
        elif len(prev) >= 4 and n == 2:
            achados.append(("ALERTA", "Sem marcação de intervalo",
                            f"Só entrada e saída ({fmt_rel(marc[0])}-{fmt_rel(marc[1])}); intervalo previsto "
                            f"{fmt_rel(prev[1])}-{fmt_rel(prev[2])} não foi registrado"))

    if d["h_trab"] is not None and d["h_trab"] > R["sobrecarga_dia_h"] * 60:
        achados.append(("ALERTA", "Sobrecarga diária",
                        f"{min_to_hm(d['h_trab'])} trabalhadas (limite 8h + 2h extras)"))
    if d["he_total"] is not None and d["he_total"] > R["he_dia_h"] * 60:
        achados.append(("ALERTA", "Hora extra acima de 2h",
                        f"{min_to_hm(d['he_total'])} de HE no dia"))
    if d["interjornada"] is not None and 0 < d["interjornada"] < R["interjornada_min_h"] * 60:
        achados.append(("ALERTA", "Interjornada menor que 11h",
                        f"Descanso entre jornadas de {min_to_hm(d['interjornada'])}"))

    if any(a[0] == "ALERTA" for a in achados):
        cls = "ALERTA"
    elif any(a[0] == "AVISO" for a in achados):
        cls = "Divergência"
    elif achados:
        cls = "OK (obs.)"
    else:
        cls = "OK"
    return cls, achados


def consolidar(dados, inicio, fim, modo):
    R = REGRAS
    por_pessoa = defaultdict(list)
    for d in dados:
        if inicio <= d["data"] <= fim:
            por_pessoa[d["nome"]].append(d)

    alertas = []      # linhas da aba Alertas
    detalhe = []      # linhas da aba Detalhe
    resumo = []       # linhas da aba Resumo

    for nome in sorted(por_pessoa, key=lambda s: s.upper()):
        dias = sorted(por_pessoa[nome], key=lambda x: x["data"])
        faltas = []
        cls_por_dia = {}
        for d in dias:
            cls, achados = analisar_dia(d)
            cls_por_dia[d["data"]] = cls
            if cls == "FALTA":
                faltas.append(d["data"])
            for grav, tipo, det in achados:
                alertas.append({"data": d["data"], "nome": nome, "grav": grav, "tipo": tipo, "detalhe": det})
            detalhe.append({**d, "classificacao": cls,
                            "obs": "; ".join(f"{t}: {det}" for _, t, det in achados)})

        # --- consolidado da pessoa
        obs = []
        semanas = defaultdict(lambda: {"dias": 0, "min": 0})
        for d in dias:
            if d["h_trab"]:
                iso = d["data"].isocalendar()
                semanas[(iso[0], iso[1])]["dias"] += 1
                semanas[(iso[0], iso[1])]["min"] += d["h_trab"]

        # faltas
        if faltas:
            if modo == "semanal":
                if len(faltas) >= R["faltas_alerta"]:
                    for f in faltas:
                        alertas.append({"data": f, "nome": nome, "grav": "ALERTA", "tipo": "Falta",
                                        "detalhe": f"{len(faltas)} faltas na semana ({', '.join(x.strftime('%d/%m') for x in faltas)})"})
                    obs.append(f"{len(faltas)} faltas: {', '.join(x.strftime('%a %d/%m') for x in faltas)}")
                else:
                    f = faltas[0]
                    alertas.append({"data": f, "nome": nome, "grav": "AVISO", "tipo": "Falta (provável folga)",
                                    "detalhe": "1 dia sem marcação na semana - provavelmente a folga, que não está lançada no Flit"})
                    obs.append(f"1 falta ({DIAS_PT[f.weekday()]} {f.strftime('%d/%m')}) - provável folga não lançada")
            else:
                obs.append(f"{len(faltas)} dia(s) sem marcação: " + ", ".join(x.strftime("%d/%m") for x in faltas))

        # semanas sem folga / sobrecarga semanal
        for (ano, sem), v in sorted(semanas.items()):
            if v["dias"] >= 7:
                dref = datetime.fromisocalendar(ano, sem, 7).date()
                alertas.append({"data": dref, "nome": nome, "grav": "ALERTA", "tipo": "7 dias sem folga",
                                "detalhe": f"Trabalhou os 7 dias da semana {sem} - sem descanso semanal (DSR)"})
                obs.append(f"7 dias sem folga na semana {sem}")
            if v["min"] > R["semana_alerta_h"] * 60:
                dref = datetime.fromisocalendar(ano, sem, 7).date()
                alertas.append({"data": dref, "nome": nome, "grav": "ALERTA", "tipo": "Sobrecarga semanal",
                                "detalhe": f"{min_to_hm(v['min'])} trabalhadas na semana {sem} (acima de {R['semana_alerta_h']}h)"})
                obs.append(f"{min_to_hm(v['min'])} na semana {sem}")
            elif v["min"] > R["semana_aviso_h"] * 60:
                dref = datetime.fromisocalendar(ano, sem, 7).date()
                alertas.append({"data": dref, "nome": nome, "grav": "AVISO", "tipo": "Acima de 44h semanais",
                                "detalhe": f"{min_to_hm(v['min'])} trabalhadas na semana {sem}"})

        n_alertas = sum(1 for a in alertas if a["nome"] == nome and a["grav"] == "ALERTA")
        n_avisos = sum(1 for a in alertas if a["nome"] == nome and a["grav"] == "AVISO")
        pend = sum(1 for d in dias if d["status"].strip().lower() not in ("verificado", ""))
        previstos = Counter(d["previsto"] for d in dias if d["previsto"])
        resumo.append({
            "nome": nome,
            "cpf": dias[0]["cpf"],
            "horario": previstos.most_common(1)[0][0] if previstos else "",
            "dias_prev": sum(1 for d in dias if d["previsto"]),
            "dias_trab": sum(1 for d in dias if d["h_trab"]),
            "faltas": len(faltas),
            "pendentes": pend,
            "alertas": n_alertas,
            "avisos": n_avisos,
            "obs": "; ".join(obs),
        })

    alertas.sort(key=lambda a: (GRAV_ORDEM[a["grav"]], a["nome"].upper(), a["data"]))
    return resumo, alertas, detalhe


# ----------------------------------------------------------------------------- excel
THIN = Side(style="thin", color="BFBFBF")
BORDA = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL_HEAD = PatternFill("solid", fgColor="1F3864")
FILL_ALERTA = PatternFill("solid", fgColor="F8CBAD")
FILL_AVISO = PatternFill("solid", fgColor="FFE699")
FILL_INFO = PatternFill("solid", fgColor="DDEBF7")
FILL_FALTA = PatternFill("solid", fgColor="D9D9D9")
FILL_OK = PatternFill("solid", fgColor="E2EFDA")
FILL_TITULO = PatternFill("solid", fgColor="D9E1F2")


def cabecalho(ws, row, cols, widths=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = FILL_HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDA
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.row_dimensions[row].height = 30


def estilo_linha(ws, row, ncols, fill=None, fmt=None):
    for j in range(1, ncols + 1):
        c = ws.cell(row=row, column=j)
        c.font = Font(name=FONT, size=10)
        c.border = BORDA
        c.alignment = Alignment(vertical="top", wrap_text=True)
        if fill:
            c.fill = fill


def titulo(ws, texto, sub=None):
    ws["A1"] = texto
    ws["A1"].font = Font(name=FONT, bold=True, size=14, color="1F3864")
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(name=FONT, italic=True, size=10, color="595959")


def gerar_excel(saida, modo, inicio, fim, resumo, alertas, detalhe, fonte):
    wb = openpyxl.Workbook()
    periodo = f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"
    n_dias = (fim - inicio).days + 1

    # ---------------- Detalhe diário (primeiro, porque o Resumo aponta para ele com fórmulas)
    wsd = wb.active
    wsd.title = "Detalhe diário"
    titulo(wsd, f"Detalhe diário - {periodo}", f"Fonte: Flit Gestor > Relatórios adicionais > Apuração de jornadas ({fonte})")
    cols_d = ["Colaborador", "Data", "Dia", "Horários previstos", "Marc. 1", "Marc. 2", "Marc. 3", "Marc. 4", "Marc. 5",
              "Intervalo", "Interjornada", "H. normais", "H. diurnas", "H. noturnas", "HE diurnas", "HE noturnas",
              "Total HE", "Total trab.", "Atraso/H. negativas", "Status Flit", "Classificação", "Observações"]
    HEAD_D = 4
    cabecalho(wsd, HEAD_D, cols_d, [30, 11, 5, 22, 7, 7, 7, 7, 7, 9, 11, 9, 9, 9, 9, 9, 9, 9, 11, 11, 13, 70])
    r = HEAD_D + 1
    for d in detalhe:
        m = d["marcacoes"] + [""] * (5 - len(d["marcacoes"]))
        vals = [d["nome"], d["data"], DIAS_PT[d["data"].weekday()], d["previsto"], *m[:5],
                min_to_excel(d["intrajornada"]), min_to_excel(d["interjornada"]), min_to_excel(d["h_normais"]),
                min_to_excel(d["h_diurnas"]), min_to_excel(d["h_noturnas"]), min_to_excel(d["he_diurnas"]),
                min_to_excel(d["he_noturnas"]), min_to_excel(d["he_total"]), min_to_excel(d["h_trab"]),
                min_to_excel(d["atraso"]), d["status"], d["classificacao"], d["obs"]]
        for j, v in enumerate(vals, 1):
            wsd.cell(row=r, column=j, value=v)
        fill = None
        if d["classificacao"] == "ALERTA":
            fill = FILL_ALERTA
        elif d["classificacao"] == "Divergência":
            fill = FILL_AVISO
        elif d["classificacao"] == "FALTA":
            fill = FILL_FALTA
        elif d["classificacao"] == "OK (obs.)":
            fill = FILL_INFO
        estilo_linha(wsd, r, len(cols_d), fill)
        wsd.cell(row=r, column=2).number_format = "DD/MM/YYYY"
        for j in range(10, 20):
            wsd.cell(row=r, column=j).number_format = "[h]:mm;-[h]:mm"
        r += 1
    LAST_D = r - 1
    wsd.freeze_panes = wsd.cell(row=HEAD_D + 1, column=3)
    wsd.auto_filter.ref = f"A{HEAD_D}:{get_column_letter(len(cols_d))}{max(LAST_D, HEAD_D)}"

    # ---------------- Resumo
    wsr = wb.create_sheet("Resumo", 0)
    titulo(wsr, ("Auditoria semanal de ponto" if modo == "semanal" else "Fechamento mensal de ponto") + f" - Tili Pizzaria",
           f"Período: {periodo} ({n_dias} dias) - gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} a partir do Flit Gestor")
    cols_r = ["Colaborador", "Horário previsto (mais comum)", "Dias previstos", "Dias trabalhados", "Faltas",
              "Horas trabalhadas", "Horas normais", "Horas noturnas", "Horas extras", "Horas negativas (atrasos)",
              "Jornadas pendentes no Flit", "Alertas", "Avisos", "Observações"]
    HEAD_R = 4
    cabecalho(wsr, HEAD_R, cols_r, [32, 24, 9, 10, 8, 11, 11, 11, 11, 12, 12, 8, 8, 80])
    r = HEAD_R + 1
    det = "'Detalhe diário'"
    rng = lambda col: f"{det}!${col}${HEAD_D + 1}:${col}${max(LAST_D, HEAD_D + 1)}"
    for p in resumo:
        nome_ref = f"$A{r}"
        vals = [p["nome"], p["horario"], p["dias_prev"], p["dias_trab"], p["faltas"],
                f"=SUMIFS({rng('R')},{rng('A')},{nome_ref})",
                f"=SUMIFS({rng('L')},{rng('A')},{nome_ref})",
                f"=SUMIFS({rng('N')},{rng('A')},{nome_ref})",
                f"=SUMIFS({rng('Q')},{rng('A')},{nome_ref})",
                f"=SUMIFS({rng('S')},{rng('A')},{nome_ref})",
                p["pendentes"], p["alertas"], p["avisos"], p["obs"]]
        for j, v in enumerate(vals, 1):
            wsr.cell(row=r, column=j, value=v)
        fill = FILL_ALERTA if p["alertas"] else (FILL_AVISO if p["avisos"] or p["faltas"] else FILL_OK)
        estilo_linha(wsr, r, len(cols_r), fill)
        for j in range(6, 11):
            wsr.cell(row=r, column=j).number_format = "[h]:mm;-[h]:mm"
        r += 1
    LAST_R = r - 1
    # totais
    wsr.cell(row=r, column=1, value="TOTAL")
    for j in range(3, 14):
        col = get_column_letter(j)
        wsr.cell(row=r, column=j, value=f"=SUM({col}{HEAD_R + 1}:{col}{LAST_R})")
    estilo_linha(wsr, r, len(cols_r), FILL_TITULO)
    for j in range(1, len(cols_r) + 1):
        wsr.cell(row=r, column=j).font = Font(name=FONT, bold=True, size=10)
    for j in range(6, 11):
        wsr.cell(row=r, column=j).number_format = "[h]:mm;-[h]:mm"
    wsr.freeze_panes = wsr.cell(row=HEAD_R + 1, column=2)
    wsr.auto_filter.ref = f"A{HEAD_R}:{get_column_letter(len(cols_r))}{LAST_R}"

    # ---------------- Alertas
    wsa = wb.create_sheet("Alertas", 1)
    titulo(wsa, f"Alertas e divergências - {periodo}",
           "ALERTA = exige ação (tratar no Flit ou com o colaborador); AVISO = divergência de horário; INFO = observação")
    cols_a = ["Gravidade", "Colaborador", "Data", "Dia", "Tipo", "Detalhe"]
    HEAD_A = 4
    cabecalho(wsa, HEAD_A, cols_a, [11, 32, 11, 5, 30, 95])
    r = HEAD_A + 1
    for a in alertas:
        vals = [a["grav"], a["nome"], a["data"], DIAS_PT[a["data"].weekday()], a["tipo"], a["detalhe"]]
        for j, v in enumerate(vals, 1):
            wsa.cell(row=r, column=j, value=v)
        estilo_linha(wsa, r, len(cols_a), {"ALERTA": FILL_ALERTA, "AVISO": FILL_AVISO, "INFO": FILL_INFO}[a["grav"]])
        wsa.cell(row=r, column=3).number_format = "DD/MM/YYYY"
        r += 1
    if r == HEAD_A + 1:
        wsa.cell(row=r, column=1, value="Nenhum alerta no período.")
    wsa.freeze_panes = wsa.cell(row=HEAD_A + 1, column=1)
    wsa.auto_filter.ref = f"A{HEAD_A}:{get_column_letter(len(cols_a))}{max(r - 1, HEAD_A)}"

    # ---------------- Contabilidade (mensal)
    if modo == "mensal":
        wsc = wb.create_sheet("Contabilidade", 1)
        titulo(wsc, f"Resumo para a folha - {periodo}",
               "Totais apurados pelo Flit Gestor (regime: horas extras, sem banco de horas). Adicional noturno: 22h-05h.")
        cols_c = ["Colaborador", "CPF", "Dias trabalhados", "Dias sem marcação (faltas/folgas)", "Horas normais",
                  "Horas noturnas (adic. noturno)", "HE diurnas", "HE noturnas", "Total HE", "Horas negativas (atrasos/saídas)",
                  "Jornadas pendentes no Flit", "Observações"]
        HEAD_C = 4
        cabecalho(wsc, HEAD_C, cols_c, [32, 16, 10, 12, 11, 12, 10, 10, 10, 13, 12, 70])
        r = HEAD_C + 1
        for p in resumo:
            nome_ref = f"$A{r}"
            vals = [p["nome"], p["cpf"], p["dias_trab"], p["faltas"],
                    f"=SUMIFS({rng('L')},{rng('A')},{nome_ref})",
                    f"=SUMIFS({rng('N')},{rng('A')},{nome_ref})",
                    f"=SUMIFS({rng('O')},{rng('A')},{nome_ref})",
                    f"=SUMIFS({rng('P')},{rng('A')},{nome_ref})",
                    f"=SUMIFS({rng('Q')},{rng('A')},{nome_ref})",
                    f"=SUMIFS({rng('S')},{rng('A')},{nome_ref})",
                    p["pendentes"], p["obs"]]
            for j, v in enumerate(vals, 1):
                wsc.cell(row=r, column=j, value=v)
            estilo_linha(wsc, r, len(cols_c), FILL_AVISO if p["pendentes"] else None)
            for j in range(5, 11):
                wsc.cell(row=r, column=j).number_format = "[h]:mm;-[h]:mm"
            r += 1
        last_c = r - 1
        wsc.cell(row=r, column=1, value="TOTAL")
        for j in range(3, 12):
            col = get_column_letter(j)
            wsc.cell(row=r, column=j, value=f"=SUM({col}{HEAD_C + 1}:{col}{last_c})")
        estilo_linha(wsc, r, len(cols_c), FILL_TITULO)
        for j in range(1, len(cols_c) + 1):
            wsc.cell(row=r, column=j).font = Font(name=FONT, bold=True, size=10)
        for j in range(5, 11):
            wsc.cell(row=r, column=j).number_format = "[h]:mm;-[h]:mm"
        wsc.cell(row=r + 2, column=1, value="Atenção: jornadas com status 'Pendente/Incompleto' no Flit ainda não foram tratadas "
                                            "pelo gestor e podem alterar os totais. Confira em Frequência > Ajustes de jornadas antes de enviar à contabilidade.")
        wsc.cell(row=r + 2, column=1).font = Font(name=FONT, italic=True, size=9, color="C00000")
        wsc.freeze_panes = wsc.cell(row=HEAD_C + 1, column=2)

    # ---------------- Regras
    wsg = wb.create_sheet("Regras")
    titulo(wsg, "Regras usadas na auditoria")
    linhas = [
        ("Tolerância de entrada/saída", f"{REGRAS['tolerancia_min']} min (mesma tolerância configurada no Flit)"),
        ("Entrada antecipada / saída após o horário", f"informativo acima de {REGRAS['entrada_antecipada_min']} min"),
        ("Intervalo mínimo", f"{REGRAS['intervalo_min']} min (CLT art. 71 - jornada acima de 6h): aviso entre {REGRAS['intervalo_alerta_min']} e 59 min, alerta abaixo de {REGRAS['intervalo_alerta_min']} min"),
        ("Intervalo fora do horário previsto", f"informativo quando começa mais de {REGRAS['intervalo_desloc_min']} min antes/depois do previsto"),
        ("Interjornada mínima", f"{REGRAS['interjornada_min_h']}h (CLT art. 66)"),
        ("Sobrecarga diária", f"acima de {REGRAS['sobrecarga_dia_h']}h trabalhadas (8h + 2h extras, CLT art. 59)"),
        ("Hora extra diária", f"alerta acima de {REGRAS['he_dia_h']}h"),
        ("Carga semanal", f"aviso acima de {REGRAS['semana_aviso_h']}h; alerta acima de {REGRAS['semana_alerta_h']}h"),
        ("Folga semanal", "alerta quando trabalha os 7 dias da semana (DSR)"),
        ("Faltas (semanal)", f"1 dia sem marcação = provável folga não lançada no Flit (aviso); {REGRAS['faltas_alerta']} ou mais = alerta"),
        ("Jornada pendente/incompleta", "status diferente de 'Verificado' no Flit = alerta (tratar em Ajustes de jornadas)"),
        ("Marcação ímpar", "1, 3 ou 5 marcações no dia = falta entrada ou saída"),
        ("Fonte dos dados", "Flit Gestor > Relatórios > Relatórios adicionais > modelo 'Apuração de jornadas'"),
        ("Observação importante", "As escalas cadastradas no Flit não têm folga (7 dias 'Dia trabalhado'). Enquanto as folgas não forem lançadas "
                                  "em Férias e folgas / Lançamentos, cada folga real aparece como 'Falta' e gera horas negativas."),
    ]
    for i, (a, b) in enumerate(linhas, 3):
        wsg.cell(row=i, column=1, value=a).font = Font(name=FONT, bold=True, size=10)
        wsg.cell(row=i, column=2, value=b).font = Font(name=FONT, size=10)
        wsg.cell(row=i, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    wsg.column_dimensions["A"].width = 38
    wsg.column_dimensions["B"].width = 110

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
    wb.save(saida)


# ----------------------------------------------------------------------------- resumo texto
def resumo_texto(modo, inicio, fim, resumo, alertas):
    periodo = f"{inicio.strftime('%d/%m')} a {fim.strftime('%d/%m/%Y')}"
    n_al = sum(1 for a in alertas if a["grav"] == "ALERTA")
    n_av = sum(1 for a in alertas if a["grav"] == "AVISO")
    pessoas_al = sorted({a["nome"] for a in alertas if a["grav"] == "ALERTA"})
    pend = sum(p["pendentes"] for p in resumo)
    faltas = sum(p["faltas"] for p in resumo)
    linhas = [f"{'Auditoria semanal' if modo == 'semanal' else 'Fechamento mensal'} de ponto - {periodo}",
              f"{len(resumo)} colaboradores | {n_al} alertas | {n_av} avisos | {pend} jornadas pendentes no Flit | {faltas} dias sem marcação"]
    tipos = Counter(a["tipo"] for a in alertas if a["grav"] == "ALERTA")
    if tipos:
        linhas.append("Alertas por tipo: " + ", ".join(f"{t} ({n})" for t, n in tipos.most_common()))
    if pessoas_al:
        linhas.append("Colaboradores com alerta: " + ", ".join(pessoas_al))
    return "\n".join(linhas)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Auditoria de ponto Tili Pizzaria (Flit)")
    ap.add_argument("--modo", choices=["semanal", "mensal"], required=True)
    ap.add_argument("--apuracao", required=True, help="xlsx 'Apuração de jornadas' exportado do Flit")
    ap.add_argument("--inicio", required=True, help="DD/MM/AAAA")
    ap.add_argument("--fim", required=True, help="DD/MM/AAAA")
    ap.add_argument("--saida", required=True, help="caminho do xlsx de saída")
    args = ap.parse_args()

    inicio, fim = parse_date(args.inicio), parse_date(args.fim)
    dados = ler_apuracao(args.apuracao)
    if not dados:
        sys.exit("Relatório de apuração vazio.")
    datas = sorted({d["data"] for d in dados})
    if datas[0] > inicio or datas[-1] < fim:
        print(f"AVISO: o relatório cobre {datas[0]} a {datas[-1]}, período pedido {inicio} a {fim}.", file=sys.stderr)
    resumo, alertas, detalhe = consolidar(dados, inicio, fim, args.modo)
    gerar_excel(args.saida, args.modo, inicio, fim, resumo, alertas, detalhe, args.apuracao.split("/")[-1])
    print(resumo_texto(args.modo, inicio, fim, resumo, alertas))
    print(f"\nArquivo gerado: {args.saida}")


if __name__ == "__main__":
    main()
