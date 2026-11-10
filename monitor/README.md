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
  - `--whatsapp`: envia só o painel em imagem pelo WhatsApp (o texto vai apenas se o painel falhar).
  - `--painel ARQ.png`: salva os painéis em `ARQ_ipad.png`, `ARQ_iphone_1.png` e `ARQ_iphone_2.png` (para conferir sem enviar).
  - `--sem-painel`: não gera nem envia o painel.
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
- No WhatsApp vai **só o painel em imagem** (`painel.py`, pedido do Emerson em 08/11/2026), em **dois formatos**, um depois do outro: **iPad** (2880 px de largura, 3 colunas, iPad deitado) e **iPhone 14 Pro Max** em 2 imagens do tamanho exato da tela (1290×2796): 1/2 com alertas, vendas, canais e ticket; 2/2 com tempos, motoboys, descontos, lucro e semana passada. Os dois têm fundo escuro, vermelho e dourado da Tili, com alertas no topo, vendas e última hora por loja, canais, ticket, cancelamento, tempos, motoboys, descontos, lucro estimado e comparação com a semana passada. É desenhado em HTML e fotografado pelo Chromium headless. Se o painel falhar (não gerado ou não aceito), vai o relatório em texto no lugar; o motivo aparece no log como `PAINEL:` ou `WHATSAPP: painel não enviado`. Código `3` só se nada for enviado.
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
- Papel timbrado:
  - A logo aparece no cabeçalho e como marca d'água no centro de cada página.
  - No rodapé há uma faixa vermelha, dourada e preta com a razão social, o CNPJ, a cidade e o WhatsApp (73) 99917-9941.
- Logo (Tili Pizza · Burguer · Sushi): `monitor/assets/logo_tili.png`. Para trocar, basta substituir o arquivo.
- Códigos de saída: `0` ok, ou dry-run, ou dia sem diarista com aviso enviado · `1` erro de login ou do ALIV · `2` faltam variáveis · `3` relatório gerado, mas o WhatsApp não aceitou a lista ou o PDF. Nesse caso a Rotina manda por e-mail.

## Regras (combinadas em 07/11/2026)

- **Dia operacional D:** turnos iniciados entre 10:00 de D e 10:00 de D+1. Os pedidos contam de 10:00 de D até **08:00 de D+1**, o que na prática é o turno das 16h às 08h. A entrega feita depois da meia-noite conta no dia D. O ALIV aceita hora na consulta, mas ignora, então o corte pela hora exata é feito no script.
- **Quem entra:** motoboy sem "CNPJ" no nome. Os prestadores com CNPJ ficam no relatório semanal. **Thiago Camilo** e **Josué Ruas**, que são logins de gerente, nunca entram.
- **Diária:** vale a que foi **gravada no ALIV**, como está. Exemplo: R$ 50 combinado com quem chegou atrasado. Só quando a diária vem **zerada ou não gravada** e o motoboy fez entregas, o script usa a padrão (R$ 100 de segunda a sexta, R$ 120 no sábado e no domingo).
- **Entrega:** sempre **R$ 2,00**, da Pizzaria ou do Sushi, seja qual for a taxa gravada. A taxa variável é do cliente. As exceções de bairro distante são pagas na hora e não entram aqui.
- **Total a pagar:** diária + R$ 2 × entregas. O fechamento do ALIV serve só para conferência.
- **Página do motoboy:** não mostra correção, divergência nem aviso. Isso aparece só na mensagem e no terminal.
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

## Rotina das 00:45

- Ativa: **Tili — Diaristas (00:45)**, cron `CRON_TZ=America/Bahia 45 0 * * *`, sessão nova a cada disparo.
- O horário passou de 00:15 para 00:45 porque, em 06/11, o ALIV só fechou o turno às 00:37. Às 00:45 o total já vem do fechamento.
- Se o turno ainda estiver aberto, o motoboy sai com "turno ainda aberto" e o total vem do cálculo.
- A Rotina usa a `main` se o `diaristas.py` já estiver lá. Se não estiver, usa o branch `claude/serene-dirac-9hyjzd`. O PDF do dia é gravado nesse mesmo branch.
- O e-mail de reserva (códigos 1, 2 e 3) precisa do conector **Gmail** na Rotina.

---

# Prestadores MEI — relatório semanal (`prestadores.py`)

Gera o pagamento semanal dos **prestadores MEI**, os motoboys com CNPJ no nome. A semana vai de segunda a domingo. Só lê o ALIV. Reaproveita do `diaristas.py` o login, o WhatsApp, o layout com papel timbrado e o gerador de PDF.

## Como rodar

```bash
python3 monitor/prestadores.py --semana 2026-10-27 --dry-run   # semana que contém a data; gera e mostra, não envia
python3 monitor/prestadores.py                                  # rodada normal: semana seg–dom que fechou, envia
```

- `--semana AAAA-MM-DD`: qualquer data da semana. O script usa a segunda e o domingo dessa semana. Sem a opção, pega a última semana completa.
- `--dry-run`: gera os PDFs e a mensagem, sem enviar nada.
- `--sem-espera`: não espera os 10 minutos quando o turno de domingo estiver aberto.
- `--raw PASTA`: salva as respostas cruas do ALIV.
- Saída:
  - `monitor/prestadores/AAAA-MM-DD/Prestadores_semana_DD-MM_a_DD-MM_COMPLETO.pdf`, com resumo, correções e alertas e uma página por prestador.
  - `monitor/prestadores/AAAA-MM-DD/individuais/<Nome>_DD-MM_a_DD-MM.pdf`, um PDF por prestador. O commit fica com a Rotina.
