"""Step 4 (BRD phase P1), part 1: Daily Tracker and Risk Appetite."""
import datetime
import json
import re

from . import core, db as dbm, matrix as mx, xlsx, xlsxw
from .api import router, need, need_str, DATE_RE
from .core import audit, now
from .risks import board_ok
from .web import HTTPError, Response

ASSIGN = xlsxw.STATUSES
DONE = ("Submitted", "Completed")
DEFAULT_CFG = {"mode": "hybrid", "soon_days": 3, "sources": {"risk_actions": True, "assessments": True, "board": True, "kri": True, "incidents": True, "sources": True, "actions": True}}
EVENT_MODULES = ("risk_register", "assessment_studio", "board_hub", "risk_appetite", "daily_tracker", "weekly_kpi", "kri_monitor", "incidents_losses")


# ------------------------------------------------------------------ Daily Tracker
def cfg(db):
    c = json.loads(json.dumps(DEFAULT_CFG))
    r = db.execute("SELECT value FROM settings WHERE key='tracker'").fetchone()
    if r:
        v = json.loads(r["value"])
        c.update({k: v[k] for k in ("mode", "soon_days") if k in v})
        c["sources"].update(v.get("sources", {}))
    return c


def task_status(t, today, soon=3):
    """The workbook rule (Completed / Rescheduled / Overdue / Due Soon / On Track), with On Hold and Cancelled kept out of the overdue count."""
    a = t["assignment"]
    if a in DONE:
        return "Completed"
    if a == "Cancelled":
        return "Cancelled"
    if a == "On Hold":
        return "On Hold"
    if t["revised"]:
        return "Overdue" if t["revised"] < today.isoformat() else "Rescheduled"
    if not t["deadline"]:
        return ""
    if t["deadline"] < today.isoformat():
        return "Overdue"
    return "Due Soon" if t["deadline"] <= (today + datetime.timedelta(days=soon)).isoformat() else "On Track"


def days_left(t, today):
    eff = t["revised"] or t["deadline"]
    return (datetime.date.fromisoformat(eff) - today).days if eff else None


def task_dict(t, today, soon):
    d = {k: t[k] for k in ("id", "title", "comment", "assignment", "owner_text", "deadline", "revised", "revised_reason", "email_label", "email_url", "source", "completed_at", "created_at")}
    d["status"], d["days"], d["effective"] = task_status(t, today, soon), days_left(t, today), t["revised"] or t["deadline"]
    return d


def task_scope(c):
    if c.user["data_scope"] == "all":
        return "1=1", []
    first = (c.user["full_name"].split() or [""])[0]
    return "(created_by=? OR owner_id=? OR owner_text LIKE ? COLLATE NOCASE OR owner_text LIKE ? COLLATE NOCASE OR owner_text='All')", [c.user["id"], c.user["id"], "%" + first + "%", "%" + c.user["username"] + "%"]


def tiles(ds, today):
    cnt = lambda k: sum(1 for t in ds if t["status"] == k)
    return {"total": len(ds), "overdue": cnt("Overdue"), "due_today": sum(1 for t in ds if t["effective"] == today.isoformat() and t["status"] in ("Overdue", "Due Soon", "On Track", "Rescheduled")), "due_soon": cnt("Due Soon"),
            "completed": cnt("Completed"), "on_track": cnt("On Track") + cnt("Rescheduled"), "other": cnt("On Hold") + cnt("Cancelled")}


def thistory(db, tid, username, action, changes=None):
    db.execute("INSERT INTO task_history(task_id,ts,username,action,changes) VALUES(?,?,?,?,?)", (tid, now(), username, action, json.dumps(changes or {}, ensure_ascii=False)))


def visible_tasks(req, c):
    where, args = task_scope(c)
    rows = req.db.execute("SELECT * FROM tasks WHERE deleted_at IS NULL AND %s ORDER BY id" % where, args).fetchall()
    k = cfg(req.db)
    return [task_dict(t, dbm.today(), k["soon_days"]) for t in rows], k


@router.route("GET", "/api/tracker")
def tracker_list(req):
    c = need(req, "daily_tracker", "view")
    ds, k = visible_tasks(req, c)
    ds.sort(key=lambda t: ({"Overdue": 0, "Due Soon": 1, "Rescheduled": 2, "On Track": 3, "": 4, "On Hold": 5, "Cancelled": 6, "Completed": 7}[t["status"]], t["effective"] or "9999"))
    return {"tasks": ds, "tiles": tiles(ds, dbm.today()), "cfg": k, "assignments": ASSIGN, "today": dbm.today().isoformat(), "owners": sorted({t["owner_text"] for t in ds if t["owner_text"]}),
            "can": {a: a in c.perms.get("daily_tracker", set()) for a in core.ACTIONS}}


def clean_task(d, existing=None):
    title = need_str(d, "title", "Task", 300)
    a = (d.get("assignment") or "Pending").strip()
    if a not in ASSIGN:
        raise HTTPError(400, "validation", "Choose an assignment status from the list.")
    dl = (d.get("deadline") or "").strip() or None
    rv = (d.get("revised") or "").strip() or None
    for v in (dl, rv):
        if v and not DATE_RE.match(v):
            raise HTTPError(400, "validation", "Dates must be YYYY-MM-DD.")
    reason = need_str(d, "revised_reason", "Reason", 300, False)
    if rv and rv != (existing["revised"] if existing else None) and len(reason) < 5:
        raise HTTPError(400, "reason_required", "A revised timeline needs a reason (at least 5 characters). The original deadline is kept for reporting.")
    link = (d.get("email_url") or "").strip() or None
    if link and not re.match(r"^https?://", link):
        raise HTTPError(400, "validation", "The e-mail link must start with http:// or https://.")
    return {"title": title, "comment": need_str(d, "comment", "Comment", 1000, False), "assignment": a, "owner_text": need_str(d, "owner_text", "Owner", 120, False), "deadline": dl, "revised": rv,
            "revised_reason": reason or (existing["revised_reason"] if existing and rv else None), "email_label": need_str(d, "email_label", "E-mail label", 200, False) or None, "email_url": link}


