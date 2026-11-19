"""Power BI-style KRI pages (Step 23).

Every page of the Power BI report that is fed by KRI figures is described here once, and computed from the stored figures (the dict that kriq.build returns).
The browser draws the pages from this description and the PowerPoint download draws the same pages with native charts, so the two always agree and both
change as soon as a report is imported or a figure is edited."""
import re

from . import kriq_parse as K

INH, APP = 25, 10  # GRC scale: inherent 25 for every risk, appetite 10
SHORT = {101: "Protection of Trust Funds (Bank Credit)", 102: "Insolvency of Operators: EcoCash", 103: "Investment Risk"}
WORST = {"red": 3, "amber": 2, "green": 1, "info": 0}


def ql(q):
    m = re.match(r"FY(\d\d)Q(\d)$", q or "")
    return "Q%s FY%s" % (m.group(2), m.group(1)) if m else (q or "")


def short_name(rk):
    return SHORT.get(rk["no"]) or re.sub(r"\s*\(Board of Trustees\)$", "", re.sub(r"\s+Risk$", "", rk["name"]))


def category(rk):
    c = rk.get("category") or ""
    if rk["no"] >= 100:
        return "Financial"
    return "Compliance & Regulatory" if c == "Regulatory" else c or "Other"


def band(v):
    """Colour band of a residual rating on the 25-point scale."""
    if v is None:
        return None
    return "green" if v <= APP else "yellow" if v <= 15 else "orange" if v < 20 else "red"


# ------------------------------------------------------------------ finding KRIs
def find(d, pat, rno=None):
    want = None if rno is None else (set(rno) if isinstance(rno, (list, tuple, set)) else {rno})
    for rk in d["risks"]:
        if want is not None and rk["no"] not in want:
            continue
        for r in rk["kris"]:
            if re.search(pat, r["name"], re.I):
                return rk, r
    return None


def _num(r, q, div):
    x = r["q"].get(q)
    if not x:
        return None
    v = x["value"]
    if v is None and re.match(r"\s*<\s*1\s*hr", x.get("raw") or "", re.I):
        v = 1.0  # "<1hr" is plotted as the upper bound, one hour
    return None if v is None else round(v / div, 4)


def _tnum(r, div):
    raw = r.get("target") or ""
    v = K.parse_target(raw, r["name"])[1] if raw else None
    return None if v is None else round(v / div, 4)


def _tname(r):
    t = re.sub(r"^[<>≤≥=\s]+", "", (r.get("target") or "").strip())
    return t


def _dir(r):
    t = (r.get("target") or "").strip()
    if not t:
        return None
    return "lower" if (r.get("lower_better") or t[:1] in "<≤") else "higher"


def _lamp(rows):
    best = "info"
    for r in rows:
        c = r.get("current") or r.get("latest")
        if c and WORST[c["status"]] > WORST[best]:
            best = c["status"]
    return best


def _empty(kind, title, qs, ylab):
    return {"kind": kind, "title": title, "sub": "No figures for this KRI yet. Enter or import a report and this chart fills in.", "cats": [ql(q) for q in qs], "series": [], "empty": True, "ylab": ylab, "lamp": "info"}


def p_line(d, title, pat, rno=None, div=1, ylab="Percent (%)"):
    qs = d["quarters"]; f = find(d, pat, rno)
    if not f:
        return _empty("line", title, qs, ylab)
    rk, r = f
    tv = _tnum(r, div); dr = _dir(r)
    ser = [{"name": "Actual", "values": [_num(r, q, div) for q in qs], "status": [(r["q"][q]["status"] if q in r["q"] else None) for q in qs], "text": [(r["q"][q]["text"] if q in r["q"] else None) for q in qs]}]
    if tv is not None:
        ser.append({"name": "Target", "values": [tv] * len(qs), "dashed": True})
    sub = ("Solid line = reported actual; dashed red line = target (%s is better)." % ("lower" if dr == "lower" else "higher")) if tv is not None else "Reported actual each quarter. The reports set no target for this KRI."
    c = r.get("current") or r.get("latest")
    return {"kind": "line", "title": title + (" vs target %s" % _tname(r) if tv is not None else ""), "sub": sub, "cats": [ql(q) for q in qs], "series": ser, "ylab": ylab, "target": tv, "better": dr,
            "lamp": c["status"] if c else "info", "now": c["text"] if c else None, "kri": r["id"], "risk": rk["no"]}


