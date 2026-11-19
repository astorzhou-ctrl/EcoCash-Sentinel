"""Speak-Up Cases (BRD 9.17, GRC Policy 2.5.3 tip-offs programme). Receives and handles tip-offs safely.
  * Case details are visible ONLY to case officers who hold an access grant. Roles do not matter: the Head of Risk, the administrator and executives cannot open a case.
  * The reporter's identity (if given) is stored encrypted and is shown only to the officer the case is assigned to; every reveal is logged.
  * Everyone else with the module sees anonymised themes: counts and trends, never a case; groups of fewer than 3 are not shown, so nobody can be identified from a count.
  * Access grants are made by the Head of Risk (never to themselves) and must be reviewed every month.
  * Service levels (acknowledge, close) are tracked; the defaults are proposals for the policy owner to confirm.
The Copilot and the e-mail reminders never read case content."""
import datetime
import json
import re

from . import mfa, xlsxbook
from .api import router, need, need_str
from .core import audit, now
from .p2 import xlsx_response
from .web import HTTPError
from . import db as dbm

THEMES = ["Fraud or theft", "Bribery or corruption", "Harassment, discrimination or abuse", "Conflict of interest", "Procurement irregularity", "Data or privacy concern", "Safety or health", "Abuse of authority or misconduct", "Retaliation against a reporter", "Other"]
CHANNELS = ["Anonymous hotline", "Web or e-mail", "In person", "Letter", "Line manager or Compliance Officer", "Other"]
STATUSES = ["received", "triage", "investigating", "substantiated", "unsubstantiated", "closed"]
NEXT = {"received": ("triage", "investigating"), "triage": ("investigating", "closed"), "investigating": ("substantiated", "unsubstantiated"), "substantiated": ("closed",), "unsubstantiated": ("closed",), "closed": ()}
PRIORITY = ("Normal", "High", "Urgent")
MIN_GROUP = 3


def settings(db):
    r = db.execute("SELECT value FROM settings WHERE key='speakup'").fetchone(); d = {"ack_days": 3, "close_days": 60}
    if r:
        d.update(json.loads(r["value"]))
    return d


def is_officer(db, user):
    return bool(db.execute("SELECT 1 FROM speakup_access WHERE user_id=? AND active=1", (user["id"],)).fetchone())


def need_officer(req, action="view"):
    c = need(req, "speak_up_cases", action)
    if not is_officer(req.db, c.user):
        raise HTTPError(403, "restricted", "Case details are restricted to case officers who hold an access grant. You can see anonymised themes only.")
    return c


def log(db, case_id, user, action):
    db.execute("INSERT INTO speakup_log(ts,case_id,username,action) VALUES(?,?,?,?)", (now(), case_id, user["username"], action))


def classify(text):
    """A suggestion for the case officer from the words: theme and priority. The officer decides."""
    t = (text or "").lower(); rules = [("Bribery or corruption", r"brib|kickback|corrupt|gift to|facilitation payment"), ("Fraud or theft", r"fraud|steal|stole|theft|embezzl|fake|forged|misappropriat|ghost"), ("Harassment, discrimination or abuse", r"harass|discriminat|abus|bully|sexual|intimidat"),
                                       ("Conflict of interest", r"conflict of interest|related party|relative|family member.*(?:tender|contract|hire)|undeclared interest"), ("Procurement irregularity", r"tender|procure|supplier selection|quotation|bid rig|single.?source"), ("Data or privacy concern", r"personal data|privacy|leak|customer data|confidential information|data breach"),
                                       ("Safety or health", r"safety|injur|unsafe|hazard|health risk"), ("Retaliation against a reporter", r"retaliat|victimi[sz]|punish.*report|fired.*report"), ("Abuse of authority or misconduct", r"abuse of (?:power|authority)|misconduct|favouritism|nepotism|coerc")]
    theme = next((n for n, rx in rules if re.search(rx, t)), "Other"); urgent = bool(re.search(r"threat|violen|weapon|child|minor|immediate danger|life", t)); high = urgent or bool(re.search(r"million|ongoing|police|regulator|senior|executive|director|retaliat|cash|bribe|systemic|many (?:staff|customers)", t))
    return {"theme": theme, "priority": "Urgent" if urgent else "High" if high else "Normal"}


