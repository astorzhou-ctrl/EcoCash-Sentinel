"""Performance Analytics: the Power BI pages (All risks LoA/LoR, Top 10, Balanced Scorecard, EMV, P2ST2, Control Universe by department, Control Taxonomy,
ISO 27001 Annex A) calculated from the register.
Definitions follow the risk assessment workbook, which feeds Power BI: the Aggregation Sheet gives each risk its level of risk (LoR), level of assurance
LoA = 1 - LoR, residual risk rating RRR = 25 x (LoR + 0.04), residual value EMV-r and actual cost EMV-a. Those values are stored on the risk when the
workbook is imported. A risk entered by hand (or imported without an Aggregation Sheet row) has no workbook assessment: its LoR is the average ICE of its controls and its RRR follows the same formula; with no controls its RRR is its residual likelihood x consequence."""
from . import depts, matrix as mx
from .api import router, need, need_str
from .core import audit
from .risks import scope_sql
from .web import HTTPError

DOMAINS = ["People", "Process", "Systems", "Technology", "Tools"]


def risk_rows(db, c):
    where, args = scope_sql(c)
    risks = db.execute("SELECT * FROM risks WHERE deleted_at IS NULL AND (is_sample IS NULL OR is_sample=0) AND %s" % where, args).fetchall()  # sample risks are for trying the system out: they are not part of the assessment or the dashboards
    ids = {r["id"] for r in risks}
    ctl = [x for x in db.execute("SELECT risk_id, domain, ice, ice_prev, owner, ref FROM risk_controls") if x["risk_id"] in ids]
    by = {}
    for x in ctl:
        by.setdefault(x["risk_id"], []).append(x)
    out = []
    for r in risks:
        cs = [x for x in by.get(r["id"], []) if x["ice"] is not None]
        avg = sum(x["ice"] for x in cs) / len(cs) if cs else None
        dom = {}
        for d in DOMAINS:
            ds = [x["ice"] for x in cs if x["domain"] == d]
            dom[d] = {"n": len([x for x in by.get(r["id"], []) if x["domain"] == d]), "ice": round(sum(ds) / len(ds), 4) if ds else None}
        inh = r["inh_l"] * r["inh_c"]
        if r["rrr"] is not None and (r["assess_source"] or "").startswith("workbook"):  # assessed in the workbook (the Aggregation Sheet that feeds Power BI)
            rrr, lor, emv_r, method = r["rrr"], r["lor"], r["emv_r"], "workbook"
        elif avg is not None:  # from the controls: LoR is the average ICE, and the residual rating follows the workbook's formula
            lor = avg; rrr = 25 * (lor + 0.04); emv_r = (r["emv_i"] or 0) * lor; method = "estimated" if r["needs_assessment"] else "controls"
        elif not r["needs_assessment"]:  # no controls: the likelihood x consequence rated by hand
            rrr = float(r["res_l"] * r["res_c"]); lor = max(0.0, rrr / 25.0 - 0.04); emv_r = (r["emv_i"] or 0) * lor; method = "rated"
        else:
            rrr = lor = emv_r = None; method = "unassessed"
        out.append({"id": r["id"], "ref": r["ref"], "source_ref": r["source_ref"], "title": r["title"], "category": r["category"], "so": r["strategic_objective"] or "Unassigned", "system": r["system"], "owner": r["owner_name"], "dept": depts.dept_of(r["owner_name"]),
                    "emv_i": r["emv_i"] or 0, "emv_a": r["emv_a"] or 0, "controls": len(by.get(r["id"], [])), "avg_ice": avg, "lor": lor, "loa": None if lor is None else 1 - lor, "emv_r": emv_r, "inh_score": inh, "rrr": None if rrr is None else round(rrr, 2), "method": method,
                    "rank": mx.rank(r["res_l"], r["res_c"]), "res_l": r["res_l"], "res_c": r["res_c"], "needs_assessment": bool(r["needs_assessment"]), "rr_target": r["rr_target"], "rr_appetite": r["rr_appetite"], "rr_tolerance": r["rr_tolerance"], "status": r["status"], "domains": dom})
    return out, ctl


def summarise(rows):
    a = [r for r in rows if r["lor"] is not None]
    return {"risks": len(rows), "assessed": len(a), "emv_i": sum(r["emv_i"] for r in rows), "emv_r": sum(r["emv_r"] or 0 for r in a), "emv_a": sum(r["emv_a"] for r in rows),
            "loa": sum(r["loa"] for r in a) / len(a) if a else None, "lor": sum(r["lor"] for r in a) / len(a) if a else None}


