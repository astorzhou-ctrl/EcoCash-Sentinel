"""Data quality: makes the risk assessment workbook and the control taxonomy agree, and says exactly what it changed.
Preview first, then apply: every change is logged old -> new so a batch can be undone. The taxonomy is the master for what a control is (its category,
statement and ICE factor); controls used in a risk but missing from the taxonomy are added to it as risk-specific controls; text damaged by a global
find-and-replace is repaired; a control with no owner takes its department from the same control elsewhere or from the risk owner."""
import json
import re
import secrets
from collections import Counter

from . import depts, textfix
from .api import router, need
from .core import audit, now
from .web import HTTPError

PREFIX = {"PEO": "People", "PRO": "Process", "SYS": "Systems", "TEC": "Technology", "TLS": "Tools"}
KINDS = ("text", "category", "statement", "ice", "missing")
RISK_TEXT = ("title", "description", "root_cause", "implication", "treatment", "objective", "strategic_objective", "owner_name")


def code_category(ref):
    parts = (ref or "").split("-")
    if len(parts) >= 2 and re.match(r"^[A-Z]{3}$", parts[-2]) and parts[-1].isdigit():
        return PREFIX.get(parts[-2])
    if len(parts) == 2 and parts[0] in PREFIX and parts[1].isdigit():
        return PREFIX[parts[0]]
    return None


def poor_statement(st, ref):
    s = (st or "").strip()
    return not s or s == ref or s.startswith("Treatment added") or s.startswith("ICE was")


def catalog(db):
    return {r["ref"]: r for r in db.execute("SELECT * FROM control_catalog WHERE kind='p2st2'")}


def controls(db):
    return db.execute("SELECT k.id, k.risk_id, k.ref, k.statement, k.domain, k.ice, k.ice_source, k.owner, r.source_ref, r.owner_name FROM risk_controls k JOIN risks r ON r.id=k.risk_id WHERE r.deleted_at IS NULL AND (r.is_sample IS NULL OR r.is_sample=0)").fetchall()


def scan(db):
    cat, rows = catalog(db), controls(db)
    out = {"catalog_loaded": bool(cat), "kinds": {}, "examples": {}}
    # 1. text damaged by find-and-replace
    n, ex = 0, []
    for r in db.execute("SELECT id, source_ref, " + ", ".join(RISK_TEXT) + " FROM risks WHERE deleted_at IS NULL"):
        for f in RISK_TEXT:
            if textfix.damaged(r[f]):
                n += 1
                if len(ex) < 4: ex.append("%s %s: %s" % (r["source_ref"] or r["id"], f, textfix.repair(r[f])[:70]))
    for r in rows:
        for f in ("statement", "owner"):
            if textfix.damaged(r[f]):
                n += 1
    for r in db.execute("SELECT s.name, s.grid FROM wb_sheets s JOIN wb_store w ON w.id=s.store_id WHERE w.deleted_at IS NULL"):
        g = json.loads(r["grid"]); k = sum(1 for row in g for c in row if textfix.damaged(c))
        if k:
            n += k
            if len(ex) < 6: ex.append("sheet %s: %d damaged words" % (r["name"], k))
    out["kinds"]["text"] = n; out["examples"]["text"] = ex
    # 2-5. controls against the taxonomy
    if cat:
        miss, catc, stm, ice, exm = [], [], [], [], {"missing": [], "category": [], "statement": [], "ice": []}
        for k in rows:
            c = cat.get(k["ref"])
            if c is None:
                miss.append(k); exm["missing"].append(k["ref"]) if len(exm["missing"]) < 4 else None
                continue
            if k["domain"] != c["category"]:
                catc.append(k); exm["category"].append("%s: %s -> %s" % (k["ref"], k["domain"], c["category"])) if len(exm["category"]) < 4 else None
            if poor_statement(k["statement"], k["ref"]) and c["statement"] and not poor_statement(c["statement"], k["ref"]):
                stm.append(k)
            if k["ice"] is not None and c["ice"] is not None and abs(k["ice"] - c["ice"]) > 1e-9 and (k["ice_source"] or "self") != "test":
                ice.append(k); exm["ice"].append("%s: %s -> %s" % (k["ref"], k["ice"], c["ice"])) if len(exm["ice"]) < 4 else None
        # a control not in the taxonomy whose own code says another category than the sheet
        for k in miss:
            pc = code_category(k["ref"])
            if pc and pc != k["domain"]:
                catc.append(k); exm["category"].append("%s: %s -> %s" % (k["ref"], k["domain"], pc)) if len(exm["category"]) < 4 else None
        out["kinds"].update({"missing": len({k["ref"] for k in miss}), "category": len(catc), "statement": len(stm), "ice": len(ice)}); out["examples"].update({k: v for k, v in exm.items()})
        out["reconcile"] = reconcile(db, cat, rows)
        refs = {k["ref"] for k in rows}; tax = {r for r, c in cat.items() if (c["origin"] or "taxonomy") == "taxonomy"}
        out["reconcile_totals"] = {"taxonomy": len(tax), "risk_specific": len([r for r, c in cat.items() if c["origin"] == "risk"]), "links": len(rows), "distinct_used": len(refs), "used_from_taxonomy": len(refs & tax), "not_used": len(tax - refs), "not_in_catalogue": len([r for r in refs if r not in cat])}
    # departments
    rd = depts.ref_departments([(k["owner"], k["ref"]) for k in rows]); why = Counter(depts.dept_for_control(k["owner"], k["ref"], rd, k["owner_name"])[1] for k in rows)
    out["departments"] = dict(why)
    # workbook conflicts that are explained rather than changed
    lor = 0
    for r in db.execute("SELECT lor, wb_detail FROM risks WHERE deleted_at IS NULL AND wb_detail IS NOT NULL AND assess_source LIKE 'workbook%'"):
        sl = (json.loads(r["wb_detail"]) or {}).get("sheet_lor")
        if sl is not None and r["lor"] is not None and abs(sl - r["lor"]) > 0.005:
            lor += 1
    out["lor_disagreements"] = lor
    integ = integration_issues(db); out["integration"] = len(integ); out["examples"]["integration"] = [i["note"] for i in integ[:3]]
    return out


