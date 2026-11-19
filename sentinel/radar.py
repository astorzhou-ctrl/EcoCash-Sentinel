"""Emerging Radar (BRD 9.10): spots new risks early. Signals come from approved feeds, the Horizon briefs and manual entry; each is placed by potential impact,
speed of arrival (velocity) and proximity. A signal becomes a risk ONLY when a person promotes it (it then arrives as a draft). Sources are approved and listed.
Themes are detected from the words of the signal (monetary policy, payments regulation, AML, data protection, tax, fraud and cyber, infrastructure, AI, suppliers)."""
import hashlib
import json
import re

from . import ai_gov, ai_web, matrix as mx, xlsxbook
from .api import router, need, need_str
from .core import audit, now
from .p2 import xlsx_response
from .web import HTTPError
from . import db as dbm

DEFAULT_FEEDS = [("BBC News: Business", "https://feeds.bbci.co.uk/news/business/rss.xml"), ("BBC News: Africa", "https://feeds.bbci.co.uk/news/world/africa/rss.xml"), ("BBC News: World", "https://feeds.bbci.co.uk/news/world/rss.xml")]
STATUSES = ("new", "watching", "promoted", "dismissed")


def theme_and_scores(db, c, title, summary, trusted=False):
    """(theme, impact, velocity, proximity, confidence, topics) from the words. All 1 to 5 except confidence (0 to 1). The person can change every value."""
    from . import ai_engine
    text = "%s. %s" % (title, summary or ""); low = text.lower(); j = ai_engine.impact_of(db, c, title, summary or "")
    topics = j["topics"]; theme = ai_engine.TOPICS[topics[0]]["label"] if topics else "Other"
    vel = 5 if re.search(r"immediate|effective (?:today|immediately)|with effect from|already|now in force", low) else 4 if re.search(r"within \d+ days|next month|deadline|from (?:january|february|march|april|may|june|july|august|september|october|november|december)", low) else 2 if re.search(r"propos|consult|draft|plans? to|expected to|considering|may introduce|could", low) else 3
    prox = 5 if re.search(r"today|this week|already|now|immediate", low) else 2 if re.search(r"propos|consult|next year|in \d{4}|long.term|by 20\d\d", low) else 3
    conf = round(min(0.95, 0.35 + (0.35 if trusted else 0.0) + 0.1 * len(topics) + (0.1 if len(text) > 250 else 0)), 2)
    return theme, max(1, min(5, j["severity"])), vel, prox, conf, topics


def add_signal(db, c, title, summary, url, source, origin, trusted=False, user="system", ratings=None, theme=None):
    key = hashlib.sha256(((url or "") + "|" + re.sub(r"\W+", " ", title.lower())).encode()).hexdigest()[:24]
    if db.execute("SELECT 1 FROM signals WHERE dedupe=?", (key,)).fetchone():
        return None
    th, imp, vel, prox, conf, topics = theme_and_scores(db, c, title, summary, trusted)
    r = ratings or {}
    return db.execute("INSERT INTO signals(ts,title,summary,url,source,theme,confidence,impact,velocity,proximity,status,origin,dedupe,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,'new',?,?,?)",
                      (now(), title[:240], (summary or "")[:900], url, source, theme or th, r.get("confidence", conf), r.get("impact", imp), r.get("velocity", vel), r.get("proximity", prox), origin, key, user)).lastrowid


def signal_from_brief(db, brief_id):
    """Every development brief with a severity of 2 or more also appears on the radar (once)."""
    b = db.execute("SELECT * FROM ai_briefs WHERE id=?", (brief_id,)).fetchone()
    if not b or (b["severity"] or 0) < 2:
        return None
    from . import ai_tools
    return add_signal(db, ai_tools.SysCtx(), b["title"], b["summary"] or "", b["url"], b["source"] or "Horizon", "horizon", True)


def view(r):
    d = dict(r); d["level"] = mx.level(mx.rank(r["proximity"], r["impact"])); d["rank"] = mx.rank(r["proximity"], r["impact"]); return d


def seed(db):
    if not db.execute("SELECT 1 FROM radar_feeds").fetchone():
        for n, u in DEFAULT_FEEDS:
            db.execute("INSERT OR IGNORE INTO radar_feeds(name,url,active) VALUES(?,?,0)", (n, u))
    if not db.execute("SELECT 1 FROM radar_watch").fetchone():
        from . import ai_engine
        for k, t in list(ai_engine.TOPICS.items())[:6]:
            db.execute("INSERT INTO radar_watch(theme,owner,notes) VALUES(?,?,?)", (t["label"], "Head of Risk", "Pre-loaded theme: set an owner and a review date."))


