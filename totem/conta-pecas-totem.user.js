// ==UserScript==
// @name         Conta-Peças no totem (Tili Sushi)
// @namespace    https://emmersonarcanjo-tech.github.io/Contapecas/
// @version      1.0.7
// @description  Conta a bandeja do buffet pela câmera e coloca as peças na sacola do totem do ALIV. Quem cobra continua sendo o ALIV.
// @match        https://app.alivhub.com.br/kiosk/*
// @require      https://emmersonarcanjo-tech.github.io/Contapecas/prompt.js
// @grant        none
// @run-at       document-idle
// ==/UserScript==

/*
 * Como funciona
 * - Põe um botão "Contar bandeja" na tela do totem do ALIV.
 * - A câmera conta a bandeja (Claude) e mostra as marcas: amarela = peça, laranja = em dúvida.
 * - Peça em dúvida: só o atendente (com a senha) confirma. Sem dúvida: o cliente toca "Colocar na sacola".
 * - As peças entram na sacola do ALIV (window.CART), com o produto e o preço do cardápio do totem.
 *   Daí em diante é o próprio ALIV que fecha o pedido, cobra (Pix/maquininha) e emite a nota.
 * - Este complemento NÃO cria pedido, NÃO cobra e NÃO fala com o servidor do ALIV.
 */
