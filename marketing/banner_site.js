// Banner do cardápio digital (site/app) do ALIV: arquivo 1200x400, nas cores da Tili (preto, vermelho C8102E, dourado D4A017).
// O site corta o banner (medido em 27/11/2026 em app.alivhub.com.br/app/tilisushipoke):
//   - celular: mostra só o miolo na largura (x de 132 a 1068) e põe por cima a bandeira/lupa/compartilhar (canto de cima à direita)
//     e a logo com o nome da loja (metade de baixo, à esquerda);
//   - computador: mostra a largura toda, mas só a faixa do meio na altura (y de 88 a 312).
// Por isso o recado principal fica numa faixa central (x 150-1050, y 112-210) e os preços no canto de baixo à direita.
// A logo não vai no arquivo: o próprio site põe a logo da loja por cima do banner.
// Uso: node banner_site.js <spec.json> <saida.jpg|png> [pasta para as prévias dos cortes]
// spec: { "selo", "titulo", "sub", "data", "precos": [ ["Temaki Hot", "19,90"], ... ] }
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017';
(async () => {
  const specPath = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]); const prev = process.argv[4] ? path.resolve(process.argv[4]) : null;
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const W = 1200, H = 400;
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; margin: 0; padding: 0 }
    body { width: ${W}px; height: ${H}px; font-family: Inter, Arial, sans-serif; color: #fff; overflow: hidden; position: relative;
           background: radial-gradient(900px 300px at 30% 0%, rgba(200,16,46,.5), rgba(200,16,46,0) 72%), radial-gradient(700px 240px at 85% 100%, rgba(212,160,23,.16), rgba(212,160,23,0) 70%), #0c0c0c }
    .data { position: absolute; left: 152px; top: 52px; font-weight: 900; font-size: 27px; letter-spacing: 3px; text-transform: uppercase; color: ${OURO}; white-space: nowrap }
    .meio { position: absolute; left: 150px; width: 900px; top: 110px; height: 100px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px }
    .l1 { display: flex; align-items: center; gap: 20px; white-space: nowrap }
    .selo { position: relative; display: inline-block; padding: 2px 22px 5px; font-weight: 900; font-style: italic; font-size: 40px; line-height: 1.05; letter-spacing: -1px; z-index: 1; text-transform: uppercase }
    .selo:before { content: ""; position: absolute; inset: 0; background: ${VERM}; border-radius: 10px 30px 14px 34px; transform: rotate(-1.5deg) skewX(-9deg); z-index: -1 }
    .tit { font-weight: 900; font-style: italic; font-size: 46px; line-height: 1; letter-spacing: -1px; text-transform: uppercase }
    .sub { font-weight: 800; font-size: 37px; line-height: 1; white-space: nowrap }
    .sub b { color: ${OURO}; font-weight: 900 }
    .precos { position: absolute; left: 748px; top: 220px; width: 304px; display: flex; flex-direction: column; gap: 3px }
    .pr { display: flex; align-items: center; justify-content: space-between; font-weight: 800; font-size: 19px; line-height: 1; white-space: nowrap }
    .pr b { background: ${VERM}; border: 2px solid ${OURO}; border-radius: 20px; padding: 1px 9px 2px; font-weight: 900; font-size: 19px }
  </style></head><body>
    <div class="data">${esc(spec.data)}</div>
    <div class="meio"><div class="l1"><span class="selo">${esc(spec.selo)}</span><span class="tit">${esc(spec.titulo)}</span></div><div class="sub">${spec.sub}</div></div>
    <div class="precos">${spec.precos.map(c => `<div class="pr"><span>${esc(c[0])}</span><b>R$ ${esc(c[1])}</b></div>`).join('')}</div>
  </body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await p.setContent(html); await p.waitForTimeout(400);
  const av = await p.evaluate(() => [['.meio', 150, 1050, 110, 212], ['.precos', 745, 1055, 214, 310], ['.data', 140, 730, 10, 112]].map(([s, x0, x1, y0, y1]) => {
    const e = document.querySelector(s); let l = 1e9, r = 0, t = 1e9, bt = 0;
    for (const c of e.querySelectorAll('*')) { const q = c.getBoundingClientRect(); if (q.width) { l = Math.min(l, q.left); r = Math.max(r, q.right); t = Math.min(t, q.top); bt = Math.max(bt, q.bottom); } }
    if (l === 1e9) { const q = e.getBoundingClientRect(); l = q.left; r = q.right; t = q.top; bt = q.bottom; }
    return `${l < x0 || r > x1 || t < y0 || bt > y1 ? 'ATENÇÃO fora da área segura' : 'ok'} ${s}: x ${Math.round(l)}-${Math.round(r)} (área ${x0}-${x1}), y ${Math.round(t)}-${Math.round(bt)} (área ${y0}-${y1})`; }));
  av.forEach(a => console.log(a));
  await p.screenshot(/\.png$/i.test(out) ? { path: out } : { path: out, type: 'jpeg', quality: 93 });
  if (prev) {                                                       // como o site corta: celular e computador
    await p.screenshot({ path: path.join(prev, 'banner_corte_celular.png'), clip: { x: 132, y: 0, width: 936, height: 400 } });
    await p.screenshot({ path: path.join(prev, 'banner_corte_computador.png'), clip: { x: 0, y: 88, width: 1200, height: 224 } });
  }
  await b.close(); console.log('ok', out, `${W}x${H}`);
})();