- Chave Pix: por padrão é o CNPJ. As exceções ficam em `monitor/assets/pix_prestadores.json` (`{"CNPJ só dígitos": "chave"}`). Hoje só o Gustavo, que recebe no e-mail.
- Códigos de saída: `0` ok · `1` erro de login ou do ALIV · `2` faltam variáveis · `3` WhatsApp falhou. Nesse caso a Rotina manda por e-mail.

## Regras (combinadas em 07/11/2026)

- **Quem entra:** motoboy com "CNPJ" no nome. Thiago Camilo e Josué Ruas nunca entram.
- **Cadastro duplicado:** quando o mesmo CNPJ ou o mesmo nome aparece em mais de um id, cada cadastro entra separado e gera alerta.
- **Dia operacional:** das **08:00 de D às 08:00 de D+1**, o que na prática é o turno das 16h às 08h. O que passa da meia-noite conta no dia D.
  - O turno conta pelo horário de início.
  - A entrega da Pizzaria conta no turno em que o ALIV a registrou, inclusive a da madrugada do domingo anterior, que fica fora da semana.
  - A entrega do Sushi conta pelo horário de criação. Pedido agendado, que vem com hora "00:00", conta pelo dia em que foi entregue.
- **Diária:** vale a que foi **gravada no ALIV**, como está (R$ 50, R$ 80…). Só quando vem **zerada ou não gravada** e o motoboy fez entregas, o script usa a padrão (R$ 100 de segunda a sexta, R$ 120 no sábado e no domingo). Esse é o único caso listado como correção.
- **Entrega:** sempre **R$ 2,00**, da Pizzaria ou do Sushi, seja qual for a taxa gravada (0; 6,99; 7; 30; 40). A taxa variável é do cliente.
- **Sushi:** conta as entregas do Sushi registradas para o motoboy no ALIV (`drivers-report/orders` + 404 no login da Pizzaria). O Sushi não tem motoboy próprio e usa os da Pizzaria.
  - Antes o Sushi saía da diferença do fechamento, mas isso dava erro de R$ 1. Exemplo: Guilherme e Ricardo em 01/11, com uma entrega do Sushi gravada a R$ 7.
- **Total do dia:** diária + R$ 2 × entregas + ajustes manuais lançados no ALIV.
- **PDF completo e PDFs individuais:** só resumo, turnos, códigos e recibo. **Nenhuma correção, divergência ou aviso aparece para o motoboy.**
- **Folha de conferência (uso interno):** fica em `Conferencia_interna_semana_DD-MM_a_DD-MM.pdf`, à parte. Mostra, por prestador, o fechamento do ALIV × o valor pago e o motivo de cada dia diferente: taxa gravada ≠ R$ 2, ou o fechamento pagou Sushi a mais ou a menos do que foi entregue. Também traz os alertas e as correções.
- **Turno de domingo aberto:** o script espera 10 minutos e lê de novo. Se continuar aberto, gera alerta e o dia é pago pelo cálculo.
- **Mensagem final** (WhatsApp para `WHATSAPP_EMERSON` e `WHATSAPP_ADMIN`, com o PDF completo e a folha de conferência): total da semana, valor de cada prestador, correções, alertas (turno aberto, cadastro duplicado, ajuste manual) e quantos turnos ficaram diferentes do ALIV.

## Endpoints (além dos do diaristas)

| Uso | Endpoint | Observação |
|---|---|---|
| Turnos da semana | `GET /admin/api/finance/driver/{id}/payouts?start=SEG&end=DOM+1` | `end` inclui o dia. Os grupos trazem `session_start`/`session_end` ("dd/mm HH:MM"), `total_paid` e `deliveries` (só Pizzaria, `fee`). Às vezes o grupo vem sem `deliveries`, como Adriano em 01/11: por isso as entregas saem de `drivers-report/orders` |
| Diária e ajustes | `GET /admin/api/finance/driver/{id}/history-audit?start=SEG&end=DOM+1` | `type "DIÁRIA/VALE"`: "Diária/Taxa Extra Manual" (gravada no fechamento do turno; a de domingo fica às 00:0x de segunda) ou ajuste manual |
| Pedidos e taxa | `GET /admin/api/finance/drivers-report/orders?driver_id=&start=SEG&end=DOM+2&date_basis=delivery` | `taxa` = taxa gravada (0; 2; 6,99; 7; 40…) |

## Conferência (semana 26/10 a 01/11/2026)

- Total a pagar: **R$ 9.296,99**. O relatório antigo deu R$ 9.286,00. Os fechamentos gravados no ALIV somam R$ 9.378,96.
- 11 dos 17 prestadores bateram com o relatório antigo.
- 16 turnos ficaram diferentes do fechamento do ALIV. Todos estão explicados na folha de conferência:
  - 10 por taxa gravada diferente de R$ 2: R$ 40, R$ 30, R$ 7 (×3), R$ 6,99 (×3) e R$ 0 (×2).
  - 6 porque o fechamento pagou Sushi a mais ou a menos do que o ALIV registra como entregue.

## Rotina de segunda às 10:00

- Cron `CRON_TZ=America/Bahia 0 10 * * 1`, sessão nova a cada disparo, conector Gmail para o e-mail de reserva.

---

# NFC-e — lista do dia e emissão sob comando (`nfce.py`)

Lojas: **Tili Pizzaria (loja 150)**, com `ALIV_USER` / `ALIV_PASS`, e **Tili Sushi (loja 155)**, com `ALIV_USER_SUSHI` / `ALIV_PASS_SUSHI`. Reaproveita o cliente e o WhatsApp do `monitor.py`. Lista, arquivo, mensagem e emissão são **separados por loja**. **Nunca emite sozinho**: a Rotina das 23:50 só roda `listar`; `emitir` só roda numa sessão, quando o Emerson responde "emite".

## Como rodar

