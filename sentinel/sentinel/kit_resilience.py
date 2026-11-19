"""Resilience modules on the kit: BCM Studio, Third-Party Risk, Cyber & IT Risk, Crisis Room."""
import csv
import datetime
import io
import json

from . import db as dbm
from .core import now, outbox
from .kit import (F, GOOD, WARN, BAD, BLUE, GREY, PURPLE, TEAL, add_months, due_item, harare_now, hist, load, make_action, panel, pct, pd, register, seed_item, set_data, set_status, tiles)
from .web import HTTPError

# =========================================================== BCM Studio
def proc_d(db, it, today):
    rto, rpo, a, b = it.get("rto_hours"), it.get("rpo_hours"), it.get("achieved_rto_hours"), it.get("achieved_rpo_hours")
    if a is None and b is None:
        st = "not tested"
    else:
        ok = (a is None or rto is None or a <= rto) and (b is None or rpo is None or b <= rpo) and not it.get("gap_open"); st = "meets" if ok else "gap"
    names_a = {x["name"].lower() for x in load(db, "cyber_it_risk", "asset", today)} if "cyber_it_risk" in __import__("sentinel.kit", fromlist=["SPECS"]).SPECS else set(); names_v = {x["name"].lower() for x in load(db, "third_party_risk", "vendor", today)}
    un = [t.strip() for t in (it.get("systems") or "").split(",") if t.strip() and t.strip().lower() not in names_a] + [t.strip() for t in (it.get("vendors") or "").split(",") if t.strip() and t.strip().lower() not in names_v]
    return {"recovery_status": st, "unlinked_deps": un}


def plan_d(db, it, today):
    nr = pd(it.get("next_review")); return {"review_overdue": bool(it["status"] == "current" and (not nr or nr < today))}


def plan_v(db, c, d, old):
    if d.get("last_review") and not d.get("next_review"):
        d["next_review"] = add_months(pd(d["last_review"]), 12).isoformat()  # a plan must be reviewed within 12 months


def ex_after(db, c, it, event, old):
    """A finished exercise updates the process's achieved recovery. A gap creates an action and keeps recovery capability lowered until a later exercise passes."""
    if it["status"] != "done" or not it.get("result"):
        return
    p = next((x for x in load(db, "bcm_studio", "process") if (x.get("name") or "").lower() == (it.get("process") or "").lower()), None)
    if not p:
        return
    upd = {"last_tested": it.get("exercise_date")}
    for k in ("achieved_rto_hours", "achieved_rpo_hours"):
        if it.get(k) is not None:
            upd[k] = it[k]
    if it["result"] == "Passed":
        upd["gap_open"] = False
    else:
        upd["gap_open"] = True
        if not p.get("gap_action"):
            upd["gap_action"] = make_action(db, c, "Exercise gap: %s (%s)" % (p["name"], it["result"]), it.get("lessons") or "The exercise did not meet the recovery targets.", p.get("owner") or "Head of Risk", 30)
            hist(db, it["id"], c.user["username"], "gap action created", upd["gap_action"])
    if it["result"] == "Passed":
        upd["gap_action"] = ""
    set_data(db, p["id"], **upd)


def bcm_overview(db, c, today):
    pr = load(db, "bcm_studio", "process", today); pl = load(db, "bcm_studio", "plan", today); ex = load(db, "bcm_studio", "exercise", today); crit = [p for p in pr if p.get("criticality") in ("Critical", "High")]; tested = [p for p in pr if p["recovery_status"] != "not tested"]
    rto_ok = [p for p in tested if p.get("achieved_rto_hours") is None or p.get("rto_hours") is None or p["achieved_rto_hours"] <= p["rto_hours"]]; rpo_ok = [p for p in tested if p.get("achieved_rpo_hours") is None or p.get("rpo_hours") is None or p["achieved_rpo_hours"] <= p["rpo_hours"]]
    yr = [e for e in ex if (e.get("exercise_date") or "")[:4] == str(today.year)]; curp = [p for p in pl if p["status"] == "current"]; ok_p = [p for p in curp if not p["review_overdue"]]
    g = [{"label": e["name"][:34], "start": int(e["exercise_date"][5:7]), "end": int(e["exercise_date"][5:7]), "color": GOOD if e["status"] == "done" else BLUE, "tip": e["exercise_date"]} for e in yr if e.get("exercise_date")]
    return [tiles(("Critical processes", len(crit), "critical or high", BLUE), ("Plans current", "%d of %d" % (len(ok_p), len(pl)), "reviewed within 12 months", GOOD if len(ok_p) == len(pl) else WARN), ("Exercises %d" % today.year, "%d of %d" % (sum(1 for e in yr if e["status"] == "done"), len(yr)), "done of planned", PURPLE), ("RTO gaps", sum(1 for p in pr if p["recovery_status"] == "gap"), "achieved recovery slower than the target", BAD if any(p["recovery_status"] == "gap" for p in pr) else GOOD)),
            panel("table", "Business impact analysis", 12, cols=["Process", "Criticality", "RTO (h)", "Achieved", "RPO (h)", "Achieved", "Minimum service", "Status"], rows=[[{"v": p["name"][:40]}, p.get("criticality") or "", p.get("rto_hours"), p.get("achieved_rto_hours") if p.get("achieved_rto_hours") is not None else "not tested", p.get("rpo_hours"), p.get("achieved_rpo_hours") if p.get("achieved_rpo_hours") is not None else "not tested", (p.get("min_service") or "")[:30], {"v": p["recovery_status"], "chip": {"meets": GOOD, "gap": BAD}.get(p["recovery_status"], GREY)}] for p in pr[:20]], note="Dependencies on systems and vendors link to Cyber & IT Risk and Third-Party Risk by name; %d dependency name(s) do not match a record yet." % sum(len(p["unlinked_deps"]) for p in pr)),
            panel("donut", "Recovery capability: processes meeting RTO", 3, items=[{"label": "meets RTO", "value": len(rto_ok), "color": GOOD}, {"label": "misses RTO", "value": len(tested) - len(rto_ok), "color": BAD}], center="tested"),
            panel("donut", "Recovery capability: processes meeting RPO", 3, items=[{"label": "meets RPO", "value": len(rpo_ok), "color": GOOD}, {"label": "misses RPO", "value": len(tested) - len(rpo_ok), "color": BAD}], center="tested"),
            panel("donut", "Plan status", 3, items=[{"label": "current", "value": len(ok_p), "color": GOOD}, {"label": "due for review", "value": len(pl) - len(ok_p), "color": BAD}], center="plans"),
            panel("gantt", "Exercise calendar, %d" % today.year, 12, items=g, empty="No exercise is planned this year.")]


