# Monitor de Operação da Tili (fase 1)

Script `monitor.py` que lê o ALIV Hub (Tili Pizzaria, loja 150, e Tili Sushi & Poke, loja 155) e imprime o relatório da operação. Ele **não usa navegador** e **só lê dados**: nunca altera nada no ALIV. A Rotina do Claude Code roda o script de hora em hora e manda o resultado por e-mail.

Ele usa só a biblioteca padrão do Python 3.9 ou mais novo, então não precisa instalar nada.

## Como rodar

```bash
export ALIV_USER='seu-usuario'      # e-mail/usuário do ALIV
export ALIV_PASS='sua-senha'
export ALIV_USER_SUSHI='usuario-do-sushi'   # opcional: inclui a Tili Sushi (loja 155)
export ALIV_PASS_SUSHI='senha-do-sushi'
python3 monitor/monitor.py
```

- A 1ª linha da saída é o **assunto** do e-mail (`Tili Pizzaria — HH:27 — N pedidos / R$ X · Sushi N / R$ Y`). O resto é o corpo.
- A cada rodada ele grava `monitor/snapshots/AAAA-MM-DD.json`. A rodada seguinte usa esse arquivo para calcular a última hora por diferença. Se não houver snapshot de 45 a 90 min atrás, ele calcula pela hora de criação dos pedidos.
- Opções:
  - `--agora 2026-11-06T19:27`: simula um horário (fuso America/Bahia).
  - `--sem-snapshot`: não grava o snapshot.
  - `--sem-semana`: pula a comparação com a semana passada.
  - `--whatsapp`: envia o relatório pelo WhatsApp (ver abaixo).
  - `--raw PASTA`: salva as respostas cruas do ALIV, para conferir os campos. Não faça commit dessa pasta.
- Códigos de saída: `0` ok, `1` erro no ALIV (o motivo sai no relatório), `2` faltam as variáveis.

## Credenciais (ALIV_USER e ALIV_PASS)

**Nunca coloque usuário ou senha no código nem no repositório.** O script só lê as duas variáveis de ambiente.

O ideal é criar no ALIV um usuário próprio para o monitor, com acesso só de leitura e **sem 2FA**. Se a conta pedir código de 2FA, o script para e avisa, porque não tem como digitar o código sozinho.

No Claude Code na nuvem:
1. Abra o menu do ambiente na barra de título da sessão e escolha o ambiente **Contapecas** → **Edit**.
2. Em **Environment variables**, adicione:
   ```
   ALIV_USER=...
   ALIV_PASS=...
   ALIV_USER_SUSHI=...
   ALIV_PASS_SUSHI=...
   ```
3. Confira que **Network** permite o host `app.alivhub.com.br`. O ambiente Contapecas já vem com ele.
4. Salve. As próximas sessões e a Rotina já recebem as variáveis.

## Envio por WhatsApp (opção `--whatsapp`)

- Usa `POST /admin/api/chat/send` (campos `phone` e `message`), o mesmo do chat de atendimento do ALIV. A mensagem sai pelo **WhatsApp principal da loja** (canal Evolution `aliv_store_150_…`), não por um número separado.
- Envia só para o número da variável `WHATSAPP_EMERSON` (com DDI e DDD, ex.: `5573…`). Sem a variável, ou se o ALIV não confirmar (`success: true`), o script sai com **código 3** e a Rotina manda o e-mail.
- A conversa aparece no chat de atendimento da loja. Se você responder, o atendente de IA pode responder também.
- O relatório semanal dos motoboys **não** usa WhatsApp: ele gera PDFs e grava na pasta do Drive.

## Rotina

Ativa: **Monitor da Tili (hora em hora)**, cron `CRON_TZ=America/Bahia 0 0,18-23 * * *` (18:00 a 00:00), sessão nova a cada disparo, conector Gmail. O script fica no branch `claude/zealous-bohr-ufzjww` até o merge na `main`; a Rotina usa esse branch e grava os snapshots nele.

Códigos de saída: `0` ok (WhatsApp enviado, se pedido) · `1` erro no ALIV · `2` faltam ALIV_USER/ALIV_PASS · `3` relatório ok, WhatsApp não enviado.

## Tili Sushi (loja 155)

