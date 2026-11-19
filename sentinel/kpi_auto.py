"""Weekly KPI automatic updates by research (Step 17).

For every active indicator that has a published source (the links in KPI_LINKS), Sentinel opens that source page, and if needed searches the web, and looks for the
latest figure next to the indicator's own words. A figure is only ever taken from a page that was read, and every reading carries the page address and the sentence it came from.
Mode (set by the administrator of the module):  auto = enter the reading and mark it 'web' so a person can confirm it; review = keep it as a suggestion until someone accepts it."""
import json
import re

from . import core, db as dbm, p2, web
from .api import router, need, audit
from .web import HTTPError

NUM = re.compile(r"(?<![\w.])(-?\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(%|percent|million|billion|bn|m\b|k\b)?", re.I)
STOP = {"the", "and", "of", "for", "vs", "by", "in", "to", "a", "report", "quarterly", "monthly", "daily", "weekly", "level", "levels", "value", "values"}

DDL = """CREATE TABLE IF NOT EXISTS kpi_suggest(id INTEGER PRIMARY KEY AUTOINCREMENT, kpi_id INTEGER NOT NULL, period TEXT NOT NULL, value REAL NOT NULL, source_url TEXT, snippet TEXT,
  found_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', decided_by TEXT, decided_at TEXT, UNIQUE(kpi_id, period, value))"""


def ensure(db):
    db.execute(DDL)


def mode(db):
    r = db.execute("SELECT value FROM settings WHERE key='kpi_auto_mode'").fetchone()
    return r["value"] if r else "review"


def words(name):
    return [w for w in re.findall(r"[a-z]{3,}", (name or "").lower()) if w not in STOP]


def to_float(txt, unit):
    v = float(re.sub(r"[,\s]", "", txt))
    u = (unit or "").lower()
    return v * {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "k": 1e3}.get(u, 1)