def bcm_rem(db, today, horizon):
    h = horizon.isoformat(); out = [due_item("Continuity plan review", p, "name", "next_review", "owner", "#/m/bcm_studio") for p in load(db, "bcm_studio", "plan", today) if p["status"] == "current" and p.get("next_review") and p["next_review"] <= h]
    return out + [due_item("Continuity exercise", e, "name", "exercise_date", "owner", "#/m/bcm_studio") for e in load(db, "bcm_studio", "exercise", today) if e["status"] == "planned" and e.get("exercise_date") and e["exercise_date"] <= h]


register("bcm_studio", {"perm": "bcm_studio", "title": "BCM Studio", "crumb": "Resilience", "color": "#2FA84F", "intro": "The operational continuity workbench: business impact analysis, recovery targets, plans and exercises. A finished exercise updates the process's achieved recovery; a gap creates an action and keeps recovery capability lowered until a later exercise passes. It feeds the BCMS workspace.",
                        "tabs": [["overview", "Overview"], ["process", "Business impact analysis"], ["plan", "Plans"], ["exercise", "Exercises"]], "overview": bcm_overview, "reminders": bcm_rem,
                        "entities": {"process": {"label": "Process", "plural": "Critical processes", "prefix": "BIA", "title_field": "name", "statuses": ["active", "retired"], "next": None, "columns": ["name", "criticality", "owner", "rto_hours", "achieved_rto_hours", "rpo_hours", "achieved_rpo_hours"], "derive": proc_d, "fields": [F("name", "Process or service", req=True), F("owner", "Process owner"), F("criticality", "Criticality", "select", opts=["Critical", "High", "Medium", "Low"]), F("rto_hours", "Recovery time objective (hours)", "number"), F("rpo_hours", "Recovery point objective (hours)", "number"), F("min_service", "Minimum service level"), F("systems", "Systems it depends on (comma separated)"), F("vendors", "Vendors it depends on (comma separated)"), F("achieved_rto_hours", "Achieved RTO in the last test (hours)", "number"), F("achieved_rpo_hours", "Achieved RPO in the last test (hours)", "number"), F("last_tested", "Last tested", "date")]},
                                     "plan": {"label": "Plan", "plural": "Plans", "prefix": "BCP", "title_field": "name", "statuses": ["draft", "current", "retired"], "next": None, "colors": {"current": "good"}, "columns": ["name", "process", "owner", "version", "last_review", "next_review", "status"], "derive": plan_d, "validate": plan_v, "fields": [F("name", "Plan", req=True), F("process", "Process covered"), F("owner", "Owner"), F("version", "Version", default="1.0"), F("last_review", "Last reviewed", "date"), F("next_review", "Next review (12 months)", "date"), F("notes", "Notes", "textarea", wide=True)]},
                                     "exercise": {"label": "Exercise", "plural": "Exercises", "prefix": "EXR", "title_field": "name", "statuses": ["planned", "done", "cancelled"], "next": None, "colors": {"done": "good"}, "columns": ["name", "type", "exercise_date", "process", "result", "status"], "after": ex_after, "fields": [F("name", "Exercise", req=True), F("type", "Type", "select", opts=["Tabletop", "Walkthrough", "Failover test", "Full simulation"]), F("exercise_date", "Date", "date", req=True), F("process", "Process tested (as named in the BIA)"), F("owner", "Lead"), F("result", "Result", "select", opts=["Passed", "Partial", "Failed"]), F("achieved_rto_hours", "Achieved RTO (hours)", "number"), F("achieved_rpo_hours", "Achieved RPO (hours)", "number"), F("lessons", "Lessons and gaps", "textarea", wide=True)]}}})