@router.route("POST", "/api/tracker/tasks")
def task_create(req):
    c = need(req, "daily_tracker", "create")
    f = clean_task(req.json())
    done = now() if f["assignment"] in DONE else None
    tid = req.db.execute("INSERT INTO tasks(title,comment,assignment,owner_text,deadline,revised,revised_reason,email_label,email_url,source,completed_at,created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,'manual',?,?,?,?,?)",
                         (f["title"], f["comment"], f["assignment"], f["owner_text"], f["deadline"], f["revised"], f["revised_reason"], f["email_label"], f["email_url"], done, now(), c.user["id"], now(), c.user["id"])).lastrowid
    thistory(req.db, tid, c.user["username"], "created", {"title": [None, f["title"]]})
    audit(req.db, "task.created", c.user, "daily_tracker", "Task added: %s" % f["title"][:80], req.ip)
    return {"id": tid}


def get_task(req, c, tid):
    where, args = task_scope(c)
    t = req.db.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL AND %s" % where, [tid] + args).fetchone()
    if not t:
        raise HTTPError(404, "not_found", "Task not found")
    return t


@router.route("PUT", "/api/tracker/tasks/<int:tid>")
def task_update(req):
    c = need(req, "daily_tracker", "edit")
    t = get_task(req, c, int(req.params["tid"]))
    f = clean_task(req.json(), t)
    ch = {k: [t[k], f[k]] for k in f if (t[k] or None) != (f[k] or None)}
    done = t["completed_at"]
    if f["assignment"] in DONE and t["assignment"] not in DONE:
        done = now()
    elif f["assignment"] not in DONE:
        done = None
    if not f["deadline"] and t["deadline"] is None:
        f["deadline"] = None
    sets = ", ".join("%s=?" % k for k in f)
    req.db.execute("UPDATE tasks SET %s, completed_at=?, updated_at=?, updated_by=? WHERE id=?" % sets, list(f.values()) + [done, now(), c.user["id"], t["id"]])
    if ch:
        thistory(req.db, t["id"], c.user["username"], "rescheduled" if "revised" in ch else "updated", ch)
        audit(req.db, "task.updated", c.user, "daily_tracker", "Task %d changed: %s" % (t["id"], ", ".join(ch)), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/tracker/tasks/<int:tid>")
def task_delete(req):
    c = need(req, "daily_tracker", "delete")
    t = get_task(req, c, int(req.params["tid"]))
    reason = need_str(req.json(), "reason", "A reason", 300)
    if len(reason) < 3:
        raise HTTPError(400, "validation", "Give a reason of at least 3 characters.")
    pol = dbm.get_policy(req.db)
    req.db.execute("UPDATE tasks SET deleted_at=?, deleted_by=?, delete_reason=? WHERE id=?", (now(), c.user["id"], reason, t["id"]))
    req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at) VALUES('task',?,?,?,?,?,?,?,?)",
                   (t["id"], t["title"][:120], "Daily Tracker", c.user["id"], c.user["username"], now(), reason, dbm.plus(days=pol["recycle_days"])))
    thistory(req.db, t["id"], c.user["username"], "deleted", {"reason": [None, reason]})
    audit(req.db, "task.deleted", c.user, "daily_tracker", "Deleted task %d: %s" % (t["id"], reason), req.ip)
    return {"ok": True}


@router.route("GET", "/api/tracker/tasks/<int:tid>")
def task_get(req):
    c = need(req, "daily_tracker", "view")
    t = get_task(req, c, int(req.params["tid"]))
    k = cfg(req.db)
    d = task_dict(t, dbm.today(), k["soon_days"])
    d["history"] = [dict(x, changes=json.loads(x["changes"] or "{}")) for x in req.db.execute("SELECT * FROM task_history WHERE task_id=? ORDER BY id DESC LIMIT 40", (t["id"],))]
    return d


@router.route("PUT", "/api/tracker/settings")
def tracker_settings(req):
    c = need(req, "daily_tracker", "approve")
    d = req.json()
    k = cfg(req.db)
    if d.get("mode") not in ("automatic", "hybrid", "manual"):
        raise HTTPError(400, "validation", "Mode must be automatic, hybrid or manual.")
    try:
        soon = int(d.get("soon_days", 3))
        assert 1 <= soon <= 14
    except (TypeError, ValueError, AssertionError):
        raise HTTPError(400, "validation", "The due-soon window must be 1 to 14 days.")
    src = {s: bool((d.get("sources") or {}).get(s, k["sources"][s])) for s in k["sources"]}
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('tracker',?)", (json.dumps({"mode": d["mode"], "soon_days": soon, "sources": src}),))
    audit(req.db, "tracker.settings", c.user, "daily_tracker", "Tracker mode %s, due-soon window %d days, sources %s" % (d["mode"], soon, ", ".join(s for s, v in src.items() if v) or "none"), req.ip)
    return {"ok": True}


