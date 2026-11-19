"""Import the ISMS / BCMS risk assessment workbook (one sheet per risk, one row per control) into the register."""
import re

from . import xlsx

SKIP = {"Strategic Coverage Summary", "Integration", "Aggregation Sheet", "-key"}
DOMAINS = ("People", "Process", "Systems", "Technology", "Tools")
SO = re.compile(r"\s*SO\s*0*(\d+)\s*[-\u2013\u2014:]?\s*(.*)$", re.I)
KEY = re.compile(r"\b(ISMS|BCMS)\s*0*(\d+)", re.I)


def num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def clean(v, n=None):
    from .textfix import repair  # text damaged by a global find-and-replace is repaired as it is read
    s = repair(re.sub(r"\s+", " ", str(v)).strip()) if v is not None else ""
    return s[:n] if n else s


def grid_of(rows):
    """A sheet as a list of rows, trimmed of empty trailing cells, with the find-and-replace damage repaired and numbers rounded."""
    from .textfix import repair
    out = []
    for r in rows:
        r = list(r)
        while r and r[-1] in (None, ""):
            r.pop()
        out.append([repair(round(c, 6) if isinstance(c, float) else c) for c in r])
    while out and not out[-1]:
        out.pop()
    return out


def dept_of(owner):
    """The EcoCash department (from the ERCO report) for an owner written as a job title."""
    from . import depts
    return depts.dept_of(owner)


def owner_function(owner):
    """The 'function' of a risk (used for department data scope): the first owner named, without 'Head of' wording. The EcoCash department for dashboards is dept_of."""
    s = clean(owner)
    if not s:
        return "Unassigned"
    s = re.split(r"\s*/\s*", s)[0]
    s = re.sub(r"\s*-\s*Head.*$", "", s, flags=re.I)
    s = re.sub(r"^Head[\s-]+(of\s+)?", "", s, flags=re.I).strip(" -")
    return s or "Unassigned"


def residual_cell(rrr, inh_l=5, inh_c=5):
    """The likelihood and consequence whose product is closest to the workbook's residual rating (RRR, 0 to 25); on a tie the higher consequence is kept,
    because controls mostly reduce how likely a risk is, not how bad it would be."""
    best = None
    for l in range(1, inh_l + 1):
        for c in range(1, inh_c + 1):
            k = (abs(l * c - rrr), -c, l)
            if best is None or k < best[0]:
                best = (k, l, c)
    return best[1], best[2]


def ref_key(text):
    m = KEY.search(text or "")
    return "%s %02d" % (m.group(1).upper(), int(m.group(2))) if m else None