def catalog_summary(db):
    out = {"loaded": False, "p2st2": {}, "annex": {}}
    out["extra"] = {r["category"]: r["n"] for r in db.execute("SELECT category, COUNT(*) n FROM control_catalog WHERE origin='risk' GROUP BY category")}
    for r in db.execute("SELECT kind, category, theme, COUNT(*) n, AVG(ice) a FROM control_catalog WHERE origin IS NULL OR origin='taxonomy' GROUP BY kind, category, theme"):
        out["loaded"] = True
        if r["kind"] == "p2st2":
            out["p2st2"][r["category"]] = {"n": r["n"], "ice": r["a"]}
        else:
            out["annex"][r["theme"]] = {"n": r["n"], "ice": r["a"]}
    return out


@router.route("GET", "/api/analytics")
def analytics(req):
    c = need(req, "performance_analytics", "view")
    out, ctl = risk_rows(req.db, c)
    universe, unmapped, why = {}, {}, {}
    owner_of = {r["id"]: r["owner"] for r in out}
    rd = depts.ref_departments([(x["owner"], x["ref"]) for x in ctl])
    for x in ctl:
        d, reason = depts.dept_for_control(x["owner"], x["ref"], rd, owner_of.get(x["risk_id"]))
        why[reason] = why.get(reason, 0) + 1
        k = (d, x["domain"])
        u = universe.setdefault(k, {"dept": d, "domain": x["domain"], "n": 0, "ice_sum": 0.0, "ice_n": 0})
        u["n"] += 1
        if x["ice"] is not None:
            u["ice_sum"] += x["ice"]; u["ice_n"] += 1
        if reason != "owner":
            unmapped[(x["owner"] or "None") + "  \u2192  " + d + " (" + reason + ")"] = unmapped.get((x["owner"] or "None") + "  \u2192  " + d + " (" + reason + ")", 0) + 1
    return {"risks": out, "universe": list(universe.values()), "portfolio": dict(summarise(out), controls=len(ctl), unassessed=sum(1 for r in out if r["needs_assessment"]), systems={s: summarise([r for r in out if r["system"] == s]) for s in ("ISMS", "BCMS")}),
            "departments": [{"name": r["name"], "owner": r["owner"]} for r in req.db.execute("SELECT name, owner FROM departments ORDER BY sort")], "unmapped": sorted(({"owner": k, "n": v} for k, v in unmapped.items()), key=lambda z: -z["n"])[:12],
            "dept_reasons": why, "catalog": catalog_summary(req.db), "targets": {"loa": 0.8, "lor": 0.2, "ice": 0.8}}


@router.route("GET", "/api/analytics/catalog")
def catalog_detail(req):
    need(req, "performance_analytics", "view")
    kind, cat = req.query.get("kind") or "p2st2", (req.query.get("category") or "").strip()
    q = "SELECT category, ref, statement, ice, theme, origin FROM control_catalog WHERE kind=?" + (" AND (category=? OR theme=?)" if cat else "") + " ORDER BY category, theme, origin DESC, ref"
    rows = req.db.execute(q, [kind] + ([cat, cat] if cat else [])).fetchall()
    return {"controls": [dict(r) for r in rows[:300]], "total": len(rows)}


