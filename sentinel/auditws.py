"""Audit Workspace (BRD 9.13, GRC Policy 1.7): a risk-based audit plan, engagements graded Good, Satisfactory, Less than satisfactory or Unsatisfactory, findings with a
management response and independent closure, and a view of assurance across the three lines.
Rules: a finding links to a risk and a control and LOWERS the assurance shown for that risk while it is open; the owner responds; only an auditor who is not the owner closes it;
internal audit has read-only access to the rest of the platform (the Internal Auditor role)."""
import datetime
import json
import re

from . import ai_engine, analytics, matrix as mx, p5, register, strategy, xlsxbook
from .api import router, need, need_str
from .core import audit as audit_log, now
from .p2 import xlsx_response
from .web import HTTPError
from . import db as dbm

GRADES = {"G": "Good", "S": "Satisfactory", "LS": "Less than satisfactory", "U": "Unsatisfactory"}
PRIORITY = {"High": 10, "Medium": 5, "Low": 2}  # points of assurance a finding takes away from its risk while open
STATUS_PLAN = ("planned", "fieldwork", "reporting", "closed")


def penalty(db, risk_id):
    pts = sum(PRIORITY.get(r["priority"], 0) for r in db.execute("SELECT priority FROM audit_findings WHERE risk_id=? AND deleted_at IS NULL AND status IN ('open','responded')", (risk_id,)))
    return min(30, pts)


def is_owner(db, user, f):
    if f["owner_id"] and f["owner_id"] == user["id"]:
        return True
    t = re.sub(r"\s+", " ", (f["owner_name"] or "").strip().lower())
    return bool(t) and t in {(user["full_name"] or "").lower(), (user["job_title"] or "").lower(), (user["username"] or "").lower()}


def fin_view(db, f, today, user=None):
    d = dict(f); d["age_days"] = max(0, (today - datetime.date.fromisoformat(f["created_at"][:10])).days)
    d["overdue"] = bool(f["status"] in ("open", "responded") and f["due_date"] and f["due_date"] < today.isoformat())
    d["days_late"] = (today - datetime.date.fromisoformat(f["due_date"])).days if d["overdue"] else 0
    r = db.execute("SELECT ref, source_ref, title FROM risks WHERE id=?", (f["risk_id"],)).fetchone() if f["risk_id"] else None
    d["risk"] = ((r["source_ref"] or r["ref"]) + " " + r["title"][:50]) if r else None
    k = db.execute("SELECT ref, statement FROM risk_controls WHERE id=?", (f["control_id"],)).fetchone() if f["control_id"] else None
    d["control"] = ((k["ref"] or "control") + " " + (k["statement"] or "")[:50]) if k else None
    d["mine"] = bool(user and is_owner(db, user, f))
    return d


def coverage(db, c, today):
    """For each strategic objective: the first line (controls attested in the last 12 months), the second line (risks assessed in the last 12 months) and the third line (audit engagements in the last 24 months)."""
    strategy.ensure(db); rows, _ = analytics.risk_rows(db, c); assessed = {r["id"]: r["assessed_on"] for r in db.execute("SELECT id, assessed_on FROM risks")}; objs = [dict(o) for o in db.execute("SELECT * FROM objectives WHERE active=1 ORDER BY sort, id")]; yr = (today - datetime.timedelta(days=365)).isoformat(); out = []
    eng = [dict(e) for e in db.execute("SELECT * FROM audit_plan WHERE deleted_at IS NULL AND status IN ('fieldwork','reporting','closed') AND year >= ?", (today.year - 1,))]
    for o in objs:
        rs = [r for r in rows if strategy.objective_of([o], r["so"] if r["so"] != "Unassigned" else "")]
        ids = [r["id"] for r in rs]
        ctl = [k for k in db.execute("SELECT risk_id, attested_on, ice_source FROM risk_controls") if k["risk_id"] in set(ids)]
        l1 = (sum(1 for k in ctl if (k["attested_on"] or "") >= yr or k["ice_source"] == "test") / len(ctl)) if ctl else 0.0
        l2 = (sum(1 for r in rs if (assessed.get(r["id"]) or "")[:10] >= yr) / len(rs)) if rs else 0.0
        l3 = sum(1 for e in eng if e["risk_id"] in set(ids) or (e["area"] and (o["name"].lower() in e["area"].lower() or o["code"].lower() in e["area"].lower())))
        pen = [(r, penalty(db, r["id"])) for r in rs]; adj = [max(0.0, (r["loa"] or 0) - p / 100.0) for r, p in pen if r["loa"] is not None]
        out.append({"code": o["code"], "name": o["name"], "risks": len(rs), "line1": round(l1, 2), "line2": round(l2, 2), "line3": l3, "open_findings": sum(1 for r in rs for _ in db.execute("SELECT 1 FROM audit_findings WHERE risk_id=? AND deleted_at IS NULL AND status IN ('open','responded')", (r["id"],))),
                    "loa": round(sum(r["loa"] for r in rs if r["loa"] is not None) / max(1, sum(1 for r in rs if r["loa"] is not None)), 3) if rs else None, "loa_adjusted": round(sum(adj) / len(adj), 3) if adj else None})
    return out


