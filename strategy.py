"""Strategy Map (BRD 9.4): how the strategic objectives are exposed to risk, on the Balanced Scorecard perspectives.
Objectives come from the register's own strategic objectives (the seven SOs in the workbook) and are completed here with a perspective, an owner and linked KPIs.
Rules: each risk belongs to exactly one objective; an objective with no risk, or with a risk outside appetite, or with a KPI off target, is flagged."""
import json
import re

from . import ai, analytics, matrix as mx, p2, register, xlsxbook
from .api import router, need, need_str
from .core import audit, now
from .p2 import xlsx_response
from .web import HTTPError

PERSPECTIVES = ["Financial", "Customer", "Internal process", "Learning and growth"]
KEYMAP = [("business performance", "Financial"), ("customer", "Customer"), ("stakeholder", "Customer"), ("risk and compliance", "Internal process"), ("innovation", "Learning and growth"), ("people", "Learning and growth"), ("organi", "Learning and growth")]
LEVEL_ORDER = {"Low": 1, "Medium": 2, "Significant": 3, "High": 4}


def split_so(s):
    m = re.match(r"^\s*(SO\s*\d+)\s*[-\u2013:]?\s*(.*)$", s or "", re.I)
    return (re.sub(r"\s+", " ", m.group(1).upper()), m.group(2).strip() or s.strip()) if m else (None, (s or "").strip())


def label(o):
    return "%s - %s" % (o["code"], o["name"])


def ensure(db):
    """Creates an objective for every strategic objective the register uses and that has none yet. The perspective is a proposal the Head of Risk confirms."""
    have = {split_so(label(o))[0] or o["name"].lower() for o in db.execute("SELECT code, name FROM objectives")}; n = db.execute("SELECT COUNT(*) n FROM objectives").fetchone()["n"]
    for r in db.execute("SELECT DISTINCT strategic_objective so FROM risks WHERE deleted_at IS NULL AND (is_sample IS NULL OR is_sample=0) AND strategic_objective IS NOT NULL AND strategic_objective != '' ORDER BY 1"):
        code, name = split_so(r["so"])
        if (code or name.lower()) in have:
            continue
        persp = next((p for k, p in KEYMAP if k in name.lower()), "Internal process"); n += 1
        db.execute("INSERT INTO objectives(code,name,perspective,sort) VALUES(?,?,?,?)", (code or "OBJ %02d" % n, name, persp, n)); have.add(code or name.lower())


def objective_of(objs, so):
    code, name = split_so(so)
    for o in objs:
        if (code and o["code"] == code) or (not code and o["name"].lower() == name.lower()):
            return o
    return None


