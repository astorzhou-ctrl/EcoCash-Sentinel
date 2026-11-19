"""AI Insights (BRD: Risk Register 'flags duplicates, suggests controls'; KRI Monitor 'flags anomalies, forecasts breaches'; Control Library 'recommends controls by similarity').
Classical machine learning that runs on this computer: TF-IDF text similarity over the organisation's own risks and controls, and robust statistics
(median and spread) with a straight-line forecast over indicator history. No data leaves the computer and nothing here changes a record: it only suggests."""
import math
import re
from collections import Counter

from . import core, risks as riskmod, matrix
from .api import router, need, need_str
from .core import audit
from .web import HTTPError

MOD = "ai_insights"
STOP = set("the and for with that this from are was were been has have had not but all any can its their our you your per than then also into over under after before during between about use used using via within without which who whom what when where while will would should could may might must more most such other these those they them there here out off one two new each every very".split())
SUFFIX = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "ed", "es", "s")


def stem(w):
    for s in ("sters", "ster"):  # fraudsters -> fraud (only when a real word of five letters or more is left, so register and monster are untouched)
        if w.endswith(s) and len(w) - len(s) >= 5:
            return w[:-len(s)]
    for s in SUFFIX:
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[:-len(s)] + ("y" if s in ("ies", "ied") else "")
    return w


def tokens(text):
    return [stem(w) for w in re.findall(r"[a-z][a-z0-9]{2,}", (text or "").lower()) if w not in STOP]


