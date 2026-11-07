#!/usr/bin/env python3
"""Monitor de Operação da Tili Pizzaria (fase 1) — só leitura no ALIV.

Faz login no ALIV Hub (app.alivhub.com.br) com ALIV_USER / ALIV_PASS
(variáveis de ambiente), consulta pedidos, tempos e motoboys, calcula os
indicadores e imprime o relatório em texto (1ª linha = assunto do e-mail).
Com ALIV_USER_SUSHI / ALIV_PASS_SUSHI inclui também a Tili Sushi (loja 155):
pedidos, vendas, peças vendidas e canais (salão, app, iFood).

Grava um snapshot diário em monitor/snapshots/AAAA-MM-DD.json para a rodada
seguinte calcular "última hora" por diferença. O commit do snapshot fica a
cargo da Rotina (ver README).

Somente biblioteca padrão do Python 3.9+. Nunca faz POST/PUT/DELETE no ALIV,
exceto o POST de login e, com --whatsapp, o POST /admin/api/chat/send.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_URL = os.environ.get("ALIV_BASE_URL", "https://app.alivhub.com.br").rstrip("/")
TZ = ZoneInfo("America/Bahia")
SNAP_DIR = Path(__file__).resolve().parent / "snapshots"

# ---------------------------------------------------------------- parâmetros
INICIO_TURNO_H = 16          # pedidos do turno: a partir das 16:00
FIM_MADRUGADA_H = 4          # 00:00–04:00 pertence ao turno anterior
TURNO_MOTOBOY = ((16, 30), (23, 45))
DIARIA_SEMANA = 100.0        # seg a sex
DIARIA_FDS = 120.0           # sáb e dom
POR_ENTREGA = 2.0

CMV = 0.265
COMISSAO_IFOOD = 0.128
IMPOSTO = 0.0945
CARTAO = 0.016

META_TICKET = 75.0
META_PREPARO = 20.0
META_ENTREGA = 45.0
META_CANCEL = 0.02
META_CUSTO_IFOOD = 0.25

LIMITE_EM_ROTA = 45.0
LIMITE_PARADO = 15.0

STATUS_FINALIZADO = {"ENTREGUE", "CONCLUIDO"}

# Sushi: peças por unidade vendida (ver pecas_por_unidade)
SUSHI_PECA_AVULSA = {"peça sushi", "peca sushi", "sashimi"}
SUSHI_PROMO_CATEGORIA = "promoção do dia"
SUSHI_PROMO_PRECO_MAX = 5.0  # peça avulsa da promoção (R$ 2,99 / 4,99), mesmo com outro nome
SUSHI_ROLO_SEM_NUMERO = 10   # Hot/Ura/Hosso sem "(N Un)" no nome (iFood) = 10 peças
RE_PECAS = re.compile(r"(\d+)\s*(?:peças|pecas|pçs|pcs|un\b|unid)", re.I)
COLUNAS_ESPERA = {"esperando preparo", "finalização", "finalizacao", "expedição",
                  "expedicao", "pronto p/ despacho", "a finalizar"}


class AlivError(RuntimeError):
    pass


# ------------------------------------------------------------------ cliente
class Aliv:
    """Cliente HTTP só leitura, sessão por cookie, relogin em 401."""

    def __init__(self, user: str, password: str, timeout: int = 30, raw_dir: Path | None = None):
        self.user, self.password, self.timeout = user, password, timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [("User-Agent", "tili-monitor/1.0"),
                                  ("Accept", "application/json")]
        self.raw_dir = raw_dir
        self.logged = False

    def login(self) -> None:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (("username", self.user), ("password", self.password)):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
        body = ("".join(parts) + f"--{boundary}--\r\n").encode()
        req = urllib.request.Request(
            BASE_URL + "/login-unified", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        status, data = self._send(req)
        if status != 200:
            msg = data.get("message") if isinstance(data, dict) else None
            raise AlivError(f"Login falhou (HTTP {status}): {msg or 'sem detalhe'}")
        if isinstance(data, dict) and data.get("twofa_required"):
            raise AlivError("Login exige 2FA (código) nesta conta — o monitor não consegue "
                            "rodar sozinho. Use um usuário sem 2FA, só leitura.")
        # Visita o redirect para o servidor terminar de montar a sessão, se precisar.
        redirect = data.get("redirect_url") if isinstance(data, dict) else None
        if redirect:
            try:
                self._send(urllib.request.Request(urllib.parse.urljoin(BASE_URL + "/", redirect)))
            except Exception:
                pass
        self.logged = True

    def get(self, path: str, params: dict | None = None):
        if not self.logged:
            self.login()
        url = BASE_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
        for tentativa in range(3):
            status, data = self._send(urllib.request.Request(url))
            if status == 401 and tentativa < 2:      # "Sessão expirada" → relogin
                self.login()
                continue
            if status in (429, 500, 502, 503, 504) and tentativa < 2:
                time.sleep(2 * (tentativa + 1))
                continue
            if status != 200:
                raise AlivError(f"GET {path} → HTTP {status}: {str(data)[:200]}")
            self._dump(path, params, data)
            return data
        raise AlivError(f"GET {path} falhou após novas tentativas")

    def enviar_whatsapp(self, telefone: str, texto: str) -> None:
        """Único envio do monitor: POST /admin/api/chat/send (mesmo do chat do ALIV),
        pelo WhatsApp principal da loja. Levanta AlivError se não confirmar."""
        boundary = uuid.uuid4().hex
        body = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                       for k, v in (("phone", telefone), ("message", texto)))
        body = (body + f"--{boundary}--\r\n").encode()
        req = urllib.request.Request(BASE_URL + "/admin/api/chat/send", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        status, data = self._send(req)
        if status == 401:
            self.login()
            status, data = self._send(req)
        if status != 200 or not (isinstance(data, dict) and data.get("success") is True):
            msg = data.get("message") if isinstance(data, dict) else None
            raise AlivError(f"WhatsApp não enviado (HTTP {status}): {msg or str(data)[:200]}")

    def _send(self, req):
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            return status, json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return status, {"_texto": raw[:300].decode("utf-8", "replace")}

    def _dump(self, path, params, data):
        if not self.raw_dir:
            return
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        nome = re.sub(r"[^A-Za-z0-9]+", "_", path + "_" + urllib.parse.urlencode(params or {}))
        (self.raw_dir / f"{nome[:150]}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- utilidades
def num(v) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("R$", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def brl(v: float) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: float) -> str:
    return f"{v * 100:.1f}%".replace(".", ",")


def parse_dt(v, ref_year: int) -> datetime | None:
    """Aceita ISO, epoch, 'dd/mm/aaaa HH:MM[:SS]' e 'dd/mm HH:MM'."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v) / (1000 if v > 1e12 else 1), TZ)
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.astimezone(TZ) if d.tzinfo else d.replace(tzinfo=TZ)
    except ValueError:
        pass
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\D+(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        dd, mm, yy, hh, mi, ss = m.groups()
        y = int(yy) if yy else ref_year
        y = y + 2000 if y < 100 else y
        return datetime(y, int(mm), int(dd), int(hh), int(mi), int(ss or 0), tzinfo=TZ)
    return None


def turno_de(agora: datetime) -> date:
    d = agora.date()
    return d - timedelta(days=1) if agora.hour < FIM_MADRUGADA_H else d


def janela_turno(dia: date) -> tuple[datetime, datetime]:
    ini = datetime(dia.year, dia.month, dia.day, INICIO_TURNO_H, tzinfo=TZ)
    fim = datetime(dia.year, dia.month, dia.day, FIM_MADRUGADA_H, tzinfo=TZ) + timedelta(days=1)
    return ini, fim


def descontos(det: dict) -> tuple[float, float, float]:
    """Retorna (loja, plataforma, manual) a partir de discount_origins (lista ou dict)."""
    loja = plat = manual = 0.0
    origens = det.get("discount_origins") or []
    itens = origens.items() if isinstance(origens, dict) else []
    if isinstance(origens, list):
        tmp = []
        for o in origens:
            if isinstance(o, dict):
                chave = o.get("kind") or o.get("origin") or o.get("origem") or o.get("source") or o.get("type") or ""
                valor = o.get("value", o.get("valor", o.get("amount", 0)))
                tmp.append((chave, valor))
            elif isinstance(o, str):
                tmp.append((o, det.get("discount_value", det.get("discount", 0))))
        itens = tmp
    for chave, valor in itens:
        c = str(chave).lower()
        if "plataforma" in c or "ifood" in c or "platform" in c:
            plat += num(valor)
        elif "manual" in c:
            manual += num(valor)
        else:
            loja += num(valor)
    return loja, plat, manual


def lista_pedidos(resp) -> list:
    if isinstance(resp, dict):
        return resp.get("orders") or []
    return resp if isinstance(resp, list) else []


# -------------------------------------------------------------------- coleta
def pedidos_do_turno(api: Aliv, dia: date, ate: datetime) -> list[dict]:
    """Lista + detalhe dos pedidos do turno `dia`, criados até `ate`."""
    ini, fim = janela_turno(dia)
    fim = min(fim, ate)
    brutos: dict = {}
    for d in (dia, dia + timedelta(days=1)):
        if datetime(d.year, d.month, d.day, tzinfo=TZ) > fim:
            break
        page = 1
        while page < 200:
            resp = api.get("/admin/api/orders/audit",
                           {"start_date": d.isoformat(), "end_date": d.isoformat(), "page": page})
            lote = lista_pedidos(resp)
            if not lote:
                break
            for o in lote:
                if isinstance(o, dict) and o.get("id") is not None:
                    brutos.setdefault(o["id"], o)
            # has_more do ALIV não é confiável (vem False antes da última página).
            page += 1

    with ThreadPoolExecutor(max_workers=6) as ex:
        detalhes = dict(zip(brutos, ex.map(lambda i: api.get(f"/admin/api/orders/{i}"), brutos)))

    pedidos = []
    for oid, item in brutos.items():
        det = detalhes[oid]
        if isinstance(det, dict) and isinstance(det.get("order"), dict):
            det = det["order"]
        det = {**item, **(det if isinstance(det, dict) else {})}
        criado = parse_dt(det.get("created_at") or det.get("created_at_fmt") or item.get("created_at"), dia.year)
        notas = str(det.get("notes") or "")
        agendado = "AGENDADO PARA" in notas.upper()
        if criado is None:
            continue
        no_turno = ini <= criado < fim
        agendado_do_dia = agendado and criado.date() == dia and criado < fim and (
            not re.search(r"\d{1,2}/\d{1,2}", notas) or dia.strftime("%d/%m") in notas)
        if not (no_turno or agendado_do_dia):
            continue
        det["_criado"] = criado
        det["_agendado"] = agendado
        pedidos.append(det)
    return pedidos


def motoboys(api: Aliv, dia: date) -> tuple[int, int, list]:
    resp = api.get("/admin/api/finance/drivers-live")
    lista = resp if isinstance(resp, list) else (resp.get("drivers") or resp.get("data") or []) if isinstance(resp, dict) else []
    online, entregas = [], 0
    for d in lista:
        if not isinstance(d, dict):
            continue
        if str(d.get("status", "")).strip().lower() != "online":
            continue
        ts = num(d.get("start_ts"))
        if not ts or datetime.fromtimestamp(ts, TZ).date() != dia:
            continue
        online.append(d)
        e = d.get("deliveries")
        entregas += len(e) if isinstance(e, list) else int(num(e))
    return len(online), entregas, online


def monitor_tempos(api: Aliv, inicio: datetime | None = None, fim: datetime | None = None) -> dict:
    if inicio is None:
        return api.get("/admin/api/operation-monitor/data", {"range_kind": "today"}) or {}
    fmt = "%Y-%m-%dT%H:%M:%S"
    return api.get("/admin/api/operation-monitor/data", {
        "range_kind": "custom", "start": inicio.strftime(fmt), "end": fim.strftime(fmt)}) or {}


# ------------------------------------------------------------------- cálculo
def status_de(p: dict) -> str:
    return str(p.get("status") or "").strip().upper()


def calcular(pedidos: list[dict], agora: datetime) -> dict:
    validos, cancelados, pix_pendente, ia_aguardando = [], [], [], []
    for p in pedidos:
        st = status_de(p)
        if st.startswith("CANCELADO"):
            cancelados.append(p)
        elif st == "AGUARDANDO_PAGAMENTO":
            pix_pendente.append(p)
        else:
            validos.append(p)
            if st == "AGUARDANDO_CONFIRMACAO" and "MONTADO PELA IA" in str(p.get("notes") or "").upper():
                ia_aguardando.append(p)

    r = {"pedidos": 0, "vendas": 0.0, "receita": 0.0, "por_canal": {}, "por_loja_ifood": {},
         "desc_loja": 0.0, "desc_plataforma": 0.0, "desc_manual": 0.0,
         "itens_entrega_ifood": 0.0, "comissao_ifood": 0.0, "desc_loja_ifood": 0.0,
         "receita_ifood": 0.0, "proprios": 0.0, "entregas_delivery": 0, "ids": []}
    for p in validos:
        canal = str(p.get("platform_slug") or "?").lower()
        pago = num(p.get("total_value"))
        loja, plat, manual = descontos(p)
        receita = pago + plat - num(p.get("service_fee"))
        r["pedidos"] += 1
        r["vendas"] += pago
        r["receita"] += receita
        r["desc_loja"] += loja + manual
        r["desc_plataforma"] += plat
        r["desc_manual"] += manual
        r["ids"].append(p.get("id"))
        c = r["por_canal"].setdefault(canal, [0, 0.0])
        c[0] += 1
        c[1] += pago
        if canal == "ifood":
            base = num(p.get("subtotal")) + num(p.get("delivery_fee")) - (loja + manual)
            r["comissao_ifood"] += max(base, 0) * COMISSAO_IFOOD
            r["desc_loja_ifood"] += loja + manual
            r["receita_ifood"] += receita
            b = r["por_loja_ifood"].setdefault(str(p.get("branch_label") or "?"), [0, 0.0])
            b[0] += 1
            b[1] += pago
        else:
            r["proprios"] += pago
        if str(p.get("delivery_type") or "").lower() == "delivery" and status_de(p) in STATUS_FINALIZADO:
            r["entregas_delivery"] += 1

    total = len(validos) + len(cancelados)
    r["cancelados"] = len(cancelados)
    r["taxa_cancel"] = len(cancelados) / total if total else 0.0
    r["ticket"] = r["vendas"] / r["pedidos"] if r["pedidos"] else 0.0
    r["pix_pendente"] = [p.get("wabiz_id") or p.get("code") or p.get("id") for p in pix_pendente]
    r["ia_aguardando"] = [p.get("wabiz_id") or p.get("code") or p.get("id") for p in ia_aguardando]
    r["custo_ifood"] = ((r["comissao_ifood"] + r["desc_loja_ifood"]) / r["receita_ifood"]
                        if r["receita_ifood"] else 0.0)
    r["ultima_hora_calc"] = sum(1 for p in validos if p["_criado"] >= agora - timedelta(hours=1))
    r["ultima_hora_valor_calc"] = sum(num(p.get("total_value")) for p in validos
                                      if p["_criado"] >= agora - timedelta(hours=1))
    return r


def itens_do_pedido(p: dict) -> list:
    it = p.get("items_json") or p.get("items") or []
    if isinstance(it, str):
        try:
            it = json.loads(it)
        except ValueError:
            return []
    return [i for i in it if isinstance(i, dict)] if isinstance(it, list) else []


def pecas_por_unidade(titulo: str, categoria: str = "", preco: float = 0.0) -> tuple[int, int]:
    """(peças de sushi, temakis) por unidade do item, pelo nome do produto.

    PEÇA SUSHI / Sashimi / "(unidade)" = 1 · item da "Promoção do Dia" até R$ 5 = 1
    (em 30/10 a peça de R$ 2,99 foi lançada como "Sunomono") · "( 10 Un )", "15 Peças",
    "(48 peças)" = N (vale o último número) · Hot/Ura/Hosso sem número = 10 ·
    Temaki conta à parte. Bebidas, poke, yakisoba, ceviche etc. = 0.
    """
    t = " ".join(str(titulo or "").lower().split())
    if "temaki" in t:
        return 0, 1
    promo = str(categoria or "").strip().lower() == SUSHI_PROMO_CATEGORIA
    if t in SUSHI_PECA_AVULSA or "(unidade)" in t or (promo and 0 < preco <= SUSHI_PROMO_PRECO_MAX):
        return 1, 0
    m = RE_PECAS.findall(t)
    if m:
        return int(m[-1]), 0
    if re.match(r"(hot|ura|hosso)\b", t):
        return SUSHI_ROLO_SEM_NUMERO, 0
    return 0, 0


def canal_sushi(p: dict) -> str:
    slug = str(p.get("platform_slug") or "?").lower()
    if slug == "pdv":
        return "PDV delivery" if str(p.get("delivery_type") or "").lower() == "delivery" else "Salão"
    return {"app": "App", "ifood": "iFood"}.get(slug, slug.upper())


def calcular_sushi(pedidos: list[dict], agora: datetime) -> dict:
    r = calcular(pedidos, agora)
    r["pecas"], r["temakis"], r["por_canal_sushi"] = 0, 0, {}
    for p in pedidos:
        st = status_de(p)
        if st.startswith("CANCELADO") or st == "AGUARDANDO_PAGAMENTO":
            continue
        pecas = tem = 0.0
        for i in itens_do_pedido(p):
            q = num(i.get("quantity") or 1)
            pp, tt = pecas_por_unidade(i.get("title") or i.get("name"), i.get("category_name"),
                                       num(i.get("price")))
            pecas += pp * q
            tem += tt * q
        c = r["por_canal_sushi"].setdefault(canal_sushi(p), [0, 0.0, 0])
        c[0] += 1
        c[1] += num(p.get("total_value"))
        c[2] += int(round(pecas))
        r["pecas"] += int(round(pecas))
        r["temakis"] += int(round(tem))
    return r


def custo_motoboys(n_online: int, entregas: int, dia: date, agora: datetime) -> float:
    diaria = DIARIA_FDS if dia.weekday() >= 5 else DIARIA_SEMANA
    (h1, m1), (h2, m2) = TURNO_MOTOBOY
    ini = datetime(dia.year, dia.month, dia.day, h1, m1, tzinfo=TZ)
    fim = datetime(dia.year, dia.month, dia.day, h2, m2, tzinfo=TZ)
    frac = min(max((agora - ini) / (fim - ini), 0.0), 1.0)
    return n_online * diaria * frac + entregas * POR_ENTREGA


def lucro(r: dict, custo_moto: float) -> dict:
    l = {"receita": r["receita"], "cmv": r["receita"] * CMV, "comissao": r["comissao_ifood"],
         "motoboys": custo_moto, "imposto": r["receita"] * IMPOSTO, "cartao": r["proprios"] * CARTAO}
    l["lucro"] = l["receita"] - sum(l[k] for k in ("cmv", "comissao", "motoboys", "imposto", "cartao"))
    l["margem"] = l["lucro"] / l["receita"] if l["receita"] else 0.0
    return l


# --------------------------------------------------------- tempos e alertas
def colunas(dados: dict) -> list[tuple[str, list]]:
    cols = dados.get("columns") if isinstance(dados, dict) else None
    out = []
    if isinstance(cols, dict):
        for nome, v in cols.items():
            cards = v if isinstance(v, list) else (v.get("orders") or v.get("cards") or v.get("items") or [])
            out.append((nome, cards))
    elif isinstance(cols, list):
        for c in cols:
            if isinstance(c, dict):
                nome = c.get("title") or c.get("name") or c.get("label") or c.get("key") or "?"
                out.append((nome, c.get("orders") or c.get("cards") or c.get("items") or []))
    return out


def alertas_operacao(dados: dict) -> dict:
    a = {"parado": [], "em_rota": [], "sem_motoboy": [], "piores": []}
    for nome, cards in colunas(dados):
        n = nome.strip().lower()
        if n == "finalizado":
            continue
        for c in cards:
            if not isinstance(c, dict):
                continue
            el = num(c.get("elapsed_min"))
            ref = str(c.get("code") or c.get("short_code") or c.get("id") or "?")
            bairro = c.get("neighborhood") or c.get("bairro")
            info = f"{ref} {el:.0f}min" + (f" ({bairro})" if bairro else "")
            a["piores"].append((el, f"{info} [{nome}]"))
            if n == "em rota" and el > LIMITE_EM_ROTA:
                a["em_rota"].append(info + (f" – {c['driver']}" if c.get("driver") else ""))
            if n == "pronto p/ despacho" and not c.get("driver"):
                a["sem_motoboy"].append(info)
            if n in COLUNAS_ESPERA and el > LIMITE_PARADO:
                a["parado"].append(f"{info} [{nome}]")
    a["piores"] = [t for _, t in sorted(a["piores"], reverse=True)[:3]]
    return a


def resumo(dados: dict, chave: str) -> dict:
    s = (dados.get("summary") or {}) if isinstance(dados, dict) else {}
    v = s.get(chave) or {}
    return v if isinstance(v, dict) else {}


def fmt_tempo(t: dict) -> str:
    if not t or not t.get("n"):
        return "sem dados"
    return (f"média {num(t.get('avg_min')):.0f} · p50 {num(t.get('p50_min')):.0f} · "
            f"máx {num(t.get('max_min')):.0f} min (n={int(num(t.get('n')))})")


def ok(cond: bool) -> str:
    return "✅" if cond else "⚠️"


# --------------------------------------------------------------- snapshots
def ler_snapshot(dia: date) -> dict:
    f = SNAP_DIR / f"{dia.isoformat()}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def motoboys_do_dia(dia: date, n_agora: int, ent_agora: int) -> tuple[int, int, int]:
    """(máximo online do dia, motoboys para o custo, entregas).

    O máximo fica no snapshot (max_motoboys_online). Se nesta rodada ninguém
    estiver online (fim do turno, todos Offline), o custo usa o máximo do dia.
    """
    snap = ler_snapshot(dia)
    rodadas = snap.get("rodadas", [])
    maximo = max([n_agora, int(num(snap.get("max_motoboys_online")))]
                 + [int(num(r.get("motoboys_online"))) for r in rodadas])
    entregas = max([ent_agora] + [int(num(r.get("entregas_live"))) for r in rodadas])
    return maximo, (n_agora if n_agora > 0 else maximo), entregas


def gravar_snapshot(dia: date, agora: datetime, r: dict, moto: dict | None = None,
                    sushi: dict | None = None) -> None:
    moto = moto or {"agora": 0, "maximo": 0, "entregas": 0}
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    snap = ler_snapshot(dia)
    rodadas = snap.get("rodadas", [])
    rodadas.append({"hora": agora.isoformat(timespec="minutes"), "pedidos": r["pedidos"],
                    "vendas": round(r["vendas"], 2), "ids": r["ids"],
                    "motoboys_online": moto["agora"], "entregas_live": moto["entregas"]})
    if sushi is not None:
        rodadas[-1].update({"sushi_pedidos": sushi["pedidos"], "sushi_vendas": round(sushi["vendas"], 2),
                            "sushi_pecas": sushi["pecas"]})
    snap = {"turno": dia.isoformat(),
            "max_motoboys_online": max(moto["maximo"], int(num(snap.get("max_motoboys_online")))),
            "rodadas": rodadas[-48:]}
    (SNAP_DIR / f"{dia.isoformat()}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


def ultima_hora(dia: date, agora: datetime, r: dict, prefixo: str = "") -> tuple[int, float, str]:
    """Diferença contra a rodada anterior (45–90 min atrás); senão, pela hora de criação.
    prefixo "sushi_" usa os campos da Tili Sushi no snapshot."""
    for rod in reversed(ler_snapshot(dia).get("rodadas", [])):
        try:
            h = datetime.fromisoformat(rod["hora"])
            ped, ven = int(rod[prefixo + "pedidos"]), num(rod[prefixo + "vendas"])
        except (KeyError, ValueError):
            continue
        if timedelta(minutes=45) <= agora - h <= timedelta(minutes=90):
            return r["pedidos"] - ped, r["vendas"] - ven, "snapshot"
    return r["ultima_hora_calc"], r["ultima_hora_valor_calc"], "hora de criação"


# ------------------------------------------------------------------ relatório
def var(a, b) -> str:
    return f"{'+' if a >= b else ''}{pct((a - b) / b)}" if b else "—"


def bloco_sushi(sushi: dict) -> list[str]:
    L = ["TILI SUSHI & POKE (loja 155)"]
    if sushi.get("erro"):
        return L + [f"• indisponível — {sushi['erro']}"]
    s, uh = sushi["r"], sushi["uh"]
    L.append(f"• Dia: {s['pedidos']} pedidos · {brl(s['vendas'])} · {s['pecas']} peças"
             + (f" + {s['temakis']} temakis" if s["temakis"] else ""))
    L.append(f"• Última hora: {uh[0]} pedidos · {brl(uh[1])} (por {uh[2]})")
    ordem = {"Salão": 0, "App": 1, "iFood": 2}
    canais = dict(s["por_canal_sushi"])
    for nome in ("Salão", "App", "iFood"):
        canais.setdefault(nome, [0, 0.0, 0])
    for nome, (n, v, pc) in sorted(canais.items(), key=lambda x: (ordem.get(x[0], 9), -x[1][1])):
        L.append(f"• {nome}: {n} · {brl(v)} · {pc} peças")
    L.append(f"• Ticket médio: {brl(s['ticket'])}")
    L.append(f"• Cancelados: {s['cancelados']} ({pct(s['taxa_cancel'])}) {ok(s['taxa_cancel'] <= META_CANCEL)} (meta até 2%)")
    if s["pix_pendente"]:
        L.append(f"• Pix pendente: {len(s['pix_pendente'])} — {', '.join(map(str, s['pix_pendente'][:6]))}")
    if s["ia_aguardando"]:
        L.append(f"• IA aguardando confirmação: {len(s['ia_aguardando'])} — {', '.join(map(str, s['ia_aguardando'][:6]))}")
    return L


def relatorio(agora: datetime, dia: date, r: dict, ops: dict, ops_h: dict, moto: tuple,
              uh: tuple, l: dict, sem: dict | None, sushi: dict | None = None) -> str:
    entregas_live = moto["entregas"]
    al = alertas_operacao(ops)
    prod_d = resumo(ops, "prod_delivery")
    rua = resumo(ops, "street")
    L = []
    assunto = f"Tili Pizzaria — {agora:%H:%M} — {r['pedidos']} pedidos / {brl(r['vendas'])}"
    if sushi and not sushi.get("erro"):
        assunto += f" · Sushi {sushi['r']['pedidos']} / {brl(sushi['r']['vendas'])}"
    L.append(assunto)
    L.append("")
    L.append(f"Turno {dia:%d/%m} (16h–04h) · atualizado {agora:%d/%m %H:%M} (America/Bahia)")
    L.append("")
    L.append("VENDAS")
    L.append(f"• Dia: {r['pedidos']} pedidos · {brl(r['vendas'])}")
    L.append(f"• Última hora: {uh[0]} pedidos · {brl(uh[1])} (por {uh[2]})")
    for canal, (n, v) in sorted(r["por_canal"].items(), key=lambda x: -x[1][1]):
        L.append(f"• {canal.upper()}: {n} · {brl(v)}")
    for loja, (n, v) in sorted(r["por_loja_ifood"].items(), key=lambda x: -x[1][1]):
        L.append(f"   iFood {loja}: {n} · {brl(v)}")
    L.append(f"• Ticket médio: {brl(r['ticket'])} {ok(r['ticket'] >= META_TICKET)} (meta {brl(META_TICKET)})")
    L.append(f"• Cancelados: {r['cancelados']} ({pct(r['taxa_cancel'])}) {ok(r['taxa_cancel'] <= META_CANCEL)} (meta até 2%)")
    L.append("")
    if sushi is not None:
        L.extend(bloco_sushi(sushi))
        L.append("")
    L.append("TEMPOS (Pizzaria)")
    L.append(f"• Preparo delivery: {fmt_tempo(prod_d)} {ok(num(prod_d.get('avg_min')) <= META_PREPARO) if prod_d.get('n') else ''}")
    L.append(f"• Preparo balcão: {fmt_tempo(resumo(ops, 'prod_balcao'))}")
    L.append(f"• Rua: {fmt_tempo(rua)}")
    life = resumo(ops, "life_delivery")
    L.append(f"• Vida delivery: {fmt_tempo(life)} {ok(num(life.get('avg_min')) <= META_ENTREGA) if life.get('n') else ''} (meta 45)")
    L.append(f"• Vida balcão: {fmt_tempo(resumo(ops, 'life_balcao'))}")
    L.append(f"• Última hora — preparo: {fmt_tempo(resumo(ops_h, 'prod_delivery'))}; rua: {fmt_tempo(resumo(ops_h, 'street'))}")
    L.append(f"• Piores agora: {'; '.join(al['piores']) or 'nenhum em aberto'}")
    L.append("")
    L.append("ALERTAS")
    L.append(f"• Parado >15 min: {len(al['parado'])}" + (f" — {', '.join(al['parado'][:6])}" if al["parado"] else ""))
    L.append(f"• Em rota >45 min: {len(al['em_rota'])}" + (f" — {', '.join(al['em_rota'][:6])}" if al["em_rota"] else ""))
    L.append(f"• Pronto sem motoboy: {len(al['sem_motoboy'])}" + (f" — {', '.join(al['sem_motoboy'][:6])}" if al["sem_motoboy"] else ""))
    L.append(f"• Pix pendente: {len(r['pix_pendente'])}" + (f" — {', '.join(map(str, r['pix_pendente'][:6]))}" if r["pix_pendente"] else ""))
    L.append(f"• IA aguardando confirmação: {len(r['ia_aguardando'])}" + (f" — {', '.join(map(str, r['ia_aguardando'][:6]))}" if r["ia_aguardando"] else ""))
    L.append("")
    L.append("MOTOBOYS")
    L.append(f"• Online agora: {moto['agora']} · máximo do dia: {moto['maximo']}"
             + (" (custo usa o máximo: ninguém online agora)" if moto["agora"] == 0 and moto["maximo"] else ""))
    L.append(f"• Entregas: {entregas_live} no ALIV (inclui Sushi) · {r['entregas_delivery']} delivery da Pizzaria finalizados")
    L.append(f"• Custo estimado: {brl(l['motoboys'])} (diária proporcional + R$ 2/entrega)")
    L.append("")
    L.append("DESCONTOS")
    L.append(f"• Loja: {brl(r['desc_loja'])}" + (f" (manual {brl(r['desc_manual'])})" if r["desc_manual"] else ""))
    L.append(f"• iFood (bancado pela plataforma): {brl(r['desc_plataforma'])}")
    L.append(f"• Custo iFood: {pct(r['custo_ifood'])} {ok(r['custo_ifood'] <= META_CUSTO_IFOOD)} (comissão + desconto loja ÷ receita iFood; meta até 25%)")
    L.append("")
    L.append("LUCRO ESTIMADO (margem de contribuição — ESTIMATIVA)")
    L.append(f"• Receita: {brl(l['receita'])}")
    L.append(f"• − CMV 26,5%: {brl(l['cmv'])} · − comissão iFood: {brl(l['comissao'])}")
    L.append(f"• − motoboys: {brl(l['motoboys'])} · − imposto 9,45%: {brl(l['imposto'])} · − cartão 1,6%: {brl(l['cartao'])}")
    L.append(f"• = {brl(l['lucro'])} ({pct(l['margem'])} da receita)")
    L.append("")
    L.append("SEMANA PASSADA (mesmo dia, mesmo horário)")
    if sem is None:
        L.append("• indisponível")
    else:
        L.append(f"• Pedidos: {r['pedidos']} vs {sem['pedidos']} ({var(r['pedidos'], sem['pedidos'])})")
        L.append(f"• Vendas: {brl(r['vendas'])} vs {brl(sem['vendas'])} ({var(r['vendas'], sem['vendas'])})")
        L.append(f"• Ticket: {brl(r['ticket'])} vs {brl(sem['ticket'])}")
        L.append(f"• Cancelamento: {pct(r['taxa_cancel'])} vs {pct(sem['taxa_cancel'])}")
    if sushi is not None and not sushi.get("erro") and sushi.get("sem"):
        s, w = sushi["r"], sushi["sem"]
        L.append(f"• Sushi — pedidos: {s['pedidos']} vs {w['pedidos']} ({var(s['pedidos'], w['pedidos'])}) · "
                 f"vendas: {brl(s['vendas'])} vs {brl(w['vendas'])} ({var(s['vendas'], w['vendas'])}) · "
                 f"peças: {s['pecas']} vs {w['pecas']} ({var(s['pecas'], w['pecas'])})")
    L.append("")
    L.append("Só leitura no ALIV. Tili Pizzaria (loja 150)"
             + (" + Tili Sushi & Poke (loja 155)." if sushi is not None else "."))
    return "\n".join(L)


# ----------------------------------------------------------------------- main
def coletar_sushi(raw_dir: Path | None, dia: date, agora: datetime, com_semana: bool) -> dict | None:
    """Tili Sushi (loja 155) com ALIV_USER_SUSHI / ALIV_PASS_SUSHI. None se não configurado;
    erro no ALIV vira {"erro": ...} e não derruba o relatório da Pizzaria."""
    user, pwd = os.environ.get("ALIV_USER_SUSHI"), os.environ.get("ALIV_PASS_SUSHI")
    if not user or not pwd:
        return None
    api = Aliv(user, pwd, raw_dir=raw_dir / "sushi" if raw_dir else None)
    try:
        api.login()
        r = calcular_sushi(pedidos_do_turno(api, dia, agora), agora)
        out = {"r": r, "uh": ultima_hora(dia, agora, r, "sushi_"), "sem": None}
        if com_semana:
            try:
                d7, a7 = dia - timedelta(days=7), agora - timedelta(days=7)
                out["sem"] = calcular_sushi(pedidos_do_turno(api, d7, a7), a7)
            except AlivError as e:
                print(f"aviso: comparação semanal do Sushi falhou: {e}", file=sys.stderr)
        return out
    except (AlivError, OSError) as e:
        print(f"aviso: Sushi falhou: {e}", file=sys.stderr)
        return {"erro": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Monitor de Operação da Tili (ALIV, só leitura)")
    ap.add_argument("--agora", help="simula o horário (AAAA-MM-DDTHH:MM), fuso America/Bahia")
    ap.add_argument("--sem-snapshot", action="store_true", help="não grava snapshot")
    ap.add_argument("--sem-semana", action="store_true", help="pula a comparação semanal")
    ap.add_argument("--raw", metavar="PASTA", help="salva as respostas cruas do ALIV (diagnóstico)")
    ap.add_argument("--whatsapp", action="store_true",
                    help="envia o relatório pelo WhatsApp da loja para WHATSAPP_EMERSON "
                         "(sai com código 3 se não enviar, para a Rotina usar o e-mail)")
    args = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: defina ALIV_USER e ALIV_PASS nas variáveis de ambiente.", file=sys.stderr)
        return 2

    agora = (datetime.fromisoformat(args.agora).replace(tzinfo=TZ) if args.agora
             else datetime.now(TZ)).replace(second=0, microsecond=0)
    dia = turno_de(agora)
    api = Aliv(user, pwd, raw_dir=Path(args.raw) if args.raw else None)

    try:
        api.login()
        pedidos = pedidos_do_turno(api, dia, agora)
        r = calcular(pedidos, agora)
        ops = monitor_tempos(api, janela_turno(dia)[0], agora)
        ops_h = monitor_tempos(api, agora - timedelta(hours=1), agora)
        n_agora, ent_agora, _ = motoboys(api, dia)
        maximo, n_custo, entregas = motoboys_do_dia(dia, n_agora, ent_agora)
        moto = {"agora": n_agora, "maximo": maximo, "custo": n_custo, "entregas": entregas}
        custo = custo_motoboys(n_custo, r["entregas_delivery"], dia, agora)
        l = lucro(r, custo)
        uh = ultima_hora(dia, agora, r)
        sem = None
        if not args.sem_semana:
            try:
                d7, a7 = dia - timedelta(days=7), agora - timedelta(days=7)
                sem = calcular(pedidos_do_turno(api, d7, a7), a7)
            except AlivError as e:
                print(f"aviso: comparação semanal falhou: {e}", file=sys.stderr)
    except AlivError as e:
        print(f"Tili Pizzaria — {agora:%H:%M} — ERRO no monitor\n\n{e}")
        return 1

    sushi = coletar_sushi(Path(args.raw) if args.raw else None, dia, agora, not args.sem_semana)
    texto = relatorio(agora, dia, r, ops, ops_h, moto, uh, l, sem, sushi)
    print(texto)
    if not args.sem_snapshot:
        gravar_snapshot(dia, agora, r, moto, sushi["r"] if sushi and not sushi.get("erro") else None)
    if args.whatsapp:
        fone = re.sub(r"\D", "", os.environ.get("WHATSAPP_EMERSON", ""))
        if not fone:
            print("WHATSAPP: não enviado — variável WHATSAPP_EMERSON não definida.", file=sys.stderr)
            return 3
        try:
            api.enviar_whatsapp(fone, texto)
            print("WHATSAPP: enviado.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {e}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
