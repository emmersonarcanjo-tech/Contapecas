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
| `monitor/folha_clt.py` | Dias 5 e 20, às 18:10 | Lança na Folha do ALIV a folha CLT paga pelo Bradesco: vale (40%) no dia 20 e saldo do mês no dia 5, com os valores do ALIV. Competência 10/2026 lançada em 15/11 (setembro ficou de fora: o ALIV não oferece mais). |

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
Formas de pagamento das duas lojas: iFood Online = 10% (comissão); iFood Online (Pix, Visa, …) = 2,73% (transação); Pix = 1%; Pix Online do app (Mercado Pago) = 1%; vales (Pluxee, Alelo, VR, Ticket) = 3,6%; Cartão Crédito 3,99% e Débito 1,99% da maquininha (aguardando o Emerson confirmar). Aba Taxas da conciliação iFood: comissão 10%, pagamento 2,73%. Novembro (01–15) recalculado. Backup da tabela antiga só na sessão.

## Aluguel (15/11/2026)
Contas a Pagar, categoria "Aluguel e Contas", Boleto via DDA, pago pelo Bradesco: Pizzaria R$ 7.000 todo dia 15 (recorrente a partir de 15/12); Sushi R$ 10.000 todo dia 25, na conta do Sushi (recorrente a partir de 25/11). Agosto a outubro (e 15/11 da Pizzaria) lançados como pagos. O "Aluguel ponto 2 — R$ 5.000" de julho, na conta da Pizzaria, era o aluguel do Sushi antes do reajuste.

## Contas fixas da Pizzaria (15/11/2026)
Recorrentes mensais, vencimento dia 10, agosto–outubro lançados como pagos (Bradesco), de 10/11 em diante em aberto: Contador R$ 1.621 e Advogada R$ 2.500 (Despesas Administrativas); Despesa extra gerencial R$ 5.288,73 e Assistente administrativo R$ 3.500 (Folha de Pagamento) — o "gerencial" é o complemento de um gerente até R$ 8.000 e NÃO deve levar o nome dele; Energia R$ 5.000, Gás R$ 2.000, Internet R$ 300 (Aluguel e Contas); Marketing R$ 2.500; Plano odontológico R$ 800 e Vale alimentação/refeição R$ 14.400 (Benefícios); Maquininha R$ 1.200 (Tarifas e Maquininha). Mensalidade do iFood NÃO se lança (vem do extrato). Salário do gerente na Folha do ALIV ajustado em 15/11 para R$ 2.711,27 (base + 40% de gerente, como na carteira). Pró-labore R$ 1.621/mês (dia 10, categoria Pró-labore). Empréstimo R$ 36.400/mês dia 20, parcelas 11/34 (ago/26) a 34/34 (jul/28), categoria Empréstimos; 11–13 lançadas pagas sem banco. Pendentes: valor do sistema ALIV, e-mail da contabilidade (folha/FGTS/INSS/DAS), pró-labore.