@router.route("GET", "/api/radar")
def radar_get(req):
    c = need(req, "emerging_radar", "view"); seed(req.db)
    sig = [view(r) for r in req.db.execute("SELECT * FROM signals WHERE status != 'dismissed' ORDER BY ts DESC LIMIT 300")]
    import datetime
    wk = (dbm.today() - datetime.timedelta(days=7)).isoformat(); week = [s for s in sig if s["ts"][:10] >= wk]
    return {"signals": sig, "this_week": len(week), "bubbles": [{"id": s["id"], "title": s["title"], "x": s["velocity"], "y": s["impact"], "size": s["proximity"], "level": s["level"], "theme": s["theme"], "status": s["status"]} for s in sig if s["status"] in ("new", "watching", "promoted")],
            "watch": [dict(r, signals=sum(1 for s in sig if s["theme"] == r["theme"])) for r in req.db.execute("SELECT * FROM radar_watch WHERE active=1 ORDER BY review_date IS NULL, review_date, theme")], "feeds": [dict(r) for r in req.db.execute("SELECT * FROM radar_feeds ORDER BY name")],
            "themes": sorted({s["theme"] for s in sig if s["theme"]}), "can": {k: k in c.perms.get("emerging_radar", set()) for k in ("create", "edit", "delete", "approve", "export")}, "can_promote": "create" in c.perms.get("risk_register", set()), "today": dbm.today().isoformat()}


def _ratings(b):
    out = {}
    for k in ("impact", "velocity", "proximity"):
        if b.get(k) not in (None, ""):
            try:
                v = int(b[k])
            except (TypeError, ValueError):
                v = 0
            if not 1 <= v <= 5:
                raise HTTPError(400, "validation", "%s must be 1 to 5." % k.capitalize())
            out[k] = v
    if b.get("confidence") not in (None, ""):
        out["confidence"] = max(0.0, min(1.0, float(b["confidence"])))
    return out


@router.route("POST", "/api/radar/signals")
def signal_add(req):
    c = need(req, "emerging_radar", "create"); b = req.json(); title = need_str(b, "title", "Signal", 240); url = str(b.get("url") or "").strip()[:500]
    if url and not re.match(r"^https?://", url):
        raise HTTPError(400, "validation", "The link must start with http:// or https://")
    from . import ai_tools
    sid = add_signal(req.db, ai_tools.SysCtx(), title, str(b.get("summary") or "").strip(), url or None, str(b.get("source") or "Entered by hand").strip()[:120], "manual", bool(url and ai_gov.trust_tier(ai_gov.settings(req.db), url) == "trusted"), c.user["username"], _ratings(b), (b.get("theme") or None))
    if sid is None:
        raise HTTPError(409, "duplicate", "That signal is already on the radar.")
    audit(req.db, "radar.signal_add", c.user, "emerging_radar", "Signal #%d added: %s" % (sid, title[:80]), req.ip)
    return {"id": sid}


@router.route("PUT", "/api/radar/signals/<int:sid>")
def signal_edit(req):
    sid = int(req.params["sid"])
    c = need(req, "emerging_radar", "edit"); b = req.json(); s = req.db.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Signal not found.")
    rt = _ratings(b); st = b.get("status")
    if st is not None and st not in ("new", "watching", "dismissed"):
        raise HTTPError(400, "validation", "A signal is set to new, watching or dismissed here; promotion has its own step.")
    if st == "dismissed" and len(str(b.get("note") or "").strip()) < 5:
        raise HTTPError(400, "validation", "Say briefly why it is dismissed.")
    sets = ["%s=?" % k for k in rt] + (["status=?", "decided_by=?", "decided_at=?", "note=?"] if st else []) + (["theme=?"] if b.get("theme") else [])
    vals = list(rt.values()) + ([st, c.user["username"], now(), str(b.get("note") or "")[:300]] if st else []) + ([str(b["theme"])[:60]] if b.get("theme") else [])
    if sets:
        req.db.execute("UPDATE signals SET %s WHERE id=?" % ",".join(sets), vals + [sid])
    audit(req.db, "radar.signal_edit", c.user, "emerging_radar", "Signal #%d %s" % (sid, st or "ratings changed"), req.ip)
    return {"ok": True}


CAT = {"Monetary policy and exchange rate": "Financial", "Payments and mobile-money regulation": "Regulatory", "Anti-money-laundering and sanctions": "Regulatory", "Data protection and cyber law": "Cyber", "Tax and levies": "Financial", "Fraud and cyber threats": "Fraud", "Power, network and infrastructure": "Technology", "AI regulation and standards": "Model / AI", "Suppliers and supply chain": "Third party"}


