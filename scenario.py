"""Scenario Lab (BRD 9.9, GRC Policy 3.7): tests shocks and treatments before they happen.
Model, the same for every scenario so it can be checked:
    inherent  = volume x loss per case x (1 + time growth x hours to contain)
    after controls = inherent x (1 - detection)          (the effect of the controls)
    residual  = after controls x (1 - recovery)           (what is recovered)
    treated   = residual x (1 - treatment)                (the planned treatment)
Each parameter has a low, a most likely and a high value. A Monte Carlo run (triangular distributions, fixed seed so the same inputs give the same answer) gives the
median and 90th percentile of the residual loss and the chance of exceeding appetite; a tornado shows which parameter moves the answer most. Every save is a new
version with the assumptions in words. The start values in the library are ILLUSTRATIVE: replace them with EcoCash's own loss data (the screen suggests ranges from the
incident history when there is one)."""
import ast
import hashlib
import json
import operator
import random

import re

from . import xlsxbook
from .api import router, need, need_str
from .core import audit, now
from .p2 import xlsx_response
from .web import HTTPError

KEYS = ["volume", "loss_per_case", "detection", "recovery", "containment_hours", "treatment"]
FRACTIONS = ("detection", "recovery", "treatment")


def P(label, unit, lo, base, hi, step=None):
    return {"label": label, "unit": unit, "min": lo, "base": base, "max": hi, "step": step or (0.01 if hi <= 1 else max(hi / 100.0, 0.1))}


TEMPLATES = {
    "sim_swap": {"name": "SIM-swap fraud wave", "risk_type": "Fraud", "growth": 0.02, "appetite": 100000, "category": "Fraud", "text": "a wave of SIM-swap account takeovers",
                 "params": {"volume": P("SIM-swap attempts per month", "attempts", 200, 600, 1500), "loss_per_case": P("Average loss per successful case", "US$", 50, 150, 400), "detection": P("Attempts detected and blocked", "share", 0.5, 0.8, 0.95), "recovery": P("Losses recovered", "share", 0.0, 0.15, 0.5), "containment_hours": P("Hours to contain", "hours", 2, 12, 48), "treatment": P("Reduction from planned treatment (for example a cooling-off period)", "share", 0.0, 0.3, 0.7)}},
    "platform_outage": {"name": "Payments platform outage", "risk_type": "Technology", "growth": 0.10, "appetite": 250000, "category": "Technology", "text": "a customer-impacting platform outage",
                        "params": {"volume": P("Outage events per year", "events", 1, 3, 6), "loss_per_case": P("Loss per event (fees, compensation, penalties)", "US$", 50000, 150000, 400000), "detection": P("Events failed over before customers notice", "share", 0.2, 0.5, 0.8), "recovery": P("Loss recovered (service credits, insurance)", "share", 0.0, 0.1, 0.4), "containment_hours": P("Hours to restore", "hours", 1, 4, 24), "treatment": P("Reduction from planned treatment (tested failover)", "share", 0.0, 0.4, 0.8)}},
    "agent_float": {"name": "Agent float shortage", "risk_type": "Financial", "growth": 0.03, "appetite": 60000, "category": "Financial", "text": "agent float shortages",
                    "params": {"volume": P("Shortage days per year", "days", 10, 40, 120), "loss_per_case": P("Lost fees and goodwill per shortage day", "US$", 500, 2000, 6000), "detection": P("Shortages caught early by monitoring", "share", 0.3, 0.6, 0.9), "recovery": P("Loss recovered", "share", 0.0, 0.1, 0.3), "containment_hours": P("Hours to rebalance", "hours", 2, 8, 36), "treatment": P("Reduction from planned treatment (automatic rebalancing)", "share", 0.0, 0.35, 0.7)}},
    "data_breach": {"name": "Customer data breach", "risk_type": "Cyber", "growth": 0.01, "appetite": 400000, "category": "Cyber", "text": "a breach of customer data",
                    "params": {"volume": P("Breach events per year", "events", 0.05, 0.25, 1), "loss_per_case": P("Loss per breach (investigation, notification, penalties, churn)", "US$", 200000, 900000, 3000000), "detection": P("Attacks stopped before data leaves", "share", 0.5, 0.75, 0.95), "recovery": P("Loss recovered (insurance)", "share", 0.0, 0.2, 0.6), "containment_hours": P("Hours to contain", "hours", 6, 48, 240), "treatment": P("Reduction from planned treatment (encryption, access reviews)", "share", 0.0, 0.3, 0.7)}},
    "regulatory_fine": {"name": "Regulatory finding and penalty", "risk_type": "Regulatory", "growth": 0.0, "appetite": 150000, "category": "Regulatory", "text": "a regulatory finding that leads to a penalty",
                        "params": {"volume": P("Findings per year", "findings", 0.5, 2, 6), "loss_per_case": P("Fine and remediation per finding", "US$", 20000, 120000, 500000), "detection": P("Gaps found internally before the regulator", "share", 0.3, 0.65, 0.9), "recovery": P("Loss recovered", "share", 0.0, 0.0, 0.1), "containment_hours": P("Hours to remediate (counted in days x 24)", "hours", 24, 240, 1200), "treatment": P("Reduction from planned treatment (obligations register)", "share", 0.0, 0.3, 0.7)}},
    "fx_shock": {"name": "Foreign-exchange shock", "risk_type": "Financial", "growth": 0.0, "appetite": 300000, "category": "Financial", "text": "an adverse foreign-exchange movement",
                 "params": {"volume": P("Foreign-currency payables exposed", "US$", 1000000, 4000000, 10000000), "loss_per_case": P("Adverse movement", "share", 0.05, 0.15, 0.4), "detection": P("Share hedged or matched in the same currency", "share", 0.1, 0.4, 0.8), "recovery": P("Loss recovered through pricing", "share", 0.0, 0.1, 0.4), "containment_hours": P("Days to reprice (x 24 hours)", "hours", 0, 0, 0), "treatment": P("Reduction from planned treatment (hedging policy)", "share", 0.0, 0.3, 0.7)}},
    "supplier_failure": {"name": "Critical supplier failure", "risk_type": "Third party", "growth": 0.04, "appetite": 120000, "category": "Third party", "text": "the failure of a critical supplier",
                         "params": {"volume": P("Critical supplier failures per year", "failures", 0.2, 1, 3), "loss_per_case": P("Loss per failure (disruption, switching, penalties)", "US$", 30000, 140000, 600000), "detection": P("Failures covered by a tested alternative", "share", 0.1, 0.4, 0.8), "recovery": P("Loss recovered (contract credits)", "share", 0.0, 0.15, 0.4), "containment_hours": P("Hours to switch", "hours", 8, 72, 336), "treatment": P("Reduction from planned treatment (second supplier)", "share", 0.0, 0.4, 0.8)}},
}


