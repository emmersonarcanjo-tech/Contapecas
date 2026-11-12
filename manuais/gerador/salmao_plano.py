"""Plano (sem gravar): nova quantidade de salmão bruto em cada ficha = peso limpo exato ÷ rendimento médio das 4 caixas."""
import sys, json
snap = json.load(open(sys.argv[1]))
caixas = [(34.954, 9.624), (28.954, 8.292), (28.730, 7.968), (29.206, 9.042)]   # recebido na balança, descarte
VELHO = sum(c[0]-c[1] for c in caixas[:2]) / sum(c[0] for c in caixas[:2])      # média de 2 caixas: o que está no ALIV hoje
NOVO = sum(c[0]-c[1] for c in caixas) / sum(c[0] for c in caixas)               # média das 4 caixas
PRECO = snap["estoque_salmao"][0]["cost"]
plano = []
for l in snap["linhas"]:
    q = l["quantity"]; limpo = q * VELHO * 1000
    if l["produto"] == "Acarajapa": exato = 1000 / (5530 / 30)                   # 1 kg de salmão limpo na massa de 5,53 kg, bolinho de 30 g
    else:
        exato = round(limpo)
        assert abs(exato - limpo) < 0.35, (l["produto"], limpo)
    if "(1 peça)" in l["produto"]:                                              # peça avulsa = porção ÷ nº de peças (mesma regra já usada no ALIV)
        n = 4 if l["produto"].startswith("Niguiri") else 2
        novo_q = round(round(n * exato / 1000 / NOVO, 4) / n, 6)
    else:
        novo_q = round(exato / 1000 / NOVO, 4)
    plano.append({**l, "limpo_estimado_g": round(limpo, 2), "limpo_exato_g": round(exato, 3), "nova_quantity": novo_q,
                  "custo_linha_novo": round(novo_q * PRECO, 4),
                  "custo_ficha_novo": round(l["custo_ficha"] - l["custo_linha"] + novo_q * PRECO, 4)})
json.dump({"rendimento_atual_aliv": VELHO, "rendimento_novo": NOVO, "preco_kg": PRECO, "caixas_recebido_descarte": caixas, "plano": plano},
          open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print(f"rendimento ALIV hoje {VELHO:.5f} | novo (4 caixas) {NOVO:.5f} | limpo R$/kg {PRECO/VELHO:.2f} -> {PRECO/NOVO:.2f}")
for p in sorted(plano, key=lambda x: (x["categoria"], x["produto"])):
    print(f"{p['produto'][:44]:44s} {p['quantity']:7.4f} limpo {p['limpo_exato_g']:8.3f} g -> {p['nova_quantity']:7.4f} | ficha {p['custo_ficha']:6.2f} -> {p['custo_ficha_novo']:6.2f}")
print("soma do aumento de custo (1 de cada):", round(sum(p["custo_ficha_novo"]-p["custo_ficha"] for p in plano), 2))
