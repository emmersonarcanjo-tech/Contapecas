# Conta-Peças no totem do ALIV

Complemento que põe um botão **Contar bandeja** na tela do totem do ALIV (`/kiosk/tilisushipoke`).
A câmera conta a bandeja e as peças entram na **sacola do ALIV**. Pedido, Pix, maquininha e nota
continuam sendo do próprio ALIV: o complemento não cria pedido, não cobra e não fala com o servidor do ALIV.

## Como funciona
1. Cliente toca **Contar bandeja** e põe a bandeja embaixo da câmera (conta sozinho quando ela para).
2. Marcas amarelas = peça; laranja = peça em dúvida.
3. Com peça em dúvida, o botão da sacola fica travado até o atendente tocar na tela e digitar a senha.
4. **Colocar na sacola** soma as peças na sacola do totem, com produto e preço do cardápio do totem.

## Instalar no totem (Android)
1. Instalar o **Firefox** e, nele, o complemento **Violentmonkey**.
2. Abrir `https://emmersonarcanjo-tech.github.io/Contapecas/totem/conta-pecas-totem.user.js` e tocar em **Instalar**.
3. Abrir o totem do ALIV no Firefox (`https://app.alivhub.com.br/kiosk/tilisushipoke`).
4. Tocar em **Contar bandeja** → **⚙**: colar a chave do Claude, escolher a câmera, definir a senha (só números) do
   atendente e conferir o produto de cada tipo de peça.

## Produtos por peça (loja 155, criados em 22/11/2026)
Categorias que só aparecem no totem (fora do app, PDV, garçom, iFood e cardápio impresso):

| Categoria | Dias | Produtos (preço) |
|---|---|---|
| Buffet por peça (totem) | todos | Nigiri 3,99 · Joy 4,99 · Sashimi 4,99 · Acarajapa 2,99 · Outras peças 2,99 |
| Buffet por peça (totem) — dias normais | seg, ter, qui–dom | Hossomaki, Uramaki, Hot roll 2,99 |
| Buffet por peça (totem) — quarta | quarta | Hossomaki, Uramaki, Hot roll 1,99 |

Os nomes terminam em "(peça buffet)" e o complemento acha cada um sozinho. Na quarta o ALIV
só mostra os de 1,99, então o preço certo vem sem configuração. Para mudar preço, mude no ALIV.

A instrução da contagem fica em `prompt.js` (a mesma do Conta-Peças do celular).

Esqueceu a senha do atendente: digite os 6 últimos caracteres da chave do Claude no lugar da senha; ela é apagada e dá para criar outra em ⚙.

Trava da sacola: as peças contadas pela câmera não podem ser diminuídas nem apagadas na sacola sem a senha do atendente (a quantidade volta sozinha). Aumentar é livre. A trava zera quando o ALIV esvazia a sacola (pedido feito, Recomeçar ou tela parada).

Foto da bandeja: ao colocar na sacola, a foto com as marcas aparece no topo da tela "Seu pedido" (toque para ampliar) e fica guardada no próprio totem por 30 dias (banco do navegador "conta_pecas_totem", com data, hora, peças, itens e total). O ALIV não guarda foto no pedido. Na sacola o botão Contar bandeja some; para outra bandeja, Continuar pedindo. Bandejas do mesmo produto somam na mesma linha.
