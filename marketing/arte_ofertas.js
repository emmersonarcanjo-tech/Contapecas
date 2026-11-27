// Arte de "várias ofertas do dia" (ex.: Black Friday no salão): selo + oferta em destaque com foto + ofertas menores +
// faixa de aviso (ex.: só no salão) + WhatsApp e logo, nas cores da Tili (preto, vermelho C8102E, dourado D4A017).
// Usa SOMENTE fotos da própria Tili (as do cardápio do ALIV, guardadas em marketing/fotos).
// Uso: node arte_ofertas.js <spec.json> <saida.jpg|png|pdf> [feed|story|a4] [previa.png]
//      feed = 1080x1350 · story = 1080x1920 · a4 = folha A4 em pé para imprimir (saída .pdf; previa.png opcional)
// spec: { "selo", "data", "destaque": { "titulo", "de", "preco", "foto", "pos", "escurecer", "nota" },
//         "ofertas": [ { "titulo", "preco", "foto", "pos", "zoom", "origem", "escurecer" } ],
//         "faixa": { "titulo", "sub" }, "obs", "zap_rotulo", "logo" }      (caminhos relativos ao spec)
// Tamanhos mínimos pensados para o celular: no feed a arte encolhe para ~35%, então texto que importa tem 32 px ou mais.
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017';
(async () => {
  const specPath = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]); const fmt = process.argv[4] || 'feed';
  const previa = process.argv[5] ? path.resolve(process.argv[5]) : null;
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); const base = path.dirname(specPath);
  const marca = JSON.parse(fs.readFileSync(path.join(__dirname, 'marca_tili_sushi.json'), 'utf8'));   // WhatsApp e assinatura da marca: um lugar só
  spec.whatsapp = spec.whatsapp || marca.whatsapp; spec.assinatura = spec.assinatura || marca.assinatura;
  const uri = f => { const p = path.resolve(base, f); const m = /\.webp$/i.test(p) ? 'image/webp' : /\.png$/i.test(p) ? 'image/png' : 'image/jpeg';
                     return `data:${m};base64,${fs.readFileSync(p).toString('base64')}`; };
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const W = 1080, H = { feed: 1350, story: 1920, a4: 1527 }[fmt];          // a4: 1080 x 1527 px na proporção da folha (210 x 297 mm)
  if (!H) { console.error('formato desconhecido:', fmt); process.exit(2); }
  // story: mesmo desenho do feed, centrado; nada nos 250 px de cima e de baixo (ficam atrás dos botões do Instagram)
  const K = {
    feed:  { padX: 44, top: 38, bot: 36, gap: 18, selo: 82, data: 40, hdest: 0,   tit: 92,  de: 38, preco: 150, cent: 68, ofoto: 172, otit: 39, opre: 70, ocent: 33, ftit: 76, fsub: 35, obs: 34, zap: 44, zapl: 30, ass: 30, logo: 136, nota: 18 },
    story: { padX: 54, top: 266, bot: 276, gap: 28, selo: 88, data: 40, hdest: 452, tit: 90,  de: 38, preco: 146, cent: 66, ofoto: 168, otit: 38, opre: 70, ocent: 33, ftit: 80, fsub: 35, obs: 34, zap: 46, zapl: 30, ass: 30, logo: 140, nota: 18 },
    a4:    { padX: 56, top: 56, bot: 52, gap: 22, selo: 92, data: 42, hdest: 458, tit: 100, de: 40, preco: 150, cent: 68, ofoto: 166, otit: 40, opre: 74, ocent: 35, ftit: 86, fsub: 36, obs: 36, zap: 50, zapl: 31, ass: 31, logo: 150, nota: 19 },
  };
  const k = Object.assign({}, K[fmt], (spec.ajuste || {})[fmt] || {});
  const preco = (v, cls) => { const [r, c] = String(v).split(','); return `<div class="preco ${cls || ''}"><span class="rs">R$</span><span class="v">${esc(r)}</span><span class="c">,${esc(c)}</span></div>`; };
  const img = o => `<img src="${uri(o.foto)}" style="object-position:${o.pos || '50% 50%'}${o.zoom ? `;transform:scale(${o.zoom});transform-origin:${o.origem || '50% 50%'}` : ''}">`;
  const d = spec.destaque;
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    @page { size: 210mm 297mm; margin: 0 }
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact }
    html, body { width: ${W}px; height: ${H}px }
    body { font-family: Inter, Arial, sans-serif; color: #fff; overflow: hidden; position: relative;
           background: radial-gradient(${W}px ${H * .40}px at 50% 0%, rgba(200,16,46,.46), rgba(200,16,46,0) 72%), radial-gradient(${W * .9}px ${H * .30}px at 50% 100%, rgba(212,160,23,.13), rgba(212,160,23,0) 70%), #0c0c0c }
    .pg { position: absolute; inset: 0; padding: ${k.top}px ${k.padX}px ${k.bot}px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: ${k.gap}px }
    .selo { position: relative; display: inline-block; padding: ${k.selo * .10}px ${k.selo * .62}px ${k.selo * .15}px; font-weight: 900; font-style: italic; font-size: ${k.selo}px; line-height: 1.05; letter-spacing: -1px; z-index: 1; text-transform: uppercase; flex: none }
    .selo:before { content: ""; position: absolute; inset: 0; background: ${VERM}; border-radius: ${k.selo * .22}px ${k.selo * .7}px ${k.selo * .3}px ${k.selo * .8}px; transform: rotate(-2deg) skewX(-9deg); z-index: -1; box-shadow: ${k.selo * .12}px ${k.selo * .1}px 0 rgba(200,16,46,.35) }
    .data { font-weight: 900; font-size: ${k.data}px; letter-spacing: 3px; text-transform: uppercase; color: ${OURO}; flex: none; line-height: 1; margin-top: ${-k.gap * .1}px }
    .dest { width: 100%; display: flex; align-items: center; gap: 34px; ${k.hdest ? `flex: none; height: ${k.hdest}px` : 'flex: 1 1 0'}; min-height: 0 }
    .dfoto { height: 100%; aspect-ratio: 1 / 1; flex: none; border-radius: 30px; overflow: hidden; border: 4px solid ${OURO}; box-shadow: 0 18px 44px rgba(0,0,0,.7); position: relative }
    .dfoto img, .ofoto img { width: 100%; height: 100%; object-fit: cover; display: block }
    /* foto tirada sobre a mesa: escurece em cima e embaixo para a madeira sumir no fundo preto da arte */
    .esc:after { content: ""; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(11,11,11,.88) 0%, rgba(11,11,11,0) 22%, rgba(11,11,11,0) 76%, rgba(11,11,11,.88) 100%) }
    .nota { position: absolute; right: 16px; bottom: 9px; font-size: ${k.nota}px; font-style: italic; font-weight: 500; color: rgba(255,255,255,.78); z-index: 2 }
    .dtxt { flex: 1; display: flex; flex-direction: column; align-items: flex-start; min-width: 0 }
    h1 { font-weight: 900; font-size: ${k.tit}px; line-height: .98; letter-spacing: -2px; text-transform: uppercase; text-shadow: 0 4px 20px rgba(0,0,0,.7) }
    h1 b { color: ${OURO} }
    .de { font-weight: 700; font-size: ${k.de}px; color: rgba(255,255,255,.88); margin: ${k.de * .42}px 0 ${k.de * .26}px; line-height: 1 }
    .de s { text-decoration-thickness: 2px; text-decoration-color: rgba(255,255,255,.75) }
    .preco { background: ${VERM}; border-radius: ${k.preco}px; padding: ${k.preco * .05}px ${k.preco * .30}px ${k.preco * .07}px; display: inline-flex; align-items: flex-start; gap: ${k.preco * .06}px; font-weight: 900; box-shadow: 0 10px 30px rgba(200,16,46,.45); border: ${Math.round(k.preco * .035)}px solid ${OURO}; flex: none; white-space: nowrap }
    .preco .rs { font-size: ${k.cent * .8}px; margin-top: ${k.preco * .38}px }
    .preco .v { font-size: ${k.preco}px; line-height: 1.08; letter-spacing: -4px }
    .preco .c { font-size: ${k.cent}px; margin-top: ${k.preco * .14}px }
    .preco.p2 { border-radius: ${k.opre}px; padding: ${k.opre * .05}px ${k.opre * .28}px ${k.opre * .07}px; gap: ${k.opre * .06}px; border-width: 3px; box-shadow: 0 6px 18px rgba(200,16,46,.4) }
    .preco.p2 .rs { font-size: ${k.ocent * .8}px; margin-top: ${k.opre * .36}px }
    .preco.p2 .v { font-size: ${k.opre}px; letter-spacing: -2px }
    .preco.p2 .c { font-size: ${k.ocent}px; margin-top: ${k.opre * .13}px }
    .ofs { width: 100%; display: flex; gap: 18px; flex: none }
    .of { flex: 1; display: flex; align-items: center; gap: 18px; background: linear-gradient(160deg, #202020, #121212); border: 2px solid #343434; border-radius: 26px; padding: 16px; min-width: 0 }
    .ofoto { width: ${k.ofoto}px; height: ${k.ofoto}px; flex: none; border-radius: 20px; overflow: hidden; border: 3px solid ${OURO}; position: relative }
    .otxt { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: ${k.otit * .3}px }
    .otit { font-weight: 900; font-size: ${k.otit}px; line-height: 1.02; letter-spacing: -1px; text-transform: uppercase }
    .otit b { color: ${OURO} }
    .faixa { align-self: stretch; margin: 0 ${-k.padX}px; background: ${VERM}; border-top: 4px solid ${OURO}; border-bottom: 4px solid ${OURO}; padding: ${k.ftit * .16}px ${k.padX}px ${k.ftit * .2}px; text-align: center; flex: none; box-shadow: 0 10px 34px rgba(200,16,46,.35) }
    .faixa .t { font-weight: 900; font-style: italic; font-size: ${k.ftit}px; line-height: 1; letter-spacing: -1px; text-transform: uppercase }
    .faixa .s { font-weight: 700; font-size: ${k.fsub}px; margin-top: ${k.fsub * .2}px; color: #fff }
    .faixa .s b { font-weight: 900 }
    .obs { font-weight: 700; font-size: ${k.obs}px; color: rgba(255,255,255,.92); text-align: center; flex: none; line-height: 1; margin: ${-k.gap * .15}px 0 }
    .obs b { color: ${OURO} }
    .rod { ${k.hdest ? '' : 'margin-top: auto;'} width: 100%; display: flex; align-items: center; justify-content: space-between; border-top: 3px solid ${VERM}; padding-top: ${k.gap * .7}px; flex: none }
    .zap .l { font-size: ${k.zapl}px; font-weight: 600; color: rgba(255,255,255,.9); line-height: 1.15 }
    .zap .t { font-size: ${k.zap}px; font-weight: 900; color: ${OURO}; letter-spacing: .5px; line-height: 1.1 }
    .zap .a { font-size: ${k.ass}px; font-weight: 600; color: #e9e7e7; margin-top: ${k.ass * .1}px; line-height: 1.15 }
    .logo { width: ${k.logo}px; height: ${k.logo}px; background: #fff; border-radius: ${k.logo * .18}px; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 26px rgba(0,0,0,.55); flex: none }
    .logo img { width: 86%; height: 84%; object-fit: contain }
  </style></head><body><div class="pg">
    <div class="selo">${spec.selo}</div>
    ${spec.data ? `<div class="data">${esc(spec.data)}</div>` : ''}
    <div class="dest"><div class="dfoto${d.escurecer ? ' esc' : ''}">${img(d)}${d.nota ? `<div class="nota">${esc(d.nota)}</div>` : ''}</div>
      <div class="dtxt"><h1>${d.titulo}</h1>${d.de ? `<div class="de">de <s>R$ ${esc(d.de)}</s> por</div>` : ''}${preco(d.preco)}</div></div>
    <div class="ofs">${spec.ofertas.map(o => `<div class="of"><div class="ofoto${o.escurecer ? ' esc' : ''}">${img(o)}</div>
      <div class="otxt"><div class="otit">${o.titulo}</div>${preco(o.preco, 'p2')}</div></div>`).join('')}</div>
    <div class="faixa"><div class="t">${esc(spec.faixa.titulo)}</div>${spec.faixa.sub ? `<div class="s">${spec.faixa.sub}</div>` : ''}</div>
    ${spec.obs ? `<div class="obs">${spec.obs}</div>` : ''}
    <div class="rod"><div class="zap"><div class="l">${esc(spec.zap_rotulo || 'WhatsApp')}</div><div class="t">${esc(spec.whatsapp)}</div><div class="a">${esc(spec.assinatura)}</div></div>
      <div class="logo"><img src="${uri(spec.logo)}"></div></div>
  </div></body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await p.setContent(html); await p.waitForTimeout(500);
  // confere se algo saiu da área útil ou ficou cortado
  const aviso = await p.evaluate(({ H, top, bot }) => {
    const r = []; let y0 = 1e9, y1 = 0;
    for (const s of ['.selo', '.data', '.dest', '.dfoto', '.dtxt', '.ofs', '.faixa', '.obs', '.rod']) {
      const e = document.querySelector(s); if (!e) continue; const q = e.getBoundingClientRect(); y0 = Math.min(y0, q.top); y1 = Math.max(y1, q.bottom);
      if (q.top < top - 12 || q.bottom > H - bot + 2 || q.left < -1 || q.right > 1081) r.push(`ATENÇÃO ${s} fora da área: ${Math.round(q.left)},${Math.round(q.top)} a ${Math.round(q.right)},${Math.round(q.bottom)}`);
    }
    for (const e of document.querySelectorAll('.dtxt, .otxt, .of, .zap')) if (e.scrollWidth > e.clientWidth + 1) r.push(`ATENÇÃO texto cortado em .${e.className}: ${e.scrollWidth} > ${e.clientWidth}`);
    const q = document.querySelector('.dfoto').getBoundingClientRect();
    r.push(`conteúdo de y=${Math.round(y0)} a y=${Math.round(y1)} (altura ${H}) | foto do destaque ${Math.round(q.width)}x${Math.round(q.height)}`);
    return r;
  }, { H, top: k.top, bot: k.bot });
  aviso.forEach(a => console.log(a));
  if (/\.pdf$/i.test(out)) {
    if (previa) await p.screenshot({ path: previa });
    await p.emulateMedia({ media: 'screen' });
    await p.pdf({ path: out, width: '210mm', height: '297mm', printBackground: true, scale: (210 / 25.4 * 96) / W, margin: { top: 0, right: 0, bottom: 0, left: 0 }, pageRanges: '1' });
  } else await p.screenshot(/\.png$/i.test(out) ? { path: out } : { path: out, type: 'jpeg', quality: 93 });
  await b.close(); console.log('ok', out, fmt, `${W}x${H}`);
})();