```bash
python3 monitor/nfce.py listar --dry-run                                 # as duas lojas, hoje; não grava nem envia
python3 monitor/nfce.py listar                                           # grava os arquivos e manda uma lista por loja
python3 monitor/nfce.py listar --loja sushi --data 2026-11-08 --dry-run  # só uma loja
python3 monitor/nfce.py emitir --data 2026-11-08 --loja sushi --dry-run  # mostra o que emitiria, sem nenhum POST
python3 monitor/nfce.py emitir --data 2026-11-08 --loja pizzaria         # emite de verdade (só após "emite")
```

- `listar --data AAAA-MM-DD`: sem a opção, vale hoje (antes das 04:00, ontem). `--loja pizzaria|150|sushi|155`: sem a opção, lista as duas. Um erro numa loja não impede a outra.
- `emitir --data` e `--loja` são obrigatórios: cada emissão é de uma loja só. `--limite N` (máx. 200 por execução).
- Arquivos: Pizzaria em `monitor/nfce/AAAA-MM-DD.json`, Sushi em `monitor/nfce/sushi/AAAA-MM-DD.json`.
- A saída tem um bloco por loja, separado por uma linha de `=`. A 1ª linha de cada bloco é o assunto (`NFC-e Tili — …` para a Pizzaria e `NFC-e Tili Sushi — …` para o Sushi).
- Cada lista termina com "Responda *emite pizzaria*" ou "*emite sushi*" (ou *emite* para as duas lojas).
- Variáveis: `ALIV_USER`, `ALIV_PASS`, `ALIV_USER_SUSHI`, `ALIV_PASS_SUSHI`, `WHATSAPP_EMERSON`. Cada lista sai pelo WhatsApp da própria loja.
- Códigos de saída: `0` ok · `1` erro no ALIV · `2` faltam variáveis · `3` WhatsApp não aceitou (a Rotina manda por e-mail) · `4` emissão parada por `LIMIT_REACHED`. Com as duas lojas, vale o mais grave (1 > 2 > 3).

## Quem entra na lista

- Pedidos **criados no dia**, status `CONCLUIDO` ou `ENTREGUE`, `fiscal_status` `PENDENTE` ou vazio. Cancelados e pedidos ainda abertos não entram (a lista mostra quantos ficaram de fora). Outro `fiscal_status` vai para ATENÇÃO.
- A loja sai do detalhe `GET /admin/api/orders/{id}`: `platform_slug`, `payment_metadata.ifood_merchant_id` e `payment_method` (formato `"Forma: valor | Forma: valor"`).

| Loja | EMITIR | NÃO EMITIR |
|---|---|---|
| App próprio, PDV, balcão | Pix (inclusive Pix Online **pago**), crédito, débito, vales (Alelo, Ticket, VR, Pluxee…) | dinheiro |
| iFood Tili Pizzaria (`21f5f70c…`) | só a maquininha do motoboy: cartão, Pix, vale | online iFood, dinheiro |
| iFood Tili Burguer (`34e58883…`) | tudo menos dinheiro, inclusive online | dinheiro |
| iFood Tili Pizzaria 2.0 (`c1577426…`) | tudo menos dinheiro, inclusive online | dinheiro |

| **Tili Sushi (loja 155)**: app, PDV, balcão e iFood | tudo menos dinheiro: Pix, Pix Online pago, cartão, vale e iFood online | dinheiro |

- Sushi: só entram pedidos com status `CONCLUIDO`. Na Pizzaria, `CONCLUIDO` ou `ENTREGUE`.
- Misto dinheiro + forma permitida: **EMITE**. Dinheiro puro: nunca.
- **ATENÇÃO** (não emite, decidir na mão): Fiado, Carteira, Conta Func., saldo usado; Pix Online não pago; pagamento "Em Aberto"; forma não reconhecida; iFood de merchant desconhecido; iFood Tili Pizzaria misto online + maquininha.

## Emissão

- Emite **só os pedidos EMITIR da lista salva** em `monitor/nfce/AAAA-MM-DD.json` (antes, `git pull` para pegar o arquivo da Rotina). Cada um é reconferido ao vivo; o que mudou de grupo, já tem nota ou foi cancelado sai da fila. Pedido novo que não estava na lista aprovada **não** é emitido, só avisado. Sem lista salva, usa a lista gerada na hora e avisa.
- `POST /admin/api/orders/{id}/emit-fiscal` (FormData `customer_document`): primeiro `""` (CPF do pedido); se a SEFAZ recusar o CPF/destinatário, de novo com `" "` (sem CPF). Confirma em `GET /admin/api/orders/{id}/check-fiscal`. Uma por vez, máximo 200.
- `LIMIT_REACHED`: para tudo e avisa (código 4). `MISSING_PAYMENT` ou rejeição SEFAZ: registra o motivo exato e segue. "Ausência de troco…": ATENÇÃO (bug do ALIV com borda/adicional como desconto negativo), não insiste. Timeout no POST: não reenvia, consulta o status e, se não confirmar, vai para ATENÇÃO.
- Conferência de CNPJ: posições 7 a 20 da chave de 44 dígitos, comparadas **em memória** com `/admin/api/stores/{loja}/fiscal-profiles` (perfil ativo cuja regra iFood bate com o merchant — hoje só o 2.0 da Pizzaria) e `fiscal-config` da loja (CNPJ principal). O Sushi não tem perfis extras: tudo deve sair no CNPJ principal da loja 155. O relatório mostra só o nome do perfil.
- **Nada sensível é gravado**: o JSON tem id, código, hora, valor, forma de pagamento, loja, grupo e motivo. Sem CPF, nome de cliente, CNPJ, chave, token, CSC ou senha.

## Relatórios

