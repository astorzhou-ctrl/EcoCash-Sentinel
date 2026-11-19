/* Small SVG chart renderer used by Weekly KPI: column, bar, line and area charts with a legend. No external libraries. */
(function () {
  'use strict';
  var PAL = ['#1F5FBF', '#E4202E', '#1BA94C', '#F58220', '#6B4FBB', '#00A3B4'], esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  function dec(f) { var m = /\.(0+)/.exec(f || ''); return m ? m[1].length : (f === '#,##0' || f === '0' ? 0 : 2); }
  function nf(v, f) { if (v == null) return ''; var d = dec(f); return Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: /,/.test(f || '') || Math.abs(v) >= 10000 }); }
  function ticks(mn, mx) { var span = mx - mn || 1, raw = span / 4, p = Math.pow(10, Math.floor(Math.log10(raw))), st = [1, 2, 2.5, 5, 10].map(function (m) { return m * p; }).filter(function (s) { return s >= raw; })[0], lo = Math.floor(mn / st) * st, hi = Math.ceil(mx / st) * st, t = []; for (var v = lo; v <= hi + st / 2; v += st) t.push(+v.toFixed(10)); return t; }
  SX.chart = function (c, o) {
    o = o || {}; var W = o.w || 560, H = o.h || 290, hz = c.ctype === 'bar', S = c.series, n = c.cats.length;
    if (!n || !S.length) return '<div class="empty">No data yet for this chart.</div>';
    var legendH = S.length > 1 ? 26 : 4, padL = hz ? 118 : 50, padR = S.some(function (s) { return s.axis === 2; }) ? 46 : 14, padT = 34, padB = (hz ? 24 : 34) + legendH, x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB;
    var all = [].concat.apply([], S.filter(function (s) { return s.axis !== 2; }).map(function (s) { return s.values.filter(function (v) { return v != null; }); }));
    var mn = Math.min.apply(null, all), mx = Math.max.apply(null, all); if (c.ctype !== 'line') { mn = Math.min(mn, 0); mx = Math.max(mx, 0); } if (mn === mx) mx = mn + 1;
    var T = ticks(mn, mx); mn = T[0]; mx = T[T.length - 1];
    var sc2 = function (v) { return y1 - (y1 - y0) * v; }, sc = function (v) { return hz ? x0 + (x1 - x0) * (v - mn) / (mx - mn) : y1 - (y1 - y0) * (v - mn) / (mx - mn); };
    var g = '<text x="' + W / 2 + '" y="18" text-anchor="middle" font-size="12.5" font-weight="700" fill="#1A1A1A">' + esc(c.title) + '</text>';
    T.forEach(function (t) { var p = sc(t); g += hz ? '<line x1="' + p + '" x2="' + p + '" y1="' + y0 + '" y2="' + y1 + '" stroke="#E6ECF4"/><text x="' + p + '" y="' + (y1 + 13) + '" font-size="9" text-anchor="middle" fill="#6B7A8C">' + nf(t, c.fmt) + '</text>' : '<line x1="' + x0 + '" x2="' + x1 + '" y1="' + p + '" y2="' + p + '" stroke="#E6ECF4"/><text x="' + (x0 - 6) + '" y="' + (p + 3) + '" font-size="9" text-anchor="end" fill="#6B7A8C">' + nf(t, c.fmt) + '</text>'; });
    if (S.some(function (s) { return s.axis === 2; })) [0, 0.25, 0.5, 0.75, 1].forEach(function (t) { g += '<line x1="' + x1 + '" x2="' + (x1 + 4) + '" y1="' + sc2(t) + '" y2="' + sc2(t) + '" stroke="#A6A6A6"/><text x="' + (x1 + 7) + '" y="' + (sc2(t) + 3) + '" font-size="9" fill="#6B7A8C">' + Math.round(t * 100) + '%</text>'; });
    var lab = c.labels !== false && n * S.length <= 72, band = (hz ? (y1 - y0) : (x1 - x0)) / n, col = function (k, s) { return s.color ? '#' + s.color : PAL[k % PAL.length]; };
    if (c.ctype === 'column' || hz) {
      var bw = band * 0.78 / S.length;
      S.forEach(function (s, k) { s.values.forEach(function (v, i) { if (v == null) return; var p0 = sc(0), p1 = sc(v), b = band * i + band * 0.11 + bw * k;
        g += hz ? '<rect x="' + Math.min(p0, p1) + '" y="' + (y0 + b) + '" width="' + Math.abs(p1 - p0) + '" height="' + bw + '" fill="' + col(k, s) + '"><title>' + esc(c.cats[i] + ' · ' + s.name + ': ' + nf(v, c.fmt)) + '</title></rect>' + (lab && !s.nolabels ? '<text x="' + (Math.max(p0, p1) + 3) + '" y="' + (y0 + b + bw / 2 + 3) + '" font-size="8.5" fill="#33465E">' + nf(v, c.fmt) + '</text>' : '')
          : '<rect x="' + (x0 + b) + '" y="' + Math.min(p0, p1) + '" width="' + bw + '" height="' + Math.max(Math.abs(p1 - p0), 0.5) + '" fill="' + col(k, s) + '"><title>' + esc(c.cats[i] + ' · ' + s.name + ': ' + nf(v, c.fmt)) + '</title></rect>' + (lab && !s.nolabels ? '<text x="' + (x0 + b + bw / 2) + '" y="' + (v >= 0 ? Math.min(p0, p1) - 3 : Math.max(p0, p1) + 10) + '" font-size="8" text-anchor="middle" fill="#33465E">' + nf(v, c.fmt) + '</text>' : ''); }); });
    } else {
      var X = function (i) { return x0 + (n === 1 ? (x1 - x0) / 2 : (x1 - x0) * i / (n - 1)); };
      S.forEach(function (s, k) {
        var pts = [], run = [];
        s.values.forEach(function (v, i) { if (v == null) { if (run.length) pts.push(run); run = []; } else run.push([X(i), (s.axis === 2 ? sc2 : sc)(v), v, i]); }); if (run.length) pts.push(run);
        pts.forEach(function (r) {
          if (c.ctype === 'area') g += '<polygon points="' + r.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') + ' ' + r[r.length - 1][0] + ',' + sc(0) + ' ' + r[0][0] + ',' + sc(0) + '" fill="' + col(k, s) + '" opacity="0.35"/>';
          g += '<polyline fill="none" stroke="' + col(k, s) + '" stroke-width="' + (s.dashed ? 1.6 : 2.4) + '"' + (s.dashed ? ' stroke-dasharray="6 4"' : '') + ' points="' + r.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') + '"/>';
          if (!s.dashed) r.forEach(function (p) { g += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="3" fill="' + col(k, s) + '"><title>' + esc(c.cats[p[3]] + ' · ' + s.name + ': ' + (s.axis === 2 ? Math.round(p[2] * 1000) / 10 + '%' : nf(p[2], c.fmt))) + '</title></circle>' + (lab && !s.nolabels && S.length * n <= 48 ? '<text x="' + p[0] + '" y="' + (p[1] - 6) + '" font-size="8" text-anchor="middle" fill="#33465E">' + (s.axis === 2 ? Math.round(p[2] * 1000) / 10 + '%' : nf(p[2], c.fmt)) + '</text>' : ''); });
        });
      });
    }
    var skip = Math.ceil(n / (hz ? n : Math.max(4, Math.floor((x1 - x0) / 52))));
    c.cats.forEach(function (t, i) { if (i % skip) return; g += hz ? '<text x="' + (x0 - 6) + '" y="' + (y0 + band * i + band / 2 + 3) + '" font-size="9" text-anchor="end" fill="#33465E">' + esc(String(t).length > 22 ? String(t).slice(0, 21) + '\u2026' : t) + '</text>' : '<text x="' + ((c.ctype === 'column' ? x0 + band * i + band / 2 : (n === 1 ? (x0 + x1) / 2 : x0 + (x1 - x0) * i / (n - 1)))) + '" y="' + (y1 + 14) + '" font-size="9" text-anchor="middle" fill="#6B7A8C">' + esc(t) + '</text>'; });
    if (S.length > 1) { var lx = x0; S.forEach(function (s, k) { g += '<rect x="' + lx + '" y="' + (H - 16) + '" width="10" height="10" fill="' + col(k, s) + '"/><text x="' + (lx + 14) + '" y="' + (H - 7) + '" font-size="9.5" fill="#33465E">' + esc(s.name.length > 26 ? s.name.slice(0, 25) + '\u2026' : s.name) + '</text>'; lx += 24 + Math.min(s.name.length, 26) * 5.4; }); }
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img" aria-label="' + esc(c.title) + '">' + g + '</svg>';
  };
  SX.chartGrid = function (charts) {
    var live = (charts || []).filter(function (c) { return !c.empty; });
    return live.length ? '<div class="cgrid">' + live.map(function (c) { return '<div class="ctile">' + SX.chart(c) + '</div>'; }).join('') + '</div>' : '';
  };
})();