def p_lines(d, title, items, div=1, ylab="", sub=None):
    qs = d["quarters"]; ser, lamps, found = [], [], 0
    for pat, rno, label in items:
        f = find(d, pat, rno)
        if not f:
            continue
        found += 1; rk, r = f
        ser.append({"name": label, "values": [_num(r, q, div) for q in qs], "status": [(r["q"][q]["status"] if q in r["q"] else None) for q in qs], "text": [(r["q"][q]["text"] if q in r["q"] else None) for q in qs], "kri": r["id"]})
        lamps.append(r)
    if not found:
        return _empty("lines", title, qs, ylab)
    return {"kind": "lines", "title": title, "sub": sub or "Each KRI reported each quarter. Targets or limits are in the title.", "cats": [ql(q) for q in qs], "series": ser, "ylab": ylab, "lamp": _lamp(lamps)}


def p_bars(d, title, items, div=1, ylab="", sub=None):
    p = p_lines(d, title, items, div, ylab, sub)
    p["kind"] = "bars" if not p.get("empty") else "bars"
    return p


def p_resid(d, title, rnos):
    qs = d["quarters"]; ser = []
    for rk in d["risks"]:
        if rk["no"] in rnos and any(rk["residual"].get(q) is not None for q in qs):
            ser.append({"name": short_name(rk), "values": [rk["residual"].get(q) for q in qs], "risk": rk["no"]})
    if not ser:
        return _empty("resid", title, qs, "Risk score (0 to 25)")
    cur = [s["values"][-1] for s in ser if s["values"][-1] is not None]
    return {"kind": "resid", "title": title, "sub": "Whole-number residual by quarter (GRC scale). Inherent is %d for every risk; %d or below is within appetite." % (INH, APP), "cats": [ql(q) for q in qs], "series": ser, "ylab": "Risk score (0 to %d)" % INH, "target": APP,
            "lamp": ("red" if any(v > 15 for v in cur) else "amber" if any(v > APP for v in cur) else "green") if cur else "info"}


def p_status(d, title, rnos):
    qs = d["quarters"]; rows = [r for rk in d["risks"] if rk["no"] in rnos for r in rk["kris"]]
    ser = []
    for k, nm in (("green", "On target"), ("amber", "Near target"), ("red", "Off target")):
        ser.append({"name": nm, "key": k, "values": [sum(1 for r in rows if q in r["q"] and r["q"][q]["status"] == k) for q in qs]})
    return {"kind": "status", "title": title, "sub": "Number of this page's KRIs in each status: green = target met, amber = near target, red = breached.", "cats": [ql(q) for q in qs], "series": ser, "ylab": "Number of KRIs", "lamp": "info"}