- Lista (23:50): assunto `NFC-e Tili — DD/MM/AAAA — N a emitir / R$ X`, EMITIR por loja (qtd e valor), NÃO EMITIR por regra, ATENÇÃO pedido a pedido e "Responda *emite* para emitir".
- Resultado da emissão: autorizadas por CNPJ/perfil, rejeitadas com pedido, hora, valor, pagamento e motivo, maior motivo de erro, ATENÇÃO e avisos. Vai pro WhatsApp e fica em `emissoes[]` no JSON do dia (commit na sessão).

## Conferido em 07/11/2026 (dia 06/11, ALIV real)

- 197 pedidos: 134 EMITIR (R$ 10.234,41), 52 NÃO EMITIR (10 dinheiro, 42 online iFood Tili Pizzaria), 1 ATENÇÃO (Conta Func.), 10 cancelados.
- `emitir --dry-run`: 120 notas no CNPJ principal e 14 no perfil Tili Pizzaria 2.0. Nenhum POST feito.

## Conferido em 09/11/2026 (dia 08/11, ALIV real)

- Sushi: 179 pedidos. 159 já tinham nota (o ALIV do Sushi emite a maioria sozinho). 1 EMITIR (iFood, cartão, R$ 173,39). 19 NÃO EMITIR (dinheiro). 0 ATENÇÃO.
- Pizzaria: 0 EMITIR (201 já com nota), 77 NÃO EMITIR, 1 ATENÇÃO (Conta Func.).
- `emitir --loja sushi --dry-run`: 1 nota no CNPJ principal, nenhum POST. Conferência com as 16 chaves reais já autorizadas do Sushi nessa página: todas no CNPJ principal da loja 155.

## Rotinas

- **Tili — NFC-e lista do dia anterior (02:00)**: cron `CRON_TZ=America/Bahia 0 2 * * *`, sessão nova a cada disparo. Roda `listar --data <ontem>`. No dia 01 não faz nada, porque o último dia do mês já foi listado às 23:50.
- **Tili — NFC-e último dia do mês (23:50)**: cron `CRON_TZ=America/Bahia 50 23 28-31 * *`. Só age quando amanhã é dia 01. Roda `listar --data <hoje>`, para a emissão sair antes da virada do mês. Pedidos criados depois das 23:50 desse dia ficam fora da lista.
- As duas só rodam `listar`, nunca `emitir`. O e-mail de reserva (códigos 1, 2 e 3) precisa do conector **Gmail** nas Rotinas.

## Despesas pelo WhatsApp da loja (`despesas.py`)

Lê as despesas que a equipe manda **no privado do número da loja** (73) 9917-9941 e baixa as fotos. **Só leitura**: não envia mensagem, não marca como atendido e não mexe na IA.

**Grupo não funciona.** Testado em 07/11/2026: o grupo "Tili — Despesas" não aparece no chat do ALIV, que só guarda conversas individuais.

Como a equipe manda:
- Foto do comprovante com a legenda `DESPESA gás 120,50`, ou
- Texto `DESPESA limpeza 85,00` e as fotos logo em seguida (até 10 min, sem legenda).

```bash
export DESPESAS_REMETENTES='5573XXXXXXXXX=Nome,5573YYYYYYYYY=Outro'   # quem manda despesa; o nome aparece no relatório
python3 monitor/despesas.py              # últimas 26h; grava monitor/despesas/AAAA-MM-DD.json
```

- Números aceitos com ou sem DDI e com ou sem o 9 (o ALIV guarda sem o 9). Lê as conversas dos `DESPESAS_REMETENTES` e as 25 conversas mais recentes do chat. O ALIV só lista 25 conversas, por isso cadastre os remetentes.
- As fotos vão para `monitor/despesas/fotos/AAAA-MM-DD/`, que fica fora do git. A Rotina deve subir essas fotos para o Drive.
- O JSON do dia guarda: data, hora, remetente, os 4 últimos dígitos do telefone, texto, descrição, valor (1º valor da legenda), fotos e total. Não guarda o telefone completo.
- **O ALIV apaga a mídia em 24h.** Rode pelo menos 1 vez por dia; de hora em hora é melhor.
- Opções: `--horas N`, `--sem-baixar`, `--sem-gravar`, `--fotos PASTA`, `--agora AAAA-MM-DDTHH:MM`.
- Códigos de saída: `0` ok · `1` erro no ALIV · `2` faltam ALIV_USER/ALIV_PASS · `3` alguma foto não baixou.
- Cuidado: a IA de atendimento pode responder a quem manda a despesa. Desligue a IA na conversa desses números, no chat do ALIV.
- As fotos ficam em `objectstorage.sa-vinhedo-1.oraclecloud.com`. Esse servidor precisa estar liberado na rede do ambiente da Rotina.

### Lançamento no ALIV: conta paga + estoque (`despesas_lancar.py`)

- Usa a entrada de nota manual do ALIV (tela "Conferência da Nota"): `POST /admin/inventory/process-invoice-items-financial`. Numa chamada só, cria a conta **paga** (`payment_origin=none`, sem mexer em caixa ou banco) e dá **entrada no estoque com custo**, o que atualiza o custo médio e as fichas técnicas.
- **Pizzaria ou Sushi:** se a legenda tiver "SUSHI", vai para o Sushi (loja 155, `ALIV_USER_SUSHI`). Senão, vai para a Pizzaria.
- **Despesa só em texto** (`DESPESA coentro 5 un 10,00`) é lançada do mesmo jeito, com o fornecedor "Sem nota (WhatsApp)".
- **Tabela de-para** (`monitor/despesas/depara.json`): o item só entra no estoque se o nome dele no cupom estiver ligado a um insumo. O item sem ligação entra **só como despesa** e vai para o WhatsApp com sugestões. O script **nunca cria insumo novo**.
- Para aprovar uma ligação, o Emerson responde no WhatsApp da loja `INSUMO coentro = 6788`, ou `INSUMO sushi coentro = ID`. O número opcional no fim é o **multiplicador**: qtd do cupom × fator = qtd que entra no estoque (ex.: `INSUMO morango 1kg = 6564 1000` se o estoque é em gramas). A rotina aplica essas respostas com `--ler-insumos`.
- Também dá para aprovar pelo terminal: `python3 monitor/despesas_lancar.py --depara pizzaria "COENTRO" 6788 [fator]` · ver candidatos: `--sugerir pizzaria coentro`.
- Proteções: confere duplicata nas contas da loja (mesmo valor e dia, mesmo nº de nota ou fornecedor) e respeita o aviso `POSSIBLE_DUPLICATE` do ALIV, sem forçar. A soma dos itens precisa bater com o total. Preço fora do padrão que pede senha de gerente **não** é forçado: volta como erro no WhatsApp.
- Sem `--confirmar`, só mostra o que faria. Códigos de saída: `0` ok · `1` algum erro · `4` WhatsApp não enviado.
- A conta criada fica com a descrição que o ALIV gera para entrada de nota, não no formato `WPP | …` da rotina antiga.

