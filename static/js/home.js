/* Home: hero with the financial year, risk pulse, market watch, quick actions. Light animation: CSS transforms only, paused when the tab is hidden, off for reduced motion. */
(function () {
  'use strict';
  var esc = SX.esc, V = SX.viz;
  var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function fmtD(d) { return d.getDate() + ' ' + MON[d.getMonth()] + ' ' + d.getFullYear(); }
  // Financial year: 1 March to the last day of February. It is named by the year it ends in: 1 Mar 2026 to 28 Feb 2027 is FY2027.
  SX.fy = function (d) {
    d = d || new Date(); var y = d.getFullYear(), m = d.getMonth(), endY = m >= 2 ? y + 1 : y;
    var start = new Date(endY - 1, 2, 1), endEx = new Date(endY, 2, 1), q = Math.floor(((m + 10) % 12) / 3) + 1;
    var qs = new Date(start.getFullYear(), 2 + (q - 1) * 3, 1), qe = new Date(qs.getFullYear(), qs.getMonth() + 3, 1), DAY = 86400000;
    var total = Math.round((endEx - start) / DAY), day = Math.floor((d - start) / DAY) + 1, qt = Math.round((qe - qs) / DAY), qd = Math.floor((d - qs) / DAY) + 1;
    return { label: 'FY' + endY, year: endY, q: q, start: start, end: new Date(endEx - DAY), total: total, day: day, pct: Math.min(100, Math.round(100 * day / total)), qpct: Math.min(100, Math.round(100 * qd / qt)), qLeft: qt - qd, left: total - day,
      text: 'Financial year ' + fmtD(start) + ' to ' + fmtD(new Date(endEx - DAY)), quarters: [0, 1, 2, 3].map(function (i) { var a = new Date(start.getFullYear(), 2 + i * 3, 1), b = new Date(a.getFullYear(), a.getMonth() + 2, 1); return { n: i + 1, span: MON[a.getMonth()] + ' to ' + MON[b.getMonth()] }; }) };
  };
  function ring(pct, label, sub) {
    var r = 52, c = 2 * Math.PI * r, o = c * (1 - pct / 100);
    return '<svg viewBox="0 0 140 140" class="fyring" role="img" aria-label="' + esc(label) + '"><defs><linearGradient id="fyg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8EC5FF"/><stop offset="1" stop-color="#38BDF8"/></linearGradient></defs>' +
      '<circle cx="70" cy="70" r="' + r + '" fill="none" stroke="rgba(255,255,255,.16)" stroke-width="11"/><circle cx="70" cy="70" r="' + r + '" fill="none" stroke="url(#fyg)" stroke-width="11" stroke-linecap="round" stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + o.toFixed(1) + '" transform="rotate(-90 70 70)" class="fyarc"/>' +
      '<text x="70" y="66" text-anchor="middle" font-size="27" font-weight="800" fill="#fff">' + pct + '%</text><text x="70" y="86" text-anchor="middle" font-size="11" fill="rgba(255,255,255,.8)">' + esc(sub) + '</text></svg>';
  }
  SX.homeHero = function (u, greet) {
    var f = SX.fy(), now = new Date();
    var qs = f.quarters.map(function (q) {
      var cur = q.n === f.q, done = q.n < f.q;
      return '<div class="qseg' + (cur ? ' cur' : '') + (done ? ' done' : '') + '"><b>Q' + q.n + '</b><span>' + q.span + '</span>' + (cur ? '<i style="width:' + f.qpct + '%"></i>' : '') + '</div>';
    }).join('');
    return '<section class="hero" id="hero"><div class="hero-bg" aria-hidden="true"><span class="orb o1"></span><span class="orb o2"></span><span class="orb o3"></span><span class="mesh"></span></div>' +
      '<div class="hero-in"><div class="hero-l"><div class="eyebrow">EcoCash Sentinel &middot; Enterprise Risk Management</div><h1>' + esc(greet) + ', ' + esc(u.full_name.split(' ')[0]) + '</h1>' +
      '<p class="hero-sub">' + now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) + '</p>' +
      '<div class="hero-chips"><span class="chip big">' + f.label + ' &middot; Q' + f.q + '</span>' + (u.roles || []).slice(0, 3).map(function (r) { return '<span class="chip">' + esc(r) + '</span>'; }).join('') + '</div>' +
      '<div class="qbar" title="' + esc(f.text) + '">' + qs + '</div><p class="hero-note">' + f.qLeft + ' days left in Q' + f.q + ' &middot; ' + f.left + ' days left in ' + f.label + ' (' + esc(f.text.replace('Financial year ', '')) + ')</p></div>' +
      '<div class="hero-r">' + ring(f.pct, f.label + ' is ' + f.pct + ' percent complete', f.label + ' elapsed') + '</div></div></section>';
  };
  SX.homeMarket = function (box) {
    SX.api('GET', '/api/home/market').then(function (d) {
      if (!d.items.length) { box.remove(); return; }
      box.innerHTML = '<div class="sec-h"><h3>Market watch <span class="muted small">live figures ' + (d.status && d.status.online ? '<i class="dot on"></i>online' : '<i class="dot"></i>last known') + '</span></h3><a href="#/m/weekly_kpi">All indicators</a></div><div class="mk">' + d.items.map(function (i, k) {
        var up = i.change_pct != null && i.change_pct >= 0, col = i.change_pct == null ? '#98A2B3' : up ? '#2FA84F' : '#EF2B2B';
        return '<a class="mk-t rise" style="--d:' + (k * 60) + 'ms" href="#/m/weekly_kpi"><div class="mk-n">' + esc(i.name.replace(' price', '')) + '</div><div class="mk-v">' + Number(i.value).toLocaleString('en-US', { maximumFractionDigits: i.value < 10 ? 4 : 2 }) + '<small> ' + esc(i.unit || '') + '</small></div>' +
          '<div class="mk-c" style="color:' + col + '">' + (i.change_pct == null ? '&nbsp;' : (up ? '&#9650; ' : '&#9660; ') + Math.abs(i.change_pct) + '%') + '</div><div class="mk-s">' + V.spark(i.spark, { color: col, w: 120, h: 30 }) + '</div></a>';
      }).join('') + '</div>';
    }, function () { box.remove(); });
  };
  SX.homeQuick = function () {
    var A = [['risk_register', 'Risk Register', 'Assess and approve risks', '#2F6FD6'], ['command_center', 'Command Center', 'Portfolio at a glance', '#7C5CE0'], ['weekly_kpi', 'Weekly KPI', 'Live market indicators', '#EF2B2B'], ['actions_issues', 'Actions & Issues', 'Close what is open', '#0EA5A5'],
      ['incidents_losses', 'Incidents & Losses', 'Events and loss data', '#F97316'], ['board_hub', 'Board Hub', 'Decisions and packs', '#2FA84F'], ['fraud_intelligence', 'Fraud Intelligence', 'Hotspots and cases', '#C2410C'], ['crisis_room', 'Crisis Room', 'Be ready to respond', '#B42318']];
    var items = A.filter(function (a) { return SX.can(a[0], 'view'); }).slice(0, 8);
    if (!items.length) return '';
    return '<div class="sec-h"><h3>Jump in</h3></div><div class="qa">' + items.map(function (a, k) { return '<a class="qa-t rise" style="--c:' + a[3] + ';--d:' + (k * 50) + 'ms" href="#/m/' + a[0] + '">' + SX.tile(a[0], 38, a[3]) + '<b>' + esc(a[1]) + '</b><span>' + esc(a[2]) + '</span></a>'; }).join('') + '</div>';
  };
  SX.countUp = function (root) {
    var els = root.querySelectorAll('[data-count]'); if (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    els.forEach(function (el) { var to = parseFloat(el.dataset.count), t0 = performance.now(), dec = (el.dataset.dec | 0); (function step(t) { var p = Math.min(1, (t - t0) / 700); el.textContent = (to * (1 - Math.pow(1 - p, 3))).toFixed(dec); if (p < 1) requestAnimationFrame(step); })(t0); });
  };
  document.addEventListener('visibilitychange', function () { var h = document.getElementById('hero'); if (h) h.classList.toggle('paused', document.hidden); });
})();
