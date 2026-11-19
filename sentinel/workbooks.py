"""Saved workbooks: the risk assessment workbook and the control taxonomy workbook are kept as uploaded (with a fingerprint), the sheets of the risk workbook
are kept for the register tabs, and both can be downloaded, deleted to the Recycle Bin and restored. Deleting the risk workbook also removes the risks it
loaded (each goes to the Recycle Bin too, and one restore brings them all back)."""
import hashlib
import json

from . import risks as riskmod
from .api import router, need, need_str
from .core import audit, now
from .p2 import xlsx_response
from .web import HTTPError, Response

DAYS = 90


def _purge_at():
    import datetime
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_risk(db, user, data, name, parsed, summary):
    h = hashlib.sha256(data).hexdigest()
    sid = db.execute("INSERT INTO wb_store(kind,name,sha256,size,uploaded_by,uploaded_at,summary,data) VALUES('risk',?,?,?,?,?,?,?)", (name[:200], h, len(data), user["username"], now(), json.dumps({"risks": summary["found"], "controls": sum(len(r["controls"]) for r in parsed["risks"]), "emv_i": summary["emv_i"], "sheets": len(parsed["sheets"])}), data)).lastrowid
    for i, (n, g) in enumerate(parsed["sheets"].items()):
        db.execute("INSERT INTO wb_sheets(store_id,name,sort,grid) VALUES(?,?,?,?)", (sid, n, i, json.dumps(g)))
    return sid


def save_taxonomy(db, user, data, name, out):
    return db.execute("INSERT INTO wb_store(kind,name,sha256,size,uploaded_by,uploaded_at,summary,data) VALUES('taxonomy',?,?,?,?,?,?,?)", (name[:200], hashlib.sha256(data).hexdigest(), len(data), user["username"], now(), json.dumps({"p2st2": out["p2st2"], "annex": out["annex"]}), data)).lastrowid


@router.route("GET", "/api/workbooks")
def wb_list(req):
    c = need(req, "risk_register", "view")
    rows = [dict(id=r["id"], kind=r["kind"], name=r["name"], size=r["size"], sha=r["sha256"][:12], by=r["uploaded_by"], at=r["uploaded_at"], summary=json.loads(r["summary"] or "{}")) for r in req.db.execute("SELECT id,kind,name,size,sha256,uploaded_by,uploaded_at,summary FROM wb_store WHERE deleted_at IS NULL ORDER BY id DESC")]
    loaded = req.db.execute("SELECT COUNT(*) n FROM risks WHERE deleted_at IS NULL AND source_ref IS NOT NULL AND (is_sample IS NULL OR is_sample=0)").fetchone()["n"]
    cat = req.db.execute("SELECT COUNT(*) n FROM control_catalog").fetchone()["n"]
    return {"workbooks": rows, "loaded_risks": loaded, "catalog": cat, "can": {"delete": "delete" in c.perms.get("risk_register", set()), "export": "export" in c.perms.get("risk_register", set())}}


