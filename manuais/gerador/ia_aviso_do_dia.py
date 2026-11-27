"""Aviso do dia para a IA do WhatsApp da Tili Sushi (ALIV > Configurações > Robô de IA e Boas-vindas no WhatsApp).

Pedido do Emerson em 27/11/2026 (Black Friday): "Hoje o delivery não funcionará, apenas consumo no salão. Dar essa instrução
para a IA do sushi e mandar a arte para quem perguntar."

O que o plano (JSON) pode mudar, e só isso:
  - "exemplos": a lista de "Cliente pergunta / Resposta ideal" da IA (no máximo 5);
  - "accept_delivery" / "accept_pickup": se a IA aceita pedido de entrega / de retirada;
  - "boas_vindas": { "modo": "link" | "so_texto" | "nada", "mandar_cardapio": true|false, "texto": "..." };
  - "foto": imagem (JPG, PNG ou WebP) enviada junto com a boas-vindas, no lugar do "cardápio em PDF ou foto".
Todo o resto da configuração da IA é regravado exatamente como está (a tela do ALIV faz igual).
A chave de API da IA passa só pela memória, como na tela: nunca é impressa nem gravada em arquivo.

  python3 ia_aviso_do_dia.py plano.json                 mostra o que mudaria (dry-run, nada gravado)
  python3 ia_aviso_do_dia.py plano.json --gravar        guarda o "antes" em manuais/aliv_backup, grava, relê e confere
  python3 ia_aviso_do_dia.py --voltar antes.json        mostra como voltaria ao que estava (dry-run)
  python3 ia_aviso_do_dia.py --voltar antes.json --gravar
"""
import sys, os, json, uuid, mimetypes, hashlib, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/Contapecas/monitor")
from monitor import Aliv, BASE_URL
LOJA = 155
args = [a for a in sys.argv[1:] if a not in ("--gravar", "--voltar")]; GRAVAR = "--gravar" in sys.argv[1:]; VOLTAR = "--voltar" in sys.argv[1:]
if len(args) != 1: print(__doc__); sys.exit(2)
arq = os.path.abspath(args[0]); dados = json.load(open(arq, encoding="utf-8"))
api = Aliv(os.environ["ALIV_USER_SUSHI"], os.environ["ALIV_PASS_SUSHI"]); api.login()
s = lambda v: "true" if v else "false"
def parar(m): print("PAREI:", m); sys.exit(1)

def enviar(path, campos=None, arquivo=None, corpo_json=None, metodo="POST"):
    """campos: lista de (nome, valor); arquivo: (nome do campo, caminho). Devolve (status, resposta)."""
    def f():
        if corpo_json is not None:
            return urllib.request.Request(BASE_URL + path, data=json.dumps(corpo_json).encode(), method=metodo, headers={"Content-Type": "application/json", "Accept": "application/json"})
        bd = uuid.uuid4().hex; corpo = b""
        for k, v in campos or []: corpo += f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        if arquivo:
            campo, caminho = arquivo; tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
            corpo += f'--{bd}\r\nContent-Disposition: form-data; name="{campo}"; filename="{os.path.basename(caminho)}"\r\nContent-Type: {tipo}\r\n\r\n'.encode() + open(caminho, "rb").read() + b"\r\n"
        corpo += f"--{bd}--\r\n".encode()
        return urllib.request.Request(BASE_URL + path, data=corpo, method=metodo, headers={"Content-Type": f"multipart/form-data; boundary={bd}", "Accept": "application/json"})
    st, r = api._send(f())
    if st == 401: api.login(); st, r = api._send(f())
    return st, r

SEGREDO = ("key", "chave", "token", "secret", "senha")
def sem_segredo(c):       # cópia da configuração sem as chaves, para comparar e mostrar
    return {k: v for k, v in c.items() if not any(x in k.lower() for x in SEGREDO)}
def marca(c):             # impressão digital das chaves (para conferir que não mudaram, sem mostrar nem guardar)
    return hashlib.sha256(json.dumps([c.get("api_key"), c.get("claude_chave_mascarada"), c.get("claude_ativo")], sort_keys=True).encode()).hexdigest()[:12]