def focus(db, c, today, limit=8):
    """Where internal audit might look next: risks high on rating, with weak controls, failed tests, indicators in alert or overdue actions, and no audit work in 24 months. A suggestion for the audit team's judgement."""
    rows, _ = analytics.risk_rows(db, c); audited = {e["risk_id"] for e in db.execute("SELECT risk_id FROM audit_plan WHERE deleted_at IS NULL AND risk_id IS NOT NULL AND year >= ?", (today.year - 1,))}; out = []
    for r in rows:
        if r["rrr"] is None:
            continue
        ev = ai_engine.evidence(db, c, r); score = (r["rrr"] / 25.0) * 40; why = ["Residual rating %.1f of 25." % r["rrr"]]
        weak = [w for w in ev["weak_domains"] if w[1] < 0.5]
        if weak:
            score += 15; why.append("Weak controls in %s." % ", ".join(w[0] for w in weak))
        failed = db.execute("SELECT COUNT(*) n FROM risk_controls WHERE risk_id=? AND lower(COALESCE(result,'')) IN ('fail','failed','ineffective')", (r["id"],)).fetchone()["n"]
        if failed:
            score += min(15, 5 * failed); why.append("%d control(s) failed a test." % failed)
        if ev["kris"]:
            score += min(10, 5 * len(ev["kris"])); why.append("%d indicator(s) in alert." % len(ev["kris"]))
        if ev["overdue"]:
            score += min(10, 3 * len(ev["overdue"])); why.append("%d overdue action(s)." % len(ev["overdue"]))
        if r["id"] not in audited:
            score += 15; why.append("No audit work linked in the last two years.")
        if score >= 20:
            out.append({"risk_id": r["id"], "ref": r["source_ref"] or r["ref"], "title": r["title"], "score": round(score), "reasons": why, "dept": r["dept"]})
    out.sort(key=lambda z: -z["score"]); return out[:limit]


def draft(db, c, risk_id, control_id=None):
    """Condition, criteria, cause, effect and recommendation drafted from the evidence in the register. The auditor writes the finding."""
    rows, _ = analytics.risk_rows(db, c); r = next((x for x in rows if x["id"] == risk_id), None)
    if not r:
        raise HTTPError(404, "not_found", "Risk not found or not visible to you.")
    ev = ai_engine.evidence(db, c, r); k = db.execute("SELECT * FROM risk_controls WHERE id=? AND risk_id=?", (control_id, risk_id)).fetchone() if control_id else None; ref = r["source_ref"] or r["ref"]
    cond = []
    if k:
        cond.append("Control %s (%s) is %s." % (k["ref"] or "", (k["statement"] or "")[:120], "rated %d%% effective" % round((1 - k["ice"]) * 100) if k["ice"] is not None else "not yet rated"))
    cond += [x for x in ai_engine.why_lines(r, ev)]
    weakest = sorted(ev["weak_domains"], key=lambda z: z[1])[:1]
    return {"title": ("Control weakness: %s" % ((k["statement"] or "")[:80] if k else r["title"][:80])).strip(), "condition_text": " ".join(cond) or "Evidence in the register for this risk is limited.", "criteria": "The GRC Policy sets a control effectiveness target of 80% and requires risks above appetite to have a dated treatment plan.",
            "cause": "To be established by the auditor%s." % (" (the weakest control category is %s)" % weakest[0][0] if weakest else ""), "effect": "Residual rating %s; level of assurance %s against the 80%% target; risk %s." % ("n/a" if r["rrr"] is None else "%.1f" % r["rrr"], "n/a" if r["loa"] is None else "%d%%" % round(r["loa"] * 100), register.position(r).lower()),
            "recommendation": "Strengthen the control, assign a dated owner action and retest independently; report progress to the Audit Committee.", "risk_id": risk_id, "control_id": k["id"] if k else None, "note": "Drafted from the register's evidence. The auditor confirms the facts and writes the finding."}