### Rotina "Tili Despesas"

- Roda 2x por dia, às 12:00 e à 00:00 (America/Bahia), numa sessão nova, com o conector Google Drive e o repositório. Usa o branch `claude/focused-babbage-fjiomt`.
- Ordem: `--ler-insumos` → `despesas.py` (coleta e baixa as fotos) → a IA da rotina lê cada foto ou texto e monta a lista de itens → `despesas_lancar.py --confirmar --whatsapp` → sobe as fotos para a pasta **Despesas** do Drive (id `1aX9b7wy-GiHzopynuyQvQOwnYQr6Bxjz`) → commit dos JSON.
- O WhatsApp para o Emerson só sai quando há despesa nova ou problema. Não usa e-mail e não manda foto.
- A IA de atendimento foi pausada (`ai_paused`) nas 4 conversas em 07/11/2026.

## Alerta de limite de consumo (`consumo.py`)

Regra do Emerson (26/10/2026): **R$ 200 por funcionário por ciclo**. O ciclo vai do dia 26 até o dia 25 do mês seguinte. Avisa "perto" a partir de R$ 160 e "estourou" a partir de R$ 200. Motoboys e donos ficam de fora.

Consumo = lançamentos CONSUMO na carteira + pedidos pagos como "Fiado / Carteira" no nome do funcionário. Um pedido que já virou CONSUMO na carteira não é contado de novo.

```bash
python3 monitor/consumo.py                 # só mostra (dry-run)
python3 monitor/consumo.py --whatsapp      # envia para WHATSAPP_EMERSON e WHATSAPP_ADMIN
python3 monitor/consumo.py --hoje 2026-11-20
```

Só manda mensagem se alguém estiver perto ou estourado. Códigos de saída: `0` ok · `1` erro no ALIV · `2` faltam ALIV_USER/ALIV_PASS · `3` WhatsApp falhou.

# Previsão de motoboys do dia (`previsao_motoboys.py`)

Todo dia às 08:00 (Bahia) recomenda quantos motoboys chamar **hoje**, com faixa (ex.: 9 a 10), o porquê em duas linhas, o histórico das últimas 4 semanas (uma linha por dia) e alerta se a semana passada teve entrega acima de 45 min. Só leitura no ALIV; reaproveita login, consultas e envio por WhatsApp do `monitor.py`.

```bash
python3 monitor/previsao_motoboys.py                  # só mostra (não envia)
python3 monitor/previsao_motoboys.py --data 2026-11-15
python3 monitor/previsao_motoboys.py --promo          # considera promoção hoje
python3 monitor/previsao_motoboys.py --painel-ipad i.png --painel-celular c.png   # gera os painéis, sem enviar
python3 monitor/previsao_motoboys.py --whatsapp       # painel iPad para o Emerson; vertical para Josué e Camilo
```

Leva uns 5 minutos (muitas consultas ao ALIV). Códigos de saída: `0` ok · `1` erro no ALIV · `2` faltam ALIV_USER/ALIV_PASS · `3` nenhum WhatsApp enviado. Josué e Camilo: usa `WHATSAPP_JOSUE` / `WHATSAPP_CAMILO` se existirem; senão pega o número do mesmo nome em `DESPESAS_REMETENTES` (a lista das despesas). Destino sem número é pulado com aviso.

**Método** (janela 16:00–00:00 de cada dia):
- Base: mesmo dia da semana nas últimas 4 semanas (pesos 35/25/15/10%) + mesmo dia do mês passado (15%).
- Entregas por hora: audit da Pizzaria (delivery, sem cancelado/Pix pendente) + audit do Sushi (mesmos motoboys).
- Motoboys do dia: drivers-report, 3+ entregas, gerentes (Josué, Camilo) fora. Motoboys por hora: quem levou pedido criado naquela hora (campo motoboy do audit, Pizzaria + Sushi).
- Tempos (Pizzaria, operation-monitor): rua média, vida média e quantas entregas passaram de 45 min (a janela é dividida até isolar cada pedido).
- Pico = hora com mais entregas. Ritmo = entregas do pico ÷ motoboys no pico.
- Dia **estourado** = mais de 10% das entregas acima de 45 min, ou vida média acima de 45.
- **Limite de entregas por saída** (`MAX_POR_SAIDA`): **desligado**. Em 08/11/2026 o Emerson decidiu manter o ritmo real do ALIV, que hoje fica em 3 a 4 entregas por saída, e acompanhar 30 dias. Se for ligado, por exemplo com 2, o ritmo máximo passa a ser 2 × 60 ÷ (2 × rua média + 5 min).
- Capacidade = melhor ritmo de um dia que não estourou **e teve movimento parecido** (pico ≥75% do previsto). Sem dia assim, usa 6,0 entregas/motoboy/h, o ritmo que funcionou em 08/10. Nunca abaixo de 4,0. Ajustado em 09/11: uma segunda fraca (19/10) tinha puxado o ritmo para 2,6 e a recomendação para 18–19. Recomendação = pico previsto ÷ capacidade. Se um dia com pico parecido (±10%) estourou com ritmo acima da capacidade, recomenda pelo menos 1 motoboy a mais que ele teve. Dia que estourou com ritmo baixo = gargalo na cozinha/expedição, não conta.
- Ajustes: feriado nacional/Bahia ou data forte (Mães, Pais, Namorados) +20% · véspera (inclui 24 e 31/12) +15% · promoção +10%. Os dias da base que eram feriado/véspera/promoção são descontados antes da média.
- Promoções e feriados municipais: `monitor/assets/promocoes.json` (`dias_semana`, `datas`, `feriados_extra`). Hoje está vazio — é só pedir ao Claude para incluir.

