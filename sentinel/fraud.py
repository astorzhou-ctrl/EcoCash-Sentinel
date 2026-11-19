"""Fraud Intelligence (BRD 9.16): turns mobile-money fraud alerts and cases into insight: typologies, agent hotspots, SIM-swap trend against the KRI thresholds, case pipeline,
fraud rate and recovery. Fraud sits with the Head of Compliance and ML/CTF. Alerts come from the fraud and AML monitoring system (CSV import) or are entered by hand.
Early patterns and hotspots are found by rule (a spike against the previous weeks; a cluster that holds more than its share); a person confirms every case."""
import csv
import datetime
import hashlib
import io
import json
import math
import re

from . import ai, analytics, xlsxbook
from .api import router, need, need_str
from .core import audit, now
from .p2 import xlsx_response
from .web import HTTPError
from . import db as dbm

TYPOLOGIES = ["SIM swap", "Account takeover", "Social engineering (phishing, vishing, OTP)", "Agent fraud (float manipulation, collusion)", "Fake or cloned agent", "Merchant or payment fraud", "Insider fraud", "Identity or KYC fraud", "Reversal fraud", "Mule account activity", "Other"]
CHANNELS = ["USSD", "App", "Agent", "Web or API", "Call centre", "Other"]
STATUSES = ["detected", "investigating", "confirmed", "recovered", "closed", "false_positive"]
NEXT = {"detected": ("investigating", "false_positive"), "investigating": ("confirmed", "false_positive"), "confirmed": ("recovered", "closed"), "recovered": ("closed",), "closed": (), "false_positive": ()}
CONTROL_IDEAS = {"SIM swap": ["Cooling-off period and lower limits after a SIM replacement", "Identity verification and biometric check at the outlet", "Alert the old device and confirm out of band", "Monitor replacement spikes by outlet"],
                 "Account takeover": ["Step-up authentication for new devices and large transfers", "Velocity and device-change rules in real-time monitoring"], "Social engineering (phishing, vishing, OTP)": ["Customer and agent awareness campaigns on OTP sharing", "Warn on first transfer to a new payee"],
                 "Agent fraud (float manipulation, collusion)": ["Float and reversal monitoring by agent", "Rotation and surprise audits for high-risk agents"], "Fake or cloned agent": ["Agent code verification and geo-checks", "Public tools to verify an agent"], "Insider fraud": ["Segregation of duties and access reviews", "Monitoring of privileged activity"],
                 "Identity or KYC fraud": ["Document and liveness checks at registration"], "Mule account activity": ["Network analysis of linked accounts", "Limits on new accounts"], "Reversal fraud": ["Reversal limits and second approval"], "Merchant or payment fraud": ["Merchant onboarding checks and settlement holds"]}


def settings(db):
    r = db.execute("SELECT value FROM settings WHERE key='fraud'").fetchone(); d = {"sim_amber_day": None, "sim_red_day": None, "fraud_rate_limit_pct": None}
    if r:
        d.update(json.loads(r["value"]))
    return d


def sim_thresholds(db):
    """Amber and red for SIM-swap attempts per day. From the SIM-swap KRI in KRI Monitor (a weekly figure, divided by 7) unless the Head of Compliance set daily values."""
    s = settings(db)
    if s["sim_amber_day"] is not None and s["sim_red_day"] is not None:
        return {"amber": s["sim_amber_day"], "red": s["sim_red_day"], "source": "Set in Fraud Intelligence"}
    k = db.execute("SELECT code, name, amber, red FROM kpis WHERE kind='kri' AND active=1 AND deleted_at IS NULL AND lower(name) LIKE '%sim%swap%' AND amber IS NOT NULL AND red IS NOT NULL ORDER BY (lower(name) LIKE '%week%') DESC LIMIT 1").fetchone()
    if k:
        per = 7.0 if "month" not in k["name"].lower() else 30.0
        return {"amber": round(k["amber"] / per, 1), "red": round(k["red"] / per, 1), "source": "KRI Monitor: %s (%s; its amber and red thresholds divided by %d to give a daily figure)" % (k["code"], k["name"], int(per))}
    return {"amber": None, "red": None, "source": None}


