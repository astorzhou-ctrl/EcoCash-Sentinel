"""Quarterly KRIs from the Board of Trustees and Risk Committee reports (Step 22).

Reports are imported (a .pptx deck or an Excel sheet) or typed in; every import is a batch that can be deleted and restored; the dashboard, the interpreted
report and the PowerPoint / Excel (Power BI data pack) downloads are all computed from what is stored, so they change as soon as the data does."""
import datetime
import json
import os
import re

from . import core, kriq_parse as K, xlsxbook
from .api import router, need, audit
from .p2 import xlsx_response
from .web import HTTPError, Response

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kriq_seed.json")
PBI_SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kriq_pbi_seed.json")
INHERENT, APPETITE = 25, 10  # the GRC scale used by the Power BI report: inherent 25 for every risk, appetite 10
START = "FY26Q4"  # the dashboard starts here by default
SRC = {"green": "On target", "amber": "Near target", "red": "Off target", "info": "No target / not comparable"}


# ------------------------------------------------------------------ storage
def _kri_find(db, risk_no, name):
    n = K.kri_norm(name)
    rows = db.execute("SELECT * FROM kriq_kris WHERE risk_no=?", (risk_no,)).fetchall()
    for r in rows:
        if r["key"].split(":", 1)[1] == n:
            return r
    for r in rows:  # a name cut short in one deck ("budget variance" for "Revenue budget variance")
        k = r["key"].split(":", 1)[1]
        if min(len(k), len(n)) >= 8 and (k.endswith(n) or n.endswith(k)):
            return r
    return None


def _same(a, b):
    return K.norm(a) == K.norm(b)