def campos_ia(c, exemplos, deliv, retir):
    """Os campos que a tela do ALIV envia ao salvar o Robô de IA, com os valores atuais; só mudam exemplos e modalidades."""
    sabores = [i["id"] for g in c.get("ai_flavor_groups") or [] for i in g.get("items") or [] if i.get("ai_default_flavor")]
    tamanhos = [t["id"] for t in c.get("ai_default_sizes") or [] if isinstance(t, dict) and t.get("ai_default")]
    return [("store_id", str(LOJA)), ("api_key", c.get("api_key") or ""), ("is_active", s(c.get("active"))), ("ai_profile", c.get("profile") or "objective"),
            ("few_shot_examples", json.dumps([e for e in exemplos if e.get("user") and e.get("assistant")], ensure_ascii=False)),
            ("ai_accept_delivery", s(deliv)), ("ai_accept_pickup", s(retir)),
            ("auto_order", s(c.get("auto_order"))), ("skip_payment_question", s(c.get("skip_payment_question") is not False)),
            ("upsell_bebidas", s(c.get("upsell_bebidas") is not False)), ("upsell_borda", s(c.get("upsell_borda") is True)),
            ("cascata_custo", s(c.get("cascata_custo") is not False)), ("perguntar_entrega_retirada", s(c.get("perguntar_entrega_retirada") is True)),
            ("pedir_referencia", s(c.get("pedir_referencia") is True)),
            ("trocas_gratis", json.dumps([t for t in c.get("trocas_gratis") or [] if (t.get("de") or "").strip() and (t.get("para") or "").strip()], ensure_ascii=False)),
            ("nome_atendente", (c.get("nome_atendente") or "").strip()), ("apresentar_nome", s(c.get("apresentar_nome") is not False)),
            ("ia_horarios", json.dumps(c.get("ia_horarios") or {"ativo": False, "dias": {}}, ensure_ascii=False)),
            ("ia_sem_validacao", s(c.get("ia_sem_validacao") is True)), ("ia_acrescenta_em_preparo", s(c.get("ia_acrescenta_em_preparo") is True)),
            ("ia_so_pedidos", s(c.get("ia_so_pedidos") is True)), ("numeros_internos", c.get("numeros_internos") or ""),
            ("ai_default_sizes_json", json.dumps(tamanhos)), ("ai_default_flavors_json", json.dumps(sabores))]

atual = api.get(f"/admin/api/stores/{LOJA}/ai-config"); bv = api.get(f"/admin/api/stores/{LOJA}/boas-vindas")
antes = {"exemplos": atual.get("few_shot_examples") or [], "accept_delivery": atual.get("accept_delivery"), "accept_pickup": atual.get("accept_pickup"),
         "boas_vindas": bv.get("boas_vindas") or {}, "tinha_arquivo_de_cardapio": bool(bv.get("cardapio_pdf"))}
if VOLTAR:
    plano = {"exemplos": dados["exemplos"], "accept_delivery": dados["accept_delivery"], "accept_pickup": dados["accept_pickup"], "boas_vindas": dados["boas_vindas"],
             "remover_foto": not dados.get("tinha_arquivo_de_cardapio")}
    if dados.get("tinha_arquivo_de_cardapio"): print("ATENÇÃO: antes havia um arquivo de cardápio na boas-vindas; este script não o recoloca.")
else:
    plano = dict(dados)
ex = plano.get("exemplos", antes["exemplos"]); deliv = plano.get("accept_delivery", antes["accept_delivery"]); retir = plano.get("accept_pickup", antes["accept_pickup"])
nbv = plano.get("boas_vindas", antes["boas_vindas"]); foto = os.path.normpath(os.path.join(os.path.dirname(arq), plano["foto"])) if plano.get("foto") else None
if len(ex) > 5: parar("a IA aceita no máximo 5 exemplos")
if nbv.get("modo") not in ("link", "so_texto", "nada"): parar("modo da boas-vindas inválido")
if foto and (not os.path.exists(foto) or os.path.splitext(foto)[1].lower() not in (".jpg", ".jpeg", ".png", ".webp")): parar(f"foto não encontrada ou formato não aceito: {foto}")

print(f"IA ligada: {atual.get('active')} | Claude: {atual.get('claude_ativo')} | perfil: {atual.get('profile')} | lança pedido sozinha: {atual.get('auto_order')}")
print(f"aceita entrega: {antes['accept_delivery']} -> {deliv} | aceita retirada: {antes['accept_pickup']} -> {retir} | aceita mesa/salão: {atual.get('accept_dining')} (não muda)")
print(f"\nEXEMPLOS HOJE ({len(antes['exemplos'])}):")
for e in antes["exemplos"]: print("   cliente:", e["user"], "\n   IA:     ", e["assistant"])
print(f"\nEXEMPLOS NOVOS ({len(ex)}):" if ex != antes["exemplos"] else "\nEXEMPLOS: não mudam")
if ex != antes["exemplos"]:
    for e in ex: print("   cliente:", e["user"], "\n   IA:     ", e["assistant"])
