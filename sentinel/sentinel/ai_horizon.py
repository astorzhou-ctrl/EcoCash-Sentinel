"""Horizon scanning and impact analysis (the 'interesting developments' part of the Copilot).
A watch-list of topics is researched on a schedule through approved sources only. When something material is found (a monetary-policy decision, a new directive, a
regulatory change), the Copilot prepares an impact analysis grounded in EcoCash's own register, KRIs and documents, and the watch owners are told that an
AI-prepared brief is waiting. The brief is labelled as unverified; a person reviews it, dismisses it, or turns it into an action. The AI never escalates by itself."""
import datetime
import hashlib
import json
import math
import re
import threading
import time

from . import db as dbm
from . import ai_agent, ai_engine, ai_gov, ai_kb, ai_tools, ai_web, p5
from .api import router, need, need_str
from .core import audit, now, outbox
from .web import HTTPError

DEFAULT_WATCH = [
    ("Monetary policy and the exchange rate", "Reserve Bank of Zimbabwe Monetary Policy Committee decisions, policy interest rate, ZiG exchange rate, inflation and money supply", 24),
    ("Payment systems and mobile money regulation", "Reserve Bank of Zimbabwe payment systems directives, mobile money, fintech and agent banking regulation, transaction limits", 24),
    ("Anti-money-laundering and terrorist financing", "FATF and ESAAMLG assessments of Zimbabwe, Financial Intelligence Unit directives, AML/CFT obligations for mobile money operators", 72),
    ("Data protection and cyber law", "POTRAZ data protection authority guidance, Cyber and Data Protection Act regulations, breach notification, cross-border data transfer", 72),
    ("Tax and levies on electronic payments", "ZIMRA and Ministry of Finance measures affecting mobile money transfers, intermediated money transfer tax, VAT and levies on fintech", 72),
    ("Fraud and cyber threats to mobile money", "SIM-swap fraud, mobile money scams, telecom and fintech cyber incidents in Zimbabwe and the SADC region", 48),
    ("AI regulation and standards", "NIST AI risk management, ISO/IEC 42001, EU AI Act implementation and guidance relevant to financial services", 168),
]
_lock = threading.Lock()


def seed(db):
    if db.execute("SELECT COUNT(*) n FROM ai_watch").fetchone()["n"] == 0:
        for name, q, h in DEFAULT_WATCH:
            db.execute("INSERT INTO ai_watch(kind,name,query,freq_hours,active,created_at) VALUES('topic',?,?,?,1,?)", (name, q, h, now()))


def _hours_since(ts):
    if not ts:
        return None
    try:
        t = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 3600


SCAN_TASK = """TASK: Horizon scan for EcoCash's risk office.
Topic: {name}. Focus: {query}.
Search ONLY the approved sources (the search tool is already limited to them). Find developments announced or published in roughly the last {days} days that could change EcoCash's risk profile. Use web_search (at most 5 searches).
Return ONLY one JSON object, no other text:
{{"developments":[{{"title":"","published":"YYYY-MM-DD or null","source_url":"","source_name":"","summary":"2-3 factual sentences","materiality":1-5,"why_it_matters":"one sentence"}}],"nothing_found":true|false,"searched":"what you looked for"}}
Materiality: 5 = needs Board attention now; 4 = Head of Risk should act this week; 3 = worth a documented review; 2 = background; 1 = noise. Report at most {mx} developments, most material first. Every item must come from a page you actually read, with its real URL. If nothing material was published, return an empty list. Never guess or fill gaps from memory."""
IMPACT_TASK = """TASK: Impact analysis of an external development on EcoCash.
Ground the analysis in EcoCash's own data: call portfolio_summary, search_register and get_risk for the risks it could touch, kpi_status for indicators, and search_knowledge for what our approved documents say. Do not rely on general knowledge for facts about EcoCash.
Return ONLY one JSON object, no other text:
{{"headline":"","why_it_matters":"2-4 sentences","severity":1-5,"time_horizon":"immediate|3 months|12 months","affected_risks":[{{"ref":"register reference","direction":"increase|decrease|new","reason":"","suggested_review":""}}],"kri_kpi_effects":[{{"code":"","effect":""}}],"financial_effect":"qualitative, or quantified with the assumptions stated","recommended_actions":[{{"action":"","owner_role":"a job title","timing":""}}],"assumptions":[""],"unknowns":[""],"confidence":0-1,"what_would_change_this":[""]}}
Do not state rating changes as facts: say which risks to review and why. If the development does not affect EcoCash, say so with a low severity. Keep it factual and say what you could not verify."""


