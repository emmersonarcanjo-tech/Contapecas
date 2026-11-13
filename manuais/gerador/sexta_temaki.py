"""Sexta do Temaki automática no ALIV (pedido do Emerson em 13/11/2026), sem trocar preço toda sexta.

Usa a tela de Promoções do próprio ALIV (Promoções > Nova promoção): UMA promoção "Sexta do Temaki", tipo "Preço final",
R$ 24,90, só na sexta-feira (o dia inteiro, até 23:59), aplicada aos temakis escolhidos. O produto continua um só:
mesma ficha, mesmo relatório, nada some do cardápio. Fora da sexta vale o preço normal.
Junto: os temakis da promoção entram na categoria "SEXTA DO TEMAKI NA TILI" (que só aparece na sexta) e os 4 que ficaram com
o preço do QR de indicação errado (27,39, resto de troca manual) voltam para preço + 10%.
Não mexe em iFood.

  python3 sexta_temaki.py                      mostra o que faria (dry-run)
  python3 sexta_temaki.py --gravar --piloto    cria a promoção só com o Temaki Atum e confere no PDV (se hoje for sexta)
  python3 sexta_temaki.py --gravar             promoção com os 9 temakis + ajustes de categoria e de QR; para no primeiro problema
  python3 sexta_temaki.py --desligar --gravar  desliga a promoção (os preços normais voltam a valer na sexta)
"""
import sys, os, json, uuid, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
ARGS = set(sys.argv[1:])
if ARGS - {"--gravar", "--piloto", "--desligar"}: print("argumento desconhecido:", ARGS - {"--gravar", "--piloto", "--desligar"}); sys.exit(2)
GRAVAR, PILOTO, DESLIGAR = "--gravar" in ARGS, "--piloto" in ARGS, "--desligar" in ARGS
NOME, PRECO, CAT_SEXTA, SEXTA = "Sexta do Temaki", 24.90, 1006, 4            # dias: 0=segunda ... 4=sexta ... 6=domingo
INICIO, FIM = "2026-11-13", "2030-12-31"
TEMAKIS = [11688, 11689, 11686, 11683, 11679, 11676, 11684, 11677, 11678]   # Atum, Hot, Salmão grelhado, Salmão, Capão, Tailandês, Filadélfia, Camarão Cozido, Camarão Empanado
alvo = TEMAKIS[:1] if PILOTO else TEMAKIS
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
b = lambda v: "true" if v else "false"

