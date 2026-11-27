"""Valor mínimo do pedido do app e da IA do WhatsApp no ALIV (Configurações > Operacional > "Valor Mínimo do Pedido (App e WhatsApp)").
Vale na entrega e na retirada; mesa, comanda, totem e PDV ficam fora. Pedido do Emerson em 27/11/2026: baixar de R$ 20 para R$ 15
(um Temaki Hot a R$ 19,90 para retirada ficava abaixo do mínimo).

  python3 pedido_minimo.py 15            mostra o que faria (dry-run)
  python3 pedido_minimo.py 15 --gravar   grava, relê e confere que nenhum outro ajuste operacional mudou
"""
import sys, os, json, uuid, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
args = [a for a in sys.argv[1:] if a != "--gravar"]; GRAVAR = "--gravar" in sys.argv[1:]
if len(args) != 1: print(__doc__); sys.exit(2)
NOVO = float(args[0].replace(",", ".")); LOJA = 155
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login(); api.timeout = max(getattr(api, "timeout", 0) or 0, 120)
def campos(): return api.get(f"/admin/api/stores/{LOJA}/operational-config")["fields"]
antes = campos()
print(f"mínimo hoje: R$ {antes['min_order_value']:.2f} | retirada com mínimo próprio: {antes.get('pedido_minimo_retirada_proprio')} (valor R$ {antes.get('pedido_minimo_retirada')}) -> novo mínimo R$ {NOVO:.2f}")
if abs(float(antes["min_order_value"]) - NOVO) < 0.005: print("já está nesse valor: nada a fazer"); sys.exit()
if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
bk = f"/workspace/Contapecas/manuais/aliv_backup/pedido_minimo_antes_{datetime.now(ZoneInfo('America/Bahia')):%Y-%m-%d_%H%M}.json"
json.dump({"quando": datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes"), "min_order_value": antes["min_order_value"], "pedido_minimo_retirada_proprio": antes.get("pedido_minimo_retirada_proprio"), "pedido_minimo_retirada": antes.get("pedido_minimo_retirada")}, open(bk, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
bd = uuid.uuid4().hex
corpo = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in (("store_id", str(LOJA)), ("min_order_value", f"{NOVO:.2f}"))) + f"--{bd}--\r\n"
st, r = api._send(urllib.request.Request(BASE_URL + "/admin/stores/save_general", data=corpo.encode(), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"}))
print("salvar:", st, str(r)[:160])
dep = campos()
# com "mínimo diferente na retirada" desligado, o ALIV copia o valor geral para o campo da retirada: isso é esperado
segue = not dep.get("pedido_minimo_retirada_proprio") and abs(float(dep.get("pedido_minimo_retirada") or 0) - NOVO) < 0.005
fora = sorted(k for k in set(antes) | set(dep) if antes.get(k) != dep.get(k) and k != "min_order_value" and not (k == "pedido_minimo_retirada" and segue))
print(f"relido: mínimo R$ {float(dep['min_order_value']):.2f} | outros ajustes que mudaram: {fora or 'nenhum'}")
if abs(float(dep["min_order_value"]) - NOVO) > 0.005 or fora: print("PAREI: não ficou como o plano — conferir na tela do ALIV"); sys.exit(1)
print("modo: GRAVAR | ok | antes guardado em", bk)