def _dedupe(title, url, published):
    return hashlib.sha256(((url or "") + "|" + re.sub(r"\W+", " ", (title or "").lower())[:120]).encode()).hexdigest()[:24]


def impact(db, ctx, dev, origin, watch=None, user=None):
    """Prepare and store a brief. dev: {title, summary, url, source, published, text}. Returns the brief id, or None when it was already known."""
    dd = _dedupe(dev.get("title"), dev.get("url"), dev.get("published"))
    if db.execute("SELECT 1 FROM ai_briefs WHERE dedupe=?", (dd,)).fetchone():
        return None
    body = "Development: %s\nSource: %s (%s)\nPublished: %s\nSummary: %s" % (dev.get("title"), dev.get("source") or "", dev.get("url") or "no link", dev.get("published") or "unknown", dev.get("summary") or "")
    docs = [{"title": "Source text: " + (dev.get("title") or "development")[:80], "version": 1, "text": dev["text"]}] if dev.get("text") else None
    if ai_agent.is_local(db):  # the built-in engine: grounded in the register by rule
        ai_gov.gate(db, None if getattr(ctx, "system", False) else ctx.user, "horizon" if origin != "user" else "chat")
        j = ai_engine.impact_of(db, ctx, dev.get("title"), (dev.get("summary") or "") + " " + (dev.get("text") or "")[:20000])
        rows, _ = ai_engine.scope_rows(db, ctx); recs = [ai_engine.rec(r) for r in (ai_engine.find_risk(rows, x["ref"]) for x in j["affected_risks"]) if r]
        log_id = ai_gov.log_call(db, None if getattr(ctx, "system", False) else ctx.user, "impact_analysis", ai_engine.ENGINE_VERSION, body[:3000], json.dumps(j)[:6000], [{"name": "impact analysis", "args": ", ".join(j["topics"])}], recs, {})
        class _R:  # the same fields the Claude path reads
            pass
        res = _R(); res.text = json.dumps(j); res.status = "ok"; res.sources = recs; res.log_id = log_id
    else:
        res = ai_agent.run_agent(db, ctx, "impact_analysis", "horizon" if origin != "user" else "chat", body, docs=docs, tier="deep", extra_system=IMPACT_TASK, tool_names=["portfolio_summary", "search_register", "get_risk", "risk_controls", "kpi_status", "recent_incidents", "search_knowledge", "risk_methodology"], max_turns=14)
        j = ai_agent.parse_json(res.text) if res.status == "ok" else None
    if ai_agent.is_local(db):
        j = json.loads(res.text)
    sev = None
    if j:
        try:
            sev = max(1, min(5, int(j.get("severity"))))
        except (TypeError, ValueError):
            sev = None
    sev = sev or int(dev.get("materiality") or 3)
    sources = [{"type": "web", "url": dev["url"], "title": dev.get("title") or dev["url"], "trusted": ai_gov.trust_tier(ai_gov.settings(db), dev["url"]) == "trusted"}] if dev.get("url") else []
    sources += [s for s in res.sources if s["type"] != "web" or s["url"] != dev.get("url")]
    bid = db.execute("INSERT INTO ai_briefs(ts,watch_id,topic,title,url,source,published,severity,summary,impact,sources,status,dedupe,log_id,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?,'new',?,?,?)",
                     (now(), watch["id"] if watch else None, watch["name"] if watch else "Added by " + (user["full_name"] if user else "a user"), (dev.get("title") or "Development")[:240], dev.get("url"), dev.get("source"), dev.get("published"), sev, dev.get("summary"),
                      json.dumps(j) if j else json.dumps({"raw": res.text[:6000], "note": "The analysis could not be put in the standard form; read the text."}), json.dumps(sources), dd, res.log_id, origin)).lastrowid
    try:  # every brief of severity 2 or more also appears on the Emerging Radar
        from . import radar
        radar.signal_from_brief(db, bid)
    except Exception:
        pass
    if sev >= ai_gov.settings(db)["horizon"]["min_severity"]:
        notify(db, bid)
    return bid