def auto_sync(db, user=None, ip=""):
    """Create, update and close the tasks the system derives from risks, assessments and Board decisions (hybrid and automatic modes)."""
    k = cfg(db)
    out = {"created": 0, "updated": 0, "closed": 0, "mode": k["mode"]}
    if k["mode"] == "manual":
        return out
    want = {}
    if k["sources"].get("risk_actions"):
        for r in db.execute("SELECT id,ref,title,owner_name,action_date FROM risks WHERE deleted_at IS NULL AND action_date IS NOT NULL AND status!='closed' AND id NOT IN (SELECT risk_id FROM actions WHERE source='risk' AND risk_id IS NOT NULL AND deleted_at IS NULL AND status!='cancelled')"):
            want["risk:%d:action" % r["id"]] = ("Treatment action due: %s %s" % (r["ref"], r["title"][:90]), "Action date on the risk (GRC Policy 2.5.1 action plan).", r["owner_name"], r["action_date"])
    if k["sources"].get("actions", True):
        for a in db.execute("SELECT * FROM actions WHERE deleted_at IS NULL AND status IN ('open','in_progress','awaiting_verification')"):
            want["action:%d" % a["id"]] = ("Action %s: %s" % (a["ref"], a["title"][:90]), "From Actions and Issues (%s). Priority %s." % (a["source"].replace("_", " "), a["priority"]), a["owner_name"], a["revised_due"] if a["revision_status"] == "approved" and a["revised_due"] else a["due_date"])
    if k["sources"].get("assessments"):
        for a in db.execute("SELECT a.id,a.status,a.assessor_name,c.name,c.due_date,r.ref,r.title FROM assignments a JOIN campaigns c ON c.id=a.campaign_id JOIN risks r ON r.id=a.risk_id WHERE c.status='open' AND a.status IN ('open','submitted','challenged') AND r.deleted_at IS NULL"):
            rev = a["status"] == "submitted"
            want["assess:%d" % a["id"]] = (("Review assessment: " if rev else "Assess: ") + "%s %s" % (a["ref"], a["title"][:80]), "Campaign: %s (%s)" % (a["name"], a["status"]), "Risk Office" if rev else (a["assessor_name"] or "Risk Office"), a["due_date"])
    if k["sources"].get("board"):
        for d in db.execute("SELECT d.id,r.ref,r.title,m.meeting_date FROM board_decisions d JOIN risks r ON r.id=d.risk_id LEFT JOIN meetings m ON m.id=d.meeting_id WHERE d.status='pending' AND r.deleted_at IS NULL"):
            want["board:%d" % d["id"]] = ("Board decision needed: %s %s" % (d["ref"], d["title"][:80]), "Risk above appetite waiting for a Board decision (GRC Policy 2.4).", "Head of Risk", d["meeting_date"])
    if k["sources"].get("kri"):
        for a in db.execute("SELECT a.id, a.opened_at, k.code, k.name, k.owner FROM kri_alerts a JOIN kpis k ON k.id=a.kpi_id WHERE a.status IN ('open','acknowledged') AND a.level='red' AND k.deleted_at IS NULL"):
            want["kri:%d" % a["id"]] = ("KRI red: %s %s" % (a["code"], a["name"][:80]), "A key risk indicator is beyond its red threshold: find the cause and act (GRC Policy 2.6).", a["owner"] or "Risk Office", str(datetime.date.fromisoformat(a["opened_at"][:10]) + datetime.timedelta(days=7)))
    if k["sources"].get("incidents"):
        for i in db.execute("SELECT * FROM incidents WHERE deleted_at IS NULL AND status!='closed' AND (severity IN ('High','Critical') OR pdb=1)"):
            dl = str(datetime.date.fromisoformat(i["detected_at"][:10]) + datetime.timedelta(days=1)) if i["pdb"] and not i["notified_at"] else str(datetime.date.fromisoformat(i["occurred_on"]) + datetime.timedelta(days=14))
            want["incident:%d" % i["id"]] = ("Incident %s: %s" % (i["ref"], i["title"][:90]), ("Personal-data breach: notify the regulator within 24 hours of detection. " if i["pdb"] and not i["notified_at"] else "") + "Contain, find the root cause and close.", i["owner"] or "Risk Office", dl)
        for i in db.execute("SELECT i.id, i.ref, i.closed_at, r.ref rref, r.owner_name FROM incidents i JOIN risks r ON r.id=i.risk_id WHERE i.deleted_at IS NULL AND i.status='closed' AND r.deleted_at IS NULL AND COALESCE(r.updated_at, r.created_at) <= i.closed_at"):
            want["incident:%d:reassess" % i["id"]] = ("Re-assess %s after incident %s was closed" % (i["rref"], i["ref"]), "A closed incident linked to this risk may change its likelihood or consequence (BRD: closed event prompts re-assessment).", i["owner_name"] or "Risk Office", str(datetime.date.fromisoformat(i["closed_at"][:10]) + datetime.timedelta(days=14)))
    if k["sources"].get("sources"):
        d3 = lambda ts, n: str(datetime.date.fromisoformat(ts[:10]) + datetime.timedelta(days=n))
        for s in db.execute("SELECT * FROM kpi_sources WHERE deleted_at IS NULL"):
            if s["status"] == "active" and s["changed_at"] and (not s["reviewed_at"] or s["reviewed_at"] < s["changed_at"]):
                want["source:%d" % s["id"]] = ("Source updated: %s" % s["name"][:90], "The page changed since the last visit. Check the linked indicators in Weekly KPI and update them, then mark the source as reviewed.", "Risk Office", d3(s["changed_at"], 3))
            elif s["status"] == "suspended":
                want["source:%d:suspended" % s["id"]] = ("Source suspended: %s" % s["name"][:90], "Sentinel stopped visiting this site (%s). Re-verify it with a second person or replace it." % (s["last_status"] or "see the visit log")[:120], "Risk Office", d3(now(), 2))
            elif s["status"] == "proposed":
                want["source:%d:verify" % s["id"]] = ("Verify data source: %s" % s["name"][:90], "A second person must check this site before Sentinel will visit it (two-person rule).", "Risk Office", d3(s["proposed_at"], 7))
        npend = db.execute("SELECT COUNT(*) c FROM kpi_proposals WHERE status IN ('pending','quarantined')").fetchone()["c"]
        if npend:
            want["proposals"] = ("Review %d value(s) proposed from verified sources" % npend, "Accept or reject them in Weekly KPI > Sources and automation.", "Risk Office", d3(now(), 2))
    existing = {t["source_key"]: t for t in db.execute("SELECT * FROM tasks WHERE source_key IS NOT NULL")}
    for key, (title, comment, owner, deadline) in want.items():
        t = existing.get(key)
        if t is None:
            tid = db.execute("INSERT INTO tasks(title,comment,assignment,owner_text,deadline,source,source_key,created_at,updated_at) VALUES(?,?,'Pending',?,?,'auto',?,?,?)", (title, comment, owner, deadline, key, now(), now())).lastrowid
            thistory(db, tid, "system", "created", {"source": [None, key]})
            out["created"] += 1
        elif t["deleted_at"] is None and t["assignment"] not in DONE and (t["title"], t["deadline"], t["owner_text"]) != (title, deadline, owner):
            db.execute("UPDATE tasks SET title=?, deadline=?, owner_text=?, updated_at=? WHERE id=?", (title, deadline, owner, now(), t["id"]))
            out["updated"] += 1
    for key, t in existing.items():
        if key not in want and t["deleted_at"] is None and t["source"] == "auto" and t["assignment"] not in DONE:
            why = None  # a task replaced by a tracked action, or whose action was cancelled, was not done: it is cancelled, never counted as completed
            parts = key.split(":")
            if len(parts) == 3 and parts[0] == "risk" and parts[2] == "action":
                a = db.execute("SELECT ref FROM actions WHERE risk_id=? AND source='risk' AND deleted_at IS NULL AND status!='cancelled' ORDER BY id DESC", (int(parts[1]),)).fetchone()
                why = "Replaced by the tracked action %s in Actions and Issues." % a["ref"] if a else None
            elif len(parts) == 2 and parts[0] == "action":
                a = db.execute("SELECT ref, status FROM actions WHERE id=?", (int(parts[1]),)).fetchone()
                why = "The action %s was cancelled." % a["ref"] if a and a["status"] == "cancelled" else None
            if why:
                db.execute("UPDATE tasks SET assignment='Cancelled', comment=?, updated_at=? WHERE id=?", ((t["comment"] or "") + " " + why, now(), t["id"]))
                thistory(db, t["id"], "system", "cancelled automatically", {"reason": why})
            else:
                db.execute("UPDATE tasks SET assignment='Completed', completed_at=?, comment=?, updated_at=? WHERE id=?", (now(), (t["comment"] or "") + " Closed automatically: the source item is finished.", now(), t["id"]))
                thistory(db, t["id"], "system", "closed automatically", {})
            out["closed"] += 1
    if k["mode"] == "automatic":
        digest(db)
    if out["created"] or out["closed"]:
        audit(db, "tracker.sync", user, "daily_tracker", "Automatic tasks: %d created, %d updated, %d closed" % (out["created"], out["updated"], out["closed"]), ip)
    return out