def parse(data):
    """Return {"risks": [...], "warnings": [...]} without touching the database."""
    sheets = xlsx.read(data)
    warnings, agg = [], {}
    rows = sheets.get("Aggregation Sheet") or []
    if rows:
        head = [clean(h) for h in rows[0]]
        for r in rows[1:]:
            k = ref_key(r[0] if r else None)
            if k:
                agg[k] = {h: r[i] for i, h in enumerate(head) if i < len(r)}
    risks = []
    for name, rows in sheets.items():
        if name in SKIP:
            continue
        if len(rows) < 3 or len(rows[1]) < 11 or clean(rows[1][2]).lower() != "risk":
            warnings.append("Sheet %s was skipped: it does not look like a risk assessment sheet." % name)
            continue
        body = [r + [None] * (35 - len(r)) for r in rows[2:]]
        first = next((r for r in body if clean(r[2])), None)
        if not first:
            warnings.append("Sheet %s was skipped: no risk description found." % name)
            continue
        key = ref_key(first[0])
        if not key:
            warnings.append("Sheet %s was skipped: the objective reference (ISMS nn or BCMS nn) was not found." % name)
            continue
        ctl = []
        for r in body:
            if r[10] in DOMAINS:
                text = clean(r[34])
                stmt = re.sub(r"^Control:\s*", "", text) if text.lower().startswith("control:") else (text or clean(r[13]))
                ice = num(r[18]) if num(r[18]) is not None else num(r[15])
                ctl.append({"ref": clean(r[13], 40), "statement": clean(stmt, 400) or clean(r[13]), "domain": r[10], "owner": clean(r[14], 120), "ice": round(ice, 2) if ice is not None else None})
        uniq = lambda i, n=6: list(dict.fromkeys(clean(r[i]) for r in body if clean(r[i])))[:n]
        emv_a_sheet = sum(num(r[27]) or 0 for r in body)
        a = agg.get(key, {})
        emv_a = num(a.get("EMV-a")) if num(a.get("EMV-a")) is not None else emv_a_sheet
        if a and abs(emv_a - emv_a_sheet) > 1:
            warnings.append("%s: action cost (EMV-a) is %s on the sheet but %s on the Aggregation Sheet; the Aggregation Sheet value was used." % (key, round(emv_a_sheet), round(emv_a)))
        if not ctl:
            warnings.append("%s has no control rows." % key)
        # the workbook's own assessment (the Aggregation Sheet, which feeds Power BI): level of risk, level of assurance, residual rating and residual value
        sheet_lor = next((num(r[18]) for r in body if clean(r[17]) == "LoR 2026" and num(r[18]) is not None), None)
        ices = [k["ice"] for k in ctl if k["ice"] is not None]
        avg_ice = sum(ices) / len(ices) if ices else None
        lor = num(a.get("LoR"))
        if lor is None:
            lor = sheet_lor if sheet_lor is not None else avg_ice
            if lor is not None:
                warnings.append("%s is not on the Aggregation Sheet; its level of risk was taken from %s." % (key, "the risk sheet" if sheet_lor is not None else "the average control ICE"))
        emv_i0 = num(first[7]) or 0.0
        rrr = num(a.get("RRR")) if num(a.get("RRR")) is not None else (25 * ((lor or 0) + 0.04) if lor is not None else None)
        emv_r = num(a.get("EMV-r")) if num(a.get("EMV-r")) is not None else (emv_i0 * lor if lor is not None else None)
        if a and sheet_lor is not None and lor is not None and abs(sheet_lor - lor) > 0.005:
            warnings.append("%s: the risk sheet %s says level of risk %.2f but the Aggregation Sheet (used by Power BI) says %.2f. The Aggregation Sheet value was used." % (key, name, sheet_lor, lor))
        for r in body:  # ICE 2025 per control, for the year-on-year view
            pass
        prev = {clean(r[13], 40): num(r[15]) for r in body if r[10] in DOMAINS and clean(r[13]) and num(r[15]) is not None}
        for k in ctl:
            k["ice_prev"] = prev.get(k["ref"])
        cfs, cur = [], None
        for r in body:
            if clean(r[3]) and clean(r[3]) != (cur or {}).get("cf"):
                cur = {"cf": clean(r[3], 12), "factor": clean(r[4], 200), "consequences": []}; cfs.append(cur)
            if cur is not None and clean(r[5]) and {"type": clean(r[5], 30), "impact": clean(r[6], 80)} not in cur["consequences"]:
                cur["consequences"].append({"type": clean(r[5], 30), "impact": clean(r[6], 80)})
        trs = [{"tr": clean(r[22], 12), "cf": clean(r[21], 12), "option": clean(r[23], 30), "steps25": clean(r[24], 220), "steps26": clean(r[25], 220), "emv_a25": num(r[26]) or 0, "emv_a26": num(r[27]) or 0, "target": num(r[28]), "appetite": num(r[29]), "tolerance": num(r[30]),
                "responsible": clean(r[31], 80), "due": xlsx.excel_date(r[33]), "comment": clean(r[34], 160)} for r in body if clean(r[22])]
        t0 = next((r for r in body if num(r[28]) is not None), None)
        det = {"cfs": cfs, "treatments": trs[:60], "agg": {d: {"ice": num(a.get(d + " ICE")), "n": int(num(a.get(d + " Count")) or 0)} for d in DOMAINS} if a else None, "sheet_lor": sheet_lor, "avg_ice": avg_ice}
        owner = clean(first[9], 120)
        risks.append({"sheet": name, "source_ref": key, "system": key.split()[0], "objective": clean(first[0], 200), "strategic_objective": clean(first[1], 120), "title": clean(first[2], 200), "owner_name": owner, "function": owner_function(owner)[:120],
                      "emv_i": num(first[7]) or 0.0, "emv_a": emv_a, "root_cause": "; ".join(uniq(4))[:1000], "implication": "; ".join(uniq(6))[:1000], "treatment": "; ".join(uniq(25, 3))[:1000],
                      "action_date": xlsx.excel_date(first[33]), "description": ("Imported from workbook sheet %s. %s" % (name, clean(first[34], 700)))[:2000], "controls": ctl,
                      "from_agg": bool(a) and num(a.get("LoR")) is not None, "lor": lor, "loa": None if lor is None else 1 - lor, "rrr": rrr, "emv_r": emv_r, "irr": num(a.get("IRR")) or num(first[8]) or 25.0, "avg_ice": avg_ice, "sheet_lor": sheet_lor, "override": bool(avg_ice is not None and lor is not None and abs(lor - avg_ice) > 0.06),
                      "assessed_on": xlsx.excel_date(a.get("Evaluation Date")) if a else None, "rr_target": num(t0[28]) if t0 else None, "rr_appetite": num(t0[29]) if t0 else None, "rr_tolerance": num(t0[30]) if t0 else None, "detail": det})
    # the same strategic objective is spelled differently on different sheets ("SO 02 - X" and "SO 02-X"): standardise on the commonest wording
    names = {}
    for r in risks:
        m = SO.match(r["strategic_objective"])
        if m:
            names.setdefault(int(m.group(1)), {}).setdefault(clean(m.group(2)), 0)
            names[int(m.group(1))][clean(m.group(2))] += 1
    changed = 0
    for r in risks:
        m = SO.match(r["strategic_objective"])
        if m:
            best = max(names[int(m.group(1))].items(), key=lambda kv: kv[1])[0]
            new = "SO %02d - %s" % (int(m.group(1)), best)
            changed += new != r["strategic_objective"]
            r["strategic_objective"] = new
    if changed:
        warnings.append("Strategic objective wording differed on %d sheets (for example hyphen spacing); it was standardised so each objective forms one group." % changed)
    if not risks:
        warnings.append("No risk sheets were found. Is this the ISMS and BCMS risk assessment workbook?")
    risks.sort(key=lambda r: (r["system"], int(r["source_ref"].split()[1])))
    return {"risks": risks, "warnings": warnings, "sheets": {n: grid_of(r) for n, r in sheets.items()}}