def notify(db, bid):
    """Tell the watch owners that an AI-prepared brief is waiting. A rule sends this message; the AI does not send or escalate anything."""
    b = db.execute("SELECT * FROM ai_briefs WHERE id=?", (bid,)).fetchone(); roles = ai_gov.settings(db)["horizon"]["watch_roles"]
    if not roles:
        return 0
    q = ",".join("?" for _ in roles); n = 0
    for u in db.execute("SELECT DISTINCT u.email, u.full_name FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name IN (%s) AND u.status='active' AND u.deleted_at IS NULL AND u.email IS NOT NULL AND u.email != ''" % q, roles).fetchall():
        outbox(db, u["email"], "[AI-prepared, unverified] Development brief (severity %d/5): %s" % (b["severity"], b["title"][:90]),
               "A development that may affect EcoCash's risk profile was found and analysed by the Sentinel Copilot.\n\n%s\n\nSource: %s\n\nThis analysis was prepared by AI from approved sources and your register. It is NOT verified. Open Sentinel > Sentinel Copilot > Horizon to review it, dismiss it, or turn it into an action.\n" % (b["summary"] or b["title"], b["url"] or "n/a"), "ai_brief")
        n += 1
    return n


def scan_local(db, w, ctx):
    """Horizon scan with the built-in engine: free web search, approved sources only, materiality by rule, impact analysis against the register."""
    gs = ai_gov.settings(db); q = w["query"] or w["name"]; out = {"watch": w["name"], "status": "ok", "found": 0, "briefs": [], "skipped": 0, "cost": 0, "error": None}
    official = [d for d, _, t in ai_gov.TRUSTED if t == "regulator" and d in gs["sources"]][:3]
    queries = [q] + ([q + " " + " OR ".join("site:" + d for d in official)] if official else [])
    seen, found, errs = set(), [], {}
    for qq in queries:
        res = ai_web.search(db, qq)
        errs.update(res["errors"])
        for x in res["results"]:
            if x["url"] not in seen:
                seen.add(x["url"]); found.append(x)
    db.execute("UPDATE ai_watch SET last_run=? WHERE id=?", (now(), w["id"]))
    if not found and errs:
        out.update(status="error", error="; ".join("%s: %s" % kv for kv in errs.items())); return out
    reads = 0
    for x in found:
        if x["trusted"] is not True:
            out["skipped"] += 1; continue
        if db.execute("SELECT 1 FROM ai_briefs WHERE url=?", (x["url"],)).fetchone():
            continue
        out["found"] += 1; text = ""; date = None
        if reads < 3:
            try:
                pg = ai_web.read_page(db, x["url"], False); text = pg["text"]; date = pg["date"]; reads += 1
            except ai_web.WebError:
                pass
        if date and (dbm.today() - datetime.date.fromisoformat(date)).days > 60:
            continue  # old news
        sev = ai_engine.impact_of(db, ctx, x["title"], x["snippet"] + " " + text[:6000])["severity"]
        if sev < gs["horizon"]["min_severity"]:
            continue
        bid = impact(db, ctx, {"title": x["title"], "summary": x["snippet"], "url": x["url"], "source": x["domain"], "published": date, "text": text, "materiality": sev}, "horizon", w)
        if bid:
            out["briefs"].append(bid)
        if len(out["briefs"]) >= gs["horizon"].get("max_per_scan", 6):
            break
    return out


