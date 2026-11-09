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
| `monitor/monitor.py` | De hora em hora, das 18h às 00h | Monitora Pizzaria e Sushi e avisa pelo WhatsApp do ALIV. |
| `monitor/previsao_motoboys.py` | Todo dia às 08:00 | Recomenda quantos motoboys chamar hoje (faixa + histórico de 4 semanas) e manda para Emerson, Josué e Camilo. |
| `monitor/diaristas.py` | Todo dia às 08:00 | PDF diário dos diaristas. Dia operacional: 16:00 até 08:00 do dia seguinte. |
| `monitor/prestadores.py` | Segunda às 08:30 | Relatório semanal dos prestadores MEI. Mesmo corte de dia (16:00–08:00). |
| `monitor/nfce.py` | Às 02:00 (na última noite do mês, às 23:50) | Lista as notas pendentes. **Só emite com o comando do Emerson.** |
| `monitor/despesas.py` / `monitor/despesas_lancar.py` | 00:00 e 12:00 | Lê o grupo **Tili Despesas** pelo ALIV e lança conta e estoque. |
| `monitor/atendimento_ia.py` | Todo dia às 03:30 (Rotina a criar) | Audita o atendimento da IA no WhatsApp da Pizzaria no turno 16:00–01:00 e manda resumo + pares de treino ao Emerson. `aprovar` grava pares só com ok do Emerson. |
| `monitor/consumo.py` | (ainda sem Rotina — hoje o alerta roda dentro da Conferência de notas 23:45) | Limite de consumo dos funcionários: R$ 200 por ciclo (26 a 25), avisa a partir de R$ 160. |

Horários no fuso da Bahia, conferidos na página de Rotinas em 07/11/2026.

Outras Rotinas ativas que não usam scripts deste repositório: Conferência de notas fiscais (21:00 e 23:45), Auditoria de ponto semanal (segunda), Fechamento de ponto mensal (dia 1).

Se os horários na página de Rotinas divergirem deste arquivo, **os da página valem** — atualize este arquivo.

## Regras de segurança
- ALIV: **só leitura**, exceto o que o script já faz.
- **Nunca** emitir nota fiscal, lançar despesa ou enviar WhatsApp sem o Emerson pedir na sessão.
- **Nunca** gravar credenciais, CPF, CNPJ, chave de nota ou senha em código, log ou commit.
- Antes de alterar qualquer rotina, **resumir o que vai mudar e esperar o ok**.

## Como agir
- **Pedido de mudança:** localize o script e a Rotina, faça a alteração, teste em dry-run contra o ALIV real quando possível, abra um pull request e explique o resultado em até cinco linhas.
- **"Algo não chegou":** confira primeiro os registros da última execução da Rotina.
