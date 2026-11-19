"""Predictive Analytics (BRD 9.20): forecasts KRI breaches and flags anomalies, with days of warning, and keeps a register of the models with their validation.
Method (plain, checkable): Holt's linear trend (double exponential smoothing, alpha 0.5, beta 0.3) on each KRI/KPI's readings; a 90% band from the model's own one-step errors, widening with
the square root of the horizon; the probability of crossing a threshold from the normal approximation. Anomalies: a reading far from the recent median in units of the median absolute
deviation. Validation: walk-forward back-testing (fit on the past, predict the next reading, compare), the lead time given before real breaches, and false alarms. Forecasts are ADVISORY:
a person confirms one before an action is raised."""
import datetime
import math
import statistics

from . import db as dbm, p2
from .api import router, need
from .core import audit, now
from .kit import F, GOOD, WARN, BAD, BLUE, GREY, PURPLE, TEAL, hist, load, make_action, panel, pd, register, seed_item, set_data, tiles
from .web import HTTPError

ALPHA, BETA, H = 0.5, 0.3, 6
NORM = statistics.NormalDist()


def holt(ys):
    """Fit; returns (level, trend, residual standard deviation) or None when there is too little history."""
    if len(ys) < 6:
        return None
    lvl, tr = ys[0], (ys[min(3, len(ys) - 1)] - ys[0]) / max(1, min(3, len(ys) - 1)); errs = []
    for y in ys[1:]:
        pred = lvl + tr; errs.append(y - pred); new = ALPHA * y + (1 - ALPHA) * pred; tr = BETA * (new - lvl) + (1 - BETA) * tr; lvl = new
    sd = statistics.pstdev(errs) if len(errs) > 1 else 0.0
    return lvl, tr, max(sd, 1e-9)


def forecast(ys, h=H):
    m = holt(ys)
    if not m:
        return None
    lvl, tr, sd = m; out = []
    for k in range(1, h + 1):
        f = lvl + k * tr; w = 1.645 * sd * math.sqrt(k); out.append({"k": k, "y": f, "lo": f - w, "hi": f + w, "sd": sd * math.sqrt(k)})
    return out


def step_days(kpi):
    return 30 if (kpi["freq"] or "weekly").startswith("month") else (1 if (kpi["freq"] or "").startswith("day") else 7)


def breach_of(kpi, fc):
    """The first forecast step at which the KRI is expected to cross its amber or red threshold, with the probability. None if it is not expected to."""
    down = kpi["better"] == "down"
    for lvl, thr in (("red", kpi["red"]), ("amber", kpi["amber"])):
        if thr is None:
            continue
        for f in fc:
            p = 1 - NORM.cdf((thr - f["y"]) / f["sd"]) if down else NORM.cdf((thr - f["y"]) / f["sd"])
            if p >= 0.5:
                return {"level": lvl, "threshold": thr, "k": f["k"], "probability": round(p, 2)}
    return None


def crossed(kpi, y):
    th = kpi["amber"] if kpi["amber"] is not None else kpi["red"]
    return th is not None and ((y >= th) if kpi["better"] == "down" else (y <= th))


def anomaly(ys):
    if len(ys) < 8:
        return None
    base = ys[-13:-1]; med = statistics.median(base); mad = statistics.median([abs(x - med) for x in base]) or (statistics.pstdev(base) * 0.6745) or 1e-9; z = 0.6745 * (ys[-1] - med) / mad
    return {"z": round(z, 1), "value": ys[-1], "median": med} if abs(z) >= 3.5 else None


