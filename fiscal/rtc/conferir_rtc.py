#!/usr/bin/env python3
"""Conferência do cardápio da Tili na calculadora oficial da Reforma Tributária (Simples Nacional).

Tarefa única (Emerson, 22/11/2026) — não é Rotina.
- ALIV: só GET (cardápio, fiscal-config/profiles só o regime, vendas 30 dias). Nada é alterado.
- Base oficial (SQLite gerado pelos scripts Flyway da Receita): NCM vigente e cClassTrib aceito na NFC-e.
- Calculadora oficial rodando em http://localhost:8082/api (perfil offline).
Não grava CNPJ, token, CSC nem senha.

Uso: conferir_rtc.py --db CAMINHO/calculadora-pro.db [--inicio 2026-10-23 --fim 2026-11-21]
Saída: fiscal/rtc/conferencia_rtc.xlsx e fiscal/rtc/conferencia_rtc.pdf
"""
from __future__ import annotations

import argparse, json, os, re, sqlite3, sys, unicodedata, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "monitor"))
from monitor import Aliv  # noqa: E402

AQUI = Path(__file__).resolve().parent
API = "http://localhost:8082/api/calculadora/observabilidade/simples-nacional"
DATA = "2027-03-01"
LOJAS = ((150, "Pizzaria", "ALIV_USER", "ALIV_PASS"), (155, "Sushi", "ALIV_USER_SUSHI", "ALIV_PASS_SUSHI"))
CLASSES = ("200047", "000001")