def scan_feed(db, w, ctx):
    """An RSS or Atom feed on the watch-list: every new item is scored and, when material, analysed."""
    gs = ai_gov.settings(db); out = {"watch": w["name"], "status": "ok", "found": 0, "briefs": [], "skipped": 0, "cost": 0, "error": None}
    db.execute("UPDATE ai_watch SET last_run=? WHERE id=?", (now(), w["id"]))
    try:
        items = ai_web.read_feed(db, w["url"])
    except ai_web.WebError as e:
        out.update(status="error", error=str(e)); return out
    for it in items[:25]:
        if db.execute("SELECT 1 FROM ai_briefs WHERE url=?", (it["url"],)).fetchone():
            continue
        out["found"] += 1
        sev = ai_engine.impact_of(db, ctx, it["title"], it["summary"])["severity"]
        if sev >= gs["horizon"]["min_severity"]:
            bid = impact(db, ctx, {"title": it["title"], "summary": it["summary"], "url": it["url"], "source": w["name"], "published": (it["published"] or "")[:16], "materiality": sev}, "horizon", w)
            if bid:
                out["briefs"].append(bid)
    return out


def scan_watch(db, w, ctx=None, user=None):
    ctx = ctx or ai_tools.SysCtx(); gs = ai_gov.settings(db); hrs = _hours_since(w["last_run"]); days = 7 if hrs is None else max(3, math.ceil(hrs / 24) + 1)
    if w["kind"] == "rss":
        return scan_feed(db, w, ctx)
    if w["kind"] == "url":
        return scan_url(db, w, ctx)
    if ai_agent.is_local(db):
        return scan_local(db, w, ctx)
    allowed = [d.strip() for d in (w["domains"] or "").split(",") if d.strip()] or None
    task = SCAN_TASK.format(name=w["name"], query=w["query"] or w["name"], days=days, mx=gs["horizon"].get("max_per_scan", 6))
    res = ai_agent.run_agent(db, ctx, "horizon_scan", "horizon", "Run the horizon scan.", tier="chat", allow_web=True, extra_system=task, tool_names=[], max_turns=8, max_tokens=12000)
    db.execute("UPDATE ai_watch SET last_run=? WHERE id=?", (now(), w["id"]))
    j = ai_agent.parse_json(res.text) if res.status == "ok" else None
    out = {"watch": w["name"], "status": res.status, "found": 0, "briefs": [], "skipped": 0, "cost": round(res.cost, 4), "error": res.error or None}
    if not j:
        return out
    for d in (j.get("developments") or [])[:gs["horizon"].get("max_per_scan", 6)]:
        url = d.get("source_url")
        if not url or ai_gov.trust_tier(gs, url) != "trusted":  # a development must come from an approved source we can name
            out["skipped"] += 1; continue
        try:
            mat = max(1, min(5, int(d.get("materiality") or 2)))
        except (TypeError, ValueError):
            mat = 2
        out["found"] += 1
        if mat < gs["horizon"]["min_severity"]:
            continue
        bid = impact(db, ctx, {"title": d.get("title"), "summary": ((d.get("summary") or "") + (" Why it matters: " + d["why_it_matters"] if d.get("why_it_matters") else "")), "url": url, "source": d.get("source_name"), "published": d.get("published"), "materiality": mat}, "horizon", w)
        if bid:
            out["briefs"].append(bid)
    return out