print(f"\nBOAS-VINDAS hoje: {json.dumps(antes['boas_vindas'], ensure_ascii=False)} | arquivo de cardápio: {antes['tinha_arquivo_de_cardapio']}")
print(f"BOAS-VINDAS nova: {json.dumps(nbv, ensure_ascii=False)} | foto: {os.path.basename(foto) if foto else ('remover' if plano.get('remover_foto') else 'não muda')}")
if not GRAVAR: print("\nmodo: dry-run (nada gravado)"); sys.exit()

if not VOLTAR:
    bk = f"/workspace/Contapecas/manuais/aliv_backup/ia_whatsapp_antes_{datetime.now(ZoneInfo('America/Bahia')):%Y-%m-%d}.json"
    if os.path.exists(bk): print("já existe o 'antes' de hoje, mantido:", bk)
    else: json.dump(dict(antes, quando=datetime.now(ZoneInfo("America/Bahia")).isoformat(timespec="minutes")), open(bk, "w", encoding="utf-8"), ensure_ascii=False, indent=1); print("antes guardado em", bk)
# 1) Robô de IA (exemplos e modalidades)
if ex != antes["exemplos"] or deliv != antes["accept_delivery"] or retir != antes["accept_pickup"]:
    st, r = enviar("/admin/api/openai/sync", campos=campos_ia(atual, ex, deliv, retir))
    print("salvar IA:", st, str(r.get("message") if isinstance(r, dict) else r)[:160])
    if st != 200 or (isinstance(r, dict) and r.get("success") is False): parar("a configuração da IA não foi salva")
    novo = api.get(f"/admin/api/stores/{LOJA}/ai-config")
    a, n = sem_segredo(atual), sem_segredo(novo)
    fora = sorted(k for k in set(a) | set(n) if a.get(k) != n.get(k) and k not in ("few_shot_examples", "accept_delivery", "accept_pickup"))
    print(f"   relido: exemplos {len(novo.get('few_shot_examples') or [])} | entrega {novo.get('accept_delivery')} | retirada {novo.get('accept_pickup')} | outros campos que mudaram: {fora or 'nenhum'} | chaves intactas: {marca(atual) == marca(novo)} | IA ligada: {novo.get('active')}")
    if (novo.get("few_shot_examples") or []) != ex or novo.get("accept_delivery") != deliv or novo.get("accept_pickup") != retir or fora or marca(atual) != marca(novo) or novo.get("active") != atual.get("active"):
        parar("a configuração da IA não ficou como o plano — conferir na tela do ALIV")
# 2) foto da boas-vindas
if foto:
    st, r = enviar(f"/admin/api/stores/{LOJA}/cardapio-pdf", arquivo=("arquivos", foto)); print("enviar foto:", st, str(r)[:200])
    if st != 200: parar("a foto não foi enviada")
elif plano.get("remover_foto"):
    st, r = enviar(f"/admin/api/stores/{LOJA}/cardapio-pdf", campos=[("remover", "true")]); print("remover foto:", st, str(r)[:160])
    if st != 200: parar("a foto não foi removida")
# 3) boas-vindas
if nbv != antes["boas_vindas"]:
    st, r = enviar(f"/admin/api/stores/{LOJA}/boas-vindas", corpo_json={"modo": nbv["modo"], "mandar_cardapio": bool(nbv.get("mandar_cardapio")), "texto": (nbv.get("texto") or "").strip()})
    print("salvar boas-vindas:", st, str(r.get("message") if isinstance(r, dict) else r)[:160])
    if st != 200: parar("a boas-vindas não foi salva")
fim = api.get(f"/admin/api/stores/{LOJA}/boas-vindas")
print("   relido boas-vindas:", json.dumps(fim.get("boas_vindas"), ensure_ascii=False), "| arquivo:", json.dumps({k: v for k, v in (fim.get("cardapio_pdf") or {}).items() if k in ("tipo", "nome", "bytes")}, ensure_ascii=False) if fim.get("cardapio_pdf") else "nenhum")
print("modo: GRAVAR | ok")
