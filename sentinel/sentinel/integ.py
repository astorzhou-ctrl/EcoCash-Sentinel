"""Integration Hub (BRD 9.22): connects Sentinel to the systems that hold the facts. Each connector has its own API key (shown once, stored only as a hash, rotated on a schedule), a
health status (connected, delayed, failed) and a log. Outside systems POST to /api/inbound/<connector> with the key in the X-Api-Key header, as JSON {"rows": [...]} or CSV text.
Handlers: kri_readings (code, period, value: KRIs and KPIs), fraud_alerts (the Fraud Intelligence CSV columns), vulnerabilities (the Cyber & IT Risk CSV columns), generic (counted and logged).
A failed or delayed feed, and a key due for rotation, raise an alert to the System Administrators in the daily e-mail."""
import csv
import datetime
import hashlib
import hmac
import io
import json
import secrets

from . import db as dbm, fraud, kit, p2
from .api import router, need
from .core import audit, now, outbox
from .web import HTTPError, Response

CONNECTORS = [("directory", "Directory", "feed", "generic", "Staff directory export, so owner names map to people", 24), ("wallet", "Wallet platform", "feed", "kri_readings", "Availability and transaction indicators as KRI readings", 24), ("fraud_aml", "Fraud and AML monitoring", "feed", "fraud_alerts", "Alerts as rows (detected_at, typology, agent_cluster, amount, loss...)", 24),
              ("siem", "SIEM", "feed", "kri_readings", "Security indicators such as mean time to detect, as KRI readings", 24), ("vuln_scanner", "Vulnerability scanner", "feed", "vulnerabilities", "Findings as rows (title, asset, severity, discovered_on...)", 24), ("itsm", "Service desk (ITSM)", "feed", "generic", "Incident and change counts", 24),
              ("hr", "HR system", "feed", "generic", "Joiners, leavers and training completion", 168), ("finance", "Finance", "feed", "generic", "Cost and revenue lines", 168), ("power_bi", "Power BI", "dataset", "datasets", "Read-only governed datasets: the key's scope is read:datasets", 0)]


def seed(db):
    for k, n, kind, h, note, ex in CONNECTORS:
        db.execute("INSERT OR IGNORE INTO integ_connectors(key,name,kind,handler,expected_hours,note,scopes,endpoint) VALUES(?,?,?,?,?,?,?,?)", (k, n, kind, h, ex, note, "read:datasets" if h == "datasets" else "write:" + h, "/api/inbound/" + k if kind == "feed" else "/api/dataset/<name>"))


def status_of(r, last_ev):
    if not r["key_hash"] or not r["enabled"]:
        return "not configured"
    if last_ev and last_ev["status"] == "error":
        return "failed"
    if r["kind"] == "dataset":
        return "connected"
    ls = r["last_sync"]
    if not ls:
        return "delayed"
    try:
        age = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(ls.replace("Z", "")[:19])).total_seconds() / 3600
    except ValueError:
        return "delayed"
    return "delayed" if r["expected_hours"] and age > r["expected_hours"] else "connected"


def rotation_due(r):
    if not r["key_created"]:
        return False
    try:
        return (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(r["key_created"].replace("Z", "")[:19])).days >= (r["rotate_days"] or 90)
    except ValueError:
        return False


def rows_of(db):
    out = []; since = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in db.execute("SELECT * FROM integ_connectors ORDER BY rowid"):
        ev = db.execute("SELECT * FROM integ_events WHERE connector=? AND status != 'denied' ORDER BY id DESC LIMIT 1", (r["key"],)).fetchone(); n24 = db.execute("SELECT COALESCE(SUM(rows_in),0) n, COUNT(*) c FROM integ_events WHERE connector=? AND ts>=? AND status='ok'", (r["key"], since)).fetchone(); den = db.execute("SELECT COUNT(*) n FROM integ_events WHERE connector=? AND ts>=? AND status='denied'", (r["key"], since)).fetchone()["n"]
        out.append({"key": r["key"], "name": r["name"], "kind": r["kind"], "handler": r["handler"], "note": r["note"], "enabled": bool(r["enabled"]), "status": status_of(r, ev), "last_sync": r["last_sync"], "last_error": r["last_error"], "expected_hours": r["expected_hours"], "rotate_days": r["rotate_days"], "key_tail": r["key_tail"], "key_created": r["key_created"], "rotation_due": rotation_due(r) and bool(r["key_hash"]), "events_24h": n24["n"], "batches_24h": n24["c"], "denied_24h": den, "endpoint": r["endpoint"], "scopes": r["scopes"]})
    return out