def reconcile(db, cat, rows):
    """Taxonomy against the controls the risks use, by P2ST2 category: why the counts differ and that they reconcile."""
    out = []
    used = Counter(); used_refs = {}
    for k in rows:
        used_refs.setdefault(k["domain"], set()).add(k["ref"])
        used[k["domain"]] += 1
    for d in ("People", "Process", "Systems", "Technology", "Tools"):
        tax = {r for r, c in cat.items() if c["category"] == d and (c["origin"] or "taxonomy") == "taxonomy"}
        risk_specific = {r for r, c in cat.items() if c["category"] == d and c["origin"] == "risk"}
        refs = used_refs.get(d, set())
        out.append({"category": d, "taxonomy": len(tax), "links": used[d], "distinct_used": len(refs), "used_from_taxonomy": len(refs & tax), "risk_specific": len(risk_specific), "not_used": len(tax - refs), "not_in_catalogue": len([r for r in refs if r not in cat])})
    return out


def stored_grid(db, name):
    r = db.execute("SELECT s.grid FROM wb_sheets s JOIN wb_store w ON w.id=s.store_id WHERE w.kind='risk' AND w.deleted_at IS NULL AND s.name=? ORDER BY w.id DESC LIMIT 1", (name,)).fetchone()
    return json.loads(r["grid"]) if r else None


def integration_issues(db):
    """Integration rows whose Objective ID contradicts their System (for example 'ISMS 07' on a BCMS row), with the risk the objective text belongs to."""
    g = stored_grid(db, "Integration")
    if not g:
        return []
    ids = {}
    for r in db.execute("SELECT source_ref, objective FROM risks WHERE deleted_at IS NULL AND source_ref IS NOT NULL"):
        ids[re.sub(r"^\S+\s*\d+\s*[-\u2013]?\s*", "", r["objective"] or "").strip().lower()[:50]] = r["source_ref"]
    out = []
    for i, row in enumerate(g):
        if len(row) > 3 and isinstance(row[1], str) and isinstance(row[2], str) and re.match(r"^(ISMS|BCMS)\s*\d+$", row[1].strip()) and row[2].strip() in ("ISMS", "BCMS") and not row[1].strip().startswith(row[2].strip()):
            guess = ids.get(re.sub(r"\s+", " ", str(row[3] or "")).strip().lower()[:50])
            out.append({"row": i, "was": row[1], "system": row[2], "should": guess if guess and guess.startswith(row[2].strip()) else None, "note": "Integration row %d: Objective ID %s but System %s" % (i + 1, row[1], row[2]) + (" (the objective text belongs to %s)" % guess if guess else "")})
    return out


