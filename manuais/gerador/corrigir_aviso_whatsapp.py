"""Mensagem de correção no WhatsApp para quem recebeu hoje o aviso antigo ("sem delivery nem retirada") e não recebeu depois a
informação certa. Pedido do Emerson em 27/11/2026: "pode mandar mensagem para os clientes" dizendo que o temaki pode ser retirado.

Regras de quem recebe:
  - a loja/IA mandou hoje, entre 15:00 e 19:04, uma mensagem dizendo que não havia retirada;
  - depois disso a conversa NÃO recebeu nenhuma mensagem da loja falando que dá para retirar/buscar;
  - não é número interno da loja; e a correção ainda não foi enviada para essa conversa.
Envia pelo chat do ALIV (mesmo caminho do atendente). Se o envio pausar a IA daquela conversa, religa, para ela anotar o pedido.
Não imprime nem grava telefone ou nome de cliente (só os 2 últimos dígitos, para conferência).

  python3 corrigir_aviso_whatsapp.py            lista quem receberia e mostra o texto (dry-run, nada enviado)
  python3 corrigir_aviso_whatsapp.py --enviar   envia e confere
"""
import sys, os, re, json, uuid, time, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
ENVIAR = "--enviar" in sys.argv[1:]; TZ = ZoneInfo("America/Bahia"); HOJE = datetime.now(TZ).date()
INI, FIM = datetime(HOJE.year, HOJE.month, HOJE.day, 15, 0, tzinfo=TZ), datetime(HOJE.year, HOJE.month, HOJE.day, 19, 4, tzinfo=TZ)
ERRADO = re.compile(r"nem retirada|n[aã]o d[aá] (?:pra|para) levar|sem delivery (?:e|nem) (?:sem )?retirada", re.I)
CERTO = re.compile(r"buscar no balc|retirad[ao] no balc|retirar no balc|pode retirar|para retirada|pra retirada|pode ser retirado", re.I)
TEXTO = ("Oi! Aqui é a Tili Sushi 😊 Corrigindo a informação que te passamos mais cedo: hoje não temos delivery, mas o TEMAKI pode ser retirado no balcão. "
         "🖤 Black Friday: Temaki Hot por R$ 19,90 e demais temakis por R$ 24,90, enquanto durar o estoque. "
         "Se quiser, é só me dizer qual temaki e a quantidade que eu já anoto seu pedido para retirada. As peças do buffet são só no salão.")
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login(); api.timeout = max(getattr(api, "timeout", 0) or 0, 120)
so_num = lambda s: re.sub(r"\D", "", str(s or ""))
internos = {so_num(x) for x in str(api.get("/admin/api/stores/155/ai-config").get("numeros_internos") or "").split(",") if so_num(x)}
def quando(m):
    s = str(m.get("sent_at") or "")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00")); return d.astimezone(TZ) if d.tzinfo else d.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    except Exception: return None
def saida(m): return str(m.get("direction") or "").lower() in ("out", "outgoing", "sent", "outbound")
def mensagens(fone):
    r = api.get("/admin/api/chat/messages/" + urllib.parse.quote(str(fone), safe=""), {"limit": 120}); return r if isinstance(r, list) else (r.get("messages") or r.get("data") or [])
conv = api.get("/admin/api/chat/contacts"); ts = [datetime.fromisoformat(c["raw_ts"]).astimezone(TZ) for c in conv if c.get("raw_ts")]
print(f"conversas na lista: {len(conv)} | da mais antiga ({min(ts):%d/%m %H:%M}) à mais nova ({max(ts):%d/%m %H:%M})" if ts else "sem conversas")
if ts and min(ts) > INI: print("ATENÇÃO: a lista de conversas não chega até as 15:00 de hoje; pode haver conversa mais antiga fora dela")
alvos = []; resumo = {"interno": 0, "sem aviso antigo": 0, "já recebeu a informação certa": 0}
exemplo_dir = None
for c in conv:
    if not c.get("raw_ts") or datetime.fromisoformat(c["raw_ts"]).astimezone(TZ) < INI: continue
    fone = c["phone"]
    if so_num(fone) in internos or any(so_num(fone).endswith(i[-8:]) for i in internos): resumo["interno"] += 1; continue
    ms = mensagens(fone)
    if exemplo_dir is None and ms: exemplo_dir = sorted({str(m.get("direction")) for m in ms})
    errados = [m for m in ms if saida(m) and (quando(m) and INI <= quando(m) <= FIM) and ERRADO.search(str(m.get("body") or ""))]
    if not errados: resumo["sem aviso antigo"] += 1; continue
    ult = max(quando(m) for m in errados)
    corrigido = [m for m in ms if saida(m) and quando(m) and quando(m) > ult and (CERTO.search(str(m.get("body") or "")) or "Corrigindo a informação" in str(m.get("body") or ""))]
    if corrigido: resumo["já recebeu a informação certa"] += 1; continue
    cliente_depois = sum(1 for m in ms if not saida(m) and quando(m) and quando(m) > ult)
    alvos.append({"fone": fone, "fim": so_num(fone)[-2:], "aviso_antigo": ult, "cliente_escreveu_depois": cliente_depois, "conta": c.get("wa_account")})
print("direções vistas nas mensagens:", exemplo_dir, "| fora da lista:", resumo)
print(f"receberiam a correção: {len(alvos)}")
for a in sorted(alvos, key=lambda a: a["aviso_antigo"]): print(f"   …{a['fim']} | aviso antigo às {a['aviso_antigo']:%H:%M} | cliente escreveu depois: {a['cliente_escreveu_depois']} | {a['conta']}")
print("\nTEXTO:", TEXTO, f"\n({len(TEXTO)} caracteres)")
if not ENVIAR: print("\nmodo: dry-run (nada enviado)"); sys.exit()
ok = falha = religou = 0
for a in sorted(alvos, key=lambda a: a["aviso_antigo"]):
    f = urllib.parse.quote(str(a["fone"]), safe="")
    try: pausada_antes = bool(api.get(f"/admin/api/chat/ai-status/{f}").get("ai_paused"))
    except Exception: pausada_antes = None
    bd = uuid.uuid4().hex
    corpo = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in (("phone", a["fone"]), ("message", TEXTO))) + f"--{bd}--\r\n"
    st, r = api._send(urllib.request.Request(BASE_URL + "/admin/api/chat/send", data=corpo.encode(), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))
    bom = st == 200 and isinstance(r, dict) and r.get("success") is True
    try: pausada_depois = bool(api.get(f"/admin/api/chat/ai-status/{f}").get("ai_paused"))
    except Exception: pausada_depois = None
    if bom and pausada_antes is False and pausada_depois is True:        # o envio manual pausou a IA: religa
        bd = uuid.uuid4().hex; corpo = f'--{bd}\r\nContent-Disposition: form-data; name="phone"\r\n\r\n{a["fone"]}\r\n--{bd}--\r\n'
        api._send(urllib.request.Request(BASE_URL + "/admin/api/chat/toggle-ai", data=corpo.encode(), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))
        pausada_depois = bool(api.get(f"/admin/api/chat/ai-status/{f}").get("ai_paused")); religou += 1
    ok += bom; falha += not bom
    print(f"   …{a['fim']} | enviado: {bom} {'' if bom else str(r)[:120]} | IA pausada antes/depois: {pausada_antes}/{pausada_depois}")
    time.sleep(1.5)
print(f"\nenviadas: {ok} | falharam: {falha} | IA religada em: {religou} conversa(s)")
