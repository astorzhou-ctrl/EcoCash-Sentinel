"""Step 4 (BRD phase P1), part 2: Assessment Studio and Board Hub."""
import datetime
import json

from . import core, db as dbm, matrix as mx
from .api import router, need, need_str, DATE_RE
from .core import audit, now
from .risks import risk_dict, control_stats, history as risk_history, board_ok, num
from .web import HTTPError

SCOPES = ("all", "needs_assessment", "category", "system", "function")
OPEN = ("open", "submitted", "challenged", "approved")


# ------------------------------------------------------------------ Assessment Studio
def user_names(db, ids):
    out = {}
    for u in db.execute("SELECT id,full_name FROM users WHERE id IN (%s)" % ",".join("?" * len(ids)), list(ids)) if ids else []:
        out[u["id"]] = u["full_name"]
    return out


def assignment_dict(a, r, st, names):
    d = {"id": a["id"], "campaign_id": a["campaign_id"], "status": a["status"], "assessor": a["assessor_name"], "assessor_id": a["assessor_id"], "rationale": a["rationale"], "review_comment": a["review_comment"],
         "submitted_at": a["submitted_at"], "submitted_by": names.get(a["submitted_by"]), "reviewed_at": a["reviewed_at"], "reviewer": names.get(a["reviewer_id"]),
         "proposed": {"inh_l": a["p_inh_l"], "inh_c": a["p_inh_c"], "res_l": a["p_res_l"], "res_c": a["p_res_c"]} if a["p_inh_l"] else None}
    rd = risk_dict(r, st.get(r["id"]))
    d["risk"] = {"id": r["id"], "ref": r["ref"], "title": r["title"], "category": r["category"], "function": r["function"], "owner_name": r["owner_name"], "inherent": rd["inherent"], "residual": rd["residual"], "needs_assessment": rd["needs_assessment"], "source_ref": r["source_ref"],
                 "controls": rd["controls"], "avg_ice": rd["avg_ice"], "emv_i": r["emv_i"]}
    if d["proposed"]:
        p = d["proposed"]
        d["proposed"]["inherent"], d["proposed"]["residual"] = mx.rating(p["inh_l"], p["inh_c"]), mx.rating(p["res_l"], p["res_c"])
    return d


@router.route("POST", "/api/assess/campaigns")
def campaign_create(req):
    c = need(req, "assessment_studio", "create")
    if c.user["data_scope"] != "all":
        raise HTTPError(403, "forbidden", "Launching a campaign covers the whole register, so it needs data scope 'all'.")
    d = req.json()
    name, due = need_str(d, "name", "Campaign name", 160), (d.get("due_date") or "").strip()
    if not DATE_RE.match(due):
        raise HTTPError(400, "validation", "Choose a due date (YYYY-MM-DD).")
    st, val = d.get("scope_type") or "all", need_str(d, "scope_value", "Scope value", 120, False)
    if st not in SCOPES or (st in ("category", "system", "function") and not val):
        raise HTTPError(400, "validation", "Choose a scope and, for category, system or function, its value.")
    where = {"all": "1=1", "needs_assessment": "needs_assessment=1", "category": "category=?", "system": "system=?", "function": "function=? COLLATE NOCASE"}[st]
    risks = req.db.execute("SELECT * FROM risks WHERE deleted_at IS NULL AND status!='closed' AND %s ORDER BY id" % where, [val] if st in ("category", "system", "function") else []).fetchall()
    if not risks:
        raise HTTPError(400, "empty", "No risks match that scope.")
    cid = req.db.execute("INSERT INTO campaigns(name,description,scope_type,scope_value,due_date,created_at,created_by) VALUES(?,?,?,?,?,?,?)", (name, need_str(d, "description", "Description", 500, False), st, val or None, due, now(), c.user["id"])).lastrowid
    for r in risks:
        req.db.execute("INSERT INTO assignments(campaign_id,risk_id,assessor_id,assessor_name) VALUES(?,?,?,?)", (cid, r["id"], r["owner_id"], r["owner_name"]))
    audit(req.db, "assess.campaign_created", c.user, "assessment_studio", "Campaign '%s' launched for %d risks, due %s" % (name, len(risks), due), req.ip)
    return {"id": cid, "assignments": len(risks)}