def digest(db):
    """Automatic mode: one outbox message per person per day listing their overdue and due-soon tasks."""
    day = str(dbm.today())
    r = db.execute("SELECT value FROM settings WHERE key='tracker_digest'").fetchone()
    if r and r["value"] == day:
        return
    k = cfg(db)
    ds = [task_dict(t, dbm.today(), k["soon_days"]) for t in db.execute("SELECT * FROM tasks WHERE deleted_at IS NULL")]
    ds = [t for t in ds if t["status"] in ("Overdue", "Due Soon")]
    for u in db.execute("SELECT * FROM users WHERE deleted_at IS NULL AND status IN ('active','invited') AND email IS NOT NULL"):
        first = (u["full_name"].split() or [""])[0].lower()
        mine = [t for t in ds if t["owner_text"] and (first in t["owner_text"].lower() or u["username"].lower() in t["owner_text"].lower() or t["owner_text"] == "All")]
        if mine:
            core.outbox(db, u["email"], "Sentinel daily digest: %d task(s) need attention" % len(mine), "\n".join("%s  %s  (%s, %s days)" % (t["status"], t["title"], t["effective"], t["days"]) for t in mine[:40]), "digest")
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('tracker_digest',?)", (day,))


@router.route("POST", "/api/tracker/sync")
def tracker_sync(req):
    c = need(req, "daily_tracker", "view")
    return auto_sync(req.db, c.user, req.ip)