def backtest(ys, kpi):
    """Walk-forward: for the last readings, fit on the past and predict the next. Returns accuracy (1 - symmetric MAPE), early-warning lead and false alarms."""
    n = len(ys)
    if n < 10:
        return None
    errs = []
    for t in range(max(6, n - 8), n):
        fc = forecast(ys[:t], 1)
        if fc:
            a, p = ys[t], fc[0]["y"]; errs.append(abs(a - p) / ((abs(a) + abs(p)) / 2 or 1))
    leads, missed, false_alarm, alarms = [], 0, 0, 0
    for t in range(max(6, n - 14), n - 1):
        fc = forecast(ys[:t], 4); b = breach_of(kpi, fc) if fc else None
        actual_k = next((k for k in range(1, 5) if t + k - 1 < n and crossed(kpi, ys[t + k - 1])), None)
        if b:
            alarms += 1
            if actual_k is None:
                false_alarm += 1
            else:
                leads.append(actual_k)
        elif actual_k is not None and not crossed(kpi, ys[t - 1]):
            missed += 1
    return {"accuracy": round(1 - sum(errs) / len(errs), 3) if errs else None, "lead": round(sum(leads) / len(leads), 1) if leads else None, "alarms": alarms, "false_alarms": false_alarm, "missed": missed, "points": len(errs)}


def series(db, kid):
    rs = db.execute("SELECT period, value FROM kpi_readings WHERE kpi_id=? ORDER BY period", (kid,)).fetchall()
    return [r["period"] for r in rs], [r["value"] for r in rs]


def usable(db):
    out = []
    for k in db.execute("SELECT * FROM kpis WHERE active=1 AND deleted_at IS NULL AND better IN ('up','down')"):
        per, ys = series(db, k["id"])
        if len(ys) >= 6:
            out.append((k, per, ys))
    return out


def predicted(db):
    rows = []
    for k, per, ys in usable(db):
        fc = forecast(ys); b = breach_of(k, fc) if fc else None; an = anomaly(ys)
        if b or an:
            last = pd(per[-1]); rows.append({"kpi_id": k["id"], "code": k["code"], "name": k["name"], "kind": k["kind"], "breach": b, "expected": (last + datetime.timedelta(days=b["k"] * step_days(k))).isoformat() if b and last else None, "anomaly": an, "latest": ys[-1], "status": p2.status_of(k, ys[-1])})
    return sorted(rows, key=lambda r: -((r["breach"] or {}).get("probability") or 0))