def scan_url(db, w, ctx):
    """A page on the watch-list (for example a regulator's notices page): fetched, compared with last time, and analysed when it has changed."""
    st = {}
    res, src = ai_tools.t_fetch_page(db, ctx, {"url": w["url"]}, st)
    db.execute("UPDATE ai_watch SET last_run=? WHERE id=?", (now(), w["id"]))
    if res.get("error"):
        return {"watch": w["name"], "status": "error", "error": res["error"], "briefs": [], "found": 0}
    h = hashlib.sha256(re.sub(r"\s+", " ", res["text"]).encode()).hexdigest()
    if w["last_hash"] == h:
        return {"watch": w["name"], "status": "ok", "found": 0, "briefs": [], "unchanged": True}
    first = w["last_hash"] is None
    db.execute("UPDATE ai_watch SET last_hash=? WHERE id=?", (h, w["id"]))
    if first:
        return {"watch": w["name"], "status": "ok", "found": 0, "briefs": [], "baseline": True}
    bid = impact(db, ctx, {"title": "Change on watched page: %s" % w["name"], "summary": "The watched page %s changed since the last check." % w["url"], "url": w["url"], "source": w["name"], "published": now()[:10], "text": res["text"], "materiality": 3}, "page_change", w)
    return {"watch": w["name"], "status": "ok", "found": 1, "briefs": [bid] if bid else []}


def scan_due(db, limit=2):
    """Run the watches that are due. Called by the scheduler; safe to call by hand."""
    if ai_gov.unavailable(db, None, "horizon"):
        return []
    out = []
    for w in db.execute("SELECT * FROM ai_watch WHERE active=1 ORDER BY COALESCE(last_run,'') ASC").fetchall():
        h = _hours_since(w["last_run"])
        if h is None or h >= w["freq_hours"]:
            out.append(scan_watch(db, w))
            db.commit()
            if len(out) >= limit:
                break
    return out


def scheduler(stop=None):
    from . import db as dbm
    time.sleep(30)
    while not (stop and stop.is_set()):
        if _lock.acquire(blocking=False):
            try:
                c = dbm.connect()
                try:
                    scan_due(c); c.commit()
                finally:
                    c.close()
            except Exception:
                pass
            finally:
                _lock.release()
        time.sleep(300)


def start_scheduler():
    t = threading.Thread(target=scheduler, name="sentinel-horizon", daemon=True); t.start(); return t


# ------------------------------------------------------------------ API
def _brief(r, full=False):
    d = dict(r)
    d["sources"] = json.loads(d["sources"] or "[]")
    try:
        d["impact"] = json.loads(d["impact"]) if d["impact"] else None
    except ValueError:
        d["impact"] = None
    if not full:
        d["impact_headline"] = (d["impact"] or {}).get("headline") if isinstance(d["impact"], dict) else None
        d["impact"] = None
    return d


@router.route("GET", "/api/ai/watch")
def watch_list(req):
    c = need(req, "sentinel_copilot", "view"); seed(req.db)
    return {"watch": [dict(r) for r in req.db.execute("SELECT * FROM ai_watch ORDER BY id")], "can": {"edit": "edit" in c.perms.get("sentinel_copilot", set())}, "min_severity": ai_gov.settings(req.db)["horizon"]["min_severity"], "roles": ai_gov.settings(req.db)["horizon"]["watch_roles"]}


@router.route("POST", "/api/ai/watch")
def watch_add(req):
    c = need(req, "sentinel_copilot", "edit"); b = req.json()
    kind = b.get("kind") if b.get("kind") in ("url", "rss") else "topic"; name = need_str(b, "name", "Name", 120)
    url = str(b.get("url") or "").strip()
    if kind in ("url", "rss"):
        try:
            ai_web.check_url(ai_gov.settings(req.db), url, ai_gov.settings(req.db)["web"]["read_unlisted"])
        except ai_web.WebError as e:
            raise HTTPError(400, "validation", str(e))
    elif len(str(b.get("query") or "")) < 10:
        raise HTTPError(400, "validation", "Describe what to watch (at least 10 characters).")
    wid = req.db.execute("INSERT INTO ai_watch(kind,name,query,url,freq_hours,active,created_at) VALUES(?,?,?,?,?,1,?)", (kind, name, str(b.get("query") or "")[:500], url or None, max(6, min(720, int(b.get("freq_hours") or 24))), now())).lastrowid
    audit(req.db, "ai.watch_added", c.user, "sentinel_copilot", "Watch added: %s (%s)" % (name, kind), req.ip)
    return {"id": wid}


