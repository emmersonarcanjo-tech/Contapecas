#!/usr/bin/env python3
"""Comprovantes de pagamento de boleto pelo WhatsApp → baixa no ALIV.

Regra do Emerson (15/11/2026): o financeiro manda os comprovantes no WhatsApp da
Pizzaria (o mesmo número que manda as listas de boletos). A Rotina:

  1. `ler`: baixa as fotos/PDFs novos que chegaram desse número (o ALIV guarda a
     mídia só 24 h) e lista o que falta ler;
  2. a Rotina (Claude) abre cada arquivo e anota valor pago, data do pagamento e
     beneficiário, num JSON;
  3. `baixar ENTRADA.json`: acha a conta a pagar certa (Pizzaria ou Sushi) pelo
     valor, data e nome do fornecedor e dá baixa como paga, saindo do BRADESCO
     da loja. Sem certeza (nenhuma ou mais de uma conta), não baixa: avisa o Emerson.

Nunca responde o financeiro no WhatsApp. Estado em monitor/comprovantes/estado.json
(comprovantes já tratados); arquivos baixados ficam fora do git.

Uso:
  comprovantes.py ler --de 5573988313572 [--horas 30]
  comprovantes.py baixar ENTRADA.json [--confirmar] [--whatsapp]
ENTRADA.json: [{"wamid", "valor": 1311.31, "data": "2026-11-17", "beneficiario": "FRISA ...",
               "vencimento": "2026-11-17"}]   # vencimento: se o comprovante mostrar
             (ou {"wamid", "ignorar": "motivo"} para o que não é comprovante de boleto)
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import BASE_URL, TZ, Aliv, AlivError, brl  # noqa: E402

PASTA = Path(__file__).resolve().parent / "comprovantes"
ESTADO = PASTA / "estado.json"
LOJAS = {"Pizzaria": ("ALIV_USER", "ALIV_PASS"), "Sushi": ("ALIV_USER_SUSHI", "ALIV_PASS_SUSHI")}
BANCO = "BRADESCO"   # escolha do Emerson: toda baixa de boleto sai do Bradesco da loja


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"\b(LTDA|ME|EPP|S/?A|SA|EIRELI|COMERCIO|COMERCIAL|DISTRIBUIDORA|INDUSTRIA|DE|DO|DA|E)\b", " ", s)
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", s).split())


def fone_aliv(f: str) -> str:
    """O ALIV guarda o celular sem o 9: 5573988313572 → 557388313572."""
    p = re.sub(r"\D", "", f)
    if len(p) in (10, 11):
        p = "55" + p
    return p[:4] + p[5:] if len(p) == 13 and p.startswith("55") and p[4] == "9" else p


def estado() -> dict:
    try:
        return json.loads(ESTADO.read_text())
    except (OSError, json.JSONDecodeError):
        return {"tratados": {}}


def gravar(e: dict) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1))


def cmd_ler(a) -> int:
    api = Aliv(os.environ["ALIV_USER"], os.environ["ALIV_PASS"])
    est = estado()
    desde = datetime.now(TZ) - timedelta(hours=a.horas)
    try:
        msgs = api.get(f"/admin/api/chat/messages/{urllib.parse.quote(fone_aliv(a.de))}", {"limit": 200}) or []
    except AlivError as e:
        print(f"ERRO no ALIV: {e}")
        return 1
    novos = []
    for m in msgs:
        if m.get("direction") != "incoming" or m.get("type") not in ("image", "document"):
            continue
        url, wamid = m.get("media_url"), m.get("wamid")
        if not url or not str(url).startswith("http") or not wamid or wamid in est["tratados"]:
            continue
        try:
            dt = datetime.strptime(f"{m['date_label']} {m['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        except (KeyError, ValueError):
            continue
        if dt < desde:
            continue
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
        ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".pdf") else (".pdf" if m["type"] == "document" else ".jpg")
        arq = PASTA / "arquivos" / dt.date().isoformat() / f"{dt:%H%M}_{re.sub(r'[^A-Za-z0-9]', '', wamid)[-12:]}{ext}"
        try:
            if not arq.exists():
                arq.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "tili/1.0"}),
                                            timeout=60) as r:
                    arq.write_bytes(r.read())
        except OSError as e:
            novos.append({"wamid": wamid, "data": dt.date().isoformat(), "hora": dt.strftime("%H:%M"),
                          "erro": f"não baixou: {e}"})
            continue
        novos.append({"wamid": wamid, "data": dt.date().isoformat(), "hora": dt.strftime("%H:%M"),
                      "arquivo": str(arq), "legenda": (m.get("body") or "").strip()[:200]})
    print(json.dumps(novos, ensure_ascii=False, indent=1))
    return 0


def contas(api: Aliv) -> list[dict]:
    d = api.get("/admin/finance/bills", {"bill_type": "payable", "status": "all"})
    d = d if isinstance(d, list) else d.get("bills", [])
    return [b for b in d if not b.get("paid_at") and b.get("due_date") and float(b.get("amount") or 0) > 0]


def candidatos(c: dict, abertas: dict[str, list[dict]]) -> list[tuple[str, dict, float]]:
    """(loja, conta, nota) — mesmo valor; vencimento até 15 dias antes ou 10 depois do pagamento."""
    v, pago = round(float(c["valor"]), 2), date.fromisoformat(c["data"])
    nome = norm(c.get("beneficiario"))
    out = []
    for loja, bs in abertas.items():
        for b in bs:
            if abs(float(b["amount"]) - v) > 0.01:
                continue
            venc = date.fromisoformat(str(b["due_date"])[:10])
            if not (pago - timedelta(days=15) <= venc <= pago + timedelta(days=10)):
                continue
            desc = norm(re.sub(r"^Compra\s+|\s+-\s+NF.*$", "", str(b.get("description") or "")))
            sim = difflib.SequenceMatcher(None, nome, desc).ratio() if nome else 0.0
            if nome and nome.split()[0] in desc.split():
                sim = max(sim, 0.6)
            alvo = date.fromisoformat(c["vencimento"]) if c.get("vencimento") else pago
            if c.get("vencimento") and venc != alvo:
                continue        # o comprovante diz o vencimento: só a parcela certa
            out.append((loja, b, sim - abs((venc - alvo).days) / 100))
    return sorted(out, key=lambda x: -x[2])


def desc_curta(b: dict) -> str:
    return re.sub(r"^Compra\s+|\s*\(Ped #\d+\)", "", str(b.get("description") or ""))[:55]


def pagar(api: Aliv, b: dict, banco_id: int, dia: str) -> tuple[bool, str]:
    campos = {"payment_method": b.get("payment_method") or "Boleto via DDA", "origin": "banco",
              "bank_account_id": banco_id, "payment_date": dia}
    k = uuid.uuid4().hex
    body = "".join(f'--{k}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'
                   for n, v in campos.items()) + f"--{k}--\r\n"
    req = urllib.request.Request(f"{BASE_URL}/admin/finance/bills/{b['id']}/pay", data=body.encode(), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={k}",
                                          "Accept": "application/json"})
    st, d = api._send(req)
    ok = st == 200 and not (isinstance(d, dict) and d.get("success") is False)
    return ok, str((d.get("message") or d.get("error")) if isinstance(d, dict) else d)[:150]


def cmd_baixar(a) -> int:
    entrada = json.loads(Path(a.entrada).read_text())
    est = estado()
    apis, abertas, bancos = {}, {}, {}
    try:
        for loja, (u, p) in LOJAS.items():
            apis[loja] = Aliv(os.environ[u], os.environ[p])
            abertas[loja] = contas(apis[loja])
            bl = apis[loja].get("/admin/api/finance/banking/accounts/list")
            bl = bl if isinstance(bl, list) else bl.get("accounts", [])
            bancos[loja] = next((x["id"] for x in bl if BANCO in str(x.get("name", "")).upper()), None)
    except (AlivError, OSError, KeyError) as e:
        print(f"Tili — Comprovantes — ERRO no ALIV\n\n{e}")
        return 1
    ok_l, avisar = [], []
    for c in entrada:
        w = c.get("wamid")
        if not w or w in est["tratados"]:
            continue
        if c.get("ignorar"):
            est["tratados"][w] = {"ignorado": c["ignorar"]}
            continue
        try:
            float(c["valor"]), date.fromisoformat(c["data"])
        except (KeyError, TypeError, ValueError):
            avisar.append(f"comprovante {c.get('data', '?')} {c.get('hora', '')}: não consegui ler valor/data")
            continue
        tag = f"{brl(float(c['valor']))} pago {date.fromisoformat(c['data']):%d/%m} · {str(c.get('beneficiario') or '?')[:30]}"
        cand = candidatos(c, abertas)
        boa = [x for x in cand if x[2] >= 0.45]
        escolha = boa[0] if len(boa) == 1 or (len(boa) > 1 and boa[0][2] - boa[1][2] >= 0.2) else (
            cand[0] if len(cand) == 1 else None)
        if not escolha and len(boa) > 1 and str(boa[0][1]["due_date"])[:10] == c.get("vencimento", c["data"]) \
                and str(boa[1][1]["due_date"])[:10] != str(boa[0][1]["due_date"])[:10]:
            escolha = boa[0]    # parcelas do mesmo fornecedor: a que vence no dia do pagamento
        if not escolha:
            motivo = "nenhuma conta em aberto com esse valor e data" if not cand else \
                f"{len(cand)} contas possíveis: " + "; ".join(f"{lj} {desc_curta(b)[:32]} venc {str(b['due_date'])[8:10]}/{str(b['due_date'])[5:7]}" for lj, b, _ in cand[:3])
            avisar.append(f"{tag}: não dei baixa — {motivo}")
            continue
        loja, b, _ = escolha
        txt = f"{loja} · {desc_curta(b)} venc {str(b['due_date'])[8:10]}/{str(b['due_date'])[5:7]} · {tag}"
        if not a.confirmar:
            ok_l.append("(teste) " + txt)
            continue
        if not bancos.get(loja):
            avisar.append(f"{txt}: conta {BANCO} não encontrada no ALIV da {loja}")
            continue
        ok, msg = pagar(apis[loja], b, bancos[loja], c["data"])
        if ok:
            ok_l.append("✓ " + txt)
            abertas[loja] = [x for x in abertas[loja] if x["id"] != b["id"]]
            est["tratados"][w] = {"loja": loja, "conta": b["id"], "valor": float(c["valor"]), "data": c["data"]}
        else:
            avisar.append(f"{txt}: ALIV recusou — {msg}")
    if a.confirmar:
        gravar(est)
    if not ok_l and not avisar:
        print("Tili — Comprovantes: nada novo.")
        return 0
    texto = (f"*Tili — Comprovantes de boleto*: {len(ok_l)} baixa(s) no ALIV ({BANCO})"
             + ("" if a.confirmar else " — TESTE, nada lançado")
             + ("\n" + "\n".join(ok_l) if ok_l else "")
             + ("\n\n*Conferir* (não dei baixa):\n" + "\n".join("• " + x for x in avisar) if avisar else ""))
    print(texto)
    if a.whatsapp:
        try:
            apis["Pizzaria"].enviar_whatsapp(re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", "")), texto[:3800])
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Comprovantes de boleto pelo WhatsApp → baixa no ALIV")
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("ler")
    l.add_argument("--de", required=True, help="WhatsApp do financeiro (ex.: 5573988313572)")
    l.add_argument("--horas", type=int, default=30)
    b = sub.add_parser("baixar")
    b.add_argument("entrada")
    b.add_argument("--confirmar", action="store_true")
    b.add_argument("--whatsapp", action="store_true")
    a = ap.parse_args()
    return cmd_ler(a) if a.cmd == "ler" else cmd_baixar(a)


if __name__ == "__main__":
    sys.exit(main())