- Login separado com `ALIV_USER_SUSHI` / `ALIV_PASS_SUSHI`. Sem essas variáveis, o relatório sai só com a Pizzaria. Se o ALIV do Sushi der erro, o bloco do Sushi mostra "indisponível — motivo" e a Pizzaria sai normal (código 0).
- Bloco **TILI SUSHI & POKE**: pedidos, vendas, peças vendidas (+ temakis), última hora, ticket, cancelados e canais. Também entra na comparação com a semana passada e no assunto do e-mail.
- Mesmas regras de turno e status da Pizzaria.
- **Canais:** Salão = `pdv` não delivery · App = `app` (delivery e retirada) · iFood = `ifood` · PDV delivery = `pdv` com entrega (só aparece se houver).
- **Peças vendidas** (por item do pedido × quantidade, pelo nome do produto):
  - `PEÇA SUSHI`, `Sashimi`, itens "(unidade)" = 1 peça.
  - Item da categoria "Promoção do Dia" com preço até R$ 5 = 1 peça. Em 30/10 a peça de R$ 2,99 foi lançada como "Sunomono".
  - "( 10 Un )", "15 Peças", "(48 peças)" = o número do nome (vale o último).
  - Hot/Ura/Hosso sem número no nome (vem assim do iFood) = 10 peças.
  - Temaki conta à parte ("+ N temakis"). Bebidas, poke, yakisoba, ceviche e sobremesas = 0.
- Tempos, alertas de colunas, motoboys, descontos e lucro continuam só da Pizzaria.
- O snapshot guarda `sushi_pedidos`, `sushi_vendas` e `sushi_pecas` em cada rodada, para a última hora do Sushi.

## Regras usadas (resumo)

- **Turno:** pedidos criados a partir das 16:00, mais os agendados do dia. Pedidos de 00:00 a 04:00 contam no turno anterior. `AGUARDANDO_PAGAMENTO` (Pix pendente) e `CANCELADO (...)` ficam fora das vendas. O pedido é identificado pelo `id`, não pelo código M-/APP-.
- **Alertas:**
  - Em rota há mais de 45 min.
  - Pronto p/ despacho sem motoboy.
  - Parado há mais de 15 min nas colunas de espera (Esperando preparo, Finalização, Expedição, Pronto p/ despacho, A finalizar).
- **Metas:** ticket de R$ 75 · preparo até 20 min · entrega até 45 min · cancelamento até 2% · custo iFood até 25%.
- **Custo iFood:** (comissão 12,8% + desconto bancado pela loja) ÷ receita iFood.
- **Lucro estimado (ESTIMATIVA):**
  - Receita = pago + desconto do iFood − taxa de serviço.
  - Descontos: CMV 26,5% · comissão iFood 12,8% sobre (itens + entrega − desconto da loja) · imposto 9,45% · cartão 1,6% só nos canais próprios.
  - Motoboys: diária de R$ 100 (seg a sex) ou R$ 120 (sáb e dom) por motoboy online, proporcional ao turno 16:30–23:45, mais R$ 2 por entrega delivery da Pizzaria finalizada.
- **Motoboys:** conta só quem está `Online` com `start_ts` de hoje. O snapshot guarda `max_motoboys_online` do dia; se na rodada ninguém estiver online, o custo usa esse máximo. As entregas do `drivers-live` incluem o Sushi e aparecem só como informação.
- **Semana passada:** mesmo dia da semana anterior, até o mesmo horário.

Todos os parâmetros ficam no topo do `monitor.py`.

## Endpoints consultados

| Uso | Endpoint |
|---|---|
| Login (form `username`/`password`, cookie de sessão) | `POST /login-unified` |
| Pedidos do dia (20 por página, até vir vazia) | `GET /admin/api/orders/audit?start_date=&end_date=&page=` |
| Detalhe do pedido | `GET /admin/api/orders/{id}` |
| Tempos e colunas | `GET /admin/api/operation-monitor/data?range_kind=today` e `range_kind=custom&start=&end=` |
| Motoboys | `GET /admin/api/finance/drivers-live` |

Se a sessão expirar (401 "Sessão expirada"), o script faz login de novo sozinho.

## Status da validação

- Conferido em 06/11/2026:
  - O login é por formulário, sem captcha.
  - O ALIV tem 2FA opcional por conta: a resposta traz `twofa_required`.
  - Com senha errada a resposta é 401 "Credenciais inválidas". Sem sessão, as APIs devolvem 401 "Sessão expirada".
