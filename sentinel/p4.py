"""Step 7: the weekly KPI report in the format of the September 2026 deck. Slide text and status tiles, dual-axis transaction charts, hourly failure
charts, data uploads from the EcoCash systems, OTP-fraud and SIM-swap statistics, and the Excel report that mirrors the deck slide by slide."""
import datetime
import json
import os
import re

from . import core, db as dbm, p2, p3, pptxgen, xlsxbook
from .api import router, need, need_str, DATE_RE
from .core import audit, now
from .p2 import check_alerts, fnum, parse_date, pdate, put_reading, read_table, xlsx_response
from .web import HTTPError, Response

HERE = os.path.dirname(os.path.abspath(__file__))
HOURLY = dict(p3.PRODUCTS, CASH_IN="Cash in", RECHARGE_OTHERS="Recharge others", M2S="Merchant to subscriber", ZESA_PAY="ZESA Pay")
HALIAS = {v.lower(): k for k, v in HOURLY.items()}
HALIAS.update({"bill": "BILL", "balance": "BALANCE", "merchant": "MERCHANT", "send money": "SEND_OTHERS", "send money others": "SEND_OTHERS", "recharge": "RECHARGE_SELF", "zesa": "ZESA", "zesa pay": "ZESA_PAY", "cashin": "CASH_IN", "merchant to sva": "M2S", "merchant to sva transfer": "M2S"})
TXN_GROUPS = {"Transaction health": ("ECOCASH TRANSACTION MONITORING", "EcoCash Operations"), "Transaction failures": ("ECOCASH TRANSACTION FAILURES", "EcoCash Operations")}
p2.GROUP_ORDER[:] = ["Inflation and prices", "Energy and fuel", "Currency and markets", "Payments sector", "Money and credit", "Economy and society", "Fraud and security", "Transaction health", "Transaction failures", "Sentinel (internal)"]  # the order of the slides in the report
p3.MODES = ("series", "snapshot", "txn", "hourly")
p3.SHORT.update({"FX_EUR": "EUR", "FXD_GBP": "GBP", "FXD_BWP": "BWP", "FCY_IN": "Inflows / receipts (US$ bn)", "FCY_PAY": "Payments (US$ bn)", "FCY_NET": "Net surplus (US$ bn)", "POWER_HWANGE": "Hwange", "POWER_KARIBA": "Kariba", "POWER_IPP": "IPPs", "POWER_DEMAND": "Demand",
                 "CPI_USD": "CPI", "UNREST": "Severity", "OTP_FRAUD_M": "OTP fraud cases", "SIM_SWAP_M": "SIM swap cases", "ZIG_SETTLE": "ZiG share", "USD_SETTLE": "USD share", "GDP": "GDP (US$ bn)", "GDP_PROJ": "GDP projected (US$ bn)", "NPL": "NPL ratio (%)",
                 "CARD_1": "Debit cards", "CARD_2": "Credit cards", "CARD_3": "Prepaid cards", "CARD_4": "Mobile banking subscribers", "CARD_5": "Internet banking subscribers", "REMIT_FY": "Full year 2025", "REMIT_9M": "Q1 to Q3 2025", "REMIT_Q": "Q1 2026",
                 "EMP_INFORMAL": "Informal", "EMP_FORMAL": "Formal", "EMP_HOUSEHOLD": "Household"})
