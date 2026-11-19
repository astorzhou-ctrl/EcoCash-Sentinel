/* Sentinel application shell: sidebar, top bar, routing, Home, My Profile, planned-module pages, idle timeout. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api;
  var S = SX.S = { me: null, perms: {}, nav: [], meta: null, policy: {}, lastActivity: Date.now(), lastPing: Date.now(), warning: null };
  SX.pages = SX.pages || {};
  SX.can = function (mod, act) { return (S.perms[mod] || []).indexOf(act || 'view') >= 0; };

  // ---------------------------------------------------------------- shell
  function initials(n) { return (n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(function (x) { return x[0].toUpperCase(); }).join(''); }
  function face(u) { return u.avatar ? '<img src="' + u.avatar + '" alt="">' : esc(initials(u.full_name)); }
  function pickPhoto(done) { // choose a picture, crop it square and shrink it to 256 px in the browser, so any photo works
    var inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/png,image/jpeg,image/webp';
    inp.onchange = function () {
      var f = inp.files[0]; if (!f) return; var r = new FileReader();
      r.onload = function () {
        var im = new Image(); im.onload = function () {
          var s = Math.min(im.width, im.height), c = document.createElement('canvas'); c.width = c.height = 256;
          c.getContext('2d').drawImage(im, (im.width - s) / 2, (im.height - s) / 2, s, s, 0, 0, 256, 256); done(c.toDataURL('image/jpeg', 0.85));
        }; im.onerror = function () { SX.toast('That file is not a picture', 'bad'); }; im.src = r.result;
      }; r.readAsDataURL(f);
    }; inp.click();
  }
  var NAVSTATE = {};
  try { NAVSTATE = JSON.parse(localStorage.getItem('sx_nav') || '{}') || {}; } catch (e) { NAVSTATE = {}; }
  function saveNav() { try { localStorage.setItem('sx_nav', JSON.stringify(NAVSTATE)); } catch (e) { /* private window: the menu just forgets */ } }
  function curKey() { var m = (location.hash || '').match(/^#\/m\/([a-z0-9_]+)/); return m ? m[1] : null; }
  function setSuite(el, open) { el.classList.toggle('open', open); var b = el.nextElementSibling; if (b) b.hidden = !open; var h = el.querySelector('.chev'); if (h) h.setAttribute('aria-expanded', open); }
  function buildSide() {
    var h = '<div class="brand"><img src="/static/img/logo_shield.png" alt=""><div><b>Sentinel</b><span>ECOCASH ENTERPRISE RISK PLATFORM</span></div></div><a class="home" id="nav-home" href="#/home">' + SX.tile('home', 24, '#4DA3FF') + '<span>Home</span></a>';
    var cur = curKey();
    S.nav.forEach(function (s, i) {
      var open = NAVSTATE[s.name] != null ? !!NAVSTATE[s.name] : s.modules.some(function (m) { return m.key === cur; });
      h += '<div class="suite' + (open ? ' open' : '') + '" data-suite="' + esc(s.name) + '" style="--c:' + s.color + '" role="button" tabindex="0">' + SX.suiteIcon(s.name, 28) + '<b>' + esc(s.name.toLowerCase().replace(/\b\w/g, function (c) { return c.toUpperCase(); })) + '</b><span class="chev" aria-label="Show or hide ' + esc(s.name) + '"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg></span></div><div class="sub"' + (open ? '' : ' hidden') + '>';
      s.modules.forEach(function (m) { h += '<a class="mod" data-key="' + m.key + '" href="#/m/' + m.key + '" style="--c:' + s.color + '">' + SX.icon(m.key, 15) + '<span class="nm">' + esc(m.name) + '</span>' + (S.isAdmin ? '<em class="' + (m.live ? 'lv' : '') + '">' + (m.live ? 'live' : m.phase) + '</em>' : '') + '</a>'; });
      h += '</div>';
    });
    h = SX.gradDefs() + h;
    $('#side').innerHTML = h;
    $$('#side .suite').forEach(function (el) {
      var go = function () { var open = !el.classList.contains('open'); NAVSTATE[el.dataset.suite] = open ? 1 : 0; saveNav(); setSuite(el, open); };
      el.addEventListener('click', go);
      el.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
  }
  function buildTop() {
    var u = S.me;
    $('#top').innerHTML = '<div class="search" id="qs-open" role="button" tabindex="0"><span>Search modules and pages</span><span>Ctrl K</span></div><span class="pill">EcoCash (Pvt) Ltd</span>' + (S.demo ? '<span class="pill" style="background:#E4002B;color:#fff;font-weight:700">DEMO: invented data</span>' : '') + '<span class="pill">' + new Date().toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }) + '</span><span class="pill fy" title="' + esc(SX.fy().text) + '">' + SX.fy().label + ' &middot; Q' + SX.fy().q + '</span><div class="sp"></div>' +
      (S.ai && S.ai.on && SX.can('sentinel_copilot', 'create') ? '<button class="btn" id="asksentinel" title="Ask Sentinel: plain-language answers with sources" style="background:#F28C28;border-color:#F28C28;color:#fff;font-weight:700;border-radius:18px;padding:6px 14px;margin-right:8px">+ Ask Sentinel</button>' : '') + '<button class="iconbtn" id="bell" title="Alerts" aria-label="Alerts">&#9993;<b id="bell-n" hidden></b></button><button class="avatar" id="avatar" title="' + esc(u.full_name) + '">' + face(u) + '</button>';
    $('#qs-open').addEventListener('click', quickSwitch);
    var ak = $('#asksentinel'); if (ak) ak.addEventListener('click', function () { if (SX.askSentinel) SX.askSentinel(); });
    $('#qs-open').addEventListener('keydown', function (e) { if (e.key === 'Enter') quickSwitch(); });
    $('#avatar').addEventListener('click', function (e) {
      SX.menu(e.currentTarget, [{ label: u.full_name + ' (' + u.username + ')', onClick: function () { location.hash = '#/profile'; } }, '-', { label: 'My profile', onClick: function () { location.hash = '#/profile'; } },
        { label: 'Change password', onClick: function () { location.hash = '#/profile/security'; } }, '-', { label: 'Sign out', danger: true, onClick: signOut }]);
    });
    $('#bell').addEventListener('click', function () { if (SX.can('access_management')) location.hash = '#/m/access_management/locked'; else SX.toast('No alerts'); });
    if (SX.can('access_management')) api('GET', '/api/users?status=locked').then(function (d) { var n = d.users.length; var b = $('#bell-n'); if (n) { b.textContent = n; b.hidden = false; } });
  }
  function signOut() { api('POST', '/api/auth/logout').then(function () { location.href = '/login?reason=signedout'; }, function () { location.href = '/login'; }); }
  SX.signOut = signOut;

  function quickSwitch() {
    var items = [{ n: 'Home', h: '#/home', s: 'Start page' }, { n: 'My profile', h: '#/profile', s: 'Account' }, { n: 'Change password', h: '#/profile/security', s: 'Account' }];
    S.nav.forEach(function (s) { s.modules.forEach(function (m) { items.push({ n: m.name, h: '#/m/' + m.key, s: s.name, c: s.color, p: S.isAdmin ? (m.live ? 'Live' : m.phase) : '' }); }); });
    var m = SX.modal({ title: 'Go to', html: '<div class="qs"><input type="text" id="qs-in" placeholder="Type a module or page name" autocomplete="off"><div class="res" id="qs-res"></div></div>', buttons: [{ label: 'Close' }] });
    var sel = 0, shown = [];
    function draw() {
      var q = m.$('#qs-in').value.trim().toLowerCase();
      shown = items.filter(function (i) { return !q || (i.n + ' ' + i.s).toLowerCase().indexOf(q) >= 0; }).slice(0, 40); if (sel >= shown.length) sel = 0;
      m.$('#qs-res').innerHTML = shown.length ? shown.map(function (i, k) { return '<a href="' + i.h + '" class="' + (k === sel ? 'sel' : '') + '"><b>' + esc(i.n) + '</b><span class="muted small" style="margin-left:auto">' + esc(i.s) + (i.p ? ' &middot; ' + i.p : '') + '</span></a>'; }).join('') : '<div class="empty">Nothing matches</div>';
      $$('a', m.el).forEach(function (a) { a.addEventListener('click', function () { m.close(); }); });
    }
    m.$('#qs-in').addEventListener('input', function () { sel = 0; draw(); });
    m.$('#qs-in').addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, shown.length - 1); draw(); e.preventDefault(); }
      if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); draw(); e.preventDefault(); }
      if (e.key === 'Enter' && shown[sel]) { location.hash = shown[sel].h; m.close(); }
    });
    draw();
  }
  document.addEventListener('keydown', function (e) { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (S.me) quickSwitch(); } });

  // ---------------------------------------------------------------- routing
  function setActive(key) {
    $$('#side a.mod').forEach(function (a) { a.classList.toggle('on', a.dataset.key === key); });
    var act = $('#side a.mod.on'); if (act) { var box = act.parentNode, st = box.previousElementSibling; if (st && !st.classList.contains('open')) setSuite(st, true); }
    $('#nav-home').classList.toggle('on', key === 'home');
  }
  function suiteOf(key) { var r = null; (S.nav || []).forEach(function (s) { s.modules.forEach(function (m) { if (m.key === key) r = s; }); }); return r; }
  function head(crumb, title, color, extra) {
    var key = curKey(), st = key && suiteOf(key), c = color || (st && st.color) || '#1F5FD0';
    return '<div class="ph banner" style="--c:' + c + '">' + (key ? SX.tile(key, 54, c) : '') + '<div class="tt"><div class="crumb">' + crumb + '</div><h1>' + esc(title) + '</h1></div><div class="sp"></div>' + (extra || '') + '</div>';
  }
  SX.head = head;
  SX.tabs = function (base, tabs, cur, color) {
    return '<div class="tabs" style="--c:' + color + '">' + tabs.map(function (t) { return '<a href="#/' + base + '/' + t[0] + '" class="' + (t[0] === cur ? 'on' : '') + '">' + t[1] + '</a>'; }).join('') + '</div>';
  };
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  // ---- every page that shows demonstration records offers its own Remove button (to people who may delete there)
  S.demoPages = {};
  function loadDemoPages() { return api('GET', '/api/demo/summary').then(function (d) { S.demoPages = d.pages || {}; demoBar(); }, function () {}); }
  function demoBar() {
    var old = $('#demobar'); if (old) old.remove();
    var m = (location.hash || '').match(/^#\/m\/([a-z0-9_]+)/), key = m && m[1];
    if (!key || !S.demoPages[key]) return;
    var d = document.createElement('div'); d.id = 'demobar'; d.className = 'demobar';
    d.innerHTML = '<span>Demonstration data on this page <b>(' + S.demoPages[key] + ')</b></span><button class="btn sm d" id="demorm">Remove it</button>';
    document.body.appendChild(d);
    $('#demorm').addEventListener('click', function () {
      SX.modal({ title: 'Remove the demonstration data?', html: '<p>Only the invented records tagged <b>demo</b> are removed from this page. Records your team entered are not touched.</p>', buttons: [{ label: 'Cancel' }, { label: 'Remove', cls: 'd', onClick: function () {
        return api('POST', '/api/demo/remove/' + key).then(function (x) { SX.toast(x.records + ' demonstration records removed', 'ok'); return loadDemoPages().then(route); }); } }] });
    });
  }
  function route() {
    SX.closeMenu(); demoBar();
    var parts = (location.hash || '#/home').replace(/^#\//, '').split('/');
    var main = $('#main'); window.scrollTo(0, 0);
    try {
      if (parts[0] === 'profile') { setActive(''); return pageProfile(parts[1] || 'details'); }
      if (parts[0] === 'm' && parts[1]) {
        setActive(parts[1]);
        if (!SX.can(parts[1], 'view')) { main.innerHTML = head('Sentinel', 'No access', '#E31B23') + '<div class="card">You do not have permission to open this module. Ask your administrator.</div>'; return; }
        if (parts[1] === 'command_center') return SX.pages.command();
        if (parts[1] === 'weekly_kpi') return SX.pages.kpi(parts[2] || 'report');
        if (parts[1] === 'kri_monitor') return SX.pages.kri(parts[2]);
        if (parts[1] === 'incidents_losses') return SX.pages.incidents();
        if (parts[1] === 'control_library_testing') return SX.pages.controls();
        if (parts[1] === 'ai_insights') return SX.pages.aiInsights(parts[2]);
        if (['obligations_hub', 'regulatory_change', 'privacy_breach_clock', 'policy_hub', 'standards_hub', 'isms_iso_27001', 'bcms_iso_22301', 'aims_iso_42001', 'bcm_studio', 'third_party_risk', 'cyber_it_risk', 'crisis_room', 'predictive_analytics'].indexOf(parts[1]) >= 0) return SX.pages.kit(parts[1], parts[2]);
        if (parts[1] === 'document_intelligence') return SX.pages.docint();
        if (parts[1] === 'workflow_designer') return SX.pages.workflow();
        if (parts[1] === 'integration_hub') return SX.pages.integration();
        if (parts[1] === 'data_reports') return SX.pages.reports(parts[2]);
        if (parts[1] === 'strategy_map') return SX.pages.strategy();
        if (parts[1] === 'scenario_lab') return SX.pages.scenario(parts[2]);
        if (parts[1] === 'emerging_radar') return SX.pages.radar();
        if (parts[1] === 'audit_workspace') return SX.pages.audit(parts[2]);
        if (parts[1] === 'fraud_intelligence') return SX.pages.fraud(parts[2]);
        if (parts[1] === 'speak_up_cases') return SX.pages.speakup(parts[2]);
        if (parts[1] === 'sentinel_copilot') return SX.pages.copilot(parts[2] || 'ask');
        if (parts[1] === 'ai_governance') return SX.pages.aigov(parts[2] || 'overview');
        if (parts[1] === 'actions_issues') return SX.pages.actions(parts[2]);
        if (parts[1] === 'daily_tracker') return SX.pages.tracker(parts[2]);
        if (parts[1] === 'risk_appetite') return SX.pages.appetite();
        if (parts[1] === 'assessment_studio') return SX.pages.assess(parts[2] || 'mine', parts[3]);
        if (parts[1] === 'board_hub') return SX.pages.board(parts[2] || 'decisions', parts[3]);
        if (parts[1] === 'performance_analytics') return SX.pages.analytics(parts[2] || 'top10');
        if (parts[1] === 'risk_register') return SX.pages.risk(parts[2]);
        if (parts[1] === 'heat_map_portfolio') return SX.pages.heatmap();
        if (parts[1] === 'access_management') return SX.pages.access(parts[2] || 'users');
        if (parts[1] === 'administration') return SX.pages.admin(parts[2] || 'audit');
        return pagePlanned(parts[1]);
      }
      setActive('home'); return pageHome();
    } catch (e) { main.innerHTML = '<div class="alert bad">' + esc(e.message) + '</div>'; }
  }

  // ---------------------------------------------------------------- Home
  function pageHome() {
    var main = $('#main');
    api('GET', '/api/home').then(function (d) {
      var u = d.user, hr = new Date().getHours(), greet = hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening';
      var h = '<div class="home">' + SX.homeHero(u, greet);
      if (d.password_warn) h += '<div class="alert warn"><b>Your password expires in ' + d.password_days_left + ' day' + (d.password_days_left === 1 ? '' : 's') + '.</b> <a href="#/profile/security">Change it now</a>.</div>';
      if (SX.can('command_center')) h += '<div id="pulse" class="card rise" style="margin-bottom:6px"><h3>Enterprise risk pulse</h3><div class="muted small">Reading the register...</div></div>';
      if (SX.can('weekly_kpi') || SX.can('command_center')) h += '<div id="market"></div>';
      h += SX.homeQuick();
      h += '<div class="grid" style="margin-top:14px">';
      h += '<div class="card s8 rise"><h3>Your account</h3><dl class="kv"><dt>Roles</dt><dd>' + u.roles.map(function (r) { return '<span class="tag">' + esc(r) + '</span>'; }).join('') + '</dd><dt>Department</dt><dd>' + esc(u.department || '\u2013') + '</dd><dt>Last sign-in</dt><dd>' + SX.fmt(u.last_login_at) + (u.last_login_ip ? ' from ' + esc(u.last_login_ip) : '') + '</dd></dl></div>';
      h += '<div class="card s4 rise"><h3>Quick links</h3><ul class="list"><li><a href="#/profile">My profile and photo</a></li><li><a href="#/profile/security">Change password</a></li><li><a href="#/profile/sessions">My sessions</a></li>' + (SX.can('access_management') ? '<li><a href="#/m/access_management/users">Manage users</a></li>' : '') + (SX.can('administration') ? '<li><a href="#/m/administration/audit">Audit trail</a></li><li><a href="#/m/administration/build">Build and demo data</a></li>' : '') + '</ul></div>';
      if (d.stats) {
        var st = d.stats, t = function (l, v, c, sub) { return '<div class="card kpi s2" style="--c:' + c + '"><div class="l">' + l + '</div><div class="v">' + v + '</div><div class="d">' + (sub || '&nbsp;') + '</div></div>'; };
        h += t('Users', st.users, '#4C5FD5', st.active + ' active') + t('Locked', st.locked, st.locked ? '#EF2B2B' : '#2FA84F', st.locked ? '<a href="#/m/access_management/locked">needs action</a>' : 'none') + t('Invited', st.invited, '#F9A825', 'not yet signed in') + t('Password expired', st.expired_password, st.expired_password ? '#FDB022' : '#2FA84F', '90-day rule') +
          t('Sessions now', st.sessions, '#17A2B8', 'active') + t('Failed sign-ins', st.failed_24h, st.failed_24h > 5 ? '#EF2B2B' : '#5B6B7C', 'last 24 hours');
      }
      if (S.isAdmin) { h += '<div class="card s6"><h3>What is live in this build</h3><ul class="list"><li><span class="badge b-live">Live</span> Secure sign-in: 90-day passwords, lock after 3 attempts, attempts remaining, reset options</li><li><span class="badge b-live">Live</span> Access Management: users, roles, permissions, sign-in policy</li><li><span class="badge b-live">Live</span> Administration: tamper-evident audit trail, Recycle Bin and restore, outbox</li><li><span class="badge b-live">Live</span> My Profile: password, sessions, notifications, delegation</li><li><span class="badge b-live">Live</span> Risk Register on the auditor&#39;s ranked matrix: workflow, controls, assurance, history, CSV download</li><li><span class="badge b-live">Live</span> Heat Map &amp; Portfolio and Command Center</li><li><span class="badge b-live">Live</span> Import of the ISMS and BCMS risk assessment workbook (33 risks, controls, effectiveness, exposure)</li><li><span class="badge b-live">Live</span> Performance Analytics: the Power BI pages on live data</li><li><span class="badge b-live">Live</span> Daily Tracker (your Excel tracker, with automatic tasks), Risk Appetite, Assessment Studio, Board Hub</li><li><span class="badge b-live">Live</span> Weekly KPI (September 2026 report format, with PowerPoint and Excel download), KRI Monitor, Incidents &amp; Losses</li><li><span class="badge b-live">Live</span> Control Library &amp; Testing (policy scale 1 to 10), Actions &amp; Issues (escalation, independent closure), AI Insights (similar risks, unusual movements)</li><li><span class="badge b-live">Live</span> Two-step sign-in, verified backups, two-person permanent delete</li><li><span class=\"badge b-live\">Live</span> Strategy Map, Scenario Lab, Emerging Radar, Audit Workspace, Fraud Intelligence and Speak-Up Cases; daily e-mail reminders for tasks due and overdue; Ask Sentinel that searches reliable sources by itself for anything outside the system</li><li><span class=\"badge b-live\">Live</span> Sentinel Copilot (answers with sources, document analysis, risk and rating drafts for approval, horizon watch with impact analysis) and AI Governance (Off, Assist, Advanced; hosting approval; kill switch; fairness and quality monitors)</li><li><span class="badge b-plan">Next</span> Fraud Intelligence, Audit Workspace, Speak-Up Cases</li></ul></div>'; }
      var mods = S.nav.reduce(function (n, s) { return n + s.modules.length; }, 0);
      h += '<div class="card s12 rise"><h3>Your modules (' + mods + ')</h3>' + S.nav.map(function (s) { return '<div style="margin-bottom:8px;display:flex;gap:10px;align-items:flex-start">' + SX.suiteIcon(s.name, 30) + '<div><span class="b small" style="color:' + s.color + '">' + esc(s.name) + '</span><br>' + s.modules.map(function (m) { return '<a class="tag" href="#/m/' + m.key + '">' + esc(m.name) + '</a>'; }).join('') + '</div></div>'; }).join('') + '</div>';
      main.innerHTML = h + '</div></div>';
      if ($('#pulse')) pulse();
      if ($('#market')) SX.homeMarket($('#market'));
      SX.countUp(main);
    });
  }
  function pulse() {
    api('GET', '/api/command').then(function (c) {
      var V = SX.viz, tot = c.total || 0, outPct = tot ? Math.round(100 * c.outside_appetite / tot) : 0, loa = c.assurance && c.assurance.loa != null ? Math.round(c.assurance.loa * 100) : null;
      var hi = (c.residual && (c.residual.High || 0)) + (c.residual && (c.residual.Significant || 0)), cats = (c.by_category || []).slice(0, 7).map(function (x) { return { label: x[0], value: x[1] }; });
      var sp = (c.trend || []).map(function (t) { return t.high_sig; });
      $('#pulse').innerHTML = '<h3>Enterprise risk pulse <span class="muted small">live from the register &middot; ' + tot + ' risks</span></h3><div class="grid" style="align-items:center">' +
        '<div class="s3" style="grid-column:span 3;text-align:center">' + V.gauge(outPct, { max: 100, unit: '%', label: 'Risks outside appetite', sub: c.outside_appetite + ' of ' + tot, bands: [[15, '#2FA84F'], [35, '#FDB022'], [100, '#EF2B2B']], size: 170 }) + '</div>' +
        '<div class="s3" style="grid-column:span 3;text-align:center">' + V.gauge(loa, { max: 100, unit: '%', label: 'Level of assurance', sub: 'controls vs exposure', bands: [[50, '#EF2B2B'], [75, '#FDB022'], [100, '#2FA84F']], size: 170 }) + '</div>' +
        '<div class="s3" style="grid-column:span 3;text-align:center">' + V.gauge(hi, { max: Math.max(10, tot), label: 'High and significant risks', sub: (sp.length > 1 ? 'trend ' : '') , bands: [[Math.max(10, tot) * 0.2, '#2FA84F'], [Math.max(10, tot) * 0.45, '#FDB022'], [Math.max(10, tot), '#EF2B2B']], size: 170 }) + (sp.length > 1 ? '<div>' + V.spark(sp, { color: '#EF2B2B', w: 120 }) + '</div>' : '') + '</div>' +
        '<div class="s3" style="grid-column:span 3">' + (cats.length ? '<div class="muted small" style="text-align:center">Risks by category</div>' + V.radial(cats, {}) : '') + '</div></div><div style="text-align:right"><a href="#/m/command_center">Open the Command Center</a></div>';
    }, function () { var p = $('#pulse'); if (p) p.remove(); });
  }

  // ---------------------------------------------------------------- planned module page
  function pagePlanned(key) {
    api('GET', '/api/modules/' + key).then(function (m) {
      var suite = S.nav.filter(function (s) { return s.modules.some(function (x) { return x.key === key; }); })[0] || { color: '#5B6B7C', name: '' };
      var h = head(esc(suite.name) + ' &rsaquo; ' + esc(m.name), m.name, suite.color, (S.isAdmin ? '<span class="badge b-plan">Planned: Phase ' + esc(m.phase) + '</span>' : ''));
      h += '<div class="alert info">This module is specified in the BRD and is not built yet. This page shows what it will contain so you can confirm the scope before development reaches it.</div><div class="grid" style="--c:' + suite.color + '">';
      h += '<div class="card s12"><h3>Purpose</h3><p style="margin:0">' + esc(m.purpose) + '</p><p class="muted small" style="margin:8px 0 0"><b>Users:</b> ' + esc(m.users) + '</p></div>';
      h += '<div class="card s6"><h3>What will be on the screen</h3><ul class="list">' + m.panels.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') + '</ul></div>';
      h += '<div class="card s6"><h3>Rules it will enforce</h3><ul class="list">' + m.rules.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join('') + '</ul></div>';
      h += '<div class="card s12"><h3>Graphs and measures</h3><table class="t"><tr><th>Graph</th><th>Type</th><th>Measure</th></tr>' + m.graphs.map(function (g) { return '<tr><td><b>' + esc(g[0]) + '</b></td><td>' + esc(g[1]) + '</td><td>' + esc(g[2]) + '</td></tr>'; }).join('') + '</table></div>';
      h += '<div class="card s12"><h3>Key requirements</h3><table class="t"><tr><th>ID</th><th>Requirement</th><th>Priority</th><th>Status</th></tr>' + m.reqs.map(function (r, i) { return '<tr><td><b>' + esc(m.key.slice(0, 3).toUpperCase() + '-' + (i + 1)) + '</b></td><td>' + esc(r[0]) + '</td><td>' + esc(r[1]) + '</td><td>' + esc(r[2]) + '</td></tr>'; }).join('') + '</table></div>';
      h += '<div class="card s12"><h3>AI-powered option</h3><table class="t"><tr><th>When AI is on</th><th>When AI is off (manual route)</th></tr>' + m.ai.map(function (a) { return '<tr><td>' + esc(a[0]) + '</td><td>' + esc(a[1]) + '</td></tr>'; }).join('') + '</table></div></div>';
      $('#main').innerHTML = h;
    });
  }

  // ---------------------------------------------------------------- My Profile
  function pageProfile(tab) {
    var tabs = [['details', 'Details'], ['security', 'Security'], ['sessions', 'Sessions'], ['preferences', 'Notifications and delegation']];
    var main = $('#main');
    api('GET', '/api/profile').then(function (u) {
      var h = head('Account', 'My Profile', '#5B6B7C') + SX.tabs('profile', tabs, tab, '#5B6B7C');
      main.innerHTML = h + '<div id="ptab"></div>';
      var box = $('#ptab');
      if (tab === 'details') {
        box.innerHTML = '<div class="grid"><div class="card s4" style="text-align:center"><div class="avatar" style="width:96px;height:96px;font-size:30px;margin:4px auto 6px;cursor:default;background:#1F5FD0">' + face(u) + '</div><div style="margin-bottom:8px"><button class="btn sm" id="ph-up">' + (u.avatar ? 'Change photo' : 'Add photo') + '</button>' + (u.avatar ? ' <button class="btn sm d" id="ph-rm">Remove</button>' : '') + '</div><b style="font-size:15px">' + esc(u.full_name) + '</b><div class="muted">' + esc(u.job_title || '') + (u.department ? ' &middot; ' + esc(u.department) : '') + '</div><div style="margin-top:8px">' + u.roles.map(function (r) { return '<span class="tag">' + esc(r) + '</span>'; }).join('') + '</div><p class="muted small">Last sign-in ' + SX.fmt(u.last_login_at) + '<br>Account created ' + SX.fmt(u.created_at, true) + '</p></div>' +
          '<div class="card s8"><h3>Details</h3><form id="pf" class="form2"><label class="f">Full name<input type="text" name="full_name" value="' + esc(u.full_name) + '" required></label><label class="f">Username<input type="text" value="' + esc(u.username) + '" readonly></label><label class="f">E-mail<input type="email" name="email" value="' + esc(u.email || '') + '"></label><label class="f">Phone<input type="text" name="phone" value="' + esc(u.phone || '') + '"></label><label class="f">Department<input type="text" value="' + esc(u.department || '') + '" readonly></label><label class="f">Time zone<input type="text" name="timezone" value="' + esc(u.timezone || 'Africa/Harare') + '"></label><div class="full"><button class="btn p" style="--c:#1F5FD0" type="submit">Save profile</button> <span class="muted small">Department, job title and roles are managed by your administrator.</span></div></form></div></div>';
        $('#ph-up').addEventListener('click', function () { pickPhoto(function (d) { api('PUT', '/api/profile/avatar', { data: d }).then(function () { S.me.avatar = d; buildTop(); SX.toast('Photo saved', 'ok'); pageProfile('details'); }, function (er) { SX.toast(er.message, 'bad'); }); }); });
        var rm = $('#ph-rm'); if (rm) rm.addEventListener('click', function () { api('DELETE', '/api/profile/avatar').then(function () { S.me.avatar = null; buildTop(); pageProfile('details'); }); });
        $('#pf').addEventListener('submit', function (e) {
          e.preventDefault(); var f = e.target;
          api('PUT', '/api/profile', { full_name: f.full_name.value, email: f.email.value, phone: f.phone.value, timezone: f.timezone.value }).then(function () { SX.toast('Profile saved', 'ok'); S.me.full_name = f.full_name.value; buildTop(); }, function (er) { SX.toast(er.message, 'bad'); });
        });
      } else if (tab === 'security') {
        var left = u.password_days_left, min = S.policy.password_min_length || 12;
        box.innerHTML = '<div class="grid"><div class="card s6"><h3>Change password</h3><form id="cp"><label class="f">Current password<input type="password" name="cur" autocomplete="current-password"></label><label class="f">New password<input type="password" name="new" autocomplete="new-password" id="np"></label><label class="f">Confirm new password<input type="password" name="new2" autocomplete="new-password"></label><ul class="list" id="pr" style="font-size:12px"></ul><button class="btn p" style="--c:#1F5FD0" type="submit">Change password</button></form></div>' +
          '<div class="card s6"><h3>Password and sign-in</h3><dl class="kv"><dt>Password age</dt><dd>' + (u.password_age_days == null ? 'temporary' : u.password_age_days + ' days') + '</dd><dt>Expires</dt><dd>' + (left == null ? '\u2013' : left < 0 ? '<span class="red b">expired</span>' : 'in ' + left + ' days (every 90 days)') + '</dd><dt>Failed attempts</dt><dd>' + u.failed_attempts + ' of ' + (S.policy.max_failed_attempts || 3) + '</dd><dt>Multi-factor</dt><dd><span class="badge b-plan">Planned: Step 2</span> required for administrators when released</dd></dl><p class="muted small">After 3 wrong passwords in a row the account locks. An administrator unlocks it, or you can reset it with the e-mail link on the sign-in page.</p></div></div>';
        var draw = function () { $('#pr').innerHTML = SX.pwRules($('#np').value, u.username, min).map(function (r) { return '<li style="padding:2px 0;border:0"><span style="color:' + (r[1] ? '#2FA84F' : '#B0B8C4') + ';font-weight:700">' + (r[1] ? '\u2713' : '\u2717') + '</span> ' + r[0] + '</li>'; }).join(''); };
        draw(); $('#np').addEventListener('input', draw);
        $('#cp').addEventListener('submit', function (e) {
          e.preventDefault(); var f = e.target;
          if (f.new.value !== f.new2.value) { SX.toast('The two new passwords do not match', 'bad'); return; }
          api('POST', '/api/auth/change-password', { current_password: f.cur.value, new_password: f.new.value }).then(function () { SX.toast('Password changed. Other sessions were signed out.', 'ok'); f.reset(); draw(); pageProfile('security'); }, function (er) { SX.toast(er.message, 'bad'); });
        });
        SX.mfaCard(box, function () { pageProfile('security'); });
      } else if (tab === 'sessions') {
        api('GET', '/api/profile/sessions').then(function (d) {
          var short = function (ua) { return /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : (ua || 'Unknown').slice(0, 30); };
          box.innerHTML = '<div class="card"><div class="toolbar"><h3 style="margin:0">Active sessions</h3><div class="sp" style="flex:1"></div><button class="btn d" id="so-all">Sign out everywhere</button></div><table class="t"><tr><th>Browser</th><th>Address</th><th>Started</th><th>Last active</th><th></th></tr>' + d.sessions.map(function (s) { return '<tr><td>' + esc(short(s.user_agent)) + (s.current ? ' <span class="tag">this device</span>' : '') + '</td><td>' + esc(s.ip) + '</td><td>' + SX.fmt(s.created_at) + '</td><td>' + SX.ago(s.last_seen) + '</td><td>' + (s.current ? '' : '<button class="btn sm" data-rev="' + s.id + '">Sign out</button>') + '</td></tr>'; }).join('') + '</table><p class="muted small">At most ' + (S.policy.max_sessions || 2) + ' sessions can be open at once; signing in on a third device ends the oldest.</p></div>';
          $$('[data-rev]', box).forEach(function (b) { b.addEventListener('click', function () { api('POST', '/api/profile/sessions/' + b.dataset.rev + '/revoke').then(function () { SX.toast('Signed out', 'ok'); pageProfile('sessions'); }); }); });
          $('#so-all').addEventListener('click', function () { api('POST', '/api/profile/signout-everywhere').then(function () { location.href = '/login?reason=signedout'; }); });
        });
      } else {
        var p = u.prefs || {}, n = p.notifications || { digest: true, red_kri: true, approvals: true, sms_breach: false }, dl = p.delegate || {};
        var ck = function (k, l) { return '<label style="display:block;padding:4px 0"><input type="checkbox" name="' + k + '"' + (n[k] ? ' checked' : '') + '> ' + l + '</label>'; };
        box.innerHTML = '<div class="grid"><div class="card s6"><h3>Notifications</h3><form id="pn">' + ck('digest', 'E-mail daily digest at 07:30') + ck('red_kri', 'Alerts when a KRI turns red') + ck('approvals', 'Approvals waiting for me') + ck('sms_breach', 'SMS for a personal-data breach clock') + '<p class="muted small">These apply when the matching modules go live; your choices are saved now.</p></form></div>' +
          '<div class="card s6"><h3>Delegation while away</h3><form id="pd"><label class="f">Delegate (username)<input type="text" name="du" value="' + esc(dl.username || '') + '" placeholder="leave empty for none"></label><div class="form2"><label class="f">From<input type="date" name="df" value="' + esc(dl.from || '') + '"></label><label class="f">To<input type="date" name="dt" value="' + esc(dl.to || '') + '"></label></div></form></div><div class="s12"><button class="btn p" style="--c:#1F5FD0" id="psave">Save</button></div></div>';
        $('#psave').addEventListener('click', function () {
          var nn = {}; $$('input[type=checkbox]', $('#pn')).forEach(function (c) { nn[c.name] = c.checked; }); var f = $('#pd');
          api('PUT', '/api/profile/preferences', { notifications: nn, delegate: { username: f.du.value.trim(), from: f.df.value, to: f.dt.value } }).then(function () { SX.toast('Saved', 'ok'); }, function (er) { SX.toast(er.message, 'bad'); });
        });
      }
    });
  }

  // ---------------------------------------------------------------- idle timeout (server enforces the same rule)
  function activity() { S.lastActivity = Date.now(); if (S.warning) { S.warning.close(); S.warning = null; } if (Date.now() - S.lastPing > 240000) { S.lastPing = Date.now(); api('GET', '/api/auth/ping').catch(function () {}); } }
  ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(function (ev) { document.addEventListener(ev, function () { if (!S.warning) activity(); }, { passive: true }); });
  setInterval(function () {
    if (!S.me) return;
    var idle = (Date.now() - S.lastActivity) / 60000, lim = S.policy.idle_minutes || 30;
    if (idle >= lim) { location.href = '/login?reason=idle'; return; }
    if (idle >= lim - 2 && !S.warning) {
      S.warning = SX.modal({ title: 'Still there?', html: '<p>For your security you will be signed out in about 2 minutes because of inactivity.</p>', sticky: true, buttons: [{ label: 'Sign out now', onClick: function () { signOut(); return false; } }, { label: 'Stay signed in', cls: 'p', onClick: function () { S.warning = null; S.lastActivity = Date.now(); S.lastPing = Date.now(); return api('GET', '/api/auth/ping'); } }] });
    }
  }, 20000);

  window.addEventListener('focus', function () { if (S.me) api('GET', '/api/auth/ping').catch(function () {}); }); // notices a different user signed in from another tab

  // ---------------------------------------------------------------- leaving the page ends the session
  // Refresh, Back, closing the tab or the browser all fire pagehide: the keepalive request is sent even while the page unloads.
  function endSession() { if (!S.me || SX.keep || S.out) return; S.out = true; try { fetch('/api/auth/logout', { method: 'POST', headers: { 'X-Sentinel': '1' }, keepalive: true, credentials: 'same-origin' }); } catch (e) {} }
  window.addEventListener('pagehide', endSession);
  window.addEventListener('pageshow', function (e) { if (e.persisted) { SX.keep = true; location.replace('/login?reason=signedout'); } }); // Back button restoring a cached page
  window.addEventListener('beforeunload', function () { if (S.me && !SX.keep) { try { sessionStorage.removeItem('sx_tab'); } catch (e) {} } });

  // ---------------------------------------------------------------- start
  var fresh = false; try { fresh = !sessionStorage.getItem('sx_tab'); } catch (e) {}
  if (fresh) { // a new tab or a restored browser: the previous visit ended, so sign in again
    SX.keep = true; fetch('/api/auth/logout', { method: 'POST', headers: { 'X-Sentinel': '1' }, credentials: 'same-origin' }).catch(function () {}).then(function () { location.replace('/login?reason=signedout'); }); return;
  }
  api('GET', '/api/me').then(function (me) {
    if (me.must_change_password) { SX.keep = true; location.href = '/login?reason=change'; return; }
    S.me = me.user; S.isAdmin = (me.user.roles || []).indexOf('System Administrator') >= 0; S.perms = me.perms; S.policy = me.policy; S.demo = !!me.demo;
    return Promise.all([api('GET', '/api/nav'), api('GET', '/api/meta'), api('GET', '/api/ai/status').catch(function () { return null; })]).then(function (r) {
      S.nav = r[0].suites; S.meta = r[1]; S.ai = r[2]; SX.AI = r[2]; buildSide(); buildTop(); window.addEventListener('hashchange', route); loadDemoPages(); route();
    });
  }).catch(function (e) { if (e && e.status !== 401) $('#main').innerHTML = '<div class="alert bad">Could not start Sentinel: ' + esc(e.message) + '</div>'; });
})();
