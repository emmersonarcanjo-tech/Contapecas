// Arte quadrada (1080x1080) de um combo para o cardápio do ALIV, com as fotos dos próprios produtos da Tili.
// Uso: node arte_combo.js <spec.json> <saida.png>
// spec: { "selo": "BLACK FRIDAY", "titulo": "COMBO 22 PEÇAS", "rodape": "4 Niguiri · ...", "logo": "caminho.png",
//         "pecas": [ { "foto": "caminho.webp", "qtd": 4, "nome": "Niguiri Salmão" }, ... ] }   (caminhos relativos ao spec)
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017', PRETO = '#1A1A1A';
(async () => {
  const specPath = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]);
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); const base = path.dirname(specPath);
  const uri = f => { const p = path.resolve(base, f); const m = /\.webp$/i.test(p) ? 'image/webp' : /\.png$/i.test(p) ? 'image/png' : 'image/jpeg';
                     return `data:${m};base64,${fs.readFileSync(p).toString('base64')}`; };
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const cols = spec.pecas.length <= 4 ? 2 : 3, linhas = Math.ceil(spec.pecas.length / cols);
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; margin: 0; padding: 0 }
    body { width: 1080px; height: 1080px; font-family: Inter, Arial, sans-serif; color: #fff; overflow: hidden;
           background: radial-gradient(900px 520px at 0% 0%, rgba(200,16,46,.55), rgba(200,16,46,0) 70%), radial-gradient(700px 500px at 100% 100%, rgba(212,160,23,.16), rgba(212,160,23,0) 70%), #0e0e0e; }
    .pg { position: absolute; inset: 0; padding: 40px 44px; display: flex; flex-direction: column; gap: 22px }
    .topo { display: flex; align-items: center; justify-content: space-between; height: 168px }
    .selo { display: inline-block; background: ${VERM}; color: #fff; font-weight: 800; font-size: 30px; letter-spacing: 6px; padding: 8px 22px 9px; border-radius: 10px; transform: rotate(-2deg) }
    h1 { font-weight: 900; font-size: 84px; line-height: 1; letter-spacing: -1px; margin-top: 16px; text-shadow: 0 4px 18px rgba(0,0,0,.6) }
    h1 b { color: ${OURO}; font-weight: 900 }
    .logo { width: 150px; height: 150px; background: #fff; border-radius: 26px; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 26px rgba(0,0,0,.55); flex: none }
    .logo img { width: 128px; height: 124px; object-fit: contain }
    .grade { flex: 1; display: grid; grid-template-columns: repeat(${cols}, 1fr); grid-template-rows: repeat(${linhas}, 1fr); gap: 18px; min-height: 0 }
    .peca { position: relative; border-radius: 24px; overflow: hidden; border: 3px solid ${OURO}; background: ${PRETO}; box-shadow: 0 10px 26px rgba(0,0,0,.5) }
    .peca img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover }
    .peca .sombra { position: absolute; left: 0; right: 0; bottom: 0; height: 52%; background: linear-gradient(to top, rgba(0,0,0,.92), rgba(0,0,0,0)) }
    .peca .nome { position: absolute; left: 16px; right: 16px; bottom: 14px; font-weight: 800; font-size: 27px; line-height: 1.12; text-shadow: 0 2px 8px #000 }
    .peca .qtd { position: absolute; left: 12px; top: 12px; min-width: 84px; height: 84px; padding: 0 10px; border-radius: 42px; background: ${VERM}; border: 4px solid #fff;
                 display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 46px; box-shadow: 0 6px 16px rgba(0,0,0,.6) }
    .peca .qtd small { font-size: 26px; font-weight: 800; margin-left: 2px }
    .rodape { height: 86px; display: flex; align-items: center; justify-content: center; border-top: 4px solid ${VERM}; color: ${OURO}; font-weight: 800; font-size: 35px; letter-spacing: .5px; text-align: center }
  </style></head><body><div class="pg">
    <div class="topo"><div>${spec.selo ? `<span class="selo">${esc(spec.selo)}</span>` : ''}<h1>${spec.titulo}</h1></div>
      <div class="logo"><img src="${uri(spec.logo)}"></div></div>
    <div class="grade">${spec.pecas.map(p => `<div class="peca"><img src="${uri(p.foto)}"><div class="sombra"></div><div class="qtd">${p.qtd}<small>x</small></div><div class="nome">${esc(p.nome)}</div></div>`).join('')}</div>
    <div class="rodape">${esc(spec.rodape)}</div>
  </div></body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1080, height: 1080 }, deviceScaleFactor: 1 });
  await p.setContent(html, { waitUntil: 'load' }); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
  await p.screenshot({ path: out, type: /\.jpe?g$/i.test(out) ? 'jpeg' : 'png', quality: /\.jpe?g$/i.test(out) ? 90 : undefined }); await b.close();
  console.log('ok', out);
})();