@router.route("GET", "/api/audit/overview")
def overview(req):
    c = need(req, "audit_workspace", "view"); today = dbm.today(); yr = int(req.query.get("year") or today.year)
    plan = [dict(e) for e in req.db.execute("SELECT * FROM audit_plan WHERE deleted_at IS NULL AND year=? ORDER BY month_start, id", (yr,))]
    for e in plan:
        e["grade_name"] = GRADES.get(e["grade"]); r = req.db.execute("SELECT ref, source_ref FROM risks WHERE id=?", (e["risk_id"],)).fetchone() if e["risk_id"] else None; e["risk"] = (r["source_ref"] or r["ref"]) if r else None
    findings = [fin_view(req.db, f, today, c.user) for f in req.db.execute("SELECT * FROM audit_findings WHERE deleted_at IS NULL ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'responded' THEN 1 ELSE 2 END, due_date")]
    allp = [dict(e) for e in req.db.execute("SELECT year, month_end, grade FROM audit_plan WHERE deleted_at IS NULL AND grade IS NOT NULL")]; q = {}
    for e in allp:
        key = "%d Q%d" % (e["year"], (e["month_end"] - 1) // 3 + 1); d = q.setdefault(key, {"G": 0, "S": 0, "LS": 0, "U": 0}); d[e["grade"]] += 1
    opn = [f for f in findings if f["status"] in ("open", "responded")]
    return {"year": yr, "plan": plan, "grades_by_quarter": [dict(quarter=k, **v) for k, v in sorted(q.items())], "findings": findings, "coverage": coverage(req.db, c, today),
            "tiles": {"engagements": len(plan), "complete": sum(1 for e in plan if e["status"] == "closed"), "open_findings": len(opn), "overdue": sum(1 for f in opn if f["overdue"]), "high_open": sum(1 for f in opn if f["priority"] == "High"), "avg_age": round(sum(f["age_days"] for f in opn) / len(opn)) if opn else 0},
            "grades": GRADES, "can": {k: k in c.perms.get("audit_workspace", set()) for k in ("create", "edit", "delete", "approve", "export")}, "years": sorted({e["year"] for e in req.db.execute("SELECT year FROM audit_plan WHERE deleted_at IS NULL")} | {today.year}), "today": today.isoformat()}


def _plan_fields(b):
    title = need_str(b, "title", "Engagement", 200)
    try:
        yr, ms, me = int(b["year"]), int(b["month_start"]), int(b["month_end"])
    except (KeyError, TypeError, ValueError):
        raise HTTPError(400, "validation", "Give the year and the first and last month.")
    if not (2020 <= yr <= 2100 and 1 <= ms <= 12 and 1 <= me <= 12 and ms <= me):
        raise HTTPError(400, "validation", "The months must be 1 to 12 and the last cannot be before the first.")
    st = b.get("status") or "planned"; g = b.get("grade") or None
    if st not in STATUS_PLAN or (g and g not in GRADES):
        raise HTTPError(400, "validation", "Check the status and the grade (G, S, LS or U).")
    if g and st not in ("reporting", "closed"):
        raise HTTPError(400, "validation", "A grade is given when the engagement is at reporting or closed.")
    return title, yr, ms, me, st, g


@router.route("POST", "/api/audit/plan")
def plan_add(req):
    c = need(req, "audit_workspace", "create"); b = req.json(); title, yr, ms, me, st, g = _plan_fields(b); rid = int(b["risk_id"]) if b.get("risk_id") else None
    pid = req.db.execute("INSERT INTO audit_plan(year,title,area,risk_id,scope,month_start,month_end,lead,status,grade,report_date,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (yr, title, str(b.get("area") or "")[:120], rid, str(b.get("scope") or "")[:600], ms, me, str(b.get("lead") or "")[:100], st, g, b.get("report_date") or None, c.user["username"], now())).lastrowid
    req.db.execute("UPDATE audit_plan SET ref=? WHERE id=?", ("AUD-%d-%02d" % (yr, pid % 100), pid)); audit_log(req.db, "audit.plan_add", c.user, "audit_workspace", "Engagement '%s' planned for %d" % (title, yr), req.ip)
    return {"id": pid}


@router.route("PUT", "/api/audit/plan/<int:pid>")
def plan_edit(req):
    pid = int(req.params["pid"])
    c = need(req, "audit_workspace", "edit"); b = req.json(); e = req.db.execute("SELECT * FROM audit_plan WHERE id=? AND deleted_at IS NULL", (pid,)).fetchone()
    if not e:
        raise HTTPError(404, "not_found", "Engagement not found.")
    title, yr, ms, me, st, g = _plan_fields(dict(dict(e), **b))
    if st == "closed" and req.db.execute("SELECT 1 FROM audit_findings WHERE engagement_id=? AND deleted_at IS NULL AND status IN ('open','responded') AND priority='High'", (pid,)).fetchone() and g in ("G", "S"):
        raise HTTPError(409, "grade", "High-priority findings are still open, so the engagement cannot be graded Good or Satisfactory.")
    req.db.execute("UPDATE audit_plan SET year=?, title=?, area=?, risk_id=?, scope=?, month_start=?, month_end=?, lead=?, status=?, grade=?, report_date=?, updated_at=? WHERE id=?", (yr, title, str(b.get("area", e["area"]) or "")[:120], int(b["risk_id"]) if b.get("risk_id") else e["risk_id"], str(b.get("scope", e["scope"]) or "")[:600], ms, me, str(b.get("lead", e["lead"]) or "")[:100], st, g, b.get("report_date", e["report_date"]), now(), pid))
    audit_log(req.db, "audit.plan_edit", c.user, "audit_workspace", "Engagement '%s' now %s%s" % (title, st, " graded %s" % g if g else ""), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/audit/plan/<int:pid>")
def plan_del(req):
    pid = int(req.params["pid"])
    c = need(req, "audit_workspace", "delete")
    if req.db.execute("SELECT 1 FROM audit_findings WHERE engagement_id=? AND deleted_at IS NULL", (pid,)).fetchone():
        raise HTTPError(409, "in_use", "The engagement has findings: it cannot be removed.")
    req.db.execute("UPDATE audit_plan SET deleted_at=? WHERE id=?", (now(), pid)); audit_log(req.db, "audit.plan_del", c.user, "audit_workspace", "Engagement #%d removed" % pid, req.ip)
    return {"ok": True}


def _finding_fields(b):
    title = need_str(b, "title", "Finding", 200); pr = b.get("priority") or "Medium"
    if pr not in PRIORITY:
        raise HTTPError(400, "validation", "Priority is High, Medium or Low.")
    due = need_str(b, "due_date", "Due date", 10)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
        raise HTTPError(400, "validation", "The due date must look like 2026-12-31.")
    return title, pr, due


@router.route("POST", "/api/audit/findings")
def finding_add(req):
    c = need(req, "audit_workspace", "create"); b = req.json(); title, pr, due = _finding_fields(b); owner = need_str(b, "owner_name", "Owner", 120)
    rid = int(b["risk_id"]) if b.get("risk_id") else None; kid = int(b["control_id"]) if b.get("control_id") else None; eid = int(b["engagement_id"]) if b.get("engagement_id") else None
    if rid and not req.db.execute("SELECT 1 FROM risks WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone():
        raise HTTPError(400, "validation", "That risk does not exist.")
    if kid and not req.db.execute("SELECT 1 FROM risk_controls WHERE id=?", (kid,)).fetchone():
        raise HTTPError(400, "validation", "That control does not exist.")
    if not rid and not eid:
        raise HTTPError(400, "validation", "Link the finding to a risk or to an engagement.")
    u = req.db.execute("SELECT id FROM users WHERE status='active' AND deleted_at IS NULL AND (lower(full_name)=lower(?) OR lower(job_title)=lower(?) OR lower(username)=lower(?))", (owner, owner, owner)).fetchone()
    fid = req.db.execute("INSERT INTO audit_findings(engagement_id,title,condition_text,criteria,cause,effect,recommendation,priority,risk_id,control_id,owner_name,owner_id,due_date,created_by,created_by_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (eid, title, str(b.get("condition_text") or "")[:1500], str(b.get("criteria") or "")[:800], str(b.get("cause") or "")[:800], str(b.get("effect") or "")[:800], str(b.get("recommendation") or "")[:1000], pr, rid, kid, owner, u["id"] if u else None, due, c.user["username"], c.user["id"], now())).lastrowid
    req.db.execute("UPDATE audit_findings SET ref=? WHERE id=?", ("AF-%04d" % fid, fid)); audit_log(req.db, "audit.finding_add", c.user, "audit_workspace", "Finding AF-%04d raised (%s priority) for %s" % (fid, pr, owner), req.ip)
    return {"id": fid, "ref": "AF-%04d" % fid}


@router.route("PUT", "/api/audit/findings/<int:fid>")
def finding_edit(req):
    fid = int(req.params["fid"])
    c = need(req, "audit_workspace", "edit"); f = req.db.execute("SELECT * FROM audit_findings WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone()
    if not f or f["status"] == "closed":
        raise HTTPError(409 if f else 404, "state", "Finding not found or already closed.")
    b = dict(dict(f), **req.json()); title, pr, due = _finding_fields(b)
    req.db.execute("UPDATE audit_findings SET title=?, condition_text=?, criteria=?, cause=?, effect=?, recommendation=?, priority=?, due_date=?, owner_name=? WHERE id=?", (title, str(b.get("condition_text") or "")[:1500], str(b.get("criteria") or "")[:800], str(b.get("cause") or "")[:800], str(b.get("effect") or "")[:800], str(b.get("recommendation") or "")[:1000], pr, due, str(b.get("owner_name") or f["owner_name"])[:120], fid))
    audit_log(req.db, "audit.finding_edit", c.user, "audit_workspace", "Finding %s edited" % f["ref"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/audit/findings/<int:fid>/respond")
def finding_respond(req):
    fid = int(req.params["fid"])
    """The owner's management response, with an optional action. Allowed to the finding's owner (or an auditor on their behalf)."""
    c = need(req, "audit_workspace", "view"); f = req.db.execute("SELECT * FROM audit_findings WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone(); b = req.json()
    if not f:
        raise HTTPError(404, "not_found", "Finding not found.")
    if not (is_owner(req.db, c.user, f) or "edit" in c.perms.get("audit_workspace", set())):
        raise HTTPError(403, "forbidden", "Only the owner of the finding, or the audit team, can respond.")
    if f["status"] == "closed":
        raise HTTPError(409, "state", "The finding is closed.")
    resp = need_str(b, "response", "Response", 1500)
    if len(resp) < 15:
        raise HTTPError(400, "validation", "Write the management response in a sentence or two: what will be done, by whom, by when.")
    ref = None
    if b.get("create_action"):
        due = str(b.get("action_due") or f["due_date"])
        out = p5.make_action(req.db, c, {"title": "Audit %s: %s" % (f["ref"], f["title"])[:200], "description": resp[:600], "owner_name": f["owner_name"], "due_date": due, "risk_id": f["risk_id"], "control_id": f["control_id"], "source": "manual", "priority": "High" if f["priority"] == "High" else "Medium"}); ref = out["ref"]
    req.db.execute("UPDATE audit_findings SET status='responded', response=?, response_by=?, response_at=?, action_ref=COALESCE(?, action_ref) WHERE id=?", (resp, c.user["full_name"], now(), ref, fid))
    audit_log(req.db, "audit.finding_respond", c.user, "audit_workspace", "Management response to %s%s" % (f["ref"], " with action " + ref if ref else ""), req.ip)
    return {"ok": True, "action": ref}


@router.route("POST", "/api/audit/findings/<int:fid>/close")
def finding_close(req):
    fid = int(req.params["fid"])
    c = need(req, "audit_workspace", "approve"); f = req.db.execute("SELECT * FROM audit_findings WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone(); note = need_str(req.json(), "note", "Verification note", 600)
    if not f:
        raise HTTPError(404, "not_found", "Finding not found.")
    if f["status"] != "responded":
        raise HTTPError(409, "state", "The owner must respond before the finding can be closed.")
    if is_owner(req.db, c.user, f):
        raise HTTPError(403, "separation", "The owner of a finding cannot close it: another auditor verifies the evidence.")
    req.db.execute("UPDATE audit_findings SET status='closed', closed_by=?, closed_at=?, close_note=? WHERE id=?", (c.user["full_name"], now(), note, fid)); audit_log(req.db, "audit.finding_close", c.user, "audit_workspace", "Finding %s closed after verification" % f["ref"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/audit/findings/<int:fid>/reopen")
def finding_reopen(req):
    fid = int(req.params["fid"])
    c = need(req, "audit_workspace", "approve"); f = req.db.execute("SELECT * FROM audit_findings WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone(); note = need_str(req.json(), "note", "Reason", 400)
    if not f or f["status"] == "open":
        raise HTTPError(409 if f else 404, "state", "Finding not found or already open.")
    req.db.execute("UPDATE audit_findings SET status='open', closed_by=NULL, closed_at=NULL, close_note=? WHERE id=?", ("Reopened by %s: %s" % (c.user["full_name"], note), fid)); audit_log(req.db, "audit.finding_reopen", c.user, "audit_workspace", "Finding %s reopened: %s" % (f["ref"], note), req.ip)
    return {"ok": True}


@router.route("GET", "/api/audit/focus")
def focus_get(req):
    c = need(req, "audit_workspace", "view")
    return {"focus": focus(req.db, c, dbm.today()), "note": "Suggestions from risk ratings, control strength, failed tests, indicators and overdue actions, with no audit work in the last two years. The audit team builds the plan."}


@router.route("POST", "/api/audit/draft")
def draft_post(req):
    c = need(req, "audit_workspace", "create"); b = req.json()
    return draft(req.db, c, int(b.get("risk_id") or 0), int(b["control_id"]) if b.get("control_id") else None)


@router.route("GET", "/api/audit/risks")
def risks_list(req):
    c = need(req, "audit_workspace", "view"); rows, _ = analytics.risk_rows(req.db, c)
    return {"risks": [{"id": r["id"], "ref": r["source_ref"] or r["ref"], "title": r["title"][:90]} for r in rows], "controls": []}


@router.route("GET", "/api/audit/risks/<int:rid>/controls")
def risk_controls(req):
    rid = int(req.params["rid"])
    need(req, "audit_workspace", "view")
    return {"controls": [{"id": k["id"], "ref": k["ref"], "statement": (k["statement"] or "")[:100], "domain": k["domain"]} for k in req.db.execute("SELECT id, ref, statement, domain, ice FROM risk_controls WHERE risk_id=? ORDER BY ice IS NULL, ice DESC LIMIT 60", (rid,))]}


@router.route("GET", "/api/audit/export.xlsx")
def export(req):
    c = need(req, "audit_workspace", "export"); today = dbm.today()
    s1 = [[("Audit plan", 3)], [], [(h, 1) for h in ("Ref", "Year", "Engagement", "Area", "Months", "Lead", "Status", "Grade")]] + [[e["ref"], e["year"], e["title"], e["area"] or "", "%d-%d" % (e["month_start"], e["month_end"]), e["lead"] or "", e["status"], GRADES.get(e["grade"], "")] for e in req.db.execute("SELECT * FROM audit_plan WHERE deleted_at IS NULL ORDER BY year, month_start")]
    s2 = [[("Audit findings", 3)], [], [(h, 1) for h in ("Ref", "Finding", "Priority", "Risk", "Owner", "Due", "Status", "Days open", "Overdue", "Response", "Verification")]]
    for f in req.db.execute("SELECT * FROM audit_findings WHERE deleted_at IS NULL ORDER BY id"):
        v = fin_view(req.db, f, today); s2.append([f["ref"], f["title"], f["priority"], v["risk"] or "", f["owner_name"], f["due_date"], f["status"], v["age_days"], "yes" if v["overdue"] else "", f["response"] or "", f["close_note"] or ""])
    s3 = [[("Assurance coverage by strategic objective", 3)], [], [(h, 1) for h in ("Objective", "Risks", "First line (controls attested in 12 months)", "Second line (risks assessed in 12 months)", "Third line (audit engagements, 24 months)", "Open findings", "Level of assurance", "Assurance after open findings")]]
    for x in coverage(req.db, c, today):
        s3.append(["%s - %s" % (x["code"], x["name"]), x["risks"], x["line1"], x["line2"], x["line3"], x["open_findings"], x["loa"], x["loa_adjusted"]])
    return xlsx_response(xlsxbook.write([("Plan", s1, [16, 7, 50, 28, 9, 22, 12, 24]), ("Findings", s2, [11, 60, 10, 40, 24, 12, 11, 10, 9, 60, 50]), ("Coverage", s3, [48, 8, 26, 26, 26, 12, 14, 18])]), "Sentinel_audit_workspace.xlsx")