def d_of(s):
    return datetime.date.fromisoformat((s or "")[:10])


def view(r):
    d = dict(r); d["hours_to_contain"] = round((datetime.datetime.fromisoformat(r["contained_at"].replace("Z", "")) - datetime.datetime.fromisoformat(r["detected_at"].replace("Z", ""))).total_seconds() / 3600, 1) if r["contained_at"] else None; d["next"] = list(NEXT.get(r["status"], ())); return d


def alerts(db, days=None, today=None):
    today = today or dbm.today(); q = "SELECT * FROM fraud_alerts WHERE deleted_at IS NULL"; a = []
    if days:
        q += " AND substr(detected_at,1,10) >= ?"; a.append((today - datetime.timedelta(days=days)).isoformat())
    return [dict(r) for r in db.execute(q + " ORDER BY detected_at DESC", a)]


def patterns(db, rows, today):
    """Early patterns and hotspots by rule: a typology up sharply on its recent weeks, and agent clusters holding more than their share."""
    out = []; wk = lambda r: (today - d_of(r["detected_at"])).days // 7
    by = {}
    for r in rows:
        if r["status"] != "false_positive":
            by.setdefault(r["typology"], {}).setdefault(wk(r), 0); by[r["typology"]][wk(r)] += 1
    for t, w in by.items():
        last = w.get(0, 0); prev = [w.get(i, 0) for i in range(1, 9)]; mean = sum(prev) / 8.0; sd = math.sqrt(sum((x - mean) ** 2 for x in prev) / 8.0) or 1.0; z = (last - mean) / sd
        if last >= 3 and z >= 2:
            out.append({"kind": "spike", "typology": t, "text": "%s: %d alerts in the last 7 days against an average of %.1f a week before (%.1f standard deviations up)." % (t, last, mean, z), "severity": "High" if z >= 3 else "Medium"})
    recent = [r for r in rows if r["agent_cluster"] and (today - d_of(r["detected_at"])).days <= 14 and r["status"] != "false_positive"]; cl = {}
    for r in recent:
        cl[r["agent_cluster"]] = cl.get(r["agent_cluster"], 0) + 1
    for k, n in sorted(cl.items(), key=lambda z: -z[1])[:5]:
        others = [v for kk, v in cl.items() if kk != k]; base = (sum(others) / len(others)) if others else 0.0  # compared with the OTHER clusters, so a dominant one cannot hide itself in the average
        if n >= 3 and (not others or n >= 2 * max(base, 1.0)):
            out.append({"kind": "hotspot", "cluster": k, "text": "Agent cluster \u201C%s\u201D: %d cases in 14 days%s." % (k, n, ", %.1f times the average of the other clusters" % (n / base) if base else ", with no other cluster above one"), "severity": "High" if n >= 5 else "Medium"})
    return out


def ideas(db, c, rows):
    """Control improvements from the outcomes of confirmed cases: the most frequent confirmed typology, the library's own controls for it, and standard practice."""
    conf = [r for r in rows if r["status"] in ("confirmed", "recovered", "closed") and (r["loss"] or 0) > 0]
    by = {}
    for r in conf:
        by[r["typology"]] = by.get(r["typology"], 0) + (r["loss"] or 0)
    out = []
    for t, loss in sorted(by.items(), key=lambda z: -z[1])[:2]:
        lib = [x["statement"][:140] for x in ai.similar(db, c, t + " fraud")["controls"][:2] if x.get("statement")]
        out.append({"typology": t, "loss": round(loss), "ideas": CONTROL_IDEAS.get(t, ["Review the controls with the owner after the post-case review"]), "library": lib})
    return out


