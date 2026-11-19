"""Live market data for the weekly KPIs (Step 18).

While the computer is online Sentinel fetches prices from public data services and writes them as readings marked 'live', with the source and time in the note:
  commodities  Yahoo Finance chart data (futures, the same contracts Bloomberg shows), with Stooq as the back-up
  currencies   open.er-api.com (ZiG, GBP, EUR, BWP against the US dollar)
  stablecoins  CoinGecko
  economy      World Bank (GDP, remittances: annual figures)
Only the fixed host names below are ever contacted (https, short time-out, small replies). A person's own reading for the same date is never overwritten.
Indicators that no public data service carries (ZERA fuel prices, RBZ money supply, ZIMSTAT inflation...) stay with the research suggestions and manual or file entry."""
import csv
import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import core, db as dbm, p2, web
from .api import router, need, audit
from .web import HTTPError

HOSTS = {"query1.finance.yahoo.com", "query2.finance.yahoo.com", "stooq.com", "open.er-api.com", "api.coingecko.com", "api.worldbank.org", "www.rbz.co.zw", "rbz.co.zw", "www.zera.co.zw", "zera.co.zw"}
UA = "Mozilla/5.0 (compatible; EcoCashSentinel/0.17; risk monitoring)"
MAXB = 600_000

# code -> (provider, symbol, divisor, unit, name)   (divisor turns the quote unit into the indicator's unit)
COMMODITIES = {
    "GOLD": ("GC=F", "gc.f", 1, "US$/oz", "Gold price"), "PLATINUM": ("PL=F", "pl.f", 1, "US$/oz", "Platinum price"), "PALLADIUM": ("PA=F", "pa.f", 1, "US$/oz", "Palladium price"),
    "SILVER": ("SI=F", "si.f", 1, "US$/oz", "Silver price"), "COPPER": ("HG=F", "hg.f", 1, "US$/lb", "Copper price"), "BRENT": ("BZ=F", "cb.f", 1, "US$/bbl", "Brent crude oil"),
    "WTI": ("CL=F", "cl.f", 1, "US$/bbl", "WTI crude oil"), "CORN": ("ZC=F", None, 100, "US$/bushel", "Corn (CBOT)"), "WHEAT": ("ZW=F", None, 100, "US$/bushel", "Wheat (CBOT)"),
    "COCOA": ("CC=F", None, 1, "US$/tonne", "Cocoa (ICE)"), "COTTON": ("CT=F", None, 100, "US$/lb", "Cotton (ICE)"),
}
NEW_KPIS = ["SILVER", "COPPER", "BRENT", "WTI", "CORN", "WHEAT", "COCOA", "COTTON"]  # not in the starter set: created the first time the engine runs
FX = {"FX_INTERBANK": ("ZWG", None), "FX_EUR": ("ZWG", "EUR"), "FXD_GBP": ("ZWG", "GBP"), "FXD_BWP": ("ZWG", "BWP"), "FXD_ZAR": ("ZWG", "ZAR")}
RBZ_CODES = {"FX_INTERBANK": "USD", "FX_EUR": "EUR", "FXD_GBP": "GBP", "FXD_BWP": "BWP", "FXD_ZAR": "ZAR"}  # the Reserve Bank's own daily mid rates win over the market average
FUEL = {"FUEL_PETROL": "petrol", "FUEL_DIESEL": "diesel", "FUEL_LPG": "lpg"}  # ZERA pump prices
COINS_Y = {"PEG_USDC": "USDC-USD", "PEG_USDT": "USDT-USD", "PEG_DAI": "DAI-USD", "PEG_USDP": "USDP-USD"}  # Yahoo Finance first (the closest free feed to Bloomberg), CoinGecko as the back-up
COINS = {"PEG_USDC": "usd-coin", "PEG_USDT": "tether", "PEG_DAI": "dai", "PEG_USDP": "paxos-standard"}
WB = {"GDP": ("NY.GDP.MKTP.CD", 1e9), "REMIT_FY": ("BX.TRF.PWKR.CD.DT", 1e9)}
LIVE_CODES = set(COMMODITIES) | set(FX) | set(COINS) | set(WB) | set(FUEL)
WATCH = ["GOLD", "SILVER", "PLATINUM", "COPPER", "BRENT", "FX_EUR", "PEG_USDT"]  # the market strip on Home