@router.route("POST", "/api/tracker/note")
def tracker_note(req):
    c = need(req, "daily_tracker", "create")
    text = need_str(req.json(), "text", "Note", 500)
    audit(req.db, "tracker.note", c.user, "daily_tracker", text, req.ip)
    return {"ok": True}


def todays_events(db):
    day = str(dbm.today())
    lo = (datetime.datetime.fromisoformat(day) - datetime.timedelta(hours=config_tz())).strftime(dbm.FMT)
    hi = (datetime.datetime.fromisoformat(day) + datetime.timedelta(days=1) - datetime.timedelta(hours=config_tz())).strftime(dbm.FMT)
    qs = ",".join("?" * len(EVENT_MODULES))
    return db.execute("SELECT ts,username,event,module,detail FROM audit WHERE ts>=? AND ts<? AND module IN (%s) ORDER BY id DESC LIMIT 300" % qs, (lo, hi) + EVENT_MODULES).fetchall()


def config_tz():
    from . import config
    return config.TZ_HOURS


@router.route("GET", "/api/tracker/events")
def tracker_events(req):
    need(req, "daily_tracker", "view")
    ev = [dict(x) for x in todays_events(req.db)]
    types = {}
    for e in ev:
        g = e["event"].split(".")[0]
        types[g] = types.get(g, 0) + 1
    by_hour = [0] * 24
    for e in ev:
        h = (datetime.datetime.strptime(e["ts"], dbm.FMT) + datetime.timedelta(hours=config_tz())).hour
        by_hour[h] += 1
    return {"date": str(dbm.today()), "events": ev, "types": types, "by_hour": by_hour, "auto": sum(1 for e in ev if e["event"] != "tracker.note")}


def summary_data(req, c):
    ds, k = visible_tasks(req, c)
    td, tm = dbm.today(), dbm.today() + datetime.timedelta(days=1)
    local = lambda ts: (datetime.datetime.strptime(ts, dbm.FMT) + datetime.timedelta(hours=config_tz())).date() if ts else None
    where, args = task_scope(c)
    moved = [dict(r) for r in req.db.execute("SELECT t.title, h.ts FROM task_history h JOIN tasks t ON t.id=h.task_id WHERE h.action='rescheduled' AND t.deleted_at IS NULL AND %s ORDER BY h.id DESC LIMIT 100" % where.replace("created_by", "t.created_by").replace("owner_id", "t.owner_id").replace("owner_text", "t.owner_text"), args)]
    return {"date": td.isoformat(), "completed_today": [t["title"] for t in ds if local(t["completed_at"]) == td], "moved_today": [m["title"] for m in moved if local(m["ts"]) == td], "overdue": [t["title"] for t in ds if t["status"] == "Overdue"],
            "due_tomorrow": [t["title"] for t in ds if t["effective"] == tm.isoformat() and t["status"] not in ("Completed", "Cancelled", "On Hold")], "auto_created_today": [t["title"] for t in ds if t["source"] == "auto" and local(t["created_at"]) == td], "tiles": tiles(ds, td)}


@router.route("GET", "/api/tracker/summary")
def tracker_summary(req):
    c = need(req, "daily_tracker", "view")
    return summary_data(req, c)


@router.route("POST", "/api/tracker/summary/send")
def tracker_summary_send(req):
    c = need(req, "daily_tracker", "view")
    s = summary_data(req, c)
    sec = lambda t, xs: "%s (%d)\n%s" % (t, len(xs), "\n".join("  - " + x for x in xs[:30]) or "  none")
    body = "End-of-day summary, %s\n\n%s\n\n%s\n\n%s\n\n%s\n\n%s" % (s["date"], sec("Completed today", s["completed_today"]), sec("Moved today", s["moved_today"]), sec("Overdue", s["overdue"]), sec("Due tomorrow", s["due_tomorrow"]), sec("Created automatically today", s["auto_created_today"]))
    core.outbox(req.db, c.user["email"] or c.user["username"], "Sentinel end-of-day summary %s" % s["date"], body, "summary")
    audit(req.db, "tracker.summary", c.user, "daily_tracker", "End-of-day summary prepared", req.ip)
    return {"ok": True, "message": "The summary is in Administration > Outbox (no mail server is connected yet)."}


# ------------------------------------------------------------------ tracker import and export (your Excel layout)
HEADERS = {"task": "title", "comment": "comment", "assignment status": "assignment", "owner": "owner_text", "deadline": "deadline", "revised timelines": "revised", "email link": "email"}


def parse_tracker(data):
    sheets = xlsx.read(data)
    name = "TRACKER" if "TRACKER" in sheets else next(iter(sheets), None)
    rows = sheets.get(name) or []
    hr = next((i for i, r in enumerate(rows[:20]) if r and str(r[0] or "").strip().lower() == "task"), None)
    if hr is None:
        raise ValueError("No header row starting with TASK was found. Is this the task tracker workbook?")
    cols = {}
    for i, h in enumerate(rows[hr]):
        k = re.sub(r"[^a-z ]", "", str(h or "").lower()).strip()
        if k in HEADERS:
            cols[HEADERS[k]] = i
    links = xlsx.hyperlinks(data, name)
    out, warnings = [], []
    for ri in range(hr + 1, len(rows)):
        r = rows[ri] + [None] * 12
        title = re.sub(r"\s+", " ", str(r[cols["title"]] or "")).strip()
        if not title:
            continue
        g = lambda k: r[cols[k]] if k in cols else None
        a = str(g("assignment") or "").strip() or "Pending"
        if a not in ASSIGN:
            warnings.append("Row %d (%s): unknown assignment status '%s', set to Pending." % (ri + 1, title[:40], a)); a = "Pending"
        dl, rv = xlsx.excel_date(g("deadline")), xlsx.excel_date(g("revised"))
        if g("deadline") and not dl:
            warnings.append("Row %d (%s): the deadline could not be read." % (ri + 1, title[:40]))
        label = str(g("email") or "").strip() or None
        ref = "%s%d" % (xlsx.__dict__.get("col_letter", lambda i: chr(65 + i))(cols["email"]) if "email" in cols else "H", ri + 1)
        out.append({"title": title[:300], "comment": re.sub(r"\s+", " ", str(g("comment") or "")).strip()[:1000], "assignment": a, "owner_text": str(g("owner_text") or "").strip()[:120], "deadline": dl, "revised": rv, "email_label": label, "email_url": links.get(ref)})
    return {"tasks": out, "warnings": warnings}