def default_params(tid):
    return {k: {"min": v["min"], "base": v["base"], "max": v["max"]} for k, v in TEMPLATES[tid]["params"].items()}


def validate_params(tid, params):
    out = {}
    for k in KEYS:
        v = (params or {}).get(k)
        if not isinstance(v, dict):
            raise HTTPError(400, "validation", "Parameter '%s' is missing." % k)
        try:
            lo, base, hi = float(v["min"]), float(v["base"]), float(v["max"])
        except (KeyError, TypeError, ValueError):
            raise HTTPError(400, "validation", "Parameter '%s' needs a low, a most likely and a high value." % TEMPLATES[tid]["params"][k]["label"])
        if not (lo <= base <= hi):
            raise HTTPError(400, "validation", "'%s': the values must run low, most likely, high." % TEMPLATES[tid]["params"][k]["label"])
        if lo < 0 or (k in FRACTIONS and hi > 1):
            raise HTTPError(400, "validation", "'%s' is out of range%s." % (TEMPLATES[tid]["params"][k]["label"], " (a share between 0 and 1)" if k in FRACTIONS else ""))
        out[k] = {"min": lo, "base": base, "max": hi}
    return out


def point(tid, v):
    """The model at one set of values {key: number}. Returns the four exposures."""
    g = TEMPLATES[tid]["growth"]; inh = v["volume"] * v["loss_per_case"] * (1 + g * v["containment_hours"]); ac = inh * (1 - v["detection"]); res = ac * (1 - v["recovery"]); tr = res * (1 - v["treatment"])
    return {"inherent": inh, "after_controls": ac, "residual": res, "treated": tr}


