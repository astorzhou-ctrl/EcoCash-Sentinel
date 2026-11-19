/* Sentinel Copilot (BRD 13.31): conversation with citations and sources, documents, risk assessment drafts, drafts awaiting approval, and the horizon watch.
   Everything the Copilot produces is labelled as AI-generated; it never changes a record: a named person accepts or rejects each draft. */
(function () {
  'use strict';
  var $ = SX.$, $$ = SX.$$, esc = SX.esc, api = SX.api, COLOR = '#7C5CE0', convId = null, ST = null, docSel = {}, TABS = [['ask', 'Ask'], ['docs', 'Documents'], ['assess', 'Assess'], ['drafts', 'Drafts for approval'], ['horizon', 'Horizon']];
  var LV = { Low: '#2FA84F', Medium: '#FDB022', Significant: '#F97316', High: '#EF2B2B' }, RANK = { '1-1': 1 };
  (function css() {
    if (document.getElementById('cpcss')) return; var s = document.createElement('style'); s.id = 'cpcss';
    s.textContent = '.cp-msg{max-width:860px;margin:10px 0;padding:12px 14px;border-radius:12px;line-height:1.5}.cp-u{background:#EEF3FF;margin-left:auto;border-bottom-right-radius:3px}.cp-a{background:#fff;border:1px solid #E1E6EE;border-bottom-left-radius:3px}.cp-a p{margin:.35em 0}.cp-a table{border-collapse:collapse;margin:6px 0;font-size:12.5px}.cp-a td,.cp-a th{border:1px solid #DDE3EC;padding:4px 8px}.cp-src{display:inline-flex;gap:5px;align-items:center;border:1px solid #DDE3EC;border-radius:14px;padding:2px 9px;font-size:11.5px;margin:2px 4px 2px 0;text-decoration:none;color:#1B2A41;background:#F8FAFD}.cp-src.cited{border-color:#7C5CE0;background:#F3EFFF}.cp-ai{display:inline-block;background:#7C5CE0;color:#fff;border-radius:4px;padding:0 6px;font-size:10px;font-weight:700;letter-spacing:.05em;margin-right:6px}.cp-box{height:calc(100vh - 430px);min-height:260px;overflow:auto;padding:4px 2px}.cp-prop{border:1px solid #E1E6EE;border-radius:10px;padding:12px;margin:10px 0;background:#fff}.cp-a blockquote{margin:6px 0;padding:6px 10px;border-left:3px solid #7C5CE0;background:#F8F6FF;font-size:13px}.cp-fu{display:inline-block;border:1px solid #D9D2F7;border-radius:14px;padding:3px 10px;font-size:12px;margin:3px 5px 0 0;cursor:pointer;background:#fff;color:#4B3BA8}.cp-bar{height:7px;border-radius:4px;background:#E6EAF0;overflow:hidden;width:90px;display:inline-block;vertical-align:middle}.cp-bar i{display:block;height:100%;background:#7C5CE0}';
    document.head.appendChild(s);
  })();
  function md(text, sources) { // a small, safe renderer: paragraphs, lists, bold, tables, and [REF] links to records
    var lines = String(text || '').split(/\r?\n/), out = [], list = false, tbl = [];
    var inl = function (t) { t = esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*([^*]+)\*/g, '<i>$1</i>').replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'); (sources || []).forEach(function (s) { if (s.type === 'record' && s.id) { var k = '[' + esc(s.ref) + ']'; t = t.split(k).join('<a href="#/m/risk_register/' + s.id + '">' + k + '</a>'); } }); return t; };
    var flush = function () { if (tbl.length) { out.push('<table>' + tbl.map(function (r, i) { return '<tr>' + r.map(function (c) { return (i === 0 ? '<th>' : '<td>') + inl(c.trim()) + (i === 0 ? '</th>' : '</td>'); }).join('') + '</tr>'; }).join('') + '</table>'); tbl = []; } if (list) { out.push('</ul>'); list = false; } };
    lines.forEach(function (l) {
      if (/^\s*\|/.test(l)) { if (/^[\s|:-]+$/.test(l)) return; if (list) { out.push('</ul>'); list = false; } tbl.push(l.replace(/^\s*\||\|\s*$/g, '').split('|')); return; }
      if (tbl.length) flush();
      var nm = /^\s*(\d+)[.)]\s+(.*)$/.exec(l);
      if (nm) { if (list) { out.push('</ul>'); list = false; } out.push('<p class="cp-num" style="margin:.3em 0"><b>' + nm[1] + '.</b> ' + inl(nm[2]) + '</p>'); return; }
      var m = /^\s*[-*]\s+(.*)$/.exec(l);
      if (m) { if (!list) { out.push('<ul>'); list = true; } out.push('<li>' + inl(m[1]) + '</li>'); return; }
      if (list) { out.push('</ul>'); list = false; }
      if (/^\s*>\s?/.test(l)) { out.push('<blockquote>' + inl(l.replace(/^\s*>\s?/, '')) + '</blockquote>'); return; }
      if (/^#{1,4}\s/.test(l)) { out.push('<p><b>' + inl(l.replace(/^#+\s*/, '')) + '</b></p>'); return; }
      if (l.trim()) out.push('<p>' + inl(l) + '</p>');
    });
    flush(); return out.join('');
  }
  function srcChips(sources) {
    if (!sources || !sources.length) return '';
    return '<div style="margin-top:8px"><span class="muted small">Sources consulted:</span> ' + sources.slice().sort(function (a, b) { return (b.cited ? 1 : 0) - (a.cited ? 1 : 0); }).map(function (s) {
      var cls = 'cp-src' + (s.cited ? ' cited' : ''), t;
      if (s.type === 'record') return '<a class="' + cls + '" href="' + (s.id ? '#/m/risk_register/' + s.id : s.kind === 'analytics' ? '#/m/performance_analytics' : '#/m/risk_register') + '" title="' + esc(s.label || '') + '">\u25A0 ' + esc(s.ref) + '</a>';
      if (s.type === 'knowledge') return '<span class="' + cls + '" title="Sentinel ERM knowledge pack">\u25C6 ' + esc(s.title) + '</span>';
      if (s.type === 'doc') return '<span class="' + cls + '" title="Approved document">\u25A4 ' + esc(s.title) + ' v' + s.version + (s.page ? ' p.' + s.page : '') + '</span>';
      t = (function () { try { return new URL(s.url).hostname.replace(/^www\./, ''); } catch (e) { return s.url; } })();
      return '<a class="' + cls + '" href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer" title="' + esc((s.title || '') + (s.cited_text ? ' \u2014 \u201C' + s.cited_text + '\u201D' : '')) + '">\uD83C\uDF10 ' + esc(t) + ' <span class="badge" style="background:' + (s.trusted ? '#2FA84F' : '#F0A04B') + ';color:#fff;font-size:9px">' + (s.trusted ? 'approved source' : 'not on the approved list') + '</span></a>';
    }).join('') + '</div>';
  }
  function head(tab) {
    var mode = ST ? ST.mode : 'off';
    return SX.head('Intelligence &rsaquo; Sentinel Copilot', 'Sentinel Copilot', COLOR, '<span class="badge" style="background:' + (ST && ST.on ? '#7C5CE0' : '#98A2B3') + ';color:#fff">AI mode: ' + esc(mode.charAt(0).toUpperCase() + mode.slice(1)) + '</span> <span class="badge" style="background:#1B2A41;color:#fff">' + (ST && ST.engine === 'claude' ? 'Engine: Claude' : 'Engine: built-in (free)') + '</span> ' + (SX.can('ai_governance', 'view') ? '<a class="btn sm" href="#/m/ai_governance" style="background:#F28C28;border-color:#F28C28;color:#fff">Settings</a>' : '')) + SX.tabs('m/sentinel_copilot', TABS, tab, COLOR) +
      '<div class="alert info" style="margin-bottom:10px"><span class="cp-ai">AI</span> Everything here is prepared by AI from your own data and approved documents. <b>Check it before you rely on it.</b> The Copilot never changes a record: it drafts, and a named person accepts or rejects.</div>' +
      (ST && !ST.on ? '<div class="alert warn" style="margin-bottom:10px"><b>The Copilot is not available.</b> ' + esc(ST.reason || '') + '</div>' : '');
  }
  function status() { return api('GET', '/api/ai/status').then(function (s) { ST = s; return s; }); }
  function busy(el, msg) { el.innerHTML = '<div class="muted"><span class="cp-ai">AI</span>' + esc(msg || 'Working on it... a careful answer can take up to a minute.') + '</div>'; }
  function money(v) { return v == null ? '' : '$' + (v < 1 ? v.toFixed(3) : v.toFixed(2)); }
  function usage(r) { if (r.engine === 'local') return '<div class="muted small" style="margin-top:6px">Built-in engine \u00B7 free, on this computer \u00B7 <a href="#/m/ai_governance">Connect Claude to answer any question</a>' + (r.flags && r.flags.length ? ' \u00B7 <span style="color:#C2410C">\u26A0 ' + esc(r.flags.join('; ')) + '</span>' : '') + (r.redactions && Object.keys(r.redactions).length ? ' \u00B7 personal data hidden in the log: ' + Object.keys(r.redactions).map(function (k) { return r.redactions[k] + ' ' + k.toLowerCase().replace('_', ' '); }).join(', ') : '') + '</div>'; return '<div class="muted small" style="margin-top:6px">' + esc(r.model) + ' \u00B7 ' + (r.usage.tokens_in + r.usage.tokens_out).toLocaleString('en-US') + ' tokens' + (r.usage.searches ? ' \u00B7 ' + r.usage.searches + ' web search' : '') + ' \u00B7 est. ' + money(r.usage.cost_usd) + (r.flags && r.flags.length ? ' \u00B7 <span style="color:#C2410C">\u26A0 ' + esc(r.flags.join('; ')) + '</span>' : '') + (r.redactions && Object.keys(r.redactions).length ? ' \u00B7 personal data hidden before sending: ' + Object.keys(r.redactions).map(function (k) { return r.redactions[k] + ' ' + k.toLowerCase().replace('_', ' '); }).join(', ') : '') + '</div>'; }

  SX.pages.copilot = function (tab) {
    var main = $('#main'); main.innerHTML = '<div class="loading">Loading...</div>';
    status().then(function () { ({ ask: ask, docs: docs, assess: assess, drafts: drafts, horizon: horizon }[tab] || ask)(main, tab); });
  };

  // ------------------------------------------------------------------ Ask (the BRD's layout: conversation, sources used, suggested prompts)
  function srcPanel(sources, web) {
    if (!sources || !sources.length) return '<div class="muted small">No sources were needed for this answer.</div>';
    var g = { record: [], doc: [], knowledge: [], web: [] }; sources.forEach(function (x) { (g[x.type] || (g[x.type] = [])).push(x); });
    var h = '';
    if (g.record.length) h += '<div class="small"><b>Register (live)</b></div>' + srcChips(g.record);
    if (g.doc.length) h += '<div class="small" style="margin-top:6px"><b>Approved documents</b></div>' + srcChips(g.doc);
    if (g.knowledge.length) h += '<div class="small" style="margin-top:6px"><b>Reference pack</b></div>' + srcChips(g.knowledge);
    if (g.web.length) h += '<div class="small" style="margin-top:6px"><b>Web</b></div>' + srcChips(g.web);
    return h.replace(/<div style="margin-top:8px"><span class="muted small">Sources consulted:<\/span> /g, '<div>');
  }
  function webBlock(w) {
    if (!w || !w.links) return '';
    var h = '<div style="margin-top:8px"><span class="muted small">Open this search in your own browser:</span> <a class="btn sm" target="_blank" rel="noopener noreferrer" href="' + esc(w.links.google) + '">Google</a> <a class="btn sm" target="_blank" rel="noopener noreferrer" href="' + esc(w.links.duckduckgo) + '">DuckDuckGo</a> <a class="btn sm" target="_blank" rel="noopener noreferrer" href="' + esc(w.links.bing) + '">Bing</a></div>';
    var rd = (w.results || []).filter(function (x) { return x.trusted; }).slice(0, 3);
    if (rd.length) h += '<div class="small" style="margin-top:4px">Read here: ' + rd.map(function (x) { return '<a href="#" data-read="' + esc(x.url) + '">' + esc((x.title || x.domain).slice(0, 50)) + '</a>'; }).join(' \u00B7 ') + '</div>';
    return h;
  }
  function readPage(url) {
    SX.toast('Reading the page...', 'ok');
    api('POST', '/api/ai/web/read', { url: url }).then(function (r) {
      SX.modal({ title: r.title || 'Page', wide: true, html: '<div class="small muted">' + esc(r.url) + (r.date ? ' \u00B7 ' + esc(r.date) : '') + ' \u00B7 <span class="badge" style="background:' + (r.trusted ? '#2FA84F' : '#F0A04B') + ';color:#fff">' + (r.trusted ? 'approved source' : 'not on the approved list') + '</span></div>' + (r.note ? '<div class="alert warn">' + esc(r.note) + '</div>' : '') + (r.flags && r.flags.length ? '<div class="alert warn">This page contains text that looks like an instruction. It was ignored.</div>' : '') + '<h4>Key points from the page</h4><ul>' + r.points.map(function (p) { return '<li>' + esc(p.text) + '</li>'; }).join('') + '</ul><p class="muted small">These are the page\u2019s own sentences, chosen by how central they are. <a href="' + esc(r.url) + '" target="_blank" rel="noopener noreferrer">Open the page</a> to read all of it.</p>', buttons: [{ label: 'Close' }] });
    }, function (e) { SX.toast(e.message, 'bad'); });
  }
  function bubbleHtml(m) { return '<div class="cp-msg cp-a" data-m="' + (m.id || '') + '"><span class="cp-ai">AI</span><span class="muted small">Sentinel Copilot</span>' + md(m.content, m.sources) + (m.id ? '' : '') + (m.extra || '') + (m.id ? '<div class="small" style="margin-top:6px"><button class="btn sm" data-fb="up">\uD83D\uDC4D Useful</button> <button class="btn sm" data-fb="down">\uD83D\uDC4E Wrong or unhelpful</button> <a href="#" data-rep="' + (m.log_id || '') + '" class="muted">Report a problem</a></div>' : '') + (m.follow && m.follow.length ? '<div style="margin-top:6px">' + m.follow.map(function (f) { return '<span class="cp-fu" data-fu="' + esc(f) + '">' + esc(f) + '</span>'; }).join('') + '</div>' : '') + '</div>'; }

  function ask(main, tab) {
    Promise.all([api('GET', '/api/ai/convs'), api('GET', '/api/ai/prompts'), api('GET', '/api/ai/docs').catch(function () { return { docs: [] }; })]).then(function (r) {
      var convs = r[0].convs, pr = r[1].prompts, docsA = r[2].docs.filter(function (d) { return d.status === 'approved' || d.mine; }), canWeb = ST && ST.caps && ST.caps.research;
      main.innerHTML = head(tab) + '<div class="grid"><div class="card s8"><div class="toolbar"><h3 style="margin:0">Conversation</h3><span class="sp" style="flex:1"></span><span class="muted small">Retrieval from approved content \u00B7 logged</span> <button class="btn sm" id="cpnew">New</button></div><div id="cpbox" class="cp-box"></div>' +
        '<textarea id="cpq" rows="2" placeholder="Ask about risks, controls, obligations, incidents, policy..." style="width:100%"></textarea><div class="toolbar" style="margin-top:6px;flex-wrap:wrap;gap:8px"><label class="small"><input type="checkbox" id="cpweb"' + (canWeb ? '' : ' disabled') + '> Search the web too (Google, DuckDuckGo, Wikipedia)' + (canWeb ? '' : ' <span class="muted">(needs Advanced mode)</span>') + '</label>' + (docsA.length ? '<select id="cpdoc" multiple size="1" style="min-width:200px;max-width:280px" title="Attach documents to this question">' + docsA.map(function (d) { return '<option value="' + d.id + '">' + esc(d.title) + ' v' + d.version + (d.status !== 'approved' ? ' (mine, pending)' : '') + '</option>'; }).join('') + '</select>' : '') + '<span class="sp" style="flex:1"></span><button class="btn p" id="cpsend" style="--c:' + COLOR + '"' + (ST && ST.on ? '' : ' disabled') + '>Ask</button></div>' +
        '<div style="margin-top:8px"><b class="small">Suggested prompts</b><div>' + pr.map(function (p) { return '<span class="cp-fu" data-p="' + esc(p) + '">' + esc(p) + '</span>'; }).join('') + '</div></div></div>' +
        '<div class="s4"><div class="card"><h3>Sources used</h3><div id="cpsrc"><div class="muted small">Answers cite the register, your approved documents and web pages, and respect your permissions. <b>Suggestions are never written to the register without approval.</b></div></div></div><div class="card" style="margin-top:12px;max-height:300px;overflow:auto"><h3>History</h3>' + (convs.length ? convs.map(function (c) { return '<div class="click" data-c="' + c.id + '" style="padding:6px 4px;border-bottom:1px solid #EEF1F6;' + (c.id === convId ? 'font-weight:700' : '') + '">' + esc(c.title || 'Conversation') + '<div class="muted small">' + SX.fmt(c.updated_at) + '</div></div>'; }).join('') : '<div class="muted small">No conversations yet.</div>') + '</div></div></div>';
      var box = $('#cpbox');
      function wire() {
        $$('[data-fb]', box).forEach(function (b) { b.addEventListener('click', function () { var id = b.closest('.cp-a').dataset.m; if (!id) return; api('POST', '/api/ai/messages/' + id + '/feedback', { value: b.dataset.fb }).then(function () { SX.toast('Thank you: this is used in the monthly quality report', 'ok'); }); }); });
        $$('[data-rep]', box).forEach(function (a) { a.addEventListener('click', function (e) { e.preventDefault(); report(a.dataset.rep); }); });
        $$('[data-fu]', box).forEach(function (a) { a.addEventListener('click', function () { send(a.dataset.fu); }); });
        $$('[data-read]', box).forEach(function (a) { a.addEventListener('click', function (e) { e.preventDefault(); readPage(a.dataset.read); }); });
      }
      function render(msgs) {
        box.innerHTML = msgs.length ? msgs.map(function (m) { return m.role === 'user' ? '<div class="cp-msg cp-u">' + esc(m.content) + '</div>' : bubbleHtml(m); }).join('') : '<div class="muted" style="padding:20px">Ask a question to begin. The Copilot reads the register and the approved documents you are allowed to see, and shows where each answer comes from.</div>';
        box.scrollTop = box.scrollHeight; wire();
        var last = msgs.filter(function (m) { return m.role === 'assistant'; }).pop(); if (last) $('#cpsrc').innerHTML = srcPanel(last.sources);
      }
      function load(id) { convId = id; if (!id) return render([]); api('GET', '/api/ai/convs/' + id).then(function (d) { render(d.messages); }); }
      function send(text) {
        if (!text.trim() || !(ST && ST.on)) return; var q = $('#cpq'); q.value = ''; if (box.innerHTML.indexOf('Ask a question to begin') >= 0) box.innerHTML = '';
        box.insertAdjacentHTML('beforeend', '<div class="cp-msg cp-u">' + esc(text) + '</div><div class="cp-msg cp-a" id="cpwait"></div>'); busy($('#cpwait')); box.scrollTop = box.scrollHeight;
        var sel = $('#cpdoc') ? Array.prototype.map.call($('#cpdoc').selectedOptions, function (o) { return +o.value; }) : []; $('#cpsend').disabled = true;
        api('POST', '/api/ai/chat', { message: text, conv_id: convId, web: $('#cpweb') && $('#cpweb').checked, doc_ids: sel }).then(function (r) {
          convId = r.conv_id; $('#cpwait').outerHTML = bubbleHtml({ id: r.message_id, content: r.text, sources: r.sources, log_id: r.log_id, follow: r.follow_ups, extra: (r.auto_web ? '<div class="small" style="margin-top:6px;color:#4B3BA8">\uD83C\uDF10 Sentinel looked this up on the web by itself, because it is outside what the system holds.</div>' : '') + webBlock(r.web) + usage(r) + (r.proposals && r.proposals.length ? '<div class="alert info small">' + r.proposals.length + ' draft(s) waiting in <a href="#/m/sentinel_copilot/drafts">Drafts for approval</a>.</div>' : '') });
          $('#cpsrc').innerHTML = srcPanel(r.sources); $('#cpsend').disabled = false; box.scrollTop = box.scrollHeight; wire();
        }, function (e) { $('#cpwait').outerHTML = '<div class="cp-msg cp-a"><div class="alert bad">' + esc(e.message) + '</div></div>'; $('#cpsend').disabled = !(ST && ST.on); });
      }
      $('#cpsend').addEventListener('click', function () { send($('#cpq').value); }); $('#cpq').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(this.value); } });
      $$('[data-p]', main).forEach(function (c) { c.addEventListener('click', function () { $('#cpq').value = c.dataset.p; send(c.dataset.p); }); });
      $$('[data-c]', main).forEach(function (c) { c.addEventListener('click', function () { convId = +c.dataset.c; ask(main, tab); }); });
      $('#cpnew').addEventListener('click', function () { convId = null; ask(main, tab); }); load(convId);
    });
  }

  // ---- Ask Sentinel: the button in the top bar, available on every page
  var quickConv = null;
  SX.askSentinel = function () {  // also answers questions about the world: it searches reliable sources on its own

    var m = SX.modal({ title: 'Ask Sentinel', wide: true, sticky: true, html: '<div class="muted small" style="margin-bottom:6px"><span class="cp-ai">AI</span> Answers come from your register and approved documents, with sources. Nothing is changed without approval.</div><div id="qbox" style="max-height:46vh;overflow:auto"></div><textarea id="qq" rows="2" placeholder="Ask about risks, controls, obligations, incidents, policy..." style="width:100%;margin-top:6px"></textarea><div id="qfu"></div>', buttons: [{ label: 'Close' }, { label: 'Open the full Copilot', onClick: function () { location.hash = '#/m/sentinel_copilot'; } }, { label: 'Ask', cls: 'p', onClick: function () { go($('#qq', m.el).value); return false; } }] });
    var q = $('#qq', m.el), box = $('#qbox', m.el);
    function go(text) {
      if (!text.trim()) return; q.value = ''; box.insertAdjacentHTML('beforeend', '<div class="cp-msg cp-u">' + esc(text) + '</div><div class="cp-msg cp-a" id="qwait"></div>'); busy($('#qwait', m.el)); box.scrollTop = box.scrollHeight;
      api('POST', '/api/ai/chat', { message: text, conv_id: quickConv }).then(function (r) {
        quickConv = r.conv_id; $('#qwait', m.el).outerHTML = '<div class="cp-msg cp-a"><span class="cp-ai">AI</span>' + md(r.text, r.sources) + srcChips(r.sources) + (r.auto_web ? '<div class="small" style="margin-top:6px;color:#4B3BA8">\uD83C\uDF10 Looked up on the web by itself.</div>' : '') + webBlock(r.web) + usage(r) + '</div>'; box.scrollTop = box.scrollHeight;
        $('#qfu', m.el).innerHTML = (r.follow_ups || []).map(function (f) { return '<span class="cp-fu" data-fu="' + esc(f) + '">' + esc(f) + '</span>'; }).join('');
        $$('[data-fu]', m.el).forEach(function (a) { a.addEventListener('click', function () { go(a.dataset.fu); }); }); $$('[data-read]', m.el).forEach(function (a) { a.addEventListener('click', function (e) { e.preventDefault(); readPage(a.dataset.read); }); });
      }, function (e) { $('#qwait', m.el).outerHTML = '<div class="cp-msg cp-a"><div class="alert bad">' + esc(e.message) + '</div></div>'; });
    }
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(q.value); } }); q.focus();
  };

  function report(logId) {
    var m = SX.modal({ title: 'Report a problem with an AI answer', sticky: true, html: '<label class="f">What went wrong?<select name="kind"><option value="wrong">The answer was wrong or invented something</option><option value="biased">The answer looked biased or unfair</option><option value="leak">It showed data I should not see</option><option value="unsafe">It was unsafe or inappropriate</option><option value="other">Something else</option></select></label><label class="f">Describe it<textarea name="description" rows="4"></textarea></label>', buttons: [{ label: 'Cancel' }, { label: 'Send to the AI owner', cls: 'p', onClick: function () { return api('POST', '/api/ai/incident', { kind: $('[name=kind]', m.el).value, description: $('[name=description]', m.el).value, log_id: logId ? +logId : null }).then(function () { SX.toast('Recorded as an AI incident. Thank you.', 'ok'); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] });
  }

  // ------------------------------------------------------------------ Documents
  function docs(main, tab) {
    api('GET', '/api/ai/docs').then(function (d) {
      var KIND = { policy: 'Policy', regulation: 'Regulation', brd: 'BRD', report: 'Report', standard: 'Standard', procedure: 'Procedure', other: 'Other' };
      main.innerHTML = head(tab) + '<div class="card"><h3>The approved content index <span class="muted small">documents the Copilot may rely on</span></h3><p class="muted small" style="margin-top:0">Upload policies, regulations, the BRD, reports or notes (.pdf, .docx, .pptx, .xlsx, .txt). A document becomes part of the Copilot\u2019s index only when <b>another person approves it</b>. A new version of the same title is compared with the one before, so a change in a policy or regulation is seen at once. You can analyse your own upload before it is approved.</p>' +
        (d.can.upload ? '<div class="toolbar" style="flex-wrap:wrap;gap:8px"><input type="file" id="dfile" accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv"><input id="dtitle" placeholder="Title (a new version keeps the same title)" style="min-width:260px"><select id="dkind">' + d.kinds.map(function (k) { return '<option value="' + k + '">' + KIND[k] + '</option>'; }).join('') + '</select><button class="btn p" id="dup" style="--c:' + COLOR + '">Upload</button></div>' : '') +
        '<table class="t" style="margin-top:10px"><tr><th>Document</th><th>Type</th><th>Version</th><th>Status</th><th>Uploaded</th><th></th></tr>' + (d.docs.length ? d.docs.map(function (x) {
          return '<tr><td><b>' + esc(x.title) + '</b><div class="muted small">' + esc(x.filename || '') + ' \u00B7 ' + (x.chars || 0).toLocaleString('en-US') + ' characters' + (x.quality === 'poor' ? ' \u00B7 <span style="color:#C2410C">text not readable by Sentinel</span>' : '') + '</div>' + (x.change ? '<div class="small" style="color:#7C5CE0">Changed from the previous version: ' + x.change.added + ' added, ' + x.change.removed + ' removed</div>' : '') + '</td><td>' + KIND[x.kind] + '</td><td>v' + x.version + '</td><td>' + badge(x.status) + '</td><td>' + esc(x.uploaded_by || '') + '<div class="muted small">' + SX.fmt(x.uploaded_at) + '</div></td><td style="text-align:right;white-space:nowrap">' +
            '<button class="btn sm" data-an="' + x.id + '">Analyse</button> ' + (x.change ? '<button class="btn sm" data-imp="' + x.id + '">Impact of the change</button> ' : '') + (x.quality === 'poor' && /\.pdf$/i.test(x.filename || '') ? (ST && ST.engine === 'claude' ? '<button class="btn sm" data-tr="' + x.id + '">Let the AI read it</button> ' : '<span class="muted small" data-needclaude="1">Scanned or special-font PDF: upload a Word or text version, or ask a System Administrator to connect Claude</span> ') : '') + (d.can.approve && x.status === 'pending' && !x.mine ? '<button class="btn sm p" data-ap="' + x.id + '" style="--c:#2FA84F">Approve</button> ' : '') + (x.status === 'pending' && x.mine ? '<span class="muted small">waiting for another person to approve</span> ' : '') + '<button class="btn sm d" data-dl="' + x.id + '">Delete</button></td></tr>';
        }).join('') : '<tr><td colspan="6" class="muted">No documents yet.</td></tr>') + '</table></div>';
      var up = $('#dup'); if (up) up.addEventListener('click', function () {
        var f = $('#dfile').files[0]; if (!f) { SX.toast('Choose a file first', 'bad'); return; }
        up.disabled = true; f.arrayBuffer().then(function (b) { return fetch('/api/ai/docs?title=' + encodeURIComponent($('#dtitle').value || f.name.replace(/\.[^.]+$/, '')) + '&kind=' + $('#dkind').value, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Sentinel': '1', 'X-Filename': f.name }, credentials: 'same-origin', body: b }); }).then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.message || 'Upload failed'); return j; }); }).then(function (j) { SX.toast('Uploaded ' + j.title + ' v' + j.version + (j.note ? '. ' + j.note : ''), j.quality === 'poor' ? 'bad' : 'ok'); docs(main, tab); }, function (e) { up.disabled = false; SX.toast(e.message, 'bad'); });
      });
      $$('[data-ap]', main).forEach(function (b) { b.addEventListener('click', function () { api('POST', '/api/ai/docs/' + b.dataset.ap + '/approve').then(function () { SX.toast('Approved into the Copilot\u2019s index', 'ok'); docs(main, tab); }, function (e) { SX.toast(e.message, 'bad'); }); }); });
      $$('[data-dl]', main).forEach(function (b) { b.addEventListener('click', function () { var q = SX.modal({ title: 'Delete this document', sticky: true, html: '<label class="f">Reason<textarea name="w" rows="3"></textarea></label><p class="muted small">It goes to the Recycle Bin for 90 days.</p>', buttons: [{ label: 'Cancel' }, { label: 'Delete', cls: 'd', onClick: function () { return api('POST', '/api/ai/docs/' + b.dataset.dl + '/delete', { reason: $('[name=w]', q.el).value }).then(function () { docs(main, tab); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] }); }); });
      $$('[data-an]', main).forEach(function (b) { b.addEventListener('click', function () { analyseDlg(+b.dataset.an, function () { docs(main, tab); }); }); });
      $$('[data-tr]', main).forEach(function (b) { b.addEventListener('click', function () { rawPdf(function () { b.disabled = true; b.textContent = 'Reading...'; api('POST', '/api/ai/docs/' + b.dataset.tr + '/transcribe', { allow_raw_pdf: true }).then(function (r) { SX.toast('Read ' + r.pages + ' pages; it can now be searched and cited', 'ok'); docs(main, tab); }, function (e) { b.disabled = false; SX.toast(e.message, 'bad'); }); }); }); });
      $$('[data-imp]', main).forEach(function (b) { b.addEventListener('click', function () { b.disabled = true; b.textContent = 'Analysing...'; api('POST', '/api/ai/docs/' + b.dataset.imp + '/impact').then(function (br) { b.disabled = false; b.textContent = 'Impact of the change'; briefDlg(br); }, function (e) { b.disabled = false; b.textContent = 'Impact of the change'; SX.toast(e.message, 'bad'); }); }); });
    });
  }
  function badge(s) { var c = { approved: '#2FA84F', pending: '#FDB022', archived: '#98A2B3' }[s] || '#98A2B3'; return '<span class="badge" style="background:' + c + ';color:' + (s === 'pending' ? '#3A2600' : '#fff') + '">' + esc(s) + '</span>'; }
  function rawPdf(go) { var m = SX.modal({ title: 'The AI will read the PDF itself', sticky: true, html: '<p>Sentinel cannot read the text of this PDF (scanned pages or special fonts), so the AI reads the PDF directly. <b>A PDF cannot be redacted first.</b> Only continue if it holds no personal or customer data.</p><label><input type="checkbox" id="rawok"> I confirm this PDF holds no personal or customer data</label>', buttons: [{ label: 'Cancel' }, { label: 'Continue', cls: 'p', onClick: function () { if (!$('#rawok', m.el).checked) { SX.toast('Tick the confirmation first', 'bad'); return false; } go(); } }] }); }
  function analyseDlg(id, done) {
    var m = SX.modal({ title: 'Analyse the document', wide: true, sticky: true, html: '<label class="f">What do you need?<select name="task"><option value="summary">Summarise it</option><option value="obligations">List the obligations, deadlines and who is responsible</option><option value="risks">Which enterprise risks does it create or address?</option><option value="questions">Answer my question about it</option><option value="compare">What changed from the previous version?</option></select></label><label class="f">Your question (for \u201Canswer my question\u201D)<input name="q"></label><div id="anr" style="margin-top:8px"></div>',
      buttons: [{ label: 'Close' }, { label: 'Analyse', cls: 'p', onClick: function () { run(false); return false; } }] });
    function run(raw) {
      var box = $('#anr', m.el); busy(box); api('POST', '/api/ai/analyse', { doc_id: id, task: $('[name=task]', m.el).value, question: $('[name=q]', m.el).value, allow_raw_pdf: raw }).then(function (r) { box.innerHTML = '<div class="cp-a cp-msg"><span class="cp-ai">AI</span>' + md(r.text, r.sources) + srcChips(r.sources) + usage(r) + '</div>'; done && done(); }, function (e) { if (e.data && e.data.error === 'raw_pdf') { box.innerHTML = ''; rawPdf(function () { run(true); }); } else box.innerHTML = '<div class="alert bad">' + esc(e.message) + '</div>'; });
    }
  }

  // ------------------------------------------------------------------ Assess
  function assess(main, tab) {
    Promise.all([api('GET', '/api/ai/docs'), api('GET', '/api/risks')]).then(function (r) {
      var docsA = r[0].docs.filter(function (d) { return (d.status === 'approved' || d.mine) && d.quality === 'good' || (d.chars > 0); }), risks = (r[1].risks || []).filter(function (x) { return !x.is_sample; });
      main.innerHTML = head(tab) + '<div class="grid"><div class="card s6"><h3>Draft risks from a document or a description</h3><p class="muted small" style="margin-top:0">The Copilot reads the material, checks the register so it does not duplicate a risk, and drafts new risks on the ranked matrix with a rationale, evidence and a confidence. <b>Nothing is added to the register</b>: each draft appears in Drafts for approval.</p>' +
        '<label class="f">Document(s), for example the BRD<select id="adoc" multiple size="4" style="width:100%">' + docsA.map(function (d) { return '<option value="' + d.id + '">' + esc(d.title) + ' v' + d.version + (d.kind === 'brd' ? ' (BRD)' : '') + '</option>'; }).join('') + '</select></label><label class="f">Or describe the situation<textarea id="atxt" rows="4" placeholder="For example: we plan to launch a new agent cash-out channel in rural areas..."></textarea></label><label class="f">Most drafts to make<input id="amax" type="number" min="1" max="12" value="6" style="width:80px"></label><button class="btn p" id="anew" style="--c:' + COLOR + '">Draft for review</button></div>' +
        '<div class="card s6"><h3>Review ratings of existing risks</h3><p class="muted small" style="margin-top:0">The Copilot compares each risk\u2019s rating with its controls, indicators and incidents and proposes a different rating <b>only where it has a reasoned case</b>. Whoever owns the risk, the same standard applies. A proposal changes nothing until you accept it, and an accepted rating sends the risk back through review and approval.</p>' +
        '<label class="f">Risks to review<select id="arisk" multiple size="7" style="width:100%">' + risks.slice(0, 120).map(function (x) { return '<option value="' + esc(x.source_ref || x.ref) + '">' + esc((x.source_ref || x.ref) + ' \u2014 ' + x.title.slice(0, 70)) + '</option>'; }).join('') + '</select></label><button class="btn p" id="arate" style="--c:' + COLOR + '">Review the ratings</button></div>' +
        '<div class="card s12" id="aout" style="display:none"></div></div>';
      function show(res) {
        var o = $('#aout'); o.style.display = ''; o.innerHTML = '<div class="cp-a cp-msg" style="max-width:none"><span class="cp-ai">AI</span>' + md(res.text, res.sources) + srcChips(res.sources) + usage(res) + '</div>' + (res.proposals.length ? '<div class="alert info"><b>' + res.proposals.length + ' draft(s)</b> are waiting for a decision. <a href="#/m/sentinel_copilot/drafts" class="btn sm p" style="--c:' + COLOR + '">Open Drafts for approval</a></div>' : '<div class="muted">No drafts were made.</div>');
      }
      function go(btn, body) { var o = $('#aout'); o.style.display = ''; busy(o, 'Reading and assessing... this can take a few minutes for a long document.'); btn.disabled = true; api('POST', '/api/ai/assess', body).then(function (res) { btn.disabled = false; show(res); }, function (e) { btn.disabled = false; o.innerHTML = '<div class="alert bad">' + esc(e.message) + '</div>'; }); }
      $('#anew').addEventListener('click', function () { go(this, { mode: 'new', doc_ids: Array.prototype.map.call($('#adoc').selectedOptions, function (o) { return +o.value; }), text: $('#atxt').value, max_risks: +$('#amax').value }); });
      $('#arate').addEventListener('click', function () { var refs = Array.prototype.map.call($('#arisk').selectedOptions, function (o) { return o.value; }); if (!refs.length) { SX.toast('Choose the risks to review', 'bad'); return; } go(this, { mode: 'rate', risk_refs: refs }); });
    });
  }

  // ------------------------------------------------------------------ Drafts awaiting approval
  var CELL = {};
  function rk(l, c) { return CELL[l + '-' + c]; }
  function drafts(main, tab) {
    var statusSel = main._st || 'pending';
    Promise.all([api('GET', '/api/ai/proposals?status=' + statusSel), api('GET', '/api/register/key').catch(function () { return null; })]).then(function (r) {
      (r[1] && r[1].auditor.cells || []).forEach(function (c) { CELL[c.l + '-' + c.c] = { rank: c.rank, level: c.level }; });
      var d = r[0]; main.innerHTML = head(tab) + '<div class="toolbar"><h3 style="margin:0">Drafts awaiting a decision</h3><span class="sp" style="flex:1"></span>' + ['pending', 'accepted', 'edited', 'rejected'].map(function (s) { return '<span class="chip' + (s === statusSel ? ' on' : '') + '" style="--c:' + COLOR + '" data-s="' + s + '">' + s + '</span>'; }).join('') + '</div>' +
        '<p class="muted small">You are the reviewer. Accepting creates a <b>draft</b> in the register (or changes a rating and sends the risk back through review and approval); it is recorded in the risk\u2019s history and the audit trail with your name. Rejecting needs a short reason, which feeds the Copilot\u2019s quality report.</p>' + (d.proposals.length ? d.proposals.map(card).join('') : '<div class="card muted">Nothing here.</div>');
      $$('[data-s]', main).forEach(function (c) { c.addEventListener('click', function () { main._st = c.dataset.s; drafts(main, tab); }); });
      $$('[data-dec]', main).forEach(function (b) { b.addEventListener('click', function () { decide(+b.dataset.id, b.dataset.dec, d.proposals.filter(function (p) { return p.id === +b.dataset.id; })[0], function () { drafts(main, tab); status(); }); }); });
    });
  }
  function cellChip(l, c) { var x = rk(l, c); return '<span class="badge" style="background:' + (x ? LV[x.level] : '#98A2B3') + ';color:' + (x && x.level === 'Medium' ? '#3A2600' : '#fff') + '">' + l + '\u00D7' + c + (x ? ' = ' + x.rank : '') + '</span>'; }
  function card(p) {
    var x = p.payload, title = p.kind === 'risk' ? x.title : p.kind === 'rating' ? 'Rating of ' + x.risk_ref : x.title, conf = p.confidence == null ? null : Math.round(p.confidence * 100);
    var body = '';
    if (p.kind === 'risk') body = '<div>Inherent ' + cellChip(x.inh_l, x.inh_c) + ' \u2192 residual ' + cellChip(x.res_l, x.res_c) + (x.emv_i ? ' \u00B7 EMV-i $' + Number(x.emv_i).toLocaleString('en-US') : '') + ' \u00B7 owner role: ' + esc(x.owner_role || 'not set') + '</div><div class="small" style="margin-top:4px"><b>Description:</b> ' + esc(x.description || '') + '<br><b>Root cause:</b> ' + esc(x.root_cause || '') + '<br><b>Consequences:</b> ' + esc(x.consequences || '') + '</div>' + ((x.controls || []).length ? '<div class="small" style="margin-top:4px"><b>Controls suggested:</b> ' + x.controls.map(function (c) { return '<span class="tag">' + esc(c.category) + '</span> ' + esc(c.statement); }).join('; ') + '</div>' : '') + ((x.kris || []).length ? '<div class="small"><b>KRIs suggested:</b> ' + x.kris.map(esc).join('; ') + '</div>' : '');
    else if (p.kind === 'rating') body = '<div>Current residual ' + cellChip(x.was.res_l, x.was.res_c) + ' \u2192 proposed inherent ' + cellChip(x.inh_l, x.inh_c) + ' and residual ' + cellChip(x.res_l, x.res_c) + '</div>';
    else body = '<div class="small">' + esc(x.description || '') + '<br>Owner role: ' + esc(x.owner_role || 'Head of Risk') + ' \u00B7 due in ' + x.due_days + ' days' + (x.risk_ref ? ' \u00B7 for ' + esc(x.risk_ref) : '') + '</div>';
    return '<div class="cp-prop"><div class="toolbar"><span class="cp-ai">AI DRAFT</span><b>' + esc(title) + '</b><span class="tag">' + p.kind + '</span><span class="sp" style="flex:1"></span>' + (conf != null ? '<span class="small">confidence ' + conf + '% <span class="cp-bar"><i style="width:' + conf + '%"></i></span></span>' : '') + '</div>' + body + '<div class="small" style="margin-top:6px;padding:6px 8px;background:#F8FAFD;border-radius:6px"><b>Rationale:</b> ' + esc(p.rationale || '') + '</div>' + ((p.evidence || []).length ? '<div style="margin-top:4px">' + p.evidence.map(function (e) { return '<span class="cp-src">' + esc(e) + '</span>'; }).join('') + '</div>' : '') +
      '<div class="muted small" style="margin-top:4px">Requested by ' + esc(p.requested_by_name || '') + ' \u00B7 ' + SX.fmt(p.created_at) + ' \u00B7 ' + esc(p.model || '') + (p.status !== 'pending' ? ' \u00B7 <b>' + p.status + '</b> by ' + esc(p.decided_by || '') + (p.applied_ref ? ' \u2192 ' + esc(p.applied_ref) : '') + (p.decision_note ? ': ' + esc(p.decision_note) : '') : '') + '</div>' + (p.status === 'pending' ? '<div class="toolbar" style="margin-top:8px"><button class="btn p" data-dec="accept" data-id="' + p.id + '" style="--c:#2FA84F">Accept</button><button class="btn" data-dec="edit" data-id="' + p.id + '">Edit then accept</button><button class="btn d" data-dec="reject" data-id="' + p.id + '">Reject</button></div>' : '') + '</div>';
  }
  function decide(id, dec, p, done) {
    var x = p.payload, fields = '';
    if (dec === 'edit') {
      fields = (p.kind === 'risk' || p.kind === 'action' ? '<label class="f">Title<input name="title" value="' + esc(x.title) + '"></label>' : '') + (p.kind !== 'action' ? ['inh_l', 'inh_c', 'res_l', 'res_c'].map(function (k) { return '<label class="f" style="display:inline-block;width:23%">' + { inh_l: 'Inherent likelihood', inh_c: 'Inherent consequence', res_l: 'Residual likelihood', res_c: 'Residual consequence' }[k] + '<input name="' + k + '" type="number" min="1" max="5" value="' + x[k] + '"></label>'; }).join('') : '<label class="f">Due in days<input name="due_days" type="number" min="1" max="365" value="' + x.due_days + '"></label>') + (p.kind === 'risk' ? '<label class="f">Owner role<input name="owner_role" value="' + esc(x.owner_role || '') + '"></label>' : '');
    }
    var m = SX.modal({ title: { accept: 'Accept this draft', edit: 'Edit, then accept', reject: 'Reject this draft' }[dec], wide: dec === 'edit', sticky: true, html: fields + '<label class="f">' + (dec === 'reject' ? 'Why are you rejecting it? (required)' : 'Your note (recorded with your name)') + '<textarea name="note" rows="3"></textarea></label>',
      buttons: [{ label: 'Cancel' }, { label: dec === 'reject' ? 'Reject' : 'Accept', cls: dec === 'reject' ? 'd' : 'p', onClick: function () {
        var body = { decision: dec, note: $('[name=note]', m.el).value };
        if (dec === 'edit') { body.edits = {}; $$('input[name]', m.el).forEach(function (i) { if (i.name !== 'note') body.edits[i.name] = i.type === 'number' ? +i.value : i.value; }); }
        return api('POST', '/api/ai/proposals/' + id + '/decide', body).then(function (r) { SX.toast(dec === 'reject' ? 'Rejected' : 'Done: ' + (r.ref || ''), 'ok'); done(); }, function (e) { SX.toast(e.message, 'bad'); return false; });
      } }] });
  }

  // ------------------------------------------------------------------ Horizon
  function horizon(main, tab) {
    var st = main._bs || 'new';
    Promise.all([api('GET', '/api/ai/briefs?status=' + st), api('GET', '/api/ai/watch')]).then(function (r) {
      var bs = r[0].briefs, w = r[1], adv = ST && ST.caps && ST.caps.horizon, sev = ['', 'Noise', 'Background', 'Review', 'Act this week', 'Board attention'];
      main.innerHTML = head(tab) + '<div class="grid"><div class="card s8"><div class="toolbar"><h3 style="margin:0">Developments and their impact</h3><span class="sp" style="flex:1"></span>' + ['new', 'reviewed', 'escalated', 'dismissed'].map(function (s) { return '<span class="chip' + (s === st ? ' on' : '') + '" style="--c:' + COLOR + '" data-b="' + s + '">' + s + '</span>'; }).join('') + '<button class="btn sm p" id="himp" style="--c:' + COLOR + '">Analyse a development</button></div><p class="muted small">Found by watching approved sources, then analysed against <b>your</b> register, indicators and documents. Briefs are <b>AI-prepared and unverified</b>: the Risk Office reviews each one. The watch owners are notified by e-mail when one is found.</p>' +
        (bs.length ? bs.map(function (b) { return '<div class="cp-prop click" data-br="' + b.id + '"><div class="toolbar"><span class="badge" style="background:' + ['#98A2B3', '#98A2B3', '#6B7A8C', '#F97316', '#EF2B2B', '#9B1C1C'][b.severity] + ';color:#fff">' + b.severity + ' \u00B7 ' + sev[b.severity] + '</span><b>' + esc(b.title) + '</b><span class="sp" style="flex:1"></span><span class="cp-ai">AI-PREPARED</span></div><div class="small muted">' + esc(b.topic || '') + ' \u00B7 ' + esc(b.source || '') + ' \u00B7 ' + esc(b.published || SX.fmt(b.ts)) + '</div>' + (b.impact_headline ? '<div style="margin-top:4px"><b>' + esc(b.impact_headline) + '</b></div>' : '') + '<div class="small" style="margin-top:2px">' + esc((b.summary || '').slice(0, 260)) + '</div></div>'; }).join('') : '<div class="muted" style="padding:14px">No ' + st + ' briefs.' + (adv ? '' : ' Horizon scanning needs Advanced mode.') + '</div>') + '</div>' +
        '<div class="card s4"><h3>What is watched</h3><table class="t">' + w.watch.map(function (x) { return '<tr><td><b>' + esc(x.name) + '</b><div class="muted small">every ' + x.freq_hours + ' h \u00B7 ' + (x.last_run ? 'last ' + SX.fmt(x.last_run) : 'not yet run') + '</div></td><td style="text-align:right;white-space:nowrap">' + (w.can.edit ? '<label class="small"><input type="checkbox" data-wa="' + x.id + '"' + (x.active ? ' checked' : '') + '> on</label> ' + (adv ? '<button class="btn sm" data-ws="' + x.id + '">Scan now</button>' : '') : (x.active ? 'on' : 'off')) + '</td></tr>'; }).join('') + '</table>' + (w.can.edit ? '<button class="btn sm" id="wadd" style="margin-top:8px">Add something to watch</button>' : '') + '<div class="muted small" style="margin-top:8px">Brief threshold: severity ' + w.min_severity + ' or higher. Only approved sources count (see AI Governance).</div></div></div>';
      $$('[data-b]', main).forEach(function (c) { c.addEventListener('click', function () { main._bs = c.dataset.b; horizon(main, tab); }); });
      $$('[data-br]', main).forEach(function (c) { c.addEventListener('click', function () { api('GET', '/api/ai/briefs/' + c.dataset.br).then(function (b) { briefDlg(b, function () { horizon(main, tab); status(); }); }); }); });
      $$('[data-wa]', main).forEach(function (c) { c.addEventListener('change', function () { api('POST', '/api/ai/watch/' + c.dataset.wa, { active: c.checked }); }); });
      $$('[data-ws]', main).forEach(function (b) { b.addEventListener('click', function () { b.disabled = true; b.textContent = 'Scanning...'; api('POST', '/api/ai/watch/' + b.dataset.ws + '/scan').then(function (r) { SX.toast('Found ' + r.found + ' development(s); ' + r.briefs.length + ' new brief(s)', 'ok'); horizon(main, tab); status(); }, function (e) { b.disabled = false; b.textContent = 'Scan now'; SX.toast(e.message, 'bad'); }); }); });
      $('#himp').addEventListener('click', function () { var m = SX.modal({ title: 'Analyse a development', wide: true, sticky: true, html: '<p class="muted small" style="margin-top:0">Paste the text of an announcement, a regulation or a news item, or give a link to an approved source. The Copilot analyses what it means for EcoCash\u2019s risks.</p><label class="f">Headline<input name="title"></label><label class="f">Link (approved sources only, optional)<input name="url"></label><label class="f">Text<textarea name="text" rows="6"></textarea></label>', buttons: [{ label: 'Cancel' }, { label: 'Analyse', cls: 'p', onClick: function () { var btn = this; return api('POST', '/api/ai/impact', { title: $('[name=title]', m.el).value, url: $('[name=url]', m.el).value, text: $('[name=text]', m.el).value }).then(function (b) { briefDlg(b, function () { horizon(main, tab); status(); }); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] }); });
      var wa = $('#wadd'); if (wa) wa.addEventListener('click', function () { var m = SX.modal({ title: 'Add something to watch', sticky: true, html: '<label class="f">Name<input name="name"></label><label class="f">What to watch for<textarea name="query" rows="3" placeholder="For example: Reserve Bank directives on agent banking limits"></textarea></label><label class="f">Check every (hours)<input name="freq" type="number" value="24" min="6" max="720"></label>', buttons: [{ label: 'Cancel' }, { label: 'Add', cls: 'p', onClick: function () { return api('POST', '/api/ai/watch', { name: $('[name=name]', m.el).value, query: $('[name=query]', m.el).value, freq_hours: +$('[name=freq]', m.el).value }).then(function () { horizon(main, tab); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] }); });
    });
  }
  function briefDlg(b, done) {
    var i = b.impact || {}, ar = i.affected_risks || [];
    var h = '<div class="alert warn small"><span class="cp-ai">AI-PREPARED</span> This analysis is not verified. Check the source and the reasoning before acting on it.</div>' +
      '<div class="small muted">' + esc(b.source || '') + ' \u00B7 ' + esc(b.published || '') + (b.url ? ' \u00B7 <a href="' + esc(b.url) + '" target="_blank" rel="noopener noreferrer">open the source</a>' : '') + ' \u00B7 severity ' + b.severity + '/5' + (i.time_horizon ? ' \u00B7 ' + esc(i.time_horizon) : '') + (i.confidence != null ? ' \u00B7 confidence ' + Math.round(i.confidence * 100) + '%' : '') + '</div><h3 style="margin:8px 0 2px">' + esc(i.headline || b.title) + '</h3><p>' + esc(i.why_it_matters || b.summary || '') + '</p>' +
      (i.raw ? '<div class="cp-a cp-msg" style="max-width:none">' + md(i.raw) + '</div>' : '') +
      (ar.length ? '<h4>Risks it may affect</h4><table class="t"><tr><th>Risk</th><th>Direction</th><th>Why</th><th>Suggested review</th></tr>' + ar.map(function (r) { var s = (b.sources || []).filter(function (x) { return x.type === 'record' && x.ref === r.ref; })[0]; return '<tr><td>' + (s && s.id ? '<a href="#/m/risk_register/' + s.id + '">' + esc(r.ref) + '</a>' : esc(r.ref)) + '</td><td>' + esc(r.direction) + '</td><td>' + esc(r.reason) + '</td><td>' + esc(r.suggested_review || '') + '</td></tr>'; }).join('') + '</table>' : '') +
      ((i.kri_kpi_effects || []).length ? '<h4>Indicators</h4><ul>' + i.kri_kpi_effects.map(function (k) { return '<li><b>' + esc(k.code) + '</b>: ' + esc(k.effect) + '</li>'; }).join('') + '</ul>' : '') + (i.financial_effect ? '<h4>Financial effect</h4><p>' + esc(i.financial_effect) + '</p>' : '') +
      ((i.recommended_actions || []).length ? '<h4>Suggested actions</h4><ul>' + i.recommended_actions.map(function (a) { return '<li>' + esc(a.action) + ' <span class="muted small">(' + esc(a.owner_role || '') + ', ' + esc(a.timing || '') + ')</span></li>'; }).join('') + '</ul>' : '') +
      ((i.assumptions || []).length ? '<h4>Assumptions</h4><ul>' + i.assumptions.map(function (a) { return '<li>' + esc(a) + '</li>'; }).join('') + '</ul>' : '') + ((i.unknowns || []).length ? '<h4>What we do not know</h4><ul>' + i.unknowns.map(function (a) { return '<li>' + esc(a) + '</li>'; }).join('') + '</ul>' : '') + srcChips(b.sources);
    var btns = [{ label: 'Close' }];
    if (b.status === 'new' && SX.can('sentinel_copilot', 'edit')) btns = btns.concat([{ label: 'Mark reviewed', onClick: function () { return rev('reviewed', false); } }, { label: 'Dismiss', cls: 'd', onClick: function () { return rev('dismissed', true); } }, { label: 'Turn into an action', cls: 'p', onClick: function () { return rev('escalated', true); } }]);
    var m = SX.modal({ title: 'Development brief', wide: true, html: h, buttons: btns });
    function rev(st, need) {
      var q = SX.modal({ title: { reviewed: 'Mark as reviewed', dismissed: 'Dismiss this brief', escalated: 'Turn this into an action' }[st], sticky: true, html: '<label class="f">' + (need ? 'Note (required)' : 'Note (optional)') + '<textarea name="n" rows="3"></textarea></label>' + (st === 'escalated' ? '<p class="muted small">An action is created for the first suggested step, due in 14 days, owned by the suggested role.</p>' : ''), buttons: [{ label: 'Cancel' }, { label: 'Confirm', cls: 'p', onClick: function () { return api('POST', '/api/ai/briefs/' + b.id + '/review', { status: st, note: $('[name=n]', q.el).value }).then(function (r) { SX.toast(r.action ? 'Action ' + r.action + ' created' : 'Recorded', 'ok'); m.close(); done && done(); }, function (e) { SX.toast(e.message, 'bad'); return false; }); } }] });
      return false;
    }
  }
})();
