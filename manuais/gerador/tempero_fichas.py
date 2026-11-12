"""Tempero do peixe que vai para a grelha (Emerson, 12/11/2026): 10 g de hondashi + 4 g de realçador por quilo de peixe CRU.
Lança o hondashi nas fichas do ALIV que levam peixe grelhado. O realçador de sabor não tem cadastro/preço no estoque: fica de fora.
O peso da ficha é de peixe já grelhado; para chegar ao cru usa o rendimento da grelha que o Emerson passou na tilápia
(1 kg grelhado ≈ 1,43 kg cru → 70%). Hondashi: pacote de 500 g (unidade do estoque = pacote).
Uso: python3 tempero_fichas.py [--gravar]   (sem --gravar só mostra)"""
import sys, os, uuid, urllib.parse, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
GRAVAR = "--gravar" in sys.argv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
GRELHADO, HONDASHI = 23638, 23640
G_POR_KG_CRU, REND_GRELHA, PACOTE_G = 10, 0.70, 500
PRODUTOS = [11686, 11689, 11667, 11651]                     # Temaki Salmão grelhado, Temaki Hot, Hosso Salmão grelhado, Ura Salmão Grelhado
ACARAJAPA, TILAPIA_CRUA_KG, BOLINHOS, HONDASHI_MASSA_G = 32379, 1 / 0.70, 5530 / 30, 30
nomes = {p["id"]: p["name"] for c in api.get("/admin/api/menu/full_data")["categories"] for p in c["products"]}

def ficha(pid): return api.get(f"/admin/menu/product/{pid}/recipes")
def custo(l): return sum(x["total_cost"] for x in l)
def incluir(pid, q):
    return api._send(urllib.request.Request(BASE_URL + "/admin/menu/recipe/save", method="POST",
        data=urllib.parse.urlencode({"product_id": pid, "ingredient_id": HONDASHI, "quantity": f"{q:.6f}"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "application/json"}))
def alterar(rid, q):
    b = uuid.uuid4().hex
    body = f'--{b}\r\nContent-Disposition: form-data; name="quantity"\r\n\r\n{q:.6f}\r\n--{b}--\r\n'.encode()
    return api._send(urllib.request.Request(BASE_URL + f"/admin/menu/recipe/{rid}/update_quantity", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"}))

erros = []
for pid in PRODUTOS:
    f = ficha(pid); peixe = next((l for l in f if l["ingredient_id"] == GRELHADO), None); hon = next((l for l in f if l["ingredient_id"] == HONDASHI), None)
    if not peixe: erros.append((pid, "sem peixe grelhado na ficha")); continue
    q = round(peixe["quantity"] / REND_GRELHA * G_POR_KG_CRU / PACOTE_G, 6)        # pacotes de hondashi
    if hon and abs(hon["quantity"] - q) < 1e-7:
        print(f"já lançado {nomes[pid][:40]:40s} hondashi {q*PACOTE_G:.2f} g | custo R$ {custo(f):.4f}"); continue
    if GRAVAR:
        st, r = alterar(hon["id"], q) if hon else incluir(pid, q)
        if st != 200: erros.append((pid, st, str(r)[:100])); continue
    d = ficha(pid)
    print(f"{'gravado ' if GRAVAR else 'lançaria'} {nomes[pid][:40]:40s} peixe grelhado {1000*peixe['quantity']:.0f} g -> hondashi {q*PACOTE_G:.2f} g ({q:.6f} pct) | custo R$ {custo(f):.4f} -> {custo(d):.4f}")
f = ficha(ACARAJAPA); hon = next(l for l in f if l["ingredient_id"] == HONDASHI)
q = round((HONDASHI_MASSA_G + TILAPIA_CRUA_KG * G_POR_KG_CRU) / PACOTE_G / BOLINHOS, 6)
if abs(hon["quantity"] - q) < 1e-7:
    print(f"já lançado {nomes[ACARAJAPA]:40s} hondashi {q:.6f} pct | custo R$ {custo(f):.4f}")
else:
    if GRAVAR:
        st, r = alterar(hon["id"], q)
        if st != 200: erros.append((ACARAJAPA, st, str(r)[:100]))
    d = ficha(ACARAJAPA)
    print(f"{'gravado ' if GRAVAR else 'lançaria'} {nomes[ACARAJAPA]:40s} hondashi {hon['quantity']:.6f} -> {q:.6f} pct por bolinho (massa 30 g + tempero da tilápia {TILAPIA_CRUA_KG*G_POR_KG_CRU:.1f} g na receita) | custo R$ {custo(f):.4f} -> {custo(d):.4f}")
print("modo:", "GRAVAR" if GRAVAR else "dry-run", "| erros:", erros or "nenhum")
