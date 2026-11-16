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

Compras do Sushi nas notas da Pizzaria (Emerson, 16/11/2026): a Pizzaria compra no CNPJ dela
insumos que só o Sushi usa (salmão, embalagem oriental, arroz japonês, nori, shoyu/tarê, temperos
do sushi). Todo mês o script soma esses itens nas notas de compra da Pizzaria emitidas no mês
(só compra de verdade: bonificação e remessa ficam de fora; devolução abate) e lança, também sem banco:
  - Sushi: despesa "Compras do Sushi pagas pela Pizzaria MM/AAAA";
  - Pizzaria: entrada "Reembolso de compras — Sushi MM/AAAA".
Também são do Sushi (Emerson, 16/11/2026): camarão empanado, picolés/sorvetes e cervejas.
Itens que as duas lojas usam (cream cheese, camarão cru ou cozido, refrigerantes) NÃO entram.
O valor é pela data de emissão da nota. Se o mês já estiver lançado com outro valor, o script só avisa;
com --complemento "motivo" lança só a diferença, em lançamento novo, sem tocar no original.

Caminho inverso (Emerson, 16/11/2026): itens que só a Pizzaria usa (Catupiry, batata frita, fermento,
sachês de ketchup e maionese, manteiga) comprados no CNPJ do Sushi. Mesma conta nas notas do Sushi; lança, sem banco:
  - Pizzaria: despesa "Compras da Pizzaria pagas pelo Sushi MM/AAAA";
  - Sushi: entrada "Reembolso de compras — Pizzaria MM/AAAA".

Uso: rateio.py [--mes AAAA-MM] [--confirmar] [--whatsapp] [--so-compras] [--complemento MOTIVO]
     (padrão: mês passado)
     --so-compras: só as compras entre as lojas (para meses em que o rateio já foi lançado)
     --complemento: mês já lançado com valor menor → lança a diferença (só com o ok do Emerson)
