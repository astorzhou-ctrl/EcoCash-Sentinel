"""Step 5 (BRD phase P2), part 2: Incidents & Losses, with the 24-hour personal-data-breach clock."""
import datetime
import re

from . import core, db as dbm
from .api import router, need, need_str, DATE_RE
from .core import audit, now
from .p2 import heads_of_risk_emails, xlsx_response, fnum
from . import xlsxbook, matrix as mx
from .risks import scope_sql, history as risk_history, CATEGORIES
from .web import HTTPError

KINDS = {"incident": "Incident", "near_miss": "Near miss", "loss": "Loss event"}
SEVERITY = ("Low", "Medium", "High", "Critical")
FLOW = {"open": ("contained", "investigating", "closed"), "contained": ("investigating", "closed"), "investigating": ("closed",), "closed": ("open",)}
CATS = CATEGORIES + ["Personal data", "Other"]


def parse_dt(s, label="Detected"):
    s = (s or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", s)
    if not m:
        raise HTTPError(400, "validation", "%s must be a date and time." % label)
    try:
        d = datetime.datetime.fromisoformat("%sT%s:%s:%s" % (m.group(1), m.group(2) or "00", m.group(3) or "00", m.group(4) or "00"))
    except ValueError:
        raise HTTPError(400, "validation", "%s must be a valid date and time." % label)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def clock(i):
    """GRC/privacy rule: a personal-data breach starts a 24-hour clock at detection; it stops when the regulator is notified."""
    if not i["pdb"]:
        return None
    deadline = datetime.datetime.strptime(i["detected_at"], "%Y-%m-%dT%H:%M:%SZ") + datetime.timedelta(hours=24)
    left = (deadline - utcnow()).total_seconds() / 3600
    if i["notified_at"]:
        done = datetime.datetime.strptime(i["notified_at"], "%Y-%m-%dT%H:%M:%SZ")
        return {"deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"), "notified": True, "late": done > deadline, "hours_left": None, "overdue": False}
    return {"deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"), "notified": False, "late": False, "hours_left": round(left, 1), "overdue": left < 0}


def inc_dict(i, risks):
    r = risks.get(i["risk_id"])
    d = {k: i[k] for k in ("id", "ref", "title", "kind", "category", "severity", "occurred_on", "detected_at", "description", "risk_id", "control_text", "gross_loss", "recovered", "status", "owner", "root_cause", "pdb", "notified_at", "notified_note", "closed_at", "created_at")}
    d["pdb"] = bool(i["pdb"]); d["net_loss"] = round(i["gross_loss"] - i["recovered"], 2); d["unlinked"] = not (i["risk_id"] and (i["control_text"] or "").strip())
    d["risk"] = {"id": r["id"], "ref": r["ref"], "title": r["title"]} if r else None
    d["clock"] = clock(i); d["kind_label"] = KINDS.get(i["kind"], i["kind"])
    return d


def scope(c):
    if c.user["data_scope"] == "all":
        return "1=1", []
    return "(created_by=? OR owner=? COLLATE NOCASE OR owner=? COLLATE NOCASE)", [c.user["id"], c.user["full_name"], c.user["username"]]


def visible(req, c):
    w, a = scope(c)
    risks = {r["id"]: r for r in req.db.execute("SELECT id, ref, title FROM risks WHERE deleted_at IS NULL")}
    return [inc_dict(i, risks) for i in req.db.execute("SELECT * FROM incidents WHERE deleted_at IS NULL AND %s ORDER BY occurred_on DESC, id DESC" % w, a)], risks