@router.route("POST", "/api/tracker/import")
def tracker_import(req):
    c = need(req, "daily_tracker", "create")
    data = req.body()
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    try:
        p = parse_tracker(data)
    except ValueError as e:
        raise HTTPError(400, "bad_file", str(e))
    except Exception:
        raise HTTPError(400, "bad_file", "The workbook could not be read. Save it as .xlsx from Excel and try again.")
    have = {(r["title"], r["deadline"] or "", r["owner_text"] or "") for r in req.db.execute("SELECT title,deadline,owner_text FROM tasks WHERE deleted_at IS NULL")}
    new = [t for t in p["tasks"] if (t["title"], t["deadline"] or "", t["owner_text"]) not in have]
    k = cfg(req.db)
    st = {}
    for t in new:
        s = task_status(t, dbm.today(), k["soon_days"]); st[s or "no date"] = st.get(s or "no date", 0) + 1
    summary = {"found": len(p["tasks"]), "to_import": len(new), "skipped": len(p["tasks"]) - len(new), "status": st, "warnings": p["warnings"], "links": sum(1 for t in new if t["email_url"])}
    if req.query.get("dry") != "0":
        return dict(summary, dry=True)
    for t in new:
        tid = req.db.execute("INSERT INTO tasks(title,comment,assignment,owner_text,deadline,revised,revised_reason,email_label,email_url,source,completed_at,created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,'import',?,?,?,?,?)",
                             (t["title"], t["comment"], t["assignment"], t["owner_text"], t["deadline"], t["revised"], "Imported from the task tracker" if t["revised"] else None, t["email_label"], t["email_url"], now() if t["assignment"] in DONE else None, now(), c.user["id"], now(), c.user["id"])).lastrowid
        thistory(req.db, tid, c.user["username"], "imported", {})
    audit(req.db, "task.imported", c.user, "daily_tracker", "Imported %d tasks from the Excel tracker (%d already present)" % (len(new), summary["skipped"]), req.ip)
    return dict(summary, dry=False, imported=len(new))


@router.route("GET", "/api/tracker/export.xlsx")
def tracker_export(req):
    c = need(req, "daily_tracker", "export")
    ds, k = visible_tasks(req, c)
    ds.sort(key=lambda t: t["id"])
    rows = [{"title": t["title"], "comment": t["comment"], "assignment": t["assignment"], "owner": t["owner_text"], "deadline": t["deadline"], "revised": t["revised"], "status": t["status"], "email_label": t["email_label"], "email_url": t["email_url"], "days": t["days"], "effective": t["effective"]} for t in ds]
    audit(req.db, "export.tracker", c.user, "daily_tracker", "Exported %d tasks to Excel" % len(rows), req.ip)
    return Response(xlsxw.build(rows, dbm.today().isoformat()), 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [("Content-Disposition", 'attachment; filename="Sentinel_Task_Tracker_%s.xlsx"' % dbm.today())])


# ------------------------------------------------------------------ Risk Appetite (GRC Policy 2.4)
def load_thresholds(db):
    r = db.execute("SELECT value FROM settings WHERE key='appetite'").fetchone()
    if r:
        mx.set_thresholds(json.loads(r["value"]))
    else:
        mx.set_thresholds({"target": 6, "appetite": 12, "tolerance": 15})


SEED = [("Portfolio", "No risk above the appetite limit may be retained without a valid Board approval (GRC Policy 2.4).", "Averse", "Risks above appetite without Board approval", "risks", "max", 0, 0.8, "computed:above_appetite"),
        ("Portfolio", "No risk above the tolerance limit may be retained without a valid Board approval.", "Averse", "Risks above tolerance without Board approval", "risks", "max", 0, 0.8, "computed:above_tolerance"),
        ("Controls", "The portfolio level of assurance (LoA) meets the 80% target used in the Power BI reports.", "Cautious", "Portfolio level of assurance", "%", "min", 80, 0.9, "computed:loa"),
        ("Treatment", "Treatment actions are completed by the dates in the risk register.", "Cautious", "Risks with an overdue action date", "risks", "max", 0, 0.8, "computed:overdue_actions"),
        ("Assessment", "Every risk carries a real assessment, not a placeholder.", "Cautious", "Risks still needing assessment", "risks", "max", 0, 0.8, "computed:unassessed")]
DIMENSIONS = ["Financial performance", "People (harm)", "Environment", "Reputation and brand", "Regulatory and legal compliance", "Customer and operations"]