@router.route("POST", "/api/ai/watch/<int:wid>")
def watch_update(req):
    c = need(req, "sentinel_copilot", "edit"); b = req.json(); wid = int(req.params["wid"])
    if "active" in b:
        req.db.execute("UPDATE ai_watch SET active=? WHERE id=?", (1 if b["active"] else 0, wid))
    if "freq_hours" in b:
        req.db.execute("UPDATE ai_watch SET freq_hours=? WHERE id=?", (max(6, min(720, int(b["freq_hours"]))), wid))
    audit(req.db, "ai.watch_changed", c.user, "sentinel_copilot", "Watch #%d changed" % wid, req.ip)
    return {"ok": True}


@router.route("POST", "/api/ai/watch/<int:wid>/delete")
def watch_delete(req):
    c = need(req, "sentinel_copilot", "edit")
    req.db.execute("DELETE FROM ai_watch WHERE id=?", (int(req.params["wid"]),))
    audit(req.db, "ai.watch_deleted", c.user, "sentinel_copilot", "Watch #%s deleted" % req.params["wid"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/ai/watch/<int:wid>/scan")
def watch_scan(req):
    c = need(req, "sentinel_copilot", "edit")
    w = req.db.execute("SELECT * FROM ai_watch WHERE id=?", (int(req.params["wid"]),)).fetchone()
    if not w:
        raise HTTPError(404, "not_found", "Watch not found.")
    ai_gov.gate(req.db, c.user, "horizon")
    out = scan_watch(req.db, w, ai_tools.SysCtx(), c.user)
    audit(req.db, "ai.scan", c.user, "sentinel_copilot", "Horizon scan run for \"%s\": %d found, %d briefs" % (w["name"], out["found"], len(out["briefs"])), req.ip)
    return out


@router.route("GET", "/api/ai/briefs")
def briefs(req):
    need(req, "sentinel_copilot", "view")
    st = req.query.get("status") or "new"
    rows = req.db.execute("SELECT * FROM ai_briefs" + ("" if st == "all" else " WHERE status=?") + " ORDER BY severity DESC, id DESC LIMIT 100", [] if st == "all" else [st]).fetchall()
    return {"briefs": [_brief(r) for r in rows]}


@router.route("GET", "/api/ai/briefs/<int:bid>")
def brief_one(req):
    need(req, "sentinel_copilot", "view")
    r = req.db.execute("SELECT * FROM ai_briefs WHERE id=?", (int(req.params["bid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Brief not found.")
    return _brief(r, True)


@router.route("POST", "/api/ai/briefs/<int:bid>/review")
def brief_review(req):
    c = need(req, "sentinel_copilot", "edit"); b = req.json()
    r = req.db.execute("SELECT * FROM ai_briefs WHERE id=?", (int(req.params["bid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Brief not found.")
    st = b.get("status") if b.get("status") in ("reviewed", "dismissed", "escalated") else None
    if not st:
        raise HTTPError(400, "validation", "Choose reviewed, dismissed or escalated.")
    note = need_str(b, "note", "Note", 1000) if st != "reviewed" else str(b.get("note") or "")[:1000]
    ref = None
    if st == "escalated":
        j = json.loads(r["impact"] or "{}"); acts = j.get("recommended_actions") or [{"action": "Review the development: " + r["title"], "owner_role": "Head of Risk", "timing": "14 days"}]
        if not ai_tools.can(c, "actions_issues", "create"):
            raise HTTPError(403, "forbidden", "You may not create actions.")
        out = p5.make_action(req.db, c, {"title": ("Review: " + str(acts[0].get("action") or r["title"]))[:200], "description": "From AI-prepared brief #%d (%s). Reviewed by %s. %s" % (r["id"], r["title"], c.user["full_name"], note), "owner_name": acts[0].get("owner_role") or "Head of Risk", "due_date": (dbm.today() + datetime.timedelta(days=14)).isoformat(), "source": "manual", "priority": "High" if r["severity"] >= 4 else "Medium"})
        ref = out["ref"]
    req.db.execute("UPDATE ai_briefs SET status=?, reviewed_by=?, reviewed_at=?, note=? WHERE id=?", (st, c.user["full_name"], now(), (note + (" Action " + ref if ref else "")).strip(), r["id"]))
    audit(req.db, "ai.brief_" + st, c.user, "sentinel_copilot", "AI brief #%d %s by %s%s" % (r["id"], st, c.user["full_name"], " -> " + ref if ref else ""), req.ip)
    return {"ok": True, "status": st, "action": ref}


@router.route("POST", "/api/ai/impact")
def impact_adhoc(req):
    """Analyse a development the user found: pasted text, a headline, or a link to an approved source."""
    c = need(req, "sentinel_copilot", "create"); b = req.json(); url = str(b.get("url") or "").strip(); text = str(b.get("text") or "")[:60000]
    title = need_str(b, "title", "Headline", 240)
    if url:
        res, _ = ai_tools.t_fetch_page(req.db, c, {"url": url}, {})
        if res.get("error"):
            raise HTTPError(400, "validation", res["error"])
        text = text or res["text"]
    if len(text) < 30 and not b.get("summary"):
        raise HTTPError(400, "validation", "Paste the text of the development, or give a link to an approved source.")
    c.roles = ai_agent.user_roles(req.db, c)
    bid = impact(req.db, c, {"title": title, "summary": str(b.get("summary") or "")[:1500], "url": url or None, "source": "Added by user", "published": str(b.get("published") or now()[:10])[:10], "text": text}, "user", None, c.user)
    if bid is None:
        raise HTTPError(409, "duplicate", "An analysis of this development already exists.")
    return _brief(req.db.execute("SELECT * FROM ai_briefs WHERE id=?", (bid,)).fetchone(), True)


@router.route("POST", "/api/ai/docs/<int:did>/impact")
def doc_impact(req):
    """A new version of a policy or regulation: what changed and what it touches."""
    c = need(req, "sentinel_copilot", "create"); r = ai_agent.load_doc(req.db, c, req.params["did"])
    prev = req.db.execute("SELECT version FROM ai_docs WHERE id=?", (r["supersedes_id"],)).fetchone() if r["supersedes_id"] else None
    chg = json.loads(r["change_summary"]) if r["change_summary"] else None
    if not chg:
        raise HTTPError(409, "no_change", "This is the first version, or the change could not be worked out, so there is nothing to compare.")
    summary = "Version %d of \"%s\" replaces version %d. %d passages were added and %d removed. Added: %s Removed: %s" % (r["version"], r["title"], prev["version"] if prev else 0, chg["added"], chg["removed"], " | ".join(chg["added_sample"][:4]), " | ".join(chg["removed_sample"][:4]))
    c.roles = ai_agent.user_roles(req.db, c)
    bid = impact(req.db, c, {"title": "Change in %s (v%d)" % (r["title"], r["version"]), "summary": summary, "url": None, "source": "Uploaded document", "published": (r["uploaded_at"] or now())[:10], "text": None, "materiality": 3}, "user", None, c.user)
    if bid is None:
        raise HTTPError(409, "duplicate", "An analysis of this change already exists.")
    return _brief(req.db.execute("SELECT * FROM ai_briefs WHERE id=?", (bid,)).fetchone(), True)