# ------------------------------------------------------------------ the pages
def pages(d):
    L = lambda *a, **k: p_line(d, *a, **k)
    B = lambda *a, **k: p_bars(d, *a, **k)
    Ls = lambda *a, **k: p_lines(d, *a, **k)
    out = []

    def page(pid, title, sub, panels, risks):
        out.append({"id": pid, "title": title, "sub": sub, "panels": panels, "risks": risks})

    page("r01", "Business Performance KRIs (R01)", "EBITDA, revenue against budget, margins and returns versus current targets. Dashed red line = target.", [
        L("EBITDA margin", r"^EBITDA"), L("Revenue above budget", r"^Revenue budget var", 1), L("Gross profit margin", r"^Gross Profit"),
        B("Return on equity (target 20%) and return on assets (target 5%) - %", [(r"^Return on equity", 1, "Return on equity"), (r"^Return on assets", 1, "Return on assets")], ylab="Percent (%)"),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [1]), p_status(d, "KRI results by quarter (number of KRIs)", [1])], [1])
    page("r03", "Operating Expenses & Economic KRIs (R03, R04)", "Cost ratios, dollarisation, FX exposure and exchange rates.", [
        B("Cost ratios, % of revenue (limits: office 4, staff 8, marketing 3.5, total 30)", [(r"^Expense ratio", None, "Expense ratio"), (r"^Marketing Expenses", None, "Marketing expenses"), (r"^Office Expense", None, "Office expense"), (r"^Staff Cost$", 4, "Staff cost")], ylab="Percent (%)"),
        L("USD revenue contribution", r"^USD revenue contribution$"), L("Monetary assets, % of total assets (limit 26%)", r"^Monetary Assets as a percentage", 3),
        B("FX loss ratios, % (limits: 5% of EBITDA, 2% of revenue)", [(r"^Foreign Exchange Loss/ ?EBITDA", None, "FX loss / EBITDA"), (r"^Foreign Exchange Loss/ ?Revenue", None, "FX loss / Revenue")], ylab="Percent (%)"),
        Ls("Official vs parallel exchange rate (ZWG per USD)", [(r"^Exchange Rate Official", None, "Official exchange rate"), (r"^Exchange Rate Parallel", None, "Parallel exchange rate")], ylab="ZWG per USD"),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [3, 4])], [3, 4])
    page("r02", "Strategic KRIs | Competition & Business Model (R02, R06)", "Customers, distribution, products and new-business contribution against current targets.", [
        B("Active customers, Mn (targets: 30-day 4.3, 90-day 5.4, USD 4.2)", [(r"^Active 30 Customers$", 2, "Active 30 customers"), (r"^Active 30 Customers \(USD\)", 2, "Active 30 customers (USD)"), (r"^Active 90 Customers", 2, "Active 90 customers")], div=1e6, ylab="Customers (million)"),
        L("DMT partners", r"^DMT Partners", 2, ylab="Number"), B("New products (target 1) and promotions (target 3)", [(r"^Number of new products", 2, "Number of new products"), (r"^Number of promotions", 2, "Number of promotions")], ylab="Number"),
        B("International remittance partners (total)", [(r"^International Remittance", 2, "International remittance partners")], ylab="Number"), L("Contribution from new businesses", r"contribution for new businesses"),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [2, 6])], [2, 6])
    page("r05", "Compliance & Regulatory KRIs (R05, R09)", "Compliance accuracy, supervisory activity and suspicious-transaction volumes. R09 has no targets.", [
        Ls("KYC accuracy (target 99%) and merchant liquidation (target 100%) - %", [(r"^KYC accuracy", 6, "KYC accuracy"), (r"^Merchant Liquidation", 6, "Merchant liquidation")], ylab="Percent (%)"),
        B("Inspections, corrective orders, new statutory instruments, fines (target 0)", [(r"^Inspections", 6, "Inspections"), (r"^Corrective Orders", 6, "Corrective orders"), (r"^# of New SI", 6, "New statutory instruments"), (r"^Regulatory Fines", 6, "Regulatory fines")], ylab="Reported value"),
        B("Suspicious transaction reports (STRs)", [(r"^Number of STRs", 6, "Number of STRs")], ylab="Number", sub="Reported actual each quarter. The reports set no target for this KRI."),
        B("AML/CFT trained individuals", [(r"^AML/CFT", 9, "AML/CFT trained individuals")], ylab="Number", sub="Reported actual each quarter. The reports set no target for this KRI."),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [5, 9]), p_status(d, "KRI results by quarter (number of KRIs)", [5, 9])], [5, 9])
    page("r07", "Cyber Security & Fraud KRIs (R07)", "Fraud cases, losses and the controls that respond to them.", [
        L("OTP fraud cases", r"^OTP Fraud", 7, ylab="Number"), B("SIM-swap cases and unauthorised account access (target 0)", [(r"^Fraudulent SIM swap cases", 7, "Fraudulent SIM swap cases"), (r"^Unauthori[sz]ed account access", 7, "Unauthorised account access")], ylab="Reported value"),
        B("Fraud losses, USD thousand", [(r"^OTP fraud value", 7, "OTP fraud value (USD thousand)"), (r"^SIM swap losses", 7, "SIM swap losses (USD thousand)")], div=1e3, ylab="USD thousand"),
        B("VAPT coverage (target 85%) and awareness training (target 100%) - %", [(r"^Vulnerability", 7, "Vulnerability assessment and pen test"), (r"^Cybersecurity Awareness", 7, "Cybersecurity awareness training")], ylab="Percent (%)"),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [7]), p_status(d, "KRI results by quarter (number of KRIs)", [7])], [7])
    page("r08", "BCM & Technology KRIs (R08, R13)", "Availability, incidents, revenue at risk and Zimswitch exposure.", [
        L("Technical incidents", r"^Technical Incidents", 8, ylab="Number"), L("System uptime", r"^System Uptime", 8),
        B("Potential revenue loss, USD thousand (target 0)", [(r"^Potential Revenue loss \(Interbank", 8, "Potential revenue loss - interbank rate"), (r"^Potential Revenue loss \(Market", 8, "Potential revenue loss - market rate")], div=1e3, ylab="USD thousand"),
        L("Disaster recovery drills (per quarter)", r"^Disaster Recovery", 8, ylab="Number"),
        B("Zimswitch net exposure vs recoveries, ZWG million", [(r"^Zimswitch Net Exposures ZWG", 13, "Zimswitch net exposure (ZWG)"), (r"^Zimswitch Recoveries ZWG", 13, "Zimswitch recoveries (ZWG)")], div=1e6, ylab="ZWG million"),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [8, 13])], [8, 13])
    page("r10", "People & Customer KRIs (R10, R11)", "Customer experience, contact-centre speed and workforce stability.", [
        Ls("Customer service rates, % (target 80% each)", [(r"^CAR$", 11, "Call answer rate (CAR)"), (r"^Customer Satisfaction", 11, "Customer satisfaction score"), (r"^Social Media Response", 11, "Social media response rate")], ylab="Percent (%)"),
        L("Net promoter score", r"^Net Promoter", 11, ylab="Reported value"),
        B("Average waiting and handling time, seconds (limit 150)", [(r"^Average Handling", 11, "Average handling time (seconds)"), (r"^Average Waiting", 11, "Average waiting time (seconds)")], ylab="Seconds"),
        L("Employee churn", r"^Employee churn", 10), L("LAWES engagement score", r"^LAWES", 10, ylab="Reported value"),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [10, 11])], [10, 11])
    page("r12", "Credit & Third-Party KRIs (R12, R14)", "Creditors, USD debt and distributor network compliance.", [
        B("Comviva and other USD debts, USD thousand", [(r"^Comviva debt", 12, "Comviva debt (USD thousand)"), (r"^Other debts", 12, "Other USD debts (USD thousand)")], div=1e3, ylab="USD thousand"),
        B("Total vs intercompany creditors, ZWG million", [(r"^Intercompany Creditors", 12, "Intercompany creditors (ZWG million)"), (r"^Total Creditors", 12, "Total creditors (ZWG million)")], div=1e6, ylab="ZWG million"),
        L("Intercompany share of creditors", r"^Intercompany share", 12), L("DMT compliance", r"^DMT Compliance", 14),
        B("EcoCash franchises", [(r"^Ecocash Franchise", 14, "EcoCash franchises")], ylab="Number", sub="Reported actual each quarter. The reports set no target for this KRI."),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [12, 14])], [12, 14])
    page("b01", "Board Trust Risks & Business Model Elements (B01-B03)", "Bank concentration of trust balances and insolvency indicators (Board of Trustees).", [
        L("TN Cybertech share of trust balances", r"^TN Cybertech", 101),
        B("Other bank shares of trust balances, % (limits: ZB 7, AFC 8, CABS 11, Nedbank 4)", [(r"^AFC", 101, "AFC share"), (r"^CABS", 101, "CABS share"), (r"^Nedbank", 101, "Nedbank share"), (r"^ZB Bank", 101, "ZB Bank share")], ylab="Percent (%)"),
        L("First Capital share of trust balances", r"^First Capital", 101),
        B("Insolvency indicators, %: monetary assets (limit 26) and staff cost (limit 8)", [(r"^Monetary assets .*BOT", 102, "Monetary assets (% of total assets)"), (r"^Staff cost .*BOT", 102, "Staff cost (% of revenue)")], ylab="Percent (%)"),
        p_resid(d, "Residual risk rating (whole numbers) vs appetite 10 and inherent 25", [101, 102, 103]), p_status(d, "KRI results by quarter (number of KRIs)", [101, 102])], [101, 102, 103])
    page("x1", "Additional KRIs | Economy, Strategy & Cyber (R04, R06, R07)", "KRIs reported in the packs that sit outside the main risk pages. Each chart shows every quarter the reports provide.", [
        L("USD month-on-month inflation", r"^Inflation Rate USD"), L("ZWG month-on-month inflation", r"^Inflation Rate ZWG"), L("New products / services", r"^New Products/ ?Services", 5, ylab="Number"),
        L("USD revenue contribution", r"^USD revenue contribution$"), L("Phishing simulations per quarter", r"^Number of phishing", 7, ylab="Number"), L("Mean time to respond (hours, upper bound)", r"^Mean Time to Respond", 7, ylab="Hours")], [4, 5, 7])
    page("x2", "Additional KRIs | Credit, Technology & Trust (R12, R13, B01)", "Debt ageing, process maturity, recovery rates, trust-account bank share and the Board's view of revenue.", [
        B("ZWG debt older than 90 days (ZWG million)", [(r"^ZWG Debt more than 90", 12, "ZWG debt older than 90 days")], div=1e6, ylab="ZWG million", sub="Reported actual each quarter. The reports set no target for this KRI."),
        L("Documented processes", r"^% of Documented", 13), L("Automation score", r"^Automation score", 13), L("Recovery rate - ZWG exposures", r"^Recovery rate - ZWG", 13),
        L("Recovery rate - USD exposures", r"^Recovery rate - USD", 13), L("Revenue budget variance - BOT view", r"^Revenue budget variance - BOT", 102)], [12, 13, 101, 102])
    mon = Ls("Monetary exposure by quarter (USD thousand)", [(r"^Other debts \(US\)", 12, "Other USD debts (USD thousand)"), (r"^Potential Revenue loss \(Interbank", 8, "Potential revenue loss - interbank rate (USD k)"), (r"^Zimswitch Exposures \(USD\)", 13, "Zimswitch exposure (USD thousand)"), (r"^Zimswitch recoveries \(USD\)", 13, "Zimswitch recoveries (USD thousand)"), (r"^Potential Revenue loss \(Market", 8, "Potential revenue loss - market rate (USD k)")], div=1e3, ylab="USD thousand",
             sub="USD thousand reported through KRIs each quarter: revenue loss, Zimswitch exposure and recoveries, other USD debts.")
    mon["kind"] = "bars"
    tot = [0.0] * len(d["quarters"])
    rows = []
    for s in mon["series"]:
        vs = s["values"]; rows.append({"name": s["name"], "values": vs, "total": round(sum(v for v in vs if v is not None), 2)})
        for i, v in enumerate(vs):
            if v is not None:
                tot[i] += v
    mon["table"] = {"cats": mon["cats"], "rows": rows, "totals": [round(x, 2) for x in tot], "grand": round(sum(tot), 2)}
    page("mon", "Monetary Exposure", "USD exposure reported through indicators: potential revenue loss, Zimswitch exposure and recoveries, other USD debts.", [mon], [8, 12, 13])
    return out


