/* Board Hub: decisions on risks above appetite (GRC Policy 2.4), meetings, and frozen report packs (GRC Policy 2.5). */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#4C5FD5', ui = null;
  var DS = { pending: ['Waiting for the Board', '#F9A825', '#3A2600'], approved: ['Approved', '#2FA84F', '#fff'], deferred: ['Deferred', '#8A97A8', '#fff'], rejected: ['Rejected', '#EF2B2B', '#fff'] };
  var BAND = { outside_appetite: ['Outside appetite', '#FDB022', '#3A2600'], outside_tolerance: ['Outside tolerance', '#EF2B2B', '#fff'] };
  function pill(t) { return '<span class="badge" style="background:' + t[1] + ';color:' + t[2] + '">' + esc(t[0]) + '</span>'; }
  function head(cur, extra) { return SX.head('Command &rsaquo; Board Hub', 'Board Hub', COLOR, extra || '') + SX.tabs('m/board_hub', [['decisions', 'Decisions'], ['meetings', 'Meetings'], ['packs', 'Report packs']], cur === 'pack' ? 'packs' : cur, COLOR); }
  function mtitle(m) { return esc(m.title) + (m.meeting_date ? ' (' + SX.fmt(m.meeting_date, true) + ')' : ''); }

  SX.pages.board = function (tab, id) {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    SX.riskUI.loadMatrix().then(function () { ui = SX.riskUI; (tab === 'meetings' ? meetings : tab === 'packs' ? packs : tab === 'pack' ? pack : decisions)(id); });
  };

  function decisions() {
    var main = $('#main');
    api('GET', '/api/board').then(function (d) {
      var can = d.can, asked = {}; d.decisions.forEach(function (x) { if (x.status === 'pending') asked[x.risk_id] = 1; });
      var cand = d.candidates.filter(function (c) { return !asked[c.id]; });
      main.innerHTML = head('decisions') + '<div class="alert info"><b>GRC Policy 2.4.</b> A risk above appetite can only be retained with the approval of the Board, and the approval is time-limited. Request the decision here; a different person records what the Board decided, with the minute reference and an expiry date.</div><div class="grid">' +
        '<div class="card s12"><h3>Risks above appetite without a pending request (' + cand.length + ')</h3>' + (cand.length ? '<table class="t"><tr><th>Ref</th><th>Risk</th><th>Owner</th><th>Residual</th><th>Position</th><th></th></tr>' + cand.map(function (c) { return '<tr><td><b>' + esc(c.ref) + '</b></td><td>' + esc(c.title) + '</td><td>' + esc(c.owner || '\u2013') + '</td><td>' + ui.badge({ level: c.level, rank: c.rank }) + '</td><td>' + pill(BAND[c.band] || BAND.outside_appetite) + '</td><td style="text-align:right">' + (can.create ? '<button class="btn sm p" style="--c:#4C5FD5" data-rq="' + c.id + '">Request Board decision</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '<div class="empty">Nothing above appetite is waiting for a request.</div>') + '</div>' +
        '<div class="card s12"><h3>Decision log</h3>' + (d.decisions.length ? '<table class="t"><tr><th>Risk</th><th>Recommendation</th><th>Meeting</th><th>Status</th><th>Board reference and conditions</th><th></th></tr>' + d.decisions.map(function (x) {
          return '<tr><td><b>' + esc(x.ref) + '</b> ' + esc(x.title) + '<div class="small muted">rank ' + x.rank_at_request + ' at request, ' + x.rank_now + ' now &middot; asked by ' + esc(x.requested_by || '') + ', ' + SX.fmt(x.requested_at, true) + '</div></td><td style="max-width:260px">' + esc(x.recommendation) + '</td><td>' + (x.meeting ? esc(x.meeting.title) : '\u2013') + '</td><td>' + pill(DS[x.status] || DS.pending) + (x.status === 'approved' ? '<div class="small">' + (x.valid ? 'valid until ' : '<span class="red">expired ') + SX.fmt(x.expiry_date, true) + (x.valid ? '' : '</span>') + '</div>' : '') + '</td><td>' + (x.reference ? '<b>' + esc(x.reference) + '</b>' : '\u2013') + (x.conditions ? '<div class="small muted">' + esc(x.conditions) + '</div>' : '') + (x.decided_by ? '<div class="small muted">by ' + esc(x.decided_by) + '</div>' : '') + '</td><td style="text-align:right">' + (x.status === 'pending' && can.approve ? '<button class="btn sm p" style="--c:#4C5FD5" data-dc="' + x.id + '">Record decision</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '<div class="empty">No decisions yet.</div>') + '</div></div>';
      $$('[data-rq]', main).forEach(function (b) { b.addEventListener('click', function () { requestForm(d.candidates.filter(function (c) { return c.id === +b.dataset.rq; })[0], d.meetings); }); });
      $$('[data-dc]', main).forEach(function (b) { b.addEventListener('click', function () { decideForm(d.decisions.filter(function (x) { return x.id === +b.dataset.dc; })[0]); }); });
    });
  }
  function requestForm(c, meetings) {
    var m = SX.modal({ title: 'Request a Board decision on ' + c.ref, sub: esc(c.title), sticky: true, html: '<p class="muted small" style="margin-top:0">Residual rating ' + c.level + ' (' + c.rank + ') is above appetite. Say what you recommend, for example: retain for 90 days while plan A-118 is funded.</p><label class="f">Meeting<select id="rm"><option value="">not yet scheduled</option>' + meetings.map(function (x) { return '<option value="' + x.id + '">' + mtitle(x) + '</option>'; }).join('') + '</select></label><label class="f">Recommendation *<textarea id="rr" rows="3"></textarea></label>', buttons: [{ label: 'Cancel' }, { label: 'Send to the Board', cls: 'p', onClick: function () {
      return api('POST', '/api/board/decisions', { risk_id: c.id, meeting_id: m.$('#rm').value || null, recommendation: m.$('#rr').value }).then(function () { SX.toast('Decision requested', 'ok'); decisions(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  function decideForm(x) {
    var exp = new Date(Date.now() + 90 * 864e5).toISOString().slice(0, 10);
    var m = SX.modal({ title: 'Record the Board decision on ' + x.ref, sub: esc(x.title), sticky: true, html: '<p class="muted small" style="margin-top:0">Recommendation: ' + esc(x.recommendation) + '</p><div class="form2"><label class="f">Decision *<select id="dd"><option value="approved">Approved: the risk may be retained</option><option value="deferred">Deferred</option><option value="rejected">Rejected: the risk returns to draft</option></select></label><label class="f">Retained until * <span class="muted">(within 12 months)</span><input type="date" id="de" value="' + exp + '"></label><label class="f full">Board minute or reference *<input type="text" id="dr" placeholder="e.g. BRC minute 2026/11/04"></label><label class="f full">Conditions<textarea id="dc" rows="2"></textarea></label></div>', buttons: [{ label: 'Cancel' }, { label: 'Record decision', cls: 'p', onClick: function () {
      return api('POST', '/api/board/decisions/' + x.id + '/decide', { decision: m.$('#dd').value, reference: m.$('#dr').value, expiry_date: m.$('#de').value, conditions: m.$('#dc').value }).then(function () { SX.toast('Decision recorded', 'ok'); decisions(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }

  function meetings() {
    var main = $('#main');
    api('GET', '/api/board').then(function (d) {
      main.innerHTML = head('meetings', d.can.create ? '<button class="btn p" id="nm" style="--c:#4C5FD5">+ New meeting</button>' : '') + '<div class="card">' + (d.meetings.length ? '<table class="t"><tr><th>Meeting</th><th>Date</th><th>Status</th><th>Notes</th><th></th></tr>' + d.meetings.map(function (m) { return '<tr><td><b>' + esc(m.title) + '</b></td><td>' + SX.fmt(m.meeting_date, true) + '</td><td><span class="tag">' + esc(m.status) + '</span></td><td>' + esc(m.notes || '') + '</td><td style="text-align:right">' + (d.can.edit ? '<button class="btn sm" data-em="' + m.id + '">Edit</button>' : '') + '</td></tr>'; }).join('') + '</table>' : '<div class="empty">No meetings yet. Schedule the Board Risk Committee so decisions and packs can be attached to it.</div>') + '</div>';
      var nm = $('#nm'); if (nm) nm.addEventListener('click', function () { meetingForm(null); });
      $$('[data-em]', main).forEach(function (b) { b.addEventListener('click', function () { meetingForm(d.meetings.filter(function (m) { return m.id === +b.dataset.em; })[0]); }); });
    });
  }
  function meetingForm(mt) {
    var m = SX.modal({ title: mt ? 'Edit meeting' : 'New meeting', sticky: true, html: '<div class="form2"><label class="f full">Title *<input type="text" id="mt" value="' + esc(mt ? mt.title : 'Board Risk Committee') + '"' + (mt ? ' readonly' : '') + '></label><label class="f">Date<input type="date" id="md" value="' + esc(mt ? mt.meeting_date || '' : '') + '"' + (mt ? ' readonly' : '') + '></label>' + (mt ? '<label class="f">Status<select id="ms">' + ['planned', 'held', 'cancelled'].map(function (s) { return '<option' + (mt.status === s ? ' selected' : '') + '>' + s + '</option>'; }).join('') + '</select></label>' : '') + '<label class="f full">Notes<textarea id="mn" rows="3">' + esc(mt ? mt.notes || '' : '') + '</textarea></label></div>', buttons: [{ label: 'Cancel' }, { label: 'Save', cls: 'p', onClick: function () {
      var p = mt ? api('PUT', '/api/board/meetings/' + mt.id, { status: m.$('#ms').value, notes: m.$('#mn').value }) : api('POST', '/api/board/meetings', { title: m.$('#mt').value, meeting_date: m.$('#md').value, notes: m.$('#mn').value });
      return p.then(function () { SX.toast('Saved', 'ok'); meetings(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }

  function packs() {
    var main = $('#main');
    api('GET', '/api/board').then(function (d) {
      var ST = { draft: '#F9A825', issued: '#2FA84F', withdrawn: '#8A97A8' };
      main.innerHTML = head('packs', d.can.create ? '<button class="btn p" id="np" style="--c:#4C5FD5">+ Generate report pack</button>' : '') + '<div class="alert info"><b>GRC Policy 2.5.</b> The Risk Management team reports quarterly to the Board through the Risk Committee (and monthly to the MD&rsquo;s meeting). A pack freezes the figures at the moment it is generated, so the numbers do not move after it is issued. Open it, add the team&rsquo;s comments, then print or save it as PDF.</div><div class="card">' + (d.packs.length ? '<table class="t"><tr><th>Pack</th><th>Generated</th><th>Status</th><th></th></tr>' + d.packs.map(function (p) { return '<tr><td><b>' + esc(p.title) + '</b></td><td>' + SX.fmt(p.created_at) + '</td><td><span class="badge" style="background:' + (ST[p.status] || '#8A97A8') + ';color:#fff">' + esc(p.status) + '</span>' + (p.issued_at ? ' <span class="small muted">' + SX.fmt(p.issued_at, true) + '</span>' : '') + '</td><td style="text-align:right"><a class="btn sm" href="#/m/board_hub/pack/' + p.id + '">Open</a></td></tr>'; }).join('') + '</table>' : '<div class="empty">No packs yet.</div>') + '</div>';
      var np = $('#np'); if (np) np.addEventListener('click', function () {
        var q = 'Q' + (Math.floor(new Date().getMonth() / 3) + 1) + ' ' + new Date().getFullYear();
        var m = SX.modal({ title: 'Generate a report pack', sticky: true, html: '<label class="f">Title *<input type="text" id="pt" value="Quarterly Risk Report ' + q + '"></label><label class="f">For meeting<select id="pm"><option value="">no meeting</option>' + d.meetings.map(function (x) { return '<option value="' + x.id + '">' + mtitle(x) + '</option>'; }).join('') + '</select></label><p class="muted small">The pack uses assessed risks only and states how many are still waiting for assessment.</p>', buttons: [{ label: 'Cancel' }, { label: 'Generate', cls: 'p', onClick: function () {
          return api('POST', '/api/board/packs', { title: m.$('#pt').value, meeting_id: m.$('#pm').value || null }).then(function (r) { SX.toast('Pack generated', 'ok'); location.hash = '#/m/board_hub/pack/' + r.id; }, function (e) { SX.toast(e.message, 'bad'); return false; });
        } }] });
      });
    });
  }

  function pack(id) {
    var main = $('#main');
    api('GET', '/api/board/packs/' + id).then(function (p) {
      var d = p.data, can = p.can, t = d.thresholds, B = { within_target: 'Within target', within_appetite: 'Within appetite', outside_appetite: 'Outside appetite', outside_tolerance: 'Outside tolerance' };
      var h = head('pack', '<span class="noprint"><button class="btn" id="print">Print or save as PDF</button>' + (p.status === 'draft' && can.approve ? '<button class="btn p" id="issue" style="--c:#2FA84F">Issue pack</button>' : '') + (p.status === 'issued' && can.approve ? '<button class="btn" id="withdraw">Withdraw</button>' : '') + (can.delete && p.status !== 'issued' ? '<button class="btn" id="delpack" style="color:#C62828">Delete</button>' : '') + '</span>');
      h += '<div class="card" style="margin-bottom:12px"><h2 style="margin:0;color:#0B1F3A">' + esc(p.title) + ' <span class="tag">' + esc(p.status) + '</span></h2><div class="muted small">EcoCash (Pvt) Ltd &middot; generated ' + SX.fmt(d.generated_at) + (p.issued_at ? ' &middot; issued ' + SX.fmt(p.issued_at) : '') + ' &middot; frozen: these figures do not change &middot; thresholds target ' + t.target + ', appetite ' + t.appetite + ', tolerance ' + t.tolerance + '</div></div><div class="grid">';
      var k = function (l, v, c) { return '<div class="card kpi s2" style="--c:' + c + '"><div class="l">' + l + '</div><div class="v">' + v + '</div></div>'; };
      h += k('Risks assessed', d.assessed, '#4C5FD5') + k('Awaiting assessment', d.unassessed, '#F9A825') + k('High', d.residual.High, '#EF2B2B') + k('Significant', d.residual.Significant, '#FDB022') + k('Outside appetite', d.outside_appetite, '#E0474C') + k('Outside tolerance', d.outside_tolerance, '#7B5CD6');
      h += '<div class="card s5" style="grid-column:span 5"><h3>Residual risk map</h3>' + ui.matrixHtml({ counts: d.cells, h: 46 }) + ui.legend() + '</div>';
      h += '<div class="card s7" style="grid-column:span 7"><h3>Top 10 risks</h3><table class="t"><tr><th>Ref</th><th>Risk</th><th>Owner</th><th>Inherent</th><th>Residual</th><th>Position</th></tr>' + d.top.map(function (x) { return '<tr><td><b>' + esc(x.ref) + '</b></td><td>' + esc(x.title.slice(0, 64)) + '</td><td>' + esc(x.owner || '') + '</td><td>' + x.inherent + '</td><td>' + ui.badge({ level: x.level, rank: x.residual }) + '</td><td>' + esc(B[x.band] || '') + '</td></tr>'; }).join('') + '</table></div>';
      h += '<div class="card s12"><h3>Risks above appetite and their Board position (' + d.above.length + ')</h3>' + (d.above.length ? '<table class="t"><tr><th>Ref</th><th>Risk</th><th>Rank</th><th>Board decision</th></tr>' + d.above.map(function (x) { return '<tr><td><b>' + esc(x.ref) + '</b></td><td>' + esc(x.title) + '</td><td>' + x.rank + '</td><td>' + esc(x.decision) + '</td></tr>'; }).join('') + '</table>' : '<div class="muted">None.</div>') + '</div>';
      h += '<div class="card s6"><h3>Movement since the last snapshot' + (d.snapshot ? ' (' + esc(d.snapshot) + ')' : '') + '</h3>' + (d.movement.length ? '<table class="t"><tr><th>Ref</th><th>Risk</th><th>From</th><th>To</th></tr>' + d.movement.map(function (x) { return '<tr><td><b>' + esc(x.ref) + '</b></td><td>' + esc(x.title.slice(0, 50)) + '</td><td>' + (x.from == null ? 'new' : x.from) + '</td><td>' + x.to + '</td></tr>'; }).join('') + '</table>' : '<div class="muted">No movement, or no snapshot yet.</div>') + '</div>';
      h += '<div class="card s6"><h3>Control assurance</h3><dl class="kv"><dt>Level of assurance</dt><dd><b>' + ui.pct(d.assurance.loa) + '</b></dd><dt>Exposure EMV-i</dt><dd>' + ui.money(d.assurance.emv_i) + '</dd><dt>Residual EMV-r</dt><dd>' + ui.money(d.assurance.emv_r) + '</dd></dl></div>';
      if (d.appetite && d.appetite.length) h += '<div class="card s12"><h3>Appetite statements against limits</h3><table class="t"><tr><th>Dimension</th><th>Measure</th><th>Limit</th><th>Actual</th><th>Status</th></tr>' + d.appetite.map(function (s) { return '<tr><td>' + esc(s.dimension) + '</td><td>' + esc(s.metric || '') + '</td><td>' + (s.limit == null ? '\u2013' : s.limit) + '</td><td>' + (s.actual == null ? '\u2013' : s.actual) + '</td><td>' + esc(s.status) + '</td></tr>'; }).join('') + '</table></div>';
      h += '<div class="card s6"><h3>Board decisions in the period</h3>' + (d.decisions.length ? '<ul class="list">' + d.decisions.map(function (x) { return '<li><b>' + esc(x.ref) + '</b> ' + esc(x.status) + (x.expiry_date ? ' until ' + esc(x.expiry_date) : '') + ' <span class="muted small">' + esc(x.reference || '') + '</span></li>'; }).join('') + '</ul>' : '<div class="muted">None in the last quarter.</div>') + '<h3 style="margin-top:12px">Waiting for the Board</h3>' + (d.pending.length ? '<ul class="list">' + d.pending.map(function (x) { return '<li><b>' + esc(x.ref) + '</b> ' + esc(x.title) + '</li>'; }).join('') + '</ul>' : '<div class="muted">Nothing pending.</div>') + '</div>';
      h += '<div class="card s6"><h3>Assessment campaigns</h3>' + (d.campaigns.length ? '<ul class="list">' + d.campaigns.map(function (c) { return '<li><b>' + esc(c.name) + '</b> due ' + SX.fmt(c.due, true) + ' &middot; ' + c.counts.approved + ' of ' + c.counts.total + ' approved</li>'; }).join('') + '</ul>' : '<div class="muted">No open campaigns.</div>') + (d.tracker ? '<h3 style="margin-top:12px">Risk Office tracker</h3><div class="muted small">' + Object.keys(d.tracker).map(function (k2) { return esc(k2.replace('_', ' ')) + ' ' + esc(d.tracker[k2]); }).join(' &middot; ') + '</div>' : '') + '</div>';
      h += '</div><p class="muted small noprint" style="margin-top:10px">Comments from the Risk Management team are added in the meeting paper that accompanies this pack. Print or save as PDF from your browser.</p>';
      main.innerHTML = h;
      var on = function (i, f) { var e = $(i); if (e) e.addEventListener('click', f); };
      on('#print', function () { window.print(); });
      on('#issue', function () { api('POST', '/api/board/packs/' + id + '/issue').then(function () { SX.toast('Pack issued', 'ok'); pack(id); }, function (e) { SX.toast(e.message, 'bad'); }); });
      on('#withdraw', function () { api('POST', '/api/board/packs/' + id + '/withdraw').then(function () { SX.toast('Pack withdrawn', 'ok'); pack(id); }, function (e) { SX.toast(e.message, 'bad'); }); });
      on('#delpack', function () { api('DELETE', '/api/board/packs/' + id).then(function () { SX.toast('Pack deleted', 'ok'); location.hash = '#/m/board_hub/packs'; }, function (e) { SX.toast(e.message, 'bad'); }); });
    });
  }
})();