@router.route("POST", "/api/taxonomy/import")
def taxonomy_import(req):
    """The Control Taxonomy workbook: sheet Aggregated (Category, #, Control Ref, Control Statement, ICE Factor) and sheet ISMS27001 Controls (Control ID, Control Name, Theme, ICE Factor)."""
    c = need(req, "performance_analytics", "edit")
    from . import xlsx
    data = req.body()
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    try:
        sh = xlsx.read(data)
    except Exception:
        raise HTTPError(400, "bad_file", "The workbook could not be read. Save it as .xlsx and try again.")
    p2, annex = [], []
    for r in (sh.get("Aggregated") or [])[1:]:
        r = list(r) + [None] * 6
        if r[0] in DOMAINS and r[2]:
            p2.append((str(r[2]).strip(), r[0], str(r[3] or "").strip()[:300], float(r[4]) if isinstance(r[4], (int, float)) else None))
    for r in (sh.get("ISMS27001 Controls") or [])[1:]:
        r = list(r) + [None] * 5
        if r[0] and r[2]:
            annex.append((str(r[0]).strip(), str(r[2]).strip(), str(r[1] or "").strip()[:300], float(r[3]) if isinstance(r[3], (int, float)) else None))
    if not p2 and not annex:
        raise HTTPError(400, "bad_file", "Expected the sheets 'Aggregated' and 'ISMS27001 Controls' (the EcoCash Control Taxonomy workbook).")
    out = {"p2st2": len(p2), "annex": len(annex), "by_category": {d: sum(1 for x in p2 if x[1] == d) for d in DOMAINS}, "themes": sorted({x[1] for x in annex}), "dry": req.query.get("dry") != "0"}
    if out["dry"]:
        return out
    req.db.execute("DELETE FROM control_catalog WHERE origin IS NULL OR origin='taxonomy'")  # risk-specific controls added by data quality are kept
    for ref, cat, st, ice in p2:
        req.db.execute("INSERT OR REPLACE INTO control_catalog(kind,category,ref,statement,ice,theme,origin) VALUES('p2st2',?,?,?,?,NULL,'taxonomy')", (cat, ref, st, ice))
    for ref, theme, st, ice in annex:
        req.db.execute("INSERT OR REPLACE INTO control_catalog(kind,category,ref,statement,ice,theme,origin) VALUES('annex',NULL,?,?,?,?,'taxonomy')", (ref, st, ice, theme))
    from . import workbooks
    workbooks.save_taxonomy(req.db, c.user, data, req.headers.get("X-Filename") or "control taxonomy workbook.xlsx", out)
    audit(req.db, "taxonomy.import", c.user, "performance_analytics", "Control taxonomy loaded: %d P2ST2 controls and %d ISO 27001 Annex A controls" % (len(p2), len(annex)), req.ip)
    return out


# ------------------------------------------------------------------ the dashboards as a PowerPoint
def _gauge(name, val, color, target):
    v = max(0.0, min(1.0, val or 0.0))
    return {"title": name, "ctype": "doughnut", "cats": ["Value", "Rest", "Hidden"], "series": [{"name": name, "values": [v, 1 - v, 1.0], "point_colors": [color, "E6ECF4", None], "angle": 270, "hole": 62, "nolabels": True, "nolegend": True}], "labels": False}


