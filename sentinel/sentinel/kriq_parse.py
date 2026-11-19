"""Reads quarterly KRIs (Step 22) from the Board of Trustees and Risk Committee decks (.pptx) and from Excel, using only the standard library.

A deck carries, on its "Detailed Risks" slides, a risk table (# / risk / rating / key mitigations / residual risk by quarter) followed by one KRI table per risk
(KRI / Target / Q3 / Q4 / Q1 / Q2 ...). The financial year starts on 1 March, so Q1 = Mar-May, Q2 = Jun-Aug, Q3 = Sep-Nov, Q4 = Dec-Feb, named by the year it ends in.
A column headed "Q3" in the Q2 FY27 deck is Q3 FY26: the latest quarter on or before the deck's own quarter with that number."""
import datetime
import io
import re
import zipfile
import xml.etree.ElementTree as ET

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

LOWER_WORDS = ("debt", "loss", "fraud", "swap", "incident", "churn", "exposure", "fine", "corrective", "inspection", "new si", "expense", "cost", "waiting", "handling",
               "unauthori", "attrition", "inflation", "churn", "creditor", "variance in", "outage", "downtime", "complaint", "breach", "phishing attack", "arrears", "write-off", "writeoff")


# ------------------------------------------------------------------ financial quarters
def parse_fq(s):
    """'FY27Q2', 'Q2 FY2027', 'Q2FY27', '2027 Q2' -> (2027, 2) or None."""
    s = str(s or "").upper().replace(" ", "")
    m = re.search(r"FY(\d{2,4})Q([1-4])", s) or re.search(r"(\d{4})Q([1-4])", s)
    if m:
        fy = int(m.group(1)); return (fy + 2000 if fy < 100 else fy, int(m.group(2)))
    m = re.search(r"Q([1-4])FY(\d{2,4})", s)
    if m:
        fy = int(m.group(2)); return (fy + 2000 if fy < 100 else fy, int(m.group(1)))
    return None


def fq_str(t):
    return "FY%02dQ%d" % (t[0] % 100, t[1])


def fq_prev(t):
    return (t[0], t[1] - 1) if t[1] > 1 else (t[0] - 1, 4)


def fq_next(t):
    return (t[0], t[1] + 1) if t[1] < 4 else (t[0] + 1, 1)


def fq_key(s):
    t = parse_fq(s)
    return t[0] * 10 + t[1] if t else 0


