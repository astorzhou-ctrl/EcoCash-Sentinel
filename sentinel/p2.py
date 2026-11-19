"""Step 5 (BRD phase P2), part 1: Weekly KPI and KRI Monitor. One indicator table serves both: a KPI has an optional target, a KRI has amber and red thresholds."""
import csv
import datetime
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import core, db as dbm, matrix as mx, xlsx, xlsxbook
from .api import router, need, need_str, DATE_RE
from .core import audit, now
from .web import HTTPError, Response

MIRROR = {"OTP_FRAUD": "KRI_OTP", "SIM_SWAP": "KRI_SIMSWAP", "TXN_MERCHANT": "KRI_MERCH"}
FREQ_AGE = {"daily": 4, "weekly": 10, "monthly": 45, "quarterly": 120, "annual": 400}
BETTER = ("up", "down", "none")
GROUP_ORDER = ["Inflation and prices", "Energy and fuel", "Currency and markets", "Money and credit", "Payments sector", "Economy and society", "Fraud and security", "Transaction health", "Sentinel (internal)"]
MODULE = {"kpi": "weekly_kpi", "kri": "kri_monitor"}
SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_seed.json")


# ------------------------------------------------------------------ helpers
def today():
    return dbm.today()


def pdate(s):
    return datetime.date.fromisoformat(s[:10])


def fnum(v, label, required=True, lo=None, hi=None):
    if v in (None, ""):
        if required:
            raise HTTPError(400, "validation", "%s is required." % label)
        return None
    try:
        x = float(v)
        if x != x or x in (float("inf"), float("-inf")):
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPError(400, "validation", "%s must be a number." % label)
    if lo is not None and x < lo or hi is not None and x > hi:
        raise HTTPError(400, "validation", "%s must be between %s and %s." % (label, lo, hi))
    return x