def seed_appetite(db):
    if db.execute("SELECT COUNT(*) c FROM appetite_statements").fetchone()["c"]:
        return
    for i, (dim, st, stance, metric, unit, direction, limit, amber, src) in enumerate(SEED):
        db.execute("INSERT INTO appetite_statements(dimension,statement,stance,metric,unit,direction,limit_value,amber,source,sort) VALUES(?,?,?,?,?,?,?,?,?,?)", (dim, st, stance, metric, unit, direction, limit, amber, src, i))
    for i, dim in enumerate(DIMENSIONS):
        db.execute("INSERT INTO appetite_statements(dimension,statement,stance,metric,unit,direction,source,sort) VALUES(?,?,NULL,NULL,NULL,'max','manual',?)",
                   (dim, "Appetite for impact on: %s (GRC Policy 2.4 and the impact scale in 2.2.2). The Board has not yet set a measurable limit." % dim.lower(), 50 + i))
    db.execute("INSERT INTO appetite_versions(ts,username,reference,reason,snapshot) VALUES(?,?,?,?,?)", (now(), "system", "defaults", "Initial values: workbook target 6, appetite 12, tolerance 15", json.dumps({"thresholds": {"target": 6, "appetite": 12, "tolerance": 15}})))
    db.commit()


def computed(db, source):
    today = str(dbm.today())
    rows = db.execute("SELECT id,res_l,res_c,action_date,status,needs_assessment,emv_i FROM risks WHERE deleted_at IS NULL").fetchall()
    assessed = [r for r in rows if not r["needs_assessment"]]
    rk = lambda r: mx.rank(r["res_l"], r["res_c"])
    if source == "above_appetite":
        return sum(1 for r in assessed if rk(r) > mx.THRESH["appetite"] and not board_ok(db, r["id"]))
    if source == "above_tolerance":
        return sum(1 for r in assessed if rk(r) > mx.THRESH["tolerance"] and not board_ok(db, r["id"]))
    if source == "overdue_actions":
        return sum(1 for r in rows if r["action_date"] and r["action_date"] < today and r["status"] != "closed")
    if source == "unassessed":
        return sum(1 for r in rows if r["needs_assessment"])
    if source == "loa":
        ei = er = 0.0
        for r in rows:
            a = db.execute("SELECT AVG(ice) a, COUNT(ice) n FROM risk_controls WHERE risk_id=?", (r["id"],)).fetchone()
            if r["emv_i"] and a["n"]:
                ei += r["emv_i"]; er += r["emv_i"] * a["a"]
        return round((1 - er / ei) * 100, 1) if ei else None
    return None


def stmt_status(limit, direction, amber, actual):
    if limit is None:
        return "not_set"
    if actual is None:
        return "no_data"
    if direction == "min":
        return "within" if actual >= limit else "near" if actual >= limit * amber else "breach"
    if limit == 0:
        return "within" if actual == 0 else "breach"
    return "within" if actual <= limit * amber else "near" if actual <= limit else "breach"


def stmt_dict(db, s):
    src = s["source"]
    actual = computed(db, src.split(":")[1]) if src.startswith("computed:") else s["actual"]
    return {"id": s["id"], "dimension": s["dimension"], "statement": s["statement"], "stance": s["stance"], "metric": s["metric"], "unit": s["unit"], "direction": s["direction"], "limit": s["limit_value"], "amber": s["amber"],
            "source": src, "computed": src.startswith("computed:"), "actual": actual, "actual_note": s["actual_note"], "actual_at": s["actual_at"], "owner": s["owner"], "status": stmt_status(s["limit_value"], s["direction"], s["amber"], actual)}


