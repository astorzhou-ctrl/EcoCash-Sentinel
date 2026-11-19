/* Two-step sign-in on My Profile > Security: set up, recovery codes, turn off. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api;
  function codesBox(codes) { return '<div style="font-family:Consolas,monospace;font-size:16px;line-height:1.9;columns:2;padding:8px 12px;background:#F2F5FA;border-radius:8px;margin:8px 0">' + codes.map(esc).join('<br>') + '</div>'; }
  function reauth(title, btnLabel, path, again, extra) {
    var m = SX.modal({ title: title, sticky: true, html: '<p class="muted small" style="margin-top:0">Confirm it is you: your password and the current 6-digit code from your authenticator app.</p><label class="f">Password<input type="password" name="password" autocomplete="current-password"></label><label class="f">Code from the app<input type="text" name="code" inputmode="numeric" maxlength="8" autocomplete="off"></label>', buttons: [{ label: 'Cancel' }, { label: btnLabel, cls: 'p', onClick: function () {
      return api('POST', path, { password: $('[name=password]', m.el).value, code: $('[name=code]', m.el).value }).then(function (r) { if (extra) extra(r); else { SX.toast('Done', 'ok'); again(); } }, function (e) { SX.toast(e.message, 'bad'); return false; });
    } }] });
  }
  function wizard(again) {
    api('POST', '/api/auth/mfa/setup').then(function (d) {
      var m = SX.modal({ title: 'Set up two-step sign-in', wide: true, sticky: true, html: '<ol style="margin-top:0;padding-left:18px;line-height:1.7"><li>Open your authenticator app (Google Authenticator, Microsoft Authenticator or similar).</li><li>Choose <b>Add account</b>, then <b>Enter a setup key</b>.</li><li>Type the account name <b>' + esc(d.account) + '</b> and this key (spaces do not matter):</li></ol><div id="mk" style="font-family:Consolas,monospace;font-size:20px;letter-spacing:.06em;padding:10px 12px;background:#F2F5FA;border-radius:8px;word-break:break-all">' + esc(d.secret) + '</div><label class="f" style="margin-top:12px">Then enter the 6-digit code the app shows<input type="text" name="code" inputmode="numeric" maxlength="8" autocomplete="off"></label>',
        buttons: [{ label: 'Cancel' }, { label: 'Turn on', cls: 'p', onClick: function () {
          return api('POST', '/api/auth/mfa/confirm', { code: $('[name=code]', m.el).value }).then(function (r) {
            SX.modal({ title: 'Save your recovery codes', sticky: true, sub: 'Each code works once if you lose your phone. They are <b>not shown again</b>.', html: codesBox(r.recovery_codes), buttons: [{ label: 'I have saved them', cls: 'p', onClick: function () { again(); } }] });
          }, function (e) { SX.toast(e.message, 'bad'); return false; });
        } }] });
    }, function (e) { SX.toast(e.message, 'bad'); });
  }
  SX.mfaCard = function (box, again) {
    api('GET', '/api/auth/mfa/status').then(function (s) {
      var el = document.createElement('div'); el.className = 'card'; el.style.marginTop = '12px'; el.id = 'mfa-card';
      el.innerHTML = '<h3>Two-step sign-in</h3><p class="muted small" style="margin-top:0">After your password, Sentinel asks for a 6-digit code from an app on your phone, so a stolen password alone is not enough. <b>Your System Administrator switches it on or off for you</b>; you cannot change it yourself.' + (s.required ? ' <b>It is switched on for you.</b>' : '') + '</p>' +
        (s.enabled ? '<dl class="kv"><dt>Status</dt><dd><b style="color:#2FA84F">On</b></dd><dt>Recovery codes left</dt><dd>' + s.recovery_left + (s.recovery_left <= 2 ? ' <span class="red b">(make new ones soon)</span>' : '') + '</dd></dl><div class="toolbar"><button class="btn" id="mfa-new">New recovery codes</button></div>'
          : '<dl class="kv"><dt>Status</dt><dd>' + (s.required ? '<b class="red">Required but not set up</b>' : 'Off') + '</dd></dl>' + (s.required ? '<div class="toolbar"><button class="btn p" id="mfa-on" style="--c:#2F6FD6">Set it up now</button></div>' : '<p class="muted small">It is off. If you should be using it, ask your System Administrator to switch it on.</p>'));
      box.appendChild(el);
      var on = function (id, fn) { var b = $(id, el); if (b) b.addEventListener('click', fn); };
      on('#mfa-on', function () { wizard(again); });
      on('#mfa-new', function () { reauth('New recovery codes', 'Make new codes', '/api/auth/mfa/recovery-codes', again, function (r) { SX.modal({ title: 'Your new recovery codes', sticky: true, sub: 'The old codes no longer work. These are <b>not shown again</b>.', html: codesBox(r.recovery_codes), buttons: [{ label: 'I have saved them', cls: 'p', onClick: function () { again(); } }] }); }); });
    });
  };
})();