S = lambda g, t, ty, mo, codes, per: (g, t, ty, mo, codes, per)
p3.DEFAULT_CHARTS = [
    S("Inflation and prices", "Month on month USD inflation rate", "column", "series", ["INF_USD_M", "INF_USD_FOOD", "INF_USD_NONFOOD"], 16), S("Inflation and prices", "M-O-M inflation", "line", "series", ["INF_ZWG_M", "INF_USD_M"], 13),
    S("Inflation and prices", "Precious metal prices", "line", "series", ["PLATINUM", "PALLADIUM", "GOLD"], 11), S("Inflation and prices", "Consumer price index", "column", "series", ["CPI_USD"], 23),
    S("Energy and fuel", "Electricity generation", "bar", "snapshot", ["POWER_HWANGE", "POWER_KARIBA", "POWER_IPP", "POWER_DEMAND"], 1), S("Energy and fuel", "Fuel prices", "column", "series", ["FUEL_PETROL", "FUEL_DIESEL"], 11),
    S("Energy and fuel", "Q1 2026 fuel consumption by product", "column", "snapshot", ["FUELQ_DIESEL", "FUELQ_JETA1", "FUELQ_LPG", "FUELQ_PETROL"], 1), S("Energy and fuel", "Foreign-currency inflows and payments", "column", "series", ["FCY_IN", "FCY_PAY", "FCY_NET"], 2),
    S("Currency and markets", "ZSE vs VFEX market capitalisation", "column", "series", ["ZSE_CAP", "VFEX_CAP"], 9), S("Currency and markets", "Exchange rate", "line", "series", ["FX_INTERBANK", "FX_PARALLEL"], 18),
    S("Currency and markets", "Foreign-exchange mid-rates", "line", "series", ["FXD_GBP", "FXD_BWP", "FX_EUR"], 8), S("Currency and markets", "Money in circulation", "column", "series", ["M1", "M2", "M3"], 7),
    S("Payments sector", "Payment-system access points", "column", "series", ["MERCHANTS", "ATMS", "POS"], 4), S("Payments sector", "Payment devices", "column", "series", ["CARD_1", "CARD_2", "CARD_3", "CARD_4", "CARD_5"], 4),
    S("Payments sector", "Active mobile money subscriptions", "column", "series", ["MM_LINES_ECONET", "MM_LINES_NETONE", "MM_LINES_TELECEL"], 6), S("Payments sector", "Market share", "column", "series", ["MM_SHARE_ECONET", "MM_SHARE_NETONE", "MM_SHARE_TELECEL"], 6),
    S("Money and credit", "Trend in non-performing loans", "line", "series", ["NPL"], 12), S("Money and credit", "Interest and lending rates", "line", "series", ["POLICY_RATE", "LENDING_RATE"], 5),
    S("Money and credit", "Stablecoin price midpoints", "line", "series", ["PEG_USDC", "PEG_USDT", "PEG_DAI", "PEG_USDP"], 8), S("Money and credit", "NPS mobile money", "line", "series", ["MM_VAL_SHARE", "MM_VOL_SHARE"], 6),
    S("Economy and society", "Zimbabwe GDP", "column", "series", ["GDP", "GDP_PROJ"], 5), S("Economy and society", "Employment share", "column", "snapshot", ["EMP_INFORMAL", "EMP_FORMAL", "EMP_HOUSEHOLD"], 1),
    S("Economy and society", "Civil-unrest severity", "line", "series", ["UNREST"], 8), S("Economy and society", "Agricultural production", "column", "series", ["CROP_MAIZE", "CROP_TOBACCO", "CROP_SORGHUM", "CROP_SOYABEANS", "CROP_COTTON"], 2),
    S("Fraud and security", "OTP fraud and SIM swaps", "column", "series", ["OTP_FRAUD_M", "SIM_SWAP_M"], 5), S("Fraud and security", "Inbound remittances", "column", "snapshot", ["REMIT_FY", "REMIT_9M", "REMIT_Q"], 1),
    S("Fraud and security", "USD transaction ratio", "column", "series", ["USD_SETTLE", "ZIG_SETTLE"], 5), S("Fraud and security", "Capital-adequacy ratio", "line", "series", ["CAR"], 10)] + \
    [S("Transaction health", HOURLY[c], "line", "txn", [c], 7) for c in ("BILL", "B2W", "MERCHANT", "BALANCE", "RECHARGE_SELF", "SEND_OTHERS", "SEND_MOBILE", "SEND_BANK", "ZESA")] + [S("Transaction health", "ZESA Pay", "line", "hourly", ["ZESA_PAY"], 3)] + \
    [S("Transaction failures", HOURLY[c], "line", "hourly", [c], 3) for c in ("CASH_IN", "BILL", "MERCHANT", "SEND_MOBILE", "B2W", "BALANCE", "SEND_OTHERS", "RECHARGE_OTHERS", "M2S", "RECHARGE_SELF")]