@router.route("POST", "/api/radar/signals/<int:sid>/promote")
def signal_promote(req):
    sid = int(req.params["sid"])
    """A person turns a signal into a DRAFT risk. The rating is a starting point from the signal's impact and proximity; the owner completes it."""
    c = need(req, "emerging_radar", "edit"); need(req, "risk_register", "create"); s = req.db.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    if not s or s["status"] == "promoted":
        raise HTTPError(409 if s else 404, "state", "Signal not found or already promoted.")
    from . import ai_agent
    inh_c = s["impact"]; inh_l = max(1, min(5, round((s["proximity"] + s["velocity"]) / 2))); res_l, res_c = max(1, inh_l - 1), max(1, inh_c - 1)
    title = re.sub(r"\s+", " ", s["title"]).strip()
    payload = {"title": ("Emerging: " + title)[:200], "description": "%s Source: %s%s. Raised from the Emerging Radar (theme: %s)." % ((s["summary"] or title)[:500], s["source"] or "entered by hand", " (%s)" % s["url"] if s["url"] else "", s["theme"]), "category": CAT.get(s["theme"], "Strategic"), "root_cause": "External development: to be confirmed by the owner.",
               "consequences": "To be assessed. Potential impact on the radar is %d of 5, arriving at a speed of %d of 5." % (s["impact"], s["velocity"]), "owner_role": "Head of Risk", "inh_l": inh_l, "inh_c": inh_c, "res_l": res_l, "res_c": res_c, "treatment": "Monitor and assess: confirm the owner, the exposure and the controls.", "controls": [], "kris": []}
    note = str(req.json().get("note") or "").strip()[:300]; ref = ai_agent.apply_risk(req.db, c, payload, note or "Promoted from the radar")
    rid = req.db.execute("SELECT id FROM risks WHERE ref=?", (ref,)).fetchone()["id"]
    req.db.execute("UPDATE risks SET assess_source=? WHERE id=?", ("Emerging radar signal #%d, promoted by %s" % (sid, c.user["full_name"]), rid))
    req.db.execute("UPDATE signals SET status='promoted', risk_id=?, decided_by=?, decided_at=?, note=? WHERE id=?", (rid, c.user["username"], now(), note, sid))
    audit(req.db, "radar.promote", c.user, "emerging_radar", "Signal #%d promoted to draft risk %s" % (sid, ref), req.ip)
    return {"ref": ref, "risk_id": rid}


@router.route("POST", "/api/radar/watch")
def watch_add(req):
    c = need(req, "emerging_radar", "create"); b = req.json(); theme = need_str(b, "theme", "Theme", 120); rd = str(b.get("review_date") or "").strip() or None
    if rd and not re.match(r"^\d{4}-\d{2}-\d{2}$", rd):
        raise HTTPError(400, "validation", "The review date must look like 2026-12-31.")
    wid = req.db.execute("INSERT INTO radar_watch(theme,owner,review_date,notes) VALUES(?,?,?,?)", (theme, str(b.get("owner") or "").strip()[:100], rd, str(b.get("notes") or "").strip()[:300])).lastrowid
    audit(req.db, "radar.watch_add", c.user, "emerging_radar", "Watch theme '%s' added" % theme, req.ip)
    return {"id": wid}


