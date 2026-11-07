#!/usr/bin/env python3
"""Despesas da Tili pelo WhatsApp da loja (só leitura).

A equipe manda a foto do comprovante no PRIVADO do número da loja, com a palavra
DESPESA na legenda (ou manda "DESPESA ..." em texto e as fotos logo depois).
O script lê o chat de atendimento do ALIV, separa essas mensagens, baixa as fotos
e grava monitor/despesas/AAAA-MM-DD.json.

Só faz GET no ALIV (login à parte). Não envia mensagem, não marca como atendido,
não liga/desliga a IA. Grupo de WhatsApp NÃO funciona: o ALIV não guarda
mensagens de grupo.

O ALIV guarda a mídia só por 24h: rode pelo menos uma vez por dia.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import Aliv, AlivError  # noqa: E402

TZ = ZoneInfo("America/Bahia")
PASTA = Path(__file__).resolve().parent / "despesas"
PALAVRA = re.compile(r"\bDESPESAS?\b")
JANELA_FOTOS = timedelta(minutes=10)   # fotos que chegam depois do texto "DESPESA"
TIPOS_MIDIA = {"image", "document"}


def normaliza(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).upper()


def eh_despesa(texto: str) -> bool:
    return bool(PALAVRA.search(normaliza(texto)))


def valor_de(texto: str) -> float | None:
    """'DESPESA gás 120,50' → 120.5 · 'R$ 1.234,00' → 1234.0. Pega o 1º valor."""
    t = re.sub(r"(?i)despesas?", " ", texto or "")
    m = re.search(r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d.,]*\d)", t)
    if not m:
        return None
    v = m.group(1)
    if "," in v or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", v):   # vírgula decimal / milhar
        v = v.replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def descricao_de(texto: str) -> str:
    t = re.sub(r"(?i)\bdespesas?\b[:\-\s]*", "", texto or "").strip()
    return re.sub(r"\s+", " ", t)[:200]


def quando(msg: dict) -> datetime | None:
    try:
        return datetime.strptime(f"{msg['date_label']} {msg['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except (KeyError, TypeError, ValueError):
        return None


def tem_midia(msg: dict) -> bool:
    u = msg.get("media_url")
    return bool(u) and str(u).startswith("http") and msg.get("type") in TIPOS_MIDIA


def mascara(phone: str) -> str:
    return f"…{phone[-4:]}" if phone else "?"


def slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", normaliza(s)).strip("-").lower()
    return s[:20] or "sem-nome"


# ------------------------------------------------------------------ coleta
def contatos(api: Aliv, remetentes: dict[str, str]) -> dict[str, str]:
    """phone → nome. Números autorizados + as 25 conversas mais recentes.
    O nome de DESPESAS_REMETENTES tem prioridade sobre o nome salvo no ALIV."""
    out = dict(remetentes)
    for c in api.get("/admin/api/chat/contacts", {"include_transactional": "true"}) or []:
        p = str(c.get("phone") or "")
        if p.isdigit() and len(p) <= 13:          # só conversas individuais
            out[p] = out.get(p) or c.get("name") or ""
    return out


def ler_remetentes(texto: str) -> dict[str, str]:
    """'5573999943046=Josué Ruas,73988190252=Thiago' → {'557399943046': 'Josué Ruas', ...}.
    Aceita com ou sem 55 e com ou sem o 9 (o ALIV guarda sem o 9)."""
    out: dict[str, str] = {}
    for item in texto.split(","):
        num, _, nome = item.partition("=")
        p = re.sub(r"\D", "", num)
        if not p:
            continue
        if len(p) in (10, 11):
            p = "55" + p
        if len(p) == 13 and p.startswith("55") and p[4] == "9":
            p = p[:4] + p[5:]
        out[p] = nome.strip()
    return out


def despesas_da_conversa(phone: str, nome: str, msgs: list[dict], desde: datetime) -> list[dict]:
    achadas: list[dict] = []
    aberta: dict | None = None
    for m in msgs:
        if m.get("direction") != "incoming":
            continue
        dt = quando(m)
        if not dt or dt < desde:
            continue
        corpo = m.get("body") or ""
        if eh_despesa(corpo):
            aberta = {
                "wamid": m.get("wamid"), "id": m.get("id"), "data": dt.date().isoformat(),
                "hora": dt.strftime("%H:%M"), "remetente": nome or mascara(phone),
                "telefone": mascara(phone), "texto": corpo.strip()[:300],
                "descricao": descricao_de(corpo), "valor": valor_de(corpo),
                "fotos": [], "_dt": dt, "_phone": phone,
            }
            achadas.append(aberta)
            if tem_midia(m):
                aberta["fotos"].append({"wamid": m.get("wamid"), "url": m["media_url"], "tipo": m.get("type")})
            continue
        # foto/documento sem legenda logo depois de um "DESPESA" em texto
        if aberta and tem_midia(m) and not corpo.strip() and dt - aberta["_dt"] <= JANELA_FOTOS:
            aberta["fotos"].append({"wamid": m.get("wamid"), "url": m["media_url"], "tipo": m.get("type")})
        elif corpo.strip():
            aberta = None
    return achadas


def baixar(url: str, destino: Path, timeout: int = 60) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "tili-despesas/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        dados = r.read()
    if not dados:
        raise OSError("arquivo vazio")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)


def ext_de(url: str, tipo: str) -> str:
    e = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return e if e in {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic"} else (".jpg" if tipo == "image" else ".bin")


def carregar(dia: str) -> dict:
    f = PASTA / f"{dia}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            pass
    return {"dia": dia, "despesas": []}


def brl(v) -> str:
    return "—" if v is None else "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--horas", type=float, default=26, help="olhar mensagens das últimas N horas (padrão 26)")
    ap.add_argument("--fotos", type=Path, default=PASTA / "fotos", help="pasta das fotos (fora do git)")
    ap.add_argument("--sem-baixar", action="store_true", help="não baixa as fotos")
    ap.add_argument("--sem-gravar", action="store_true", help="não grava o JSON")
    ap.add_argument("--agora", help="simula o horário (AAAA-MM-DDTHH:MM, fuso America/Bahia)")
    a = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("Faltam ALIV_USER/ALIV_PASS", file=sys.stderr)
        return 2
    remetentes = ler_remetentes(os.environ.get("DESPESAS_REMETENTES", ""))

    agora = datetime.fromisoformat(a.agora).replace(tzinfo=TZ) if a.agora else datetime.now(TZ)
    desde = agora - timedelta(hours=a.horas)
    api = Aliv(user, pwd)
    try:
        conversas = contatos(api, remetentes)
        novas: list[dict] = []
        for phone, nome in conversas.items():
            msgs = api.get(f"/admin/api/chat/messages/{urllib.parse.quote(phone)}", {"limit": 200}) or []
            novas += despesas_da_conversa(phone, nome, msgs, desde)
    except AlivError as e:
        print(f"Tili Despesas — erro no ALIV: {e}")
        return 1

    falhas = 0
    por_dia: dict[str, dict] = {}
    for d in sorted(novas, key=lambda x: x["_dt"]):
        doc = por_dia.setdefault(d["data"], carregar(d["data"]))
        velha = next((x for x in doc["despesas"] if x["wamid"] == d["wamid"]), None)
        alvo = velha or d
        if velha:   # mantém o que já foi baixado; acrescenta fotos novas da janela
            conhecidas = {f["wamid"] for f in velha["fotos"]}
            velha["fotos"] += [f for f in d["fotos"] if f["wamid"] not in conhecidas]
        else:
            doc["despesas"].append(d)
        for i, f in enumerate(alvo["fotos"], 1):
            if f.get("arquivo") or a.sem_baixar:
                continue
            nome_arq = f"{d['data']}_{d['hora'].replace(':', '')}_{slug(d['remetente'])}_{str(d['wamid'])[-6:]}_{i}{ext_de(f['url'], f.get('tipo', ''))}"
            try:
                baixar(f["url"], a.fotos / d["data"] / nome_arq)
                f["arquivo"] = f"{d['data']}/{nome_arq}"
                f.pop("erro", None)
            except Exception as e:  # noqa: BLE001
                f["erro"] = str(e)[:120]
                falhas += 1

    for doc in por_dia.values():
        for x in doc["despesas"]:
            x.pop("_dt", None)
            x.pop("_phone", None)
        doc["total"] = round(sum(x["valor"] or 0 for x in doc["despesas"]), 2)
        doc["atualizado"] = agora.isoformat(timespec="minutes")
        if not a.sem_gravar:
            PASTA.mkdir(parents=True, exist_ok=True)
            (PASTA / f"{doc['dia']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    # ---- relatório (1ª linha = assunto)
    todas = [x for doc in por_dia.values() for x in doc["despesas"]]
    total = sum(x["valor"] or 0 for x in todas)
    print(f"Tili Despesas — {agora:%d/%m %H:%M} — {len(todas)} despesa(s) / {brl(total)}")
    print(f"Conversas lidas: {len(conversas)} (autorizados: {len(remetentes)}) · janela: últimas {a.horas:g}h")
    for x in sorted(todas, key=lambda x: (x["data"], x["hora"])):
        fotos = len(x["fotos"])
        ok = sum(1 for f in x["fotos"] if f.get("arquivo"))
        print(f"- {x['data'][8:]}/{x['data'][5:7]} {x['hora']} · {x['remetente']} · {brl(x['valor'])} · "
              f"{x['descricao'] or '(sem descrição)'} · fotos {ok}/{fotos}")
    avisos = [x for x in todas if not x["fotos"]]
    sem_valor = [x for x in todas if x["valor"] is None]
    if avisos:
        print(f"ATENÇÃO: {len(avisos)} despesa(s) sem foto.")
    if sem_valor:
        print(f"ATENÇÃO: {len(sem_valor)} despesa(s) sem valor na legenda.")
    if falhas:
        print(f"ATENÇÃO: {falhas} foto(s) não baixada(s). A mídia some do ALIV em 24h.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