def store(db, ex, source, bid, who, fq_hint=None):
    """ex: {'risks': [...], 'kris': [{risk_no, name, target, values:{fq: raw}}]} (values may be {fq: {'raw','src','prev_raw','prev_src'}}).
    Returns (new, changed, same, undo) and records every replaced value so the batch can be deleted cleanly."""
    new = changed = same = 0; undo = []; now = core.now()
    for r in ex.get("risks", []):
        old = db.execute("SELECT * FROM kriq_risks WHERE no=?", (r["no"],)).fetchone()
        if not old:
            db.execute("INSERT INTO kriq_risks(no,name,category,rating) VALUES(?,?,?,?)", (r["no"], r["name"], r.get("category"), r.get("rating")))
        else:
            db.execute("UPDATE kriq_risks SET category=COALESCE(?,category), rating=COALESCE(?,rating) WHERE no=?", (r.get("category"), r.get("rating"), r["no"]))
        for fq in set(r.get("residual", {})) | set(r.get("notes", {})):
            was = db.execute("SELECT * FROM kriq_risk_q WHERE risk_no=? AND fq=?", (r["no"], fq)).fetchone()
            if was:
                undo.append(["rq", r["no"], fq, was["residual"], was["note"], was["source"], was["import_id"]])
            res = r.get("residual", {}).get(fq, was["residual"] if was else None); note = r.get("notes", {}).get(fq, was["note"] if was else None)
            db.execute("INSERT OR REPLACE INTO kriq_risk_q(risk_no,fq,residual,note,source,import_id) VALUES(?,?,?,?,?,?)", (r["no"], fq, res, note, source, bid))
    for k in ex.get("kris", []):
        rno = k["risk_no"]
        if not db.execute("SELECT 1 FROM kriq_risks WHERE no=?", (rno,)).fetchone():
            nm = next((c[1] for c in K.CANON if c[0] == rno), "Risk %d" % rno)
            db.execute("INSERT INTO kriq_risks(no,name,category) VALUES(?,?,?)", (rno, nm, None))
        row = _kri_find(db, rno, k["name"])
        if not row:
            op, tv, tu = K.parse_target(k.get("target"), k["name"])
            unit = tu or next((K.parse_value(v if not isinstance(v, dict) else v["raw"])[1] for v in k["values"].values() if K.parse_value(v if not isinstance(v, dict) else v["raw"])[1]), None)
            if not unit and re.search(r"\((us|usd)\)", k["name"], re.I) and not re.search(r"customer|subscriber|user", k["name"], re.I): unit = "USD"
            if not unit and re.search(r"\(zwg\)", k["name"], re.I): unit = "ZWG"
            kid = db.execute("INSERT INTO kriq_kris(key,risk_no,name,target_raw,op,target,unit,lower_better,sort) VALUES(?,?,?,?,?,?,?,?,?)",
                             ("%d:%s" % (rno, K.kri_norm(k["name"])), rno, k["name"], k.get("target") or "", op, tv, unit, 1 if K.lower_better(k["name"]) else 0,
                              (db.execute("SELECT COALESCE(MAX(sort),0)+1 FROM kriq_kris").fetchone()[0]))).lastrowid
            row = db.execute("SELECT * FROM kriq_kris WHERE id=?", (kid,)).fetchone()
        elif row["deleted_at"] and k.get("revive", True):
            db.execute("UPDATE kriq_kris SET deleted_at=NULL WHERE id=?", (row["id"],))
        newest = max((K.fq_key(f) for f in k["values"]), default=0)
        if k.get("target") and newest >= K.fq_key(row["last_fq"]):  # the newest report sets the current target
            op, tv, tu = K.parse_target(k["target"], row["name"])
            db.execute("UPDATE kriq_kris SET target_raw=?, op=?, target=?, unit=COALESCE(unit,?) WHERE id=?", (k["target"], op, tv, tu, row["id"]))
        scale = K.target_scale(k.get("target") or row["target_raw"])
        for fq, v in k["values"].items():
            raw = v["raw"] if isinstance(v, dict) else v
            src = (v.get("src") if isinstance(v, dict) else None) or source
            val, _u = K.parse_value(raw, scale)
            vtarget = (v.get("target") if isinstance(v, dict) else None) or k.get("target")
            if isinstance(raw, float):
                val = raw
                if (row["unit"] == "%" or K.unit_of(k.get("target") or row["target_raw"]) == "%") and 0 < abs(raw) <= 1 and (row["target"] or 0) > 1:
                    val = raw * 100  # an Excel cell formatted as a percentage holds 0.33 for 33%
                raw = ("%g" % raw)
            old = db.execute("SELECT * FROM kriq_values WHERE kri_id=? AND fq=?", (row["id"], fq)).fetchone()
            prev_raw = v.get("prev_raw") if isinstance(v, dict) else None; prev_src = v.get("prev_src") if isinstance(v, dict) else None
            if old:
                if old["raw"] == str(raw) and (old["target_raw"] or "") == (vtarget or old["target_raw"] or ""):
                    same += 1; continue
                undo.append(["kv", row["id"], fq, old["raw"], old["value"], old["target_raw"], old["source"], old["prev_raw"], old["prev_source"], old["import_id"], old["entered_by"], old["created_at"]])
                if old["raw"] != str(raw) and not prev_raw:
                    prev_raw, prev_src = old["raw"], old["source"]
                db.execute("DELETE FROM kriq_values WHERE id=?", (old["id"],)); changed += 1
            else:
                new += 1
            db.execute("INSERT INTO kriq_values(kri_id,fq,raw,value,target_raw,source,prev_raw,prev_source,import_id,entered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (row["id"], fq, str(raw), val, vtarget or None, src, prev_raw, prev_src, bid, who, now))
            if K.fq_key(fq) >= K.fq_key(row["last_fq"]):
                db.execute("UPDATE kriq_kris SET last_fq=? WHERE id=?", (fq, row["id"])); row = db.execute("SELECT * FROM kriq_kris WHERE id=?", (row["id"],)).fetchone()
    return new, changed, same, undo


def _batch(db, who, filename, kind="kriq"):
    return db.execute("INSERT INTO kpi_imports(ts,username,kind,filename,rows_new,rows_replaced) VALUES(?,?,?,?,0,0)", (core.now(), who, kind, filename)).lastrowid


def _finish(db, bid, new, changed, undo):
    db.execute("UPDATE kpi_imports SET rows_new=?, rows_replaced=?, undo=? WHERE id=?", (new, changed, json.dumps(undo), bid))


def load_seed(db, who="starter set"):
    """The reports of Q4 FY26 to Q2 FY27 (RISCO and Board of Trustees decks), loaded once as one batch that can be deleted and restored."""
    if not os.path.exists(SEED):
        return None
    sd = json.load(open(SEED, encoding="utf-8"))
    if db.execute("SELECT 1 FROM kpi_imports WHERE filename=? AND kind='kriq'", (sd["name"],)).fetchone():
        return None
    bid = _batch(db, who, sd["name"])
    new, changed, same, undo = store(db, sd, sd["name"], bid, who)
    _finish(db, bid, new, changed, undo)
    return {"new": new, "changed": changed}


def load_pbi(db, who="starter set"):
    """The residual ratings (whole numbers, GRC scale) and the extra KRIs that appear in the Power BI report. One batch, deletable and restorable."""
    if not os.path.exists(PBI_SEED):
        return None
    sd = json.load(open(PBI_SEED, encoding="utf-8"))
    if db.execute("SELECT 1 FROM kpi_imports WHERE filename=? AND kind='kriq'", (sd["name"],)).fetchone():
        return None
    bid = _batch(db, who, sd["name"])
    new, changed, same, undo = store(db, sd, sd["name"], bid, who)
    _finish(db, bid, new, changed, undo)
    # the intercompany creditors line is an amount in ZWG; the 50% limit belongs to its share of all creditors
    db.execute("UPDATE kriq_kris SET unit='ZWG', target_raw='', op=NULL, target=NULL WHERE name LIKE 'Intercompany Creditors%' AND (unit IS NULL OR unit='%')")
    return {"new": new, "changed": changed}


def code(no):
    return ("R%02d" % no) if no < 100 else ("B%02d" % (no - 100))


# ------------------------------------------------------------------ analysis
def build(db, frm=None, to=None):
    """Everything the dashboard, the report and the downloads show, computed from the stored values."""
    frm = frm or START
    allq = sorted({r[0] for r in db.execute("SELECT DISTINCT fq FROM kriq_values")} | {r[0] for r in db.execute("SELECT DISTINCT fq FROM kriq_risk_q")}, key=K.fq_key)
    qs = [q for q in allq if K.fq_key(q) >= K.fq_key(frm) and (not to or K.fq_key(q) <= K.fq_key(to))]
    out = {"quarters": qs, "all_quarters": allq, "from": frm, "to": qs[-1] if qs else None, "risks": [], "tiles": {}, "trend": [], "empty": not allq}
    if not qs:
        return out
    risks = {r["no"]: dict(r) for r in db.execute("SELECT * FROM kriq_risks ORDER BY no")}
    rq = {}
    for r in db.execute("SELECT * FROM kriq_risk_q"):
        rq.setdefault(r["risk_no"], {})[r["fq"]] = {"residual": r["residual"], "note": r["note"]}
    vals = {}
    for v in db.execute("SELECT * FROM kriq_values"):
        vals.setdefault(v["kri_id"], {})[v["fq"]] = v
    by_risk = {}
    for k in db.execute("SELECT * FROM kriq_kris WHERE deleted_at IS NULL ORDER BY risk_no, sort, id"):
        vs = vals.get(k["id"], {})
        if not any(q in vs for q in qs):
            continue
        row = {"id": k["id"], "name": k["name"], "target": k["target_raw"] or "", "unit": k["unit"], "lower_better": bool(k["lower_better"]), "q": {}}
        for q in qs:
            v = vs.get(q)
            if not v:
                continue
            tr = v["target_raw"] or k["target_raw"]
            op, tv, _ = K.parse_target(tr, k["name"])
            if op and k["lower_better"] and not (tr or "").strip()[:1] in "<>≤≥":
                op = "le"
            st = K.status(v["value"], v["raw"], op, tv, tr)
            row["q"][q] = {"raw": v["raw"], "value": v["value"], "text": K.fmt_value(v["value"], k["unit"]) if v["value"] is not None else (v["raw"] or "–"), "status": st, "target": tr, "source": v["source"], "prev": v["prev_raw"], "prev_source": v["prev_source"]}
        have = [(q, row["q"][q]) for q in qs if q in row["q"]]
        row["latest_q"] = have[-1][0] if have else None
        row["latest"] = have[-1][1] if have else None
        row["current"] = row["q"].get(qs[-1])
        nums = [(q, x["value"]) for q, x in have if x["value"] is not None]
        row["delta"] = row["delta_pct"] = row["move"] = None
        kop = K.parse_target(k["target_raw"], k["name"])[0] if k["target_raw"] else None
        if k["lower_better"]: kop = "le"
        if len(nums) >= 2:
            a, b = nums[-2][1], nums[-1][1]
            row["delta"] = b - a; row["delta_pct"] = ((b - a) / abs(a) * 100) if a else None
            if b == a:
                row["move"] = "flat"
            elif kop is None:
                row["move"] = "up" if b > a else "down"  # no target and no known direction: the change is shown but not judged
            else:
                row["move"] = "better" if ((b < a) == (kop == "le")) else "worse"
        streak = 0
        for q, x in reversed(have):
            if x["status"] == "red": streak += 1
            else: break
        row["red_streak"] = streak
        by_risk.setdefault(k["risk_no"], []).append(row)
    for no in sorted(set(by_risk) | {n for n, qd in rq.items() if any(qd.get(q, {}).get("residual") is not None for q in qs) and n in risks}):
        kris = by_risk.get(no, [])
        rk = risks.get(no, {"no": no, "name": "Risk %d" % no})
        cnt = {"green": 0, "amber": 0, "red": 0, "info": 0}
        for r in kris:
            c = r["current"]
            if c: cnt[c["status"]] += 1
        out["risks"].append({"no": no, "code": code(no), "name": rk["name"], "category": rk.get("category"), "rating": rk.get("rating"), "kris": kris, "counts": cnt,
                             "residual": {q: rq.get(no, {}).get(q, {}).get("residual") for q in qs}, "notes": {q: rq.get(no, {}).get(q, {}).get("note") for q in qs}})
    for q in qs:
        c = {"green": 0, "amber": 0, "red": 0, "info": 0, "total": 0}
        for rk in out["risks"]:
            for r in rk["kris"]:
                x = r["q"].get(q)
                if x:
                    c[x["status"]] += 1; c["total"] += 1
        out["trend"].append(dict(c, q=q))
    cur = out["trend"][-1]; prev = out["trend"][-2] if len(out["trend"]) > 1 else None
    kr = [r for rk in out["risks"] for r in rk["kris"]]
    judged = cur["green"] + cur["amber"] + cur["red"]
    out["tiles"] = {"kris": len(kr), "reported": cur["total"], "green": cur["green"], "amber": cur["amber"], "red": cur["red"], "info": cur["info"],
                    "pct_on_target": round(100 * cur["green"] / judged) if judged else None,
                    "prev_pct_on_target": (round(100 * prev["green"] / max(1, prev["green"] + prev["amber"] + prev["red"])) if prev and (prev["green"] + prev["amber"] + prev["red"]) else None),
                    "improving": sum(1 for r in kr if r["move"] == "better"), "worsening": sum(1 for r in kr if r["move"] == "worse"),
                    "missing": sum(1 for r in kr if out["to"] not in r["q"])}
    return out


def narrative(d):
    """The interpreted report: plain-language findings written from the numbers. Rule-based, so every sentence can be traced to a figure."""
    if d["empty"] or not d["quarters"]:
        return {"headline": "No quarterly KRI data is loaded yet.", "points": [], "sections": [], "watch": [], "restated": [], "gaps": []}
    q = d["to"]; t = d["tiles"]; qp = d["quarters"][-2] if len(d["quarters"]) > 1 else None
    kr = [(rk, r) for rk in d["risks"] for r in rk["kris"]]
    judged = t["green"] + t["amber"] + t["red"]
    head = "%s: %d of %d KRIs with a target are on target (%s%%), %d are near target and %d are off target." % (q, t["green"], judged, t["pct_on_target"] if t["pct_on_target"] is not None else "n/a", t["amber"], t["red"])
    if t["prev_pct_on_target"] is not None and t["pct_on_target"] is not None:
        diff = t["pct_on_target"] - t["prev_pct_on_target"]
        head += " That is %s than %s (%s%%)." % ("better" if diff > 0 else "worse" if diff < 0 else "no different", qp, t["prev_pct_on_target"]) if diff else " That is unchanged from %s." % qp
    pts = []
    bad = [(rk, r) for rk, r in kr if r["current"] and r["current"]["status"] == "red"]
    pts.append("%d KRIs are off target in %s%s." % (len(bad), q, ": " + "; ".join("%s (%s, target %s)" % (r["name"], r["current"]["text"], r["current"]["target"] or "n/a") for rk, r in bad[:8]) + ("; and %d more" % (len(bad) - 8) if len(bad) > 8 else "") if bad else ""))
    pers = [(rk, r) for rk, r in kr if r["red_streak"] >= 2 and r["current"] and r["current"]["status"] == "red"]
    watch = ["%s: %s has been off target for %d quarters in a row (now %s against %s). Risk: %s." % (q, r["name"], r["red_streak"], r["current"]["text"], r["current"]["target"] or "no target", rk["name"]) for rk, r in sorted(pers, key=lambda x: -x[1]["red_streak"])]
    worse = [(rk, r) for rk, r in kr if r["move"] == "worse" and r["current"] and r["delta_pct"] is not None and abs(r["delta_pct"]) >= 10]
    better = [(rk, r) for rk, r in kr if r["move"] == "better" and r["current"] and r["delta_pct"] is not None and abs(r["delta_pct"]) >= 10]
    if worse:
        pts.append("Moved the wrong way by 10%% or more since %s: %s." % (qp, "; ".join("%s (%s to %s)" % (r["name"], r["q"][d["quarters"][-2]]["text"] if d["quarters"][-2] in r["q"] else "?", r["current"]["text"]) for rk, r in worse[:8])))
    if better:
        pts.append("Moved the right way by 10%% or more: %s." % "; ".join("%s (%s to %s)" % (r["name"], r["q"][d["quarters"][-2]]["text"] if d["quarters"][-2] in r["q"] else "?", r["current"]["text"]) for rk, r in better[:8]))
    flips = [(rk, r) for rk, r in kr if qp and qp in r["q"] and r["current"] and r["q"][qp]["status"] in ("green", "amber") and r["current"]["status"] == "red"]
    if flips:
        pts.append("Newly off target this quarter: %s." % "; ".join("%s (%s)" % (r["name"], r["current"]["text"]) for rk, r in flips[:8]))
    back = [(rk, r) for rk, r in kr if qp and qp in r["q"] and r["q"][qp]["status"] == "red" and r["current"] and r["current"]["status"] == "green"]
    if back:
        pts.append("Back on target: %s." % "; ".join("%s (%s)" % (r["name"], r["current"]["text"]) for rk, r in back[:8]))
    res = []
    for rk in d["risks"]:
        a, b = (rk["residual"].get(qp) if qp else None), rk["residual"].get(q)
        if a is not None and b is not None and a != b:
            res.append((rk["name"], a, b))
    if res:
        pts.append("Residual risk changed for: %s." % "; ".join("%s %g to %g (%s)" % (n, a, b, "lower" if b < a else "higher") for n, a, b in res))
    secs = []
    for rk in d["risks"]:
        c = rk["counts"]; lines = []
        n = c["green"] + c["amber"] + c["red"]
        lines.append("%d of %d KRIs with a target are on target%s." % (c["green"], n, "" if not c["red"] else "; %d off target" % c["red"]))
        rr = [rk["residual"].get(x) for x in d["quarters"]]
        if any(v is not None for v in rr):
            lines.append("Residual risk by quarter: " + ", ".join("%s %s" % (x, ("%g" % v) if v is not None else "n/a") for x, v in zip(d["quarters"], rr)) + ".")
        for r in rk["kris"]:
            cu = r["current"]
            if cu and cu["status"] == "red":
                lines.append("%s is %s against a target of %s%s." % (r["name"], cu["text"], cu["target"] or "n/a", " (off target for %d quarters)" % r["red_streak"] if r["red_streak"] >= 2 else ""))
        note = rk["notes"].get(q)
        secs.append({"risk": "%s" % rk["name"], "no": rk["no"], "lines": lines, "management": note})
    miss = ["%s (%s) has no %s figure." % (r["name"], rk["name"], q) for rk, r in kr if q not in r["q"]]
    restated = []
    for rk, r in kr:
        for x in d["quarters"]:
            c = r["q"].get(x)
            if c and c["prev"] and not K.norm(c["prev"]) == K.norm(c["raw"]):
                restated.append("%s, %s: %s (%s) replaced %s (%s)." % (r["name"], x, c["raw"], c["source"], c["prev"], c["prev_source"]))
    return {"headline": head, "points": pts, "sections": secs, "watch": watch, "gaps": miss, "restated": restated, "quarter": q, "prepared": "Prepared by Sentinel from the stored KRI figures. Check against the source reports before it is relied on."}


# ------------------------------------------------------------------ API: dashboard and data
def _perm(req, action="view"):
    return need(req, "kri_monitor", action)


@router.route("GET", "/api/kriq/dashboard")
def dashboard(req):
    c = _perm(req)
    d = build(req.db, req.query.get("from") or None, req.query.get("to") or None)
    d["narrative"] = narrative(d)
    loaded = req.db.execute("SELECT 1 FROM kpi_imports WHERE kind='kriq' LIMIT 1").fetchone()
    d["seed_available"] = os.path.exists(SEED) and not loaded
    d["pbi_pending"] = bool(loaded) and os.path.exists(PBI_SEED) and not req.db.execute("SELECT 1 FROM kpi_imports WHERE kind='kriq' AND filename=?", (json.load(open(PBI_SEED, encoding="utf-8"))["name"],)).fetchone()
    d["inherent"], d["appetite"] = INHERENT, APPETITE
    d["can"] = {"edit": "edit" in c.perms.get("kri_monitor", set()), "create": "create" in c.perms.get("kri_monitor", set()), "export": "export" in c.perms.get("kri_monitor", set()) or "view" in c.perms.get("kri_monitor", set())}
    return d


@router.route("GET", "/api/kriq/pages")
def pbi_pages(req):
    """The Power BI-style pages, computed from the stored figures: panels for the risk pages and the period overview for the executive pages."""
    from . import kriq_pages as PG
    c = _perm(req)
    d = build(req.db, req.query.get("from") or None, req.query.get("to") or None)
    if d["empty"]:
        return {"empty": True, "seed_available": os.path.exists(SEED) and not req.db.execute("SELECT 1 FROM kpi_imports WHERE kind='kriq' LIMIT 1").fetchone(), "can": {"edit": "edit" in c.perms.get("kri_monitor", set())}}
    pend = bool(req.db.execute("SELECT 1 FROM kpi_imports WHERE kind='kriq' LIMIT 1").fetchone()) and os.path.exists(PBI_SEED) and not req.db.execute("SELECT 1 FROM kpi_imports WHERE kind='kriq' AND filename=?", (json.load(open(PBI_SEED, encoding="utf-8"))["name"],)).fetchone()
    return {"empty": False, "pbi_pending": pend, "quarters": d["quarters"], "all_quarters": d["all_quarters"], "from": d["from"], "to": d["to"], "pages": PG.pages(d), "summary": PG.summary(d, req.query.get("period") or None),
            "risks": [{"no": r["no"], "code": r["code"], "name": r["name"]} for r in d["risks"]],
            "can": {"edit": "edit" in c.perms.get("kri_monitor", set()), "create": "create" in c.perms.get("kri_monitor", set())}}


@router.route("POST", "/api/kriq/seed")
def seed_route(req):
    c = _perm(req, "edit")
    r = load_seed(req.db, c.user["username"])
    if r:
        audit(req.db, "kriq.seed", c.user, "kri_monitor", "Loaded the quarterly KRIs from the BoT and RISCO reports (%d new values)" % r["new"], req.ip)
    p = load_pbi(req.db, c.user["username"])
    if p:
        audit(req.db, "kriq.seed", c.user, "kri_monitor", "Loaded the Power BI residual ratings and extra KRIs (%d new values, %d changed)" % (p["new"], p["changed"]), req.ip)
    return {"loaded": bool(r or p), **(r or {})}


@router.route("GET", "/api/kriq/entry")
def entry(req):
    """Everything the manual-entry form needs for one quarter: each KRI with its target, last value and the value already entered for the quarter."""
    _perm(req)
    fq = req.query.get("fq") or ""
    if not K.parse_fq(fq):
        t = K.parse_fq(max((r[0] for r in req.db.execute("SELECT DISTINCT fq FROM kriq_values")), key=K.fq_key, default="FY27Q2")); fq = K.fq_str(K.fq_next(t))
    fq = K.fq_str(K.parse_fq(fq))
    risks = {r["no"]: r["name"] for r in req.db.execute("SELECT no,name FROM kriq_risks ORDER BY no")}
    rows = []
    for k in req.db.execute("SELECT * FROM kriq_kris WHERE deleted_at IS NULL ORDER BY risk_no, sort, id"):
        last = req.db.execute("SELECT fq,raw FROM kriq_values WHERE kri_id=? AND fq<>? ORDER BY fq DESC LIMIT 1", (k["id"], fq)).fetchone()
        cur = req.db.execute("SELECT raw FROM kriq_values WHERE kri_id=? AND fq=?", (k["id"], fq)).fetchone()
        rows.append({"id": k["id"], "risk_no": k["risk_no"], "risk": risks.get(k["risk_no"], ""), "name": k["name"], "target": k["target_raw"] or "", "last_fq": last["fq"] if last else None, "last": last["raw"] if last else None, "current": cur["raw"] if cur else ""})
    res = {r["risk_no"]: r["residual"] for r in req.db.execute("SELECT risk_no,residual FROM kriq_risk_q WHERE fq=?", (fq,))}
    return {"fq": fq, "kris": rows, "risks": [{"no": n, "name": nm, "residual": res.get(n)} for n, nm in risks.items()], "quarters": [r[0] for r in req.db.execute("SELECT DISTINCT fq FROM kriq_values")]}


@router.route("POST", "/api/kriq/values")
def save_values(req):
    c = _perm(req, "edit")
    b = json.loads(req.body() or b"{}")
    fq = K.parse_fq(b.get("fq"))
    if not fq:
        raise HTTPError(400, "validation", "Choose the quarter, for example FY27Q3.")
    fqs = K.fq_str(fq); ks, n_skipped = [], 0
    for r in b.get("values") or []:
        raw = str(r.get("raw") if r.get("raw") is not None else "").strip()
        k = req.db.execute("SELECT * FROM kriq_kris WHERE id=?", (int(r.get("kri_id") or 0),)).fetchone()
        if not k or not raw:
            n_skipped += 1; continue
        ks.append({"risk_no": k["risk_no"], "name": k["name"], "target": None, "values": {fqs: raw}})
    rk = []
    for r in b.get("residual") or []:
        try:
            rk.append({"no": int(r["risk_no"]), "name": "", "residual": {fqs: float(r["residual"])}, "notes": ({fqs: str(r.get("note") or "")} if r.get("note") else {})})
        except (TypeError, ValueError, KeyError):
            continue
    if not ks and not rk:
        raise HTTPError(400, "validation", "Enter at least one value.")
    bid = _batch(req.db, c.user["username"], "Manual entry %s" % fqs)
    new, changed, same, undo = store(req.db, {"risks": [x for x in rk if req.db.execute("SELECT 1 FROM kriq_risks WHERE no=?", (x["no"],)).fetchone()], "kris": ks}, "Entered manually", bid, c.user["username"])
    _finish(req.db, bid, new, changed, undo)
    audit(req.db, "kriq.manual", c.user, "kri_monitor", "Entered %s KRI figures: %d new, %d changed" % (fqs, new, changed), req.ip)
    return {"batch": bid, "new": new, "changed": changed, "same": same}


@router.route("POST", "/api/kriq/grid")
def save_grid(req):
    """Edit any figure of any quarter: a value typed over an old one replaces it, an emptied cell removes it, residual likewise. One batch, so it can be deleted and restored."""
    c = _perm(req, "edit")
    b = json.loads(req.body() or b"{}")
    by_kri, clears, n_cleared = {}, [], 0
    for x in b.get("cells") or []:
        fq = K.parse_fq(x.get("fq")); k = req.db.execute("SELECT * FROM kriq_kris WHERE id=?", (int(x.get("kri_id") or 0),)).fetchone()
        if not fq or not k:
            continue
        raw = str(x.get("raw") if x.get("raw") is not None else "").strip()
        if raw:
            by_kri.setdefault(k["id"], {"risk_no": k["risk_no"], "name": k["name"], "target": None, "values": {}})["values"][K.fq_str(fq)] = raw
        else:
            clears.append((k["id"], K.fq_str(fq)))
    rk, rclear = [], []
    for x in b.get("residual") or []:
        fq = K.parse_fq(x.get("fq"))
        if not fq or not req.db.execute("SELECT 1 FROM kriq_risks WHERE no=?", (int(x.get("risk_no") or 0),)).fetchone():
            continue
        if x.get("residual") in (None, ""):
            rclear.append((int(x["risk_no"]), K.fq_str(fq))); continue
        try:
            rk.append({"no": int(x["risk_no"]), "name": "", "residual": {K.fq_str(fq): float(x["residual"])}})
        except (TypeError, ValueError):
            raise HTTPError(400, "validation", "A residual rating must be a number.")
    if not (by_kri or clears or rk or rclear):
        raise HTTPError(400, "validation", "Nothing to save.")
    bid = _batch(req.db, c.user["username"], "Edited in the KRI grid")
    new, changed, same, undo = store(req.db, {"risks": rk, "kris": list(by_kri.values())}, "Edited in Sentinel", bid, c.user["username"])
    for kid, fq in clears:
        was = req.db.execute("SELECT * FROM kriq_values WHERE kri_id=? AND fq=?", (kid, fq)).fetchone()
        if was:
            undo.append(["kv", kid, fq, was["raw"], was["value"], was["target_raw"], was["source"], was["prev_raw"], was["prev_source"], was["import_id"], was["entered_by"], was["created_at"]])
            req.db.execute("DELETE FROM kriq_values WHERE id=?", (was["id"],)); n_cleared += 1
    for rno, fq in rclear:
        was = req.db.execute("SELECT * FROM kriq_risk_q WHERE risk_no=? AND fq=?", (rno, fq)).fetchone()
        if was:
            undo.append(["rq", rno, fq, was["residual"], was["note"], was["source"], was["import_id"]])
            req.db.execute("DELETE FROM kriq_risk_q WHERE risk_no=? AND fq=?", (rno, fq)); n_cleared += 1
    _finish(req.db, bid, new, changed + n_cleared, undo)
    audit(req.db, "kriq.grid", c.user, "kri_monitor", "Edited KRI figures: %d new, %d changed, %d cleared" % (new, changed, n_cleared), req.ip)
    return {"batch": bid, "new": new, "changed": changed, "cleared": n_cleared}


@router.route("GET", "/api/kriq/removed")
def removed_kris(req):
    _perm(req)
    return {"kris": [{"id": k["id"], "name": k["name"], "risk": k["rname"], "target": k["target_raw"] or ""} for k in req.db.execute("SELECT k.*, r.name AS rname FROM kriq_kris k LEFT JOIN kriq_risks r ON r.no=k.risk_no WHERE k.deleted_at IS NOT NULL ORDER BY k.risk_no, k.name")]}


@router.route("POST", "/api/kriq/kris/<int:kid>/restore")
def kri_restore(req):
    c = _perm(req, "edit")
    k = req.db.execute("SELECT * FROM kriq_kris WHERE id=? AND deleted_at IS NOT NULL", (int(req.params["kid"]),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "That KRI is not in the removed list.")
    req.db.execute("UPDATE kriq_kris SET deleted_at=NULL WHERE id=?", (k["id"],))
    audit(req.db, "kriq.kri_restore", c.user, "kri_monitor", "Restored quarterly KRI %s" % k["name"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/kriq/kris")
def kri_create(req):
    c = _perm(req, "create")
    b = json.loads(req.body() or b"{}")
    name = (b.get("name") or "").strip()
    try:
        rno = int(b.get("risk_no"))
    except (TypeError, ValueError):
        raise HTTPError(400, "validation", "Choose the risk this KRI belongs to.")
    if not name:
        raise HTTPError(400, "validation", "Give the KRI a name.")
    if not req.db.execute("SELECT 1 FROM kriq_risks WHERE no=?", (rno,)).fetchone():
        rname = (b.get("risk_name") or "").strip()
        if not rname:
            raise HTTPError(400, "validation", "Name the new risk.")
        req.db.execute("INSERT INTO kriq_risks(no,name) VALUES(?,?)", (rno, rname))
    if _kri_find(req.db, rno, name):
        raise HTTPError(409, "exists", "That KRI already exists under this risk.")
    op, tv, tu = K.parse_target(b.get("target"), name)
    lb = 1 if b.get("lower_better") else 0
    if lb and op == "ge" and not (b.get("target") or "").strip()[:1] in "<>≤≥":
        op = "le"
    kid = req.db.execute("INSERT INTO kriq_kris(key,risk_no,name,target_raw,op,target,unit,lower_better,sort) VALUES(?,?,?,?,?,?,?,?,?)", ("%d:%s" % (rno, K.kri_norm(name)), rno, name, b.get("target") or "", op, tv, tu, lb, 9000)).lastrowid
    audit(req.db, "kriq.kri_add", c.user, "kri_monitor", "Added quarterly KRI: %s" % name, req.ip)
    return {"id": kid}


@router.route("PUT", "/api/kriq/kris/<int:kid>")
def kri_edit(req):
    c = _perm(req, "edit")
    k = req.db.execute("SELECT * FROM kriq_kris WHERE id=?", (int(req.params["kid"]),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "That KRI is not there.")
    b = json.loads(req.body() or b"{}")
    name = (b.get("name") or k["name"]).strip(); tr = b.get("target") if b.get("target") is not None else k["target_raw"]
    lb = 1 if b.get("lower_better") else 0 if "lower_better" in b else k["lower_better"]
    op, tv, tu = K.parse_target(tr, name)
    if lb and op == "ge" and not (tr or "").strip()[:1] in "<>≤≥":
        op = "le"
    req.db.execute("UPDATE kriq_kris SET name=?, target_raw=?, op=?, target=?, unit=COALESCE(?,unit), lower_better=? WHERE id=?", (name, tr, op, tv, tu, lb, k["id"]))
    audit(req.db, "kriq.kri_edit", c.user, "kri_monitor", "Edited quarterly KRI %s (target %s)" % (name, tr), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/kriq/kris/<int:kid>")
def kri_delete(req):
    c = _perm(req, "edit")
    k = req.db.execute("SELECT * FROM kriq_kris WHERE id=? AND deleted_at IS NULL", (int(req.params["kid"]),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "That KRI is not there.")
    req.db.execute("UPDATE kriq_kris SET deleted_at=? WHERE id=?", (core.now(), k["id"]))
    audit(req.db, "kriq.kri_remove", c.user, "kri_monitor", "Removed quarterly KRI %s (its history is kept)" % k["name"], req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ API: import, batches
def _extract_upload(data, quarter, filename):
    if data[:2] != b"PK":
        raise HTTPError(400, "bad_file", "Use a PowerPoint (.pptx) report or an Excel (.xlsx) sheet.")
    import io
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    if "ppt/presentation.xml" in names:
        sl = K.pptx_slides(data)
        dq = K.parse_fq(quarter) or K.deck_quarter(sl)
        if not dq:
            raise HTTPError(400, "quarter", "Sentinel could not tell which quarter this report is for. Choose the quarter and import again.")
        ex = K.extract_deck(sl, dq); ex["deck"] = K.fq_str(dq); ex["kind"] = "deck"
        if not ex["kris"]:
            raise HTTPError(400, "no_kris", "No KRI tables were found. Sentinel reads the 'Detailed Risks' slides (a table headed KRI, Target, then the quarters).")
        return ex
    if "xl/workbook.xml" in names:
        x = K.excel_rows(data)
        if not x["kris"] and not x["residual"]:
            raise HTTPError(400, "no_kris", "No KRI rows were found. Use the Sentinel template: columns Risk No, Risk, KRI, Target and one column per quarter (or Quarter and Value).")
        kris, risks, warn = {}, {}, list(x["warnings"])
        for no, rname, cat, nm, tg, fq, raw in x["kris"]:
            if no is None:
                no, _std = K.canon_risk(rname) if rname else (None, None)
            if no is None:
                warn.append("%s: no risk number or recognisable risk name, skipped" % nm); continue
            e = kris.setdefault((no, K.kri_norm(nm)), {"risk_no": no, "name": nm, "target": tg, "values": {}})
            e["values"][fq] = raw
            if rname and no not in risks:
                risks[no] = {"no": no, "name": rname, "category": cat or None, "residual": {}, "notes": {}}
        for no, fq, rv, note in x["residual"]:
            r = risks.setdefault(no, {"no": no, "name": next((c[1] for c in K.CANON if c[0] == no), "Risk %d" % no), "category": None, "residual": {}, "notes": {}})
            r["residual"][fq] = rv
            if note: r["notes"][fq] = note
        return {"risks": list(risks.values()), "kris": list(kris.values()), "warnings": warn, "deck": None, "kind": "excel"}
    raise HTTPError(400, "bad_file", "This is not a PowerPoint or Excel file.")


@router.route("POST", "/api/kriq/import")
def import_file(req):
    c = _perm(req, "edit")
    data = req.body()
    if not data:
        raise HTTPError(400, "validation", "No file received.")
    fname = __import__("urllib.parse").parse.unquote(req.headers.get("X-Filename") or "")[:120] or "report"
    try:
        ex = _extract_upload(data, req.query.get("quarter"), fname)
    except HTTPError:
        raise
    except Exception:
        raise HTTPError(400, "bad_file", "The file could not be read. Use a PowerPoint (.pptx) or Excel (.xlsx) file.")
    dry = req.query.get("dry") != "0"
    src = (fname.rsplit(".", 1)[0] if fname else "report") + ((" (" + ex["deck"] + ")") if ex.get("deck") else "")
    if dry:
        new = changed = same = 0; newkri = 0; fqs = set(); sample = []
        for k in ex["kris"]:
            row = _kri_find(req.db, k["risk_no"], k["name"])
            if not row: newkri += 1
            for fq, raw in k["values"].items():
                fqs.add(fq); old = req.db.execute("SELECT raw FROM kriq_values WHERE kri_id=? AND fq=?", (row["id"], fq)).fetchone() if row else None
                if not old: new += 1
                elif old["raw"] != str(raw if not isinstance(raw, float) else "%g" % raw): changed += 1; sample.append("%s %s: %s -> %s" % (k["name"], fq, old["raw"], raw))
                else: same += 1
        return {"kind": ex["kind"], "deck": ex.get("deck"), "risks": len(ex["risks"]), "kris": len(ex["kris"]), "new_kris": newkri, "quarters": sorted(fqs, key=K.fq_key), "new": new, "changed": changed, "same": same, "changes": sample[:12], "warnings": ex.get("warnings", [])[:10], "dry": True}
    bid = _batch(req.db, c.user["username"], fname)
    new, changed, same, undo = store(req.db, ex, src, bid, c.user["username"])
    _finish(req.db, bid, new, changed, undo)
    audit(req.db, "kriq.import", c.user, "kri_monitor", "Imported %s: %d new KRI values, %d changed" % (fname, new, changed), req.ip)
    return {"batch": bid, "new": new, "changed": changed, "same": same, "dry": False}


@router.route("GET", "/api/kriq/imports")
def imports(req):
    _perm(req)
    live, gone = [], []
    for r in req.db.execute("SELECT * FROM kpi_imports WHERE kind='kriq' ORDER BY id DESC LIMIT 100"):
        n = req.db.execute("SELECT (SELECT COUNT(*) FROM kriq_values WHERE import_id=?)+(SELECT COUNT(*) FROM kriq_risk_q WHERE import_id=?)", (r["id"], r["id"])).fetchone()[0]
        item = {"id": r["id"], "ts": r["ts"], "by": r["username"], "filename": r["filename"], "new": r["rows_new"], "replaced": r["rows_replaced"], "now": n}
        if r["deleted_at"]:
            if r["snapshot"]: item["deleted_at"] = r["deleted_at"]; gone.append(item)
        else:
            live.append(item)
    return {"imports": live, "deleted": gone}


@router.route("DELETE", "/api/kriq/imports/<int:iid>")
def imports_delete(req):
    c = _perm(req, "edit")
    r = req.db.execute("SELECT * FROM kpi_imports WHERE id=? AND kind='kriq' AND deleted_at IS NULL", (int(req.params["iid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "That import is not there.")
    snap = {"kv": [list(x) for x in req.db.execute("SELECT kri_id,fq,raw,value,target_raw,source,prev_raw,prev_source,entered_by,created_at FROM kriq_values WHERE import_id=?", (r["id"],))],
            "rq": [list(x) for x in req.db.execute("SELECT risk_no,fq,residual,note,source FROM kriq_risk_q WHERE import_id=?", (r["id"],))]}
    req.db.execute("UPDATE kpi_imports SET snapshot=? WHERE id=?", (json.dumps(snap), r["id"]))
    gone = req.db.execute("DELETE FROM kriq_values WHERE import_id=?", (r["id"],)).rowcount + req.db.execute("DELETE FROM kriq_risk_q WHERE import_id=?", (r["id"],)).rowcount
    back = _put_back(req.db, json.loads(r["undo"] or "[]"))
    req.db.execute("UPDATE kpi_imports SET deleted_at=? WHERE id=?", (core.now(), r["id"]))
    audit(req.db, "kriq.import_delete", c.user, "kri_monitor", "Deleted KRI import #%d (%s): %d figures removed, %d earlier values restored" % (r["id"], r["filename"], gone, back), req.ip)
    return {"removed": gone, "restored": back}


def _put_back(db, undo):
    n = 0
    for u in undo:
        if u[0] == "kv":
            _, kid, fq, raw, val, tr, src, praw, psrc, imp, by, created = u
            if not db.execute("SELECT 1 FROM kriq_values WHERE kri_id=? AND fq=?", (kid, fq)).fetchone():
                db.execute("INSERT INTO kriq_values(kri_id,fq,raw,value,target_raw,source,prev_raw,prev_source,import_id,entered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (kid, fq, raw, val, tr, src, praw, psrc, imp, by, created)); n += 1
        elif u[0] == "rq":
            _, rno, fq, res, note, src, imp = u
            if not db.execute("SELECT 1 FROM kriq_risk_q WHERE risk_no=? AND fq=?", (rno, fq)).fetchone():
                db.execute("INSERT INTO kriq_risk_q(risk_no,fq,residual,note,source,import_id) VALUES(?,?,?,?,?,?)", (rno, fq, res, note, src, imp)); n += 1
    return n


@router.route("POST", "/api/kriq/imports/<int:iid>/restore")
def imports_restore(req):
    c = _perm(req, "edit")
    r = req.db.execute("SELECT * FROM kpi_imports WHERE id=? AND kind='kriq' AND deleted_at IS NOT NULL AND snapshot IS NOT NULL", (int(req.params["iid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "There is nothing to restore for that import.")
    sn = json.loads(r["snapshot"]); undo, n = [], 0
    for kid, fq, raw, val, tr, src, praw, psrc, by, created in sn["kv"]:
        was = req.db.execute("SELECT * FROM kriq_values WHERE kri_id=? AND fq=?", (kid, fq)).fetchone()
        if was:
            undo.append(["kv", kid, fq, was["raw"], was["value"], was["target_raw"], was["source"], was["prev_raw"], was["prev_source"], was["import_id"], was["entered_by"], was["created_at"]])
            req.db.execute("DELETE FROM kriq_values WHERE id=?", (was["id"],))
        req.db.execute("INSERT INTO kriq_values(kri_id,fq,raw,value,target_raw,source,prev_raw,prev_source,import_id,entered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (kid, fq, raw, val, tr, src, praw, psrc, r["id"], by, created)); n += 1
    for rno, fq, res, note, src in sn["rq"]:
        was = req.db.execute("SELECT * FROM kriq_risk_q WHERE risk_no=? AND fq=?", (rno, fq)).fetchone()
        if was:
            undo.append(["rq", rno, fq, was["residual"], was["note"], was["source"], was["import_id"]])
        req.db.execute("INSERT OR REPLACE INTO kriq_risk_q(risk_no,fq,residual,note,source,import_id) VALUES(?,?,?,?,?,?)", (rno, fq, res, note, src, r["id"])); n += 1
    req.db.execute("UPDATE kpi_imports SET deleted_at=NULL, snapshot=NULL, undo=? WHERE id=?", (json.dumps(undo), r["id"]))
    audit(req.db, "kriq.import_restore", c.user, "kri_monitor", "Restored KRI import #%d (%s): %d figures put back" % (r["id"], r["filename"], n), req.ip)
    return {"restored": n}


# ------------------------------------------------------------------ API: template and downloads
@router.route("GET", "/api/kriq/template.xlsx")
def template(req):
    _perm(req)
    qs = sorted({r[0] for r in req.db.execute("SELECT DISTINCT fq FROM kriq_values")}, key=K.fq_key)
    nxt = K.fq_str(K.fq_next(K.parse_fq(qs[-1]))) if qs else "FY27Q3"
    last = qs[-2:] if qs else []
    risks = {r["no"]: r["name"] for r in req.db.execute("SELECT no,name FROM kriq_risks ORDER BY no")}
    head = [(h, 1) for h in ["Risk No", "Risk", "KRI", "Target"] + last + [nxt]]
    rows = [[("Quarterly KRI data", 3)], ["One row per KRI. Type the new quarter's value in the last column exactly as you would on the slide (33%, 4.68m, USD193k, 08:46). Add a column headed with another quarter, for example FY27Q1, to load several quarters at once. New KRIs can be added as new rows."], [], head]
    for k in req.db.execute("SELECT * FROM kriq_kris WHERE deleted_at IS NULL ORDER BY risk_no, sort, id"):
        vs = {r["fq"]: r["raw"] for r in req.db.execute("SELECT fq,raw FROM kriq_values WHERE kri_id=?", (k["id"],))}
        rows.append([k["risk_no"], risks.get(k["risk_no"], ""), k["name"], k["target_raw"] or ""] + [vs.get(q, "") for q in last] + [""])
    res = [[(h, 1) for h in ("Risk No", "Risk", "Quarter", "Residual", "Comment")]] + [[n, nm, nxt, None, ""] for n, nm in risks.items()]
    return xlsx_response(xlsxbook.write([("KRI data", rows, [9, 34, 40, 12] + [12] * (len(last) + 1)), ("Residual", res, [9, 40, 10, 10, 60])]), "Sentinel_Quarterly_KRI_template.xlsx")


def _rep(req):
    _perm(req)
    d = build(req.db, req.query.get("from") or None, req.query.get("to") or None)
    return d, narrative(d)


@router.route("GET", "/api/kriq/report")
def report(req):
    d, n = _rep(req)
    return {"narrative": n, "tiles": d["tiles"], "quarters": d["quarters"], "generated": core.now()}


@router.route("GET", "/api/kriq/export.xlsx")
def export_xlsx(req):
    c = _perm(req)
    d, n = _rep(req)
    if d["empty"]:
        raise HTTPError(404, "empty", "There are no quarterly KRI figures to export yet.")
    qs = d["quarters"]; kris, facts, resid = [], [], []
    for rk in d["risks"]:
        for r in rk["kris"]:
            kris.append([r["id"], r["name"], rk["no"], rk["name"], rk["category"] or "", r["target"], r["unit"] or "", "Lower is better" if r["lower_better"] else "Higher is better"])
            for q in qs:
                x = r["q"].get(q)
                if x:
                    facts.append([r["id"], q, ("date", K.fq_dates(q)[1].isoformat()), x["value"], x["raw"], x["target"], SRC[x["status"]], 1 if x["status"] == "green" else 0, 1 if x["status"] == "red" else 0, x["source"] or ""])
        for q in qs:
            if rk["residual"].get(q) is not None:
                resid.append([rk["no"], rk["name"], q, rk["residual"][q], rk["notes"].get(q) or ""])
    readme = [[("EcoCash quarterly KRI data pack", 3)], ["Generated %s by %s. Quarters %s to %s." % (core.now()[:16], c.user["username"], qs[0], qs[-1])], [],
              ["Open Power BI Desktop > Get data > Excel workbook, tick Fact_KRI, Dim_KRI, Dim_Risk, Dim_Quarter and Fact_Residual, then relate Fact_KRI[KRI_ID] to Dim_KRI[KRI_ID], Fact_KRI[Quarter] to Dim_Quarter[Quarter] and Dim_KRI[Risk_No] to Dim_Risk[Risk_No]."],
              ["Value is a number (percent as 33 for 33%, money in dollars, time in seconds); Raw is the text exactly as reported. Status is worked out against the target stated for that quarter."], ["Refresh after each quarter: download this pack again and press Refresh in Power BI."]]
    dim_q = [[q, "FY%d" % K.parse_fq(q)[0], "Q%d" % K.parse_fq(q)[1], ("date", K.fq_dates(q)[0].isoformat()), ("date", K.fq_dates(q)[1].isoformat()), i + 1] for i, q in enumerate(qs)]
    rep = [[("KRI report " + n.get("quarter", ""), 3)], [n["headline"]], [], [("Findings", 4)]] + [[p] for p in n["points"]] + [[], [("Watch list", 4)]] + [[p] for p in n["watch"]] + [[], [("Figures that changed between versions of a report", 4)]] + [[p] for p in n["restated"][:80]] + [[], [("Missing", 4)]] + [[p] for p in n["gaps"][:80]]
    sheets = [("Read me", readme, [120]),
              ("Fact_KRI", [[(h, 1) for h in ("KRI_ID", "Quarter", "Quarter_End", "Value", "Raw", "Target", "Status", "Met", "Breach", "Source")]] + facts, [8, 10, 12, 14, 14, 12, 22, 6, 8, 34]),
              ("Dim_KRI", [[(h, 1) for h in ("KRI_ID", "KRI", "Risk_No", "Risk", "Category", "Target", "Unit", "Direction")]] + kris, [8, 44, 8, 38, 16, 12, 8, 18]),
              ("Dim_Risk", [[(h, 1) for h in ("Risk_No", "Risk", "Category")]] + [[rk["no"], rk["name"], rk["category"] or ""] for rk in d["risks"]], [8, 44, 18]),
              ("Dim_Quarter", [[(h, 1) for h in ("Quarter", "FY", "Q", "Start", "End", "Sort")]] + dim_q, [10, 8, 6, 12, 12, 6]),
              ("Fact_Residual", [[(h, 1) for h in ("Risk_No", "Risk", "Quarter", "Residual", "Comment")]] + resid, [8, 40, 10, 10, 80]),
              ("Report", rep, [150])]
    from . import kriq_pages as PG
    sm = PG.summary(d)
    mv = [[x["code"], x["name"], x["category"], x["register"], x["inherent"]] + [x["residual"].get(q) for q in qs] + [x["change"], x["appetite"] or ""] + [x["att"].get(q) for q in qs] + [x["impact"]] for x in sm["risks"]]
    sheets.insert(-1, ("Risk_Movement", [[(h, 1) for h in ["Code", "Risk", "Category", "Register", "Inherent"] + ["Residual " + q for q in qs] + ["Change", "Appetite"] + ["KRI attainment " + q for q in qs] + ["Why the rating moved"]]] + mv, [7, 40, 22, 18, 9] + [12] * len(qs) + [9, 16] + [14] * len(qs) + [120]))
    sheets.insert(-1, ("Indicator_Universe", [[(h, 1) for h in ("Period", "Code", "Risk", "Category", "Indicator", "Unit", "Better when", "Target", "Value", "Status")]] + [[sm["period"], i["id"], i["risk"], i["category"], i["name"], i["unit"], i["better"], i["target"], i["value"], SRC[i["status"]]] for i in sm["indicators"]], [10, 7, 34, 22, 44, 8, 16, 12, 14, 22]))
    readme.append(["Risk_Movement and Indicator_Universe are the tables behind the Residual Risk Rating Movement and Indicator Universe pages. Attainment = KRIs met plus half of those near target, over KRIs assessed. Inherent is 25 and appetite 10 on the GRC scale."])
    return xlsx_response(xlsxbook.write(sheets), "EcoCash_KRI_PowerBI_data_%s.xlsx" % d["to"])


@router.route("GET", "/api/kriq/export.pptx")
def export_pptx(req):
    from . import pptx_writer as W
    c = _perm(req)
    d, n = _rep(req)
    if d["empty"]:
        raise HTTPError(404, "empty", "There are no quarterly KRI figures to export yet.")
    qs = d["quarters"]; q = d["to"]
    dk = W.Deck(); dk.title_slide("KEY RISK INDICATORS", "Quarterly KRI report: %s to %s" % (qs[0], q))
    G, A, Rr = "1BA94C", "F5A623", "E4202E"
    dk.chart_slide("KRI performance against target by quarter", [{"type": "column", "title": "Number of KRIs by status", "cats": qs, "series": [{"name": "On target", "values": [t["green"] for t in d["trend"]], "color": G}, {"name": "Near target", "values": [t["amber"] for t in d["trend"]], "color": A}, {"name": "Off target", "values": [t["red"] for t in d["trend"]], "color": Rr}]},
                                    {"type": "line", "title": "Share of KRIs on target (%)", "cats": qs, "series": [{"name": "On target %", "values": [round(100 * t["green"] / max(1, t["green"] + t["amber"] + t["red"])) for t in d["trend"]], "color": "1F5FBF"}], "fmt": "0"}],
                   bullets=[n["headline"]] + n["points"][:2], footer="Source: BoT and Risk Committee reports, stored in Sentinel")
    _pbi_slides(dk, d, n)
    rr = [rk for rk in d["risks"] if any(v is not None for v in rk["residual"].values())]
    if rr:
        dk.chart_slide("Residual risk by quarter", [{"type": "column", "title": "Residual risk rating", "cats": [(rk["name"].replace(" Risk", ""))[:26] for rk in rr], "series": [{"name": x, "values": [rk["residual"].get(x) for rk in rr]} for x in qs]}], footer="Residual risk as reported to the committee")
    for rk in d["risks"]:
        nums = [r for r in rk["kris"] if any(x["value"] is not None for x in r["q"].values())]
        for i in range(0, max(1, len(nums)), 4):
            chunk = nums[i:i + 4]
            if not chunk:
                break
            charts = []
            for r in chunk:
                vs = [r["q"][x]["value"] if x in r["q"] else None for x in qs]
                mx = max([abs(v) for v in vs if v is not None] + [0]); div, suf = (1e6, " (millions)") if mx >= 1e6 else (1e3, " (thousands)") if mx >= 1e5 else (1, "")
                if r["unit"] == "mm:ss": div, suf = 60, " (minutes)"
                tv = None
                for x in qs:
                    if x in r["q"] and r["q"][x]["target"]:
                        tv = K.parse_target(r["q"][x]["target"], r["name"])[1]
                ser = [{"name": "Actual", "values": [None if v is None else v / div for v in vs], "color": "1F5FBF"}]
                if tv is not None and K.parse_target(r["target"], r["name"])[1] is not None:
                    ser.append({"name": "Target", "values": [tv / div] * len(qs), "color": Rr, "dashed": True})
                charts.append({"type": "line", "title": (r["name"] + (" [%s]" % r["unit"] if r["unit"] == "%" else "") + suf)[:70], "cats": qs, "series": ser, "fmt": "General"})
            red = [r for r in rk["kris"] if r["current"] and r["current"]["status"] == "red"]
            bl = ["%s: %d of %d KRIs on target in %s%s" % (rk["name"], rk["counts"]["green"], rk["counts"]["green"] + rk["counts"]["amber"] + rk["counts"]["red"], q, ("; off target: " + ", ".join("%s %s" % (r["name"], r["current"]["text"]) for r in red[:3])) if red else "")]
            dk.chart_slide("%s" % rk["name"], charts, bullets=bl, footer="Dashed red line = target. Source: BoT and Risk Committee reports")
    _text_slide(dk, "What the figures tell us: %s" % q, [n["headline"]] + n["points"])
    if n["watch"]:
        _text_slide(dk, "Watch list: persistent breaches", n["watch"][:9])
    if n["restated"]:
        _text_slide(dk, "Figures that differ between versions of a report", n["restated"][:9])
    dk.end_slide()
    return Response(dk.save(), 200, "application/vnd.openxmlformats-officedocument.presentationml.presentation", [("Content-Disposition", 'attachment; filename="EcoCash_KRI_Report_%s.pptx"' % q)])


def _pbi_slides(dk, d, n):
    """The Power BI-style pages as PowerPoint slides: the executive overview, the rating movement, the indicator universe, then one slide of up to six native charts per risk page."""
    from . import kriq_pages as PG
    G, A, Rr = "1BA94C", "F5A623", "E4202E"
    sm = PG.summary(d); t = sm["tiles"]; q = sm["period"]; ql = PG.ql
    rated = sorted([x for x in sm["risks"] if x["current"] is not None], key=lambda x: -x["current"])
    cats = {}
    for x in rated:
        cats.setdefault(x["category"], []).append(x["current"])
    dk.chart_slide("Executive Overview | %s" % ql(q), [
        {"type": "column", "title": "Top 10 risks: residual rating (inherent %d, appetite %d)" % (PG.INH, PG.APP), "cats": [x["code"] + " " + x["name"][:22] for x in rated[:10]], "series": [{"name": "Residual", "values": [x["current"] for x in rated[:10]], "color": "1F5FBF"}], "fmt": "General"},
        {"type": "column", "title": "Average residual vs inherent by risk category", "cats": list(cats), "series": [{"name": "Average residual", "values": [round(sum(v) / len(v), 1) for v in cats.values()], "color": "1F5FBF"}, {"name": "Inherent", "values": [PG.INH] * len(cats), "color": Rr}], "fmt": "General"}],
        bullets=["%d risks rated; average residual %s of %d; %d outside appetite, %d within." % (t["rated"], t["avg_residual"], PG.INH, t["outside"], t["within"]),
                 "Implied control effect %s%%. KRI attainment %s%% (%d assessed: %d met, %d near target, %d breached, %d without a target)." % (t["effect"], t["attainment"], t["assessed"], t["met"], t["near"], t["breached"], t["info"])],
        footer="Attainment = KRIs met plus half of those near target, over KRIs assessed. Source: Sentinel KRI figures", band=True)
    mv = [x for x in sm["risks"] if x["current"] is not None]
    for i in range(0, len(mv), 6):
        _text_slide(dk, "Residual risk rating movement | %s to %s (%d of %d)" % (ql(d["quarters"][0]), ql(q), i // 6 + 1, (len(mv) + 5) // 6),
                    ["%s %s: %s; %s. %s" % (x["code"], x["name"], " > ".join("%g" % x["residual"][y] for y in d["quarters"] if x["residual"].get(y) is not None), x["appetite"].lower(), x["impact"]) for x in mv[i:i + 6]])
    bycat = {}
    for x in sm["indicators"]:
        c = bycat.setdefault(x["category"], {"green": 0, "amber": 0, "red": 0})
        if x["status"] in c: c[x["status"]] += 1
    dk.chart_slide("Indicator Universe | KRIs against target in %s" % ql(q), [{"type": "column", "title": "KRIs by status and risk category", "cats": list(bycat), "series": [{"name": "On target", "values": [v["green"] for v in bycat.values()], "color": G}, {"name": "Near target", "values": [v["amber"] for v in bycat.values()], "color": A}, {"name": "Off target", "values": [v["red"] for v in bycat.values()], "color": Rr}]}],
                   bullets=["%d KRIs assessed: %d met, %d near target, %d breached; %d have no target. Attainment %s%%." % (t["assessed"], t["met"], t["near"], t["breached"], t["info"], t["attainment"])], footer="Green = target met, amber = within 10% of target, red = breached", band=True)
    for pg in PG.pages(d):
        charts = []
        for p in pg["panels"]:
            if p.get("empty") or not p["series"]:
                continue
            kind = p["kind"]
            if kind == "status":
                ser = [{"name": s["name"], "values": s["values"], "color": {"green": G, "amber": A, "red": Rr}[s["key"]]} for s in p["series"]]; typ = "column"
            elif kind in ("line", "lines"):
                ser = [{"name": s["name"], "values": s["values"], "dashed": s.get("dashed"), "color": (Rr if s.get("dashed") else None)} for s in p["series"]]; typ = "line"
            else:
                ser = [{"name": s["name"], "values": s["values"]} for s in p["series"]]; typ = "column"
            charts.append({"type": typ, "title": p["title"][:72], "cats": p["cats"], "series": ser, "fmt": "General"})
        if charts:
            dk.chart_slide(pg["title"][:80], charts[:6], footer=pg["sub"][:160] + " Source: Sentinel KRI figures", band=True)


def _text_slide(dk, title, lines):
    from . import pptx_writer as W
    rels = [W.rel(1, "slideLayout", "../slideLayouts/slideLayout1.xml")]
    sh = [W.box(2, "Accent bar", W.emu(0.3), W.emu(0.3), W.emu(0.09), W.emu(0.5), fill=W.BLUE), W.box(3, "Title", W.emu(0.5), W.emu(0.25), W.emu(10.4), W.emu(0.6), W.para(W.run(title, 2000, True, W.BLUE)), anchor="ctr", inset=0.04)]
    lg = dk._logo(4, rels)
    if lg: sh.append(lg)
    ps = "".join(W.para(W.run(t[:420], 1300, False, "1A1A1A"), bullet=True, space=600) for t in lines)
    sh.append(W.box(5, "Findings", W.emu(0.5), W.emu(1.1), W.emu(12.3), W.emu(5.3), ps, anchor="t", inset=0.1))
    sh.append(W.box(6, "Footer", W.emu(0.3), W.emu(6.62), W.emu(11.2), W.emu(0.26), W.para(W.run("Prepared by Sentinel from the stored KRI figures. Check against the source reports before use.", 700, False, W.GREY)), anchor="ctr", inset=0.02))
    dk.slides.append((W.slide_xml(sh), rels, []))