@router.route("GET", "/api/appetite")
def appetite_get(req):
    c = need(req, "risk_appetite", "view")
    db = req.db
    rows = db.execute("SELECT * FROM risks WHERE deleted_at IS NULL AND needs_assessment=0").fetchall()
    bands = {"within_target": 0, "within_appetite": 0, "outside_appetite": 0, "outside_tolerance": 0}
    above = []
    for r in rows:
        rk = mx.rank(r["res_l"], r["res_c"])
        bands[mx.band(rk)] += 1
        if rk > mx.THRESH["appetite"]:
            d = db.execute("SELECT status,expiry_date,reference FROM board_decisions WHERE risk_id=? ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
            above.append({"id": r["id"], "ref": r["ref"], "title": r["title"], "rank": rk, "level": mx.level(rk), "band": mx.band(rk), "decision": d["status"] if d else "none", "expiry": d["expiry_date"] if d else None, "approved_valid": board_ok(db, r["id"])})
    above.sort(key=lambda x: -x["rank"])
    return {"thresholds": dict(mx.THRESH), "bands": bands, "above": above, "unassessed": db.execute("SELECT COUNT(*) c FROM risks WHERE deleted_at IS NULL AND needs_assessment=1").fetchone()["c"],
            "statements": [stmt_dict(db, s) for s in db.execute("SELECT * FROM appetite_statements WHERE active=1 ORDER BY sort, id")],
            "versions": [dict(v, snapshot=json.loads(v["snapshot"])) for v in db.execute("SELECT * FROM appetite_versions ORDER BY id DESC LIMIT 10")],
            "policy": {"section": "2.4", "quote": "With regards any identified risk, a net risk score of greater than 10 is in excess of tolerable limits. Such a risk can only be taken with the approval of the board of directors."},
            "can": {a: a in c.perms.get("risk_appetite", set()) for a in core.ACTIONS}}


@router.route("PUT", "/api/appetite/thresholds")
def appetite_thresholds(req):
    c = need(req, "risk_appetite", "edit")
    d = req.json()
    try:
        t = {k: int(d[k]) for k in ("target", "appetite", "tolerance")}
    except (KeyError, TypeError, ValueError):
        raise HTTPError(400, "validation", "Give whole numbers for target, appetite and tolerance.")
    if not 1 <= t["target"] <= t["appetite"] <= t["tolerance"] <= 25:
        raise HTTPError(400, "validation", "Thresholds must satisfy 1 <= target <= appetite <= tolerance <= 25 (ranks on the ranked matrix).")
    ref, reason = need_str(d, "reference", "The Board approval reference", 200), need_str(d, "reason", "A reason", 500)
    if len(ref) < 5 or len(reason) < 5:
        raise HTTPError(400, "validation", "Give the Board approval reference (for example the minute number) and a reason of at least 5 characters.")
    old = dict(mx.THRESH)
    db = req.db
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('appetite',?)", (json.dumps(t),))
    db.execute("INSERT INTO appetite_versions(ts,username,reference,reason,snapshot) VALUES(?,?,?,?,?)", (now(), c.user["username"], ref, reason, json.dumps({"thresholds": t, "previous": old})))
    mx.set_thresholds(t)
    audit(db, "appetite.thresholds", c.user, "risk_appetite", "Thresholds target/appetite/tolerance %s -> %s (%s)" % ("/".join(str(old[k]) for k in ("target", "appetite", "tolerance")), "/".join(str(t[k]) for k in ("target", "appetite", "tolerance")), ref), req.ip)
    return {"thresholds": t}


def stmt_fields(d):
    dim = need_str(d, "dimension", "Dimension", 80)
    stance = (d.get("stance") or "").strip() or None
    if stance and stance not in ("Averse", "Cautious", "Open"):
        raise HTTPError(400, "validation", "Stance must be Averse, Cautious or Open.")
    direction = d.get("direction") or "max"
    if direction not in ("max", "min"):
        raise HTTPError(400, "validation", "Direction must be max or min.")
    def fl(k, label, lo=None, hi=None):
        v = d.get(k)
        if v in (None, ""):
            return None
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise HTTPError(400, "validation", "%s must be a number." % label)
        if lo is not None and not lo <= v <= hi:
            raise HTTPError(400, "validation", "%s must be between %s and %s." % (label, lo, hi))
        return v
    return {"dimension": dim, "statement": need_str(d, "statement", "Statement", 600), "stance": stance, "metric": need_str(d, "metric", "Metric", 160, False) or None, "unit": need_str(d, "unit", "Unit", 20, False) or None,
            "direction": direction, "limit_value": fl("limit", "Limit"), "amber": fl("amber", "Near-limit factor", 0.1, 1.0) or 0.8, "owner": need_str(d, "owner", "Owner", 120, False) or None}


@router.route("POST", "/api/appetite/statements")
def stmt_create(req):
    c = need(req, "risk_appetite", "create")
    f = stmt_fields(req.json())
    sid = req.db.execute("INSERT INTO appetite_statements(dimension,statement,stance,metric,unit,direction,limit_value,amber,source,owner,sort) VALUES(?,?,?,?,?,?,?,?,'manual',?,90)", (f["dimension"], f["statement"], f["stance"], f["metric"], f["unit"], f["direction"], f["limit_value"], f["amber"], f["owner"])).lastrowid
    audit(req.db, "appetite.statement_added", c.user, "risk_appetite", "Statement added: %s" % f["dimension"], req.ip)
    return {"id": sid}


@router.route("PUT", "/api/appetite/statements/<int:sid>")
def stmt_update(req):
    c = need(req, "risk_appetite", "edit")
    s = req.db.execute("SELECT * FROM appetite_statements WHERE id=? AND active=1", (int(req.params["sid"]),)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Statement not found")
    d = req.json()
    f = stmt_fields(dict(d, dimension=d.get("dimension") or s["dimension"], statement=d.get("statement") or s["statement"]))
    actual = s["actual"]
    if not s["source"].startswith("computed:") and "actual" in d:
        try:
            actual = None if d["actual"] in (None, "") else float(d["actual"])
        except (TypeError, ValueError):
            raise HTTPError(400, "validation", "The actual value must be a number.")
    req.db.execute("UPDATE appetite_statements SET dimension=?,statement=?,stance=?,metric=?,unit=?,direction=?,limit_value=?,amber=?,owner=?,actual=?,actual_note=?,actual_at=? WHERE id=?",
                   (f["dimension"], f["statement"], f["stance"], f["metric"], f["unit"], f["direction"], f["limit_value"], f["amber"], f["owner"], actual, need_str(d, "actual_note", "Note", 300, False) or s["actual_note"], now() if "actual" in d else s["actual_at"], s["id"]))
    audit(req.db, "appetite.statement_changed", c.user, "risk_appetite", "Statement %d (%s) changed" % (s["id"], f["dimension"]), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/appetite/statements/<int:sid>")
def stmt_delete(req):
    c = need(req, "risk_appetite", "delete")
    s = req.db.execute("SELECT * FROM appetite_statements WHERE id=? AND active=1", (int(req.params["sid"]),)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Statement not found")
    req.db.execute("UPDATE appetite_statements SET active=0 WHERE id=?", (s["id"],))
    audit(req.db, "appetite.statement_removed", c.user, "risk_appetite", "Statement %d removed (%s)" % (s["id"], s["dimension"]), req.ip)
    return {"ok": True}