**Correção (Emerson, 09/11/2026):** se uma previsão enviada estiver errada, a corrigida vai logo em seguida para os mesmos destinatários, com `--whatsapp --correcao "motivo"`. A legenda sai "⚠️ CORREÇÃO … desconsidere o anterior".

**Painéis (pedido do Emerson, 08/11/2026):** no WhatsApp vai só a imagem, com uma legenda curta. O texto só vai se a imagem falhar.
- **Emerson:** recebe as duas, iPad e iPhone. Versão iPad deitado, tela cheia de 2360 × 1640, com 3 colunas e fonte grande (`--painel-ipad`). A versão larga de 2880 px, igual ao painel de vendas, ainda sai com `--painel`, mas não é enviada.
- **Josué e Camilo:** versão celular, 1 coluna e fonte grande, no tamanho de uma tela de iPhone (19,5:9). A imagem sai com 2160 × 4680 px.
- **Chuva:** a recomendação principal fica normal. Uma faixa abaixo mostra o tempo e, se chover, "+2 a 3 motoboys". Fontes: Open-Meteo (modelos ECMWF, GFS e ICON), MET Norway e a previsão oficial do aeroporto de Porto Seguro (TAF SBPS). O tempo de agora vem do boletim do aeroporto (METAR SBPS). Só conta como chuva com 2 fontes de acordo. Os hosts `api.open-meteo.com`, `api.met.no` e `aviationweather.gov` estão liberados no ambiente Contapecas.

# Auditoria do atendimento da IA no WhatsApp (`atendimento_ia.py`)

Todo dia às 03:30 (Bahia) audita as conversas do WhatsApp da **Tili Pizzaria (loja 150)** e da **Tili Sushi & Poke (loja 155)** no turno que fechou: **16:00 de D até 01:00 de D+1**. Só lê o ALIV. Nunca responde cliente, não marca conversa como atendida e não liga/desliga a IA. Reaproveita o login e o envio por WhatsApp do `monitor.py` e a leitura do chat do `despesas.py`.

```bash
python3 monitor/atendimento_ia.py --data 2026-11-07 --sem-gravar   # teste: mostra, não grava, não envia
python3 monitor/atendimento_ia.py --whatsapp                        # rodada normal: turno de ontem
```

- `--loja pizzaria|sushi|todas` (padrão: todas). Cada loja usa o seu login (`ALIV_USER`/`ALIV_PASS` e `ALIV_USER_SUSHI`/`ALIV_PASS_SUSHI`). O WhatsApp sai sempre pelo número da Pizzaria.
- `--painel ARQ.png`: salva os painéis (iPad e iPhone 1/2, por loja) sem enviar. Com `--whatsapp` manda os painéis e depois o texto com os pares.
- Grava `monitor/atendimento/AAAA-MM-DD.md` (Pizzaria) e `AAAA-MM-DD_sushi.md` (Sushi), cada um com o seu `.json` (só números e pares, usado na comparação de 7 dias). **Nenhum nome, telefone ou endereço** de cliente: os trechos passam pela função `anonimiza`.
- `--whatsapp`: manda o resumo curto com os pares propostos só para `WHATSAPP_EMERSON`.
- Códigos de saída: `0` ok · `1` erro no ALIV · `2` faltam variáveis · `3` relatório gravado, WhatsApp não enviado.

## Como acha as conversas

O `chat/contacts` do ALIV só devolve as ~50 conversas mais recentes e não pagina. Por isso o script junta:
1. `GET /admin/api/chat/contacts` (com `include_transactional` e `so_pedido_ia`) e `GET /admin/api/chat/pending-attention`;
2. `GET /admin/api/chat/search?q=5573…`: busca por prefixo do telefone, descendo um dígito quando a busca volta cheia (a busca do ALIV corta em ~20). Fica só quem falou de D em diante. Até 2.000 buscas, 6 em paralelo;
3. telefones dos pedidos do turno (`orders/audit` + detalhe).

Depois lê `GET /admin/api/chat/messages/{phone}?limit=500` de cada um. Conversa = telefone com mensagem do cliente na janela. Números internos (`numeros_internos` da config da IA, `DESPESAS_REMETENTES`, `WHATSAPP_EMERSON`, `WHATSAPP_ADMIN`) ficam de fora.

## Regras