@router.route("GET", "/api/predict/forecast/<int:kid>")
def forecast_get(req):
    need(req, "predictive_analytics", "view"); kid = int(req.params["kid"]); k = req.db.execute("SELECT * FROM kpis WHERE id=? AND deleted_at IS NULL", (kid,)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Indicator not found.")
    per, ys = series(req.db, kid); fc = forecast(ys); last = pd(per[-1]) if per else None
    if not fc:
        return {"name": k["name"], "enough": False, "needs": "At least 6 readings are needed to forecast; there are %d." % len(ys)}
    sd = step_days(k); return {"name": k["name"], "enough": True, "better": k["better"], "actual": [{"x": p, "y": y} for p, y in zip(per[-24:], ys[-24:])], "forecast": [{"x": (last + datetime.timedelta(days=f["k"] * sd)).isoformat(), "y": round(f["y"], 2), "lo": round(f["lo"], 2), "hi": round(f["hi"], 2)} for f in fc], "thresholds": {"amber": k["amber"], "red": k["red"]}, "breach": breach_of(k, fc), "anomaly": anomaly(ys), "backtest": backtest(ys, k)}


def act_revalidate(db, c, body):
    res = []; acc, leads, fa, al = [], [], 0, 0
    for k, per, ys in usable(db):
        b = backtest(ys, k)
        if b and b["accuracy"] is not None:
            acc.append(b["accuracy"]); fa += b["false_alarms"]; al += b["alarms"]
            if b["lead"] is not None:
                leads.append(b["lead"])
            res.append({"kri": k["code"], **b})
    if not acc:
        raise HTTPError(409, "state", "No indicator has enough readings (10 or more) to back-test yet.")
    m = {"accuracy": round(sum(acc) / len(acc), 3), "lead": round(sum(leads) / len(leads), 1) if leads else None, "false_alarm_rate": round(fa / al, 2) if al else 0.0, "indicators": len(acc)}
    seed_item(db, "predictive_analytics", "validation", dict(m, validated_on=dbm.today().isoformat(), by=c.user["full_name"], detail=res[:30]), "recorded", c.user["username"])
    for mo in load(db, "predictive_analytics", "model"):
        if mo.get("method") == "forecast":
            set_data(db, mo["id"], accuracy=m["accuracy"], validated_on=dbm.today().isoformat(), lead=m["lead"], false_alarm_rate=m["false_alarm_rate"])
    return m


def act_confirm(db, c, body):
    k = db.execute("SELECT * FROM kpis WHERE id=? AND deleted_at IS NULL", (int(body.get("kpi_id") or 0),)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Indicator not found.")
    per, ys = series(db, k["id"]); fc = forecast(ys); b = breach_of(k, fc) if fc else None
    if not b:
        raise HTTPError(409, "state", "No breach is forecast for this indicator now.")
    ref = make_action(db, c, "Forecast breach of %s: %s expected in about %d period(s)" % (k["code"], b["level"], b["k"]), "Advisory forecast (probability %d%%) confirmed by %s. %s" % (round(b["probability"] * 100), c.user["full_name"], str(body.get("note") or "")), "Head of Risk", 14)
    seed_item(db, "predictive_analytics", "confirmation", {"kpi": k["code"], "level": b["level"], "probability": b["probability"], "action": ref, "by": c.user["full_name"], "at": now()}, "confirmed", c.user["username"])
    return {"action": ref}


def overview(db, c, today):
    ms = load(db, "predictive_analytics", "model", today); cands = usable(db); pr = predicted(db); val = sorted(load(db, "predictive_analytics", "validation", today), key=lambda v: v.get("validated_on") or "", reverse=True); v = val[0] if val else None
    top = next((r for r in pr if r["breach"]), None) or (pr[0] if pr else None); first = top["kpi_id"] if top else (cands[0][0]["id"] if cands else None)
    return [tiles(("Active models", sum(1 for m in ms if m["status"] == "active"), "%d on the register" % len(ms), BLUE), ("Forecast accuracy", ("%d%%" % round(v["accuracy"] * 100)) if v else "not validated", "walk-forward back-test over %d indicators" % v["indicators"] if v else "run a validation", GOOD if v and v["accuracy"] >= 0.8 else WARN), ("Average early warning", ("%s periods" % v["lead"]) if v and v.get("lead") else "n/a", "before a real breach, in back-tests", PURPLE), ("False alarms", ("%d%%" % round(v["false_alarm_rate"] * 100)) if v else "n/a", "of back-tested alarms", TEAL)),
            panel("forecast", "Forecast with confidence band", 12, indicators=[{"id": k["id"], "name": "%s: %s" % (k["code"], k["name"])} for k, p, y in cands], first=first, empty="No indicator has 6 or more readings yet."),
            panel("table", "Predicted breaches and anomalies (advisory)", 12, cols=["Indicator", "Latest", "Expected", "Confidence", "Anomaly", ""], rows=[[{"v": "%s %s" % (r["code"], r["name"][:40])}, {"v": r["latest"], "chip": {"red": BAD, "amber": "#FDB022"}.get(r["status"])}, {"v": ("%s in about %d period(s), around %s" % (r["breach"]["level"], r["breach"]["k"], r["expected"])) if r["breach"] else "none forecast"}, {"v": ("%d%%" % round(r["breach"]["probability"] * 100)) if r["breach"] else ""}, {"v": ("unusual: z=%s" % r["anomaly"]["z"]) if r["anomaly"] else "", "chip": BAD if r["anomaly"] else None}, {"v": "Confirm and open an action" if r["breach"] and "edit" in c.perms.get("predictive_analytics", set()) else "", "btn": {"kpi_id": r["kpi_id"]}}] for r in pr], note="Forecasts are advisory. A person confirms one before an action is raised; models are revalidated on a schedule."),
            panel("table", "Model register", 12, cols=["Model", "Use", "Accuracy", "Validated", "Status"], rows=[[{"v": m["name"]}, (m.get("use") or "")[:60], ("%d%%" % round(m["accuracy"] * 100)) if m.get("accuracy") is not None else "not validated", {"v": m.get("validated_on") or "never", "chip": BAD if m["stale"] else None}, m["status"]] for m in ms], note="Method and limits are on each model. A model not validated in 90 days is flagged.")]


def model_d(db, it, today):
    vd = pd(it.get("validated_on")); return {"stale": bool(it["status"] == "active" and (not vd or (today - vd).days > 90))}


def seed(db):
    for n, u, m, lim in (("KRI trend forecast (Holt linear trend)", "Early warning of KRI and KPI breaches up to 6 periods ahead", "forecast", "Needs 6 or more readings; assumes the recent trend continues; it cannot foresee a sudden shock; the band is 90% from the model's own errors."), ("KRI anomaly detector (robust z-score)", "Flags a reading far from the recent median (median absolute deviation)", "anomaly", "Needs 8 or more readings; flags unusual values, not their cause."), ("Transaction anomaly detection", "Anomalies in transactions (planned)", "planned", "Not built: needs a transaction feed through the Integration Hub.")):
        seed_item(db, "predictive_analytics", "model", {"name": n, "use": u, "method": m, "owner": "Head of Risk", "limits": lim, "accuracy": None, "validated_on": ""}, "active" if m != "planned" else "planned")


register("predictive_analytics", {"perm": "predictive_analytics", "title": "Predictive Analytics", "crumb": "Intelligence", "color": "#F28C28", "intro": "Forecasts KRI breaches and detects anomalies, giving days of warning. The method is plain and stated on the model register; accuracy is measured by walk-forward back-testing on your own readings, not assumed. Forecasts are advisory: a person confirms before an action is raised.",
                                  "tabs": [["overview", "Forecasts"], ["model", "Model register"], ["validation", "Validations"], ["confirmation", "Confirmations"]], "overview": overview, "seed": seed, "actions": [{"id": "revalidate", "label": "Revalidate the models", "needs": "edit", "run": act_revalidate}, {"id": "confirm", "label": "Confirm a forecast", "needs": "edit", "run": act_confirm}],
                                  "entities": {"model": {"label": "Model", "plural": "Model register", "prefix": "MDL", "title_field": "name", "statuses": ["active", "planned", "retired"], "next": None, "columns": ["name", "use", "accuracy", "validated_on", "status"], "derive": model_d, "fields": [F("name", "Model", req=True), F("use", "Use", "textarea", wide=True), F("method", "Method", "select", opts=["forecast", "anomaly", "planned"]), F("owner", "Owner"), F("limits", "Limits and assumptions", "textarea", wide=True), F("accuracy", "Accuracy (0 to 1)", "number"), F("validated_on", "Validated on", "date")]},
                                               "validation": {"label": "Validation", "plural": "Validations", "prefix": "VAL", "title_field": "validated_on", "readonly": True, "statuses": ["recorded"], "next": None, "columns": ["validated_on", "accuracy", "lead", "false_alarm_rate", "indicators", "by"], "fields": [F("validated_on", "Validated on"), F("accuracy", "Accuracy"), F("lead", "Early warning (periods)"), F("false_alarm_rate", "False alarm rate"), F("indicators", "Indicators"), F("by", "By")]},
                                               "confirmation": {"label": "Confirmation", "plural": "Confirmed forecasts", "prefix": "CNF", "title_field": "kpi", "readonly": True, "statuses": ["confirmed"], "next": None, "columns": ["kpi", "level", "probability", "action", "by", "at"], "fields": [F("kpi", "Indicator"), F("level", "Level"), F("probability", "Probability"), F("action", "Action"), F("by", "Confirmed by"), F("at", "When")]}}})