# =========================================================== Third-Party Risk
QUESTIONS = [("q1", "Information security policy and ISO 27001 (or equivalent) certification", 10), ("q2", "Access control and multi-factor authentication for our data", 10), ("q3", "Data protection and privacy compliance, including transfers outside Zimbabwe", 10), ("q4", "Incident response and breach notification within 24 hours", 10), ("q5", "Business continuity and disaster recovery tested in the last 12 months", 10), ("q6", "Subcontractors (fourth parties) disclosed and controlled", 8), ("q7", "Evidence of financial stability", 8), ("q8", "Service levels with reporting and penalties", 8), ("q9", "Right to audit and regulator access in the contract", 8), ("q10", "Vulnerability management and penetration testing", 8), ("q11", "Exit and termination terms, including return of data", 5), ("q12", "Staff screening and training", 5)]
LEVELS = ["Low", "Medium", "Significant", "High"]


def rating_of(score, tier, inc):
    if score is None:
        return "Not assessed"
    i = 0 if score >= 80 else 1 if score >= 65 else 2 if score >= 50 else 3
    if str(tier) == "1" and (inc or 0) >= 2:
        i = min(3, i + 1)
    return LEVELS[i]


def vend_d(db, it, today):
    ad = pd(it.get("assessment_date")); ce = pd(it.get("contract_end")); tier = str(it.get("tier") or "")
    return {"risk_rating": rating_of(it.get("assessment_score"), tier, it.get("incidents_12m")), "assessment_current": bool(ad and (today - ad).days <= 365), "contract_days": (ce - today).days if ce else None, "contract_soon": bool(ce and 0 <= (ce - today).days <= 90), "contract_ended": bool(ce and ce < today and it["status"] == "active"), "exit_gap": bool(tier == "1" and it.get("exit_plan") != "Tested" and it["status"] in ("prospect", "active", "under review"))}


def act_assess(db, c, body):
    from . import kit
    r, v = kit.one(db, "third_party_risk", "vendor", int(body.get("id") or 0)); ans = body.get("answers") or {}; tot = 0.0
    for q, t, w in QUESTIONS:
        a = ans.get(q)
        if a not in ("yes", "partial", "no"):
            raise HTTPError(400, "validation", "Answer every question (yes, partial or no): missing '%s'." % t[:50])
        tot += w * {"yes": 1.0, "partial": 0.5, "no": 0.0}[a]
    score = round(tot); today = dbm.today().isoformat(); seed_item(db, "third_party_risk", "assessment", {"vendor_id": v["id"], "vendor": v["name"], "date": today, "score": score, "answers": ans, "by": c.user["full_name"], "weak": [t for q, t, w in QUESTIONS if ans[q] == "no"]}, "recorded", c.user["username"])
    set_data(db, v["id"], assessment_date=today, assessment_score=score); hist(db, v["id"], c.user["username"], "assessed", "score %d" % score)
    return {"score": score, "rating": rating_of(score, v.get("tier"), v.get("incidents_12m"))}


