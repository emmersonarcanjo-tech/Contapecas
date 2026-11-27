// Etiquetas de preço para o buffet, em folhas A4 para imprimir e recortar (8 por folha, 95 x 66,5 mm cada), nas cores da Tili.
// Uso: node etiquetas.js <spec.json> <saida.pdf> [previa.png]
// spec: { "logo", "whatsapp" (opcional; padrão = marca_tili_sushi.json),
//         "etiquetas": [ { "tipo": "black" | "normal", "nome", "preco": "1,99", "de": "2,99" (opcional), "un": "a peça", "qtd": 2 } ] }
// "black" = fundo preto com selo Black Friday; "normal" = fundo branco (gasta menos tinta).
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const VERM = '#C8102E', OURO = '#D4A017', PRETO = '#1A1A1A';
(async () => {
  const specPath = path.resolve(process.argv[2]), out = path.resolve(process.argv[3]); const prev = process.argv[4] ? path.resolve(process.argv[4]) : null;
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8')); const base = path.dirname(specPath);
  const marca = JSON.parse(fs.readFileSync(path.join(__dirname, 'marca_tili_sushi.json'), 'utf8')); const zap = spec.whatsapp || marca.whatsapp;
  const logo = `data:image/png;base64,${fs.readFileSync(path.resolve(base, spec.logo)).toString('base64')}`;
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const lista = spec.etiquetas.flatMap(e => Array.from({ length: e.qtd || 1 }, () => e));
  const tag = e => { const [r, c] = String(e.preco).split(','); const bl = e.tipo === 'black';
    return `<div class="tag ${bl ? 'bl' : 'nm'}">
      <div class="topo">${bl ? '<span class="selo">Black Friday</span>' : '<span class="marca">Tili Sushi</span>'}<span class="logo"><img src="${logo}"></span></div>
      <div class="nome">${esc(e.nome)}</div>
      <div class="linha"><div class="esq">${e.de ? `<div class="de">de <s>R$ ${esc(e.de)}</s> por</div>` : ''}<div class="un">${esc(e.un || 'a peça')}</div></div>
        <div class="preco"><span class="rs">R$</span><span class="v">${esc(r)}</span><span class="c">,${esc(c)}</span></div></div>
      <div class="rod">${esc(marca.assinatura)} · WhatsApp ${esc(zap)}</div></div>`; };
  const paginas = []; for (let i = 0; i < lista.length; i += 8) paginas.push(lista.slice(i, i + 8));
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    @page { size: 210mm 297mm; margin: 0 }
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact }
    body { font-family: Inter, Arial, sans-serif }
    .folha { width: 210mm; height: 297mm; padding: 8mm 8mm; display: grid; grid-template-columns: 95mm 95mm; grid-auto-rows: 66.5mm; gap: 4mm; justify-content: center; page-break-after: always; overflow: hidden }
    .folha:last-child { page-break-after: auto }
    .tag { position: relative; overflow: hidden; border: 0.3mm dashed #888; border-radius: 3mm; padding: 4mm 5mm 3mm; display: flex; flex-direction: column }
    .bl { color: #fff; background: radial-gradient(70mm 30mm at 40% 0%, rgba(200,16,46,.55), rgba(200,16,46,0) 72%), #0c0c0c }
    .nm { color: ${PRETO}; background: #fff; border-top: 3mm solid ${VERM} }
    .topo { display: flex; align-items: center; justify-content: space-between; height: 11mm; flex: none }
    .selo { position: relative; display: inline-block; padding: 0.6mm 4mm 1.2mm; font-weight: 900; font-style: italic; font-size: 15pt; letter-spacing: -0.3px; text-transform: uppercase; z-index: 1; color: #fff }
    .selo:before { content: ""; position: absolute; inset: 0; background: ${VERM}; border-radius: 1.6mm 5mm 2mm 5.5mm; transform: rotate(-2deg) skewX(-9deg); z-index: -1 }
    .marca { font-weight: 900; font-size: 12pt; letter-spacing: 2px; text-transform: uppercase; color: ${VERM} }
    .logo { width: 10.5mm; height: 10.5mm; background: #fff; border-radius: 2mm; display: flex; align-items: center; justify-content: center; flex: none; border: 0.2mm solid #ddd }
    .logo img { width: 86%; height: 84%; object-fit: contain }
    .nome { font-weight: 900; font-size: 27pt; line-height: 1; letter-spacing: -0.8px; text-transform: uppercase; margin-top: 2.5mm; white-space: nowrap; flex: none }
    .linha { flex: 1; display: flex; align-items: center; justify-content: space-between; gap: 3mm; min-height: 0 }
    .de { font-weight: 700; font-size: 11.5pt; line-height: 1.1 }
    .bl .de { color: rgba(255,255,255,.9) } .nm .de { color: #444 }
    .de s { text-decoration-thickness: 1.5px }
    .un { font-weight: 900; font-size: 14pt; text-transform: uppercase; letter-spacing: 1px; margin-top: 1mm; color: ${OURO} }
    .nm .un { color: ${VERM} }
    .preco { background: ${VERM}; color: #fff; border: 0.9mm solid ${OURO}; border-radius: 20mm; padding: 0.5mm 6mm 1.2mm; display: inline-flex; align-items: flex-start; gap: 1mm; font-weight: 900; white-space: nowrap; flex: none }
    .preco .rs { font-size: 15pt; margin-top: 7mm }
    .preco .v { font-size: 50pt; line-height: 1.08; letter-spacing: -2px }
    .preco .c { font-size: 22pt; margin-top: 2.8mm }
    .rod { font-size: 7pt; font-weight: 600; flex: none; text-align: center; letter-spacing: .3px }
    .bl .rod { color: rgba(255,255,255,.75) } .nm .rod { color: #555 }
  </style></head><body>${paginas.map(pg => `<div class="folha">${pg.map(tag).join('')}</div>`).join('')}</body></html>`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 794, height: 1123 }, deviceScaleFactor: 2 });
  await p.setContent(html); await p.waitForTimeout(500);
  const av = await p.evaluate(() => [...document.querySelectorAll('.tag')].map((t, i) => { const n = t.querySelector('.nome'); const l = t.querySelector('.linha'); return (n.scrollWidth > n.clientWidth + 1 || l.scrollWidth > l.clientWidth + 1 || t.scrollHeight > t.clientHeight + 1) ? `ATENÇÃO etiqueta ${i + 1} (${n.textContent}) estourou` : null; }).filter(Boolean));
  av.forEach(a => console.log(a));
  if (prev) await p.screenshot({ path: prev, fullPage: true });
  await p.pdf({ path: out, width: '210mm', height: '297mm', printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await b.close(); console.log('ok', out, '|', lista.length, 'etiquetas em', paginas.length, 'folha(s)');
})();