def parar(msg): print("PAREI:", msg); sys.exit(1)
def multipart(pares, path):
    """pares: lista de (campo, valor) — aceita campo repetido (days[], prod_ids[])."""
    def f():
        bd = uuid.uuid4().hex
        corpo = "".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in pares) + f"--{bd}--\r\n"
        return urllib.request.Request(BASE_URL + path, data=corpo.encode(), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"})
    st, r = api._send(f())
    if st == 401: api.login(); st, r = api._send(f())
    return st, r
def cardapio():
    out = {}
    for c in api.get("/admin/api/menu/full_data")["categories"]:
        for p in c["products"]: out.setdefault(p["id"], p)
    return out
def promocao():
    return next((x for x in api.get("/admin/api/promotions/data").get("promotions", []) if x.get("name") == NOME), None)
def pdv():
    return {p["id"]: p for p in api.get("/admin/api/pdv/data")["products"]}

def campos_produto(p, **troca):
    """Todos os campos do produto como a tela do ALIV envia; `troca` muda só o que foi pedido."""
    fd = p["full_data"]; cfg = fd.get("config") or {}
    c = {"prod_id": p["id"], "name": fd["name"], "description": fd.get("description") or "", "category_id": fd["category_id"], "price": fd["price"],
         "price_in_points": fd.get("price_in_points") or 0, "channel_prices_json": json.dumps(fd.get("channel_prices") or {}),
         "compare_at_price": fd.get("compare_at_price") or 0, "allows_flavors": b(fd.get("allows_flavors")), "max_flavors": fd.get("max_flavors") or 1,
         "is_pizza": b(fd.get("is_pizza")), "auto_disable_on_stock_zero": b(fd.get("auto_disable_on_stock_zero")), "sold_by_weight": b(fd.get("sold_by_weight")),
         "kitchen_alert_active": b(fd.get("kitchen_alert_active")), "kitchen_alert_text": fd.get("kitchen_alert_text") or "",
         "show_in_kiosk": b(fd.get("show_in_kiosk")), "show_in_pdv": b(fd.get("show_in_pdv")), "show_in_waiter": b(fd.get("show_in_waiter")),
         "show_in_ia": b(fd.get("show_in_ia")), "show_in_delivery": b(fd.get("show_in_delivery")), "show_in_print_menu": b(fd.get("show_in_print_menu", True)),
         "menu_ids_json": json.dumps(fd.get("menu_ids") or []), "schedule_rules_json": json.dumps(fd.get("schedule_rules") or []),
         "pausa_horario_ligada": b((fd.get("pausa_horario") or {}).get("ligada")), "size_prices_json": json.dumps(fd.get("size_prices") or []),
         "config_json": json.dumps({"additional_categories": cfg.get("additional_categories") or [], "allowed_addons": cfg.get("allowed_addons") or [], "blocked_addons": cfg.get("blocked_addons") or []})}
    for k in ("detailed_description", "preparation_method", "barcode", "ncm", "cfop", "uom", "cest"):
        if fd.get(k) is not None: c[k] = fd[k]
    if p.get("external_code") is not None: c["external_code"] = p["external_code"]
    if fd.get("image_bank_id") is not None: c["image_bank_id"] = fd["image_bank_id"]
    elif fd.get("image_url"): c["image_url"] = fd["image_url"]
    c.update(troca); return list(c.items())

card = cardapio(); pr = promocao(); hoje = datetime.now(ZoneInfo("America/Bahia"))
for pid in TEMAKIS:
    if pid not in card: parar(f"temaki {pid} não está no cardápio")
print(f"hoje: {hoje:%d/%m/%Y %H:%M} (Bahia), dia da semana {hoje.weekday()} | promoção '{NOME}':", json.dumps(pr, ensure_ascii=False) if pr else "ainda não existe")
print(f"{'temaki':36s} {'preço':>6s} {'na promoção':>12s} | categoria da sexta | QR de indicação")
ajustes = []
for pid in TEMAKIS:
    p = card[pid]; fd = p["full_data"]; adic = (fd.get("config") or {}).get("additional_categories") or []
    canais = dict(fd.get("channel_prices") or {}); qr_certo = round(p["price"] * 1.10, 2)
    novo_adic = adic if CAT_SEXTA in adic else adic + [CAT_SEXTA]
    novo_canais = dict(canais, indicacao=qr_certo) if "indicacao" in canais and abs(canais["indicacao"] - qr_certo) > 0.005 else canais
    if novo_adic != adic or novo_canais != canais: ajustes.append((pid, novo_adic, novo_canais))
    print(f"{p['name'][:36]:36s} {p['price']:6.2f} {'sim' if pid in alvo else '—':>12s} | {'já está' if CAT_SEXTA in adic else 'entra':18s} | {canais.get('indicacao')} {'ok' if novo_canais == canais else '-> ' + str(qr_certo)}")

if DESLIGAR:
    if not pr: parar("a promoção não existe")
    ligada = pr.get("is_active", pr.get("active"))
    print("promoção ligada:", ligada)
    if GRAVAR and ligada:
        st, r = multipart([], f"/admin/promotions/{pr['id']}/toggle"); print("desligar:", st, str(r)[:120]); print("agora:", json.dumps(promocao(), ensure_ascii=False))
    sys.exit()
if not GRAVAR:
    print(f"faria: promoção '{NOME}' preço final R$ {PRECO:.2f}, só sexta, {len(alvo)} temaki(s), de {INICIO} a {FIM}; {len(ajustes) if not PILOTO else 0} produto(s) com ajuste de categoria/QR")
    print("modo: dry-run (nada gravado)"); sys.exit()

# 1) promoção (cria ou atualiza)
pares = ([("promo_id", pr["id"])] if pr else []) + [("name", NOME), ("promo_type", "fixed_price"), ("value", f"{PRECO:.2f}"), ("usage_limit", "0"),
        ("start_date", INICIO), ("end_date", FIM), ("target_type", "product"), ("days[]", str(SEXTA))] + [("prod_ids[]", str(i)) for i in alvo] + [
        ("show_in_kiosk", "true"), ("show_in_pdv", "true"), ("show_in_waiter", "true"), ("show_in_delivery", "true"), ("show_in_ia", "true"),
        ("payment_condition", ""), ("menu_ids_json", "[]")]
st, r = multipart(pares, "/admin/promotions/save"); print("salvar promoção:", st, str(r)[:200])
if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar("a promoção não foi salva")
pr = promocao()
if not pr: parar("a promoção não apareceu na lista")
print("promoção gravada:", json.dumps(pr, ensure_ascii=False))
ok = (pr.get("promo_type") == "fixed_price" and abs(float(pr.get("value")) - PRECO) < 0.001 and [int(d) for d in (pr.get("days") or [])] == [SEXTA]
      and pr.get("target_type") == "product" and sorted(int(i) for i in (pr.get("target_ids") or [])) == sorted(alvo))
if not ok: parar("a promoção não ficou como o plano")
if pr.get("is_active", pr.get("active", True)) is False:
    st, r = multipart([], f"/admin/promotions/{pr['id']}/toggle"); pr = promocao()
    if pr.get("is_active", pr.get("active")) is False: parar("a promoção ficou desligada")

# 2) conferência no PDV (só faz sentido na sexta)
if hoje.weekday() == SEXTA:
    v = pdv()
    for pid in TEMAKIS:
        p = v.get(pid)
        if not p: parar(f"{card[pid]['name']}: sumiu do PDV")
        esperado = PRECO if pid in alvo else card[pid]["price"]
        print(f"   PDV {card[pid]['name'][:34]:34s} preço R$ {p['price']:.2f} | original R$ {p.get('original_price')} | esperado R$ {esperado:.2f}")
        if abs(p["price"] - esperado) > 0.001: parar(f"{card[pid]['name']}: no PDV está R$ {p['price']:.2f}, esperado R$ {esperado:.2f}")
else:
    print("hoje não é sexta: o preço da promoção só aparece no PDV na sexta")

# 3) ajustes nos produtos (categoria da sexta e QR de indicação) — não no piloto
if not PILOTO:
    for pid, novo_adic, novo_canais in ajustes:
        p = card[pid]; fd = p["full_data"]; cfg = fd.get("config") or {}
        st, r = multipart(campos_produto(p, channel_prices_json=json.dumps(novo_canais),
                  config_json=json.dumps({"additional_categories": novo_adic, "allowed_addons": cfg.get("allowed_addons") or [], "blocked_addons": cfg.get("blocked_addons") or []})), "/admin/menu/product/save")
        if st != 200: parar(f"{p['name']}: não salvou ({st} {str(r)[:120]})")
        d = cardapio()[pid]; a, n = fd, d["full_data"]
        fora = sorted(k for k in set(a) | set(n) if a.get(k) != n.get(k) and k not in ("channel_prices", "config"))
        if fora or p["is_active"] != d["is_active"] or p["price"] != d["price"]: parar(f"{p['name']}: mudou o que não devia: {fora}")
        if (n.get("channel_prices") or {}) != novo_canais or ((n.get("config") or {}).get("additional_categories") or []) != novo_adic:
            parar(f"{p['name']}: categoria/QR não gravou ({n.get('channel_prices')}, {(n.get('config') or {}).get('additional_categories')})")
        print(f"   ajustado {p['name'][:34]:34s} categorias extras {novo_adic} | QR {novo_canais.get('indicacao')}")
print("modo: GRAVAR", "(piloto)" if PILOTO else "", "| ok")