def clean(db, d, existing=None):
    f = {"title": need_str(d, "title", "Title", 200), "description": need_str(d, "description", "Description", 2000, False), "owner": need_str(d, "owner", "Owner", 120, False) or None,
         "control_text": need_str(d, "control_text", "The control that failed or applied", 300, False) or None, "root_cause": need_str(d, "root_cause", "Root cause", 1000, False) or None}
    f["kind"] = (d.get("kind") or "incident").strip()
    f["severity"] = (d.get("severity") or "Medium").strip()
    f["category"] = (d.get("category") or "Other").strip()
    if f["kind"] not in KINDS or f["severity"] not in SEVERITY or f["category"] not in CATS:
        raise HTTPError(400, "validation", "Choose the kind, severity and category from the lists.")
    occ = (d.get("occurred_on") or "").strip()
    if not DATE_RE.match(occ) or occ > str(dbm.today()):
        raise HTTPError(400, "validation", "Give the date the event happened (today or earlier).")
    f["occurred_on"] = occ
    f["pdb"] = 1 if d.get("pdb") else 0
    det = (d.get("detected_at") or "").strip()
    f["detected_at"] = parse_dt(det) if det else (existing["detected_at"] if existing else now())
    if f["detected_at"] > now():
        raise HTTPError(400, "validation", "Detection cannot be in the future.")
    f["gross_loss"] = fnum(d.get("gross_loss", 0), "Gross loss", False, 0) or 0.0
    f["recovered"] = fnum(d.get("recovered", 0), "Recovered", False, 0) or 0.0
    if f["recovered"] > f["gross_loss"]:
        raise HTTPError(400, "validation", "The amount recovered cannot exceed the gross loss.")
    if f["kind"] == "near_miss" and f["gross_loss"]:
        raise HTTPError(400, "validation", "A near miss has no loss. Record it as an incident or loss event if money was lost.")
    rid = d.get("risk_id")
    if rid not in (None, "", 0):
        if not db.execute("SELECT 1 FROM risks WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone():
            raise HTTPError(400, "validation", "Unknown risk.")
        f["risk_id"] = int(rid)
    else:
        f["risk_id"] = None
    return f


def get_inc(req, c, iid):
    w, a = scope(c)
    i = req.db.execute("SELECT * FROM incidents WHERE id=? AND deleted_at IS NULL AND %s" % w, [iid] + a).fetchone()
    if not i:
        raise HTTPError(404, "not_found", "Incident not found")
    return i


@router.route("GET", "/api/incidents")
def inc_list(req):
    c = need(req, "incidents_losses", "view")
    rows, risks = visible(req, c)
    t = dbm.today(); q = req.query
    def net(r): return r["net_loss"]
    tiles = {"open": sum(1 for r in rows if r["status"] != "closed" and r["kind"] != "near_miss"), "near_misses": sum(1 for r in rows if r["kind"] == "near_miss" and r["occurred_on"] >= str(t - datetime.timedelta(days=90))),
             "net_ytd": round(sum(net(r) for r in rows if r["occurred_on"] >= "%d-01-01" % t.year), 2), "net_30d": round(sum(net(r) for r in rows if r["occurred_on"] >= str(t - datetime.timedelta(days=30))), 2),
             "unlinked": sum(1 for r in rows if r["unlinked"] and r["status"] != "closed"), "clocks": sum(1 for r in rows if r["clock"] and not r["clock"]["notified"] and r["status"] != "closed")}
    cat = {}
    for r in rows:
        if net(r):
            cat[r["category"]] = cat.get(r["category"], 0) + net(r)
    months = []
    for i in range(11, -1, -1):
        y, m = t.year, t.month - i
        while m <= 0:
            m += 12; y -= 1
        key = "%04d-%02d" % (y, m)
        months.append({"month": datetime.date(y, m, 1).strftime("%b %Y"), "net": round(sum(net(r) for r in rows if r["occurred_on"].startswith(key)), 2)})
    flt = rows
    if q.get("status"):
        flt = [r for r in flt if r["status"] == q["status"]]
    if q.get("kind"):
        flt = [r for r in flt if r["kind"] == q["kind"]]
    if q.get("category"):
        flt = [r for r in flt if r["category"] == q["category"]]
    if q.get("q"):
        s = q["q"].lower(); flt = [r for r in flt if s in (r["ref"] + " " + r["title"] + " " + (r["owner"] or "")).lower()]
    w, a = scope(c)
    vis_risks = req.db.execute("SELECT id, ref, title FROM risks WHERE deleted_at IS NULL AND %s ORDER BY ref" % scope_sql(c)[0], scope_sql(c)[1]).fetchall()
    return {"incidents": flt, "total": len(flt), "tiles": tiles, "by_category": sorted([{"category": k, "net": round(v, 2)} for k, v in cat.items()], key=lambda x: -x["net"]), "by_month": months,
            "clocks": [r for r in rows if r["clock"] and not r["clock"]["notified"] and r["status"] != "closed"], "kinds": KINDS, "severities": SEVERITY, "categories": CATS,
            "risks": [dict(r) for r in vis_risks], "can": {x: x in c.perms.get("incidents_losses", set()) for x in core.ACTIONS}}


@router.route("POST", "/api/incidents")
def inc_create(req):
    c = need(req, "incidents_losses", "create")
    f = clean(req.db, req.json())
    cols = list(f) + ["status", "created_at", "created_by"]
    iid = req.db.execute("INSERT INTO incidents(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), list(f.values()) + ["open", now(), c.user["id"]]).lastrowid
    ref = "INC-%03d" % iid
    req.db.execute("UPDATE incidents SET ref=? WHERE id=?", (ref, iid))
    if f["severity"] in ("High", "Critical") or f["pdb"]:
        for e in heads_of_risk_emails(req.db):
            core.outbox(req.db, e, "Sentinel: %s %s - %s" % (f["severity"], KINDS[f["kind"]].lower(), ref), "%s: %s. %s%s" % (ref, f["title"], f["description"] or "", " Personal-data breach: the 24-hour clock is running." if f["pdb"] else ""), "incident")
    audit(req.db, "incident.created", c.user, "incidents_losses", "%s %s (%s, %s%s)" % (ref, f["title"], KINDS[f["kind"]], f["severity"], ", personal-data breach" if f["pdb"] else ""), req.ip)
    return {"id": iid, "ref": ref}


@router.route("GET", "/api/incidents/<int:iid>")
def inc_get(req):
    c = need(req, "incidents_losses", "view")
    i = get_inc(req, c, int(req.params["iid"]))
    risks = {r["id"]: r for r in req.db.execute("SELECT id, ref, title FROM risks WHERE deleted_at IS NULL")}
    d = inc_dict(i, risks)
    d["events"] = [dict(r) for r in req.db.execute("SELECT ts, username, event, detail FROM audit WHERE detail LIKE ? ORDER BY id DESC LIMIT 30", ("%" + i["ref"] + "%",))]
    d["can"] = {x: x in c.perms.get("incidents_losses", set()) for x in core.ACTIONS}
    return d


@router.route("PUT", "/api/incidents/<int:iid>")
def inc_update(req):
    c = need(req, "incidents_losses", "edit")
    i = get_inc(req, c, int(req.params["iid"]))
    if i["status"] == "closed" and "approve" not in c.perms.get("incidents_losses", set()):
        raise HTTPError(409, "closed", "A closed incident can only be changed after it is reopened by someone who can approve.")
    f = clean(req.db, req.json(), i)
    if i["pdb"] and not f["pdb"] and i["notified_at"]:
        raise HTTPError(409, "validation", "The regulator was already notified, so this cannot be un-flagged as a personal-data breach.")
    req.db.execute("UPDATE incidents SET %s, updated_at=? WHERE id=?" % ",".join("%s=?" % k for k in f), list(f.values()) + [now(), i["id"]])
    audit(req.db, "incident.updated", c.user, "incidents_losses", "%s changed" % i["ref"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/incidents/<int:iid>/status")
def inc_status(req):
    c = need(req, "incidents_losses", "edit")
    i = get_inc(req, c, int(req.params["iid"]))
    d = req.json()
    to, note = d.get("to"), need_str(d, "note", "Note", 400, False)
    if to not in FLOW.get(i["status"], ()):
        raise HTTPError(409, "bad_transition", "A %s incident cannot move to %s." % (i["status"], to))
    if to == "open" and ("approve" not in c.perms.get("incidents_losses", set()) or len(note) < 5):
        raise HTTPError(403, "forbidden", "Reopening needs someone who can approve, and a reason (at least 5 characters).")
    if to == "closed":
        if len((i["root_cause"] or "").strip()) < 5:
            raise HTTPError(400, "root_cause_required", "Record the root cause before closing (edit the incident).")
        if i["pdb"] and not i["notified_at"]:
            raise HTTPError(409, "regulator_not_notified", "This is a personal-data breach. Record the regulator notification before closing.")
        req.db.execute("UPDATE incidents SET status='closed', closed_at=?, closed_by=?, updated_at=? WHERE id=?", (now(), c.user["username"], now(), i["id"]))
        if i["risk_id"]:
            risk_history(req.db, i["risk_id"], c.user, "incident closed", {"incident": [None, "%s: re-assess this risk" % i["ref"]]})
    else:
        req.db.execute("UPDATE incidents SET status=?, closed_at=NULL, closed_by=NULL, updated_at=? WHERE id=?", (to, now(), i["id"]))
    audit(req.db, "incident.status", c.user, "incidents_losses", "%s %s to %s%s" % (i["ref"], i["status"], to, (": " + note) if note else ""), req.ip)
    return {"status": to, "reassess": bool(to == "closed" and i["risk_id"])}


@router.route("POST", "/api/incidents/<int:iid>/notify")
def inc_notify(req):
    c = need(req, "incidents_losses", "edit")
    i = get_inc(req, c, int(req.params["iid"]))
    if not i["pdb"]:
        raise HTTPError(409, "bad_state", "Only a personal-data breach has a regulator notification.")
    if i["notified_at"]:
        raise HTTPError(409, "bad_state", "The regulator notification is already recorded.")
    note = need_str(req.json(), "note", "The notification reference", 300)
    if len(note) < 5:
        raise HTTPError(400, "validation", "Give the notification reference or note (at least 5 characters).")
    req.db.execute("UPDATE incidents SET notified_at=?, notified_note=?, updated_at=? WHERE id=?", (now(), note, now(), i["id"]))
    late = now() > clock(i)["deadline"]
    audit(req.db, "incident.notified", c.user, "incidents_losses", "%s regulator notified%s: %s" % (i["ref"], " (LATE: after the 24-hour clock)" if late else " within 24 hours", note[:100]), req.ip)
    return {"late": late}


@router.route("DELETE", "/api/incidents/<int:iid>")
def inc_delete(req):
    c = need(req, "incidents_losses", "delete")
    i = get_inc(req, c, int(req.params["iid"]))
    reason = need_str(req.json(), "reason", "A reason", 300)
    if len(reason) < 3:
        raise HTTPError(400, "validation", "Give a reason of at least 3 characters.")
    pol = dbm.get_policy(req.db)
    req.db.execute("UPDATE incidents SET deleted_at=?, deleted_by=?, delete_reason=? WHERE id=?", (now(), c.user["id"], reason, i["id"]))
    req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at) VALUES('incident',?,?,?,?,?,?,?,?)", (i["id"], "%s %s" % (i["ref"], i["title"]), "Incidents & Losses", c.user["id"], c.user["username"], now(), reason, dbm.plus(days=pol["recycle_days"])))
    audit(req.db, "incident.deleted", c.user, "incidents_losses", "%s deleted: %s" % (i["ref"], reason), req.ip)
    return {"ok": True}


@router.route("GET", "/api/incidents/export.xlsx")
def inc_export(req):
    c = need(req, "incidents_losses", "export")
    rows, _ = visible(req, c)
    sheet = [[("Incidents and losses", 3)], ["Generated", ("date", str(dbm.today())), "By", c.user["username"]], [],
             [(h, 1) for h in ("Ref", "Title", "Kind", "Category", "Severity", "Status", "Happened", "Detected", "Owner", "Risk", "Control", "Gross loss", "Recovered", "Net loss", "Personal-data breach", "Regulator notified", "Root cause")]]
    for r in rows:
        sheet.append([r["ref"], r["title"], r["kind_label"], r["category"], r["severity"], r["status"], ("date", r["occurred_on"]), r["detected_at"], r["owner"], r["risk"]["ref"] if r["risk"] else "NOT LINKED", r["control_text"] or "NOT LINKED", r["gross_loss"], r["recovered"], r["net_loss"],
                      "yes" if r["pdb"] else "", r["notified_at"] or ("NOT YET" if r["pdb"] else ""), r["root_cause"]])
    audit(req.db, "export.incidents", c.user, "incidents_losses", "Exported %d incidents" % len(rows), req.ip)
    return xlsx_response(xlsxbook.write([("Incidents", sheet, [10, 44, 12, 16, 10, 13, 12, 22, 20, 10, 30, 12, 12, 12, 12, 22, 40])]), "Sentinel_incidents_%s.xlsx" % dbm.today())
