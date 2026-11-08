#!/usr/bin/env python3
"""Previsão de motoboys do dia — Tili Pizzaria + Tili Sushi (só leitura no ALIV).

Roda às 08:00 (America/Bahia) e recomenda quantos motoboys chamar HOJE, com uma
faixa (ex.: 9 a 10) e o porquê em duas linhas.

Método (dias de comparação = mesmo dia da semana nas últimas 4 semanas + mesmo
dia do mês passado), janela 16:00–00:00 de cada dia:
  • Pizzaria: pedidos de delivery por hora (audit, cancelados fora).
  • Sushi: entregas por hora (audit do login do Sushi; mesmos motoboys).
  • Motoboys: quem trabalhou no dia (drivers-report, 3+ entregas, gerentes fora) e,
    por hora, quantos levaram pedido criado naquela hora (motoboy do audit, Pizzaria + Sushi).
  • Tempos da Pizzaria (operation-monitor): rua média, vida média e quantas
    entregas passaram de 45 min (janelas divididas até isolar cada pedido).
  • Pico = hora com mais entregas (Pizzaria + Sushi). Entregas por motoboy por
    hora no pico = entregas da hora ÷ motoboys em turno nessa hora.
  • Dia "estourado" = mais de 10% das entregas acima de 45 min ou vida média > 45.
  • Capacidade segura = o melhor ritmo (entregas/motoboy/hora no pico) de um dia
    que NÃO estourou. Recomendação = pico previsto ÷ capacidade, arredondado em
    faixa; nunca abaixo do nº de motoboys de um dia que estourou com movimento parecido.
  • Ajustes: feriado/data forte (+20%), véspera (+15%), promoção (+10%,
    monitor/assets/promocoes.json). Dias da base que eram feriado/véspera/promo
    são descontados do ajuste antes de entrar na média.
  • Alerta se algum dia dos últimos 7 teve atraso.

Uso:
  python3 monitor/previsao_motoboys.py                  # hoje, imprime e NÃO envia
  python3 monitor/previsao_motoboys.py --data 2026-11-08
  python3 monitor/previsao_motoboys.py --painel p.png   # gera o painel em PNG, sem enviar
  python3 monitor/previsao_motoboys.py --whatsapp       # envia o painel para EMERSON, JOSUE e CAMILO
  python3 monitor/previsao_motoboys.py --promo          # força "tem promoção hoje"

Códigos de saída: 0 ok · 1 erro no ALIV · 2 faltam ALIV_USER/ALIV_PASS ·
3 previsão ok, mas nenhum WhatsApp enviado (a Rotina manda por e-mail).
Não grava nada em arquivo e não mostra nomes, CPF ou CNPJ: só números.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import Aliv, AlivError, TZ, lista_pedidos, num, parse_dt  # noqa: E402

# ---------------------------------------------------------------- parâmetros
HORA_INI, HORA_FIM = 16, 24          # janela analisada: 16:00 até 00:00
LIMITE_MIN = 45                      # entrega acima disso = atrasada
LIMITE_ATRASO_PCT = 0.10             # dia "estourado": >10% acima de 45 min...
LIMITE_VIDA_MEDIA = 45               # ...ou vida média acima de 45 min
PESOS = [0.35, 0.25, 0.15, 0.10]     # semanas -1, -2, -3, -4
PESO_MES = 0.15                      # mesmo dia do mês passado
AJ_FERIADO, AJ_VESPERA, AJ_PROMO = 1.20, 1.15, 1.10
CAPACIDADE_PADRAO = 4.0              # entregas/motoboy/hora, se nenhum dia servir de base
GERENTES = [{"thiago", "camilo"}, {"josue", "ruas"}]   # logins de gerente no ALIV (qualquer ordem)
MIN_ENTREGAS = 3                     # menos que isso no dia = não conta como motoboy do dia
DESTINOS = ("WHATSAPP_EMERSON", "WHATSAPP_JOSUE", "WHATSAPP_CAMILO")
PROMO_ARQ = Path(__file__).resolve().parent / "assets" / "promocoes.json"
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
DIAS_CURTO = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


# ---------------------------------------------------------------- calendário
def pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    return date(ano, mes, (h + l - 7 * m + 114) % 31 + 1)


def feriados(ano: int) -> dict[date, str]:
    p = pascoa(ano)
    f = {date(ano, 1, 1): "Ano Novo", date(ano, 4, 21): "Tiradentes", date(ano, 5, 1): "Dia do Trabalho",
         date(ano, 7, 2): "Independência da Bahia", date(ano, 9, 7): "Independência",
         date(ano, 10, 12): "N. Sra. Aparecida", date(ano, 11, 2): "Finados",
         date(ano, 11, 15): "Proclamação da República", date(ano, 11, 20): "Consciência Negra",
         date(ano, 12, 25): "Natal",
         p - timedelta(days=48): "Carnaval", p - timedelta(days=47): "Carnaval",
         p - timedelta(days=2): "Sexta-feira Santa", p + timedelta(days=60): "Corpus Christi"}
    # datas fortes para delivery (não são feriado, mas o movimento sobe)
    maio = date(ano, 5, 1)
    f[maio + timedelta(days=(6 - maio.weekday()) % 7 + 7)] = "Dia das Mães"
    ago = date(ano, 8, 1)
    f[ago + timedelta(days=(6 - ago.weekday()) % 7 + 7)] = "Dia dos Pais"
    f[date(ano, 6, 12)] = "Dia dos Namorados"
    for extra in promocoes().get("feriados_extra", []):        # ex.: feriado municipal
        try:
            d = date.fromisoformat(extra["data"])
            if d.year == ano:
                f[d] = extra.get("nome", "feriado")
        except (KeyError, ValueError, TypeError):
            pass
    return f


def promocoes() -> dict:
    """monitor/assets/promocoes.json: {"dias_semana": ["quarta"], "datas": ["2026-11-11"],
    "feriados_extra": [{"data": "2026-12-08", "nome": "..."}]}. Sem arquivo = sem promoção."""
    try:
        return json.loads(PROMO_ARQ.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tem_promo(d: date) -> bool:
    p = promocoes()
    return d.isoformat() in p.get("datas", []) or DIAS[d.weekday()] in [str(x).lower() for x in p.get("dias_semana", [])]


def contexto(d: date, forcar_promo: bool) -> tuple[float, list[str]]:
    fer = {**feriados(d.year), **feriados(d.year + 1)}
    fator, motivos = 1.0, []
    if d in fer:
        fator *= AJ_FERIADO
        motivos.append(f"{fer[d]} hoje (+{round((AJ_FERIADO - 1) * 100)}%)")
    elif d + timedelta(days=1) in fer or d.month == 12 and d.day in (24, 31):
        nome = fer.get(d + timedelta(days=1), "Natal/Ano Novo")
        fator *= AJ_VESPERA
        motivos.append(f"véspera de {nome} (+{round((AJ_VESPERA - 1) * 100)}%)")
    if forcar_promo or tem_promo(d):
        fator *= AJ_PROMO
        motivos.append(f"promoção hoje (+{round((AJ_PROMO - 1) * 100)}%)")
    return fator, motivos


def dias_base(hoje: date) -> list[tuple[str, date]]:
    out = [(f"-{i}sem", hoje - timedelta(weeks=i)) for i in range(1, 5)]
    m, a = (hoje.month - 1, hoje.year) if hoje.month > 1 else (12, hoje.year - 1)
    try:
        mes = date(a, m, hoje.day)
    except ValueError:                       # 31 → último dia do mês anterior
        mes = date(hoje.year, hoje.month, 1) - timedelta(days=1)
    if mes not in [d for _, d in out]:
        out.append(("mês", mes))
    return out


# ---------------------------------------------------------------- coleta
@dataclass
class Dia:
    dia: date
    piz_h: dict = field(default_factory=dict)     # hora -> pedidos delivery Pizzaria
    sushi_h: dict = field(default_factory=dict)   # hora -> entregas Sushi
    moto_h: dict = field(default_factory=dict)    # hora -> motoboys em turno
    motoboys: int = 0
    rua: float = 0.0
    vida: float = 0.0
    vida_n: int = 0
    atrasos: int = 0
    sushi_ok: bool = True
    fator: float = 1.0                           # feriado/véspera/promo daquele dia

    @property
    def total_h(self) -> dict:
        return {h: self.piz_h.get(h, 0) + self.sushi_h.get(h, 0) for h in range(HORA_INI, HORA_FIM)}

    @property
    def pico(self) -> int:
        t = self.total_h
        return max(t, key=lambda h: (t[h], -h))

    @property
    def entregas_pico(self) -> int:
        return self.total_h[self.pico]

    @property
    def motos_pico(self) -> int:
        return self.moto_h.get(self.pico) or self.motoboys

    @property
    def eph(self) -> float:
        return self.entregas_pico / self.motos_pico if self.motos_pico else 0.0

    @property
    def pct_atraso(self) -> float:
        return self.atrasos / self.vida_n if self.vida_n else 0.0

    @property
    def estourou(self) -> bool:
        return self.pct_atraso > LIMITE_ATRASO_PCT or self.vida > LIMITE_VIDA_MEDIA


def eh_gerente(nome: str) -> bool:
    t = set(re.sub(r"[^a-z ]", "", str(nome).lower()).split())
    return any(g <= t for g in GERENTES)


def entregas_por_hora(api: Aliv, d: date) -> tuple[dict, dict]:
    """Pedidos delivery (não cancelados, não Pix pendente) criados de 16:00 a 23:59, por hora,
    e os motoboys (nome no audit) que levaram pedido criado em cada hora."""
    por_h, motos_h, page = {}, {}, 1
    while page < 50:
        lote = lista_pedidos(api.get("/admin/api/orders/audit", {
            "start_date": d.isoformat(), "end_date": d.isoformat(), "page": page, "limit": 200}))
        if not lote:
            break
        for o in lote:
            st = str(o.get("status") or "").upper()
            if str(o.get("delivery_type") or "").lower() != "delivery" or st.startswith("CANCEL") \
                    or st == "AGUARDANDO_PAGAMENTO":
                continue
            c = parse_dt(o.get("created_at"), d.year)
            if c and c.date() == d and HORA_INI <= c.hour < HORA_FIM:
                por_h[c.hour] = por_h.get(c.hour, 0) + 1
                m = str(o.get("driver") or "").strip()
                if m and m.lower() != "sem motoboy" and not eh_gerente(m):
                    motos_h.setdefault(c.hour, set()).add(m.lower())
        page += 1
    return por_h, motos_h


def janela_ops(api: Aliv, ini: datetime, fim: datetime) -> dict:
    f = "%Y-%m-%dT%H:%M:%S"
    r = api.get("/admin/api/operation-monitor/data",
                {"range_kind": "custom", "start": ini.strftime(f), "end": fim.strftime(f)}) or {}
    return (r.get("summary") or {}) if isinstance(r, dict) else {}


def conta_atrasos(api: Aliv, ini: datetime, fim: datetime, vida: dict | None = None) -> int:
    """Entregas (vida delivery) acima de 45 min na janela: divide a janela ao meio até
    isolar cada pedido. Num minuto com vários pedidos, estima pela média/mediana."""
    if vida is None:
        vida = janela_ops(api, ini, fim).get("life_delivery") or {}
    n, mx = int(num(vida.get("n"))), num(vida.get("max_min"))
    if n == 0 or mx <= LIMITE_MIN:
        return 0
    if num(vida.get("avg_min")) > LIMITE_MIN and num(vida.get("p50_min")) > LIMITE_MIN and n <= 2:
        return n
    if n == 1:
        return 1
    if fim - ini <= timedelta(minutes=1):
        if num(vida.get("avg_min")) > LIMITE_MIN:
            return n
        return max(1, math.ceil(n / 2)) if num(vida.get("p50_min")) > LIMITE_MIN else 1
    meio = ini + (fim - ini) / 2
    meio = meio.replace(second=0, microsecond=0)
    if meio <= ini:
        meio = ini + timedelta(minutes=1)
    return conta_atrasos(api, ini, meio) + conta_atrasos(api, meio, fim)


def motoboys_do_dia(api: Aliv, d: date) -> int:
    """Motoboys que trabalharam no dia (drivers-report): 3+ entregas, gerentes fora."""
    rel = api.get("/admin/api/finance/drivers-report", {
        "start": d.isoformat(), "end": (d + timedelta(days=1)).isoformat(),
        "tipo": "entrega,financeiro", "date_basis": "delivery"})
    rows = (rel.get("rows") if isinstance(rel, dict) else []) or []
    return sum(1 for r in rows if int(num(r.get("entregas"))) >= MIN_ENTREGAS and not eh_gerente(r.get("name", "")))


def coletar_dia(api: Aliv, api_sushi: Aliv | None, d: date) -> Dia:
    x = Dia(d)
    x.piz_h, motos = entregas_por_hora(api, d)
    if api_sushi is not None:
        try:
            x.sushi_h, ms = entregas_por_hora(api_sushi, d)
            for h, v in ms.items():
                motos.setdefault(h, set()).update(v)
        except (AlivError, OSError) as e:
            print(f"aviso: Sushi {d} falhou: {e}", file=sys.stderr)
            x.sushi_ok = False
    else:
        x.sushi_ok = False
    x.moto_h = {h: len(v) for h, v in motos.items()}
    x.motoboys = motoboys_do_dia(api, d)
    x.fator = contexto(d, False)[0]
    ini = datetime(d.year, d.month, d.day, HORA_INI, tzinfo=TZ)
    fim = datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(hours=HORA_FIM)
    s = janela_ops(api, ini, fim)
    vida, rua = s.get("life_delivery") or {}, s.get("street") or {}
    x.vida, x.vida_n, x.rua = num(vida.get("avg_min")), int(num(vida.get("n"))), num(rua.get("avg_min"))
    x.atrasos = conta_atrasos(api, ini, fim, vida)
    return x


def atraso_semana(api: Aliv, hoje: date) -> list[tuple[date, int, int, float]]:
    """Dias dos últimos 7 com entrega acima de 45 min: (dia, atrasos, n, vida média)."""
    def um(d: date):
        ini = datetime(d.year, d.month, d.day, HORA_INI, tzinfo=TZ)
        fim = datetime(d.year, d.month, d.day, tzinfo=TZ) + timedelta(hours=HORA_FIM)
        vida = janela_ops(api, ini, fim).get("life_delivery") or {}
        return d, conta_atrasos(api, ini, fim, vida), int(num(vida.get("n"))), num(vida.get("avg_min"))
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(um, [hoje - timedelta(days=i) for i in range(7, 0, -1)]))
    return [r for r in res if r[1] > 0]


# ---------------------------------------------------------------- previsão
def recomendar(base: list[tuple[str, Dia]], fator: float) -> dict:
    pesos = {f"-{i + 1}sem": p for i, p in enumerate(PESOS)} | {"mês": PESO_MES}
    usados = [(pesos[k], x) for k, x in base if x.entregas_pico > 0]
    tot = sum(p for p, _ in usados) or 1.0
    pico_prev = sum(p * x.entregas_pico / x.fator for p, x in usados) / tot * fator
    dia_prev = sum(p * sum(x.total_h.values()) / x.fator for p, x in usados) / tot * fator
    horas_prev = {h: sum(p * x.total_h[h] / x.fator for p, x in usados) / tot * fator
                  for h in range(HORA_INI, HORA_FIM)}

    bons = [x for _, x in base if not x.estourou and x.eph > 0]
    ruins = [x for _, x in base if x.estourou and x.eph > 0]
    if bons:
        cap = max(x.eph for x in bons)
    elif ruins:
        cap = min(x.eph for x in ruins) * 0.85     # todos estouraram: ritmo 15% menor
    else:
        cap = CAPACIDADE_PADRAO
    cap = max(cap, 1.0)
    if pico_prev <= 0:
        return {"pico_prev": 0.0, "dia_prev": 0.0, "cap": cap, "lo": 1, "hi": 2, "base_cap": None,
                "ruins": ruins, "horas_prev": horas_prev}
    alvo = pico_prev / cap
    lo = max(1, math.floor(alvo))
    hi = max(lo + 1, math.ceil(alvo)) if alvo - lo > 0.15 or alvo == lo else lo + 1
    # piso: um dia que estourou com pico parecido (±10%) pede mais motoboys do que ele tinha
    # (só conta se o ritmo passou da capacidade: se cada motoboy fez pouco e mesmo assim atrasou,
    # o gargalo foi a cozinha/expedição, e mais motoboy não resolve)
    piso = max([x.motos_pico + 1 for x in ruins
                if 0.9 <= x.entregas_pico / pico_prev <= 1.1 and x.eph > cap] or [0])
    if piso > lo:
        lo, hi = piso, max(hi, piso + 1)
    if hi - lo > 1:
        lo = hi - 1
    return {"pico_prev": pico_prev, "dia_prev": dia_prev, "cap": cap, "lo": lo, "hi": hi,
            "base_cap": bons and max(bons, key=lambda x: x.eph) or None, "ruins": ruins,
            "horas_prev": horas_prev}


# ---------------------------------------------------------------- texto
def f1(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def linha_hist(k: str, x: Dia) -> str:
    sushi = "" if x.sushi_ok else " (sem Sushi)"
    marca = " ⚠️ estourou" if x.estourou else " ✅"
    return (f"{x.dia:%d/%m} {DIAS_CURTO[x.dia.weekday()]}: {sum(x.total_h.values())} entregas{sushi} · "
            f"{x.motoboys} motoboys · pico {x.pico}h {x.entregas_pico} ({f1(x.eph)}/moto/h) · "
            f"rua {x.rua:.0f} · vida {x.vida:.0f} min · {x.atrasos} >45min ({x.pct_atraso * 100:.0f}%){marca}")


def mensagem(hoje: date, base: list[tuple[str, Dia]], rec: dict, motivos: list[str],
             semana: list[tuple[date, int, int, float]]) -> str:
    L = [f"*Tili — Motoboys hoje {hoje:%d/%m} ({DIAS[hoje.weekday()]})*",
         f"👉 Chamar *{rec['lo']} a {rec['hi']} motoboys*"]
    b = rec["base_cap"]
    porque1 = (f"Pico previsto ~{rec['pico_prev']:.0f} entregas/h (Pizzaria + Sushi)"
               + (f", {', '.join(motivos)}" if motivos else "") + ".")
    if b:
        porque2 = (f"Sem atraso, cada motoboy faz até {f1(rec['cap'])} entregas/h no pico "
                   f"(como em {b.dia:%d/%m}, com {b.motos_pico} em turno).")
    else:
        porque2 = f"Nenhum dia sem atraso na base: usei ritmo de {f1(rec['cap'])} entregas/motoboy/h para folgar."
    sobrecarga = [x for x in rec["ruins"] if x.eph > rec["cap"]]
    if sobrecarga:
        r = max(sobrecarga, key=lambda x: x.eph)
        porque2 += (f" Em {r.dia:%d/%m} estourou com {r.motos_pico} no pico ({f1(r.eph)}/moto/h).")
    elif rec["ruins"]:
        porque2 += " Os dias que estouraram não tinham falta de motoboy: o atraso veio da cozinha/expedição."
    L += [porque1, porque2, "", "*Últimas 4 semanas*"]
    L += [linha_hist(k, x) for k, x in base if k != "mês"]
    mes = [x for k, x in base if k == "mês"]
    if mes:
        L.append("Mês passado: " + linha_hist("mês", mes[0]))
    if semana:
        L += ["", f"⚠️ *Atraso na semana passada* ({len(semana)} de 7 dias, entregas >45min): " + " · ".join(
            f"{DIAS_CURTO[d.weekday()]} {d:%d/%m} {a}" for d, a, n, v in semana)]
    else:
        L += ["", "✅ Semana passada sem entrega acima de 45 min."]
    return "\n".join(L)


# ---------------------------------------------------------------- cache de teste
def gravar_dados(arq: Path, base: list, semana: list) -> None:
    def dia(x: Dia) -> dict:
        d = asdict(x)
        d["dia"] = x.dia.isoformat()
        return d
    arq.write_text(json.dumps({"base": [[k, dia(x)] for k, x in base],
                               "semana": [[d.isoformat(), a, n, v] for d, a, n, v in semana]}), encoding="utf-8")


def ler_dados(arq: Path) -> tuple[list, list]:
    j = json.loads(arq.read_text(encoding="utf-8"))
    base = []
    for k, d in j["base"]:
        d["dia"] = date.fromisoformat(d["dia"])
        for c in ("piz_h", "sushi_h", "moto_h"):
            d[c] = {int(h): v for h, v in d[c].items()}
        base.append((k, Dia(**d)))
    return base, [(date.fromisoformat(d), a, n, v) for d, a, n, v in j["semana"]]


# ---------------------------------------------------------------- main
def fone_remetente(var: str) -> str:
    """Sem WHATSAPP_JOSUE / WHATSAPP_CAMILO, usa o número do mesmo nome em DESPESAS_REMETENTES
    ("numero=Nome,numero=Nome", a lista das despesas)."""
    chave = var.removeprefix("WHATSAPP_").lower()
    for item in os.environ.get("DESPESAS_REMETENTES", "").split(","):
        num_, _, nome = item.partition("=")
        nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
        if chave in nome.split():
            return re.sub(r"\D", "", num_)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Previsão de motoboys do dia (ALIV, só leitura)")
    ap.add_argument("--data", help="dia da previsão (AAAA-MM-DD); padrão: hoje")
    ap.add_argument("--promo", action="store_true", help="considera promoção hoje")
    ap.add_argument("--whatsapp", action="store_true",
                    help="envia para WHATSAPP_EMERSON, WHATSAPP_JOSUE e WHATSAPP_CAMILO")
    ap.add_argument("--raw", metavar="PASTA", help="salva as respostas cruas do ALIV (diagnóstico, não commitar)")
    ap.add_argument("--painel", metavar="ARQ.png", help="salva o painel em PNG neste arquivo")
    ap.add_argument("--sem-painel", action="store_true", help="não gera o painel (manda só o texto)")
    ap.add_argument("--salvar-dados", metavar="ARQ.json", help="guarda os números coletados (para testar o painel)")
    ap.add_argument("--usar-dados", metavar="ARQ.json", help="usa números já coletados, sem consultar o ALIV")
    args = ap.parse_args()

    user, pwd = os.environ.get("ALIV_USER"), os.environ.get("ALIV_PASS")
    if not user or not pwd:
        print("ERRO: defina ALIV_USER e ALIV_PASS nas variáveis de ambiente.", file=sys.stderr)
        return 2
    hoje = date.fromisoformat(args.data) if args.data else datetime.now(TZ).date()
    raw = Path(args.raw) if args.raw else None
    api = Aliv(user, pwd, raw_dir=raw)
    api_sushi = None
    us, ps = os.environ.get("ALIV_USER_SUSHI"), os.environ.get("ALIV_PASS_SUSHI")
    if us and ps:
        api_sushi = Aliv(us, ps, raw_dir=raw / "sushi" if raw else None)
        try:
            api_sushi.login()
        except (AlivError, OSError) as e:
            print(f"aviso: login do Sushi falhou: {e}", file=sys.stderr)
            api_sushi = None

    try:
        api.login()
        if args.usar_dados:
            base, semana = ler_dados(Path(args.usar_dados))
        else:
            dias = dias_base(hoje)
            with ThreadPoolExecutor(3) as ex:
                base = list(zip([k for k, _ in dias], ex.map(lambda kd: coletar_dia(api, api_sushi, kd[1]), dias)))
            semana = atraso_semana(api, hoje)
            if args.salvar_dados:
                gravar_dados(Path(args.salvar_dados), base, semana)
    except AlivError as e:
        print(f"Tili — Motoboys {hoje:%d/%m} — ERRO no ALIV\n\n{e}")
        return 1

    fator, motivos = contexto(hoje, args.promo)
    rec = recomendar(base, fator)
    texto = mensagem(hoje, base, rec, motivos, semana)
    print(texto)

    print("\n--- detalhe por hora (entregas Pizzaria+Sushi / motoboys em turno) ---", file=sys.stderr)
    for k, x in base:
        t = x.total_h
        print(f"{k:>5} {x.dia:%d/%m}: " + " ".join(f"{h}h {t[h]}/{x.moto_h.get(h, 0)}" for h in t), file=sys.stderr)
    print(f"capacidade {rec['cap']:.2f}/moto/h · pico previsto {rec['pico_prev']:.1f} · "
          f"dia previsto {rec['dia_prev']:.0f} · fator {fator:.2f}", file=sys.stderr)

    painel = None
    if not args.sem_painel and (args.painel or args.whatsapp):
        destino = Path(args.painel) if args.painel else Path(tempfile.mkdtemp()) / f"motoboys_{hoje:%d-%m}.png"
        try:
            from painel_motoboys import gerar_painel
            painel = gerar_painel(destino, hoje, base, rec, motivos, semana)
            print(f"PAINEL: {painel}", file=sys.stderr)
        except Exception as e:      # o painel nunca derruba a previsão em texto
            print(f"PAINEL: não gerado — {e}", file=sys.stderr)

    if not args.whatsapp:
        print("\nWHATSAPP: não enviado (sem --whatsapp).", file=sys.stderr)
        return 0
    # Como o painel de vendas: vai só a imagem (legenda curta); o texto só se a imagem falhar.
    legenda = f"Motoboys hoje {hoje:%d/%m}: chamar {rec['lo']} a {rec['hi']}"
    enviados = 0
    for var in DESTINOS:
        fone = re.sub(r"\D", "", os.environ.get(var, "")) or fone_remetente(var)
        if not fone:
            print(f"WHATSAPP: {var} não definida — pulado.", file=sys.stderr)
            continue
        if painel is not None:
            try:
                api.enviar_whatsapp(fone, legenda, arquivo=painel)
                enviados += 1
                print(f"WHATSAPP: painel enviado para {var}.", file=sys.stderr)
                continue
            except (AlivError, OSError) as e:
                print(f"WHATSAPP: painel não enviado para {var} — {e}; mandando o texto", file=sys.stderr)
        try:
            api.enviar_whatsapp(fone, texto)
            enviados += 1
            print(f"WHATSAPP: texto enviado para {var}.", file=sys.stderr)
        except (AlivError, OSError) as e:
            print(f"WHATSAPP: {var} falhou — {e}", file=sys.stderr)
    return 0 if enviados else 3


if __name__ == "__main__":
    sys.exit(main())
