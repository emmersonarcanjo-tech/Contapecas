"""Salmão: grava nas fichas do ALIV a quantidade bruta calculada num plano (peso limpo ÷ rendimento médio medido).

Uso: python3 salmao_plano_gravar.py plano.json            -> só mostra o que mudaria (dry-run)
     python3 salmao_plano_gravar.py plano.json --gravar   -> grava e relê cada linha

O plano traz, por linha: recipe_id, product_id, quantity (valor lido antes) e nova_quantity.
Antes de gravar, relê a ficha e só altera se a quantidade atual ainda for a do plano (ninguém mexeu no meio).
Autorizado pelo Emerson: manter as fichas no rendimento medido das caixas.
"""
import sys, os, json, uuid, urllib.request
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL

SAL = 23889
plano = json.load(open(sys.argv[1]))["plano"]
gravar = "--gravar" in sys.argv
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()


def linha(pid, rid):
    for r in api.get(f"/admin/menu/product/{pid}/recipes"):
        if r["id"] == rid and r["ingredient_id"] == SAL:
            return r
    return None


ok, pulos, erros = 0, [], []
for p in plano:
    atual = linha(p["product_id"], p["recipe_id"])
    if atual is None:
        pulos.append((p["produto"], "linha não encontrada")); continue
    if abs(atual["quantity"] - p["nova_quantity"]) < 0.00005:
        ok += 1; continue                                    # já está no valor novo
    if abs(atual["quantity"] - p["quantity"]) > 0.00005:
        pulos.append((p["produto"], f"quantidade mudou: {atual['quantity']} (plano esperava {p['quantity']})")); continue
    if not gravar:
        print(f"mudaria {p['produto'][:44]:44s} {p['quantity']:.4f} -> {p['nova_quantity']:.4f}"); continue
    b = uuid.uuid4().hex
    body = f'--{b}\r\nContent-Disposition: form-data; name="quantity"\r\n\r\n{p["nova_quantity"]}\r\n--{b}--\r\n'.encode()
    st, _ = api._send(urllib.request.Request(BASE_URL + f"/admin/menu/recipe/{p['recipe_id']}/update_quantity", data=body, method="POST",
                      headers={"Content-Type": f"multipart/form-data; boundary={b}", "Accept": "application/json"}))
    depois = linha(p["product_id"], p["recipe_id"])
    if st == 200 and depois and abs(depois["quantity"] - p["nova_quantity"]) < 0.00005:
        ok += 1
    else:
        erros.append((p["produto"], st, depois and depois["quantity"]))
print("linhas no plano", len(plano), "| no valor novo", ok, "| puladas", pulos, "| erros", erros, "| modo", "GRAVAR" if gravar else "dry-run")