def tpr_overview(db, c, today):
    vs = [v for v in load(db, "third_party_risk", "vendor", today) if v["status"] != "exited"]; n = len(vs); cur = [v for v in vs if v["assessment_current"]]; soon = [v for v in vs if v["contract_soon"]]; cat = {}
    for v in vs:
        cat[v.get("service") or "Unspecified"] = cat.get(v.get("service") or "Unspecified", 0) + 1
    mat = {(t, r): 0 for t in ("1", "2", "3") for r in LEVELS + ["Not assessed"]}
    for v in vs:
        t = str(v.get("tier") or "3"); mat[(t, v["risk_rating"])] = mat.get((t, v["risk_rating"]), 0) + 1
    fp = {}
    for v in vs:
        for f in [x.strip() for x in (v.get("fourth_parties") or "").split(",") if x.strip()]:
            fp.setdefault(f, []).append(v["name"])
    watch = [[{"v": v["name"][:40]}, "Tier 1 without a tested exit plan", {"v": v.get("exit_plan") or "none", "chip": BAD}] for v in vs if v["exit_gap"]] + [[{"v": f}, "Fourth party used by %d vendors" % len(l), {"v": ", ".join(l)[:50], "chip": WARN}] for f, l in fp.items() if len(l) >= 2]
    return [tiles(("Vendors", n, "%d critical (tier 1)" % sum(1 for v in vs if str(v.get("tier")) == "1"), BLUE), ("Assessments current", "%s%%" % (pct(len(cur), n) or 0), "%d of %d within 12 months" % (len(cur), n), GOOD), ("Contracts ending", len(soon), "within 90 days", WARN if soon else GOOD), ("Vendor incidents", sum(v.get("incidents_12m") or 0 for v in vs), "in the last 12 months", PURPLE)),
            panel("table", "Vendor register", 12, cols=["Vendor", "Service", "Tier", "Risk", "Assessment score", "Contract end"], rows=[[{"v": v["name"][:40]}, v.get("service") or "", str(v.get("tier") or ""), {"v": v["risk_rating"], "chip": {"Low": GOOD, "Medium": "#FDB022", "Significant": "#F97316", "High": BAD}.get(v["risk_rating"], GREY)}, {"v": v.get("assessment_score") if v.get("assessment_score") is not None else "not assessed", "bar": v.get("assessment_score")}, {"v": v.get("contract_end") or "", "chip": BAD if v["contract_ended"] else (WARN if v["contract_soon"] else None)}] for v in sorted(vs, key=lambda z: str(z.get("tier") or "3"))[:25]]),
            panel("bars", "Concentration: vendors per service category", 4, items=[{"label": k, "value": v, "color": WARN if v >= 3 else BLUE} for k, v in sorted(cat.items(), key=lambda z: -z[1])]),
            panel("matrix", "Criticality (tier) against risk rating", 4, rows=["Tier 1", "Tier 2", "Tier 3"], cols=LEVELS + ["Not assessed"], cells=[[mat[(t, r)] for r in LEVELS + ["Not assessed"]] for t in ("1", "2", "3")]),
            panel("table", "Exit and fourth-party watch", 4, cols=["Vendor or party", "Why", "Detail"], rows=watch, note="Tier 1 vendors need a tested exit plan. A fourth party behind several vendors is a hidden concentration.")]


def tpr_rem(db, today, horizon):
    h = horizon.isoformat(); out = []
    for v in load(db, "third_party_risk", "vendor", today):
        if v["status"] in ("exited",):
            continue
        if v.get("contract_end") and v["contract_end"] <= (today + datetime.timedelta(days=90)).isoformat():
            out.append({"kind": "Vendor contract ends", "ref": v["ref"], "title": v["name"][:100], "due": v["contract_end"], "owner_text": v.get("owner"), "owner_id": None, "level": None, "url": "#/m/third_party_risk"})
        if v.get("assessment_date") and add_months(pd(v["assessment_date"]), 12).isoformat() <= h:
            out.append({"kind": "Vendor assessment due", "ref": v["ref"], "title": v["name"][:100], "due": add_months(pd(v["assessment_date"]), 12).isoformat(), "owner_text": v.get("owner"), "owner_id": None, "level": None, "url": "#/m/third_party_risk"})
    return out


register("third_party_risk", {"perm": "third_party_risk", "title": "Third-Party Risk", "crumb": "Resilience", "color": "#2FA84F", "intro": "Vendors and partners EcoCash depends on: tiering, a weighted 12-question assessment, concentration and exit planning. Tier 1 vendors need a tested exit plan; contracts ending in 90 days and assessments older than 12 months raise reminders.",
                              "tabs": [["overview", "Overview"], ["vendor", "Vendor register"], ["assessment", "Assessments"]], "overview": tpr_overview, "reminders": tpr_rem, "extras": {"questions": [{"id": q, "text": t, "weight": w} for q, t, w in QUESTIONS]}, "actions": [{"id": "assess", "label": "Record an assessment", "needs": "edit", "run": act_assess}],
                              "entities": {"vendor": {"label": "Vendor", "plural": "Vendors", "prefix": "VEN", "title_field": "name", "statuses": ["prospect", "active", "under review", "exiting", "exited"], "next": None, "colors": {"active": "good", "exiting": "warn", "exited": "warn"}, "columns": ["name", "service", "tier", "owner", "assessment_score", "contract_end", "status"], "derive": vend_d,
                                                        "fields": [F("name", "Vendor", req=True), F("service", "Service category", "select", req=True, opts=["Payments and switching", "Mobile network and connectivity", "Cloud and hosting", "Software and platforms", "Cash logistics", "Agent services", "Professional services", "Marketing", "Facilities", "Other"]), F("tier", "Tier (1 critical, 3 low)", "select", req=True, opts=["1", "2", "3"]), F("owner", "Vendor owner"), F("contract_start", "Contract start", "date"), F("contract_end", "Contract end", "date"), F("data_access", "Handles our data", "bool"), F("exit_plan", "Exit plan", "select", opts=["None", "Documented", "Tested"], default="None"), F("exit_tested_on", "Exit plan tested on", "date"), F("fourth_parties", "Its own critical suppliers (comma separated)"), F("incidents_12m", "Incidents in 12 months", "number"), F("notes", "Notes", "textarea", wide=True)]},
                                           "assessment": {"label": "Assessment", "plural": "Assessments", "prefix": "ASM", "title_field": "vendor", "readonly": True, "statuses": ["recorded"], "next": None, "columns": ["vendor", "date", "score", "by"], "fields": [F("vendor", "Vendor"), F("date", "Date"), F("score", "Score (0 to 100)"), F("by", "Assessed by")]}}})