def view(db, r, full=False, user=None):
    today = dbm.today().isoformat(); d = {"id": r["id"], "ref": r["ref"], "received_at": r["received_at"], "channel": r["channel"], "theme": r["theme"], "priority": r["priority"], "status": r["status"], "anonymous": bool(r["anonymous"]), "ack_due": r["ack_due"], "close_due": r["close_due"], "acknowledged_at": r["acknowledged_at"], "closed_at": r["closed_at"],
                                         "ack_overdue": bool(not r["acknowledged_at"] and r["ack_due"] and r["ack_due"] < today and r["status"] != "closed"), "close_overdue": bool(r["status"] != "closed" and r["close_due"] and r["close_due"] < today)}
    o = db.execute("SELECT id, full_name FROM users WHERE id=?", (r["officer_id"],)).fetchone() if r["officer_id"] else None; d["officer"] = o["full_name"] if o else None; d["officer_id"] = r["officer_id"]; d["mine"] = bool(user and r["officer_id"] == user["id"]); d["next"] = list(NEXT.get(r["status"], ()))
    d["has_reporter"] = bool(r["reporter_sealed"])
    if full:
        d.update({"summary": r["summary"], "detail": r["detail"], "outcome": r["outcome"]})
    return d


@router.route("GET", "/api/speakup/status")
def status(req):
    c = need(req, "speak_up_cases", "view"); s = settings(req.db); off = is_officer(req.db, c.user)
    acc = req.db.execute("SELECT MIN(COALESCE(last_review, granted_at)) m FROM speakup_access WHERE active=1").fetchone()["m"]; due = bool(acc and acc[:10] < (dbm.today() - datetime.timedelta(days=31)).isoformat())
    return {"officer": off, "can_manage": "approve" in c.perms.get("speak_up_cases", set()), "can_create": "create" in c.perms.get("speak_up_cases", set()) and off, "settings": s, "review_overdue": due, "themes": THEMES, "channels": CHANNELS, "priorities": list(PRIORITY), "statuses": STATUSES}


@router.route("GET", "/api/speakup/themes")
def themes(req):
    """Anonymised: counts and trends by theme. No case-level data. Groups below three are hidden."""
    need(req, "speak_up_cases", "view"); today = dbm.today(); rows = [dict(r) for r in req.db.execute("SELECT * FROM speakup_cases WHERE deleted_at IS NULL")]; by = {}
    for r in rows:
        by.setdefault(r["theme"], []).append(r)
    th = []
    for t, rs in sorted(by.items(), key=lambda z: -len(z[1])):
        n = len(rs)
        if n < MIN_GROUP:
            th.append({"theme": t, "count": None, "note": "fewer than %d" % MIN_GROUP}); continue
        th.append({"theme": t, "count": n, "open": sum(1 for r in rs if r["status"] != "closed"), "substantiated": sum(1 for r in rs if r["status"] == "substantiated"), "last_90_days": sum(1 for r in rs if (today - datetime.date.fromisoformat(r["received_at"][:10])).days <= 90)})
    closed = [r for r in rows if r["closed_at"]]; days = [(datetime.date.fromisoformat(r["closed_at"][:10]) - datetime.date.fromisoformat(r["received_at"][:10])).days for r in closed]; months = {}
    for r in rows:
        months[r["received_at"][:7]] = months.get(r["received_at"][:7], 0) + 1
    td = today.isoformat(); n = len(rows)
    return {"total": n, "open": sum(1 for r in rows if r["status"] != "closed"), "anonymous_pct": round(100 * sum(1 for r in rows if r["anonymous"]) / n) if n else None, "substantiated": sum(1 for r in rows if r["status"] == "substantiated"), "avg_days_to_close": round(sum(days) / len(days), 1) if days else None,
            "days_series": [{"month": m, "days": None} for m in sorted(months)][-6:], "themes": th, "by_month": [{"month": m, "count": months[m]} for m in sorted(months)][-12:], "ack_overdue": sum(1 for r in rows if not r["acknowledged_at"] and r["ack_due"] and r["ack_due"] < td and r["status"] != "closed"), "close_overdue": sum(1 for r in rows if r["status"] != "closed" and r["close_due"] and r["close_due"] < td),
            "min_group": MIN_GROUP, "rules": ["Reporter identity is hidden from everyone except the case officer assigned to the case.", "Access is reviewed monthly.", "Themes feed the register without personal details."]}


@router.route("GET", "/api/speakup/cases")
def queue(req):
    c = need_officer(req); rows = [view(req.db, r, False, c.user) for r in req.db.execute("SELECT * FROM speakup_cases WHERE deleted_at IS NULL ORDER BY CASE status WHEN 'closed' THEN 1 ELSE 0 END, CASE priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 ELSE 2 END, received_at DESC")]
    log(req.db, None, c.user, "opened the case queue")
    return {"cases": rows}