@router.route("GET", "/api/integration")
def overview(req):
    c = need(req, "integration_hub", "view"); seed(req.db); cs = rows_of(req.db)
    return {"connectors": cs, "can": {k: k in c.perms.get("integration_hub", set()) for k in ("edit", "create", "delete")}, "base": req.headers.get("Host") or "", "log": [dict(r) for r in req.db.execute("SELECT ts, connector, status, rows_in, rows_bad, detail FROM integ_events ORDER BY id DESC LIMIT 30")],
            "docs": {"auth": "Send the connector's key in the X-Api-Key header. Keys are shown once when created or rotated and stored only as a hash.", "json": "POST /api/inbound/<connector>  Content-Type: application/json  {\"rows\": [{...}, ...]}", "csv": "POST /api/inbound/<connector>  Content-Type: text/csv  (header row, then data)",
                     "handlers": {"kri_readings": "rows: code, period (2026-11-03), value", "fraud_alerts": "columns: detected_at, typology, channel, agent_cluster, region, amount, loss, recovered, status, ref", "vulnerabilities": "columns: title, asset, severity, discovered_on, due_on, cve, source", "generic": "any rows: counted and logged", "datasets": "GET /api/dataset/<name> with the Power BI key (see Data & Reports)"}, "curl": "curl -X POST https://<sentinel>/api/inbound/siem -H \"X-Api-Key: <key>\" -H \"Content-Type: application/json\" -d '{\"rows\":[{\"code\":\"KRI_MTTD\",\"period\":\"2026-11-03\",\"value\":4.5}]}'"}}


@router.route("POST", "/api/integration/<key>/config")
def config(req):
    c = need(req, "integration_hub", "edit"); seed(req.db); k = req.params["key"]; r = req.db.execute("SELECT * FROM integ_connectors WHERE key=?", (k,)).fetchone(); b = req.json()
    if not r:
        raise HTTPError(404, "not_found", "Unknown connector.")
    en = 1 if b.get("enabled", r["enabled"]) else 0
    if en and not r["key_hash"]:
        raise HTTPError(409, "state", "Create a key first (Rotate key): a connector needs a key before it can be switched on.")
    req.db.execute("UPDATE integ_connectors SET enabled=?, expected_hours=?, rotate_days=?, note=? WHERE key=?", (en, max(0, int(b.get("expected_hours", r["expected_hours"]) or 0)), max(7, min(365, int(b.get("rotate_days", r["rotate_days"]) or 90))), str(b.get("note", r["note"]) or "")[:300], k))
    audit(req.db, "integration.config", c.user, "integration_hub", "Connector %s %s" % (k, "switched on" if en else "switched off or edited"), req.ip)
    return {"ok": True}


@router.route("POST", "/api/integration/<key>/rotate")
def rotate(req):
    c = need(req, "integration_hub", "edit"); seed(req.db); k = req.params["key"]
    if not req.db.execute("SELECT 1 FROM integ_connectors WHERE key=?", (k,)).fetchone():
        raise HTTPError(404, "not_found", "Unknown connector.")
    key = "sk_" + secrets.token_urlsafe(32); req.db.execute("UPDATE integ_connectors SET key_hash=?, key_tail=?, key_created=?, last_error=NULL WHERE key=?", (hashlib.sha256(key.encode()).hexdigest(), key[-4:], now(), k))
    audit(req.db, "integration.rotate", c.user, "integration_hub", "Key for connector %s created or rotated" % k, req.ip)
    return {"key": key, "note": "Copy it now. It is shown only once and is stored only as a hash. The old key stops working at once."}


def log(db, key, status, n, bad, detail):
    db.execute("INSERT INTO integ_events(ts,connector,status,rows_in,rows_bad,detail) VALUES(?,?,?,?,?,?)", (now(), key, status, n, bad, (detail or "")[:300]))
    db.execute("DELETE FROM integ_events WHERE ts < ?", ((datetime.datetime.utcnow() - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),))


