// Arte de "várias ofertas do dia" (ex.: Black Friday no salão): selo + oferta em destaque com foto + ofertas menores +
// faixa de aviso (ex.: só no salão) + WhatsApp e logo, nas cores da Tili (preto, vermelho C8102E, dourado D4A017).
// Usa SOMENTE fotos da própria Tili (as do cardápio do ALIV, guardadas em marketing/fotos).
// Uso: node arte_ofertas.js <spec.json> <saida.jpg|png> [feed|story]      feed = 1080x1350 · story = 1080x1920
// spec: { "selo", "data", "destaque": { "titulo", "de", "preco", "foto", "pos" },
//         "ofertas": [ { "titulo", "sub", "prefixo", "preco", "foto", "pos" } ],
//         "faixa": { "titulo", "sub" }, "obs", "zap_rotulo", "logo" }      (caminhos relativos ao spec)
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017';
(async () => {
  const specPath = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]); const fmt = process.argv[4] || 'feed';
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); const base = path.dirname(specPath);
  const marca = JSON.parse(fs.readFileSync(path.join(__dirname, 'marca_tili_sushi.json'), 'utf8'));   // WhatsApp e assinatura da marca: um lugar só
  spec.whatsapp = spec.whatsapp || marca.whatsapp; spec.assinatura = spec.assinatura || marca.assinatura;
  const uri = f => { const p = path.resolve(base, f); const m = /\.webp$/i.test(p) ? 'image/webp' : /\.png$/i.test(p) ? 'image/png' : 'image/jpeg';
                     return `data:${m};base64,${fs.readFileSync(p).toString('base64')}`; };
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const story = fmt === 'story'; const W = 1080, H = story ? 1920 : 1350;
  // story: mesmo desenho do feed, centrado; nada nos 250 px de cima e de baixo (ficam atrás dos botões do Instagram)
  const k = story ? { padX: 54, top: 250, bot: 260, gap: 34, selo: 92, data: 28, hdest: 438, tit: 92, de: 32, preco: 146, cent: 66, ofoto: 168, otit: 38, osub: 24, opre: 70, ocent: 33, opref: 22, ftit: 82, fsub: 35, obs: 25, zap: 46, zapl: 25, ass: 23, logo: 132 }
                  : { padX: 44, top: 40, bot: 38, gap: 20, selo: 84, data: 27, hdest: 0, tit: 92, de: 32, preco: 150, cent: 68, ofoto: 172, otit: 39, osub: 24, opre: 70, ocent: 33, opref: 22, ftit: 76, fsub: 35, obs: 25, zap: 44, zapl: 24, ass: 22, logo: 124 };
  Object.assign(k, (spec.ajuste || {})[fmt] || {});
  const preco = (v, cls) => { const [r, c] = String(v).split(','); return `<div class="preco ${cls || ''}"><span class="rs">R$</span><span class="v">${esc(r)}</span><span class="c">,${esc(c)}</span></div>`; };
  const d = spec.destaque;
  const textoDestaque = `<div class="dtxt"><h1>${d.titulo}</h1>${d.de ? `<div class="de">de <s>R$ ${esc(d.de)}</s> por</div>` : ''}${preco(d.preco)}</div>`;
  const fotoDestaque = `<div class="dfoto"><img src="${uri(d.foto)}" style="object-position:${d.pos || '50% 50%'}"></div>`;
  const ofertas = spec.ofertas.map(o => `<div class="of"><div class="ofoto"><img src="${uri(o.foto)}" style="object-position:${o.pos || '50% 50%'}"></div>
      <div class="otxt"><div class="otit">${o.titulo}</div>${o.sub ? `<div class="osub">${esc(o.sub)}</div>` : ''}
      <div class="opl">${o.prefixo ? `<span class="opref">${esc(o.prefixo)}</span>` : ''}${preco(o.preco, 'p2')}</div></div></div>`).join('');
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; margin: 0; padding: 0 }
    body { width: ${W}px; height: ${H}px; font-family: Inter, Arial, sans-serif; color: #fff; overflow: hidden;
           background: radial-gradient(${W}px ${H * .40}px at 50% 0%, rgba(200,16,46,.46), rgba(200,16,46,0) 72%), radial-gradient(${W * .9}px ${H * .30}px at 50% 100%, rgba(212,160,23,.13), rgba(212,160,23,0) 70%), #0c0c0c }
    .pg { position: absolute; inset: 0; padding: ${k.top}px ${k.padX}px ${k.bot}px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: ${k.gap}px }
    .selo { position: relative; display: inline-block; padding: ${k.selo * .10}px ${k.selo * .62}px ${k.selo * .15}px; font-weight: 900; font-style: italic; font-size: ${k.selo}px; line-height: 1.05; letter-spacing: -1px; z-index: 1; text-transform: uppercase; flex: none }
    .selo:before { content: ""; position: absolute; inset: 0; background: ${VERM}; border-radius: ${k.selo * .22}px ${k.selo * .7}px ${k.selo * .3}px ${k.selo * .8}px; transform: rotate(-2deg) skewX(-9deg); z-index: -1; box-shadow: ${k.selo * .12}px ${k.selo * .1}px 0 rgba(200,16,46,.35) }
    .selo b { color: ${OURO} }
    .data { font-weight: 800; font-size: ${k.data}px; letter-spacing: 3px; text-transform: uppercase; color: ${OURO}; flex: none; margin-top: ${-k.gap * .15}px }
    .dest { width: 100%; display: flex; align-items: center; gap: 34px; ${k.hdest ? `flex: none; height: ${k.hdest}px` : 'flex: 1 1 0'}; min-height: 0 }
    .dfoto { height: 100%; aspect-ratio: 1 / 1; flex: none; border-radius: 30px; overflow: hidden; border: 4px solid ${OURO}; box-shadow: 0 18px 44px rgba(0,0,0,.7) }
    .dfoto img, .ofoto img { width: 100%; height: 100%; object-fit: cover; display: block }
    .dtxt { flex: 1; display: flex; flex-direction: column; align-items: flex-start; min-width: 0 }
    h1 { font-weight: 900; font-size: ${k.tit}px; line-height: .98; letter-spacing: -2px; text-transform: uppercase; text-shadow: 0 4px 20px rgba(0,0,0,.7) }
    h1 b { color: ${OURO} }
    .de { font-weight: 700; font-size: ${k.de}px; color: rgba(255,255,255,.82); margin: ${k.de * .5}px 0 ${k.de * .3}px; font-style: italic }
    .de s { text-decoration-thickness: 3px; text-decoration-color: ${VERM} }
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
    .ofoto { width: ${k.ofoto}px; height: ${k.ofoto}px; flex: none; border-radius: 20px; overflow: hidden; border: 3px solid ${OURO} }
    .otxt { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start }
    .otit { font-weight: 900; font-size: ${k.otit}px; line-height: 1; letter-spacing: -1px; text-transform: uppercase }
    .osub { font-weight: 700; font-size: ${k.osub}px; color: ${OURO}; font-style: italic; margin-top: ${k.osub * .25}px; line-height: 1.1 }
    .opl { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; margin-top: ${k.osub * .45}px }
    .opref { font-weight: 800; font-size: ${k.opref}px; color: #fff; font-style: italic }
    .faixa { align-self: stretch; margin: 0 ${-k.padX}px; background: ${VERM}; border-top: 4px solid ${OURO}; border-bottom: 4px solid ${OURO}; padding: ${k.ftit * .16}px ${k.padX}px ${k.ftit * .2}px; text-align: center; flex: none; box-shadow: 0 10px 34px rgba(200,16,46,.35) }
    .faixa .t { font-weight: 900; font-style: italic; font-size: ${k.ftit}px; line-height: 1; letter-spacing: -1px; text-transform: uppercase }
    .faixa .s { font-weight: 800; font-size: ${k.fsub}px; margin-top: ${k.fsub * .2}px; color: #fff }
    .faixa .s b { color: #ffd65c }
    .obs { font-weight: 700; font-size: ${k.obs}px; color: rgba(255,255,255,.9); text-align: center; flex: none; margin: ${-k.gap * .3}px 0 }
    .obs b { color: ${OURO} }
    .rod { ${k.hdest ? '' : 'margin-top: auto;'} width: 100%; display: flex; align-items: center; justify-content: space-between; border-top: 3px solid ${VERM}; padding-top: ${k.gap * .7}px; flex: none }
    .zap .l { font-size: ${k.zapl}px; font-weight: 600; color: rgba(255,255,255,.85) }
    .zap .t { font-size: ${k.zap}px; font-weight: 900; color: ${OURO}; letter-spacing: .5px; line-height: 1.1 }
    .zap .a { font-size: ${k.ass}px; font-weight: 600; color: rgba(255,255,255,.7); margin-top: ${k.ass * .2}px }
    .logo { width: ${k.logo}px; height: ${k.logo}px; background: #fff; border-radius: ${k.logo * .18}px; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 26px rgba(0,0,0,.55); flex: none }
    .logo img { width: 86%; height: 84%; object-fit: contain }
  </style></head><body><div class="pg">
    <div class="selo">${spec.selo}</div>
    ${spec.data ? `<div class="data">${esc(spec.data)}</div>` : ''}
    <div class="dest">${fotoDestaque}${textoDestaque}</div>
    <div class="ofs">${ofertas}</div>
    <div class="faixa"><div class="t">${esc(spec.faixa.titulo)}</div>${spec.faixa.sub ? `<div class="s">${spec.faixa.sub}</div>` : ''}</div>
    ${spec.obs ? `<div class="obs">${spec.obs}</div>` : ''}
    <div class="rod"><div class="zap"><div class="l">${esc(spec.zap_rotulo || 'WhatsApp')}</div><div class="t">${esc(spec.whatsapp)}</div><div class="a">${esc(spec.assinatura)}</div></div>
      <div class="logo"><img src="${uri(spec.logo)}"></div></div>
  </div></body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await p.setContent(html); await p.waitForTimeout(500);
  // confere se algo saiu da área útil ou ficou cortado
  const aviso = await p.evaluate(({ H, top, bot }) => {
    const r = [];
    for (const s of ['.selo', '.data', '.dest', '.dfoto', '.dtxt', '.ofs', '.faixa', '.obs', '.rod']) {
      const e = document.querySelector(s); if (!e) continue; const q = e.getBoundingClientRect();
      if (q.top < top - 30 || q.bottom > H - bot + 2 || q.left < -1 || q.right > 1081) r.push(`${s} fora da área: ${Math.round(q.left)},${Math.round(q.top)} a ${Math.round(q.right)},${Math.round(q.bottom)}`);
    }
    for (const e of document.querySelectorAll('.dtxt, .otxt, .of')) if (e.scrollWidth > e.clientWidth + 1) r.push(`texto cortado em .${e.className}: ${e.scrollWidth} > ${e.clientWidth}`);
    const q = document.querySelector('.dfoto').getBoundingClientRect(); r.push(`foto do destaque: ${Math.round(q.width)}x${Math.round(q.height)}`);
    return r;
  }, { H, top: k.top, bot: k.bot });
  aviso.forEach(a => console.log(a));
  await p.screenshot(/\.png$/i.test(out) ? { path: out } : { path: out, type: 'jpeg', quality: 93 });
  await b.close(); console.log('ok', out, `${W}x${H}`);
})();