def fq_dates(s):
    """(start, end) dates of a financial quarter. FY27 = 1 Mar 2026 to 28 Feb 2027."""
    fy, q = parse_fq(s)
    sm = 3 + 3 * (q - 1); sy = fy - 1
    start = datetime.date(sy + (sm - 1) // 12, (sm - 1) % 12 + 1, 1)
    em = sm + 3; ey = sy + (em - 1) // 12; em = (em - 1) % 12 + 1
    return start, datetime.date(ey, em, 1) - datetime.timedelta(days=1)


def fq_of_date(d):
    m = d.month; fy = d.year + (1 if m >= 3 else 0); q = ((m - 3) % 12) // 3 + 1
    return fq_str((fy, q))


def label_to_fq(label, deck):
    """'Q3' read in a deck of quarter `deck` (a tuple) -> the latest quarter <= deck that is Q3."""
    m = re.match(r"^\s*Q([1-4])\b", str(label or ""), re.I)
    if not m:
        return None
    q = int(m.group(1)); t = deck
    for _ in range(4):
        if t[1] == q:
            return fq_str(t)
        t = fq_prev(t)
    return None


# ------------------------------------------------------------------ values and targets
def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


CANON = [(1, "Business Performance Risk", ("businessperformance",)), (2, "Competition Risk", ("competition",)), (3, "Escalating Operating Expenses Risk", ("escalating", "operatingexpense")),
         (4, "Economic Risk", ("economic",)), (5, "Regulatory Risk", ("regulatory",)), (6, "Business Model Risk", ("businessmodel",)), (7, "Cyber Security & Fraud Risk", ("cybersecurity", "cyber", "fraudrisk")),
         (8, "BCM Risk", ("bcm", "businesscontinuity")), (9, "Money Laundering Risk", ("moneylaundering", "mlrisk")), (10, "Staff Attrition & Disengagement Risk", ("staff", "attrition", "disengagement")),
         (11, "Conduct Risk", ("conduct",)), (12, "Credit Risk", ("credit",)), (13, "Digital Transformation & Technology Risk", ("digitaltransformation", "technologyrisk")),
         (14, "Over-reliance on Third Parties", ("thirdparty", "overreliance")), (101, "Protection of Trust Funds: Credit Risk (Board of Trustees)", ("protectionoftrust", "trustfund")),
         (102, "Insolvency of Operators: EcoCash (Board of Trustees)", ("insolvency",)), (103, "Investment Risk (Board of Trustees)", ("investmentrisk",))]


def canon_risk(name):
    """The numbering of the risks changes from deck to deck, so a risk is recognised by its name. -> (number, standard name)."""
    n = norm(name)
    for no, nm, keys in sorted(CANON, key=lambda x: -x[0] // 100):  # the Board of Trustees' own risks are tested first ("credit risk" also appears in their title)
        pass
    for no, nm, keys in sorted(CANON, key=lambda x: 0 if x[0] >= 100 else 1):
        if any(k in n for k in keys):
            return no, nm
    return 200 + sum(ord(c) for c in n) % 700, clean_name(name)


def clean_name(s):
    s = re.sub(r"\s+", " ", str(s or "").replace(" ", " ")).strip()
    return re.sub(r"[\s*.]+$", "", s)


NUM = r"(-?\d[\d,]*\.?\d*|-?\.\d+)"
CUR = {"$": "USD", "US$": "USD", "USD": "USD", "ZWG": "ZWG", "ZIG": "ZWG", "ZWL": "ZWG"}


def parse_value(raw, scale=None):
    """-> (number or None, unit or None). Percent stays a percent number; k / M / bn are expanded; hh:mm is read as minutes:seconds and kept in seconds."""
    s = str(raw if raw is not None else "").replace(" ", " ").replace("*", "").strip()
    if not s or s in ("-", "–", "—") or s.lower() in ("n/a", "na", "nil"):
        return None, None
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        return float(int(m.group(1)) * 60 + int(m.group(2))), "mm:ss"
    m = re.match(r"^(USD|US\$|\$|ZWG|ZiG|ZWL)?\s*" + NUM + r"\s*(%|bn|Mn|MN|mn|M|m|k|K)?\s*$", s, re.I)
    if not m:
        return None, None
    cur, n, suf = m.groups()
    try:
        v = float(re.sub(r",(?=\d{1,2}$)", ".", n).replace(",", ""))  # '2,5K' is 2.5K; '3,861' is 3861
    except ValueError:
        return None, None
    unit = CUR.get((cur or "").upper()) if cur else None
    sl = (suf or "").lower()
    if sl == "%":
        unit = "%"
    elif sl == "k":
        v *= 1e3
    elif sl in ("m", "mn"):
        v *= 1e6
    elif sl == "bn":
        v *= 1e9
    elif scale and 0 < abs(v) < 1000:
        v *= scale
    return v, unit


def target_scale(t):
    m = re.search(r"\d\s*(bn|mn|m|k)\s*$", str(t or "").strip(), re.I)
    return {"bn": 1e9, "mn": 1e6, "m": 1e6, "k": 1e3}.get(m.group(1).lower()) if m else None


def parse_target(raw, name=""):
    """-> (op 'ge'|'le'|None, number, unit). A bare target is read 'at least' unless it is 0 or the indicator is something you want less of."""
    s = str(raw or "").replace(" ", " ").strip()
    if not s:
        return None, None, None
    op = None
    if s[0] in ">≥":
        op = "ge"
    elif s[0] in "<≤":
        op = "le"
    body = s.lstrip("<>≥≤= ").strip()
    if re.match(r"^\d{1,2}:\d{2}$", body):
        v, u = parse_value(body)
    else:
        v, u = parse_value(body)
    if v is None:
        return op, None, None
    if op is None:
        op = "le" if (v == 0 or lower_better(name)) else "ge"
    return op, v, u


def lower_better(name):
    n = str(name or "").lower()
    return any(w in n for w in LOWER_WORDS)


ALIAS = {"otpfraud": "otpfraudandsimswap", "technicalissues": "technicalincidents", "potentiallossinterbankrate": "potentialrevenuelossinterbankrate", "potentiallossmarketrate": "potentialrevenuelossmarketrate",
         "usdcontribution": "usdrevenuecontribution", "budgetvariance": "revenuebudgetvariance", "foreignexchangeloss": "foreignexchangelossrevenue", "netpromoterscore": "netpromoterscore"}


def kri_norm(name):
    n = norm(name)
    return ALIAS.get(n, n)


def status(value, raw, op, target, target_raw, unit=None):
    """'green' | 'amber' | 'red' | 'info' (no target or not comparable)."""
    if value is None:
        if raw and target_raw and norm(raw) == norm(target_raw):
            return "green"
        return "info"
    if target is None or op is None:
        return "info"
    if unit_of(target_raw) == "%" and abs(value) > 1000:
        return "info"
    if op == "ge":
        if value >= target:
            return "green"
        short = (target - value) / abs(target) if target else 1
    else:
        if value <= target:
            return "green"
        short = (value - target) / abs(target) if target else 1
    return "amber" if short <= 0.10 else "red"


def unit_of(raw):
    return parse_target(raw)[2] if raw else None


def fmt_value(v, unit):
    if v is None:
        return "\u2013"
    if unit == "%":
        return ("%.2f" % v).rstrip("0").rstrip(".") + "%"
    if unit == "mm:ss":
        return "%d:%02d" % (int(v) // 60, int(v) % 60)
    pre = (unit + " ") if unit in ("USD", "ZWG") else ""
    a = abs(v); z = lambda x: ("%.2f" % x).rstrip("0").rstrip(".")
    if a >= 1e9:
        s = z(v / 1e9) + "bn"
    elif a >= 1e6:
        s = z(v / 1e6) + "M"
    elif pre and a >= 1e3:
        s = ("%.1f" % (v / 1e3)).rstrip("0").rstrip(".") + "K"
    elif a == int(a):
        s = "{:,}".format(int(v))
    else:
        s = z(v)
    return pre + s


# ------------------------------------------------------------------ reading a .pptx with the standard library
def pptx_slides(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    if "ppt/presentation.xml" not in names:
        raise ValueError("This is not a PowerPoint (.pptx) file.")
    rels = {}
    if "ppt/_rels/presentation.xml.rels" in names:
        for r in ET.fromstring(z.read("ppt/_rels/presentation.xml.rels")):
            rels[r.get("Id")] = r.get("Target")
    order = []
    for s in ET.fromstring(z.read("ppt/presentation.xml")).iter(P + "sldId"):
        t = rels.get(s.get(R + "id"))
        if t:
            order.append("ppt/" + t.lstrip("/").replace("ppt/", "", 1) if not t.startswith("/") else t.lstrip("/"))
    if not order:
        order = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    out = []
    for n in order:
        if n not in names:
            continue
        root = ET.fromstring(z.read(n)); tables = []
        for tbl in root.iter(A + "tbl"):
            rows = []
            for tr in tbl.iter(A + "tr"):
                rows.append(["\n".join("".join(t.text or "" for t in p.iter(A + "t")) for p in tc.iter(A + "p")).strip() for tc in tr.findall(A + "tc")])
            tables.append(rows)
        text = " ".join("".join(t.text or "" for t in p.iter(A + "t")) for p in root.iter(A + "p"))
        out.append({"tables": tables, "text": text})
    return out


def deck_quarter(slides):
    for s in slides[:4]:
        m = re.search(r"Q([1-4])\s*FY\s*(\d{2,4})", s["text"], re.I) or re.search(r"Q([1-4])\s*(?:of\s*)?(?:FY|financial year)\s*(\d{2,4})", s["text"], re.I)
        if m:
            fy = int(m.group(2)); return (fy + 2000 if fy < 100 else fy, int(m.group(1)))
    return None


def extract_deck(slides, deck):
    """-> {'risks': [{no, name, category, rating, residual:{fq: n}, notes:{fq: text}}], 'kris': [{risk_no, name, target, values:{fq: raw}}], 'warnings': []}"""
    risks, kris, warn = {}, [], []
    cur = []; ki = 0; last = None
    for si, sl in enumerate(slides, 1):
        cur_slide_started = False
        for rows in sl["tables"]:
            if not rows or len(rows[0]) < 2:
                continue
            h = [c.strip() for c in rows[0]]
            if h[0].startswith("#") and "risk" in h[1].lower() and len(h) > 2 and "rating" in h[2].lower():
                cur, ki, cur_slide_started = [], 0, True
                trust = h[1].strip().lower() == "risk"  # the Board of Trustees' own register (trust funds, insolvency, investment) is numbered from 1 too: keep it apart
                mit = next((i for i, c in enumerate(h) if c.lower().startswith("key mitig")), None)
                res = [(i, label_to_fq(re.sub(r"(?i)residual risk\s*", "", c), deck)) for i, c in enumerate(h) if c.lower().startswith("residual")]
                for r in rows[1:]:
                    if not r or not re.match(r"^\d+$", r[0].strip()):
                        continue
                    lines = [x.strip(" /") for x in r[1].split("\n") if x.strip(" /")]
                    no, std = canon_risk(lines[0] if lines else "Risk " + r[0])
                    cat = re.search(r"Risk Category\s*:\s*([A-Za-z &]+)", r[1])
                    rk = risks.setdefault(no, {"no": no, "name": std, "category": None, "rating": None, "residual": {}, "notes": {}})
                    if cat:
                        rk["category"] = cat.group(1).strip()
                    if no >= 100 and no < 200:
                        rk["category"] = "Board of Trustees"
                    try:
                        rk["rating"] = float(r[2])
                    except (ValueError, IndexError):
                        pass
                    for i, fq in res:
                        try:
                            if fq: rk["residual"][fq] = float(r[i])
                        except (ValueError, IndexError):
                            pass
                    if mit is not None and mit < len(r) and r[mit].strip():
                        rk["notes"][fq_str(deck)] = re.sub(r"\s+", " ", r[mit]).strip()[:1500]
                    cur.append(no); last = no
            elif len(h) >= 3 and h[1].lower() == "target":
                cols = [(i, label_to_fq(c, deck)) for i, c in enumerate(h) if i >= 2]
                cols = [(i, fq) for i, fq in cols if fq]
                if not cols:
                    continue
                rno = cur[min(ki, len(cur) - 1)] if cur else last
                ki += 1
                if rno is None:
                    warn.append("Slide %d: a KRI table with no risk before it was skipped" % si); continue
                for r in rows[1:]:
                    nm = clean_name(r[0]) if r else ""
                    if not nm:
                        continue
                    vals = {fq: r[i].strip() for i, fq in cols if i < len(r) and r[i].strip() != ""}
                    kris.append({"risk_no": rno, "name": nm, "target": (r[1] if len(r) > 1 else "").strip(), "values": vals})
    return {"risks": list(risks.values()), "kris": kris, "warnings": warn}


# ------------------------------------------------------------------ reading Excel
def excel_rows(data):
    """-> {'kris': [(risk_no, risk, category, kri, target, fq, raw)], 'residual': [(risk_no, fq, residual, note)], 'warnings': []}"""
    from . import xlsx
    book = xlsx.read(data); out = {"kris": [], "residual": [], "warnings": []}

    def cells(r):
        return [("" if c is None else (str(c).strip() if not isinstance(c, float) else c)) for c in r]

    def hdr(rows):
        for i, r in enumerate(rows[:25]):
            low = [str(c).strip().lower() for c in r]
            if "kri" in low or any(parse_fq(c) and re.match(r"^(fy\d{2,4}q[1-4]|q[1-4]\s*fy\d{2,4})$", str(c).replace(" ", "").lower()) for c in r):
                return i, low
        return None, None
    for name, rows in book.items():
        i, low = hdr(rows)
        if i is None:
            continue
        col = lambda *ws: next((k for k, c in enumerate(low) if c in ws), None)
        ck, cr, cn, cc, ct, cq, cv = col("kri", "key risk indicator", "kri name"), col("risk", "risk name"), col("risk no", "risk no.", "#", "no", "risk #"), col("category", "risk category"), col("target"), col("quarter", "fq", "period"), col("value", "new value", "actual")
        qcols = [(k, parse_fq(c)) for k, c in enumerate(rows[i]) if re.match(r"^(fy\d{2,4}q[1-4]|q[1-4]\s*fy\d{2,4})$", str(c).replace(" ", "").lower())]
        if ck is None:
            continue
        for r in rows[i + 1:]:
            r = list(r) + [None] * 14
            nm = clean_name(r[ck])
            if not nm:
                continue
            no = r[cn] if cn is not None else None
            try:
                no = int(float(no))
            except (TypeError, ValueError):
                no = None
            base = (no, str(r[cr] or "").strip() if cr is not None else "", str(r[cc] or "").strip() if cc is not None else "", nm, str(r[ct] if ct is not None and r[ct] is not None else "").strip())
            if cq is not None and cv is not None:
                fq = parse_fq(r[cq])
                if fq and r[cv] not in (None, ""):
                    out["kris"].append(base + (fq_str(fq), r[cv]))
            for k, fq in qcols:
                if r[k] not in (None, ""):
                    out["kris"].append(base + (fq_str(fq), r[k]))
    for name, rows in book.items():
        if "resid" not in name.lower():
            continue
        head = [str(c).strip().lower() for c in (rows[0] if rows else [])]
        for r in rows[1:]:
            d = dict(zip(head, list(r) + [None] * 8))
            try:
                no = int(float(d.get("risk no") or d.get("#") or d.get("no")))
            except (TypeError, ValueError):
                continue
            fq = parse_fq(d.get("quarter") or d.get("fq"))
            try:
                rv = float(d.get("residual") if d.get("residual") not in (None, "") else d.get("residual risk"))
            except (TypeError, ValueError):
                continue
            if fq:
                out["residual"].append((no, fq_str(fq), rv, str(d.get("comment") or d.get("note") or "").strip()))
    return out