def _log(db, batch, user, kind, tbl, rid, field, old, new):
    db.execute("INSERT INTO dq_fixes(batch,ts,username,kind,tbl,row_id,field,old,new) VALUES(?,?,?,?,?,?,?,?,?)", (batch, now(), user["username"] if user else "system", kind, tbl, rid, field, None if old is None else str(old), None if new is None else str(new)))


def apply(db, user, kinds, ip=""):
    kinds = [k for k in kinds if k in KINDS or k == "integration"]
    batch = secrets.token_hex(6); done = Counter(); cat = catalog(db)
    if "text" in kinds:
        for r in db.execute("SELECT id, " + ", ".join(RISK_TEXT) + " FROM risks WHERE deleted_at IS NULL").fetchall():
            for f in RISK_TEXT:
                nv = textfix.repair(r[f])
                if nv != r[f]:
                    db.execute("UPDATE risks SET %s=? WHERE id=?" % f, (nv, r["id"])); _log(db, batch, user, "text", "risks", r["id"], f, r[f], nv); done["text"] += 1
        for r in db.execute("SELECT id, statement, owner FROM risk_controls").fetchall():
            for f in ("statement", "owner"):
                nv = textfix.repair(r[f])
                if nv != r[f]:
                    db.execute("UPDATE risk_controls SET %s=? WHERE id=?" % f, (nv, r["id"])); _log(db, batch, user, "text", "risk_controls", r["id"], f, r[f], nv); done["text"] += 1
        for r in db.execute("SELECT store_id, name, grid FROM wb_sheets").fetchall():
            g = json.loads(r["grid"]); ng = textfix.repair_grid(g)
            if ng != g:
                k = sum(1 for a, b in zip(g, ng) for x, y in zip(a, b) if x != y)
                db.execute("UPDATE wb_sheets SET grid=? WHERE store_id=? AND name=?", (json.dumps(ng), r["store_id"], r["name"])); _log(db, batch, user, "text", "wb_sheets:%d:%s" % (r["store_id"], r["name"]), None, "grid", r["grid"], json.dumps(ng)); done["text"] += k
    if cat:
        rows = controls(db)
        if "missing" in kinds:
            for k in rows:
                if k["ref"] and k["ref"] not in cat:
                    c = code_category(k["ref"]) or k["domain"]; st = k["ref"] if not re.match(r"^[A-Z]{2}\d{2}-[A-Z]{3}-\d{3}$", k["ref"]) else ""
                    db.execute("INSERT OR IGNORE INTO control_catalog(kind,category,ref,statement,ice,theme,origin) VALUES('p2st2',?,?,?,?,NULL,'risk')", (c, k["ref"], st, k["ice"])); _log(db, batch, user, "missing", "control_catalog", None, "ref", None, k["ref"]); done["missing"] += 1
            cat = catalog(db)
        for k in rows:
            c = cat.get(k["ref"])
            if c is None:
                continue
            if "category" in kinds and k["domain"] != c["category"]:
                db.execute("UPDATE risk_controls SET domain=? WHERE id=?", (c["category"], k["id"])); _log(db, batch, user, "category", "risk_controls", k["id"], "domain", k["domain"], c["category"]); done["category"] += 1
            if "statement" in kinds and poor_statement(k["statement"], k["ref"]) and c["statement"] and not poor_statement(c["statement"], k["ref"]):
                db.execute("UPDATE risk_controls SET statement=? WHERE id=?", (c["statement"], k["id"])); _log(db, batch, user, "statement", "risk_controls", k["id"], "statement", k["statement"], c["statement"]); done["statement"] += 1
            if "ice" in kinds and k["ice"] is not None and c["ice"] is not None and abs(k["ice"] - c["ice"]) > 1e-9 and (k["ice_source"] or "self") != "test":
                db.execute("UPDATE risk_controls SET ice=? WHERE id=?", (c["ice"], k["id"])); _log(db, batch, user, "ice", "risk_controls", k["id"], "ice", k["ice"], c["ice"]); done["ice"] += 1
        # a control whose own code names another category than the sheet, but which is not in the taxonomy
        if "category" in kinds:
            for k in controls(db):
                pc = code_category(k["ref"])
                if pc and k["ref"] not in cat and pc != k["domain"]:
                    db.execute("UPDATE risk_controls SET domain=? WHERE id=?", (pc, k["id"])); _log(db, batch, user, "category", "risk_controls", k["id"], "domain", k["domain"], pc); done["category"] += 1
    if "integration" in kinds or "text" in kinds:
        for it in integration_issues(db):
            if it["should"]:
                for r in db.execute("SELECT s.store_id, s.name, s.grid FROM wb_sheets s JOIN wb_store w ON w.id=s.store_id WHERE s.name='Integration' AND w.deleted_at IS NULL").fetchall():
                    g = json.loads(r["grid"])
                    if g[it["row"]][1] == it["was"]:
                        g[it["row"]][1] = it["should"]; db.execute("UPDATE wb_sheets SET grid=? WHERE store_id=? AND name='Integration'", (json.dumps(g), r["store_id"])); _log(db, batch, user, "integration", "wb_sheets:%d:Integration" % r["store_id"], it["row"], "Objective ID", it["was"], it["should"]); done["integration"] += 1
    audit(db, "dq.apply", user, "risk_register", "Data quality fixes applied (batch %s): %s" % (batch, ", ".join("%s %d" % (k, v) for k, v in done.items()) or "nothing to change"), ip)
    return {"batch": batch, "done": dict(done)}