(function () {
  'use strict';
  if (window.__contaPecasTotem) return;
  window.__contaPecasTotem = true;

  var TIPOS = { niguiri: 'Nigiri', sashimi: 'Sashimi', joy: 'Joy', ura: 'Uramaki', hosso: 'Hossomaki', hot: 'Hot roll', acara: 'Acarajapa', outro: 'Outros' };
  // Produto padrão de cada tipo, pelo nome no cardápio do totem (dá para trocar em ⚙).
  // Produto de cada tipo pelo nome no cardápio do totem (categoria "Buffet por peça (totem)").
  // Hossomaki, Uramaki e Hot têm um produto de quarta (R$ 1,99) com o mesmo nome: o ALIV só
  // mostra no totem o do dia, então o preço certo vem sozinho. Dá para trocar em ⚙.
  var PB = function (n) { return new RegExp('^' + n + ' \\(pe[çc]a buffet\\)$', 'i'); };
  var PADRAO = {
    niguiri: [PB('nigiri')], sashimi: [PB('sashimi')], joy: [PB('joy')],
    ura: [PB('uramaki')], hosso: [PB('hossomaki')], hot: [PB('hot roll')],
    acara: [PB('acarajapa')], outro: [PB('outras pe[çc]as')]
  };
  var MODELOS = { preciso: 'claude-sonnet-5-5', rapido: 'claude-haiku-5-5' };
  var CFG_KEY = 'conta_pecas_totem';
  var cfg = { key: '', modo: 'preciso', camId: '', pin: '', mapa: {}, auto: true };
  try { Object.assign(cfg, JSON.parse(localStorage.getItem(CFG_KEY) || '{}')); } catch (e) { }
  function salvarCfg() { try { localStorage.setItem(CFG_KEY, JSON.stringify(cfg)); } catch (e) { } }

  var st = { pecas: [], w: 0, h: 0, ia: null, obs: '', contando: false, liberado: false, stream: null, timer: null, ultimo: null, estavelDesde: 0, ultContado: null, vazio: null };

  // ---------- cardápio do totem ----------
  function produtos() {
    var out = [];
    (window.MENU_DATA || []).forEach(function (c) { (c.items || []).forEach(function (p) { if (p && p.is_active !== false) out.push(p); }); });
    return out;
  }
  function produtoDe(tipo) {
    var lista = produtos(), id = cfg.mapa[tipo];
    if (id) { for (var i = 0; i < lista.length; i++) if (String(lista[i].id) === String(id)) return lista[i]; }
    var regras = PADRAO[tipo] || PADRAO.outro;
    for (var r = 0; r < regras.length; r++) for (var j = 0; j < lista.length; j++) if (regras[r].test(String(lista[j].name || '').trim())) return lista[j];
    return null;
  }
  function brl(v) { return 'R$ ' + (Math.round(v * 100) / 100).toFixed(2).replace('.', ','); }

  // ---------- interface ----------
  var css = document.createElement('style');
  css.textContent = [
    '#cpt-btn{position:fixed;left:24px;bottom:24px;z-index:2147483000;background:#D62828;color:#fff;border:0;border-radius:999px;padding:22px 34px;font:800 26px system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.35)}',
    '#cpt{position:fixed;inset:0;z-index:2147483001;background:#141112;color:#F5F0EE;font:16px system-ui,sans-serif;display:flex;flex-direction:column;gap:12px;padding:16px}',
    '#cpt[hidden]{display:none}',
    '#cpt .topo{display:flex;align-items:center;gap:12px}#cpt .topo b{font:800 26px system-ui;flex:1}',
    '#cpt button{border:0;border-radius:14px;padding:16px 22px;font:700 20px system-ui;background:#272122;color:#F5F0EE}',
    '#cpt button.pri{background:#1B8A4A;color:#fff}#cpt button.red{background:#D62828;color:#fff}#cpt button:disabled{opacity:.45}',
    '#cpt .palco{position:relative;flex:1;min-height:0;background:#000;border-radius:16px;overflow:hidden}',
    '#cpt video,#cpt img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}',
    '#cpt .camada{position:absolute}',
    '#cpt .m{position:absolute;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;background:#FFB800;color:#1A1A1A;font:800 15px system-ui;display:grid;place-items:center;border:2px solid #1A1A1A;padding:0}',
    '#cpt .m.inc{background:#FF7A00;color:#fff;border-color:#fff;box-shadow:0 0 0 4px rgba(255,122,0,.45)}',
    '#cpt .status{font:600 18px system-ui;color:#F2A93B;min-height:24px}',
    '#cpt .res{display:flex;flex-wrap:wrap;gap:8px;align-items:center}#cpt .chip{background:#272122;border-radius:999px;padding:8px 14px;font-weight:600}',
    '#cpt .tot{font:800 34px system-ui;margin-right:12px}',
    '#cpt .acoes{display:flex;gap:10px;flex-wrap:wrap}',
    '#cpt .cfg{background:#1F1A1B;border-radius:14px;padding:14px;display:grid;gap:10px;max-height:45vh;overflow:auto}',
    '#cpt .cfg label{display:grid;gap:4px;font-size:14px;color:#A89F9C}#cpt .cfg input,#cpt .cfg select{font:16px system-ui;padding:10px;border-radius:10px;border:1px solid #342C2D;background:#141112;color:#F5F0EE}'
  ].join('\n');
  document.head.appendChild(css);

  var btn = document.createElement('button'); btn.id = 'cpt-btn'; btn.type = 'button'; btn.textContent = '📷 Contar bandeja';
  document.body.appendChild(btn);
  var ui = document.createElement('div'); ui.id = 'cpt'; ui.hidden = true;
  ui.innerHTML = '<div class="topo"><b>Conta-Peças</b><button type="button" data-a="cfg">⚙</button><button type="button" class="red" data-a="fechar">Fechar</button></div>' +
    '<div class="status" data-r="status"></div>' +
    '<div class="cfg" data-r="cfg" hidden></div>' +
    '<div class="palco"><video data-r="video" playsinline muted autoplay></video><img data-r="foto" hidden alt="Bandeja"><div class="camada" data-r="camada"></div></div>' +
    '<div class="res" data-r="res"></div>' +
    '<div class="acoes"><button type="button" data-a="contar">Contar agora</button><button type="button" data-a="foto">Usar foto</button><button type="button" data-a="nova">Outra bandeja</button><button type="button" class="pri" data-a="sacola" disabled>Colocar na sacola</button></div>' +
    '<input type="file" accept="image/*" data-r="arquivo" hidden>';
  document.body.appendChild(ui);
  // O botão fica no canto de baixo, mas sobe sozinho quando o ALIV mostra um botão largo no
  // rodapé (ex.: "Finalizar pedido" na sacola), para nunca tampar outro botão.
  function noTopo(el) {
    if (!el) return false; var r = el.getBoundingClientRect(); if (!r.width || !r.height) return false;
    var x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 20);
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) return false;
    var topo = document.elementFromPoint(x, y); return !!topo && (topo === el || el.contains(topo) || topo.contains(el));
  }
  function telaDeEscolha() {
    if (Array.prototype.some.call(document.querySelectorAll('input[placeholder*="Buscar"]'), noTopo)) return true;   // cardápio
    return Array.prototype.some.call(document.querySelectorAll('span, p, div, button'), function (e) {   // tela inicial
      return e.childElementCount <= 2 && /^Toque para pedir$/i.test(e.textContent.trim()) && noTopo(e);
    });
  }
  function posicionarBotao() {
    // Na tela da sacola o botão some (lá ficam o total e o Finalizar). Para outra bandeja: Continuar pedindo.
    // O botão só aparece no cardápio e na tela inicial do totem. Sacola, Pix, maquininha e
    // confirmação ficam limpos (não tampa total, Finalizar, nem o aviso de pagamento).
    btn.style.display = telaDeEscolha() ? '' : 'none';
    if (btn.style.display === 'none') return;
    var H = window.innerHeight, W = window.innerWidth, topo = H;
    document.querySelectorAll('button, a, [role="button"]').forEach(function (el) {
      if (el === btn || ui.contains(el)) return;
      var r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
      if (r.width > W * 0.85 && r.top > H - 200 && r.bottom <= H + 2 && r.top < topo) topo = r.top;
    });
    btn.style.bottom = (topo < H ? Math.round(H - topo + 16) : 24) + 'px';
  }
  setInterval(posicionarBotao, 500); window.addEventListener('resize', posicionarBotao); posicionarBotao();
  function $(r) { return ui.querySelector('[data-r="' + r + '"]'); }
  function status(t) { $('status').textContent = t || ''; }

  // ---------- câmera ----------
  async function ligarCamera() {
    pararCamera();
    var v = { width: { ideal: 1920 }, height: { ideal: 1080 } };
    if (cfg.camId) v.deviceId = { exact: cfg.camId }; else v.facingMode = { ideal: 'environment' };
    try { st.stream = await navigator.mediaDevices.getUserMedia({ video: v, audio: false }); }
    catch (e) { status('Câmera não abriu (' + (e && e.name) + '). Escolha a câmera em ⚙ ou use "Usar foto".'); return false; }
    var vid = $('video'); vid.srcObject = st.stream; vid.hidden = false; $('foto').hidden = true;
    try { await vid.play(); } catch (e) { }
    iniciarMonitor(); return true;
  }
  function pararCamera() {
    if (st.timer) { clearInterval(st.timer); st.timer = null; }
    if (st.stream) { st.stream.getTracks().forEach(function (t) { t.stop(); }); st.stream = null; }
  }
  function mad(a, b) { var s = 0; for (var i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]); return s / a.length; }
  function iniciarMonitor() {
    var small = document.createElement('canvas'); small.width = 64; small.height = 48; var sx = small.getContext('2d', { willReadFrequently: true });
    st.estavelDesde = Date.now();
    st.timer = setInterval(function () {
      var v = $('video'); if (!v.videoWidth || v.hidden || st.contando) return;
      sx.drawImage(v, 0, 0, 64, 48); var d = sx.getImageData(0, 0, 64, 48).data, g = new Float32Array(64 * 48);
      for (var i = 0, p = 0; i < g.length; i++, p += 4) g[i] = 0.299 * d[p] + 0.587 * d[p + 1] + 0.114 * d[p + 2];
      var dif = st.ultimo ? mad(g, st.ultimo) : 999; st.ultimo = g; var agora = Date.now();
      if (dif > 4) st.estavelDesde = agora;
      if (!cfg.auto) { status('Ponha a bandeja e toque em Contar agora.'); return; }
      if (agora - st.estavelDesde < 1200) { status('Movimento… deixe a bandeja parada.'); return; }
      if (st.vazio && mad(g, st.vazio) < 10) { status('Aguardando bandeja.'); return; }
      if (st.ultContado && mad(g, st.ultContado) < 10) return;
      st.ultContado = g; contarDaCamera();
    }, 350);
  }
  function capturar() {
    var v = $('video'); if (!v.videoWidth) return null;
    var c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight; c.getContext('2d').drawImage(v, 0, 0); return c;
  }
  function reduzir(src, w, h) {
    var s = Math.min(1, 1280 / Math.max(w, h)), c = document.createElement('canvas');
    c.width = Math.round(w * s); c.height = Math.round(h * s); c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
    return { url: c.toDataURL('image/jpeg', 0.86), w: c.width, h: c.height };
  }
  async function contarDaCamera() {
    var c = capturar(); if (!c) return;
    var r = reduzir(c, c.width, c.height); mostrarFoto(r); await contar(r);
    if (st.ia === 0 && st.ultimo) { st.vazio = st.ultimo; voltarCamera(); }
  }
  function mostrarFoto(r) {
    st.w = r.w; st.h = r.h; st.url = r.url; st.pecas = []; st.ia = null; st.obs = ''; st.liberado = false;
    var f = $('foto'); f.src = r.url; f.hidden = false; $('video').hidden = true; ajustarCamada(); render();
  }
  function voltarCamera() { $('foto').hidden = true; $('video').hidden = false; st.pecas = []; st.ia = null; st.liberado = false; render(); }

  // ---------- Claude ----------
  function extrairJson(txt) {
    var s = String(txt || '').trim(), m = s.match(/```(?:json)?\s*([\s\S]*?)```/); if (m) s = m[1];
    var a = s.indexOf('{'), b = s.lastIndexOf('}'); if (a >= 0 && b > a) s = s.slice(a, b + 1);
    try { return JSON.parse(s); } catch (e) {
      var pecas = [], re = /\{[^{}]*"x"\s*:[^{}]*\}/g, mm;
      while ((mm = re.exec(s))) { try { pecas.push(JSON.parse(mm[0])); } catch (e2) { } }
      if (!pecas.length) throw e;
      return { pecas: pecas, total: pecas.length, obs: 'resposta veio cortada; confira se faltou alguma peça' };
    }
  }
  async function contar(r) {
    if (!cfg.key) { status('Falta a chave do Claude: atendente, toque em ⚙.'); return; }
    if (!window.CONTA_PECAS_PROMPT) { status('Instrução da contagem não carregou. Confira a internet e recarregue.'); return; }
    st.contando = true; status('Contando… (5 a 15 s)'); render();
    try {
      var resp = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-api-key': cfg.key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: MODELOS[cfg.modo] || MODELOS.preciso, max_tokens: 16000, messages: [{ role: 'user', content: [
          { type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: r.url.split(',')[1] } },
          { type: 'text', text: window.CONTA_PECAS_PROMPT + '\nTamanho da imagem: ' + r.w + ' x ' + r.h + ' pixels (largura x altura).' }] }] })
      });
      var j = null; try { j = await resp.json(); } catch (e) { }
      if (!resp.ok) throw new Error((j && j.error && j.error.message) || ('HTTP ' + resp.status));
      var txt = (j.content || []).filter(function (c) { return c.type === 'text'; }).map(function (c) { return c.text; }).join('\n');
      var d = extrairJson(txt), lista = Array.isArray(d.pecas) ? d.pecas : [];
      var emPx = lista.some(function (p) { return Number(p.x) > 100 || Number(p.y) > 100; });
      st.pecas = lista.map(function (p) {
        var x = Number(p.x), y = Number(p.y); if (emPx) { x = x / st.w * 100; y = y / st.h * 100; }
        return { x: Math.min(100, Math.max(0, x || 50)), y: Math.min(100, Math.max(0, y || 50)), tipo: TIPOS[p.tipo] ? String(p.tipo) : 'outro', incerta: !!p.incerta };
      });
      st.ia = st.pecas.length; st.obs = d.obs ? String(d.obs).slice(0, 160) : '';
      status(st.pecas.length ? '' : 'Não vi peças. Ajuste a bandeja embaixo da câmera.');
    } catch (e) {
      status(/401/.test(String(e.message)) ? 'Chave do Claude inválida: atendente, confira em ⚙.' : 'Falha na contagem: ' + String(e.message || e).slice(0, 120));
    } finally { st.contando = false; render(); }
  }

  // ---------- marcas e resumo ----------
  function ajustarCamada() {
    var palco = ui.querySelector('.palco'), W = palco.clientWidth, H = palco.clientHeight, s = Math.min(W / st.w, H / st.h);
    var c = $('camada'); c.style.width = st.w * s + 'px'; c.style.height = st.h * s + 'px'; c.style.left = (W - st.w * s) / 2 + 'px'; c.style.top = (H - st.h * s) / 2 + 'px';
  }
  window.addEventListener('resize', function () { if (st.w) ajustarCamada(); });
  function resumo() {
    var t = {}, faltando = [];
    st.pecas.forEach(function (p) { t[p.tipo] = (t[p.tipo] || 0) + 1; });
    var linhas = Object.keys(t).map(function (k) {
      var prod = produtoDe(k); if (!prod) faltando.push(TIPOS[k]);
      return { tipo: k, qtd: t[k], prod: prod, valor: prod ? (Number(prod.price) || 0) * t[k] : 0 };
    });
    return { linhas: linhas, faltando: faltando, total: linhas.reduce(function (s, l) { return s + l.valor; }, 0) };
  }
  function render() {
    var camada = $('camada'); camada.innerHTML = '';
    var fotoVisivel = !$('foto').hidden;
    if (fotoVisivel) st.pecas.forEach(function (p, i) {
      var m = document.createElement('button'); m.type = 'button'; m.className = 'm' + (p.incerta ? ' inc' : '');
      m.style.left = p.x + '%'; m.style.top = p.y + '%'; m.textContent = i + 1; m.dataset.i = i; camada.appendChild(m);
    });
    var res = $('res'); res.innerHTML = '';
    var inc = st.pecas.filter(function (p) { return p.incerta; }).length, r = resumo();
    if (st.pecas.length) {
      var tot = document.createElement('span'); tot.className = 'tot'; tot.textContent = st.pecas.length + ' peças · ' + brl(r.total); res.appendChild(tot);
      r.linhas.forEach(function (l) { var c = document.createElement('span'); c.className = 'chip'; c.textContent = l.qtd + ' ' + TIPOS[l.tipo] + (l.prod ? '' : ' (sem produto)'); res.appendChild(c); });
    }
    var podeSacola = st.pecas.length > 0 && !st.contando && !r.faltando.length && (inc === 0 || st.liberado);
    ui.querySelector('[data-a="sacola"]').disabled = !podeSacola;
    if (st.contando) return;
    if (r.faltando.length) status('Sem produto no totem para: ' + r.faltando.join(', ') + '. Atendente: ajuste em ⚙.');
    else if (inc && !st.liberado) status(inc + ' peça(s) em dúvida (laranja). Chame o atendente para conferir.');
    else if (st.pecas.length) status(st.obs ? 'Obs.: ' + st.obs : 'Confira e toque em Colocar na sacola.');
  }
  $('camada').addEventListener('click', function (ev) {
    var alvo = ev.target.closest('.m'), c = $('camada'), rc = c.getBoundingClientRect();
    if (!st.liberado) { if (pedirPin()) { st.liberado = true; render(); } return; }
    if (alvo) { var p = st.pecas[Number(alvo.dataset.i)]; if (p.incerta) p.incerta = false; else st.pecas.splice(Number(alvo.dataset.i), 1); }
    else st.pecas.push({ x: (ev.clientX - rc.left) / rc.width * 100, y: (ev.clientY - rc.top) / rc.height * 100, tipo: 'outro', incerta: false });
    render();
  });
  // Senha só com números: o teclado do totem e o preenchimento automático do navegador
  // não conseguem trocar letras, espaços ou maiúsculas.
  function soNumeros(v) { return String(v == null ? '' : v).replace(/\D/g, ''); }
  function pedirPin(msg) {
    var pin = soNumeros(cfg.pin); if (!pin) return true;
    var p = window.prompt((msg || 'Senha do atendente') + ' (só números)'); if (p === null) return false;
    if (soNumeros(p) === pin) return true;
    // Esqueceu a senha: os 6 últimos caracteres da chave do Claude liberam e apagam a senha.
    var k = String(cfg.key || '').trim();
    if (k.length >= 6 && String(p).trim() === k.slice(-6)) { cfg.pin = ''; salvarCfg(); window.alert('Senha apagada. Crie outra em ⚙.'); return true; }
    window.alert('Senha errada.'); return false;
  }

  // ---------- sacola do ALIV ----------
  // Trava: peças contadas pela câmera não podem ser diminuídas ou apagadas na sacola sem a senha
  // do atendente. Se o cliente tentar, a quantidade volta sozinha. Aumentar é sempre livre.
  // A trava zera quando o ALIV esvazia a sacola (pedido feito, Recomeçar ou tela parada).
  var trava = {};           // product_id -> { qtd, item }
  var restaurando = false;
  function qtdNaSacola() {
    var q = {}; (window.CART || []).forEach(function (i) { q[i.product_id] = (q[i.product_id] || 0) + (Number(i.quantity) || 0); }); return q;
  }
  function conferirTrava() {
    if (restaurando || !Object.keys(trava).length) return;
    var q = qtdNaSacola(), faltando = [];
    Object.keys(trava).forEach(function (id) { if ((q[id] || 0) < trava[id].qtd) faltando.push(id); });
    if (!faltando.length) return;
    restaurando = true;
    try {
      var ok = soNumeros(cfg.pin) ? pedirPin('Peças contadas pela câmera. Para retirar, digite a senha do atendente') : false;
      if (ok) { faltando.forEach(function (id) { var n = q[id] || 0; if (n) trava[id].qtd = n; else delete trava[id]; }); return; }
      var cart = window.CART || [];
      faltando.forEach(function (id) {
        var linha = null; for (var i = 0; i < cart.length; i++) if (String(cart[i].product_id) === String(id)) { linha = cart[i]; break; }
        var falta = trava[id].qtd - (q[id] || 0);
        if (linha) linha.quantity = (Number(linha.quantity) || 0) + falta;
        else { var novo = JSON.parse(JSON.stringify(trava[id].item)); novo._tempId = Date.now() + Math.random(); novo.quantity = falta; cart.push(novo); }
      });
      if (!soNumeros(cfg.pin)) window.alert('As peças contadas pela câmera não podem ser retiradas. Chame o atendente.');
      if (window.updateCartUI) window.updateCartUI();
    } finally { restaurando = false; }
  }
  window.addEventListener('aliv:cart-updated', function () { setTimeout(conferirTrava, 0); });
  (function () {
    var limpar = window.__totemClearCart;
    if (typeof limpar === 'function') window.__totemClearCart = function () { trava = {}; fotosSacola = []; return limpar.apply(this, arguments); };
  })();
  // ---------- foto da bandeja: no topo da sacola e guardada no totem ----------
  // O ALIV não guarda foto no pedido. A foto (com as marcas) aparece no topo da sacola para o
  // cliente conferir e fica guardada no próprio totem por 30 dias, com data, hora, peças e total.
  var fotosSacola = [];
  function fotoComMarcas() {
    var img = $('foto'); if (!img || !img.naturalWidth) return null;
    var s = Math.min(1, 720 / Math.max(img.naturalWidth, img.naturalHeight)), c = document.createElement('canvas');
    c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
    var g = c.getContext('2d'); g.drawImage(img, 0, 0, c.width, c.height);
    var raio = Math.max(9, Math.round(c.width / 45));
    st.pecas.forEach(function (p, i) {
      var x = p.x / 100 * c.width, y = p.y / 100 * c.height;
      g.beginPath(); g.arc(x, y, raio, 0, 7); g.fillStyle = '#FFB800'; g.fill(); g.lineWidth = 2; g.strokeStyle = '#1A1A1A'; g.stroke();
      g.fillStyle = '#1A1A1A'; g.font = 'bold ' + Math.round(raio * 1.05) + 'px system-ui'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(String(i + 1), x, y + 1);
    });
    return c.toDataURL('image/jpeg', 0.8);
  }
  function abrirBanco() {
    return new Promise(function (ok) {
      try { var rq = indexedDB.open('conta_pecas_totem', 1); rq.onupgradeneeded = function () { rq.result.createObjectStore('bandejas', { keyPath: 'quando' }); };
        rq.onsuccess = function () { ok(rq.result); }; rq.onerror = function () { ok(null); }; } catch (e) { ok(null); }
    });
  }
  async function guardarNoTotem(reg) {
    var db = await abrirBanco(); if (!db) return;
    try {
      var tx = db.transaction('bandejas', 'readwrite'), loja = tx.objectStore('bandejas'); loja.put(reg);
      var limite = Date.now() - 30 * 864e5; loja.openCursor().onsuccess = function (e) { var cur = e.target.result; if (cur) { if (cur.value.quando < limite) cur.delete(); cur.continue(); } };
    } catch (e) { }
  }
  function registrarFoto(r) {
    var url = fotoComMarcas(); if (!url) return;
    var reg = { quando: Date.now(), foto: url, pecas: st.pecas.length, total: Math.round(r.total * 100) / 100, ia: st.ia, conferido: st.liberado,
      itens: r.linhas.map(function (l) { return { tipo: l.tipo, qtd: l.qtd, produto: l.prod.name, preco: Number(l.prod.price) || 0 }; }) };
    fotosSacola.push(reg); guardarNoTotem(reg);
  }
  var cssFoto = document.createElement('style');
  cssFoto.textContent = '#cpt-fotos{display:flex;gap:10px;overflow-x:auto;padding:10px 24px 4px;background:transparent}#cpt-fotos figure{margin:0;flex:0 0 auto;text-align:center;font:600 14px system-ui;color:#334155}#cpt-fotos img{display:block;height:180px;border-radius:12px;border:2px solid #e2e8f0}#cpt-zoom{position:fixed;inset:0;z-index:2147483002;background:rgba(0,0,0,.85);display:grid;place-items:center}#cpt-zoom img{max-width:96vw;max-height:90vh;border-radius:12px}';
  document.head.appendChild(cssFoto);
  function cabecalhoDaSacola() {
    var t = Array.prototype.find.call(document.querySelectorAll('h1,h2,h3,div,span,p'), function (e) {
      if (e.childElementCount !== 0 || e.textContent.trim() !== 'Seu pedido') return false; var r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0;
    });
    if (!t) return null; var linha = t; while (linha.parentElement && linha.parentElement.getBoundingClientRect().height < 140) linha = linha.parentElement;
    return linha;
  }
  function mostrarFotosNaSacola() {
    var velho = document.getElementById('cpt-fotos'), cab = fotosSacola.length ? cabecalhoDaSacola() : null;
    if (!cab) { if (velho) velho.remove(); return; }
    if (velho && velho.previousElementSibling === cab && velho.dataset.n === String(fotosSacola.length)) return;
    if (velho) velho.remove();
    var box = document.createElement('div'); box.id = 'cpt-fotos'; box.dataset.n = String(fotosSacola.length);
    fotosSacola.forEach(function (f, i) {
      var fig = document.createElement('figure'), img = document.createElement('img'), cap = document.createElement('figcaption');
      img.src = f.foto; img.alt = 'Bandeja ' + (i + 1); cap.textContent = (fotosSacola.length > 1 ? 'Bandeja ' + (i + 1) + ' · ' : 'Sua bandeja · ') + f.pecas + ' peças · ' + brl(f.total);
      img.addEventListener('click', function () { var z = document.createElement('div'); z.id = 'cpt-zoom'; var zi = document.createElement('img'); zi.src = f.foto; z.appendChild(zi); z.addEventListener('click', function () { z.remove(); }); document.body.appendChild(z); });
      fig.appendChild(img); fig.appendChild(cap); box.appendChild(fig);
    });
    cab.insertAdjacentElement('afterend', box);
  }
  setInterval(mostrarFotosNaSacola, 500);
  function colocarNaSacola() {
    var r = resumo(); if (r.faltando.length) return;
    var itens = r.linhas.map(function (l) {
      return { _tempId: Date.now() + Math.random(), product_id: l.prod.id, name: l.prod.name, type: 'product', quantity: l.qtd, price: Number(l.prod.price) || 0,
        price_in_points: 0, observation: '', size_id: null, size_name: '', size_slices: 0, parts: [], addons: [], combo_data: [], details: [],
        removed_ingredients: [], removed_names: [], desc_resume: l.prod.name, offer_items: [] };
    });
    itens.forEach(function (it) { var t = trava[it.product_id] || { qtd: 0, item: it }; t.qtd += it.quantity; trava[it.product_id] = t; });
    registrarFoto(r);
    // Mesmo produto já na sacola (outra bandeja): soma na mesma linha.
    var atual = (window.CART || []).slice();
    itens.forEach(function (it) {
      var ja = null; for (var i = 0; i < atual.length; i++) if (String(atual[i].product_id) === String(it.product_id) && atual[i].type === 'product' && !(atual[i].addons || []).length) { ja = atual[i]; break; }
      if (ja) ja.quantity = (Number(ja.quantity) || 0) + it.quantity; else atual.push(it);
    });
    if (typeof window.__totemSetCart === 'function') window.__totemSetCart(atual);
    else { window.CART = atual; if (window.updateCartUI) window.updateCartUI(); }
    fechar();
  }

  // ---------- configurações (atendente) ----------
  async function abrirCfg() {
    var box = $('cfg'); if (!box.hidden) { box.hidden = true; return; }
    if (!pedirPin()) return;
    var cams = []; try { cams = (await navigator.mediaDevices.enumerateDevices()).filter(function (d) { return d.kind === 'videoinput'; }); } catch (e) { }
    var ps = produtos();
    function opts(sel) { return '<option value="">automático</option>' + ps.map(function (p) { return '<option value="' + p.id + '"' + (String(sel) === String(p.id) ? ' selected' : '') + '>' + String(p.name).replace(/</g, '&lt;') + ' — ' + brl(Number(p.price) || 0) + '</option>'; }).join(''); }
    box.innerHTML = '<label>Chave do Claude<input type="password" data-c="key" autocomplete="off" value="' + (cfg.key ? '••••••••' : '') + '" placeholder="sk-ant-…"></label>' +
      '<label>Modo<select data-c="modo"><option value="preciso"' + (cfg.modo !== 'rapido' ? ' selected' : '') + '>Preciso (Sonnet 5.5)</option><option value="rapido"' + (cfg.modo === 'rapido' ? ' selected' : '') + '>Rápido (Haiku 5.5)</option></select></label>' +
      '<label>Câmera<select data-c="camId"><option value="">automática</option>' + cams.map(function (c, i) { return '<option value="' + c.deviceId + '"' + (c.deviceId === cfg.camId ? ' selected' : '') + '>' + (c.label || 'Câmera ' + (i + 1)) + '</option>'; }).join('') + '</select></label>' +
      '<label>Contar sozinho quando a bandeja para<select data-c="auto"><option value="1"' + (cfg.auto ? ' selected' : '') + '>Sim</option><option value="0"' + (!cfg.auto ? ' selected' : '') + '>Não</option></select></label>' +
      '<label>Senha do atendente, só números (para confirmar peça em dúvida e abrir ⚙)<input type="tel" data-c="pin" inputmode="numeric" pattern="[0-9]*" maxlength="8" autocomplete="off" autocorrect="off" spellcheck="false" value="' + soNumeros(cfg.pin) + '"></label>' +
      Object.keys(TIPOS).map(function (k) { var p = produtoDe(k); return '<label>' + TIPOS[k] + ' → produto do totem (hoje: ' + (p ? String(p.name).replace(/</g, '&lt;') : 'nenhum') + ')<select data-m="' + k + '">' + opts(cfg.mapa[k]) + '</select></label>'; }).join('') +
      '<button type="button" class="pri" data-a="salvar">Salvar</button>';
    box.hidden = false;
  }
  function salvarCfgUI() {
    var box = $('cfg'), k = box.querySelector('[data-c="key"]').value.trim();
    if (k && k.indexOf('•') < 0) cfg.key = k;
    cfg.modo = box.querySelector('[data-c="modo"]').value;
    var cam = box.querySelector('[data-c="camId"]').value, mudouCam = cam !== cfg.camId; cfg.camId = cam;
    cfg.auto = box.querySelector('[data-c="auto"]').value === '1';
    var novoPin = soNumeros(box.querySelector('[data-c="pin"]').value), pinMudou = novoPin !== soNumeros(cfg.pin); cfg.pin = novoPin;
    box.querySelectorAll('[data-m]').forEach(function (s) { if (s.value) cfg.mapa[s.dataset.m] = Number(s.value); else delete cfg.mapa[s.dataset.m]; });
    salvarCfg(); box.hidden = true; if (mudouCam && ui.hidden === false) ligarCamera(); render();
    status(pinMudou ? (novoPin ? 'Configuração salva. Senha do atendente: ' + novoPin + ' — anote.' : 'Configuração salva, sem senha de atendente.') : 'Configuração salva.');
  }

  // ---------- abrir / fechar ----------
  async function abrir() {
    if (typeof window.__totemLoadMenu === 'function' && !produtos().length) { try { await window.__totemLoadMenu(); } catch (e) { } }
    ui.hidden = false; st.pecas = []; st.ia = null; st.liberado = false; st.ultContado = null; $('foto').hidden = true; render(); status('');
    await ligarCamera();
  }
  function fechar() { pararCamera(); ui.hidden = true; $('cfg').hidden = true; }

  btn.addEventListener('click', abrir);
  ui.addEventListener('click', function (ev) {
    var a = ev.target.closest('[data-a]'); if (!a) return;
    var acao = a.dataset.a;
    if (acao === 'fechar') fechar();
    else if (acao === 'cfg') abrirCfg();
    else if (acao === 'salvar') salvarCfgUI();
    else if (acao === 'contar') { if (!$('video').hidden) contarDaCamera(); else if (st.url) contar({ url: st.url, w: st.w, h: st.h }); }
    else if (acao === 'foto') { var f = $('arquivo'); f.value = ''; f.click(); }
    else if (acao === 'nova') { st.ultContado = null; voltarCamera(); if (!st.stream) ligarCamera(); }
    else if (acao === 'sacola') colocarNaSacola();
  });
  $('arquivo').addEventListener('change', function (e) {
    var file = e.target.files && e.target.files[0]; if (!file) return;
    var img = new Image(), url = URL.createObjectURL(file);
    img.onload = function () { var r = reduzir(img, img.naturalWidth, img.naturalHeight); URL.revokeObjectURL(url); if (st.timer) { clearInterval(st.timer); st.timer = null; } mostrarFoto(r); contar(r); };
    img.src = url;
  });
})();
