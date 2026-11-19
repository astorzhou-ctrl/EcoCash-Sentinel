"""Workflow Designer (BRD 9.21): the Risk Office configures the lifecycles of the modules built on the kit without code: states, who may move a record, fields required for a move,
time limits (SLA) with an escalation role. Rules: every change is a new VERSION, published only after someone other than its author approves it; a record keeps the version it started on.
Lifecycles that Sentinel's own code enforces (audit findings, fraud cases, speak-up cases) are shown read-only, generated from that code, so they can be read and compared."""
import json
import re

from . import db as dbm, fraud, kit, speakup
from .api import router, need, need_str
from .core import audit, now
from .web import HTTPError

BUILTIN = {"audit_finding": ("Audit finding lifecycle", "Audit Workspace", {"open": ["responded"], "responded": ["closed", "open"], "closed": ["open"]}, "The owner responds; a different auditor verifies and closes."),
           "fraud_case": ("Fraud case lifecycle", "Fraud Intelligence", {k: list(v) for k, v in fraud.NEXT.items()}, "The outcome must be written down to confirm, close or mark a false positive."),
           "speakup_case": ("Speak-up case lifecycle", "Speak-Up Cases", {k: list(v) for k, v in speakup.NEXT.items()}, "Only the assigned officer moves a case; the outcome is recorded without the reporter's name.")}


def targets(db):
    out = []
    for key, (name, used, nxt, note) in BUILTIN.items():
        out.append({"target": "builtin/" + key, "name": name, "used_by": used, "builtin": True, "states": list(nxt), "version": 0, "published": False, "draft": False, "note": note})
    for module, s in kit.SPECS.items():
        if s.get("data_module") and s["data_module"] != module:
            continue
        for ent, e in s["entities"].items():
            if e.get("readonly"):
                continue
            tr = kit.transitions(db, module, ent); t = "%s.%s" % (module, ent)
            out.append({"target": "%s/%s" % (module, ent), "name": "%s: %s" % (s["title"], e["label"]), "used_by": s["title"], "builtin": False, "states": tr["states"], "version": tr["version"], "published": tr["published"], "draft": bool(db.execute("SELECT 1 FROM workflow_defs WHERE target=? AND status='draft'", (t,)).fetchone()), "note": ""})
    return out


def detail(db, module, entity):
    if module == "builtin":
        if entity not in BUILTIN:
            raise HTTPError(404, "not_found", "Unknown workflow.")
        name, used, nxt, note = BUILTIN[entity]
        return {"target": "builtin/" + entity, "name": name, "builtin": True, "note": note, "states": [{"name": s} for s in nxt], "transitions": [{"from": a, "to": b, "roles": []} for a, bs in nxt.items() for b in bs], "versions": [], "fields": [], "roles": []}
    s, e = kit.get_spec(module, entity); tr = kit.transitions(db, module, entity); target = "%s.%s" % (kit.dm(module), entity)
    vs = [{"version": r["version"], "status": r["status"], "created_by": r["created_by"], "created_at": r["created_at"], "approved_by": r["approved_by"], "approved_at": r["approved_at"], "note": r["note"], "states": json.loads(r["states"]), "transitions": json.loads(r["transitions"])} for r in db.execute("SELECT * FROM workflow_defs WHERE target=? ORDER BY version DESC", (target,))]
    if tr["published"]:
        w = next(v for v in vs if v["status"] == "published"); states, trans = w["states"], w["transitions"]
    else:
        nxt = e.get("next"); sts = e.get("statuses") or []; states = [{"name": x} for x in sts]; trans = [{"from": a, "to": b, "roles": []} for a in sts for b in (nxt.get(a, []) if nxt is not None else [x for x in sts if x != a])]
    return {"target": "%s/%s" % (module, entity), "name": "%s: %s" % (s["title"], e["label"]), "builtin": False, "published": tr["published"], "version": tr["version"], "states": states, "transitions": trans, "versions": vs, "fields": [f["key"] for f in e["fields"]], "roles": [r["name"] for r in db.execute("SELECT name FROM roles ORDER BY name")], "default_note": "" if tr["published"] else "This is the module's default lifecycle. Publish a version to replace it for new records."}


@router.route("GET", "/api/workflows")
def wf_list(req):
    c = need(req, "workflow_designer", "view")
    return {"me": c.user["username"], "workflows": targets(req.db), "can": {k: k in c.perms.get("workflow_designer", set()) for k in ("create", "edit", "approve")}}


@router.route("GET", "/api/workflows/<module>/<entity>")
def wf_get(req):
    need(req, "workflow_designer", "view")
    return detail(req.db, req.params["module"], req.params["entity"])