def counts(db, cid):
    o = {k: 0 for k in OPEN}
    for r in db.execute("SELECT status, COUNT(*) n FROM assignments WHERE campaign_id=? GROUP BY status", (cid,)):
        o[r["status"]] = r["n"]
    o["total"] = sum(o.values())
    return o


@router.route("GET", "/api/assess/campaigns")
def campaign_list(req):
    c = need(req, "assessment_studio", "view")
    out = []
    for k in req.db.execute("SELECT * FROM campaigns ORDER BY id DESC"):
        n = counts(req.db, k["id"])
        out.append(dict(dict(k), counts=n, completion=round(100 * n["approved"] / n["total"]) if n["total"] else 0, overdue=k["status"] == "open" and k["due_date"] < str(dbm.today()) and n["approved"] < n["total"]))
    return {"campaigns": out, "can": {a: a in c.perms.get("assessment_studio", set()) for a in core.ACTIONS}, "scope_all": c.user["data_scope"] == "all", "categories": sorted({r["category"] for r in req.db.execute("SELECT DISTINCT category FROM risks WHERE deleted_at IS NULL")}),
            "functions": sorted({r["function"] for r in req.db.execute("SELECT DISTINCT function FROM risks WHERE deleted_at IS NULL AND function IS NOT NULL")})}