# =========================================================== Cyber & IT Risk
SLA = {"Critical": 7, "High": 30, "Medium": 90, "Low": 180}  # days to patch: proposed, the CISO confirms


def vuln_v(db, c, d, old):
    if d.get("discovered_on") and not d.get("due_on") and d.get("severity") in SLA:
        d["due_on"] = (pd(d["discovered_on"]) + datetime.timedelta(days=SLA[d["severity"]])).isoformat()


def vuln_d(db, it, today):
    due = pd(it.get("due_on")); pat = pd(it.get("patched_on"))
    return {"overdue": bool(it["status"] == "open" and due and due < today), "days_overdue": (today - due).days if it["status"] == "open" and due and due < today else 0, "within_sla": bool(pat and due and pat <= due) if it["status"] == "patched" else None}


def vuln_after(db, c, it, event, old):
    if it["status"] == "patched" and not it.get("patched_on"):
        set_data(db, it["id"], patched_on=dbm.today().isoformat())


def act_import_vulns(db, c, body):
    """Vulnerabilities from the scanner as CSV text: title, asset, severity, discovered_on, due_on, cve, source. Rows already held are skipped."""
    rows = list(csv.DictReader(io.StringIO(str(body.get("csv") or "")))); added = skipped = bad = 0; have = {(v["title"], v.get("asset"), v.get("discovered_on")) for v in load(db, "cyber_it_risk", "vuln")}
    for r in rows:
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}; sev = r.get("severity", "").capitalize()
        if not r.get("title") or sev not in SLA:
            bad += 1; continue
        d = {"title": r["title"][:200], "asset": r.get("asset", ""), "severity": sev, "discovered_on": r.get("discovered_on") or dbm.today().isoformat(), "cve": r.get("cve", ""), "source": r.get("source") or "scanner import"}
        d["due_on"] = r.get("due_on") or (pd(d["discovered_on"]) + datetime.timedelta(days=SLA[sev])).isoformat()
        if (d["title"], d["asset"], d["discovered_on"]) in have:
            skipped += 1; continue
        seed_item(db, "cyber_it_risk", "vuln", d, "open", c.user["username"]); added += 1; have.add((d["title"], d["asset"], d["discovered_on"]))
    return {"added": added, "skipped": skipped, "rejected": bad}


def cyber_overview(db, c, today):
    from . import kit_standards as ks
    vs = load(db, "cyber_it_risk", "vuln", today); assets = [a for a in load(db, "cyber_it_risk", "asset", today) if a.get("in_scope") is not False]; snaps = sorted(load(db, "cyber_it_risk", "snapshot", today), key=lambda s: s.get("week") or "")
    op = [v for v in vs if v["status"] == "open"]; crit = [v for v in op if v["severity"] == "Critical"]; late = [v for v in crit if v["overdue"]]; pat = [v for v in vs if v["status"] == "patched" and v.get("patched_on") and (today - pd(v["patched_on"])).days <= 90]; ok = [v for v in pat if v["within_sla"]]
    mfa = pct(sum(1 for a in assets if a.get("mfa")), len(assets)) if assets else (snaps[-1].get("mfa_pct") if snaps else None); sl = (pct(len(ok), len(pat)) if pat else (snaps[-1].get("patch_sla_pct") if snaps else None)); last = snaps[-1] if snaps else {}
    pts = [{"x": s["week"], "y": (s.get("open_critical") or 0) + (s.get("open_high") or 0)} for s in snaps if s.get("week")] + [{"x": today.isoformat(), "y": sum(1 for v in op if v["severity"] in ("Critical", "High"))}]
    ctl = [x for x in load(db, "standards_hub", "control") if x["standard"] == ks.S27 and x["status"] != "not applicable"]; th = {}
    for x in ctl:
        g = th.setdefault(x["theme"], [0, 0]); g[1] += 1; g[0] += 1 if x["status"] == "implemented" else 0
    risks = []
    try:
        from . import analytics, register
        rows, _ = analytics.risk_rows(db, c); risks = sorted([r for r in rows if (r.get("category") == "Cyber") or r.get("system") == "ISMS"], key=lambda z: -(z["rrr"] or 0))[:6]
    except Exception:
        pass
    return [tiles(("Critical vulnerabilities", len(crit), "%d beyond the %d-day SLA" % (len(late), SLA["Critical"]), BAD if late else (WARN if crit else GOOD)), ("Patch SLA", "%s%%" % sl if sl is not None else "n/a", "patched within SLA, last 90 days", GOOD if (sl or 0) >= 90 else WARN), ("MFA coverage", "%s%%" % mfa if mfa is not None else "n/a", "of assets in scope", TEAL), ("Mean time to detect", "%s h" % last.get("mttd_hours") if last.get("mttd_hours") is not None else "n/a", "latest weekly snapshot", PURPLE)),
            panel("list", "Alerts", 12, items=[{"text": "%s: %s (%s) is %d days beyond its SLA" % (v["severity"], v["title"][:70], v.get("asset") or "asset not named", v["days_overdue"]), "color": BAD} for v in late[:8]], empty="No critical vulnerability is open beyond its SLA."),
            panel("line", "Open critical and high vulnerabilities per week", 7, points=pts), panel("bars", "ISO 27001 Annex A coverage by theme (implemented)", 5, items=[{"label": k, "value": pct(v[0], v[1]) or 0, "text": "%d of %d" % (v[0], v[1]), "color": TEAL} for k, v in th.items()], max=100, percent=True),
            panel("table", "Top cyber risks", 12, cols=["Risk", "Title", "Owner", "Residual", "Assurance"], rows=[[r["source_ref"] or r["ref"], r["title"][:75], r.get("owner") or "", "n/a" if r["rrr"] is None else "%.1f" % r["rrr"], "%d%%" % round(100 * (r["loa"] or 0))] for r in risks])]