- **1ª execução real em 07/11/2026 (01:23)**, com a conta do ambiente. Campos confirmados e correções feitas:
  - `discount_origins` é uma lista de `{kind, label, value}`, com `kind` = `plataforma`, `loja` ou `manual`. Antes o script não lia `kind` e jogava tudo em "loja".
  - `operation-monitor`: `range_kind=today` é o dia do calendário (desde 00:00), então vinha vazio de madrugada. Agora usa `custom` do início do turno (16:00) até agora. `start`/`end` são em horário local.
  - Cards das colunas: `code`, `elapsed_min`, `driver`, `neighborhood`. As colunas vêm por `label` ("Esperando preparo", "Preparo", "Finalização", "Pronto p/ despacho", "Em rota", "A finalizar", "Finalizado").
  - `orders/audit`: lista traz `created_at` ("06/11/2026 23:42"), `wabiz_id`, `total`; o detalhe traz `total_value`, `subtotal`, `delivery_fee`, `service_fee`, `platform_slug`, `branch_label`, `created_at_fmt` ("30/10/2026 às 17:52"). O `has_more` **não é confiável** (vem `false` antes da última página), por isso a paginação segue até a página vazia.
  - `drivers-live`: depois do turno todos ficam `Offline` (`start_ts` = 9999999999). O snapshot agora guarda os motoboys online de cada rodada, e o custo usa o máximo do turno.
  - Os detalhes dos pedidos são buscados em paralelo (6 por vez): a rodada caiu de ~6 min para ~1,5 min.
- **Sushi testado no ALIV real em 07/11/2026 (02:13)**, turno 06/11: 224 pedidos · R$ 14.565,10 · 2.810 peças + 164 temakis (Salão 157 · App 51 · iFood 14 · PDV delivery 2). A conta do Sushi usa os mesmos endpoints; os itens vêm em `items_json` (`title`, `quantity`, `price`, `category_name`). A rodada completa (Pizzaria + Sushi + semana passada) levou ~2,5 min.

---

# Diaristas — relatório diário dos motoboys (`diaristas.py`)

Gera o pagamento do dia dos **motoboys diaristas**: PDF A4 completo e uma lista em texto para o WhatsApp. Só lê o ALIV. Reaproveita o login e o envio por WhatsApp do `monitor.py`.

## Como rodar

```bash
python3 monitor/diaristas.py --data 2026-11-06 --dry-run   # gera e mostra, não envia
python3 monitor/diaristas.py                                # rodada normal: dia que acabou de fechar, envia
```

- `--data AAAA-MM-DD`: dia operacional. Sem ela, antes das 10:00 vale o dia anterior; por isso a rodada das 00:15, ou uma atrasada, sai sempre para o dia certo.
- `--dry-run`: gera o PDF e imprime a lista, sem enviar nada.
- `--agora AAAA-MM-DDTHH:MM` simula a hora da rodada. `--raw PASTA` salva as respostas cruas do ALIV.
- Variáveis: `ALIV_USER`, `ALIV_PASS`, `WHATSAPP_EMERSON`, `WHATSAPP_ADMIN`.
- Saída: `monitor/diaristas/AAAA-MM-DD/diaristas_DD-MM.pdf`. O commit fica com a Rotina.
- PDF no mesmo layout do relatório semanal dos prestadores: o script monta um HTML e imprime com o `chrome-headless-shell` de `/opt/pw-browsers`, que já vem no ambiente. O Chrome completo (`/usr/bin/google-chrome`, da variável `CHROME_PATH`) trava no modo headless, por isso o script não usa ele. Para usar outro, defina `DIARISTAS_CHROME`.
- Logo: `monitor/assets/logo_tili.png`. Para trocar, basta substituir o arquivo.
- Códigos de saída: `0` ok, ou dry-run, ou dia sem diarista com aviso enviado · `1` erro de login ou do ALIV · `2` faltam variáveis · `3` relatório gerado, mas o WhatsApp não aceitou a lista ou o PDF. Nesse caso a Rotina manda por e-mail.

## Regras

- **Dia operacional D:** turnos iniciados entre 10:00 de D e 10:00 de D+1, ou até a hora da rodada se for antes. Pedidos criados entre 10:00 de D e 06:00 de D+1. A entrega feita depois da meia-noite conta no dia D.
- **Quem entra:** motoboy sem "CNPJ" no nome. Os prestadores com CNPJ ficam no relatório semanal. **Thiago Camilo** e **Josué Ruas**, que são logins de gerente, nunca entram.
- **Diária:** R$ 100 de segunda a sexta e R$ 120 no sábado e no domingo, pelo dia operacional.
  - Se o ALIV gravou R$ 100 no fim de semana, o script corrige para R$ 120 e marca **CORRIGIDO**.
  - Sem diária gravada, usa a padrão e avisa.
