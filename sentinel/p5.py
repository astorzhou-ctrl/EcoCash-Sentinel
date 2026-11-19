"""Step 8: Control Library and Testing, Actions and Issues, and verified backups.
GRC Policy 2.5 and the control-effectiveness scale (policy p26): a control is scored 1 (highly effective) to 10 (non-existent); the factor is score / 10
and the effectiveness is 100% less 10 points per score. Scores 1 to 3 are Accept, 4 to 6 Mitigate, 7 to 10 Immediate Action."""
import datetime
import hashlib
import json
import os
import re
import sqlite3

from . import config, core, db as dbm, matrix, p2, risks as riskmod, wbimport, xlsxbook
from .api import router, need, need_str, DATE_RE
from .core import audit, now, outbox
from .web import HTTPError, Response

BANDS = {1: ("Strong", "Accept"), 2: ("Strong", "Accept"), 3: ("Reasonably Strong", "Accept"), 4: ("Good", "Mitigate"), 5: ("Adequate", "Mitigate"), 6: ("Marginally Adequate", "Mitigate"),
         7: ("Needs Improvement", "Immediate Action"), 8: ("Weak", "Immediate Action"), 9: ("Very Weak", "Immediate Action"), 10: ("Non-Existent", "Immediate Action")}
TARGET_EFF = 0.8  # the policy's 80% (score 2)
SOURCES = ("manual", "risk", "control_test", "audit", "incident", "board", "compliance")
OPEN = ("open", "in_progress", "awaiting_verification")
CM, AM = "control_library_testing", "actions_issues"
d2 = datetime.date.fromisoformat
today = lambda: p2.today()


def score_of(ice):
    return None if ice is None else max(1, min(10, int(round(ice * 10))))


def me(c):
    return (c.user["full_name"] or c.user["username"]).strip()


def same(a, b):
    return bool(a and b and a.strip().lower() == b.strip().lower())


def ice_val(d):
    try:
        v = float(d.get("ice"))
    except (TypeError, ValueError):
        raise HTTPError(400, "validation", "Self-rated effectiveness (ICE) must be a number from 0.1 to 1.0 (score divided by 10).")
    if not 0.1 <= v <= 1.0:
        raise HTTPError(400, "validation", "Self-rated effectiveness (ICE) must be from 0.1 to 1.0 (score divided by 10).")
    return round(v, 1)


def clean_date(v, label, future_ok=True, past_ok=True):
    v = (v or "").strip()
    if not DATE_RE.match(v):
        raise HTTPError(400, "validation", "%s must be a date (YYYY-MM-DD)." % label)
    try:
        d = d2(v)
    except ValueError:
        raise HTTPError(400, "validation", "%s is not a real date." % label)
    if not future_ok and d > today():
        raise HTTPError(400, "validation", "%s cannot be in the future." % label)
    if not past_ok and d < today():
        raise HTTPError(400, "validation", "%s cannot be in the past." % label)
    return v


# ------------------------------------------------------------------ Control Library and Testing
def enrich(k, t):
    sc = score_of(k["ice"]); band = BANDS.get(sc)
    rank = matrix.rank(k["res_l"], k["res_c"]) if not k["needs_assessment"] else None
    high = rank is not None and rank >= 13
    nd = k["next_due"]
    if not k["last_test"]:
        status = "never"
    elif nd and nd < str(t):
        status = "overdue"
    elif nd and nd <= str(t + datetime.timedelta(days=30)):
        status = "due_soon"
    else:
        status = "ok"
    return {"id": k["id"], "ref": k["ref"], "statement": k["statement"], "domain": k["domain"], "ctype": k["ctype"], "owner": k["owner"], "dept": wbimport.dept_of(k["owner"]) if k["owner"] else None, "ice": k["ice"], "score": sc,
            "effectiveness": None if sc is None else 100 - sc * 10, "classification": band[0] if band else None, "treat": band[1] if band else None, "ice_source": k["ice_source"] or "self", "last_test": k["last_test"], "next_due": nd,
            "status": status, "needs_test": status in ("overdue",) or (status == "never" and high), "risk": {"id": k["risk_id"], "ref": k["rref"], "title": k["rtitle"], "rank": rank, "level": matrix.level(rank) if rank else None}, "result": k["result"], "attested_on": k["attested_on"]}


def ctrl_all(db, c):
    sc, sp = riskmod.scope_sql(c)
    t = today()
    return [enrich(k, t) for k in db.execute("SELECT k.*, r.ref rref, r.title rtitle, r.res_l, r.res_c, r.needs_assessment FROM risk_controls k JOIN risks r ON r.id=k.risk_id WHERE r.deleted_at IS NULL AND " + sc + " ORDER BY k.id", sp)]


def ctrl_one(db, c, cid):
    sc, sp = riskmod.scope_sql(c)
    k = db.execute("SELECT k.*, r.ref rref, r.title rtitle, r.res_l, r.res_c, r.needs_assessment FROM risk_controls k JOIN risks r ON r.id=k.risk_id WHERE k.id=? AND r.deleted_at IS NULL AND " + sc, [cid] + sp).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Control not found.")
    return k