- **Virou pedido:** há pedido do mesmo telefone (últimos 8 dígitos) no turno. "Pela IA" quando a nota tem *Pedido montado pela IA*. iFood fica de fora. Pedido da IA cancelado conta como "cancelado depois de montado". Sem pedido = **abandonada**.
- **Pediu pelo link:** a IA manda o link do cardápio (`alivhub.com.br/app/tilipizzaria`) na saudação. Pedido do App do mesmo telefone **sem** a nota da IA = "pediu pelo link" e conta como convertido, não como abandono. O abandono é separado em "recebeu o link e não pediu" e "sem link". Se o cliente pedir pelo link com outro telefone, o script não consegue ligar os dois.
- **Tempo de resposta:** da 1ª mensagem de cada bloco do cliente até a próxima mensagem da loja (minutos, o ALIV só dá HH:MM). Acima de 5 min = demora.
- **Problemas** (por palavras-chave, conta 1 por conversa): não entendeu · item ou preço errado (inclui "não encontrei no cardápio") · endereço/taxa · demora · pergunta repetida pela IA (frases com "?" 80% iguais) · reclamou/pediu humano · não soube responder (horário, promoção, pagamento, tempo de entrega: sem resposta em 10 min ou "não sei/vou verificar") · cancelado depois de montado.
- **Pares sugeridos:** modelo por tema, no tom das respostas que já estão no campo. Antes de propor, compara com os exemplos atuais; se já há um parecido, o par sai marcado "já existe parecido" e não vai no WhatsApp. Trechos entre colchetes (ex.: promoção do dia) precisam ser completados antes de aprovar.
- Comparação: média dos 7 dias anteriores a partir dos `.json` gravados.

## Campo de treinamento da IA (investigado em 08/11/2026, só leitura)

Mesma tela e mesmos endpoints nas duas lojas (Sushi: `/admin/api/stores/155/ai-config`). Tela: **Configurações da loja → IA → "Ensine o jeito da sua loja (opcional)"**. Campos "Cliente pergunta" e "Resposta ideal (seu tom)". **Limite: 5 exemplos** (em 08/11: Pizzaria 5 de 5, Sushi 3 de 5).

| Ação | Endpoint | Observação |
|---|---|---|
| Listar | `GET /admin/api/stores/150/ai-config` | `few_shot_examples: [{user, assistant}]`, junto com o resto da config da IA |
| Gravar | `POST /admin/api/openai/sync` (multipart) | **Não existe endpoint só para os exemplos.** O POST regrava a config inteira da IA (chave, ligada/desligada, perfil, upsell, horários, números internos, tamanhos e sabores padrão) e **ressincroniza o cardápio**, igual ao botão Salvar da tela. `few_shot_examples` vai como JSON |

### Comando `aprovar` (só com ordem do Emerson na sessão)

```bash
python3 monitor/atendimento_ia.py aprovar --loja pizzaria --data 2026-11-07 --par 1 --no-lugar-de 3   # mostra o antes/depois
python3 monitor/atendimento_ia.py aprovar --data 2026-11-07 --par 1 --no-lugar-de 3 --confirmo # grava
```
- Sem `--confirmo` não grava nada.
- Lê a config atual e reenvia **todos os campos exatamente como estão**, trocando só os exemplos. Depois relê e confere que os exemplos entraram e que nenhum outro campo mudou.
- Recusa se já existir exemplo parecido (75%) ou se a resposta ainda tiver `[colchetes]`. `--pergunta` / `--resposta` trocam o texto antes de gravar.
- Como o campo está cheio, `--no-lugar-de N` diz qual exemplo atual sai.

## Rotina das 03:30

Cron `CRON_TZ=America/Bahia 30 3 * * *`, sessão nova a cada disparo, ambiente Contapecas. Roda `--whatsapp` e faz commit de `monitor/atendimento/`.

# Fechamento semanal (`fechamento_semanal.py`)

Toda **segunda às 09:00** (America/Bahia) fecha a semana que terminou, **segunda a domingo**, com **dia operacional das 16:00 às 04:00** (o turno do monitor). Só lê o ALIV. Reaproveita do `monitor.py` o login das duas lojas, a coleta de pedidos, os cálculos (vendas, ticket, cancelamento, descontos, custo iFood, peças do Sushi, lucro) e o envio por WhatsApp; do `previsao_motoboys.py`, a contagem de entregas acima de 45 min e os feriados; do `painel.py`, o estilo e o Chromium.

## Como rodar

```bash
python3 monitor/fechamento_semanal.py                        # semana passada, imprime e NÃO envia
python3 monitor/fechamento_semanal.py --semana 2026-11-02    # semana (seg–dom) que contém o dia
python3 monitor/fechamento_semanal.py --inicio 2026-10-27    # 7 dias a partir do dia exato (teste)
python3 monitor/fechamento_semanal.py --whatsapp             # envia painel + texto para WHATSAPP_EMERSON
```

- Saídas: texto resumido no terminal, relatório completo em `monitor/semanal/AAAA-MM-DD.md` (data = 1º dia da semana) e painel PNG (`--painel PASTA` para guardar; senão vai para uma pasta temporária). O commit fica com a Rotina.
- Painel: **só iPad, 2360×1640** (resolução nativa do iPad deitado, uma tela, 4 colunas). Emerson pediu sem a versão de celular em 09/11/2026.
- Cache: cada dia fechado vira `monitor/semanal/dias/AAAA-MM-DD.json` (só números e o apelido do motoboy como aparece no pedido, sem dígitos — nunca CPF/CNPJ). Um dia leva ~1–5 min no ALIV; com o cache, a segunda só busca os 7 dias novos. `--sem-cache` refaz tudo.
- Códigos de saída: `0` ok · `1` erro no ALIV · `2` faltam variáveis · `3` WhatsApp não aceitou (a Rotina manda por e-mail).

## O que entra