def _tri(rng, lo, base, hi):
    return lo if hi <= lo else rng.triangular(lo, hi, base)


def run(tid, params, appetite, runs=4000):
    base = {k: v["base"] for k, v in params.items()}; b = point(tid, base)
    seed = int(hashlib.sha256((tid + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:12], 16); rng = random.Random(seed); res, tr = [], []
    for _ in range(runs):
        pt = point(tid, {k: _tri(rng, v["min"], v["base"], v["max"]) for k, v in params.items()}); res.append(pt["residual"]); tr.append(pt["treated"])
    res.sort(); tr.sort(); q = lambda a, p: a[min(len(a) - 1, int(p * len(a)))]
    torn = []
    for k, v in params.items():
        lo = point(tid, dict(base, **{k: v["min"]}))["residual"]; hi = point(tid, dict(base, **{k: v["max"]}))["residual"]
        torn.append({"key": k, "label": TEMPLATES[tid]["params"][k]["label"], "low": lo, "high": hi, "swing": abs(hi - lo)})
    torn.sort(key=lambda z: -z["swing"])
    p90 = q(res, 0.90); status = "Above appetite" if appetite and p90 > appetite else "Within appetite"
    return {"point": b, "bridge": [{"label": "Inherent exposure", "value": b["inherent"], "kind": "total"}, {"label": "Control effect", "value": -(b["inherent"] - b["after_controls"]), "kind": "down"}, {"label": "Recoveries", "value": -(b["after_controls"] - b["residual"]), "kind": "down"}, {"label": "Residual exposure", "value": b["residual"], "kind": "total"},
                                                              {"label": "Treatment effect", "value": -(b["residual"] - b["treated"]), "kind": "down"}, {"label": "Treated exposure", "value": b["treated"], "kind": "total"}],
            "mc": {"runs": runs, "p50": q(res, 0.5), "p90": p90, "mean": sum(res) / runs, "p_above": (sum(1 for x in res if x > appetite) / runs) if appetite else None, "treated_p50": q(tr, 0.5), "treated_p90": q(tr, 0.9), "seed": seed},
            "tornado": torn, "appetite": appetite, "diff_p90": p90 - appetite if appetite else None, "treated_diff_p90": q(tr, 0.9) - appetite if appetite else None, "status": status, "treated_status": "Above appetite" if appetite and q(tr, 0.9) > appetite else "Within appetite"}


def narrative(tid, name, params, r, assumptions=""):
    t = TEMPLATES[tid]; b = {k: v["base"] for k, v in params.items()}; mc = r["mc"]; top = r["tornado"][0]
    money = lambda v: "$%s" % format(int(round(v)), ",")
    s = ("Scenario: %s. This tests %s. On the most likely values (%s %s, loss per case %s, %d%% detected, %d%% recovered, %d hours to contain) the inherent exposure is %s, the residual exposure after controls and recoveries is %s and, with the planned treatment, %s. "
         "Across the ranges the residual loss is %s at the median and %s at the 90th percentile, %s the appetite of %s%s. The parameter that moves the result most is \u201C%s\u201D. The planned treatment %s the 90th-percentile loss to %s (%s)."
         % (name, t["text"], "{:g}".format(b["volume"]), t["params"]["volume"]["unit"], money(b["loss_per_case"]) if b["loss_per_case"] > 1 else "%d%%" % round(b["loss_per_case"] * 100), round(b["detection"] * 100), round(b["recovery"] * 100), round(b["containment_hours"]), money(r["point"]["inherent"]), money(r["point"]["residual"]), money(r["point"]["treated"]),
            money(mc["p50"]), money(mc["p90"]), "above" if r["status"] == "Above appetite" else "within", money(r["appetite"]) if r["appetite"] else "no stated amount", (" (the chance of exceeding it is %d%%)" % round(mc["p_above"] * 100)) if mc["p_above"] is not None else "", top["label"], "reduces" if mc["treated_p90"] < mc["p90"] else "does not change", money(mc["treated_p90"]), r["treated_status"].lower()))
    return s + (" Assumptions: " + assumptions.strip() if assumptions.strip() else "") + " (Drafted by Sentinel from the numbers; the owner writes the final narrative.)"


def history_ranges(db, tid):
    """Suggested ranges from the loss history: what incidents in this category cost. Only when there is a history; the owner decides."""
    cat = TEMPLATES[tid]["category"]; rows = [r["gross_loss"] for r in db.execute("SELECT gross_loss FROM incidents WHERE deleted_at IS NULL AND gross_loss > 0 AND lower(COALESCE(category,''))=lower(?)", (cat,))]
    if len(rows) < 3:
        return None
    rows.sort(); q = lambda p: rows[min(len(rows) - 1, int(p * len(rows)))]
    return {"n": len(rows), "loss_per_case": {"min": q(0.1), "base": q(0.5), "max": q(0.9)}, "note": "From %d recorded %s incident losses (10th, 50th, 90th percentile). Peers' data is not available to Sentinel." % (len(rows), cat.lower())}


def row(db, s):
    last = db.execute("SELECT * FROM scenario_versions WHERE scenario_id=? ORDER BY version DESC LIMIT 1", (s["id"],)).fetchone(); n = db.execute("SELECT COUNT(*) n FROM scenario_versions WHERE scenario_id=?", (s["id"],)).fetchone()["n"]
    res = json.loads(last["results"]) if last else None; sc = db.execute("SELECT AVG(score) a, COUNT(*) n FROM scenario_scores WHERE scenario_id=?", (s["id"],)).fetchone()
    risk = db.execute("SELECT ref, source_ref, title FROM risks WHERE id=?", (s["risk_id"],)).fetchone() if s["risk_id"] else None
    return {"id": s["id"], "name": s["name"], "template": s["template"], "template_name": TEMPLATES[s["template"]]["name"], "risk_type": TEMPLATES[s["template"]]["risk_type"], "risk_id": s["risk_id"], "risk": ((risk["source_ref"] or risk["ref"]) + " " + risk["title"][:60]) if risk else None, "appetite_usd": s["appetite_usd"], "narrative": s["narrative"], "status": s["status"],
            "version": last["version"] if last else 0, "versions": n, "p90": res["mc"]["p90"] if res else None, "status_vs_appetite": res["status"] if res else None, "treated_p90": res["mc"]["treated_p90"] if res else None, "created_by": s["created_by"], "updated_at": s["updated_at"] or s["created_at"], "avg_score": round(sc["a"], 2) if sc["a"] else None, "scorers": sc["n"]}


def _save_version(db, s, params, assumptions, user, narr=None):
    r = run(s["template"], params, s["appetite_usd"]); v = db.execute("SELECT COALESCE(MAX(version),0)+1 v FROM scenario_versions WHERE scenario_id=?", (s["id"],)).fetchone()["v"]
    db.execute("INSERT INTO scenario_versions(scenario_id,version,params,assumptions,results,created_by,created_at) VALUES(?,?,?,?,?,?,?)", (s["id"], v, json.dumps(params), assumptions, json.dumps(r), user, now()))
    db.execute("UPDATE scenarios SET narrative=?, updated_at=? WHERE id=?", (narr if narr is not None else narrative(s["template"], s["name"], params, r, assumptions), now(), s["id"]))
    return v, r


def get_or_404(db, sid):
    s = db.execute("SELECT * FROM scenarios WHERE id=? AND deleted_at IS NULL", (sid,)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Scenario not found.")
    return s


@router.route("GET", "/api/scenarios/templates")
def templates(req):
    need(req, "scenario_lab", "view")
    return {"templates": [{"id": k, "name": t["name"], "risk_type": t["risk_type"], "appetite": t["appetite"], "params": t["params"], "history": history_ranges(req.db, k)} for k, t in TEMPLATES.items()], "note": "The start values are illustrative. Replace them with EcoCash's own loss data before relying on a result."}


@router.route("GET", "/api/scenarios")
def scenarios_list(req):
    c = need(req, "scenario_lab", "view")
    return {"scenarios": [row(req.db, s) for s in req.db.execute("SELECT * FROM scenarios WHERE deleted_at IS NULL ORDER BY COALESCE(updated_at, created_at) DESC")], "can": {k: k in c.perms.get("scenario_lab", set()) for k in ("create", "edit", "delete", "export")}}


@router.route("POST", "/api/scenarios/preview")
def preview(req):
    need(req, "scenario_lab", "view"); b = req.json(); tid = b.get("template")
    if tid not in TEMPLATES:
        raise HTTPError(400, "validation", "Choose a scenario from the library.")
    params = validate_params(tid, b.get("params")); app = max(0.0, float(b.get("appetite_usd") or 0))
    return run(tid, params, app, 2000)


@router.route("POST", "/api/scenarios")
def scenario_create(req):
    c = need(req, "scenario_lab", "create"); b = req.json(); tid = b.get("template")
    if tid not in TEMPLATES:
        raise HTTPError(400, "validation", "Choose a scenario from the library.")
    name = need_str(b, "name", "Name", 140); app = float(b.get("appetite_usd") if b.get("appetite_usd") not in (None, "") else TEMPLATES[tid]["appetite"])
    if app < 0:
        raise HTTPError(400, "validation", "Appetite cannot be negative.")
    rid = int(b["risk_id"]) if b.get("risk_id") else None
    if rid and not req.db.execute("SELECT 1 FROM risks WHERE id=? AND deleted_at IS NULL", (rid,)).fetchone():
        raise HTTPError(400, "validation", "That risk does not exist.")
    params = validate_params(tid, b["params"]) if b.get("params") else default_params(tid)
    sid = req.db.execute("INSERT INTO scenarios(name,template,risk_id,appetite_usd,created_by,created_at) VALUES(?,?,?,?,?,?)", (name, tid, rid, app, c.user["username"], now())).lastrowid
    s = req.db.execute("SELECT * FROM scenarios WHERE id=?", (sid,)).fetchone(); assumptions = str(b.get("assumptions") or "Start values from the library: illustrative, to be replaced with EcoCash data.").strip()[:1500]
    _save_version(req.db, s, params, assumptions, c.user["username"]); audit(req.db, "scenario.create", c.user, "scenario_lab", "Scenario '%s' created from %s" % (name, TEMPLATES[tid]["name"]), req.ip)
    return {"id": sid}


@router.route("GET", "/api/scenarios/sequence")
def sequence(req):
    """GRC Policy 3.7.4: scenarios are sequenced by the average of the probability scores given to them; the highest average is expected to play out first."""
    need(req, "scenario_lab", "view")
    rows = [row(req.db, s) for s in req.db.execute("SELECT * FROM scenarios WHERE deleted_at IS NULL")]
    scored = sorted([r for r in rows if r["avg_score"]], key=lambda r: (-r["avg_score"], -(r["p90"] or 0)))
    return {"sequence": [{"order": i + 1, "id": r["id"], "name": r["name"], "avg_score": r["avg_score"], "scorers": r["scorers"], "p90": r["p90"], "status": r["status_vs_appetite"]} for i, r in enumerate(scored)], "unscored": [{"id": r["id"], "name": r["name"]} for r in rows if not r["avg_score"]]}


@router.route("GET", "/api/scenarios/<int:sid>")
def scenario_get(req):
    sid = int(req.params["sid"])
    c = need(req, "scenario_lab", "view"); s = get_or_404(req.db, sid)
    vs = [{"version": v["version"], "params": json.loads(v["params"]), "assumptions": v["assumptions"], "results": json.loads(v["results"]), "created_by": v["created_by"], "created_at": v["created_at"]} for v in req.db.execute("SELECT * FROM scenario_versions WHERE scenario_id=? ORDER BY version DESC", (sid,))]
    mine = req.db.execute("SELECT score FROM scenario_scores WHERE scenario_id=? AND username=?", (sid, c.user["username"])).fetchone(); risk = None
    if s["risk_id"]:
        r = req.db.execute("SELECT emv_r, emv_i FROM risks WHERE id=?", (s["risk_id"],)).fetchone(); risk = {"emv_r": r["emv_r"], "emv_i": r["emv_i"]} if r else None
    return dict(row(req.db, s), template_def=TEMPLATES[s["template"]], versions_detail=vs, my_score=mine["score"] if mine else None, risk_exposure=risk)


@router.route("POST", "/api/scenarios/<int:sid>/versions")
def scenario_version(req):
    sid = int(req.params["sid"])
    c = need(req, "scenario_lab", "edit"); s = get_or_404(req.db, sid); b = req.json(); params = validate_params(s["template"], b.get("params")); assumptions = need_str(b, "assumptions", "Assumptions", 1500)
    if len(assumptions) < 10:
        raise HTTPError(400, "validation", "Write the assumptions behind these values (at least a sentence): they are recorded with the version.")
    if "appetite_usd" in b and b["appetite_usd"] not in (None, ""):
        app = float(b["appetite_usd"])
        if app < 0:
            raise HTTPError(400, "validation", "Appetite cannot be negative.")
        req.db.execute("UPDATE scenarios SET appetite_usd=? WHERE id=?", (app, sid)); s = get_or_404(req.db, sid)
    v, r = _save_version(req.db, s, params, assumptions, c.user["username"], str(b["narrative"]).strip()[:3000] if b.get("narrative") else None)
    audit(req.db, "scenario.version", c.user, "scenario_lab", "Scenario '%s' version %d saved: P90 residual $%s, %s" % (s["name"], v, format(int(r["mc"]["p90"]), ","), r["status"]), req.ip)
    return {"version": v, "results": r}


@router.route("POST", "/api/scenarios/<int:sid>/score")
def scenario_score(req):
    sid = int(req.params["sid"])
    c = need(req, "scenario_lab", "create"); get_or_404(req.db, sid)
    try:
        sc = int(req.json().get("score"))
    except (TypeError, ValueError):
        sc = 0
    if not 1 <= sc <= 5:
        raise HTTPError(400, "validation", "The probability score is 1 (remote) to 5 (almost certain).")
    req.db.execute("INSERT INTO scenario_scores(scenario_id,username,score,ts) VALUES(?,?,?,?) ON CONFLICT(scenario_id,username) DO UPDATE SET score=excluded.score, ts=excluded.ts", (sid, c.user["username"], sc, now()))
    return {"ok": True}


@router.route("DELETE", "/api/scenarios/<int:sid>")
def scenario_delete(req):
    sid = int(req.params["sid"])
    c = need(req, "scenario_lab", "delete"); s = get_or_404(req.db, sid)
    req.db.execute("UPDATE scenarios SET deleted_at=? WHERE id=?", (now(), sid)); audit(req.db, "scenario.delete", c.user, "scenario_lab", "Scenario '%s' deleted" % s["name"], req.ip)
    return {"ok": True}


@router.route("GET", "/api/scenarios/<int:sid>/export.xlsx")
def scenario_export(req):
    sid = int(req.params["sid"])
    c = need(req, "scenario_lab", "export"); s = get_or_404(req.db, sid)
    vs = req.db.execute("SELECT * FROM scenario_versions WHERE scenario_id=? ORDER BY version", (sid,)).fetchall(); t = TEMPLATES[s["template"]]
    s1 = [[("Scenario: %s" % s["name"], 3)], [("%s | appetite $%s | start values are illustrative unless replaced" % (t["name"], format(int(s["appetite_usd"]), ",")), 4)], [], [(h, 1) for h in ("Version", "Saved by", "Saved at", "Median residual", "P90 residual", "P90 treated", "Chance above appetite", "Status", "Assumptions")]]
    s2 = [[("Parameters by version", 3)], [], [(h, 1) for h in ("Version", "Parameter", "Low", "Most likely", "High")]]
    for v in vs:
        r = json.loads(v["results"]); s1.append([v["version"], v["created_by"], v["created_at"], round(r["mc"]["p50"]), round(r["mc"]["p90"]), round(r["mc"]["treated_p90"]), None if r["mc"]["p_above"] is None else round(r["mc"]["p_above"], 3), r["status"], v["assumptions"]])
        for k, p in json.loads(v["params"]).items():
            s2.append([v["version"], t["params"][k]["label"], p["min"], p["base"], p["max"]])
    return xlsx_response(xlsxbook.write([("Versions", s1, [9, 16, 22, 16, 16, 16, 14, 16, 70]), ("Parameters", s2, [9, 62, 14, 14, 14])]), "Sentinel_scenario_%d.xlsx" % sid)