def kpi_state(db, kid):
    k = db.execute("SELECT * FROM kpis WHERE id=? AND active=1 AND deleted_at IS NULL", (kid,)).fetchone()
    if not k:
        return None
    rs = db.execute("SELECT value, period FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (kid,)).fetchone()
    return {"id": k["id"], "code": k["code"], "name": k["name"], "kind": k["kind"], "unit": k["unit"], "latest": rs["value"] if rs else None, "period": rs["period"] if rs else None, "status": p2.status_of(k, rs["value"]) if rs else None}


def build(db, c):
    ensure(db); rows, _ = analytics.risk_rows(db, c); objs = [dict(o) for o in db.execute("SELECT * FROM objectives WHERE active=1 ORDER BY sort, id")]
    by = {o["id"]: [] for o in objs}; unassigned = []
    for r in rows:
        o = objective_of(objs, r["so"] if r["so"] != "Unassigned" else "")
        item = {"id": r["id"], "ref": r["source_ref"] or r["ref"], "title": r["title"], "rank": mx.rank(r["res_l"], r["res_c"]) if r["res_l"] else None, "rrr": r["rrr"], "position": register.position(r), "owner": r["owner"], "dept": r["dept"]}
        item["level"] = mx.level(item["rank"]) if item["rank"] else None
        (by[o["id"]] if o else unassigned).append(item)
    out = {p: [] for p in PERSPECTIVES}
    for o in objs:
        rs = sorted(by[o["id"]], key=lambda z: -(z["rank"] or 0)); worst = rs[0]["rank"] if rs and rs[0]["rank"] else None
        kp = [s for s in (kpi_state(db, x["kpi_id"]) for x in db.execute("SELECT kpi_id FROM objective_kpis WHERE objective_id=?", (o["id"],))) if s]
        above = [r for r in rs if r["position"] in ("Above appetite", "Above tolerance")]; flags = []
        if not rs:
            flags.append("No risk is linked to this objective")
        if above:
            flags.append("%d risk(s) outside appetite" % len(above))
        off = [k for k in kp if k["status"] in ("red", "amber", "off")]
        if off:
            flags.append("%d KPI/KRI off target" % len(off))
        out.setdefault(o["perspective"], []).append({"id": o["id"], "code": o["code"], "name": o["name"], "perspective": o["perspective"], "owner": o["owner"], "description": o["description"], "target_text": o["target_text"], "risks": rs, "count": len(rs), "worst_rank": worst, "worst_level": mx.level(worst) if worst else None,
                                                    "sig_high": sum(1 for r in rs if r["level"] in ("Significant", "High")), "above": len(above), "kpis": kp, "kpis_off": len(off), "flags": flags, "kpi_ids": [k["id"] for k in kp]})
    flat = [o for p in PERSPECTIVES for o in out.get(p, [])]
    return {"perspectives": [{"name": p, "objectives": out.get(p, [])} for p in PERSPECTIVES], "unassigned": unassigned, "exposure": sorted([{"code": o["code"], "name": o["name"], "sig_high": o["sig_high"], "count": o["count"]} for o in flat], key=lambda z: -z["sig_high"]),
            "flagged": sum(1 for o in flat if o["flags"]), "objectives": len(flat), "risks": len(rows), "can_edit": "edit" in c.perms.get("strategy_map", set())}


@router.route("GET", "/api/strategy")
def strategy_get(req):
    c = need(req, "strategy_map", "view")
    return build(req.db, c)


@router.route("GET", "/api/strategy/kpis")
def strategy_kpis(req):
    need(req, "strategy_map", "view")
    return {"kpis": [dict(r) for r in req.db.execute("SELECT id, code, name, kind FROM kpis WHERE active=1 AND deleted_at IS NULL ORDER BY kind, name")]}


def _fields(req, b, o=None):
    name = need_str(b, "name", "Name", 120); persp = b.get("perspective")
    if persp not in PERSPECTIVES:
        raise HTTPError(400, "validation", "Choose one of the four perspectives.")
    return name, persp, str(b.get("owner") or "").strip()[:120], str(b.get("description") or "").strip()[:600], str(b.get("target_text") or "").strip()[:300]


def _link(db, oid, ids):
    db.execute("DELETE FROM objective_kpis WHERE objective_id=?", (oid,))
    for k in {int(i) for i in (ids or [])}:
        if db.execute("SELECT 1 FROM kpis WHERE id=? AND deleted_at IS NULL", (k,)).fetchone():
            db.execute("INSERT INTO objective_kpis(objective_id,kpi_id) VALUES(?,?)", (oid, k))


@router.route("POST", "/api/strategy/objectives")
def objective_add(req):
    c = need(req, "strategy_map", "create"); b = req.json(); name, persp, owner, desc, tgt = _fields(req, b); code = need_str(b, "code", "Code", 12).upper()
    if req.db.execute("SELECT 1 FROM objectives WHERE code=?", (code,)).fetchone():
        raise HTTPError(409, "duplicate", "An objective with that code exists.")
    oid = req.db.execute("INSERT INTO objectives(code,name,perspective,owner,description,target_text,sort) VALUES(?,?,?,?,?,?,(SELECT COALESCE(MAX(sort),0)+1 FROM objectives))", (code, name, persp, owner, desc, tgt)).lastrowid
    _link(req.db, oid, b.get("kpi_ids")); audit(req.db, "strategy.objective_add", c.user, "strategy_map", "Objective %s added" % code, req.ip)
    return {"id": oid}


@router.route("PUT", "/api/strategy/objectives/<int:oid>")
def objective_edit(req):
    oid = int(req.params["oid"])
    c = need(req, "strategy_map", "edit"); b = req.json(); o = req.db.execute("SELECT * FROM objectives WHERE id=?", (oid,)).fetchone()
    if not o:
        raise HTTPError(404, "not_found", "Objective not found.")
    name, persp, owner, desc, tgt = _fields(req, b, o)
    if name != o["name"] and req.db.execute("SELECT 1 FROM risks WHERE strategic_objective=? AND deleted_at IS NULL", (label(o),)).fetchone():  # renaming would orphan the risks that carry the old label
        req.db.execute("UPDATE risks SET strategic_objective=? WHERE strategic_objective=?", ("%s - %s" % (o["code"], name), label(o)))
    req.db.execute("UPDATE objectives SET name=?, perspective=?, owner=?, description=?, target_text=? WHERE id=?", (name, persp, owner, desc, tgt, oid)); _link(req.db, oid, b.get("kpi_ids"))
    audit(req.db, "strategy.objective_edit", c.user, "strategy_map", "Objective %s updated (%s, owner %s)" % (o["code"], persp, owner or "none"), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/strategy/objectives/<int:oid>")
def objective_del(req):
    oid = int(req.params["oid"])
    c = need(req, "strategy_map", "delete"); o = req.db.execute("SELECT * FROM objectives WHERE id=?", (oid,)).fetchone()
    if not o:
        raise HTTPError(404, "not_found", "Objective not found.")
    if req.db.execute("SELECT 1 FROM risks WHERE strategic_objective=? AND deleted_at IS NULL", (label(o),)).fetchone():
        raise HTTPError(409, "in_use", "Risks are linked to this objective. Move them to another objective first.")
    req.db.execute("UPDATE objectives SET active=0 WHERE id=?", (oid,)); audit(req.db, "strategy.objective_remove", c.user, "strategy_map", "Objective %s removed" % o["code"], req.ip)
    return {"ok": True}


@router.route("PUT", "/api/strategy/risk/<int:rid>")
def risk_objective(req):
    rid = int(req.params["rid"])
    """Moves a risk to one objective (a risk belongs to exactly one)."""
    c = need(req, "risk_register", "edit"); code = need_str(req.json(), "code", "Objective", 12).upper()
    o = req.db.execute("SELECT * FROM objectives WHERE code=? AND active=1", (code,)).fetchone(); r = req.db.execute("SELECT id, ref, strategic_objective FROM risks WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone()
    if not o or not r:
        raise HTTPError(404, "not_found", "Objective or risk not found.")
    req.db.execute("UPDATE risks SET strategic_objective=?, updated_at=?, updated_by=? WHERE id=?", (label(o), now(), c.user["username"], rid))
    req.db.execute("INSERT INTO risk_history(risk_id,ts,user_id,username,action,changes) VALUES(?,?,?,?,?,?)", (rid, now(), c.user["id"], c.user["username"], "objective", json.dumps({"strategic_objective": [r["strategic_objective"], label(o)]})))
    return {"ok": True}


@router.route("GET", "/api/strategy/suggest")
def suggest(req):
    """Which objective a new risk probably belongs to: similarity of its words to the risks already under each objective. The person chooses."""
    c = need(req, "strategy_map", "view"); text = (req.query.get("text") or "").strip()
    if len(text) < 8:
        raise HTTPError(400, "validation", "Describe the risk in a few words.")
    ensure(req.db); b = build(req.db, c); objs = [o for p in b["perspectives"] for o in p["objectives"]]
    docs = [o["name"] + " " + " ".join(r["title"] for r in o["risks"]) for o in objs]; vecs, idf = ai.vectors(docs); q = ai.qvec(text, idf)
    sc = sorted(((ai.cos(q, v), o) for v, o in zip(vecs, objs)), key=lambda z: -z[0])
    return {"suggestions": [{"code": o["code"], "name": o["name"], "score": round(s, 2)} for s, o in sc[:3] if s > 0.02], "note": "A suggestion from the words of the risks already under each objective. You choose."}


@router.route("GET", "/api/strategy/export.xlsx")
def export(req):
    c = need(req, "strategy_map", "view"); b = build(req.db, c)
    s1 = [[("Strategy map: objective health", 3)], [], [(h, 1) for h in ("Perspective", "Objective", "Owner", "Risks", "Worst level", "Significant or High", "Outside appetite", "KPIs off target", "Flags")]]
    for p in b["perspectives"]:
        for o in p["objectives"]:
            s1.append([p["name"], "%s - %s" % (o["code"], o["name"]), o["owner"] or "", o["count"], o["worst_level"] or "none", o["sig_high"], o["above"], o["kpis_off"], "; ".join(o["flags"])])
    s2 = [[("Risks by objective", 3)], [], [(h, 1) for h in ("Objective", "Risk", "Title", "Level", "Position", "Owner")]]
    for p in b["perspectives"]:
        for o in p["objectives"]:
            for r in o["risks"]:
                s2.append([o["code"], r["ref"], r["title"], r["level"] or "", r["position"], r["owner"] or ""])
    return xlsx_response(xlsxbook.write([("Objective health", s1, [14, 40, 22, 8, 14, 14, 14, 14, 50]), ("Risks by objective", s2, [10, 12, 70, 14, 18, 28])]), "Sentinel_strategy_map.xlsx")
