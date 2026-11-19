"""The risk assessment register in the format of the register template (ISMS and BCMS Risk Assessment workbook):
the Strategic Coverage Summary (objectives covered by ISMS and BCMS), the register with one row per risk (the Aggregation Sheet columns), and for each
risk the three blocks of its sheet: risk identification, risk assessment (controls by P2ST2 category with ICE) and risk treatment."""
import json
import re

from . import analytics, depts, xlsxbook
from .api import router, need
from .core import audit
from .p2 import xlsx_response
from .web import HTTPError

DOMAINS = analytics.DOMAINS


def so_key(name):
    m = re.match(r"\s*SO\s*0*(\d+)", name or "", re.I)
    return int(m.group(1)) if m else 99


def position(r):
    t, a, tol = r.get("rr_target") or 6.0, r.get("rr_appetite") or 12.0, r.get("rr_tolerance") or 15.0
    v = r["rrr"]
    if v is None:
        return "Not assessed"
    return "Within target" if v <= t else "Within appetite" if v <= a else "Above appetite" if v <= tol else "Above tolerance"


def coverage(rows):
    so = {}
    for r in rows:
        d = so.setdefault(r["so"], {"so": r["so"], "bcms": [], "isms": []})
        (d["bcms"] if r["system"] == "BCMS" else d["isms"]).append(r["source_ref"] or r["ref"])
    out = []
    for name in sorted(so, key=so_key):
        d = so[name]; b, i = len(d["bcms"]), len(d["isms"])
        out.append({"so": name, "bcms": b, "isms": i, "total": b + i, "status": "Covered" if b and i else "Gap", "bcms_ids": ", ".join(sorted(d["bcms"])), "isms_ids": ", ".join(sorted(d["isms"])), "coverage": 1 if b and i else 0})
    return out


def register_rows(db, c):
    rows, _ = analytics.risk_rows(db, c)
    extra = {r["id"]: r for r in db.execute("SELECT id, objective, treatment, action_date, assessed_on, assess_source, root_cause, implication FROM risks WHERE deleted_at IS NULL AND (is_sample IS NULL OR is_sample=0)")}
    out = []
    for r in rows:
        e = extra.get(r["id"])
        out.append(dict(r, objective=e["objective"], treatment=e["treatment"], action_date=e["action_date"], assessed_on=e["assessed_on"], assess_source=e["assess_source"], position=position(r),
                        judgement=bool(r["avg_ice"] is not None and r["lor"] is not None and r["method"] == "workbook" and abs(r["lor"] - r["avg_ice"]) > 0.06)))
    out.sort(key=lambda z: (so_key(z["so"]), -(z["rrr"] or -1), z["source_ref"] or ""))
    return out


@router.route("GET", "/api/register/assessment")
def register_assessment(req):
    c = need(req, "risk_register", "view")
    rows = register_rows(req.db, c)
    return {"coverage": coverage(rows), "risks": rows, "summary": {"objectives": len({r["so"] for r in rows}), "bcms": sum(1 for r in rows if r["system"] == "BCMS"), "isms": sum(1 for r in rows if r["system"] == "ISMS"), "risks": len(rows),
            "dual": sum(1 for x in coverage(rows) if x["status"] == "Covered"), "assessed": sum(1 for r in rows if r["rrr"] is not None), "judgement": sum(1 for r in rows if r["judgement"]),
            "above_appetite": sum(1 for r in rows if r["position"] in ("Above appetite", "Above tolerance")), "can_export": "export" in c.perms.get("risk_register", set())}}


