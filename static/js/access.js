/* Access Management: users, roles and permissions, locked and expired accounts, sign-in policy. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#5B6B7C';
  var uf = { q: '', status: '', deleted: false }, roleSel = null;
  var TABS = [['users', 'Users'], ['roles', 'Roles and permissions'], ['locked', 'Locked and expired'], ['policy', 'Sign-in policy']];

  function statusBadge(u) {
    var s = u.status === 'invited' ? 'Invited' : u.status.charAt(0).toUpperCase() + u.status.slice(1);
    return '<span class="badge b-' + u.status + '">' + s + '</span>' + (u.password_expired ? ' <span class="badge b-expired">Password expired</span>' : '');
  }
  function pwCell(u) {
    if (u.status === 'invited' || u.must_change) return '<span class="muted">temporary</span>';
    if (u.password_days_left == null) return '\u2013';
    if (u.password_days_left < 0) return '<span class="red b">expired</span>';
    return u.password_days_left <= 14 ? '<span style="color:#B36B00" class="b">' + u.password_days_left + ' days</span>' : u.password_days_left + ' days';
  }

  SX.pages.access = function (tab) {
    var main = $('#main');
    main.innerHTML = SX.head('Platform &rsaquo; Access Management', 'Access Management', COLOR, SX.can('access_management', 'create') && tab === 'users' && !uf.deleted ? '<button class="btn p" id="add-user" style="--c:#5B6B7C">+ Add user</button>' : '') + SX.tabs('m/access_management', TABS, tab, COLOR) + '<div id="atab"></div>';
    var b = $('#add-user'); if (b) b.addEventListener('click', function () { userForm(null); });
    if (tab === 'users') usersTab(); else if (tab === 'roles') rolesTab(); else if (tab === 'locked') lockedTab(); else policyTab();
  };

  // ------------------------------------------------------------ users
  function usersTab() {
    var box = $('#atab');
    box.innerHTML = '<div class="grid" id="ustats"></div><div class="card" style="margin-top:12px"><div class="toolbar"><input type="search" id="uq" placeholder="Search name, username, e-mail, department" value="' + esc(uf.q) + '"><span id="uchips"></span><div style="flex:1"></div><button class="btn" id="udel">' + (uf.deleted ? 'Back to active users' : 'Deleted users') + '</button></div><div id="utable"><div class="loading">Loading...</div></div></div>';
    var chips = [['', 'All'], ['active', 'Active'], ['invited', 'Invited'], ['locked', 'Locked'], ['deactivated', 'Deactivated'], ['expired', 'Password expired']];
    $('#uchips').innerHTML = uf.deleted ? '' : chips.map(function (c) { return '<span class="chip' + (uf.status === c[0] ? ' on' : '') + '" style="--c:#5B6B7C" data-st="' + c[0] + '">' + c[1] + '</span>'; }).join('');
    $$('[data-st]', box).forEach(function (c) { c.addEventListener('click', function () { uf.status = c.dataset.st; usersTab(); }); });
    var t; $('#uq').addEventListener('input', function (e) { uf.q = e.target.value; clearTimeout(t); t = setTimeout(load, 220); });
    $('#udel').addEventListener('click', function () { uf.deleted = !uf.deleted; uf.status = ''; SX.pages.access('users'); });
    load();
    function load() {
      api('GET', '/api/users?q=' + encodeURIComponent(uf.q) + '&status=' + encodeURIComponent(uf.status) + '&deleted=' + (uf.deleted ? 1 : 0)).then(function (d) {
        var s = d.stats, k = function (l, v, c, sub) { return '<div class="card kpi s2" style="--c:' + c + '"><div class="l">' + l + '</div><div class="v">' + v + '</div><div class="d">' + sub + '</div></div>'; };
        $('#ustats').innerHTML = k('Users', s.total, '#4C5FD5', s.active + ' active') + k('Locked', s.locked, s.locked ? '#EF2B2B' : '#2FA84F', 'awaiting unlock') + k('Invited', s.invited, '#F9A825', 'not yet signed in') + k('Password expired', s.expired_password, '#FDB022', '90-day rule') + k('Access expiring', s.access_expiring, '#17A2B8', 'next 30 days') + k('In Recycle Bin', s.in_bin, '#5B6B7C', 'restorable');
        var rows = d.users;
        $('#utable').innerHTML = rows.length ? '<table class="t"><tr><th>User</th><th>Department</th><th>Roles</th><th>Status</th><th>Last sign-in</th><th>Password</th><th></th></tr>' + rows.map(function (u) {
          return '<tr><td><b>' + esc(u.full_name) + '</b><div class="muted small">' + esc(u.username) + ' &middot; ' + esc(u.email || '') + '</div></td><td>' + esc(u.department || '\u2013') + '</td><td>' + u.roles.map(function (r) { return '<span class="tag">' + esc(r) + '</span>'; }).join('') + '</td><td>' + statusBadge(u) + '</td><td>' + (u.last_login_at ? SX.fmt(u.last_login_at) : '<span class="muted">never</span>') + '</td><td>' + (uf.deleted ? '<span class="muted small">deleted ' + SX.fmt(u.deleted_at, true) + '<br>' + esc(u.delete_reason || '') + '</span>' : pwCell(u)) + '</td><td style="text-align:right">' + (uf.deleted ? '<button class="btn sm" data-restore="' + u.id + '">Restore</button>' : '<button class="btn sm" data-menu="' + u.id + '" aria-label="Actions for ' + esc(u.username) + '">Manage &#9662;</button>') + '</td></tr>';
        }).join('') + '</table>' : '<div class="empty">No users match.</div>';
        $$('[data-menu]', box).forEach(function (b) { b.addEventListener('click', function () { rowMenu(b, rows.filter(function (u) { return u.id === +b.dataset.menu; })[0]); }); });
        $$('[data-restore]', box).forEach(function (b) { b.addEventListener('click', function () { restoreUser(+b.dataset.restore); }); });
      });
    }
  }
  function refresh() { SX.pages.access(location.hash.split('/')[3] || 'users'); }
  function rowMenu(btn, u) {
    var can = function (a) { return SX.can('access_management', a); }, items = [];
    items.push({ label: 'View activity', onClick: function () { activity(u); } });
    if (can('edit')) {
      items.push({ label: 'Edit details and roles', onClick: function () { userForm(u); } }, { label: 'Reset password (issue temporary)', onClick: function () { resetPw(u); } });
      if (u.status === 'locked') items.push({ label: 'Unlock account', onClick: function () { act(u, 'unlock', 'Unlocked'); } });
      items.push({ label: 'Force sign-out', onClick: function () { act(u, 'force-logout', 'Signed out everywhere'); } });
      items.push(u.status === 'deactivated' ? { label: 'Reactivate', onClick: function () { act(u, 'reactivate', 'Reactivated'); } } : { label: 'Deactivate', onClick: function () { confirmDo('Deactivate ' + u.full_name + '?', 'They lose access at once. History is kept and you can reactivate later.', function () { return act(u, 'deactivate', 'Deactivated'); }); } });
    }
    if (can('delete')) items.push('-', { label: 'Delete (to Recycle Bin)', danger: true, onClick: function () { deleteUser(u); } });
    SX.menu(btn, items);
  }
  function act(u, what, msg) {
    return api('POST', '/api/users/' + u.id + '/' + what).then(function () { SX.toast(msg + ': ' + u.username, 'ok'); refresh(); }, function (e) { SX.toast(e.message, 'bad'); });
  }
  function confirmDo(title, text, fn) { SX.modal({ title: title, html: '<p>' + esc(text) + '</p>', buttons: [{ label: 'Cancel' }, { label: 'Confirm', cls: 'd', onClick: fn }] }); }
  function tempShown(title, u, pw, extra) {
    SX.modal({ title: title, html: '<p>Give these sign-in details to <b>' + esc(u.full_name) + '</b>. The temporary password is shown <b>only now</b>; it is valid for 48 hours and must be changed at first sign-in. A copy of the message is in Administration &rsaquo; Outbox.</p><dl class="kv"><dt>Username</dt><dd><b>' + esc(u.username) + '</b></dd><dt>Temporary password</dt><dd><div class="pw">' + esc(pw) + '</div></dd></dl>' + (extra || ''), buttons: [{ label: 'Copy password', onClick: function () { SX.copy(pw); return false; } }, { label: 'Done', cls: 'p' }], sticky: true });
  }
  function resetPw(u) {
    confirmDo('Reset the password of ' + u.full_name + '?', 'A temporary password is issued, the account is unlocked and all of their sessions end. They must choose a new password at the next sign-in.', function () {
      return api('POST', '/api/users/' + u.id + '/reset-password').then(function (d) { refresh(); setTimeout(function () { tempShown('Temporary password issued', u, d.temp_password); }, 50); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    });
  }
  function deleteUser(u) {
    SX.modal({ title: 'Delete ' + u.full_name + '?', html: '<p>The account moves to the Recycle Bin and can be restored for 90 days. Their history stays in the audit trail.</p><label class="f">Reason (required)<textarea id="dreason" rows="2" placeholder="For example: left the company"></textarea></label>', buttons: [{ label: 'Cancel' }, { label: 'Move to Recycle Bin', cls: 'd', onClick: function (m) {
      var r = m.$('#dreason').value.trim(); if (r.length < 3) { SX.toast('Give a reason of at least 3 characters', 'bad'); return false; }
      return api('DELETE', '/api/users/' + u.id, { reason: r }).then(function () { SX.toast('Moved to the Recycle Bin', 'ok'); refresh(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  function restoreUser(id) {
    api('GET', '/api/admin/recycle').then(function (d) {
      var it = d.items.filter(function (i) { return i.entity_type === 'user' && i.entity_id === id; })[0];
      if (!it) { SX.toast('Not found in the Recycle Bin', 'bad'); return; }
      return api('POST', '/api/admin/recycle/' + it.id + '/restore').then(function () { SX.toast('Restored as deactivated. Check the roles, then reactivate.', 'ok'); uf.deleted = false; refresh(); });
    }).catch(function (e) { SX.toast(e.message, 'bad'); });
  }
  function activity(u) {
    api('GET', '/api/users/' + u.id).then(function (d) {
      SX.modal({ title: d.full_name, sub: esc(d.username) + ' &middot; ' + d.roles.map(esc).join(', '), wide: true, html: '<div class="grid"><div class="s6"><h3>Account</h3><dl class="kv"><dt>Status</dt><dd>' + statusBadge(d) + '</dd><dt>Last sign-in</dt><dd>' + SX.fmt(d.last_login_at) + '</dd><dt>Failed attempts</dt><dd>' + d.failed_attempts + '</dd><dt>Access expires</dt><dd>' + SX.fmt(d.access_expires, true) + '</dd><dt>Data scope</dt><dd>' + esc(d.data_scope) + '</dd><dt>Open sessions</dt><dd>' + d.sessions.length + '</dd></dl></div><div class="s6"><h3>Recent activity</h3><div class="timeline">' + (d.recent.length ? d.recent.map(function (r) { return '<div class="e"><b class="small">' + esc(r.event) + '</b> <span class="muted small">' + SX.fmt(r.ts) + '</span><div class="small">' + esc(r.detail || '') + '</div></div>'; }).join('') : '<div class="muted">No activity yet.</div>') + '</div></div></div>' });
    });
  }
  function userForm(u) {
    var edit = !!u, roles = SX.S.meta.roles, scopes = SX.S.meta.scopes;
    var rid = u ? u.role_ids : [];
    var h = '<form id="uform" class="form2"><label class="f">Full name *<input type="text" name="full_name" value="' + esc(u ? u.full_name : '') + '"></label><label class="f">Username *<input type="text" name="username" value="' + esc(u ? u.username : '') + '"' + (edit ? ' readonly' : '') + ' autocomplete="off"></label>' +
      '<label class="f">E-mail *<input type="email" name="email" value="' + esc(u ? u.email || '' : '') + '"></label><label class="f">Phone<input type="text" name="phone" value="' + esc(u ? u.phone || '' : '') + '"></label>' +
      '<label class="f">Department<input type="text" name="department" value="' + esc(u ? u.department || '' : '') + '"></label><label class="f">Job title<input type="text" name="job_title" value="' + esc(u ? u.job_title || '' : '') + '"></label>' +
      '<div class="full"><span class="f" style="display:block;font-size:10.5px;font-weight:700;color:#40536C;text-transform:uppercase;margin-bottom:6px">Roles * (several allowed)</span>' + roles.map(function (r) { return '<label style="display:inline-block;margin:0 14px 6px 0"><input type="checkbox" name="role" value="' + r.id + '"' + (rid.indexOf(r.id) >= 0 ? ' checked' : '') + '> ' + esc(r.name) + '</label>'; }).join('') + '</div>' +
      '<label class="f">Data scope <span class="muted">(oversight roles use "all")</span><select name="data_scope">' + scopes.map(function (s) { return '<option value="' + s + '"' + ((u ? u.data_scope : 'own') === s ? ' selected' : '') + '>' + s.replace('_', ' ') + '</option>'; }).join('') + '</select></label><label class="f">Access expires (optional)<input type="date" name="access_expires" value="' + esc(u ? u.access_expires || '' : '') + '"></label>';
    if (!edit) h += '<div class="full" style="background:#F3F6FA;border-radius:9px;padding:10px 12px;margin-bottom:6px"><b>Password setup</b><br><label style="display:block;margin-top:6px"><input type="radio" name="pm" value="generate" checked> Generate a temporary password (valid 48 hours, must be changed at first sign-in)</label><label style="display:block"><input type="radio" name="pm" value="manual"> I will type a temporary password</label><input type="password" name="manual_password" placeholder="Temporary password (must meet the policy)" style="margin-top:6px;display:none" autocomplete="new-password"></div>';
    h += '</form>';
    var m = SX.modal({ title: edit ? 'Edit ' + u.full_name : 'Add user', wide: true, html: h, sticky: true, buttons: [{ label: 'Cancel' }, { label: edit ? 'Save changes' : 'Create user', cls: 'p', onClick: function () {
      var f = m.$('#uform'), body = { full_name: f.full_name.value, username: f.username.value, email: f.email.value, phone: f.phone.value, department: f.department.value, job_title: f.job_title.value, data_scope: f.data_scope.value, access_expires: f.access_expires.value || null,
        role_ids: $$('[name=role]:checked', f).map(function (c) { return +c.value; }) };
      if (!edit) { body.password_mode = f.pm.value; body.manual_password = f.manual_password.value; }
      return api(edit ? 'PUT' : 'POST', '/api/users' + (edit ? '/' + u.id : ''), body).then(function (d) {
        refresh(); if (edit) SX.toast('Changes saved', 'ok'); else setTimeout(function () { tempShown('User created', d.user, d.temp_password); }, 60);
      }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
    var f = m.$('#uform');
    if (!edit) {
      var scopeTouched = false, ALLSCOPE = ['Head of Risk', 'Risk Manager', 'Auditor (read-only)', 'Executive and Board'];
      f.data_scope.addEventListener('change', function () { scopeTouched = true; });
      $$('[name=role]', f).forEach(function (c) { c.addEventListener('change', function () { if (scopeTouched) return; f.data_scope.value = $$('[name=role]:checked', f).some(function (x) { return ALLSCOPE.indexOf(x.parentNode.textContent.trim()) >= 0; }) ? 'all' : 'own'; }); });
      var manual = false;
      f.username.addEventListener('input', function () { manual = true; });
      f.full_name.addEventListener('input', function () { if (!manual) { var p = f.full_name.value.trim().toLowerCase().replace(/[^a-z\s.-]/g, '').split(/\s+/); f.username.value = p.length > 1 ? p[0] + '.' + p[p.length - 1] : p[0] || ''; } });
      $$('[name=pm]', f).forEach(function (r) { r.addEventListener('change', function () { f.manual_password.style.display = f.pm.value === 'manual' ? 'block' : 'none'; }); });
    }
  }

  // ------------------------------------------------------------ roles and permissions
  function rolesTab() {
    var box = $('#atab'), can = function (a) { return SX.can('access_management', a); };
    api('GET', '/api/roles').then(function (d) {
      var roles = d.roles; if (!roleSel || !roles.some(function (r) { return r.id === roleSel; })) roleSel = roles[0].id;
      var r = roles.filter(function (x) { return x.id === roleSel; })[0], fixed = r.name === 'System Administrator', ro = fixed || !can('edit');
      var meta = SX.S.meta, bysuite = {};
      meta.modules.forEach(function (m) { (bysuite[m.suite] = bysuite[m.suite] || []).push(m); });
      var mx = '<table class="mx"><tr><th>Module</th>' + meta.actions.map(function (a) { return '<th>' + a + '</th>'; }).join('') + '</tr>';
      meta.suites.forEach(function (s) {
        mx += '<tr class="suite-row"><td colspan="7" style="color:' + s.color + '">' + esc(s.name) + '</td></tr>';
        bysuite[s.name].forEach(function (m) { mx += '<tr><td>' + esc(m.name) + '</td>' + meta.actions.map(function (a) { return '<td><input type="checkbox" data-m="' + m.key + '" data-a="' + a + '"' + (((r.permissions[m.key] || []).indexOf(a) >= 0) ? ' checked' : '') + (ro ? ' disabled' : '') + ' aria-label="' + esc(m.name + ' ' + a) + '"></td>'; }).join('') + '</tr>'; });
      });
      mx += '</table>';
      box.innerHTML = '<div class="grid"><div class="card s4"><div class="toolbar"><h3 style="margin:0">Roles</h3><div style="flex:1"></div>' + (can('create') ? '<button class="btn sm p" id="newrole" style="--c:#5B6B7C">+ New role</button>' : '') + '</div><div class="rolelist">' + roles.map(function (x) { return '<div class="r' + (x.id === roleSel ? ' on' : '') + '" data-r="' + x.id + '"><b>' + esc(x.name) + '</b><span class="muted small">' + x.user_count + ' user' + (x.user_count === 1 ? '' : 's') + (x.is_system ? ' &middot; system role' : ' &middot; custom') + '</span></div>'; }).join('') + '</div></div>' +
        '<div class="card s8"><div class="toolbar"><h3 style="margin:0">' + esc(r.name) + '</h3><div style="flex:1"></div>' + (!ro ? '<button class="btn sm" id="allview">Grant view on all</button><button class="btn sm" id="clearall">Clear all</button><button class="btn sm p" id="saverole" style="--c:#5B6B7C">Save permissions</button>' : '') + (!r.is_system && can('delete') ? '<button class="btn sm d" id="delrole">Delete role</button>' : '') + '</div>' +
        '<p class="muted small" style="margin-top:0">' + esc(r.description || '') + '</p>' + (fixed ? '<div class="alert info">The System Administrator role is fixed. It manages users and the platform but cannot see risk data, so the person who adds users cannot also change risk ratings.</div>' : '') + '<div style="max-height:62vh;overflow:auto">' + mx + '</div><p class="muted small">Changes take effect at each user\'s next sign-in. Data scope (own function, business unit, all) is set per user.</p></div></div>';
      $$('[data-r]', box).forEach(function (e) { e.addEventListener('click', function () { roleSel = +e.dataset.r; rolesTab(); }); });
      var collect = function () { var p = {}; $$('input[data-m]:checked', box).forEach(function (c) { (p[c.dataset.m] = p[c.dataset.m] || []).push(c.dataset.a); }); return p; };
      var on = function (id, fn) { var e = $(id); if (e) e.addEventListener('click', fn); };
      on('#saverole', function () { api('PUT', '/api/roles/' + r.id, { permissions: collect() }).then(function () { SX.toast('Permissions saved for ' + r.name, 'ok'); rolesTab(); }, function (e) { SX.toast(e.message, 'bad'); }); });
      on('#allview', function () { $$('input[data-a=view]', box).forEach(function (c) { c.checked = true; }); });
      on('#clearall', function () { $$('input[data-m]', box).forEach(function (c) { c.checked = false; }); });
      on('#delrole', function () { confirmDo('Delete role ' + r.name + '?', 'This cannot be undone. Roles that still have users cannot be deleted.', function () { return api('DELETE', '/api/roles/' + r.id).then(function () { roleSel = null; SX.toast('Role deleted', 'ok'); rolesTab(); }, function (e) { SX.toast(e.message, 'bad'); return false; }); }); });
      on('#newrole', function () {
        var m = SX.modal({ title: 'New custom role', html: '<label class="f">Name *<input type="text" id="rn"></label><label class="f">Description<input type="text" id="rd"></label><p class="muted small">Start with no permissions, then tick what the role may do.</p>', buttons: [{ label: 'Cancel' }, { label: 'Create role', cls: 'p', onClick: function () {
          return api('POST', '/api/roles', { name: m.$('#rn').value, description: m.$('#rd').value, permissions: {} }).then(function (d) { roleSel = d.role.id; SX.S.meta.roles.push({ id: d.role.id, name: d.role.name }); SX.toast('Role created', 'ok'); rolesTab(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
        } }] });
      });
    });
  }

  // ------------------------------------------------------------ locked and expired
  function lockedTab() {
    var box = $('#atab');
    Promise.all([api('GET', '/api/users?status=locked'), api('GET', '/api/users?status=expired')]).then(function (r) {
      var tbl = function (rows, kind) {
        if (!rows.length) return '<div class="empty">None. Nothing needs attention.</div>';
        return '<table class="t"><tr><th>User</th><th>Reason</th><th>Since</th><th></th></tr>' + rows.map(function (u) { return '<tr><td><b>' + esc(u.full_name) + '</b><div class="muted small">' + esc(u.username) + '</div></td><td>' + (kind === 'locked' ? 'Locked after ' + u.failed_attempts + ' failed attempts' : 'Password older than 90 days') + '</td><td>' + (kind === 'locked' ? SX.fmt(u.locked_at) : '') + '</td><td style="text-align:right">' + (SX.can('access_management', 'edit') ? (kind === 'locked' ? '<button class="btn sm p" style="--c:#5B6B7C" data-un="' + u.id + '">Unlock</button> ' : '') + '<button class="btn sm" data-rp="' + u.id + '">Reset password</button>' : '') + '</td></tr>'; }).join('') + '</table>';
      };
      box.innerHTML = '<div class="grid"><div class="card s12"><h3>Locked accounts (' + r[0].users.length + ')</h3>' + tbl(r[0].users, 'locked') + '</div><div class="card s12"><h3>Password expired (' + r[1].users.length + ')</h3>' + tbl(r[1].users, 'expired') + '</div></div>';
      var all = r[0].users.concat(r[1].users);
      $$('[data-un]', box).forEach(function (b) { b.addEventListener('click', function () { act(all.filter(function (u) { return u.id === +b.dataset.un; })[0], 'unlock', 'Unlocked'); }); });
      $$('[data-rp]', box).forEach(function (b) { b.addEventListener('click', function () { resetPw(all.filter(function (u) { return u.id === +b.dataset.rp; })[0]); }); });
    });
  }

  // ------------------------------------------------------------ policy
  var LABELS = [['password_max_age_days', 'Password life (days)'], ['password_warn_days', 'Warn this many days before expiry'], ['password_min_length', 'Minimum password length'], ['password_history', 'Remember last N passwords'], ['max_failed_attempts', 'Lock the account after failed attempts'], ['idle_minutes', 'Sign out after idle minutes'],
    ['session_hours', 'Maximum session length (hours)'], ['max_sessions', 'Concurrent sessions per user'], ['temp_password_hours', 'Temporary password valid (hours)'], ['reset_link_minutes', 'Reset link valid (minutes)'], ['recycle_days', 'Recycle Bin retention (days)']];
  function policyTab() {
    var box = $('#atab');
    api('GET', '/api/admin/settings').then(function (d) {
      var p = d.policy, edit = SX.can('administration', 'edit');
      box.innerHTML = '<div class="card"><h3>Sign-in and session policy</h3><p class="muted small" style="margin-top:0">These values follow the BRD (section 5). Every change is recorded in the audit trail.</p><form id="pol" class="form2">' + LABELS.map(function (l) { var lim = d.limits[l[0]]; return '<label class="f">' + l[1] + ' <span class="muted">(' + lim[0] + ' to ' + lim[1] + ')</span><input type="number" name="' + l[0] + '" value="' + p[l[0]] + '" min="' + lim[0] + '" max="' + lim[1] + '"' + (edit ? '' : ' disabled') + '></label>'; }).join('') +
        '<label class="f full"><input type="checkbox" name="self_service_reset"' + (p.self_service_reset ? ' checked' : '') + (edit ? '' : ' disabled') + '> Let users reset a forgotten or locked password with an e-mail link</label>' + (edit ? '<div class="full"><button class="btn p" style="--c:#5B6B7C" type="submit">Save policy</button></div>' : '') + '</form></div>';
      $('#pol').addEventListener('submit', function (e) {
        e.preventDefault(); var f = e.target, body = {};
        LABELS.forEach(function (l) { body[l[0]] = f[l[0]].value; }); body.self_service_reset = f.self_service_reset.checked;
        api('PUT', '/api/admin/settings', { policy: body }).then(function (r) { SX.toast(r.changed.length ? 'Policy saved (' + r.changed.length + ' change' + (r.changed.length > 1 ? 's' : '') + ')' : 'No changes', 'ok'); SX.S.policy.idle_minutes = r.policy.idle_minutes; }, function (er) { SX.toast(er.message, 'bad'); });
      });
    }, function (e) { box.innerHTML = '<div class="alert warn">' + esc(e.status === 403 ? 'You can view users and roles, but the sign-in policy needs the Administration permission.' : e.message) + '</div>'; });
  }
})();
