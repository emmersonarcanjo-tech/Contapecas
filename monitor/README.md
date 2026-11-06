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

## Como criar a Rotina

Na sessão do Claude Code (ambiente **Contapecas**, repositório `contapecas`), peça:

> Crie uma Rotina que abre uma sessão nova a cada disparo, no fuso America/Bahia, às 17:27, 18:27, 19:27, 20:27, 21:27, 22:27 e 23:27 (cron `CRON_TZ=America/Bahia 27 17-23 * * *`), com o conector Gmail, e este prompt:

Prompt da Rotina:

```
Monitor da Tili (só leitura). Na pasta do repositório contapecas:
1. git pull origin main
2. python3 monitor/monitor.py > /tmp/relatorio.txt ; guarde o código de saída.
3. Envie um e-mail pelo Gmail para emmersonarcanjo@gmail.com:
   assunto = 1ª linha de /tmp/relatorio.txt; corpo = o restante, sem alterar nada.
   Se o código de saída for 2 ou o arquivo estiver vazio, mande o assunto
   "Tili Pizzaria — monitor com ERRO" com a mensagem de erro.
4. git add monitor/snapshots && git commit -m "monitor: snapshot" && git push origin main
   (se não houver mudança, siga em frente).
Não altere nada no ALIV nem no código. Não abra pull request.
```

Notas:
- A Rotina precisa ter permissão de push na `main` para gravar os snapshots. Se preferir não dar essa permissão, retire o passo 4: a "última hora" passa a ser calculada pela hora de criação dos pedidos.
- Na 1ª semana, rode em paralelo com o agente do PC e compare os números.
- **Alternativa ao e-mail: Telegram.** Troque o passo 3 por um envio para um bot do Telegram. Fica para a fase 2.

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
- **Motoboys:** conta só quem está `Online` com `start_ts` de hoje. As entregas do `drivers-live` incluem o Sushi e aparecem só como informação.
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
- O script foi testado contra um servidor falso que imita essas respostas. **Ainda não rodou com a conta real.** Na 1ª execução, use `--raw /tmp/aliv-raw` para conferir os nomes dos campos (`discount_origins`, `columns`, `deliveries`, `created_at_fmt`). O código aceita formatos variados, mas convém confirmar.