def deck_slides(db, c):
    rows, ctl = risk_rows(db, c)
    if not rows:
        return []
    a = [r for r in rows if r["rrr"] is not None]; sm = summarise(rows)
    cat = catalog_summary(db); M = lambda v: "$%.1fM" % (v / 1e6)
    eff = lambda ice: None if ice is None else round((1 - ice) * 100, 1)
    top = sorted(a, key=lambda r: (-r["rrr"], -r["emv_i"]))[:10]
    sl = []
    sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "ALL RISKS   |   LEVEL OF ASSURANCE (LoA) AND LEVEL OF RISK (LoR)", "source": "EcoCash Sentinel (risk assessment register)", "per_slide": 4,
               "charts": [_gauge("Average LoA (target 80%)", sm["loa"], "2FA84F" if (sm["loa"] or 0) >= .8 else "E9C440", .8), _gauge("Average LoR (target 20%)", sm["lor"], "2FA84F" if (sm["lor"] or 1) <= .2 else "E0474C", .2)],
               "bullets": ["%d risks assessed, EMV inherent %s, EMV residual %s." % (sm["assessed"], M(sm["emv_i"]), M(sm["emv_r"])), "Average LoA %.1f%%, average LoR %.1f%% (LoA = 1 \u2212 LoR)." % ((sm["loa"] or 0) * 100, (sm["lor"] or 0) * 100)] + ["%s: %d risks, LoA %.1f%%." % (s_, len(g), 100 * sum(r["loa"] for r in g if r["loa"] is not None) / max(1, sum(1 for r in g if r["loa"] is not None))) for s_ in ("ISMS", "BCMS") for g in [[r for r in a if r["system"] == s_]] if g],
               "tiles": [{"word": "%.0f%%" % ((sm["loa"] or 0) * 100), "caption": "Average LoA"}, {"word": "%.0f%%" % ((sm["lor"] or 0) * 100), "caption": "Average LoR"}, {"word": M(sm["emv_i"]), "caption": "EMV inherent"}, {"word": M(sm["emv_r"]), "caption": "EMV residual"}]})
    if top:
        sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "TOP 10 RISKS BY RESIDUAL RISK RATING (RRR)", "source": "EcoCash Sentinel", "per_slide": 4,
                   "charts": [{"title": "Top 10 risks by RRR", "ctype": "column", "cats": [r["source_ref"] or r["ref"] for r in top], "series": [{"name": "RRR", "values": [r["rrr"] for r in top], "color": "0070C0"}], "fmt": "0.0"},
                              {"title": "EMV inherent and residual ($M)", "ctype": "column", "cats": [r["source_ref"] or r["ref"] for r in top], "series": [{"name": "EMV-i", "values": [round(r["emv_i"] / 1e6, 2) for r in top], "color": "FF0000"}, {"name": "EMV-r", "values": [round((r["emv_r"] or 0) / 1e6, 2) for r in top], "color": "00B050"}], "fmt": "0.0"}],
                   "bullets": ["RRR = 25 \u00D7 (LoR + 0.04). Highest: %s at %.2f." % (top[0]["source_ref"] or top[0]["ref"], top[0]["rrr"]), "Position uses the target 6, appetite 12 and tolerance 15."], "tiles": []})
        sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "TOP 10 RISKS AND P2ST2 CONTROL EFFECTIVENESS", "source": "EcoCash Sentinel", "per_slide": 1,
                   "charts": [{"title": "Control effectiveness (1 \u2212 ICE, %) by P2ST2 category, top 10 risks", "ctype": "column", "cats": [r["source_ref"] or r["ref"] for r in top], "series": [{"name": d, "values": [eff(r["domains"][d]["ice"]) for r in top], "color": col} for d, col in zip(DOMAINS, ("2F6FD6", "3BA55C", "E9C440", "E0474C", "F0A04B"))], "fmt": "0", "labels": False}], "bullets": ["People, Process, Systems, Technology and Tools: the P2ST2 control categories.", "Target effectiveness is 80%."], "tiles": []})
    sos = sorted({r["so"] for r in a})
    if sos:
        g = lambda so, k: sum(r[k] for r in a if r["so"] == so and r[k] is not None) / max(1, sum(1 for r in a if r["so"] == so and r[k] is not None))
        sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "BALANCED SCORECARD PERSPECTIVES: LoA AND LoR BY STRATEGIC OBJECTIVE", "source": "EcoCash Sentinel", "per_slide": 4,
                   "charts": [{"title": "LoA and LoR by strategic objective (%)", "ctype": "bar", "cats": [x[:28] for x in sos], "series": [{"name": "LoA", "values": [round(g(x, "loa") * 100, 1) for x in sos], "color": "0070C0"}, {"name": "LoR", "values": [round(g(x, "lor") * 100, 1) for x in sos], "color": "FF0000"}], "fmt": "0"},
                              {"title": "EMV inherent by strategic objective ($M)", "ctype": "bar", "cats": [x[:28] for x in sos], "series": [{"name": "EMV-i", "values": [round(sum(r["emv_i"] for r in a if r["so"] == x) / 1e6, 2) for x in sos], "color": "1F4E9E"}], "fmt": "0.0"}], "bullets": ["%d strategic objectives, %d risks." % (len(sos), len(a))], "tiles": []})
    dom = {d: [sum(x["domains"][d]["n"] for x in rows), None] for d in DOMAINS}
    for d in DOMAINS:
        k = sum(x["domains"][d]["n"] for x in rows if x["domains"][d]["ice"] is not None); s_ = sum(x["domains"][d]["ice"] * x["domains"][d]["n"] for x in rows if x["domains"][d]["ice"] is not None)
        dom[d][1] = (1 - s_ / k) if k else None
    cols = ["2F6FD6", "3BA55C", "E9C440", "E0474C", "F0A04B"]
    sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "CONTROL COUNT AND CONTROL EFFECTIVENESS BY P2ST2 CATEGORY", "source": "EcoCash Sentinel", "per_slide": 4,
               "charts": [{"title": "Control count", "ctype": "doughnut", "cats": DOMAINS, "series": [{"name": "Controls", "values": [dom[d][0] for d in DOMAINS], "point_colors": cols, "fmt": "#,##0", "hole": 55}], "labels": True}, {"title": "Control effectiveness", "ctype": "doughnut", "cats": DOMAINS, "series": [{"name": "Effectiveness", "values": [round((dom[d][1] or 0) * 100, 1) for d in DOMAINS], "point_colors": cols, "fmt": "0\"%\"", "hole": 55}], "labels": True}],
               "bullets": ["%s controls linked to risks across the five P2ST2 categories." % "{:,}".format(len(ctl))], "tiles": [{"word": "%.0f%%" % ((dom[d][1] or 0) * 100), "caption": d} for d in DOMAINS[:4]]})
    rd = depts.ref_departments([(x["owner"], x["ref"]) for x in ctl]); owner_of = {r["id"]: r["owner"] for r in rows}; dd = {}
    for x in ctl:
        d_, _ = depts.dept_for_control(x["owner"], x["ref"], rd, owner_of.get(x["risk_id"])); e = dd.setdefault(d_, [0, 0.0, 0]); e[0] += 1
        if x["ice"] is not None: e[1] += x["ice"]; e[2] += 1
    ds = sorted(dd, key=lambda k: -dd[k][0])
    if ds:
        sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "CONTROL UNIVERSE BY DEPARTMENT (ERCO FUNCTIONS)", "source": "EcoCash Sentinel", "per_slide": 4,
                   "charts": [{"title": "Controls by department", "ctype": "bar", "cats": [x[:26] for x in ds], "series": [{"name": "Controls", "values": [dd[k][0] for k in ds], "color": "1F4E9E"}], "fmt": "#,##0"}, {"title": "Average control effectiveness by department (%)", "ctype": "bar", "cats": [x[:26] for x in ds], "series": [{"name": "Effectiveness", "values": [round((1 - dd[k][1] / dd[k][2]) * 100, 1) if dd[k][2] else None for k in ds], "color": "00B050"}], "fmt": "0"}],
                   "bullets": ["A control with no owner takes its department from the same control elsewhere, or from the owner of the risk it protects."], "tiles": []})
    if cat["loaded"] and cat["p2st2"]:
        sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "P2ST2 CONTROL TAXONOMY", "source": "EcoCash Control Taxonomy workbook", "per_slide": 4,
                   "charts": [{"title": "Controls in the taxonomy", "ctype": "column", "cats": DOMAINS, "series": [{"name": "Controls", "values": [cat["p2st2"].get(d, {"n": 0})["n"] for d in DOMAINS], "color": "0070C0"}], "fmt": "#,##0"}, {"title": "Taxonomy control effectiveness (%)", "ctype": "column", "cats": DOMAINS, "series": [{"name": "Effectiveness", "values": [eff(cat["p2st2"].get(d, {"ice": None})["ice"]) for d in DOMAINS], "color": "00B050"}], "fmt": "0"}],
                   "bullets": ["%s controls in the taxonomy; %s risk-specific controls used by risks are listed separately." % ("{:,}".format(sum(v["n"] for v in cat["p2st2"].values())), "{:,}".format(sum(cat["extra"].values())))], "tiles": []})
    if cat["loaded"] and cat["annex"]:
        th = [t for t in ("Organizational", "People", "Physical", "Technological") if t in cat["annex"]]
        sl.append({"title": "RISK PERFORMANCE ANALYTICS", "subtitle": "ISO/IEC 27001 ANNEX A CONTROLS BY THEME", "source": "EcoCash Control Taxonomy workbook", "per_slide": 4,
                   "charts": [{"title": "Annex A controls by theme", "ctype": "column", "cats": th, "series": [{"name": "Controls", "values": [cat["annex"][t]["n"] for t in th], "color": "0070C0"}], "fmt": "0"}, {"title": "Effectiveness by theme (%)", "ctype": "column", "cats": th, "series": [{"name": "Effectiveness", "values": [eff(cat["annex"][t]["ice"]) for t in th], "color": "00B050"}], "fmt": "0"}],
                   "bullets": ["%d Annex A controls in %d themes." % (sum(v["n"] for v in cat["annex"].values()), len(th))], "tiles": []})
    return sl


@router.route("GET", "/api/analytics/export.pptx")
def analytics_pptx(req):
    c = need(req, "performance_analytics", "export")
    import datetime
    from . import pptxgen
    from .web import Response
    slides = deck_slides(req.db, c)
    if not slides:
        raise HTTPError(409, "no_data", "There is nothing to put in a presentation yet. Import the risk assessment workbook first.")
    for sl_ in slides:
        for ch in sl_["charts"]:
            ch.setdefault("unit", None); ch.setdefault("labels", True)
    data = pptxgen.build({"as_of": str(datetime.date.today()), "cover_title": "RISK ANALYTICS REPORT", "slides": slides})
    audit(req.db, "export.analytics_pptx", c.user, "performance_analytics", "Performance Analytics downloaded as PowerPoint (%d slides)" % (len(slides) + 2), req.ip)
    return Response(data, 200, "application/vnd.openxmlformats-officedocument.presentationml.presentation", [("Content-Disposition", 'attachment; filename="Sentinel_Performance_Analytics.pptx"')])