- **Por loja e consolidado:** pedidos, vendas, ticket, cancelamentos; canais (App, iFood por loja, PDV delivery, Salão); peças do Sushi; desconto da loja, desconto bancado pelo iFood e custo iFood (comissão 12,8% + desconto da loja ÷ receita iFood).
- **Motoboys (Pizzaria + Sushi):** turno = motoboy com entrega finalizada no dia (gerentes fora); custo = diária (R$ 100 seg–sex, R$ 120 sáb–dom) por turno + R$ 2 por entrega, dividido entre as lojas pelas entregas. Custo por entrega e entregas por motoboy.
- **Tempos:** média ponderada de preparo, rua e vida (operation-monitor) e entregas com vida acima de 45 min.
- **Lucro ESTIMADO:** mesma fórmula do monitor (receita − CMV 26,5% − imposto 9,45% − comissão iFood − cartão 1,6% nos próprios − motoboys). Sempre marcado como estimativa.
- **Melhor e pior dia** pelas vendas consolidadas (feriado aparece no nome do dia).
- **Comparações:** semana anterior e mesma semana do mês passado (4 semanas antes, mesmos dias da semana), com variação em % e setas (percentuais em pontos percentuais). Verde = melhorou, vermelho = piorou.
- **Mês até agora:** do dia 1 até o domingo da semana, com projeção simples (média diária × dias do mês).
- **Destaques:** o indicador que mais melhorou e o que mais piorou contra a semana anterior, e uma recomendação por regra (atrasos > 10% → reforço de motoboy no pior dia; custo iFood > 25%; cancelamento > 2%; ticket < R$ 75; preparo > 20 min; senão, promoção no dia mais fraco).

## Rotina de segunda às 08:51

Cron `CRON_TZ=America/Bahia 51 8 * * 1` (Rotina "Fechamento semanal Tili (segunda)"; a coleta leva ~10 min, o painel chega por volta das 09:00), sessão nova a cada disparo, ambiente Contapecas, conector Gmail para o e-mail de reserva. Roda `--whatsapp`, faz commit de `monitor/semanal/` no branch da sessão e abre um pull request para a `main` ("semanal: fechamento DD/MM a DD/MM"), que o Emerson aceita.

---

# Contagem física do estoque (`contagem.py` e `contagem_lancar.py`) — sob demanda

Não é Rotina: roda só quando o Emerson pedir.

## 1. Gerar a folha (`contagem.py`, só leitura)

```bash
python3 monitor/contagem.py
```

Gera em `manuais/`:
- `Folha_de_Contagem_Tili_Pizzaria.pdf` (A4, letra grande, linhas de 14 mm):
  - **Parte 1** — contagem por área: Freezer, Câmara/Geladeira, Estoque seco, Bebidas, Embalagens, Limpeza. Em cada área, primeiro os insumos **em uso nas fichas**, depois o resto, em ordem alfabética. Colunas: insumo (nome de exibição; o nome do ALIV aparece embaixo quando é diferente), unidade de contagem (= unidade de compra/estoque do ALIV: KG, CX, FD, UN…), fator (quanto 1 unidade vale na ficha, ex.: 1 KG = 1.000 G), quantidade em branco e observação.
  - **Parte 2** — decidir "contar" ou "zerar": insumos com saldo negativo e insumos fora de todas as fichas (inclui utensílios, equipamentos e material de obra cadastrados como insumo, que ficam fora da Parte 1).
  - **Parte 3** — pizzas e lanches ativos sem ficha ou com ficha incompleta.
- `Folha_de_Contagem_Tili_Pizzaria.xlsx`: aba **Contagem** com as mesmas linhas da Parte 1 (só digitar a coluna amarela), aba **Decidir (Parte 2)** e aba **Fichas (Parte 3)**.

Regras:
- **Em uso** = aparece em alguma ficha de produto ativo (todos os tamanhos), de adicional ativo, ou é componente de uma sub-receita em uso (ex.: a farinha da massa). Conferido em 09/11/2026: bate 100% com o campo `in_use` do ALIV (59 insumos).
- **Área**: por palavras do nome (o ALIV só tem 3 categorias). As regras ficam em `REGRAS` no topo do script.
- **Ficha incompleta**: ficha vazia em algum tamanho; pizza sem massa; lanche sem pão; batata sem batata; sem embalagem; menos de 3 itens; item com quantidade 0; insumo da ficha sem custo.
- `--cache ARQ.json` guarda/reaproveita a coleta (útil para refazer o PDF sem consultar o ALIV de novo).

Endpoints lidos: `/admin/inventory/api/ingredients`, `/admin/api/menu/full_data`, `/admin/menu/product/{id}/recipes?size_id=`, `/admin/menu/addon/{id}/recipe_matrix`.

## 2. Lançar a contagem (`contagem_lancar.py`) — só com o ok do Emerson

```bash
python3 monitor/contagem_lancar.py manuais/Folha_de_Contagem_Tili_Pizzaria.xlsx              # dry-run: mostra, não grava
python3 monitor/contagem_lancar.py manuais/Folha_de_Contagem_Tili_Pizzaria.xlsx --confirmar  # lança
```

- Quantidade em branco = não lança. `0` = contado e zerado. "zerar" na aba Decidir lança 0.
- Quantidade enviada = contada × "Fator p/ estoque ALIV" (padrão 1). Ex.: contou 3 caixas de 12 de um item que o ALIV controla em UN → fator 12 → lança 36 UN.
- Confere antes: insumo existe, não está pausado, o nome da linha bate com o ALIV e a unidade não mudou desde que a planilha foi gerada. Aceita também a planilha baixada do Google Planilhas como .xlsx (usa a 1ª aba). Com linha inválida na planilha, `--confirmar` não lança nada.
- Usa a Conferência de Estoque do ALIV: abre uma (`check/start`) se não houver, e grava cada item com `check/update-item` (zera e soma, igual aos botões da tela). Item que já tem contagem na sessão só é regravado com `--sobrescrever`.
- **Não finaliza.** O ajuste do estoque é feito pelo Emerson na tela: Estoque → Conferência → Finalizar (responsável + senha).
- Testado em dry-run contra o ALIV real em 09/11/2026. O modo `--confirmar` ainda não foi rodado (grava no ALIV).
- Códigos de saída: `0` ok · `1` erro no ALIV · `2` faltam variáveis ou planilha inválida · `3` lançou com falhas.