def vectors(docs, extra=None):
    """TF-IDF vectors (L2-normalised) for docs, using document frequencies of docs plus extra texts."""
    toks = [tokens(t) for t in docs]; allt = toks + ([tokens(x) for x in extra] if extra else [])
    df = Counter(w for t in allt for w in set(t)); n = len(allt)
    idf = {w: math.log((n + 1.0) / (c + 1.0)) + 1.0 for w, c in df.items()}
    out = []
    for t in toks:
        tf = Counter(t); v = {w: (1 + math.log(c)) * idf[w] for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0; out.append({w: x / norm for w, x in v.items()})
    return out, idf


def qvec(text, idf):
    tf = Counter(w for w in tokens(text)); v = {w: (1 + math.log(c)) * idf.get(w, math.log(2.0) + 1.0) for w, c in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {w: x / norm for w, x in v.items()}


def cos(a, b):
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def shared(q, d, k=4):
    return [w for w, _ in sorted(((w, q[w] * d[w]) for w in q if w in d), key=lambda z: -z[1])[:k]]


def similar(db, c, text, exclude_id=None):
    sc, sp = riskmod.scope_sql(c)
    rs = db.execute("SELECT id, ref, title, category, status, root_cause, treatment, res_l, res_c, needs_assessment FROM risks WHERE deleted_at IS NULL AND " + sc, sp).fetchall()
    rs = [r for r in rs if r["id"] != exclude_id]
    ks = db.execute("SELECT k.id, k.ref, k.statement, k.domain, k.ctype, k.ice, k.ice_source, k.risk_id, r.ref rref FROM risk_controls k JOIN risks r ON r.id=k.risk_id WHERE r.deleted_at IS NULL AND " + sc, sp).fetchall()
    ks = [k for k in ks if k["risk_id"] != exclude_id]
    rdocs = [" ".join([r["title"] or ""] * 2 + [r["category"] or "", r["root_cause"] or "", r["treatment"] or ""]) for r in rs]; kdocs = [(k["statement"] or "") + " " + (k["domain"] or "") for k in ks]
    allv, idf = vectors(rdocs + kdocs); rv, kv = allv[:len(rs)], allv[len(rs):]; q = qvec(text, idf)
    risks_out = []
    for r, v in zip(rs, rv):
        full = cos(q, v); s = max(full, 0.5 * full + 0.5 * cos(q, qvec(r["title"], idf)))  # the title counts as much as the whole description, so a long description cannot hide a close title
        if s >= 0.12:
            rating = matrix.rating(r["res_l"], r["res_c"]) if not r["needs_assessment"] else None
            risks_out.append({"id": r["id"], "ref": r["ref"], "title": r["title"], "category": r["category"], "status": r["status"], "level": rating["level"] if rating else None, "similarity": round(s, 3), "because": shared(q, v), "duplicate": s >= 0.5})
    risks_out.sort(key=lambda z: -z["similarity"]); risks_out = risks_out[:5]
    near = {r["id"]: r["similarity"] for r in risks_out}; seen, ctl = set(), []
    score = lambda k, v: 0.65 * cos(q, v) + 0.35 * near.get(k["risk_id"], 0.0)  # the control's own wording matters most; belonging to a similar risk only helps
    for k, v in sorted(zip(ks, kv), key=lambda z: -score(*z)):
        s = score(k, v)
        if cos(q, v) < 0.05:
            continue
        key = re.sub(r"\W+", " ", (k["statement"] or "").lower()).strip()
        if s < 0.12 or key in seen or len(ctl) >= 6:
            continue
        seen.add(key)
        ctl.append({"id": k["id"], "ref": k["ref"], "statement": k["statement"], "domain": k["domain"], "type": k["ctype"], "effectiveness": None if k["ice"] is None else 100 - max(1, min(10, int(round(k["ice"] * 10)))) * 10, "tested": k["ice_source"] == "test", "from_risk": k["rref"], "similarity": round(s, 3), "because": shared(q, v)})
    return {"risks": risks_out, "controls": ctl, "indexed": {"risks": len(rs), "controls": len(ks)}}


@router.route("POST", "/api/ai/similar")
def ai_similar(req):
    c = need(req, MOD, "view"); d = req.json()
    text = need_str(d, "text", "Description", 1500)
    if len(tokens(text)) < 2:
        raise HTTPError(400, "validation", "Describe the risk in a few words (at least two meaningful words).")
    out = similar(req.db, c, text, int(d["exclude_id"]) if d.get("exclude_id") else None)
    audit(req.db, "ai.similar", c.user, MOD, "Similar-risk search: %d risks and %d controls suggested" % (len(out["risks"]), len(out["controls"])), req.ip)
    return out


def median(xs):
    s = sorted(xs); n = len(s); return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def analyse(k, pts):
    vals = [p[1] for p in pts]; last = vals[-1]; base = vals[:-1][-12:]; med = median(base)
    mad = median([abs(x - med) for x in base]) * 1.4826
    if mad < 1e-9:
        mad = (sum(abs(x - med) for x in base) / len(base)) * 1.2533
    z = None if mad < 1e-9 else (last - med) / mad
    better, flags, bad = k["better"], [], False
    worse = lambda delta: (delta > 0 and better == "down") or (delta < 0 and better == "up")
    msg = []
    if z is not None and abs(z) >= 3.0:
        flags.append("spike"); bad = bad or worse(last - med)
        msg.append("The latest value %s is %.1f times the usual spread away from the recent typical value %s" % (fmt(last), abs(z), fmt(med)) + (", in the wrong direction." if worse(last - med) else ", in the good direction."))
    d5 = [b - a for a, b in zip(vals[-6:-1], vals[-5:])]
    if len(d5) == 5 and (all(x > 0 for x in d5) or all(x < 0 for x in d5)):
        flags.append("trend"); bad = bad or worse(d5[-1])
        msg.append("It has moved %s for five readings in a row (%s to %s)%s" % ("up" if d5[-1] > 0 else "down", fmt(vals[-6]), fmt(last), ", the wrong way." if worse(d5[-1]) else "."))
    fc = None; w = vals[-8:]
    if len(w) >= 6 and k["kind"] == "kri" and k["red"] is not None and better in ("up", "down"):
        n = len(w); xm = (n - 1) / 2.0; ym = sum(w) / n; den = sum((i - xm) ** 2 for i in range(n)); slope = sum((i - xm) * (y - ym) for i, y in enumerate(w)) / den
        if worse(slope) and abs(slope) > 1e-9 and ((better == "down" and last < k["red"]) or (better == "up" and last > k["red"])):
            steps = (k["red"] - last) / slope
            if 0 < steps <= 12:
                days = (pts[-1][2] - pts[-8][2]) / 7.0 if len(pts) >= 8 else 7.0
                fc = {"periods": round(steps, 1), "weeks": round(steps * days, 1), "red": k["red"]}; flags.append("forecast"); bad = True
                msg.append("If the recent pace continues it reaches the red threshold (%s) in about %.0f week(s)." % (fmt(k["red"]), max(round(steps * days), 1)))
    if not flags:
        return None
    return {"code": k["code"], "name": k["name"], "kind": k["kind"], "grp": k["grp"], "unit": k["unit"], "latest": {"period": pts[-1][0], "value": last}, "typical": round(med, 3), "z": None if z is None else round(z, 2), "flags": flags, "bad": bad,
            "forecast": fc, "message": " ".join(msg), "spark": vals[-12:], "severity": (3 if bad else 0.5) + (min(abs(z), 10) / 10 if z is not None else 0) + (1 if "forecast" in flags else 0)}


def fmt(v):
    return ("%.1f" % v).rstrip("0").rstrip(".") if abs(v) < 1000 else "{:,.0f}".format(v)


@router.route("GET", "/api/ai/signals")
def ai_signals(req):
    c = need(req, MOD, "view"); import datetime
    out = []
    for k in req.db.execute("SELECT * FROM kpis WHERE deleted_at IS NULL AND internal_key IS NULL").fetchall():
        rows = req.db.execute("SELECT period, value FROM kpi_readings WHERE kpi_id=? ORDER BY period", (k["id"],)).fetchall()
        if len(rows) < 8:
            continue
        pts = [(r["period"], r["value"], datetime.date.fromisoformat(r["period"]).toordinal()) for r in rows]
        a = analyse(k, pts)
        if a:
            out.append(a)
    out.sort(key=lambda z: -z["severity"])
    return {"signals": out[:25], "checked": req.db.execute("SELECT COUNT(*) n FROM kpis WHERE deleted_at IS NULL AND internal_key IS NULL").fetchone()["n"], "method": "Median and spread of the previous 12 readings (robust z-score), five-in-a-row trend rule, straight-line forecast to the red threshold"}
