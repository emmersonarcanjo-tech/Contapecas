// Exporta a "Apuração de jornadas" do Flit Gestor (headless, só leitura) e grava em JSON.
// Uso: node flit_apuracao.js DD/MM/AAAA DD/MM/AAAA saida.json   (login: FLIT_USER / FLIT_PASS)
// O arquivo do Flit é capturado na memória da página (sem download), como no RUNBOOK.
const { chromium } = require('playwright');
const fs = require('fs');
const [ini, fim, saida] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  try {
    await p.goto('https://manager.flitapp.com.br/login', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await p.waitForSelector('#mat-input-0', { timeout: 60000 });
    await p.fill('#mat-input-0', process.env.FLIT_USER || '');
    await p.fill('input[type=password]', process.env.FLIT_PASS || '');
    await p.locator('button[type=submit]', { hasText: 'Entrar' }).first().click();
    await p.waitForURL(u => !u.toString().includes('/login'), { timeout: 30000 });
    await p.goto('https://manager.flitapp.com.br/relatorios-adicionais', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await p.waitForSelector('mat-select', { timeout: 30000 });
    const r = await p.evaluate(async ([INI, FIM]) => {
      const s = ms => new Promise(r => setTimeout(r, ms));
      window.__blobs = []; const o = URL.createObjectURL.bind(URL);
      URL.createObjectURL = b => { const u = o(b); window.__blobs.push(b); return u; };
      const oc = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = function () { if ((this.href || '').startsWith('blob:')) return; return oc.apply(this, arguments); };
      document.querySelector('mat-select').click(); await s(800);
      const opt = Array.from(document.querySelectorAll('.cdk-overlay-container mat-option')).find(o => o.innerText.trim() === 'Apuração de jornadas');
      if (!opt) return { erro: 'opção Apuração de jornadas não encontrada' };
      opt.click(); await s(700);
      const set = (e, v) => { const st = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; st.call(e, v);
        e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); e.blur(); e.dispatchEvent(new Event('blur', { bubbles: true })); };
      const ins = document.querySelectorAll('input[placeholder="Data inicial"],input[placeholder="Data final"]');
      set(ins[0], INI); set(ins[1], FIM); await s(900);
      const n0 = window.__blobs.length; document.querySelector('button[aria-label="Export button"]').click();
      const t0 = Date.now(); while (window.__blobs.length === n0 && Date.now() - t0 < 60000) await s(400);
      if (window.__blobs.length === n0) return { erro: 'timeout na exportação' };
      const buf = new Uint8Array(await window.__blobs[window.__blobs.length - 1].arrayBuffer());
      const dv = new DataView(buf.buffer); const td = new TextDecoder(); const files = {}; let q = 0;
      while (q + 30 <= buf.length && dv.getUint32(q, true) === 0x04034b50) {
        const m = dv.getUint16(q + 8, true), cs = dv.getUint32(q + 18, true), nl = dv.getUint16(q + 26, true), el = dv.getUint16(q + 28, true);
        const nm = td.decode(buf.subarray(q + 30, q + 30 + nl)); const d0 = q + 30 + nl + el; const dt = buf.subarray(d0, d0 + cs);
        files[nm] = m === 0 ? td.decode(dt) : await new Response(new Blob([dt]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();
        q = d0 + cs;
      }
      const dec = s => s.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'");
      const ss = []; for (const m of (files['xl/sharedStrings.xml'] || '').matchAll(/<si>([\s\S]*?)<\/si>/g))
        ss.push(dec(Array.from(m[1].matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)).map(x => x[1]).join('')));
      const sheet = Object.entries(files).find(([n]) => /worksheets\/sheet1\.xml/.test(n))[1]; const R = [];
      for (const rm of sheet.matchAll(/<row[^>]*>([\s\S]*?)<\/row>/g)) { const c = {};
        for (const cm of rm[1].matchAll(/<c r="([A-Z]+)\d+"([^>]*)>([\s\S]*?)<\/c>/g)) {
          let v = (cm[3].match(/<v>([\s\S]*?)<\/v>/) || [])[1];
          if (v === undefined) v = (cm[3].match(/<t[^>]*>([\s\S]*?)<\/t>/) || [])[1] || ''; else if (/t="s"/.test(cm[2])) v = ss[+v];
          c[cm[1].replace(/\d+/, '')] = dec(String(v)); }
        R.push(c); }
      const H = R[0];
      return { linhas: R.slice(1).filter(r => r.A).map(r => { const o = {}; Object.keys(H).forEach(k => o[H[k]] = r[k] || ''); return o; }) };
    }, [ini, fim]);
    if (r.erro) throw new Error(r.erro);
    fs.writeFileSync(saida, JSON.stringify(r.linhas));
    console.log(`apuração: ${r.linhas.length} linhas`);
  } catch (e) {
    console.error('FLIT ERRO: ' + String(e.message || e).split(process.env.FLIT_PASS || '\u0000').join('***'));
    process.exitCode = 1;
  } finally { await b.close(); }
})();