def check(db, module, entity, b):
    s, e = kit.get_spec(module, entity); states = b.get("states") or []; names = []
    if not isinstance(states, list) or not states or len(states) > 14:
        raise HTTPError(400, "validation", "Give between one and fourteen states.")
    roles = {r["name"] for r in db.execute("SELECT name FROM roles")}; fkeys = {f["key"] for f in e["fields"]}; clean_states = []
    for st in states:
        nm = str(st.get("name") or "").strip()[:30]
        if not nm or nm in names:
            raise HTTPError(400, "validation", "Each state needs a different name.")
        names.append(nm); sla = st.get("sla_hours"); sla = float(sla) if sla not in (None, "") else None
        if sla is not None and sla <= 0:
            raise HTTPError(400, "validation", "A time limit must be above zero hours.")
        esc_ = (st.get("escalate_to") or "").strip() or None
        if esc_ and esc_ not in roles:
            raise HTTPError(400, "validation", "Escalate to a role that exists: '%s' does not." % esc_)
        clean_states.append({"name": nm, "sla_hours": sla, "escalate_to": esc_})
    trans = []
    for t in b.get("transitions") or []:
        a, z = str(t.get("from") or ""), str(t.get("to") or "")
        if a not in names or z not in names or a == z:
            raise HTTPError(400, "validation", "Every move must go from one state to a different one, both in the list.")
        rl = [r for r in (t.get("roles") or []) if r]; bad = [r for r in rl if r not in roles]; rq = [r for r in (t.get("requires") or []) if r]; badf = [r for r in rq if r not in fkeys]
        if bad or badf:
            raise HTTPError(400, "validation", "Unknown %s: %s." % ("role" if bad else "field", ", ".join(bad or badf)))
        trans.append({"from": a, "to": z, "roles": rl, "requires": rq, "note": str(t.get("note") or "")[:200]})
    reach = {names[0]}; grew = True
    while grew:
        grew = False
        for t in trans:
            if t["from"] in reach and t["to"] not in reach:
                reach.add(t["to"]); grew = True
    if len(names) > 1 and set(names) - reach:
        raise HTTPError(400, "validation", "These states cannot be reached from the first state: %s." % ", ".join(sorted(set(names) - reach)))
    return clean_states, trans


@router.route("POST", "/api/workflows/<module>/<entity>/draft")
def wf_draft(req):
    c = need(req, "workflow_designer", "edit"); module, entity = req.params["module"], req.params["entity"]; b = req.json()
    if module == "builtin":
        raise HTTPError(409, "readonly", "This lifecycle is enforced by Sentinel's own code and cannot be changed here.")
    states, trans = check(req.db, module, entity, b); target = "%s.%s" % (kit.dm(module), entity); v = req.db.execute("SELECT COALESCE(MAX(version),0)+1 v FROM workflow_defs WHERE target=?", (target,)).fetchone()["v"]
    req.db.execute("DELETE FROM workflow_defs WHERE target=? AND status='draft' AND created_by=?", (target, c.user["username"]))  # one open draft per author
    req.db.execute("INSERT INTO workflow_defs(target,name,version,status,states,transitions,note,created_by,created_at) VALUES(?,?,?,'draft',?,?,?,?,?)", (target, target, v, json.dumps(states), json.dumps(trans), str(b.get("note") or "")[:300], c.user["username"], now()))
    audit(req.db, "workflow.draft", c.user, "workflow_designer", "Draft version %d of %s saved" % (v, target), req.ip)
    return {"version": v}


@router.route("POST", "/api/workflows/<module>/<entity>/approve")
def wf_approve(req):
    c = need(req, "workflow_designer", "approve"); module, entity = req.params["module"], req.params["entity"]; target = "%s.%s" % (kit.dm(module), entity); ver = int(req.json().get("version") or 0)
    w = req.db.execute("SELECT * FROM workflow_defs WHERE target=? AND version=? AND status='draft'", (target, ver)).fetchone()
    if not w:
        raise HTTPError(404, "not_found", "That draft does not exist.")
    if w["created_by"] == c.user["username"]:
        raise HTTPError(403, "separation", "You wrote this version, so someone else must approve it before it is published.")
    req.db.execute("UPDATE workflow_defs SET status='superseded' WHERE target=? AND status='published'", (target,)); req.db.execute("UPDATE workflow_defs SET status='published', approved_by=?, approved_at=? WHERE id=?", (c.user["username"], now(), w["id"]))
    audit(req.db, "workflow.publish", c.user, "workflow_designer", "Version %d of %s published (author %s)" % (ver, target, w["created_by"]), req.ip)
    return {"ok": True, "version": ver}


@router.route("POST", "/api/workflows/<module>/<entity>/discard")
def wf_discard(req):
    c = need(req, "workflow_designer", "edit"); target = "%s.%s" % (kit.dm(req.params["module"]), req.params["entity"]); ver = int(req.json().get("version") or 0)
    r = req.db.execute("DELETE FROM workflow_defs WHERE target=? AND version=? AND status='draft'", (target, ver)); audit(req.db, "workflow.discard", c.user, "workflow_designer", "Draft version %d of %s discarded" % (ver, target), req.ip)
    return {"ok": True}


@router.route("POST", "/api/workflows/<module>/<entity>/simulate")
def wf_sim(req):
    """Walks a path of states through a version (the draft if one is given) and says, for each move, who may make it and what must be filled in."""
    need(req, "workflow_designer", "view"); module, entity = req.params["module"], req.params["entity"]; b = req.json(); d = detail(req.db, module, entity); ver = b.get("version")
    src = next((v for v in d["versions"] if v["version"] == ver), None) if ver else None; states, trans = (src["states"], src["transitions"]) if src else (d["states"], d["transitions"]); path = b.get("path") or []; steps = []; cur = path[0] if path else (states[0]["name"] if states else None)
    for nxt in path[1:]:
        t = next((x for x in trans if x["from"] == cur and x["to"] == nxt), None); steps.append({"from": cur, "to": nxt, "allowed": bool(t), "roles": (t or {}).get("roles") or ["anyone with edit rights"], "requires": (t or {}).get("requires") or [], "sla": next((s.get("sla_hours") for s in states if s["name"] == nxt), None)})
        if not t:
            break
        cur = nxt
    return {"steps": steps, "ok": all(s["allowed"] for s in steps)}
