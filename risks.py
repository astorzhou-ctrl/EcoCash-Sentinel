"""Risk Register, Heat Map & Portfolio and Command Center API (BRD phase P1). Ratings come from the ranked matrix lookup."""
import csv
import io
import json
import re

from . import core, db as dbm, matrix as mx
from .api import router, need, need_str, DATE_RE
from .core import audit, now
from .db import parse
from .web import HTTPError, Response, jr

CATEGORIES = ["Fraud", "Technology", "Cyber", "Compliance", "Regulatory", "Financial", "Operational", "Third party", "People", "Reputation", "Strategic", "Model / AI"]
STATUSES = ["draft", "submitted", "reviewed", "approved", "closed"]
DOMAINS = ["People", "Process", "Systems", "Technology", "Tools"]
CTYPES = ["preventive", "detective", "corrective"]
RESULTS = ["effective", "partial", "failed", "not tested"]
TRACKED = ["title", "description", "category", "function", "objective", "owner_name", "root_cause", "implication", "treatment", "action_date", "review_date", "emv_i", "inh_l", "inh_c", "res_l", "res_c", "tgt_l", "tgt_c", "subcategory", "delegate_name"]


# ------------------------------------------------------------------ helpers
def scope_sql(c):
    sc, uid = c.user["data_scope"], c.user["id"]
    if sc == "all":
        return "1=1", []
    if sc == "own":
        return "(owner_id=? OR created_by=?)", [uid, uid]
    return "(function=? COLLATE NOCASE OR owner_id=? OR created_by=?)", [c.user["department"] or "", uid, uid]


def control_stats(db, ids=None):
    out = {}
    for r in db.execute("SELECT risk_id, COUNT(*) n, AVG(ice) a, SUM(CASE WHEN ice IS NULL THEN 1 ELSE 0 END) m FROM risk_controls GROUP BY risk_id"):
        out[r["risk_id"]] = (r["n"], r["a"], r["m"])
    return out


def assurance(r, st):
    n, avg, missing = st if st else (0, None, 0)
    if not n or avg is None:
        return {"controls": n, "avg_ice": None, "loa": None, "lor": None, "emv_r": None}
    lor = round(avg, 4)
    return {"controls": n, "avg_ice": round(avg, 2), "loa": round(1 - lor, 4), "lor": lor, "emv_r": round(r["emv_i"] * lor, 2) if r["emv_i"] else None}


ICE_CLASS = {1: ("Strong", "Accept"), 2: ("Strong", "Accept"), 3: ("Reasonably strong", "Accept"), 4: ("Good", "Mitigate"), 5: ("Adequate", "Mitigate"), 6: ("Marginally adequate", "Mitigate"),
             7: ("Needs improvement", "Immediate action"), 8: ("Weak", "Immediate action"), 9: ("Very weak", "Immediate action"), 10: ("Non-existent", "Immediate action")}


def ice_class(ice):
    """GRC Policy 2.3.1: effectiveness scale 1-10 (ICE 0.1 to 1.0) with its description and action class."""
    if ice is None:
        return None
    s = max(1, min(10, int(round(ice * 10))))
    return {"score": s, "label": ICE_CLASS[s][0], "action": ICE_CLASS[s][1]}


def board_ok(db, risk_id):
    """True when an approved Board decision for the risk has not expired."""
    return db.execute("SELECT 1 FROM board_decisions WHERE risk_id=? AND status='approved' AND (expiry_date IS NULL OR expiry_date>=?)", (risk_id, str(dbm.today()))).fetchone() is not None


def missing_fields(r):
    m = []
    for k, label in (("owner_name", "owner"), ("root_cause", "root cause"), ("treatment", "treatment"), ("action_date", "action date")):
        if not (r[k] or "").strip():
            m.append(label)
    return m


def risk_dict(r, st=None, full=False):
    inh, res = mx.rating(r["inh_l"], r["inh_c"]), mx.rating(r["res_l"], r["res_c"])
    d = {"id": r["id"], "ref": r["ref"], "title": r["title"], "category": r["category"], "function": r["function"], "owner_name": r["owner_name"], "owner_id": r["owner_id"], "status": r["status"],
         "inherent": inh, "residual": res, "target": mx.rating(r["tgt_l"], r["tgt_c"]) if r["tgt_l"] else None, "emv_i": r["emv_i"], "needs_board": bool(r["needs_board"]), "is_sample": bool(r["is_sample"]),
         "outside_appetite": mx.outside_appetite(r["category"], res["rank"]), "appetite_band": mx.band(res["rank"]), "missing": missing_fields(r), "action_date": r["action_date"], "review_date": r["review_date"], "updated_at": r["updated_at"] or r["created_at"]}
    d.update(assurance(r, st))
    d.update({"system": r["system"], "source_ref": r["source_ref"], "strategic_objective": r["strategic_objective"], "needs_assessment": bool(r["needs_assessment"]), "subcategory": r["subcategory"], "delegate_name": r["delegate_name"], "emv_a": r["emv_a"]})
    if full:
        for k in ("description", "objective", "root_cause", "implication", "treatment", "created_at", "created_by", "deleted_at"):
            d[k] = r[k]
    return d


def load_visible(req, c, include_deleted=False, assessed=False):
    where, args = scope_sql(c)
    rows = req.db.execute("SELECT * FROM risks WHERE deleted_at IS %s AND %s" % ("NOT NULL" if include_deleted else "NULL", where), args).fetchall()
    st = control_stats(req.db)
    out = [risk_dict(r, st.get(r["id"])) for r in rows]
    return [x for x in out if not x["needs_assessment"]] if assessed else out


def split_visible(req, c):
    """Assessed risks (used for ratings, maps and trends) and the number still waiting for a real assessment."""
    allr = load_visible(req, c)
    a = [x for x in allr if not x["needs_assessment"]]
    return a, len(allr) - len(a)


