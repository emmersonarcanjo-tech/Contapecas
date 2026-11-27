// Banner do cardápio digital (site/app) do ALIV: 1200x400, nas cores da Tili (preto, vermelho C8102E, dourado D4A017), com logo.
// Uso: node banner_site.js <spec.json> <saida.jpg|png>
// spec: { "selo", "titulo", "data" e "sub" (linha do meio), "chips": [ ["Temaki Hot", "19,90"], ... ], "logo" }   (caminhos relativos ao spec)
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017';
(async () => {
  const specPath = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]);
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); const base = path.dirname(specPath);
  const uri = f => { const p = path.resolve(base, f); const m = /\.webp$/i.test(p) ? 'image/webp' : /\.png$/i.test(p) ? 'image/png' : 'image/jpeg'; return `data:${m};base64,${fs.readFileSync(p).toString('base64')}`; };
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const W = 1200, H = 400;
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; margin: 0; padding: 0 }
    body { width: ${W}px; height: ${H}px; font-family: Inter, Arial, sans-serif; color: #fff; overflow: hidden; position: relative;
           background: radial-gradient(900px 300px at 22% 0%, rgba(200,16,46,.5), rgba(200,16,46,0) 72%), radial-gradient(700px 240px at 90% 100%, rgba(212,160,23,.16), rgba(212,160,23,0) 70%), #0c0c0c }
    .pg { position: absolute; inset: 0; padding: 26px 28px 24px; display: flex; flex-direction: column; justify-content: space-between }
    .l1 { display: flex; align-items: center; justify-content: space-between; gap: 28px }
    .esq { display: flex; flex-direction: column; align-items: flex-start; gap: 10px }
    .selo { position: relative; display: inline-block; padding: 6px 36px 9px; font-weight: 900; font-style: italic; font-size: 62px; line-height: 1.05; letter-spacing: -1px; z-index: 1; text-transform: uppercase; white-space: nowrap }
    .selo:before { content: ""; position: absolute; inset: 0; background: ${VERM}; border-radius: 16px 50px 22px 56px; transform: rotate(-2deg) skewX(-9deg); z-index: -1; box-shadow: 8px 7px 0 rgba(200,16,46,.35) }
    .lm { display: flex; align-items: center; justify-content: center; gap: 26px; white-space: nowrap }
    .data { font-weight: 900; font-size: 34px; letter-spacing: 2px; text-transform: uppercase; color: ${OURO} }
    .dir { text-align: right; flex: 1; min-width: 0 }
    .tit { font-weight: 900; font-style: italic; font-size: 84px; line-height: .95; letter-spacing: -2px; text-transform: uppercase; white-space: nowrap }
    .sub { font-weight: 800; font-size: 50px; white-space: nowrap; line-height: 1 }
    .sub b { color: ${OURO}; font-weight: 900 }
    .l2 { display: flex; align-items: center; gap: 10px; border-top: 3px solid ${VERM}; padding-top: 16px }
    .chip { display: flex; align-items: center; gap: 9px; background: linear-gradient(160deg, #222, #131313); border: 2px solid #3a3a3a; border-radius: 40px; padding: 6px 7px 6px 16px; white-space: nowrap }
    .chip .n { font-weight: 800; font-size: 22px; line-height: 1 }
    .chip .p { background: ${VERM}; border: 2px solid ${OURO}; border-radius: 30px; padding: 3px 14px 4px; font-weight: 900; font-size: 25px; line-height: 1.05 }
    .logo { margin-left: auto; width: 64px; height: 64px; background: #fff; border-radius: 12px; display: flex; align-items: center; justify-content: center; flex: none }
    .logo img { width: 86%; height: 84%; object-fit: contain }
  </style></head><body><div class="pg">
    <div class="l1"><div class="esq"><div class="selo">${esc(spec.selo)}</div></div>
      <div class="dir"><div class="tit">${esc(spec.titulo)}</div></div></div>
    <div class="lm"><span class="data">${esc(spec.data)}</span><span class="sub">${spec.sub}</span></div>
    <div class="l2">${spec.chips.map(c => `<div class="chip"><span class="n">${esc(c[0])}</span><span class="p">R$ ${esc(c[1])}</span></div>`).join('')}<div class="logo"><img src="${uri(spec.logo)}"></div></div>
  </div></body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await p.setContent(html); await p.waitForTimeout(400);
  const av = await p.evaluate(() => { const r = []; for (const s of ['.l1', '.lm', '.l2', '.dir', '.esq']) { const e = document.querySelector(s); if (e.scrollWidth > e.clientWidth + 1) r.push(`ATENÇÃO ${s} estourou: ${e.scrollWidth} > ${e.clientWidth}`); } const l = document.querySelector('.l2').getBoundingClientRect(); r.push(`linha de baixo até y=${Math.round(l.bottom)}`); return r; });
  av.forEach(a => console.log(a));
  await p.screenshot(/\.png$/i.test(out) ? { path: out } : { path: out, type: 'jpeg', quality: 93 });
  await b.close(); console.log('ok', out, `${W}x${H}`);
})();