@router.route("GET", "/api/register/risk/<int:rid>")
def register_risk(req):
    c = need(req, "risk_register", "view")
    row = next((r for r in register_rows(req.db, c) if r["id"] == int(req.params["rid"])), None)
    if not row:
        raise HTTPError(404, "not_found", "Risk not found.")
    r = req.db.execute("SELECT wb_detail, root_cause, implication, description FROM risks WHERE id=?", (row["id"],)).fetchone()
    det = json.loads(r["wb_detail"]) if r["wb_detail"] else {}
    ctl = [dict(x, dept=depts.dept_of(x["owner"])) for x in req.db.execute("SELECT ref, domain, statement, owner, ice, ice_prev FROM risk_controls WHERE risk_id=? ORDER BY domain, ref", (row["id"],))]
    by = {d: [x for x in ctl if x["domain"] == d] for d in DOMAINS}
    return {"risk": row, "factors": det.get("cfs") or [], "treatments": det.get("treatments") or [], "controls": by, "sheet_lor": det.get("sheet_lor"), "agg": det.get("agg")}


@router.route("GET", "/api/register/export.xlsx")
def register_export(req):
    c = need(req, "risk_register", "export")
    rows = register_rows(req.db, c); cov = coverage(rows)
    s1 = [[("STRATEGIC OBJECTIVE COVERAGE", 3)], [("ISMS and BCMS alignment ahead of the strategic objectives", 4)], [],
          [(h, 1) for h in ("Strategic Objective", "BCMS Count", "ISMS Count", "Total", "Coverage Status", "BCMS Objective IDs", "ISMS Objective IDs", "Coverage %")]]
    for x in cov:
        s1.append([x["so"], x["bcms"], x["isms"], x["total"], x["status"], x["bcms_ids"], x["isms_ids"], x["coverage"]])
    s1.append([("Total", 1), sum(x["bcms"] for x in cov), sum(x["isms"] for x in cov), sum(x["total"] for x in cov), "", "", "", ""])
    hdr = ["Ref #", "Evaluation Date", "Strategic Objective", "ISMS/BCMS Objective", "Risk Description", "Risk Owner", "Department", "EMV-i", "IRR"] + [d + " ICE" if i % 2 == 0 else d + " Count" for d in DOMAINS for i in (0, 1)] + ["LoR", "LoA", "EMV-r", "RRR", "EMV-a", "Position against appetite", "Status"]
    s2 = [[("EcoCash risk assessment register (the Aggregation Sheet format)", 3)], [("RRR = 25 x (LoR + 0.04). LoA = 1 - LoR. Position uses the workbook's target, appetite and tolerance (6, 12, 15).", 4)], [], [(h, 1) for h in hdr]]
    for r in rows:
        line = [r["source_ref"] or r["ref"], r["assessed_on"], r["so"], r["objective"], r["title"], r["owner"], r["dept"], r["emv_i"], 25]
        for d in DOMAINS:
            line += [r["domains"][d]["ice"], r["domains"][d]["n"]]
        s2.append(line + [r["lor"], r["loa"], r["emv_r"], r["rrr"], r["emv_a"], r["position"], r["status"]])
    s3 = [[("Controls by risk and P2ST2 category", 3)], [], [(h, 1) for h in ("Risk", "Category", "Control Ref", "Control", "Control Owner", "Department", "ICE 2025", "ICE 2026", "Effectiveness 2026 (1 - ICE)")]]
    s4 = [[("Risk treatment", 3)], [], [(h, 1) for h in ("Risk", "TR#", "CF#", "Treatment option", "Action steps 2025", "Action steps 2026", "EMV-a 2025", "EMV-a 2026", "RR target", "RR appetite", "RR tolerance", "Responsible", "Due", "Comments")]]
    for r in rows:
        d = req.db.execute("SELECT wb_detail FROM risks WHERE id=?", (r["id"],)).fetchone()["wb_detail"]
        for t in (json.loads(d).get("treatments") if d else []) or []:
            s4.append([r["source_ref"] or r["ref"], t["tr"], t["cf"], t["option"], t["steps25"], t["steps26"], t["emv_a25"], t["emv_a26"], t["target"], t["appetite"], t["tolerance"], t["responsible"], t["due"], t["comment"]])
        for x in req.db.execute("SELECT ref, domain, statement, owner, ice, ice_prev FROM risk_controls WHERE risk_id=? ORDER BY domain, ref", (r["id"],)):
            s3.append([r["source_ref"] or r["ref"], x["domain"], x["ref"], x["statement"], x["owner"], depts.dept_of(x["owner"]), x["ice_prev"], x["ice"], None if x["ice"] is None else round(1 - x["ice"], 3)])
    sheets = [("Strategic Coverage Summary", s1, [34, 12, 12, 10, 16, 44, 44, 12])]
    from . import dq
    store = req.db.execute("SELECT id FROM wb_store WHERE kind='risk' AND deleted_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    if store:  # the sheets of the saved workbook, repaired and with the controls as the register now holds them
        dbc = {}
        for x in req.db.execute("SELECT k.risk_id, k.ref, k.domain, k.ice, r.source_ref FROM risk_controls k JOIN risks r ON r.id=k.risk_id WHERE r.deleted_at IS NULL"):
            dbc[(x["source_ref"], x["ref"])] = x
        for sh in req.db.execute("SELECT name, grid FROM wb_sheets WHERE store_id=? ORDER BY sort", (store["id"],)):
            g = json.loads(sh["grid"])
            if sh["name"] == "Strategic Coverage Summary":
                continue
            rows_ = []
            for ri, row in enumerate(g):
                row = list(row)
                if len(sh["name"]) == 4 and sh["name"][1] == "-" and ri >= 2 and len(row) > 18 and row[13]:
                    key = re.sub(r"^\S+\s*(\d+).*", lambda m: None, "x")
                    ref0 = next((str(r0[0]) for r0 in g[2:4] if r0 and r0[0]), "")
                    m = re.search(r"(ISMS|BCMS)\s*0*(\d+)", ref0); sref = "%s %02d" % (m.group(1), int(m.group(2))) if m else None
                    x = dbc.get((sref, str(row[13]).strip()))
                    if x:
                        row[10] = x["domain"]
                        if x["ice"] is not None:
                            row[18] = x["ice"]
                rows_.append([(c, 1) if ri < 2 and isinstance(c, str) and c else c for c in row])
            sheets.append((sh["name"][:31], rows_, [18] * 6 + [14] * 30))
    sheets += [("Register", s2, [14, 14, 30, 50, 60, 22, 24, 14, 6] + [10, 8] * 5 + [8, 8, 14, 8, 12, 22, 12]), ("Controls", s3, [16, 12, 14, 70, 30, 26, 10, 10, 14]), ("Treatment", s4, [14, 8, 8, 16, 50, 50, 12, 12, 9, 9, 9, 24, 12, 40])]
    audit(req.db, "export.register", c.user, "risk_register", "Risk assessment register downloaded (%d risks)" % len(rows), req.ip)
    return xlsx_response(xlsxbook.write(sheets), "Sentinel_risk_assessment_register.xlsx")


@router.route("GET", "/api/register/key")
def register_key(req):
    """The Key tab: the risk matrix recommended by the external auditor (ranked, a lookup), beside the workbook's own matrix; the internal control effectiveness
    scale; and the risk treatment guidance, as in the workbook's -key sheet."""
    need(req, "risk_register", "view")
    from . import dq, matrix as mx
    g = dq.stored_grid(req.db, "-key") or []
    wb_matrix = [[(g[r][c] if r < len(g) and c < len(g[r]) else None) for c in range(0, 6)] for r in range(1, 7)] if g else []
    ice = []
    for r in g[2:]:
        r = list(r) + [None] * 17
        if r[8] not in (None, "") and str(r[8]).strip().isdigit():
            ice.append({"score": int(str(r[8]).strip()), "description": r[9], "classification": r[10], "factor": r[11], "effectiveness": r[12], "treatment": r[13]})
    return {"auditor": {"cells": [{"l": l, "c": c, "rank": rk, "level": mx.level(rk)} for (l, c), rk in sorted(mx.MATRIX.items(), reverse=True)], "likelihood": mx.LIKELIHOOD, "consequence": mx.CONSEQUENCE, "bands": [{"level": b[0], "from": b[1], "to": b[2], "response": mx.RESPONSE[b[0]]} for b in mx.BANDS], "thresholds": mx.THRESH},
            "workbook_matrix": wb_matrix, "ice": ice, "saved": bool(g)}
