// Arte de promoção de combo no estilo "selo + nome + preço + foto da bandeja + contagem das peças + WhatsApp e logo",
// nas cores da Tili (preto, vermelho C8102E, dourado D4A017). Usa SOMENTE fotos da própria Tili.
// Uso: node arte_promo.js <spec.json> <saida.jpg|png> [quadrado|story]
// spec: { "selo", "titulo", "preco": "59,90", "chamada": "22 peças por", "foto", "logo", "whatsapp", "assinatura", "nota",
//         "pecas": [ ["4","Niguiri","salmão"], ... ] }   (caminhos relativos ao spec)
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017';
(async () => {
  const specPath = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]); const fmt = process.argv[4] || 'quadrado';
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); const base = path.dirname(specPath);
  const uri = f => { const p = path.resolve(base, f); const m = /\.webp$/i.test(p) ? 'image/webp' : /\.png$/i.test(p) ? 'image/png' : 'image/jpeg';
                     return `data:${m};base64,${fs.readFileSync(p).toString('base64')}`; };
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const W = 1080, H = fmt === 'story' ? 1920 : 1080;
  const k = fmt === 'story' ? { pad: 70, selo: 92, tit: 100, preco: 150, cent: 70, cham: 44, foto: 700, num: 96, nome: 44, det: 28, zap: 54, zapl: 30, logo: 180, gap: 44, ass: 30 }
                            : { pad: 40, selo: 56, tit: 82, preco: 100, cent: 48, cham: 31, foto: 392, num: 62, nome: 31, det: 20, zap: 38, zapl: 21, logo: 104, gap: 16, ass: 20 };
  const [reais, cent] = String(spec.preco).split(',');
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; margin: 0; padding: 0 }
    body { width: ${W}px; height: ${H}px; font-family: Inter, Arial, sans-serif; color: #fff; overflow: hidden;
           background: radial-gradient(${W}px ${H * .42}px at 50% 0%, rgba(200,16,46,.42), rgba(200,16,46,0) 72%), radial-gradient(${W * .9}px ${H * .35}px at 50% 100%, rgba(212,160,23,.14), rgba(212,160,23,0) 70%), #0c0c0c; }
    .pg { position: absolute; inset: 0; padding: ${k.pad}px; display: flex; flex-direction: column; align-items: center; gap: ${k.gap}px }
    .selo { position: relative; display: inline-block; padding: ${k.selo * .12}px ${k.selo * .62}px ${k.selo * .16}px; font-weight: 900; font-style: italic; font-size: ${k.selo}px; line-height: 1.05; letter-spacing: -1px; z-index: 1 }
    .selo:before { content: ""; position: absolute; inset: 0; background: ${VERM}; border-radius: ${k.selo * .22}px ${k.selo * .7}px ${k.selo * .3}px ${k.selo * .8}px; transform: rotate(-2.5deg) skewX(-9deg); z-index: -1; box-shadow: ${k.selo * .12}px ${k.selo * .1}px 0 rgba(200,16,46,.35) }
    h1 { font-weight: 900; font-size: ${k.tit}px; line-height: 1; letter-spacing: -2px; text-align: center; text-shadow: 0 4px 20px rgba(0,0,0,.7); margin-top: ${-k.gap * .35}px }
    h1 b { color: ${OURO} }
    .linha-preco { display: flex; align-items: center; gap: ${k.cham * .7}px }
    .chamada { font-weight: 700; font-size: ${k.cham}px; color: #fff; font-style: italic; text-align: right; line-height: 1.1 }
    .preco { background: ${VERM}; border-radius: ${k.preco}px; padding: ${k.preco * .06}px ${k.preco * .42}px ${k.preco * .08}px; display: flex; align-items: flex-start; gap: ${k.preco * .08}px; font-weight: 900; box-shadow: 0 10px 30px rgba(200,16,46,.45); border: ${Math.round(k.preco * .04)}px solid ${OURO} }
    .preco .rs { font-size: ${k.cent}px; margin-top: ${k.preco * .34}px }
    .preco .v { font-size: ${k.preco}px; line-height: 1.08; letter-spacing: -3px }
    .preco .c { font-size: ${k.cent}px; margin-top: ${k.preco * .14}px }
    .foto { width: ${Math.min(W - 2 * k.pad, Math.round(k.foto * 1.55))}px; height: ${k.foto}px; flex: none; position: relative; margin: ${-k.gap * .4}px 0 }
    .foto img { width: 100%; height: 100%; object-fit: cover; object-position: 50% 52%; -webkit-mask-image: radial-gradient(ellipse closest-side, #000 86%, rgba(0,0,0,0) 100%); mask-image: radial-gradient(ellipse closest-side, #000 86%, rgba(0,0,0,0) 100%) }
    .nota { position: absolute; right: ${k.foto * .12}px; bottom: ${-k.det * .2}px; font-size: ${k.det * .9}px; color: rgba(255,255,255,.6); font-style: italic }
    .pecas { display: flex; align-items: stretch; justify-content: center; width: 100% }
    .p { flex: 1; text-align: center; padding: 0 ${k.nome * .25}px; border-left: 3px solid ${VERM} }
    .p:first-child { border-left: 0 }
    .p .n { font-weight: 900; font-size: ${k.num}px; line-height: 1 }
    .p .nm { font-weight: 800; font-size: ${k.nome}px; line-height: 1.1; margin-top: ${k.nome * .12}px }
    .p .dt { font-weight: 500; font-size: ${k.det}px; color: rgba(255,255,255,.78); margin-top: ${k.det * .2}px; line-height: 1.15 }
    .rod { margin-top: auto; width: 100%; display: flex; align-items: center; justify-content: space-between; border-top: 3px solid ${VERM}; padding-top: ${k.gap * .7}px }
    .zap .l { font-size: ${k.zapl}px; font-weight: 600; color: rgba(255,255,255,.85) }
    .zap .t { font-size: ${k.zap}px; font-weight: 900; color: ${OURO}; letter-spacing: .5px; line-height: 1.1 }
    .zap .a { font-size: ${k.ass}px; font-weight: 600; color: rgba(255,255,255,.7); margin-top: ${k.ass * .2}px }
    .logo { width: ${k.logo}px; height: ${k.logo}px; background: #fff; border-radius: ${k.logo * .18}px; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 26px rgba(0,0,0,.55); flex: none }
    .logo img { width: 86%; height: 84%; object-fit: contain }
  </style></head><body><div class="pg">
    <div class="selo">${esc(spec.selo)}</div>
    <h1>${spec.titulo}</h1>
    <div class="linha-preco"><div class="chamada">${spec.chamada}</div><div class="preco"><span class="rs">R$</span><span class="v">${esc(reais)}</span><span class="c">,${esc(cent)}</span></div></div>
    <div class="foto"><img src="${uri(spec.foto)}">${spec.nota ? `<div class="nota">${esc(spec.nota)}</div>` : ''}</div>
    <div class="pecas">${spec.pecas.map(p => `<div class="p"><div class="n">${esc(p[0])}</div><div class="nm">${esc(p[1])}</div>${p[2] ? `<div class="dt">${esc(p[2])}</div>` : ''}</div>`).join('')}</div>
    <div class="rod"><div class="zap"><div class="l">Pedido pelo WhatsApp</div><div class="t">${esc(spec.whatsapp)}</div><div class="a">${esc(spec.assinatura)}</div></div>
      <div class="logo"><img src="${uri(spec.logo)}"></div></div>
  </div></body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await p.setContent(html, { waitUntil: 'load' }); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
  const estouro = await p.evaluate(() => { const pg = document.querySelector('.pg'); return pg.scrollHeight - pg.clientHeight; });
  await p.screenshot({ path: out, type: /\.jpe?g$/i.test(out) ? 'jpeg' : 'png', quality: /\.jpe?g$/i.test(out) ? 90 : undefined }); await b.close();
  console.log('ok', out, '| sobra de altura (px, >0 = estourou):', estouro);
})();