@router.route("PUT", "/api/radar/watch/<int:wid>")
def watch_edit(req):
    wid = int(req.params["wid"])
    c = need(req, "emerging_radar", "edit"); b = req.json(); w = req.db.execute("SELECT * FROM radar_watch WHERE id=?", (wid,)).fetchone()
    if not w:
        raise HTTPError(404, "not_found", "Watch theme not found.")
    rd = (b.get("review_date") if "review_date" in b else w["review_date"]) or None
    if rd and not re.match(r"^\d{4}-\d{2}-\d{2}$", rd):
        raise HTTPError(400, "validation", "The review date must look like 2026-12-31.")
    req.db.execute("UPDATE radar_watch SET owner=?, review_date=?, notes=?, active=? WHERE id=?", (str(b.get("owner", w["owner"]) or "")[:100], rd, str(b.get("notes", w["notes"]) or "")[:300], 1 if b.get("active", w["active"]) else 0, wid))
    audit(req.db, "radar.watch_edit", c.user, "emerging_radar", "Watch theme '%s' updated" % w["theme"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/radar/feeds")
def feed_add(req):
    c = need(req, "emerging_radar", "approve"); b = req.json(); name = need_str(b, "name", "Name", 100); url = need_str(b, "url", "Address", 400)
    try:
        ai_web.check_url(ai_gov.settings(req.db), url, False)
    except ai_web.WebError as e:
        raise HTTPError(400, "validation", str(e))
    try:
        fid = req.db.execute("INSERT INTO radar_feeds(name,url,active) VALUES(?,?,1)", (name, url)).lastrowid
    except Exception:
        raise HTTPError(409, "duplicate", "That feed is already listed.")
    audit(req.db, "radar.feed_add", c.user, "emerging_radar", "Feed '%s' approved" % name, req.ip)
    return {"id": fid}


@router.route("PUT", "/api/radar/feeds/<int:fid>")
def feed_toggle(req):
    fid = int(req.params["fid"])
    c = need(req, "emerging_radar", "approve"); on = 1 if req.json().get("active") else 0
    if not req.db.execute("SELECT 1 FROM radar_feeds WHERE id=?", (fid,)).fetchone():
        raise HTTPError(404, "not_found", "Feed not found.")
    req.db.execute("UPDATE radar_feeds SET active=? WHERE id=?", (on, fid)); audit(req.db, "radar.feed_toggle", c.user, "emerging_radar", "Feed #%d %s" % (fid, "switched on" if on else "switched off"), req.ip)
    return {"ok": True}


@router.route("POST", "/api/radar/scan")
def scan(req):
    """Reads the approved feeds that are switched on, and the Horizon briefs, and adds what is relevant to the radar. Needs web research to be on (System Administrator)."""
    c = need(req, "emerging_radar", "create"); seed(req.db); from . import ai_tools; sys_ctx = ai_tools.SysCtx(); added = 0; read = 0; errors = {}
    n_h = 0
    for b in req.db.execute("SELECT id FROM ai_briefs WHERE severity >= 2 ORDER BY id DESC LIMIT 50").fetchall():
        if signal_from_brief(req.db, b["id"]):
            n_h += 1
    feeds = req.db.execute("SELECT * FROM radar_feeds WHERE active=1").fetchall()
    if feeds:
        ai_gov.gate(req.db, c.user, "research")
    st = ai_gov.settings(req.db)
    for f in feeds:
        try:
            items = ai_web.read_feed(req.db, f["url"])
        except ai_web.WebError as e:
            errors[f["name"]] = str(e); continue
        read += len(items); req.db.execute("UPDATE radar_feeds SET last_run=? WHERE id=?", (now(), f["id"]))
        for it in items[:40]:
            th, imp, vel, prox, conf, topics = theme_and_scores(req.db, sys_ctx, it["title"], it["summary"], ai_gov.trust_tier(st, it["url"]) == "trusted")
            if not topics:  # a headline that touches none of the themes Sentinel watches is not a signal
                continue
            if add_signal(req.db, sys_ctx, it["title"], it["summary"], it["url"], f["name"], "feed", ai_gov.trust_tier(st, it["url"]) == "trusted", "feed"):
                added += 1
    audit(req.db, "radar.scan", c.user, "emerging_radar", "Radar scan: %d feed items read, %d signals added, %d from Horizon briefs" % (read, added, n_h), req.ip)
    return {"feeds": len(feeds), "read": read, "added": added, "from_horizon": n_h, "errors": errors}


@router.route("GET", "/api/radar/export.xlsx")
def export(req):
    need(req, "emerging_radar", "export")
    s1 = [[("Emerging radar: signals", 3)], [], [(h, 1) for h in ("Received", "Signal", "Theme", "Impact", "Velocity", "Proximity", "Expected level", "Confidence", "Source", "Status", "Link")]]
    for r in req.db.execute("SELECT * FROM signals ORDER BY ts DESC"):
        v = view(r); s1.append([r["ts"][:10], r["title"], r["theme"], r["impact"], r["velocity"], r["proximity"], v["level"], r["confidence"], r["source"], r["status"], r["url"] or ""])
    s2 = [[("Watch list", 3)], [], [(h, 1) for h in ("Theme", "Owner", "Review date", "Notes")]] + [[r["theme"], r["owner"], r["review_date"] or "", r["notes"]] for r in req.db.execute("SELECT * FROM radar_watch WHERE active=1")]
    return xlsx_response(xlsxbook.write([("Signals", s1, [12, 70, 34, 8, 9, 10, 14, 11, 26, 11, 50]), ("Watch list", s2, [38, 22, 14, 60])]), "Sentinel_emerging_radar.xlsx")
