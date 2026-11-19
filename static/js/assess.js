/* Assessment Studio: campaigns, guided scoring by risk owners, review and challenge by the Risk Office (GRC Policy 2.1 to 2.2). */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#2F6FD6', ui = null;
  var ST = { open: ['To assess', '#E3E9F2', '#40536C'], challenged: ['Returned for rework', '#FDB022', '#3A2600'], submitted: ['Awaiting review', '#2F6FD6', '#fff'], approved: ['Approved', '#2FA84F', '#fff'] };
  function chip(s) { var c = ST[s] || ST.open; return '<span class="badge" style="background:' + c[1] + ';color:' + c[2] + '">' + c[0] + '</span>'; }
  function tabs(cur) { return SX.tabs('m/assessment_studio', [['mine', 'My assessments'], ['campaigns', 'Campaigns']], cur === 'campaign' ? 'campaigns' : cur, COLOR); }
  function head(cur, extra) { return SX.head('Risk &rsaquo; Assessment Studio', 'Assessment Studio', COLOR, extra || '') + tabs(cur); }

  SX.pages.assess = function (tab, id) {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    SX.riskUI.loadMatrix().then(function (M) { ui = SX.riskUI; window.__M = M; (tab === 'campaigns' ? campaigns : tab === 'campaign' ? campaign : mine)(id); });
  };
  function ratingText(x) { return ui.badge(x); }

  function mine() {
    var main = $('#main');
    api('GET', '/api/assess/mine').then(function (d) {
      var rows = d.assignments, can = SX.can('assessment_studio', 'approve');
      main.innerHTML = head('mine') + '<div class="card"><p class="muted small" style="margin-top:0">Rate each risk you own: its likelihood and consequence before and after controls, with your evidence. The Risk Office reviews every assessment and may challenge it; only an approved assessment changes the register.</p>' + (rows.length ? '<table class="t"><tr><th>Campaign</th><th>Risk</th><th>Assessor</th><th>Current</th><th>Proposed</th><th>Due</th><th>Status</th><th></th></tr>' + rows.map(function (a) {
        return '<tr><td>' + esc(a.campaign) + '</td><td><b>' + esc(a.risk.ref) + '</b> ' + esc(a.risk.title) + (a.status === 'challenged' && a.review_comment ? '<div class="small" style="color:#B36B00"><b>Reviewer:</b> ' + esc(a.review_comment) + '</div>' : '') + '</td><td>' + esc(a.assessor || '\u2013') + '</td><td>' + (a.risk.needs_assessment ? '<span class="badge" style="background:#FFF1B8;color:#7D4A00">Needs assessment</span>' : ratingText(a.risk.residual)) + '</td><td>' + (a.proposed ? ratingText(a.proposed.residual) : '\u2013') + '</td><td>' + SX.fmt(a.due_date, true) + '</td><td>' + chip(a.status) + '</td><td style="text-align:right">' +
          ((a.status === 'open' || a.status === 'challenged') ? '<button class="btn sm p" style="--c:#2F6FD6" data-as="' + a.id + '">Assess</button>' : a.status === 'submitted' && can ? '<button class="btn sm p" style="--c:#2F6FD6" data-rv="' + a.id + '">Review</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '<div class="empty">Nothing is waiting for you. When the Risk Office launches a campaign, your risks appear here.</div>') + '</div>';
      $$('[data-as]', main).forEach(function (b) { b.addEventListener('click', function () { assessForm(rows.filter(function (a) { return a.id === +b.dataset.as; })[0], mine); }); });
      $$('[data-rv]', main).forEach(function (b) { b.addEventListener('click', function () { reviewForm(rows.filter(function (a) { return a.id === +b.dataset.rv; })[0], mine); }); });
    });
  }

  function picker(prefix, l, c) {
    var M = window.__M, sel = function (n, v, labels) { return '<select name="' + prefix + '_' + n + '">' + labels.map(function (x, i) { return '<option value="' + (i + 1) + '"' + (v === i + 1 ? ' selected' : '') + '>' + (i + 1) + ' ' + esc(x) + '</option>'; }).join('') + '</select>'; };
    return '<div class="form2"><label class="f">Likelihood' + sel('l', l, M.likelihood) + '</label><label class="f">Consequence' + sel('c', c, M.consequence) + '</label></div>';
  }
  function assessForm(a, after) {
    var r = a.risk, p = a.proposed || {}, M = window.__M;
    var prev = r.needs_assessment ? { l: 3, c: 3 } : r.inherent, prevR = r.needs_assessment ? { l: 3, c: 3 } : r.residual;
    var m = SX.modal({ title: 'Assess ' + r.ref, sub: esc(r.title), wide: true, sticky: true, html: '<div class="alert info" style="margin-bottom:10px"><b>' + esc(r.category) + '</b> &middot; owner ' + esc(r.owner_name || '\u2013') + ' &middot; ' + r.controls + ' linked control(s)' + (r.avg_ice != null ? ', average ICE ' + r.avg_ice : '') + (r.needs_assessment ? ' &middot; <b>placeholder rating, please assess for real</b>' : ' &middot; currently inherent ' + r.inherent.level + ' (' + r.inherent.rank + '), residual ' + r.residual.level + ' (' + r.residual.rank + ')') + '</div>' + (a.status === 'challenged' && a.review_comment ? '<div class="alert warn"><b>Returned by ' + esc(a.reviewer || 'the reviewer') + ':</b> ' + esc(a.review_comment) + '</div>' : '') +
      '<form id="af"><div class="form2"><div><b>Inherent (before controls)</b> <span id="pi"></span>' + picker('inh', p.inh_l || prev.l, p.inh_c || prev.c) + '</div><div><b>Residual (after controls)</b> <span id="pr"></span>' + picker('res', p.res_l || prevR.l, p.res_c || prevR.c) + '</div><label class="f full">Rationale * <span class="muted">(evidence, controls tested, incidents, KRIs: at least 10 characters)</span><textarea name="rationale" rows="3">' + esc(a.rationale || '') + '</textarea></label></div></form>', buttons: [{ label: 'Cancel' }, { label: 'Submit for review', cls: 'p', onClick: function () {
      var f = m.$('#af'); return api('POST', '/api/assess/assignments/' + a.id + '/submit', { inh_l: f.inh_l.value, inh_c: f.inh_c.value, res_l: f.res_l.value, res_c: f.res_c.value, rationale: f.rationale.value }).then(function () { SX.toast('Submitted for review', 'ok'); after(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
    var f = m.$('#af'), show = function () { [['inh', 'pi'], ['res', 'pr']].forEach(function (q) { var l = +f[q[0] + '_l'].value, c = +f[q[0] + '_c'].value, k = M.cells[l + ',' + c]; m.$('#' + q[1]).innerHTML = ui.badge({ level: k >= 21 ? 'High' : k >= 13 ? 'Significant' : k >= 6 ? 'Medium' : 'Low', rank: k }); }); };
    $$('select', f).forEach(function (s) { s.addEventListener('change', show); }); show();
  }
  function reviewForm(a, after) {
    var r = a.risk, p = a.proposed;
    var m = SX.modal({ title: 'Review ' + r.ref, sub: esc(r.title), wide: true, sticky: true, html: '<table class="t"><tr><th></th><th>Current in the register</th><th>Proposed by ' + esc(a.assessor || 'the owner') + '</th></tr><tr><td><b>Inherent</b></td><td>' + (r.needs_assessment ? 'placeholder' : ratingText(r.inherent)) + '</td><td>' + ratingText(p.inherent) + '</td></tr><tr><td><b>Residual</b></td><td>' + (r.needs_assessment ? 'placeholder' : ratingText(r.residual)) + '</td><td>' + ratingText(p.residual) + '</td></tr></table>' +
      '<p><b>Rationale:</b> ' + esc(a.rationale || '') + '</p><p class="muted small">' + r.controls + ' control(s)' + (r.avg_ice != null ? ', average ICE ' + r.avg_ice : '') + '. You cannot review an assessment you submitted yourself.</p><label class="f">Comment <span class="muted">(required to challenge)</span><textarea id="rc" rows="2"></textarea></label>', buttons: [{ label: 'Close' }, { label: 'Challenge', onClick: function () {
        return api('POST', '/api/assess/assignments/' + a.id + '/review', { decision: 'challenge', comment: m.$('#rc').value }).then(function () { SX.toast('Returned to the owner', 'ok'); after(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
      } }, { label: 'Approve and apply to the register', cls: 'p', onClick: function () {
        return api('POST', '/api/assess/assignments/' + a.id + '/review', { decision: 'approve', comment: m.$('#rc').value }).then(function (d) { SX.toast('Approved. Residual rating is now ' + d.residual.level + ' (' + d.residual.rank + ')', 'ok'); after(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
      } }] });
  }

  function campaigns() {
    var main = $('#main');
    api('GET', '/api/assess/campaigns').then(function (d) {
      var launch = d.can.create && d.scope_all;
      main.innerHTML = head('campaigns', launch ? '<button class="btn p" id="launch" style="--c:#2F6FD6">+ Launch campaign</button>' : '') + '<div class="card">' + (d.campaigns.length ? '<table class="t"><tr><th>Campaign</th><th>Scope</th><th>Due</th><th style="width:200px">Progress</th><th>Approved</th><th>Awaiting review</th><th>Status</th></tr>' + d.campaigns.map(function (k) {
        return '<tr style="cursor:pointer" data-c="' + k.id + '"><td><b>' + esc(k.name) + '</b><div class="small muted">' + esc(k.description || '') + '</div></td><td>' + esc(k.scope_type.replace('_', ' ')) + (k.scope_value ? ': ' + esc(k.scope_value) : '') + '</td><td>' + SX.fmt(k.due_date, true) + (k.overdue ? ' <span class="badge" style="background:#EF2B2B;color:#fff">overdue</span>' : '') + '</td><td><div class="bar"><i style="width:' + k.completion + '%;background:#2F6FD6"></i></div><span class="small muted">' + k.completion + '% (' + k.counts.approved + ' of ' + k.counts.total + ')</span></td><td>' + k.counts.approved + '</td><td>' + k.counts.submitted + '</td><td><span class="tag">' + esc(k.status) + '</span></td></tr>'; }).join('') + '</table>' : '<div class="empty">No campaigns yet.' + (launch ? ' Launch the first one to have owners assess their risks, for example the imported risks that still need a real rating.' : '') + '</div>') + '</div>';
      $$('[data-c]', main).forEach(function (tr) { tr.addEventListener('click', function () { location.hash = '#/m/assessment_studio/campaign/' + tr.dataset.c; }); });
      var l = $('#launch'); if (l) l.addEventListener('click', function () { launchForm(d); });
    });
  }
  function launchForm(d) {
    var due = new Date(Date.now() + 21 * 864e5).toISOString().slice(0, 10);
    var m = SX.modal({ title: 'Launch an assessment campaign', wide: true, sticky: true, html: '<form id="lf" class="form2"><label class="f full">Campaign name *<input type="text" name="name" value="Q4 2026 risk assessment"></label><label class="f">Which risks?<select name="scope_type"><option value="needs_assessment">Risks that still need a real assessment (imported)</option><option value="all">All open risks</option><option value="category">One category</option><option value="system">One management system</option><option value="function">One function</option></select></label>' +
      '<label class="f">Value (for category, system or function)<input type="text" name="scope_value" list="sv" placeholder="e.g. Fraud, ISMS, Finance"><datalist id="sv">' + d.categories.map(function (c) { return '<option value="' + esc(c) + '">'; }).join('') + ['ISMS', 'BCMS'].map(function (c) { return '<option value="' + c + '">'; }).join('') + d.functions.map(function (c) { return '<option value="' + esc(c) + '">'; }).join('') + '</datalist></label><label class="f">Due date *<input type="date" name="due_date" value="' + due + '"></label><label class="f full">Description<input type="text" name="description"></label></form><p class="muted small">Each risk is assigned to its owner. The Risk Office reviews every submission; owners and reviewers see their work in My assessments and in the Daily Tracker.</p>', buttons: [{ label: 'Cancel' }, { label: 'Launch', cls: 'p', onClick: function () {
      var f = m.$('#lf'); return api('POST', '/api/assess/campaigns', { name: f.name.value, scope_type: f.scope_type.value, scope_value: f.scope_value.value, due_date: f.due_date.value, description: f.description.value }).then(function (r) { SX.toast('Campaign launched for ' + r.assignments + ' risks', 'ok'); location.hash = '#/m/assessment_studio/campaign/' + r.id; }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  function campaign(id) {
    var main = $('#main');
    api('GET', '/api/assess/campaigns/' + id).then(function (d) {
      var k = d.campaign, n = d.counts, can = d.can;
      var tile = function (l, v, c) { return '<div class="card kpi s2" style="--c:' + c + '"><div class="l">' + l + '</div><div class="v">' + v + '</div></div>'; };
      main.innerHTML = head('campaign', (can.approve && k.status === 'open' ? '<button class="btn" id="close">Close campaign</button>' : '') + '<a class="btn" href="#/m/assessment_studio/campaigns">All campaigns</a>') + '<div class="grid"><div class="card s12"><h3 style="margin:0">' + esc(k.name) + ' <span class="tag">' + esc(k.status) + '</span></h3><div class="muted small">' + esc(k.description || '') + ' Due ' + SX.fmt(k.due_date, true) + '</div></div>' +
        tile('Total', n.total, '#4C5FD5') + tile('To assess', n.open, '#8A97A8') + tile('Returned', n.challenged, '#FDB022') + tile('Awaiting review', n.submitted, '#2F6FD6') + tile('Approved', n.approved, '#2FA84F') + tile('Completion', n.total ? Math.round(n.approved / n.total * 100) + '%' : '0%', '#7B5CD6') +
        '<div class="card s4"><h3>Completion by function</h3>' + d.by_function.map(function (f) { var p = f.total ? Math.round(f.approved / f.total * 100) : 0; return '<div class="hrow"><span class="n" style="width:110px">' + esc(f.function) + '</span><div class="bar"><i style="width:' + p + '%;background:#2FA84F"></i></div><b style="width:60px">' + f.approved + '/' + f.total + '</b></div>'; }).join('') + '</div>' +
        '<div class="card s8"><h3>Assessments</h3><div style="max-height:520px;overflow:auto"><table class="t"><tr><th>Risk</th><th>Assessor</th><th>Current</th><th>Proposed</th><th>Status</th><th></th></tr>' + d.assignments.map(function (a) {
          return '<tr><td><b>' + esc(a.risk.ref) + '</b> ' + esc(a.risk.title.slice(0, 70)) + '</td><td>' + esc(a.assessor || '\u2013') + '</td><td>' + (a.risk.needs_assessment ? '<span class="badge" style="background:#FFF1B8;color:#7D4A00">Needs assessment</span>' : ratingText(a.risk.residual)) + '</td><td>' + (a.proposed ? ratingText(a.proposed.residual) : '\u2013') + '</td><td>' + chip(a.status) + '</td><td style="text-align:right">' + (a.status === 'submitted' && can.approve && k.status === 'open' ? '<button class="btn sm p" style="--c:#2F6FD6" data-rv="' + a.id + '">Review</button>' : '') + '</td></tr>'; }).join('') + '</table></div></div></div>';
      $$('[data-rv]', main).forEach(function (b) { b.addEventListener('click', function () { reviewForm(d.assignments.filter(function (a) { return a.id === +b.dataset.rv; })[0], function () { campaign(id); }); }); });
      var c = $('#close'); if (c) c.addEventListener('click', function () { api('POST', '/api/assess/campaigns/' + id + '/close').then(function (r) { SX.toast('Campaign closed: ' + r.approved + ' of ' + r.total + ' approved', 'ok'); campaign(id); }, function (e) { SX.toast(e.message, 'bad'); }); });
    });
  }
})();
