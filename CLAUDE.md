# Tili — automação da operação

Este repositório automatiza a operação da Tili, de Emerson, dono da **Tili Pizzaria** e **Tili Sushi** em Porto Seguro, Bahia.
Tudo roda como **Rotinas do Claude Code na nuvem**, ambiente **Contapecas**. As credenciais do ALIV e os números de WhatsApp ficam nas **variáveis de ambiente**.

## Como falar com o Emerson
- Sempre em português, curto e objetivo.
- Emerson não é programador: explique em linguagem simples.
- Nunca peça para ele editar código.

## Rotinas
| Script | Quando | O que faz |
|---|---|---|
| `monitor/monitor.py` | De hora em hora às :55, das 17:55 às 23:55 (chega perto da hora cheia) | Monitora Pizzaria e Sushi e avisa pelo WhatsApp do ALIV. |
| `monitor/previsao_motoboys.py` | Todo dia às 08:00 | Recomenda quantos motoboys chamar hoje (faixa + histórico de 4 semanas) e manda para Emerson, Josué e Camilo. |
| `monitor/diaristas.py` | Todo dia às 08:00 | PDF diário dos diaristas. Dia operacional: 16:00 até 08:00 do dia seguinte. |
| `monitor/prestadores.py` | Segunda às 08:30 | Relatório semanal dos prestadores MEI. Mesmo corte de dia (16:00–08:00). |
| `monitor/nfce.py` | Às 02:00 (na última noite do mês, às 23:50) | Lista as notas pendentes. **Só emite com o comando do Emerson.** |
| `monitor/despesas.py` / `monitor/despesas_lancar.py` | 00:00 e 12:00 | Lê o grupo **Tili Despesas** pelo ALIV e lança conta e estoque. |
| `monitor/atendimento_ia.py` | Todo dia às 03:30 | Audita o atendimento da IA no WhatsApp da Pizzaria e do Sushi no turno 16:00–01:00 e manda painel + resumo + pares de treino ao Emerson. `aprovar` grava pares só com ok do Emerson. |
| `monitor/fechamento_semanal.py` | Segunda às 08:51 (chega ~09:00) | Fechamento da semana (seg–dom, dia 16:00–04:00) da Pizzaria, Sushi e consolidado, com comparações, mês até agora, destaques e painel do iPad (2360×1640) + texto para o Emerson. Salva `monitor/semanal/AAAA-MM-DD.md`. |
| `monitor/consumo.py` | Todo dia às 02:20 | Limite de consumo dos funcionários: R$ 200 por ciclo (26 a 25), avisa a partir de R$ 160. Só esta Rotina avisa (saiu da Conferência 23:45 em 07/11). |
| `monitor/notas_entrada.py` | Todo dia às 20:30 | Notas de fornecedor (SEFAZ) da Pizzaria e do Sushi: entrada no estoque + boletos nas Contas a Pagar. Vencido = pago; sem pagamento na nota = só estoque (conta paga sem caixa); Norsa sem data = +4 dias (até 15/11). Item sem insumo ligado: não lança, manda para o Emerson conferir. |
| `monitor/baixa_motoboys.py` | Segunda às 17:00 | Baixa na folha do ALIV do saldo dos motoboys (diaristas e prestadores) até o domingo anterior, como Pix sem mexer em caixa/banco; o que é de depois fica adiado. Valor = saldo do ALIV. |
| `monitor/boletos.py` | Segunda 07:00 e sexta 10:00 | PDFs de boletos (Pizzaria + Sushi) para o WhatsApp do financeiro: segunda = sáb–seg e ter–sex; sexta = conferência (fora da lista de segunda + vencidos sem baixa). |
| `monitor/comprovantes.py` | Seg a sáb, 11:00, 15:00 e 19:00 | Lê os comprovantes que o financeiro manda no WhatsApp da Pizzaria e dá baixa no boleto certo, saindo do Bradesco da loja. Sem certeza, não baixa: avisa o Emerson. |
| `monitor/ifood_semanal.py` | Segunda às 09:00 | PDF do iFood da semana (Pizzaria, Burguer, 2.0, Sushi) para o Emerson: vendas, descontos, comissão, taxas, anúncios, antecipação, repasse e verificação das taxas × contrato (`monitor/ifood/contrato.json`: comissão 10%, transação 2,73%). |
| `monitor/folha_clt.py` | Dias 5 e 20, às 18:10 | Lança na Folha do ALIV (Pizzaria **e Sushi**) a folha CLT paga pelo Bradesco: vale (40%) no dia 20 e saldo do mês no dia 5, com os valores do ALIV. Competência 10/2026 lançada em 15/11 (setembro ficou de fora: o ALIV não oferece mais). |
| `monitor/guias.py` | Seg a sáb, 09:40 | Lê no Gmail (tilipizzariadp@) os e-mails da contabilidade Mamed com guias (DAS, parcelamentos, FGTS, INSS/DARF, DAE) e lança cada guia nas Contas a Pagar da Pizzaria (Impostos e Encargos, em aberto), sem duplicar. Guia ilegível não é lançada: vai para o Emerson conferir. |

Horários no fuso da Bahia, conferidos na página de Rotinas em 07/11/2026.

Outras Rotinas ativas que não usam scripts deste repositório: Conferência de notas fiscais (21:00 e 23:45), Auditoria de ponto semanal (segunda), Fechamento de ponto mensal (dia 1).

Se os horários na página de Rotinas divergirem deste arquivo, **os da página valem** — atualize este arquivo.