# ------------------------------------------------------------------ charts: dual-axis transactions and hourly failures
def _day(d):
    x = pdate(d)
    return "%02d-%s-%02d" % (x.day, x.strftime("%b"), x.year % 100)


def build_txn(db, ch, out, as_of):
    prod = json.loads(ch["codes"])[0]
    rows = db.execute("SELECT day, ts, tf, ta FROM txn_daily WHERE product=? AND day<=? ORDER BY day DESC LIMIT ?", (prod, as_of, ch["periods"])).fetchall()[::-1]
    if not rows:
        return out
    k = db.execute("SELECT target FROM kpis WHERE code=? AND deleted_at IS NULL", ("TXN_" + prod,)).fetchone()
    out["cats"] = [p3.label(r["day"], "daily") for r in rows]
    ser = []
    if any(r["ta"] for r in rows):
        ser.append({"name": "TA", "values": [r["ta"] or None for r in rows], "color": "7F7F7F", "nolabels": True})
    ser += [{"name": "TF", "values": [r["tf"] for r in rows], "color": "FF0000", "nolabels": True}, {"name": "TS", "values": [r["ts"] for r in rows], "color": "002060", "nolabels": True},
            {"name": "TS success rate", "values": [r["ts"] / (r["ts"] + r["tf"]) if r["ts"] + r["tf"] else None for r in rows], "axis": 2, "color": "4472C4", "thin": True, "fmt": "0%", "nolabels": True}]
    if k and k["target"] is not None:
        ser.append({"name": "TS target", "values": [k["target"] / 100.0] * len(rows), "axis": 2, "color": "FF0000", "dashed": True, "nolabels": True})
    out.update(series=ser, fmt="#,##0", empty=False, labels=False, secondary=True)
    return out


def build_hourly(db, ch, out, as_of):
    prod = json.loads(ch["codes"])[0]
    days = [r["day"] for r in db.execute("SELECT DISTINCT day FROM txn_hourly WHERE product=? AND day<=? ORDER BY day DESC LIMIT ?", (prod, as_of, ch["periods"]))][::-1]
    if not days:
        return out
    pal = ["002060", "FF0000", "00B050", "7030A0", "ED7D31"]
    out["cats"] = [str(h) for h in range(1, 25)]
    for i, d in enumerate(days):
        m = {r["hour"]: r["failed"] for r in db.execute("SELECT hour, failed FROM txn_hourly WHERE product=? AND day=?", (prod, d))}
        out["series"].append({"name": _day(d), "values": [m.get(h) for h in range(1, 25)], "color": pal[i % len(pal)], "legend": True, "thin": True, "nolabels": True})
    out.update(fmt="#,##0", empty=False, labels=False)
    return out


_orig_build = p3.build_chart


def build_chart(db, ch, as_of):
    if ch["mode"] in ("txn", "hourly"):
        base = {"id": ch["id"], "grp": ch["grp"], "title": ch["title"], "ctype": ch["ctype"], "mode": ch["mode"], "codes": json.loads(ch["codes"]), "periods": ch["periods"], "cats": [], "series": [], "fmt": "General", "empty": True, "labels": False}
        return (build_txn if ch["mode"] == "txn" else build_hourly)(db, ch, base, as_of)
    out = _orig_build(db, ch, as_of)
    out.setdefault("labels", True)
    k = db.execute("SELECT unit FROM kpis WHERE code=?", (out["codes"][0],)).fetchone() if out.get("codes") else None
    out.setdefault("unit", k["unit"] if k and k["unit"] and k["unit"] != "%" else (k["unit"] if k else None))
    return out


p3.build_chart = build_chart