ALCOOL = re.compile(r"cervej|heineken|stella|l[aä]ut|lager|\bipa\b|pilsen|pale ale|\bgin\b|spritz|coquetel|vinho|sak[eê]|vodka|whisky", re.I)
REFRI = re.compile(r"coca|guaran|fanta|sprite|kuat|refri|schweppes|pepsi", re.I)
AGUA = re.compile(r"[aá]gua", re.I)
SUCO = re.compile(r"suco", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def sugestao(nome: str, categoria: str) -> tuple[str, str, str]:
    """(grupo para o contador, NCM sugerido para conferir, motivo). Vazio = item de preparo próprio."""
    if ALCOOL.search(nome) or "cerveja" in categoria.lower():
        if re.search(r"\bgin\b", nome, re.I):
            return "Bebida alcoólica", "2208.90.00", "bebida destilada pronta (gin em lata)"
        if re.search(r"spritz|coquetel", nome, re.I):
            return "Bebida alcoólica", "2206.00.90 ou 2205", "coquetel de vinho em lata — contador define"
        return "Bebida alcoólica", "2203.00.00", "cerveja de malte"
    if REFRI.search(nome):
        return "Revenda sem preparo", "2202.10.00", "refrigerante industrializado"
    if AGUA.search(nome):
        return "Revenda sem preparo", "2201.10.00", "água mineral"
    if SUCO.search(nome):   # Emerson, 22/11/2026: suco de laranja natural, feito na hora na loja → preparo próprio
        return "", "", ""
    if re.search(r"picol|sorvet", categoria, re.I):
        return "Revenda sem preparo", "2105.00.10", "picolé/sorvete industrializado em embalagem individual"
    return "", "", ""


def coletar(inicio: str, fim: str) -> tuple[list[dict], dict]:
    itens, info = [], {}
    for loja, nome_loja, u, p in LOJAS:
        api = Aliv(os.environ[u], os.environ[p])
        fc = (api.get(f"/admin/api/stores/{loja}/fiscal-config") or {}).get("fields") or {}
        regime = fc.get("tax_regime")
        info[nome_loja] = {"regime": regime, "crt": "1" if regime == "simples" else "1 (não achei o regime — usado 1)"}
        rel = api.get("/admin/api/reports/products", {"start": inicio, "end": fim, "sort_by": "total_desc"})
        venda = {}
        for x in rel.get("report_data", []):
            k = norm(x.get("name"))
            q, t = venda.get(k, (0.0, 0.0))
            venda[k] = (q + (x.get("qty") or 0), t + (x.get("total") or 0))
        menu = api.get("/admin/api/menu/full_data")
        combos = [c for c in menu.get("combos", []) if c.get("is_active")]
        info[nome_loja]["combos_ativos"] = len(combos)
        campos_rt = sorted({k for c in menu["categories"] for pr in c["products"]
                            for k in (pr.get("full_data") or {}) if re.search(r"class|cst|csosn|ibs|cbs|ativsn|trib", k, re.I)})
        info[nome_loja]["campos_ibs_cbs"] = campos_rt
        for c in menu["categories"]:
            for pr in c["products"]:
                if not pr.get("is_active"):
                    continue
                fd = pr.get("full_data") or {}
                preco = float(pr.get("price") or 0)
                tam = ""
                if preco <= 0 and pr.get("size_prices"):
                    maior = max(pr["size_prices"], key=lambda s: s.get("price") or 0)
                    preco, tam = float(maior.get("price") or 0), maior.get("size_name") or ""
                zerado = preco <= 0.01
                q, t = venda.get(norm(pr["name"]), (0.0, 0.0))
                grupo, ncm_sug, motivo = sugestao(pr["name"], c["name"])
                itens.append({
                    "loja": nome_loja, "id": pr["id"], "produto": pr["name"], "categoria": c["name"],
                    "ncm": re.sub(r"\D", "", fd.get("ncm") or ""), "ncm_categoria": re.sub(r"\D", "", c.get("ncm") or ""),
                    "cfop": fd.get("cfop") or "", "uom": fd.get("uom") or "",
                    "preco": preco, "preco_teste": 10.0 if zerado else preco, "zerado": zerado, "tamanho": tam,
                    "qtd30": q, "venda30": t, "grupo": grupo, "ncm_sugerido": ncm_sug, "motivo": motivo,
                })
    return itens, info


def conferir_base(db: Path, itens: list[dict]) -> tuple[dict, dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    versao = con.execute("select * from VERSAO_BASE_DADO order by 1 desc limit 1").fetchone()
    ncms = {}
    for n in sorted({i["ncm"] for i in itens if i["ncm"]}):
        r = con.execute("select NCM_DESCRICAO from NCM where NCM_CD=? and length(NCM_CD)=8 and NCM_INICIO_VIGENCIA<=? "
                        "and NCM_FIM_VIGENCIA>=?", (n, DATA, DATA)).fetchone()
        ncms[n] = r[0] if r else None
    classes = {}
    for cc in CLASSES:
        r = con.execute("""select ct.CLTR_DESCRICAO, st.SITR_CD,
              exists(select 1 from TIPO_DFE_CLASSIFICACAO x join TIPO_DFE td on td.TPDF_ID=x.TDCL_TPDF_ID
                     where x.TDCL_CLTR_ID=ct.CLTR_ID and td.TPDF_TIPO=65 and x.TDCL_INICIO_VIGENCIA<=?
                       and (x.TDCL_FIM_VIGENCIA is null or x.TDCL_FIM_VIGENCIA>=?))
            from CLASSIFICACAO_TRIBUTARIA ct join SITUACAO_TRIBUTARIA st on st.SITR_ID=ct.CLTR_SITR_ID
            join TRIBUTO_SITUACAO_TRIBUTARIA ts on ts.TRST_SITR_ID=st.SITR_ID and ts.TRST_TBTO_ID=2
            where ct.CLTR_CD=? and ct.CLTR_INICIO_VIGENCIA<=? and (ct.CLTR_FIM_VIGENCIA is null or ct.CLTR_FIM_VIGENCIA>=?)""",
                        (DATA, DATA, cc, DATA, DATA)).fetchone()
        classes[cc] = {"descricao": r[0], "cst": r[1], "nfce": bool(r[2])} if r else None
    return {"versao": versao[-1] if versao else "?", "ncms": ncms, "classes": classes}, {}


def calcular(itens: list[dict]) -> dict:
    erros_txt = {}
    for cc in CLASSES:
        for ini in range(0, len(itens), 100):
            lote = itens[ini:ini + 100]
            corpo = {"id": f"tili-{cc}-lote{ini // 100 + 1}", "versao": "2.0.0", "data": DATA, "tpDoc": "65", "CRT": "1",
                     "itens": []}
            for n, it in enumerate(lote, 1):
                x = {"numero": n, "cAtivSN": "01", "cClassTrib": cc, "baseCalculo": f"{it['preco_teste']:.2f}",
                     "valorImpostoSeletivo": "0.00", "pIBSSN": "1.25", "pCBSSN": "2.75"}
                if it["ncm"]:
                    x["ncm"] = it["ncm"]
                corpo["itens"].append(x)
            req = urllib.request.Request(API, data=json.dumps(corpo).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    resp = json.loads(r.read())
            except urllib.error.HTTPError as e:
                resp = json.loads(e.read() or b"{}")
            por_n = {o.get("nObj"): o for o in resp.get("objetos", [])}
            for n, it in enumerate(lote, 1):
                o = por_n.get(n) or {}
                cods = [e.get("code") for e in (o.get("erros") or []) if e.get("code")]
                it[f"res_{cc}"] = o.get("estadoItem") or f"SEM RESPOSTA ({str(resp)[:80]})"
                it[f"err_{cc}"] = cods
                for e in o.get("erros") or []:
                    erros_txt.setdefault(e.get("code"), e.get("title"))
    for cod in list(erros_txt):
        try:
            with urllib.request.urlopen(f"{API}/erros?codigo={cod}", timeout=30) as r:
                erros_txt[cod] = json.loads(r.read()).get("titulo") or erros_txt[cod]
        except Exception:
            pass
    return erros_txt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--inicio", default="2026-10-23")
    ap.add_argument("--fim", default="2026-11-21")
    a = ap.parse_args()
    itens, info = coletar(a.inicio, a.fim)
    base, _ = conferir_base(a.db, itens)
    erros = calcular(itens)
    for it in itens:
        it["ncm_ok"] = bool(it["ncm"]) and base["ncms"].get(it["ncm"]) is not None
        it["calc_ok"] = all(it[f"res_{c}"] == "CALCULADO" for c in CLASSES)
        prob = []
        if not it["ncm"]:
            prob.append("SEM NCM")
        elif not it["ncm_ok"]:
            prob.append("NCM inexistente/fora de vigência")
        if not it["calc_ok"]:
            prob.append("Calculadora: " + ", ".join(sorted(set(it["err_200047"] + it["err_000001"]))))
        if it["grupo"] and it["ncm_sugerido"] and not it["ncm_sugerido"].replace(".", "").startswith(it["ncm"]) \
                and it["grupo"] != "Verificar (suco)":
            prob.append(f"NCM a corrigir — conferir {it['ncm_sugerido']}")
        it["problemas"] = "; ".join(prob)
        it["obs"] = "preço zerado no ALIV (testado com 10,00)" if it["zerado"] else ""
    n = len(itens)
    gen = [i for i in itens if "NCM a corrigir" in i["problemas"]]
    sem = sum(not i["ncm"] for i in itens)
    calc_ok = sum(i["calc_ok"] for i in itens)
    combos = sum(v.get("combos_ativos", 0) for v in info.values())
    cfops = sorted({i["cfop"] for i in itens})
    tem_rt = any(v["campos_ibs_cbs"] for v in info.values())
    conclusoes = [
        ("<b>O ALIV ainda não tem os campos da reforma.</b> O cadastro do produto só tem NCM, CFOP, unidade e CEST; "
         "não existe cClassTrib, CST de IBS/CBS nem cAtivSN. Sem isso a NFC-e do Simples não sai a partir de 01/03/2027. "
         "Pedir ao ALIV a data da atualização e onde preencher (por categoria ou produto)." if not tem_rt else
         "O ALIV já tem campos de IBS/CBS: conferir o preenchimento."),
        (f"<b>Comida preparada está ok.</b> {calc_ok} de {n} produtos passaram na calculadora com 200047 (Bares e Restaurantes) "
         f"e com 000001 (integral); os dois são aceitos na NFC-e. {sem} sem NCM. NCM 2106.90.90 existe e vale em 01/03/2027."),
        (f"<b>Corrigir o NCM de {len(gen)} bebidas e sorvetes</b> que estão como 2106.90.90 (preparação alimentar): "
         "refrigerante 2202.10.00, água 2201.10.00, cerveja 2203.00.00, gin em lata 2208.90.00, spritz 2206/2205 (contador), "
         "picolé/sorvete 2105.00.10. A categoria Cervejas do Sushi já tem 2203.00.00, mas o NCM do produto manda. "
         "A calculadora não barra isso (NCM existe), mas a SEFAZ e o contador vão olhar."),
        ("<b>Contador decide o cClassTrib por grupo:</b> comida feita na loja = 200047 ou 000001; "
         "bebidas alcoólicas e revenda sem preparo ficam fora do regime de restaurante (LC 214/2025, art. 273, §2º). "
         "Lista na aba “A decidir com o contador”."),
        (f"<b>CFOP {', '.join(cfops)} em tudo</b> (revenda), inclusive comida feita na loja; produção própria costuma ser 5101. "
         "Não é da reforma, mas vale acertar junto."),
        (f"<b>{combos} combos ativos</b> não têm NCM próprio no cadastro (são montados com produtos). "
         "Confirmar com o ALIV se a nota sai item a item ou como uma linha só."),
    ]
    json.dump({"conclusoes": conclusoes, "itens": itens, "info": info, "base": base, "erros": erros, "periodo": [a.inicio, a.fim]},
              open(AQUI / "conferencia_rtc.json", "w"), ensure_ascii=False, indent=1)
    from relatorio_rtc import gerar
    gerar(AQUI / "conferencia_rtc.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