def get_risk(req, c, rid, action="view"):
    r = req.db.execute("SELECT * FROM risks WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Risk not found")
    where, args = scope_sql(c)
    if not req.db.execute("SELECT 1 FROM risks WHERE id=? AND %s" % where, [rid] + args).fetchone():
        raise HTTPError(403, "forbidden", "This risk is outside your data scope.")
    return r


def history(db, rid, user, action, changes=None):
    db.execute("INSERT INTO risk_history(risk_id,ts,user_id,username,action,changes) VALUES(?,?,?,?,?,?)", (rid, now(), user["id"], user["username"], action, json.dumps(changes or {}, ensure_ascii=False)))


def num(d, key, label, lo, hi, required=True):
    v = d.get(key)
    if v in (None, ""):
        if required:
            raise HTTPError(400, "validation", "%s is required." % label)
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise HTTPError(400, "validation", "%s must be a whole number." % label)
    if not lo <= v <= hi:
        raise HTTPError(400, "validation", "%s must be between %d and %d." % (label, lo, hi))
    return v


def clean_fields(db, d):
    f = {"title": need_str(d, "title", "Title", 200), "description": need_str(d, "description", "Description", 2000, False), "function": need_str(d, "function", "Function", 120, False),
         "objective": need_str(d, "objective", "Objective", 200, False), "owner_name": need_str(d, "owner_name", "Owner", 120, False), "root_cause": need_str(d, "root_cause", "Root cause", 1000, False),
         "implication": need_str(d, "implication", "Implication", 1000, False), "treatment": need_str(d, "treatment", "Treatment", 1000, False),
         "subcategory": need_str(d, "subcategory", "Subcategory", 120, False), "delegate_name": need_str(d, "delegate_name", "Delegate", 120, False)}
    cat = need_str(d, "category", "Category", 60)
    if cat not in CATEGORIES:
        raise HTTPError(400, "validation", "Choose a category from the list.")
    f["category"] = cat
    for k in ("action_date", "review_date"):
        v = (d.get(k) or "").strip() or None
        if v and not DATE_RE.match(v):
            raise HTTPError(400, "validation", "%s must be a date (YYYY-MM-DD)." % k.replace("_", " ").capitalize())
        f[k] = v
    emv = d.get("emv_i")
    if emv in (None, ""):
        f["emv_i"] = None
    else:
        try:
            f["emv_i"] = float(emv)
            assert f["emv_i"] >= 0
        except (TypeError, ValueError, AssertionError):
            raise HTTPError(400, "validation", "Estimated value (EMV-i) must be a number, zero or more.")
    f["inh_l"], f["inh_c"] = num(d, "inh_l", "Inherent likelihood", 1, 5), num(d, "inh_c", "Inherent consequence", 1, 5)
    f["res_l"] = num(d, "res_l", "Residual likelihood", 1, 5, False) or f["inh_l"]
    f["res_c"] = num(d, "res_c", "Residual consequence", 1, 5, False) or f["inh_c"]
    if f["res_l"] > f["inh_l"] or f["res_c"] > f["inh_c"]:
        raise HTTPError(400, "validation", "Residual likelihood and consequence cannot be higher than inherent.")
    f["tgt_l"], f["tgt_c"] = num(d, "tgt_l", "Target likelihood", 1, 5, False), num(d, "tgt_c", "Target consequence", 1, 5, False)
    if bool(f["tgt_l"]) != bool(f["tgt_c"]):
        raise HTTPError(400, "validation", "Give both target likelihood and target consequence, or neither.")
    if f["tgt_l"] and (f["tgt_l"] > f["res_l"] or f["tgt_c"] > f["res_c"]):
        raise HTTPError(400, "validation", "The target cannot be higher than the residual rating.")
    return f


def resolve_owner(db, name):
    if not name:
        return None
    u = db.execute("SELECT id FROM users WHERE full_name=? COLLATE NOCASE AND deleted_at IS NULL AND status IN ('active','invited')", (name,)).fetchone()
    return u["id"] if u else None


# ------------------------------------------------------------------ reference data
@router.route("GET", "/api/matrix")
def api_matrix(req):
    need(req)
    d = mx.describe()
    d.update({"categories": CATEGORIES, "statuses": STATUSES, "domains": DOMAINS, "ctypes": CTYPES, "results": RESULTS})
    return d


@router.route("GET", "/api/risks/owners")
def risk_owners(req):
    need(req, "risk_register", "view")
    return {"owners": [dict(id=u["id"], name=u["full_name"], department=u["department"]) for u in req.db.execute("SELECT id,full_name,department FROM users WHERE deleted_at IS NULL AND status IN ('active','invited') ORDER BY full_name COLLATE NOCASE")]}


# ------------------------------------------------------------------ register
@router.route("GET", "/api/risks")
def risks_list(req):
    c = need(req, "risk_register", "view")
    rows = load_visible(req, c)
    q = req.query
    t = (q.get("q") or "").strip().lower()
    if t:
        rows = [r for r in rows if t in (r["ref"] + " " + r["title"] + " " + (r["owner_name"] or "") + " " + (r["category"] or "")).lower()]
    if q.get("category"):
        rows = [r for r in rows if r["category"] == q["category"]]
    if q.get("level"):
        rows = [r for r in rows if r["residual"]["level"] == q["level"]]
    if q.get("status"):
        rows = [r for r in rows if r["status"] == q["status"]]
    if q.get("outside") == "1":
        rows = [r for r in rows if r["outside_appetite"] and not r["needs_assessment"]]
    if q.get("assessment") == "needs":
        rows = [r for r in rows if r["needs_assessment"]]
    if q.get("cell"):
        try:
            l, cc = [int(x) for x in q["cell"].split(",")]
            basis = q.get("basis") if q.get("basis") in ("inherent", "residual", "target") else "residual"
            rows = [r for r in rows if r[basis] and (r[basis]["l"], r[basis]["c"]) == (l, cc)]
        except ValueError:
            pass
    rows.sort(key=lambda r: (r["needs_assessment"], -r["residual"]["rank"], -r["inherent"]["rank"], r["ref"]))
    return {"risks": rows, "total": len(rows), "needs_assessment": sum(1 for r in rows if r["needs_assessment"])}