def weekly_from_daily(db, prod, who):
    """The weekly success rate is the average of the daily success rates, as in the weekly report ('averaged 76.1%')."""
    k = db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", ("TXN_" + prod,)).fetchone()
    days = [r["day"] for r in db.execute("SELECT day FROM txn_daily WHERE product=? ORDER BY day", (prod,))]
    if not days or not k:
        return 0
    last, n = datetime.date.fromisoformat(days[-1]), 0
    for w in range(8):
        end = last - datetime.timedelta(days=7 * w); start = end - datetime.timedelta(days=6)
        rates = [r["ts"] / (r["ts"] + r["tf"]) * 100 for r in db.execute("SELECT ts, tf FROM txn_daily WHERE product=? AND day>=? AND day<=?", (prod, str(start), str(end))) if r["ts"] + r["tf"] > 0]
        if len(rates) >= 5 and put_reading(db, k, str(end), round(sum(rates) / len(rates), 2), "upload", "Average of %d daily success rates from the uploaded transaction data" % len(rates), who) != "same":
            n += 1
    check_alerts(db, k, who)
    return n


p3.weekly_from_daily = weekly_from_daily


# ------------------------------------------------------------------ slide text, tiles and the pages of the deck
def deck_rows(db, as_of):
    m = db.execute("SELECT MAX(as_of) m FROM kpi_deck WHERE as_of<=?", (as_of,)).fetchone()["m"]
    rows = {}
    if m:
        for r in db.execute("SELECT * FROM kpi_deck WHERE as_of=?", (m,)):
            rows[(r["grp"], r["page"])] = {"subtitle": r["subtitle"], "source": r["source"], "tiles": json.loads(r["tiles"]), "bullets": json.loads(r["bullets"])}
    return m, rows


def month_year(as_of):
    d = pdate(as_of)
    return "%s %d" % (d.strftime("%B").upper(), d.year)


def deck_pages(db, rep, groups, lay, as_of, chunk=None):
    """One entry per slide: title, subtitle, source, charts, commentary and tiles. chunk=4 fixes four charts per page (used by the Excel report)."""
    m, rows = deck_rows(db, as_of)
    gmap = {g["name"]: g for g in rep["groups"]}
    order = [g for g in p2.GROUP_ORDER if g in groups] + sorted(g for g in groups if g not in p2.GROUP_ORDER)
    pages = []
    for gname in order:
        charts = [c for c in groups[gname] if not c["empty"]]
        if not charts:
            continue
        per = chunk or lay.get(gname, 4)
        g = gmap.get(gname)
        note = [x.strip(" -\u2022") for x in re.split(r"[\r\n]+", (g or {}).get("note") or "") if x.strip()]
        srcs = []
        for k in (g or {}).get("kpis", []):
            s0 = (k["source"] or "").split("/")[0].split("(")[0].strip()
            if s0 and s0 not in srcs and not k["internal_key"] and "weekly" not in s0.lower():
                srcs.append(s0)
        for i in range(0, len(charts), per):
            pg = i // per + 1
            d = rows.get((gname, pg), {})
            title, defsrc = TXN_GROUPS.get(gname, ("ECONOMIC OUTLOOK", "EcoCash Research"))
            sub = d.get("subtitle") or ("WEEKLY KPI REPORT   |   " + (month_year(as_of) if gname in TXN_GROUPS else (", ".join(srcs[:4]) or gname)))
            bullets = d.get("bullets") or (note if pg == 1 else []) or (p3.bullets_for(g, charts) if pg == 1 and g else [])
            pages.append({"grp": gname, "page": pg, "title": title, "subtitle": sub, "source": d.get("source") or defsrc, "per": per, "charts": charts[i:i + per], "bullets": bullets, "tiles": d.get("tiles") or [], "carried_from": m if m and m != as_of else None})
    return pages


