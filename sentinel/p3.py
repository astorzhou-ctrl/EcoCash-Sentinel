"""Step 6: report charts and their layout, the PowerPoint download, and upload of internal transaction data."""
import csv
import datetime
import io
import json
import re

from . import core, db as dbm, p2, pptx_writer, xlsx
from .api import router, need, need_str, DATE_RE
from .core import audit, now
from .p2 import put_reading, check_alerts, status_of, recent, kpi_weekly, xlsx_response, parse_date, read_table
from .web import HTTPError, Response

CTYPES = ("column", "bar", "line", "area")
MODES = ("series", "snapshot", "txn")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PRODUCTS = {"BILL": "Bill payment", "B2W": "Bank to wallet", "MERCHANT": "Merchant payment", "BALANCE": "Balance enquiry", "RECHARGE_SELF": "Recharge self", "SEND_OTHERS": "Send money (others)", "SEND_MOBILE": "Send to mobile", "SEND_BANK": "Send to bank", "ZESA": "ZESA payment"}
ALIAS = {"bill payment": "BILL", "bill": "BILL", "bank to wallet": "B2W", "b2w": "B2W", "merchant payment": "MERCHANT", "merchant": "MERCHANT", "balance enquiry": "BALANCE", "balance": "BALANCE", "recharge self": "RECHARGE_SELF", "recharge": "RECHARGE_SELF",
         "send money": "SEND_OTHERS", "send money (others)": "SEND_OTHERS", "send money others": "SEND_OTHERS", "send to mobile": "SEND_MOBILE", "send to bank": "SEND_BANK", "zesa payment": "ZESA", "zesa": "ZESA"}
SHORT = {"INF_USD_M": "USD overall", "INF_USD_FOOD": "Food", "INF_USD_NONFOOD": "Non-food", "INF_ZWG_M": "ZWG", "PLATINUM": "Platinum", "PALLADIUM": "Palladium", "GOLD": "Gold", "FUEL_PETROL": "Petrol", "FUEL_DIESEL": "Diesel", "EXPORTS": "Exports", "IMPORTS": "Imports",
         "ZSE_CAP": "ZSE", "VFEX_CAP": "VFEX", "FX_INTERBANK": "Official interbank rate", "FX_PARALLEL": "Parallel market rate", "FXD_USD": "USD", "FXD_GBP": "GBP", "FXD_BWP": "BWP", "M1": "M1 (narrow money)", "M2": "M2 (broad money)", "M3": "M3 (broad money)",
         "POLICY_RATE": "Bank policy rate", "LENDING_RATE": "Average lending rate", "PEG_USDC": "USDC", "PEG_USDT": "USDT", "PEG_DAI": "DAI", "PEG_USDP": "USDP", "MM_LINES_ECONET": "Econet", "MM_LINES_NETONE": "NetOne", "MM_LINES_TELECEL": "Telecel",
         "MM_SHARE_ECONET": "Econet", "MM_SHARE_NETONE": "NetOne", "MM_SHARE_TELECEL": "Telecel", "MM_VOL_SHARE": "Volumes", "MM_VAL_SHARE": "Values", "MERCHANTS": "Mobile banking merchants", "POS": "POS devices", "OTP_FRAUD": "OTP fraud cases", "SIM_SWAP": "SIM-swap cases",
         "CROP_MAIZE": "Maize", "CROP_TOBACCO": "Tobacco", "CROP_SORGHUM": "Sorghum", "CROP_SOYABEANS": "Soyabeans", "CROP_COTTON": "Cotton", "NPL": "NPL ratio", "CAR": "Capital adequacy ratio", "USD_SETTLE": "USD share"}
