(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var params = new URLSearchParams(location.search);
  var policy = { password_min_length: 12, max_failed_attempts: 3, self_service_reset: true };
  var lastPassword = '', mode = 'login', resetToken = params.get('reset');

  function api(method, url, body) {
    return fetch(url, { method: method, headers: { 'Content-Type': 'application/json', 'X-Sentinel': '1' }, credentials: 'same-origin', body: body ? JSON.stringify(body) : undefined })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._status = r.status; return d; }); });
  }
  function view(name) {
    ['login', 'locked', 'change', 'forgot', 'mfa', 'enroll'].forEach(function (v) { $('#v-' + v).hidden = v !== name; });
    var f = { login: '#username', change: '#newpw', forgot: '#ident', mfa: '#mfacode', enroll: '#enrollcode' }[name];
    if (f) setTimeout(function () { $(f).focus(); }, 30);
  }
  function banner(id, kind, html) { var b = $(id); b.className = 'banner ' + kind; b.innerHTML = html; b.hidden = false; }
  function hide(id) { $(id).hidden = true; }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function busy(btn, on, label) { btn.disabled = on; if (label) btn.querySelector('span').textContent = on ? 'Please wait...' : label; }
  function shake() { var c = $('#card'); c.classList.remove('shake'); void c.offsetWidth; c.classList.add('shake'); }

  // eye toggles
  document.querySelectorAll('[data-eye]').forEach(function (b) {
    b.addEventListener('click', function () { var i = document.getElementById(b.dataset.eye); i.type = i.type === 'password' ? 'text' : 'password'; i.focus(); });
  });
  document.querySelectorAll('[data-back]').forEach(function (a) { a.addEventListener('click', function (e) { e.preventDefault(); resetToken = null; history.replaceState(null, '', '/login'); view('login'); }); });
  $('#go-forgot').addEventListener('click', function (e) { e.preventDefault(); if (!policy.self_service_reset) { banner('#banner', 'amber', 'Self-service reset is switched off. Ask your administrator to reset your password.'); return; } view('forgot'); });

  // remembered username
  try { var ru = localStorage.getItem('sentinel_user'); if (ru) { $('#username').value = ru; $('#remember').checked = true; } } catch (e) {}
  if (params.get('reason') === 'idle') banner('#banner', 'amber', 'You were signed out after a period of inactivity. Sign in again to continue.');
  if (params.get('reason') === 'signedout') banner('#banner', 'green', 'You have signed out.');
  if (params.get('reason') === 'change') banner('#banner', 'blue', 'Sign in again to choose a new password.');

  api('GET', '/api/public/policy').then(function (p) {
    if (!p.password_min_length) return;
    policy = p; buildRules();
    var words = { 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten' };
    $('#locked-reset-note').textContent = 'If you forgot your password, reset it now with a link sent to your registered e-mail (valid ' + p.reset_link_minutes + ' minutes).';
    document.querySelector('#v-locked .sub').textContent = (words[p.max_failed_attempts] || p.max_failed_attempts) + ' failed sign-in attempts. To protect the account it has been locked and the administrator has been told.';
  });

  // ---- sign in
  var pending = null, recMode = false;
  function proceed(d, p) {
    if (d.must_change_password) { lastPassword = p; mode = 'forced'; prepareChange(d.reason === 'expired' ? 'Your password is 90 days old and has expired. Choose a new one to continue.' : 'You signed in with a temporary password. Choose your own password to continue.'); return; }
        try { sessionStorage.setItem('sx_tab', '1'); sessionStorage.setItem('sentinel_warn', d.warn ? String(d.password_days_left) : ''); } catch (e) {}
        location.href = '/app';
  }
  $('#v-login').addEventListener('submit', function (e) {
    e.preventDefault();
    var u = $('#username').value.trim(), p = $('#password').value;
    ['#username', '#password'].forEach(function (s) { $(s).closest('.field').classList.remove('err'); });
    if (!u || !p) { banner('#banner', 'red', 'Enter your username and your password.'); shake(); return; }
    var btn = $('#btn-login'); busy(btn, true, 'Login'); hide('#banner');
    api('POST', '/api/auth/login', { username: u, password: p }).then(function (d) {
      busy(btn, false, 'Login');
      if (d.ok) {
        try { if ($('#remember').checked) localStorage.setItem('sentinel_user', u); else localStorage.removeItem('sentinel_user'); } catch (e) {}
        if (d.mfa === 'verify' || d.mfa === 'enroll') { pending = { d: d, p: p }; return d.mfa === 'verify' ? startVerify() : startEnroll(); }
        proceed(d, p);
      } else if (d.error === 'bad_credentials') {
        banner('#banner', 'red', '<b>Incorrect username or password.</b> Check them and try again.'); // the lock-out rule still applies; the screen no longer spells it out
        $('#password').closest('.field').classList.add('err'); $('#password').value = ''; $('#password').focus(); shake();
      } else if (d.error === 'locked') {
        $('#password').value = ''; $('#locked-reset-note').hidden = !policy.self_service_reset; $('#btn-locked-reset').hidden = !policy.self_service_reset; view('locked');
      } else {
        banner('#banner', d._status === 429 ? 'amber' : 'red', esc(d.message || 'Sign-in failed. Try again.')); shake();
      }
    }).catch(function () { busy(btn, false, 'Login'); banner('#banner', 'red', 'Cannot reach the server. Check that Sentinel is running and try again.'); });
  });

  // ---- two-step sign-in
  function startVerify() { recMode = false; $('#mfacode').value = ''; $('#mfacode').placeholder = '6-digit code'; $('#mfa-rec').textContent = 'Use a recovery code instead'; hide('#bannermfa'); view('mfa'); setTimeout(function () { $('#mfacode').focus(); }, 60); }
  $('#mfa-rec').addEventListener('click', function (e) { e.preventDefault(); recMode = !recMode; $('#mfacode').value = ''; $('#mfacode').placeholder = recMode ? 'recovery code, e.g. a1b2c-3d4e5' : '6-digit code'; this.textContent = recMode ? 'Use the code from the app instead' : 'Use a recovery code instead'; $('#mfacode').focus(); });
  $('#v-mfa').addEventListener('submit', function (e) {
    e.preventDefault(); var v = $('#mfacode').value.trim(); if (!v) { banner('#bannermfa', 'red', 'Enter the code.'); shake(); return; }
    var btn = $('#btn-mfa'); busy(btn, true, 'Verify');
    api('POST', '/api/auth/mfa/verify', recMode ? { recovery: v } : { code: v }).then(function (d) {
      busy(btn, false, 'Verify');
      if (d.ok) { proceed(pending.d, pending.p); }
      else if (d.error === 'locked') { view('locked'); }
      else { banner('#bannermfa', 'red', '<b>' + esc(d.message || 'That code is not correct.') + '</b>' + (d.attempts_remaining != null ? ' ' + d.attempts_remaining + ' attempt(s) left before the account is locked.' : '')); $('#mfacode').value = ''; shake(); }
    });
  });
  function startEnroll() {
    hide('#bannerenroll'); $('#enroll-setup').hidden = false; $('#enroll-codes').hidden = true; $('#enrollcode').value = '';
    api('POST', '/api/auth/mfa/setup').then(function (d) { if (d.secret) { $('#enroll-key').textContent = d.secret; view('enroll'); setTimeout(function () { $('#enrollcode').focus(); }, 60); } else { view('login'); banner('#banner', 'red', esc(d.message || 'Two-step set-up could not start.')); } });
  }
  $('#btn-enroll').addEventListener('click', function () {
    var btn = this; busy(btn, true, 'Turn on');
    api('POST', '/api/auth/mfa/confirm', { code: $('#enrollcode').value }).then(function (d) {
      busy(btn, false, 'Turn on');
      if (d.ok) { $('#enroll-list').innerHTML = d.recovery_codes.map(esc).join('<br>'); $('#enroll-setup').hidden = true; $('#enroll-codes').hidden = false; }
      else if (d.error === 'locked') { view('locked'); }
      else { banner('#bannerenroll', 'red', esc(d.message || 'That code is not correct.')); $('#enrollcode').value = ''; shake(); }
    });
  });
  $('#btn-enroll-done').addEventListener('click', function () { proceed(pending.d, pending.p); });

  // ---- locked
  $('#btn-locked-reset').addEventListener('click', function () { $('#ident').value = $('#username').value; view('forgot'); });
  $('#btn-locked-admin').addEventListener('click', function () {
    var n = $('#locked-admin'); n.hidden = false;
    n.innerHTML = 'Ask your System Administrator to unlock <b>' + esc($('#username').value) + '</b> in Access Management. Reference: LK-' + new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '');
  });

  // ---- forgot
  $('#v-forgot').addEventListener('submit', function (e) {
    e.preventDefault();
    var v = $('#ident').value.trim(); if (!v) { banner('#banner3', 'red', 'Enter your username or e-mail.'); return; }
    var btn = $('#btn-forgot'); busy(btn, true, 'Send reset link');
    api('POST', '/api/auth/forgot', { identifier: v }).then(function (d) {
      busy(btn, false, 'Send reset link');
      banner('#banner3', 'green', esc(d.message || 'If an account matches, a reset link has been sent.'));
    });
  });

  // ---- choose a new password (forced change or reset link)
  var RULES = [['len', function (p) { return p.length >= policy.password_min_length; }, function () { return 'At least ' + policy.password_min_length + ' characters'; }],
    ['lo', function (p) { return /[a-z]/.test(p); }, function () { return 'A lower-case letter'; }], ['up', function (p) { return /[A-Z]/.test(p); }, function () { return 'An upper-case letter'; }],
    ['dg', function (p) { return /[0-9]/.test(p); }, function () { return 'A number'; }], ['sy', function (p) { return /[^A-Za-z0-9]/.test(p); }, function () { return 'A symbol'; }],
    ['nm', function (p) { var u = $('#username').value.trim().toLowerCase(); return !(u.length >= 3 && p.toLowerCase().indexOf(u) >= 0); }, function () { return 'Not your username'; }]];
  function buildRules() { $('#rules').innerHTML = RULES.map(function (r) { return '<li data-r="' + r[0] + '">' + r[2]() + '</li>'; }).join(''); }
  function evalPw() {
    var p = $('#newpw').value, ok = 0;
    RULES.forEach(function (r) { var good = r[1](p); if (good) ok++; var li = document.querySelector('[data-r="' + r[0] + '"]'); if (li) li.className = good ? 'ok' : ''; });
    var lvl = !p ? 0 : ok <= 2 ? 1 : ok <= 4 ? 2 : ok === 5 ? 3 : 4;
    document.querySelectorAll('.meter i').forEach(function (i, n) { i.className = n < lvl ? 'on' + lvl : ''; });
    $('#meter-label').textContent = ['Enter a password', 'Weak', 'Fair', 'Good', 'Strong'][lvl];
    return ok === RULES.length;
  }
  function prepareChange(note) {
    buildRules(); $('#newpw').value = ''; $('#newpw2').value = ''; evalPw(); hide('#banner2');
    $('#change-title').textContent = mode === 'reset' ? 'Reset your password' : 'Create a new password';
    $('#change-note').innerHTML = esc(note); view('change');
  }
  $('#newpw').addEventListener('input', evalPw);
  $('#v-change').addEventListener('submit', function (e) {
    e.preventDefault();
    var a = $('#newpw').value, b = $('#newpw2').value;
    if (!evalPw()) { banner('#banner2', 'red', 'The new password does not meet every rule listed below.'); shake(); return; }
    if (a !== b) { banner('#banner2', 'red', 'The two passwords do not match.'); shake(); return; }
    var btn = $('#btn-change'); busy(btn, true, 'Save and continue');
    var req = mode === 'reset' ? api('POST', '/api/auth/reset', { token: resetToken, new_password: a }) : api('POST', '/api/auth/change-password', { current_password: lastPassword, new_password: a });
    req.then(function (d) {
      busy(btn, false, 'Save and continue');
      if (d.ok) {
        if (mode === 'reset') { resetToken = null; history.replaceState(null, '', '/login'); view('login'); banner('#banner', 'green', 'Your password was changed. Sign in with the new password.'); $('#password').focus(); }
        else { try { sessionStorage.setItem('sx_tab', '1'); } catch (e) {} location.href = '/app'; }
      } else { banner('#banner2', 'red', esc(d.message || 'The password could not be changed.')); shake(); }
    });
  });

  buildRules();
  if (resetToken) { mode = 'reset'; prepareChange('Choose a new password. The reset link works once and then expires.'); }
  else view('login');
})();