def cyber_rem(db, today, horizon):
    h = horizon.isoformat()
    return [{"kind": "Vulnerability (%s)" % v["severity"], "ref": v["ref"], "title": ("%s on %s" % (v["title"], v.get("asset") or "an asset"))[:110], "due": v["due_on"], "owner_text": next((a.get("owner") for a in load(db, "cyber_it_risk", "asset", today) if (a["name"] or "").lower() == (v.get("asset") or "").lower()), None) or "CISO", "owner_id": None, "level": None, "url": "#/m/cyber_it_risk"} for v in load(db, "cyber_it_risk", "vuln", today) if v["status"] == "open" and v.get("due_on") and v["due_on"] <= h and v["severity"] in ("Critical", "High")]


register("cyber_it_risk", {"perm": "cyber_it_risk", "title": "Cyber & IT Risk", "crumb": "Resilience", "color": "#2FA84F", "intro": "The technical view of cyber and IT risk: assets, vulnerabilities with patch SLAs (proposed: Critical 7 days, High 30, Medium 90, Low 180; the CISO confirms), weekly snapshots from the security tools, and Annex A coverage next to the ISMS risks. A critical vulnerability open beyond its SLA raises an alert and a reminder to the asset's owner. Scanner exports can be imported, or sent in through the Integration Hub.",
                           "tabs": [["overview", "Overview"], ["vuln", "Vulnerabilities"], ["asset", "Assets"], ["snapshot", "Weekly snapshots"]], "overview": cyber_overview, "reminders": cyber_rem, "actions": [{"id": "import", "label": "Import scanner CSV", "needs": "create", "run": act_import_vulns}],
                           "entities": {"vuln": {"label": "Vulnerability", "plural": "Vulnerabilities", "prefix": "VUL", "title_field": "title", "statuses": ["open", "patched", "accepted"], "next": {"open": ["patched", "accepted"], "patched": ["open"], "accepted": ["open"]}, "colors": {"patched": "good", "accepted": "warn", "open": "bad"}, "columns": ["title", "asset", "severity", "discovered_on", "due_on", "status"], "derive": vuln_d, "validate": vuln_v, "after": vuln_after, "fields": [F("title", "Vulnerability", req=True), F("asset", "Asset (as named in Assets)"), F("severity", "Severity", "select", req=True, opts=list(SLA)), F("discovered_on", "Discovered on", "date", default=lambda: dbm.today().isoformat()), F("due_on", "Patch due (from the SLA)", "date"), F("patched_on", "Patched on", "date"), F("cve", "CVE or reference"), F("source", "Found by"), F("notes", "Notes", "textarea", wide=True)]},
                                        "asset": {"label": "Asset", "plural": "Assets", "prefix": "AST", "title_field": "name", "statuses": ["active", "retired"], "next": None, "columns": ["name", "type", "criticality", "owner", "mfa", "internet_facing"], "fields": [F("name", "Asset", req=True), F("type", "Type", "select", opts=["Application", "Server", "Database", "Network", "Endpoint fleet", "Cloud service", "Other"]), F("criticality", "Criticality", "select", opts=["Critical", "High", "Medium", "Low"]), F("owner", "Owner"), F("internet_facing", "Internet facing", "bool"), F("mfa", "Multi-factor authentication enforced", "bool"), F("in_scope", "In scope", "bool", default=True)]},
                                        "snapshot": {"label": "Snapshot", "plural": "Weekly snapshots", "prefix": "SNP", "title_field": "week", "statuses": ["recorded"], "next": None, "columns": ["week", "open_critical", "open_high", "patch_sla_pct", "mfa_pct", "mttd_hours"], "fields": [F("week", "Week starting", "date", req=True), F("open_critical", "Open critical vulnerabilities", "number"), F("open_high", "Open high vulnerabilities", "number"), F("patch_sla_pct", "Patched within SLA (%)", "number"), F("mfa_pct", "MFA coverage (%)", "number"), F("mttd_hours", "Mean time to detect (hours)", "number")]}}})