DEFAULT_CHARTS = [  # (group, title, type, mode, codes, periods)
    ("Inflation and prices", "Month on month USD inflation (%)", "column", "series", ["INF_USD_M", "INF_USD_FOOD", "INF_USD_NONFOOD"], 12),
    ("Inflation and prices", "USD and ZWG month on month inflation (%)", "line", "series", ["INF_USD_M", "INF_ZWG_M"], 12),
    ("Inflation and prices", "Precious metal prices (US$/oz)", "line", "series", ["PLATINUM", "PALLADIUM", "GOLD"], 9),
    ("Energy and fuel", "Fuel pump prices (US$/litre)", "column", "series", ["FUEL_PETROL", "FUEL_DIESEL"], 9),
    ("Energy and fuel", "Electricity generation and demand (MW)", "bar", "snapshot", ["POWER_GEN", "POWER_DEMAND"], 1),
    ("Energy and fuel", "Fuel consumption growth year on year (%)", "column", "snapshot", ["FUELQ_DIESEL", "FUELQ_JETA1", "FUELQ_LPG", "FUELQ_PETROL"], 1),
    ("Energy and fuel", "Imports and exports (US$ bn)", "column", "series", ["EXPORTS", "IMPORTS"], 5),
    ("Currency and markets", "ZSE vs VFEX market capitalisation (US$ bn)", "column", "series", ["ZSE_CAP", "VFEX_CAP"], 8),
    ("Currency and markets", "Interbank vs parallel market rate (ZWG per US$1)", "line", "series", ["FX_INTERBANK", "FX_PARALLEL"], 12),
    ("Currency and markets", "ZiG per US dollar and pound (daily)", "line", "series", ["FXD_USD", "FXD_GBP"], 8),
    ("Currency and markets", "Parallel market premium over interbank (%)", "line", "series", ["FX_PREMIUM"], 12),
    ("Money and credit", "Money in circulation (ZWG million)", "column", "series", ["M1", "M2", "M3"], 5),
    ("Money and credit", "Non-performing loans ratio (%)", "line", "series", ["NPL"], 12),
    ("Money and credit", "Policy and average lending rate (%)", "line", "series", ["POLICY_RATE", "LENDING_RATE"], 5),
    ("Money and credit", "Stablecoin prices (US$)", "line", "series", ["PEG_USDC", "PEG_USDT", "PEG_DAI", "PEG_USDP"], 7),
    ("Payments sector", "Active mobile money lines", "column", "series", ["MM_LINES_ECONET", "MM_LINES_NETONE", "MM_LINES_TELECEL"], 5),
    ("Payments sector", "Mobile money market share (%)", "column", "series", ["MM_SHARE_ECONET", "MM_SHARE_NETONE", "MM_SHARE_TELECEL"], 5),
    ("Payments sector", "Mobile money share of payment volume and value (%)", "line", "series", ["MM_VOL_SHARE", "MM_VAL_SHARE"], 5),
    ("Payments sector", "Mobile banking merchants and POS devices", "column", "series", ["MERCHANTS", "POS"], 3),
    ("Economy and society", "GDP (US$ bn)", "column", "series", ["GDP"], 5),
    ("Economy and society", "Employment levels (% of employment)", "column", "snapshot", ["EMP_FORMAL", "EMP_INFORMAL", "EMP_HOUSEHOLD", "EMP_AGRICULTURE"], 1),
    ("Economy and society", "Agricultural produce (tonnes)", "column", "series", ["CROP_MAIZE", "CROP_TOBACCO", "CROP_SORGHUM", "CROP_SOYABEANS", "CROP_COTTON"], 2),
    ("Fraud and security", "OTP-fraud and SIM-swap cases per week", "column", "series", ["OTP_FRAUD", "SIM_SWAP"], 8),
    ("Fraud and security", "Share of transactions settled in USD (%)", "column", "series", ["USD_SETTLE"], 5),
    ("Fraud and security", "Sector capital adequacy ratio (%)", "line", "series", ["CAR"], 10),
    ("Transaction health", "Weekly transaction success rate by product vs target (%)", "bar", "snapshot", ["TXN_" + c for c in PRODUCTS], 1),
    ("Transaction health", "Daily transactions: Bill payment", "line", "txn", ["BILL"], 14), ("Transaction health", "Daily transactions: Bank to wallet", "line", "txn", ["B2W"], 14),
    ("Transaction health", "Daily transactions: Merchant payment", "line", "txn", ["MERCHANT"], 14), ("Transaction health", "Daily transactions: Balance enquiry", "line", "txn", ["BALANCE"], 14)]