## Regras de segurança
- ALIV: **só leitura**, exceto o que o script já faz.
- **Nunca** emitir nota fiscal, lançar despesa ou enviar WhatsApp sem o Emerson pedir na sessão.
  - Exceção (Emerson, 09/11/2026): se uma previsão de motoboys já enviada estiver errada, mande **logo em seguida** a corrigida, para os mesmos destinatários, com `python3 monitor/previsao_motoboys.py --whatsapp --correcao "o que estava errado"`. Depois avise o Emerson do que mudou.
- **Nunca** gravar credenciais, CPF, CNPJ, chave de nota ou senha em código, log ou commit.
- Antes de alterar qualquer rotina, **resumir o que vai mudar e esperar o ok**.

## Como agir
- **Pedido de mudança:** localize o script e a Rotina, faça a alteração, teste em dry-run contra o ALIV real quando possível, abra um pull request e explique o resultado em até cinco linhas.
- **"Algo não chegou":** confira primeiro os registros da última execução da Rotina.

## Taxas no ALIV (15/11/2026)
Formas de pagamento das duas lojas: iFood Online = 10% (comissão); iFood Online (Pix, Visa, …) = 2,73% (transação); Pix = 1%; Pix Online do app (Mercado Pago) = 1%; vales (Pluxee, Alelo, VR, Ticket) = 3,6%; Cartão Crédito 3,49% e Débito 1,27% da maquininha (confirmado pelo Emerson em 15/11). Aba Taxas da conciliação iFood: comissão 10%, pagamento 2,73%. Novembro (01–15) recalculado. Backup da tabela antiga só na sessão.

## Aluguel (15/11/2026)
Contas a Pagar, categoria "Aluguel e Contas", Boleto via DDA, pago pelo Bradesco: Pizzaria R$ 7.000 todo dia 15 (recorrente a partir de 15/12); Sushi R$ 10.000 todo dia 25, na conta do Sushi (recorrente a partir de 25/11). Agosto a outubro (e 15/11 da Pizzaria) lançados como pagos. O "Aluguel ponto 2 — R$ 5.000" de julho, na conta da Pizzaria, era o aluguel do Sushi antes do reajuste.

## Contas fixas da Pizzaria (15/11/2026)
Recorrentes mensais, vencimento dia 10, agosto–outubro lançados como pagos (Bradesco), de 10/11 em diante em aberto: Contador R$ 1.621 e Advogada R$ 2.500 (Despesas Administrativas); Despesa extra gerencial R$ 5.288,73 e Assistente administrativo R$ 3.500 (Folha de Pagamento) — o "gerencial" é o complemento de um gerente até R$ 8.000 e NÃO deve levar o nome dele; Energia R$ 5.000, Gás R$ 2.000, Internet R$ 300 (Aluguel e Contas); Marketing R$ 2.500; Plano odontológico R$ 800 e Vale alimentação/refeição R$ 14.400 (Benefícios); Maquininha R$ 1.200 (Tarifas e Maquininha). Mensalidade do iFood NÃO se lança (vem do extrato). Salário do gerente na Folha do ALIV ajustado em 15/11 para R$ 2.711,27 (base + 40% de gerente, como na carteira). Pró-labore R$ 1.621/mês (dia 10, categoria Pró-labore). Empréstimo iFood Pago (CCB MovilePay SCD, emitida 18/09/2025): R$ 750.000 líquidos + tarifa de cadastro R$ 50.175 + IOF R$ 23.350,53; 34 parcelas de R$ 36.327,95 todo dia 20, de 20/11/2025 a 20/08/2028; juros 2,32% a.m., CET 2,95% a.m.; débito automático na conta iFood Pago (Zoop), com trava dos recebíveis iFood e cartões 30 dias antes de cada parcela. No ALIV: parcelas 10/34 (ago/26) a 34/34, categoria Empréstimos, juros e amortização na descrição; 10–12 pagas sem banco. Sistema ALIV: R$ 999/mês dia 22, só na Pizzaria (o Sushi não tem fatura separada). Guias da contabilidade: Rotina `guias.py` (15/11/2026); parcelamentos de 10/2026 (simplificado, PARCSN 8/15, PGFN, PARCSN So Delivery 15/60) lançados em aberto, vencidos em 30/10.

## Sushi e divisão de custos (15/11/2026)
Regra do Emerson: cada despesa fica na loja que usa, mesmo com a carteira na outra (é a mesma empresa). Exclusivos 100% na loja; motoboys divididos por nº de entregas (sem contar as entregas lançadas no login do Josué ou do Thiago Camilo — eles só registram pedidos de motoboy terceirizado); Josué (gerente geral das duas lojas), Thiago Camilo (gerente de logística), assistente, contador, advogada, ALIV e marketing por % do faturamento (rateio mensal — a fazer).
Folha do Sushi no ALIV: Djalma, Jamaria, Luiz Fernando e Tamile (= "Tamiris"; cadastro da Pizzaria desativado, no Sushi admissão gerencial 01/11). Outubro deles lançado com os valores do extrato da Mamed. Faltam Rebeca, Atricio e Junior (não estão na folha de 10/2026).
Contas fixas do Sushi (dia 10, ago–out pagas pelo Bradesco do Sushi, de 10/11 em aberto): Energia R$ 2.900, Internet R$ 100, Aluguel da maquininha R$ 200, Sushiman Flávio e Jonatan (contrato) R$ 3.500 cada, Diaristas sushiman ~R$ 3.500, Lorena diarista ~R$ 3.640 (R$ 140/dia, ter–dom).
