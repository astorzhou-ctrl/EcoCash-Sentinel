"""Weekly KPI data hygiene (Step 18): see what was loaded, and delete it again.
  imports       every file import is a batch; deleting a batch removes its readings and puts back any value it had replaced
  starter set   the readings and slide texts that came with the system (method 'seed'): remove them once real figures are flowing in"""
import json

from . import core
from .api import router, need, audit
from .web import HTTPError

def _module(kind):
    return "kri_monitor" if kind == "kri" else "weekly_kpi"


@router.route("GET", "/api/kpi/imports")
def imports_list(req):
    need(req, "weekly_kpi")
    rows = []
    for r in req.db.execute("SELECT * FROM kpi_imports WHERE deleted_at IS NULL AND kind<>'kriq' ORDER BY id DESC LIMIT 100"):
        n = req.db.execute("SELECT COUNT(*) n FROM kpi_readings WHERE import_id=?", (r["id"],)).fetchone()["n"]
        rows.append({"id": r["id"], "ts": r["ts"], "by": r["username"], "kind": r["kind"], "filename": r["filename"], "new": r["rows_new"], "replaced": r["rows_replaced"], "readings_now": n})
    seed = req.db.execute("SELECT COUNT(*) n FROM kpi_readings WHERE method='seed'").fetchone()["n"]
    slides = req.db.execute("SELECT COUNT(*) n FROM kpi_deck").fetchone()["n"]
    txn = req.db.execute("SELECT (SELECT COUNT(*) FROM txn_daily WHERE uploaded_by='starter set')+(SELECT COUNT(*) FROM txn_hourly WHERE uploaded_by='starter set') n").fetchone()["n"]
    gone = [{"id": r["id"], "ts": r["ts"], "filename": r["filename"], "deleted_at": r["deleted_at"], "readings": len(json.loads(r["snapshot"] or "[]"))}
            for r in req.db.execute("SELECT * FROM kpi_imports WHERE deleted_at IS NOT NULL AND snapshot IS NOT NULL AND kind<>'kriq' ORDER BY id DESC LIMIT 30")]
    bk = req.db.execute("SELECT value FROM settings WHERE key='starter_backup'").fetchone()
    return {"imports": rows, "deleted": gone, "starter": {"readings": seed, "slides": slides, "transactions": txn, "backup": bool(bk)}, "can": {"delete": "create" in need(req, "weekly_kpi").perms.get("weekly_kpi", set())}}