def ensure_charts(db, reset_group=None):
    if reset_group:
        db.execute("DELETE FROM kpi_charts WHERE grp=?", (reset_group,))
    elif db.execute("SELECT 1 FROM kpi_charts").fetchone():
        return
    have = {r["grp"] for r in db.execute("SELECT DISTINCT grp FROM kpi_charts")}
    for i, (g, t, ty, mo, codes, per) in enumerate(DEFAULT_CHARTS):
        if (reset_group and g == reset_group) or (not reset_group and g not in have):
            db.execute("INSERT INTO kpi_charts(grp,title,ctype,mode,codes,periods,sort) VALUES(?,?,?,?,?,?,?)", (g, t, ty, mo, json.dumps(codes), per, i))


def label(period, freq):
    d = datetime.date.fromisoformat(period)
    if freq == "annual":
        return str(d.year)
    if freq == "quarterly":
        return "Q%d %d" % ((d.month - 1) // 3 + 1, d.year)
    if freq == "monthly":
        return "%s-%02d" % (MONTHS[d.month - 1], d.year % 100)
    return "%d %s" % (d.day, MONTHS[d.month - 1])


def fmt_for(ks, vals):
    big = max([abs(v) for v in vals if v is not None] or [0])
    if ks and ks[0]["unit"] == "%":
        return "0.0"
    return "#,##0" if big >= 1000 else ("0." + "0" * min(ks[0]["decimals"] if ks else 2, 3)) if ks and ks[0]["decimals"] else "0"


def build_chart(db, ch, as_of):
    codes = json.loads(ch["codes"])
    out = {"id": ch["id"], "grp": ch["grp"], "title": ch["title"], "ctype": ch["ctype"], "mode": ch["mode"], "codes": codes, "periods": ch["periods"], "cats": [], "series": [], "fmt": "General", "empty": True}
    if ch["mode"] == "txn":
        rows = db.execute("SELECT day, ts, tf, ta FROM txn_daily WHERE product=? AND day<=? ORDER BY day DESC LIMIT ?", (codes[0], as_of, ch["periods"])).fetchall()[::-1]
        if rows:
            out["cats"] = [label(r["day"], "daily") for r in rows]
            out["series"] = [{"name": "Successful", "values": [r["ts"] for r in rows], "color": "1BA94C"}, {"name": "Failed", "values": [r["tf"] for r in rows], "color": "E4202E"}] + ([{"name": "Other", "values": [r["ta"] for r in rows], "color": "F58220"}] if any(r["ta"] for r in rows) else [])
            out.update(fmt="#,##0", empty=False)
        return out
    ks = [k for c in codes for k in [db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", (c,)).fetchone()] if k]
    if not ks:
        return out
    rec = recent(db, [k["id"] for k in ks], as_of, max(ch["periods"], 2) + 40)
    if ch["mode"] == "snapshot":
        pts = [(k, rec[k["id"]][0]) for k in ks if rec.get(k["id"])]
        if pts:
            out["cats"] = [re.sub(r"^(Transaction success rate|Fuel consumption growth year on year|Employment share|Local power generation|Power generation|Power demand):\s*", "", k["name"]) if ":" in k["name"] else k["name"].replace("Local power generation", "Generation").replace("Power demand", "Demand") for k, _ in pts]
            out["series"] = [{"name": "Latest", "values": [r["value"] for _, r in pts]}]
            if any(k["target"] is not None for k, _ in pts):
                out["series"].append({"name": "Target", "values": [k["target"] for k, _ in pts], "color": "E4202E"})
            out.update(fmt=fmt_for([k for k, _ in pts], [r["value"] for _, r in pts]), empty=False)
        return out
    periods = sorted({r["period"] for k in ks for r in rec.get(k["id"], [])})[-ch["periods"]:]
    if not periods:
        return out
    out["cats"] = [label(p, ks[0]["freq"]) for p in periods]
    allv = []
    for k in ks:
        by = {r["period"]: r["value"] for r in rec.get(k["id"], [])}
        vals = [by.get(p) for p in periods]; allv += vals
        out["series"].append({"name": SHORT.get(k["code"]) or k["name"][:34], "code": k["code"], "values": vals})
    if len(ks) == 1 and ks[0]["target"] is not None and ch["ctype"] == "line":
        out["series"].append({"name": "Benchmark" if ks[0]["better"] == "down" else "Minimum", "values": [ks[0]["target"]] * len(periods), "dashed": True, "color": "E4202E"})
    out.update(fmt=fmt_for(ks, allv), empty=False)
    return out


def charts_for(db, as_of):
    ensure_charts(db)
    lay = {r["grp"]: r["per_slide"] for r in db.execute("SELECT grp, per_slide FROM kpi_layout")}
    groups = {}
    for ch in db.execute("SELECT * FROM kpi_charts WHERE active=1 ORDER BY sort, id"):
        groups.setdefault(ch["grp"], []).append(build_chart(db, ch, as_of))
    return groups, lay


@router.route("GET", "/api/kpi/charts")
def kpi_charts(req):
    c = need(req, "weekly_kpi", "view")
    ensure_charts(req.db)
    as_of = (req.query.get("as_of") or "").strip()
    if not DATE_RE.match(as_of):
        as_of = req.db.execute("SELECT MAX(r.period) m FROM kpi_readings r JOIN kpis k ON k.id=r.kpi_id WHERE k.kind='kpi' AND r.period<=?", (str(dbm.today()),)).fetchone()["m"] or str(dbm.today())
    groups, lay = charts_for(req.db, as_of)
    order = [g for g in p2.GROUP_ORDER if g in groups] + sorted(g for g in groups if g not in p2.GROUP_ORDER)
    return {"as_of": as_of, "groups": [{"name": g, "per_slide": lay.get(g, 4), "charts": groups[g]} for g in order], "ctypes": CTYPES, "modes": MODES, "products": PRODUCTS,
            "kpis": [dict(code=k["code"], name=k["name"], grp=k["grp"], unit=k["unit"]) for k in req.db.execute("SELECT code, name, grp, unit FROM kpis WHERE kind='kpi' AND deleted_at IS NULL ORDER BY grp, name")],
            "can": {a: a in c.perms.get("weekly_kpi", set()) for a in core.ACTIONS}}


def clean_chart(d):
    codes = d.get("codes") or []
    if not isinstance(codes, list) or not 1 <= len(codes) <= 9 or not all(re.match(r"^[A-Za-z0-9_]{1,40}$", str(c)) for c in codes):
        raise HTTPError(400, "validation", "Choose between 1 and 9 indicators for the chart.")
    ct, mo = (d.get("ctype") or "column"), (d.get("mode") or "series")
    if ct not in CTYPES or mo not in MODES:
        raise HTTPError(400, "validation", "Choose the chart type and what it shows from the lists.")
    per = int(p2.fnum(d.get("periods", 12), "Number of periods", False, 1, 60) or 12)
    return {"grp": need_str(d, "grp", "Group", 80), "title": need_str(d, "title", "Title", 120), "ctype": ct, "mode": mo, "codes": json.dumps([str(c).upper() if mo != "txn" else str(c) for c in codes]), "periods": per}


@router.route("POST", "/api/kpi/charts")
def chart_add(req):
    c = need(req, "weekly_kpi", "edit")
    f = clean_chart(req.json())
    n = req.db.execute("SELECT COALESCE(MAX(sort),0)+1 n FROM kpi_charts").fetchone()["n"]
    cid = req.db.execute("INSERT INTO kpi_charts(grp,title,ctype,mode,codes,periods,sort) VALUES(?,?,?,?,?,?,?)", (f["grp"], f["title"], f["ctype"], f["mode"], f["codes"], f["periods"], n)).lastrowid
    audit(req.db, "kpi.chart", c.user, "weekly_kpi", "Chart added: %s" % f["title"], req.ip)
    return {"id": cid}


@router.route("PUT", "/api/kpi/charts/<int:cid>")
def chart_edit(req):
    c = need(req, "weekly_kpi", "edit")
    f = clean_chart(req.json())
    if not req.db.execute("UPDATE kpi_charts SET grp=?, title=?, ctype=?, mode=?, codes=?, periods=? WHERE id=?", (f["grp"], f["title"], f["ctype"], f["mode"], f["codes"], f["periods"], int(req.params["cid"]))).rowcount:
        raise HTTPError(404, "not_found", "Chart not found")
    audit(req.db, "kpi.chart", c.user, "weekly_kpi", "Chart changed: %s" % f["title"], req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/kpi/charts/<int:cid>")
def chart_del(req):
    c = need(req, "weekly_kpi", "edit")
    req.db.execute("DELETE FROM kpi_charts WHERE id=?", (int(req.params["cid"]),))
    audit(req.db, "kpi.chart", c.user, "weekly_kpi", "Chart %d removed" % int(req.params["cid"]), req.ip)
    return {"ok": True}


@router.route("POST", "/api/kpi/charts/move")
def chart_move(req):
    need(req, "weekly_kpi", "edit")
    d = req.json(); a = req.db.execute("SELECT id, sort, grp FROM kpi_charts WHERE id=?", (d.get("id") or 0,)).fetchone()
    if not a:
        raise HTTPError(404, "not_found", "Chart not found")
    op = "<" if d.get("dir") == "up" else ">"
    b = req.db.execute("SELECT id, sort FROM kpi_charts WHERE grp=? AND sort%s? ORDER BY sort %s LIMIT 1" % (op, "DESC" if op == "<" else "ASC"), (a["grp"], a["sort"])).fetchone()
    if b:
        req.db.execute("UPDATE kpi_charts SET sort=? WHERE id=?", (b["sort"], a["id"])); req.db.execute("UPDATE kpi_charts SET sort=? WHERE id=?", (a["sort"], b["id"]))
    return {"ok": True}


@router.route("PUT", "/api/kpi/charts/layout")
def chart_layout(req):
    c = need(req, "weekly_kpi", "edit")
    d = req.json(); per = int(d.get("per_slide") or 0)
    if per not in (1, 2, 4):
        raise HTTPError(400, "validation", "Charts per slide must be 1, 2 or 4.")
    req.db.execute("INSERT INTO kpi_layout(grp, per_slide) VALUES(?,?) ON CONFLICT(grp) DO UPDATE SET per_slide=excluded.per_slide", (need_str(d, "grp", "Group", 80), per))
    audit(req.db, "kpi.layout", c.user, "weekly_kpi", "%s: %d chart(s) per slide" % (d["grp"], per), req.ip)
    return {"ok": True}


@router.route("POST", "/api/kpi/charts/reset")
def chart_reset(req):
    c = need(req, "weekly_kpi", "edit")
    g = (req.json().get("grp") or "").strip() or None
    ensure_charts(req.db, g) if g else (req.db.execute("DELETE FROM kpi_charts"), req.db.execute("DELETE FROM kpi_layout"), ensure_charts(req.db))
    audit(req.db, "kpi.layout", c.user, "weekly_kpi", "Chart layout reset to the standard%s" % (" for " + g if g else ""), req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ PowerPoint
def bullets_for(rep_group, charts):
    used = [c for ch in charts for c in ch["codes"]]
    ks = sorted(rep_group["kpis"], key=lambda k: (k["code"] not in used, k["name"]))
    out = []
    for k in ks:
        L = k["latest"]
        if not L or k["kind"] != "kpi":
            continue
        v = ("{:,.%df}" % k["decimals"]).format(L["value"]) + ("%" if k["unit"] == "%" else (" " + k["unit"] if k["unit"] else ""))
        s = "%s: %s (%s)" % (k["name"], v, label(L["period"], "daily") + " " + L["period"][:4])
        if k["previous"] is not None and k["change"]:
            s += ", %s from %s" % ("up" if k["change"] > 0 else "down", ("{:,.%df}" % k["decimals"]).format(k["previous"]["value"]))
        if k["status"] == "off":
            s += ", below target" if k["better"] == "up" else ", above target"
        out.append(s[:170])
        if len(out) == 4:
            break
    return out


@router.route("GET", "/api/kpi/export.pptx")
def kpi_pptx(req):
    c = need(req, "weekly_kpi", "export")
    ensure_charts(req.db)
    rep = p2.kpi_weekly(req)
    as_of = rep["as_of"]
    groups, lay = charts_for(req.db, as_of)
    d = datetime.date.fromisoformat(as_of)
    title_date = "%s %d" % (["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"][d.month - 1], d.year)
    style = (req.query.get("style") or "template").strip()
    if style not in ("template", "clean"):
        raise HTTPError(400, "validation", "Choose the slide style: template or clean.")
    if style == "template":
        from . import p4
        return p4.pptx_response(req, c, rep, groups, lay, as_of)
    deck = pptx_writer.Deck()
    deck.title_slide("WEEKLY KPIs REPORT", title_date)
    n = 0
    for g in rep["groups"]:
        charts = [ch for ch in groups.get(g["name"], []) if not ch["empty"]]
        if not charts:
            continue
        per = lay.get(g["name"], 4)
        srcs = sorted({k["source"] for k in g["kpis"] if k["source"] and not k["internal_key"]})
        footer = "Sources: %s. Figures as of %s. Values older than their reporting frequency are flagged stale in the Sentinel report." % (", ".join(srcs[:6]) or "Sentinel", as_of)
        text = [x.strip() for x in re.split(r"[\r\n]+", g["note"] or "") if x.strip()]
        for i in range(0, len(charts), per):
            chunk = charts[i:i + per]
            specs = [{"type": ch["ctype"], "title": ch["title"], "cats": ch["cats"], "series": ch["series"], "fmt": ch["fmt"]} for ch in chunk]
            deck.chart_slide(g["name"].upper() + (" (continued)" if i else ""), specs, (text or bullets_for(g, charts)) if i == 0 else None, footer, band=g["name"] in ("Fraud and security", "Transaction health"))
            n += 1
    deck.end_slide()
    audit(req.db, "export.weekly_kpi_pptx", c.user, "weekly_kpi", "Weekly KPI PowerPoint as of %s downloaded (%d slides)" % (as_of, n + 2), req.ip)
    return Response(deck.save(), 200, "application/vnd.openxmlformats-officedocument.presentationml.presentation", [("Content-Disposition", 'attachment; filename="Sentinel_Weekly_KPI_%s.pptx"' % as_of)])


# ------------------------------------------------------------------ internal transaction data (from the EcoCash systems)
def parse_txn(data):
    rows = read_table(data)
    hi = next((i for i, r in enumerate(rows[:12]) if any(str(c or "").strip().lower() == "product" for c in r)), None)
    if hi is None:
        raise HTTPError(400, "bad_file", "No header row with Date, Product, TS and TF columns was found. Download the template.")
    head = [str(c or "").strip().lower() for c in rows[hi]]
    need_cols = {"date": ("date", "day"), "product": ("product",), "ts": ("ts", "successful", "success"), "tf": ("tf", "failed", "fail"), "ta": ("ta", "other", "abandoned")}
    ix = {}
    for k, names in need_cols.items():
        ix[k] = next((head.index(n) for n in names if n in head), None)
    if None in (ix["date"], ix["product"], ix["ts"], ix["tf"]):
        raise HTTPError(400, "bad_file", "The file needs the columns Date, Product, TS and TF (TA is optional).")
    good, errors, unknown = {}, [], set()
    for n, r in enumerate(rows[hi + 1:], hi + 2):
        r = list(r) + [None] * 10
        if r[ix["product"]] in (None, "") and r[ix["date"]] in (None, ""):
            continue
        prod = ALIAS.get(str(r[ix["product"]] or "").strip().lower()) or (str(r[ix["product"]]).strip().upper() if str(r[ix["product"]] or "").strip().upper() in PRODUCTS else None)
        if not prod:
            unknown.add(str(r[ix["product"]])); continue
        day = parse_date(r[ix["date"]])
        try:
            ts, tf, ta = int(float(r[ix["ts"]] or 0)), int(float(r[ix["tf"]] or 0)), int(float(r[ix["ta"]] or 0)) if ix["ta"] is not None else 0
            assert ts >= 0 and tf >= 0 and ta >= 0
        except (TypeError, ValueError, AssertionError):
            errors.append("Row %d: TS, TF and TA must be whole numbers, zero or more." % n); continue
        if not day or datetime.date.fromisoformat(day) > dbm.today():
            errors.append("Row %d: the date is missing, not a date, or in the future." % n); continue
        good[(prod, day)] = (ts, tf, ta)
    return good, sorted(unknown), errors


def weekly_from_daily(db, prod, who):
    days = [r["day"] for r in db.execute("SELECT day FROM txn_daily WHERE product=? ORDER BY day", (prod,))]
    k = db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", ("TXN_" + prod,)).fetchone()
    if not days or not k:
        return 0
    last, n = datetime.date.fromisoformat(days[-1]), 0
    for w in range(8):
        end = last - datetime.timedelta(days=7 * w); start = end - datetime.timedelta(days=6)
        r = db.execute("SELECT COUNT(*) n, SUM(ts) ts, SUM(tf) tf FROM txn_daily WHERE product=? AND day>=? AND day<=?", (prod, str(start), str(end))).fetchone()
        if r["n"] >= 5 and (r["ts"] or 0) + (r["tf"] or 0) > 0:
            if put_reading(db, k, str(end), round(r["ts"] / (r["ts"] + r["tf"]) * 100, 2), "upload", "Weekly success rate from %d days of uploaded transaction data" % r["n"], who) != "same":
                n += 1
    check_alerts(db, k, who)
    return n


@router.route("POST", "/api/kpi/txn-upload")
def txn_upload(req):
    c = need(req, "weekly_kpi", "create")
    data = req.body()
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    try:
        good, unknown, errors = parse_txn(data)
    except HTTPError:
        raise
    except Exception:
        raise HTTPError(400, "bad_file", "The file could not be read. Use the template (.xlsx) or a CSV file.")
    new = sum(1 for k in good if not req.db.execute("SELECT 1 FROM txn_daily WHERE product=? AND day=?", k).fetchone())
    out = {"rows": len(good), "new": new, "replaced": len(good) - new, "products": sorted({PRODUCTS[p] for p, _ in good}), "from": min((d for _, d in good), default=None), "to": max((d for _, d in good), default=None), "unknown": unknown, "errors": errors[:20], "error_count": len(errors), "dry": req.query.get("dry") != "0"}
    if out["dry"]:
        return out
    for (prod, day), (ts, tf, ta) in good.items():
        req.db.execute("INSERT INTO txn_daily(product,day,ts,tf,ta,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(product,day) DO UPDATE SET ts=excluded.ts, tf=excluded.tf, ta=excluded.ta, uploaded_by=excluded.uploaded_by, uploaded_at=excluded.uploaded_at", (prod, day, ts, tf, ta, c.user["username"], now()))
    out["weekly_readings"] = sum(weekly_from_daily(req.db, p, c.user["username"]) for p in {p for p, _ in good})
    audit(req.db, "kpi.txn_upload", c.user, "weekly_kpi", "Transaction data uploaded: %d day-product rows (%s to %s), %d weekly success rates updated" % (len(good), out["from"], out["to"], out["weekly_readings"]), req.ip)
    return out


@router.route("GET", "/api/kpi/txn-template.xlsx")
def txn_template(req):
    need(req, "weekly_kpi", "view")
    from . import xlsxbook
    rows = [[("Transaction monitoring upload", 3)], ["One row per product per day. TS = successful, TF = failed, TA = other (optional). Success rate = TS / (TS + TF). Dates as YYYY-MM-DD."], [], [(h, 1) for h in ("Date", "Product", "TS", "TF", "TA")]]
    prods = [[("Product names accepted", 1)]] + [[v] for v in PRODUCTS.values()]
    return xlsx_response(xlsxbook.write([("Upload", rows, [14, 26, 12, 12, 12]), ("Products", prods, [30])]), "Sentinel_transaction_upload_template.xlsx")