@router.route("GET", "/api/workbooks/<int:wid>/download")
def wb_download(req):
    c = need(req, "risk_register", "export")
    r = req.db.execute("SELECT * FROM wb_store WHERE id=? AND deleted_at IS NULL", (int(req.params["wid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Workbook not found.")
    audit(req.db, "workbook.download", c.user, "risk_register", "Saved workbook %s downloaded" % r["name"], req.ip)
    return Response(bytes(r["data"]), 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [("Content-Disposition", 'attachment; filename="%s"' % (r["name"] or "workbook.xlsx").replace('"', ""))])


@router.route("POST", "/api/workbooks/<int:wid>/delete")
def wb_delete(req):
    c = need(req, "risk_register", "delete")
    r = req.db.execute("SELECT * FROM wb_store WHERE id=? AND deleted_at IS NULL", (int(req.params["wid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Workbook not found.")
    why = need_str(req.json(), "reason", "Reason", 300)
    if len(why) < 10:
        raise HTTPError(400, "validation", "Give the reason (at least 10 characters).")
    payload, n = {}, 0
    if r["kind"] == "risk":
        ids = []
        for k in req.db.execute("SELECT id, ref, title FROM risks WHERE deleted_at IS NULL AND source_ref IS NOT NULL AND (is_sample IS NULL OR is_sample=0)").fetchall():
            req.db.execute("UPDATE risks SET deleted_at=?, deleted_by=?, delete_reason=? WHERE id=?", (now(), c.user["id"], "Risk workbook %s removed: %s" % (r["name"], why), k["id"]))
            rid = req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at) VALUES('risk',?,?,?,?,?,?,?,?)", (k["id"], "%s %s" % (k["ref"], k["title"][:80]), "risk_register", c.user["id"], c.user["full_name"], now(), "Risk workbook removed: " + why, _purge_at())).lastrowid
            ids.append([k["id"], rid]); n += 1
        payload = {"risks": ids}
    else:
        payload = {"catalog": [dict(x) for x in req.db.execute("SELECT kind, category, ref, statement, ice, theme, origin FROM control_catalog")]}; n = len(payload["catalog"])
        req.db.execute("DELETE FROM control_catalog")
    req.db.execute("UPDATE wb_store SET deleted_at=? WHERE id=?", (now(), r["id"]))
    req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at,payload) VALUES('workbook',?,?,?,?,?,?,?,?,?)", (r["id"], "%s workbook %s (%d %s)" % ("Risk assessment" if r["kind"] == "risk" else "Control taxonomy", r["name"], n, "risks" if r["kind"] == "risk" else "controls"), "risk_register", c.user["id"], c.user["full_name"], now(), why, _purge_at(), json.dumps(payload)))
    audit(req.db, "workbook.delete", c.user, "risk_register", "Workbook %s deleted to the Recycle Bin with %d %s: %s" % (r["name"], n, "risks" if r["kind"] == "risk" else "controls", why), req.ip)
    return {"removed": n, "kind": r["kind"]}


def restore(db, rec, user):
    """Called by the Recycle Bin when a 'workbook' item is restored."""
    w = db.execute("SELECT * FROM wb_store WHERE id=?", (rec["entity_id"],)).fetchone()
    p = json.loads(rec["payload"] or "{}")
    if w is not None:
        db.execute("UPDATE wb_store SET deleted_at=NULL WHERE id=?", (w["id"],))
    for rid, recid in p.get("risks", []):
        db.execute("UPDATE risks SET deleted_at=NULL, deleted_by=NULL, delete_reason=NULL WHERE id=?", (rid,))
        db.execute("UPDATE recycle SET restored_at=? WHERE id=?", (now(), recid))
    for x in p.get("catalog", []):
        db.execute("INSERT OR REPLACE INTO control_catalog(kind,category,ref,statement,ice,theme,origin) VALUES(?,?,?,?,?,?,?)", (x["kind"], x["category"], x["ref"], x["statement"], x["ice"], x["theme"], x["origin"]))


@router.route("POST", "/api/risks/delete-loaded")
def delete_loaded(req):
    """Delete every risk that was loaded from a workbook, without a saved workbook record (for installations that imported before workbooks were kept)."""
    c = need(req, "risk_register", "delete")
    why = need_str(req.json(), "reason", "Reason", 300)
    if len(why) < 10:
        raise HTTPError(400, "validation", "Give the reason (at least 10 characters).")
    n = 0
    for k in req.db.execute("SELECT id, ref, title FROM risks WHERE deleted_at IS NULL AND source_ref IS NOT NULL AND (is_sample IS NULL OR is_sample=0)").fetchall():
        req.db.execute("UPDATE risks SET deleted_at=?, deleted_by=?, delete_reason=? WHERE id=?", (now(), c.user["id"], "Loaded risks removed: " + why, k["id"]))
        req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at) VALUES('risk',?,?,?,?,?,?,?,?)", (k["id"], "%s %s" % (k["ref"], k["title"][:80]), "risk_register", c.user["id"], c.user["full_name"], now(), "Loaded risks removed: " + why, _purge_at())); n += 1
    audit(req.db, "risk.delete_loaded", c.user, "risk_register", "%d loaded risks deleted to the Recycle Bin: %s" % (n, why), req.ip)
    return {"removed": n}


@router.route("GET", "/api/register/sheet")
def register_sheet(req):
    need(req, "risk_register", "view")
    name = (req.query.get("name") or "").strip()
    from . import dq
    g = dq.stored_grid(req.db, name) if name else None
    if g is None:
        raise HTTPError(404, "not_found", "That sheet is not in a saved workbook. Import the risk assessment workbook first.")
    return {"name": name, "grid": g, "issues": dq.integration_issues(req.db) if name == "Integration" else []}


@router.route("GET", "/api/register/sheets")
def register_sheets(req):
    need(req, "risk_register", "view")
    r = req.db.execute("SELECT id FROM wb_store WHERE kind='risk' AND deleted_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return {"sheets": [], "risk_sheets": []}
    names = [x["name"] for x in req.db.execute("SELECT name FROM wb_sheets WHERE store_id=? ORDER BY sort", (r["id"],))]
    risk = [n for n in names if len(n) == 4 and n[1] == "-" and n[:1] in "BRCPISO"]
    return {"sheets": [n for n in names if n not in risk], "risk_sheets": risk, "store_id": r["id"]}
