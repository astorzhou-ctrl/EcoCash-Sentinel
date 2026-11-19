/* Quarterly KRI dashboard (Step 22): the KRIs from the Board of Trustees and Risk Committee reports, quarter by quarter, in the style of the Power BI pages.
   Everything is read from the stored figures, so importing a report or typing figures in updates the dashboard, the report and the downloads at once. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#E0474C';
  var ST = { green: ['#2FA84F', 'On target', '#fff'], amber: ['#F5A623', 'Near target', '#3A2600'], red: ['#E4202E', 'Off target', '#fff'], info: ['#C9D2DE', 'No target', '#33415C'] };
  SX.KRI_TABS = [['monitor', 'Live KRI monitor'], ['dashboard', 'Quarterly dashboard'], ['pbi', 'Power BI pages'], ['format', 'Report format'], ['report', 'Quarterly report'], ['data', 'Enter and import']];
  var UI = { from: null, to: null, view: 'grid', show: 'all', open: {} };
  function tabs(cur) { return SX.tabs('m/kri_monitor', SX.KRI_TABS, cur, COLOR); }
  function head(cur, extra) { return SX.head('Events &amp; Fraud &rsaquo; KRI Monitor', 'KRI Monitor', COLOR, extra || '') + tabs(cur); }
  function qlab(q) { return q ? q.replace(/^FY(\d\d)Q(\d)$/, 'Q$2 FY$1') : ''; }
  function dl(url, label, cls) { return '<a class="btn ' + (cls || '') + '" href="' + url + '"' + (cls === 'p' ? ' style="--c:#2F6FD6"' : '') + '>' + label + '</a>'; }
  function qs() { return (UI.from ? 'from=' + UI.from : '') + (UI.to ? (UI.from ? '&' : '') + 'to=' + UI.to : ''); }
  function chip(st) { var c = ST[st] || ST.info; return '<span class="badge" style="background:' + c[0] + ';color:' + c[2] + '">' + c[1] + '</span>'; }

  // traffic light at the end of each KRI: red = off target (pulses as a warning), amber = near target, green = on target, all dark = no target to judge against
  (function () {
    if (document.getElementById('kq-css')) return; var st = document.createElement('style'); st.id = 'kq-css';
    st.textContent = '.kq-tl{display:inline-flex;gap:4px;padding:4px 6px;background:#10192A;border-radius:12px;vertical-align:middle;box-shadow:inset 0 0 0 1px #0A101C,0 1px 2px rgba(0,0,0,.25)}.kq-tl i{width:13px;height:13px;border-radius:50%;background:#2B3547;display:block}' +
      '.kq-tl i.red.on{background:#FF2D2D;box-shadow:0 0 10px 3px rgba(255,45,45,.95);animation:kqr .7s steps(1,end) infinite}' +
      '.kq-tl i.amber.on{background:#FFB020;box-shadow:0 0 10px 3px rgba(255,176,32,.9);animation:kqa 1.2s steps(1,end) infinite}' +
      '.kq-tl i.green.on{background:#22E060;box-shadow:0 0 10px 3px rgba(34,224,96,.85);animation:kqg 2s ease-in-out infinite}' +
      '@keyframes kqr{0%{opacity:1}50%{opacity:.12;box-shadow:none}100%{opacity:1}}@keyframes kqa{0%{opacity:1}60%{opacity:.18;box-shadow:none}100%{opacity:1}}@keyframes kqg{0%,100%{opacity:1}50%{opacity:.45}}' +
      '.kq-lt{font-size:11px;font-weight:700;margin-left:6px;vertical-align:middle;white-space:nowrap}' +
      '.kq-band{background:#0B3A82;color:#fff;padding:12px 18px;display:flex;justify-content:space-between;align-items:center;gap:24px;border-radius:8px 8px 0 0}.kq-band h2{margin:0;font-size:21px;color:#fff;font-weight:700}.kq-band .s{font-size:12px;max-width:420px;opacity:.92;text-align:right}' +
      '.kq-wrap{background:#EEF3FB;padding:10px;border-radius:0 0 8px 8px;border:1px solid #D5DEEC;border-top:0}.kq-g3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.kq-g2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}' +
      '.kq-pan{background:#fff;border:1px solid #E1E6EE;border-radius:6px;padding:9px 11px;min-width:0}.kq-pan .t{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}.kq-pan .t b{font-size:12.5px;color:#0B3A82;line-height:1.25}' +
      '.kq-leg{display:flex;gap:10px;flex-wrap:wrap;font-size:10.5px;color:#33415C;margin-top:2px}.kq-leg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:3px}' +
      '.kq-pages{position:sticky;bottom:0;z-index:5;display:flex;gap:2px;overflow-x:auto;background:#F4F6FA;border:1px solid #D5DEEC;border-radius:8px;padding:4px;margin-top:12px}.kq-pages button{border:0;background:transparent;padding:7px 12px;font-size:12px;white-space:nowrap;cursor:pointer;border-radius:6px;color:#33415C}.kq-pages button.on{background:#0B3A82;color:#fff;font-weight:700}.kq-pages button:hover:not(.on){background:#E1E8F4}' +
      '.kq-tile{border-radius:6px;color:#fff;text-align:center;padding:10px 6px}.kq-tile b{display:block;font-size:30px;line-height:1.1}.kq-tile span{font-size:12px}' +
      '.kq-tbl{width:100%;border-collapse:collapse;font-size:12px}.kq-tbl th{background:#0B3A82;color:#fff;text-align:left;padding:6px 8px;font-weight:600;position:sticky;top:0}.kq-tbl td{padding:5px 8px;border-bottom:1px solid #EEF1F6;vertical-align:top}.kq-tbl tr:nth-child(even) td{background:#F8FAFD}' +
      '@media (max-width:1150px){.kq-g3{grid-template-columns:repeat(2,minmax(0,1fr))}}@media (max-width:720px){.kq-g3,.kq-g2{grid-template-columns:1fr}.kq-band{flex-direction:column;align-items:flex-start}.kq-band .s{text-align:left}}';
    document.head.appendChild(st);
  
})();
  var LAB = { red: 'Off target', amber: 'Near target', green: 'On target', info: 'No target' };
  function lamp(st, tip, label) {
    st = LAB[st] ? st : 'info';
    return '<span class="kq-tl' + (st === 'red' ? ' kq-warn' : '') + '" role="img" aria-label="' + LAB[st] + '" title="' + esc(tip || LAB[st]) + '">' + ['red', 'amber', 'green'].map(function (k) { return '<i class="' + k + (k === st ? ' on' : '') + '"></i>'; }).join('') + '</span>' +
      (label ? '<span class="kq-lt" style="color:' + (st === 'info' ? '#6B7A8C' : ST[st][0]) + '">' + LAB[st] + '</span>' : '');
  }
  function worst(c) { return c.red ? 'red' : c.amber ? 'amber' : c.green ? 'green' : 'info'; }

  // ------------------------------------------------------------------ small SVG charts
  function lineChart(cats, series, o) {
    o = o || {}; var w = o.w || 300, h = o.h || 120, L = 34, R = 8, T = 10, B = 22, all = [];
    series.forEach(function (s) { s.values.forEach(function (v) { if (v != null) all.push(v); }); });
    if (!all.length) return '<div class="muted small" style="padding:20px">No numbers to chart</div>';
    var mn = Math.min.apply(null, all), mx = Math.max.apply(null, all); if (mn === mx) { mn -= Math.abs(mn) * .1 || 1; mx += Math.abs(mx) * .1 || 1; }
    var pad = (mx - mn) * .12; mn -= pad; mx += pad; if (o.zero && mn > 0) mn = 0;
    var X = function (i) { return L + (cats.length < 2 ? (w - L - R) / 2 : i * (w - L - R) / (cats.length - 1)); }, Y = function (v) { return T + (1 - (v - mn) / (mx - mn)) * (h - T - B); };
    var out = '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" style="max-width:' + w + 'px;display:block">';
    [0, .5, 1].forEach(function (f) { var v = mn + (mx - mn) * f, y = Y(v); out += '<line x1="' + L + '" x2="' + (w - R) + '" y1="' + y + '" y2="' + y + '" stroke="#E6EBF3"/><text x="' + (L - 4) + '" y="' + (y + 3) + '" font-size="8.5" fill="#6B7A8C" text-anchor="end">' + (o.axis ? o.axis(v) : short(v)) + '</text>'; });
    cats.forEach(function (c, i) { out += '<text x="' + X(i) + '" y="' + (h - 7) + '" font-size="8.5" fill="#6B7A8C" text-anchor="middle">' + esc(c) + '</text>'; });
    series.forEach(function (s) {
      var pts = [], seg = '';
      s.values.forEach(function (v, i) { if (v != null) pts.push([X(i), Y(v), v, i]); });
      if (s.dashed) { if (pts.length) out += '<line x1="' + pts[0][0] + '" x2="' + pts[pts.length - 1][0] + '" y1="' + pts[0][1] + '" y2="' + pts[0][1] + '" stroke="' + s.color + '" stroke-width="1.6" stroke-dasharray="5 4"/>'; return; }
      out += '<polyline fill="none" stroke="' + s.color + '" stroke-width="2.2" points="' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + '"/>';
      pts.forEach(function (p) { var c = s.dots && s.dots[p[3]] || s.color; out += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="4" fill="' + c + '" stroke="#fff" stroke-width="1.2"><title>' + esc((s.labels && s.labels[p[3]]) || p[2]) + '</title></circle>'; });
    });
    return out + '</svg>';
  }
  function short(v) { var a = Math.abs(v); return a >= 1e9 ? (v / 1e9).toFixed(1) + 'bn' : a >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : a >= 1e4 ? (v / 1e3).toFixed(0) + 'K' : a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2); }
  function stacked(trend) {
    var w = 460, h = 190, L = 30, B = 26, T = 12, mx = Math.max.apply(null, trend.map(function (t) { return t.green + t.amber + t.red + t.info; }).concat([1])), bw = Math.min(70, (w - L) / trend.length - 24), o = '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" style="max-width:' + w + 'px">';
    [0, .5, 1].forEach(function (f) { var y = T + (1 - f) * (h - T - B); o += '<line x1="' + L + '" x2="' + (w - 6) + '" y1="' + y + '" y2="' + y + '" stroke="#E6EBF3"/><text x="' + (L - 4) + '" y="' + (y + 3) + '" font-size="9" fill="#6B7A8C" text-anchor="end">' + Math.round(mx * f) + '</text>'; });
    trend.forEach(function (t, i) {
      var cx = L + (i + .5) * (w - L - 6) / trend.length, y = h - B;
      [['green', t.green], ['amber', t.amber], ['red', t.red], ['info', t.info]].forEach(function (p) { var hh = p[1] / mx * (h - T - B); y -= hh; if (hh > 0) o += '<rect x="' + (cx - bw / 2) + '" y="' + y + '" width="' + bw + '" height="' + hh + '" fill="' + ST[p[0]][0] + '"><title>' + ST[p[0]][1] + ': ' + p[1] + '</title></rect>' + (hh > 13 ? '<text x="' + cx + '" y="' + (y + hh / 2 + 4) + '" font-size="10" font-weight="700" fill="' + ST[p[0]][2] + '" text-anchor="middle">' + p[1] + '</text>' : ''); });
      o += '<text x="' + cx + '" y="' + (h - 8) + '" font-size="10" fill="#33415C" text-anchor="middle" font-weight="600">' + qlab(t.q) + '</text>';
    });
    return o + '</svg>';
  }
  function share(c) { var n = c.green + c.amber + c.red || 1; return '<div style="display:flex;height:10px;border-radius:5px;overflow:hidden;background:#E6EBF3;min-width:90px">' + ['green', 'amber', 'red'].map(function (k) { return c[k] ? '<div title="' + ST[k][1] + ': ' + c[k] + '" style="width:' + (c[k] / n * 100) + '%;background:' + ST[k][0] + '"></div>' : ''; }).join('') + '</div>'; }
  function tile(label, value, sub, color) { return '<div class="card s2" style="border-top:3px solid ' + color + ';padding:12px 14px"><div class="muted small" style="text-transform:uppercase;letter-spacing:.04em">' + label + '</div><div style="font-size:28px;font-weight:700;color:' + color + '">' + value + '</div><div class="muted small">' + (sub || '&nbsp;') + '</div></div>'; }
  function series(r, qsl) {
    var vals = qsl.map(function (q) { return r.q[q] ? r.q[q].value : null; }), out = [{ name: 'Actual', color: '#2F6FD6', values: vals, labels: qsl.map(function (q) { return r.q[q] ? qlab(q) + ': ' + r.q[q].text + ' (' + ST[r.q[q].status][1] + ')' : ''; }), dots: qsl.map(function (q) { return r.q[q] ? ST[r.q[q].status][0] : '#2F6FD6'; }) }];
    var t = null; qsl.forEach(function (q) { if (r.q[q] && r.q[q].target) { t = parseTarget(r.q[q].target, r.q[q].raw, r.unit); } });
    if (t != null) out.push({ name: 'Target', color: '#E4202E', dashed: true, values: qsl.map(function () { return t; }) });
    return out;
  }
  function parseTarget(tr, raw, unit) {
    var s = String(tr || '').replace(/[<>≤≥=\s]/g, ''), m = s.match(/^(?:USD|US\$|\$|ZWG)?(-?[\d,.]+)(%|bn|Mn|mn|M|m|k|K)?$/i); if (!m) { var t = s.match(/^(\d+):(\d+)$/); return t ? +t[1] * 60 + +t[2] : null; }
    var v = parseFloat(m[1].replace(/,/g, '')), x = (m[2] || '').toLowerCase(); return x === 'k' ? v * 1e3 : (x === 'm' || x === 'mn') ? v * 1e6 : x === 'bn' ? v * 1e9 : v;
  }

  // ------------------------------------------------------------------ the dashboard
  SX.kriq = function (tab) {
    if (tab === 'report') return report();
    if (tab === 'data') return dataTab();
    if (tab === 'format') return SX.kriqFormat ? SX.kriqFormat() : dashboard();
    if (tab === 'pbi') return SX.kriqPbi ? SX.kriqPbi() : dashboard();
    return dashboard();
  };

  function dashboard() {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    api('GET', '/api/kriq/dashboard?' + qs()).then(function (d) {
      if (d.empty && d.seed_available) {
        if (d.can.edit) { main.innerHTML = head('dashboard', '') + '<div class="card" style="text-align:center;padding:34px"><h3>Loading the KRIs from the Board of Trustees and Risk Committee reports (Q4 FY26 to Q2 FY27)&hellip;</h3></div>'; return api('POST', '/api/kriq/seed', {}).then(dashboard); }
        main.innerHTML = head('dashboard', '') + '<div class="card" style="text-align:center;padding:34px"><h3>No quarterly KRI data yet</h3><p class="muted">Ask a person who can edit the KRI Monitor to open this page once, or import a report.</p></div>'; return;
      }
      if (!d.empty && d.pbi_pending && d.can.edit) { return api('POST', '/api/kriq/seed', {}).then(dashboard); }
      if (d.empty) { main.innerHTML = head('dashboard', '') + '<div class="card" style="text-align:center;padding:34px"><h3>No quarterly KRI data</h3><p class="muted">Import a Board of Trustees or Risk Committee report, or type the figures in.</p><a class="btn p" style="--c:#E0474C" href="#/m/kri_monitor/data">Enter and import</a></div>'; return; }
      var t = d.tiles, Q = d.quarters; UI.from = d.from; UI.to = d.to;
      var opts = function (sel) { return d.all_quarters.map(function (q) { return '<option value="' + q + '"' + (q === sel ? ' selected' : '') + '>' + qlab(q) + '</option>'; }).join(''); };
      var h = head('dashboard', '<label class="small muted">From</label><select id="qf" style="width:104px">' + opts(d.from) + '</select><label class="small muted">to</label><select id="qt" style="width:104px">' + opts(d.to) + '</select>' + (d.can.edit ? '<button class="btn" id="qe">Enter or edit a quarter</button>' : '') + dl('/api/kriq/export.pptx?' + qs(), 'Download PowerPoint', 'p') + dl('/api/kriq/export.xlsx?' + qs(), 'Download Power BI data'));
      h += '<div class="grid">' + tile('KRIs reported ' + qlab(d.to), t.reported, t.kris + ' tracked', '#2F6FD6') + tile('On target', t.pct_on_target == null ? 'n/a' : t.pct_on_target + '%', t.prev_pct_on_target == null ? '' : 'was ' + t.prev_pct_on_target + '% last quarter', '#2FA84F') +
        tile('Near target', t.amber, 'within 10% of target', '#F5A623') + tile('Off target', t.red, 'needs attention', '#E4202E') + tile('Improving', t.improving, 'since last quarter', '#0EA5A5') + tile('Worsening', t.worsening, 'since last quarter', '#C2410C');
      h += '<div class="card s5"><h3>KRI status by quarter</h3>' + stacked(d.trend) + '<div class="small" style="display:flex;gap:12px;flex-wrap:wrap;margin-top:4px">' + ['green', 'amber', 'red', 'info'].map(function (k) { return '<span><i style="display:inline-block;width:10px;height:10px;border-radius:2px;background:' + ST[k][0] + '"></i> ' + ST[k][1] + '</span>'; }).join('') + '</div></div>';
      var pc = d.trend.map(function (x) { var n = x.green + x.amber + x.red; return n ? Math.round(100 * x.green / n) : null; });
      h += '<div class="card s3"><h3>Share on target</h3>' + lineChart(Q.map(qlab), [{ color: '#2F6FD6', values: pc, labels: pc.map(function (v) { return v + '%'; }) }], { w: 250, h: 190, axis: function (v) { return Math.round(v) + '%'; } }) + '</div>';
      h += '<div class="card s4"><h3>Residual risk by quarter</h3>' + resTable(d) + '</div>';
      h += '<div class="card s12"><h3>Risk scorecard <span class="muted small">KRIs against target in ' + qlab(d.to) + '</span></h3><table class="t"><tr><th>Risk</th><th style="width:70px">Light</th><th style="width:180px">Status of its KRIs</th><th>On target</th><th>Near</th><th>Off</th>' + Q.map(function (q) { return '<th style="text-align:right">Residual ' + qlab(q) + '</th>'; }).join('') + '</tr>' +
        d.risks.map(function (r) { var c = r.counts; return '<tr><td><b>' + esc(r.name) + '</b>' + (r.category ? '<div class="small muted">' + esc(r.category) + '</div>' : '') + '</td><td>' + lamp(worst(c), c.red + ' off target, ' + c.amber + ' near, ' + c.green + ' on target') + '</td><td>' + share(c) + '</td><td>' + c.green + '</td><td>' + c.amber + '</td><td><b style="color:' + (c.red ? '#E4202E' : '#6B7A8C') + '">' + c.red + '</b></td>' + Q.map(function (q) { return '<td style="text-align:right">' + (r.residual[q] != null ? r.residual[q] : '–') + '</td>'; }).join('') + '</tr>'; }).join('') + '</table></div>';
      h += '<div class="card s12"><div class="toolbar" style="margin:0 0 6px"><h3 style="margin:0">KRIs by risk</h3><div style="flex:1"></div><select id="vw" style="width:150px"><option value="grid"' + (UI.view === 'grid' ? ' selected' : '') + '>Heat grid</option><option value="charts"' + (UI.view === 'charts' ? ' selected' : '') + '>Charts</option></select><select id="sh" style="width:170px"><option value="all">All KRIs</option><option value="red"' + (UI.show === 'red' ? ' selected' : '') + '>Off target only</option><option value="worse"' + (UI.show === 'worse' ? ' selected' : '') + '>Getting worse</option></select></div>' + (UI.view === 'charts' ? charts(d) : grid(d)) + '</div>';
      main.innerHTML = h + '</div>' + '<div class="small muted" style="margin:10px 0">Source: Board of Trustees and Risk Committee reports, and figures entered here. Status is judged against the target stated for each quarter: near target is within 10%. Click a KRI for its detail.</div>';
      var on = function (id, ev, fn) { var e = $(id); if (e) e.addEventListener(ev, fn); };
      on('#qf', 'change', function () { UI.from = this.value; dashboard(); }); on('#qt', 'change', function () { UI.to = this.value; dashboard(); });
      on('#qe', 'click', function () { manual(d); });
      $$('[data-edit]', main).forEach(function (e) { e.addEventListener('click', function (ev) { ev.stopPropagation(); editGrid([+e.dataset.edit], dashboard); }); });
      on('#vw', 'change', function () { UI.view = this.value; dashboard(); }); on('#sh', 'change', function () { UI.show = this.value; dashboard(); });
      $$('[data-k]', main).forEach(function (e) { e.addEventListener('click', function () { var id = +e.dataset.k, k = null; d.risks.forEach(function (r) { r.kris.forEach(function (x) { if (x.id === id) k = [r, x]; }); }); if (k) detail(k[0], k[1], d); }); });
      $$('[data-rk]', main).forEach(function (e) { e.addEventListener('click', function () { UI.open[e.dataset.rk] = !UI.open[e.dataset.rk]; dashboard(); }); });
    }, function (e) { main.innerHTML = head('dashboard', '') + '<div class="card">' + esc(e.message || 'Could not load') + '</div>'; });
  }
  function resTable(d) {
    var rows = d.risks.filter(function (r) { return d.quarters.some(function (q) { return r.residual[q] != null; }); });
    if (!rows.length) return '<div class="muted small">No residual ratings loaded.</div>';
    var cs = ['#9DB8E8', '#5B8DE0', '#1F5FBF', '#0B3A82'];
    return '<div style="display:grid;gap:5px">' + rows.map(function (r) { return '<div style="display:flex;align-items:center;gap:6px"><div class="small" style="width:108px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis" title="' + esc(r.name) + '">' + esc(r.name.replace(/ Risk$/, '')) + '</div><div style="flex:1;display:grid;gap:2px">' + d.quarters.map(function (q, i) { var v = r.residual[q]; return v == null ? '' : '<div title="' + qlab(q) + ': ' + v + '" style="height:7px;border-radius:3px;background:' + cs[i % 4] + ';width:' + (v / 25 * 100) + '%"></div>'; }).join('') + '</div></div>'; }).join('') + '</div><div class="small muted" style="margin-top:6px">Bars: ' + d.quarters.map(function (q, i) { return '<i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:' + cs[i % 4] + '"></i> ' + qlab(q); }).join(' &nbsp; ') + ' (scale 0 to 25)</div>';
  }
  function visible(r) { var c = r.current || r.latest; if (UI.show === 'red') return c && c.status === 'red'; if (UI.show === 'worse') return r.move === 'worse'; return true; }
  function grid(d) {
    var h = '';
    d.risks.forEach(function (rk) {
      var ks = rk.kris.filter(visible); if (!ks.length) return;
      var open = UI.open[rk.no] !== false;
      h += '<div style="margin:10px 0 4px;display:flex;align-items:center;gap:10px;cursor:pointer" data-rk="' + rk.no + '"><span style="font-size:11px">' + (open ? '▼' : '▶') + '</span><b>' + esc(rk.name) + '</b>' + lamp(worst(rk.counts), 'Worst status among this risk\'s KRIs') + '<span class="small muted">' + rk.counts.green + ' on target &middot; ' + rk.counts.amber + ' near &middot; ' + rk.counts.red + ' off</span>' + (d.can.edit ? '<button class="btn sm" data-edit="' + rk.no + '" style="margin-left:auto">Edit figures</button>' : '') + '</div>';
      if (!open) return;
      h += '<table class="t" style="margin-bottom:4px"><tr><th>KRI</th><th>Target</th>' + d.quarters.map(function (q) { return '<th style="text-align:center">' + qlab(q) + '</th>'; }).join('') + '<th>Trend</th><th style="width:130px">Status</th></tr>' + ks.map(function (r) {
        return '<tr style="cursor:pointer" data-k="' + r.id + '"><td>' + esc(r.name) + '</td><td class="muted">' + esc(r.target || '–') + '</td>' + d.quarters.map(function (q) { var x = r.q[q]; if (!x) return '<td style="text-align:center" class="muted">–</td>'; var c = ST[x.status]; return '<td style="text-align:center"><span style="display:inline-block;min-width:64px;padding:3px 7px;border-radius:6px;background:' + c[0] + ';color:' + c[2] + ';font-weight:600;font-size:12px" title="' + c[1] + (x.prev ? ' • earlier report said ' + esc(x.prev) : '') + '">' + esc(x.text) + (x.prev ? '*' : '') + '</span></td>'; }).join('') + '<td>' + trendMark(r) + '</td><td>' + (function () { var c = r.current || r.latest; return lamp(c ? c.status : 'info', c ? (LAB[c.status] + ': ' + c.text + ' against target ' + (r.target || 'none')) : '', true); })() + '</td></tr>';
      }).join('') + '</table>';
    });
    return (h || '<div class="muted" style="padding:14px">Nothing matches this filter.</div>') + '<div class="small muted">* the figure differs between versions of the report; the later one is shown.</div>';
  }
  function trendMark(r) { if (!r.move) return ''; var m = { better: ['▲ better', '#2FA84F'], worse: ['▼ worse', '#E4202E'], flat: ['▬ same', '#6B7A8C'], up: ['▲ up', '#6B7A8C'], down: ['▼ down', '#6B7A8C'] }[r.move]; return '<span style="color:' + m[1] + ';font-weight:600;font-size:12px">' + m[0] + (r.delta_pct != null && r.move !== 'flat' ? ' ' + Math.abs(r.delta_pct).toFixed(0) + '%' : '') + '</span>'; }
  function charts(d) {
    var h = '';
    d.risks.forEach(function (rk) {
      var ks = rk.kris.filter(visible).filter(function (r) { return d.quarters.some(function (q) { return r.q[q] && r.q[q].value != null; }); }); if (!ks.length) return;
      h += '<h3 style="margin:14px 0 6px">' + esc(rk.name) + '</h3><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:10px">' + ks.map(function (r) {
        var c = r.current || r.latest; return '<div class="card" data-k="' + r.id + '" style="box-shadow:none;border:1px solid #E1E6EE;cursor:pointer;padding:10px;border-top:3px solid ' + ST[c ? c.status : 'info'][0] + '"><div style="display:flex;justify-content:space-between;gap:8px"><b class="small">' + esc(r.name) + '</b>' + lamp(c ? c.status : 'info', c ? LAB[c.status] : '', true) + '</div><div class="small muted">Target ' + esc(r.target || 'none') + (c ? ' &middot; now <b style="color:#1A1A1A">' + esc(c.text) + '</b>' : '') + '</div>' + lineChart(d.quarters.map(qlab), series(r, d.quarters), { w: 290, h: 118 }) + '</div>';
      }).join('') + '</div>';
    });
    return h || '<div class="muted" style="padding:14px">Nothing matches this filter.</div>';
  }
  function detail(rk, r, d) {
    var rows = d.quarters.map(function (q) { var x = r.q[q]; return x ? '<tr><td>' + qlab(q) + '</td><td><b>' + esc(x.text) + '</b></td><td>' + esc(x.raw) + '</td><td>' + esc(x.target || '–') + '</td><td>' + chip(x.status) + '</td><td class="small">' + esc(x.source || '') + (x.prev ? '<div class="muted">replaced ' + esc(x.prev) + ' (' + esc(x.prev_source || '') + ')</div>' : '') + '</td></tr>' : ''; }).join('');
    var m = SX.modal({ title: r.name, wide: true, html: '<div class="muted small" style="margin-top:0">' + esc(rk.name) + ' &middot; target ' + esc(r.target || 'none') + (r.lower_better ? ' &middot; lower is better' : '') + ' &nbsp; ' + (function () { var c = r.current || r.latest; return lamp(c ? c.status : 'info', '', true); })() + '</div>' + lineChart(d.quarters.map(qlab), series(r, d.quarters), { w: 560, h: 190 }) + '<table class="t"><tr><th>Quarter</th><th>Value</th><th>As reported</th><th>Target</th><th>Status</th><th>Source</th></tr>' + rows + '</table>' + (d.can.edit ? '<div style="margin-top:8px"><button class="btn sm" id="eg">Edit the figures</button> <button class="btn sm" id="ek">Edit the target or name</button> <button class="btn sm" id="dk" style="color:#C62828">Remove this KRI</button></div>' : ''), buttons: [{ label: 'Close' }] });
    var g = m.$('#eg'); if (g) g.addEventListener('click', function () { m.close && m.close(); editGrid([rk.no], dashboard); });
    var e = m.$('#ek'); if (e) e.addEventListener('click', function () { m.close && m.close(); kriForm(r, d); });
    var x = m.$('#dk'); if (x) x.addEventListener('click', function () { api('DELETE', '/api/kriq/kris/' + r.id).then(function () { SX.toast('KRI removed (its history is kept)', 'ok'); m.close && m.close(); dashboard(); }, function (er) { SX.toast(er.message, 'bad'); }); });
  }
  function kriForm(r, d, cb) {
    var m = SX.modal({ title: r ? 'Edit ' + r.name : 'Add a KRI', sticky: true, html: '<form class="form2"><label class="f">KRI name *<input name="name" value="' + esc(r ? r.name : '') + '"></label><label class="f">Target (as on the slide, for example &gt;35%, &lt;5%, 0)<input name="target" value="' + esc(r ? r.target : '') + '"></label>' +
      (r ? '' : '<label class="f">Risk *<select name="risk_no">' + (d.risks || []).map(function (x) { return '<option value="' + x.no + '">' + esc(x.name) + '</option>'; }).join('') + '</select></label>') + '<label class="f"><span><input type="checkbox" name="lb"' + (r && r.lower_better ? ' checked' : '') + '> Lower is better (losses, incidents, costs)</span></label></form>',
      buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () { var f = m.$('form'), b = { name: f.name.value, target: f.target.value, lower_better: f.lb.checked }; if (!r) b.risk_no = f.risk_no.value; return api(r ? 'PUT' : 'POST', '/api/kriq/kris' + (r ? '/' + r.id : ''), b).then(function () { SX.toast('Saved', 'ok'); if (cb) cb(); else dashboard(); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] });
  }

  // ------------------------------------------------------------------ the interpreted report
  function report() {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    api('GET', '/api/kriq/dashboard?' + qs()).then(function (d) {
      var n = d.narrative;
      if (d.empty) { main.innerHTML = head('report', '') + '<div class="card" style="text-align:center;padding:30px">No quarterly KRI data yet. Open the Quarterly dashboard once to load the reports, or import one.</div>'; return; }
      var li = function (a) { return a.length ? '<ul class="list">' + a.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '<p class="muted small">None.</p>'; };
      var h = head('report', dl('/api/kriq/export.pptx?' + qs(), 'Download PowerPoint', 'p') + dl('/api/kriq/export.xlsx?' + qs(), 'Download Power BI data') + '<button class="btn" id="pr">Print</button>');
      h += '<div class="card" style="border-left:5px solid #2F6FD6"><div class="muted small" style="text-transform:uppercase">KRI report &middot; ' + qlab(d.from) + ' to ' + qlab(d.to) + '</div><h2 style="margin:4px 0 8px">' + esc(n.headline) + '</h2>' + li(n.points) + '<div class="small muted">' + esc(n.prepared || '') + '</div></div>';
      h += '<div class="grid"><div class="card s6"><h3>Watch list: off target for two quarters or more</h3>' + li(n.watch) + '</div><div class="card s6"><h3>Missing for ' + qlab(d.to) + '</h3>' + li(n.gaps) + '</div>' +
        '<div class="card s12"><h3>Figures that differ between versions of a report <span class="muted small">the later version is used; check which is right</span></h3>' + li(n.restated) + '</div></div>';
      h += '<h3 style="margin:16px 0 6px">By risk</h3>' + n.sections.map(function (s) { return '<div class="card" style="margin-bottom:8px"><b>' + esc(s.risk) + '</b>' + li(s.lines) + (s.management ? '<details><summary class="small" style="cursor:pointer">Management commentary in the report</summary><p class="small">' + esc(s.management) + '</p></details>' : '') + '</div>'; }).join('');
      main.innerHTML = h; var p = $('#pr'); if (p) p.addEventListener('click', function () { window.print(); });
    });
  }

  // ------------------------------------------------------------------ enter and import
  function dataTab() {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    Promise.all([api('GET', '/api/kriq/dashboard'), api('GET', '/api/kriq/imports'), api('GET', '/api/kriq/removed')]).then(function (r) {
      var d = r[0], im = r[1], can = d.can, rm = r[2].kris;
      var h = head('data', '');
      h += '<div class="grid"><div class="card s6"><h3>Import a report</h3><p class="muted small" style="margin-top:0">Choose the quarterly Board of Trustees or Risk Committee report (.pptx), or the Sentinel Excel template. Sentinel reads the KRI tables on the Detailed Risks slides, shows what will change, and only then loads it. The dashboards update at once.</p>' + (can.edit ? '<button class="btn p" id="imp" style="--c:#E0474C">Import a report</button> ' : '<span class="muted small">You can view this page; ask the Risk Office to import.</span> ') + dl('/api/kriq/template.xlsx', 'Download the Excel template') + '</div>' +
        '<div class="card s6"><h3>Type the figures in</h3><p class="muted small" style="margin-top:0">Choose the quarter and enter each KRI as it appears in the report (33%, 4.68m, USD193k, 08:46). Leave a row empty to skip it.</p>' + (can.edit ? '<button class="btn p" id="man" style="--c:#E0474C">Enter a quarter</button> ' : '') + (can.create ? '<button class="btn" id="addk">+ Add a KRI</button>' : '') + '</div>';
      h += '<div class="card s12" id="loaded"><h3>What has been loaded</h3><p class="muted small" style="margin-top:0">Every import or manual entry is a batch. Delete removes what it added and puts back any value it replaced; Restore brings it back.</p>' +
        (im.imports.length ? '<table class="t"><tr><th>When</th><th>By</th><th>Source</th><th>New</th><th>Changed</th><th>Still in the system</th><th></th></tr>' + im.imports.map(function (i) { return '<tr><td>' + SX.fmt(i.ts) + '</td><td>' + esc(i.by || '') + '</td><td>' + esc(i.filename || '') + '</td><td>' + i.new + '</td><td>' + i.replaced + '</td><td>' + i.now + '</td><td style="text-align:right">' + (can.edit ? '<button class="btn sm" style="color:#C62828" data-del="' + i.id + '">Delete</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '<p class="muted">Nothing loaded.</p>') +
        (im.deleted.length ? '<h3 style="margin-top:14px">Deleted <span class="muted small">can be restored</span></h3><table class="t">' + im.deleted.map(function (i) { return '<tr><td>' + esc(i.filename || '') + '</td><td>' + SX.fmt(i.deleted_at) + '</td><td style="text-align:right">' + (can.edit ? '<button class="btn sm p" style="--c:#2F6FD6" data-res="' + i.id + '">Restore</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '') + '</div></div>';
      h = h.replace(/<\/div><\/div>$/, '</div>') + '</div>';
      if (rm.length) h += '<div class="card" style="margin-top:12px"><h3>Removed KRIs <span class="muted small">their figures are kept; restore brings a KRI back</span></h3><table class="t">' + rm.map(function (k) { return '<tr><td>' + esc(k.name) + '</td><td class="muted">' + esc(k.risk || '') + '</td><td style="text-align:right">' + (can.edit ? '<button class="btn sm p" style="--c:#2F6FD6" data-rk2="' + k.id + '">Restore</button>' : '') + '</td></tr>'; }).join('') + '</table></div>';
      main.innerHTML = h;
      $$('[data-rk2]', main).forEach(function (b) { b.addEventListener('click', function () { api('POST', '/api/kriq/kris/' + b.dataset.rk2 + '/restore', {}).then(function () { SX.toast('KRI restored', 'ok'); dataTab(); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
      var on = function (id, fn) { var e = $(id); if (e) e.addEventListener('click', fn); };
      on('#imp', importDialog); on('#man', function () { manual(d); }); on('#addk', function () { api('GET', '/api/kriq/dashboard?from=FY00Q1').then(function (x) { kriForm(null, x); }); });
      $$('[data-del]', main).forEach(function (b) { b.addEventListener('click', function () { if (!confirm('Delete this import? Its figures leave the dashboard. You can restore it afterwards.')) return; api('DELETE', '/api/kriq/imports/' + b.dataset.del).then(function (x) { SX.toast('Deleted: ' + x.removed + ' figures removed, ' + x.restored + ' earlier values put back', 'ok'); dataTab(); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
      $$('[data-res]', main).forEach(function (b) { b.addEventListener('click', function () { api('POST', '/api/kriq/imports/' + b.dataset.res + '/restore', {}).then(function (x) { SX.toast('Restored ' + x.restored + ' figures', 'ok'); dataTab(); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
    });
  }
  function importDialog() {
    var qopts = '<option value="">Detect from the report</option>' + (function () { var o = '', y = 26; for (; y <= 28; y++) for (var q = 1; q <= 4; q++) o += '<option value="FY' + y + 'Q' + q + '">Q' + q + ' FY' + y + '</option>'; return o; })();
    var m = SX.modal({ title: 'Import a quarterly report', wide: true, sticky: true, html: '<p class="muted small" style="margin-top:0">PowerPoint (.pptx) from the Board of Trustees or Risk Committee, or the Sentinel Excel template (.xlsx).</p><label class="f">File<input type="file" id="kf" accept=".pptx,.xlsx"></label><label class="f">Quarter the report is for<select id="kq">' + qopts + '</select></label><div id="kpv"></div>',
      buttons: [{ label: 'Cancel' }, { label: 'Check the file', onClick: function () { return send(1); } }, { label: 'Import', cls: 'p', onClick: function () { return send(0); } }] });
    function send(dry) {
      var f = m.$('#kf').files[0]; if (!f) { SX.toast('Choose the file first', 'bad'); return false; }
      return f.arrayBuffer().then(function (buf) { return fetch('/api/kriq/import?dry=' + dry + '&quarter=' + encodeURIComponent(m.$('#kq').value), { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Sentinel': '1', 'X-Filename': encodeURIComponent(f.name) }, credentials: 'same-origin', body: buf }); })
        .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.message || 'Import failed'); return d; }); })
        .then(function (d) {
          if (dry) { m.$('#kpv').innerHTML = '<div class="alert info"><b>' + d.kris + ' KRIs</b> across ' + d.risks + ' risks' + (d.deck ? ' (report for <b>' + qlab(d.deck) + '</b>)' : '') + ', quarters ' + d.quarters.map(qlab).join(', ') + '.<br><b>' + d.new + '</b> new figures, <b>' + d.changed + '</b> would change, ' + d.same + ' already the same' + (d.new_kris ? ', ' + d.new_kris + ' new KRIs' : '') + '.' + (d.changes.length ? '<ul class="list small">' + d.changes.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul>' : '') + (d.warnings.length ? '<div class="small">' + d.warnings.map(esc).join('<br>') + '</div>' : '') + '</div>'; return false; }
          SX.toast('Imported: ' + d.new + ' new, ' + d.changed + ' changed', 'ok'); m.close && m.close(); setTimeout(function () { location.hash = '#/m/kri_monitor/dashboard'; dashboard(); }, 50);
        }, function (e) { SX.toast(e.message, 'bad'); return false; });
    }
  }
  function manual(d0) {
    api('GET', '/api/kriq/entry').then(function (e) {
      var nxt = e.fq, qopts = function (sel) { var o = '', y; for (y = 26; y <= 29; y++) for (var q = 1; q <= 4; q++) { var v = 'FY' + y + 'Q' + q; o += '<option value="' + v + '"' + (v === sel ? ' selected' : '') + '>Q' + q + ' FY' + y + '</option>'; } return o; };
      var body = function (e2) {
        var last = '', h = '<table class="t"><tr><th>KRI</th><th>Target</th><th>Last</th><th style="width:150px">' + qlab(e2.fq) + '</th></tr>';
        e2.kris.forEach(function (k) { if (k.risk !== last) { last = k.risk; var rs = e2.risks.filter(function (r) { return r.name === k.risk; })[0]; h += '<tr><td colspan="3" style="background:#EEF3FB"><b>' + esc(k.risk) + '</b></td><td style="background:#EEF3FB">' + (rs ? '<input type="number" step="0.5" data-rr="' + rs.no + '" placeholder="residual" value="' + (rs.residual == null ? '' : rs.residual) + '" style="width:90px">' : '') + '</td></tr>'; }
          h += '<tr><td>' + esc(k.name) + '</td><td class="muted">' + esc(k.target) + '</td><td class="muted">' + esc(k.last || '') + '</td><td><input type="text" data-kv="' + k.id + '" value="' + esc(k.current) + '" style="width:130px"></td></tr>'; });
        return h + '</table>';
      };
      var m = SX.modal({ title: 'Enter quarterly KRI figures', wide: true, sticky: true, html: '<label class="f" style="max-width:240px">Quarter<select id="mq">' + qopts(nxt) + '</select></label><div id="mt" style="max-height:60vh;overflow:auto">' + body(e) + '</div>',
        buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () {
          var vals = [], res = []; $$('[data-kv]', m.el).forEach(function (i) { if (i.value.trim()) vals.push({ kri_id: +i.dataset.kv, raw: i.value.trim() }); }); $$('[data-rr]', m.el).forEach(function (i) { if (i.value !== '') res.push({ risk_no: +i.dataset.rr, residual: +i.value }); });
          return api('POST', '/api/kriq/values', { fq: m.$('#mq').value, values: vals, residual: res }).then(function (r) { SX.toast('Saved: ' + r.new + ' new, ' + r.changed + ' changed', 'ok'); setTimeout(function () { location.hash = '#/m/kri_monitor/dashboard'; dashboard(); }, 50); }, function (er) { SX.toast(er.message, 'bad'); return false; });
        } }] });
      m.$('#mq').addEventListener('change', function () { api('GET', '/api/kriq/entry?fq=' + this.value).then(function (e2) { m.$('#mt').innerHTML = body(e2); }); });
    });
  }
  // ------------------------------------------------------------------ edit figures: any quarter of any KRI of a risk, add the next quarter, remove a KRI
  function nextQ(q) { var m = /^FY(\d\d)Q(\d)$/.exec(q || ''); if (!m) return 'FY27Q3'; var y = +m[1], n = +m[2] + 1; if (n > 4) { n = 1; y++; } return 'FY' + y + 'Q' + n; }
  function editGrid(riskNos, after) {
    Promise.all([api('GET', '/api/kriq/dashboard?from=FY00Q1'), api('GET', '/api/kriq/entry')]).then(function (r) {
      var d = r[0], en = r[1], qs = d.all_quarters.slice(), rows = {}, kn = {};
      d.risks.forEach(function (rk) { rk.kris.forEach(function (k) { rows[k.id] = k; }); });
      var last = qs[qs.length - 1] || 'FY27Q2', nq = nextQ(last), cols = qs.filter(function (q) { return q >= 'FY26Q4'; }).concat([nq]);
      var resid = {}; d.risks.forEach(function (rk) { resid[rk.no] = rk.residual; });
      function table() {
        var h = '';
        riskNos.forEach(function (no) {
          var rname = (en.risks.filter(function (x) { return x.no === no; })[0] || {}).name || ('Risk ' + no), ks = en.kris.filter(function (k) { return k.risk_no === no; });
          h += '<h3 style="margin:12px 0 4px">' + esc(rname) + '</h3><table class="t kq-ed"><tr><th>KRI</th><th>Target</th>' + cols.map(function (q) { return '<th style="text-align:center">' + qlab(q) + (q === nq ? ' <span class="muted small">(new)</span>' : '') + '</th>'; }).join('') + '<th></th></tr>';
          h += '<tr style="background:#EEF3FB"><td colspan="2"><b>Residual rating</b> <span class="muted small">0 to 25</span></td>' + cols.map(function (q) { var v = (resid[no] || {})[q]; return '<td><input type="text" inputmode="decimal" data-r="' + no + '" data-q="' + q + '" data-o="' + (v == null ? '' : v) + '" value="' + (v == null ? '' : v) + '" style="width:84px;text-align:center"></td>'; }).join('') + '<td></td></tr>';
          ks.forEach(function (k) {
            var row = rows[k.id];
            h += '<tr data-krow="' + k.id + '"><td>' + esc(k.name) + '</td><td class="muted">' + esc(k.target || '–') + '</td>' + cols.map(function (q) { var x = row && row.q[q], v = x ? x.raw : ''; return '<td><input type="text" data-k="' + k.id + '" data-q="' + q + '" data-o="' + esc(v) + '" value="' + esc(v) + '" style="width:84px;text-align:center"></td>'; }).join('') + '<td style="text-align:right;white-space:nowrap"><button type="button" class="btn sm" data-rm="' + k.id + '" style="color:#C62828">Remove</button></td></tr>';
          });
          h += '</table><div style="margin:4px 0"><button type="button" class="btn sm" data-add="' + no + '">+ Add a KRI to this risk</button></div>';
        });
        return h;
      }
      var m = SX.modal({ title: 'Edit figures', wide: true, sticky: true, html: '<p class="muted small" style="margin-top:0">Type a figure as it appears in the report (33%, 4.68Mn, USD193k, 08:46). Change a figure to correct it, fill the last column to add the next quarter, or empty a box to remove that figure. Every save is a batch that can be deleted and restored in Enter and import.</p><div id="egt" style="max-height:62vh;overflow:auto">' + table() + '</div>',
        buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () {
          var cells = [], res = [], clr = 0;
          $$('input[data-k]', m.el).forEach(function (i) { if (i.value.trim() !== i.dataset.o) { cells.push({ kri_id: +i.dataset.k, fq: i.dataset.q, raw: i.value.trim() }); if (!i.value.trim()) clr++; } });
          $$('input[data-r]', m.el).forEach(function (i) { if (i.value.trim() !== i.dataset.o) { res.push({ risk_no: +i.dataset.r, fq: i.dataset.q, residual: i.value.trim() === '' ? null : i.value.trim() }); if (!i.value.trim()) clr++; } });
          if (!cells.length && !res.length) { SX.toast('Nothing was changed', 'ok'); return; }
          if (clr && !confirm(clr + ' figure(s) will be removed. Continue?')) return false;
          return api('POST', '/api/kriq/grid', { cells: cells, residual: res }).then(function (x) { SX.toast('Saved: ' + x.new + ' new, ' + x.changed + ' changed, ' + x.cleared + ' removed', 'ok'); setTimeout(function () { (after || dashboard)(); }, 50); }, function (e) { SX.toast(e.message, 'bad'); return false; });
        } }] });
      m.el.addEventListener('click', function (ev) {
        var b = ev.target.closest && ev.target.closest('[data-rm]'), a = ev.target.closest && ev.target.closest('[data-add]');
        if (b) { if (!confirm('Remove this KRI from the dashboards? Its figures are kept and you can restore it in Enter and import.')) return; api('DELETE', '/api/kriq/kris/' + b.dataset.rm).then(function () { var tr = b.closest('tr'); tr.parentNode.removeChild(tr); SX.toast('KRI removed', 'ok'); }, function (e) { SX.toast(e.message, 'bad'); }); }
        if (a) { var no = +a.dataset.add; kriForm(null, { risks: en.risks.filter(function (x) { return x.no === no; }) }, function () { m.close && m.close(); editGrid(riskNos, after); }); }
      });
    }, function (e) { SX.toast(e.message, 'bad'); });
  }
  SX.KQ = { ST: ST, LAB: LAB, lamp: lamp, worst: worst, qlab: qlab, qs: qs, UI: UI, dl: dl, head: head, editGrid: editGrid, short: short, manual: manual, importDialog: importDialog };
})();
