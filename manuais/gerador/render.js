const { chromium } = require('playwright');
const [html, pdf, prev] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch();
  const pg = await b.newPage({ viewport: { width: 794, height: 1123 } });
  await pg.goto('file://' + html);
  await pg.waitForTimeout(400);
  const ajustadas = await pg.evaluate(() => {
    let n = 0;
    for (const p of document.querySelectorAll('.pg')) {
      const c = p.querySelector('.corpo'), r = p.querySelector('.rod');
      if (!c || !r) continue;
      let z = 1;
      while (c.getBoundingClientRect().bottom > r.getBoundingClientRect().top - 6 && z > 0.6) {
        z -= 0.03; c.style.zoom = z;
      }
      if (z < 1) n++;
    }
    return n;
  });
  console.log('páginas reduzidas para caber:', ajustadas);
  await pg.pdf({ path: pdf, format: 'A4', printBackground: true, preferCSSPageSize: true });
  if (prev) {
    const els = await pg.$$('.pg');
    for (let i = 0; i < els.length; i++)
      await els[i].screenshot({ path: `${prev}/p${String(i + 1).padStart(2, '0')}.png` });
  }
  await b.close();
})();
