"""Religa a IA nas conversas de WhatsApp que receberam hoje a mensagem de correção e estão com a IA pausada.
Pedido do Emerson em 27/11/2026 ("Sim" para religar nas 5 conversas em que ela já estava pausada).
Não imprime telefone nem nome (só os 2 últimos dígitos).

  python3 religar_ia_conversas.py            mostra o que faria (dry-run)
  python3 religar_ia_conversas.py --gravar   religa e confere
"""
import sys, os, re, uuid, urllib.request, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR = "--gravar" in sys.argv[1:]; TZ = ZoneInfo("America/Bahia"); HOJE = datetime.now(TZ).date()
MARCA = "Corrigindo a informação que te passamos"
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login(); api.timeout = max(getattr(api, "timeout", 0) or 0, 120)
so_num = lambda s: re.sub(r"\D", "", str(s or ""))
def pausada(f): return bool(api.get("/admin/api/chat/ai-status/" + urllib.parse.quote(str(f), safe="")).get("ai_paused"))
alvos = []
for c in api.get("/admin/api/chat/contacts"):
    if not c.get("raw_ts") or datetime.fromisoformat(c["raw_ts"]).astimezone(TZ).date() != HOJE: continue
    r = api.get("/admin/api/chat/messages/" + urllib.parse.quote(str(c["phone"]), safe=""), {"limit": 60}); ms = r if isinstance(r, list) else (r.get("messages") or r.get("data") or [])
    if any(str(m.get("direction")).lower() == "outgoing" and MARCA in str(m.get("body") or "") for m in ms):
        alvos.append((c["phone"], pausada(c["phone"])))
print(f"conversas que receberam a correção hoje: {len(alvos)} | com a IA pausada: {sum(1 for _, p in alvos if p)}")
feitas = 0
for fone, p in alvos:
    if not p: print(f"   …{so_num(fone)[-2:]} | IA já ligada"); continue
    if not GRAVAR: print(f"   …{so_num(fone)[-2:]} | IA pausada -> religaria"); continue
    bd = uuid.uuid4().hex; corpo = f'--{bd}\r\nContent-Disposition: form-data; name="phone"\r\n\r\n{fone}\r\n--{bd}--\r\n'
    st, r = api._send(urllib.request.Request(BASE_URL + "/admin/api/chat/toggle-ai", data=corpo.encode(), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))
    depois = pausada(fone); feitas += (not depois)
    print(f"   …{so_num(fone)[-2:]} | religar: {st} | IA pausada agora: {depois}")
print("modo:", "GRAVAR" if GRAVAR else "dry-run (nada alterado)", "| religadas:", feitas)
