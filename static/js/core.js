/* Shared helpers for the Sentinel front end: API calls, escaping, dates, modals, menus, toasts. */
(function () {
  'use strict';
  var SX = window.SX = {}; SX.pages = {};
  SX.$ = function (s, r) { return (r || document).querySelector(s); };
  SX.$$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  SX.esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };

  SX.api = function (method, url, body) {
    return fetch(url, { method: method, headers: { 'Content-Type': 'application/json', 'X-Sentinel': '1' }, credentials: 'same-origin', body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        var who = r.headers.get('X-Sentinel-User');
        if (who && SX.S && SX.S.me && who !== SX.S.me.username) { SX.keep = true; location.reload(); return new Promise(function () {}); }  // another tab signed in as someone else: reload quietly
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (r.status === 401) { location.href = '/login?reason=idle'; return new Promise(function () {}); }
          if (d.error === 'password_change_required') { SX.keep = true; location.href = '/login?reason=change'; return new Promise(function () {}); }
          if (!r.ok) { var e = new Error(d.message || 'The request failed'); e.data = d; e.status = r.status; throw e; }
          return d;
        });
      });
  };
  SX.fmt = function (ts, dateOnly) {
    if (!ts) return '\u2013';
    var d = new Date(ts.length === 10 ? ts + 'T00:00:00' : ts);
    if (isNaN(d)) return SX.esc(ts);
    var o = { day: '2-digit', month: 'short', year: 'numeric' };
    if (!dateOnly && ts.length > 10) { o.hour = '2-digit'; o.minute = '2-digit'; }
    return d.toLocaleString('en-GB', o);
  };
  SX.ago = function (ts) {
    if (!ts) return 'never';
    var s = (Date.now() - new Date(ts).getTime()) / 1000;
    if (s < 90) return 'just now'; if (s < 3600) return Math.round(s / 60) + ' min ago'; if (s < 86400) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' days ago';
  };
  SX.toast = function (msg, kind) {
    var t = document.createElement('div'); t.className = 'toast ' + (kind || ''); t.textContent = msg;
    SX.$('#toasts').appendChild(t); setTimeout(function () { t.remove(); }, kind === 'bad' ? 7000 : 3800);
  };
  SX.copy = function (text) {
    var done = function () { SX.toast('Copied to the clipboard', 'ok'); };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(done, function () { fallback(); }); } else fallback();
    function fallback() { var a = document.createElement('textarea'); a.value = text; document.body.appendChild(a); a.select(); try { document.execCommand('copy'); done(); } catch (e) { SX.toast('Select and copy it manually', 'bad'); } a.remove(); }
  };

  var stack = [];
  SX.modal = function (o) {
    var bg = document.createElement('div'); bg.className = 'modal-bg';
    var m = document.createElement('div'); m.className = 'modal' + (o.wide ? ' wide' : ''); m.setAttribute('role', 'dialog'); m.setAttribute('aria-modal', 'true');
    m.innerHTML = '<h2>' + SX.esc(o.title || '') + '</h2>' + (o.sub ? '<div class="muted small" style="margin-bottom:10px">' + o.sub + '</div>' : '') + '<div class="mbody">' + (o.html || '') + '</div><div class="acts"></div>';
    bg.appendChild(m); document.body.appendChild(bg);
    var api = { el: m, $: function (s) { return SX.$(s, m); }, close: function () { bg.remove(); stack = stack.filter(function (x) { return x !== api; }); } };
    (o.buttons || [{ label: 'Close' }]).forEach(function (b) {
      var btn = document.createElement('button'); btn.type = 'button'; btn.className = 'btn ' + (b.cls || ''); btn.textContent = b.label;
      btn.addEventListener('click', function () {
        if (!b.onClick) { api.close(); return; }
        btn.disabled = true;
        Promise.resolve(b.onClick(api)).then(function (r) { if (r !== false) api.close(); else btn.disabled = false; }, function () { btn.disabled = false; });
      });
      SX.$('.acts', m).appendChild(btn);
    });
    bg.addEventListener('mousedown', function (e) { if (e.target === bg && !o.sticky) api.close(); });
    stack.push(api);
    var first = SX.$('input:not([type=checkbox]):not([type=radio]):not([readonly]),select,textarea', m); if (first) setTimeout(function () { first.focus(); }, 30);
    return api;
  };
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && stack.length) stack[stack.length - 1].close(); });

  var openMenu = null;
  SX.menu = function (anchor, items) {
    SX.closeMenu();
    var m = document.createElement('div'); m.className = 'menu';
    items.forEach(function (it) {
      if (it === '-') { m.appendChild(document.createElement('hr')); return; }
      var b = document.createElement('button'); b.type = 'button'; b.textContent = it.label; if (it.danger) b.className = 'danger';
      b.addEventListener('click', function () { SX.closeMenu(); it.onClick(); }); m.appendChild(b);
    });
    document.body.appendChild(m);
    var r = anchor.getBoundingClientRect();
    m.style.top = Math.min(r.bottom + 4, window.innerHeight - m.offsetHeight - 8) + 'px';
    m.style.left = Math.max(8, Math.min(r.right - m.offsetWidth, window.innerWidth - m.offsetWidth - 8)) + 'px';
    openMenu = m;
  };
  SX.closeMenu = function () { if (openMenu) { openMenu.remove(); openMenu = null; } };
  document.addEventListener('mousedown', function (e) { if (openMenu && !openMenu.contains(e.target)) SX.closeMenu(); });
  window.addEventListener('scroll', function () { SX.closeMenu(); }, true);

  // password rules (mirror of the server policy) used by the profile page
  SX.pwRules = function (p, username, min) {
    return [['At least ' + min + ' characters', p.length >= min], ['A lower-case letter', /[a-z]/.test(p)], ['An upper-case letter', /[A-Z]/.test(p)], ['A number', /[0-9]/.test(p)], ['A symbol', /[^A-Za-z0-9]/.test(p)],
      ['Does not contain your username', !(username && username.length >= 3 && p.toLowerCase().indexOf(username.toLowerCase()) >= 0)]];
  };
})();
