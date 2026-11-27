"""Aviso e banner do cardápio digital (site/app) do ALIV: Configurações > Aparência dos Cardápios ("Logo, banner, cor e aviso").
Pedido do Emerson em 27/11/2026: o site falar só da Black Friday no salão e avisar que hoje não tem delivery.
Muda SÓ o texto de aviso e o banner; não fecha a loja, não mexe em cardápio, preço, cor nem logo.

  python3 site_aviso.py "<texto do aviso>" <banner 1200x400 .jpg/.png> [--gravar]   põe o aviso e o banner (guarda o "antes")
  python3 site_aviso.py --voltar <antes.json> [--gravar]                           volta o aviso e o banner ao que eram
Sem --gravar só mostra o que faria.
"""
import sys, os, json, uuid, mimetypes, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
LOJA = 155
args = [a for a in sys.argv[1:] if a not in ("--gravar", "--voltar")]; GRAVAR = "--gravar" in sys.argv[1:]; VOLTAR = "--voltar" in sys.argv[1:]
if (VOLTAR and len(args) != 1) or (not VOLTAR and len(args) != 2): print(__doc__); sys.exit(2)
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login(); api.timeout = max(getattr(api, "timeout", 0) or 0, 120)
def parar(m): print("PAREI:", m); sys.exit(1)
def aparencia():
    a = api.get(f"/admin/api/stores/{LOJA}/appearance-config"); return {k: a.get(k) for k in ("slug", "banner_url", "banner_padrao_url", "informative_text", "app_theme_color", "logo_url", "delivery_langs")}
def salvar(campos, arquivo=None):
    bd = uuid.uuid4().hex; corpo = b""
    for k, v in campos: corpo += f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    if arquivo:
        tipo = mimetypes.guess_type(arquivo)[0] or "application/octet-stream"
        corpo += f'--{bd}\r\nContent-Disposition: form-data; name="banner_file"; filename="{os.path.basename(arquivo)}"\r\nContent-Type: {tipo}\r\n\r\n'.encode() + open(arquivo, "rb").read() + b"\r\n"
    corpo += f"--{bd}--\r\n".encode()
    req = urllib.request.Request(BASE_URL + "/admin/stores/save_appearance", data=corpo, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"})
    st, r = api._send(req); print("salvar aparência:", st, str(r)[:200])
    if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar("a aparência não foi salva")
antes = aparencia()
print("hoje no site: aviso =", repr(antes["informative_text"]), "| banner próprio =", antes["banner_url"] or "nenhum", "| cor", antes["app_theme_color"])
if VOLTAR:
    d = json.load(open(args[0], encoding="utf-8")); texto = d.get("informative_text") or ""; tinha = bool(d.get("banner_url"))
    print("voltaria: aviso =", repr(texto), "| banner:", "manter (havia um banner próprio antes; recolocar à mão)" if tinha else "remover o banner da Black (antes não havia banner próprio)")
    if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
    salvar([("store_id", str(LOJA)), ("slug", antes["slug"]), ("informative_text", texto)] + ([] if tinha else [("remove_banner", "1")]))
    dep = aparencia(); print("relido: aviso =", repr(dep["informative_text"]), "| banner próprio =", dep["banner_url"] or "nenhum")
    fora = [k for k in ("slug", "app_theme_color", "logo_url", "delivery_langs") if antes[k] != dep[k]]
    if dep["informative_text"] != texto or (not tinha and dep["banner_url"]) or fora: parar(f"não voltou como devia (mudou também: {fora})")
    print("modo: GRAVAR | ok")
else:
    texto, banner = args[0].strip(), os.path.abspath(args[1])
    if not os.path.exists(banner) or os.path.getsize(banner) > 8 * 1024 * 1024: parar("banner não encontrado ou maior que 8 MB")
    print("faria: aviso =", repr(texto), f"({len(texto)} caracteres) | banner =", os.path.basename(banner), f"({os.path.getsize(banner) // 1024} KB)")
    if not GRAVAR: print("modo: dry-run (nada gravado)"); sys.exit()
    bk = f"/workspace/Contapecas/manuais/aliv_backup/site_antes_{datetime.now(ZoneInfo('America/Bahia')):%Y-%m-%d}.json"
    if not os.path.exists(bk): json.dump(dict(antes, quando=datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes")), open(bk, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print("antes guardado em", bk)
    salvar([("store_id", str(LOJA)), ("slug", antes["slug"]), ("informative_text", texto)], arquivo=banner)
    dep = aparencia(); print("relido: aviso =", repr(dep["informative_text"]), "| banner próprio =", dep["banner_url"] or "nenhum")
    fora = [k for k in ("slug", "app_theme_color", "logo_url", "delivery_langs") if antes[k] != dep[k]]
    if dep["informative_text"] != texto or not dep["banner_url"] or fora: parar(f"não ficou como o plano (mudou também: {fora})")
    print("modo: GRAVAR | ok")