@router.route("GET", "/api/fraud/overview")
def overview(req):
    c = need(req, "fraud_intelligence", "view"); today = dbm.today(); rows = alerts(req.db); r90 = [r for r in rows if (today - d_of(r["detected_at"])).days <= 90]; r30 = [r for r in rows if (today - d_of(r["detected_at"])).days <= 30]; live = [r for r in r90 if r["status"] != "false_positive"]
    mix = {}
    for r in live:
        mix[r["typology"]] = mix.get(r["typology"], 0) + 1
    stage = {"Detected": len(live), "Investigating": sum(1 for r in live if r["status"] != "detected"), "Confirmed": sum(1 for r in live if r["status"] in ("confirmed", "recovered", "closed") and (r["loss"] or 0) >= 0 and r["status"] != "detected" and r["outcome"] != "not fraud"), "Recovered": sum(1 for r in live if (r["recovered"] or 0) > 0)}
    cl = {}
    for r in live:
        if r["agent_cluster"]:
            cl[r["agent_cluster"]] = cl.get(r["agent_cluster"], 0) + 1
    daily = {r["day"]: dict(r) for r in req.db.execute("SELECT * FROM fraud_sim_daily WHERE day >= ? ORDER BY day", ((today - datetime.timedelta(days=60)).isoformat(),))}
    for r in rows:
        if r["typology"] == "SIM swap" and (today - d_of(r["detected_at"])).days <= 60 and r["detected_at"][:10] not in daily:
            daily.setdefault("_c" + r["detected_at"][:10], {"day": r["detected_at"][:10], "attempts": 0})["attempts"] += 1
    series = {}
    for v in daily.values():
        series[v["day"]] = series.get(v["day"], 0) + v["attempts"]
    line = [{"day": (today - datetime.timedelta(days=i)).isoformat(), "attempts": series.get((today - datetime.timedelta(days=i)).isoformat(), 0)} for i in range(59, -1, -1)]
    sim7 = sum(x["attempts"] for x in line[-7:]); simp = sum(x["attempts"] for x in line[-14:-7]); loss30 = sum(r["loss"] or 0 for r in r30 if r["status"] != "false_positive")
    base = req.db.execute("SELECT txn_value FROM fraud_base WHERE period=?", ((today.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m"),)).fetchone() or req.db.execute("SELECT txn_value FROM fraud_base ORDER BY period DESC LIMIT 1").fetchone()
    lim = settings(req.db)["fraud_rate_limit_pct"]; rate = (loss30 / base["txn_value"] * 100) if base and base["txn_value"] else None
    loss90 = sum(r["loss"] or 0 for r in live); rec90 = sum(r["recovered"] or 0 for r in live); contain = [view(r)["hours_to_contain"] for r in live if r["contained_at"]]
    thr = sim_thresholds(req.db); frows, _ = analytics.risk_rows(req.db, c) if "risk_register" in c.perms else ([], None)
    risks = [{"id": r["id"], "ref": r["source_ref"] or r["ref"], "title": r["title"][:90], "rrr": r["rrr"], "loa": r["loa"]} for r in frows if (r["category"] or "") == "Fraud" or "fraud" in (r["title"] or "").lower()][:8]
    kris = []
    for k in req.db.execute("SELECT id, code, name, kind, better, target, amber, red FROM kpis WHERE active=1 AND deleted_at IS NULL AND (lower(name) LIKE '%fraud%' OR lower(name) LIKE '%sim%swap%' OR lower(name) LIKE '%otp%') ORDER BY kind DESC LIMIT 8"):
        rs = req.db.execute("SELECT value FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
        from . import p2
        kris.append({"code": k["code"], "name": k["name"], "kind": k["kind"], "latest": rs["value"] if rs else None, "status": p2.status_of(k, rs["value"]) if rs else None})
    return {"kpis": {"fraud_rate_pct": round(rate, 4) if rate is not None else None, "fraud_rate_limit_pct": lim, "fraud_rate_status": None if rate is None or lim is None else ("Above limit" if rate > lim else "Within limit"), "loss_30d": round(loss30), "sim7": sim7, "sim_prev7": simp, "recovery_rate": round(rec90 / loss90, 3) if loss90 else None, "loss_90d": round(loss90), "recovered_90d": round(rec90), "hours_to_contain": round(sum(contain) / len(contain), 1) if contain else None, "contained_n": len(contain)},
            "typology_mix": sorted([{"typology": k, "count": v} for k, v in mix.items()], key=lambda z: -z["count"]), "pipeline": stage, "hotspots": sorted([{"cluster": k, "count": v} for k, v in cl.items()], key=lambda z: -z["count"])[:10], "sim_line": line, "thresholds": thr, "patterns": patterns(req.db, rows, today), "ideas": ideas(req.db, c, rows), "risks": risks, "indicators": kris,
            "open_cases": sum(1 for r in rows if r["status"] in ("detected", "investigating")), "total": len(rows), "typologies": TYPOLOGIES, "channels": CHANNELS, "statuses": STATUSES, "can": {k: k in c.perms.get("fraud_intelligence", set()) for k in ("create", "edit", "delete", "export")}, "settings": settings(req.db), "base": [dict(r) for r in req.db.execute("SELECT * FROM fraud_base ORDER BY period DESC LIMIT 6")]}


@router.route("GET", "/api/fraud/cases")
def cases(req):
    need(req, "fraud_intelligence", "view"); q = req.query; rows = alerts(req.db)
    for k, f in (("status", "status"), ("typology", "typology"), ("cluster", "agent_cluster")):
        if q.get(k):
            rows = [r for r in rows if r[f] == q[k]]
    if q.get("q"):
        t = q["q"].lower(); rows = [r for r in rows if t in ((r["ref"] or "") + " " + (r["notes"] or "") + " " + (r["agent_cluster"] or "") + " " + (r["region"] or "")).lower()]
    return {"cases": [view(r) for r in rows[:300]], "total": len(rows)}


def clean(b, partial=False, old=None):
    o = dict(old or {}); o.update({k: b[k] for k in b if k in ("detected_at", "typology", "channel", "agent_cluster", "region", "amount", "loss", "recovered", "assigned_to", "notes", "outcome", "risk_id", "control_id", "contained_at")})
    if o.get("typology") not in TYPOLOGIES:
        raise HTTPError(400, "validation", "Choose a typology from the list.")
    if not re.match(r"^\d{4}-\d{2}-\d{2}", str(o.get("detected_at") or "")):
        raise HTTPError(400, "validation", "Give the date (and time) it was detected, like 2026-11-03 or 2026-11-03T09:30.")
    for k in ("amount", "loss", "recovered"):
        try:
            o[k] = float(o.get(k) or 0)
        except (TypeError, ValueError):
            raise HTTPError(400, "validation", "%s must be a number." % k.capitalize())
        if o[k] < 0:
            raise HTTPError(400, "validation", "%s cannot be negative." % k.capitalize())
    if o["recovered"] > o["loss"] + 0.005:
        raise HTTPError(400, "validation", "Recovered cannot be more than the loss.")
    if o.get("channel") and o["channel"] not in CHANNELS:
        raise HTTPError(400, "validation", "Choose a channel from the list.")
    if o.get("contained_at") and str(o["contained_at"]) < str(o["detected_at"]):
        raise HTTPError(400, "validation", "Containment cannot be before detection.")
    return o


@router.route("POST", "/api/fraud/cases")
def case_add(req):
    c = need(req, "fraud_intelligence", "create"); o = clean(req.json()); b = req.json()
    cur = req.db.execute("INSERT INTO fraud_alerts(detected_at,typology,channel,agent_cluster,region,amount,status,assigned_to,loss,recovered,risk_id,control_id,contained_at,notes,source,created_by,created_at) VALUES(?,?,?,?,?,?,'detected',?,?,?,?,?,?,?, 'manual',?,?)",
                         (str(o["detected_at"]), o["typology"], o.get("channel"), str(o.get("agent_cluster") or "").strip()[:80] or None, str(o.get("region") or "").strip()[:60] or None, o["amount"], str(o.get("assigned_to") or "")[:80] or None, o["loss"], o["recovered"], o.get("risk_id") or None, o.get("control_id") or None, o.get("contained_at") or None, str(o.get("notes") or "")[:800], c.user["username"], now()))
    fid = cur.lastrowid; req.db.execute("UPDATE fraud_alerts SET ref=? WHERE id=?", ("FRD-%04d" % fid, fid)); audit(req.db, "fraud.case_add", c.user, "fraud_intelligence", "Fraud alert FRD-%04d (%s)" % (fid, o["typology"]), req.ip)
    return {"id": fid, "ref": "FRD-%04d" % fid}


@router.route("PUT", "/api/fraud/cases/<int:fid>")
def case_edit(req):
    fid = int(req.params["fid"])
    c = need(req, "fraud_intelligence", "edit"); r = req.db.execute("SELECT * FROM fraud_alerts WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone(); b = req.json()
    if not r:
        raise HTTPError(404, "not_found", "Case not found.")
    o = clean(b, True, dict(r)); st = b.get("status") or r["status"]
    if st != r["status"]:
        if st not in NEXT.get(r["status"], ()):
            raise HTTPError(409, "state", "A case moves %s \u2192 %s." % (r["status"], " or ".join(NEXT[r["status"]]) or "nowhere: it is final"))
        if st in ("confirmed", "false_positive", "closed") and len(str(b.get("outcome") or r["outcome"] or "").strip()) < 5:
            raise HTTPError(400, "validation", "Record the outcome in a sentence (what was found, and what was done).")
    if st == "recovered" and o["recovered"] <= 0:
        raise HTTPError(400, "validation", "Enter the amount recovered.")
    req.db.execute("UPDATE fraud_alerts SET detected_at=?, typology=?, channel=?, agent_cluster=?, region=?, amount=?, assigned_to=?, loss=?, recovered=?, risk_id=?, control_id=?, contained_at=?, notes=?, outcome=?, status=?, closed_at=? WHERE id=?",
                   (str(o["detected_at"]), o["typology"], o.get("channel"), o.get("agent_cluster"), o.get("region"), o["amount"], o.get("assigned_to"), o["loss"], o["recovered"], o.get("risk_id") or None, o.get("control_id") or None, o.get("contained_at") or None, str(o.get("notes") or "")[:800], str(b.get("outcome", r["outcome"]) or "")[:600], st, now() if st in ("closed", "false_positive") else r["closed_at"], fid))
    audit(req.db, "fraud.case_edit", c.user, "fraud_intelligence", "%s %s%s" % (r["ref"], "moved to " + st if st != r["status"] else "updated", "; contained" if b.get("contained_at") and not r["contained_at"] else ""), req.ip)
    return {"ok": True}


@router.route("POST", "/api/fraud/cases/<int:fid>/incident")
def case_incident(req):
    fid = int(req.params["fid"])
    """Records a confirmed case as an incident or loss event, linked to its risk."""
    c = need(req, "fraud_intelligence", "edit"); need(req, "incidents_losses", "create"); r = req.db.execute("SELECT * FROM fraud_alerts WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone()
    if not r or r["status"] not in ("confirmed", "recovered", "closed") or r["incident_id"]:
        raise HTTPError(409, "state", "Only a confirmed case without an incident can be recorded as one.")
    iid = req.db.execute("INSERT INTO incidents(title,kind,category,severity,occurred_on,detected_at,description,risk_id,gross_loss,recovered,status,owner,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,'open',?,?,?)",
                         ("%s: %s" % (r["typology"], r["ref"]), "loss" if (r["loss"] or 0) > 0 else "incident", "Fraud", "High" if (r["loss"] or 0) >= 10000 else "Medium", r["detected_at"][:10], r["detected_at"][:10], "From fraud case %s. %s" % (r["ref"], r["outcome"] or ""), r["risk_id"], r["loss"], r["recovered"], r["assigned_to"] or "Head of Compliance and ML/CTF", now(), c.user["id"])).lastrowid
    ref = "INC-%03d" % iid; req.db.execute("UPDATE incidents SET ref=? WHERE id=?", (ref, iid)); req.db.execute("UPDATE fraud_alerts SET incident_id=? WHERE id=?", (iid, fid)); audit(req.db, "fraud.incident", c.user, "fraud_intelligence", "%s recorded as incident %s" % (r["ref"], ref), req.ip)
    return {"ref": ref}


@router.route("DELETE", "/api/fraud/cases/<int:fid>")
def case_del(req):
    fid = int(req.params["fid"])
    c = need(req, "fraud_intelligence", "delete"); r = req.db.execute("SELECT ref FROM fraud_alerts WHERE id=? AND deleted_at IS NULL", (fid,)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Case not found.")
    req.db.execute("UPDATE fraud_alerts SET deleted_at=? WHERE id=?", (now(), fid)); audit(req.db, "fraud.case_del", c.user, "fraud_intelligence", "%s removed" % r["ref"], req.ip)
    return {"ok": True}


HEAD = {"detected_at": ("detected_at", "detected", "date", "timestamp", "time"), "typology": ("typology", "type", "fraud_type", "category"), "channel": ("channel",), "agent_cluster": ("agent_cluster", "agent", "agent_code", "cluster"), "region": ("region", "province", "district"), "amount": ("amount", "attempted", "value"), "loss": ("loss", "loss_amount"), "recovered": ("recovered", "recovery"), "status": ("status",), "ref": ("ref", "id", "alert_id", "case_id")}


def import_text(db, username, text):
    """Alerts from CSV text (used by the screen and by the Integration Hub's fraud connector). Returns the counts."""
    rd = csv.DictReader(io.StringIO(text)); cols = {}
    for f in rd.fieldnames or []:
        for k, alts in HEAD.items():
            if f.strip().lower().replace(" ", "_") in alts and k not in cols:
                cols[k] = f
    if "detected_at" not in cols or "typology" not in cols:
        raise HTTPError(400, "validation", "The file needs at least a date column (detected_at) and a typology column.")
    added = skipped = bad = 0; errors = []; lower = {t.lower(): t for t in TYPOLOGIES}
    for i, row in enumerate(rd, 2):
        g = lambda k: (row.get(cols[k]) or "").strip() if k in cols else ""
        ty = lower.get(g("typology").lower()) or next((t for t in TYPOLOGIES if g("typology").lower() and g("typology").lower() in t.lower()), None) or "Other"
        try:
            o = clean({"detected_at": g("detected_at"), "typology": ty, "channel": g("channel") if g("channel") in CHANNELS else None, "agent_cluster": g("agent_cluster"), "region": g("region"), "amount": g("amount").replace(",", "") or 0, "loss": g("loss").replace(",", "") or 0, "recovered": g("recovered").replace(",", "") or 0})
        except HTTPError as e:
            bad += 1; errors.append("Row %d: %s" % (i, e.message)); continue
        ext = g("ref") or "IMP-" + hashlib.sha256(("%s|%s|%s|%s" % (o["detected_at"], ty, o["agent_cluster"], o["amount"])).encode()).hexdigest()[:10]
        if db.execute("SELECT 1 FROM fraud_alerts WHERE ref=?", (ext,)).fetchone():
            skipped += 1; continue
        st = g("status").lower().replace(" ", "_"); st = st if st in STATUSES else "detected"
        db.execute("INSERT INTO fraud_alerts(ref,detected_at,typology,channel,agent_cluster,region,amount,status,loss,recovered,source,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'feed',?,?)", (ext, str(o["detected_at"]), ty, o.get("channel"), o.get("agent_cluster") or None, o.get("region") or None, o["amount"], st, o["loss"], o["recovered"], username, now())); added += 1
    return {"added": added, "skipped": skipped, "rejected": bad, "errors": errors[:8]}


@router.route("POST", "/api/fraud/import")
def import_csv(req):
    """Alerts from the fraud and AML monitoring system as a CSV (columns: detected_at, typology, channel, agent_cluster, region, amount, loss, recovered, status, ref). Rows already imported (same ref) are skipped."""
    c = need(req, "fraud_intelligence", "create"); text = (req.body() or b"").decode("utf-8-sig", "replace")
    if not text.strip():
        raise HTTPError(400, "validation", "The file is empty.")
    r = import_text(req.db, c.user["username"], text)
    audit(req.db, "fraud.import", c.user, "fraud_intelligence", "Fraud alert import: %d added, %d already held, %d rejected" % (r["added"], r["skipped"], r["rejected"]), req.ip)
    return r


@router.route("POST", "/api/fraud/sim-daily")
def sim_daily(req):
    c = need(req, "fraud_intelligence", "create"); b = req.json(); n = 0
    for r in b.get("rows") or []:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(r.get("day") or "")) or int(r.get("attempts") or -1) < 0:
            raise HTTPError(400, "validation", "Each row needs a date (2026-11-03) and a number of attempts.")
        req.db.execute("INSERT INTO fraud_sim_daily(day,attempts,blocked) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET attempts=excluded.attempts, blocked=excluded.blocked", (r["day"], int(r["attempts"]), int(r.get("blocked") or 0))); n += 1
    audit(req.db, "fraud.sim_daily", c.user, "fraud_intelligence", "SIM-swap daily counts: %d day(s) saved" % n, req.ip)
    return {"saved": n}


@router.route("POST", "/api/fraud/settings")
def save_settings(req):
    c = need(req, "fraud_intelligence", "edit"); b = req.json(); s = settings(req.db)
    for k in ("sim_amber_day", "sim_red_day", "fraud_rate_limit_pct"):
        if k in b:
            s[k] = None if b[k] in (None, "") else float(b[k])
    if s["sim_amber_day"] is not None and s["sim_red_day"] is not None and s["sim_red_day"] < s["sim_amber_day"]:
        raise HTTPError(400, "validation", "Red must be at or above amber.")
    req.db.execute("INSERT INTO settings(key,value) VALUES('fraud',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(s),))
    for p, v in (b.get("base") or {}).items():
        if re.match(r"^\d{4}-\d{2}$", p) and float(v) > 0:
            req.db.execute("INSERT INTO fraud_base(period,txn_value) VALUES(?,?) ON CONFLICT(period) DO UPDATE SET txn_value=excluded.txn_value", (p, float(v)))
    audit(req.db, "fraud.settings", c.user, "fraud_intelligence", "Fraud thresholds and exposure base updated", req.ip)
    return {"ok": True}


@router.route("GET", "/api/fraud/export.xlsx")
def export(req):
    need(req, "fraud_intelligence", "export")
    s1 = [[("Fraud alerts and cases", 3)], [], [(h, 1) for h in ("Ref", "Detected", "Typology", "Channel", "Agent cluster", "Region", "Attempted", "Loss", "Recovered", "Status", "Hours to contain", "Outcome")]]
    for r in alerts(req.db):
        v = view(r); s1.append([r["ref"], r["detected_at"], r["typology"], r["channel"] or "", r["agent_cluster"] or "", r["region"] or "", r["amount"], r["loss"], r["recovered"], r["status"], v["hours_to_contain"] if v["hours_to_contain"] is not None else "", r["outcome"] or ""])
    return xlsx_response(xlsxbook.write([("Cases", s1, [12, 20, 40, 12, 28, 16, 12, 12, 12, 14, 12, 50])]), "Sentinel_fraud_cases.xlsx")