@router.route("GET", "/api/speakup/cases/<int:cid>")
def case_get(req):
    cid = int(req.params["cid"])
    c = need_officer(req); r = req.db.execute("SELECT * FROM speakup_cases WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Case not found.")
    log(req.db, cid, c.user, "opened the case")
    d = view(req.db, r, True, c.user); d["log"] = [dict(x) for x in req.db.execute("SELECT ts, username, action FROM speakup_log WHERE case_id=? ORDER BY id DESC LIMIT 30", (cid,))]
    d["officers"] = [{"id": u["id"], "name": u["full_name"]} for u in req.db.execute("SELECT u.id, u.full_name FROM users u JOIN speakup_access a ON a.user_id=u.id WHERE a.active=1 AND u.status='active' AND u.deleted_at IS NULL")]
    return d


@router.route("POST", "/api/speakup/suggest")
def suggest(req):
    need_officer(req, "create")
    return dict(classify(need_str(req.json(), "text", "Report text", 6000)), note="A suggestion from the words of the report. The case officer classifies.")


@router.route("POST", "/api/speakup/cases")
def case_add(req):
    c = need_officer(req, "create"); b = req.json(); s = settings(req.db)
    theme, ch, pr = b.get("theme"), b.get("channel"), b.get("priority") or "Normal"
    if theme not in THEMES or ch not in CHANNELS or pr not in PRIORITY:
        raise HTTPError(400, "validation", "Choose the theme, the channel and the priority from the lists.")
    summary = need_str(b, "summary", "Summary", 600); detail = str(b.get("detail") or "").strip()[:6000]; anon = 0 if str(b.get("reporter_contact") or "").strip() else 1
    sealed = mfa.seal(str(b["reporter_contact"]).strip()[:300]) if not anon else None; today = dbm.today()
    cid = req.db.execute("INSERT INTO speakup_cases(received_at,channel,theme,priority,summary,detail,anonymous,reporter_sealed,status,officer_id,ack_due,close_due,created_by) VALUES(?,?,?,?,?,?,?,?,'received',?,?,?,?)",
                         (b.get("received_at") or now(), ch, theme, pr, summary, detail, anon, sealed, c.user["id"], (today + datetime.timedelta(days=s["ack_days"])).isoformat(), (today + datetime.timedelta(days=s["close_days"])).isoformat(), c.user["username"])).lastrowid
    ref = "SU-%04d" % cid; req.db.execute("UPDATE speakup_cases SET ref=? WHERE id=?", (ref, cid)); log(req.db, cid, c.user, "logged the case")
    audit(req.db, "speakup.case_add", c.user, "speak_up_cases", "Case %s logged (%s)" % (ref, theme), req.ip)  # the audit trail records that a case exists, never what it says
    return {"id": cid, "ref": ref}