def pptx_response(req, c, rep, groups, lay, as_of):
    pages = deck_pages(req.db, rep, groups, lay, as_of)
    slides = [{"title": pg["title"], "subtitle": pg["subtitle"], "source": pg["source"], "per_slide": pg["per"], "bullets": pg["bullets"], "tiles": pg["tiles"],
               "charts": [{"title": ch["title"], "ctype": ch["ctype"] if ch["ctype"] in pptxgen.CTYPES else "column", "cats": ch["cats"], "series": ch["series"], "unit": ch.get("unit"), "labels": ch.get("labels", True), "fmt": "#,##0.##" if ch.get("fmt") in (None, "General") else ch["fmt"]} for ch in pg["charts"]]} for pg in pages]
    data = pptxgen.build({"as_of": as_of, "slides": slides})
    audit(req.db, "export.weekly_kpi_pptx", c.user, "weekly_kpi", "Weekly KPI PowerPoint (EcoCash template) as of %s downloaded (%d slides)" % (as_of, len(slides) + 2), req.ip)
    return Response(data, 200, "application/vnd.openxmlformats-officedocument.presentationml.presentation", [("Content-Disposition", 'attachment; filename="Sentinel_Weekly_KPI_%s.pptx"' % as_of)])


@router.route("GET", "/api/kpi/deck")
def deck_get(req):
    c = need(req, "weekly_kpi", "view")
    as_of = (req.query.get("as_of") or str(p2.today())).strip()
    if not DATE_RE.match(as_of):
        raise HTTPError(400, "validation", "as_of must be a date (YYYY-MM-DD).")
    m, rows = deck_rows(req.db, as_of)
    out = {}
    for (g, pg), v in sorted(rows.items(), key=lambda x: (x[0][0], x[0][1])):
        out.setdefault(g, []).append(dict(v, page=pg))
    return {"as_of": as_of, "carried_from": m if m and m != as_of else None, "from": m, "pages": out, "loaded": bool(req.db.execute("SELECT 1 FROM kpis WHERE code='OTP_FRAUD_M'").fetchone() or req.db.execute("SELECT 1 FROM settings WHERE key='demo_mode'").fetchone()),
            "can": {a: a in c.perms.get("weekly_kpi", set()) for a in core.ACTIONS}}