@router.route("GET", "/api/assess/campaigns/<int:cid>")
def campaign_get(req):
    c = need(req, "assessment_studio", "view")
    k = req.db.execute("SELECT * FROM campaigns WHERE id=?", (int(req.params["cid"]),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Campaign not found")
    st = control_stats(req.db)
    rows = req.db.execute("SELECT a.*, r.id rid FROM assignments a JOIN risks r ON r.id=a.risk_id WHERE a.campaign_id=? AND r.deleted_at IS NULL ORDER BY a.id", (k["id"],)).fetchall()
    risks = {r["id"]: r for r in req.db.execute("SELECT * FROM risks WHERE id IN (SELECT risk_id FROM assignments WHERE campaign_id=?)", (k["id"],))}
    names = user_names(req.db, {x for a in rows for x in (a["submitted_by"], a["reviewer_id"]) if x})
    ass = [assignment_dict(a, risks[a["risk_id"]], st, names) for a in rows]
    by = {}
    for a in ass:
        f = a["risk"]["function"] or "Unassigned"
        e = by.setdefault(f, {"function": f, "total": 0, "approved": 0})
        e["total"] += 1; e["approved"] += a["status"] == "approved"
    n = counts(req.db, k["id"])
    return {"campaign": dict(k), "counts": n, "assignments": ass, "by_function": sorted(by.values(), key=lambda x: -x["total"]), "me": c.user["id"], "can": {a: a in c.perms.get("assessment_studio", set()) for a in core.ACTIONS}, "scope_all": c.user["data_scope"] == "all"}


@router.route("GET", "/api/assess/mine")
def assess_mine(req):
    c = need(req, "assessment_studio", "view")
    first = (c.user["full_name"].split() or [""])[0].lower()
    st = control_stats(req.db)
    out = []
    for a in req.db.execute("SELECT a.*, k.name cname, k.due_date FROM assignments a JOIN campaigns k ON k.id=a.campaign_id WHERE k.status='open' AND a.status IN ('open','challenged','submitted') ORDER BY k.due_date, a.id"):
        mine = a["assessor_id"] == c.user["id"] or (a["assessor_name"] and (c.user["full_name"].lower() == a["assessor_name"].lower() or c.user["username"].lower() == a["assessor_name"].lower()))
        if not mine and not (c.user["data_scope"] == "all" and "approve" in c.perms.get("assessment_studio", set())):
            continue
        r = req.db.execute("SELECT * FROM risks WHERE id=? AND deleted_at IS NULL", (a["risk_id"],)).fetchone()
        if r:
            out.append(dict(assignment_dict(a, r, st, {}), campaign=a["cname"], due_date=a["due_date"], mine=bool(mine)))
    return {"assignments": out}


def ratings(d):
    f = {"inh_l": num(d, "inh_l", "Inherent likelihood", 1, 5), "inh_c": num(d, "inh_c", "Inherent consequence", 1, 5), "res_l": num(d, "res_l", "Residual likelihood", 1, 5), "res_c": num(d, "res_c", "Residual consequence", 1, 5)}
    if f["res_l"] > f["inh_l"] or f["res_c"] > f["inh_c"]:
        raise HTTPError(400, "validation", "Residual likelihood and consequence cannot be higher than inherent.")
    return f


def get_assignment(req, aid):
    a = req.db.execute("SELECT a.*, k.status cstatus FROM assignments a JOIN campaigns k ON k.id=a.campaign_id WHERE a.id=?", (aid,)).fetchone()
    if not a:
        raise HTTPError(404, "not_found", "Assessment not found")
    if a["cstatus"] != "open":
        raise HTTPError(409, "closed", "This campaign is closed.")
    r = req.db.execute("SELECT * FROM risks WHERE id=? AND deleted_at IS NULL", (a["risk_id"],)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "The risk no longer exists.")
    return a, r


@router.route("POST", "/api/assess/assignments/<int:aid>/submit")
def assess_submit(req):
    c = need(req, "assessment_studio", "edit")
    a, r = get_assignment(req, int(req.params["aid"]))
    if a["status"] not in ("open", "challenged"):
        raise HTTPError(409, "bad_state", "This assessment is already %s." % a["status"])
    mine = a["assessor_id"] == c.user["id"] or (a["assessor_name"] or "").lower() in (c.user["full_name"].lower(), c.user["username"].lower())
    if not mine and not (c.user["data_scope"] == "all" or "approve" in c.perms.get("assessment_studio", set())):
        raise HTTPError(403, "forbidden", "Only the risk owner (or the Risk Office on the owner's behalf) can submit this assessment.")
    d = req.json()
    f = ratings(d)
    why = need_str(d, "rationale", "The rationale", 1000)
    if len(why) < 10:
        raise HTTPError(400, "validation", "Explain the rating in at least 10 characters (evidence, controls, incidents).")
    req.db.execute("UPDATE assignments SET status='submitted', p_inh_l=?, p_inh_c=?, p_res_l=?, p_res_c=?, rationale=?, submitted_by=?, submitted_at=?, review_comment=NULL WHERE id=?", (f["inh_l"], f["inh_c"], f["res_l"], f["res_c"], why, c.user["id"], now(), a["id"]))
    audit(req.db, "assess.submitted", c.user, "assessment_studio", "%s assessed: inherent %d, residual %d%s" % (r["ref"], mx.rank(f["inh_l"], f["inh_c"]), mx.rank(f["res_l"], f["res_c"]), "" if mine else " (on behalf of the owner)"), req.ip)
    return {"ok": True}


@router.route("POST", "/api/assess/assignments/<int:aid>/review")
def assess_review(req):
    c = need(req, "assessment_studio", "approve")
    a, r = get_assignment(req, int(req.params["aid"]))
    if a["status"] != "submitted":
        raise HTTPError(409, "bad_state", "Only a submitted assessment can be reviewed.")
    if a["submitted_by"] == c.user["id"]:
        raise HTTPError(409, "same_person", "You submitted this assessment, so someone else must review it (separation of duties).")
    d = req.json()
    dec, comment = d.get("decision"), need_str(d, "comment", "Comment", 500, False)
    if dec not in ("approve", "challenge"):
        raise HTTPError(400, "validation", "Choose approve or challenge.")
    if dec == "challenge":
        if len(comment) < 5:
            raise HTTPError(400, "validation", "Say what the owner should reconsider (at least 5 characters).")
        req.db.execute("UPDATE assignments SET status='challenged', reviewer_id=?, reviewed_at=?, review_comment=? WHERE id=?", (c.user["id"], now(), comment, a["id"]))
        audit(req.db, "assess.challenged", c.user, "assessment_studio", "%s challenged: %s" % (r["ref"], comment[:100]), req.ip)
        return {"status": "challenged"}
    new = {"inh_l": a["p_inh_l"], "inh_c": a["p_inh_c"], "res_l": a["p_res_l"], "res_c": a["p_res_c"]}
    ch = {k: [r[k], v] for k, v in new.items() if r[k] != v}
    tgt = (r["tgt_l"], r["tgt_c"])
    clear = bool(tgt[0]) and (tgt[0] > new["res_l"] or tgt[1] > new["res_c"])
    req.db.execute("UPDATE risks SET inh_l=?, inh_c=?, res_l=?, res_c=?, needs_assessment=0%s, updated_at=?, updated_by=? WHERE id=?" % (", tgt_l=NULL, tgt_c=NULL" if clear else ""), (new["inh_l"], new["inh_c"], new["res_l"], new["res_c"], now(), c.user["id"], r["id"]))
    if r["needs_assessment"]:
        ch["assessment"] = ["placeholder rating", "assessed in campaign, approved by %s" % c.user["username"]]
    if clear:
        ch["target"] = ["%s,%s" % tgt, "cleared (above the new residual)"]
    ch["rationale"] = [None, a["rationale"][:200]]
    risk_history(req.db, r["id"], c.user, "assessment approved", ch)
    req.db.execute("UPDATE assignments SET status='approved', reviewer_id=?, reviewed_at=?, review_comment=? WHERE id=?", (c.user["id"], now(), comment or None, a["id"]))
    audit(req.db, "assess.approved", c.user, "assessment_studio", "%s rating applied: inherent %d, residual %d (%s)" % (r["ref"], mx.rank(new["inh_l"], new["inh_c"]), mx.rank(new["res_l"], new["res_c"]), mx.band(mx.rank(new["res_l"], new["res_c"]))), req.ip)
    return {"status": "approved", "residual": mx.rating(new["res_l"], new["res_c"])}


@router.route("POST", "/api/assess/campaigns/<int:cid>/close")
def campaign_close(req):
    c = need(req, "assessment_studio", "approve")
    k = req.db.execute("SELECT * FROM campaigns WHERE id=? AND status='open'", (int(req.params["cid"]),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Open campaign not found")
    n = counts(req.db, k["id"])
    req.db.execute("UPDATE campaigns SET status='closed', closed_at=? WHERE id=?", (now(), k["id"]))
    audit(req.db, "assess.campaign_closed", c.user, "assessment_studio", "Campaign '%s' closed: %d of %d approved" % (k["name"], n["approved"], n["total"]), req.ip)
    return {"ok": True, "approved": n["approved"], "total": n["total"]}


# ------------------------------------------------------------------ Board Hub
def assessed_dicts(db):
    st = control_stats(db)
    return [risk_dict(r, st.get(r["id"])) for r in db.execute("SELECT * FROM risks WHERE deleted_at IS NULL AND needs_assessment=0")]


def decision_dict(db, d):
    r = db.execute("SELECT ref,title,owner_name,category,res_l,res_c FROM risks WHERE id=?", (d["risk_id"],)).fetchone()
    names = user_names(db, {x for x in (d["requested_by"], d["decided_by"]) if x})
    m = db.execute("SELECT title,meeting_date FROM meetings WHERE id=?", (d["meeting_id"],)).fetchone() if d["meeting_id"] else None
    rk = mx.rank(r["res_l"], r["res_c"]) if r else None
    return {"id": d["id"], "risk_id": d["risk_id"], "ref": r["ref"] if r else "?", "title": r["title"] if r else "(deleted)", "owner": r["owner_name"] if r else None, "rank_now": rk, "level_now": mx.level(rk) if rk else None, "rank_at_request": d["rank_at_request"],
            "recommendation": d["recommendation"], "status": d["status"], "requested_by": names.get(d["requested_by"]), "requested_at": d["requested_at"], "decided_by": names.get(d["decided_by"]), "decided_at": d["decided_at"], "reference": d["reference"],
            "expiry_date": d["expiry_date"], "conditions": d["conditions"], "meeting": dict(m) if m else None, "valid": d["status"] == "approved" and (not d["expiry_date"] or d["expiry_date"] >= str(dbm.today()))}


@router.route("GET", "/api/board")
def board_get(req):
    c = need(req, "board_hub", "view")
    db = req.db
    decs = [decision_dict(db, d) for d in db.execute("SELECT * FROM board_decisions ORDER BY id DESC")]
    have = {d["risk_id"] for d in decs if d["status"] == "pending" or d["valid"]}
    cand = [{"id": r["id"], "ref": r["ref"], "title": r["title"], "owner": r["owner_name"], "rank": r["residual"]["rank"], "level": r["residual"]["level"], "band": r["appetite_band"]} for r in assessed_dicts(db) if r["residual"]["rank"] > mx.THRESH["appetite"] and r["id"] not in have]
    cand.sort(key=lambda x: -x["rank"])
    packs = [{"id": p["id"], "title": p["title"], "status": p["status"], "created_at": p["created_at"], "issued_at": p["issued_at"], "meeting_id": p["meeting_id"]} for p in db.execute("SELECT * FROM board_packs ORDER BY id DESC")]
    return {"meetings": [dict(m) for m in db.execute("SELECT * FROM meetings ORDER BY COALESCE(meeting_date,'9999') DESC, id DESC")], "decisions": decs, "candidates": cand, "packs": packs, "thresholds": dict(mx.THRESH), "me": c.user["id"],
            "can": {a: a in c.perms.get("board_hub", set()) for a in core.ACTIONS}}


@router.route("POST", "/api/board/meetings")
def meeting_create(req):
    c = need(req, "board_hub", "create")
    d = req.json()
    dt = (d.get("meeting_date") or "").strip()
    if not DATE_RE.match(dt):
        raise HTTPError(400, "validation", "Choose the meeting date (YYYY-MM-DD).")
    mid = req.db.execute("INSERT INTO meetings(title,meeting_date,notes,created_by,created_at) VALUES(?,?,?,?,?)", (need_str(d, "title", "Title", 160), dt, need_str(d, "notes", "Notes", 1000, False), c.user["id"], now())).lastrowid
    audit(req.db, "board.meeting_created", c.user, "board_hub", "Meeting scheduled for %s" % dt, req.ip)
    return {"id": mid}


@router.route("PUT", "/api/board/meetings/<int:mid>")
def meeting_update(req):
    c = need(req, "board_hub", "edit")
    d = req.json()
    st = d.get("status")
    if st not in ("planned", "held", "cancelled"):
        raise HTTPError(400, "validation", "Status must be planned, held or cancelled.")
    n = req.db.execute("UPDATE meetings SET status=?, notes=COALESCE(?,notes) WHERE id=?", (st, need_str(d, "notes", "Notes", 1000, False) or None, int(req.params["mid"]))).rowcount
    if not n:
        raise HTTPError(404, "not_found", "Meeting not found")
    audit(req.db, "board.meeting_updated", c.user, "board_hub", "Meeting %s marked %s" % (req.params["mid"], st), req.ip)
    return {"ok": True}


@router.route("POST", "/api/board/decisions")
def decision_request(req):
    c = need(req, "board_hub", "create")
    d = req.json()
    r = req.db.execute("SELECT * FROM risks WHERE id=? AND deleted_at IS NULL", (d.get("risk_id"),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Risk not found")
    if r["needs_assessment"]:
        raise HTTPError(409, "unassessed", "This risk still has a placeholder rating. Assess it first.")
    rk = mx.rank(r["res_l"], r["res_c"])
    if rk <= mx.THRESH["appetite"]:
        raise HTTPError(409, "within_appetite", "This risk (rank %d) is within the appetite limit (%d); no Board approval is needed." % (rk, mx.THRESH["appetite"]))
    if req.db.execute("SELECT 1 FROM board_decisions WHERE risk_id=? AND status='pending'", (r["id"],)).fetchone():
        raise HTTPError(409, "pending", "A decision request for this risk is already waiting.")
    mid = d.get("meeting_id") or None
    if mid and not req.db.execute("SELECT 1 FROM meetings WHERE id=?", (mid,)).fetchone():
        raise HTTPError(400, "validation", "Unknown meeting.")
    rec = need_str(d, "recommendation", "The recommendation", 800)
    if len(rec) < 10:
        raise HTTPError(400, "validation", "Write the recommendation (for example: retain for 90 days while plan A-118 is funded) in at least 10 characters.")
    did = req.db.execute("INSERT INTO board_decisions(risk_id,meeting_id,recommendation,rank_at_request,requested_by,requested_at) VALUES(?,?,?,?,?,?)", (r["id"], mid, rec, rk, c.user["id"], now())).lastrowid
    risk_history(req.db, r["id"], c.user, "board decision requested", {"recommendation": [None, rec[:200]]})
    audit(req.db, "board.requested", c.user, "board_hub", "%s sent to the Board (rank %d): %s" % (r["ref"], rk, rec[:80]), req.ip)
    return {"id": did}


@router.route("POST", "/api/board/decisions/<int:did>/decide")
def decision_decide(req):
    c = need(req, "board_hub", "approve")
    dc = req.db.execute("SELECT * FROM board_decisions WHERE id=? AND status='pending'", (int(req.params["did"]),)).fetchone()
    if not dc:
        raise HTTPError(404, "not_found", "No pending decision with that number")
    if dc["requested_by"] == c.user["id"]:
        raise HTTPError(409, "same_person", "You requested this decision, so someone else must record it (separation of duties).")
    d = req.json()
    st = d.get("decision")
    if st not in ("approved", "deferred", "rejected"):
        raise HTTPError(400, "validation", "Choose approved, deferred or rejected.")
    ref = need_str(d, "reference", "The Board minute or reference", 200)
    if len(ref) < 5:
        raise HTTPError(400, "validation", "Give the Board minute or reference (at least 5 characters).")
    exp = (d.get("expiry_date") or "").strip() or None
    if st == "approved":
        if not exp or not DATE_RE.match(exp) or not str(dbm.today()) <= exp <= str(dbm.today() + datetime.timedelta(days=366)):
            raise HTTPError(400, "validation", "Retention must end on a date within the next 12 months (GRC Policy 2.4: approval is time-limited).")
    r = req.db.execute("SELECT * FROM risks WHERE id=?", (dc["risk_id"],)).fetchone()
    cond = need_str(d, "conditions", "Conditions", 800, False)
    req.db.execute("UPDATE board_decisions SET status=?, decided_by=?, decided_at=?, reference=?, expiry_date=?, conditions=? WHERE id=?", (st, c.user["id"], now(), ref, exp if st == "approved" else None, cond, dc["id"]))
    if st == "approved":
        req.db.execute("UPDATE risks SET needs_board=1 WHERE id=?", (r["id"],))
    elif st == "rejected" and r["status"] != "draft":
        req.db.execute("UPDATE risks SET status='draft', needs_board=0, updated_at=?, updated_by=? WHERE id=?", (now(), c.user["id"], r["id"]))
    risk_history(req.db, r["id"], c.user, "board decision %s" % st, {"reference": [None, ref], "expiry": [None, exp], "conditions": [None, cond[:200]]})
    audit(req.db, "board.decided", c.user, "board_hub", "%s: %s (%s%s)" % (r["ref"], st, ref, ", until " + exp if exp else ""), req.ip)
    return {"status": st}


def build_pack(db, title):
    rows = assessed_dicts(db)
    lv = lambda k: {n: sum(1 for r in rows if r[k]["level"] == n) for n in mx.LEVELS}
    decs = [decision_dict(db, d) for d in db.execute("SELECT * FROM board_decisions ORDER BY id DESC")]
    top = sorted(rows, key=lambda r: (-r["residual"]["rank"], -r["inherent"]["rank"]))[:10]
    snap = db.execute("SELECT * FROM risk_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    mv = []
    if snap:
        old = {x["id"]: x for x in json.loads(snap["data"])}
        for r in rows:
            o = old.get(r["id"])
            if o and o["res"] != r["residual"]["rank"] or not o:
                mv.append({"ref": r["ref"], "title": r["title"], "from": o["res"] if o else None, "to": r["residual"]["rank"]})
    ei = sum(r["emv_i"] for r in rows if r["emv_r"] is not None and r["emv_i"])
    er = sum(r["emv_r"] for r in rows if r["emv_r"] is not None)
    from . import p1
    sts = [p1.stmt_dict(db, s) for s in db.execute("SELECT * FROM appetite_statements WHERE active=1 ORDER BY sort, id")]
    k = p1.cfg(db)
    tasks = [p1.task_dict(t, dbm.today(), k["soon_days"]) for t in db.execute("SELECT * FROM tasks WHERE deleted_at IS NULL")]
    camps = [dict(name=c["name"], due=c["due_date"], counts=counts(db, c["id"])) for c in db.execute("SELECT * FROM campaigns WHERE status='open'")]
    cells = {}
    for r in rows:
        key = "%d,%d" % (r["residual"]["l"], r["residual"]["c"]); cells[key] = cells.get(key, 0) + 1
    return {"title": title, "generated_at": now(), "thresholds": dict(mx.THRESH), "assessed": len(rows), "unassessed": db.execute("SELECT COUNT(*) c FROM risks WHERE deleted_at IS NULL AND needs_assessment=1").fetchone()["c"],
            "residual": lv("residual"), "inherent": lv("inherent"), "cells": cells, "outside_appetite": sum(1 for r in rows if r["outside_appetite"]), "outside_tolerance": sum(1 for r in rows if r["appetite_band"] == "outside_tolerance"),
            "top": [{"ref": r["ref"], "title": r["title"], "owner": r["owner_name"], "category": r["category"], "inherent": r["inherent"]["rank"], "residual": r["residual"]["rank"], "level": r["residual"]["level"], "band": r["appetite_band"], "loa": r["loa"]} for r in top],
            "above": [{"ref": r["ref"], "title": r["title"], "rank": r["residual"]["rank"], "decision": next((d["status"] + (" until " + d["expiry_date"] if d["expiry_date"] else "") for d in decs if d["risk_id"] == r["id"]), "none")} for r in sorted(rows, key=lambda r: -r["residual"]["rank"]) if r["outside_appetite"]],
            "movement": mv, "snapshot": snap["label"] if snap else None, "assurance": {"loa": round(1 - er / ei, 4) if ei else None, "emv_i": ei, "emv_r": er},
            "decisions": [d for d in decs if d["status"] != "pending" and d["decided_at"] and d["decided_at"] >= dbm.minus(days=92)], "pending": [d for d in decs if d["status"] == "pending"],
            "appetite": [{"dimension": s["dimension"], "metric": s["metric"], "limit": s["limit"], "actual": s["actual"], "unit": s["unit"], "status": s["status"]} for s in sts], "campaigns": camps, "tracker": p1.tiles(tasks, dbm.today())}


@router.route("POST", "/api/board/packs")
def pack_create(req):
    c = need(req, "board_hub", "create")
    d = req.json()
    mid = d.get("meeting_id") or None
    pid = req.db.execute("INSERT INTO board_packs(title,meeting_id,data,created_by,created_at) VALUES(?,?,?,?,?)", (need_str(d, "title", "Title", 160), mid, json.dumps(build_pack(req.db, need_str(d, "title", "Title", 160))), c.user["id"], now())).lastrowid
    audit(req.db, "board.pack_created", c.user, "board_hub", "Pack drafted from live data (frozen at this moment): %s" % d.get("title", "")[:80], req.ip)
    return {"id": pid}


@router.route("GET", "/api/board/packs/<int:pid>")
def pack_get(req):
    c = need(req, "board_hub", "view")
    p = req.db.execute("SELECT * FROM board_packs WHERE id=?", (int(req.params["pid"]),)).fetchone()
    if not p:
        raise HTTPError(404, "not_found", "Pack not found")
    return {"id": p["id"], "title": p["title"], "status": p["status"], "created_at": p["created_at"], "issued_at": p["issued_at"], "data": json.loads(p["data"]), "can": {a: a in c.perms.get("board_hub", set()) for a in core.ACTIONS}}


@router.route("POST", "/api/board/packs/<int:pid>/<action>")
def pack_action(req):
    c = need(req, "board_hub", "approve")
    p = req.db.execute("SELECT * FROM board_packs WHERE id=?", (int(req.params["pid"]),)).fetchone()
    if not p:
        raise HTTPError(404, "not_found", "Pack not found")
    act = req.params["action"]
    if act == "issue" and p["status"] == "draft":
        req.db.execute("UPDATE board_packs SET status='issued', issued_by=?, issued_at=? WHERE id=?", (c.user["id"], now(), p["id"]))
    elif act == "withdraw" and p["status"] == "issued":
        req.db.execute("UPDATE board_packs SET status='withdrawn' WHERE id=?", (p["id"],))
    else:
        raise HTTPError(409, "bad_state", "A %s pack cannot be %s." % (p["status"], act))
    audit(req.db, "board.pack_%s" % act, c.user, "board_hub", "Pack %d (%s): %s" % (p["id"], p["title"][:60], act), req.ip)
    return {"status": "issued" if act == "issue" else "withdrawn"}


@router.route("DELETE", "/api/board/packs/<int:pid>")
def pack_delete(req):
    c = need(req, "board_hub", "delete")
    p = req.db.execute("SELECT * FROM board_packs WHERE id=?", (int(req.params["pid"]),)).fetchone()
    if not p:
        raise HTTPError(404, "not_found", "Pack not found")
    if p["status"] != "draft":
        raise HTTPError(409, "issued", "Only a draft pack can be deleted. An issued pack can be withdrawn but is kept for the record.")
    req.db.execute("DELETE FROM board_packs WHERE id=?", (p["id"],))
    audit(req.db, "board.pack_deleted", c.user, "board_hub", "Draft pack %d deleted" % p["id"], req.ip)
    return {"ok": True}
