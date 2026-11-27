// Imagem do card de aviso no cardápio digital (site/app) do ALIV: 800x800, nas cores da Tili.
// O site mostra o card em "Destaques" cortando em cima e embaixo (só a faixa do meio, y de ~95 a ~705) e põe o selo
// "Recomendado" por cima do canto de cima à esquerda (até y ~225). Por isso tudo fica entre y 236 e 676.
// Uso: node card_site.js <saida.jpg|png> "<selo>" "<titulo>" "<faixa>" "<linha 1>" "<linha 2>"
const { chromium } = require('playwright'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017';
(async () => {
  const [out, selo, titulo, faixa, l1, l2] = process.argv.slice(2); const esc = s => String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; margin: 0; padding: 0 }
    body { width: 800px; height: 800px; font-family: Inter, Arial, sans-serif; color: #fff; overflow: hidden; position: relative;
           background: radial-gradient(800px 380px at 50% 8%, rgba(200,16,46,.5), rgba(200,16,46,0) 72%), radial-gradient(700px 300px at 50% 100%, rgba(212,160,23,.15), rgba(212,160,23,0) 70%), #0c0c0c }
    .pg { position: absolute; left: 0; right: 0; top: 236px; height: 440px; display: flex; flex-direction: column; align-items: center; justify-content: space-between }
    .selo { position: relative; display: inline-block; padding: 4px 38px 9px; font-weight: 900; font-style: italic; font-size: 60px; line-height: 1.05; letter-spacing: -1px; z-index: 1; text-transform: uppercase; white-space: nowrap }
    .selo:before { content: ""; position: absolute; inset: 0; background: ${VERM}; border-radius: 16px 52px 22px 58px; transform: rotate(-2deg) skewX(-9deg); z-index: -1; box-shadow: 9px 8px 0 rgba(200,16,46,.35) }
    .tit { font-weight: 900; font-style: italic; font-size: 98px; line-height: .95; letter-spacing: -3px; text-transform: uppercase; white-space: nowrap }
    .faixa { align-self: stretch; background: ${VERM}; border-top: 5px solid ${OURO}; border-bottom: 5px solid ${OURO}; text-align: center; padding: 11px 10px 15px; font-weight: 900; font-size: 56px; line-height: 1; letter-spacing: -1px; text-transform: uppercase; white-space: nowrap }
    .l { font-weight: 800; font-size: 30px; line-height: 1.22; text-align: center; white-space: nowrap }
    .l b { color: ${OURO}; font-weight: 900 }
  </style></head><body><div class="pg">
    <div class="selo">${esc(selo)}</div><div class="tit">${esc(titulo)}</div><div class="faixa">${esc(faixa)}</div>
    <div><div class="l">${l1 || ''}</div><div class="l">${l2 || ''}</div></div>
  </div></body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 800, height: 800 }, deviceScaleFactor: 1 });
  await p.setContent(html); await p.waitForTimeout(400);
  const av = await p.evaluate(() => [...document.querySelectorAll('.selo, .tit, .faixa, .l')].map(e => { const q = e.getBoundingClientRect(); return (e.scrollWidth > 800 || q.left < 0 || q.right > 800 || q.top < 110 || q.bottom > 690) ? `ATENÇÃO fora: .${e.className} ${Math.round(q.left)}-${Math.round(q.right)} x ${Math.round(q.top)}-${Math.round(q.bottom)}` : null; }).filter(Boolean));
  av.forEach(a => console.log(a));
  await p.screenshot(/\.png$/i.test(out) ? { path: path.resolve(out) } : { path: path.resolve(out), type: 'jpeg', quality: 93 });
  await b.close(); console.log('ok', out);
})();
