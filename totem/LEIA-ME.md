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
4. Tocar em **Contar bandeja** → **⚙**: colar a chave do Claude, escolher a câmera, definir a senha do
   atendente e conferir o produto de cada tipo de peça.

## Antes de usar (no cardápio do ALIV, loja 155)
Cada tipo de peça precisa de um produto **vendido por peça** e marcado para aparecer no totem.
Hoje existem `PEÇA SUSHI` (R$ 2,99), `Acarajapa` (R$ 2,99) e `Sashimi` (R$ 4,99) na Promoção do Dia,
mas nenhum está no totem. Sem produto, o complemento avisa "Sem produto no totem" e não põe nada na sacola.

A instrução da contagem fica em `prompt.js` (a mesma do Conta-Peças do celular).