# ------------------------------------------------------------------ the overview pages (period chosen by the reader)
def _att(rows, q):
    g = sum(1 for r in rows if q in r["q"] and r["q"][q]["status"] == "green"); a = sum(1 for r in rows if q in r["q"] and r["q"][q]["status"] == "amber"); rd = sum(1 for r in rows if q in r["q"] and r["q"][q]["status"] == "red")
    n = g + a + rd
    return None if not n else round((g + 0.5 * a) / n, 2)


def impact(rk, q, prev):
    """Why the rating moved, written from the figures only."""
    cur = rk["residual"].get(q); old = rk["residual"].get(prev) if prev else None
    parts = []
    if cur is None:
        return "No residual rating is stored for %s." % ql(q)
    if old is None:
        parts.append("Rated %g in %s." % (cur, ql(q)))
    elif cur == old:
        parts.append("Unchanged at %g since %s." % (cur, ql(prev)))
    else:
        parts.append("%s from %g to %g since %s." % ("Improved" if cur < old else "Worsened", old, cur, ql(prev)))
    parts.append("Within appetite (%d)." % APP if cur <= APP else "Above the appetite of %d." % APP)
    red = [r for r in rk["kris"] if q in r["q"] and r["q"][q]["status"] == "red"]
    ok = sum(1 for r in rk["kris"] if q in r["q"] and r["q"][q]["status"] == "green")
    judged = sum(1 for r in rk["kris"] if q in r["q"] and r["q"][q]["status"] in ("green", "amber", "red"))
    if judged:
        s = "%d of %d KRIs are on target" % (ok, judged)
        if red:
            s += "; off target: " + ", ".join("%s %s (target %s)" % (r["name"], r["q"][q]["text"], r["q"][q]["target"] or r["target"]) for r in red[:3])
        parts.append(s + ".")
    better = [r for r in rk["kris"] if r.get("move") == "better" and q in r["q"]][:2]
    worse = [r for r in rk["kris"] if r.get("move") == "worse" and q in r["q"]][:2]
    if better:
        parts.append("Improving: " + ", ".join(r["name"] for r in better) + ".")
    if worse:
        parts.append("Worsening: " + ", ".join(r["name"] for r in worse) + ".")
    return " ".join(parts)