def extract(text, name, unit_hint=None):
    """Best figure for an indicator in a page of text: sentences holding most of the indicator's words and a number. Returns (value, sentence) or None."""
    ws = words(name)
    if not ws:
        return None
    best = None
    for sent in re.split(r"(?<=[.!?\n])\s+", text or ""):
        s = sent.strip()
        if not (20 <= len(s) <= 400):
            continue
        low = s.lower()
        hit = sum(1 for w in ws if w in low)
        if hit < max(1, (len(ws) + 1) // 2):
            continue
        nums = [m for m in NUM.finditer(s) if not re.match(r"^(19|20)\d\d$", m.group(1))]  # a year is not a figure
        if not nums:
            continue
        m = nums[0]
        try:
            val = to_float(m.group(1), None if (m.group(2) or "").lower() in ("%", "percent") else m.group(2))
        except ValueError:
            continue
        score = hit / len(ws) + (0.15 if m.group(2) else 0)
        if best is None or score > best[0]:
            best = (score, val, s)
    return (best[1], best[2]) if best else None


import contextlib


@contextlib.contextmanager
def _tx(db):
    """Short write: takes the server's write lock only for the few statements, never while waiting on the internet.
    If the caller already has a transaction open (a request handler), it stays the caller's."""
    from . import web
    if db.in_transaction:
        yield
        return
    with web.hold("kpi_auto #1"):
        db.execute("BEGIN IMMEDIATE")
        try:
            yield
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def research_one(db, k, who="system"):
    """Returns (status, message). Never raises: a site that is down is a normal event."""
    from . import ai_web
    ensure(db)
    pages = []
    try:
        if k["source_url"]:
            pages.append(ai_web.read_page(db, k["source_url"], allow_unlisted=True))
    except Exception as e:
        err = str(e)
    else:
        err = ""
    found = extract(" ".join(p["text"] for p in pages), k["name"]) if pages else None
    url = pages[0]["url"] if pages and found else None
    if not found:
        try:
            for r in ai_web.search(db, "%s %s Zimbabwe latest" % (k["name"], k["source"] or ""), 4, use_cache=True)["results"]:
                try:
                    pg = ai_web.read_page(db, r["url"], allow_unlisted=False)
                except Exception:
                    continue
                found = extract(pg["text"], k["name"])
                if found:
                    url = pg["url"]; break
        except Exception as e:
            err = err or str(e)
    if not found:
        return "none", err or "No figure for this indicator was found on the source page or in a search."
    val, sent = found
    period = str(p2.today())
    with _tx(db):
        cur = db.execute("SELECT 1 FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], period)).fetchone()
        if cur:
            return "same", "A reading for %s already exists." % period
        db.execute("INSERT OR IGNORE INTO kpi_suggest(kpi_id,period,value,source_url,snippet,found_at) VALUES(?,?,?,?,?,?)", (k["id"], period, val, url, sent[:300], core.now()))
        sid = db.execute("SELECT id FROM kpi_suggest WHERE kpi_id=? AND period=? AND value=?", (k["id"], period, val)).fetchone()["id"]
        if mode(db) == "auto":
            accept(db, sid, "auto")
            return "entered", "%s" % val
    return "suggested", "%s (waiting for a person to accept)" % val


def accept(db, sid, who):
    s = db.execute("SELECT * FROM kpi_suggest WHERE id=?", (sid,)).fetchone()
    if not s or s["status"] != "pending":
        raise HTTPError(409, "state", "That suggestion has already been decided.")
    k = db.execute("SELECT * FROM kpis WHERE id=?", (s["kpi_id"],)).fetchone()
    p2.put_reading(db, k, s["period"], s["value"], "web", "Found by research: %s | %s" % (s["source_url"] or "", (s["snippet"] or "")[:160]), who)
    p2.check_alerts(db, k, who)
    db.execute("UPDATE kpi_suggest SET status='accepted', decided_by=?, decided_at=? WHERE id=?", (who, core.now(), sid))


def run(db, who="system", only=None):
    ensure(db)
    out = []
    from . import live_data
    try:
        live_data.get("https://open.er-api.com/v6/latest/USD", timeout=6)  # offline: do not try ninety pages one after another
    except live_data.LiveError as e:
        if "could not be reached" in str(e):
            return [{"code": "-", "status": "none", "message": "No internet connection"}]
    for k in db.execute("SELECT * FROM kpis WHERE active=1 AND deleted_at IS NULL AND feed_url IS NULL AND internal_key IS NULL AND kind='kpi' AND (source_url IS NOT NULL OR source IS NOT NULL) ORDER BY sort,id").fetchall():
        if only and k["id"] not in only:
            continue
        from . import live_data
        if k["code"] in live_data.LIVE_CODES:
            continue
        st, msg = research_one(db, k, who)
        with _tx(db):
            db.execute("INSERT INTO kpi_feed_log(ts,kpi_id,ok,message) VALUES(?,?,?,?)", (core.now(), k["id"], int(st in ("entered", "suggested", "same")), "Research: " + msg[:200]))
        out.append({"code": k["code"], "status": st, "message": msg})
    with _tx(db):
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kpi_auto_last',?)", (json.dumps({"ts": core.now(), "tried": len(out), "entered": sum(1 for x in out if x["status"] == "entered"), "suggested": sum(1 for x in out if x["status"] == "suggested")}),))
    return out


def run_free(who="system", only=None):
    """Research with its own connection, in autocommit: nothing is locked while pages are downloaded."""
    c = dbm.connect(); c.isolation_level = None
    try:
        return run(c, who, only)
    finally:
        c.close()


@router.route("GET", "/api/kpi/auto")
def auto_status(req):
    c = need(req, "weekly_kpi")
    ensure(req.db)
    last = req.db.execute("SELECT value FROM settings WHERE key='kpi_auto_last'").fetchone()
    sug = [dict(r) for r in req.db.execute("SELECT s.*, k.code, k.name FROM kpi_suggest s JOIN kpis k ON k.id=s.kpi_id WHERE s.status='pending' ORDER BY s.id DESC LIMIT 100")]
    n = req.db.execute("SELECT COUNT(*) n FROM kpis WHERE active=1 AND deleted_at IS NULL AND feed_url IS NULL AND kind='kpi' AND internal_key IS NULL AND (source_url IS NOT NULL OR source IS NOT NULL)").fetchone()["n"]
    return {"mode": mode(req.db), "last": json.loads(last["value"]) if last else None, "suggestions": sug, "watched": n, "can": {"run": "create" in c.perms.get("weekly_kpi", set()), "approve": "approve" in c.perms.get("weekly_kpi", set())}}


@router.route("POST", "/api/kpi/auto/run")
def auto_run(req):
    c = need(req, "weekly_kpi", "create")
    req.db.commit()
    res = run_free(c.user["username"])
    with web.hold("kpi_auto #2"):
        _audit_run(req, c, res)
    return {"results": res}


auto_run.nolock = True


def _audit_run(req, c, res):
    audit(req.db, "kpi.auto", c.user, "weekly_kpi", "Research update: %d indicator(s) tried, %d entered" % (len(res), sum(1 for x in res if x["status"] == "entered")), req.ip)
    req.db.commit()


@router.route("PUT", "/api/kpi/auto/mode")
def auto_mode(req):
    c = need(req, "weekly_kpi", "approve")
    m = req.json().get("mode")
    if m not in ("auto", "review", "off"):
        raise HTTPError(400, "validation", "Mode must be auto, review or off.")
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kpi_auto_mode',?)", (m,))
    audit(req.db, "kpi.auto_mode", c.user, "weekly_kpi", "Research update mode: " + m, req.ip)
    return {"mode": m}


@router.route("POST", "/api/kpi/auto/<int:sid>/<act>")
def auto_decide(req):
    c = need(req, "weekly_kpi", "create")
    sid, act = int(req.params["sid"]), req.params["act"]
    if act == "accept":
        accept(req.db, sid, c.user["username"])
    elif act == "reject":
        req.db.execute("UPDATE kpi_suggest SET status='rejected', decided_by=?, decided_at=? WHERE id=? AND status='pending'", (c.user["username"], core.now(), sid))
    else:
        raise HTTPError(404, "not_found", "Unknown action")
    return {"ok": True}


def daily():
    """Once a day, outside any lock (called by the server's daily loop)."""
    c = dbm.connect(); c.isolation_level = None
    try:
        if mode(c) == "off":
            return
        on = c.execute("SELECT value FROM settings WHERE key='kpi_auto_daily'").fetchone()
        if not on or on["value"] != "on":  # heavy page-reading research is started by a person (Update now); the light price feeds are the automatic part
            return
        r = c.execute("SELECT value FROM settings WHERE key='kpi_auto_day'").fetchone()
        if r and r["value"] == str(p2.today()):
            return
        run(c)
        with _tx(c):
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kpi_auto_day',?)", (str(p2.today()),))
    finally:
        c.close()


# ---- demonstration data: load / remove (System Administrator)
@router.route("GET", "/api/admin/demo")
def demo_state(req):
    need(req, "administration")
    r = req.db.execute("SELECT value FROM settings WHERE key='demo_loaded'").fetchone()
    return {"loaded": r["value"] if r else None}


@router.route("POST", "/api/admin/demo/<act>")
def demo_act(req):
    c = need(req, "administration", "create")
    from . import demo_seed
    if req.params["act"] == "load":
        n = demo_seed.load(req.db)
    elif req.params["act"] == "remove":
        n = demo_seed.remove(req.db)
    else:
        raise HTTPError(404, "not_found", "Unknown action")
    audit(req.db, "admin.demo", c.user, "administration", "Demonstration data %s: %d records" % (req.params["act"], n), req.ip)
    return {"records": n}


@router.route("GET", "/api/admin/build")
def build_state(req):
    """Which modules are live and which build stage each belongs to: shown only to the System Administrator, never on the user pages."""
    need(req, "administration")
    from .api import CATALOG
    live = [{"key": m["key"], "name": m["name"], "suite": m["suite"], "phase": m["phase"], "live": m["key"] in core.LIVE} for m in CATALOG["modules"]]
    return {"modules": live, "live": sum(1 for m in live if m["live"]), "total": len(live)}