class LiveError(Exception):
    pass


def get(url, timeout=10, maxb=None):
    maxb = maxb or MAXB
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise LiveError("Host not approved: %s" % u.hostname)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/csv,*/*"}), timeout=timeout) as r:
            raw = r.read(maxb + 1)
    except urllib.error.HTTPError as e:
        raise LiveError("%s answered %s" % (u.hostname, e.code))
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise LiveError("%s could not be reached (%s)" % (u.hostname, getattr(e, "reason", e)))
    if len(raw) > maxb:
        raise LiveError("%s reply too large" % u.hostname)
    return raw


# ---------------------------------------------------------------- parsers (kept apart so they are tested with sample replies)
def parse_yahoo(raw):
    j = json.loads(raw.decode("utf-8"))
    res = (j.get("chart") or {}).get("result")
    if not res:
        raise LiveError("Yahoo returned no data")
    m = res[0]["meta"]
    price = m.get("regularMarketPrice")
    if price is None:
        closes = [c for c in (((res[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
        price = closes[-1] if closes else None
    if price is None:
        raise LiveError("Yahoo had no price")
    return float(price), m.get("regularMarketTime")


def parse_stooq(raw):
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))))
    if not rows or rows[0].get("Close") in (None, "", "N/D"):
        raise LiveError("Stooq had no price")
    return float(rows[0]["Close"]), None


def parse_fx(raw):
    j = json.loads(raw.decode("utf-8"))
    if j.get("result") != "success" or "rates" not in j:
        raise LiveError("Exchange-rate service returned no rates")
    return j["rates"], j.get("time_last_update_unix")


def parse_coins(raw):
    j = json.loads(raw.decode("utf-8"))
    return {k: v.get("usd") for k, v in j.items() if isinstance(v, dict) and v.get("usd") is not None}


def parse_wb(raw):
    j = json.loads(raw.decode("utf-8"))
    for d in (j[1] if isinstance(j, list) and len(j) > 1 and j[1] else []):
        if d.get("value") is not None:
            return int(d["date"]), float(d["value"])
    raise LiveError("World Bank had no value")


def parse_rbz(text):
    """RBZ daily exchange-rate sheet (text from the PDF): a currency code followed by six numbers; the last is the mid rate in ZWG. Returns {code: value}."""
    out = {}
    for line in text.splitlines():
        m = re.search(r"\b([A-Z]{3})\b(.*)", line)
        if not m or m.group(1) in out:
            continue
        nums = re.findall(r"\d[\d,]*\.\d+", m.group(2))
        if len(nums) >= 2:
            try:
                out[m.group(1)] = float((nums[5] if len(nums) >= 6 else nums[-1]).replace(",", ""))
            except ValueError:
                pass
    return out


def parse_zera(html):
    """ZERA home page: 'As Of: dd-mm-yyyy' and the Petrol, Diesel and LPG pump prices. Returns (iso date, {code: value})."""
    t = re.sub(r"<[^>]+>", " ", html); t = re.sub(r"&nbsp;|\s+", " ", t)
    m = re.search(r"As\s*Of\s*:?\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})", t, re.I)
    if not m:
        raise LiveError("ZERA page has no 'As Of' date")
    iso = "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1)))
    out = {}
    for code, word in FUEL.items():
        mm = re.search(word + r".{0,60}?(\d+\.\d+)", t, re.I)
        if mm:
            out[code] = float(mm.group(1))
    if not out:
        raise LiveError("ZERA page had no prices")
    return iso, out


def fetch_rbz(today=None):
    """Try today and the ten days before it for the Reserve Bank's daily rate sheet. Returns (iso date, {code: value})."""
    import datetime
    from . import ai_kb
    d0 = today or datetime.date.today(); last = None
    for back in range(11):
        d = d0 - datetime.timedelta(days=back)
        if d.weekday() > 4:
            continue
        for day in (str(d.day), "%02d" % d.day):
            url = "https://www.rbz.co.zw/documents/Exchange_Rates/%d/%s/RATES_%s_%s_%d.pdf" % (d.year, d.strftime("%B"), day, d.strftime("%B").upper(), d.year)
            try:
                raw = get(url, timeout=8, maxb=4_000_000)
            except LiveError as e:
                last = e; continue
            rates = parse_rbz(ai_kb.pdf_text(raw)[0])
            if rates:
                return d.isoformat(), rates
    raise LiveError("RBZ daily rate sheet not found (%s)" % (last or "no reply"))


# ---------------------------------------------------------------- fetching: returns {code: (value, as_of_text, source_text)}, errors
def fetch_all(codes=None):
    codes = set(codes or LIVE_CODES); out, errs = {}, {}
    try:  # one quick probe: when the computer is offline this ends the round in seconds instead of waiting for every service
        get("https://open.er-api.com/v6/latest/USD", timeout=6)
    except LiveError as e:
        if "could not be reached" in str(e):
            return {}, {"network": "No internet connection (%s)" % e}
    for code, (ysym, ssym, div, unit, name) in COMMODITIES.items():
        if code not in codes:
            continue
        try:
            try:
                v, ts = parse_yahoo(get("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=5d&interval=1d" % urllib.parse.quote(ysym))); src = "Yahoo Finance %s" % ysym
            except (LiveError, ValueError, KeyError) as e1:
                if not ssym:
                    raise
                v, ts = parse_stooq(get("https://stooq.com/q/l/?s=%s&f=sd2t2ohlc&h&e=csv" % ssym)); src = "Stooq %s (after: %s)" % (ssym, e1)
            out[code] = (v / div, ts, src)
        except (LiveError, ValueError, KeyError, IndexError) as e:
            errs[code] = str(e)
    if codes & set(FX):
        try:
            rates, ts = parse_fx(get("https://open.er-api.com/v6/latest/USD"))
            for code, (num, den) in FX.items():
                if code in codes and rates.get(num) and (den is None or rates.get(den)):
                    out[code] = (rates[num] / (rates[den] if den else 1), ts, "open.er-api.com")
                elif code in codes:
                    errs[code] = "rate missing in the reply"
        except (LiveError, ValueError, KeyError) as e:
            for code in FX:
                if code in codes:
                    errs[code] = str(e)
    if codes & set(RBZ_CODES):
        try:
            d, rates = fetch_rbz()
            for code, cur in RBZ_CODES.items():
                if code in codes and rates.get(cur):
                    out[code] = (rates[cur], d, "RBZ daily rates")
        except (LiveError, ValueError, KeyError, IndexError, OSError) as e:
            errs["RBZ"] = str(e)
    if codes & set(FUEL):
        try:
            d, px = parse_zera(get("https://www.zera.co.zw/").decode("utf-8", "replace"))
            for code, v in px.items():
                if code in codes:
                    out[code] = (v, d, "ZERA")
        except (LiveError, ValueError) as e:
            errs["ZERA"] = str(e)
    cs = {c: i for c, i in COINS.items() if c in codes}
    for code in list(cs):  # Yahoo Finance first
        try:
            v, ts = parse_yahoo(get("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=5d&interval=1d" % COINS_Y[code]))
            out[code] = (v, ts, "Yahoo Finance %s" % COINS_Y[code]); del cs[code]
        except (LiveError, ValueError, KeyError, IndexError):
            pass
    if cs:
        try:
            got = parse_coins(get("https://api.coingecko.com/api/v3/simple/price?ids=%s&vs_currencies=usd" % ",".join(cs.values())))
            for code, cid in cs.items():
                if cid in got:
                    out[code] = (float(got[cid]), None, "CoinGecko")
                else:
                    errs[code] = "not in the reply"
        except (LiveError, ValueError, KeyError) as e:
            for code in cs:
                errs[code] = str(e)
    for code, (ind, div) in WB.items():
        if code in codes:
            try:
                yr, v = parse_wb(get("https://api.worldbank.org/v2/country/ZWE/indicator/%s?format=json&per_page=8" % ind))
                out[code] = (v / div, "%d-12-31" % yr, "World Bank %s (%d)" % (ind, yr))
            except (LiveError, ValueError, KeyError) as e:
                errs[code] = str(e)
    return out, errs


# ---------------------------------------------------------------- writing
def ensure_kpis(db):
    n = 0
    for code in NEW_KPIS:
        if not db.execute("SELECT 1 FROM kpis WHERE code=?", (code,)).fetchone():
            y, s, d, unit, name = COMMODITIES[code]
            db.execute("INSERT INTO kpis(code,name,grp,kind,unit,freq,source,source_url,better,decimals,sort,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (code, name, "Commodities (live)", "kpi", unit, "daily", "Yahoo Finance", "https://finance.yahoo.com/quote/%s" % y, "none", 2, 900 + NEW_KPIS.index(code), core.now())); n += 1
    return n


def ensure_catalogue(db):
    """Make sure every KPI of the catalogue (kpi_seed.json, 99 indicators) exists, so none is ever missing from the weekly report. Only the definitions are added,
    never starter readings, so removed demonstration figures stay removed. A KPI a person deleted (it is kept, marked deleted) is not recreated."""
    try:
        data = json.load(open(p2.SEED_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for i, s in enumerate(data["kpis"]):
        if s.get("kind", "kpi") != "kpi" or db.execute("SELECT 1 FROM kpis WHERE code=?", (s["code"],)).fetchone():
            continue
        db.execute("INSERT INTO kpis(code,name,grp,kind,unit,freq,source,source_url,better,target,amber,red,decimals,internal_key,sort,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (s["code"], s["name"], s["grp"], "kpi", s["unit"], s["freq"], s["source"], s["source_url"], s["better"], s["target"], s["amber"], s["red"], s["decimals"], s["internal_key"], i, core.now())); n += 1
    return n


def apply(db, out, who="live-data"):
    """Write fetched values as readings. A person's reading for the same date stays; an earlier live reading for that date is updated."""
    wrote = 0
    today = str(p2.today())
    for code, (val, ts, src) in out.items():
        k = db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", (code,)).fetchone()
        if not k:
            continue
        period = ts if (isinstance(ts, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", ts)) else today
        old = db.execute("SELECT method FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], period)).fetchone()
        if old and old["method"] not in ("live", "seed"):
            continue
        note = "Live: %s at %s" % (src, core.now()[:16])
        if old and old["method"] == "seed":
            db.execute("DELETE FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], period))
        p2.put_reading(db, k, period, round(val, 6), "live", note, who)
        p2.check_alerts(db, k, who)
        wrote += 1
    return wrote


PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_update_pack.json")


def load_pack(db, who="update-pack"):
    """Load the dated update pack (figures read from the published sources on 17 Nov 2026) as one deletable, restorable import batch. Done once:
    if the batch exists (even deleted) nothing is loaded again. A person's own or live reading is never replaced; a starter-set value is."""
    if not os.path.exists(PACK):
        return None
    pk = json.load(open(PACK, encoding="utf-8"))
    if db.execute("SELECT 1 FROM kpi_imports WHERE filename=?", (pk["name"],)).fetchone():
        return None
    bid = db.execute("INSERT INTO kpi_imports(ts,username,kind,filename,rows_new,rows_replaced) VALUES(?,?,?,?,0,0)", (core.now(), who, "kpi", pk["name"])).lastrowid
    new = rep = 0; undo = []; n = 0
    for e in pk["kpis"]:
        k = db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", (e["code"],)).fetchone()
        if not k and e.get("name"):
            db.execute("INSERT INTO kpis(code,name,grp,kind,unit,freq,source,better,decimals,sort,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (e["code"], e["name"], e.get("grp"), "kpi", e.get("unit"), e.get("freq", "monthly"), e.get("source"), e.get("better", "none"), e.get("decimals", 2), 950 + n, core.now())); n += 1
            k = db.execute("SELECT * FROM kpis WHERE code=?", (e["code"],)).fetchone()
        if not k:
            continue
        for period, val in e["readings"]:
            old = db.execute("SELECT value, method, note, entered_by, created_at FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], period)).fetchone()
            if old and old["method"] not in ("seed",):
                continue
            if old:
                undo.append([k["id"], period, old["value"], old["method"], old["note"], old["entered_by"], old["created_at"]]); rep += 1
                db.execute("DELETE FROM kpi_readings WHERE kpi_id=? AND period=?", (k["id"], period))
            else:
                new += 1
            p2.put_reading(db, k, period, val, "import", e.get("note") or pk["name"], who)
            db.execute("UPDATE kpi_readings SET import_id=? WHERE kpi_id=? AND period=?", (bid, k["id"], period))
    links = pk.get("links", {})
    for k in db.execute("SELECT id,code,internal_key FROM kpis WHERE deleted_at IS NULL").fetchall():
        if k["internal_key"] or k["code"] in COMMODITIES:
            continue
        best = max((p for p in links if k["code"].startswith(p)), key=len, default=None)
        if best:
            db.execute("UPDATE kpis SET source_url=? WHERE id=?", (links[best], k["id"]))
    db.execute("UPDATE kpi_imports SET rows_new=?, rows_replaced=?, undo=? WHERE id=?", (new, rep, json.dumps(undo), bid))
    return {"new": new, "replaced": rep}


@router.route("POST", "/api/kpi/pack/load")
def pack_load(req):
    c = need(req, "weekly_kpi", "create")
    ensure_catalogue(req.db)
    r = load_pack(req.db, c.user["username"])
    audit(req.db, "kpi.pack", c.user, "weekly_kpi", "Update pack loaded: %s" % (r or "already loaded"), req.ip)
    return {"loaded": bool(r), **(r or {})}


_LOCK = threading.Lock()


def status(db):
    r = db.execute("SELECT value FROM settings WHERE key='live_status'").fetchone()
    return json.loads(r["value"]) if r else {"online": None, "last_ok": None, "last_try": None, "updated": 0, "errors": {}}


def mode(db):
    r = db.execute("SELECT value FROM settings WHERE key='kpi_live_mode'").fetchone()
    return r["value"] if r else "on"


def refresh(codes=None, who="live-data"):
    """Fetch (no database lock held), then write. Safe to call from a thread. Returns the status dict."""
    from . import web
    if not _LOCK.acquire(blocking=False):
        c = dbm.connect()
        try:
            return status(c)
        finally:
            c.close()
    try:
        out, errs = fetch_all(codes)
        c = dbm.connect()
        try:
            with web.hold("live_data #1"):
                ensure_kpis(c)
                ensure_catalogue(c)
                load_pack(c)
                out2 = out
                n = apply(c, out2, who)
                st = status(c); online = bool(out)
                st.update({"online": online, "last_try": core.now(), "updated": n, "errors": errs, "fetched": len(out)})
                if online:
                    st["last_ok"] = core.now()
                c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('live_status',?)", (json.dumps(st),))
                c.commit()
            return st
        finally:
            c.close()
    finally:
        _LOCK.release()


def loop():
    """Started with the server. Online and healthy: refresh about every 30 minutes. Offline: look again every 90 seconds, so figures appear soon after the laptop connects."""
    time.sleep(45)  # let sign-in and the first pages load before any background work
    while True:
        wait = 90
        try:
            c = dbm.connect()
            try:
                on, st = mode(c) != "off", status(c)
            finally:
                c.close()
            if on:
                last = st.get("last_ok")
                due = (not last) or (time.time() - time.mktime(time.strptime(last[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))) > 1800 or not st.get("online")
                if due:
                    st = refresh()
                wait = 1800 if st.get("online") else 90
        except Exception:
            wait = 90
        time.sleep(wait)


# ---------------------------------------------------------------- endpoints
@router.route("GET", "/api/kpi/live")
def live_status(req):
    c = need(req, "weekly_kpi")
    st = status(req.db)
    st["mode"] = mode(req.db)
    st["codes"] = sorted(LIVE_CODES)
    st["can"] = {"run": "create" in c.perms.get("weekly_kpi", set()), "approve": "approve" in c.perms.get("weekly_kpi", set())}
    return st


@router.route("POST", "/api/kpi/live/run")
def live_run(req):
    c = need(req, "weekly_kpi", "create")
    req.db.commit()
    st = refresh(who=c.user["username"])
    with web.hold("live_data #2"):
        audit(req.db, "kpi.live", c.user, "weekly_kpi", "Live data refresh: %d updated, %d unavailable" % (st.get("updated", 0), len(st.get("errors", {}))), req.ip)
        req.db.commit()
    return st


live_run.nolock = True


@router.route("POST", "/api/kpi/live/kick")
def live_kick(req):
    """Called when the Weekly KPI page opens: starts a refresh in the background when the data is more than 10 minutes old, and returns at once."""
    need(req, "weekly_kpi")
    st = status(req.db)
    last = st.get("last_ok")
    old = (not last) or (time.time() - time.mktime(time.strptime(last[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))) > 600
    if old and mode(req.db) != "off":
        threading.Thread(target=refresh, daemon=True).start()
    return {"started": bool(old)}


@router.route("PUT", "/api/kpi/live/mode")
def live_mode(req):
    c = need(req, "weekly_kpi", "approve")
    m = req.json().get("mode")
    if m not in ("on", "off"):
        raise HTTPError(400, "validation", "Mode must be on or off.")
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kpi_live_mode',?)", (m,))
    audit(req.db, "kpi.live_mode", c.user, "weekly_kpi", "Live data mode: " + m, req.ip)
    return {"mode": m}


@router.route("GET", "/api/home/market")
def home_market(req):
    c = need(req)
    if not (c.perms.get("weekly_kpi") or c.perms.get("command_center")):
        raise HTTPError(403, "forbidden", "You do not have permission to do this.")
    out = []
    for code in WATCH:
        k = req.db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", (code,)).fetchone()
        if not k:
            continue
        rs = [dict(r) for r in req.db.execute("SELECT period,value,method FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 24", (k["id"],))][::-1]
        if not rs:
            continue
        last, prev = rs[-1], (rs[-2] if len(rs) > 1 else None)
        out.append({"code": code, "name": k["name"], "unit": k["unit"], "value": last["value"], "period": last["period"], "method": last["method"], "change_pct": round(100 * (last["value"] - prev["value"]) / prev["value"], 2) if prev and prev["value"] else None,
                    "spark": [r["value"] for r in rs], "decimals": k["decimals"]})
    return {"items": out, "status": status(req.db)}


@router.route("GET", "/api/health")
def health(req):
    """No sign-in needed: shows which copy of Sentinel is answering and whether a background task is making others wait."""
    from . import config, web
    since = web.LOCK_INFO.get("since")
    return {"ok": True, "version": config.VERSION, "pid": os.getpid(), "started": STARTED,
            "write_lock_held_by": web.LOCK_INFO.get("who"), "held_seconds": round(time.time() - since, 1) if since else 0}


STARTED = time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- report readiness: what is live, what waits for a release, what needs a person
LIMIT = {"daily": 4, "weekly": 10, "monthly": 50, "quarterly": 115, "annual": 400}


def readiness(db):
    today = p2.today()
    out = {"live": [], "published": [], "internal": [], "start": None}
    r = db.execute("SELECT value FROM settings WHERE key='kpi_report_start'").fetchone()
    out["start"] = r["value"] if r else None
    for k in db.execute("SELECT id,code,name,grp,freq,internal_key,source FROM kpis WHERE kind='kpi' AND active=1 AND deleted_at IS NULL ORDER BY sort,id"):
        last = db.execute("SELECT period,method FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
        age = (today - p2.pdate(last["period"])).days if last else None
        row = {"code": k["code"], "name": k["name"], "grp": k["grp"], "last": last["period"] if last else None, "age": age, "source": k["source"]}
        if k["code"] in LIVE_CODES:
            row["fresh"] = age is not None and age <= 3; out["live"].append(row)
        elif k["internal_key"] or (k["source"] or "").lower().startswith(("ecocash", "sentinel", "internal", "operations")):
            row["fresh"] = age is not None and age <= LIMIT.get(k["freq"], 50); out["internal"].append(row)
        else:
            row["fresh"] = age is not None and age <= LIMIT.get(k["freq"], 50); out["published"].append(row)
    return out


@router.route("GET", "/api/kpi/readiness")
def readiness_get(req):
    c = need(req, "weekly_kpi")
    d = readiness(req.db); d["today"] = str(p2.today()); d["can"] = {"run": "create" in c.perms.get("weekly_kpi", set())}
    return d


@router.route("POST", "/api/kpi/bring-up-to-date")
def bring_up_to_date(req):
    """One press: fetch every live figure now and start the report from today. Internal measures stay manual; published statistics appear as their sources release them."""
    c = need(req, "weekly_kpi", "create")
    req.db.commit()
    st = refresh(who=c.user["username"])
    with web.hold("live_data bring-up"):
        if not req.db.execute("SELECT 1 FROM settings WHERE key='kpi_report_start'").fetchone():
            req.db.execute("INSERT INTO settings(key,value) VALUES('kpi_report_start',?)", (str(p2.today()),))
        audit(req.db, "kpi.bring_up", c.user, "weekly_kpi", "Report brought up to date: %d live figures updated, %d unavailable" % (st.get("updated", 0), len(st.get("errors", {}))), req.ip)
        req.db.commit()
    d = readiness(req.db); d["status"] = st; d["today"] = str(p2.today())
    return d


bring_up_to_date.nolock = True
