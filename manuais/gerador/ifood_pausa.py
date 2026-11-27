"""Pausa da loja no iFood pelo ALIV (Painel iFood > Loja, pausas e horários). Pedido do Emerson em 27/11/2026:
"não quero delivery do iFood hoje" (Black Friday só no salão).

  python3 ifood_pausa.py ver                                   mostra o estado da loja no iFood e as pausas (somente leitura)
  python3 ifood_pausa.py pausar <fim AAAA-MM-DDTHH:MM> "<motivo>" [--gravar]   pausa de agora até o fim (hora da Bahia)
  python3 ifood_pausa.py remover <id da pausa> [--gravar]        reabre (remove a pausa)
Sem --gravar só mostra o que faria. O motivo aparece no iFood. O iFood aceita pausa de 1 minuto a 7 dias.
"""
import sys, os, json, urllib.request, urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
args = [a for a in sys.argv[1:] if a != "--gravar"]; GRAVAR = "--gravar" in sys.argv[1:]
if not args or args[0] not in ("ver", "pausar", "remover"): print(__doc__); sys.exit(2)
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login(); api.timeout = max(getattr(api, "timeout", 0) or 0, 120)
TZ = ZoneInfo("America/Bahia")
contas = api.get("/admin/api/ifood/contas"); lojas = [l for l in contas.get("lojas_do_app") or [] if l.get("conectada_aqui")] or contas.get("conectadas") or []
if not lojas: print("PAREI: nenhuma loja do iFood ligada"); sys.exit(1)
loja = lojas[0]; mid = loja.get("merchant_id") or loja.get("id")
def estado():
    st = api.get(f"/admin/api/ifood/status/{mid}"); lj = api.get(f"/admin/api/ifood/loja/{mid}")
    pausas = lj.get("pausas") or lj.get("interrupcoes") or lj.get("interruptions") or []
    op = (st.get("operacoes") or [{}])[0]; msg = op.get("mensagem") or {}
    print(f"loja no iFood: {loja.get('nome') or loja.get('name')} (…{str(mid)[-6:]}) | estado: {st.get('estado')} | disponível: {st.get('disponivel')} | {msg.get('title')} — {msg.get('subtitle')}")
    for v in op.get("validacoes") or []: print("    ·", v.get("codigo"), v.get("estado"), "|", (v.get("mensagem") or {}).get("title"), "—", (v.get("mensagem") or {}).get("subtitle"))
    print("pausas:", json.dumps(pausas, ensure_ascii=False) if pausas else "nenhuma", "| chaves da loja:", [k for k in lj.keys()][:14])
    return st, lj, pausas
def enviar(path, corpo=None, metodo="POST"):
    req = urllib.request.Request(BASE_URL + path, data=(json.dumps(corpo).encode() if corpo is not None else None), method=metodo, headers={"Content-Type": "application/json", "Accept": "application/json"})
    st, r = api._send(req)
    if st == 401: api.login(); st, r = api._send(req)
    return st, r
agora = datetime.now(TZ); print("agora:", agora.strftime("%a %d/%m/%Y %H:%M"), "(Bahia)")
st, lj, pausas = estado()
if args[0] == "ver": sys.exit()
if args[0] == "pausar":
    fim = datetime.fromisoformat(args[1]).replace(tzinfo=TZ); motivo = args[2][:255]; inicio = agora + timedelta(minutes=2)
    if not (timedelta(minutes=1) < fim - inicio <= timedelta(days=7)): print("PAREI: o iFood aceita pausa de 1 minuto a 7 dias"); sys.exit(1)
    corpo = {"merchant_id": mid, "descricao": motivo, "inicio": inicio.strftime("%Y-%m-%dT%H:%M"), "fim": fim.strftime("%Y-%m-%dT%H:%M")}
    print("faria: pausar no iFood de", corpo["inicio"], "até", corpo["fim"], "(hora da Bahia) | motivo:", motivo)
    if not GRAVAR: print("modo: dry-run (nada enviado ao iFood)"); sys.exit()
    s2, r = enviar("/admin/api/ifood/pausa", corpo); print("pausar:", s2, json.dumps(r, ensure_ascii=False)[:400])
    if s2 != 200 or (isinstance(r, dict) and r.get("success") is False): print("PAREI: o iFood não aceitou a pausa"); sys.exit(1)
    print("--- conferindo"); estado(); print("modo: GRAVAR | ok")
else:
    pid = args[1]; print("faria: remover a pausa", pid)
    if not GRAVAR: print("modo: dry-run (nada enviado ao iFood)"); sys.exit()
    s2, r = enviar(f"/admin/api/ifood/pausa/{mid}/{urllib.parse.quote(pid, safe='')}", metodo="DELETE"); print("remover:", s2, json.dumps(r, ensure_ascii=False)[:300])
    print("--- conferindo"); estado()