@router.route("GET", "/api/controls")
def controls_list(req):
    c = need(req, CM, "view")
    rows = ctrl_all(req.db, c); t = today(); q = req.query
    tested = [x for x in rows if x["last_test"] and x["last_test"] >= str(t - datetime.timedelta(days=365))]
    scored = [x for x in rows if x["score"]]
    tiles = {"total": len(rows), "tested_12m": len(tested), "tested_pct": round(len(tested) / len(rows) * 100, 1) if rows else 0, "avg_effectiveness": round(sum(x["effectiveness"] for x in scored) / len(scored), 1) if scored else None,
             "failing": sum(1 for x in scored if x["score"] >= 7), "no_owner": sum(1 for x in rows if not x["owner"]), "due": sum(1 for x in rows if x["needs_test"]), "overdue": sum(1 for x in rows if x["status"] == "overdue")}
    dom = {}
    for x in scored:
        dom.setdefault(x["domain"] or "Unclassified", []).append(x["effectiveness"])
    domains = sorted([{"domain": d, "n": len(v), "effectiveness": round(sum(v) / len(v), 1)} for d, v in dom.items()], key=lambda z: z["effectiveness"])
    qt = {}
    for r in req.db.execute("SELECT tested_on, score FROM control_tests"):
        key = "%s Q%d" % (r["tested_on"][:4], (int(r["tested_on"][5:7]) - 1) // 3 + 1); a = qt.setdefault(key, [0, 0]); a[0] += 1; a[1] += 1 if r["score"] >= 7 else 0
    quarters = [{"q": k, "tests": v[0], "failed": v[1]} for k, v in sorted(qt.items())][-6:]
    text = (q.get("q") or "").strip().lower()
    dm, ow, st, band, rk = [(q.get(x) or "").strip() for x in ("domain", "dept", "status", "band", "risk")]
    def keep(x):
        if text and text not in (" ".join(str(x[k] or "") for k in ("ref", "statement", "owner", "domain")) + " " + str(x["risk"]["ref"] or "")).lower():
            return False
        if dm and x["domain"] != dm or ow and x["dept"] != ow or rk and x["risk"]["ref"] != rk:
            return False
        if st == "due" and not x["needs_test"] or st in ("never", "overdue", "due_soon", "ok") and x["status"] != st:
            return False
        if st == "noowner" and x["owner"]:
            return False
        if band == "weak" and not (x["score"] and x["score"] >= 7) or band == "adequate" and not (x["score"] and 4 <= x["score"] <= 6) or band == "strong" and not (x["score"] and x["score"] <= 3) or band == "unscored" and x["score"]:
            return False
        return True
    out = [x for x in rows if keep(x)]
    order = {"overdue": 0, "never": 1, "due_soon": 2, "ok": 3}
    out.sort(key=lambda x: (0 if x["needs_test"] else 1, order[x["status"]], -(x["risk"]["rank"] or 0), x["ref"] or ""))
    page, size = max(1, int(q.get("page") or 1)), 50
    return {"controls": out[(page - 1) * size: page * size], "total": len(out), "page": page, "size": size, "tiles": tiles, "domains": domains, "quarters": quarters, "target": TARGET_EFF * 100,
            "depts": sorted({x["dept"] for x in rows if x["dept"]}), "domain_list": sorted({x["domain"] for x in rows if x["domain"]}), "can": {a: a in c.perms.get(CM, set()) for a in core.ACTIONS}}


@router.route("GET", "/api/controls/<int:cid>")
def control_get(req):
    c = need(req, CM, "view")
    k = enrich(ctrl_one(req.db, c, req.params["cid"]), today())
    tests = [dict(r) for r in req.db.execute("SELECT * FROM control_tests WHERE control_id=? ORDER BY tested_on DESC, id DESC", (k["id"],))]
    att = [dict(r) for r in req.db.execute("SELECT * FROM control_attest WHERE control_id=? ORDER BY period DESC", (k["id"],))]
    acts = [{"id": a["id"], "ref": a["ref"], "title": a["title"], "status": a["status"], "due": a["due_date"]} for a in req.db.execute("SELECT * FROM actions WHERE control_id=? AND deleted_at IS NULL ORDER BY id DESC", (k["id"],))]
    return {"control": k, "tests": tests, "attestations": att, "actions": acts, "scale": [{"score": s, "classification": b[0], "treat": b[1], "effectiveness": 100 - s * 10} for s, b in BANDS.items()], "independent": not same(k["owner"], me(c)), "can": {a: a in c.perms.get(CM, set()) for a in core.ACTIONS}}


def clean_control(d, partial=False):
    out = {"statement": need_str(d, "statement", "Control description", 600), "domain": need_str(d, "domain", "Domain", 80, False) or None, "ctype": need_str(d, "ctype", "Control type", 60, False) or None, "owner": need_str(d, "owner", "Owner", 120, False) or None}
    return out


@router.route("POST", "/api/controls")
def control_add(req):
    c = need(req, CM, "create")
    d = req.json(); f = clean_control(d); rid = int(d.get("risk_id") or 0)
    sc, sp = riskmod.scope_sql(c)
    r = req.db.execute("SELECT * FROM risks WHERE id=? AND deleted_at IS NULL AND " + sc, [rid] + sp).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Choose a risk you can see.")
    ice = d.get("ice")
    ice = None if ice in (None, "") else ice_val(d)
    cid = req.db.execute("INSERT INTO risk_controls(risk_id,ref,statement,domain,ctype,ice,owner,ice_source) VALUES(?,?,?,?,?,?,?,?)", (rid, need_str(d, "ref", "Reference", 40, False) or None, f["statement"], f["domain"], f["ctype"], ice, f["owner"], "self")).lastrowid
    riskmod.history(req.db, rid, c.user, "control added", {"control": f["statement"][:80]})
    audit(req.db, "control.add", c.user, CM, "Control added to %s: %s" % (r["ref"], f["statement"][:80]), req.ip)
    return {"id": cid}


@router.route("PUT", "/api/controls/<int:cid>")
def control_edit(req):
    c = need(req, CM, "edit")
    k = ctrl_one(req.db, c, req.params["cid"]); d = req.json(); f = clean_control(d)
    ice = k["ice"]
    if "ice" in d and d["ice"] not in (None, ""):
        if (k["ice_source"] or "self") == "test":
            raise HTTPError(409, "from_tests", "The current effectiveness of this control comes from its test results. Record a new test to change it.")
        ice = ice_val(d)
    req.db.execute("UPDATE risk_controls SET statement=?, domain=?, ctype=?, owner=?, ice=?, score=? WHERE id=?", (f["statement"], f["domain"], f["ctype"], f["owner"], ice, score_of(ice), k["id"]))
    riskmod.history(req.db, k["risk_id"], c.user, "control edited", {"control": (k["ref"] or "")[:40], "owner": f["owner"]})
    audit(req.db, "control.edit", c.user, CM, "Control %s edited" % (k["ref"] or k["id"]), req.ip)
    return {"ok": True}


@router.route("POST", "/api/controls/<int:cid>/tests")
def control_test(req):
    c = need(req, CM, "edit")
    k = ctrl_one(req.db, c, req.params["cid"]); d = req.json()
    ttype = d.get("ttype")
    if ttype not in ("design", "operating"):
        raise HTTPError(400, "validation", "Choose design or operating test.")
    on = clean_date(d.get("tested_on"), "Test date", future_ok=False)
    if on < "2020-01-01":
        raise HTTPError(400, "validation", "Test date is too far in the past.")
    try:
        sc = int(d.get("score")); assert 1 <= sc <= 10
    except (TypeError, ValueError, AssertionError):
        raise HTTPError(400, "validation", "Score the control from 1 (highly effective) to 10 (non-existent), as in the GRC Policy scale.")
    ev = need_str(d, "evidence", "Evidence and what was tested", 1500)
    if len(ev) < 10:
        raise HTTPError(400, "validation", "Describe what was tested and the evidence (at least 10 characters).")
    if same(k["owner"], me(c)):
        raise HTTPError(409, "independence", "The control owner cannot test their own control. Ask someone independent (Risk Office or Internal Audit) to record the test.")
    band = BANDS[sc]; result = "effective" if sc <= 3 else "partially effective" if sc <= 6 else "ineffective"
    t = d2(on); rank = matrix.rank(k["res_l"], k["res_c"]) if not k["needs_assessment"] else 0
    due = str(t + datetime.timedelta(days=180 if rank >= 13 else 365))
    new_ice = round(sc / 10.0, 1)
    req.db.execute("INSERT INTO control_tests(control_id,ttype,tested_on,tester,tester_id,score,result,evidence,prev_ice,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (k["id"], ttype, on, me(c), c.user["id"], sc, result, ev, k["ice"], now()))
    if not k["last_test"] or on >= k["last_test"]:  # an older test recorded late does not overwrite a newer one
        req.db.execute("UPDATE risk_controls SET ice=?, score=?, ice_source='test', last_test=?, result=?, next_due=? WHERE id=?", (new_ice, sc, on, result, due, k["id"]))
        riskmod.history(req.db, k["risk_id"], c.user, "control tested", {"control": (k["ref"] or "")[:40], "ice": [k["ice"], new_ice], "result": result})
    act = None
    if sc >= 7 and not req.db.execute("SELECT 1 FROM actions WHERE control_id=? AND source='control_test' AND status IN ('open','in_progress','awaiting_verification') AND deleted_at IS NULL", (k["id"],)).fetchone():
        act = make_action(req.db, c, {"title": "Remediate control %s after a failed test (score %d, %s)" % (k["ref"] or k["id"], sc, band[0]), "description": "%s test on %s scored %d: %s. %s" % (ttype.capitalize(), on, sc, band[1], ev[:300]), "source": "control_test", "risk_id": k["risk_id"],
                                       "control_id": k["id"], "owner_name": k["owner"] or "Head of Risk", "priority": "High", "due_date": str(today() + datetime.timedelta(days=30))})
    audit(req.db, "control.test", c.user, CM, "%s test of %s scored %d (%s)%s" % (ttype, k["ref"] or k["id"], sc, band[0], "; action %s raised" % act["ref"] if act else ""), req.ip)
    return {"score": sc, "classification": band[0], "treat": band[1], "result": result, "next_due": due, "action": act["ref"] if act else None}


def quarter(t):
    return "%d-Q%d" % (t.year, (t.month - 1) // 3 + 1)


@router.route("POST", "/api/controls/<int:cid>/attest")
def control_attest(req):
    c = need(req, CM, "view")
    k = ctrl_one(req.db, c, req.params["cid"]); d = req.json()
    if not (same(k["owner"], me(c)) or "edit" in c.perms.get(CM, set())):
        raise HTTPError(403, "forbidden", "Only the control owner (or the Risk Office) can attest to a control.")
    ok = bool(d.get("ok")); note = need_str(d, "note", "Note", 400, False) or None
    if not ok and not note:
        raise HTTPError(400, "validation", "Say what is wrong when you cannot confirm the control is operating as designed.")
    req.db.execute("INSERT INTO control_attest(control_id,period,attested_by,ok,note,ts) VALUES(?,?,?,?,?,?) ON CONFLICT(control_id,period) DO UPDATE SET attested_by=excluded.attested_by, ok=excluded.ok, note=excluded.note, ts=excluded.ts", (k["id"], quarter(today()), me(c), 1 if ok else 0, note, now()))
    req.db.execute("UPDATE risk_controls SET attested_on=? WHERE id=?", (str(today()), k["id"]))
    act = None
    if not ok and not req.db.execute("SELECT 1 FROM actions WHERE control_id=? AND source='control_test' AND status IN ('open','in_progress','awaiting_verification') AND deleted_at IS NULL", (k["id"],)).fetchone():
        act = make_action(req.db, c, {"title": "Owner cannot confirm control %s is operating" % (k["ref"] or k["id"]), "description": note, "source": "control_test", "risk_id": k["risk_id"], "control_id": k["id"], "owner_name": k["owner"] or "Head of Risk", "priority": "High", "due_date": str(today() + datetime.timedelta(days=30))})
    audit(req.db, "control.attest", c.user, CM, "Quarterly attestation for %s: %s" % (k["ref"] or k["id"], "confirmed" if ok else "issue reported"), req.ip)
    return {"period": quarter(today()), "action": act["ref"] if act else None}


@router.route("GET", "/api/controls/export.xlsx")
def controls_export(req):
    c = need(req, CM, "export")
    rows = [[("EcoCash controls: library and test status", 3)], [("Effectiveness follows the GRC Policy scale: score 1 (highly effective) to 10 (non-existent); effectiveness = 100% less 10 points per score.", 4)], [], [(h, 1) for h in ("Control", "Description", "Domain", "Type", "Owner", "Department", "Risk", "Score", "Effectiveness %", "Classification", "Treatment", "Source of rating", "Last test", "Next due", "Test status")]]
    for x in ctrl_all(req.db, c):
        rows.append([x["ref"], x["statement"], x["domain"], x["ctype"], x["owner"], x["dept"], (x["risk"]["ref"] or "") + " " + (x["risk"]["title"] or "")[:60], x["score"], x["effectiveness"], x["classification"], x["treat"], x["ice_source"], x["last_test"], x["next_due"], x["status"]])
    audit(req.db, "export.controls", c.user, CM, "Control library downloaded (%d controls)" % (len(rows) - 4), req.ip)
    return p2.xlsx_response(xlsxbook.write([("Controls", rows, [16, 60, 22, 14, 24, 18, 40, 8, 14, 20, 16, 12, 12, 12, 12])]), "Sentinel_controls_%s.xlsx" % today())


# ------------------------------------------------------------------ Actions and Issues
def eff_due(a):
    return a["revised_due"] if a["revision_status"] == "approved" and a["revised_due"] else a["due_date"]


def a_log(db, aid, user, event, detail=None):
    db.execute("INSERT INTO action_log(action_id,ts,username,event,detail) VALUES(?,?,?,?,?)", (aid, now(), user if isinstance(user, str) else user["username"], event, detail))


def make_action(db, c, d):
    title = need_str(d, "title", "Title", 200); owner = need_str(d, "owner_name", "Owner", 120)
    src = d.get("source") or "manual"
    if src not in SOURCES:
        raise HTTPError(400, "validation", "Choose where the action comes from.")
    pr = d.get("priority") or "Medium"
    if pr not in ("Low", "Medium", "High"):
        raise HTTPError(400, "validation", "Priority must be Low, Medium or High.")
    due = clean_date(d.get("due_date"), "Due date")
    aid = db.execute("INSERT INTO actions(title,description,source,risk_id,control_id,incident_id,owner_name,priority,due_date,status,created_by,created_by_name,created_at) VALUES(?,?,?,?,?,?,?,?,?,'open',?,?,?)",
                     (title, need_str(d, "description", "Description", 1500, False) or None, src, d.get("risk_id") or None, d.get("control_id") or None, d.get("incident_id") or None, owner, pr, due, c.user["id"], me(c), now())).lastrowid
    ref = "ACT-%04d" % aid
    db.execute("UPDATE actions SET ref=? WHERE id=?", (ref, aid))
    a_log(db, aid, c.user, "created", "Owner %s, due %s" % (owner, due))
    em = p2.person_email(db, owner)
    if em:
        outbox(db, em, "Action assigned: %s %s" % (ref, title[:80]), "You are the owner of action %s, due %s.\n\n%s" % (ref, due, d.get("description") or title), "action")
    return {"id": aid, "ref": ref}


def vis_ids(db, c):
    sc, sp = riskmod.scope_sql(c)
    return {r["id"] for r in db.execute("SELECT id FROM risks WHERE deleted_at IS NULL AND " + sc, sp)}


def act_visible(c, a, rids):
    if c.user["data_scope"] == "all" or a["created_by"] == c.user["id"] or same(a["owner_name"], me(c)):
        return True
    return bool(a["risk_id"] and a["risk_id"] in rids)


def act_view(a, t):
    due = eff_due(a); open_ = a["status"] in OPEN; days = (t - d2(due)).days if open_ else 0
    lvl = 0 if days < 1 else 3 if days >= 7 else 2 if days >= 3 else 1
    age = (t - d2(a["created_at"][:10])).days
    return {"id": a["id"], "ref": a["ref"], "title": a["title"], "description": a["description"], "source": a["source"], "risk_id": a["risk_id"], "control_id": a["control_id"], "owner": a["owner_name"], "priority": a["priority"], "due": a["due_date"], "effective_due": due,
            "revised_due": a["revised_due"], "revision_status": a["revision_status"], "revision_reason": a["revision_reason"], "status": a["status"], "evidence": a["evidence"], "overdue": open_ and days > 0, "days_overdue": max(days, 0), "escalation": lvl, "esc_level": a["esc_level"],
            "age": age, "created_by": a["created_by_name"], "created_at": a["created_at"], "closed_at": a["closed_at"], "closed_by": a["closed_by"]}


def acts_all(db, c):
    rids = vis_ids(db, c); t = today()
    return [act_view(a, t) for a in db.execute("SELECT * FROM actions WHERE deleted_at IS NULL ORDER BY id DESC") if act_visible(c, a, rids)]


@router.route("GET", "/api/actions")
def actions_list(req):
    c = need(req, AM, "view")
    rows = acts_all(req.db, c); q = req.query
    live = [x for x in rows if x["status"] in OPEN]
    closed = [x for x in rows if x["status"] == "closed" and x["closed_at"]]
    days = [(d2(x["closed_at"][:10]) - d2(x["created_at"][:10])).days for x in closed]
    tiles = {"open": len(live), "on_time": sum(1 for x in live if not x["overdue"]), "overdue": sum(1 for x in live if x["overdue"]), "avg_days_to_close": round(sum(days) / len(days), 1) if days else None, "closed": len(closed), "awaiting": sum(1 for x in live if x["status"] == "awaiting_verification")}
    ageing = [{"band": b, "n": sum(1 for x in live if lo <= x["age"] <= hi)} for b, lo, hi in (("0 to 7 days", 0, 7), ("8 to 30 days", 8, 30), ("31 to 60 days", 31, 60), ("Over 60 days", 61, 9999))]
    by_source = {}
    for x in rows:
        by_source[x["source"]] = by_source.get(x["source"], 0) + 1
    st, src, ow, tx = [(q.get(k) or "").strip() for k in ("status", "source", "owner", "q")]
    def keep(x):
        return (not st or (st == "overdue" and x["overdue"]) or x["status"] == st) and (not src or x["source"] == src) and (not ow or same(x["owner"], ow)) and (not tx or tx.lower() in (x["ref"] + " " + x["title"] + " " + x["owner"]).lower())
    out = [x for x in rows if keep(x)]
    out.sort(key=lambda x: (x["status"] not in OPEN, x["effective_due"]))
    return {"actions": out, "tiles": tiles, "ageing": ageing, "by_source": [{"source": k, "n": v} for k, v in sorted(by_source.items(), key=lambda z: -z[1])], "owners": sorted({x["owner"] for x in rows}), "sources": SOURCES,
            "can": {a: a in c.perms.get(AM, set()) for a in core.ACTIONS}, "me": me(c)}


def act_one(db, c, aid):
    a = db.execute("SELECT * FROM actions WHERE id=? AND deleted_at IS NULL", (aid,)).fetchone()
    if not a or not act_visible(c, a, vis_ids(db, c)):
        raise HTTPError(404, "not_found", "Action not found.")
    return a


@router.route("GET", "/api/actions/<int:aid>")
def action_get(req):
    c = need(req, AM, "view")
    a = act_one(req.db, c, req.params["aid"])
    return {"action": act_view(a, today()), "log": [dict(r) for r in req.db.execute("SELECT ts, username, event, detail FROM action_log WHERE action_id=? ORDER BY id", (a["id"],))], "can": {x: x in c.perms.get(AM, set()) for x in core.ACTIONS}, "me": me(c)}


@router.route("POST", "/api/actions")
def action_add(req):
    c = need(req, AM, "create")
    d = req.json()
    if d.get("risk_ref") and not d.get("risk_id"):
        r0 = req.db.execute("SELECT id FROM risks WHERE ref=? AND deleted_at IS NULL", (str(d["risk_ref"]).strip(),)).fetchone()
        if not r0:
            raise HTTPError(404, "not_found", "No risk has the reference %s." % d["risk_ref"])
        d["risk_id"] = r0["id"]
    if d.get("risk_id"):
        sc, sp = riskmod.scope_sql(c)
        if not req.db.execute("SELECT 1 FROM risks WHERE id=? AND deleted_at IS NULL AND " + sc, [int(d["risk_id"])] + sp).fetchone():
            raise HTTPError(404, "not_found", "Choose a risk you can see.")
    d["due_date"] = clean_date(d.get("due_date"), "Due date", past_ok=False)
    r = make_action(req.db, c, d)
    audit(req.db, "action.create", c.user, AM, "Action %s created: %s" % (r["ref"], (d.get("title") or "")[:80]), req.ip)
    return r


@router.route("PUT", "/api/actions/<int:aid>")
def action_edit(req):
    c = need(req, AM, "edit")
    a = act_one(req.db, c, req.params["aid"]); d = req.json()
    if a["status"] in ("closed", "cancelled"):
        raise HTTPError(409, "closed", "A closed or cancelled action cannot be edited. Reopen it first.")
    pr = d.get("priority") or a["priority"]
    if pr not in ("Low", "Medium", "High"):
        raise HTTPError(400, "validation", "Priority must be Low, Medium or High.")
    req.db.execute("UPDATE actions SET title=?, description=?, owner_name=?, priority=?, updated_at=? WHERE id=?", (need_str(d, "title", "Title", 200), need_str(d, "description", "Description", 1500, False) or None, need_str(d, "owner_name", "Owner", 120), pr, now(), a["id"]))
    a_log(req.db, a["id"], c.user, "edited"); audit(req.db, "action.edit", c.user, AM, "Action %s edited" % a["ref"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/actions/<int:aid>/status")
def action_status(req):
    c = need(req, AM, "view")
    a = act_one(req.db, c, req.params["aid"]); d = req.json(); to = d.get("to"); note = need_str(d, "note", "Note", 800, False) or None
    edit, appr = "edit" in c.perms.get(AM, set()), "approve" in c.perms.get(AM, set())
    owner = same(a["owner_name"], me(c)); frm = a["status"]
    if to == "in_progress" and frm in ("open", "awaiting_verification"):
        if not (owner or edit):
            raise HTTPError(403, "forbidden", "Only the action owner or the Risk Office can change this action.")
        req.db.execute("UPDATE actions SET status='in_progress', updated_at=? WHERE id=?", (now(), a["id"]))
    elif to == "awaiting_verification" and frm in ("open", "in_progress"):
        if not (owner or edit):
            raise HTTPError(403, "forbidden", "Only the action owner or the Risk Office can change this action.")
        ev = need_str(d, "evidence", "Evidence", 1500)
        if len(ev) < 10:
            raise HTTPError(400, "validation", "Give the evidence that the action is done (at least 10 characters).")
        req.db.execute("UPDATE actions SET status='awaiting_verification', evidence=?, updated_at=? WHERE id=?", (ev, now(), a["id"]))
    elif to == "closed" and frm == "awaiting_verification":
        if not appr:
            raise HTTPError(403, "forbidden", "Closing an action needs an approver (Head of Risk) to verify the evidence independently.")
        if owner or same(a["created_by_name"], me(c)):
            raise HTTPError(409, "separation", "The person who owns or raised the action cannot verify its closure. Ask another reviewer.")
        req.db.execute("UPDATE actions SET status='closed', closed_at=?, closed_by=?, esc_level=0, updated_at=? WHERE id=?", (now(), me(c), now(), a["id"]))
        if a["control_id"]:  # closing an action prompts a retest of the control
            req.db.execute("UPDATE risk_controls SET next_due=? WHERE id=?", (str(today() + datetime.timedelta(days=14)), a["control_id"]))
        if a["risk_id"]:
            riskmod.history(req.db, a["risk_id"], c.user, "action closed", {"action": a["ref"], "title": a["title"][:80]})
    elif to == "cancelled" and frm in OPEN:
        if not appr or not note or len(note) < 10:
            raise HTTPError(403 if not appr else 400, "forbidden" if not appr else "validation", "Cancelling needs an approver and a reason (at least 10 characters).")
        req.db.execute("UPDATE actions SET status='cancelled', esc_level=0, updated_at=? WHERE id=?", (now(), a["id"]))
    elif to == "open" and frm in ("closed", "cancelled"):
        if not appr or not note or len(note) < 10:
            raise HTTPError(403 if not appr else 400, "forbidden" if not appr else "validation", "Reopening needs an approver and a reason (at least 10 characters).")
        req.db.execute("UPDATE actions SET status='open', closed_at=NULL, closed_by=NULL, updated_at=? WHERE id=?", (now(), a["id"]))
    else:
        raise HTTPError(409, "transition", "An action cannot go from %s to %s." % (frm.replace("_", " "), str(to).replace("_", " ")))
    a_log(req.db, a["id"], c.user, "%s to %s" % (frm.replace("_", " "), to.replace("_", " ")), note or d.get("evidence"))
    audit(req.db, "action.status", c.user, AM, "Action %s: %s to %s" % (a["ref"], frm, to), req.ip)
    return {"status": to}


@router.route("POST", "/api/actions/<int:aid>/revise")
def action_revise(req):
    c = need(req, AM, "view")
    a = act_one(req.db, c, req.params["aid"]); d = req.json()
    if a["status"] not in OPEN:
        raise HTTPError(409, "closed", "Only open actions can have a revised deadline.")
    owner, edit, appr = same(a["owner_name"], me(c)), "edit" in c.perms.get(AM, set()), "approve" in c.perms.get(AM, set())
    if d.get("decision"):  # an approver decides on a request that someone else made
        if not appr or a["revision_status"] != "pending":
            raise HTTPError(403, "forbidden", "There is no pending request for you to decide on.")
        if same(a["revision_by"], me(c)):
            raise HTTPError(409, "separation", "You cannot approve your own request for more time.")
        ok = d["decision"] == "approve"
        req.db.execute("UPDATE actions SET revision_status=?, esc_level=?, updated_at=? WHERE id=?", ("approved" if ok else "rejected", 0 if ok else a["esc_level"], now(), a["id"]))
        a_log(req.db, a["id"], c.user, "revised deadline %s" % ("approved" if ok else "rejected"), a["revised_due"]); audit(req.db, "action.revise", c.user, AM, "Action %s: revised deadline %s" % (a["ref"], "approved" if ok else "rejected"), req.ip)
        return {"revision_status": "approved" if ok else "rejected"}
    if not (owner or edit):
        raise HTTPError(403, "forbidden", "Only the action owner or the Risk Office can ask for more time.")
    new = clean_date(d.get("revised_due"), "Revised due date")
    if new <= a["due_date"]:
        raise HTTPError(400, "validation", "The revised date must be later than the original due date (%s)." % a["due_date"])
    why = need_str(d, "reason", "Reason", 600)
    if len(why) < 10:
        raise HTTPError(400, "validation", "Give the reason for the delay (at least 10 characters).")
    req.db.execute("UPDATE actions SET revised_due=?, revision_reason=?, revision_status='pending', revision_by=?, updated_at=? WHERE id=?", (new, why, me(c), now(), a["id"]))
    a_log(req.db, a["id"], c.user, "asked for more time", "%s: %s" % (new, why)); audit(req.db, "action.revise", c.user, AM, "Action %s: revised deadline %s requested" % (a["ref"], new), req.ip)
    for em in p2.heads_of_risk_emails(req.db):
        outbox(req.db, em, "Revised deadline to approve: %s" % a["ref"], "%s asks to move %s from %s to %s: %s" % (me(c), a["title"][:80], a["due_date"], new, why), "action")
    return {"revision_status": "pending"}


@router.route("POST", "/api/actions/convert-treatments")
def action_convert(req):
    c = need(req, AM, "create")
    sc, sp = riskmod.scope_sql(c); n = 0
    for r in req.db.execute("SELECT * FROM risks WHERE deleted_at IS NULL AND status!='closed' AND treatment IS NOT NULL AND TRIM(treatment)!='' AND action_date IS NOT NULL AND " + sc, sp).fetchall():
        if req.db.execute("SELECT 1 FROM actions WHERE risk_id=? AND source='risk' AND deleted_at IS NULL AND status!='cancelled'", (r["id"],)).fetchone():
            continue
        make_action(req.db, c, {"title": "Treat %s: %s" % (r["ref"], r["title"][:100]), "description": r["treatment"][:1400], "source": "risk", "risk_id": r["id"], "owner_name": r["owner_name"] or "Head of Risk", "priority": "Medium", "due_date": r["action_date"]}); n += 1
    audit(req.db, "action.convert", c.user, AM, "%d risk treatment(s) turned into tracked actions" % n, req.ip)
    return {"created": n}


def escalate(db, actor="system"):
    """Overdue actions: day 1 the owner, day 3 the Head of Risk too, day 7 the MD (Executive and Board) too (BRD rule). Each level is sent once."""
    t = today(); n = 0
    md = [r["email"] for r in db.execute("SELECT DISTINCT u.email FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name='Executive and Board' AND u.deleted_at IS NULL AND u.status='active' AND u.email IS NOT NULL")]
    for a in db.execute("SELECT * FROM actions WHERE deleted_at IS NULL AND status IN ('open','in_progress','awaiting_verification')").fetchall():
        days = (t - d2(eff_due(a))).days
        lvl = 0 if days < 1 else 3 if days >= 7 else 2 if days >= 3 else 1
        if lvl <= a["esc_level"]:
            continue
        to = {p2.person_email(db, a["owner_name"])}
        if lvl >= 2:
            to |= set(p2.heads_of_risk_emails(db))
        if lvl >= 3:
            to |= set(md)
        for em in filter(None, to):
            outbox(db, em, "Action overdue (%d days): %s %s" % (days, a["ref"], a["title"][:70]), "Action %s owned by %s was due %s and is %d day(s) overdue. Escalation level %d.\n\n%s" % (a["ref"], a["owner_name"], eff_due(a), days, lvl, a["title"]), "action")
        db.execute("UPDATE actions SET esc_level=? WHERE id=?", (lvl, a["id"])); a_log(db, a["id"], actor, "escalated to level %d" % lvl, "%d days overdue" % days); n += 1
    if n:
        audit(db, "action.escalate", None, AM, "%d overdue action(s) escalated" % n, username=actor)
    return n


@router.route("POST", "/api/actions/escalate")
def action_escalate(req):
    c = need(req, AM, "approve")
    return {"escalated": escalate(req.db, c.user["username"])}


@router.route("GET", "/api/actions/export.xlsx")
def actions_export(req):
    c = need(req, AM, "export")
    rows = [[("EcoCash action tracker", 3)], [], [(h, 1) for h in ("Action", "Title", "Source", "Owner", "Priority", "Status", "Due", "Revised due (approved)", "Days overdue", "Escalation level", "Created", "Closed")]]
    for x in acts_all(req.db, c):
        rows.append([x["ref"], x["title"], x["source"], x["owner"], x["priority"], x["status"], x["due"], x["revised_due"] if x["revision_status"] == "approved" else None, x["days_overdue"], x["escalation"], x["created_at"][:10], (x["closed_at"] or "")[:10]])
    audit(req.db, "export.actions", c.user, AM, "Action tracker downloaded (%d actions)" % (len(rows) - 3), req.ip)
    return p2.xlsx_response(xlsxbook.write([("Actions", rows, [12, 60, 14, 24, 10, 20, 12, 14, 10, 10, 12, 12])]), "Sentinel_actions_%s.xlsx" % today())


# Sentinel's own measures for the Weekly KPI report
def v_action_overdue(db):
    t = today(); return sum(1 for a in db.execute("SELECT * FROM actions WHERE deleted_at IS NULL AND status IN ('open','in_progress','awaiting_verification')") if d2(eff_due(a)) < t)


def v_ctl_eff(db):
    r = db.execute("SELECT AVG((1.0 - ice) * 100) a FROM risk_controls WHERE ice IS NOT NULL").fetchone()["a"]
    return None if r is None else round(r, 1)


def v_ctl_tested(db):
    n = db.execute("SELECT COUNT(*) n FROM risk_controls").fetchone()["n"]
    return 0 if not n else round(db.execute("SELECT COUNT(*) n FROM risk_controls WHERE last_test>=?", (str(today() - datetime.timedelta(days=365)),)).fetchone()["n"] / n * 100, 1)


p2.INTERNAL.update({"action.overdue": ("Overdue actions", v_action_overdue), "control.effectiveness": ("Average control effectiveness (%)", v_ctl_eff), "control.tested_pct": ("Controls tested in the last 12 months (%)", v_ctl_tested)})


# ------------------------------------------------------------------ backups
BDIR = lambda: os.path.join(config.DATA, "backups")


def backup_create(label="manual"):
    os.makedirs(BDIR(), exist_ok=True)
    name = "sentinel_%s_%s.db" % (datetime.datetime.now().strftime("%Y%m%d_%H%M%S"), label)
    path = os.path.join(BDIR(), name)
    src = sqlite3.connect(config.DB_PATH); dst = sqlite3.connect(path)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    h = hashlib.sha256(open(path, "rb").read()).hexdigest()
    open(path + ".sha256", "w").write(h)
    return {"name": name, "size": os.path.getsize(path), "sha256": h}


def backup_verify(name):
    path = os.path.join(BDIR(), os.path.basename(name))
    if not os.path.isfile(path) or not name.endswith(".db"):
        raise HTTPError(404, "not_found", "Backup not found.")
    stored = open(path + ".sha256").read().strip() if os.path.isfile(path + ".sha256") else None
    h = hashlib.sha256(open(path, "rb").read()).hexdigest()
    con = sqlite3.connect(path)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        risks = con.execute("SELECT COUNT(*) FROM risks").fetchone()[0]
    finally:
        con.close()
    return {"name": name, "hash_ok": stored == h, "integrity": integrity, "ok": stored == h and integrity == "ok", "users": users, "risks": risks}


def backup_list():
    out = []
    if os.path.isdir(BDIR()):
        for f in sorted(os.listdir(BDIR()), reverse=True):
            if f.endswith(".db"):
                p = os.path.join(BDIR(), f); out.append({"name": f, "size": os.path.getsize(p), "when": datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"), "kind": "automatic" if "_auto" in f else "manual"})
    return out


def backup_prune(keep=30):
    for b in backup_list()[keep:]:
        for ext in ("", ".sha256"):
            try:
                os.remove(os.path.join(BDIR(), b["name"] + ext))
            except OSError:
                pass


def nightly(db):
    """Part of the daily job: escalate overdue actions, then take a verified backup (kept: the latest 30)."""
    escalate(db)
    if not any(b["when"][:10] == str(today()) and b["kind"] == "automatic" for b in backup_list()):
        db.commit()
        b = backup_create("auto"); v = backup_verify(b["name"]); backup_prune()
        audit(db, "backup.auto", None, "administration", "Automatic backup %s taken (%s)" % (b["name"], "verified" if v["ok"] else "FAILED verification"), username="system")


@router.route("GET", "/api/admin/backups")
def backups_get(req):
    need(req, "administration", "view")
    return {"backups": backup_list(), "folder": BDIR()}


@router.route("POST", "/api/admin/backups")
def backups_make(req):
    c = need(req, "administration", "edit")
    req.db.commit()
    b = backup_create("manual"); v = backup_verify(b["name"]); backup_prune()
    audit(req.db, "backup.create", c.user, "administration", "Backup %s taken (%s)" % (b["name"], "verified" if v["ok"] else "FAILED verification"), req.ip)
    return dict(b, verified=v["ok"])


@router.route("POST", "/api/admin/backups/verify")
def backups_verify(req):
    c = need(req, "administration", "view")
    v = backup_verify(need_str(req.json(), "name", "Backup", 120))
    audit(req.db, "backup.verify", c.user, "administration", "Backup %s checked: %s" % (v["name"], "good" if v["ok"] else "PROBLEM"), req.ip)
    return v


# ------------------------------------------------------------------ permanent delete needs a second administrator
def purge_entity(db, r):
    tables = {"user": "users", "risk": "risks", "task": "tasks", "incident": "incidents", "workbook": "wb_store", "ai_doc": "ai_docs"}
    if r["entity_type"] in tables:
        db.execute("DELETE FROM %s WHERE id=? AND deleted_at IS NOT NULL" % tables[r["entity_type"]], (r["entity_id"],))
    db.execute("DELETE FROM recycle WHERE id=?", (r["id"],))


@router.route("POST", "/api/admin/recycle/<int:rid>/purge-request")
def purge_request(req):
    c = need(req, "administration", "edit")
    r = req.db.execute("SELECT * FROM recycle WHERE id=? AND restored_at IS NULL", (req.params["rid"],)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Item not found in the Recycle Bin.")
    why = need_str(req.json(), "reason", "Reason", 400)
    if len(why) < 10:
        raise HTTPError(400, "validation", "Give the reason for deleting it for good (at least 10 characters).")
    if req.db.execute("SELECT 1 FROM purge_requests WHERE recycle_id=? AND status='pending'", (r["id"],)).fetchone():
        raise HTTPError(409, "pending", "A request to delete this item permanently is already waiting for a second administrator.")
    pid = req.db.execute("INSERT INTO purge_requests(recycle_id,title,entity_type,requested_by,requested_name,reason,requested_at) VALUES(?,?,?,?,?,?,?)", (r["id"], r["title"], r["entity_type"], c.user["id"], me(c), why, now())).lastrowid
    audit(req.db, "recycle.purge_requested", c.user, "administration", "Permanent deletion of %s requested: %s" % (r["title"], why[:100]), req.ip)
    for a in req.db.execute("SELECT DISTINCT u.email FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles ro ON ro.id=ur.role_id WHERE ro.name='System Administrator' AND u.status='active' AND u.id!=? AND u.email IS NOT NULL", (c.user["id"],)):
        outbox(req.db, a["email"], "Sentinel: a second administrator is needed to delete %s" % (r["title"] or "an item"), "%s asks to delete %s permanently: %s. Open Administration > Recycle Bin to approve or reject." % (me(c), r["title"], why), "security")
    return {"id": pid}


@router.route("GET", "/api/admin/purge-requests")
def purge_list(req):
    c = need(req, "administration", "view")
    return {"requests": [dict(r, mine=r["requested_by"] == c.user["id"]) for r in req.db.execute("SELECT * FROM purge_requests WHERE status='pending' ORDER BY id DESC")]}


@router.route("POST", "/api/admin/purge-requests/<int:pid>/decide")
def purge_decide(req):
    c = need(req, "administration", "edit")
    p = req.db.execute("SELECT * FROM purge_requests WHERE id=? AND status='pending'", (req.params["pid"],)).fetchone()
    if not p:
        raise HTTPError(404, "not_found", "No pending request.")
    if p["requested_by"] == c.user["id"]:
        raise HTTPError(409, "separation", "A different administrator must approve a permanent deletion. You cannot approve your own request.")
    d = req.json(); ok = d.get("decision") == "approve"
    if d.get("decision") not in ("approve", "reject"):
        raise HTTPError(400, "validation", "Approve or reject.")
    if ok:
        r = req.db.execute("SELECT * FROM recycle WHERE id=?", (p["recycle_id"],)).fetchone()
        if r:
            purge_entity(req.db, r)
    req.db.execute("UPDATE purge_requests SET status=?, decided_by=?, decided_at=?, note=? WHERE id=?", ("approved" if ok else "rejected", me(c), now(), need_str(d, "note", "Note", 300, False) or None, p["id"]))
    audit(req.db, "recycle.purged_approved" if ok else "recycle.purge_rejected", c.user, "administration", "Permanent deletion of %s %s (requested by %s)" % (p["title"], "approved and carried out" if ok else "rejected", p["requested_name"]), req.ip)
    return {"status": "approved" if ok else "rejected"}