Saída: 0 ok, 1 erro ALIV, 3 WhatsApp falhou.
"""
from __future__ import annotations

import argparse
import io
import unicodedata
import urllib.error
import urllib.request
import uuid
import calendar
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
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
CAT_COMPRAS_SUSHI = "Compras pagas pela Pizzaria"
CAT_COMPRAS_PIZ = "Reembolso de compras (Sushi)"
CAT_COMPRAS_INV_PIZ = "Compras pagas pelo Sushi"            # caminho inverso: despesa na Pizzaria
CAT_COMPRAS_INV_SUSHI = "Reembolso de compras (Pizzaria)"   # caminho inverso: entrada no Sushi
LOJA = {"piz": "Pizzaria", "sushi": "Sushi"}
NFE = "{http://www.portalfiscal.inf.br/nfe}"
# Itens que só o Sushi usa (nenhuma ficha da Pizzaria leva). Lista conferida nas notas de ago–nov/2026.
# De propósito ficam de fora: atum em lata, cream cheese, camarão, bebidas, cogumelos, gergelim e molhos comuns.
SO_SUSHI = [
    ("Salmão e peixes", r"\bSALMAO\b|\bSALMON\b|LOMBO (DE )?ATUM|ATUM FRESCO|\bTOBIKO\b|\bOVAS?\b|MASSAGO"),
    ("Embalagens orientais, hashi e potes", r"EMB\.? ?ORIENTAL|EMBALAGEM ORIENTAL|POTE ORIENTAL|EMBALAGEM COMBINADO|\bHASHI\b|\bGOHAN\b"),
    ("Arroz japonês", r"KOSHIHIKARI|JAPONICO|ARROZ (JAPONES|P/? ?SUSHI|CURTO)"),
    ("Alga nori", r"\bNORI\b|\bKOMBU\b|\bALGA\b"),
    ("Shoyu e tarê", r"\bSHOY[UO]\b|\bTARE\b|SASHIMI"),
    ("Temperos do sushi", r"TEMPERO (P/? ?|PARA )SUSHI|\bSAQUE\b|\bMIRIN\b|HONDASHI|\bWASS?ABI\b|GENGIBRE|VINAGRE.*ARROZ"),
    ("Outros do sushi", r"YAKIS+OBA|\bKANI\b|KANI-?KAMA|PEPINO JAPONES|\bSUDARE\b|PAPEL DE ARROZ|PANKO|GELEIA.*PIMENTA"),
    # Emerson, 16/11/2026: camarão empanado, picolés e cervejas comprados pela Pizzaria são do Sushi
    ("Camarão empanado", r"CAMARAO EMPANADO"),
    ("Picolés e sorvetes", r"\bPICOLE\b|\bSORVETE\b|^PALETA CX|^CONE CX"),
    ("Cervejas", r"\bCERVEJA\b|LONG NECK|\bHEINEKEN\b|STELLA ARTOIS|\bCORONA\b"),
]
# caminho inverso (Emerson, 16/11/2026): itens que só a Pizzaria usa, comprados no CNPJ do Sushi
SO_PIZZARIA = [
    ("Catupiry", r"REQUEIJAO.*CATUPIRY"),
    ("Batata frita", r"\bBATATA\b.*(FAST FOOD|\d+ ?MM|PALITO|PRE.?FRITA)"),
    ("Fermento", r"\bFERMENTO\b"),
    # Emerson, 16/11/2026: sachês de ketchup e maionese e manteiga comprados no CNPJ do Sushi são da Pizzaria
    ("Ketchup e maionese em sachê", r"(CATCHUP|KETCHUP|MAIONESE).*SACHE|SACHE.*(CATCHUP|KETCHUP|MAIONESE)"),
    ("Manteiga", r"\bMANTEIGA\b"),
]
# compra de verdade (inclui 5929/6929: nota de atacarejo sobre cupom); 59xx/69xx restantes = bonificação, remessa, comodato
CFOP_VENDA = {p + c for p in "56" for c in ("101", "102", "103", "104", "105", "106", "116", "117", "118", "119", "120",
                                             "122", "123", "401", "402", "403", "404", "405", "929")}
CFOP_DEVOLUCAO = {"1201", "1202", "1410", "1411", "2201", "2202", "2410", "2411"}      # o fornecedor recebe de volta: abate


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


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", s).strip()


def familia(nome: str, regras: list) -> str | None:
    """Família do item se ele casa com alguma regra da lista; None se não casa."""
    n = _sem_acento(nome)
    return next((fam for fam, rx in regras if re.search(rx, n)), None)


def familia_sushi(nome: str) -> str | None:
    """Família do item se ele é de uso só do Sushi; None se não é."""
    return familia(nome, SO_SUSHI)


def compras_do_sushi(api, ini: date, fim: date) -> dict:
    """Itens só do Sushi nas notas de compra da Pizzaria emitidas entre ini e fim."""
    return compras_da_outra_loja(api, ini, fim, SO_SUSHI, "Pizzaria")


def compras_da_pizzaria(api, ini: date, fim: date) -> dict:
    """Caminho inverso: itens só da Pizzaria nas notas de compra do Sushi emitidas entre ini e fim."""
    return compras_da_outra_loja(api, ini, fim, SO_PIZZARIA, "Sushi")


def compras_da_outra_loja(api, ini: date, fim: date, regras: list, dona: str) -> dict:
    """Itens que só a OUTRA loja usa (regras) nas notas de compra da loja `dona` (login `api`), pelo XML da nota."""
    req = urllib.request.Request(f"{BASE_URL}/admin/inventory/invoices/xml-zip?start={ini.isoformat()}&end={fim.isoformat()}")
    try:
        with api.opener.open(req, timeout=300) as r:
            bruto = r.read()
    except urllib.error.HTTPError as e:
        raise AlivError(f"não consegui baixar as notas da loja {dona} (HTTP {e.code})") from e
    try:
        z = zipfile.ZipFile(io.BytesIO(bruto))
    except zipfile.BadZipFile as e:
        raise AlivError(f"o ALIV não devolveu o arquivo das notas da loja {dona}") from e
    fam: dict[str, float] = {}
    itens: dict[str, float] = {}
    forn: dict[str, list] = {}          # fornecedor → [R$ da outra loja, {item que não entrou: R$}]
    vistas: set[str] = set()
    notas = nao_lidas = 0
    for nome in z.namelist():
        if not nome.lower().endswith(".xml"):
            continue
        try:
            x = ET.fromstring(z.read(nome))
        except ET.ParseError:
            nao_lidas += 1
            continue
        inf, ide = x.find(f".//{NFE}infNFe"), x.find(f".//{NFE}ide")
        if inf is None or ide is None:
            if x.find(f".//{NFE}infEvento") is None:        # evento (cancelamento, carta de correção) não é nota
                nao_lidas += 1
            continue
        chave = inf.get("Id") or nome
        emissao = (ide.findtext(f"{NFE}dhEmi") or ide.findtext(f"{NFE}dEmi") or "")[:10]
        if chave in vistas or not (ini.isoformat() <= emissao <= fim.isoformat()):
            continue
        vistas.add(chave)
        notas += 1
        f_nome = _sem_acento(x.findtext(f".//{NFE}emit/{NFE}xNome") or "")[:30]
        fx = forn.setdefault(f_nome, [0.0, {}])
        for det in x.iter(f"{NFE}det"):
            pr = det.find(f"{NFE}prod")
            if pr is None:
                continue
            cf = pr.findtext(f"{NFE}CFOP") or ""
            if cf not in CFOP_VENDA and cf not in CFOP_DEVOLUCAO:
                continue
            # valor do item = produto − desconto (frete e impostos por fora ficam na loja que comprou)
            v = float(pr.findtext(f"{NFE}vProd") or 0) - float(pr.findtext(f"{NFE}vDesc") or 0)
            if cf in CFOP_DEVOLUCAO:
                v = -v
            n = _sem_acento(pr.findtext(f"{NFE}xProd") or "")[:48]
            f = familia(n, regras)
            if not f:
                fx[1][n] = fx[1].get(n, 0.0) + v
                continue
            fam[f] = fam.get(f, 0.0) + v
            itens[n] = itens.get(n, 0.0) + v
            fx[0] += v
    if notas == 0:
        raise AlivError(f"não veio nenhuma nota da loja {dona} no arquivo do mês — conferir")
    # itens que NÃO entraram, de fornecedores em que a maior parte da compra é da outra loja: para o Emerson bater o olho
    fora: dict[str, float] = {}
    for da_outra, outros in forn.values():
        if da_outra > 0 and da_outra >= sum(outros.values()):
            for n, v in outros.items():
                fora[n] = fora.get(n, 0.0) + v
    # notas que o ALIV ainda não tem o XML (não vêm no arquivo): só aviso
    sem_xml = (0, 0.0)
    try:
        lst = api.get("/admin/inventory/invoices/list", {"start": ini.isoformat(), "end": fim.isoformat()})
        lst = lst if isinstance(lst, list) else (lst.get("invoices") or lst.get("data") or [])
        def _no_mes(x) -> bool:              # a lista devolve "dd/mm/aaaa" e nem sempre respeita o período pedido
            d = str(x.get("date") or "")
            iso = f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if len(d) >= 10 and d[2] == "/" else d[:10]
            return ini.isoformat() <= iso <= fim.isoformat()
        aw = [x for x in lst if str(x.get("status")) == "AWAITING_XML" and _no_mes(x)]
        sem_xml = (len(aw), sum(float(x.get("total") or 0) for x in aw))
    except (AlivError, OSError, ValueError, AttributeError):
        pass
    return {"total": round(sum(fam.values()), 2), "familias": fam, "itens": itens, "notas": notas, "nao_lidas": nao_lidas,
            "fora": sorted(fora.items(), key=lambda kv: -kv[1])[:8], "sem_xml": sem_xml}


def texto_compras(C: dict, mes: date, de: str = "Sushi", dona: str = "Pizzaria") -> str:
    """`de` = loja que usa os itens; `dona` = loja que comprou (em cujo CNPJ saiu a nota)."""
    art = "a" if de == "Pizzaria" else "o"
    L = [f"*Compras d{art} {de} nas notas d{'a' if dona == 'Pizzaria' else 'o'} {dona}* {mes:%m/%Y}: *{brl(C['total'])}*"
         f" (itens que só {art} {de} usa, em {C['notas']} notas lidas)"]
    L += [f"  • {f}: {brl(v)}" for f, v in sorted(C["familias"].items(), key=lambda kv: -kv[1])]
    if C.get("fora"):
        L.append(f"  Não entraram (mesmos fornecedores — avise se algum for só d{art} {de}): "
                 + "; ".join(f"{n.title()} {brl(v)}" for n, v in C["fora"]))
    if C.get("sem_xml", (0, 0))[0]:
        L.append(f"  ⚠️ {C['sem_xml'][0]} nota(s) sem XML no ALIV ({brl(C['sem_xml'][1])}) ficaram de fora — conferir na tela de notas")
    if C.get("nao_lidas"):
        L.append(f"  ⚠️ {C['nao_lidas']} arquivo(s) de nota não pude ler")
    return "\n".join(L)


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
    if nome not in cats:
        raise AlivError(f"não consegui criar a categoria '{nome}' no ALIV")
    return cats[nome]


def lancar(api, tipo: str, desc: str, valor: float, dia: date, cat: str, complemento: str = "") -> str:
    """Lança sem banco. Se o mês já tem lançamento com outro valor, só avisa — a não ser que venha `complemento`
    (motivo dito pelo Emerson): aí lança só a diferença, em lançamento novo, sem tocar no original."""
    b = api.get("/admin/finance/bills", {"bill_type": tipo, "status": "all"})
    b = b if isinstance(b, list) else b.get("bills", [])
    ja = [x for x in b if str(x.get("description")) == desc or str(x.get("description")).startswith(desc + " — complemento")]
    extra = ""
    if ja:
        try:
            antes = sum(float(x.get("amount") or 0) for x in ja)
        except (TypeError, ValueError):
            antes = valor
        dif = round(valor - antes, 2)
        if abs(dif) < 1:
            return "já lançado"
        if not complemento or dif < 0:     # mesmo mês, outro valor (nota atrasada, lista mudou): não mexo sozinho
            return f"já lançado com {brl(antes)} — agora deu {brl(valor)}: conferir"
        desc, valor, extra = f"{desc} — complemento ({complemento})", dif, f" complemento de {brl(dif)} (já havia {brl(antes)})"
    st, d = _form(api, "/admin/finance/bills/save", {
        "bill_type": tipo, "description": desc, "amount": f"{valor:.2f}", "due_date": dia.isoformat(),
        "payment_method": "Transferência interna", "category_id": _categoria(api, cat), "is_recurring": "false",
        "installments": "1", "pay_on_create": "true", "payment_origin": "none", "payment_date": dia.isoformat()})
    return f"✓{extra}" if st == 200 and isinstance(d, dict) and d.get("success") else f"ERRO {str(d)[:120]}"


def lancar_par(apis: dict, desc_paga: str, desc_recebe: str, valor: float, dia: date, cat_paga: str, cat_recebe: str,
               paga: str = "sushi", recebe: str = "piz", complemento: str = "") -> tuple[str, bool]:
    """Lança os dois lados sem banco: despesa na loja `paga` (padrão: Sushi) e entrada na loja `recebe`
    (padrão: Pizzaria). Devolve (texto, deu certo)."""
    np, nr = LOJA[paga], LOJA[recebe]
    try:
        _categoria(apis[paga], cat_paga)              # as duas categorias antes de gravar qualquer lado
        _categoria(apis[recebe], cat_recebe)
        r1 = lancar(apis[paga], "payable", desc_paga, valor, dia, cat_paga, complemento)
        if r1.startswith("ERRO"):
            return f"ALIV: {np} (despesa) {r1} · {nr} (reembolso) NÃO lançado — rodar de novo depois de conferir", False
        r2 = lancar(apis[recebe], "receivable", desc_recebe, valor, dia, cat_recebe, complemento)
    except (AlivError, OSError, KeyError, ValueError) as e:
        return f"ERRO ao lançar no ALIV: {e} — confira se ficou só um lado lançado (rodar de novo não duplica)", False
    ok = not (r2.startswith("ERRO") or "conferir" in r1 or "conferir" in r2)
    return f"ALIV: {np} (despesa) {r1} · {nr} (reembolso) {r2} — sem mexer em banco", ok


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
    ap.add_argument("--so-compras", action="store_true",
                    help="só as compras de uma loja nas notas da outra (rateio do mês já lançado)")
    ap.add_argument("--complemento", default="", metavar="MOTIVO",
                    help="se o mês já foi lançado com valor menor, lança só a diferença com este motivo (ex.: 'camarão empanado')")
    a = ap.parse_args()
    agora = datetime.now(TZ).replace(second=0, microsecond=0)
    mes = (date.fromisoformat(a.mes + "-01") if a.mes else (agora.date().replace(day=1) - timedelta(days=1)))
    ini = mes.replace(day=1)
    fim = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
    if a.confirmar and fim >= agora.date():
        print(f"Tili — Rateio — {ini:%m/%Y} ainda não terminou: não lanço mês incompleto.")
        return 1
    apis = {"piz": AlivSemanal(os.environ["ALIV_USER"], os.environ["ALIV_PASS"]),
            "sushi": AlivSemanal(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"])}
    try:
        for x in apis.values():
            x.login()
        R = None if a.so_compras else calcular(apis, mes, agora)
    except (AlivError, OSError) as e:
        print(f"Tili — Rateio — ERRO no ALIV\n\n{e}")
        return 1
    falhou = False
    partes = []
    if R is not None:
        t = texto(R)
        if a.confirmar and R["sushi"] > 0.009:
            r, ok = lancar_par(apis, f"Rateio de custos da Pizzaria {ini:%m/%Y}", f"Reembolso do rateio — Sushi {ini:%m/%Y}",
                               R["sushi"], fim, CAT_SUSHI, CAT_PIZ)
            falhou = falhou or not ok
            t += "\n" + r
        partes.append(t)
    try:                                            # depois do rateio: ele não depende das notas
        C = compras_do_sushi(apis["piz"], ini, fim)
        erro_compras = ""
    except Exception as e:  # noqa: BLE001 — qualquer problema nas notas vira aviso, não derruba a rotina
        C, erro_compras = None, f"{type(e).__name__}: {e}"[:200]
    if C is None:
        falhou = True
        partes.append(f"*Compras do Sushi nas notas da Pizzaria* {ini:%m/%Y}: ⚠️ não consegui ler as notas ({erro_compras}). Nada lançado.")
    elif C["total"] <= 0.009:
        partes.append(f"*Compras do Sushi nas notas da Pizzaria* {ini:%m/%Y}: nenhum item só do Sushi em {C['notas']} notas da Pizzaria.")
    else:
        t = texto_compras(C, ini)
        if a.confirmar:
            r, ok = lancar_par(apis, f"Compras do Sushi pagas pela Pizzaria {ini:%m/%Y}", f"Reembolso de compras — Sushi {ini:%m/%Y}",
                               C["total"], fim, CAT_COMPRAS_SUSHI, CAT_COMPRAS_PIZ, complemento=a.complemento)
            falhou = falhou or not ok
            t += "\n" + r
        partes.append(t)
    try:                                            # caminho inverso: itens só da Pizzaria nas notas do Sushi
        Ci = compras_da_pizzaria(apis["sushi"], ini, fim)
        erro_inv = ""
    except Exception as e:  # noqa: BLE001 — qualquer problema nas notas vira aviso, não derruba a rotina
        Ci, erro_inv = None, f"{type(e).__name__}: {e}"[:200]
    if Ci is None:
        falhou = True
        partes.append(f"*Compras da Pizzaria nas notas do Sushi* {ini:%m/%Y}: ⚠️ não consegui ler as notas ({erro_inv}). Nada lançado.")
    elif Ci["total"] > 0.009:
        t = texto_compras(Ci, ini, de="Pizzaria", dona="Sushi")
        if a.confirmar:
            r, ok = lancar_par(apis, f"Compras da Pizzaria pagas pelo Sushi {ini:%m/%Y}", f"Reembolso de compras — Pizzaria {ini:%m/%Y}",
                               Ci["total"], fim, CAT_COMPRAS_INV_PIZ, CAT_COMPRAS_INV_SUSHI, paga="piz", recebe="sushi",
                               complemento=a.complemento)
            falhou = falhou or not ok
            t += "\n" + r
        partes.append(t)
    t = "\n\n".join(partes)
    if not a.confirmar:
        t += "\n(teste — nada lançado)"
    print(t)
    if a.whatsapp:
        try:
            apis["piz"].enviar_whatsapp(re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", "")), t[:3800])
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