def summary(d, q=None):
    qs = d["quarters"]
    if not qs:
        return {"empty": True}
    q = q if q in qs else qs[-1]
    prev = qs[qs.index(q) - 1] if qs.index(q) > 0 else None
    risks, inds = [], []
    for rk in d["risks"]:
        res = {x: rk["residual"].get(x) for x in qs}
        cur = res.get(q); old = res.get(prev) if prev else None
        risks.append({"no": rk["no"], "code": rk["code"], "name": short_name(rk), "category": category(rk), "register": "Board of Trustees" if rk["no"] >= 100 else "Enterprise (RISCO)", "inherent": INH, "residual": res, "current": cur,
                      "change": (None if cur is None or old is None else round(cur - old, 2)), "appetite": (None if cur is None else ("Within appetite" if cur <= APP else "Outside appetite")),
                      "effect": (None if cur is None else round(1 - cur / INH, 2)), "att": {x: _att(rk["kris"], x) for x in qs}, "impact": impact(rk, q, prev), "band": {x: band(res[x]) for x in qs}})
        for r in rk["kris"]:
            c = r["q"].get(q)
            if not c:
                continue
            dr = _dir(r)
            inds.append({"id": rk["code"], "risk": short_name(rk), "category": category(rk), "kri": r["id"], "name": r["name"], "unit": r["unit"] or "", "better": ("Lower is better" if dr == "lower" else "Higher is better" if dr == "higher" else "No target"),
                         "target": c["target"] or r["target"] or "", "value": c["text"], "status": c["status"]})
    g = sum(1 for i in inds if i["status"] == "green"); a = sum(1 for i in inds if i["status"] == "amber"); rd = sum(1 for i in inds if i["status"] == "red"); inf = sum(1 for i in inds if i["status"] == "info")
    n = g + a + rd
    rated = [x for x in risks if x["current"] is not None]
    avg = round(sum(x["current"] for x in rated) / len(rated), 1) if rated else None
    return {"period": q, "prev": prev, "risks": risks, "indicators": inds, "quarters": qs,
            "tiles": {"rated": len(rated), "inherent": INH, "avg_residual": avg, "outside": sum(1 for x in rated if x["current"] > APP), "within": sum(1 for x in rated if x["current"] <= APP),
                      "effect": (None if avg is None else int(100 * (1 - avg / INH) + 0.5)), "assessed": n, "met": g, "near": a, "breached": rd, "info": inf, "attainment": (None if not n else int(100 * (g + 0.5 * a) / n + 0.5))}}