@router.route("DELETE", "/api/kpi/imports/<int:iid>")
def imports_delete(req):
    r = req.db.execute("SELECT * FROM kpi_imports WHERE id=? AND deleted_at IS NULL AND kind<>'kriq'", (int(req.params["iid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "That import is not there.")
    c = need(req, _module(r["kind"]), "create" if r["kind"] != "kri" else "edit")
    snap = [list(x) for x in req.db.execute("SELECT kpi_id,period,value,method,note,entered_by,created_at FROM kpi_readings WHERE import_id=?", (r["id"],)).fetchall()]
    req.db.execute("UPDATE kpi_imports SET snapshot=? WHERE id=?", (json.dumps(snap), r["id"]))  # kept so the batch can be restored
    gone = req.db.execute("DELETE FROM kpi_readings WHERE import_id=?", (r["id"],)).rowcount
    back = 0
    for kid, period, val, method, note, by, created in json.loads(r["undo"] or "[]"):  # a value the import replaced comes back
        if not req.db.execute("SELECT 1 FROM kpi_readings WHERE kpi_id=? AND period=?", (kid, period)).fetchone():
            req.db.execute("INSERT INTO kpi_readings(kpi_id,period,value,method,note,entered_by,created_at) VALUES(?,?,?,?,?,?,?)", (kid, period, val, method, note, by, created)); back += 1
    req.db.execute("UPDATE kpi_imports SET deleted_at=? WHERE id=?", (core.now(), r["id"]))
    audit(req.db, "kpi.import_delete", c.user, _module(r["kind"]), "Deleted import #%d (%s): %d readings removed, %d earlier values restored" % (r["id"], r["filename"] or "file", gone, back), req.ip)
    return {"removed": gone, "restored": back}


@router.route("POST", "/api/kpi/imports/<int:iid>/restore")
def imports_restore(req):
    r = req.db.execute("SELECT * FROM kpi_imports WHERE id=? AND deleted_at IS NOT NULL AND snapshot IS NOT NULL AND kind<>'kriq'", (int(req.params["iid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "There is nothing to restore for that import.")
    c = need(req, _module(r["kind"]), "create" if r["kind"] != "kri" else "edit")
    undo, n = [], 0
    for kid, period, val, method, note, by, created in json.loads(r["snapshot"]):
        if not req.db.execute("SELECT 1 FROM kpis WHERE id=? AND deleted_at IS NULL", (kid,)).fetchone():
            continue
        was = req.db.execute("SELECT value, method, note, entered_by, created_at FROM kpi_readings WHERE kpi_id=? AND period=?", (kid, period)).fetchone()
        if was:
            undo.append([kid, period, was["value"], was["method"], was["note"], was["entered_by"], was["created_at"]])
            req.db.execute("DELETE FROM kpi_readings WHERE kpi_id=? AND period=?", (kid, period))
        req.db.execute("INSERT INTO kpi_readings(kpi_id,period,value,method,note,entered_by,created_at,import_id) VALUES(?,?,?,?,?,?,?,?)", (kid, period, val, method, note, by, created, r["id"])); n += 1
    req.db.execute("UPDATE kpi_imports SET deleted_at=NULL, snapshot=NULL, undo=? WHERE id=?", (json.dumps(undo), r["id"]))
    audit(req.db, "kpi.import_restore", c.user, _module(r["kind"]), "Restored import #%d (%s): %d readings put back" % (r["id"], r["filename"] or "file", n), req.ip)
    return {"restored": n}


_STARTER = (("kpi_readings", "method='seed'"), ("kpi_deck", "1=1"), ("txn_daily", "uploaded_by='starter set'"), ("txn_hourly", "uploaded_by='starter set'"))


@router.route("POST", "/api/kpi/starter/restore")
def starter_restore(req):
    c = need(req, "weekly_kpi", "create")
    r = req.db.execute("SELECT value FROM settings WHERE key='starter_backup'").fetchone()
    if not r:
        raise HTTPError(404, "not_found", "There is no removed starter set to restore.")
    n = 0
    for table, rows in json.loads(r["value"]).items():
        for row in rows:
            cols = list(row)
            try:
                req.db.execute("INSERT OR IGNORE INTO %s(%s) VALUES(%s)" % (table, ",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols]); n += 1
            except Exception:
                pass
    req.db.execute("DELETE FROM settings WHERE key='starter_backup'")
    audit(req.db, "kpi.starter_restore", c.user, "weekly_kpi", "Starter set restored: %d rows" % n, req.ip)
    return {"restored": n}


@router.route("POST", "/api/kpi/starter/remove")
def starter_remove(req):
    c = need(req, "weekly_kpi", "create")
    backup = {t: [dict(x) for x in req.db.execute("SELECT * FROM %s WHERE %s" % (t, w))] for t, w in _STARTER}
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('starter_backup',?)", (json.dumps(backup),))  # kept so it can be restored
    a = req.db.execute("DELETE FROM kpi_readings WHERE method='seed'").rowcount
    b = req.db.execute("DELETE FROM kpi_deck").rowcount
    d = req.db.execute("DELETE FROM txn_daily WHERE uploaded_by='starter set'").rowcount + req.db.execute("DELETE FROM txn_hourly WHERE uploaded_by='starter set'").rowcount
    audit(req.db, "kpi.starter_remove", c.user, "weekly_kpi", "Starter set removed: %d readings, %d slide texts, %d transaction rows" % (a, b, d), req.ip)
    return {"readings": a, "slides": b, "transactions": d}


@router.route("GET", "/api/demo/summary")
def demo_summary(req):
    """Pages that currently show demonstration records, limited to the pages this user may delete from."""
    c = need(req)
    from . import demo_seed
    return {"pages": {k: v for k, v in demo_seed.summary(req.db).items() if "delete" in c.perms.get(k, set())}}


@router.route("POST", "/api/demo/remove/<page>")
def demo_remove_page(req):
    page = req.params["page"]
    c = need(req, page, "delete")
    from . import demo_seed
    n = demo_seed.remove_module(req.db, page)
    audit(req.db, "demo.remove_page", c.user, page, "Demonstration data removed from %s: %d records" % (page, n), req.ip)
    return {"records": n}
