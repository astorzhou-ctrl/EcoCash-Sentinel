/* Control Library & Testing: the control universe, effectiveness on the GRC Policy scale (1 to 10), design and operating tests, quarterly attestation. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#2F7D6B', f = { q: '', domain: '', dept: '', status: '', band: '', page: 1 };
  var TREAT = { Accept: ['#2FA84F', '#fff'], Mitigate: ['#FDB022', '#3A2600'], 'Immediate Action': ['#EF2B2B', '#fff'] };
  var ST = { never: ['Never tested', '#98A2B3', '#fff'], overdue: ['Test overdue', '#EF2B2B', '#fff'], due_soon: ['Due within 30 days', '#FDB022', '#3A2600'], ok: ['Up to date', '#2FA84F', '#fff'] };
  function badge(t, bg, fg) { return '<span class="badge" style="background:' + bg + ';color:' + fg + '">' + esc(t) + '</span>'; }
  function rating(x) { if (!x.score) return '<span class="muted">Not rated</span>'; var c = TREAT[x.treat] || TREAT.Mitigate; return badge(x.score + ' · ' + x.classification, c[0], c[1]); }
  function tile(label, v, sub, color) { return '<div class="card s2" style="border-top:3px solid ' + (color || COLOR) + '"><div class="muted small" style="text-transform:uppercase;letter-spacing:.04em">' + label + '</div><div style="font-size:26px;font-weight:700">' + v + '</div><div class="muted small">' + (sub || '&nbsp;') + '</div></div>'; }
  function bar(label, pct, target, n) {
    var col = pct >= target ? '#2FA84F' : pct >= target - 20 ? '#FDB022' : '#EF2B2B';
    return '<div style="display:flex;align-items:center;gap:8px;margin:5px 0"><div style="width:150px;font-size:12px">' + esc(label) + '</div><div style="flex:1;background:#EEF1F6;height:14px;border-radius:7px;position:relative"><div style="width:' + Math.max(pct, 1) + '%;background:' + col + ';height:14px;border-radius:7px"></div><div style="position:absolute;left:' + target + '%;top:-3px;bottom:-3px;border-left:2px dashed #1B2A41"></div></div><div style="width:70px;font-size:12px;text-align:right">' + pct + '% <span class="muted">(' + n + ')</span></div></div>';
  }

  SX.pages.controls = function () {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    var qs = Object.keys(f).map(function (k) { return k + '=' + encodeURIComponent(f[k]); }).join('&');
    api('GET', '/api/controls?' + qs).then(function (d) {
      var T = d.tiles, can = d.can, h = SX.head('Controls &amp; Assurance &rsaquo; Control Library &amp; Testing', 'Control Library & Testing', COLOR, (can.export ? '<a class="btn" href="/api/controls/export.xlsx">Download Excel</a> ' : '') + (can.create ? '<button class="btn p" id="addc" style="--c:' + COLOR + '">Add a control</button>' : ''));
      h += '<div class="alert info" style="margin-bottom:10px">Controls are scored on the GRC Policy scale: <b>1</b> (highly effective, 90%) to <b>10</b> (non-existent, 0%). Scores 1 to 3 are <b>Accept</b>, 4 to 6 <b>Mitigate</b>, 7 to 10 <b>Immediate Action</b>. A control&rsquo;s current rating comes from its latest <b>test</b>, not from self-rating alone; a failed test raises an action and lowers the assurance of the risks it protects.</div><div class="grid">';
      h += tile('Controls', T.total.toLocaleString('en-US'), T.no_owner ? T.no_owner + ' without an owner' : 'all have an owner', T.no_owner ? '#EF2B2B' : COLOR);
      h += tile('Tested in 12 months', T.tested_12m.toLocaleString('en-US'), T.tested_pct + '% of the library', '#2F6FD6');
      h += tile('Average effectiveness', T.avg_effectiveness == null ? 'n/a' : T.avg_effectiveness + '%', 'target ' + d.target + '%', T.avg_effectiveness != null && T.avg_effectiveness >= d.target ? '#2FA84F' : '#FDB022');
      h += tile('Failing (score 7 to 10)', T.failing, 'Immediate Action', T.failing ? '#EF2B2B' : '#2FA84F');
      h += tile('Due for testing', T.due, T.overdue + ' overdue', T.due ? '#FDB022' : '#2FA84F');
      h += tile('Test results', d.quarters.length ? d.quarters[d.quarters.length - 1].tests : 0, d.quarters.length ? 'this quarter, ' + d.quarters[d.quarters.length - 1].failed + ' failed' : 'none recorded yet', '#7C5CE0');
      h += '</div><div class="grid" style="margin-top:12px"><div class="card s8"><h3>Effectiveness by domain <span class="muted small">against the policy&rsquo;s ' + d.target + '% (dashed line)</span></h3>' + (d.domains.length ? '<div class="grid" style="align-items:center"><div class="s7" style="grid-column:span 7">' + SX.viz.gauges(d.domains.map(function (z) { return { label: z.domain, value: z.effectiveness, sub: z.n + ' controls' }; }), { max: 100, unit: '%', target: d.target, size: 138, bands: [[d.target - 20, '#EF2B2B'], [d.target, '#FDB022'], [100, '#2FA84F']] }) + '</div><div class="s5" style="grid-column:span 5">' + SX.viz.radar(d.domains.map(function (z) { return { label: z.domain, value: z.effectiveness, text: z.effectiveness + '%' }; }), { max: 100, target: d.target, color: '#7C5CE0' }) + '</div></div>' : '<div class="muted">No controls have a rating yet.</div>') + '</div>';
      h += '<div class="card s4"><h3>Test results by quarter</h3>' + (d.quarters.length ? '<table class="t"><tr><th>Quarter</th><th>Tests</th><th>Failed</th></tr>' + d.quarters.map(function (z) { return '<tr><td>' + esc(z.q) + '</td><td>' + z.tests + '</td><td>' + (z.failed ? '<b style="color:#EF2B2B">' + z.failed + '</b>' : '0') + '</td></tr>'; }).join('') + '</table>' : '<div class="muted">No tests recorded yet. Open a control and record the first test.</div>') + '</div></div>';
      var sel = function (id, label, arr, cur) { return '<select id="' + id + '" style="width:190px" aria-label="' + label + '"><option value="">' + label + '</option>' + arr.map(function (a) { var v = Array.isArray(a) ? a[0] : a, t = Array.isArray(a) ? a[1] : a; return '<option value="' + esc(v) + '"' + (cur === v ? ' selected' : '') + '>' + esc(t) + '</option>'; }).join('') + '</select>'; };
      h += '<div class="card" style="margin-top:12px"><div class="toolbar" style="flex-wrap:wrap;gap:8px"><input id="cq" type="search" placeholder="Search controls, owners, risks" value="' + esc(f.q) + '" style="min-width:240px">' + sel('cdom', 'All domains', d.domain_list, f.domain) + sel('cdep', 'All departments', d.depts, f.dept) +
        sel('cst', 'Any test status', [['due', 'Due for testing'], ['never', 'Never tested'], ['overdue', 'Test overdue'], ['due_soon', 'Due within 30 days'], ['ok', 'Up to date'], ['noowner', 'No owner']], f.status) + sel('cbd', 'Any rating', [['strong', 'Strong (1 to 3)'], ['adequate', 'Adequate (4 to 6)'], ['weak', 'Weak (7 to 10)'], ['unscored', 'Not rated']], f.band) + '</div>';
      h += '<div class="muted small" style="margin:8px 0">Showing ' + (d.total ? (d.page - 1) * d.size + 1 : 0) + ' to ' + Math.min(d.page * d.size, d.total) + ' of ' + d.total.toLocaleString('en-US') + ' controls, those that need testing first.</div>';
      h += '<div style="overflow-x:auto"><table class="t"><tr><th>Control</th><th>Risk</th><th>Domain</th><th>Owner</th><th>Rating</th><th>Last test</th><th>Test status</th></tr>';
      h += d.controls.map(function (x) { var s = ST[x.status]; return '<tr class="click" data-c="' + x.id + '"><td style="max-width:340px"><b>' + esc(x.ref || '') + '</b> ' + esc((x.statement || '').slice(0, 110)) + '</td><td>' + esc(x.risk.ref || '') + '</td><td>' + esc(x.domain || '') + '</td><td>' + (x.owner ? esc(x.owner) : '<b style="color:#EF2B2B">No owner</b>') + '</td><td>' + rating(x) + (x.ice_source === 'test' ? '' : ' <span class="muted small">self-rated</span>') + '</td><td>' + (x.last_test ? SX.fmt(x.last_test, true) : '-') + '</td><td>' + badge(s[0], s[1], s[2]) + (x.needs_test ? ' <b style="color:#EF2B2B">test now</b>' : '') + '</td></tr>'; }).join('') || '<tr><td colspan="7" class="muted">No controls match.</td></tr>';
      h += '</table></div><div class="toolbar" style="margin-top:8px"><button class="btn" id="cprev"' + (d.page <= 1 ? ' disabled' : '') + '>Previous</button><button class="btn" id="cnext"' + (d.page * d.size >= d.total ? ' disabled' : '') + '>Next</button></div></div>';
      main.innerHTML = h; wire(d);
    }, function (e) { main.innerHTML = '<div class="card">' + esc(e.message) + '</div>'; });
  };

  function wire(d) {
    var reload = SX.pages.controls, t = null;
    var on = function (id, ev, fn) { var e = $(id); if (e) e.addEventListener(ev, fn); };
    on('#cq', 'input', function () { clearTimeout(t); var v = this.value; t = setTimeout(function () { f.q = v; f.page = 1; reload(); }, 350); });
    [['#cdom', 'domain'], ['#cdep', 'dept'], ['#cst', 'status'], ['#cbd', 'band']].forEach(function (p) { on(p[0], 'change', function () { f[p[1]] = this.value; f.page = 1; reload(); }); });
    on('#cprev', 'click', function () { f.page--; reload(); }); on('#cnext', 'click', function () { f.page++; reload(); });
    $$('tr[data-c]').forEach(function (r) { r.addEventListener('click', function () { detail(+r.dataset.c); }); });
    on('#addc', 'click', addForm);
  }

  function addForm() {
    var m = SX.modal({ title: 'Add a control', wide: true, sticky: true, html: '<div class="form2"><label class="f">Risk reference<input name="risk" placeholder="e.g. R-0007"></label><label class="f">Control reference (optional)<input name="ref"></label><label class="f full">What the control does<textarea name="statement" rows="3"></textarea></label><label class="f">Domain<input name="domain"></label><label class="f">Type<select name="ctype"><option>Preventive</option><option>Detective</option><option>Corrective</option></select></label><label class="f">Owner<input name="owner"></label><label class="f">Self-rated effectiveness (0.1 to 1.0, optional)<input name="ice" type="number" step="0.1" min="0.1" max="1"></label></div>', buttons: [{ label: 'Cancel' }, { label: 'Add', cls: 'p', onClick: function () {
      var v = {}; $$('[name]', m.el).forEach(function (e) { v[e.name] = e.value; });
      return api('GET', '/api/risks?q=' + encodeURIComponent(v.risk)).then(function (r) {
        var hit = (r.risks || []).filter(function (x) { return x.ref === v.risk.trim(); })[0]; if (!hit) throw new Error('No risk with the reference ' + v.risk + ' is visible to you.');
        return api('POST', '/api/controls', { risk_id: hit.id, ref: v.ref, statement: v.statement, domain: v.domain, ctype: v.ctype, owner: v.owner, ice: v.ice });
      }).then(function () { SX.toast('Control added', 'ok'); SX.pages.controls(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }

  function detail(id) {
    api('GET', '/api/controls/' + id).then(function (d) {
      var k = d.control, can = d.can, h = '<dl class="kv"><dt>Risk</dt><dd>' + esc(k.risk.ref || '') + ' ' + esc(k.risk.title || '') + (k.risk.level ? ' <span class="muted">(' + esc(k.risk.level) + ')</span>' : '') + '</dd><dt>Control</dt><dd>' + esc(k.statement) + '</dd><dt>Domain and type</dt><dd>' + esc(k.domain || '-') + ' · ' + esc(k.ctype || '-') + '</dd><dt>Owner</dt><dd>' + (k.owner ? esc(k.owner) + (k.dept ? ' <span class="muted">(' + esc(k.dept) + ')</span>' : '') : '<b style="color:#EF2B2B">No owner: assign one</b>') + '</dd><dt>Current rating</dt><dd>' + rating(k) + (k.score ? ' · effectiveness ' + k.effectiveness + '% · ' + (k.ice_source === 'test' ? 'from the latest test' : 'self-rated, not yet tested') : '') + '</dd><dt>Next test</dt><dd>' + (k.next_due ? SX.fmt(k.next_due, true) : 'Not scheduled: record the first test') + '</dd></dl>';
      h += '<h3 style="margin-bottom:4px">Tests</h3>' + (d.tests.length ? '<table class="t"><tr><th>Date</th><th>Type</th><th>Score</th><th>Tester</th><th>Evidence</th></tr>' + d.tests.map(function (t) { var c = TREAT[(d.scale[t.score - 1] || {}).treat] || TREAT.Mitigate; return '<tr><td>' + SX.fmt(t.tested_on, true) + '</td><td>' + esc(t.ttype) + '</td><td>' + badge(t.score + ' · ' + d.scale[t.score - 1].classification, c[0], c[1]) + '</td><td>' + esc(t.tester || '') + '</td><td>' + esc(t.evidence) + '</td></tr>'; }).join('') + '</table>' : '<div class="muted">No tests yet.</div>');
      if (d.actions.length) h += '<h3 style="margin:10px 0 4px">Actions</h3>' + d.actions.map(function (a) { return '<div><a href="#/m/actions_issues">' + esc(a.ref) + '</a> ' + esc(a.title) + ' <span class="muted">(' + a.status.replace(/_/g, ' ') + ', due ' + SX.fmt(a.due, true) + ')</span></div>'; }).join('');
      if (d.attestations.length) h += '<h3 style="margin:10px 0 4px">Attestations</h3>' + d.attestations.slice(0, 4).map(function (a) { return '<div>' + esc(a.period) + ': ' + (a.ok ? 'confirmed operating as designed' : '<b style="color:#EF2B2B">issue reported</b>: ' + esc(a.note || '')) + ' <span class="muted">by ' + esc(a.attested_by) + '</span></div>'; }).join('');
      var btns = [{ label: 'Close' }];
      if (can.edit) { btns.push({ label: 'Edit', onClick: function () { editForm(k); } }); btns.push({ label: 'Record a test', cls: 'p', onClick: function () { testForm(d); } }); }
      btns.push({ label: 'Attest', onClick: function () { attestForm(k); } });
      SX.modal({ title: (k.ref || 'Control') + ' · ' + (k.domain || ''), wide: true, html: h, buttons: btns });
    });
  }

  function testForm(d) {
    var k = d.control, opts = d.scale.map(function (s) { return '<option value="' + s.score + '">' + s.score + ' · ' + esc(s.classification) + ' (' + s.effectiveness + '%, ' + esc(s.treat) + ')</option>'; }).join('');
    var m = SX.modal({ title: 'Record a test of ' + (k.ref || 'the control'), wide: true, sticky: true, sub: d.independent ? 'The test must be independent of the control owner.' : '<b style="color:#EF2B2B">You are the owner of this control, so you cannot test it. Ask someone independent.</b>',
      html: '<div class="form2"><label class="f">Type of test<select name="ttype"><option value="operating">Operating effectiveness</option><option value="design">Design</option></select></label><label class="f">Date of the test<input name="tested_on" type="date" max="' + new Date().toISOString().slice(0, 10) + '" value="' + new Date().toISOString().slice(0, 10) + '"></label><label class="f full">Score on the GRC Policy scale<select name="score">' + opts + '</select></label><label class="f full">What was tested and the evidence<textarea name="evidence" rows="4" placeholder="e.g. Re-performed 25 reconciliations from June; two were not signed off."></textarea></label></div><div class="muted small">A score of 7 to 10 raises an action for the owner automatically.</div>',
      buttons: [{ label: 'Cancel' }, { label: 'Save the test', cls: 'p', onClick: function () {
        var v = {}; $$('[name]', m.el).forEach(function (e) { v[e.name] = e.value; });
        return api('POST', '/api/controls/' + k.id + '/tests', v).then(function (r) { SX.toast('Scored ' + r.score + ' (' + r.classification + ', ' + r.treat + ')' + (r.action ? '. Action ' + r.action + ' raised.' : ''), 'ok'); SX.pages.controls(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
      } }] });
  }

  function attestForm(k) {
    var m = SX.modal({ title: 'Quarterly attestation: ' + (k.ref || ''), sticky: true, html: '<p class="muted small" style="margin-top:0">Confirm that this control operated as designed this quarter, or report the problem.</p><label class="f">Note (needed if you cannot confirm)<textarea name="note" rows="3"></textarea></label>',
      buttons: [{ label: 'Cancel' }, { label: 'Report a problem', onClick: function () { return go(false); } }, { label: 'Confirm it is operating', cls: 'p', onClick: function () { return go(true); } }] });
    function go(ok) { return api('POST', '/api/controls/' + k.id + '/attest', { ok: ok, note: $('[name=note]', m.el).value }).then(function (r) { SX.toast('Attestation recorded' + (r.action ? '. Action ' + r.action + ' raised.' : ''), 'ok'); SX.pages.controls(); }, function (e) { SX.toast(e.message, 'bad'); return false; }); }
  }

  function editForm(k) {
    var m = SX.modal({ title: 'Edit ' + (k.ref || 'control'), wide: true, sticky: true, html: '<div class="form2"><label class="f full">What the control does<textarea name="statement" rows="3">' + esc(k.statement) + '</textarea></label><label class="f">Domain<input name="domain" value="' + esc(k.domain || '') + '"></label><label class="f">Type<input name="ctype" value="' + esc(k.ctype || '') + '"></label><label class="f full">Owner<input name="owner" value="' + esc(k.owner || '') + '"></label></div>',
      buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () { var v = {}; $$('[name]', m.el).forEach(function (e) { v[e.name] = e.value; }); return api('PUT', '/api/controls/' + k.id, v).then(function () { SX.toast('Saved', 'ok'); SX.pages.controls(); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] });
  }
})();
