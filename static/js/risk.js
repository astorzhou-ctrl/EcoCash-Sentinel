/* Command Center, Risk Register and Heat Map & Portfolio (BRD phase P1). Ratings always come from the ranked matrix. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, M = null;
  var LV = { Low: ['#2FA84F', '#fff'], Medium: ['#FFE03D', '#3A3200'], Significant: ['#FDB022', '#3A2600'], High: ['#EF2B2B', '#fff'] };
  var LEVELS = ['High', 'Significant', 'Medium', 'Low'];
  var STAT = { draft: 'Draft', submitted: 'Submitted', reviewed: 'Reviewed', approved: 'Approved', closed: 'Closed' };
  var rf = { q: '', category: '', level: '', status: '', outside: false, assessment: '' };

  function loadMatrix() { return M ? Promise.resolve(M) : api('GET', '/api/matrix').then(function (m) { M = m; return m; }); }
  function lvl(r) { return r >= 21 ? 'High' : r >= 13 ? 'Significant' : r >= 6 ? 'Medium' : 'Low'; }
  function badge(x) { return '<span class="badge" style="background:' + LV[x.level][0] + ';color:' + LV[x.level][1] + '">' + x.level + ' (' + x.rank + ')</span>'; }
  function rc(x, k) { return x.needs_assessment ? '<span class="badge" style="background:#FFF1B8;color:#7D4A00">Needs assessment</span>' : badge(x[k]); }
  function lvBadge(l, n) { return '<span class="badge" style="background:' + LV[l][0] + ';color:' + LV[l][1] + '">' + esc(l) + (n != null ? ' ' + n : '') + '</span>'; }
  function money(v) { return v == null ? '\u2013' : '$' + Math.round(v).toLocaleString('en-US'); }
  function pct(v) { return v == null ? '\u2013' : Math.round(v * 100) + '%'; }

  // ranked matrix: counts {"l,c": n}, marks [{l,c,t,k}], click enables cell selection, h = cell height
  function matrixHtml(o) {
    o = o || {}; var counts = o.counts || {}, marks = o.marks || [], h = '<div class="mxwrap" style="--mxh:' + (o.h || 58) + 'px"><div class="mxy">LIKELIHOOD</div><div class="mxg">';
    for (var l = 5; l >= 1; l--) {
      h += '<div class="mxl">' + esc(M.likelihood[l - 1]) + '</div>';
      for (var c = 1; c <= 5; c++) {
        var r = M.cells[l + ',' + c], lv = lvl(r), n = counts[l + ',' + c] || 0, ms = marks.filter(function (m) { return m.l === l && m.c === c; });
        h += '<div class="mxc' + (o.click ? ' click' : '') + (o.sel === l + ',' + c ? ' sel' : '') + (ms.length ? ' hl' : '') + '" data-cell="' + l + ',' + c + '" style="background:' + LV[lv][0] + ';color:' + LV[lv][1] + '" title="Likelihood ' + esc(M.likelihood[l - 1]) + ', consequence ' + esc(M.consequence[c - 1]) + ': ' + lv + ' (' + r + ')"><span class="mxn">' + lv + '</span><span class="mxr">' + r + '</span>' + (n ? '<b class="mxk">' + n + '</b>' : '') + ms.map(function (m) { return '<span class="mxm ' + (m.k || '') + '">' + esc(m.t) + '</span>'; }).join('') + '</div>';
      }
    }
    h += '<div></div>' + M.consequence.map(function (x) { return '<div class="mxh">' + esc(x) + '</div>'; }).join('') + '<div></div><div class="mxcap">CONSEQUENCE</div></div></div>';
    return h;
  }
  function legend() { return '<div class="legend">' + M.bands.map(function (b) { return '<span><i style="background:' + LV[b.level][0] + '"></i>' + b.level + ' ' + b.from + '-' + b.to + '</span>'; }).join('') + '</div>'; }
  function bars(rows, total) { // rows [[label, value, color]]
    var mx = Math.max.apply(null, rows.map(function (r) { return r[1]; }).concat([1]));
    return rows.map(function (r) { return '<div class="hrow"><span class="n">' + esc(r[0]) + '</span><div class="bar"><i style="width:' + (r[1] / mx * 100) + '%;background:' + (r[2] || '#1F5FD0') + '"></i></div><b>' + r[1] + '</b></div>'; }).join('');
  }
  function stacked(e) { var t = LEVELS.reduce(function (a, k) { return a + e[k]; }, 0) || 1; return '<div class="bar" style="height:14px">' + LEVELS.map(function (k) { return e[k] ? '<i style="width:' + e[k] / t * 100 + '%;background:' + LV[k][0] + '" title="' + k + ': ' + e[k] + '"></i>' : ''; }).join('') + '</div>'; }
  function head(title, extra) { return SX.head('Sentinel', title, '#4C5FD5', extra); }

  SX.riskUI = { matrixHtml: matrixHtml, badge: badge, lvBadge: lvBadge, legend: legend, loadMatrix: loadMatrix, money: money, pct: pct, rc: rc };

  // ============================================================ Command Center
  SX.pages.command = function () {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    Promise.all([api('GET', '/api/command'), loadMatrix()]).then(function (r) {
      var d = r[0], h = SX.head('Command &rsaquo; Command Center', 'Command Center', '#4C5FD5', '<span class="muted small">Residual ratings on the ranked matrix &middot; your data scope</span>');
      if (!d.total) {
        h += '<div class="card" style="text-align:center;padding:40px"><h3>' + (d.unassessed ? d.unassessed + ' risks are waiting for a real assessment' : 'No risks in view yet') + '</h3><p class="muted">' + (d.unassessed ? 'Imported risks carry a placeholder rating, so they are kept out of the heat map until an owner rates them. Open the Risk Register to assess them.' : 'The Command Center fills in as soon as risks are in the register.') + '</p>' +
          (SX.can('risk_register', 'create') ? '<a class="btn p" style="--c:#1F5FD0" href="#/m/risk_register">Open the Risk Register</a> <button class="btn" id="load-sample">Load 14 sample risks to explore</button>' : '') + '</div>';
        main.innerHTML = h; var b = $('#load-sample'); if (b) b.addEventListener('click', function () { api('POST', '/api/risks/sample').then(function () { SX.toast('Sample risks loaded', 'ok'); SX.pages.command(); }, function (e) { SX.toast(e.message, 'bad'); }); });
        return;
      }
      var k = function (l, v, c, sub, href) { return '<div class="card kpi s2" style="--c:' + c + '"><div class="l">' + l + '</div><div class="v">' + v + '</div><div class="d">' + (href ? '<a href="' + href + '">' + sub + '</a>' : sub) + '</div></div>'; };
      h += '<div class="grid">' + k('Risks assessed', d.total, '#4C5FD5', d.unassessed ? d.unassessed + ' still need assessment' : d.draft + ' in draft', '#/m/risk_register') + k('High', d.residual.High, '#EF2B2B', 'residual rating', '#/m/heat_map_portfolio') + k('Significant', d.residual.Significant, '#FDB022', 'residual rating', '#/m/heat_map_portfolio') +
        k('Outside appetite', d.outside_appetite, d.outside_appetite ? '#E0474C' : '#2FA84F', 'view them', '#/m/risk_register') + k('Awaiting decision', d.awaiting_review + d.awaiting_approval, '#F0A04B', d.awaiting_review + ' review &middot; ' + d.awaiting_approval + ' approval') + k('Board decisions', d.needs_board, '#7B5CD6', 'recorded as required');
      h += '<div class="card s5" style="grid-column:span 5"><h3>Residual heat map</h3>' + matrixHtml({ counts: d.cells, h: 52 }) + legend() + '</div>';
      h += '<div class="card s7" style="grid-column:span 7"><h3>High and Significant risks over time</h3><div id="trend"></div></div>';
      h += '<div class="card s6"><h3>Top five risks</h3><table class="t"><tr><th>Ref</th><th>Risk</th><th>Owner</th><th>Residual</th></tr>' + d.top.map(function (t) { return '<tr><td><b>' + esc(t.ref) + '</b></td><td>' + (SX.can('risk_register', 'view') ? '<a href="#/m/risk_register/' + t.id + '">' + esc(t.title) + '</a>' : esc(t.title)) + (t.outside ? ' <span class="tag">outside appetite</span>' : '') + '</td><td>' + esc(t.owner_name || '') + '</td><td>' + badge(t.residual) + '</td></tr>'; }).join('') + '</table></div>';
      h += '<div class="card s3"><h3>Risks by category</h3>' + bars(d.by_category.map(function (x) { return [x[0], x[1], '#2F6FD6']; })) + '</div>';
      h += '<div class="card s3"><h3>Needs attention</h3><ul class="list" style="font-size:12.5px"><li><b>' + d.outside_appetite + '</b> outside appetite</li><li><b>' + d.incomplete + '</b> missing owner, cause, treatment or date</li><li><b>' + d.awaiting_review + '</b> waiting for review</li><li><b>' + d.awaiting_approval + '</b> waiting for approval</li><li><b>' + d.needs_board + '</b> need a Board decision on file</li>' + (d.unassessed ? '<li><b>' + d.unassessed + '</b> need a real assessment (imported placeholders)</li>' : '') + '</ul>' +
        (d.assurance.loa != null ? '<p class="small muted" style="margin:8px 0 0">Portfolio assurance (LoA): <b>' + pct(d.assurance.loa) + '</b> on ' + money(d.assurance.emv_i) + ' exposure</p>' : '') + '</div>';
      main.innerHTML = h + '</div>';
      $$('[data-cell]', main).forEach(function (c) { c.addEventListener('click', function () { location.hash = '#/m/heat_map_portfolio'; }); });
      var t = d.trend, box = $('#trend');
      if (t.length < 2) box.innerHTML = '<div class="empty">The trend needs at least two snapshots. A Head of Risk takes one at each quarter-end in Heat Map &amp; Portfolio (' + t.length + ' so far).</div>';
      else {
        var W = 560, H = 190, mx = Math.max.apply(null, t.map(function (x) { return x.high_sig; }).concat([1])) * 1.2, X = function (i) { return 36 + (W - 50) * i / (t.length - 1); }, Y = function (v) { return 14 + (H - 44) * (1 - v / mx); };
        box.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%">' + [0, .5, 1].map(function (f) { return '<line x1="36" x2="' + (W - 14) + '" y1="' + Y(mx * f) + '" y2="' + Y(mx * f) + '" stroke="#E6ECF4"/><text x="30" y="' + (Y(mx * f) + 3) + '" font-size="9" text-anchor="end" fill="#8896A8">' + Math.round(mx * f) + '</text>'; }).join('') +
          [['high_sig', '#EF2B2B'], ['outside', '#7B5CD6']].map(function (s) { return '<polyline fill="none" stroke="' + s[1] + '" stroke-width="2.4" points="' + t.map(function (x, i) { return X(i) + ',' + Y(x[s[0]]); }).join(' ') + '"/>' + t.map(function (x, i) { return '<circle cx="' + X(i) + '" cy="' + Y(x[s[0]]) + '" r="3" fill="' + s[1] + '"/>'; }).join(''); }).join('') +
          t.map(function (x, i) { return '<text x="' + X(i) + '" y="' + (H - 8) + '" font-size="9" text-anchor="middle" fill="#8896A8">' + esc(x.label.slice(0, 12)) + '</text>'; }).join('') + '</svg><div class="legend"><span><i style="background:#EF2B2B"></i>High + Significant</span><span><i style="background:#7B5CD6"></i>Outside appetite</span></div>';
      }
    });
  };

  // ============================================================ Risk Register
  SX.pages.risk = function (id) { if (id === 'assessment') return SX.regAssessment(); if (['strategic', 'integration', 'aggregation', 'key', 'sheets', 'quality'].indexOf(id) >= 0) return SX.regTab(id); return id && id !== 'all' ? detail(+id) : list(); };

  function list() {
    var main = $('#main');
    Promise.all([loadMatrix(), api('GET', '/api/risks?' + ['q', 'category', 'level', 'status'].map(function (k) { return k + '=' + encodeURIComponent(rf[k]); }).join('&') + '&outside=' + (rf.outside ? 1 : 0) + '&assessment=' + rf.assessment)]).then(function (r) {
      var rows = r[1].risks, can = function (a) { return SX.can('risk_register', a); };
      var h = SX.head('Risk &rsaquo; Risk Register', 'Risk Register', '#2F6FD6', (can('export') ? '<a class="btn" href="/api/risks/export.csv">Download Excel (CSV)</a> ' : '') + '<button class="btn" id="wbm">Saved workbooks</button> ' + (rows.some(function (x) { return x.is_sample; }) && can('delete') ? '<button class="btn" id="rmsample" style="color:#C62828">Remove sample risks</button>' : '') + (can('create') ? '<button class="btn" id="imp">Import workbook</button><button class="btn p" id="add" style="--c:#2F6FD6">+ Add risk</button>' : ''));
      h += SX.tabs('m/risk_register', SX.REG_TABS, 'all', '#2F6FD6');
      if (r[1].needs_assessment) h += '<div class="alert warn" style="margin-bottom:10px"><b>' + r[1].needs_assessment + ' risks need a real assessment.</b> They carry the imported placeholder rating, so the heat map and Command Center leave them out until an owner rates them. <a href="#" id="onlyna">' + (rf.assessment ? 'Show all risks' : 'Show only these') + '</a></div>';
      h += '<div class="card"><div class="toolbar"><input type="search" id="q" placeholder="Search reference, title, owner" value="' + esc(rf.q) + '"><select id="cat" style="width:150px"><option value="">All categories</option>' + M.categories.map(function (c) { return '<option' + (rf.category === c ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') + '</select><select id="st" style="width:130px"><option value="">All statuses</option>' + M.statuses.map(function (s) { return '<option value="' + s + '"' + (rf.status === s ? ' selected' : '') + '>' + STAT[s] + '</option>'; }).join('') + '</select>' +
        '<span>' + [''].concat(LEVELS).map(function (l) { return '<span class="chip' + (rf.level === l ? ' on' : '') + '" style="--c:#2F6FD6" data-lv="' + l + '">' + (l || 'All levels') + '</span>'; }).join('') + '<span class="chip' + (rf.outside ? ' on' : '') + '" style="--c:#E0474C" id="out">Outside appetite</span></span></div>';
      h += rows.length ? '<table class="t"><tr><th>Ref</th><th>Risk</th><th>Category</th><th>Owner</th><th>Inherent</th><th>Residual</th><th>Status</th><th>Assurance</th></tr>' + rows.map(function (x) {
        return '<tr style="cursor:pointer" data-open="' + x.id + '"><td><b>' + esc(x.ref) + '</b></td><td><b>' + esc(x.title) + '</b>' + (x.source_ref ? ' <span class="tag">' + esc(x.source_ref) + '</span>' : '') + (x.is_sample ? ' <span class="tag">sample</span>' : '') + (x.missing.length ? '<div class="small" style="color:#B36B00">missing: ' + esc(x.missing.join(', ')) + '</div>' : '') + '</td><td>' + esc(x.category) + '</td><td>' + esc(x.owner_name || '\u2013') + '</td><td>' + rc(x, 'inherent') + '</td><td>' + rc(x, 'residual') + (x.outside_appetite && !x.needs_assessment ? '<div class="small red">outside appetite</div>' : '') + '</td><td><span class="tag">' + STAT[x.status] + '</span>' + (x.needs_board ? '<span class="tag">Board</span>' : '') + '</td><td>' + (x.loa == null ? '<span class="muted">no controls</span>' : pct(x.loa) + ' <span class="muted small">(' + x.controls + ' ctl)</span>') + '</td></tr>';
      }).join('') + '</table><div class="muted small" style="margin-top:8px">' + rows.length + ' risks, highest residual rating first.</div>' : '<div class="empty">No risks match.' + (can('create') ? ' <button class="btn" id="load-sample">Load 14 sample risks</button>' : '') + '</div>';
      main.innerHTML = h + '</div>';
      var t, go = function () { rf.q = $('#q').value; rf.category = $('#cat').value; rf.status = $('#st').value; list(); };
      $('#q').addEventListener('input', function () { clearTimeout(t); t = setTimeout(go, 250); }); $('#cat').addEventListener('change', go); $('#st').addEventListener('change', go);
      $$('[data-lv]', main).forEach(function (c) { c.addEventListener('click', function () { rf.level = c.dataset.lv; list(); }); }); $('#out').addEventListener('click', function () { rf.outside = !rf.outside; list(); });
      $$('[data-open]', main).forEach(function (tr) { tr.addEventListener('click', function () { location.hash = '#/m/risk_register/' + tr.dataset.open; }); });
      var a = $('#add'); if (a) a.addEventListener('click', function () { riskForm(null); });
      var im = $('#imp'); if (im) im.addEventListener('click', function () { SX.regImportDialog(list); }); var wb = $('#wbm'); if (wb) wb.addEventListener('click', function () { SX.wbManager(list); });
      var rs = $('#rmsample'); if (rs) rs.addEventListener('click', function () {
        SX.modal({ title: 'Remove the sample risks?', html: '<p>This permanently deletes the illustrative sample risks (marked "sample") and their controls so they do not mix with your real data. Your own risks are not touched.</p>', buttons: [{ label: 'Cancel' }, { label: 'Remove sample risks', cls: 'd', onClick: function () {
          return api('DELETE', '/api/risks/sample').then(function (d) { SX.toast(d.removed + ' sample risks removed', 'ok'); list(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
        } }] });
      });
      var na = $('#onlyna'); if (na) na.addEventListener('click', function (e) { e.preventDefault(); rf.assessment = rf.assessment ? '' : 'needs'; list(); });
      var b = $('#load-sample'); if (b) b.addEventListener('click', function () { api('POST', '/api/risks/sample').then(function () { SX.toast('Sample risks loaded. Remove them any time with the Remove sample risks button in the Risk Register.', 'ok'); list(); }, function (e) { SX.toast(e.message, 'bad'); }); });
    });
  }

  function importDialog() {
    var m = SX.modal({ title: 'Import the risk assessment workbook', wide: true, sticky: true, html: '<p class="muted small" style="margin-top:0">Choose the ISMS and BCMS workbook (.xlsx): one sheet per risk with its controls, owners, effectiveness (ICE) and exposure. Nothing is saved until you press Import. Risks already imported (same ISMS or BCMS number) are skipped, so it is safe to run twice. Imported risks get a placeholder 5 x 5 rating and are marked <b>Needs assessment</b>.</p><input type="file" id="wbf" accept=".xlsx"><div id="wbr" style="margin-top:12px"></div>', buttons: [{ label: 'Close' }, { label: 'Import', cls: 'p', onClick: function () {
      var f = m.$('#wbf').files[0]; if (!f) { SX.toast('Choose the workbook first', 'bad'); return false; }
      return send(f, 0).then(function (d) { SX.toast('Imported ' + d.imported + ' risks with ' + d.controls + ' controls', 'ok'); list(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
    function send(file, dry) {
      return file.arrayBuffer().then(function (buf) { return fetch('/api/risks/import?dry=' + dry, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Sentinel': '1' }, credentials: 'same-origin', body: buf }); })
        .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.message || 'The import failed'); return d; }); });
    }
    m.$('#wbf').addEventListener('change', function () {
      var f = this.files[0], box = m.$('#wbr'); if (!f) return; box.innerHTML = '<span class="muted">Checking the workbook...</span>';
      send(f, 1).then(function (d) {
        box.innerHTML = '<div class="alert info"><b>' + d.to_import + ' risks</b> will be imported (' + (d.systems.ISMS || 0) + ' ISMS, ' + (d.systems.BCMS || 0) + ' BCMS) with <b>' + d.controls.toLocaleString('en-US') + ' controls</b> and exposure of <b>' + money(d.emv_i) + '</b>.' + (d.skipped.length ? ' ' + d.skipped.length + ' already in the register will be skipped.' : '') + '</div>' + (d.warnings.length ? '<div class="alert warn"><b>Please note</b><ul style="margin:4px 0 0 18px">' + d.warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></div>' : '');
      }, function (e) { box.innerHTML = '<div class="alert bad">' + esc(e.message) + '</div>'; });
    });
  }

  function ratingPicker(prefix, l, c, optional) {
    var sel = function (n, v, labels) { return '<select name="' + prefix + '_' + n + '">' + (optional ? '<option value="">-</option>' : '') + labels.map(function (x, i) { return '<option value="' + (i + 1) + '"' + (v === i + 1 ? ' selected' : '') + '>' + (i + 1) + ' ' + esc(x) + '</option>'; }).join('') + '</select>'; };
    return '<div class="form2"><label class="f">Likelihood' + sel('l', l, M.likelihood) + '</label><label class="f">Consequence' + sel('c', c, M.consequence) + '</label></div>';
  }
  function riskForm(r) {
    var edit = !!r;
    api('GET', '/api/risks/owners').then(function (o) {
      var v = function (k) { return esc(r && r[k] != null ? r[k] : ''); }, ri = r ? r.inherent : { l: 3, c: 3 }, rr = r ? r.residual : { l: 3, c: 3 }, rt = r && r.target ? r.target : { l: '', c: '' };
      var h = '<form id="rform"><div class="form2"><label class="f full">Title *<input type="text" name="title" value="' + v('title') + '"></label><label class="f">Category *<select name="category">' + M.categories.map(function (c) { return '<option' + ((r ? r.category : 'Operational') === c ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') + '</select></label>' +
        '<label class="f">Owner<input type="text" name="owner_name" list="owners" value="' + v('owner_name') + '" placeholder="Type a name or role"><datalist id="owners">' + o.owners.map(function (u) { return '<option value="' + esc(u.name) + '">'; }).join('') + '</datalist></label>' +
        '<label class="f">Function<input type="text" name="function" value="' + v('function') + '"></label><label class="f">Strategic objective<input type="text" name="objective" value="' + v('objective') + '"></label><label class="f">Subcategory<input type="text" name="subcategory" value="' + v('subcategory') + '"></label><label class="f">Delegate (while the owner is away)<input type="text" name="delegate_name" list="owners" value="' + v('delegate_name') + '"></label><label class="f full">Description<textarea name="description" rows="2">' + v('description') + '</textarea></label>' +
        '<label class="f">Root cause<textarea name="root_cause" rows="2">' + v('root_cause') + '</textarea></label><label class="f">Implication<textarea name="implication" rows="2">' + v('implication') + '</textarea></label><label class="f full">Treatment (mitigation plan)<textarea name="treatment" rows="2">' + v('treatment') + '</textarea></label>' +
        '<label class="f">Action date<input type="date" name="action_date" value="' + v('action_date') + '"></label><label class="f">Review date<input type="date" name="review_date" value="' + v('review_date') + '"></label><label class="f">Estimated value at risk, EMV-i ($)<input type="number" min="0" step="1" name="emv_i" value="' + v('emv_i') + '"></label><div></div></div>' +
        '<div class="form2" style="margin-top:4px"><div><b>Inherent rating</b> <span id="p-inh"></span>' + ratingPicker('inh', ri.l, ri.c) + '</div><div><b>Residual rating</b> <span id="p-res"></span>' + ratingPicker('res', rr.l, rr.c) + '</div><div><b>Target rating (optional)</b> <span id="p-tgt"></span>' + ratingPicker('tgt', rt.l, rt.c, true) + '</div>' +
        (edit ? '<label class="f">Reason for change <span class="muted">(needed if the residual moves two or more levels)</span><textarea name="reason" rows="2"></textarea></label>' : '<div></div>') + '</div></form>';
      var m = SX.modal({ title: edit ? 'Edit ' + r.ref : 'Add risk', wide: true, sticky: true, html: h, buttons: [{ label: 'Cancel' }, { label: edit ? 'Save changes' : 'Create risk', cls: 'p', onClick: function () {
        var f = m.$('#rform'), g = function (n) { return f[n].value; }, body = { title: g('title'), category: g('category'), owner_name: g('owner_name'), function: g('function'), objective: g('objective'), subcategory: g('subcategory'), delegate_name: g('delegate_name'), description: g('description'), root_cause: g('root_cause'), implication: g('implication'), treatment: g('treatment'),
          action_date: g('action_date'), review_date: g('review_date'), emv_i: g('emv_i'), inh_l: g('inh_l'), inh_c: g('inh_c'), res_l: g('res_l'), res_c: g('res_c'), tgt_l: g('tgt_l'), tgt_c: g('tgt_c') };
        if (edit) body.reason = g('reason');
        return api(edit ? 'PUT' : 'POST', '/api/risks' + (edit ? '/' + r.id : ''), body).then(function (d) { SX.toast(edit ? 'Saved' : 'Risk ' + d.risk.ref + ' created', 'ok'); if (edit) detail(r.id); else location.hash = '#/m/risk_register/' + d.risk.id; }, function (e) { SX.toast(e.message, 'bad'); return false; });
      } }] });
      var f = m.$('#rform'), touched = edit;
      var show = function () {
        [['inh', 'p-inh'], ['res', 'p-res'], ['tgt', 'p-tgt']].forEach(function (p) { var l = +f[p[0] + '_l'].value, c = +f[p[0] + '_c'].value; m.$('#' + p[1]).innerHTML = l && c ? badge({ level: lvl(M.cells[l + ',' + c]), rank: M.cells[l + ',' + c] }) : '<span class="muted small">none</span>'; });
      };
      ['res_l', 'res_c'].forEach(function (n) { f[n].addEventListener('change', function () { touched = true; }); });
      ['inh_l', 'inh_c'].forEach(function (n) { f[n].addEventListener('change', function () { if (!touched) { f.res_l.value = f.inh_l.value; f.res_c.value = f.inh_c.value; } show(); }); });
      $$('select', f).forEach(function (s) { s.addEventListener('change', show); }); show();
    });
  }

  function detail(id) {
    var main = $('#main');
    Promise.all([loadMatrix(), api('GET', '/api/risks/' + id)]).then(function (r) {
      var d = r[1], can = d.can, i = d.inherent, s = d.residual, sg = d.suggestion;
      var flow = ['draft', 'submitted', 'reviewed', 'approved', 'closed'], at = flow.indexOf(d.status);
      var h = SX.head('Risk &rsaquo; <a href="#/m/risk_register">Risk Register</a> &rsaquo; ' + esc(d.ref), d.ref + '  ' + d.title, '#2F6FD6', (can.edit ? '<button class="btn" id="edit">Edit</button>' : '') + (can.delete ? '<button class="btn" id="del" style="color:#C62828">Delete</button>' : ''));
      h += '<div class="steps">' + flow.map(function (f, k) { return '<span class="' + (k < at ? 'done' : k === at ? 'cur' : '') + '">' + STAT[f] + '</span>'; }).join('') + '</div><div class="wf" id="wf"></div>';
      h += '<div class="grid" style="margin-top:12px"><div class="card s8"><h3>Details</h3><dl class="kv"><dt>Category</dt><dd>' + esc(d.category) + (d.subcategory ? ' / ' + esc(d.subcategory) : '') + '</dd>' + (d.system ? '<dt>Management system</dt><dd>' + esc(d.system) + ' &middot; workbook ref ' + esc(d.source_ref || '') + '</dd><dt>Strategic objective</dt><dd>' + esc(d.strategic_objective || '\u2013') + '</dd>' : '') + (d.delegate_name ? '<dt>Delegate</dt><dd>' + esc(d.delegate_name) + '</dd>' : '') + '<dt>Owner</dt><dd>' + esc(d.owner_name || '\u2013') + '</dd><dt>Function</dt><dd>' + esc(d.function || '\u2013') + '</dd><dt>Objective</dt><dd>' + esc(d.objective || '\u2013') + '</dd><dt>Description</dt><dd>' + esc(d.description || '\u2013') + '</dd><dt>Root cause</dt><dd>' + esc(d.root_cause || '\u2013') + '</dd><dt>Implication</dt><dd>' + esc(d.implication || '\u2013') + '</dd><dt>Treatment</dt><dd>' + esc(d.treatment || '\u2013') + '</dd><dt>Action / review date</dt><dd>' + SX.fmt(d.action_date, true) + ' / ' + SX.fmt(d.review_date, true) + '</dd><dt>EMV-i</dt><dd>' + money(d.emv_i) + '</dd></dl>' +
        (d.missing.length ? '<div class="alert warn" style="margin:10px 0 0">Complete before submitting: ' + esc(d.missing.join(', ')) + '.</div>' : '') + '</div>';
      h += '<div class="card s4"><h3>Rating</h3>' + (d.needs_assessment ? '<div class="alert warn" style="margin-bottom:8px"><b>Needs assessment.</b> The 5 x 5 rating is an imported placeholder. Press Edit and choose the real likelihood and consequence.</div>' : '') + '<div class="row" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">Inherent ' + badge(i) + ' &rarr; Residual ' + badge(s) + '</div>' + (d.outside_appetite ? '<div class="alert bad" style="margin:8px 0">Outside appetite for ' + esc(d.category) + '.</div>' : '') + '<div style="margin-top:8px">' + matrixHtml({ h: 34, marks: [{ l: i.l, c: i.c, t: 'inh' }, { l: s.l, c: s.c, t: 'res', k: 'res' }].concat(d.target ? [{ l: d.target.l, c: d.target.c, t: 'tgt', k: 'res' }] : []) }) + '</div><p class="small muted" style="margin:6px 0 0">' + M.bands.filter(function (b) { return b.level === s.level; })[0].response + '</p></div>';
      h += '<div class="card s8"><div class="toolbar"><h3 style="margin:0">Controls</h3><div style="flex:1"></div>' + (can.edit ? '<button class="btn sm p" id="addc" style="--c:#17A2B8">+ Add control</button>' : '') + '</div>' + (d.controls.length ? '<table class="t"><tr><th>Ref</th><th>Control</th><th>Type</th><th>Domain</th><th>ICE</th><th>Policy class</th><th>Result</th><th></th></tr>' + d.controls.map(function (c) { return '<tr><td>' + esc(c.ref || '') + '</td><td>' + esc(c.statement) + '</td><td>' + esc(c.ctype || '\u2013') + '</td><td>' + esc(c.domain || '\u2013') + '</td><td>' + (c.ice == null ? '\u2013' : c.ice.toFixed(1)) + '</td><td>' + (c.policy_class ? '<span class="small">' + esc(c.policy_class.label) + ' &middot; <b>' + esc(c.policy_class.action) + '</b></span>' : '\u2013') + '</td><td>' + esc(c.result || '\u2013') + '</td><td style="text-align:right;white-space:nowrap">' + (can.edit ? '<button class="btn sm" data-ec="' + c.id + '">Edit</button> <button class="btn sm" data-dc="' + c.id + '">Remove</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '<div class="empty">No controls linked yet. Add the controls that reduce this risk, with their effectiveness (ICE: 0.1 strong to 1.0 none).</div>') + '</div>';
      h += '<div class="card s4"><h3>Assurance</h3><dl class="kv" style="grid-template-columns:110px 1fr"><dt>Controls</dt><dd>' + d.controls.length + '</dd><dt>Average ICE</dt><dd>' + (d.avg_ice == null ? '\u2013' : d.avg_ice) + '</dd><dt>Level of assurance</dt><dd><b>' + pct(d.loa) + '</b></dd><dt>Level of risk</dt><dd>' + pct(d.lor) + '</dd><dt>EMV-r</dt><dd>' + money(d.emv_r) + '</dd></dl>' +
        '<div class="sugg" style="margin-top:10px"><b>Suggested residual:</b> ' + badge(sg.rating) + '<br><span class="muted">' + sg.likelihood_steps + ' step(s) off likelihood, ' + sg.consequence_steps + ' off consequence, from ' + esc(sg.basis) + '. The owner confirms; nothing changes automatically.</span>' + (can.edit && (sg.l !== s.l || sg.c !== s.c) ? '<div style="margin-top:6px"><button class="btn sm" id="apply">Use this suggestion</button></div>' : '') + '</div></div>';
      h += '<div class="card s12"><h3>History</h3><div class="timeline">' + d.history.map(function (x) { var ch = Object.keys(x.changes).map(function (k) { var v = x.changes[k]; return esc(k.replace(/_/g, ' ')) + ': ' + esc(v[0] == null ? '\u2013' : v[0]) + ' &rarr; ' + esc(v[1] == null ? '\u2013' : v[1]); }).join('; '); return '<div class="e"><b class="small">' + esc(x.action) + '</b> <span class="muted small">' + esc(x.username) + ' &middot; ' + SX.fmt(x.ts) + '</span><div class="small muted">' + ch + '</div></div>'; }).join('') + '</div></div></div>';
      main.innerHTML = h;
      var wf = $('#wf'), btn = function (to, label, cls) { return '<button class="btn ' + (cls || '') + '" data-to="' + to + '" style="--c:#1F5FD0">' + label + '</button>'; };
      var next = { draft: [['submitted', 'Submit for review', 'p']], submitted: [['reviewed', 'Mark as reviewed', 'p'], ['draft', 'Return to draft']], reviewed: [['approved', 'Approve', 'p'], ['draft', 'Return to draft']], approved: [['closed', 'Close the risk', 'p'], ['draft', 'Reopen as draft']], closed: [['draft', 'Reopen as draft']] }[d.status];
      wf.innerHTML = next.map(function (n) { return btn(n[0], n[1], n[2]); }).join('') + (d.needs_board ? '<span class="tag" style="align-self:center">Board decision on file</span>' : '');
      $$('[data-to]', wf).forEach(function (b) { b.addEventListener('click', function () { transition(d, b.dataset.to, b.textContent); }); });
      var e = $('#edit'); if (e) e.addEventListener('click', function () { riskForm(d); });
      var del = $('#del'); if (del) del.addEventListener('click', function () { deleteRisk(d); });
      var a = $('#addc'); if (a) a.addEventListener('click', function () { controlForm(d, null); });
      $$('[data-ec]', main).forEach(function (b) { b.addEventListener('click', function () { controlForm(d, d.controls.filter(function (c) { return c.id === +b.dataset.ec; })[0]); }); });
      $$('[data-dc]', main).forEach(function (b) { b.addEventListener('click', function () { api('DELETE', '/api/risks/' + d.id + '/controls/' + b.dataset.dc).then(function () { SX.toast('Control removed', 'ok'); detail(d.id); }, function (er) { SX.toast(er.message, 'bad'); }); }); });
      var ap = $('#apply'); if (ap) ap.addEventListener('click', function () { var copy = JSON.parse(JSON.stringify(d)); copy.residual = { l: sg.l, c: sg.c }; riskForm(copy); });
    });
  }
  function transition(d, to, label) {
    var need = to === 'draft' || to === 'approved';
    var m = SX.modal({ title: label, html: '<p class="muted small" style="margin-top:0">' + (to === 'approved' ? 'If the residual rating is High or outside appetite, record the Board decision or its reference here (at least 10 characters).' : to === 'draft' ? 'Say why it goes back to draft.' : 'Add a comment if useful.') + '</p><label class="f">Comment' + (need ? ' *' : '') + '<textarea id="cm" rows="3"></textarea></label>', buttons: [{ label: 'Cancel' }, { label: 'Confirm', cls: 'p', onClick: function () {
      return api('POST', '/api/risks/' + d.id + '/status', { to: to, comment: m.$('#cm').value }).then(function () { SX.toast('Status updated', 'ok'); detail(d.id); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  function deleteRisk(d) {
    var m = SX.modal({ title: 'Delete ' + d.ref + '?', html: '<p>It moves to the Recycle Bin and an administrator can restore it for 90 days.</p><label class="f">Reason (required)<textarea id="rs" rows="2"></textarea></label>', buttons: [{ label: 'Cancel' }, { label: 'Move to Recycle Bin', cls: 'd', onClick: function () {
      return api('DELETE', '/api/risks/' + d.id, { reason: m.$('#rs').value }).then(function () { SX.toast('Moved to the Recycle Bin', 'ok'); location.hash = '#/m/risk_register'; }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  function controlForm(d, c) {
    var o = function (arr, v) { return '<option value="">-</option>' + arr.map(function (x) { return '<option' + (v === x ? ' selected' : '') + '>' + esc(x) + '</option>'; }).join(''); };
    var v = function (k) { return esc(c && c[k] != null ? c[k] : ''); };
    var m = SX.modal({ title: c ? 'Edit control' : 'Add control', wide: true, sticky: true, html: '<form id="cf" class="form2"><label class="f">Reference<input type="text" name="ref" value="' + v('ref') + '"></label><label class="f">Owner<input type="text" name="owner" value="' + v('owner') + '"></label><label class="f full">Control statement *<textarea name="statement" rows="2">' + v('statement') + '</textarea></label>' +
      '<label class="f">Type<select name="ctype">' + o(M.ctypes, c && c.ctype) + '</select></label><label class="f">P2ST2 domain<select name="domain">' + o(M.domains, c && c.domain) + '</select></label><label class="f">Effectiveness ICE (0.1 strong to 1.0 none)<input type="number" step="0.1" min="0.1" max="1" name="ice" value="' + v('ice') + '"></label><label class="f">Test result<select name="result">' + o(M.results, c && c.result) + '</select></label><label class="f">Last test date<input type="date" name="last_test" value="' + v('last_test') + '"></label></form>', buttons: [{ label: 'Cancel' }, { label: 'Save control', cls: 'p', onClick: function () {
      var f = m.$('#cf'), body = {}; ['ref', 'owner', 'statement', 'ctype', 'domain', 'ice', 'result', 'last_test'].forEach(function (k) { body[k] = f[k].value; });
      return api(c ? 'PUT' : 'POST', '/api/risks/' + d.id + '/controls' + (c ? '/' + c.id : ''), body).then(function () { SX.toast('Control saved', 'ok'); detail(d.id); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }

  // ============================================================ Heat Map & Portfolio
  var hcat = '', hsel = null;
  SX.pages.heatmap = function () {
    var main = $('#main');
    Promise.all([loadMatrix(), api('GET', '/api/heatmap' + (hcat ? '?category=' + encodeURIComponent(hcat) : '')), api('GET', '/api/portfolio')]).then(function (r) {
      var hm = r[1], p = r[2], maps = hm.maps, counts = function (b) { var o = {}; Object.keys(maps[b].cells).forEach(function (k) { o[k] = maps[b].cells[k].count; }); return o; };
      var hasT = Object.keys(maps.target.cells).length > 0 && p.total;
      var h = SX.head('Risk &rsaquo; Heat Map &amp; Portfolio', 'Heat Map & Portfolio', '#2F6FD6', '<select id="hc" style="width:170px"><option value="">All categories</option>' + M.categories.map(function (c) { return '<option' + (hcat === c ? ' selected' : '') + '>' + esc(c) + '</option>'; }).join('') + '</select>' + (SX.can('risk_register', 'export') ? '<a class="btn" href="/api/risks/export.csv">Download register (CSV)</a>' : ''));
      if (hm.unassessed) h += '<div class="alert info">' + hm.unassessed + ' imported risks still need a real assessment and are not on these maps.</div>';
      if (!hm.total) { main.innerHTML = h + '<div class="card empty">No assessed risks in view yet. Add risks in the Risk Register (or load the sample risks there).</div>'; $('#hc').addEventListener('change', function (e) { hcat = e.target.value; SX.pages.heatmap(); }); return; }
      h += '<div class="grid"><div class="card s6"><h3>Inherent <span class="muted small">before controls</span></h3><div id="m-inh">' + matrixHtml({ counts: counts('inherent'), click: true, h: 54 }) + '</div></div><div class="card s6"><h3>Residual <span class="muted small">after controls</span></h3><div id="m-res">' + matrixHtml({ counts: counts('residual'), click: true, h: 54 }) + '</div></div>';
      h += '<div class="card s12" id="cellbox" hidden></div>';
      h += '<div class="card s4"><h3>Residual by level</h3>' + bars(LEVELS.map(function (l) { return [l, p.residual[l], LV[l][0]]; })) + legend() + '</div>';
      h += '<div class="card s4"><h3>Inherent by level</h3>' + bars(LEVELS.map(function (l) { return [l, p.inherent[l], LV[l][0]]; })) + '</div>';
      h += '<div class="card s4"><h3>By workflow status</h3>' + bars(M.statuses.map(function (s) { return [STAT[s], p.by_status[s], '#4C5FD5']; })) + '</div>';
      h += '<div class="card s6"><h3>Residual level by category</h3>' + p.by_category.map(function (c) { return '<div class="hrow"><span class="n">' + esc(c.category) + '</span><div style="flex:1">' + stacked(c) + '</div><b>' + LEVELS.reduce(function (a, k) { return a + c[k]; }, 0) + '</b></div>'; }).join('') + '</div>';
      h += '<div class="card s6"><div class="toolbar"><h3 style="margin:0">Movement since last snapshot</h3><div style="flex:1"></div>' + (p.can_snapshot ? '<button class="btn sm p" style="--c:#2F6FD6" id="snap">Take snapshot</button>' : '') + '</div>' +
        (p.snapshot ? '<p class="muted small" style="margin-top:0">Compared with "' + esc(p.snapshot.label) + '" (' + SX.fmt(p.snapshot.date, true) + ').</p>' + (p.movement.length ? '<table class="t"><tr><th>Ref</th><th>Risk</th><th>From</th><th>To</th></tr>' + p.movement.map(function (m) { return '<tr><td><b>' + esc(m.ref) + '</b></td><td>' + esc(m.title) + '</td><td>' + (m.from == null ? '<span class="tag">new</span>' : lvBadge(m.from_level, '(' + m.from + ')')) + '</td><td>' + lvBadge(m.to_level, '(' + m.to + ')') + '</td></tr>'; }).join('') + '</table>' : '<div class="empty">No residual rating has moved.</div>') : '<div class="empty">No snapshot yet. A Head of Risk takes one at each quarter-end to track movement and feed the Command Center trend.</div>') + '</div>';
      h += '<div class="card s12"><h3>What each level means</h3><table class="t"><tr><th>Level</th><th>Rank</th><th>Required response</th></tr>' + M.bands.slice().reverse().map(function (b) { return '<tr><td>' + lvBadge(b.level) + '</td><td>' + b.from + ' to ' + b.to + '</td><td>' + esc(b.response) + '</td></tr>'; }).join('') + '</table><p class="muted small">Appetite (GRC Policy 2.4, set in Risk Appetite): target rank ' + M.appetite.target + ', appetite ' + M.appetite.appetite + ', tolerance ' + M.appetite.tolerance + '. A residual rank above the appetite limit can only be retained with Board approval.</p></div></div>';
      main.innerHTML = h;
      $('#hc').addEventListener('change', function (e) { hcat = e.target.value; hsel = null; SX.pages.heatmap(); });
      var pick = function (basis, cell) {
        var e = maps[basis].cells[cell], box = $('#cellbox'); box.hidden = false;
        var rank = M.cells[cell], parts = cell.split(',');
        box.innerHTML = '<h3>' + (basis === 'inherent' ? 'Inherent' : 'Residual') + ': likelihood ' + esc(M.likelihood[+parts[0] - 1]) + ', consequence ' + esc(M.consequence[+parts[1] - 1]) + ' ' + lvBadge(lvl(rank), '(' + rank + ')') + '</h3>' + (e ? '<ul class="list">' + e.risks.map(function (x) { return '<li><b>' + esc(x.ref) + '</b> ' + (SX.can('risk_register', 'view') ? '<a href="#/m/risk_register/' + x.id + '">' + esc(x.title) + '</a>' : esc(x.title)) + '</li>'; }).join('') + (e.count > e.risks.length ? '<li class="muted">and ' + (e.count - e.risks.length) + ' more</li>' : '') + '</ul>' : '<p class="muted">No risks in this cell.</p>');
        $$('.mxc', $('#m-inh')).concat($$('.mxc', $('#m-res'))).forEach(function (c) { c.classList.remove('sel'); });
        $$('.mxc[data-cell="' + cell + '"]', $(basis === 'inherent' ? '#m-inh' : '#m-res')).forEach(function (c) { c.classList.add('sel'); });
      };
      $$('#m-inh .mxc', main).forEach(function (c) { c.addEventListener('click', function () { pick('inherent', c.dataset.cell); }); });
      $$('#m-res .mxc', main).forEach(function (c) { c.addEventListener('click', function () { pick('residual', c.dataset.cell); }); });
      var s = $('#snap'); if (s) s.addEventListener('click', function () {
        var m = SX.modal({ title: 'Take a snapshot', html: '<p class="muted small" style="margin-top:0">Freezes every rating as it stands now, so later movement can be shown. Do this at each quarter-end.</p><label class="f">Label<input type="text" id="sl" value="Quarter-end ' + new Date().toISOString().slice(0, 10) + '"></label>', buttons: [{ label: 'Cancel' }, { label: 'Take snapshot', cls: 'p', onClick: function () {
          return api('POST', '/api/risks/snapshot', { label: m.$('#sl').value }).then(function (d) { SX.toast('Snapshot taken (' + d.count + ' risks)', 'ok'); SX.pages.heatmap(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
        } }] });
      });
    });
  };
})();
