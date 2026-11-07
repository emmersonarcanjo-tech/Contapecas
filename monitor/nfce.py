#!/usr/bin/env python3
"""NFC-e da Tili Pizzaria (loja 150) — lista do dia e emissão sob comando.

Dois subcomandos:

  listar  Lê os pedidos criados no dia, separa em EMITIR / NÃO EMITIR / ATENÇÃO
          pelas regras combinadas, grava monitor/nfce/AAAA-MM-DD.json e manda a
          lista pro WhatsApp do Emerson. NÃO emite nada. É o que a Rotina das
          23:50 roda.

  emitir  Emite as NFC-e da lista aprovada do dia (--data obrigatório). Só roda
          quando o Emerson manda "emite" numa sessão. Uma nota por vez, no máximo
          200. Com --dry-run não faz nenhum POST: só mostra o que faria.

Reaproveita o login (ALIV_USER / ALIV_PASS) e o envio por WhatsApp do monitor.py.
Nunca grava CNPJ, chave de acesso, token, CSC ou senha em arquivo, log ou commit:
a conferência de CNPJ (posições 7 a 20 da chave) é feita só em memória, contra
/admin/api/stores/150/fiscal-profiles e fiscal-config lidos na hora.

Uso:
  python3 monitor/nfce.py listar                         # hoje (antes das 04:00 vale ontem)
  python3 monitor/nfce.py listar --data 2026-11-06 --dry-run
  python3 monitor/nfce.py emitir --data 2026-11-06 --dry-run
  python3 monitor/nfce.py emitir --data 2026-11-06       # emite de verdade

Códigos de saída:
  0 ok (ou dry-run)
  1 erro de login/ALIV
  2 faltam ALIV_USER / ALIV_PASS
  3 tudo feito, mas o WhatsApp não aceitou a mensagem (a Rotina manda por e-mail)
  4 emissão interrompida por LIMIT_REACHED (pacote de notas esgotado)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, TZ, Aliv, AlivError, brl, lista_pedidos, num, parse_dt  # noqa: E402

PASTA = Path(__file__).resolve().parent / "nfce"
LOJA = 150
MAX_POR_EXECUCAO = 200
VIRADA_H = 4                 # antes das 04:00, "hoje" ainda é o dia anterior

STATUS_OK = {"CONCLUIDO", "ENTREGUE"}
FISCAL_PENDENTE = {"", "PENDENTE"}

# iFood: merchant → (nome, emite pagamento online iFood?)
IFOOD_PIZZARIA = "21f5f70c-dd67-4f86-b6b5-961ac09161ff"
IFOOD_BURGUER = "34e58883-b578-4dde-812f-95ca1a14d373"
IFOOD_PIZZARIA_20 = "c1577426-a0fd-420f-ad1e-cfbade3d7740"
MERCHANTS = {
    IFOOD_PIZZARIA: ("iFood Tili Pizzaria", False),
    IFOOD_BURGUER: ("iFood Tili Burguer", True),
    IFOOD_PIZZARIA_20: ("iFood Tili Pizzaria 2.0", True),
}
ORDEM_LOJAS = ["Loja (app próprio)", "Loja (PDV/balcão)", "iFood Tili Pizzaria",
               "iFood Tili Burguer", "iFood Tili Pizzaria 2.0"]

RE_REJ_CPF = re.compile(r"(cpf|cnpj|documento)[^.]{0,40}(destinat[aá]rio|inv[aá]lid)|destinat[aá]rio[^.]{0,30}inv[aá]lid", re.I)
RE_REJ_TROCO = re.compile(r"aus[eê]ncia de troco", re.I)


# ---------------------------------------------------------------- utilidades
def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def dm(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def hoje_operacional(agora: datetime) -> date:
    return agora.date() - timedelta(days=1) if agora.hour < VIRADA_H else agora.date()


def dig(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ---------------------------------------------------------------- pagamento
def partes_pagamento(texto: str) -> list[tuple[str, float | None]]:
    """'Dinheiro (Troco -> R$ 1.01): 3.99 (Troco: 0.00) | Pix: 25.00' → [(nome, valor), ...]."""
    out = []
    for parte in str(texto or "").split("|"):
        parte = parte.strip()
        if not parte:
            continue
        m = re.match(r"^(.*?):\s*(-?\d+(?:\.\d+)?)\s*(?:\(Troco:[^)]*\))?\s*$", parte)
        out.append((m.group(1).strip(), float(m.group(2))) if m else (parte, None))
    return out


def tipo_pagamento(nome: str) -> str:
    """dinheiro | pix | pix_online | pix_online_pendente | credito | debito | vale |
    ifood_online | bloqueado (fiado/carteira/conta func.) | aberto | desconhecido"""
    n = sem_acento(nome)
    if n.startswith("ifood online") or n == "ifood":
        return "ifood_online"
    if "fiado" in n or "carteira" in n or "conta func" in n or "saldo" in n:
        return "bloqueado"
    if "dinheiro" in n:
        return "dinheiro"
    if "pix online" in n:
        return "pix_online" if "pago" in n else "pix_online_pendente"
    if "pix" in n:
        return "pix"
    if "credito" in n:
        return "credito"
    if "debito" in n:
        return "debito"
    if re.search(r"alelo|ticket|\bvr\b|pluxee|sodexo|refeicao|alimentacao|\bvale\b|ben visa|caju|flash|swile", n):
        return "vale"
    if "em aberto" in n or n in ("", "-", "pendente"):
        return "aberto"
    return "desconhecido"


PERMITIDO_LOJA = {"pix", "pix_online", "credito", "debito", "vale"}
PERMITIDO_MAQUININHA = {"pix", "credito", "debito", "vale"}


def loja_do_pedido(det: dict) -> tuple[str, str | None]:
    """(rótulo da loja, merchant iFood ou None)."""
    canal = str(det.get("platform_slug") or "").lower()
    meta = det.get("payment_metadata") if isinstance(det.get("payment_metadata"), dict) else {}
    merchant = meta.get("ifood_merchant_id")
    if canal == "ifood" or merchant:
        nome = MERCHANTS.get(merchant, (f"iFood ? ({det.get('branch_label') or 'loja desconhecida'})", None))[0]
        return nome, merchant
    return ("Loja (app próprio)" if canal == "app" else "Loja (PDV/balcão)"), None


def classificar(det: dict) -> tuple[str, str]:
    """('EMITIR' | 'NAO_EMITIR' | 'ATENCAO', regra/motivo)."""
    loja, merchant = loja_do_pedido(det)
    partes = partes_pagamento(det.get("payment_method") or det.get("payment") or "")
    tipos = [tipo_pagamento(n) for n, _ in partes] or ["aberto"]
    if num(det.get("balance_used")) > 0:
        tipos.append("bloqueado")

    if "bloqueado" in tipos:
        return "ATENCAO", "fiado / carteira / conta func. — decidir manualmente"
    if "aberto" in tipos:
        return "ATENCAO", "pagamento em aberto"
    if "pix_online_pendente" in tipos:
        return "ATENCAO", "Pix Online não confirmado como pago"
    if "desconhecido" in tipos:
        return "ATENCAO", "forma de pagamento não reconhecida"

    if merchant is None and loja.startswith("iFood"):
        return "ATENCAO", "pedido iFood sem merchant conhecido"
    if merchant is None:
        permitidos = PERMITIDO_LOJA
    elif MERCHANTS[merchant][1]:            # Burguer e 2.0: tudo menos dinheiro
        permitidos = PERMITIDO_MAQUININHA | {"ifood_online"}
    else:                                   # iFood Tili Pizzaria: só maquininha do motoboy
        permitidos = PERMITIDO_MAQUININHA
        if "ifood_online" in tipos and any(t in permitidos for t in tipos):
            return "ATENCAO", "iFood Tili Pizzaria misto online + maquininha"

    if any(t in permitidos for t in tipos):
        return "EMITIR", "misto com dinheiro" if "dinheiro" in tipos else "ok"
    if set(tipos) == {"dinheiro"}:
        return "NAO_EMITIR", "dinheiro"
    if "ifood_online" in tipos:
        return "NAO_EMITIR", "pagamento online iFood (Tili Pizzaria)"
    return "NAO_EMITIR", "forma não permitida: " + ", ".join(sorted(set(tipos)))


# ---------------------------------------------------------------- coleta
def coletar(api: Aliv, dia: date) -> dict:
    """Pedidos criados em `dia` na loja 150, com detalhe e classificação."""
    brutos: dict = {}
    page = 1
    while page < 200:
        lote = lista_pedidos(api.get("/admin/api/orders/audit",
                                     {"start_date": dia.isoformat(), "end_date": dia.isoformat(), "page": page}))
        if not lote:
            break
        for o in lote:
            if isinstance(o, dict) and o.get("id") is not None:
                brutos.setdefault(o["id"], o)
        page += 1   # has_more do ALIV não é confiável

    def detalhe(i):
        d = api.get(f"/admin/api/orders/{i}")
        return d["order"] if isinstance(d, dict) and isinstance(d.get("order"), dict) else d

    with ThreadPoolExecutor(max_workers=6) as ex:
        dets = dict(zip(brutos, ex.map(detalhe, brutos)))

    pedidos, contagem = [], {"cancelados": 0, "abertos": 0, "ja_emitidos": 0, "outra_loja": 0, "outro_dia": 0}
    for oid, item in brutos.items():
        det = {**item, **(dets[oid] if isinstance(dets[oid], dict) else {})}
        if item.get("store_id") not in (None, LOJA):
            contagem["outra_loja"] += 1
            continue
        criado = parse_dt(item.get("created_at") or det.get("created_at_fmt"), dia.year)
        if criado is None or criado.date() != dia:
            contagem["outro_dia"] += 1
            continue
        st = str(det.get("status") or "").strip().upper()
        if st.startswith("CANCELADO"):
            contagem["cancelados"] += 1
            continue
        if st not in STATUS_OK:
            contagem["abertos"] += 1
            continue
        fiscal = str(det.get("fiscal_status") or "").strip().upper()
        if fiscal == "AUTORIZADO":
            contagem["ja_emitidos"] += 1
            continue
        loja, merchant = loja_do_pedido(det)
        if fiscal not in FISCAL_PENDENTE:
            grupo, regra = "ATENCAO", f"fiscal_status {fiscal}"
        else:
            grupo, regra = classificar(det)
        pedidos.append({
            "id": oid,
            "codigo": det.get("wabiz_id") or str(oid),
            "hora": criado.strftime("%H:%M"),
            "valor": round(num(det.get("total_value", item.get("total"))), 2),
            "pagamento": str(det.get("payment_method") or item.get("payment") or ""),
            "loja": loja,
            "merchant": merchant,
            "grupo": grupo,
            "regra": regra,
        })
    pedidos.sort(key=lambda p: (p["hora"], p["id"]))
    return {"pedidos": pedidos, "contagem": contagem}


# ---------------------------------------------------------------- texto da lista
def _soma(ps) -> float:
    return round(sum(p["valor"] for p in ps), 2)


def texto_lista(dia: date, col: dict) -> tuple[str, str]:
    """(assunto, corpo)."""
    ps = col["pedidos"]
    emitir = [p for p in ps if p["grupo"] == "EMITIR"]
    nao = [p for p in ps if p["grupo"] == "NAO_EMITIR"]
    aten = [p for p in ps if p["grupo"] == "ATENCAO"]
    assunto = f"NFC-e Tili — {dm(dia)} — {len(emitir)} a emitir / {brl(_soma(emitir))}"
    L = [f"*{assunto}*", "", f"*EMITIR — {len(emitir)} / {brl(_soma(emitir))}*"]
    lojas = sorted({p["loja"] for p in emitir}, key=lambda x: (ORDEM_LOJAS.index(x) if x in ORDEM_LOJAS else 99, x))
    for loja in lojas:
        g = [p for p in emitir if p["loja"] == loja]
        L.append(f"• {loja}: {len(g)} / {brl(_soma(g))}")
    if not emitir:
        L.append("• nenhum pedido")
    L += ["", f"*NÃO EMITIR — {len(nao)} / {brl(_soma(nao))}*"]
    for regra in sorted({p["regra"] for p in nao}):
        g = [p for p in nao if p["regra"] == regra]
        L.append(f"• {regra}: {len(g)} / {brl(_soma(g))}")
    if not nao:
        L.append("• nenhum pedido")
    L += ["", f"*ATENÇÃO — {len(aten)}*"]
    for p in aten:
        L.append(f"• #{p['codigo']} {p['hora']} {brl(p['valor'])} — {p['pagamento']} — {p['regra']}")
    if not aten:
        L.append("• nada")
    c = col["contagem"]
    L += ["", f"Fora da lista: {c['cancelados']} cancelados, {c['abertos']} ainda abertos, "
              f"{c['ja_emitidos']} já com nota.", "", "Responda *emite* para emitir."]
    return assunto, "\n".join(L)


def detalhe_texto(col: dict) -> str:
    L = []
    for p in col["pedidos"]:
        L.append(f"{p['grupo']:<10} #{p['codigo']:<10} {p['hora']} {brl(p['valor']):>12}  "
                 f"{p['loja']:<24} {p['pagamento']}  [{p['regra']}]")
    return "\n".join(L)


# ---------------------------------------------------------------- arquivo do dia
def arquivo(dia: date) -> Path:
    return PASTA / f"{dia}.json"


def ler_arquivo(dia: date) -> dict:
    try:
        return json.loads(arquivo(dia).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gravar_arquivo(dia: date, dados: dict) -> Path:
    PASTA.mkdir(parents=True, exist_ok=True)
    caminho = arquivo(dia)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return caminho


# ---------------------------------------------------------------- envio
def enviar(api: Aliv, texto: str) -> str | None:
    """Manda para WHATSAPP_EMERSON. Devolve o motivo da falha ou None."""
    fone = dig(os.environ.get("WHATSAPP_EMERSON"))
    if not fone:
        return "variável WHATSAPP_EMERSON não definida"
    try:
        api.enviar_whatsapp(fone, texto)
    except (AlivError, OSError) as e:
        return str(e)
    return None


# ---------------------------------------------------------------- fiscal
class Fiscal:
    """Perfis fiscais lidos ao vivo. CNPJs ficam só em memória, nunca saem."""

    def __init__(self, api: Aliv):
        fc = api.get(f"/admin/api/stores/{LOJA}/fiscal-config") or {}
        fp = api.get(f"/admin/api/stores/{LOJA}/fiscal-profiles") or {}
        campos = fc.get("fields") or {}
        self.ativo = bool(campos.get("fiscal_active"))
        self._principal = dig(campos.get("cnpj"))
        self._por_merchant: dict[str, tuple[str, str]] = {}
        self._nomes: dict[str, str] = {self._principal: "CNPJ principal"} if self._principal else {}
        for p in fp.get("profiles") or []:
            cnpj = dig(p.get("cnpj"))
            if not cnpj:
                continue
            self._nomes.setdefault(cnpj, f"perfil {p.get('name')}")
            if not p.get("active"):
                continue
            for r in p.get("match_rules") or []:
                if str(r.get("platform")).lower() == "ifood" and r.get("account_id"):
                    self._por_merchant[r["account_id"]] = (cnpj, f"perfil {p.get('name')}")

    def esperado(self, merchant: str | None) -> str:
        """Nome do perfil em que a nota deve sair (sem CNPJ)."""
        return self._por_merchant.get(merchant or "", (None, "CNPJ principal"))[1]

    def conferir(self, chave: str, merchant: str | None) -> tuple[str, bool]:
        """(perfil em que a nota saiu, bateu com o esperado?). Usa as posições 7 a 20 da chave."""
        k = dig(chave)
        if len(k) != 44:
            return "chave ausente", False
        emitente = k[6:20]
        esperado = self._por_merchant.get(merchant or "", (self._principal, ""))[0]
        return self._nomes.get(emitente, "CNPJ desconhecido"), emitente == esperado


def post_form(api: Aliv, path: str, campos: dict, timeout: int = 120):
    boundary = uuid.uuid4().hex
    body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                   for k, v in campos.items()) + f"--{boundary}--\r\n"
    req = urllib.request.Request(BASE_URL + path, data=body.encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    antigo, api.timeout = api.timeout, timeout
    try:
        status, data = api._send(req)
        if status == 401:   # sessão expirada: o POST não chegou a emitir
            api.login()
            status, data = api._send(req)
    finally:
        api.timeout = antigo
    return status, data if isinstance(data, dict) else {}


def autorizado(r: dict) -> bool:
    """Mesma regra da tela do ALIV (yr)."""
    d = r.get("data") if isinstance(r.get("data"), dict) else {}
    st = str(r.get("status_sefaz") or d.get("status_sefaz") or "").strip()
    msg = str(d.get("mensagem_sefaz") or "").lower()
    return (bool(r.get("success")) or st == "100" or "autorizado" in msg
            or str(d.get("status") or r.get("status") or "").lower() == "autorizado" or bool(r.get("chave_nfe")))


def motivo(r: dict, status: int) -> str:
    d = r.get("data") if isinstance(r.get("data"), dict) else {}
    st = str(r.get("status_sefaz") or d.get("status_sefaz") or "").strip()
    txt = r.get("message") or r.get("error") or d.get("mensagem_sefaz") or d.get("message") or ""
    if not txt:
        txt = f"HTTP {status} sem mensagem"
    return f"{st} — {txt}" if st and st not in str(txt) else str(txt)


def checar(api: Aliv, oid) -> dict:
    for tentativa in range(4):
        try:
            r = api.get(f"/admin/api/orders/{oid}/check-fiscal") or {}
        except AlivError as e:
            r = {"status": "ERRO", "message": str(e)}
        if str(r.get("status")).upper() == "AUTORIZADO" or tentativa == 3:
            return r
        time.sleep(3)
    return {}


def emitir_um(api: Aliv, p: dict) -> dict:
    """Uma emissão: CPF do pedido; se a SEFAZ recusar o CPF, de novo com espaço (sem CPF)."""
    res = {"id": p["id"], "codigo": p["codigo"], "hora": p["hora"], "valor": p["valor"],
           "pagamento": p["pagamento"], "loja": p["loja"], "tentativas": []}
    for doc, rotulo in (("", "CPF do pedido"), (" ", "sem CPF")):
        try:
            status, r = post_form(api, f"/admin/api/orders/{p['id']}/emit-fiscal", {"customer_document": doc})
        except OSError as e:     # timeout: não reenviar às cegas — consulta o status
            status, r = 0, {"message": f"sem resposta do ALIV ({e})"}
            ck = checar(api, p["id"])
            if str(ck.get("status")).upper() == "AUTORIZADO":
                status, r = 200, {"success": True}
        res["tentativas"].append(rotulo)
        if r.get("error_code") == "LIMIT_REACHED":
            return {**res, "resultado": "LIMITE", "motivo": "LIMIT_REACHED — pacote de notas esgotado"}
        if autorizado(r):
            ck = checar(api, p["id"])
            ok = str(ck.get("status")).upper() == "AUTORIZADO"
            return {**res, "resultado": "AUTORIZADA" if ok else "ATENCAO",
                    "motivo": "" if ok else f"emitida, mas check-fiscal respondeu: {ck.get('status')} {ck.get('message') or ''}".strip()}
        m = motivo(r, status)
        if r.get("error_code") == "MISSING_PAYMENT" or re.search(r"sem o? pagamento", str(r.get("error") or ""), re.I):
            return {**res, "resultado": "REJEITADA", "motivo": f"MISSING_PAYMENT — {m}"}
        if RE_REJ_TROCO.search(m):
            return {**res, "resultado": "ATENCAO",
                    "motivo": f"{m} (bug do ALIV: borda/adicional como desconto negativo — não insistir)"}
        if status == 0:
            return {**res, "resultado": "ATENCAO", "motivo": m + " — conferir no ALIV antes de tentar de novo"}
        if doc == "" and RE_REJ_CPF.search(m):
            res["motivo_cpf"] = m
            time.sleep(1)
            continue
        return {**res, "resultado": "REJEITADA", "motivo": m}
    return {**res, "resultado": "REJEITADA", "motivo": res.get("motivo_cpf", "rejeitada")}


def texto_emissao(dia: date, resumo: dict, dry: bool) -> str:
    rs = resumo["resultados"]
    aut = [r for r in rs if r["resultado"] == "AUTORIZADA"]
    rej = [r for r in rs if r["resultado"] == "REJEITADA"]
    aten = [r for r in rs if r["resultado"] == "ATENCAO"]
    titulo = "SIMULAÇÃO (dry-run) — " if dry else ""
    L = [f"*{titulo}NFC-e Tili — {dm(dia)} — resultado*", ""]
    if dry:
        L.append(f"Seriam emitidas {len(rs)} notas / {brl(_soma(rs))} (nenhum POST feito).")
        for perfil in sorted({r['perfil_esperado'] for r in rs}):
            g = [r for r in rs if r["perfil_esperado"] == perfil]
            L.append(f"• {perfil}: {len(g)} / {brl(_soma(g))}")
    else:
        L.append(f"*Autorizadas — {len(aut)} / {brl(_soma(aut))}*")
        for perfil in sorted({r.get("perfil_emitido", "?") for r in aut}):
            g = [r for r in aut if r.get("perfil_emitido") == perfil]
            L.append(f"• {perfil}: {len(g)} / {brl(_soma(g))}")
        errados = [r for r in aut if r.get("perfil_ok") is False]
        if errados:
            L.append(f"⚠ {len(errados)} nota(s) saíram no CNPJ errado: "
                     + ", ".join(f"#{r['codigo']} ({r['perfil_emitido']}, esperado {r['perfil_esperado']})" for r in errados))
        L += ["", f"*Rejeitadas — {len(rej)} / {brl(_soma(rej))}*"]
        for r in rej:
            L.append(f"• #{r['codigo']} {r['hora']} {brl(r['valor'])} — {r['pagamento']} — {r['motivo']}")
        if rej:
            cont: dict = {}
            for r in rej:
                cont[r["motivo"]] = cont.get(r["motivo"], 0) + 1
            m, n = max(cont.items(), key=lambda x: x[1])
            L.append(f"Maior motivo: {m} ({n}x)")
        L += ["", f"*ATENÇÃO — {len(aten)}*"]
        for r in aten:
            L.append(f"• #{r['codigo']} {r['hora']} {brl(r['valor'])} — {r['pagamento']} — {r['motivo']}")
        if not aten:
            L.append("• nada")
    for aviso in resumo.get("avisos", []):
        L += ["", f"⚠ {aviso}"]
    return "\n".join(L)


# ---------------------------------------------------------------- comandos
def cmd_listar(api: Aliv, dia: date, dry: bool) -> int:
    col = coletar(api, dia)
    assunto, corpo = texto_lista(dia, col)
    print(assunto + "\n")
    print(corpo)
    print("\nDETALHE\n" + detalhe_texto(col))
    if dry:
        print("\nDRY-RUN: nada gravado nem enviado.", file=sys.stderr)
        return 0
    dados = ler_arquivo(dia)
    dados.update({"data": dia.isoformat(), "loja": LOJA,
                  "lista": {"gerada_em": datetime.now(TZ).isoformat(timespec="seconds"), **col}})
    caminho = gravar_arquivo(dia, dados)
    print(f"\nArquivo: {caminho.relative_to(PASTA.parent.parent)}")
    falha = enviar(api, corpo)
    if falha:
        print(f"WHATSAPP: não enviado — {falha}", file=sys.stderr)
        return 3
    print("WHATSAPP: lista enviada.", file=sys.stderr)
    return 0


def cmd_emitir(api: Aliv, dia: date, dry: bool, limite: int) -> int:
    dados = ler_arquivo(dia)
    aprovada = dados.get("lista")
    avisos = []
    col = coletar(api, dia)                       # estado ao vivo
    vivos = {p["id"]: p for p in col["pedidos"]}
    if not aprovada:
        avisos.append(f"Sem lista salva de {dm(dia)}: usei a lista gerada agora.")
        ids_aprovados = [p["id"] for p in col["pedidos"] if p["grupo"] == "EMITIR"]
    else:
        ids_aprovados = [p["id"] for p in aprovada.get("pedidos", []) if p["grupo"] == "EMITIR"]

    fila, pulados = [], []
    for oid in ids_aprovados:
        p = vivos.get(oid)
        if p is None:
            pulados.append(f"{oid}: não está mais pendente (já emitido, cancelado ou reaberto)")
        elif p["grupo"] != "EMITIR":
            pulados.append(f"#{p['codigo']}: agora está em {p['grupo']} ({p['regra']})")
        else:
            fila.append(p)
    novos = [p for p in col["pedidos"] if p["grupo"] == "EMITIR" and p["id"] not in set(ids_aprovados)]
    if novos:
        avisos.append(f"{len(novos)} pedido(s) novos que não estavam na lista aprovada NÃO foram emitidos: "
                      + ", ".join(f"#{p['codigo']}" for p in novos))
    if pulados:
        avisos.append("Saíram da fila: " + "; ".join(pulados))
    if len(fila) > limite:
        avisos.append(f"Fila com {len(fila)} notas: só as primeiras {limite} entram nesta execução. Rode de novo para o resto.")
        fila = fila[:limite]

    fiscal = Fiscal(api)
    if not fiscal.ativo:
        avisos.append("fiscal_active = false no fiscal-config da loja 150.")

    resultados, interrompido = [], False
    for i, p in enumerate(fila, 1):
        base = {"perfil_esperado": fiscal.esperado(p["merchant"])}
        if dry:
            r = {"id": p["id"], "codigo": p["codigo"], "hora": p["hora"], "valor": p["valor"],
                 "pagamento": p["pagamento"], "loja": p["loja"], "resultado": "SIMULADA", "motivo": ""}
        else:
            r = emitir_um(api, p)
            if r["resultado"] == "AUTORIZADA":
                try:
                    det = api.get(f"/admin/api/orders/{p['id']}")
                    det = det.get("order", det) if isinstance(det, dict) else {}
                    r["perfil_emitido"], r["perfil_ok"] = fiscal.conferir(det.get("fiscal_key"), p["merchant"])
                except AlivError as e:
                    r["perfil_emitido"], r["perfil_ok"] = f"não conferido ({e})", None
            print(f"[{i}/{len(fila)}] #{p['codigo']} {brl(p['valor'])} → {r['resultado']} {r.get('motivo', '')}",
                  file=sys.stderr)
            time.sleep(1)
        resultados.append({**r, **base})
        if r["resultado"] == "LIMITE":
            interrompido = True
            avisos.insert(0, f"LIMIT_REACHED na nota {i} de {len(fila)}: pacote de notas esgotado. "
                             "Emissão PARADA — falar com o suporte do ALIV.")
            break

    resumo = {"executada_em": datetime.now(TZ).isoformat(timespec="seconds"), "dry_run": dry,
              "resultados": resultados, "avisos": avisos}
    texto = texto_emissao(dia, resumo, dry)
    print(texto)
    if dry:
        print("\nDRY-RUN: nenhum POST, nada gravado nem enviado.", file=sys.stderr)
        return 0
    dados.setdefault("data", dia.isoformat())
    dados.setdefault("emissoes", []).append(resumo)
    caminho = gravar_arquivo(dia, dados)
    print(f"\nArquivo: {caminho.relative_to(PASTA.parent.parent)}")
    falha = enviar(api, texto)
    if falha:
        print(f"WHATSAPP: não enviado — {falha}", file=sys.stderr)
    if interrompido:
        return 4
    return 3 if falha else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="NFC-e da Tili Pizzaria (loja 150): listar e emitir")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("listar", help="lista do dia (não emite)")
    pl.add_argument("--data", help="AAAA-MM-DD (padrão: hoje; antes das 04:00, ontem)")
    pl.add_argument("--dry-run", action="store_true", help="não envia WhatsApp")
    pe = sub.add_parser("emitir", help="emite a lista aprovada do dia")
    pe.add_argument("--data", required=True, help="AAAA-MM-DD da lista aprovada")
    pe.add_argument("--dry-run", action="store_true", help="não faz POST, só mostra")
    pe.add_argument("--limite", type=int, default=MAX_POR_EXECUCAO, help="máximo de notas (até 200)")
    for p in (pl, pe):
        p.add_argument("--raw", metavar="PASTA", help="salva as respostas cruas do ALIV (não commitar)")
    args = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: defina ALIV_USER e ALIV_PASS nas variáveis de ambiente.", file=sys.stderr)
        return 2
    dia = date.fromisoformat(args.data) if args.data else hoje_operacional(datetime.now(TZ))
    api = Aliv(user, pwd, raw_dir=Path(args.raw) if args.raw else None)
    try:
        api.login()
        if args.cmd == "listar":
            return cmd_listar(api, dia, args.dry_run)
        return cmd_emitir(api, dia, args.dry_run, max(1, min(args.limite, MAX_POR_EXECUCAO)))
    except (AlivError, OSError) as e:
        print(f"NFC-e Tili — {dm(dia)} — ERRO no ALIV\n\n{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
