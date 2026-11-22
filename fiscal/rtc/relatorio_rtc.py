"""Gera conferencia_rtc.xlsx e conferencia_rtc.pdf a partir de conferencia_rtc.json."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

AVISO = ("pIBSSN e pCBSSN usados no teste (1,25% e 2,75%) são fictícios: as alíquotas reais saem do PGDAS-D. "
         "O objetivo é validar cadastro e classificação, não o valor do imposto.")
VERM = "B71C1C"


def brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_ncm(n: str) -> str:
    return f"{n[:4]}.{n[4:6]}.{n[6:]}" if len(n) == 8 else (n or "—")


def resumo(itens):
    r = defaultdict(lambda: defaultdict(int))
    for it in itens:
        for k in (it["loja"], "Total"):
            r[k]["total"] += 1
            r[k]["calc_ok"] += it["calc_ok"]
            r[k]["calc_erro"] += not it["calc_ok"]
            r[k]["sem_ncm"] += not it["ncm"]
            r[k]["ncm_generico"] += "NCM a corrigir" in it["problemas"]
            r[k]["decidir"] += bool(it["grupo"])
            r[k]["ok"] += not it["problemas"] and not it["grupo"]
            r[k]["problema"] += bool(it["problemas"])
    return r


def gerar(caminho: Path) -> None:
    d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    itens, base, info, erros = d["itens"], d["base"], d["info"], d["erros"]
    pasta = Path(caminho).parent
    r = resumo(itens)
    hdr = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor=VERM)

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Conferência do cardápio na calculadora oficial da Reforma Tributária (Simples Nacional)"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Data simulada {d.get('data', '2027-03-01')} · NFC-e (65) · CRT 1 · cAtivSN 01 · base oficial {base['versao']} · vendas {d['periodo'][0]} a {d['periodo'][1]}"])
    ws.append([AVISO])
    ws.append([])
    cab = ["Loja", "Produtos ativos", "OK (sem nada a corrigir)", "Com problema", "Sem NCM", "NCM genérico em bebida/sorvete",
           "Calculadora OK (200047 e 000001)", "Calculadora com erro", "A decidir com o contador", "Combos ativos (não testados)"]
    ws.append(cab)
    for c in ws[5]:
        c.font, c.fill = hdr, fill
    for loja in ("Pizzaria", "Sushi", "Total"):
        x = r[loja]
        cmb = sum(v.get("combos_ativos", 0) for v in info.values()) if loja == "Total" else info[loja].get("combos_ativos", 0)
        ws.append([loja, x["total"], x["ok"], x["problema"], x["sem_ncm"], x["ncm_generico"], x["calc_ok"], x["calc_erro"], x["decidir"], cmb])
    ws.append([])
    for loja, v in info.items():
        ws.append([f"{loja}: regime no ALIV = {v['regime']} → CRT {v['crt']}. Campos de IBS/CBS no cadastro do produto: "
                   + (", ".join(v["campos_ibs_cbs"]) or "nenhum (não há cClassTrib, CST de IBS/CBS nem cAtivSN)")])
    for cc, v in base["classes"].items():
        ws.append([f"cClassTrib {cc}: " + (f"{v['descricao']} — CST {v['cst']} — aceito na NFC-e: {'sim' if v['nfce'] else 'NÃO'}" if v else "não encontrado na base")])
    if erros:
        ws.append(["Códigos de erro da calculadora: " + "; ".join(f"{k} = {t}" for k, t in erros.items())])
    ws.column_dimensions["A"].width = 14
    for col in range(2, 11):
        ws.column_dimensions[get_column_letter(col)].width = 17
    for row in ws.iter_rows(min_row=5, max_row=5):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")

    ws2 = wb.create_sheet("Itens")
    cab2 = ["Loja", "ID", "Produto", "Categoria", "NCM", "CFOP", "Un.", "Preço testado", "Resultado 200047", "Resultado 000001",
            "Erro / problema", "Obs.", "Qtd 30 dias", "Venda 30 dias (R$)"]
    ws2.append(cab2)
    for c in ws2[1]:
        c.font, c.fill = hdr, fill
    for it in sorted(itens, key=lambda i: (i["loja"], -i["venda30"])):
        ws2.append([it["loja"], it["id"], it["produto"] + (f" ({it['tamanho']})" if it["tamanho"] else ""), it["categoria"],
                    it["ncm"] or "SEM NCM", it["cfop"], it["uom"], round(it["preco_teste"], 2),
                    it["res_200047"] + (f" {','.join(it['err_200047'])}" if it["err_200047"] else ""),
                    it["res_000001"] + (f" {','.join(it['err_000001'])}" if it["err_000001"] else ""),
                    it["problemas"], it.get("obs", ""), round(it["qtd30"], 1), round(it["venda30"], 2)])
    ws2.auto_filter.ref = ws2.dimensions
    ws2.freeze_panes = "A2"
    for col, w in zip("ABCDEFGHIJKLMN", (9, 8, 46, 26, 11, 6, 5, 10, 16, 16, 48, 30, 10, 14)):
        ws2.column_dimensions[col].width = w

    ws3 = wb.create_sheet("NCMs usados")
    ws3.append(["NCM", "Descrição oficial (base da Receita)", "Nº de produtos", "Exemplos"])
    for c in ws3[1]:
        c.font, c.fill = hdr, fill
    por = defaultdict(list)
    for it in itens:
        por[it["ncm"] or "SEM NCM"].append(it)
    for n, lst in sorted(por.items(), key=lambda kv: -len(kv[1])):
        desc = base["ncms"].get(n) if n != "SEM NCM" else "—"
        ws3.append([n, desc or "NÃO ENCONTRADO / fora de vigência em 01/03/2027", len(lst),
                    "; ".join(i["produto"] for i in sorted(lst, key=lambda i: -i["venda30"])[:8])])
    for col, w in zip("ABCD", (11, 50, 14, 110)):
        ws3.column_dimensions[col].width = w

    ws4 = wb.create_sheet("A decidir com o contador")
    ws4.append(["LC 214/2025, art. 273, §2º: itens revendidos sem preparo e bebidas alcoólicas ficam fora do regime de bares e restaurantes."])
    ws4.append(["Loja", "ID", "Produto", "Categoria", "Grupo", "NCM no ALIV", "NCM a conferir (sugestão)", "Motivo", "Venda 30 dias (R$)"])
    for c in ws4[2]:
        c.font, c.fill = hdr, fill
    for it in sorted([i for i in itens if i["grupo"]], key=lambda i: (i["grupo"], -i["venda30"])):
        ws4.append([it["loja"], it["id"], it["produto"], it["categoria"], it["grupo"], it["ncm"], it["ncm_sugerido"],
                    it["motivo"], round(it["venda30"], 2)])
    for col, w in zip("ABCDEFGHI", (9, 8, 46, 22, 20, 11, 30, 44, 14)):
        ws4.column_dimensions[col].width = w
    wb.save(pasta / "conferencia_rtc.xlsx")

    # ---------------------------------------------------------------- PDF
    ss = getSampleStyleSheet()
    p = ParagraphStyle("p", parent=ss["Normal"], fontSize=8.5, leading=11)
    h = ParagraphStyle("h", parent=ss["Heading2"], fontSize=11, textColor=colors.HexColor("#" + VERM), spaceAfter=3, spaceBefore=6)
    doc = SimpleDocTemplate(str(pasta / "conferencia_rtc.pdf"), pagesize=A4, leftMargin=1.4 * cm, rightMargin=1.4 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    el = [Paragraph("<b>Tili — cardápio × Reforma Tributária (NFC-e a partir de 01/03/2027)</b>", ss["Title"]),
          Paragraph(f"Calculadora oficial da Receita (Simples Nacional v1.0.2, base {base['versao']}) · NFC-e · CRT 1 · "
                    f"cAtivSN 01 · vendas de {d['periodo'][0]} a {d['periodo'][1]}. <i>{AVISO}</i>", p)]
    t = [["Loja", "Produtos", "OK", "Com problema", "Sem NCM", "NCM genérico", "Calc. com erro", "A decidir"]]
    for loja in ("Pizzaria", "Sushi", "Total"):
        x = r[loja]
        t.append([loja, x["total"], x["ok"], x["problema"], x["sem_ncm"], x["ncm_generico"], x["calc_erro"], x["decidir"]])
    tb = Table(t, hAlign="LEFT")
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + VERM)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
    el += [Spacer(1, 4), tb, Paragraph("O que corrigir no cadastro fiscal do ALIV", h)]
    for linha in d.get("conclusoes", []):
        el.append(Paragraph("• " + linha, p))
    el.append(Paragraph("Problemas ordenados por venda (30 dias)", h))
    probs = sorted([i for i in itens if i["problemas"]], key=lambda i: -i["venda30"])
    t2 = [["Loja", "Produto", "NCM", "Problema", "Venda 30d"]]
    for it in probs[:40]:
        t2.append([it["loja"], Paragraph(it["produto"][:60], p), it["ncm"] or "—", Paragraph(it["problemas"], p), brl(it["venda30"])])
    if len(probs) > 40:
        t2.append(["", f"+ {len(probs) - 40} itens na planilha (aba Itens)", "", "", ""])
    tb2 = Table(t2, colWidths=[1.6 * cm, 6.2 * cm, 1.8 * cm, 6.4 * cm, 2.2 * cm], repeatRows=1)
    tb2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#" + VERM)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                             ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (-1, 0), (-1, -1), "RIGHT")]))
    el.append(tb2)
    doc.build(el)


if __name__ == "__main__":
    import sys
    gerar(Path(sys.argv[1]))