# =========================================================== Crisis Room
def crisis_d(db, it, today):
    try:
        t0 = datetime.datetime.fromisoformat((it.get("declared_at") or "")[:16]); mins = int((harare_now() - t0).total_seconds() // 60)
    except ValueError:
        mins = None
    return {"elapsed": "%dh %02dm" % (mins // 60, mins % 60) if mins is not None and it["status"] == "active" else None}


def crisis_rule(db, c, it, new, note):
    if new == "closed" and len((it.get("lessons") or "").strip()) < 20:
        raise HTTPError(409, "rule", "Record the lessons (what worked, what did not, what changes) before a crisis is closed: they feed the after-action review.")


def crisis_after(db, c, it, event, old):
    if event == "create":
        tag = "DRILL: " if it.get("drill") else ""; seed_item(db, "crisis_room", "log", {"crisis_id": it["id"], "kind": "Decision", "text": "%sCrisis declared at level %s by %s: %s" % (tag, it.get("level") or "?", c.user["full_name"], it.get("summary") or it["title"]), "at": harare_now().isoformat()[:16], "by": c.user["full_name"]}, "logged", c.user["username"]); n = 0
        for k in load(db, "crisis_room", "contact"):
            if k.get("email"):
                outbox(db, k["email"], "%sCRISIS DECLARED (level %s): %s" % (tag, it.get("level") or "?", it["title"]), "%s%s\n\nDeclared by %s. Join the crisis team now. Your role: %s." % (tag, it.get("summary") or it["title"], c.user["full_name"], k["title"]), "crisis"); n += 1
        hist(db, it["id"], c.user["username"], "team notified", "%d contact(s) e-mailed" % n)


def act_log(db, c, body):
    act = next((x for x in load(db, "crisis_room", "crisis") if x["status"] == "active"), None); cid = int(body.get("crisis_id") or (act["id"] if act else 0))
    if not cid:
        raise HTTPError(409, "state", "No crisis is active.")
    if body.get("kind") not in ("Decision", "Action", "Message", "Note"):
        raise HTTPError(400, "validation", "Choose Decision, Action, Message or Note.")
    t = str(body.get("text") or "").strip()[:800]
    if len(t) < 3:
        raise HTTPError(400, "validation", "Write the entry.")
    seed_item(db, "crisis_room", "log", {"crisis_id": cid, "kind": body["kind"], "text": t, "at": harare_now().isoformat()[:16], "by": c.user["full_name"]}, "logged", c.user["username"]); return {"ok": True}


def pb_d(db, it, today):
    lt = pd(it.get("last_tested")); return {"stale": bool(not lt or (today - lt).days > 365)}


def crisis_overview(db, c, today):
    cr = load(db, "crisis_room", "crisis", today); act = [x for x in cr if x["status"] == "active"]; ct = load(db, "crisis_room", "contact", today); pb = [p for p in load(db, "crisis_room", "playbook", today) if p["status"] == "active"]; lg = load(db, "crisis_room", "log", today)
    a = act[0] if act else None; mine = sorted([x for x in lg if a and x.get("crisis_id") == a["id"]], key=lambda z: z.get("at") or "", reverse=True)
    return [panel("status", "Status board", 12, state=("ACTIVE: %s" % a["title"]) if a else "No crisis is active", level=a.get("level") if a else None, drill=bool(a and a.get("drill")), elapsed=a["elapsed"] if a else None, color=BAD if a else GOOD, decisions=sum(1 for x in mine if x["kind"] == "Decision"), crisis_id=a["id"] if a else None),
            panel("list", "Timeline of the active crisis", 12, items=[{"text": "%s  [%s] %s (%s)" % ((x.get("at") or "").replace("T", " "), x["kind"], x["text"], x.get("by")), "color": BAD if x["kind"] == "Decision" else BLUE} for x in mine[:25]], empty="The timeline starts when a crisis is declared. Decisions and actions are recorded for the after-action review."),
            panel("table", "Crisis team and contacts", 6, cols=["Role", "Primary", "Deputy", "Reachable"], rows=[[{"v": k["title"]}, k.get("primary") or "", k.get("deputy") or "", {"v": k.get("reachable") or "Unknown", "chip": {"Yes": GOOD, "No": BAD}.get(k.get("reachable"), GREY)}] for k in ct], note="Contacts are people's details: only those you enter are shown."),
            panel("table", "Playbook readiness", 6, cols=["Playbook", "Trigger", "Owner", "Last tested"], rows=[[{"v": p["name"]}, (p.get("trigger") or "")[:50], p.get("owner") or "", {"v": p.get("last_tested") or "never tested", "chip": BAD if p["stale"] else None}] for p in pb])]


def crisis_rem(db, today, horizon):
    return [{"kind": "Crisis playbook test", "ref": p["ref"], "title": p["name"][:100], "due": add_months(pd(p["last_tested"]), 12).isoformat(), "owner_text": p.get("owner"), "owner_id": None, "level": None, "url": "#/m/crisis_room"} for p in load(db, "crisis_room", "playbook", today) if p["status"] == "active" and p.get("last_tested") and add_months(pd(p["last_tested"]), 12).isoformat() <= horizon.isoformat()]


def crisis_seed(db):
    for n, t in (("Payments platform outage", "Platform unavailable for more than the RTO of a critical service"), ("Cyber attack or data breach", "Confirmed compromise of systems or customer data"), ("Fraud wave", "Fraud losses or SIM-swap attempts above the red threshold"), ("Loss of a critical supplier", "A tier 1 vendor fails or is unavailable")):
        seed_item(db, "crisis_room", "playbook", {"name": n, "trigger": t, "owner": "", "last_tested": "", "steps": ""}, "active")
    for n, a, t in (("Message to staff", "Staff", "Team: we are managing a crisis (level __). What we know: __. What we are doing: __. What we need from you: __. Next update at __."), ("Message to the regulator", "Regulator", "To: __ (RBZ / POTRAZ). We are notifying you of an incident affecting __. Time detected: __. Services affected: __. Customers affected: __. Actions underway: __. Contact: __."), ("Message to customers", "Customers", "Dear customer, some EcoCash services are affected by __. Your money is __. We are working to restore service by __. Please contact __ if you need help.")):
        seed_item(db, "crisis_room", "template", {"name": n, "audience": a, "text": t}, "active")


register("crisis_room", {"perm": "crisis_room", "title": "Crisis Room", "crumb": "Resilience", "color": "#2FA84F", "intro": "Runs a crisis from one screen: declare, assemble the team (the contacts with an e-mail address are e-mailed at once), follow playbooks, record decisions on a timeline, and learn afterwards. Drills use the same screens. Message templates are starting points to edit.", "declare": {"entity": "crisis", "label": "Declare a crisis"},
                         "tabs": [["overview", "Status board"], ["crisis", "Crises and drills"], ["contact", "Contacts"], ["playbook", "Playbooks"], ["template", "Message templates"], ["log", "Logs"]], "overview": crisis_overview, "seed": crisis_seed, "reminders": crisis_rem, "actions": [{"id": "log", "label": "Add to the timeline", "needs": "edit", "run": act_log}],
                         "entities": {"crisis": {"label": "Crisis", "plural": "Crises and drills", "prefix": "CRS", "title_field": "title", "statuses": ["active", "stood down", "closed"], "next": {"active": ["stood down"], "stood down": ["closed", "active"], "closed": []}, "colors": {"active": "bad", "stood down": "warn", "closed": "good"}, "columns": ["title", "level", "declared_at", "drill", "status"], "derive": crisis_d, "status_rule": crisis_rule, "after": crisis_after,
                                                    "fields": [F("title", "What has happened", req=True), F("level", "Level", "select", req=True, opts=["1", "2", "3"]), F("summary", "Summary", "textarea", wide=True), F("declared_at", "Declared (Harare time)", "datetime", default=lambda: harare_now().isoformat()[:16]), F("drill", "This is a drill", "bool"), F("lessons", "Lessons for the after-action review", "textarea", wide=True)]},
                                      "log": {"label": "Timeline entry", "plural": "Timeline entries", "prefix": "LOG", "title_field": "text", "readonly": True, "statuses": ["logged"], "next": None, "columns": ["at", "kind", "text", "by"], "fields": [F("at", "When"), F("kind", "Kind"), F("text", "Entry"), F("by", "By")]},
                                      "contact": {"label": "Contact", "plural": "Crisis team contacts", "prefix": "CON", "title_field": "title", "statuses": ["active"], "next": None, "columns": ["title", "primary", "phone", "deputy", "reachable"], "fields": [F("title", "Role", req=True), F("primary", "Primary person"), F("phone", "Phone"), F("email", "E-mail"), F("deputy", "Deputy"), F("deputy_phone", "Deputy phone"), F("reachable", "Reachable now", "select", opts=["Yes", "No", "Unknown"], default="Unknown"), F("last_checked", "Contact details checked on", "date")]},
                                      "playbook": {"label": "Playbook", "plural": "Playbooks", "prefix": "PBK", "title_field": "name", "statuses": ["active", "retired"], "next": None, "columns": ["name", "trigger", "owner", "last_tested"], "derive": pb_d, "fields": [F("name", "Playbook", req=True), F("trigger", "Trigger", req=True), F("owner", "Owner"), F("last_tested", "Last tested", "date"), F("steps", "Steps", "textarea", wide=True)]},
                                      "template": {"label": "Message template", "plural": "Message templates", "prefix": "TPL", "title_field": "name", "statuses": ["active"], "next": None, "columns": ["name", "audience"], "fields": [F("name", "Template", req=True), F("audience", "Audience", "select", opts=["Staff", "Regulator", "Customers", "Media"]), F("text", "Text (fill the __ gaps)", "textarea", wide=True)]}}})