@router.route("POST", "/api/risks")
def risks_create(req):
    c = need(req, "risk_register", "create")
    f = clean_fields(req.db, req.json())
    owner_id = resolve_owner(req.db, f["owner_name"])
    cols = list(f) + ["owner_id", "status", "created_at", "created_by", "updated_at", "updated_by"]
    vals = list(f.values()) + [owner_id, "draft", now(), c.user["id"], now(), c.user["id"]]
    rid = req.db.execute("INSERT INTO risks(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), vals).lastrowid
    ref = "R-%03d" % rid
    req.db.execute("UPDATE risks SET ref=? WHERE id=?", (ref, rid))
    history(req.db, rid, c.user, "created", {"title": [None, f["title"]]})
    audit(req.db, "risk.created", c.user, "risk_register", "%s %s (inherent %s, residual %s)" % (ref, f["title"], mx.rating(f["inh_l"], f["inh_c"])["rank"], mx.rating(f["res_l"], f["res_c"])["rank"]), req.ip)
    return {"risk": risk_dict(req.db.execute("SELECT * FROM risks WHERE id=?", (rid,)).fetchone(), None, True)}


@router.route("GET", "/api/risks/<int:rid>")
def risks_get(req):
    c = need(req, "risk_register", "view")
    r = get_risk(req, c, int(req.params["rid"]))
    st = control_stats(req.db).get(r["id"])
    d = risk_dict(r, st, True)
    d["controls"] = [dict(x, policy_class=ice_class(x["ice"])) for x in req.db.execute("SELECT * FROM risk_controls WHERE risk_id=? ORDER BY id", (r["id"],))]
    d["board_decision"] = ([dict(x) for x in req.db.execute("SELECT status,reference,expiry_date,decided_at FROM board_decisions WHERE risk_id=? ORDER BY id DESC LIMIT 1", (r["id"],))] or [None])[0]
    d["history"] = [dict(x, changes=json.loads(x["changes"] or "{}")) for x in req.db.execute("SELECT * FROM risk_history WHERE risk_id=? ORDER BY id DESC LIMIT 60", (r["id"],))]
    d["suggestion"] = suggest(r, d["controls"])
    d["can"] = {a: a in c.perms.get("risk_register", set()) for a in core.ACTIONS}
    return d


def suggest(r, controls):
    """Suggest residual likelihood / consequence from control evidence (BRD 3.3): up to two steps each, owner confirms."""
    def strength(types):
        e = [1 - x["ice"] for x in controls if x["ctype"] in types and x["ice"] is not None and x["result"] != "failed"]
        return sum(e) / len(e) if e else 0.0
    ls, cs = int(round(2 * strength(("preventive", "detective")))), int(round(2 * strength(("corrective",))))
    l, cc = max(1, r["inh_l"] - ls), max(1, r["inh_c"] - cs)
    return {"likelihood_steps": ls, "consequence_steps": cs, "l": l, "c": cc, "rating": mx.rating(l, cc), "basis": "%d control(s) with an effectiveness score" % len([x for x in controls if x["ice"] is not None])}


@router.route("PUT", "/api/risks/<int:rid>")
def risks_update(req):
    c = need(req, "risk_register", "edit")
    r = get_risk(req, c, int(req.params["rid"]))
    d = req.json()
    if r["status"] in ("submitted", "reviewed", "approved", "closed") and "approve" not in c.perms.get("risk_register", set()):
        raise HTTPError(409, "locked", "This risk is %s. Return it to draft before editing." % r["status"])
    f = clean_fields(req.db, d)
    old_res, new_res = mx.rating(r["res_l"], r["res_c"]), mx.rating(f["res_l"], f["res_c"])
    reason = need_str(d, "reason", "Reason", 500, False)
    same = (f["inh_l"], f["inh_c"], f["res_l"], f["res_c"]) == (r["inh_l"], r["inh_c"], r["res_l"], r["res_c"])
    if r["needs_assessment"] and same and len(reason) < 5:
        raise HTTPError(400, "placeholder", "This risk still has the imported placeholder rating (likelihood %d, consequence %d). Choose the real rating, or if it truly is that rating, write a reason confirming it." % (r["inh_l"], r["inh_c"]))
    if not r["needs_assessment"] and abs(mx.level_index(new_res["rank"]) - mx.level_index(old_res["rank"])) >= 2 and len(reason) < 5:
        raise HTTPError(400, "reason_required", "The residual rating moves two or more levels (%s to %s). Give a written reason." % (old_res["level"], new_res["level"]))
    changes = {k: [r[k], f[k]] for k in TRACKED if (r[k] if r[k] != "" else None) != (f[k] if f[k] != "" else None)}
    if reason:
        changes["reason"] = [None, reason]
    if r["needs_assessment"]:
        changes["assessment"] = ["placeholder rating", "assessed by %s" % c.user["username"]]
    sets = ", ".join("%s=?" % k for k in f)
    req.db.execute("UPDATE risks SET %s, owner_id=?, needs_assessment=0, updated_at=?, updated_by=? WHERE id=?" % sets, list(f.values()) + [resolve_owner(req.db, f["owner_name"]), now(), c.user["id"], r["id"]])
    if changes:
        history(req.db, r["id"], c.user, "updated", changes)
        audit(req.db, "risk.updated", c.user, "risk_register", "%s changed: %s" % (r["ref"], ", ".join(k for k in changes if k != "reason")), req.ip)
    return {"risk": risk_dict(req.db.execute("SELECT * FROM risks WHERE id=?", (r["id"],)).fetchone(), control_stats(req.db).get(r["id"]), True)}


@router.route("DELETE", "/api/risks/<int:rid>")
def risks_delete(req):
    c = need(req, "risk_register", "delete")
    r = get_risk(req, c, int(req.params["rid"]))
    reason = need_str(req.json(), "reason", "A reason", 300)
    if len(reason) < 3:
        raise HTTPError(400, "validation", "Give a reason of at least 3 characters.")
    if r["status"] in ("submitted", "reviewed"):
        raise HTTPError(409, "pending", "This risk is waiting for review or approval. Return it to draft or finish the approval first.")
    pol = dbm.get_policy(req.db)
    req.db.execute("UPDATE risks SET deleted_at=?, deleted_by=?, delete_reason=? WHERE id=?", (now(), c.user["id"], reason, r["id"]))
    req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at) VALUES('risk',?,?,?,?,?,?,?,?)",
                   (r["id"], "%s %s" % (r["ref"], r["title"]), "Risk Register", c.user["id"], c.user["username"], now(), reason, dbm.plus(days=pol["recycle_days"])))
    history(req.db, r["id"], c.user, "deleted", {"reason": [None, reason]})
    audit(req.db, "risk.deleted", c.user, "risk_register", "Deleted %s: %s" % (r["ref"], reason), req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ workflow
TRANSITIONS = {"draft": ["submitted"], "submitted": ["reviewed", "draft"], "reviewed": ["approved", "draft"], "approved": ["closed", "draft"], "closed": ["draft"]}


@router.route("POST", "/api/risks/<int:rid>/status")
def risks_status(req):
    c = need(req, "risk_register", "view")
    r = get_risk(req, c, int(req.params["rid"]))
    d = req.json()
    to, comment = str(d.get("to", "")), need_str(d, "comment", "Comment", 500, False)
    perms = c.perms.get("risk_register", set())
    if to not in TRANSITIONS.get(r["status"], []):
        raise HTTPError(409, "bad_transition", "A %s risk cannot move to %s." % (r["status"], to))
    if to == "submitted":
        if not ({"create", "edit"} & perms):
            raise HTTPError(403, "forbidden", "You cannot submit risks.")
        if missing_fields(r):
            raise HTTPError(400, "incomplete", "Complete these before submitting: " + ", ".join(missing_fields(r)) + ".")
    elif to == "reviewed":
        if "edit" not in perms:
            raise HTTPError(403, "forbidden", "You cannot review risks.")
        if c.user["id"] in (r["owner_id"], r["created_by"]):
            raise HTTPError(409, "same_person", "You cannot review a risk you own or created (separation of duties).")
    elif to in ("approved", "closed"):
        if "approve" not in perms:
            raise HTTPError(403, "forbidden", "You do not have permission to approve.")
        if to == "approved" and c.user["id"] in (r["owner_id"], r["created_by"]):
            raise HTTPError(409, "same_person", "You cannot approve a risk you own or created (separation of duties).")
    elif to == "draft":
        if not ({"edit", "approve"} & perms):
            raise HTTPError(403, "forbidden", "You cannot return risks to draft.")
        if len(comment) < 3:
            raise HTTPError(400, "validation", "Say why you are returning it to draft.")
    needs_board = r["needs_board"]
    if to == "approved":
        res = mx.rating(r["res_l"], r["res_c"])
        if mx.outside_appetite(r["category"], res["rank"]):
            if not board_ok(req.db, r["id"]) and len(comment) < 10:
                raise HTTPError(400, "board_ref_required", "This risk is above appetite (rank %d; appetite limit %d). GRC Policy 2.4: it can only be retained with Board approval. Record the decision in Board Hub, or give the Board reference in the comment (at least 10 characters)." % (res["rank"], mx.THRESH["appetite"]))
            needs_board = 1
    if to == "draft":
        needs_board = 0
    req.db.execute("UPDATE risks SET status=?, needs_board=?, updated_at=?, updated_by=? WHERE id=?", (to, needs_board, now(), c.user["id"], r["id"]))
    history(req.db, r["id"], c.user, "status", {"status": [r["status"], to], "comment": [None, comment]})
    audit(req.db, "risk.status", c.user, "risk_register", "%s %s to %s%s" % (r["ref"], r["status"], to, (": " + comment) if comment else ""), req.ip)
    return {"status": to, "needs_board": bool(needs_board)}


# ------------------------------------------------------------------ controls linked to a risk
def control_fields(d):
    st = need_str(d, "statement", "Control statement", 400)
    dom = (d.get("domain") or "").strip() or None
    ct = (d.get("ctype") or "").strip() or None
    res = (d.get("result") or "").strip() or None
    if dom and dom not in DOMAINS or ct and ct not in CTYPES or res and res not in RESULTS:
        raise HTTPError(400, "validation", "Choose domain, type and result from the lists.")
    ice = d.get("ice")
    if ice in (None, ""):
        ice = None
    else:
        try:
            ice = round(float(ice), 2)
            assert 0.1 <= ice <= 1.0
        except (TypeError, ValueError, AssertionError):
            raise HTTPError(400, "validation", "Control effectiveness (ICE) must be between 0.1 (strong) and 1.0 (none).")
    lt = (d.get("last_test") or "").strip() or None
    if lt and not DATE_RE.match(lt):
        raise HTTPError(400, "validation", "Last test must be a date (YYYY-MM-DD).")
    return (need_str(d, "ref", "Reference", 40, False), st, dom, ct, ice, need_str(d, "owner", "Owner", 120, False), lt, res)


@router.route("POST", "/api/risks/<int:rid>/controls")
def control_add(req):
    c = need(req, "risk_register", "edit")
    r = get_risk(req, c, int(req.params["rid"]))
    v = control_fields(req.json())
    cid = req.db.execute("INSERT INTO risk_controls(risk_id,ref,statement,domain,ctype,ice,owner,last_test,result) VALUES(?,?,?,?,?,?,?,?,?)", (r["id"],) + v).lastrowid
    history(req.db, r["id"], c.user, "control added", {"control": [None, v[1]]})
    audit(req.db, "risk.control_added", c.user, "risk_register", "%s: control added (%s)" % (r["ref"], v[1][:60]), req.ip)
    return {"id": cid}


@router.route("PUT", "/api/risks/<int:rid>/controls/<int:cid>")
def control_edit(req):
    c = need(req, "risk_register", "edit")
    r = get_risk(req, c, int(req.params["rid"]))
    v = control_fields(req.json())
    n = req.db.execute("UPDATE risk_controls SET ref=?,statement=?,domain=?,ctype=?,ice=?,owner=?,last_test=?,result=? WHERE id=? AND risk_id=?", v + (int(req.params["cid"]), r["id"])).rowcount
    if not n:
        raise HTTPError(404, "not_found", "Control not found")
    history(req.db, r["id"], c.user, "control changed", {"control": [None, v[1]]})
    audit(req.db, "risk.control_changed", c.user, "risk_register", "%s: control changed (%s)" % (r["ref"], v[1][:60]), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/risks/<int:rid>/controls/<int:cid>")
def control_delete(req):
    c = need(req, "risk_register", "edit")
    r = get_risk(req, c, int(req.params["rid"]))
    row = req.db.execute("SELECT statement FROM risk_controls WHERE id=? AND risk_id=?", (int(req.params["cid"]), r["id"])).fetchone()
    if not row:
        raise HTTPError(404, "not_found", "Control not found")
    req.db.execute("DELETE FROM risk_controls WHERE id=?", (int(req.params["cid"]),))
    history(req.db, r["id"], c.user, "control removed", {"control": [row["statement"], None]})
    audit(req.db, "risk.control_removed", c.user, "risk_register", "%s: control removed" % r["ref"], req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ export, snapshots, sample data
@router.route("GET", "/api/risks/export.csv")
def risks_export(req):
    c = need(req, "risk_register", "export")
    where, args = scope_sql(c)
    rows = req.db.execute("SELECT * FROM risks WHERE deleted_at IS NULL AND %s ORDER BY id" % where, args).fetchall()
    st = control_stats(req.db)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Sentinel risk register export", "by " + c.user["username"], now(), "Company confidential"])
    w.writerow(["Ref", "Title", "Category", "Function", "Objective", "Owner", "Status", "Inherent L", "Inherent C", "Inherent rank", "Inherent level", "Residual L", "Residual C", "Residual rank", "Residual level",
                "Outside appetite", "Root cause", "Implication", "Treatment", "Action date", "Review date", "EMV-i", "Controls", "Average ICE", "LoA", "EMV-r", "Subcategory", "Delegate", "Management system", "Workbook reference", "Strategic objective", "Needs assessment", "EMV-a", "Appetite band"])
    for r in rows:
        d = risk_dict(r, st.get(r["id"]))
        w.writerow([r["ref"], r["title"], r["category"], r["function"], r["objective"], r["owner_name"], r["status"], r["inh_l"], r["inh_c"], d["inherent"]["rank"], d["inherent"]["level"], r["res_l"], r["res_c"], d["residual"]["rank"], d["residual"]["level"],
                    "yes" if d["outside_appetite"] and not r["needs_assessment"] else "no", r["root_cause"], r["implication"], r["treatment"], r["action_date"], r["review_date"], r["emv_i"], d["controls"], d["avg_ice"], d["loa"], d["emv_r"],
                    r["subcategory"], r["delegate_name"], r["system"], r["source_ref"], r["strategic_objective"], "yes" if r["needs_assessment"] else "no", r["emv_a"], d["appetite_band"]])
    audit(req.db, "export.risks", c.user, "risk_register", "Exported %d risks to CSV" % len(rows), req.ip)
    body = ("\ufeff" + out.getvalue()).encode("utf-8")
    return Response(body, 200, "text/csv; charset=utf-8", [("Content-Disposition", 'attachment; filename="sentinel_risk_register_%s.csv"' % now()[:10])])


def snapshot_rows(rows):
    return [{"id": r["id"], "ref": r["ref"], "title": r["title"], "category": r["category"], "inh": r["inherent"]["rank"], "res": r["residual"]["rank"], "outside": r["outside_appetite"]} for r in rows]


@router.route("POST", "/api/risks/snapshot")
def snapshot_take(req):
    c = need(req, "risk_register", "approve")
    if c.user["data_scope"] != "all":
        raise HTTPError(403, "forbidden", "Snapshots cover the whole register, so they need data scope 'all'.")
    rows = load_visible(req, c, assessed=True)
    label = need_str(req.json(), "label", "Label", 60, False) or "Snapshot " + now()[:10]
    req.db.execute("INSERT INTO risk_snapshots(snap_date,label,taken_by,data) VALUES(?,?,?,?)", (now(), label, c.user["username"], json.dumps(snapshot_rows(rows))))
    audit(req.db, "risk.snapshot", c.user, "risk_register", "Snapshot taken: %s (%d risks)" % (label, len(rows)), req.ip)
    return {"ok": True, "count": len(rows)}


SAMPLE = [("SIM-swap and account-takeover fraud", "Fraud", "Head of Compliance and ML/CTF", 5, 4, 3, 4, 2400000), ("Mobile-money platform outage over 4 hours", "Technology", "CTO", 3, 5, 2, 5, 3100000), ("Agent float and liquidity shortfall", "Financial", "CFO", 4, 3, 3, 3, 900000),
          ("Personal-data breach (24-hour duty)", "Compliance", "DPO", 3, 5, 2, 4, 1800000), ("AML / CFT control failure", "Regulatory", "MLRO", 3, 5, 2, 5, 2200000), ("Ransomware on core systems", "Cyber", "CISO", 3, 5, 2, 5, 2700000),
          ("Cloud and third-party provider failure", "Third party", "CTO", 3, 4, 2, 4, 1200000), ("Foreign-exchange and liquidity pressure", "Financial", "CFO", 4, 4, 3, 4, 1500000), ("Licence-condition breach", "Regulatory", "Head of Compliance", 2, 5, 1, 5, 2000000),
          ("Insider fraud and privileged misuse", "Fraud", "Head of Compliance and ML/CTF", 3, 4, 2, 4, 800000), ("Key-person and skills attrition", "People", "CHRO", 4, 2, 3, 2, 300000), ("Bias or drift in analytics models", "Model / AI", "Head of Data", 2, 3, 1, 3, 250000),
          ("Power loss at network hubs", "Operational", "COO", 3, 3, 2, 3, 400000), ("Brand damage from misinformation", "Reputation", "Head of Comms", 3, 2, 2, 2, 200000)]
SAMPLE_CONTROLS = [("Cooling-off period on SIM change", "Process", "preventive", 0.3, "effective"), ("Real-time SIM-change alerts", "Systems", "detective", 0.4, "partial"), ("Recovery and reimbursement process", "Process", "corrective", 0.5, "effective")]


@router.route("POST", "/api/risks/sample")
def sample_load(req):
    c = need(req, "risk_register", "create")
    if req.db.execute("SELECT 1 FROM risks WHERE is_sample=1 AND deleted_at IS NULL").fetchone():
        raise HTTPError(409, "exists", "Sample risks are already loaded.")
    for t, cat, owner, il, ic, rl, rc, emv in SAMPLE:
        rid = req.db.execute("""INSERT INTO risks(title,category,function,owner_name,owner_id,root_cause,treatment,action_date,inh_l,inh_c,res_l,res_c,emv_i,status,is_sample,created_at,created_by,updated_at,updated_by,description)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'draft',1,?,?,?,?,?)""", (t, cat, "Sample", owner, None, "Sample root cause", "Sample treatment plan", "2027-03-31", il, ic, rl, rc, emv, now(), c.user["id"], now(), c.user["id"], "ILLUSTRATIVE SAMPLE: delete when you load real risks.")).lastrowid
        req.db.execute("UPDATE risks SET ref=? WHERE id=?", ("R-%03d" % rid, rid))
        if cat in ("Fraud", "Cyber", "Technology"):
            for i, (st, dom, ct, ice, res) in enumerate(SAMPLE_CONTROLS):
                req.db.execute("INSERT INTO risk_controls(risk_id,ref,statement,domain,ctype,ice,owner,result) VALUES(?,?,?,?,?,?,?,?)", (rid, "SMP-%02d" % (i + 1), st, dom, ct, ice, owner, res))
        history(req.db, rid, c.user, "created", {"title": [None, t]})
    audit(req.db, "risk.sample_loaded", c.user, "risk_register", "Loaded %d sample risks" % len(SAMPLE), req.ip)
    return {"loaded": len(SAMPLE)}


@router.route("DELETE", "/api/risks/sample")
def sample_remove(req):
    c = need(req, "risk_register", "delete")
    n = req.db.execute("DELETE FROM risks WHERE is_sample=1").rowcount
    audit(req.db, "risk.sample_removed", c.user, "risk_register", "Removed %d sample risks" % n, req.ip)
    return {"removed": n}


# ------------------------------------------------------------------ heat map, portfolio, command center
def level_counts(rows, basis):
    out = {n: 0 for n in mx.LEVELS}
    for r in rows:
        out[r[basis]["level"]] += 1
    return out


@router.route("GET", "/api/heatmap")
def heatmap(req):
    c = need(req, "heat_map_portfolio", "view")
    rows, unassessed = split_visible(req, c)
    cat = req.query.get("category")
    if cat:
        rows = [r for r in rows if r["category"] == cat]
    out = {}
    for basis in ("inherent", "residual", "target"):
        cells = {}
        for r in rows:
            x = r[basis] if r[basis] else (r["residual"] if basis == "target" else None)
            if not x:
                continue
            k = "%d,%d" % (x["l"], x["c"])
            e = cells.setdefault(k, {"count": 0, "risks": []})
            e["count"] += 1
            if len(e["risks"]) < 12:
                e["risks"].append({"id": r["id"], "ref": r["ref"], "title": r["title"]})
        out[basis] = {"cells": cells, "levels": level_counts(rows, "residual" if basis == "target" else basis)}
    return {"total": len(rows), "unassessed": unassessed, "category": cat, "maps": out}


@router.route("GET", "/api/portfolio")
def portfolio(req):
    c = need(req, "heat_map_portfolio", "view")
    rows, unassessed = split_visible(req, c)
    cats = {}
    for r in rows:
        e = cats.setdefault(r["category"], {n: 0 for n in mx.LEVELS})
        e[r["residual"]["level"]] += 1
    snap = req.db.execute("SELECT * FROM risk_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    movement = []
    if snap:
        old = {x["id"]: x for x in json.loads(snap["data"])}
        for r in rows:
            o = old.get(r["id"])
            if o and o["res"] != r["residual"]["rank"]:
                movement.append({"id": r["id"], "ref": r["ref"], "title": r["title"], "from": o["res"], "from_level": mx.level(o["res"]), "to": r["residual"]["rank"], "to_level": r["residual"]["level"]})
            elif not o:
                movement.append({"id": r["id"], "ref": r["ref"], "title": r["title"], "from": None, "from_level": "new", "to": r["residual"]["rank"], "to_level": r["residual"]["level"]})
    status = {s: 0 for s in STATUSES}
    for r in rows:
        status[r["status"]] += 1
    return {"total": len(rows), "unassessed": unassessed, "inherent": level_counts(rows, "inherent"), "residual": level_counts(rows, "residual"), "by_category": [dict(category=k, **v) for k, v in sorted(cats.items())], "by_status": status,
            "movement": movement, "snapshot": {"label": snap["label"], "date": snap["snap_date"]} if snap else None, "can_snapshot": "approve" in c.perms.get("risk_register", set()) and c.user["data_scope"] == "all"}


@router.route("GET", "/api/command")
def command(req):
    c = need(req, "command_center", "view")
    rows, unassessed = split_visible(req, c)  # dashboard figures follow the user's data scope; executives need no register permission
    res = level_counts(rows, "residual")
    top = sorted(rows, key=lambda r: (-r["residual"]["rank"], -r["inherent"]["rank"]))[:5]
    cells = {}
    for r in rows:
        k = "%d,%d" % (r["residual"]["l"], r["residual"]["c"])
        cells[k] = cells.get(k, 0) + 1
    trend = []
    for s in req.db.execute("SELECT * FROM risk_snapshots ORDER BY id DESC LIMIT 8").fetchall()[::-1]:
        d = json.loads(s["data"])
        trend.append({"label": s["label"], "date": s["snap_date"][:10], "high_sig": sum(1 for x in d if x["res"] >= 13), "outside": sum(1 for x in d if x["outside"])})
    emv_i = sum(r["emv_i"] for r in rows if r["emv_r"] is not None and r["emv_i"])
    emv_r = sum(r["emv_r"] for r in rows if r["emv_r"] is not None)
    cat = {}
    for r in rows:
        cat[r["category"]] = cat.get(r["category"], 0) + 1
    return {"total": len(rows), "unassessed": unassessed, "residual": res, "outside_appetite": sum(1 for r in rows if r["outside_appetite"]), "draft": sum(1 for r in rows if r["status"] == "draft"), "incomplete": sum(1 for r in rows if r["missing"]),
            "awaiting_review": sum(1 for r in rows if r["status"] == "submitted"), "awaiting_approval": sum(1 for r in rows if r["status"] == "reviewed"), "needs_board": sum(1 for r in rows if r["needs_board"]),
            "cells": cells, "top": [{"id": r["id"], "ref": r["ref"], "title": r["title"], "owner_name": r["owner_name"], "residual": r["residual"], "category": r["category"], "outside": r["outside_appetite"]} for r in top],
            "trend": trend, "by_category": sorted(cat.items(), key=lambda x: -x[1]), "assurance": {"loa": round(1 - emv_r / emv_i, 4) if emv_i else None, "emv_i": emv_i, "emv_r": emv_r},
            "has_samples": any(r["is_sample"] for r in rows), "can_create": "create" in c.perms.get("risk_register", set())}


# ------------------------------------------------------------------ workbook import
@router.route("POST", "/api/risks/import")
def risks_import(req):
    """Body: the .xlsx file (raw bytes). ?dry=1 only checks and reports; ?dry=0 imports."""
    from . import wbimport
    c = need(req, "risk_register", "create")
    data = req.body()
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    try:
        parsed = wbimport.parse(data)
    except ValueError as e:
        raise HTTPError(400, "bad_file", str(e))
    except Exception:
        raise HTTPError(400, "bad_file", "The workbook could not be read. Save it as .xlsx from Excel and try again.")
    have = {r["source_ref"]: r["id"] for r in req.db.execute("SELECT id, source_ref FROM risks WHERE deleted_at IS NULL AND source_ref IS NOT NULL")}
    update = req.query.get("update") == "1"  # redo the assessment of risks that are already in the register
    new = [r for r in parsed["risks"] if r["source_ref"] not in have]
    upd = [r for r in parsed["risks"] if r["source_ref"] in have] if update else []
    skipped = [] if update else [r["source_ref"] for r in parsed["risks"] if r["source_ref"] in have]
    asm = [r for r in parsed["risks"] if r.get("from_agg")]
    summary = {"found": len(parsed["risks"]), "to_import": len(new), "to_update": len(upd), "update": update, "controls": sum(len(r["controls"]) for r in new + upd), "emv_i": sum(r["emv_i"] for r in new + upd), "skipped": skipped, "warnings": parsed["warnings"],
               "systems": {s: sum(1 for r in new + upd if r["system"] == s) for s in ("ISMS", "BCMS")},
               "assessment": {"avg_loa": sum(r["loa"] for r in asm) / len(asm) if asm else None, "avg_lor": sum(r["lor"] for r in asm) / len(asm) if asm else None, "emv_i": sum(r["emv_i"] for r in asm), "emv_r": sum(r["emv_r"] or 0 for r in asm), "overrides": sum(1 for r in asm if r.get("override")),
                              "disagree": sum(1 for w in parsed["warnings"] if "risk sheet" in w and "Aggregation Sheet" in w), "top": [{"ref": r["source_ref"], "rrr": round(r["rrr"], 2), "lor": r["lor"]} for r in sorted(asm, key=lambda z: -z["rrr"])[:5]]}}
    if req.query.get("dry") != "0":
        return dict(summary, dry=True)
    def fields(r):
        if not r.get("from_agg"):  # no assessment on the Aggregation Sheet: the risk waits for its owner, with the placeholder rating, as before
            return dict(lor=None, rrr=None, emv_r=None, rr_target=r.get("rr_target"), rr_appetite=r.get("rr_appetite"), rr_tolerance=r.get("rr_tolerance"), assessed_on=None, wb_detail=json.dumps(r.get("detail") or {}), assess_source=None, res_l=5, res_c=5, needs_assessment=1)
        l, cc = wbimport.residual_cell(r["rrr"], 5, 5)
        return dict(lor=r.get("lor"), rrr=r.get("rrr"), emv_r=r.get("emv_r"), rr_target=r.get("rr_target"), rr_appetite=r.get("rr_appetite"), rr_tolerance=r.get("rr_tolerance"), assessed_on=r.get("assessed_on"), wb_detail=json.dumps(r.get("detail") or {}), assess_source="workbook Aggregation Sheet",
                    res_l=l, res_c=cc, needs_assessment=0)
    for r in new:
        cat = "Cyber" if r["system"] == "ISMS" else "Operational"; f = fields(r)
        rid = req.db.execute("""INSERT INTO risks(title,description,category,function,objective,owner_name,owner_id,root_cause,implication,treatment,action_date,inh_l,inh_c,res_l,res_c,emv_i,emv_a,status,system,source_ref,strategic_objective,needs_assessment,
                                lor,rrr,emv_r,rr_target,rr_appetite,rr_tolerance,assessed_on,wb_detail,assess_source,created_at,created_by,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,5,5,?,?,?,?,'draft',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                             (r["title"], r["description"], cat, r["function"], r["objective"], r["owner_name"], resolve_owner(req.db, r["owner_name"]), r["root_cause"], r["implication"], r["treatment"], r["action_date"], f["res_l"], f["res_c"], r["emv_i"], r["emv_a"], r["system"], r["source_ref"], r["strategic_objective"], f["needs_assessment"],
                              f["lor"], f["rrr"], f["emv_r"], f["rr_target"], f["rr_appetite"], f["rr_tolerance"], f["assessed_on"], f["wb_detail"], f["assess_source"], now(), c.user["id"], now(), c.user["id"])).lastrowid
        req.db.execute("UPDATE risks SET ref=? WHERE id=?", ("R-%03d" % rid, rid))
        for k in r["controls"]:
            req.db.execute("INSERT INTO risk_controls(risk_id,ref,statement,domain,ice,ice_prev,owner) VALUES(?,?,?,?,?,?,?)", (rid, k["ref"], k["statement"], k["domain"], k["ice"], k.get("ice_prev"), k["owner"]))
        history(req.db, rid, c.user, "imported", {"source": [None, "workbook %s" % r["sheet"]], "rrr": [None, r.get("rrr")]})
    for r in upd:
        rid = have[r["source_ref"]]; old = req.db.execute("SELECT * FROM risks WHERE id=?", (rid,)).fetchone(); f = fields(r)
        keep_rating = not (old["needs_assessment"] or (old["assess_source"] or "").startswith("workbook"))  # a rating someone entered by hand is not overwritten
        req.db.execute("""UPDATE risks SET emv_i=?, emv_a=?, emv_r=?, lor=?, rrr=?, rr_target=?, rr_appetite=?, rr_tolerance=?, assessed_on=?, wb_detail=?, assess_source=?, function=?, strategic_objective=?, objective=?, updated_at=?, updated_by=? WHERE id=?""",
                         (r["emv_i"], r["emv_a"], f["emv_r"], f["lor"], f["rrr"], f["rr_target"], f["rr_appetite"], f["rr_tolerance"], f["assessed_on"], f["wb_detail"], f["assess_source"], r["function"], r["strategic_objective"], r["objective"], now(), c.user["id"], rid))
        if not keep_rating:
            req.db.execute("UPDATE risks SET inh_l=5, inh_c=5, res_l=?, res_c=?, needs_assessment=? WHERE id=?", (f["res_l"], f["res_c"], f["needs_assessment"], rid))
        for k in r["controls"]:
            ex = req.db.execute("SELECT id, ice_source FROM risk_controls WHERE risk_id=? AND ref=?", (rid, k["ref"])).fetchone()
            if ex and (ex["ice_source"] or "self") == "test":
                req.db.execute("UPDATE risk_controls SET ice_prev=? WHERE id=?", (k.get("ice_prev"), ex["id"]))  # a tested rating is never overwritten by the workbook
            elif ex:
                req.db.execute("UPDATE risk_controls SET statement=?, domain=?, ice=?, ice_prev=?, owner=? WHERE id=?", (k["statement"], k["domain"], k["ice"], k.get("ice_prev"), k["owner"], ex["id"]))
            else:
                req.db.execute("INSERT INTO risk_controls(risk_id,ref,statement,domain,ice,ice_prev,owner) VALUES(?,?,?,?,?,?,?)", (rid, k["ref"], k["statement"], k["domain"], k["ice"], k.get("ice_prev"), k["owner"]))
        history(req.db, rid, c.user, "assessment corrected", {"rrr": [old["rrr"], f["rrr"]], "lor": [old["lor"], f["lor"]], "residual": ["%sx%s" % (old["res_l"], old["res_c"]), "%sx%s" % (f["res_l"], f["res_c"]) if not keep_rating else "kept"]})
    from . import workbooks
    workbooks.save_risk(req.db, c.user, data, req.headers.get("X-Filename") or "risk assessment workbook.xlsx", parsed, summary)
    audit(req.db, "risk.imported", c.user, "risk_register", "Risk assessment workbook: %d risks imported, %d corrected from the workbook's assessment, %d controls (%d skipped as already present)" % (len(new), len(upd), summary["controls"], len(skipped)), req.ip)
    return dict(summary, dry=False, imported=len(new), updated=len(upd))