def parse_date(s):
    """ISO, d/m/yyyy, dd-mm-yyyy, an Excel serial, or a datetime: returns YYYY-MM-DD or None."""
    if isinstance(s, (int, float)):
        return xlsx.excel_date(s)
    s = str(s or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try:
            return datetime.date.fromisoformat(s[:10]).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", s)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def status_of(k, v):
    """KRI: green, amber or red against its thresholds. KPI: 'ok' or 'off' against its target, or None."""
    if v is None:
        return None
    if k["kind"] == "kri":
        if k["better"] == "down":
            if k["red"] is not None and v >= k["red"]:
                return "red"
            if k["amber"] is not None and v >= k["amber"]:
                return "amber"
        elif k["better"] == "up":
            if k["red"] is not None and v <= k["red"]:
                return "red"
            if k["amber"] is not None and v <= k["amber"]:
                return "amber"
        return "green"
    if k["target"] is not None and k["better"] in ("up", "down"):
        return "ok" if (v >= k["target"] if k["better"] == "up" else v <= k["target"]) else "off"
    return None


def recent(db, ids, as_of, n=14):
    out = {}
    if not ids:
        return out
    q = "SELECT kpi_id, period, value, method, note FROM kpi_readings WHERE period<=? AND kpi_id IN (%s) ORDER BY kpi_id, period DESC" % ",".join("?" * len(ids))
    for r in db.execute(q, [as_of] + list(ids)):
        lst = out.setdefault(r["kpi_id"], [])
        if len(lst) < n:
            lst.append(dict(r))
    return out


def heads_of_risk_emails(db):
    return [r["email"] for r in db.execute("SELECT DISTINCT u.email FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name='Head of Risk' AND u.deleted_at IS NULL AND u.status='active' AND u.email IS NOT NULL")]


def person_email(db, name):
    if not name:
        return None
    u = db.execute("SELECT email FROM users WHERE (full_name=? COLLATE NOCASE OR username=? COLLATE NOCASE) AND deleted_at IS NULL AND status='active'", (name.strip(), name.strip())).fetchone()
    return u["email"] if u else None


def _live_codes():
    from . import live_data
    return live_data.LIVE_CODES


def kpi_dict(k, rs, as_of):
    latest = rs[0] if rs else None
    prev = rs[1] if len(rs) > 1 else None
    d = {"id": k["id"], "code": k["code"], "name": k["name"], "grp": k["grp"], "kind": k["kind"], "unit": k["unit"], "freq": k["freq"], "source": k["source"], "source_url": k["source_url"], "better": k["better"], "target": k["target"],
         "amber": k["amber"], "red": k["red"], "decimals": k["decimals"], "owner": k["owner"], "risk_id": k["risk_id"], "has_feed": bool(k["feed_url"]), "live_feed": k["code"] in _live_codes(), "internal_key": k["internal_key"], "latest": None, "previous": None, "change": None, "change_pct": None,
         "status": None, "stale": False, "age_days": None, "good": None, "spark": [r["value"] for r in reversed(rs[:12])], "active": bool(k["active"])}
    if latest:
        d["latest"], d["status"] = latest, status_of(k, latest["value"])
        d["age_days"] = (pdate(as_of) - pdate(latest["period"])).days
        d["stale"] = d["age_days"] > FREQ_AGE.get(k["freq"], 45)
    if prev:
        d["previous"] = prev
        d["change"] = latest["value"] - prev["value"]
        d["change_pct"] = (d["change"] / abs(prev["value"]) * 100) if prev["value"] else None
        if k["better"] in ("up", "down") and d["change"] != 0:
            d["good"] = (d["change"] > 0) == (k["better"] == "up")
    return d


def fmt(v, dec):
    return None if v is None else round(v, dec)


# ------------------------------------------------------------------ the weekly report
@router.route("GET", "/api/kpi/weekly")
def kpi_weekly(req):
    need(req, "weekly_kpi", "view")
    db = req.db
    ks = db.execute("SELECT * FROM kpis WHERE kind='kpi' AND active=1 AND deleted_at IS NULL ORDER BY sort, name").fetchall()
    mxp = db.execute("SELECT MAX(r.period) m FROM kpi_readings r JOIN kpis k ON k.id=r.kpi_id WHERE k.kind='kpi' AND r.period<=?", (str(today()),)).fetchone()["m"]
    as_of = (req.query.get("as_of") or mxp or str(today())).strip()
    if not DATE_RE.match(as_of):
        raise HTTPError(400, "validation", "as_of must be a date (YYYY-MM-DD).")
    rec = recent(db, [k["id"] for k in ks], as_of)
    rows = [kpi_dict(k, rec.get(k["id"], []), as_of) for k in ks]
    groups = {}
    for r in rows:
        groups.setdefault(r["grp"] or "Other", []).append(r)
    order = [g for g in GROUP_ORDER if g in groups] + sorted(g for g in groups if g not in GROUP_ORDER)
    withdata = [r for r in rows if r["latest"]]
    dates = [r["period"] for r in db.execute("SELECT DISTINCT r.period FROM kpi_readings r JOIN kpis k ON k.id=r.kpi_id WHERE k.kind='kpi' AND r.period<=? ORDER BY r.period DESC LIMIT 14", (str(today()),))]
    notes = {r["grp"]: r["text"] for r in db.execute("SELECT grp, text FROM kpi_notes WHERE as_of=?", (as_of,))}
    c = req.ctx
    return {"as_of": as_of, "latest_date": mxp, "dates": dates, "groups": [{"name": g, "kpis": groups[g], "note": notes.get(g, "")} for g in order],
            "summary": {"total": len(rows), "with_data": len(withdata), "stale": sum(1 for r in withdata if r["stale"]), "off_target": sum(1 for r in withdata if r["status"] == "off"), "auto": sum(1 for r in withdata if r["latest"]["method"] in ("feed", "internal")), "manual": sum(1 for r in withdata if r["latest"]["method"] not in ("feed", "internal"))},
            "can": {a: a in c.perms.get("weekly_kpi", set()) for a in core.ACTIONS}}


@router.route("PUT", "/api/kpi/notes")
def kpi_note(req):
    c = need(req, "weekly_kpi", "edit")
    d = req.json()
    as_of, grp, text = (d.get("as_of") or "").strip(), need_str(d, "grp", "Group", 80), need_str(d, "text", "Commentary", 2000, False)
    if not DATE_RE.match(as_of):
        raise HTTPError(400, "validation", "as_of must be a date.")
    if text:
        req.db.execute("INSERT INTO kpi_notes(as_of,grp,text,author,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(as_of,grp) DO UPDATE SET text=excluded.text, author=excluded.author, updated_at=excluded.updated_at", (as_of, grp, text, c.user["username"], now()))
    else:
        req.db.execute("DELETE FROM kpi_notes WHERE as_of=? AND grp=?", (as_of, grp))
    audit(req.db, "kpi.commentary", c.user, "weekly_kpi", "Commentary for %s, week of %s" % (grp, as_of), req.ip)
    return {"ok": True}


@router.route("GET", "/api/kpi/series")
def kpi_series(req):
    c = need(req, "weekly_kpi", "view") if (req.query.get("kind") != "kri") else need(req, "kri_monitor", "view")
    k = req.db.execute("SELECT * FROM kpis WHERE id=? AND deleted_at IS NULL", (req.query.get("id") or 0,)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Indicator not found")
    n = min(int(req.query.get("n") or 36), 400)
    rows = [dict(r) for r in req.db.execute("SELECT period, value, method, note FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT ?", (k["id"], n))][::-1]
    return {"kpi": kpi_dict(k, rows[::-1][:14], str(today())), "points": rows}


# ------------------------------------------------------------------ catalogue
def clean_kpi(d, kind, existing=None):
    code = re.sub(r"[^A-Za-z0-9_]", "_", need_str(d, "code", "Code", 40)).upper()
    f = {"code": code, "name": need_str(d, "name", "Name", 160), "grp": need_str(d, "grp", "Group", 80, False) or ("Fraud" if kind == "kri" else "Other"), "unit": need_str(d, "unit", "Unit", 24, False) or None, "source": need_str(d, "source", "Source", 120, False) or None,
         "owner": need_str(d, "owner", "Owner", 120, False) or None}
    f["freq"] = (d.get("freq") or "weekly").strip()
    f["better"] = (d.get("better") or "none").strip()
    if f["freq"] not in FREQ_AGE or f["better"] not in BETTER:
        raise HTTPError(400, "validation", "Choose the frequency and the direction from the lists.")
    url = (d.get("source_url") or "").strip() or None
    if url and not re.match(r"^https?://", url):
        raise HTTPError(400, "validation", "The source link must start with http:// or https://.")
    f["source_url"] = url
    f["decimals"] = int(fnum(d.get("decimals", 1), "Decimals", False, 0, 6) or 0) if d.get("decimals") not in (None, "") else 1
    f["target"] = fnum(d.get("target"), "Target", False)
    f["amber"], f["red"] = fnum(d.get("amber"), "Amber threshold", False), fnum(d.get("red"), "Red threshold", False)
    if kind == "kri":
        if f["better"] == "none" or f["amber"] is None or f["red"] is None:
            raise HTTPError(400, "validation", "A KRI needs a direction and both an amber and a red threshold.")
        if (f["better"] == "down" and f["red"] < f["amber"]) or (f["better"] == "up" and f["red"] > f["amber"]):
            raise HTTPError(400, "validation", "The red threshold must be worse than the amber threshold.")
    fu = (d.get("feed_url") or "").strip() or None
    if fu and not re.match(r"^https?://", fu):
        raise HTTPError(400, "validation", "The feed link must start with https://.")
    f["feed_url"], f["feed_fmt"] = fu, ((d.get("feed_fmt") or "csv").strip() if fu else None)
    if fu and f["feed_fmt"] not in ("csv", "json"):
        raise HTTPError(400, "validation", "The feed format must be csv or json.")
    f["feed_keys"] = (need_str(d, "feed_keys", "Feed columns", 80, False) or "date,value") if fu else None
    ik = (d.get("internal_key") or "").strip() or None
    if ik and ik not in INTERNAL:
        raise HTTPError(400, "validation", "Unknown Sentinel measure.")
    f["internal_key"] = ik
    rid = d.get("risk_id")
    f["risk_id"] = int(rid) if rid not in (None, "", 0) else None
    return f


@router.route("GET", "/api/kpi/catalog")
def kpi_catalog(req):
    kind = req.query.get("kind") if req.query.get("kind") in ("kpi", "kri") else "kpi"
    c = need(req, MODULE[kind], "view")
    out = []
    for k in req.db.execute("SELECT * FROM kpis WHERE kind=? AND deleted_at IS NULL ORDER BY grp, sort, name", (kind,)):
        last = req.db.execute("SELECT period, value, method FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
        n = req.db.execute("SELECT COUNT(*) c FROM kpi_readings WHERE kpi_id=?", (k["id"],)).fetchone()["c"]
        out.append(dict(dict(k), last=dict(last) if last else None, readings=n))
    return {"items": out, "internal": {key: v[0] for key, v in INTERNAL.items()}, "can": {a: a in c.perms.get(MODULE[kind], set()) for a in core.ACTIONS}, "hosts": hosts(req.db)}


@router.route("POST", "/api/kpi/catalog")
def kpi_catalog_create(req):
    d = req.json()
    kind = d.get("kind") if d.get("kind") in ("kpi", "kri") else "kpi"
    c = need(req, MODULE[kind], "create")
    f = clean_kpi(d, kind)
    if req.db.execute("SELECT 1 FROM kpis WHERE code=?", (f["code"],)).fetchone():
        raise HTTPError(409, "exists", "An indicator with the code %s already exists." % f["code"])
    cols = list(f) + ["kind", "created_at"]
    kid = req.db.execute("INSERT INTO kpis(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), list(f.values()) + [kind, now()]).lastrowid
    audit(req.db, "kpi.created", c.user, MODULE[kind], "%s %s added (%s)" % (kind.upper(), f["code"], f["name"]), req.ip)
    return {"id": kid}


@router.route("PUT", "/api/kpi/catalog/<int:kid>")
def kpi_catalog_update(req):
    k = req.db.execute("SELECT * FROM kpis WHERE id=? AND deleted_at IS NULL", (int(req.params["kid"]),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Indicator not found")
    c = need(req, MODULE[k["kind"]], "edit")
    d = dict(req.json(), code=k["code"])
    f = clean_kpi(d, k["kind"])
    if "active" in req.json():
        f["active"] = 1 if req.json()["active"] else 0
    req.db.execute("UPDATE kpis SET %s WHERE id=?" % ",".join("%s=?" % x for x in f), list(f.values()) + [k["id"]])
    audit(req.db, "kpi.changed", c.user, MODULE[k["kind"]], "%s %s changed" % (k["kind"].upper(), k["code"]), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/kpi/catalog/<int:kid>")
def kpi_catalog_delete(req):
    k = req.db.execute("SELECT * FROM kpis WHERE id=? AND deleted_at IS NULL", (int(req.params["kid"]),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Indicator not found")
    c = need(req, MODULE[k["kind"]], "delete")
    req.db.execute("UPDATE kpis SET deleted_at=?, active=0 WHERE id=?", (now(), k["id"]))
    audit(req.db, "kpi.removed", c.user, MODULE[k["kind"]], "%s %s removed (history kept)" % (k["kind"].upper(), k["code"]), req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ readings
def put_reading(db, k, period, value, method, note, who):
    """Insert or replace one reading. Returns 'new', 'replaced' or 'same'. Feeds never overwrite (see run_feeds)."""
    old = db.execute("SELECT id, value, method FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], period)).fetchone()
    if old and old["value"] == value:
        res = "same"
    elif old:
        db.execute("UPDATE kpi_readings SET value=?, method=?, note=?, entered_by=?, created_at=? WHERE id=?", (value, method, note, who, now(), old["id"]))
        res = "replaced"
    else:
        db.execute("INSERT INTO kpi_readings(kpi_id,period,value,method,note,entered_by,created_at) VALUES(?,?,?,?,?,?,?)", (k["id"], period, value, method, note, who, now()))
        res = "new"
    twin = MIRROR.get(k["code"])
    if twin and res != "same":  # the same figure feeds the weekly report and the KRI that watches it
        t = db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", (twin,)).fetchone()
        if t:
            put_reading(db, t, period, value, method, note, who)
            check_alerts(db, t, who)
    return res


def check_alerts(db, k, actor="system", ip=""):
    """KRI rule (BRD): amber tells the owner, red also tells the Head of Risk and opens an action in the tracker; a return to green resolves the alert."""
    if k["kind"] != "kri":
        return None
    r = db.execute("SELECT period, value FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
    if not r:
        return None
    st = status_of(k, r["value"])
    open_ = db.execute("SELECT * FROM kri_alerts WHERE kpi_id=? AND status IN ('open','acknowledged')", (k["id"],)).fetchall()
    if st in ("amber", "red"):
        if any(a["level"] == st for a in open_):
            return None
        for a in open_:
            if a["level"] != st:
                db.execute("UPDATE kri_alerts SET status='resolved', resolved_at=? WHERE id=?", (now(), a["id"]))
        db.execute("INSERT INTO kri_alerts(kpi_id,level,period,value,opened_at) VALUES(?,?,?,?,?)", (k["id"], st, r["period"], r["value"], now()))
        who = {e for e in ([person_email(db, k["owner"])] + (heads_of_risk_emails(db) if st == "red" else [])) if e}
        for e in who:
            core.outbox(db, e, "Sentinel KRI %s: %s" % (st.upper(), k["name"]), "%s is %s: %s on %s (amber %s, red %s).%s" % (k["code"], st, round(r["value"], k["decimals"]), r["period"], k["amber"], k["red"], " An action has been added to the Daily Tracker." if st == "red" else ""), "kri")
        audit(db, "kri.alert", None, "kri_monitor", "%s %s: %s on %s" % (k["code"], st, round(r["value"], k["decimals"]), r["period"]), ip, actor)
        return st
    for a in open_:
        db.execute("UPDATE kri_alerts SET status='resolved', resolved_at=? WHERE id=?", (now(), a["id"]))
    return "resolved" if open_ else None


@router.route("POST", "/api/kpi/readings")
def reading_add(req):
    d = req.json()
    k = req.db.execute("SELECT * FROM kpis WHERE (id=? OR code=?) AND deleted_at IS NULL", (d.get("id") or 0, (d.get("code") or "").upper())).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Indicator not found")
    c = need(req, MODULE[k["kind"]], "create" if k["kind"] == "kpi" else "edit")
    period = parse_date(d.get("period"))
    if not period or pdate(period) > today():
        raise HTTPError(400, "validation", "Give the as-of date of the value (today or earlier).")
    value = fnum(d.get("value"), "Value")
    res = put_reading(req.db, k, period, value, "manual", need_str(d, "note", "Note", 300, False) or None, c.user["username"])
    if res != "same":
        audit(req.db, "kpi.reading", c.user, MODULE[k["kind"]], "%s %s = %s as of %s" % (res, k["code"], value, period), req.ip)
    alert = check_alerts(req.db, k, c.user["username"], req.ip)
    return {"result": res, "alert": alert}


# ------------------------------------------------------------------ import and Excel
def read_table(data):
    """Rows of a workbook (.xlsx) or CSV as lists of cell values."""
    if data[:2] == b"PK":
        sheets = xlsx.read(data)
        name = "Enter readings" if "Enter readings" in sheets else next(iter(sheets))
        return sheets[name]
    text = data.decode("utf-8-sig", errors="replace")
    return [r for r in csv.reader(io.StringIO(text))]


def parse_readings(db, data, kind):
    rows = read_table(data)
    hi = next((i for i, r in enumerate(rows[:12]) if any(str(c or "").strip().lower() == "code" for c in r)), None)
    if hi is None:
        raise HTTPError(400, "bad_file", "No header row with a Code column was found. Download the template from Weekly KPI > Enter and import.")
    head = [str(c or "").strip().lower() for c in rows[hi]]
    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return None
    ci, di, vi, ni = col("code"), col("new date", "date", "period", "as of"), col("new value", "value"), col("note", "notes")
    if di is None or vi is None:
        raise HTTPError(400, "bad_file", "The file needs a Date (or New date) column and a Value (or New value) column.")
    known = {k["code"]: k for k in db.execute("SELECT * FROM kpis WHERE deleted_at IS NULL")}
    good, unknown, errors, seen = [], [], [], set()
    for n, r in enumerate(rows[hi + 1:], hi + 2):
        r = list(r) + [None] * (max(ci, di, vi, ni or 0) + 1 - len(r))
        code = str(r[ci] or "").strip().upper()
        if not code or (r[vi] in (None, "") and r[di] in (None, "")):
            continue
        if r[vi] in (None, ""):
            continue
        k = known.get(code)
        if not k:
            unknown.append(code); continue
        if k["kind"] != kind:
            errors.append("Row %d: %s is a %s, not a %s." % (n, code, k["kind"].upper(), kind.upper())); continue
        p = parse_date(r[di])
        try:
            v = float(r[vi]) if not isinstance(r[vi], str) else float(r[vi].replace(",", "").replace("%", "").strip())
        except (TypeError, ValueError):
            errors.append("Row %d: the value for %s is not a number." % (n, code)); continue
        if not p:
            errors.append("Row %d: the date for %s is missing or not a date." % (n, code)); continue
        if pdate(p) > today():
            errors.append("Row %d: the date for %s is in the future." % (n, code)); continue
        if (code, p) in seen:
            errors.append("Row %d: %s appears twice for %s." % (n, code, p)); continue
        seen.add((code, p)); good.append({"k": k, "period": p, "value": v, "note": str(r[ni]).strip()[:300] if ni is not None and r[ni] else None})
    return good, sorted(set(unknown)), errors


@router.route("POST", "/api/kpi/import")
def kpi_import(req):
    kind = req.query.get("kind") if req.query.get("kind") in ("kpi", "kri") else "kpi"
    c = need(req, MODULE[kind], "create" if kind == "kpi" else "edit")
    data = req.body()
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    try:
        good, unknown, errors = parse_readings(req.db, data, kind)
    except HTTPError:
        raise
    except Exception:
        raise HTTPError(400, "bad_file", "The file could not be read. Use the template (.xlsx) or a CSV file.")
    new = replaced = 0
    for g in good:
        old = req.db.execute("SELECT value FROM kpi_readings WHERE kpi_id=? AND period=?", (g["k"]["id"], g["period"])).fetchone()
        if old is None:
            new += 1
        elif old["value"] != g["value"]:
            replaced += 1
    out = {"valid": len(good), "new": new, "replaced": replaced, "unchanged": len(good) - new - replaced, "unknown": unknown, "errors": errors[:25], "error_count": len(errors), "dry": req.query.get("dry") != "0"}
    if out["dry"]:
        return out
    touched = {}; undo = []
    bid = req.db.execute("INSERT INTO kpi_imports(ts,username,kind,filename,rows_new,rows_replaced) VALUES(?,?,?,?,?,?)", (now(), c.user["username"], kind, __import__("urllib.parse").parse.unquote(req.headers.get("X-Filename") or "")[:120], new, replaced)).lastrowid
    for g in good:
        was = req.db.execute("SELECT value, method, note, entered_by, created_at FROM kpi_readings WHERE kpi_id=? AND period=?", (g["k"]["id"], g["period"])).fetchone()
        if was:
            undo.append([g["k"]["id"], g["period"], was["value"], was["method"], was["note"], was["entered_by"], was["created_at"]])
        put_reading(req.db, g["k"], g["period"], g["value"], "import", g["note"] or "Imported from file", c.user["username"])
        req.db.execute("UPDATE kpi_readings SET import_id=? WHERE kpi_id=? AND period=?", (bid, g["k"]["id"], g["period"]))
        touched[g["k"]["id"]] = g["k"]
    req.db.execute("UPDATE kpi_imports SET undo=? WHERE id=?", (json.dumps(undo), bid))
    for k in touched.values():
        check_alerts(req.db, k, c.user["username"], req.ip)
    audit(req.db, "kpi.import", c.user, MODULE[kind], "Imported %d readings (%d new, %d replaced)" % (len(good), new, replaced), req.ip)
    return out


def xlsx_response(data, name):
    return Response(data, 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [("Content-Disposition", 'attachment; filename="%s"' % name)])


@router.route("GET", "/api/kpi/template.xlsx")
def kpi_template(req):
    kind = req.query.get("kind") if req.query.get("kind") in ("kpi", "kri") else "kpi"
    c = need(req, MODULE[kind], "view")
    rows = [[("Enter readings", 3)], ["Type the new date and value for each indicator you are updating, then import the file in Sentinel. Leave a row empty to skip it. Dates as YYYY-MM-DD."], [],
            [(h, 1) for h in ("Code", "Indicator", "Group", "Unit", "Frequency", "Last date", "Last value", "New date", "New value", "Note")]]
    for k in req.db.execute("SELECT * FROM kpis WHERE kind=? AND active=1 AND deleted_at IS NULL AND feed_url IS NULL AND internal_key IS NULL ORDER BY grp, sort, name", (kind,)):
        last = req.db.execute("SELECT period, value FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
        rows.append([k["code"], k["name"], k["grp"], k["unit"], k["freq"], ("date", last["period"]) if last else None, last["value"] if last else None, None, None, None])
    return xlsx_response(xlsxbook.write([("Enter readings", rows, [18, 46, 22, 10, 11, 12, 12, 12, 12, 30])]), "Sentinel_%s_template.xlsx" % kind.upper())


@router.route("GET", "/api/kpi/export.xlsx")
def kpi_export(req):
    c = need(req, "weekly_kpi", "export")
    rep = kpi_weekly(req)
    as_of = rep["as_of"]
    S = rep["summary"]
    rows = [[("EcoCash Weekly KPI Report", 3)], ["As of", ("date", as_of), "Generated", ("date", str(today())), "By", c.user["username"]], ["Indicators", S["total"], "With data", S["with_data"], "Stale", S["stale"], "Off target", S["off_target"], "Captured automatically", S["auto"]], [],
            [(h, 1) for h in ("Indicator", "Unit", "As of", "Latest", "Previous", "Change", "Change %", "Target", "Status", "Stale", "Source", "How captured", "Code")]]
    for g in rep["groups"]:
        rows.append([(g["name"], 4)] + [("", 4)] * 12)
        for k in g["kpis"]:
            L, P, dec = k["latest"], k["previous"], k["decimals"]
            st = {"ok": ("On target", 5), "off": ("Off target", 6)}.get(k["status"], ("", 0))
            rows.append([k["name"], k["unit"], ("date", L["period"]) if L else None, fmt(L["value"], dec) if L else "no data", fmt(P["value"], dec) if P else None, fmt(k["change"], dec) if k["change"] is not None else None,
                         fmt(k["change_pct"], 1) if k["change_pct"] is not None else None, k["target"], st, ("Yes", 6) if k["stale"] else None, k["source"], {"feed": "Automatic feed", "internal": "Sentinel", "import": "Imported", "manual": "Manual"}.get(L["method"], L["method"]) if L else None, k["code"]])
    hist = [[(h, 1) for h in ("Code", "Indicator", "Group", "Date", "Value", "How captured", "Note")]]
    for r in req.db.execute("SELECT k.code, k.name, k.grp, r.period, r.value, r.method, r.note FROM kpi_readings r JOIN kpis k ON k.id=r.kpi_id WHERE k.kind='kpi' AND k.deleted_at IS NULL AND r.period<=? ORDER BY k.grp, k.name, r.period DESC", (as_of,)):
        hist.append([r["code"], r["name"], r["grp"], ("date", r["period"]), r["value"], r["method"], r["note"]])
    notes = [[(h, 1) for h in ("Group", "Commentary")]] + [[g["name"], (g["note"], 7)] for g in rep["groups"] if g["note"]]
    srcs = [[(h, 1) for h in ("Indicator", "Code", "Source", "Source link", "Frequency", "Automatic feed", "Sentinel measure")]]
    for g in rep["groups"]:
        for k in g["kpis"]:
            srcs.append([k["name"], k["code"], k["source"], k["source_url"], k["freq"], "yes" if k["has_feed"] else "", k["internal_key"]])
    audit(req.db, "export.weekly_kpi", c.user, "weekly_kpi", "Weekly KPI report as of %s downloaded" % as_of, req.ip)
    from . import p3, p4
    gr, lay = p3.charts_for(req.db, as_of)
    return xlsx_response(xlsxbook.write(p4.deck_sheets(req.db, rep, gr, lay, as_of) + [("Indicators", rows, [46, 11, 12, 14, 14, 12, 10, 10, 12, 8, 26, 16, 18]), ("History", hist, [18, 46, 22, 12, 14, 12, 40]), ("Commentary", notes, [28, 110]), ("Sources", srcs, [46, 18, 26, 44, 12, 12, 22])]), "Sentinel_Weekly_KPI_%s.xlsx" % as_of)


# ------------------------------------------------------------------ automatic updates: Sentinel's own measures and approved feeds
def risk_rows(db):
    return db.execute("SELECT * FROM risks WHERE deleted_at IS NULL").fetchall()


def v_assessed(db):
    return sum(1 for r in risk_rows(db) if not r["needs_assessment"])


def v_unassessed(db):
    return sum(1 for r in risk_rows(db) if r["needs_assessment"])


def v_outside(db):
    return sum(1 for r in risk_rows(db) if not r["needs_assessment"] and mx.outside_appetite(r["category"], mx.rank(r["res_l"], r["res_c"])))


def v_loa(db):
    ei = er = 0.0
    for r in risk_rows(db):
        a = db.execute("SELECT AVG(ice) a, COUNT(ice) n FROM risk_controls WHERE risk_id=?", (r["id"],)).fetchone()
        if r["emv_i"] and a["n"]:
            ei += r["emv_i"]; er += r["emv_i"] * a["a"]
    return round((1 - er / ei) * 100, 1) if ei else None


def v_overdue(db):
    from . import p1
    k = p1.cfg(db)
    return sum(1 for t in db.execute("SELECT * FROM tasks WHERE deleted_at IS NULL") if p1.task_dict(t, today(), k["soon_days"])["status"] == "Overdue")


def v_inc_open(db):
    return db.execute("SELECT COUNT(*) c FROM incidents WHERE deleted_at IS NULL AND status!='closed' AND kind!='near_miss'").fetchone()["c"]


def v_loss30(db):
    r = db.execute("SELECT COALESCE(SUM(gross_loss-recovered),0) s FROM incidents WHERE deleted_at IS NULL AND occurred_on>=?", (str(today() - datetime.timedelta(days=30)),)).fetchone()
    return round(r["s"], 2)


def v_kri_red(db):
    n = 0
    for k in db.execute("SELECT * FROM kpis WHERE kind='kri' AND active=1 AND deleted_at IS NULL"):
        r = db.execute("SELECT value FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
        n += bool(r) and status_of(k, r["value"]) == "red"
    return n


INTERNAL = {"risk.assessed": ("Risks assessed", v_assessed), "risk.unassessed": ("Risks waiting for assessment", v_unassessed), "risk.outside_appetite": ("Risks outside appetite", v_outside), "risk.loa": ("Portfolio level of assurance (%)", v_loa),
            "tracker.overdue": ("Overdue tracker tasks", v_overdue), "incident.open": ("Open incidents", v_inc_open), "incident.net_loss_30d": ("Net loss, last 30 days", v_loss30), "kri.red": ("KRIs in red", v_kri_red)}


def snapshot_internal(db, who="system"):
    n = 0
    for k in db.execute("SELECT * FROM kpis WHERE internal_key IS NOT NULL AND active=1 AND deleted_at IS NULL").fetchall():
        v = INTERNAL[k["internal_key"]][1](db)
        if v is not None and put_reading(db, k, str(today()), float(v), "internal", "Calculated by Sentinel", who) != "same":
            n += 1
        check_alerts(db, k, who)
    return n


def hosts(db):
    r = db.execute("SELECT value FROM settings WHERE key='kpi_hosts'").fetchone()
    return json.loads(r["value"]) if r else []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch_feed(db, k, who="system"):
    """Pull new readings from the indicator's feed. Uses the same hardened connection as verified sources: approved hosts only, https, public addresses,
    no redirects to other hosts, size and time limits. A feed never overwrites an existing value."""
    from .p3s import safe_get, FetchError
    url = k["feed_url"]
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    try:
        raw = safe_get(url, set(hosts(db)))["body"]
    except FetchError as e:
        return False, str(e)
    dk, vk = [x.strip().lower() for x in ((k["feed_keys"] or "date,value") + ",value").split(",")[:2]]
    items = []
    try:
        if k["feed_fmt"] == "json":
            j = json.loads(raw.decode("utf-8-sig"))
            j = j.get("data", j.get("readings", [j])) if isinstance(j, dict) else j
            items = [(i.get(dk) or i.get("date"), i.get(vk) if vk in i else i.get("value")) for i in j if isinstance(i, dict)]
        else:
            for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
                low = {str(a or "").strip().lower(): b for a, b in r.items()}
                items.append((low.get(dk), low.get(vk)))
    except Exception:
        return False, "The feed could not be read as %s." % k["feed_fmt"].upper()
    n = 0
    for dt, v in items[-400:]:
        p_ = parse_date(dt)
        try:
            val = float(str(v).replace(",", "").replace("%", "").strip())
        except (TypeError, ValueError):
            continue
        if not p_ or pdate(p_) > today():
            continue
        if not db.execute("SELECT 1 FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], p_)).fetchone():
            put_reading(db, k, p_, val, "feed", "Feed %s" % host, who); n += 1
    if n:
        check_alerts(db, k, who)
    return True, "%d new reading(s)" % n


def run_feeds(db, who="system", only=None):
    out = []
    for k in db.execute("SELECT * FROM kpis WHERE feed_url IS NOT NULL AND active=1 AND deleted_at IS NULL").fetchall():
        if only and k["id"] not in only:
            continue
        ok, msg = fetch_feed(db, k, who)
        db.execute("INSERT INTO kpi_feed_log(ts,kpi_id,ok,message) VALUES(?,?,?,?)", (now(), k["id"], int(ok), msg))
        out.append({"code": k["code"], "ok": ok, "message": msg})
    return out


def daily_job(db):
    """Runs once a day from the server: Sentinel's own measures, then the approved feeds."""
    r = db.execute("SELECT value FROM settings WHERE key='kpi_job'").fetchone()
    if r and r["value"] == str(today()):
        return False
    snapshot_internal(db); run_feeds(db)
    from . import p5
    p5.nightly(db)
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kpi_job',?)", (str(today()),))
    return True


@router.route("POST", "/api/kpi/refresh")
def kpi_refresh(req):
    c = need(req, "weekly_kpi", "create")
    n = snapshot_internal(req.db, c.user["username"])
    res = run_feeds(req.db, c.user["username"])
    audit(req.db, "kpi.refresh", c.user, "weekly_kpi", "Refresh: %d Sentinel measure(s) updated, %d feed(s) tried, %d failed" % (n, len(res), sum(1 for x in res if not x["ok"])), req.ip)
    return {"internal_updated": n, "feeds": res}


@router.route("PUT", "/api/kpi/hosts")
def kpi_hosts(req):
    c = need(req, "weekly_kpi", "approve")
    hs = []
    for h in req.json().get("hosts", []):
        h = str(h).strip().lower()
        if h and not re.match(r"^[a-z0-9.-]+$", h):
            raise HTTPError(400, "validation", "%s is not a valid host name." % h)
        if h and h not in hs:
            hs.append(h)
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kpi_hosts',?)", (json.dumps(hs),))
    audit(req.db, "kpi.hosts", c.user, "weekly_kpi", "Approved feed hosts: %s" % (", ".join(hs) or "none"), req.ip)
    return {"hosts": hs}


@router.route("GET", "/api/kpi/feedlog")
def kpi_feedlog(req):
    need(req, "weekly_kpi", "view")
    return {"log": [dict(r) for r in req.db.execute("SELECT l.ts, l.ok, l.message, k.code FROM kpi_feed_log l LEFT JOIN kpis k ON k.id=l.kpi_id ORDER BY l.id DESC LIMIT 50")]}


# ------------------------------------------------------------------ starter set from the July 2026 weekly report
def seed_catalog(db, who="system", include_kri=True):
    data = json.load(open(SEED_FILE, encoding="utf-8"))
    added = readings = 0
    for i, s in enumerate(data["kpis"]):
        if s["kind"] == "kri" and not include_kri:
            continue
        k = db.execute("SELECT * FROM kpis WHERE code=?", (s["code"],)).fetchone()
        if not k:
            kid = db.execute("INSERT INTO kpis(code,name,grp,kind,unit,freq,source,source_url,better,target,amber,red,decimals,internal_key,sort,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (s["code"], s["name"], s["grp"], s["kind"], s["unit"], s["freq"], s["source"], s["source_url"], s["better"], s["target"], s["amber"], s["red"], s["decimals"], s["internal_key"], i, now())).lastrowid
            k = db.execute("SELECT * FROM kpis WHERE id=?", (kid,)).fetchone(); added += 1
        for period, value in s["readings"]:
            if not period or not DATE_RE.match(str(period)):
                continue
            if not db.execute("SELECT 1 FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], period)).fetchone():
                db.execute("INSERT INTO kpi_readings(kpi_id,period,value,method,note,entered_by,created_at) VALUES(?,?,?,?,?,?,?)", (k["id"], period, value, "seed", "From the %s" % data["source"], who, now())); readings += 1
        check_alerts(db, k, who)
    return added, readings, data["source"]


@router.route("POST", "/api/kpi/seed")
def kpi_seed(req):
    c = need(req, "weekly_kpi", "create")
    kri_ok = "create" in c.perms.get("kri_monitor", set())
    added, readings, src = seed_catalog(req.db, c.user["username"], kri_ok)
    snapshot_internal(req.db, c.user["username"])
    try:
        reset = bool(req.json().get("reset_charts"))
    except Exception:
        reset = False
    from . import p4
    extra = p4.seed_extras(req.db, c.user["username"], reset)
    audit(req.db, "kpi.seed", c.user, "weekly_kpi", "Starter set loaded from the %s: %d indicators, %d readings, %d slide texts, %d transaction rows%s" % (src, added, readings, extra["slides"], extra["daily"] + extra["hourly"], "; graph layout reset to the standard" if reset else ""), req.ip)
    return {"added": added, "readings": readings, "source": src, "slides": extra["slides"], "daily": extra["daily"], "hourly": extra["hourly"]}


# ------------------------------------------------------------------ KRI Monitor
def month_strip(db, kid, k):
    """Status of the latest reading in each of the last twelve calendar months (None where there is no reading)."""
    t = today(); out = []
    for i in range(11, -1, -1):
        y, m = t.year, t.month - i
        while m <= 0:
            m += 12; y -= 1
        a = datetime.date(y, m, 1)
        b = datetime.date(y + (m == 12), m % 12 + 1, 1)
        r = db.execute("SELECT value FROM kpi_readings WHERE kpi_id=? AND period>=? AND period<? ORDER BY period DESC LIMIT 1", (kid, str(a), str(b))).fetchone()
        out.append({"month": a.strftime("%b %Y"), "status": status_of(k, r["value"]) if r else None})
    return out


@router.route("GET", "/api/kri")
def kri_list(req):
    c = need(req, "kri_monitor", "view")
    db = req.db
    ks = db.execute("SELECT * FROM kpis WHERE kind='kri' AND active=1 AND deleted_at IS NULL ORDER BY grp, name").fetchall()
    rec = recent(db, [k["id"] for k in ks], str(today()), 8)
    risks = {r["id"]: r for r in db.execute("SELECT id, ref, title, res_l, res_c, needs_assessment FROM risks WHERE deleted_at IS NULL")}
    items = []
    for k in ks:
        d = kpi_dict(k, rec.get(k["id"], []), str(today()))
        d["strip"] = month_strip(db, k["id"], k)
        rk = risks.get(k["risk_id"])
        d["risk"] = {"id": rk["id"], "ref": rk["ref"], "title": rk["title"]} if rk else None
        d["alert"] = db.execute("SELECT id, level, status, opened_at FROM kri_alerts WHERE kpi_id=? AND status IN ('open','acknowledged') ORDER BY id DESC LIMIT 1", (k["id"],)).fetchone()
        d["alert"] = dict(d["alert"]) if d["alert"] else None
        items.append(d)
    covered = {k["risk_id"] for k in ks if k["risk_id"]}
    need_kri = [{"id": r["id"], "ref": r["ref"], "title": r["title"], "rank": mx.rank(r["res_l"], r["res_c"]), "level": mx.level(mx.rank(r["res_l"], r["res_c"]))} for r in risks.values() if not r["needs_assessment"] and mx.rank(r["res_l"], r["res_c"]) >= 13]
    missing = sorted([r for r in need_kri if r["id"] not in covered], key=lambda r: -r["rank"])
    alerts = [dict(a, code=next((k["code"] for k in ks if k["id"] == a["kpi_id"]), ""), name=next((k["name"] for k in ks if k["id"] == a["kpi_id"]), "")) for a in db.execute("SELECT * FROM kri_alerts ORDER BY id DESC LIMIT 30")]
    cnt = {s: sum(1 for i in items if i["status"] == s) for s in ("red", "amber", "green")}
    cnt["nodata"] = sum(1 for i in items if i["status"] is None)
    return {"kris": items, "tiles": cnt, "alerts": alerts, "coverage": {"required": len(need_kri), "covered": len(need_kri) - len(missing), "missing": missing[:40]}, "can": {a: a in c.perms.get("kri_monitor", set()) for a in core.ACTIONS},
            "risks": [{"id": r["id"], "ref": r["ref"], "title": r["title"]} for r in sorted(risks.values(), key=lambda r: r["ref"] or "")]}


@router.route("POST", "/api/kri/alerts/<int:aid>/ack")
def kri_ack(req):
    c = need(req, "kri_monitor", "edit")
    a = req.db.execute("SELECT * FROM kri_alerts WHERE id=? AND status='open'", (int(req.params["aid"]),)).fetchone()
    if not a:
        raise HTTPError(404, "not_found", "No open alert with that number")
    note = need_str(req.json(), "note", "Note", 300)
    if len(note) < 5:
        raise HTTPError(400, "validation", "Say what is being done (at least 5 characters).")
    req.db.execute("UPDATE kri_alerts SET status='acknowledged', ack_by=?, ack_at=?, ack_note=? WHERE id=?", (c.user["username"], now(), note, a["id"]))
    audit(req.db, "kri.ack", c.user, "kri_monitor", "Alert %d acknowledged: %s" % (a["id"], note[:100]), req.ip)
    return {"ok": True}