def revert(db, user, batch, ip=""):
    rows = db.execute("SELECT * FROM dq_fixes WHERE batch=? AND reverted_at IS NULL ORDER BY id DESC", (batch,)).fetchall()
    if not rows:
        raise HTTPError(404, "not_found", "Nothing to undo for that batch.")
    for r in rows:
        if r["tbl"] == "control_catalog":
            db.execute("DELETE FROM control_catalog WHERE kind='p2st2' AND ref=? AND origin='risk'", (r["new"],))
        elif r["tbl"].startswith("wb_sheets:"):
            _, sid, name = r["tbl"].split(":", 2)
            if r["field"] == "grid":
                db.execute("UPDATE wb_sheets SET grid=? WHERE store_id=? AND name=?", (r["old"], int(sid), name))
            else:
                g = json.loads(db.execute("SELECT grid FROM wb_sheets WHERE store_id=? AND name=?", (int(sid), name)).fetchone()["grid"]); g[r["row_id"]][1] = r["old"]; db.execute("UPDATE wb_sheets SET grid=? WHERE store_id=? AND name=?", (json.dumps(g), int(sid), name))
        else:
            val = float(r["old"]) if r["field"] == "ice" and r["old"] is not None else r["old"]
            db.execute("UPDATE %s SET %s=? WHERE id=?" % (r["tbl"], r["field"]), (val, r["row_id"]))
        db.execute("UPDATE dq_fixes SET reverted_at=? WHERE id=?", (now(), r["id"]))
    audit(db, "dq.revert", user, "risk_register", "Data quality batch %s undone (%d changes)" % (batch, len(rows)), ip)
    return {"reverted": len(rows)}


@router.route("GET", "/api/dq/scan")
def dq_scan(req):
    c = need(req, "risk_register", "view")
    out = scan(req.db); out["batches"] = [dict(r) for r in req.db.execute("SELECT batch, MIN(ts) ts, MIN(username) username, COUNT(*) n, SUM(reverted_at IS NOT NULL) reverted FROM dq_fixes GROUP BY batch ORDER BY MIN(id) DESC LIMIT 8")]
    out["can_fix"] = "edit" in c.perms.get("risk_register", set())
    return out


@router.route("POST", "/api/dq/apply")
def dq_apply(req):
    c = need(req, "risk_register", "edit")
    kinds = req.json().get("kinds") or []
    if not isinstance(kinds, list) or not kinds:
        raise HTTPError(400, "validation", "Choose what to fix.")
    return apply(req.db, c.user, kinds, req.ip)


@router.route("POST", "/api/dq/revert")
def dq_revert(req):
    c = need(req, "risk_register", "edit")
    return revert(req.db, c.user, str(req.json().get("batch") or ""), req.ip)