@router.route("PUT", "/api/speakup/cases/<int:cid>")
def case_edit(req):
    cid = int(req.params["cid"])
    c = need_officer(req, "edit"); r = req.db.execute("SELECT * FROM speakup_cases WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone(); b = req.json()
    if not r:
        raise HTTPError(404, "not_found", "Case not found.")
    if r["officer_id"] != c.user["id"]:
        raise HTTPError(403, "restricted", "Only the officer the case is assigned to can change it. Ask the assigned officer to reassign it.")
    theme = b.get("theme", r["theme"]); pr = b.get("priority", r["priority"]); st = b.get("status", r["status"]); outcome = b.get("outcome", r["outcome"])
    if theme not in THEMES or pr not in PRIORITY:
        raise HTTPError(400, "validation", "Choose the theme and the priority from the lists.")
    if st != r["status"]:
        if st not in NEXT[r["status"]]:
            raise HTTPError(409, "state", "A case moves %s \u2192 %s." % (r["status"], " or ".join(NEXT[r["status"]]) or "nowhere: it is closed"))
        if st in ("substantiated", "unsubstantiated", "closed") and len(str(outcome or "").strip()) < 10:
            raise HTTPError(400, "validation", "Record the outcome in a sentence or two (no names of the reporter).")
    ack = r["acknowledged_at"] or (now() if b.get("acknowledge") else None)
    req.db.execute("UPDATE speakup_cases SET theme=?, priority=?, status=?, outcome=?, acknowledged_at=?, closed_at=? WHERE id=?", (theme, pr, st, str(outcome or "")[:1500], ack, now() if st == "closed" else r["closed_at"], cid))
    if st != r["status"]:
        log(req.db, cid, c.user, "moved the case to %s" % st)
    if b.get("acknowledge") and not r["acknowledged_at"]:
        log(req.db, cid, c.user, "acknowledged receipt to the reporter")
    audit(req.db, "speakup.case_edit", c.user, "speak_up_cases", "Case %s %s" % (r["ref"], "moved to " + st if st != r["status"] else "updated"), req.ip)
    return {"ok": True}


@router.route("POST", "/api/speakup/cases/<int:cid>/assign")
def assign(req):
    cid = int(req.params["cid"])
    c = need_officer(req, "edit"); r = req.db.execute("SELECT * FROM speakup_cases WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone(); to = int(req.json().get("officer_id") or 0)
    if not r or r["officer_id"] != c.user["id"]:
        raise HTTPError(403, "restricted", "Only the officer the case is assigned to can reassign it.")
    if not req.db.execute("SELECT 1 FROM speakup_access WHERE user_id=? AND active=1", (to,)).fetchone():
        raise HTTPError(400, "validation", "That person is not a case officer with access.")
    req.db.execute("UPDATE speakup_cases SET officer_id=? WHERE id=?", (to, cid)); log(req.db, cid, c.user, "reassigned the case"); audit(req.db, "speakup.assign", c.user, "speak_up_cases", "Case %s reassigned" % r["ref"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/speakup/cases/<int:cid>/reveal")
def reveal(req):
    cid = int(req.params["cid"])
    """The reporter's contact, to the assigned officer only. Logged every time."""
    c = need_officer(req); r = req.db.execute("SELECT * FROM speakup_cases WHERE id=? AND deleted_at IS NULL", (cid,)).fetchone()
    if not r or r["officer_id"] != c.user["id"]:
        raise HTTPError(403, "restricted", "Only the officer the case is assigned to can see how to reach the reporter.")
    if not r["reporter_sealed"]:
        return {"contact": None, "note": "The reporter is anonymous: there is no contact."}
    log(req.db, cid, c.user, "viewed the reporter's contact"); audit(req.db, "speakup.reveal", c.user, "speak_up_cases", "Reporter contact viewed on case %s" % r["ref"], req.ip)
    return {"contact": mfa.unseal(r["reporter_sealed"])}


@router.route("GET", "/api/speakup/access")
def access_list(req):
    c = need(req, "speak_up_cases", "approve"); s = req.db.execute("SELECT a.user_id, u.full_name, u.job_title, a.granted_by, a.granted_at, a.last_review, a.active FROM speakup_access a JOIN users u ON u.id=a.user_id ORDER BY a.active DESC, u.full_name").fetchall(); lim = (dbm.today() - datetime.timedelta(days=31)).isoformat()
    cands = [{"id": u["id"], "name": u["full_name"], "role": ", ".join(r["name"] for r in req.db.execute("SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id=r.id WHERE ur.user_id=?", (u["id"],)))} for u in req.db.execute("SELECT DISTINCT u.id, u.full_name FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name='Case Officer' AND u.status='active' AND u.deleted_at IS NULL AND u.id NOT IN (SELECT user_id FROM speakup_access WHERE active=1)")]
    ev = [dict(x) for x in req.db.execute("SELECT l.ts, l.username, l.action, c.ref FROM speakup_log l LEFT JOIN speakup_cases c ON c.id=l.case_id ORDER BY l.id DESC LIMIT 40")]
    return {"officers": [dict(x, review_overdue=bool(x["active"] and (x["last_review"] or x["granted_at"])[:10] < lim)) for x in s], "candidates": cands, "log": ev}


@router.route("POST", "/api/speakup/access")
def access_grant(req):
    c = need(req, "speak_up_cases", "approve"); uid = int(req.json().get("user_id") or 0)
    if uid == c.user["id"]:
        raise HTTPError(403, "separation", "You cannot grant yourself access to cases. Another approver must do it.")
    u = req.db.execute("SELECT full_name FROM users WHERE id=? AND status='active' AND deleted_at IS NULL", (uid,)).fetchone()
    if not u or not req.db.execute("SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=? AND r.name='Case Officer'", (uid,)).fetchone():
        raise HTTPError(400, "validation", "Access can be granted only to an active user with the Case Officer role.")
    req.db.execute("INSERT INTO speakup_access(user_id,granted_by,granted_at,last_review,active) VALUES(?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET active=1, granted_by=excluded.granted_by, granted_at=excluded.granted_at, last_review=excluded.last_review", (uid, c.user["username"], now(), now()))
    audit(req.db, "speakup.access_grant", c.user, "speak_up_cases", "Case access granted to %s" % u["full_name"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/speakup/access/<int:uid>/review")
def access_review(req):
    uid = int(req.params["uid"])
    c = need(req, "speak_up_cases", "approve"); b = req.json(); a = req.db.execute("SELECT * FROM speakup_access WHERE user_id=? AND active=1", (uid,)).fetchone()
    if not a:
        raise HTTPError(404, "not_found", "That person has no active access.")
    if b.get("keep") is False:
        open_ = req.db.execute("SELECT COUNT(*) n FROM speakup_cases WHERE officer_id=? AND status != 'closed' AND deleted_at IS NULL", (uid,)).fetchone()["n"]
        if open_:
            raise HTTPError(409, "in_use", "This officer still has %d open case(s). Reassign them first." % open_)
        req.db.execute("UPDATE speakup_access SET active=0 WHERE user_id=?", (uid,)); audit(req.db, "speakup.access_revoke", c.user, "speak_up_cases", "Case access removed (user #%d)" % uid, req.ip)
    else:
        req.db.execute("UPDATE speakup_access SET last_review=? WHERE user_id=?", (now(), uid)); audit(req.db, "speakup.access_review", c.user, "speak_up_cases", "Case access reviewed and kept (user #%d)" % uid, req.ip)
    return {"ok": True}


@router.route("POST", "/api/speakup/settings")
def save_settings(req):
    c = need(req, "speak_up_cases", "approve"); b = req.json(); s = settings(req.db)
    for k in ("ack_days", "close_days"):
        if k in b:
            s[k] = max(1, min(365, int(b[k])))
    req.db.execute("INSERT INTO settings(key,value) VALUES('speakup',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(s),)); audit(req.db, "speakup.settings", c.user, "speak_up_cases", "Service levels set: acknowledge %d days, close %d days" % (s["ack_days"], s["close_days"]), req.ip)
    return {"ok": True}


CAT = {"Fraud or theft": "Fraud", "Bribery or corruption": "Regulatory", "Harassment, discrimination or abuse": "People", "Conflict of interest": "Regulatory", "Procurement irregularity": "Third party", "Data or privacy concern": "Cyber", "Safety or health": "Operational", "Abuse of authority or misconduct": "People", "Retaliation against a reporter": "People", "Other": "Operational"}


@router.route("POST", "/api/speakup/themes/to-risk")
def theme_to_risk(req):
    """A theme with at least three reports becomes a DRAFT risk. The risk carries counts only: no case, no reporter, no personal detail."""
    c = need(req, "speak_up_cases", "approve"); need(req, "risk_register", "create"); theme = need_str(req.json(), "theme", "Theme", 80)
    n = req.db.execute("SELECT COUNT(*) n, SUM(status='substantiated') s FROM speakup_cases WHERE theme=? AND deleted_at IS NULL", (theme,)).fetchone()
    if theme not in THEMES or n["n"] < MIN_GROUP:
        raise HTTPError(409, "too_few", "A theme needs at least %d reports before it can become a risk: fewer would point to individuals." % MIN_GROUP)
    from . import ai_agent
    p = {"title": "Pattern of speak-up reports: %s" % theme.lower(), "description": "%d speak-up reports on the theme '%s' have been received, %d substantiated. This risk carries counts only, from the anonymised themes of the Speak-Up Cases module." % (n["n"], theme, n["s"] or 0), "category": CAT[theme], "root_cause": "To be assessed by the owner without reference to individual cases.",
         "consequences": "Loss, regulatory exposure and damage to trust if the pattern is not addressed.", "owner_role": "Head of Compliance and ML/CTF", "inh_l": 3, "inh_c": 3, "res_l": 2, "res_c": 3, "treatment": "Review the theme with the Audit Committee; confirm the controls.", "controls": [], "kris": ["Speak-up reports per quarter on this theme"]}
    ref = ai_agent.apply_risk(req.db, c, p, "From speak-up themes"); rid = req.db.execute("SELECT id FROM risks WHERE ref=?", (ref,)).fetchone()["id"]
    req.db.execute("UPDATE risks SET assess_source='Speak-up themes (anonymised counts)' WHERE id=?", (rid,)); audit(req.db, "speakup.theme_risk", c.user, "speak_up_cases", "Theme '%s' raised as draft risk %s" % (theme, ref), req.ip)
    return {"ref": ref}
