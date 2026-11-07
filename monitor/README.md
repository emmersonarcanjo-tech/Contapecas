# Monitor de Operação da Tili (fase 1)

Script `monitor.py` que lê o ALIV Hub (Tili Pizzaria, loja 150) e imprime o relatório da operação. Ele **não usa navegador** e **só lê dados**: nunca altera nada no ALIV. A Rotina do Claude Code roda o script de hora em hora e manda o resultado por e-mail.

Ele usa só a biblioteca padrão do Python 3.9 ou mais novo, então não precisa instalar nada.

## Como rodar

```bash
export ALIV_USER='seu-usuario'      # e-mail/usuário do ALIV
export ALIV_PASS='sua-senha'
python3 monitor/monitor.py
```

- A 1ª linha da saída é o **assunto** do e-mail (`Tili Pizzaria — HH:27 — N pedidos / R$ X`). O resto é o corpo.
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