- **Taxa por entrega:** R$ 2,00 na Pizzaria e R$ 2,00 no Sushi.
- **Total a pagar:** é o fechamento do turno no ALIV, mais a diferença da diária quando ela foi corrigida. Sem fechamento, vale o cálculo (diária + entregas × R$ 2).
  - Se o fechamento for diferente do cálculo, os dois aparecem e o motoboy é marcado com **DIVERGÊNCIA**.
- **Pizzaria ou Sushi:** o pedido é da Pizzaria quando está nas entregas do turno (`payouts`) ou quando `GET /admin/api/orders/{id}` responde no login da Pizzaria. Quando esse GET dá 404, o pedido é do Sushi.
- **Dia sem diarista:** não gera PDF. Só manda o aviso.

## Envio

- O envio usa `POST /admin/api/chat/send`, o mesmo do monitor. Vai para `WHATSAPP_EMERSON` e `WHATSAPP_ADMIN`: primeiro a lista e depois o PDF.
- O PDF vai no campo `file` (multipart), o mesmo que o chat do ALIV usa para anexos.
- Se o ALIV não confirmar (`success: true`), o script sai com código 3. Aí a Rotina manda a lista e o PDF pelo Gmail para emmersonarcanjo@gmail.com.

## Endpoints e campos reais (conferido em 07/11/2026)

| Uso | Endpoint | Campos usados |
|---|---|---|
| Motoboys (todos, status) | `GET /admin/api/finance/drivers-live` | lista de `{id, name, status ("Online"/"Offline"), start_ts (unix s; 9999999999 = offline), deliveries (inclui Sushi), final_pay}` |
| Quem trabalhou no dia | `GET /admin/api/finance/drivers-report?start=D&end=D+1&tipo=entrega,financeiro&date_basis=delivery` | `rows[]: {id, name, entregas, soma_taxas, dias_trabalhados}`. **`end` é exclusivo**: `start=end=D` volta vazio. Os números incluem as entregas do Sushi |
| Pedidos entregues | `GET /admin/api/finance/drivers-report/orders?driver_id=&start=&end=&date_basis=delivery` | `orders[]: {id, wabiz_id, date ("06/11/2026 23:53" = criação), status, taxa}`. Pizzaria e Sushi juntos |
| Turno e fechamento | `GET /admin/api/finance/driver/{id}/payouts?start=D&end=D+1` | `groups[]: {session_start "06/11 18:07", session_end "07/11 00:37", total_paid, total_fees, payments[]{method ("FOLHA"…), value, desc}, deliveries[]{order_id, wabiz_id, fee}}`. As `deliveries` são **só as da Pizzaria** |
| Diária gravada | `GET /admin/api/finance/driver/{id}/history-audit?start=D&end=D+1` | `history[]: {type "DIÁRIA/VALE", desc "Diária/Taxa Extra Manual", value, sort_date (ISO UTC), is_credit}`. O fechamento aparece como `type "BONUS"` |
| Código / loja do pedido | `GET /admin/api/orders/{id}` | `wabiz_id`, `branch_label`. Dá 404 quando o pedido é da outra loja |

- O login do Sushi (`ALIV_USER_SUSHI`) devolve o mesmo `drivers-report`. Por isso o script usa só o login da Pizzaria.
- O fechamento do ALIV ("Fechamento do turno adiado para a folha — R$ X (diária/entregas do dia)") já soma a diária e todas as entregas, das duas lojas.
- A diária manual aparece no histórico na hora em que o turno fecha.
- Conferido com o ALIV real:
  - 06/11 (sexta): 1 diarista, Crisley, com 10 entregas na Pizzaria + 6 no Sushi, diária de R$ 100 e fechamento de R$ 132. Bateu.
  - 01/11 (domingo): 5 diaristas, todos com diária de R$ 120. Os 5 bateram com o fechamento.

## Rotina das 00:15

- Cron `CRON_TZ=America/Bahia 15 0 * * *`, sessão nova a cada disparo, conector Gmail.
- Se a Rotina rodar antes de o ALIV fechar o turno, o motoboy sai com "turno ainda aberto" e o total vem do cálculo.
