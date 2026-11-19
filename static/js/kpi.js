/* Weekly KPI: the weekly report as a live module, with as-of dates, manual entry, import, automatic sources and Excel download. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#2F6FD6', asOf = '';
  var HOW = { manual: ['Manual', '#E3E9F2', '#40536C'], import: ['Imported', '#DCE8FB', '#1B4A96'], feed: ['Feed', '#DDF1E3', '#146C2E'], internal: ['Sentinel', '#E6DDF8', '#5B3FA8'], seed: ['Starter set', '#FFF1B8', '#7D4A00'], live: ['Live', '#D4F4DF', '#0B6B2E'], web: ['Web search', '#FDE7D0', '#8A4B00'] };
  var TABS = [['report', 'Weekly report'], ['enter', 'Enter and import'], ['charts', 'Charts and PowerPoint'], ['verified', 'Verified sources'], ['sources', 'Feeds and automation']];
  function tabs(cur) { return SX.tabs('m/weekly_kpi', TABS, cur, COLOR); }
  function head(cur, extra) { return SX.head('Events &amp; Fraud &rsaquo; Weekly KPI', 'Weekly KPI', COLOR, extra || '') + '<div id="livechip" style="margin:-2px 0 10px"></div>' + tabs(cur); }
  function num(v, dec) { return v == null ? '\u2013' : Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }); }
  function val(k, v) { var u = k.unit || ''; return num(v, k.decimals) + (u === '%' ? '%' : u ? ' <span class="muted small">' + esc(u) + '</span>' : ''); }
  function how(m, lf) { var h = (lf && m !== 'live') ? ['Live feed', '#EAF7EF', '#0B6B2E'] : (HOW[m] || HOW.manual); return '<span class="badge" style="background:' + h[1] + ';color:' + h[2] + '">' + h[0] + '</span>'; }
  function spark(vs) {
    if (!vs || vs.length < 2) return '<span class="muted small">\u2013</span>';
    var mn = Math.min.apply(null, vs), mx = Math.max.apply(null, vs), r = (mx - mn) || 1, w = 84, h = 22;
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '"><polyline fill="none" stroke="#4C5FD5" stroke-width="1.6" points="' + vs.map(function (v, i) { return (i * (w - 4) / (vs.length - 1) + 2).toFixed(1) + ',' + (h - 3 - (v - mn) / r * (h - 6)).toFixed(1); }).join(' ') + '"/><circle cx="' + (w - 2) + '" cy="' + (h - 3 - (vs[vs.length - 1] - mn) / r * (h - 6)).toFixed(1) + '" r="2.4" fill="#4C5FD5"/></svg>';
  }
  function change(k) {
    if (k.change == null) return '<span class="muted">\u2013</span>';
    var c = k.good === true ? '#146C2E' : k.good === false ? '#B3261E' : '#51627A', a = k.change > 0 ? '\u25B2' : k.change < 0 ? '\u25BC' : '\u25AC';
    return '<span style="color:' + c + ';font-weight:700;white-space:nowrap">' + a + ' ' + num(Math.abs(k.change), k.decimals) + '</span>' + (k.change_pct != null ? '<div class="small muted">' + num(k.change_pct, 1) + '%</div>' : '');
  }

  SX.pages.kpi = function (tab) {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    (({ enter: enter, sources: sources, charts: function () { SX.kpiCharts(); }, verified: function () { SX.kpiVerified(); } })[tab] || report)();
    api('POST', '/api/kpi/live/kick').catch(function () {}); // opening the page asks for fresh market data when the last update is older than 10 minutes
    [900, 3500, 9000].forEach(function (ms) { setTimeout(liveChip, ms); });
  };
  function ago(ts) { if (!ts) return 'never'; var d = new Date(/(Z|[+-]\d\d:?\d\d)$/.test(ts) ? ts : ts.replace(' ', 'T') + 'Z'), m = isNaN(d) ? null : Math.round((Date.now() - d.getTime()) / 60000); if (m === null) return 'a while ago'; return m < 1 ? 'just now' : m < 90 ? m + ' min ago' : Math.round(m / 60) + ' h ago'; }
  function liveChip() {
    var el = $('#livechip'); if (!el) return;
    api('GET', '/api/kpi/live').then(function (s) {
      var on = s.online, col = on ? '#2FA84F' : s.online === false ? '#EF2B2B' : '#98A2B3';
      el.innerHTML = '<span class="pill" style="background:#fff;border:1px solid #E1E6EE"><i style="display:inline-block;width:9px;height:9px;border-radius:50%;background:' + col + ';margin-right:6px' + (on ? ';animation:pulse 2s infinite' : '') + '"></i>' + (s.mode === 'off' ? 'Live data is switched off' : on ? 'Live market data: online, updated ' + ago(s.last_ok) : s.online === false ? 'Offline: live data will update when the internet is back (last ' + ago(s.last_ok) + ')' : 'Live market data: waiting for the first update') + '</span>';
    }, function () {});
  }

  function readyBox() {
    api('GET', '/api/kpi/readiness').then(function (r) {
      var box = $('#ready'); if (!box) return;
      var n = function (a) { return a.length; }, ok = function (a) { return a.filter(function (x) { return x.fresh; }).length; };
      var list = function (a) { return a.filter(function (x) { return !x.fresh; }).map(function (x) { return '<li>' + esc(x.name) + ' <span class="muted small">' + (x.last ? 'last ' + SX.fmt(x.last, true) : 'no reading yet') + '</span></li>'; }).join(''); };
      var tile = function (t, c, a, sub) { return '<div class="card" style="flex:1;min-width:200px;border-top:4px solid ' + c + ';margin:0"><div class="muted small">' + t + '</div><div style="font-size:26px;font-weight:800;color:#1B2A41">' + ok(a) + '<span class="muted" style="font-size:15px"> / ' + n(a) + ' up to date</span></div><div class="small muted">' + sub + '</div></div>'; };
      box.innerHTML = '<div class="card" style="margin-bottom:10px;border-left:5px solid #2F6FD6"><div class="toolbar" style="margin:0 0 8px"><h3 style="margin:0">Report status for ' + SX.fmt(r.today, true) + (r.start ? ' <span class="muted small">running since ' + SX.fmt(r.start, true) + '</span>' : '') + '</h3>' + (r.can.run ? '<button class="btn p" id="bring" style="--c:#2F6FD6">Bring report up to date</button>' : '') + '</div>' +
        '<div style="display:flex;gap:10px;flex-wrap:wrap">' + tile('Live market and macro data', '#2FA84F', r.live, 'refreshes itself whenever this computer is online') + tile('Published statistics', '#F0A04B', r.published, 'appear as ZIMSTAT, RBZ, ZERA and others release them') + tile('EcoCash and Sentinel measures', '#E0474C', r.internal, 'entered by the departments, or measured by Sentinel') + '</div>' +
        (n(r.published) - ok(r.published) + n(r.internal) - ok(r.internal) ? '<details style="margin-top:8px"><summary class="small" style="cursor:pointer">Show what is still waiting</summary><div style="display:flex;gap:24px;flex-wrap:wrap"><div><b class="small">Published, awaiting release</b><ul class="small">' + (list(r.published) || '<li>Nothing</li>') + '</ul></div><div><b class="small">Needs the department</b><ul class="small">' + (list(r.internal) || '<li>Nothing</li>') + '</ul></div></div></details>' : '') + '</div>';
      var b = $('#bring'); if (b) b.addEventListener('click', function () { b.disabled = true; b.textContent = 'Updating...'; api('POST', '/api/kpi/bring-up-to-date').then(function (x) { SX.toast((x.status && x.status.online === false ? 'No internet: live figures will update when this computer is online' : (x.status.updated || 0) + ' live figures updated'), x.status && x.status.online === false ? 'bad' : 'ok'); SX.pages.kpi(); }, function (e) { SX.toast(e.message, 'bad'); b.disabled = false; b.textContent = 'Bring report up to date'; }); });
    }, function () {});
  }

  function report() {
    var main = $('#main');
    Promise.all([api('GET', '/api/kpi/weekly' + (asOf ? '?as_of=' + asOf : '')), api('GET', '/api/kpi/charts' + (asOf ? '?as_of=' + asOf : '')), api('GET', '/api/kpi/deck' + (asOf ? '?as_of=' + asOf : ''))]).then(function (rr) {
      var d = rr[0], dk = rr[2], chg = {}; rr[1].groups.forEach(function (g) { chg[g.name] = g; }); d.deck = dk; d.chg = chg;
      var can = d.can, S = d.summary; asOf = asOf || ''; var sel = asOf || d.as_of;
      var opts = ['<option value="">Latest data (' + SX.fmt(d.latest_date || d.as_of, true) + ')</option>'].concat(d.dates.map(function (x) { return '<option value="' + x + '"' + (asOf === x ? ' selected' : '') + '>' + SX.fmt(x, true) + '</option>'; })).join('');
      var h = head('report', '<label class="small muted" style="margin-right:6px">As of</label><select id="asof" style="width:210px">' + opts + '</select>' + (SX.can('weekly_kpi', 'export') ? '<a class="btn" href="/api/kpi/export.xlsx?as_of=' + sel + '">Download Excel</a><a class="btn p" style="--c:#2F6FD6" href="/api/kpi/export.pptx?as_of=' + sel + '">Download PowerPoint</a>' : '') + (can.create ? '<button class="btn" id="refresh">Refresh now</button>' : '') + '<button class="btn" id="wbk">Workbooks: delete / restore</button>');
      h += '<div id="ready"></div>';
      h += (!dk.loaded && can.create && S.total ? '<div class="alert warn" style="margin-bottom:10px"><b>The September 2026 report is not loaded yet.</b> It brings the new indicators, the report\'s charts, slide text and status tiles, and the transaction data behind the transaction slides. Values you entered are kept. <button class="btn p" id="upd" style="--c:#2F6FD6;margin-left:8px">Update to the September 2026 report</button></div>' : '');
      if (!S.total) {
        main.innerHTML = h + '<div class="card" style="text-align:center;padding:36px"><h3>No indicators yet</h3><p class="muted">Start from your September 2026 weekly KPI report: about 95 indicators with their history, sources and targets (inflation, fuel, exchange rates, money and credit, payments sector, fraud cases, transaction success rates), plus Sentinel&rsquo;s own measures. You can add, change or remove any of them.</p>' + (can.create ? '<button class="btn p" id="seed" style="--c:#2F6FD6">Load the September 2026 report</button> <button class="btn" id="addk">+ Add an indicator</button>' : '') + '</div>';
        wire(); return;
      }
      var k = function (l, v, c, s) { return '<div class="card kpi s2" style="--c:' + c + '"><div class="l">' + l + '</div><div class="v">' + v + '</div><div class="d">' + s + '</div></div>'; };
      h += (dk.carried_from ? '<div class="alert warn" style="margin-bottom:10px">The slide text and status tiles on the PowerPoint and Excel are carried over from ' + SX.fmt(dk.carried_from, true) + '. Update them for this week under each group\'s <b>Slide text</b>.</div>' : '') + '<div class="alert info" style="margin-bottom:10px"><b>Figures as of ' + SX.fmt(d.as_of, true) + '.</b> Each value shows the date it is really from: a value older than its reporting frequency allows is marked <b>stale</b>. Every number is traceable to its source and to how it was captured.</div><div class="grid">' +
        k('Indicators', S.total, '#4C5FD5', S.with_data + ' with data') + k('Stale', S.stale, S.stale ? '#F0A04B' : '#2FA84F', 'older than their frequency') + k('Off target', S.off_target, S.off_target ? '#E0474C' : '#2FA84F', 'against their targets') + k('Automatic', S.auto, '#7B5CD6', 'feeds and Sentinel') + k('Manual or import', S.manual, '#2F6FD6', 'entered by people') + '<div class="card s2"><h3>Download</h3><div class="small muted">Excel with the report, full history, commentary and sources.</div></div>';
      d.groups.forEach(function (g) {
        h += '<div class="card s12"><h3>' + esc(g.name) + ' <span class="muted small">' + g.kpis.length + ' indicators</span>' + (can.edit ? ' <button class="btn sm" data-slide="' + esc(g.name) + '" style="float:right">Slide text</button>' : '') + '</h3><table class="t"><tr><th>Indicator</th><th style="text-align:right">Latest</th><th style="text-align:right">Previous</th><th>Change</th><th>Target</th><th>As of</th><th>How</th><th>Last 12</th><th></th></tr>' + g.kpis.map(function (x) {
          var L = x.latest, st = x.status === 'ok' ? '<span class="badge b-active">On target</span>' : x.status === 'off' ? '<span class="badge" style="background:#EF2B2B;color:#fff">Off target</span>' : '';
          return '<tr><td><b>' + esc(x.name) + '</b><div class="small muted">' + esc(x.source || '') + (x.source_url ? ' &middot; <a href="' + esc(x.source_url) + '" target="_blank" rel="noopener noreferrer">source</a>' : '') + '</div></td><td style="text-align:right;font-size:15px;font-weight:700">' + (L ? val(x, L.value) : '<span class="muted">no data</span>') + '</td><td style="text-align:right" class="muted">' + (x.previous ? val(x, x.previous.value) : '\u2013') + '</td><td>' + change(x) + '</td><td>' + (x.target != null ? (x.better === 'up' ? '\u2265 ' : '\u2264 ') + num(x.target, x.decimals) + '<div>' + st + '</div>' : '') + '</td><td>' + (L ? SX.fmt(L.period, true) + (x.stale ? '<div><span class="badge" style="background:#FDB022;color:#3A2600">stale ' + x.age_days + ' days</span></div>' : '') : '') + '</td><td>' + (L ? how(L.method, x.live_feed) : (x.live_feed ? how('', true) : '')) + '</td><td>' + spark(x.spark) + '</td><td style="text-align:right">' + (can.create && !x.has_feed && !x.internal_key ? '<button class="btn sm" data-up="' + x.id + '">Update</button>' : '') + '</td></tr>';
        }).join('') + '</table>' + SX.chartGrid((chg[g.name] || {}).charts) + (can.edit ? '<label class="f" style="margin-top:8px">Commentary for this week<textarea data-note="' + esc(g.name) + '" rows="2" placeholder="What moved and why it matters">' + esc(g.note) + '</textarea></label>' : g.note ? '<p style="margin:8px 0 0"><b>Commentary:</b> ' + esc(g.note) + '</p>' : '') + '</div>';
      });
      Object.keys(chg).forEach(function (n) { if (d.groups.some(function (g) { return g.name === n; })) return; var live = chg[n].charts.filter(function (c) { return !c.empty; }), gc = SX.chartGrid(chg[n].charts); if (gc) h += '<div class="card s12"><h3>' + esc(n) + ' <span class="muted small">' + live.length + ' charts from uploaded data</span>' + (can.edit ? ' <button class="btn sm" data-slide="' + esc(n) + '" style="float:right">Slide text</button>' : '') + '</h3>' + gc + '</div>'; });
      main.innerHTML = h + '</div>'; readyBox();
      wire(d);
    });
  }
  function wire(d) {
    var main = $('#main'), on = function (id, fn) { var e = $(id); if (e) e.addEventListener('click', fn); };
    var s = $('#asof'); if (s) s.addEventListener('change', function () { asOf = s.value; report(); });
    on('#seed', function () { api('POST', '/api/kpi/seed').then(function (r) { SX.toast('Loaded ' + r.added + ' indicators and ' + r.readings + ' readings', 'ok'); report(); }, function (e) { SX.toast(e.message, 'bad'); }); });
    on('#addk', function () { kpiForm(null, 'kpi', report); });
    on('#upd', function () { api('POST', '/api/kpi/seed', { reset_charts: true }).then(function (r) { SX.toast('September 2026 report loaded: ' + r.added + ' new indicators, ' + r.readings + ' readings, ' + r.slides + ' slide texts', 'ok'); report(); }, function (e) { SX.toast(e.message, 'bad'); }); });
    on('#wbk', function () { location.hash = '#/m/weekly_kpi/enter'; setTimeout(function () { var e = document.getElementById('loadedbox'); if (e) e.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 900); });
    on('#refresh', function () { api('POST', '/api/kpi/refresh').then(function (r) { var bad = r.feeds.filter(function (f) { return !f.ok; }).length; SX.toast('Sentinel measures updated: ' + r.internal_updated + '. Feeds tried: ' + r.feeds.length + (bad ? ' (' + bad + ' failed, see Sources and automation)' : ''), bad ? 'bad' : 'ok'); report(); }, function (e) { SX.toast(e.message, 'bad'); }); });
    if (!d) return;
    $$('[data-slide]', main).forEach(function (b) { b.addEventListener('click', function () { slideText(b.dataset.slide, d); }); });
    $$('[data-up]', main).forEach(function (b) { b.addEventListener('click', function () { var k = null; d.groups.forEach(function (g) { g.kpis.forEach(function (x) { if (x.id === +b.dataset.up) k = x; }); }); entryForm(k, report); }); });
    $$('[data-note]', main).forEach(function (t) { t.addEventListener('change', function () { api('PUT', '/api/kpi/notes', { as_of: d.as_of, grp: t.dataset.note, text: t.value }).then(function () { SX.toast('Commentary saved', 'ok'); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
  }
  function slideText(group, d) {
    var dk = d.deck, g = d.chg[group] || { charts: [], per_slide: 4 }, live = g.charts.filter(function (c) { return !c.empty; }).length, pages = Math.max(1, Math.ceil(live / (g.per_slide || 4))), cur = dk.pages[group] || [];
    var v = function (x) { return esc(x == null ? '' : x); }, html = '<p class="muted small" style="margin-top:0">This is the text on the slide for the report dated ' + SX.fmt(d.as_of, true) + ': the subtitle, the commentary in the blue panel, the four status tiles (one word and a caption each) and the source line. The PowerPoint and the Excel report both use it.</p>';
    for (var p = 1; p <= pages; p++) {
      var x = cur.filter(function (r) { return r.page === p; })[0] || { subtitle: '', source: '', tiles: [], bullets: [] };
      html += '<div class="card" style="box-shadow:none;border:1px solid #E1E6EE;margin-bottom:10px"><b>Slide ' + p + ' of ' + pages + '</b><div class="form2"><label class="f full">Subtitle<input type="text" data-p="' + p + '" data-f="subtitle" value="' + v(x.subtitle) + '"></label><label class="f">Source<input type="text" data-p="' + p + '" data-f="source" value="' + v(x.source) + '"></label><div></div><label class="f full">Commentary (one line each, up to five)<textarea data-p="' + p + '" data-f="bullets" rows="4">' + v((x.bullets || []).join('\n')) + '</textarea></label></div><div class="form2">';
      for (var i = 0; i < 4; i++) { var t = (x.tiles || [])[i] || {}; html += '<label class="f">Tile ' + (i + 1) + ': word<input type="text" data-p="' + p + '" data-f="tw' + i + '" value="' + v(t.word) + '" placeholder="e.g. STABLE"></label><label class="f">caption<input type="text" data-p="' + p + '" data-f="tc' + i + '" value="' + v(t.caption) + '" placeholder="e.g. Exchange rates"></label>'; }
      html += '</div></div>';
    }
    var m = SX.modal({ title: 'Slide text: ' + group, wide: true, sticky: true, html: html, buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () {
      var jobs = [];
      for (var p = 1; p <= pages; p++) {
        var f = {}; SX.$$('[data-p="' + p + '"]', m.el).forEach(function (e) { f[e.dataset.f] = e.value; });
        var tiles = [0, 1, 2, 3].map(function (i) { return { word: f['tw' + i], caption: f['tc' + i] }; }).filter(function (t) { return t.word || t.caption; });
        jobs.push(api('PUT', '/api/kpi/deck', { as_of: d.as_of, grp: group, page: p, subtitle: f.subtitle, source: f.source, tiles: tiles, bullets: (f.bullets || '').split(/\n/).filter(function (z) { return z.trim(); }) }));
      }
      return Promise.all(jobs).then(function () { SX.toast('Slide text saved', 'ok'); report(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  function entryForm(k, after, kind) {
    var m = SX.modal({ title: 'Update ' + k.name, sub: k.latest ? 'Latest: ' + num(k.latest.value, k.decimals) + ' as of ' + SX.fmt(k.latest.period, true) : 'No value yet', sticky: true, html: '<div class="form2"><label class="f">As-of date *<input type="date" id="ed" value="' + new Date().toISOString().slice(0, 10) + '" max="' + new Date().toISOString().slice(0, 10) + '"></label><label class="f">Value *' + (k.unit ? ' (' + esc(k.unit) + ')' : '') + '<input type="number" step="any" id="ev"></label><label class="f full">Source note<input type="text" id="en" placeholder="e.g. RBZ press statement 8 July"></label></div><p class="muted small">Use the date the value is really for, not today&rsquo;s date, so the report can show how old it is.</p>', buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () {
      return api('POST', '/api/kpi/readings', { id: k.id, period: m.$('#ed').value, value: m.$('#ev').value, note: m.$('#en').value }).then(function (r) { SX.toast(r.result === 'same' ? 'No change' : 'Saved' + (r.alert ? ' (' + r.alert + ' alert)' : ''), 'ok'); after(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  SX.kpiEntryForm = entryForm;

  function importDialog(kind, after) {
    var m = SX.modal({ title: 'Import readings from Excel or CSV', wide: true, sticky: true, html: '<p class="muted small" style="margin-top:0">Use the Excel template (fill the <b>New date</b> and <b>New value</b> columns), or any CSV or Excel file with the columns <b>Code, Date, Value</b> and optionally <b>Note</b>. Nothing is saved until you press Import.</p><input type="file" id="kf" accept=".xlsx,.csv"><div id="kr" style="margin-top:12px"></div>', buttons: [{ label: 'Close' }, { label: 'Import', cls: 'p', onClick: function () {
      var f = m.$('#kf').files[0]; if (!f) { SX.toast('Choose a file first', 'bad'); return false; }
      return send(f, 0).then(function (d) { SX.toast('Imported ' + d.valid + ' readings (' + d.new + ' new, ' + d.replaced + ' replaced)', 'ok'); after(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
    function send(f, dry) { return f.arrayBuffer().then(function (b) { return fetch('/api/kpi/import?kind=' + kind + '&dry=' + dry, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Sentinel': '1', 'X-Filename': encodeURIComponent(f.name) }, credentials: 'same-origin', body: b }); }).then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.message || 'Import failed'); return d; }); }); }
    m.$('#kf').addEventListener('change', function () {
      var f = this.files[0], box = m.$('#kr'); if (!f) return; box.innerHTML = '<span class="muted">Checking the file...</span>';
      send(f, 1).then(function (d) { box.innerHTML = '<div class="alert info"><b>' + d.valid + ' readings</b> are ready: ' + d.new + ' new, ' + d.replaced + ' replacing an earlier value, ' + d.unchanged + ' unchanged.</div>' + (d.unknown.length ? '<div class="alert warn">Unknown codes (skipped): ' + esc(d.unknown.join(', ')) + '</div>' : '') + (d.errors.length ? '<div class="alert warn"><b>' + d.error_count + ' rows have problems and will be skipped</b><ul style="margin:4px 0 0 18px">' + d.errors.map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul></div>' : ''); }, function (e) { box.innerHTML = '<div class="alert bad">' + esc(e.message) + '</div>'; });
    });
  }
  SX.kpiImport = importDialog;
  SX.kpiUI = { head: head, num: num, how: how, spark: spark, val: val };

  function enter() {
    var main = $('#main');
    api('GET', '/api/kpi/weekly').then(function (d) {
      var can = d.can, due = [];
      d.groups.forEach(function (g) { g.kpis.forEach(function (x) { if (!x.has_feed && !x.internal_key && (!x.latest || x.stale)) due.push(x); }); });
      main.innerHTML = head('enter') + '<div class="card"><h3>Bring readings in</h3><p class="muted small" style="margin-top:0">Three ways to update, all kept with their date, source and who captured them: type a value for one indicator, fill in the Excel template and import it, or let a feed or Sentinel update it (Sources and automation).</p><div class="toolbar"><a class="btn" href="/api/kpi/template.xlsx?kind=kpi">Download the Excel template</a>' + (can.create ? '<button class="btn p" id="imp" style="--c:#2F6FD6">Import Excel or CSV</button>' : '') + '</div></div>' +
        '<div class="card" style="margin-top:12px"><h3>Waiting for an update (' + due.length + ')</h3>' + (due.length ? '<div style="max-height:520px;overflow:auto"><table class="t"><tr><th>Indicator</th><th>Last value</th><th>As of</th><th>Frequency</th><th></th></tr>' + due.map(function (x) { return '<tr><td><b>' + esc(x.name) + '</b><div class="small muted">' + esc(x.source || '') + '</div></td><td>' + (x.latest ? val(x, x.latest.value) : '\u2013') + '</td><td>' + (x.latest ? SX.fmt(x.latest.period, true) + ' <span class="badge" style="background:#FDB022;color:#3A2600">stale ' + x.age_days + ' days</span>' : 'never') + '</td><td>' + esc(x.freq) + '</td><td style="text-align:right">' + (can.create ? '<button class="btn sm p" style="--c:#2F6FD6" data-up="' + x.id + '">Enter value</button>' : '') + '</td></tr>'; }).join('') + '</table></div>' : '<div class="empty">Everything is up to date.</div>') + '</div>';
      var lb = document.createElement('div'); lb.id = 'loadedbox'; main.appendChild(lb); loadedBox();
      var i = $('#imp'); if (i) i.addEventListener('click', function () { importDialog('kpi', enter); });
      if (SX.kpiEnterExtras) SX.kpiEnterExtras(d, enter);
      $$('[data-up]', main).forEach(function (b) { b.addEventListener('click', function () { entryForm(due.filter(function (x) { return x.id === +b.dataset.up; })[0], enter); }); });
    });
  }


  function kpiForm(k, kind, after) {
    var edit = !!k, v = function (x) { return esc(k && k[x] != null ? k[x] : ''); }, opt = function (arr, cur) { return arr.map(function (a) { return '<option value="' + a[0] + '"' + (cur === a[0] ? ' selected' : '') + '>' + a[1] + '</option>'; }).join(''); };
    api('GET', '/api/kpi/catalog?kind=' + kind).then(function (c) {
      var m = SX.modal({ title: edit ? 'Edit ' + k.code : 'Add an indicator', wide: true, sticky: true, html: '<form id="kf2" class="form2"><label class="f">Code * <span class="muted">(letters, numbers, underscore)</span><input type="text" name="code" value="' + v('code') + '"' + (edit ? ' readonly' : '') + '></label><label class="f">Group<input type="text" name="grp" value="' + v('grp') + '"></label><label class="f full">Name *<input type="text" name="name" value="' + v('name') + '"></label>' +
        '<label class="f">Unit<input type="text" name="unit" value="' + v('unit') + '"></label><label class="f">How often<select name="freq">' + opt(['daily', 'weekly', 'monthly', 'quarterly', 'annual'].map(function (x) { return [x, x]; }), k ? k.freq : 'weekly') + '</select></label><label class="f">Better when<select name="better">' + opt([['up', 'higher is better'], ['down', 'lower is better'], ['none', 'no preference']], k ? k.better : 'none') + '</select></label><label class="f">Target (optional)<input type="number" step="any" name="target" value="' + v('target') + '"></label><label class="f">Decimals<input type="number" min="0" max="6" name="decimals" value="' + (k ? k.decimals : 1) + '"></label><label class="f">Source<input type="text" name="source" value="' + v('source') + '"></label><label class="f full">Link to the source (https://)<input type="text" name="source_url" value="' + v('source_url') + '"></label>' +
        '<label class="f full">Automatic feed link (https://, CSV or JSON; the host must be approved first)<input type="text" name="feed_url" value="' + v('feed_url') + '"></label><label class="f">Feed format<select name="feed_fmt">' + opt([['csv', 'CSV'], ['json', 'JSON']], k ? k.feed_fmt : 'csv') + '</select></label><label class="f">Feed columns (date,value)<input type="text" name="feed_keys" value="' + v('feed_keys') + '" placeholder="date,value"></label>' +
        '<label class="f full">Or let Sentinel calculate it<select name="internal_key"><option value="">no: entered by people or a feed</option>' + Object.keys(c.internal).map(function (x) { return '<option value="' + x + '"' + (k && k.internal_key === x ? ' selected' : '') + '>' + esc(c.internal[x]) + '</option>'; }).join('') + '</select></label></form>', buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () {
          var f = m.$('#kf2'), b = { kind: kind }; ['code', 'grp', 'name', 'unit', 'freq', 'better', 'target', 'decimals', 'source', 'source_url', 'feed_url', 'feed_fmt', 'feed_keys', 'internal_key'].forEach(function (x) { b[x] = f[x].value; });
          return api(edit ? 'PUT' : 'POST', '/api/kpi/catalog' + (edit ? '/' + k.id : ''), b).then(function () { SX.toast('Saved', 'ok'); after(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
        } }] });
    });
  }
  SX.kpiForm = kpiForm;

  function liveBox() {
    api('GET', '/api/kpi/live').then(function (s) {
      var box = $('#livebox'); if (!box) return; var errs = Object.keys(s.errors || {});
      box.innerHTML = '<div class="card" style="border-left:5px solid ' + (s.online ? '#2FA84F' : '#F0A04B') + '"><h3>Live market data <span class="badge ' + (s.mode === 'off' ? 'b-plan' : 'b-live') + '">' + (s.mode === 'off' ? 'Off' : s.online ? 'Online' : 'Waiting for internet') + '</span></h3>' +
        '<p class="small" style="margin-top:0">While this computer is online Sentinel fetches the market figures by itself, about every 30 minutes (every 90 seconds until it connects): <b>gold, silver, platinum, palladium, copper, oil, maize, wheat, cocoa, cotton</b> (the same futures contracts Bloomberg shows), <b>ZiG exchange rates</b>, <b>stablecoin pegs</b>, and <b>GDP and remittances</b> (World Bank). Each reading is marked <b>Live</b> with its source and time. Last successful update: <b>' + ago(s.last_ok) + '</b>; ' + (s.updated || 0) + ' readings written in the last round. Indicators that no public service publishes (ZERA fuel prices, RBZ money supply, ZIMSTAT inflation) are updated by file, by hand or from the research suggestions below.</p>' +
        '<div class="toolbar">' + (s.can.run ? '<button class="btn p" id="lv-run" style="--c:#2FA84F">Update now</button>' : '') + (s.can.approve ? '<select id="lv-mode" style="width:auto;min-width:240px"><option value="on"' + (s.mode !== 'off' ? ' selected' : '') + '>Update automatically</option><option value="off"' + (s.mode === 'off' ? ' selected' : '') + '>Off</option></select>' : '') + '</div>' +
        (errs.length ? '<div class="alert warn small" style="margin-top:8px"><b>Not available this round:</b> ' + errs.slice(0, 10).map(function (c) { return esc(c) + ' (' + esc(s.errors[c]) + ')'; }).join('; ') + '</div>' : '') + '</div>';
      var r = $('#lv-run'); if (r) r.addEventListener('click', function () { r.disabled = true; r.textContent = 'Updating...'; api('POST', '/api/kpi/live/run').then(function (x) { SX.toast(x.online ? x.updated + ' readings updated' : 'No internet connection', x.online ? 'ok' : 'bad'); sources(); }, function (e) { SX.toast(e.message, 'bad'); sources(); }); });
      var m = $('#lv-mode'); if (m) m.addEventListener('change', function () { api('PUT', '/api/kpi/live/mode', { mode: m.value }).then(function () { sources(); }); });
    });
  }
  function loadedBox() {
    api('GET', '/api/kpi/imports').then(function (d) {
      var box = $('#loadedbox'); if (!box) return; var st = d.starter;
      box.innerHTML = '<div class="card" style="margin-top:12px"><h3>What has been loaded</h3><p class="muted small" style="margin-top:0">Every file import is kept as a batch. Deleting a batch removes the readings it added and puts back any value it replaced.</p>' +
        (d.imports.length ? '<table class="t"><tr><th>When</th><th>By</th><th>File</th><th>New</th><th>Replaced</th><th>Still in the system</th><th></th></tr>' + d.imports.map(function (i) { return '<tr><td>' + SX.fmt(i.ts) + '</td><td>' + esc(i.by || '') + '</td><td>' + esc(i.filename || '(file)') + ' <span class="muted small">' + esc(i.kind || '') + '</span></td><td>' + i.new + '</td><td>' + i.replaced + '</td><td>' + i.readings_now + '</td><td>' + (d.can.delete ? '<button class="btn sm d" data-di="' + i.id + '">Delete this import</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '<div class="muted small">No file has been imported yet.</div>') +
        ((d.deleted || []).length ? '<h3 style="margin-top:14px">Deleted imports <span class="muted small">can be restored</span></h3><table class="t"><tr><th>File</th><th>Deleted</th><th>Readings kept</th><th></th></tr>' + d.deleted.map(function (i) { return '<tr><td>' + esc(i.filename || '(file)') + '</td><td>' + SX.fmt(i.deleted_at) + '</td><td>' + i.readings + '</td><td>' + (d.can.delete ? '<button class="btn sm" data-ri="' + i.id + '">Restore</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '') +
        '<h3 style="margin-top:14px">Starter set <span class="muted small">figures that came with the system for demonstration</span></h3><p class="small" style="margin-top:0">' + st.readings + ' readings, ' + st.slides + ' slide texts and ' + st.transactions + ' transaction rows. ' + (d.can.delete && (st.readings || st.slides || st.transactions) ? '<button class="btn sm d" id="rm-starter">Remove the starter set</button>' : '') + (d.can.delete && st.backup ? ' <button class="btn sm" id="rs-starter">Restore the removed starter set</button>' : '') + '</p></div>';
      $$('[data-di]', box).forEach(function (b) { b.addEventListener('click', function () { SX.modal({ title: 'Delete this import?', html: '<p>The readings this file added are removed, and any value it replaced is put back. This is recorded in the audit trail.</p>', buttons: [{ label: 'Cancel' }, { label: 'Delete import', cls: 'd', onClick: function () { return api('DELETE', '/api/kpi/imports/' + b.dataset.di).then(function (x) { SX.toast(x.removed + ' readings removed, ' + x.restored + ' restored', 'ok'); enter(); }); } }] }); }); });
      $$('[data-ri]', box).forEach(function (b) { b.addEventListener('click', function () { api('POST', '/api/kpi/imports/' + b.dataset.ri + '/restore').then(function (x) { SX.toast(x.restored + ' readings restored', 'ok'); enter(); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
      var rr = $('#rs-starter'); if (rr) rr.addEventListener('click', function () { api('POST', '/api/kpi/starter/restore').then(function (x) { SX.toast('Starter set restored', 'ok'); enter(); }, function (e) { SX.toast(e.message, 'bad'); }); });
      var rs = $('#rm-starter'); if (rs) rs.addEventListener('click', function () { SX.modal({ title: 'Remove the starter set?', html: '<p>The readings, slide texts and transaction rows that came with Sentinel are removed. Figures you imported or typed, and live figures, stay.</p>', buttons: [{ label: 'Cancel' }, { label: 'Remove', cls: 'd', onClick: function () { return api('POST', '/api/kpi/starter/remove').then(function (x) { SX.toast('Removed ' + x.readings + ' readings', 'ok'); enter(); }); } }] }); });
    });
  }
  function autoBox() {
    api('GET', '/api/kpi/auto').then(function (a) {
      var box = $('#autobox'); if (!box) return;
      box.innerHTML = '<div class="card" style="border-left:5px solid #2FA84F"><h3>Automatic research updates <span class="badge ' + (a.mode === 'off' ? 'b-plan' : 'b-live') + '">' + (a.mode === 'auto' ? 'On: enters readings' : a.mode === 'review' ? 'On: suggestions only' : 'Off') + '</span></h3>' +
        '<p class="small" style="margin-top:0">Every morning Sentinel opens the published source of each indicator (' + a.watched + ' watched), and searches the web when the page has no figure, looks for the latest value next to the indicator&rsquo;s own words, and records it with the page address and the sentence it was taken from. Readings found this way are marked <b>web</b> so a person can confirm them. ' + (a.last ? 'Last run ' + SX.fmt(a.last.ts) + ': ' + a.last.tried + ' tried, ' + a.last.entered + ' entered, ' + a.last.suggested + ' suggested.' : 'It has not run yet.') + '</p>' +
        '<div class="toolbar">' + (a.can.run ? '<button class="btn p" id="au-run" style="--c:#2FA84F">Run the research now</button>' : '') + (a.can.approve ? '<select id="au-mode" style="width:auto;min-width:240px"><option value="auto"' + (a.mode === 'auto' ? ' selected' : '') + '>Enter readings automatically</option><option value="review"' + (a.mode === 'review' ? ' selected' : '') + '>Suggest only: a person accepts</option><option value="off"' + (a.mode === 'off' ? ' selected' : '') + '>Off</option></select>' : '') + '</div>' +
        (a.suggestions.length ? '<table class="t"><tr><th>Indicator</th><th>Found</th><th>Taken from</th><th></th></tr>' + a.suggestions.map(function (s) { return '<tr><td><b>' + esc(s.code) + '</b> ' + esc(s.name) + '</td><td><b>' + s.value + '</b><div class="muted small">' + esc(s.period) + '</div></td><td class="small">' + esc(s.snippet || '') + '<br><a href="' + esc(s.source_url || '#') + '" target="_blank" rel="noopener">source</a></td><td>' + (a.can.run ? '<button class="btn sm p" data-sa="' + s.id + '">Accept</button> <button class="btn sm d" data-sr="' + s.id + '">Reject</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '') + '</div>';
      var on = function (id, fn) { var e = $(id); if (e) e.addEventListener(id.charAt(0) === '#' && id !== '#au-mode' ? 'click' : 'change', fn); };
      on('#au-run', function () { SX.toast('Researching sources... this can take a minute'); api('POST', '/api/kpi/auto/run').then(function (r) { SX.toast(r.results.filter(function (x) { return x.status === 'entered'; }).length + ' reading(s) entered, ' + r.results.filter(function (x) { return x.status === 'suggested'; }).length + ' suggested', 'ok'); sources(); }, function (e) { SX.toast(e.message, 'bad'); }); });
      on('#au-mode', function () { api('PUT', '/api/kpi/auto/mode', { mode: $('#au-mode').value }).then(function () { sources(); }); });
      $$('[data-sa]', box).forEach(function (b) { b.addEventListener('click', function () { api('POST', '/api/kpi/auto/' + b.dataset.sa + '/accept').then(function () { sources(); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
      $$('[data-sr]', box).forEach(function (b) { b.addEventListener('click', function () { api('POST', '/api/kpi/auto/' + b.dataset.sr + '/reject').then(function () { sources(); }); }); });
    });
  }
  function sources() {
    var main = $('#main');
    Promise.all([api('GET', '/api/kpi/catalog?kind=kpi'), api('GET', '/api/kpi/feedlog')]).then(function (r) {
      var c = r[0], log = r[1].log, can = c.can;
      main.innerHTML = head('sources', can.create ? '<button class="btn" id="refresh">Refresh now</button><button class="btn p" id="addk" style="--c:#2F6FD6">+ Add indicator</button>' : '') +
        '<div class="alert info"><b>How automatic updates work.</b> Sentinel never reaches out to a website unless the administrator of this module approves its host name below. Once a day it asks each approved feed for new readings (it never overwrites a value a person entered) and recalculates the measures it can work out itself. Official bodies often publish data only as web pages or PDFs; for those, enter the value by hand or import it, and the report still shows its date and source.</div>' +
        '<div id="livebox" style="margin-bottom:12px"></div><div id="autobox"></div><div class="grid" style="margin-top:12px"><div class="card s5"><h3>Approved feed hosts</h3><textarea id="hosts" rows="4" placeholder="one host name per line, for example data.example.org"' + (can.approve ? '' : ' disabled') + '>' + esc((c.hosts || []).join('\n')) + '</textarea>' + (can.approve ? '<div style="margin-top:8px"><button class="btn p" id="savehosts" style="--c:#2F6FD6">Save approved hosts</button></div>' : '<div class="muted small">Only someone who can approve may change this list.</div>') + '</div>' +
        '<div class="card s7"><h3>Recent refreshes</h3>' + (log.length ? '<div style="max-height:180px;overflow:auto"><table class="t"><tr><th>When</th><th>Indicator</th><th>Result</th></tr>' + log.map(function (l) { return '<tr><td>' + SX.fmt(l.ts) + '</td><td>' + esc(l.code || '') + '</td><td>' + (l.ok ? '' : '<span class="red">failed: </span>') + esc(l.message) + '</td></tr>'; }).join('') + '</table></div>' : '<div class="empty">No feeds have run yet.</div>') + '</div>' +
        '<div class="card s12"><h3>Indicators and where they come from (' + c.items.length + ')</h3><div style="max-height:620px;overflow:auto"><table class="t"><tr><th>Code</th><th>Indicator</th><th>Group</th><th>Frequency</th><th>Source</th><th>Updated by</th><th>Last reading</th><th></th></tr>' + c.items.map(function (x) {
          return '<tr><td><b>' + esc(x.code) + '</b></td><td>' + esc(x.name) + '</td><td>' + esc(x.grp || '') + '</td><td>' + esc(x.freq) + '</td><td>' + esc(x.source || '') + (x.source_url ? ' <a href="' + esc(x.source_url) + '" target="_blank" rel="noopener noreferrer">link</a>' : '') + '</td><td>' + (x.feed_url ? '<span class="badge" style="background:#DDF1E3;color:#146C2E">Feed</span>' : x.internal_key ? '<span class="badge" style="background:#E6DDF8;color:#5B3FA8">Sentinel</span>' : 'People') + '</td><td>' + (x.last ? SX.fmt(x.last.period, true) + ' (' + x.readings + ' readings)' : 'none') + '</td><td style="text-align:right;white-space:nowrap">' + (can.edit ? '<button class="btn sm" data-ek="' + x.id + '">Edit</button>' : '') + (can['delete'] ? ' <button class="btn sm" data-dk="' + x.id + '" style="color:#C62828">Remove</button>' : '') + '</td></tr>'; }).join('') + '</table></div></div></div>';
      liveBox(); autoBox();
      var on = function (id, fn) { var e = $(id); if (e) e.addEventListener('click', fn); };
      on('#addk', function () { kpiForm(null, 'kpi', sources); });
      on('#refresh', function () { api('POST', '/api/kpi/refresh').then(function (x) { SX.toast('Updated ' + x.internal_updated + ' Sentinel measures; ' + x.feeds.length + ' feeds tried', 'ok'); sources(); }, function (e) { SX.toast(e.message, 'bad'); }); });
      on('#savehosts', function () { api('PUT', '/api/kpi/hosts', { hosts: $('#hosts').value.split(/\n/) }).then(function () { SX.toast('Approved hosts saved', 'ok'); sources(); }, function (e) { SX.toast(e.message, 'bad'); }); });
      $$('[data-ek]', main).forEach(function (b) { b.addEventListener('click', function () { kpiForm(c.items.filter(function (x) { return x.id === +b.dataset.ek; })[0], 'kpi', sources); }); });
      $$('[data-dk]', main).forEach(function (b) { b.addEventListener('click', function () { api('DELETE', '/api/kpi/catalog/' + b.dataset.dk).then(function () { SX.toast('Indicator removed (its history is kept)', 'ok'); sources(); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
    });
  }
})();
