/* Daily Tracker: your Excel task tracker as a live module (same tiles, columns and status rules), plus automation, events and summary. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#4C5FD5';
  var TABS = [['tasks', 'Tasks'], ['events', 'Events today'], ['summary', 'End-of-day summary'], ['settings', 'Automation']];
  var ST = { 'Overdue': ['#CC0000', '#fff', '\uD83D\uDD34 Overdue'], 'Due Soon': ['#FFC000', '#3A2600', '\uD83D\uDFE0 Due Soon'], 'On Track': ['#00A651', '#fff', '\uD83D\uDFE2 On Track'], 'Completed': ['#00802B', '#fff', '\u2705 Completed'], 'Rescheduled': ['#7030A0', '#fff', '\uD83D\uDCC5 Rescheduled'], 'On Hold': ['#8A97A8', '#fff', '\u23F8 On Hold'], 'Cancelled': ['#8A97A8', '#fff', '\u26D4 Cancelled'], '': ['#E6ECF4', '#51627A', '\u2013'] };
  var f = { q: '', show: 'active', owner: '' }, D = null;

  function chip(s) { var c = ST[s] || ST['']; return '<span class="badge" style="background:' + c[0] + ';color:' + c[1] + ';min-width:96px;text-align:center">' + c[2] + '</span>'; }
  function head(tab, extra) { return SX.head('Command &rsaquo; Daily Tracker', 'Daily Tracker', COLOR, extra || '') + SX.tabs('m/daily_tracker', TABS.filter(function (t) { return t[0] !== 'settings' || SX.can('daily_tracker', 'approve'); }), tab, COLOR); }

  SX.pages.tracker = function (tab) {
    tab = tab || 'tasks'; var main = $('#main');
    main.innerHTML = head(tab) + '<div id="tk"><div class="loading">Loading...</div></div>';
    if (tab === 'events') return events(); if (tab === 'summary') return summary(); if (tab === 'settings') return settings();
    api('POST', '/api/tracker/sync').catch(function () { return {}; }).then(function (s) { return api('GET', '/api/tracker').then(function (d) { D = d; tasks(s); }); });
  };

  function tile(l, v, bg, fg) { return '<div style="background:' + bg + ';color:' + fg + ';border-radius:10px;text-align:center;padding:10px 6px;grid-column:span 2"><div style="font-size:11px;font-weight:700;letter-spacing:.5px">' + l + '</div><div style="font-size:32px;font-weight:700;line-height:38px">' + v + '</div></div>'; }
  function tasks(sync) {
    var d = D, t = d.tiles, box = $('#tk'), can = d.can;
    var rows = d.tasks.filter(function (x) {
      if (f.owner && x.owner_text !== f.owner) return false;
      if (f.q && (x.title + ' ' + (x.comment || '') + ' ' + (x.owner_text || '')).toLowerCase().indexOf(f.q.toLowerCase()) < 0) return false;
      return { all: true, active: x.status !== 'Completed' && x.status !== 'Cancelled', overdue: x.status === 'Overdue', soon: x.status === 'Due Soon' || x.status === 'Overdue', done: x.status === 'Completed', auto: x.source === 'auto', manual: x.source !== 'auto' }[f.show];
    });
    var h = '<div class="grid" style="margin-bottom:12px">' + tile('TOTAL TASKS', t.total, '#4472C4', '#fff') + tile('OVERDUE', t.overdue, '#CC0000', '#fff') + tile('DUE TODAY', t.due_today, '#ED7D31', '#fff') + tile('DUE SOON', t.due_soon, '#FFC000', '#3A2600') + tile('COMPLETED', t.completed, '#00802B', '#fff') + tile('ON TRACK', t.on_track, '#00A651', '#fff') + '</div>';
    if (sync && (sync.created || sync.closed)) h += '<div class="alert info">Automatic rules added <b>' + sync.created + '</b> task(s) and closed <b>' + sync.closed + '</b> (see the Source column). Change this under the Automation tab.</div>';
    h += '<div class="card"><div class="toolbar"><input type="search" id="tq" placeholder="Search task, comment, owner" value="' + esc(f.q) + '" style="width:230px"><select id="to" style="width:160px"><option value="">All owners</option>' + d.owners.map(function (o) { return '<option' + (f.owner === o ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select>' +
      [['active', 'Active'], ['all', 'All'], ['overdue', 'Overdue'], ['soon', 'Overdue + due soon'], ['done', 'Completed'], ['auto', 'Automatic'], ['manual', 'Manual / imported']].map(function (c) { return '<span class="chip' + (f.show === c[0] ? ' on' : '') + '" style="--c:#4C5FD5" data-show="' + c[0] + '">' + c[1] + '</span>'; }).join('') +
      '<div style="flex:1"></div><span class="muted small">Mode: <b>' + esc(d.cfg.mode) + '</b></span>' + (can.create ? '<button class="btn" id="timp">Import Excel</button>' : '') + (can.export ? '<a class="btn" href="/api/tracker/export.xlsx">Download Excel</a>' : '') + (can.create ? '<button class="btn p" id="tadd" style="--c:#4C5FD5">+ New task</button>' : '') + '</div>';
    h += rows.length ? '<div style="overflow:auto"><table class="t"><tr><th>Task</th><th>Comment</th><th>Assignment status</th><th>Owner</th><th>Deadline</th><th>Revised timeline</th><th>Completion status</th><th>E-mail link</th><th>Days left</th><th></th></tr>' + rows.map(function (x) {
      var sel = can.edit ? '<select data-qs="' + x.id + '" style="width:150px;padding:4px 6px;font-size:11.5px">' + d.assignments.map(function (a) { return '<option' + (x.assignment === a ? ' selected' : '') + '>' + esc(a) + '</option>'; }).join('') + '</select>' : '<span class="tag">' + esc(x.assignment) + '</span>';
      return '<tr><td style="min-width:240px"><b>' + esc(x.title) + '</b>' + (x.source === 'auto' ? ' <span class="tag" title="Created by an automatic rule">Auto</span>' : x.source === 'import' ? ' <span class="tag">Imported</span>' : '') + '</td><td style="min-width:180px">' + esc(x.comment || '') + '</td><td>' + sel + '</td><td>' + esc(x.owner_text || '') + '</td><td style="white-space:nowrap">' + SX.fmt(x.deadline, true) + '</td><td style="white-space:nowrap">' + (x.revised ? SX.fmt(x.revised, true) : '<span class="muted">\u2013</span>') + '</td><td>' + chip(x.status) + '</td><td>' + (x.email_url ? '<a href="' + esc(x.email_url) + '" target="_blank" rel="noopener noreferrer">' + esc(x.email_label || 'Open e-mail') + '</a>' : (x.email_label ? esc(x.email_label) : '')) + '</td><td style="text-align:center"><b' + (x.days != null && x.days < 0 && x.status !== 'Completed' ? ' class="red"' : '') + '>' + (x.days == null ? '' : x.days) + '</b></td><td style="white-space:nowrap">' + (can.edit ? '<button class="btn sm" data-edit="' + x.id + '">Edit</button>' : '') + '</td></tr>';
    }).join('') + '</table></div><div class="muted small" style="margin-top:8px">' + rows.length + ' of ' + d.tasks.length + ' tasks. Status and days left are calculated: Completed when the assignment is Submitted or Completed; Rescheduled when a revised timeline is set; Overdue before today; Due Soon within ' + d.cfg.soon_days + ' days.</div>' : '<div class="empty">No tasks match.' + (can.create && !d.tasks.length ? ' Import your Excel tracker or add the first task.' : '') + '</div>';
    box.innerHTML = h + '</div>';
    var tm; $('#tq').addEventListener('input', function (e) { f.q = e.target.value; clearTimeout(tm); tm = setTimeout(function () { tasks(); }, 200); });
    $('#to').addEventListener('change', function (e) { f.owner = e.target.value; tasks(); });
    $$('[data-show]', box).forEach(function (c) { c.addEventListener('click', function () { f.show = c.dataset.show; tasks(); }); });
    var a = $('#tadd'); if (a) a.addEventListener('click', function () { form(null); });
    var im = $('#timp'); if (im) im.addEventListener('click', importDialog);
    $$('[data-edit]', box).forEach(function (b) { b.addEventListener('click', function () { form(D.tasks.filter(function (x) { return x.id === +b.dataset.edit; })[0]); }); });
    $$('[data-qs]', box).forEach(function (s) { s.addEventListener('change', function () {
      var x = D.tasks.filter(function (y) { return y.id === +s.dataset.qs; })[0];
      api('PUT', '/api/tracker/tasks/' + x.id, { title: x.title, comment: x.comment, assignment: s.value, owner_text: x.owner_text, deadline: x.deadline, revised: x.revised, revised_reason: x.revised_reason, email_label: x.email_label, email_url: x.email_url }).then(function () { SX.toast('Status updated', 'ok'); SX.pages.tracker('tasks'); }, function (e) { SX.toast(e.message, 'bad'); SX.pages.tracker('tasks'); });
    }); });
  }

  function form(x) {
    var edit = !!x, v = function (k) { return esc(x && x[k] != null ? x[k] : ''); };
    var m = SX.modal({ title: edit ? 'Edit task' : 'New task', wide: true, sticky: true, html: '<form id="tf" class="form2"><label class="f full">Task *<input type="text" name="title" value="' + v('title') + '"></label><label class="f full">Comment<textarea name="comment" rows="2">' + v('comment') + '</textarea></label>' +
      '<label class="f">Assignment status<select name="assignment">' + D.assignments.map(function (a) { return '<option' + ((x ? x.assignment : 'Pending') === a ? ' selected' : '') + '>' + esc(a) + '</option>'; }).join('') + '</select></label><label class="f">Owner<input type="text" name="owner_text" list="tow" value="' + v('owner_text') + '"><datalist id="tow">' + D.owners.map(function (o) { return '<option value="' + esc(o) + '">'; }).join('') + '</datalist></label>' +
      '<label class="f">Deadline<input type="date" name="deadline" value="' + v('deadline') + '"></label><label class="f">Revised timeline <span class="muted">(keeps the original deadline)</span><input type="date" name="revised" value="' + v('revised') + '"></label><label class="f full" id="rr" style="display:' + (x && x.revised ? 'block' : 'none') + '">Reason for the revised timeline *<input type="text" name="revised_reason" value="' + v('revised_reason') + '"></label>' +
      '<label class="f">E-mail link label<input type="text" name="email_label" value="' + v('email_label') + '" placeholder="[Re: Subject | Outlook]"></label><label class="f">E-mail link (URL)<input type="text" name="email_url" value="' + v('email_url') + '" placeholder="https://..."></label></form>' + (edit ? '<div class="muted small">' + (x.source === 'auto' ? 'Created automatically by a rule; edits are kept.' : x.source === 'import' ? 'Imported from your Excel tracker.' : 'Added manually.') + '</div>' : ''),
      buttons: [{ label: 'Cancel' }].concat(edit && D.can['delete'] ? [{ label: 'Delete', cls: 'd', onClick: function () { remove(x); } }] : []).concat([{ label: edit ? 'Save task' : 'Add task', cls: 'p', onClick: function () {
        var fm = m.$('#tf'), body = {}; ['title', 'comment', 'assignment', 'owner_text', 'deadline', 'revised', 'revised_reason', 'email_label', 'email_url'].forEach(function (k) { body[k] = fm[k].value; });
        return api(edit ? 'PUT' : 'POST', '/api/tracker/tasks' + (edit ? '/' + x.id : ''), body).then(function () { SX.toast('Saved', 'ok'); SX.pages.tracker('tasks'); }, function (e) { SX.toast(e.message, 'bad'); return false; });
      } }]) });
    m.$('[name=revised]').addEventListener('change', function (e) { m.$('#rr').style.display = e.target.value ? 'block' : 'none'; });
  }
  function remove(x) {
    var m = SX.modal({ title: 'Delete this task?', html: '<p>It moves to the Recycle Bin and can be restored for 90 days.</p><label class="f">Reason (required)<textarea id="dr" rows="2"></textarea></label>', buttons: [{ label: 'Cancel' }, { label: 'Move to Recycle Bin', cls: 'd', onClick: function () {
      return api('DELETE', '/api/tracker/tasks/' + x.id, { reason: m.$('#dr').value }).then(function () { SX.toast('Moved to the Recycle Bin', 'ok'); SX.pages.tracker('tasks'); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }

  function importDialog() {
    var m = SX.modal({ title: 'Import your Excel task tracker', wide: true, sticky: true, html: '<p class="muted small" style="margin-top:0">Choose the tracker workbook (.xlsx) with the columns TASK, COMMENT, ASSIGNMENT STATUS, Owner, DEADLINE, Revised Timelines and EMAIL LINK. Completion status and days remaining are recalculated by Sentinel, and your Outlook links are kept. Nothing is saved until you press Import; tasks already present are skipped, so it is safe to run twice.</p><input type="file" id="tkf" accept=".xlsx"><div id="tkr" style="margin-top:12px"></div>', buttons: [{ label: 'Close' }, { label: 'Import', cls: 'p', onClick: function () {
      var fl = m.$('#tkf').files[0]; if (!fl) { SX.toast('Choose the workbook first', 'bad'); return false; }
      return send(fl, 0).then(function (d) { SX.toast('Imported ' + d.imported + ' tasks', 'ok'); SX.pages.tracker('tasks'); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
    function send(file, dry) { return file.arrayBuffer().then(function (b) { return fetch('/api/tracker/import?dry=' + dry, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Sentinel': '1' }, credentials: 'same-origin', body: b }); }).then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.message || 'The import failed'); return d; }); }); }
    m.$('#tkf').addEventListener('change', function () {
      var fl = this.files[0], box = m.$('#tkr'); if (!fl) return; box.innerHTML = '<span class="muted">Checking the workbook...</span>';
      send(fl, 1).then(function (d) {
        box.innerHTML = '<div class="alert info"><b>' + d.to_import + ' tasks</b> will be imported' + (d.skipped ? ' (' + d.skipped + ' already present are skipped)' : '') + '. ' + Object.keys(d.status).map(function (k) { return d.status[k] + ' ' + esc(k.toLowerCase()); }).join(', ') + '. ' + d.links + ' with an e-mail link.</div>' + (d.warnings.length ? '<div class="alert warn"><b>Please note</b><ul style="margin:4px 0 0 18px">' + d.warnings.slice(0, 8).map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></div>' : '');
      }, function (e) { box.innerHTML = '<div class="alert bad">' + esc(e.message) + '</div>'; });
    });
  }

  function events() {
    api('GET', '/api/tracker/events').then(function (d) {
      var mx = Math.max.apply(null, d.by_hour.concat([1])), hours = d.by_hour.map(function (n, h) { return '<div style="flex:1;text-align:center"><div style="height:80px;display:flex;align-items:flex-end;justify-content:center"><div title="' + n + ' events" style="width:70%;height:' + (n / mx * 78) + 'px;background:#2F6FD6;border-radius:3px 3px 0 0"></div></div><div class="muted" style="font-size:9px">' + h + '</div></div>'; }).join('');
      var tl = Object.keys(d.types).sort(function (a, b) { return d.types[b] - d.types[a]; });
      $('#tk').innerHTML = '<div class="grid"><div class="card kpi s3" style="--c:#2F6FD6"><div class="l">Events today</div><div class="v">' + d.events.length + '</div><div class="d">' + d.auto + ' captured automatically</div></div><div class="card s9"><h3>Events by hour</h3><div style="display:flex;gap:2px">' + hours + '</div></div>' +
        '<div class="card s8"><h3>Today, ' + SX.fmt(d.date, true) + ': everything that happened in the risk modules</h3><div class="toolbar"><input type="text" id="ntx" placeholder="Add a note to today\'s log (for example: regulator call about licence returns)" style="flex:1"><button class="btn p" id="nadd" style="--c:#4C5FD5">Add note</button></div>' +
        (d.events.length ? '<ul class="list">' + d.events.map(function (e) { return '<li><b style="width:50px">' + new Date(e.ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) + '</b><span style="flex:1">' + esc(e.detail || e.event) + ' <span class="muted small">' + esc(e.username || 'system') + ' &middot; ' + esc(e.event) + '</span></span></li>'; }).join('') + '</ul>' : '<div class="empty">Nothing yet today.</div>') + '</div><div class="card s4"><h3>By type</h3>' + (tl.length ? tl.map(function (k) { return '<div class="hrow"><span class="n" style="width:90px">' + esc(k) + '</span><div class="bar"><i style="width:' + d.types[k] / d.events.length * 100 + '%;background:#4C5FD5"></i></div><b>' + d.types[k] + '</b></div>'; }).join('') : '<div class="muted">No events.</div>') + '</div></div>';
      $('#nadd').addEventListener('click', function () { var t = $('#ntx').value.trim(); if (!t) return; api('POST', '/api/tracker/note', { text: t }).then(function () { SX.toast('Note added', 'ok'); events(); }, function (e) { SX.toast(e.message, 'bad'); }); });
    });
  }

  function summary() {
    api('GET', '/api/tracker/summary').then(function (s) {
      var sec = function (t, xs, c) { return '<div class="card s6"><h3 style="color:' + c + '">' + t + ' (' + xs.length + ')</h3>' + (xs.length ? '<ul class="list">' + xs.slice(0, 30).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '<div class="muted">None</div>') + '</div>'; };
      $('#tk').innerHTML = '<div class="alert info">End-of-day summary for <b>' + SX.fmt(s.date, true) + '</b> built from your tracker and today\'s events. <button class="btn sm" id="ssend">Prepare as a message</button></div><div class="grid">' + sec('Completed today', s.completed_today, '#00802B') + sec('Moved to a new date today', s.moved_today, '#7030A0') + sec('Overdue now', s.overdue, '#CC0000') + sec('Due tomorrow', s.due_tomorrow, '#ED7D31') + sec('Created automatically today', s.auto_created_today, '#2F6FD6') + '</div>';
      $('#ssend').addEventListener('click', function () { api('POST', '/api/tracker/summary/send').then(function (r) { SX.toast(r.message, 'ok'); }, function (e) { SX.toast(e.message, 'bad'); }); });
    });
  }

  function settings() {
    api('GET', '/api/tracker').then(function (d) {
      var k = d.cfg, src = { risk_actions: 'Action dates on risks (GRC Policy 2.5.1)', assessments: 'Assessment Studio assessments and reviews', board: 'Board decisions waiting', kri: 'KRIs in red (KRI Monitor)', incidents: 'Serious incidents, breach clocks and re-assessment after closure', sources: 'Data sources to verify, changed or suspended, and proposed values to review' };
      $('#tk').innerHTML = '<div class="card"><h3>How the tracker is fed</h3><form id="cf"><div style="margin-bottom:10px">' + [['automatic', 'Automatic', 'The system creates, updates and closes tasks by rule, and prepares a daily digest for each person. You can still add tasks.'], ['hybrid', 'Hybrid (recommended)', 'The system adds tasks from risks, assessments and Board decisions; people add and manage the rest.'], ['manual', 'Manual', 'Nothing is created by rule. The tracker is only what people enter or import.']].map(function (m) { return '<label style="display:block;padding:6px 0"><input type="radio" name="mode" value="' + m[0] + '"' + (k.mode === m[0] ? ' checked' : '') + '> <b>' + m[1] + '</b><div class="muted small" style="margin-left:22px">' + m[2] + '</div></label>'; }).join('') + '</div>' +
        '<label class="f" style="max-width:260px">Due-soon window (days)<input type="number" name="soon_days" min="1" max="14" value="' + k.soon_days + '"></label><div class="b small" style="margin-bottom:6px">Automatic sources</div>' + Object.keys(src).map(function (s) { return '<label style="display:block;padding:3px 0"><input type="checkbox" name="src_' + s + '"' + (k.sources[s] ? ' checked' : '') + '> ' + src[s] + '</label>'; }).join('') + '<p class="muted small">Tasks created by a rule show an Auto tag. They close themselves when their source item is finished. A task you delete is not recreated.</p><button class="btn p" style="--c:#4C5FD5" type="submit">Save</button></form></div>';
      $('#cf').addEventListener('submit', function (e) {
        e.preventDefault(); var fm = e.target, body = { mode: fm.mode.value, soon_days: fm.soon_days.value, sources: {} }; Object.keys(src).forEach(function (s) { body.sources[s] = fm['src_' + s].checked; });
        api('PUT', '/api/tracker/settings', body).then(function () { SX.toast('Saved', 'ok'); }, function (er) { SX.toast(er.message, 'bad'); });
      });
    });
  }
})();