@router.route("PUT", "/api/kpi/deck")
def deck_put(req):
    c = need(req, "weekly_kpi", "edit")
    d = req.json()
    as_of, grp, page = (d.get("as_of") or "").strip(), need_str(d, "grp", "Group", 80), int(d.get("page") or 1)
    if not DATE_RE.match(as_of) or not 1 <= page <= 12:
        raise HTTPError(400, "validation", "Give the report date and a slide number from 1 to 12.")
    tiles = [{"word": need_str(t, "word", "Tile word", 24, False).upper(), "caption": need_str(t, "caption", "Tile caption", 40, False)} for t in (d.get("tiles") or [])[:4]]
    bullets = [need_str({"b": b}, "b", "Commentary line", 220, False) for b in (d.get("bullets") or [])[:6] if str(b).strip()]
    req.db.execute("INSERT INTO kpi_deck(as_of,grp,page,subtitle,source,tiles,bullets,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(as_of,grp,page) DO UPDATE SET subtitle=excluded.subtitle, source=excluded.source, tiles=excluded.tiles, bullets=excluded.bullets, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                   (as_of, grp, page, need_str(d, "subtitle", "Subtitle", 120, False) or None, need_str(d, "source", "Source", 80, False) or None, json.dumps(tiles), json.dumps(bullets), c.user["username"], now()))
    audit(req.db, "kpi.deck", c.user, "weekly_kpi", "Slide text saved: %s, slide %d, report %s" % (grp, page, as_of), req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ hourly failures from the EcoCash systems
def parse_hourly(data):
    rows = read_table(data)
    hi = next((i for i, r in enumerate(rows[:12]) if "product" in [str(c or "").strip().lower() for c in r] and "hour" in [str(c or "").strip().lower() for c in r]), None)
    if hi is None:
        raise HTTPError(400, "bad_file", "Expected columns: Date, Hour, Product, Failed. Download the template.")
    head = [str(c or "").strip().lower() for c in rows[hi]]
    ix = lambda *n: next((head.index(x) for x in n if x in head), None)
    di, hh, pi, fi = ix("date", "day"), ix("hour"), ix("product"), ix("failed", "failures", "tf", "count")
    if None in (di, hh, pi, fi):
        raise HTTPError(400, "bad_file", "Expected columns: Date, Hour, Product, Failed.")
    good, errors, unknown, hours = {}, [], set(), set()
    for n, r in enumerate(rows[hi + 1:], hi + 2):
        r = list(r) + [None] * (len(head) - len(r))
        if all(x in (None, "") for x in (r[di], r[pi], r[hh])):
            continue
        prod = HALIAS.get(str(r[pi] or "").strip().lower()) or (str(r[pi]).strip().upper() if str(r[pi] or "").strip().upper() in HOURLY else None)
        day = parse_date(r[di])
        try:
            h, f = int(float(r[hh])), int(float(r[fi] or 0)); assert 0 <= h <= 24 and f >= 0
        except (TypeError, ValueError, AssertionError):
            errors.append("Row %d: the hour must be 0 to 24 and the failed count a whole number, zero or more." % n); continue
        if not prod:
            unknown.add(str(r[pi])); continue
        if not day or pdate(day) > p2.today():
            errors.append("Row %d: the date is missing, not a date, or in the future." % n); continue
        hours.add(h); good[(prod, day, h)] = good.get((prod, day, h), 0) + f
    if 0 in hours:  # hours given as 0 to 23 are shown as 1 to 24, as in the report
        good = {(p, d, h + 1): f for (p, d, h), f in good.items()}
    return good, sorted(unknown), errors


@router.route("POST", "/api/kpi/hourly-upload")
def hourly_upload(req):
    c = need(req, "weekly_kpi", "create")
    data = req.body()
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    try:
        good, unknown, errors = parse_hourly(data)
    except HTTPError:
        raise
    except Exception:
        raise HTTPError(400, "bad_file", "The file could not be read. Use the template (.xlsx) or a CSV file.")
    new = sum(1 for k in good if not req.db.execute("SELECT 1 FROM txn_hourly WHERE product=? AND day=? AND hour=?", k).fetchone())
    out = {"rows": len(good), "new": new, "replaced": len(good) - new, "products": sorted({HOURLY[p] for p, _, _ in good}), "days": len({(p, d) for p, d, _ in good}), "from": min((d for _, d, _ in good), default=None), "to": max((d for _, d, _ in good), default=None),
           "unknown": unknown, "errors": errors[:20], "error_count": len(errors), "dry": req.query.get("dry") != "0"}
    if out["dry"]:
        return out
    for (p, d, h), f in good.items():
        req.db.execute("INSERT INTO txn_hourly(product,day,hour,failed,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?) ON CONFLICT(product,day,hour) DO UPDATE SET failed=excluded.failed, uploaded_by=excluded.uploaded_by, uploaded_at=excluded.uploaded_at", (p, d, h, f, c.user["username"], now()))
    audit(req.db, "kpi.hourly_upload", c.user, "weekly_kpi", "Hourly failure data uploaded: %d rows, %d product-days (%s to %s)" % (len(good), out["days"], out["from"], out["to"]), req.ip)
    return out


@router.route("GET", "/api/kpi/hourly-template.xlsx")
def hourly_template(req):
    need(req, "weekly_kpi", "view")
    d = str(p2.today() - datetime.timedelta(days=1))
    rows = [[("Hourly failed transactions upload", 3)], ["One row per product per hour. Hour is 1 to 24 (or 0 to 23). Failed is the number of failed transactions in that hour. Dates as YYYY-MM-DD."], [], [(h, 1) for h in ("Date", "Hour", "Product", "Failed")],
            [("date", d), 9, "Cash in", 64], [("date", d), 10, "Cash in", 58], [("date", d), 18, "Merchant payment", 18764]]
    return xlsx_response(xlsxbook.write([("Upload", rows, [14, 8, 26, 12]), ("Products", [[(("Product names accepted"), 1)]] + [[v] for v in HOURLY.values()], [30])]), "Sentinel_hourly_failures_template.xlsx")


# ------------------------------------------------------------------ OTP-fraud and SIM-swap statistics, given by the Risk Office
@router.route("POST", "/api/kpi/fraud-stats")
def fraud_stats(req):
    c = need(req, "weekly_kpi", "create")
    d = req.json()
    raw = (d.get("period") or "").strip()
    day = parse_date(raw) or (parse_date(raw + "-01") if re.match(r"^\d{4}-\d{2}$", raw) else None)
    if not day:
        raise HTTPError(400, "validation", "Give the month (YYYY-MM) or the last date the figures cover.")
    dt = pdate(day)
    if re.match(r"^\d{4}-\d{2}$", raw):
        dt = datetime.date(dt.year + (dt.month == 12), dt.month % 12 + 1, 1) - datetime.timedelta(days=1)
    dt = min(dt, p2.today())
    otp, sim = fnum(d.get("otp"), "OTP-fraud cases", True, 0), fnum(d.get("simswap"), "SIM-swap cases", True, 0)
    note = need_str(d, "note", "Note", 300, False) or None
    n = 0
    for code, v in (("OTP_FRAUD_M", otp), ("SIM_SWAP_M", sim), ("KRI_OTP_M", otp), ("KRI_SIMSWAP_M", sim)):
        k = req.db.execute("SELECT * FROM kpis WHERE code=? AND deleted_at IS NULL", (code,)).fetchone()
        if not k:
            continue
        if put_reading(req.db, k, str(dt), v, "manual", note or "Statistics given by the Risk Office", c.user["username"]) != "same":
            n += 1
        check_alerts(req.db, k, c.user["username"], req.ip)
    if not n and not req.db.execute("SELECT 1 FROM kpis WHERE code='OTP_FRAUD_M'").fetchone():
        raise HTTPError(409, "no_indicator", "Load the September 2026 data first (Weekly KPI report > Update to the September 2026 report).")
    audit(req.db, "kpi.fraud_stats", c.user, "weekly_kpi", "Fraud statistics to %s: OTP fraud %d, SIM swaps %d" % (dt, otp, sim), req.ip)
    return {"period": str(dt), "saved": n}


# ------------------------------------------------------------------ starter data
def seed_extras(db, who, reset=False):
    out = {"slides": 0, "daily": 0, "hourly": 0}
    dk = json.load(open(os.path.join(HERE, "deck_seed.json"), encoding="utf-8"))
    for pg in dk["pages"]:
        if not db.execute("SELECT 1 FROM kpi_deck WHERE as_of=? AND grp=? AND page=?", (dk["as_of"], pg["grp"], pg["page"])).fetchone():
            db.execute("INSERT INTO kpi_deck(as_of,grp,page,subtitle,source,tiles,bullets,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (dk["as_of"], pg["grp"], pg["page"], pg["subtitle"], pg["source"], json.dumps(pg["tiles"]), json.dumps(pg["bullets"]), "starter set", now()))
            out["slides"] += 1
    tx = json.load(open(os.path.join(HERE, "txn_seed.json"), encoding="utf-8"))
    for p, d, ts, tf, ta in tx["daily"]:
        if not db.execute("SELECT 1 FROM txn_daily WHERE product=? AND day=?", (p, d)).fetchone():
            db.execute("INSERT INTO txn_daily(product,day,ts,tf,ta,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,?)", (p, d, ts, tf, ta, "starter set", now())); out["daily"] += 1
    for p, d, h, f in tx["hourly"]:
        if not db.execute("SELECT 1 FROM txn_hourly WHERE product=? AND day=? AND hour=?", (p, d, h)).fetchone():
            db.execute("INSERT INTO txn_hourly(product,day,hour,failed,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?)", (p, d, h, f, "starter set", now())); out["hourly"] += 1
    if reset:
        db.execute("DELETE FROM kpi_charts"); db.execute("DELETE FROM kpi_layout"); p3.ensure_charts(db)
    return out


# ------------------------------------------------------------------ the Excel report in the deck's format
def deck_sheets(db, rep, groups, lay, as_of):
    """One sheet per slide of the deck: title, native charts with data labels, commentary, tiles, source, and the tables behind the charts."""
    pages = deck_pages(db, rep, groups, lay, as_of, chunk=4)
    sheets, used = [], set()
    for no, pg in enumerate(pages, 2):
        nm = re.sub(r"[\[\]:*?/\\]", "", "%02d %s" % (no, pg["grp"] + (" %d" % pg["page"] if pg["page"] > 1 else "")))[:31]
        while nm in used:
            nm = nm[:28] + "~%d" % len(used)
        used.add(nm)
        rows = [[(pg["title"], 3)], [(pg["subtitle"], 4)]] + [[] for _ in range(33)]
        rows[35 - 1] = [("Commentary", 1)] + [("", 1)] * 8
        for i, b in enumerate(pg["bullets"][:5]):
            rows.append(["\u2022  " + b])
        while len(rows) < 42:
            rows.append([])
        rows.append([("Status tiles", 1)] + [("", 1)] * 8)
        rows.append([t.get("word") for t in pg["tiles"][:4]] if pg["tiles"] else [])
        rows.append([t.get("caption") for t in pg["tiles"][:4]] if pg["tiles"] else [])
        rows.append(["Source: %s     |     ENTERPRISE RISK MANAGEMENT     |     Figures as of %s" % (pg["source"], pptxgen.long_date(as_of))])
        rows.append([])
        anchors = []
        for k, ch in enumerate(pg["charts"]):
            rows.append([(ch["title"].upper(), 4)] + [("", 4)] * (len(ch["series"]) or 1))
            hdr = len(rows) + 1
            rows.append([("Period" if ch["mode"] != "hourly" else "Hour", 1)] + [(s["name"], 1) for s in ch["series"]])
            for i, c in enumerate(ch["cats"]):
                rows.append([str(c)] + [s["values"][i] for s in ch["series"]])
            rows.append([])
            fmt = "#,##0.##" if ch.get("fmt") in (None, "General") else ch["fmt"]
            xml = pptxgen.chart_xml(ch["title"].upper(), ch["ctype"] if ch["ctype"] in pptxgen.CTYPES else "column", ch["cats"], ch["series"], ch.get("unit"), ch.get("labels", True), refs=pptxgen.default_refs(nm, len(ch["cats"]), len(ch["series"]), hdr), embed=False, fmt=fmt)
            anchors.append({"col": 0 if k % 2 == 0 else 6, "row": 3 if k < 2 else 19, "cx": 5486400, "cy": 2926080, "xml": xml})
        sheets.append((nm, rows, [26] + [13] * 30, anchors))
    cover = [[("EcoCash Weekly KPI Report", 3)], [("ENTERPRISE RISK MANAGEMENT  |  Figures as of %s" % pptxgen.long_date(as_of), 4)], [], [("Slide", 1), ("Sheet", 1), ("Charts", 1)]]
    for no, (nm, _, _, ch) in enumerate(sheets, 2):
        cover.append([no, nm, len(ch)])
    cover += [[], ["Each sheet follows one slide of the PowerPoint: the charts (with data labels) at the top, the commentary and status tiles, then the tables behind the charts."], ["The Indicators, History, Commentary and Sources sheets at the end hold every indicator with its date, source and how it was captured."]]
    return [("Cover", cover, [10, 34, 10])] + sheets


p2.MIRROR.update({"OTP_FRAUD_M": "KRI_OTP_M", "SIM_SWAP_M": "KRI_SIMSWAP_M"})  # a manual monthly figure also feeds the KRI that watches it

p3.PRODUCTS.update(HOURLY)  # the chart editor offers every product, including those that only have hourly data
