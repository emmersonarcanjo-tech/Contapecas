#!/usr/bin/env python3
"""Relatório semanal do iFood (Pizzaria, Burguer, Pizzaria 2.0 e Sushi) em PDF.

Pedido do Emerson (15/11/2026): toda segunda às 09:00, semana anterior (seg–dom),
com vendas, descontos, comissão, taxas, anúncios, antecipação e repasse de cada loja
iFood — e a VERIFICAÇÃO DAS TAXAS contra o contrato (monitor/ifood/contrato.json):
  - comissão: % sobre (itens + entrega − desconto da loja), pedido a pedido;
  - taxa de transação: % sobre o valor pago online (cliente + subsídio do iFood),
    por forma de pagamento. Pix online = 1% pelo contrato.
Diferença cobrada a mais aparece em R$ (para contestar com o iFood).

Fonte: conciliação iFood do ALIV (/admin/api/finance/ifood/{merchant}/vendas,
/lancamentos e /antecipacoes) — só leitura. Envia o PDF para WHATSAPP_EMERSON.

Uso: ifood_semanal.py [--inicio AAAA-MM-DD --fim AAAA-MM-DD] [--whatsapp] [--pdf PASTA]
Saída: 0 ok, 1 erro no ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import TZ, Aliv, AlivError, brl  # noqa: E402

CONTRATO = Path(__file__).resolve().parent / "ifood" / "contrato.json"
LOJAS = {"Pizzaria": ("ALIV_USER", "ALIV_PASS"), "Sushi": ("ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")}
NOMES = {"TILI PIZZARIA": "Tili Pizzaria", "Tili Burguer": "Tili Burguer", "Tili Pizzaria 2.0": "Tili Pizzaria 2.0"}
VERMELHO, DOURADO = "#C8102E", "#D4A017"
METODO = {"PIX": "Pix", "Crédito": "Crédito", "Débito": "Débito", "Carteira digital": "Carteira digital",
          "Pagamento pelo banco": "Pagto. pelo banco", "Vale-refeição": "Vale-refeição"}


def pct(v: float) -> str:
    return f"{v:.2f}%".replace(".", ",")


def contrato() -> dict:
    try:
        return json.loads(CONTRATO.read_text())
    except (OSError, json.JSONDecodeError):
        return {"comissao_pct": None, "taxa_transacao_pct": {"PIX": 1.0}}


def analisar(api: Aliv, mid: str, nome: str, ini: date, fim: date, ct: dict) -> dict:
    q = {"inicio": ini.isoformat(), "fim": fim.isoformat(), "homologacao": 0}
    v = api.get(f"/admin/api/finance/ifood/{mid}/vendas", q)
    peds = v.get("pedidos") or []
    t = v.get("totais") or {}
    r = {"nome": nome, "pedidos": len(peds), "cancelados": sum(1 for p in peds if p.get("cancelado")),
         "nao_faturados": sum(1 for p in peds if not p.get("faturado") and not p.get("cancelado")),
         "bruto": t.get("bruto_itens", 0), "entrega": t.get("taxa_entrega", 0), "pago": t.get("pago_cliente", 0),
         "desc_loja": t.get("beneficios_loja", 0), "desc_ifood": t.get("beneficios_ifood", 0),
         "comissao": -t.get("comissoes", 0), "taxas": -t.get("taxas", 0), "repasse": t.get("repasse", 0),
         "reembolsos": sum(p.get("reembolso_cliente") or 0 for p in peds)}
    # comissão pedido a pedido
    com_cob = com_base = 0.0
    tx = defaultdict(lambda: [0.0, 0.0, 0])          # método → [taxa, base, pedidos]
    for p in peds:
        if not p.get("faturado") or p.get("cancelado"):
            continue
        L = defaultdict(float)
        for x in p.get("lancamentos") or []:
            L[x.get("nome")] += float(x.get("valor") or 0)
        c = -L["ORDER_COMMISSION"]
        if c:
            com_cob += c
            com_base += (p.get("bruto_itens") or 0) + (p.get("taxa_entrega") or 0) - (p.get("beneficios_loja") or 0)
        taxa = -L["PAYMENT_TRANSACTION_FEE"]
        online = [g for g in p.get("pagamentos") or [] if g.get("tipo") == "Online"]
        if taxa and len(online) == 1:
            k = online[0].get("metodo") or "?"
            tx[k][0] += taxa
            tx[k][1] += (p.get("pago_cliente") or 0) + (p.get("beneficios_ifood") or 0)
            tx[k][2] += 1
    r["com_efetiva"] = 100 * com_cob / com_base if com_base else None
    c_pct = ct.get("comissao_pct")
    r["com_excesso"] = (com_cob - com_base * c_pct / 100) if (c_pct and com_base) else None
    r["taxas_metodo"] = []
    contr = ct.get("taxa_transacao_pct") or {}
    for k, (tv, base, n) in sorted(tx.items(), key=lambda x: -x[1][1]):
        alvo = contr.get(k, contr.get("padrao"))
        exc = tv - base * alvo / 100 if alvo is not None else None
        r["taxas_metodo"].append({"metodo": METODO.get(k, k), "pedidos": n, "base": base, "cobrado": tv,
                                  "efetiva": 100 * tv / base if base else 0, "contrato": alvo, "excesso": exc})
    # anúncios e outras ocorrências (lançamentos do período)
    lanc = api.get(f"/admin/api/finance/ifood/{mid}/lancamentos", q).get("lancamentos") or []
    r["anuncios"] = -sum(x["valor"] for x in lanc if "Anúncio" in (x.get("rotulo") or ""))
    r["ocorrencias"] = [(x["data"][:10], x["rotulo"], x["valor"]) for x in lanc
                        if x.get("ocorrencia") and "Anúncio" not in (x.get("rotulo") or "")]
    # antecipações feitas na semana
    # a API devolve as antecipações pela semana de VENDA (apuração); a antecipação de uma semana
    # acontece na semana seguinte. Busca as 3 semanas anteriores e fica com as feitas nesta semana.
    an = []
    for k in (1, 2, 3):
        an += api.get(f"/admin/api/finance/ifood/{mid}/antecipacoes",
                      {"inicio": (ini - timedelta(days=7 * k)).isoformat(),
                       "fim": (fim - timedelta(days=7 * k)).isoformat(), "homologacao": 0}).get("itens") or []
    feitas = [i for i in an if ini.isoformat() <= str(i.get("data_antecipada") or "")[:10] <= fim.isoformat()]
    r["antecipado"] = sum(i.get("valor_original") or 0 for i in feitas)
    r["antecipacao_taxa"] = sum(i.get("taxa") or 0 for i in feitas)
    r["antecipacao_pct"] = feitas[0].get("taxa_pct") if feitas else None
    return r


def html_relatorio(lojas: list[dict], ini: date, fim: date, agora: datetime, ct: dict) -> str:
    T = lambda k: sum((x.get(k) or 0) for x in lojas)  # noqa: E731
    exc_tx = sum(m["excesso"] for x in lojas for m in x["taxas_metodo"] if m["excesso"] and m["excesso"] > 0)
    exc_com = sum(x["com_excesso"] for x in lojas if x["com_excesso"] and x["com_excesso"] > 0.5)
    custo = T("comissao") + T("taxas") + T("desc_loja") + T("anuncios") + T("antecipacao_taxa")
    alertas = []
    for x in lojas:
        for m in x["taxas_metodo"]:
            if m["excesso"] and m["excesso"] > 1:
                alertas.append(f"{x['nome']}: {m['metodo']} cobrado a {pct(m['efetiva'])} (contrato {pct(m['contrato'])}) "
                               f"— {brl(m['excesso'])} a mais em {m['pedidos']} pedidos")
        if x["com_excesso"] and x["com_excesso"] > 1:
            alertas.append(f"{x['nome']}: comissão {pct(x['com_efetiva'])} (contrato {pct(ct['comissao_pct'])}) "
                           f"— {brl(x['com_excesso'])} a mais")
        if x["anuncios"]:
            alertas.append(f"{x['nome']}: pacote de anúncios {brl(x['anuncios'])}")
        if x["antecipacao_taxa"]:
            alertas.append(f"{x['nome']}: antecipação de {brl(x['antecipado'])} custou {brl(x['antecipacao_taxa'])}"
                           + (f" ({pct(x['antecipacao_pct'])})" if x["antecipacao_pct"] else ""))
        for d, rot, v in x["ocorrencias"]:
            alertas.append(f"{x['nome']}: {rot} {brl(v)} em {d[8:10]}/{d[5:7]}")
    linhas = "".join(
        f"<tr><td><b>{html.escape(x['nome'])}</b></td><td class=n>{x['pedidos']}</td><td class=n>{brl(x['pago'])}</td>"
        f"<td class=n>{brl(x['desc_loja'])}</td><td class=n>{brl(x['comissao'])}</td><td class=n>{brl(x['taxas'])}</td>"
        f"<td class=n>{brl(x['anuncios'] + x['antecipacao_taxa'])}</td><td class=n><b>{brl(x['repasse'])}</b></td></tr>"
        for x in lojas)
    linhas += (f"<tr class=tot><td>Total</td><td class=n>{T('pedidos')}</td><td class=n>{brl(T('pago'))}</td>"
               f"<td class=n>{brl(T('desc_loja'))}</td><td class=n>{brl(T('comissao'))}</td><td class=n>{brl(T('taxas'))}</td>"
               f"<td class=n>{brl(T('anuncios') + T('antecipacao_taxa'))}</td><td class=n><b>{brl(T('repasse'))}</b></td></tr>")
    verif = []
    for x in lojas:
        rows = "".join(
            f"<tr{' class=ruim' if m['excesso'] and m['excesso'] > 1 else ''}><td>{html.escape(m['metodo'])}</td>"
            f"<td class=n>{m['pedidos']}</td><td class=n>{brl(m['base'])}</td><td class=n>{brl(m['cobrado'])}</td>"
            f"<td class=n>{pct(m['efetiva'])}</td><td class=n>{pct(m['contrato']) if m['contrato'] is not None else '—'}</td>"
            f"<td class=n>{brl(m['excesso']) if m['excesso'] and m['excesso'] > 0.005 else '—'}</td></tr>"
            for m in x["taxas_metodo"])
        com = (f"Comissão cobrada: <b>{pct(x['com_efetiva'])}</b> sobre itens + entrega − desconto da loja"
               + (f" · contrato {pct(ct['comissao_pct'])}" if ct.get("comissao_pct") else "") if x["com_efetiva"] else "")
        verif.append(f"<h3>{html.escape(x['nome'])}</h3><p class=c>{com}</p><table><thead><tr><th>Pagamento online</th>"
                     f"<th class=n>Pedidos</th><th class=n>Base</th><th class=n>Taxa cobrada</th><th class=n>% cobrado</th>"
                     f"<th class=n>% contrato</th><th class=n>A mais</th></tr></thead><tbody>{rows}</tbody></table>")
    css = f"""
    @page {{ size: A4; margin: 11mm 10mm }} * {{ box-sizing: border-box }}
    body {{ font-family: "Liberation Sans", Arial, sans-serif; font-size: 10.5pt; color: #111; margin: 0 }}
    .faixa {{ height: 6px; background: linear-gradient(90deg,{VERMELHO} 0 62%,{DOURADO} 62% 100%) }}
    h1 {{ color: {VERMELHO}; font-size: 19pt; margin: 8px 0 0 }} h1 span {{ color: #111 }}
    .sub {{ color: #555 }} h2 {{ font-size: 12.5pt; border-bottom: 2px solid {DOURADO}; margin: 14px 0 6px }}
    h3 {{ font-size: 11pt; margin: 10px 0 2px }} .c {{ margin: 0 0 4px; font-size: 9.5pt }}
    .cards {{ display: flex; gap: 8px; margin-top: 10px }} .card {{ flex: 1; border: 1px solid #ddd; border-top: 4px solid {DOURADO};
      border-radius: 6px; padding: 6px 8px }} .card.v {{ border-top-color: {VERMELHO} }}
    .card .r {{ font-size: 8.5pt; color: #555 }} .card .val {{ font-size: 14pt; font-weight: bold }}
    table {{ width: 100%; border-collapse: collapse }} th {{ font-size: 8.5pt; color: #555; text-align: left; border-bottom: 1px solid #999; padding: 3px }}
    td {{ border-bottom: 1px solid #e3e3e3; padding: 3px }} .n {{ text-align: right; white-space: nowrap }}
    tr.tot td {{ font-weight: bold; border-top: 2px solid #111 }} tr.ruim td {{ background: #fde8eb }}
    ul {{ margin: 4px 0 0 16px; padding: 0 }} li {{ margin: 2px 0 }}
    footer {{ margin-top: 12px; font-size: 8pt; color: #777 }}
    """
    return (f"<!doctype html><html lang=pt-br><head><meta charset=utf-8><style>{css}</style></head><body>"
            f"<div class=faixa></div><h1>Tili <span>· iFood da semana</span></h1>"
            f"<div class=sub>{ini:%d/%m} a {fim:%d/%m/%Y} · Pizzaria, Burguer, Pizzaria 2.0 e Sushi</div>"
            f"<div class=cards><div class=card><div class=r>Pedidos</div><div class=val>{T('pedidos')}</div></div>"
            f"<div class=card><div class=r>Clientes pagaram</div><div class=val>{brl(T('pago'))}</div></div>"
            f"<div class=card><div class=r>Custo iFood total*</div><div class=val>{brl(custo)}</div></div>"
            f"<div class='card v'><div class=r>Repasse líquido</div><div class=val>{brl(T('repasse'))}</div></div>"
            f"<div class='card v'><div class=r>Cobrado a mais</div><div class=val>{brl(exc_tx + exc_com)}</div></div></div>"
            f"<h2>Por loja</h2><table><thead><tr><th>Loja</th><th class=n>Pedidos</th><th class=n>Cliente pagou</th>"
            f"<th class=n>Desc. loja</th><th class=n>Comissão</th><th class=n>Taxas</th><th class=n>Anúncio/antecip.</th>"
            f"<th class=n>Repasse</th></tr></thead><tbody>{linhas}</tbody></table>"
            f"<h2>Alertas</h2>" + ("<ul>" + "".join(f"<li>{html.escape(a)}</li>" for a in alertas) + "</ul>"
                                   if alertas else "<p>Nenhum alerta na semana.</p>")
            + "<h2>Verificação das taxas × contrato</h2>" + "".join(verif)
            + f"<footer>* comissão + taxas + desconto bancado pela loja + anúncios + antecipação. Base da taxa de transação = "
              f"valor pago online (cliente + subsídio do iFood). Pedidos ainda não faturados pelo iFood ficam de fora da "
              f"verificação. Fonte: conciliação iFood do ALIV · gerado em {agora:%d/%m/%Y %H:%M}.</footer></body></html>")


def main() -> int:
    ap = argparse.ArgumentParser(description="Relatório semanal do iFood (PDF)")
    ap.add_argument("--inicio")
    ap.add_argument("--fim")
    ap.add_argument("--whatsapp", action="store_true")
    ap.add_argument("--pdf")
    a = ap.parse_args()
    agora = datetime.now(TZ)
    hoje = agora.date()
    ini = date.fromisoformat(a.inicio) if a.inicio else hoje - timedelta(days=hoje.weekday() + 7)
    fim = date.fromisoformat(a.fim) if a.fim else ini + timedelta(days=6)
    ct = contrato()
    lojas, api_envio = [], None
    try:
        for loja, (u, p) in LOJAS.items():
            api = Aliv(os.environ[u], os.environ[p])
            api_envio = api_envio or api
            for c in api.get("/admin/api/finance/ifood/contas").get("contas") or []:
                nome = NOMES.get(c.get("nome"), "Tili Sushi" if loja == "Sushi" else c.get("nome"))
                lojas.append(analisar(api, c["merchant_id"], nome, ini, fim, ct))
    except (AlivError, OSError, KeyError) as e:
        print(f"Tili — iFood semanal — ERRO no ALIV\n\n{e}")
        return 1
    from boletos import pdf
    destino = (Path(a.pdf) if a.pdf else Path(tempfile.mkdtemp())) / f"iFood_semana_{ini:%d-%m}_a_{fim:%d-%m}.pdf"
    pdf(html_relatorio(lojas, ini, fim, agora, ct), destino)
    exc = sum(m["excesso"] for x in lojas for m in x["taxas_metodo"] if m["excesso"] and m["excesso"] > 0)
    exc += sum(x["com_excesso"] for x in lojas if x["com_excesso"] and x["com_excesso"] > 0.5)
    texto = (f"📊 *iFood da semana* {ini:%d/%m} a {fim:%d/%m}: {sum(x['pedidos'] for x in lojas)} pedidos · "
             f"clientes pagaram {brl(sum(x['pago'] for x in lojas))} · repasse {brl(sum(x['repasse'] for x in lojas))}"
             + (f"\n⚠️ Cobrado a mais que o contrato: {brl(exc)}" if exc > 1 else "\n✅ Taxas conforme o contrato"))
    print(texto + f"\nPDF: {destino}")
    if a.whatsapp:
        try:
            api_envio.enviar_whatsapp(re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", "")), texto, arquivo=destino)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
