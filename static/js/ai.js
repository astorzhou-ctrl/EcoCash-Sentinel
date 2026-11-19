/* AI Insights: similar risks and controls (text similarity) and unusual indicator movements (robust statistics and a forecast). Local, explainable, suggestion only. */
(function () {
  'use strict';
  var $ = SX.$, esc = SX.esc, api = SX.api, COLOR = '#7C5CE0', TABS = [['similar', 'Similar risks and controls'], ['signals', 'Unusual movements']];
  var LEVEL = { Low: '#2FA84F', Medium: '#FDB022', Significant: '#F97316', High: '#EF2B2B' };
  function badge(t, bg, fg) { return '<span class="badge" style="background:' + bg + ';color:' + (fg || '#fff') + '">' + esc(t) + '</span>'; }
  function spark(vals, bad) {
    var w = 150, h = 38, mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals), r = mx - mn || 1;
    var pts = vals.map(function (v, i) { return (4 + i * (w - 8) / (vals.length - 1)).toFixed(1) + ',' + (h - 5 - (v - mn) / r * (h - 10)).toFixed(1); }), last = pts[pts.length - 1].split(',');
    return '<svg width="' + w + '" height="' + h + '" role="img" aria-label="Last readings"><polyline fill="none" stroke="' + (bad ? '#EF2B2B' : '#2F6FD6') + '" stroke-width="2" points="' + pts.join(' ') + '"/><circle cx="' + last[0] + '" cy="' + last[1] + '" r="3.5" fill="' + (bad ? '#EF2B2B' : '#2F6FD6') + '"/></svg>';
  }
  function bar(p) { var c = p >= 50 ? '#EF2B2B' : p >= 30 ? '#FDB022' : '#2F6FD6'; return '<div style="display:flex;align-items:center;gap:6px"><div style="width:90px;background:#EEF1F6;height:10px;border-radius:5px"><div style="width:' + Math.min(p, 100) + '%;background:' + c + ';height:10px;border-radius:5px"></div></div><b>' + p + '%</b></div>'; }

  SX.pages.aiInsights = function (tab) {
    tab = tab || 'similar'; var main = $('#main');
    main.innerHTML = SX.head('Risk &rsaquo; AI Insights', 'AI Insights', COLOR) + SX.tabs('m/ai_insights', TABS, tab, COLOR) + '<div id="aitab"></div>';
    (tab === 'signals' ? signals : similar)();
  };

  function similar() {
    var box = $('#aitab');
    box.innerHTML = '<div class="alert info" style="margin-bottom:10px"><b>How it works.</b> Sentinel compares your description with every risk and control already in the register using text similarity (TF-IDF, a machine-learning technique). It runs on this computer, nothing leaves it, and it only <b>suggests</b>: you decide. Every search is recorded in the audit trail.</div>' +
      '<div class="card"><label class="f">Describe the risk in your own words<textarea id="aiq" rows="3" placeholder="e.g. Fraudsters get a replacement SIM card for a customer and empty their mobile money wallet"></textarea></label><div class="toolbar" style="margin-top:8px"><button class="btn p" id="aigo" style="--c:' + COLOR + '">Find similar risks and suggest controls</button></div></div><div id="airs"></div>';
    $('#aigo').addEventListener('click', function () {
      var btn = this; btn.disabled = true; $('#airs').innerHTML = '<div class="loading">Analysing...</div>';
      api('POST', '/api/ai/similar', { text: $('#aiq').value }).then(function (d) {
        btn.disabled = false; var h = '', dup = d.risks.filter(function (r) { return r.duplicate; });
        if (dup.length) h += '<div class="alert warn" style="margin-top:12px;border-left:4px solid #EF2B2B"><b>Possible duplicate.</b> ' + esc(dup[0].ref) + ' <b>' + esc(dup[0].title) + '</b> is ' + Math.round(dup[0].similarity * 100) + '% similar. Check it before adding a new risk.</div>';
        h += '<div class="card" style="margin-top:12px"><h3>Similar risks</h3>' + (d.risks.length ? '<table class="t"><tr><th>Risk</th><th>Category</th><th>Level</th><th>Status</th><th>Similarity</th><th>Because of</th></tr>' + d.risks.map(function (r) { return '<tr><td><b>' + esc(r.ref) + '</b> ' + esc(r.title) + '</td><td>' + esc(r.category || '') + '</td><td>' + (r.level ? badge(r.level, LEVEL[r.level] || '#98A2B3', r.level === 'Medium' ? '#3A2600' : '#fff') : '<span class="muted">not rated</span>') + '</td><td>' + esc(r.status) + '</td><td>' + bar(Math.round(r.similarity * 100)) + '</td><td class="muted">' + esc(r.because.join(', ')) + '</td></tr>'; }).join('') + '</table>' : '<div class="muted">Nothing in the register is similar to this description.</div>') + '</div>';
        h += '<div class="card" style="margin-top:12px"><h3>Controls used on similar risks</h3>' + (d.controls.length ? '<table class="t"><tr><th>Control</th><th>Domain</th><th>Type</th><th>Effectiveness</th><th>From risk</th><th>Match</th></tr>' + d.controls.map(function (c) { return '<tr><td><b>' + esc(c.ref || '') + '</b> ' + esc(c.statement) + '</td><td>' + esc(c.domain || '') + '</td><td>' + esc(c.type || '') + '</td><td>' + (c.effectiveness == null ? '<span class="muted">not rated</span>' : c.effectiveness + '%' + (c.tested ? ' <span class="muted small">tested</span>' : ' <span class="muted small">self-rated</span>')) + '</td><td>' + esc(c.from_risk) + '</td><td>' + bar(Math.round(c.similarity * 100)) + '</td></tr>'; }).join('') + '</table>' : '<div class="muted">No control in the library matches yet.</div>') + '</div>';
        h += '<p class="muted small" style="margin-top:8px">Compared with ' + d.indexed.risks + ' risks and ' + d.indexed.controls + ' controls you can see.</p>'; $('#airs').innerHTML = h;
      }, function (e) { btn.disabled = false; $('#airs').innerHTML = ''; SX.toast(e.message, 'bad'); });
    });
  }

  function signals() {
    var box = $('#aitab'); box.innerHTML = '<div class="loading">Checking the indicators...</div>';
    api('GET', '/api/ai/signals').then(function (d) {
      var h = '<div class="alert info" style="margin-bottom:10px"><b>How it works.</b> ' + esc(d.method) + '. Checked ' + d.checked + ' indicators with enough history. A flag is a prompt to look, not a conclusion.</div>';
      if (!d.signals.length) h += '<div class="card"><div class="muted">Nothing unusual: no spikes, long runs in one direction, or forecast breaches in the indicators checked.</div></div>';
      else h += '<div class="grid">' + d.signals.map(function (s) {
        var chips = s.flags.map(function (f) { return badge({ spike: 'Unusual value', trend: 'Five in a row', forecast: 'Forecast to red' }[f], s.bad ? '#EF2B2B' : '#2F6FD6'); }).join(' ');
        return '<div class="card s6" style="border-left:5px solid ' + (s.bad ? '#EF2B2B' : '#2F6FD6') + '"><div style="display:flex;justify-content:space-between;gap:10px"><div><div class="muted small">' + esc(s.kind.toUpperCase()) + ' · ' + esc(s.grp || '') + ' · ' + esc(s.code) + '</div><div style="font-weight:700;font-size:16px;margin:2px 0">' + esc(s.name) + '</div><div>' + chips + '</div></div><div>' + spark(s.spark, s.bad) + '</div></div>' +
          '<div style="margin-top:8px"><b>Latest ' + esc(String(s.latest.value)) + '</b> <span class="muted">on ' + SX.fmt(s.latest.period, true) + ', typical ' + esc(String(s.typical)) + '</span></div><div style="margin-top:6px">' + esc(s.message) + '</div></div>';
      }).join('') + '</div>';
      box.innerHTML = h;
    }, function (e) { box.innerHTML = '<div class="card">' + esc(e.message) + '</div>'; });
  }
})();
