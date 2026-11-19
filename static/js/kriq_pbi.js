/* Power BI-style KRI pages (Step 23): the pages of the EcoCash Power BI risk report that are fed by KRI figures, drawn from the stored quarterly figures.
   Importing a report or editing a figure changes every page at once. Each page can be edited, and the whole set downloads as PowerPoint or a Power BI data pack. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, K = SX.KQ;
  var PAL = ['#0B3A82', '#2F8FE8', '#C8102E', '#F5A623', '#6B4FBB', '#0EA5A5'], BAND = { green: '#2FA84F', yellow: '#F2C200', orange: '#F28A1E', red: '#D7263D' };
  var P = { page: 'exec', period: null, reg: '', cat: '', dir: '', app: '', cats: {}, rks: {} };
  var FIRST = [['exec', 'Executive Overview'], ['move', 'Residual Risk Rating Movement'], ['univ', 'Indicator Universe']];

  function nice(mx) { if (mx <= 0) return 1; var e = Math.pow(10, Math.floor(Math.log(mx) / Math.LN10)), f = mx / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * e; }
  function top(mx) { var raw = Math.max(mx, 1e-9) * 1.08 / 4, e = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), f = raw / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e * 4; }
  function fn(v) { if (v == null) return ''; var a = Math.abs(v); return a >= 1e6 ? +(v / 1e6).toFixed(1) + 'M' : a >= 1e4 ? +(v / 1e3).toFixed(1) + 'K' : a >= 100 ? String(Math.round(v)) : String(+v.toFixed(2)); }
  function legend(ser) { if (ser.filter(function (s) { return !s.dashed; }).length < 2) return ''; return '<div class="kq-leg">' + ser.filter(function (s) { return !s.dashed; }).map(function (s, i) { return '<span><i style="background:' + PAL[i % PAL.length] + '"></i>' + esc(s.name) + '</span>'; }).join('') + '</div>'; }

  // ---------------------------------------------------------------- panel charts
  function frame(w, h, L, T, B, lo, hi, ticks, cats, X) {
    var o = '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" role="img" style="display:block">';
    for (var i = 0; i <= ticks; i++) { var v = lo + (hi - lo) * i / ticks, y = T + (1 - i / ticks) * (h - T - B); o += '<line x1="' + L + '" x2="' + (w - 6) + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '" stroke="#E6EBF3"/><text x="' + (L - 4) + '" y="' + (y + 3).toFixed(1) + '" font-size="8.5" fill="#6B7A8C" text-anchor="end">' + fn(v) + '</text>'; }
    cats.forEach(function (c, i) { o += '<text x="' + X(i).toFixed(1) + '" y="' + (h - 6) + '" font-size="8.5" fill="#33415C" text-anchor="middle">' + esc(c.replace(' ', '')) + '</text>'; });
    return o;
  }
  function bars(p, stack) {
    p = Object.assign({}, p, { series: p.series.filter(function (s) { return !s.dashed; }) });
    var w = p.wide ? 760 : 360, h = p.wide ? 250 : 190, L = 36, T = 14, B = 22, n = p.cats.length, m = p.series.length, all = [];
    p.series.forEach(function (s) { s.values.forEach(function (v) { if (v != null) all.push(v); }); });
    var mx = stack ? Math.max.apply(null, p.cats.map(function (c, i) { return p.series.reduce(function (a, s) { return a + (s.values[i] || 0); }, 0); }).concat([1])) : Math.max.apply(null, all.concat([p.target || 0, 1])), hi = top(mx), lo = 0;
    var gw = (w - L - 6) / n, X = function (i) { return L + gw * (i + .5); }, Y = function (v) { return T + (1 - (v - lo) / (hi - lo)) * (h - T - B); }, o = frame(w, h, L, T, B, lo, hi, 4, p.cats, X);
    p.cats.forEach(function (c, i) {
      var bw = stack ? Math.min(46, gw * .6) : Math.min(30, gw * .78 / m), x0 = X(i) - (stack ? bw / 2 : bw * m / 2), base = 0;
      p.series.forEach(function (s, k) {
        var v = s.values[i]; if (v == null) return;
        var col = stack ? ({ green: '#2FA84F', amber: '#F5C400', red: '#D7263D' }[s.key] || PAL[k % PAL.length]) : (p.kind === 'resid' ? BAND[bandOf(v)] : PAL[k % PAL.length]), x = stack ? x0 : x0 + k * bw;
        if (stack) { var y1 = Y(base + v), y0 = Y(base); if (v > 0) o += '<rect x="' + x.toFixed(1) + '" y="' + y1.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + (y0 - y1).toFixed(1) + '" fill="' + col + '"><title>' + esc(s.name + ': ' + v) + '</title></rect>' + (y0 - y1 > 11 ? '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + ((y0 + y1) / 2 + 3.5).toFixed(1) + '" font-size="9.5" font-weight="700" fill="' + (s.key === 'amber' ? '#3A2600' : '#fff') + '" text-anchor="middle">' + v + '</text>' : ''); base += v; return; }
        var y = Y(v); o += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + (bw - 1).toFixed(1) + '" height="' + Math.max(0, Y(0) - y).toFixed(1) + '" fill="' + col + '"><title>' + esc(s.name + ' ' + p.cats[i] + ': ' + (s.text && s.text[i] || fn(v))) + '</title></rect><text x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 2.5).toFixed(1) + '" font-size="8" fill="#33415C" text-anchor="middle">' + fn(v) + '</text>';
      });
    });
    if (p.target != null && p.kind === 'resid') { var ty = Y(p.target); o += '<line x1="' + L + '" x2="' + (w - 6) + '" y1="' + ty.toFixed(1) + '" y2="' + ty.toFixed(1) + '" stroke="#D7263D" stroke-width="1.5" stroke-dasharray="5 4"/><text x="' + (w - 8) + '" y="' + (ty - 3).toFixed(1) + '" font-size="8" fill="#D7263D" text-anchor="end">appetite ' + p.target + '</text>'; }
    return o + '</svg>';
  }
  function bandOf(v) { return v <= 10 ? 'green' : v <= 15 ? 'yellow' : v < 20 ? 'orange' : 'red'; }
  function lines(p) {
    var w = p.wide ? 760 : 360, h = p.wide ? 250 : 190, L = 36, T = 14, B = 22, n = p.cats.length, all = [];
    p.series.forEach(function (s) { s.values.forEach(function (v) { if (v != null) all.push(v); }); });
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all); if (p.target != null) { lo = Math.min(lo, p.target); hi = Math.max(hi, p.target); }
    if (lo === hi) { lo -= Math.abs(lo) * .1 || 1; hi += Math.abs(hi) * .1 || 1; } var pad = (hi - lo) * .15; lo -= pad; hi += pad; if (lo < 0 && Math.min.apply(null, all) >= 0) lo = 0;
    var X = function (i) { return L + (n < 2 ? (w - L - 6) / 2 : i * (w - L - 6) / (n - 1)) + (n < 2 ? 0 : 0); }, Y = function (v) { return T + (1 - (v - lo) / (hi - lo)) * (h - T - B); }, o = frame(w, h, L + 6, T, B, lo, hi, 3, p.cats, function (i) { return X(i); }), multi = p.series.filter(function (s) { return !s.dashed; }).length > 1;
    p.series.forEach(function (s, k) {
      var col = PAL[k % PAL.length], run = [];
      if (s.dashed) { var t = s.values.filter(function (v) { return v != null; })[0]; if (t != null) o += '<line x1="' + L + '" x2="' + (w - 6) + '" y1="' + Y(t).toFixed(1) + '" y2="' + Y(t).toFixed(1) + '" stroke="#D7263D" stroke-width="1.6" stroke-dasharray="5 4"><title>Target ' + fn(t) + '</title></line>'; return; }
      var flush = function () { if (run.length > 1) o += '<polyline fill="none" stroke="' + col + '" stroke-width="2.2" points="' + run.map(function (r) { return r[0].toFixed(1) + ',' + r[1].toFixed(1); }).join(' ') + '"/>'; run = []; };
      s.values.forEach(function (v, i) { if (v == null) { flush(); return; } run.push([X(i), Y(v)]); }); flush();
      s.values.forEach(function (v, i) {
        if (v == null) return; var st = !multi && s.status && s.status[i], c = st && st !== 'info' ? { green: '#2FA84F', amber: '#F5A623', red: '#E4202E' }[st] : col;
        o += '<circle cx="' + X(i).toFixed(1) + '" cy="' + Y(v).toFixed(1) + '" r="4.2" fill="' + c + '" stroke="#fff" stroke-width="1.3"><title>' + esc(s.name + ' ' + p.cats[i] + ': ' + (s.text && s.text[i] || fn(v)) + (st ? ' (' + K.LAB[st] + ')' : '')) + '</title></circle><text x="' + X(i).toFixed(1) + '" y="' + (Y(v) - 7).toFixed(1) + '" font-size="8.5" fill="#33415C" text-anchor="middle">' + fn(v) + '</text>';
      });
    });
    return o + '</svg>';
  }

  function hbars(p) {
    var ser = p.series.filter(function (s) { return !s.dashed; }), n = p.cats.length, m = ser.length, w = p.wide ? 760 : 360, rowH = Math.max(14, Math.min(34, (m * 11) + 8)), h = Math.max(120, 22 + n * rowH), L = 96, all = [];
    ser.forEach(function (s) { s.values.forEach(function (v) { if (v != null) all.push(v); }); });
    var hi = top(Math.max.apply(null, all.concat([1]))), X = function (v) { return L + (v / hi) * (w - L - 36); }, o = '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" role="img" style="display:block">';
    for (var i = 0; i <= 4; i++) { var x = L + (w - L - 36) * i / 4; o += '<line x1="' + x.toFixed(1) + '" x2="' + x.toFixed(1) + '" y1="6" y2="' + (h - 14) + '" stroke="#E6EBF3"/><text x="' + x.toFixed(1) + '" y="' + (h - 3) + '" font-size="8.5" fill="#6B7A8C" text-anchor="middle">' + fn(hi * i / 4) + '</text>'; }
    p.cats.forEach(function (c, i) {
      var y0 = 8 + i * rowH, bh = Math.max(4, (rowH - 4) / m);
      o += '<text x="' + (L - 5) + '" y="' + (y0 + rowH / 2 + 1) + '" font-size="8.5" fill="#33415C" text-anchor="end">' + esc(String(c).slice(0, 18)) + '</text>';
      ser.forEach(function (s, k) { var v = s.values[i]; if (v == null) return; var col = p.kind === 'resid' ? BAND[bandOf(v)] : ({ green: '#2FA84F', amber: '#F5C400', red: '#D7263D' }[s.key] || PAL[k % PAL.length]); o += '<rect x="' + L + '" y="' + (y0 + k * bh).toFixed(1) + '" width="' + Math.max(0, X(v) - L).toFixed(1) + '" height="' + (bh - 1).toFixed(1) + '" fill="' + col + '"><title>' + esc(s.name + ' ' + c + ': ' + (s.text && s.text[i] || fn(v))) + '</title></rect><text x="' + (X(v) + 3).toFixed(1) + '" y="' + (y0 + k * bh + bh / 2 + 3).toFixed(1) + '" font-size="8" fill="#33415C">' + fn(v) + '</text>'; });
    });
    return o + '</svg>';
  }
  function area(p) {
    var ser = p.series.filter(function (s) { return !s.dashed; }), w = p.wide ? 760 : 360, h = p.wide ? 250 : 190, L = 36, T = 14, B = 22, n = p.cats.length, all = [];
    ser.forEach(function (s) { s.values.forEach(function (v) { if (v != null) all.push(v); }); });
    var hi = top(Math.max.apply(null, all.concat([1]))), X = function (i) { return L + 6 + (n < 2 ? (w - L - 12) / 2 : i * (w - L - 12) / (n - 1)); }, Y = function (v) { return T + (1 - v / hi) * (h - T - B); }, o = frame(w, h, L + 6, T, B, 0, hi, 4, p.cats, X);
    ser.forEach(function (s, k) {
      var col = PAL[k % PAL.length], pts = s.values.map(function (v, i) { return v == null ? null : [X(i), Y(v)]; }).filter(Boolean); if (!pts.length) return;
      o += '<polygon fill="' + col + '" fill-opacity=".22" stroke="none" points="' + pts.map(function (a) { return a[0].toFixed(1) + ',' + a[1].toFixed(1); }).concat([pts[pts.length - 1][0].toFixed(1) + ',' + Y(0).toFixed(1), pts[0][0].toFixed(1) + ',' + Y(0).toFixed(1)]).join(' ') + '"/><polyline fill="none" stroke="' + col + '" stroke-width="2.2" points="' + pts.map(function (a) { return a[0].toFixed(1) + ',' + a[1].toFixed(1); }).join(' ') + '"/>';
      s.values.forEach(function (v, i) { if (v != null) o += '<circle cx="' + X(i).toFixed(1) + '" cy="' + Y(v).toFixed(1) + '" r="3.4" fill="' + col + '" stroke="#fff"><title>' + esc(s.name + ' ' + p.cats[i] + ': ' + (s.text && s.text[i] || fn(v))) + '</title></circle><text x="' + X(i).toFixed(1) + '" y="' + (Y(v) - 6).toFixed(1) + '" font-size="8.5" fill="#33415C" text-anchor="middle">' + fn(v) + '</text>'; });
    });
    return o + '</svg>';
  }
  function dtable(p) {
    var ser = p.series;
    return '<div style="overflow:auto;max-height:230px"><table class="kq-tbl" style="width:100%"><tr><th></th>' + p.cats.map(function (c) { return '<th style="text-align:right">' + esc(c) + '</th>'; }).join('') + '</tr>' + ser.map(function (s) { return '<tr><td>' + esc(s.name) + (s.dashed ? ' (target)' : '') + '</td>' + s.values.map(function (v, i) { return '<td style="text-align:right">' + (v == null ? '&ndash;' : esc(s.text && s.text[i] || fn(v))) + '</td>'; }).join('') + '</tr>'; }).join('') + '</table></div>';
  }
  function chart(p) {
    var t = p.type || (p.kind === 'line' || p.kind === 'lines' ? 'line' : p.kind === 'status' ? 'stacked' : 'bars');
    return t === 'line' ? lines(p) : t === 'hbars' ? hbars(p) : t === 'area' ? area(p) : t === 'table' ? dtable(p) : bars(p, t === 'stacked');
  }
  var TYPES = [['line', 'Line'], ['bars', 'Clustered columns'], ['hbars', 'Horizontal bars'], ['stacked', 'Stacked columns'], ['area', 'Area'], ['table', 'Data table']];
  function typeName(t) { return (TYPES.filter(function (x) { return x[0] === t; })[0] || [0, t])[1]; }
  function editor(pgId, p, done) {
    var base = { line: 'line', lines: 'line', bars: 'bars', resid: 'bars', status: 'stacked' }[p.kind] || 'bars';
    var html = '<label class="f">Heading<input id="ce-t" maxlength="140" value="' + esc(p.title) + '"></label><label class="f">Sub-heading<input id="ce-s" maxlength="240" value="' + esc(p.sub || '') + '"></label>' +
      '<label class="f">Chart type<select id="ce-y">' + TYPES.map(function (t) { return '<option value="' + t[0] + '"' + (t[0] === p.type ? ' selected' : '') + '>' + t[1] + (t[0] === p.best.type ? ' (best for this data)' : '') + '</option>'; }).join('') + '</select></label>' +
      '<div class="small" style="margin:8px 0;padding:8px;background:#EEF5FF;border-radius:6px">Best for this data: <b>' + esc(typeName(p.best.type)) + '</b>. ' + esc(p.best.why) + '. <button type="button" class="btn sm" id="ce-b">Use it</button></div>' +
      '<div class="small muted">Applies to this chart on screen and in the PowerPoint. The figures are not changed.</div>';
    var m = SX.modal({ title: 'Edit chart', html: html, sticky: true, buttons: [
      { label: 'Reset to original', onClick: function () { return api('DELETE', '/api/kriq/charts?page=' + pgId + '&idx=' + p.idx).then(function () { SX.toast('Chart reset', 'ok'); done(); }); } },
      { label: 'Cancel' },
      { label: 'Apply', cls: 'p', onClick: function (mm) { var y = mm.$('#ce-y').value; return api('PUT', '/api/kriq/charts', { page: pgId, idx: p.idx, title: mm.$('#ce-t').value, sub: mm.$('#ce-s').value, type: y === base ? '' : y }).then(function () { SX.toast('Chart updated', 'ok'); done(); }, function (e) { SX.toast(e.message || 'Could not save', 'bad'); return false; }); } }] });
    m.$('#ce-b').onclick = function () { m.$('#ce-y').value = p.best.type; };
  }
  function panel(p, can, pgId) {
    var body = p.empty ? '<div class="muted small" style="padding:30px 6px;text-align:center">' + esc(p.sub) + '</div>' : chart(p) + (p.type === 'table' ? '' : legend(p.series));
    return '<div class="kq-pan"><div class="t"><b>' + esc(p.title) + '</b>' + (can && !p.empty && p.idx != null ? '<button class="btn" data-ce="' + p.idx + '" title="Change chart type or heading" style="float:right;padding:1px 7px;font-size:11px">' + (p.custom ? 'Edited' : 'Edit') + '</button>' : '') + (p.lamp && !p.empty && p.kind !== 'status' ? K.lamp(p.lamp, p.now ? 'Now ' + p.now : '') : '') + '</div>' + (p.empty ? '' : '<div class="muted" style="font-size:10.5px;margin:1px 0 3px">' + esc(p.sub) + '</div>') + body + '</div>';
  }

  // ---------------------------------------------------------------- gauge
  function gauge(frac, label, marker, color, sub) {
    frac = Math.max(0, Math.min(1, frac)); var cx = 110, cy = 100, r = 78, pt = function (f, rr) { return [cx - (rr || r) * Math.cos(f * Math.PI), cy - (rr || r) * Math.sin(f * Math.PI)]; }, a = pt(0), b = pt(frac), z = pt(1), mk = pt(marker, r + 10), mk2 = pt(marker, r - 22);
    return '<svg viewBox="0 0 220 130" width="100%" style="max-width:260px;display:block;margin:0 auto"><path d="M' + a[0] + ' ' + a[1] + ' A' + r + ' ' + r + ' 0 0 1 ' + z[0] + ' ' + z[1] + '" fill="none" stroke="#E3E8F0" stroke-width="20"/>' + (frac > 0 ? '<path d="M' + a[0] + ' ' + a[1] + ' A' + r + ' ' + r + ' 0 0 1 ' + b[0].toFixed(1) + ' ' + b[1].toFixed(1) + '" fill="none" stroke="' + color + '" stroke-width="20"/>' : '') +
      '<line x1="' + mk[0].toFixed(1) + '" y1="' + mk[1].toFixed(1) + '" x2="' + mk2[0].toFixed(1) + '" y2="' + mk2[1].toFixed(1) + '" stroke="#0B3A82" stroke-width="2.5"/><text x="' + cx + '" y="' + (cy - 6) + '" font-size="26" fill="#33415C" text-anchor="middle">' + label + '</text><text x="' + (cx - r) + '" y="' + (cy + 14) + '" font-size="9" fill="#6B7A8C" text-anchor="middle">0</text><text x="' + (cx + r) + '" y="' + (cy + 14) + '" font-size="9" fill="#6B7A8C" text-anchor="middle">' + (sub || '') + '</text></svg>';
  }
  function tile(v, label, bg) { return '<div class="kq-tile" style="background:' + bg + '"><b>' + v + '</b><span>' + label + '</span></div>'; }
  function sel(id, label, opts, cur) { return '<label class="small muted" style="display:block;margin-bottom:6px">' + label + '<select id="' + id + '" style="width:100%">' + opts.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (o[0] === cur ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') + '</select></label>'; }
  function pct(v) { return v == null ? '' : v.toFixed(2); }
  function attColor(v) { return v == null ? '' : v >= .8 ? '#8FD19E' : v >= .6 ? '#F6E27A' : '#F08A8A'; }

  // ---------------------------------------------------------------- the three overview pages
  function filtered(sm) { return sm.risks.filter(function (x) { return (!P.reg || x.register === P.reg) && (!P.cat || x.category === P.cat); }); }
  function exec(sm, d) {
    var rs = filtered(sm).filter(function (x) { return x.current != null; }), n = rs.length, avg = n ? rs.reduce(function (a, x) { return a + x.current; }, 0) / n : 0, out = rs.filter(function (x) { return x.current > 10; }).length;
    var inds = sm.indicators.filter(function (i) { return rs.some(function (x) { return x.code === i.id; }); }), g = inds.filter(function (i) { return i.status === 'green'; }).length, a = inds.filter(function (i) { return i.status === 'amber'; }).length, rd = inds.filter(function (i) { return i.status === 'red'; }).length, att = g + a + rd ? Math.round(100 * (g + a / 2) / (g + a + rd)) : 0;
    var eff = Math.round(100 * (1 - avg / 25)), top = rs.slice().sort(function (x, y) { return y.current - x.current; }).slice(0, 10), cats = {};
    rs.forEach(function (x) { (cats[x.category] = cats[x.category] || []).push(x.current); });
    var catS = { cats: Object.keys(cats), series: [{ name: 'Avg residual', values: Object.keys(cats).map(function (c) { return +(cats[c].reduce(function (s, v) { return s + v; }, 0) / cats[c].length).toFixed(1); }) }, { name: 'Inherent', values: Object.keys(cats).map(function () { return 25; }) }], kind: 'bars' };
    catS.cats = catS.cats.map(function (c) { return c.replace('Compliance & Regulatory', 'Compl.&Reg.'); });
    var topS = { cats: top.map(function (x) { return x.code; }), kind: 'resid', target: 10, series: [{ name: 'Residual', values: top.map(function (x) { return x.current; }) }] };
    return '<div class="kq-wrap"><div style="display:grid;grid-template-columns:200px 1fr;gap:10px">' +
      '<div class="kq-pan">' + sel('fp', 'Period', sm.quarters.map(function (q) { return [q, K.qlab(q)]; }), sm.period) + sel('fr', 'Register', [['', 'All'], ['Enterprise (RISCO)', 'Enterprise (RISCO)'], ['Board of Trustees', 'Board of Trustees']], P.reg) + sel('fc', 'Risk category', [['', 'All']].concat(uniq(sm.risks.map(function (x) { return x.category; })).map(function (c) { return [c, c]; })), P.cat) + '<div class="small muted">Inherent is 25 for every risk; appetite is 10. Attainment counts KRIs met plus half of those near target.</div></div>' +
      '<div><div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px">' + tile(n, 'Risks rated', '#0B3A82') + tile(25, 'Inherent (all risks)', '#C8102E') + tile(avg.toFixed(0), 'Average residual', '#F28A1E') + tile(out, 'Outside appetite', '#7A1F1F') + tile(n - out, 'Within appetite', '#2FA84F') + '</div>' +
      '<div class="kq-g3" style="margin-top:10px"><div class="kq-pan"><b style="font-size:12px;color:#0B3A82">Average residual vs inherent 25 (marker = appetite 10)</b>' + gauge(avg / 25, avg.toFixed(0), 10 / 25, avg <= 10 ? '#2FA84F' : avg <= 15 ? '#F5C400' : '#F28A1E', '25') + '</div>' +
      '<div class="kq-pan"><b style="font-size:12px;color:#0B3A82">Implied control effect (marker 60%)</b>' + gauge(eff / 100, eff + '%', .6, eff >= 60 ? '#2FA84F' : '#F5C400', '100%') + '</div>' +
      '<div class="kq-pan"><b style="font-size:12px;color:#0B3A82">Indicators on target (marker 80%)</b>' + gauge(att / 100, att + '%', .8, att >= 80 ? '#2FA84F' : att >= 60 ? '#2FA84F' : '#F5C400', '100%') + '</div></div></div></div>' +
      '<div class="kq-g3" style="margin-top:10px;grid-template-columns:1fr 1.4fr 1.6fr"><div class="kq-pan"><b style="font-size:12px;color:#0B3A82">Residual vs inherent by risk category</b>' + bars(catS) + legend(catS.series) + '</div>' +
      '<div class="kq-pan"><b style="font-size:12px;color:#0B3A82">Top 10 risks by residual (colour = band; dashed red = appetite 10)</b>' + bars(topS) + '</div>' +
      '<div class="kq-pan"><b style="font-size:12px;color:#0B3A82">Top 10 risks</b><table class="kq-tbl" style="margin-top:4px"><tr><th>ID</th><th>Risk</th><th>Resid.</th><th>Effect</th><th>KRIs</th><th></th></tr>' + top.map(function (x) {
        var at = x.att[sm.period]; return '<tr><td>' + x.code + '</td><td>' + esc(x.name) + '</td><td style="background:' + BAND[bandOf(x.current)] + ';color:' + (bandOf(x.current) === 'yellow' ? '#3A2F00' : '#fff') + ';text-align:center;font-weight:700">' + x.current + '</td><td>' + Math.round(100 * x.effect) + '%</td><td style="background:' + attColor(at) + '">' + (at == null ? '' : Math.round(at * 100) + '%') + '</td><td>' + K.lamp(at == null ? 'info' : at >= .8 ? 'green' : at >= .6 ? 'amber' : 'red', 'KRI attainment') + '</td></tr>'; }).join('') + '</table></div></div></div>';
  }
  function uniq(a) { var s = {}; return a.filter(function (x) { return x && !s[x] && (s[x] = 1); }); }
  function move(sm) {
    var rs = filtered(sm).filter(function (x) { return (!P.dir || (P.dir === 'up' ? x.change > 0 : P.dir === 'down' ? x.change < 0 : x.change === 0)) && (!P.app || x.appetite === P.app); }), Q = sm.quarters, cell = function (v) { return v == null ? '<td></td>' : '<td style="background:' + BAND[bandOf(v)] + ';color:' + (bandOf(v) === 'yellow' ? '#3A2F00' : '#fff') + ';text-align:right;font-weight:700">' + v + '</td>'; };
    return '<div class="kq-wrap"><div class="kq-g3" style="grid-template-columns:repeat(4,1fr);margin-bottom:10px">' + sel('fr', 'Register', [['', 'All'], ['Enterprise (RISCO)', 'Enterprise (RISCO)'], ['Board of Trustees', 'Board of Trustees']], P.reg) + sel('fc', 'Risk category', [['', 'All']].concat(uniq(sm.risks.map(function (x) { return x.category; })).map(function (c) { return [c, c]; })), P.cat) + sel('fd', 'Direction of change', [['', 'All'], ['up', 'Rating went up (worse)'], ['down', 'Rating went down (better)'], ['same', 'No change']], P.dir) + sel('fa', 'Appetite (' + K.qlab(sm.period) + ')', [['', 'All'], ['Within appetite', 'Within appetite'], ['Outside appetite', 'Outside appetite']], P.app) + '</div>' +
      '<div class="kq-pan" style="overflow:auto"><b style="font-size:13px;color:#0B3A82">All risks: residual rating movement</b><div class="muted" style="font-size:10.5px;margin-bottom:4px">Residual risk by quarter, change, appetite status and KRI attainment. The explanation is written from the KRI figures.</div><table class="kq-tbl"><tr><th>ID</th><th>Risk</th><th>Inherent</th>' + Q.map(function (q) { return '<th>' + K.qlab(q) + '</th>'; }).join('') + '<th>Change</th><th>Appetite</th>' + Q.map(function (q) { return '<th>KRIs ' + K.qlab(q).split(' ')[0] + '</th>'; }).join('') + '<th>Why the rating moved (' + K.qlab(sm.period) + ' position)</th></tr>' +
      rs.map(function (x) { var c = x.change, cc = c == null ? '' : c > 0 ? '<td style="background:#F9D5D5;color:#9B1C1C;font-weight:700">▲ ' + c + '</td>' : c < 0 ? '<td style="background:#D5F0DC;color:#1E7A39;font-weight:700">▼ ' + Math.abs(c) + '</td>' : '<td style="background:#EDEFF3;font-weight:700">■ 0</td>'; return '<tr><td>' + x.code + '</td><td><b>' + esc(x.name) + '</b></td><td style="background:#D7263D;color:#fff;text-align:right;font-weight:700">25</td>' + Q.map(function (q) { return cell(x.residual[q]); }).join('') + (cc || '<td></td>') + '<td>' + (x.appetite ? '<span style="white-space:nowrap">' + K.lamp(x.appetite === 'Within appetite' ? 'green' : 'red', x.appetite) + ' ' + x.appetite.replace(' appetite', '') + '</span>' : '') + '</td>' + Q.map(function (q) { var v = x.att[q]; return '<td style="background:' + attColor(v) + ';text-align:center">' + pct(v) + '</td>'; }).join('') + '<td style="min-width:360px">' + esc(x.impact) + '</td></tr>'; }).join('') + '</table></div></div>';
  }
  function univ(sm) {
    var cats = uniq(sm.risks.map(function (x) { return x.category; })), rks = sm.risks.map(function (x) { return x.name; }), inds = sm.indicators.filter(function (i) { var cs = Object.keys(P.cats).filter(function (k) { return P.cats[k]; }), rr = Object.keys(P.rks).filter(function (k) { return P.rks[k]; }); return (!cs.length || cs.indexOf(i.category) >= 0) && (!rr.length || rr.indexOf(i.risk) >= 0); });
    var g = inds.filter(function (i) { return i.status === 'green'; }).length, a = inds.filter(function (i) { return i.status === 'amber'; }).length, rd = inds.filter(function (i) { return i.status === 'red'; }).length, inf = inds.length - g - a - rd, n = g + a + rd, att = n ? Math.round(100 * (g + a / 2) / (n)) : 0;
    var by = cats.map(function (c) { var x = inds.filter(function (i) { return i.category === c; }), gg = x.filter(function (i) { return i.status === 'green'; }).length, aa = x.filter(function (i) { return i.status === 'amber'; }).length, nn = gg + aa + x.filter(function (i) { return i.status === 'red'; }).length; return [c, nn ? Math.round(100 * (gg + aa / 2) / nn) : null]; });
    return '<div class="kq-wrap"><div style="display:grid;grid-template-columns:220px 1fr;gap:10px"><div class="kq-pan">' + sel('fp', 'Period', sm.quarters.map(function (q) { return [q, K.qlab(q)]; }), sm.period) + '<b class="small">Risk category</b>' + cats.map(function (c) { return '<label style="display:block;font-size:12px"><input type="checkbox" data-cat="' + esc(c) + '"' + (P.cats[c] ? ' checked' : '') + '> ' + esc(c) + '</label>'; }).join('') + '<b class="small" style="display:block;margin-top:8px">Risk</b><div style="max-height:260px;overflow:auto">' + rks.map(function (c) { return '<label style="display:block;font-size:11.5px"><input type="checkbox" data-rk="' + esc(c) + '"' + (P.rks[c] ? ' checked' : '') + '> ' + esc(c) + '</label>'; }).join('') + '</div></div>' +
      '<div><div style="display:grid;grid-template-columns:260px 1fr;gap:10px"><div class="kq-pan"><b style="font-size:12px;color:#0B3A82">Attainment (marker 80%)</b>' + gauge(att / 100, att + '%', .8, att >= 60 ? '#2FA84F' : '#F5C400', '100%') + '</div><div><div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px">' + tile(n, 'Assessed', '#0B3A82') + tile(g, 'Met', '#2FA84F') + tile(a, 'Near target', '#C98A00') + tile(rd, 'Breached', '#D7263D') + tile(inf, 'No target (info)', '#6B7A8C') + '</div>' +
      '<div style="display:grid;grid-template-columns:repeat(' + Math.max(1, by.length) + ',1fr);gap:8px;margin-top:8px">' + by.map(function (b) { return '<div class="kq-tile" style="background:#F2C200;color:#3A2F00"><b style="font-size:24px">' + (b[1] == null ? '-' : b[1] + '%') + '</b><span>' + esc(b[0]) + '</span></div>'; }).join('') + '</div></div></div>' +
      '<div class="kq-pan" style="margin-top:10px;max-height:520px;overflow:auto"><b style="font-size:12.5px;color:#0B3A82">Indicators in scope (' + K.qlab(sm.period) + ')</b><div class="muted" style="font-size:10.5px;margin-bottom:4px">Each KRI with its target, reported value and status (green met, amber within 10%, red breached, grey = no target).</div><table class="kq-tbl"><tr><th>ID</th><th>Indicator</th><th>Better when</th><th>Target</th><th>Value</th><th>Status</th></tr>' +
      inds.map(function (i) { var c = { green: '#C9ECD2', amber: '#FBE9A6', red: '#F7C9C9', info: '#E8ECF2' }[i.status]; return '<tr><td>' + i.id + '</td><td>' + esc(i.name) + '</td><td>' + i.better + '</td><td>' + esc(i.target) + '</td><td style="text-align:right"><b>' + esc(i.value) + '</b></td><td style="background:' + c + '">' + K.lamp(i.status, '', true) + '</td></tr>'; }).join('') + '</table></div></div></div></div>';
  }

  // ---------------------------------------------------------------- the page
  SX.kriqPbi = function () {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    var q = (K.UI.from ? 'from=' + K.UI.from : '') + (K.UI.to ? (K.UI.from ? '&' : '') + 'to=' + K.UI.to : '') + (P.period ? (K.UI.from || K.UI.to ? '&' : '') + 'period=' + P.period : '');
    api('GET', '/api/kriq/pages?' + q).then(function (r) {
      if (r.empty) {
        if (r.seed_available && r.can.edit) { main.innerHTML = K.head('pbi', '') + '<div class="card" style="text-align:center;padding:34px"><h3>Loading the KRIs from the reports&hellip;</h3></div>'; return api('POST', '/api/kriq/seed', {}).then(SX.kriqPbi); }
        main.innerHTML = K.head('pbi', '') + '<div class="card" style="text-align:center;padding:34px"><h3>No quarterly KRI data yet</h3><p class="muted">Import a Board of Trustees or Risk Committee report, or type the figures in.</p><a class="btn p" style="--c:#E0474C" href="#/m/kri_monitor/data">Enter and import</a></div>'; return;
      }
      if (r.pbi_pending && r.can.edit) { return api('POST', '/api/kriq/seed', {}).then(SX.kriqPbi); }
      K.UI.from = r.from; K.UI.to = r.to; P.period = r.summary.period;
      var all = FIRST.concat(r.pages.map(function (p) { return [p.id, p.title.replace(/ \(.*$/, '').replace(/^Additional KRIs \| /, 'Additional: ')]; })), pg = r.pages.filter(function (p) { return p.id === P.page; })[0];
      if (!pg && ['exec', 'move', 'univ'].indexOf(P.page) < 0) P.page = 'exec';
      var opts = function (sel) { return r.all_quarters.map(function (x) { return '<option value="' + x + '"' + (x === sel ? ' selected' : '') + '>' + K.qlab(x) + '</option>'; }).join(''); };
      var title = P.page === 'exec' ? 'EcoCash Risk Dashboard | Executive Overview' : P.page === 'move' ? 'Residual Risk Rating Movement | ' + K.qlab(r.from) + ' to ' + K.qlab(r.to) : P.page === 'univ' ? 'Indicator Universe | KRIs against target' : pg.title,
        subt = P.page === 'exec' ? 'Residual risk, control effect and KRI attainment for the chosen period.' : P.page === 'move' ? 'Why each rating moved, written from the KRI figures.' : P.page === 'univ' ? 'Green = target met, amber = within 10% of target, red = breached. Attainment = met plus half of near-target, over KRIs assessed.' : pg.sub;
      var risksOf = pg ? pg.risks : r.risks.map(function (x) { return x.no; });
      var h = K.head('pbi', '<label class="small muted">From</label><select id="qf" style="width:104px">' + opts(r.from) + '</select><label class="small muted">to</label><select id="qt" style="width:104px">' + opts(r.to) + '</select>' + (r.can.edit ? '<button class="btn" id="eg">Edit figures</button><button class="btn" id="qe">Enter or edit a quarter</button>' : '') + K.dl('/api/kriq/export.pptx?' + K.qs(), 'Download PowerPoint', 'p') + K.dl('/api/kriq/export.xlsx?' + K.qs(), 'Download Power BI data'));
      h += '<div class="kq-band"><h2>' + esc(title) + '</h2><div class="s">' + esc(subt) + '</div></div>';
      if (P.page === 'exec') h += exec(r.summary, r); else if (P.page === 'move') h += move(r.summary); else if (P.page === 'univ') h += univ(r.summary);
      else h += '<div class="kq-wrap"><div class="' + (pg.panels.length === 1 ? '' : 'kq-g3') + '">' + pg.panels.map(function (p) { p.wide = pg.panels.length === 1; return panel(p, r.can.edit, pg.id); }).join('') + '</div>' + (pg.panels[0].table ? monTable(pg.panels[0].table) : '') + '</div>';
      h += '<div class="kq-pages" role="tablist">' + all.map(function (p) { return '<button role="tab" data-pg="' + p[0] + '" class="' + (p[0] === P.page ? 'on' : '') + '">' + esc(p[1]) + '</button>'; }).join('') + '</div><div class="small muted" style="margin:8px 0">Every chart is drawn from the stored KRI figures, so an import or an edit updates all pages. The lamp beside a chart shows the latest status of its KRI: red = off target, amber = near target, green = on target. Residual ratings use the Power BI report\'s whole-number GRC scale (inherent 25, appetite 10).</div>';
      main.innerHTML = h;
      var on = function (id, ev, f) { var e = $(id); if (e) e.addEventListener(ev, f); };
      on('#qf', 'change', function () { K.UI.from = this.value; SX.kriqPbi(); }); on('#qt', 'change', function () { K.UI.to = this.value; P.period = null; SX.kriqPbi(); });
      on('#fp', 'change', function () { P.period = this.value; SX.kriqPbi(); }); on('#fr', 'change', function () { P.reg = this.value; SX.kriqPbi(); }); on('#fc', 'change', function () { P.cat = this.value; SX.kriqPbi(); }); on('#fd', 'change', function () { P.dir = this.value; SX.kriqPbi(); }); on('#fa', 'change', function () { P.app = this.value; SX.kriqPbi(); });
      on('#eg', 'click', function () { K.editGrid(risksOf, SX.kriqPbi); }); on('#qe', 'click', function () { K.manual({}); });
      $$('[data-ce]', main).forEach(function (b) { b.addEventListener('click', function () { var pp = pg.panels[+b.dataset.ce]; if (pp) editor(pg.id, pp, SX.kriqPbi); }); });
      $$('[data-pg]', main).forEach(function (b) { b.addEventListener('click', function () { P.page = b.dataset.pg; SX.kriqPbi(); window.scrollTo(0, 0); }); });
      $$('[data-cat]', main).forEach(function (b) { b.addEventListener('change', function () { P.cats[b.dataset.cat] = b.checked; SX.kriqPbi(); }); }); $$('[data-rk]', main).forEach(function (b) { b.addEventListener('change', function () { P.rks[b.dataset.rk] = b.checked; SX.kriqPbi(); }); });
    }, function (e) { main.innerHTML = K.head('pbi', '') + '<div class="card">' + esc(e.message || 'Could not load') + '</div>'; });
  };
  function monTable(t) {
    return '<div class="kq-pan" style="margin-top:10px"><b style="font-size:12.5px;color:#0B3A82">Values (USD thousand)</b><div class="muted" style="font-size:10.5px;margin-bottom:4px">USD thousand as reported each quarter.</div><table class="kq-tbl" style="max-width:760px"><tr><th>KRI</th>' + t.cats.map(function (c) { return '<th style="text-align:right">' + esc(c) + '</th>'; }).join('') + '<th style="text-align:right">Total</th></tr>' +
      t.rows.map(function (x) { return '<tr><td>' + esc(x.name) + '</td>' + x.values.map(function (v) { return '<td style="text-align:right">' + (v == null ? '' : fn(v)) + '</td>'; }).join('') + '<td style="text-align:right"><b>' + fn(x.total) + '</b></td></tr>'; }).join('') + '<tr><td><b>Total</b></td>' + t.totals.map(function (v) { return '<td style="text-align:right"><b>' + fn(v) + '</b></td>'; }).join('') + '<td style="text-align:right"><b>' + fn(t.grand) + '</b></td></tr></table></div>';
  }
})();