def to_csv(rows):
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    out = io.StringIO(); w = csv.writer(out); w.writerow(cols)
    for r in rows:
        w.writerow([r.get(k, "") for k in cols])
    return out.getvalue()


def handle(db, handler, rows):
    if handler == "kri_readings":
        ok = bad = 0; why = []
        for r in rows:
            k = db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", (str(r.get("code") or "").strip(),)).fetchone()
            try:
                v = float(r.get("value")); per = str(r.get("period") or "")[:10]; datetime.date.fromisoformat(per)
            except (TypeError, ValueError):
                k = None
            if not k:
                bad += 1; why.append("row %d" % (ok + bad)); continue
            p2.put_reading(db, k, per, v, "feed", "Integration Hub", "feed"); ok += 1
        return ok, bad, "; ".join(why[:5])
    if handler == "fraud_alerts":
        r = fraud.import_text(db, "feed", to_csv(rows)); return r["added"] + r["skipped"], r["rejected"], "added %d, already held %d" % (r["added"], r["skipped"])
    if handler == "vulnerabilities":
        from . import kit_resilience
        r = kit_resilience.act_import_vulns(db, kit.SYS, {"csv": to_csv(rows)}); return r["added"] + r["skipped"], r["rejected"], "added %d, already held %d" % (r["added"], r["skipped"])
    return len(rows), 0, "counted"


@router.route("POST", "/api/inbound/<key>")
def inbound(req):
    """An outside system posts rows. Authenticated by the connector's API key only (no session, no cookies)."""
    k = req.params["key"]; r = req.db.execute("SELECT * FROM integ_connectors WHERE key=? AND kind='feed'", (k,)).fetchone(); given = req.headers.get("X-Api-Key") or ""
    if not r or not r["enabled"] or not r["key_hash"] or not hmac.compare_digest(hashlib.sha256(given.encode()).hexdigest(), r["key_hash"]):
        if r:
            log(req.db, k, "denied", 0, 0, "refused: missing, wrong or switched-off key"); req.db.commit()  # the refusal is kept even though the request fails
        raise HTTPError(401, "unauthorized", "The key is missing or wrong, or the connector is switched off.")
    body = (req.body() or b"").decode("utf-8-sig", "replace")
    try:
        ct = (req.environ.get("CONTENT_TYPE") or "").lower()  # this server passes only HTTP_* headers through, so the content type is read from the environment
        if "json" in ct:
            d = json.loads(body); rows = d.get("rows") if isinstance(d, dict) else d
        else:
            rows = list(csv.DictReader(io.StringIO(body)))
        if not isinstance(rows, list) or len(rows) > 20000 or not all(isinstance(x, dict) for x in rows):
            raise ValueError("rows")
    except (ValueError, TypeError):
        log(req.db, k, "error", 0, 0, "unreadable body"); req.db.execute("UPDATE integ_connectors SET last_error=? WHERE key=?", ("unreadable body", k)); req.db.commit()
        raise HTTPError(400, "validation", "Send JSON {\"rows\": [...]} or CSV text with a header row (up to 20,000 rows).")
    ok, bad, detail = handle(req.db, r["handler"], rows); st = "ok" if ok or not rows else "error"
    log(req.db, k, st, ok, bad, detail); req.db.execute("UPDATE integ_connectors SET last_sync=?, last_error=? WHERE key=?", (now(), None if st == "ok" else "all rows rejected: " + detail, k))
    return {"accepted": ok, "rejected": bad, "detail": detail}


def alert_admins(db):
    """The daily alert: connectors that are failed or delayed, and keys due for rotation, to the System Administrators."""
    seed(db); bad = [c for c in rows_of(db) if c["enabled"] and (c["status"] in ("failed", "delayed") or c["rotation_due"])]
    if not bad:
        return 0
    lines = ["%s: %s%s" % (c["name"], c["status"], "; key due for rotation" if c["rotation_due"] else "") for c in bad]; n = 0
    for u in db.execute("SELECT DISTINCT u.email FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name='System Administrator' AND u.status='active' AND u.deleted_at IS NULL AND u.email IS NOT NULL AND u.email != ''"):
        outbox(db, u["email"], "Sentinel: %d integration connector(s) need attention" % len(bad), "These connectors need attention:\n  - " + "\n  - ".join(lines) + "\n\nOpen Sentinel > Integration Hub.", "integration"); n += 1
    return n
