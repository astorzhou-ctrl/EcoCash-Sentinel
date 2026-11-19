/* KRI report format (Step 24): upload the report template the Risk Office uses, choose and rename the sections, set the colours, check the figures, download. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, K = SX.KQ;
  var LV = { error: ['#FDECEC', '#B71C1C', 'Error'], warn: ['#FFF4DC', '#8A5A00', 'Check'], info: ['#EAF1FB', '#27456F', 'Note'] };

  function send(f, dry) {
    return f.arrayBuffer().then(function (b) { return fetch('/api/kriq/template?dry=' + dry, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Sentinel': '1', 'X-Filename': encodeURIComponent(f.name) }, credentials: 'same-origin', body: b }); })
      .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.message || 'The template could not be read'); return d; }); });
  }
  function preview(pr) {
    var o = '<div class="small"><b>' + esc(pr.name) + '</b>: ' + pr._slides + ' slides read. Colours ' + ['primary', 'blue', 'accent'].map(function (k) { return '<span style="display:inline-block;width:12px;height:12px;background:#' + pr[k] + ';border:1px solid #ccc;vertical-align:middle"></span> #' + pr[k]; }).join(' ') + ', font ' + esc(pr.font) + ', logo ' + (pr._has_logo ? 'found' : 'not found (the current logo is kept)') + '.</div>';
    (pr._warnings || []).forEach(function (w) { o += '<div class="small" style="margin-top:4px;color:#8A5A00">' + esc(w) + '</div>'; });
    o += '<table class="kq-tbl" style="margin-top:8px;width:100%"><tr><th>Template slide</th><th>Becomes the Sentinel section</th></tr>' + pr._matched.map(function (m) { return '<tr><td>' + esc(m.template) + '</td><td>' + esc(m.section) + '</td></tr>'; }).join('') + '</table>';
    if (pr._unmatched.length) o += '<div class="small muted" style="margin-top:6px">Not matched to a KRI section (left out): ' + pr._unmatched.map(esc).join('; ') + '.</div>';
    return o + '<div class="small muted" style="margin-top:6px">Sections the template does not mention are kept at the end and can be switched off.</div>';
  }
  function upload(done) {
    var cur = null;
    var m = SX.modal({ title: 'Upload a report template', wide: true, sticky: true, html: '<p class="muted small" style="margin-top:0">A PowerPoint (.pptx) report your office already uses. Sentinel reads its colours, font, logo and slide titles and uses them for the KRI report, in the same order. The template\'s own slide designs are not copied.</p><label class="f">Template<input type="file" id="tf" accept=".pptx"></label><div id="tp"></div>',
      buttons: [{ label: 'Cancel' }, { label: 'Use this template', cls: 'p', onClick: function (mm) { if (!cur) { SX.toast('Choose a template first', 'bad'); return false; } return send(cur, 0).then(function () { SX.toast('Template adopted', 'ok'); done(); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] });
    m.$('#tf').addEventListener('change', function () { var f = this.files[0]; if (!f) return; m.$('#tp').innerHTML = '<div class="muted small">Reading&hellip;</div>'; send(f, 1).then(function (r) { cur = f; m.$('#tp').innerHTML = preview(r.proposal); }, function (e) { cur = null; m.$('#tp').innerHTML = '<div class="small" style="color:#B71C1C">' + esc(e.message) + '</div>'; }); });
  }

  SX.kriqFormat = function () {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    Promise.all([api('GET', '/api/kriq/format?' + K.qs()), api('GET', '/api/kriq/checks?' + K.qs())]).then(function (rs) {
      var f = rs[0].format, can = rs[0].can.edit, ck = rs[1];
      var h = K.head('format', K.dl('/api/kriq/export.pptx?' + K.qs(), 'Download PowerPoint', 'p') + K.dl('/api/kriq/export.xlsx?' + K.qs(), 'Download Power BI data'));
      // integrity checks first: what to confirm before the report goes out
      h += '<div class="card"><h3 style="margin-top:0">Report checks ' + (ck.ok ? '<span class="badge" style="background:#E3F6E8;color:#1B6B34">Figures reconcile</span>' : '<span class="badge" style="background:#FDECEC;color:#B71C1C">Does not reconcile</span>') + '</h3><div class="small muted">' + esc(ck.reconciliation || '') + '</div>' +
        '<div class="small" style="margin:6px 0">' + ck.counts.error + ' errors, ' + ck.counts.warn + ' to confirm, ' + ck.counts.info + ' for the record. These checks are also in the PowerPoint and the data pack.</div>' +
        (ck.items.length ? '<div style="max-height:260px;overflow:auto">' + ck.items.map(function (i) { var c = LV[i.level]; return '<div class="small" style="padding:5px 8px;margin:3px 0;border-radius:5px;background:' + c[0] + ';color:' + c[1] + '"><b>' + c[2] + '</b> &middot; ' + esc(i.text) + '</div>'; }).join('') + '</div>' : '<div class="small">Nothing to confirm.</div>') + '</div>';
      h += '<div class="card"><h3 style="margin-top:0">Report format: ' + esc(f.name) + '</h3><div class="small muted">Used by the PowerPoint download. ' + (can ? '' : 'You can view the format; changing it needs edit rights.') + '</div>';
      if (can) h += '<div style="margin:8px 0"><button class="btn p" id="ft-up" style="--c:#0B3A82">Upload a report template</button> <button class="btn" id="ft-rs">Reset to EcoCash standard</button></div>';
      h += '<div class="form2" style="max-width:820px"><label class="f">Cover title<input id="ft-title" value="' + esc(f.title) + '"' + (can ? '' : ' disabled') + '></label><label class="f">Organisation<input id="ft-org" value="' + esc(f.org) + '"' + (can ? '' : ' disabled') + '></label><label class="f">Footer note (every slide)<input id="ft-foot" value="' + esc(f.footer) + '"' + (can ? '' : ' disabled') + '></label>' +
        ['primary', 'blue', 'accent'].map(function (k) { return '<label class="f">' + { primary: 'Title band colour', blue: 'Main colour', accent: 'Accent colour' }[k] + ' (hex)<input id="ft-' + k + '" value="' + esc(f[k]) + '" maxlength="7"' + (can ? '' : ' disabled') + '></label>'; }).join('') + '<label class="f">Font<input id="ft-font" value="' + esc(f.font) + '"' + (can ? '' : ' disabled') + '></label></div>' +
        '<div class="small muted">Logo: ' + (f.has_logo ? 'from the uploaded template' : 'EcoCash logo') + '.</div>' +
        '<h4>Sections, in report order</h4><table class="kq-tbl" id="ft-sec" style="width:100%;max-width:820px"><tr><th>Include</th><th>Heading in the report</th><th>Sentinel section</th>' + (can ? '<th></th>' : '') + '</tr>' +
        f.sections.map(function (s, i) { return '<tr data-id="' + s.id + '"><td><input type="checkbox" ' + (s.enabled ? 'checked ' : '') + (can ? '' : 'disabled') + '></td><td><input style="width:100%" maxlength="120" value="' + esc(s.title) + '"' + (can ? '' : ' disabled') + '></td><td class="small muted">' + esc(s.default) + '</td>' + (can ? '<td style="white-space:nowrap"><button class="btn sm" data-up="' + i + '">&uarr;</button><button class="btn sm" data-dn="' + i + '">&darr;</button></td>' : '') + '</tr>'; }).join('') + '</table>';
      if (can) h += '<div style="margin-top:10px"><button class="btn p" id="ft-save" style="--c:#0B3A82">Save the format</button></div>';
      main.innerHTML = h + '</div>';
      var body = function () {
        return { title: $('#ft-title').value, org: $('#ft-org').value, footer: $('#ft-foot').value, primary: $('#ft-primary').value, blue: $('#ft-blue').value, accent: $('#ft-accent').value, font: $('#ft-font').value,
          sections: $$('#ft-sec tr[data-id]', main).map(function (tr) { return { id: tr.dataset.id, enabled: $('input[type=checkbox]', tr).checked, title: $('td:nth-child(2) input', tr).value }; }) };
      };
      var save = function (b, msg) { return api('PUT', '/api/kriq/format', b).then(function () { SX.toast(msg || 'Format saved', 'ok'); SX.kriqFormat(); }, function (e) { SX.toast(e.message, 'bad'); }); };
      var on = function (id, f2) { var e = $(id); if (e) e.addEventListener('click', f2); };
      on('#ft-save', function () { save(body()); }); on('#ft-up', function () { upload(SX.kriqFormat); });
      on('#ft-rs', function () { api('DELETE', '/api/kriq/format').then(function () { SX.toast('Reset to the EcoCash standard', 'ok'); SX.kriqFormat(); }); });
      $$('[data-up],[data-dn]', main).forEach(function (b) { b.addEventListener('click', function () { var b2 = body(), i = +(b.dataset.up != null ? b.dataset.up : b.dataset.dn), j = b.dataset.up != null ? i - 1 : i + 1; if (j < 0 || j >= b2.sections.length) return; var t = b2.sections[i]; b2.sections[i] = b2.sections[j]; b2.sections[j] = t; save(b2, 'Order changed'); }); });
    }, function (e) { main.innerHTML = K.head('format', '') + '<div class="card">' + esc(e.message || 'Could not load') + '</div>'; });
  };
})();
