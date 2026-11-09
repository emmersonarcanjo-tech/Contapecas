#!/usr/bin/env python3
"""Auditoria do atendimento da IA no WhatsApp da Tili Pizzaria (loja 150) e da Tili Sushi (loja 155) — só leitura.

Uso normal (Rotina das 03:30, fuso da Bahia):
    python3 monitor/atendimento_ia.py --whatsapp

Lê as conversas do chat do ALIV do turno que fechou (16:00 até 01:00), cruza com
os pedidos do turno (orders/audit + nota "Pedido montado pela IA"), classifica os
problemas e grava monitor/atendimento/AAAA-MM-DD.md (relatório) e .json (só números
e pares propostos). Nenhum nome, telefone ou endereço de cliente vai para os arquivos.

Só faz GET no ALIV, fora o login e o envio do resumo para WHATSAPP_EMERSON
(POST /admin/api/chat/send, o mesmo do monitor.py). Nunca responde cliente, não marca
conversa como atendida e não liga/desliga a IA.

Comando separado, só com ordem do Emerson na sessão:
    python3 monitor/atendimento_ia.py aprovar --data AAAA-MM-DD --par N [--no-lugar-de M] [--confirmo]
Sem --confirmo só mostra o antes/depois. Com --confirmo grava no campo
"Ensine o jeito da sua loja" (POST /admin/api/openai/sync, ver README).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import Aliv, AlivError, lista_pedidos, parse_dt  # noqa: E402
from painel import ROTULOS  # noqa: E402

TZ = ZoneInfo("America/Bahia")
PASTA = Path(__file__).resolve().parent / "atendimento"
# Cada loja tem o seu login no ALIV. Arquivos: AAAA-MM-DD.md (Pizzaria) e AAAA-MM-DD_sushi.md (Sushi).
LOJAS = {
    "pizzaria": {"id": 150, "nome": "Tili Pizzaria", "curto": "Pizzaria", "user": "ALIV_USER",
                 "senha": "ALIV_PASS", "sufixo": "", "emoji": "🍕"},
    "sushi": {"id": 155, "nome": "Tili Sushi & Poke", "curto": "Sushi", "user": "ALIV_USER_SUSHI",
              "senha": "ALIV_PASS_SUSHI", "sufixo": "_sushi", "emoji": "🍣"},
}
LOJA = 150
SUFIXO = ""
LOJA_INFO = LOJAS["pizzaria"]


def usar_loja(chave: str) -> dict:
    global LOJA, SUFIXO, LOJA_INFO
    LOJA_INFO = LOJAS[chave]
    LOJA, SUFIXO = LOJA_INFO["id"], LOJA_INFO["sufixo"]
    return LOJA_INFO
INICIO_H, FIM_H = 16, 1                 # turno: 16:00 de D até 01:00 de D+1
DEMORA_MIN = 5                           # resposta acima disso = "demora"
MAX_EXEMPLOS = 5                         # limite do campo no ALIV
LIMITE_MSGS = 500
BUSCA_PREFIXOS = ("5573",)               # DDD 73; a busca do ALIV corta em ~20 resultados
BUSCA_MAX_CHAMADAS = 2000
NOTA_IA = "montado pela ia"

PROBLEMAS = {
    "nao_entendeu": "Não entendeu o pedido",
    "item_preco": "Item ou preço errado",
    "endereco_taxa": "Endereço ou taxa de entrega errada",
    "demora": f"Demora na resposta (> {DEMORA_MIN} min)",
    "repetiu": "Pediu a mesma informação duas vezes",
    "reclamou_humano": "Cliente reclamou ou pediu humano",
    "nao_soube": "Pergunta que a IA não soube responder",
    "cancelado": "Pedido cancelado depois de montado",
}


class AlivLeitura(Aliv):
    """Aliv do monitor.py + nova tentativa quando o ALIV derruba a conexão (só em GET)."""

    def _send(self, req):
        for tentativa in range(5):
            try:
                return super()._send(req)
            except OSError:
                if req.get_method() != "GET" or tentativa == 4:
                    raise
                time.sleep(2 ** tentativa)


# ------------------------------------------------------------------ texto
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip()


def tem(texto: str, padroes) -> bool:
    t = norm(texto)
    return any(re.search(p, t) for p in padroes)


def digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def chave_fone(s) -> str:
    """Últimos 8 dígitos: o ALIV guarda o chat sem o 9 e os pedidos às vezes com."""
    d = digitos(s)
    return d[-8:] if len(d) >= 8 else ""


# Cliente
C_NAO_ENTENDEU = [r"nao (foi|e) (isso|esse|essa)", r"nao (pedi|falei|disse) (isso|esse|essa)",
                  r"voce nao entendeu", r"nao entendeu", r"ta errado o pedido", r"pedido (ta|esta) errado",
                  r"nao (e|era) (esse|essa) (sabor|pizza|tamanho)", r"eu (pedi|falei|disse) (que|uma|um|o|a)\b"]
C_ITEM_PRECO = [r"(preco|valor|total) (ta |esta )?(errad|diferente)", r"cobr(ou|aram|ando) (a )?mais",
                r"nao e esse (valor|preco)", r"(ta|esta) mais caro", r"no (cardapio|app|site) (ta|esta|e|custa)",
                r"faltou (o|a|um|uma)\b", r"veio errad", r"tirou (o|a)\b.*\?$"]
C_ENDERECO = [r"(taxa|entrega) (ta |esta )?(cara|errad|absurd|alta)", r"endereco (ta |esta )?(errad|diferente)",
              r"nao (e|moro) (esse|nesse|neste) endereco", r"nao e (ai|la|esse bairro)", r"mudei de endereco",
              r"outro endereco", r"(sempre|semana passada) (paguei|pago) .*taxa", r"taxa de .* (pra|para) (o|a)"]
C_HUMANO = [r"\batendente\b", r"\bhumano\b", r"falar com (alguem|uma pessoa|o dono|gerente|voce)",
            r"\bpessoa de verdade\b", r"\brobo\b", r"\bpessim[oa]\b", r"\babsurdo\b", r"\bhorrivel\b",
            r"\bvergonha\b", r"\breclama", r"\bdescaso\b", r"nunca mais", r"\bdemor(ou|ando|a demais)\b",
            r"cade (o|meu) pedido", r"\bfrio\b.*pizza|pizza.*\bfria\b"]
C_DEMORA = [r"\balguem (ai|me responde)", r"^\?+$", r"\bresponde\b", r"\boi\?{2,}"]
TOPICOS = {
    "horário": [r"\bhorario\b", r"que horas (abre|fecha|abrem|fecham)", r"(ta|estao|esta|vcs estao) abert",
                r"\bfecha(m)? que horas", r"\bfuncionando\b", r"abre (hoje|amanha|que horas)"],
    "promoção": [r"\bpromo", r"\bcupom\b", r"\bdesconto\b", r"\bcombo do dia\b", r"\boferta\b"],
    "pagamento": [r"\bpix\b.*\?", r"\bcartao\b.*\?", r"aceita(m)? (cartao|pix|vale|ticket|vr|alelo|sodexo|dinheiro)",
                  r"\btroco\b", r"\bmaquin(ha|eta)\b", r"\bvale refeicao\b|\bvr\b|\bticket\b|\balelo\b|\bsodexo\b"],
    "tempo de entrega": [r"quanto tempo", r"\bdemora (quanto|muito)\b", r"tempo de entrega", r"previsao",
                         r"\bque horas (chega|vai chegar|fica pronto)", r"\bvai demorar\b", r"\bja saiu\b",
                         r"\bchega (que horas|em quanto)"],
}
# IA
I_NAO_ENTENDEU = [r"nao (entendi|consegui entender|compreendi)", r"pode(ria)? (repetir|explicar melhor|reformular)",
                  r"nao ficou claro", r"poderia me dizer de novo"]
I_NAO_SOUBE = [r"nao (sei|tenho essa informacao|tenho como (informar|saber|confirmar)|consigo (informar|confirmar|ver|saber))",
               r"vou (verificar|confirmar|consultar|checar) (com|e)", r"(um|uma) (atendente|pessoa da equipe|colaborador)",
               r"vou (te )?passar (para|pra)", r"(ligue|entre em contato|consulte)", r"nao tenho acesso"]
I_SEM_ITEM = [r"nao (encontrei|achei|temos|trabalhamos com|tem)\b.*(cardapio|esse|essa|item|sabor|opcao|disponivel)",
              r"nao (esta|ta) disponivel", r"(esgotad|em falta|acabou)", r"nao consta"]
I_FORA_AREA = [r"nao (entregamos|atendemos|fazemos entrega)", r"fora da (nossa )?(area|regiao)",
               r"nao consegui (calcular|localizar|achar) (a taxa|o endereco|seu endereco)"]


# ------------------------------------------------------------------ anonimização
RE_LINK = re.compile(r"alivhub\.com\.br/app/|https?://\S*(cardapio|pedido|menu)", re.I)
RE_FONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
RE_EMAIL = re.compile(r"\S+@\S+")
RE_CEP = re.compile(r"\b\d{5}-?\d{3}\b")
RE_ENDERECO = re.compile(
    r"(?i)\b(rua|r\.|av\.?|avenida|travessa|tv\.?|alameda|estrada|rodovia|br-?\d+|quadra|qd\.?|lote|lt\.?|"
    r"condom[ií]nio|cond\.?|residencial|loteamento|bairro|casa|apto?\.?|apartamento|bloco|n[ºo°]\.?|numero|número)"
    r"\b[^\n,.;!?]*")
RE_LINHA_ENTREGA = re.compile(r"(?im)^.*(📍|entrega:|endere[cç]o:|refer[eê]ncia:).*$")
RE_NEGRITO_NOME = re.compile(r"\*([A-ZÀ-Ú][a-zà-ú]+(?: [A-ZÀ-Ú][a-zà-ú]+)*)\*")
RE_SAUDACAO_NOME = re.compile(r"(?i)\b(oi|ol[aá]|obrigad[oa]|valeu|boa noite|boa tarde|bom dia),? ([A-ZÀ-Ú][a-zà-ú]{2,})\b")


def anonimiza(texto: str, nomes: set[str]) -> str:
    t = texto or ""
    t = RE_LINHA_ENTREGA.sub("[endereço]", t)
    t = RE_EMAIL.sub("[e-mail]", t)
    t = RE_CEP.sub("[cep]", t)
    t = RE_FONE.sub("[telefone]", t)
    t = RE_ENDERECO.sub("[endereço]", t)
    t = RE_NEGRITO_NOME.sub("*[nome]*", t)
    t = RE_SAUDACAO_NOME.sub(lambda m: f"{m.group(1)}, [nome]", t)
    for n in sorted(nomes, key=len, reverse=True):
        if len(n) >= 3:
            t = re.sub(rf"(?i)\b{re.escape(n)}\b", "[nome]", t)
    t = re.sub(r"\b\d{3,}\b", "[nº]", t)
    t = re.sub(r"(\[endereço\][\s,]*)+", "[endereço] ", t)
    return re.sub(r"\s+", " ", t).strip()


def corta(s: str, n: int = 140) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ------------------------------------------------------------------ coleta
def janela(dia: date) -> tuple[datetime, datetime]:
    ini = datetime(dia.year, dia.month, dia.day, INICIO_H, tzinfo=TZ)
    return ini, datetime(dia.year, dia.month, dia.day, FIM_H, tzinfo=TZ) + timedelta(days=1)


def quando(m: dict) -> datetime | None:
    try:
        return datetime.strptime(f"{m['date_label']} {m['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except (KeyError, TypeError, ValueError):
        return None


def pedidos(api: Aliv, dia: date) -> list[dict]:
    """Pedidos do WhatsApp/app/balcão do turno (iFood fica de fora: não passa pela IA)."""
    ini, fim = janela(dia)
    brutos: dict = {}
    for d in (dia, dia + timedelta(days=1)):
        page = 1
        while page < 200:
            lote = lista_pedidos(api.get("/admin/api/orders/audit",
                                         {"start_date": d.isoformat(), "end_date": d.isoformat(), "page": page}))
            if not lote:
                break
            for o in lote:
                if isinstance(o, dict) and o.get("id") is not None:
                    brutos.setdefault(o["id"], o)
            page += 1
    alvo = {}
    for oid, o in brutos.items():
        criado = parse_dt(o.get("created_at"), dia.year)
        if criado and ini - timedelta(hours=1) <= criado < fim + timedelta(hours=2):
            alvo[oid] = o

    def det(oid):
        r = api.get(f"/admin/api/orders/{oid}")
        return r.get("order", r) if isinstance(r, dict) else {}

    with ThreadPoolExecutor(max_workers=4) as ex:
        detalhes = dict(zip(alvo, ex.map(det, alvo)))
    out = []
    for oid, o in alvo.items():
        d = {**o, **(detalhes.get(oid) or {})}
        if str(d.get("platform_slug") or "").lower() == "ifood":
            continue
        d["_criado"] = parse_dt(d.get("created_at"), dia.year)
        d["_ia"] = NOTA_IA in norm(d.get("notes") or "")
        d["_fone"] = chave_fone(d.get("customer_phone") or d.get("phone"))
        out.append(d)
    return out


def fones_candidatos(api: Aliv, peds: list[dict], max_busca: int, dia: date) -> dict[str, str]:
    """phone do chat → nome salvo. Junta: 48 conversas mais recentes, quem precisa de
    atenção, telefones dos pedidos e a busca por prefixo (a lista do ALIV não pagina)."""
    out: dict[str, str] = {}
    for params in ({"include_transactional": "true"}, {"so_pedido_ia": "true"}):
        for c in api.get("/admin/api/chat/contacts", params) or []:
            if isinstance(c, dict) and digitos(c.get("phone")) == str(c.get("phone")):
                out.setdefault(c["phone"], c.get("name") or "")
    for c in api.get("/admin/api/chat/pending-attention") or []:
        if isinstance(c, dict) and c.get("phone"):
            out.setdefault(str(c["phone"]), c.get("name") or "")
    # busca por prefixo, em largura e em paralelo; fica só quem falou de D em diante
    recentes = {dia.strftime("%d/%m"), (dia + timedelta(days=1)).strftime("%d/%m")}
    hoje = datetime.now(TZ).date()
    d = dia + timedelta(days=2)
    while d <= hoje:
        recentes.add(d.strftime("%d/%m"))
        d += timedelta(days=1)
    nivel, chamadas = list(BUSCA_PREFIXOS), 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        while nivel and chamadas < max_busca:
            nivel = nivel[: max_busca - chamadas]
            chamadas += len(nivel)
            prox = []
            for pref, r in zip(nivel, ex.map(lambda q: api.get("/admin/api/chat/search", {"q": q}) or [], nivel)):
                for c in r:
                    t = str(c.get("time") or "") if isinstance(c, dict) else ""
                    if str(c.get("phone", "")).isdigit() and (t in recentes or re.fullmatch(r"\d{1,2}:\d{2}", t)):
                        out.setdefault(c["phone"], c.get("name") or "")
                if len(r) >= 9 and len(pref) < 10:
                    prox += [pref + x for x in "0123456789"]
            nivel = prox
    fones_candidatos.chamadas = chamadas
    # telefones dos pedidos que ainda não apareceram (formato do chat: 55 + DDD + 8 dígitos)
    conhecidos = {chave_fone(p) for p in out}
    for p in peds:
        d = digitos(p.get("customer_phone") or p.get("phone"))
        if not p["_fone"] or p["_fone"] in conhecidos:
            continue
        if len(d) in (10, 11):
            d = "55" + d
        if len(d) == 13 and d[4] == "9":
            d = d[:4] + d[5:]
        out.setdefault(d, p.get("customer_name") or "")
        conhecidos.add(p["_fone"])
    return out


def internos(cfg: dict) -> set[str]:
    nums = [cfg.get("numeros_internos") or "", os.environ.get("DESPESAS_REMETENTES", ""),
            os.environ.get("WHATSAPP_EMERSON", ""), os.environ.get("WHATSAPP_ADMIN", "")]
    return {chave_fone(x) for s in nums for x in re.split(r"[,;\s]+", s) if chave_fone(x)}


# ------------------------------------------------------------------ análise
def analisa(phone: str, nome: str, msgs: list[dict], dia: date, peds_fone: list[dict]) -> dict | None:
    ini, fim = janela(dia)
    m_all = [m for m in msgs if not m.get("is_campaign")]
    for m in m_all:
        m["_dt"] = quando(m)
    janela_msgs = [m for m in m_all if m["_dt"] and ini <= m["_dt"] < fim]
    if not any(m.get("direction") == "incoming" for m in janela_msgs):
        return None
    conv = [m for m in janela_msgs if not m.get("is_transactional")]
    nomes = {p for p in re.split(r"\s+", nome or "") if p}
    for p in peds_fone:
        nomes |= {x for x in re.split(r"\s+", str(p.get("customer_name") or "")) if x}
        for k in ("address_street", "address_neighborhood", "address_complement"):
            v = str(p.get(k) or "").strip()
            if len(v) >= 4:
                nomes.add(v)

    prob: Counter = Counter()
    trechos: dict[str, list[dict]] = {}
    topicos_sem_resposta: list[str] = []
    itens_faltando: list[str] = []
    perguntas_topico: dict[str, str] = {}
    tempos: list[float] = []

    def marca(chave: str, idx: int):
        prob[chave] += 1
        if chave not in trechos:
            a, b = max(0, idx - 2), min(len(conv), idx + 2)
            trechos[chave] = [{"de": "Cliente" if x.get("direction") == "incoming" else "IA",
                               "t": corta(anonimiza(x.get("body") or f"[{x.get('type')}]", nomes))}
                              for x in conv[a:b] if (x.get("body") or "").strip()]

    # tempo de resposta: 1ª mensagem do cliente de cada bloco → próxima resposta
    esperando: datetime | None = None
    perguntas_ia: list[str] = []
    for i, m in enumerate(conv):
        corpo = m.get("body") or ""
        if m.get("direction") == "incoming":
            if esperando is None:
                esperando = m["_dt"]
            if tem(corpo, C_NAO_ENTENDEU):
                marca("nao_entendeu", i)
            if tem(corpo, C_ITEM_PRECO):
                marca("item_preco", i)
            if tem(corpo, C_ENDERECO):
                marca("endereco_taxa", i)
            if tem(corpo, C_HUMANO):
                marca("reclamou_humano", i)
            for top, pads in TOPICOS.items():
                if tem(corpo, pads) and top not in perguntas_topico:
                    perguntas_topico[top] = corpo
                    resp = next((x for x in conv[i + 1:i + 4] if x.get("direction") == "outgoing"), None)
                    if resp is None or tem(resp.get("body") or "", I_NAO_SOUBE) or (
                            resp["_dt"] - m["_dt"]).total_seconds() > 600:
                        marca("nao_soube", i)
                        topicos_sem_resposta.append(top)
            continue
        # saída (IA ou equipe)
        if esperando is not None:
            dt = (m["_dt"] - esperando).total_seconds() / 60
            tempos.append(dt)
            if dt > DEMORA_MIN:
                marca("demora", i)
            esperando = None
        if tem(corpo, I_NAO_ENTENDEU):
            marca("nao_entendeu", i)
        if tem(corpo, I_SEM_ITEM):
            ant = next((x for x in reversed(conv[:i]) if x.get("direction") == "incoming"
                        and (x.get("body") or "").strip()), None)
            if ant:
                itens_faltando.append(corta(anonimiza(ant["body"], nomes), 80))
            marca("item_preco", i)
        if tem(corpo, I_FORA_AREA):
            marca("endereco_taxa", i)
        for frase in re.findall(r"[^.!?\n]*\?", corpo):
            f = norm(frase)
            if len(f) < 15 or "mais alguma coisa" in f or "posso mandar" in f:
                continue
            if any(difflib.SequenceMatcher(None, f, q).ratio() > 0.8 for q in perguntas_ia):
                marca("repetiu", i)
                break
            perguntas_ia.append(f)
    if esperando is not None and conv and conv[-1].get("direction") == "incoming":
        tempos_sem = True
    else:
        tempos_sem = False

    primeira = next(m["_dt"] for m in conv if m.get("direction") == "incoming") if conv else ini
    peds_turno = [p for p in peds_fone if p["_criado"] and primeira - timedelta(hours=1) <= p["_criado"] < fim + timedelta(hours=2)]
    ped_ia = [p for p in peds_turno if p["_ia"]]
    cancelados = [p for p in ped_ia if "CANCEL" in str(p.get("status")).upper()]
    if cancelados:
        prob["cancelado"] += len(cancelados)
        trechos.setdefault("cancelado", [{"de": "Sistema", "t": "Pedido montado pela IA e depois "
                                          + str(cancelados[0].get("status")).lower()}])
    validos = [p for p in peds_turno if "CANCEL" not in str(p.get("status")).upper()]
    if any(p["_ia"] for p in validos):
        desfecho = "pedido_ia"
    elif any(str(p.get("platform_slug") or "").lower() == "app" for p in validos):
        desfecho = "pedido_link"          # fez pelo link do cardápio (App, sem a nota da IA)
    elif validos:
        desfecho = "pedido_outro_canal"   # balcão/PDV
    elif cancelados:
        desfecho = "cancelado"
    else:
        desfecho = "abandonada"
    humano = any(m.get("direction") == "outgoing" and m.get("wa_account") for m in conv)
    link = any(m.get("direction") == "outgoing" and RE_LINK.search(m.get("body") or "") for m in conv)
    return {"desfecho": desfecho, "problemas": dict(prob), "trechos": trechos, "tempos": tempos,
            "sem_resposta_final": tempos_sem, "topicos_sem_resposta": topicos_sem_resposta,
            "itens_faltando": itens_faltando, "perguntas": {k: corta(anonimiza(v, nomes), 100)
                                                           for k, v in perguntas_topico.items()},
            "equipe_respondeu": humano, "msgs": len(conv), "recebeu_link": link,
            "pedidos_ia": len(ped_ia), "cancelados": len(cancelados)}


# ------------------------------------------------------------------ correções
def fatos(api: Aliv) -> dict:
    f = {"horario": "16:30 às 23:45", "dias": "todos os dias", "pagamentos": [], "taxa": None}
    try:
        sch = api.get(f"/admin/api/stores/{LOJA}/schedule-config").get("operating_schedule") or []
        hs = {(d.get("start"), d.get("end")) for d in sch}
        if len(hs) == 1:
            a, b = hs.pop()
            dias = {d.get("day") for d in sch}
            nomes = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
            fechado = [nomes[i] for i in range(7) if i not in dias]
            f["horario"] = f"{a} às {b}"
            f["dias"] = "todos os dias" if not fechado else "menos " + " e ".join(fechado)
    except (AlivError, AttributeError):
        pass
    try:
        pay = api.get(f"/admin/api/stores/{LOJA}/payments-config").get("payments") or []
        f["pagamentos"] = [p["name"] for p in pay if p.get("is_active") and p.get("show_in_delivery_app")
                           and "ifood" not in norm(p.get("name"))]
    except (AlivError, AttributeError):
        pass
    return f


def tempo_medio_entrega(peds: list[dict]) -> int | None:
    return None  # o detalhe do pedido não traz hora de entrega; a regra pede para o Emerson definir


def propostas(cont: Counter, topicos: Counter, perguntas: dict[str, str], itens: list[str],
              existentes: list[dict], fx: dict) -> tuple[list[dict], list[str]]:
    pag = ", ".join(fx["pagamentos"]) if fx["pagamentos"] else "Pix, cartão e dinheiro"
    modelos = {
        "horário": ("Vocês estão funcionando agora?",
                    f"Estamos sim! {LOJA_INFO['emoji']} Nosso horário é das {fx['horario']}, {fx.get('dias', 'todos os dias')}. Me fala o que vai querer que eu já anoto 🛵"),
        "promoção": ("Tem alguma promoção hoje?",
                     "Tem sim! 😍 [DIGITE AQUI A PROMOÇÃO DO DIA]. Quer que eu já monte o seu?"),
        "pagamento": ("Vocês aceitam cartão ou pix?",
                      f"Aceitamos {pag} 💳 Na entrega o motoboy leva a maquininha. Se for dinheiro, me avisa o troco 😉"),
        "tempo de entrega": ("Quanto tempo demora pra chegar?",
                             "Hoje está saindo em média em [XX] a [YY] minutos 🛵 Assim que sair pra entrega eu te aviso aqui!"),
        "reclamou_humano": ("Quero falar com um atendente",
                            "Claro! 🙏 Já chamei alguém da equipe pra falar com você aqui mesmo. Enquanto isso, me conta o que aconteceu que eu já adianto."),
        "endereco_taxa": ("A taxa pro meu bairro tá errada",
                          "Me manda o bairro e uma referência, por favor 🙏 Confiro a taxa certinha e ajusto antes de enviar o pedido."),
        "nao_entendeu": ("Não foi isso que eu pedi",
                         "Desculpa! 🙏 Me fala de novo o item, o tamanho e o sabor que eu corrijo agora no seu pedido."),
    }
    pares, regras = [], []
    ordem = [t for t, _ in topicos.most_common()] + [k for k, _ in cont.most_common()]
    vistos = set()
    for chave in ordem:
        if chave in vistos or chave not in modelos:
            continue
        vistos.add(chave)
        u, a = modelos[chave]
        exemplo_real = perguntas.get(chave)
        parecido = None
        for i, ex in enumerate(existentes, 1):
            r = max(difflib.SequenceMatcher(None, norm(u), norm(ex.get("user", ""))).ratio(),
                    difflib.SequenceMatcher(None, norm(exemplo_real or u), norm(ex.get("user", ""))).ratio())
            if r >= 0.6 or (chave == "horário" and tem(ex.get("user", ""), TOPICOS["horário"])) or (
                    chave in TOPICOS and tem(ex.get("user", ""), TOPICOS[chave])):
                parecido = i
                break
        pares.append({"tema": chave, "user": u, "assistant": a, "exemplo_cliente": exemplo_real,
                      "ja_existe_parecido": parecido, "falta_preencher": "[" in a})
        if len(pares) >= 5:
            break
    if topicos.get("tempo de entrega"):
        regras.append("Informar um tempo médio de entrega (ex.: 40–50 min) e avisar quando o pedido sair.")
    if topicos.get("promoção"):
        regras.append("Cadastrar a promoção do dia no ALIV antes das 16:30 para a IA saber responder.")
    if topicos.get("pagamento"):
        regras.append(f"Formas de pagamento aceitas na entrega: {pag}.")
    if cont.get("reclamou_humano"):
        regras.append("Quando o cliente pedir atendente ou reclamar, chamar a equipe na hora e não insistir no pedido.")
    if cont.get("endereco_taxa"):
        regras.append("Confirmar bairro e referência antes de fechar a taxa; nunca assumir o endereço salvo sem perguntar.")
    if cont.get("repetiu"):
        regras.append("Não repetir pergunta já respondida (endereço, pagamento, tamanho): conferir o histórico da conversa.")
    return pares, regras


# ------------------------------------------------------------------ relatório
def resumo_num(convs: list[dict]) -> dict:
    n = len(convs)
    ped = sum(1 for c in convs if c["desfecho"] in ("pedido_ia", "pedido_link", "pedido_outro_canal"))
    ped_ia = sum(1 for c in convs if c["desfecho"] == "pedido_ia")
    aband = sum(1 for c in convs if c["desfecho"] == "abandonada")
    tempos = [t for c in convs for t in c["tempos"]]
    prob = Counter()
    for c in convs:
        for k, v in c["problemas"].items():
            prob[k] += 1          # conversas com o problema (não ocorrências)
    return {"conversas": n, "pedidos": ped, "pedidos_ia": ped_ia, "abandonadas": aband,
            "conversao": round(ped / n, 3) if n else 0.0, "abandono": round(aband / n, 3) if n else 0.0,
            "tempo_medio_min": round(statistics.mean(tempos), 1) if tempos else None,
            "tempo_mediana_min": round(statistics.median(tempos), 1) if tempos else None,
            "sem_resposta": sum(1 for c in convs if c["sem_resposta_final"]),
            "cancelados_ia": sum(c["cancelados"] for c in convs),
            "pedidos_link": sum(1 for c in convs if c["desfecho"] == "pedido_link"),
            "pedidos_outro": sum(1 for c in convs if c["desfecho"] == "pedido_outro_canal"),
            "receberam_link": sum(1 for c in convs if c.get("recebeu_link")),
            "abandono_com_link": sum(1 for c in convs if c["desfecho"] == "abandonada" and c.get("recebeu_link")),
            "abandono_sem_link": sum(1 for c in convs if c["desfecho"] == "abandonada" and not c.get("recebeu_link")),
            "problemas": dict(prob)}


def pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def carregar_historico(dia: date) -> list[dict]:
    out = []
    for i in range(1, 8):
        d = dia - timedelta(days=i)
        f = PASTA / f"{d.isoformat()}{SUFIXO}.json"
        if f.exists():
            try:
                out.append(json.loads(f.read_text())["resumo"] | {"dia": d.isoformat()})
            except (ValueError, KeyError):
                pass
    return out


def tendencia(hoje: dict, hist: list[dict]) -> list[str]:
    if not hist:
        return ["Sem histórico ainda (os arquivos dos dias anteriores são gravados a cada rodada)."]
    def media(k):
        v = [h[k] for h in hist if h.get(k) is not None]
        return statistics.mean(v) if v else None
    L = [f"Base: {len(hist)} dia(s) anteriores ({hist[-1]['dia'][8:]}/{hist[-1]['dia'][5:7]} a "
         f"{hist[0]['dia'][8:]}/{hist[0]['dia'][5:7]})."]
    L.append("| Indicador | Ontem | Média 7 dias | |")
    L.append("|---|---|---|---|")
    for k, nome, fmt, melhor_maior in (("conversas", "Conversas", str, None),
                                       ("conversao", "Conversão", pct, True),
                                       ("abandono", "Abandono", pct, False),
                                       ("tempo_medio_min", "Tempo médio de resposta (min)", str, False)):
        m = media(k)
        h = hoje.get(k)
        seta = ""
        if m is not None and h is not None and melhor_maior is not None:
            seta = "✅ melhor" if (h > m) == melhor_maior and h != m else ("⚠️ pior" if h != m else "=")
        L.append(f"| {nome} | {fmt(h) if h is not None else '—'} | "
                 f"{(fmt(round(m, 3)) if k != 'conversas' else f'{m:.0f}') if m is not None else '—'} | {seta} |")
    tot_h = sum(hoje["problemas"].values()) / max(hoje["conversas"], 1)
    tot_m = statistics.mean(sum(h["problemas"].values()) / max(h["conversas"], 1) for h in hist)
    L.append(f"| Problemas por conversa | {tot_h:.2f} | {tot_m:.2f} | "
             f"{'✅ melhor' if tot_h < tot_m else ('⚠️ pior' if tot_h > tot_m else '=')} |")
    return L


def gerar(dia: date, convs: list[dict], pares, regras, itens, hist, existentes, n_fones) -> tuple[str, dict]:
    r = resumo_num(convs)
    ini, fim = janela(dia)
    top5 = Counter(r["problemas"]).most_common(5)
    L = [f"# Atendimento da IA — {LOJA_INFO['nome']} — turno {dia:%d/%m/%Y}",
         "", f"Janela: {ini:%d/%m %H:%M} até {fim:%d/%m %H:%M} (horário da Bahia). Só WhatsApp da loja {LOJA}; iFood fica de fora.",
         "", "## 1) Resumo do dia", "",
         f"- Conversas com cliente: **{r['conversas']}**",
         f"- Pedidos fechados: **{r['pedidos']}** — {r['pedidos_ia']} montados pela IA · "
         f"{r['pedidos_link']} pelo link do cardápio que a IA mandou · {r['pedidos_outro']} no balcão/PDV",
         f"- Taxa de conversão: **{pct(r['conversao'])}**",
         f"- Abandono (sem pedido em nenhum canal): **{r['abandonadas']}** ({pct(r['abandono'])}) — "
         f"{r['abandono_com_link']} receberam o link e não pediram · {r['abandono_sem_link']} sem link",
         f"- Conversas em que a IA mandou o link do cardápio: {r['receberam_link']}",
         f"- Tempo médio de resposta: **{r['tempo_medio_min'] if r['tempo_medio_min'] is not None else '—'} min** "
         f"(mediana {r['tempo_mediana_min'] if r['tempo_mediana_min'] is not None else '—'} min)",
         f"- Conversas que terminaram sem resposta: {r['sem_resposta']}",
         f"- Pedidos da IA cancelados depois de montados: {r['cancelados_ia']}",
         "", "**5 problemas mais frequentes** (nº de conversas):", ""]
    L += [f"{i}. {PROBLEMAS[k]} — {v}" for i, (k, v) in enumerate(top5, 1)] or ["Nenhum problema encontrado."]
    L += ["", "## 2) Exemplos (anonimizados)", ""]
    exemplos = []
    for k, _ in Counter(r["problemas"]).most_common():
        for c in convs:
            if k in c["trechos"] and len([e for e in exemplos if e[0] == k]) < 2:
                exemplos.append((k, c["trechos"][k]))
        if len(exemplos) >= 10:
            break
    for i, (k, tr) in enumerate(exemplos[:10], 1):
        L.append(f"**{i}. {PROBLEMAS[k]}**")
        L += [f"> {x['de']}: {x['t']}" for x in tr[:4]]
        L.append("")
    if not exemplos:
        L.append("Nenhum.")
    L += ["## 3) Correções sugeridas", "",
          "### Pares para \"Ensine o jeito da sua loja\" (Configurações da loja → IA)", "",
          f"O campo aceita até {MAX_EXEMPLOS} exemplos e hoje tem {len(existentes)}. "
          "Para entrar um par novo é preciso escolher qual sai (comando `aprovar --no-lugar-de N`).", ""]
    for i, p in enumerate(pares, 1):
        aviso = f" — ⚠️ já existe parecido (exemplo {p['ja_existe_parecido']}), não proposto" if p["ja_existe_parecido"] else ""
        falta = " — ✏️ completar o trecho entre colchetes antes de aprovar" if p["falta_preencher"] else ""
        L.append(f"**Par {i}** ({p['tema']}){aviso}{falta}")
        L.append(f"- Cliente pergunta: {p['user']}")
        L.append(f"- Resposta ideal: {p['assistant']}")
        if p.get("exemplo_cliente"):
            L.append(f"- Pergunta real de ontem: \"{p['exemplo_cliente']}\"")
        L.append("")
    if not pares:
        L.append("Nenhum par novo necessário.")
    L += ["", "**Exemplos que já estão no campo:**", ""]
    L += [f"{i}. {corta(e.get('user', ''), 60)}" for i, e in enumerate(existentes, 1)]
    L += ["", "### Itens ou preços que a IA não encontrou no cardápio", ""]
    cont_itens = Counter(itens).most_common(10)
    L += [f"- \"{t}\" ({n}x)" for t, n in cont_itens] or ["- Nenhum."]
    L += ["", "### Regras que ela precisa saber", ""]
    L += [f"- {x}" for x in regras] or ["- Nenhuma nova."]
    L += ["", "## 4) Comparação com os últimos 7 dias", ""] + tendencia(r, hist)
    L += ["", "---", f"Telefones verificados: {n_fones}. Classificação automática por palavras-chave; "
          "confira os exemplos antes de aprovar qualquer par."]
    dados = {"dia": dia.isoformat(), "loja": LOJA_INFO["curto"], "resumo": r, "pares": pares, "regras": regras,
             "itens_faltando": [t for t, _ in cont_itens]}
    return "\n".join(L) + "\n", dados


def resumo_whatsapp(dia: date, dados: dict, hist: list[dict]) -> str:
    r = dados["resumo"]
    L = [f"*Atendimento IA {LOJA_INFO['curto']} — turno {dia:%d/%m}*",
         f"{r['conversas']} conversas · {r['pedidos']} pedidos ({pct(r['conversao'])}) · "
         f"abandono {pct(r['abandono'])} · resposta média {r['tempo_medio_min'] if r['tempo_medio_min'] is not None else '—'} min"]
    L.append(f"Pedidos: {r['pedidos_ia']} pela IA · {r['pedidos_link']} pelo link · {r.get('pedidos_outro', 0)} balcão. "
             f"Abandono real: {r['abandono_com_link']} com link · {r['abandono_sem_link']} sem link")
    if hist:
        m = statistics.mean(h["conversao"] for h in hist)
        L.append(f"Conversão 7 dias: {pct(m)} → ontem {pct(r['conversao'])} "
                 f"{'✅' if r['conversao'] >= m else '⚠️'}")
    top = Counter(r["problemas"]).most_common(3)
    if top:
        L.append("Problemas: " + " · ".join(f"{PROBLEMAS[k]} {v}" for k, v in top))
    novos = [p for p in dados["pares"] if not p["ja_existe_parecido"]]
    if novos:
        L.append("")
        L.append("*Pares propostos* (só entram com seu ok):")
        for i, p in enumerate(dados["pares"], 1):
            if p["ja_existe_parecido"]:
                continue
            L.append(f"{i}) P: {p['user']}\nR: {corta(p['assistant'], 160)}")
    L.append("")
    L.append(f"Relatório completo: monitor/atendimento/{dia.isoformat()}{SUFIXO}.md")
    return "\n".join(L)


# ------------------------------------------------------------------ rodada
def auditar(a) -> int:
    """Roda as lojas pedidas. O WhatsApp sai sempre pelo número da Pizzaria (como o monitor.py)."""
    agora = datetime.now(TZ)
    dia = date.fromisoformat(a.data) if a.data else agora.date() - timedelta(days=1)   # turno que fechou
    lojas = list(LOJAS) if a.loja == "todas" else [a.loja]
    remetente = None
    if a.whatsapp and os.environ.get("ALIV_USER") and os.environ.get("ALIV_PASS"):
        remetente = AlivLeitura(os.environ["ALIV_USER"], os.environ["ALIV_PASS"])
    codigos = []
    for chave in lojas:
        info = usar_loja(chave)
        if not os.environ.get(info["user"]) or not os.environ.get(info["senha"]):
            print(f"{info['curto']}: faltam {info['user']}/{info['senha']}", file=sys.stderr)
            codigos.append(2)
            continue
        print(f"\n######## {info['nome']} ########\n")
        codigos.append(auditar_loja(a, dia, remetente))
    return max(codigos) if codigos else 2


def auditar_loja(a, dia: date, remetente) -> int:
    api = AlivLeitura(os.environ[LOJA_INFO["user"]], os.environ[LOJA_INFO["senha"]])
    try:
        cfg = api.get(f"/admin/api/stores/{LOJA}/ai-config")
        cfg = cfg.get("config", cfg)
        existentes = cfg.get("few_shot_examples") or []
        excluir = internos(cfg)
        peds = pedidos(api, dia)
        fones = fones_candidatos(api, peds, a.busca, dia)
        fones = {p: n for p, n in fones.items() if chave_fone(p) not in excluir}
        with ThreadPoolExecutor(max_workers=4) as ex:
            msgs = dict(zip(fones, ex.map(lambda p: api.get(
                f"/admin/api/chat/messages/{urllib.parse.quote(p)}", {"limit": LIMITE_MSGS}) or [], fones)))
        fx = fatos(api)
    except (AlivError, OSError) as e:
        print(f"Atendimento IA {LOJA_INFO['curto']} — erro no ALIV: {e}")
        return 1

    por_fone: dict[str, list[dict]] = {}
    for p in peds:
        por_fone.setdefault(p["_fone"], []).append(p)
    convs, achados = [], set()
    for phone, nome in fones.items():
        c = analisa(phone, nome, msgs.get(phone) or [], dia, por_fone.get(chave_fone(phone), []))
        if c:
            convs.append(c)
            achados.add(chave_fone(phone))
    # pedidos da IA cujo telefone não achamos no chat continuam contando como conversa convertida
    ped_ia_turno = [p for p in peds if p["_ia"] and p["_criado"] and janela(dia)[0] <= p["_criado"] < janela(dia)[1]]
    sem_chat = [p for p in ped_ia_turno if p["_fone"] not in achados]
    for p in sem_chat:
        cancel = "CANCEL" in str(p.get("status")).upper()
        convs.append({"desfecho": "cancelado" if cancel else "pedido_ia", "problemas": {"cancelado": 1} if cancel else {},
                      "trechos": {}, "tempos": [], "sem_resposta_final": False, "topicos_sem_resposta": [],
                      "itens_faltando": [], "perguntas": {}, "equipe_respondeu": False, "msgs": 0,
                      "pedidos_ia": 1, "cancelados": int(cancel)})

    cont = Counter()
    topicos = Counter()
    perguntas: dict[str, str] = {}
    itens = []
    for c in convs:
        for k in c["problemas"]:
            cont[k] += 1
        for t in c["topicos_sem_resposta"]:
            topicos[t] += 1
        for t, q in c["perguntas"].items():
            perguntas.setdefault(t, q)
        itens += c["itens_faltando"]
    pares, regras = propostas(cont, topicos, perguntas, itens, existentes, fx)
    hist = carregar_historico(dia)
    md, dados = gerar(dia, convs, pares, regras, itens, hist, existentes, len(fones))
    dados["pedidos_ia_sem_chat"] = len(sem_chat)

    if not a.sem_gravar:
        PASTA.mkdir(parents=True, exist_ok=True)
        (PASTA / f"{dia.isoformat()}{SUFIXO}.md").write_text(md, encoding="utf-8")
        (PASTA / f"{dia.isoformat()}{SUFIXO}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    texto = resumo_whatsapp(dia, dados, hist)
    print(texto)
    print("\n" + "=" * 60 + "\n")
    print(md)
    paineis: dict = {}
    if not a.sem_painel and (a.painel or a.whatsapp):
        import tempfile
        from painel_atendimento import gerar_paineis
        base = a.painel or Path(tempfile.mkdtemp()) / "atendimento.png"
        base = base.with_name(f"{base.stem}{SUFIXO}{base.suffix}")
        paineis = gerar_paineis(base, dia, dados, hist)
        for rot, arq in paineis.items():
            print(f"Painel {rot}: {arq}", file=sys.stderr)
    if a.whatsapp:
        api = remetente or api
        fone = digitos(os.environ.get("WHATSAPP_EMERSON", ""))
        if not fone:
            print("WhatsApp não enviado: falta WHATSAPP_EMERSON")
            return 3
        falhou = False
        for rot, arq in paineis.items():
            if isinstance(arq, Exception):
                print(f"Painel {rot} não gerado: {arq}", file=sys.stderr)
                continue
            try:
                api.enviar_whatsapp(fone, f"Atendimento IA {LOJA_INFO['curto']} ({ROTULOS.get(rot, rot)}) — turno {dia:%d/%m}", arquivo=arq)
                print(f"WhatsApp: painel {rot} enviado.")
            except AlivError as e:
                print(f"WhatsApp: painel {rot} não enviado — {e}")
                falhou = True
        try:
            api.enviar_whatsapp(fone, texto)
            print("WhatsApp: resumo com os pares enviado.")
        except AlivError as e:
            print(f"WhatsApp não enviado: {e}")
            return 3
        if falhou:
            return 3
    return 0


# ------------------------------------------------------------------ aprovar
def form_config(cfg: dict, exemplos: list[dict]) -> list[tuple[str, str]]:
    """Mesmos campos, na mesma forma, que a tela 'Configurações da loja → IA' manda ao salvar."""
    b = lambda v: "true" if v else "false"  # noqa: E731
    sizes = [s["id"] for s in cfg.get("ai_default_sizes") or [] if s.get("ai_default")]
    flavors = [it["id"] for g in cfg.get("ai_flavor_groups") or [] for it in g.get("items") or []
               if it.get("ai_default_flavor")]
    return [
        ("store_id", str(LOJA)), ("api_key", (cfg.get("api_key") or "").strip()),
        ("is_active", b(cfg.get("active"))), ("ai_profile", cfg.get("profile") or "objective"),
        ("few_shot_examples", json.dumps([e for e in exemplos if e.get("user") and e.get("assistant")],
                                         ensure_ascii=False)),
        ("ai_accept_delivery", b(cfg.get("accept_delivery"))), ("ai_accept_pickup", b(cfg.get("accept_pickup"))),
        ("auto_order", b(cfg.get("auto_order"))),
        ("skip_payment_question", b(cfg.get("skip_payment_question") is not False)),
        ("upsell_bebidas", b(cfg.get("upsell_bebidas") is not False)),
        ("upsell_borda", b(cfg.get("upsell_borda") is True)),
        ("cascata_custo", b(cfg.get("cascata_custo") is not False)),
        ("perguntar_entrega_retirada", b(cfg.get("perguntar_entrega_retirada") is True)),
        ("pedir_referencia", b(cfg.get("pedir_referencia") is True)),
        ("nome_atendente", (cfg.get("nome_atendente") or "").strip()),
        ("ia_horarios", json.dumps(cfg.get("ia_horarios") or {"ativo": False, "dias": {}}, ensure_ascii=False)),
        ("mostrar_contador_pedidos", b(cfg.get("mostrar_contador_pedidos") is True)),
        ("ia_sem_validacao", b(cfg.get("ia_sem_validacao") is True)),
        ("ia_acrescenta_em_preparo", b(cfg.get("ia_acrescenta_em_preparo") is True)),
        ("numeros_internos", cfg.get("numeros_internos") or ""),
        ("ai_default_sizes_json", json.dumps(sizes)), ("ai_default_flavors_json", json.dumps(flavors)),
    ]


def aprovar(a) -> int:
    usar_loja(a.loja)
    f = PASTA / f"{a.data}{SUFIXO}.json"
    if not f.exists():
        print(f"Não achei {f}. Rode a auditoria desse dia primeiro.")
        return 2
    pares = json.loads(f.read_text())["pares"]
    if not 1 <= a.par <= len(pares):
        print(f"Par {a.par} não existe (há {len(pares)}).")
        return 2
    par = pares[a.par - 1]
    if a.pergunta:
        par["user"] = a.pergunta
    if a.resposta:
        par["assistant"] = a.resposta
    if "[" in par["assistant"]:
        print("A resposta ainda tem trecho entre colchetes para completar. Use --resposta \"texto final\".")
        return 2
    api = AlivLeitura(os.environ[LOJA_INFO["user"]], os.environ[LOJA_INFO["senha"]])
    cfg = api.get(f"/admin/api/stores/{LOJA}/ai-config")
    cfg = cfg.get("config", cfg)
    atuais = list(cfg.get("few_shot_examples") or [])
    for i, ex in enumerate(atuais, 1):
        if difflib.SequenceMatcher(None, norm(par["user"]), norm(ex.get("user", ""))).ratio() >= 0.75:
            print(f"Já existe um exemplo parecido (nº {i}): \"{ex.get('user')}\". Nada foi alterado.")
            return 4
    novos = list(atuais)
    if a.no_lugar_de:
        if not 1 <= a.no_lugar_de <= len(atuais):
            print(f"--no-lugar-de deve ser de 1 a {len(atuais)}.")
            return 2
        sai = novos[a.no_lugar_de - 1]
        novos[a.no_lugar_de - 1] = {"user": par["user"], "assistant": par["assistant"]}
    else:
        if len(atuais) >= MAX_EXEMPLOS:
            print(f"O campo já tem {MAX_EXEMPLOS} exemplos (limite do ALIV). Escolha qual sai com --no-lugar-de N:")
            for i, ex in enumerate(atuais, 1):
                print(f"  {i}. {ex.get('user')}")
            return 2
        sai = None
        novos.append({"user": par["user"], "assistant": par["assistant"]})
    print("ENTRA:\n  P: " + par["user"] + "\n  R: " + par["assistant"])
    if sai:
        print("SAI:\n  P: " + sai.get("user", "") + "\n  R: " + sai.get("assistant", ""))
    if not a.confirmo:
        print("\nNada foi gravado. Para gravar, rode de novo com --confirmo (só com o ok do Emerson).")
        return 0
    campos = form_config(cfg, novos)
    import uuid
    import urllib.request
    from monitor import BASE_URL
    bnd = uuid.uuid4().hex
    body = "".join(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in campos)
    req = urllib.request.Request(BASE_URL + "/admin/api/openai/sync", data=(body + f"--{bnd}--\r\n").encode(),
                                 method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    status, resp = api._send(req)
    if status != 200:
        print(f"ALIV recusou (HTTP {status}): {str(resp)[:200]}")
        return 1
    depois = api.get(f"/admin/api/stores/{LOJA}/ai-config")
    depois = depois.get("config", depois)
    ok = depois.get("few_shot_examples") == novos
    mudou = [k for k in ("active", "profile", "auto_order", "nome_atendente", "accept_delivery", "accept_pickup",
                         "upsell_bebidas", "upsell_borda", "ia_horarios", "numeros_internos")
             if depois.get(k) != cfg.get(k)]
    print("Gravado e conferido." if ok else "⚠️ ALIV respondeu OK, mas os exemplos não batem. Confira na tela.")
    if mudou:
        print(f"⚠️ Outros campos mudaram depois de salvar: {', '.join(mudou)}. Confira na tela.")
    return 0 if ok and not mudou else 1


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "aprovar":
        ap = argparse.ArgumentParser(prog="atendimento_ia.py aprovar")
        ap.add_argument("--data", required=True, help="dia do relatório (AAAA-MM-DD)")
        ap.add_argument("--loja", choices=list(LOJAS), default="pizzaria")
        ap.add_argument("--par", type=int, required=True, help="número do par no relatório")
        ap.add_argument("--no-lugar-de", type=int, help="exemplo atual que sai (1 a 5)")
        ap.add_argument("--pergunta", help="troca o texto da pergunta antes de gravar")
        ap.add_argument("--resposta", help="troca o texto da resposta antes de gravar")
        ap.add_argument("--confirmo", action="store_true", help="grava de verdade (só com o ok do Emerson)")
        return aprovar(ap.parse_args(sys.argv[2:]))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", help="turno a auditar (AAAA-MM-DD). Padrão: ontem (o turno que fechou à 01:00)")
    ap.add_argument("--whatsapp", action="store_true", help="manda painel e resumo para WHATSAPP_EMERSON")
    ap.add_argument("--loja", choices=["todas", *LOJAS], default="todas", help="padrão: Pizzaria e Sushi")
    ap.add_argument("--sem-gravar", action="store_true", help="não grava os arquivos")
    ap.add_argument("--painel", type=Path, help="salva os painéis em ARQ_ipad.png, ARQ_iphone_1.png e ARQ_iphone_2.png")
    ap.add_argument("--sem-painel", action="store_true", help="não gera nem envia o painel")
    ap.add_argument("--busca", type=int, default=BUSCA_MAX_CHAMADAS, help="máx. de buscas por prefixo de telefone")
    return auditar(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
