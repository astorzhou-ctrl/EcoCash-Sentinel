"""Compliance modules on the kit: Obligations Hub, Regulatory Change, Privacy & Breach Clock, Policy Hub."""
import datetime
import json

from . import db as dbm
from .core import now, outbox
from .kit import (F, GOOD, WARN, BAD, BLUE, GREY, PURPLE, TEAL, SYS, add_months, due_item, hist, harare_now, load, make_action, make_incident, panel, pct, pd, register, seed_item, set_data, set_status, tiles)
from .web import HTTPError

# =========================================================== Obligations Hub
LAWS = [("Reserve Bank of Zimbabwe Acts", "RBZ"), ("National Payment Systems Act", "RBZ"), ("Guidelines for Retail Payment Systems and Instruments", "RBZ"), ("Money Laundering and Proceeds of Crime Amendment Act", "FIU"), ("Broadcasting Authority of Zimbabwe Act (BAZ)", "BAZ"), ("City Councils By-Laws", "Local authorities"), ("Companies Act", "Companies Registry"), ("Competition Commission", "Competition and Tariff Commission"),
        ("Environmental Management Agency (EMA)", "EMA"), ("Labour Relations Act", "Labour authorities"), ("Lotteries and Gaming Commissions", "Lotteries and Gaming Board"), ("National Archives Museums and Monuments", "National Archives"), ("National Social Security Authority Act", "NSSA"), ("Post and Telecommunications Regulatory Authority of Zimbabwe (POTRAZ)", "POTRAZ"), ("Public Health Act", "Ministry of Health and Child Care"),
        ("Rural District Councils Act (RDCs)", "Local authorities"), ("Zimbabwe Stock Exchange Regulations", "ZSE"), ("Zimbabwe Revenue Authority Acts (ZIMRA)", "ZIMRA"), ("Insurance Pensions Commissions of Zimbabwe Regulations (IPEC)", "IPEC"), ("Ministry of Lands, Agriculture, Water, Climate and Rural Resettlement", "Ministry of Lands"), ("Agricultural Marketing Act", "Agricultural Marketing Authority"),
        ("Ministry of Health and Child Care", "Ministry of Health and Child Care"), ("Bank Use Promotion Act", "RBZ"), ("SI 80 on interoperability", "RBZ"), ("Cyber and Data Protection Act [Chapter 12:07]", "POTRAZ")]
FREQ_M = {"Monthly": 1, "Quarterly": 3, "Annual": 12}


def obl_seed(db):
    first = add_months(dbm.today().replace(day=1), 1) - datetime.timedelta(days=1)
    for name, reg in LAWS:
        seed_item(db, "obligations_hub", "obligation", {"name": name, "regulator": reg, "citation": "GRC Policy Appendix II" if name != LAWS[-1][0] else "GRC Policy section 4; Cyber and Data Protection Act", "owner": "", "frequency": "Monthly", "next_due": first.isoformat(), "material": name in ("Money Laundering and Proceeds of Crime Amendment Act", "National Payment Systems Act", "Cyber and Data Protection Act [Chapter 12:07]"), "evidence": "", "notes": "Seeded from the GRC Policy. Name the owner and ask for the first statement."}, "not assessed")


def obl_derive(db, it, today):
    nd = pd(it.get("next_due"))
    return {"days_to_due": (nd - today).days if nd else None, "overdue": bool(nd and nd < today), "owner_missing": not (it.get("owner") or "").strip(), "statement_this_month": it.get("last_statement") == today.strftime("%Y-%m")}


def obl_attest(db, c, it, body):
    st = body.get("status")
    if st not in ("compliant", "partial", "exception"):
        raise HTTPError(400, "validation", "The statement is compliant, partial or exception.")
    comment = str(body.get("comment") or "").strip()[:800]
    if st != "compliant" and len(comment) < 10:
        raise HTTPError(400, "validation", "Say in a sentence what is not compliant and what is being done.")
    period = dbm.today().strftime("%Y-%m"); iid = it["id"]; d = {"obligation_id": iid, "obligation": it["name"], "period": period, "status": st, "comment": comment, "by": c.user["full_name"]}
    seed_item(db, "obligations_hub", "statement", d, st, c.user["username"])
    upd = {"last_statement": period, "last_attested": now(), "evidence": comment or it.get("evidence") or ""}; res = {"note": "%s statement for %s" % (st, period)}
    today = dbm.today(); eom = add_months(today.replace(day=1), 1) - datetime.timedelta(days=1); nd = pd(it.get("next_due"))
    if it.get("frequency") in FREQ_M and (nd is None or nd <= eom):  # a statement for this period moves the schedule on once; a second one in the same month does not
        upd["next_due"] = (add_months(today.replace(day=1), FREQ_M[it["frequency"]] + 1) - datetime.timedelta(days=1)).isoformat()
    if st == "exception":  # an exception creates an action and, if material, an incident
        upd["exception_action"] = make_action(db, c, "Obligation exception: %s" % it["name"], comment, it.get("owner") or "Head of Compliance and ML/CTF", 30); res["action"] = upd["exception_action"]
        if it.get("material"):
            upd["exception_incident"] = make_incident(db, c, "Regulatory exception: %s" % it["name"], comment, "Regulatory", "High", it.get("owner")); res["incident"] = upd["exception_incident"]
    set_data(db, iid, **upd); set_status(db, iid, st)
    return res


def obl_overview(db, c, today):
    ob = load(db, "obligations_hub", "obligation", today); n = len(ob); cnt = lambda s: sum(1 for o in ob if o["status"] == s)
    exp = [o for o in ob if o.get("frequency") == "Monthly" and not o["owner_missing"]]; got = sum(1 for o in exp if o["statement_this_month"])
    cal = sorted([o for o in ob if o.get("next_due")], key=lambda o: o["next_due"])[:8]; need = [o for o in ob if o["status"] == "exception" or o["overdue"] or o["owner_missing"]][:12]
    return [tiles(("Obligations", n, "%d with an owner" % sum(1 for o in ob if not o["owner_missing"])), ("Compliant", cnt("compliant"), "%s%%" % (pct(cnt("compliant"), n) or 0), GOOD), ("Exceptions", cnt("exception"), "each has an action", BAD if cnt("exception") else GOOD), ("Statements this month", "%d of %d" % (got, len(exp)), "expected from owners of monthly obligations", PURPLE)),
            panel("donut", "Compliance status", 4, items=[{"label": k, "value": cnt(k), "color": col} for k, col in (("compliant", GOOD), ("partial", WARN), ("exception", BAD), ("not assessed", GREY)) if cnt(k)], center="obligations"),
            panel("cards", "Regulatory calendar: next statement dates", 8, items=[{"title": o["name"][:60], "sub": "%s \u00B7 %s" % (o.get("regulator") or "", o.get("owner") or "no owner"), "tag": o["next_due"], "color": BAD if o["overdue"] else (WARN if (o["days_to_due"] or 99) <= 7 else BLUE)} for o in cal]),
            panel("table", "Needs attention", 12, cols=["Obligation", "Regulator", "Owner", "Status", "Next due"], rows=[[{"v": o["name"][:70]}, o.get("regulator") or "", {"v": o.get("owner") or "OWNER NEEDED", "chip": BAD if o["owner_missing"] else None}, {"v": o["status"], "chip": {"compliant": GOOD, "partial": WARN, "exception": BAD}.get(o["status"], GREY)}, {"v": o.get("next_due") or "", "chip": BAD if o["overdue"] else None}] for o in need], note="An obligation needs an owner and a monthly statement. Owners attest from the Register tab.")]


def obl_reminders(db, today, horizon):
    h = horizon.isoformat() if hasattr(horizon, "isoformat") else horizon
    return [due_item("Obligation statement", o, "name", "next_due", "owner", "#/m/obligations_hub") for o in load(db, "obligations_hub", "obligation", today) if o.get("next_due") and o["next_due"] <= h and not o["owner_missing"]]


register("obligations_hub", {"perm": "obligations_hub", "title": "Obligations Hub", "crumb": "Compliance &amp; Privacy", "color": "#7C5CE0", "intro": "Every legal and regulatory obligation, who owns it, the evidence and the monthly status. Seeded from the 24 laws in Appendix II of the GRC Policy and the Cyber and Data Protection Act. An exception creates an action and, if the obligation is material, an incident.",
                             "tabs": [["overview", "Overview"], ["obligation", "Register"], ["statement", "Statements"]], "overview": obl_overview, "seed": obl_seed, "reminders": obl_reminders,
                             "entities": {"obligation": {"label": "Obligation", "plural": "Obligations", "prefix": "OBL", "title_field": "name", "colors": {"compliant": "good", "partial": "warn", "exception": "bad"}, "statuses": ["not assessed", "compliant", "partial", "exception"], "next": None, "columns": ["name", "regulator", "owner", "status", "next_due", "evidence"], "attest": obl_attest, "attest_label": "Monthly statement", "attest_who": "owner", "owner_field": "owner", "derive": obl_derive,
                                                       "attest_fields": [{"key": "status", "label": "My statement", "opts": ["compliant", "partial", "exception"]}, {"key": "comment", "label": "Comment or evidence (needed unless compliant)", "type": "textarea"}],
                                                       "fields": [F("name", "Obligation, Act or regulation", req=True), F("regulator", "Regulator"), F("citation", "Section or reference"), F("owner", "Owner (Head of Function)"), F("frequency", "Statement frequency", "select", opts=["Monthly", "Quarterly", "Annual", "Event-driven"], default="Monthly"), F("next_due", "Next statement due", "date"), F("material", "Material if breached", "bool"), F("evidence", "Evidence held", "textarea", wide=True), F("risk_id", "Linked risk", "risk"), F("notes", "Notes", "textarea", wide=True)]},
                                          "statement": {"label": "Statement", "plural": "Statements", "prefix": "STM", "title_field": "obligation", "readonly": True, "colors": {"compliant": "good", "partial": "warn", "exception": "bad"}, "statuses": ["compliant", "partial", "exception"], "next": None, "columns": ["obligation", "period", "status", "by", "comment"], "fields": [F("obligation", "Obligation"), F("period", "Month"), F("by", "By"), F("comment", "Comment", "textarea")]}}})


# =========================================================== Regulatory Change
def chg_derive(db, it, today):
    ed = pd(it.get("effective_date"))
    return {"overdue": bool(ed and ed < today and it["status"] != "closed"), "days_to_effective": (ed - today).days if ed else None, "updates_done": sum(1 for k in ("obligations_updated", "controls_updated", "policies_updated") if it.get(k))}


def chg_rule(db, c, it, new, note):
    if new == "closed":
        miss = [l for k, l in (("obligations_updated", "obligations"), ("controls_updated", "controls"), ("policies_updated", "policies")) if not it.get(k)]
        if miss or not it.get("attested_by"):
            raise HTTPError(409, "rule", "A change closes only when the %s are updated and the owner has attested. Still missing: %s." % ("obligations, controls and policies", ", ".join(miss + ([] if it.get("attested_by") else ["the owner's attestation"]))))


def chg_attest(db, c, it, body):
    if it["status"] not in ("assessed", "implementing"):
        raise HTTPError(409, "state", "The owner attests once the change is assessed and being implemented.")
    set_data(db, it["id"], attested_by=c.user["full_name"], attested_on=dbm.today().isoformat())
    return {"note": "owner attested"}


def chg_overview(db, c, today):
    ch = load(db, "regulatory_change", "change", today); n = len(ch); yr = today.year
    awaiting = [x for x in ch if x["status"] in ("new", "assessing")]; assessed = [x for x in ch if x["status"] in ("assessed", "implementing", "closed")]; gantt = []
    for x in ch:
        if x.get("effective_date") and x["status"] != "closed":
            s = pd(x.get("received_on")) or today; e = pd(x["effective_date"]); sm = s.month if s.year == yr else (1 if s.year < yr else 12); em = e.month if e.year == yr else (12 if e.year > yr else 1)
            gantt.append({"label": x["title"][:40], "start": min(sm, em), "end": max(sm, em), "color": BAD if x["overdue"] else BLUE, "tip": "effective " + x["effective_date"]})
    flow = [{"label": s, "value": sum(1 for x in ch if x["status"] == s)} for s in ("new", "assessing", "assessed", "implementing", "closed")]
    return [tiles(("Changes tracked", n), ("Assessed", len(assessed), "", GOOD), ("Awaiting assessment", len(awaiting), "", WARN if awaiting else GOOD), ("Overdue", sum(1 for x in ch if x["overdue"]), "effective date passed, not closed", BAD if any(x["overdue"] for x in ch) else GOOD)),
            panel("gantt", "Effective dates, %d" % yr, 7, items=gantt), panel("funnel", "Change-to-control flow", 5, items=flow),
            panel("table", "Regulatory change log", 12, cols=["Change", "Regulator", "Effective", "Impact", "Owner", "Status", "Updates done"], rows=[[{"v": x["title"][:70]}, x.get("regulator") or "", {"v": x.get("effective_date") or "", "chip": BAD if x["overdue"] else None}, {"v": x.get("impact") or "", "chip": {"High": BAD, "Medium": WARN, "Low": GOOD}.get(x.get("impact"))}, x.get("owner") or "", x["status"], "%d of 3" % x["updates_done"]] for x in ch[:25]], note="A change closes only when the obligations, controls and policies are updated and the owner attests.")]


def chg_reminders(db, today, horizon):
    h = horizon.isoformat()
    return [due_item("Regulatory change", x, "title", "effective_date", "owner", "#/m/regulatory_change") for x in load(db, "regulatory_change", "change", today) if x["status"] != "closed" and x.get("effective_date") and x["effective_date"] <= h]


register("regulatory_change", {"perm": "regulatory_change", "title": "Regulatory Change", "crumb": "Compliance &amp; Privacy", "color": "#7C5CE0", "intro": "Tracks new and changing regulation from notice to updated controls. Document Intelligence can log a change from a regulation or circular you upload.",
                               "tabs": [["overview", "Overview"], ["change", "Change log"]], "overview": chg_overview, "reminders": chg_reminders,
                               "entities": {"change": {"label": "Regulatory change", "plural": "Regulatory changes", "prefix": "RCH", "title_field": "title", "statuses": ["new", "assessing", "assessed", "implementing", "closed"], "next": {"new": ["assessing"], "assessing": ["assessed"], "assessed": ["implementing"], "implementing": ["closed", "assessed"], "closed": []}, "colors": {"closed": "good", "implementing": "warn", "new": "bad"},
                                                        "columns": ["title", "regulator", "effective_date", "impact", "owner", "status"], "derive": chg_derive, "status_rule": chg_rule, "attest": chg_attest, "attest_label": "Owner attests", "attest_who": "owner", "owner_field": "owner", "attest_fields": [],
                                                        "fields": [F("title", "Change", req=True), F("regulator", "Regulator"), F("reference", "Circular or reference"), F("received_on", "Received on", "date", default=lambda: dbm.today().isoformat()), F("effective_date", "Effective date", "date"), F("impact", "Impact", "select", opts=["Low", "Medium", "High"]), F("owner", "Owner"), F("summary", "What changes", "textarea", wide=True), F("obligations_ref", "Obligations affected"), F("policies_ref", "Policies affected"), F("controls_ref", "Controls affected"), F("obligations_updated", "Obligations updated", "bool"), F("controls_updated", "Controls updated", "bool"), F("policies_updated", "Policies updated", "bool"), F("notes", "Notes", "textarea", wide=True)]}}})

# =========================================================== Privacy & Breach Clock
BASIS = ["Consent", "Contract", "Legal obligation", "Vital interests", "Public task", "Legitimate interests"]


def breach_derive(db, it, today):
    now_h = harare_now(); out = {}
    try:
        aware = datetime.datetime.fromisoformat((it.get("aware_at") or "")[:16])
    except ValueError:
        return out
    for key, hrs, done, cond in (("potraz", 24, it.get("potraz_notice_at"), True), ("subjects", 72, it.get("subject_notice_at"), it.get("risk_to_subjects") == "High")):
        if not cond:
            out[key] = None; continue
        dl = aware + datetime.timedelta(hours=hrs); left = (dl - now_h).total_seconds() / 3600
        out[key] = {"deadline": dl.isoformat()[:16].replace("T", " "), "done": done, "hours_left": round(left, 1), "state": "sent" if done else ("overdue" if left < 0 else "due soon" if left < 6 else "open")}
    out["elapsed_hours"] = round((now_h - aware).total_seconds() / 3600, 1)
    return out


def breach_rule(db, c, it, new, note):
    if new == "closed":
        if not it.get("potraz_notice_at"):
            raise HTTPError(409, "rule", "Record the POTRAZ notice before closing: the 24-hour duty applies to every personal-data breach unless the DPO records why it does not.")
        if it.get("risk_to_subjects") == "High" and not it.get("subject_notice_at"):
            raise HTTPError(409, "rule", "The risk to data subjects is High: record the notice to data subjects (72 hours) before closing.")
    if new == "notified" and not (it.get("potraz_notice_at") or it.get("subject_notice_at")):
        raise HTTPError(409, "rule", "Generate and record a notice first (Notices).")


def breach_sync(db, c):
    """The clock starts when an incident is marked as a personal-data breach: every such incident gets a breach record, once."""
    have = {x.get("incident_id") for x in load(db, "privacy_breach_clock", "breach") if x.get("incident_id")}
    for r in db.execute("SELECT id, ref, title, detected_at, description, owner FROM incidents WHERE pdb=1 AND deleted_at IS NULL"):
        if r["id"] in have:
            continue
        try:
            aw = (datetime.datetime.fromisoformat(r["detected_at"].replace("Z", "")[:19]) + datetime.timedelta(hours=dbm.config.TZ_HOURS)).isoformat()[:16]
        except (ValueError, TypeError):
            aw = harare_now().isoformat()[:16]
        seed_item(db, "privacy_breach_clock", "breach", {"title": r["title"], "incident_id": r["id"], "incident_ref": r["ref"], "aware_at": aw, "risk_to_subjects": "Not assessed", "data_categories": "", "individuals": 0, "description": (r["description"] or "")[:600], "owner": r["owner"] or "DPO"}, "aware", "system")


def notice_text(it, kind):
    when = it.get("aware_at", "").replace("T", " ")
    if kind == "potraz":
        return ("To: Data Protection Authority (POTRAZ)\nSubject: Notification of a personal data breach (%s)\n\n1. What happened: %s\n2. When we became aware: %s (Harare time)\n3. Categories of personal data: %s\n4. Approximate number of people affected: %s\n5. Likely consequences for the people affected: %s\n6. Measures taken or proposed to address it and reduce harm: %s\n7. Contact: the Data Protection Officer, EcoCash.\n\nThis is a template for the DPO to review before sending. Confirm the content required by the Cyber and Data Protection Act [Chapter 12:07] and SI 155 of 2024."
                % (it["ref"], it.get("description") or it["title"], when, it.get("data_categories") or "to be completed", it.get("individuals") or "to be confirmed", it.get("consequences") or "to be completed", it.get("measures") or "to be completed"))
    return ("Subject: Important information about your personal data\n\nWe are writing to tell you about an incident that may affect your personal data.\n\nWhat happened: %s\nWhat information was involved: %s\nWhat we are doing about it: %s\nWhat you can do to protect yourself: change your PIN and password, be careful with calls or messages that ask for codes, and contact us on our usual customer line if you see anything unusual.\n\nWe are sorry. This is a template for the DPO to review before sending."
            % (it.get("description") or it["title"], it.get("data_categories") or "to be completed", it.get("measures") or "to be completed"))


def act_notice(db, c, body):
    from . import kit
    r, it = kit.one(db, "privacy_breach_clock", "breach", int(body.get("id") or 0)); kind = body.get("kind")
    if kind not in ("potraz", "subjects"):
        raise HTTPError(400, "validation", "Choose the POTRAZ notice or the notice to data subjects.")
    hist(db, it["id"], c.user["username"], "notice generated: " + kind, "from template"); res = {"text": notice_text(it, kind), "sent_recorded": False}
    if body.get("mark_sent"):
        set_data(db, it["id"], **{("potraz_notice_at" if kind == "potraz" else "subject_notice_at"): harare_now().isoformat()[:16]}); hist(db, it["id"], c.user["username"], "notice recorded as sent: " + kind, ""); res["sent_recorded"] = True
        if it["status"] in ("aware", "assessing"):
            set_status(db, it["id"], "notified")
    return res


def priv_overview(db, c, today):
    br = load(db, "privacy_breach_clock", "breach", today); pr = load(db, "privacy_breach_clock", "processing", today); dp = load(db, "privacy_breach_clock", "dpia", today); rq = load(db, "privacy_breach_clock", "request", today); lic = load(db, "privacy_breach_clock", "licence", today)
    active = [b for b in br if b["status"] != "closed"]; need_dpia = [p for p in pr if p.get("dpia_required")]; done = [p for p in need_dpia if not p["dpia_gap"]]; comp = sum(1 for p in pr if p["record_complete"]); op = [r for r in rq if r["status"] in ("received", "in progress", "extended")]; dd = [r["days_taken"] for r in rq if r.get("days_taken") is not None]
    mon = {}
    for b in br:
        k = (b.get("aware_at") or "")[:7]; mon[k] = mon.get(k, 0) + 1
    months = []
    d = today.replace(day=1)
    for i in range(11, -1, -1):
        m = add_months(d, -i).strftime("%Y-%m"); months.append({"label": m[2:], "value": mon.get(m, 0)})
    L = lic[0] if lic else None
    clk = [{"label": b["title"][:60] + " (%s)" % b["ref"], "sub": "aware %s, %s hours ago; risk to data subjects: %s" % ((b.get("aware_at") or "").replace("T", " "), b.get("elapsed_hours"), b.get("risk_to_subjects") or "not assessed"), "stages": [dict(label="POTRAZ notice (24 h)", **b["potraz"])] + ([dict(label="Data subjects (72 h)", **b["subjects"])] if b.get("subjects") else [])} for b in active if b.get("potraz")]
    return [tiles(("POTRAZ licence", (L or {}).get("status") or "not recorded", "expires %s" % ((L or {}).get("expires_on") or "n/a"), GOOD if (L or {}).get("status") == "Registered" else WARN), ("DPIAs complete", "%d of %d" % (len(done), len(need_dpia)), "of those required", TEAL), ("Processing records", "%s%%" % (pct(comp, len(pr)) or 0), "%d of %d complete" % (comp, len(pr)), BLUE), ("Subject requests open", len(op), "average %s days to complete" % (("%g" % round(sum(dd) / len(dd), 1)) if dd else "n/a"), PURPLE)),
            panel("clock", "Active breaches: notice deadlines", 12, items=clk, empty="No breach is open. A breach appears here the moment an incident is marked as a personal-data breach."), panel("columns", "Breaches per month, last 12 months", 6, items=months),
            panel("table", "Processing activities", 6, cols=["System", "Data", "Lawful basis", "DPIA", "Owner"], rows=[[{"v": p["system"][:30]}, (p.get("data") or "")[:40], p.get("lawful_basis") or "", {"v": "gap" if p["dpia_gap"] else ("yes" if p.get("dpia_required") else "not needed"), "chip": BAD if p["dpia_gap"] else None}, p.get("owner") or ""] for p in pr[:12]], note="A record needs the system, the data, the lawful basis and an owner."),
            panel("table", "Breach history", 12, cols=["Breach", "Aware", "Risk to subjects", "POTRAZ notice", "Status"], rows=[[{"v": b["title"][:60]}, (b.get("aware_at") or "").replace("T", " "), b.get("risk_to_subjects") or "", (b.get("potraz_notice_at") or "not recorded").replace("T", " "), b["status"]] for b in br[:15]])]


def proc_derive(db, it, today):
    ok = bool((it.get("system") or "").strip() and (it.get("data") or "").strip() and it.get("lawful_basis") and (it.get("owner") or "").strip())
    gap = False
    if it.get("dpia_required"):
        name = (it.get("system") or "").lower(); gap = not any(d["status"] == "Complete" and name and (name in (d.get("activity") or "").lower() or (d.get("activity") or "").lower() in name) for d in load(db, "privacy_breach_clock", "dpia", today))
    return {"record_complete": ok, "dpia_gap": gap}


def req_derive(db, it, today):
    r = pd(it.get("received_on")); due = pd(it.get("due_on")); done = pd(it.get("completed_on"))
    return {"days_taken": (done - r).days if r and done else None, "overdue": bool(due and not done and due < today and it["status"] in ("received", "in progress", "extended")), "days_open": (today - r).days if r and not done else None}


def req_validate(db, c, data, old):
    if data.get("received_on") and not data.get("due_on"):
        data["due_on"] = (pd(data["received_on"]) + datetime.timedelta(days=30)).isoformat()  # proposed 30 days: the DPO confirms the legal period


def priv_reminders(db, today, horizon):
    out = [due_item("Breach notice", b, "title", "_dl", "owner", "#/m/privacy_breach_clock") for b in []]
    for b in load(db, "privacy_breach_clock", "breach", today):
        if b["status"] != "closed" and b.get("potraz") and not b["potraz"]["done"]:
            out.append({"kind": "Breach notice (POTRAZ, 24 h)", "ref": b["ref"], "title": b["title"][:100], "due": b["potraz"]["deadline"][:10], "owner_text": b.get("owner") or "DPO", "owner_id": None, "level": None, "url": "#/m/privacy_breach_clock"})
    h = horizon.isoformat()
    out += [due_item("Subject request", r, "type", "due_on", "owner", "#/m/privacy_breach_clock") for r in load(db, "privacy_breach_clock", "request", today) if r["status"] in ("received", "in progress", "extended") and r.get("due_on") and r["due_on"] <= h]
    return out


def priv_seed(db):
    seed_item(db, "privacy_breach_clock", "licence", {"title": "POTRAZ data controller licence", "licence_no": "", "registered_on": "", "expires_on": ""}, "Not recorded")


register("privacy_breach_clock", {"perm": "privacy_breach_clock", "title": "Privacy & Breach Clock", "crumb": "Compliance &amp; Privacy", "color": "#7C5CE0", "intro": "Meets data-protection duties: the 24-hour notice to POTRAZ, the 72-hour notice to data subjects when the risk is high, DPIAs, processing records and subject requests. The clock starts when an incident is marked as a personal-data breach (Incidents &amp; Losses). Notices are generated from templates for the DPO to review; they are not sent by Sentinel.",
                                 "tabs": [["overview", "Clock and coverage"], ["breach", "Breaches"], ["processing", "Processing records"], ["dpia", "DPIAs"], ["request", "Subject requests"], ["licence", "Licence"]], "overview": priv_overview, "sync": breach_sync, "seed": priv_seed, "reminders": priv_reminders,
                                 "actions": [{"id": "notice", "label": "Generate a notice", "needs": "edit", "run": act_notice}],
                                 "entities": {"breach": {"label": "Breach", "plural": "Breaches", "prefix": "BRC", "title_field": "title", "statuses": ["aware", "assessing", "notified", "closed"], "next": {"aware": ["assessing", "notified"], "assessing": ["notified"], "notified": ["closed"], "closed": []}, "colors": {"closed": "good", "notified": "warn", "aware": "bad", "assessing": "bad"}, "columns": ["title", "aware_at", "risk_to_subjects", "potraz_notice_at", "status"], "derive": breach_derive, "status_rule": breach_rule,
                                                        "fields": [F("title", "Breach", req=True), F("incident_ref", "Incident"), F("aware_at", "Became aware (Harare time)", "datetime", req=True), F("risk_to_subjects", "Risk to data subjects", "select", opts=["Not assessed", "Low", "Medium", "High"], default="Not assessed"), F("data_categories", "Categories of personal data"), F("individuals", "People affected (approximate)", "number"), F("description", "What happened", "textarea", wide=True), F("consequences", "Likely consequences", "textarea", wide=True), F("measures", "Measures taken", "textarea", wide=True), F("potraz_notice_at", "POTRAZ notified at", "datetime"), F("subject_notice_at", "Data subjects notified at", "datetime"), F("owner", "Owner", default="DPO")]},
                                              "processing": {"label": "Processing activity", "plural": "Processing records", "prefix": "PRC", "title_field": "system", "statuses": ["active"], "next": None, "columns": ["system", "data", "lawful_basis", "dpia_required", "owner"], "derive": proc_derive, "fields": [F("system", "System or activity", req=True), F("data", "Personal data held", req=True), F("lawful_basis", "Lawful basis", "select", opts=BASIS), F("purpose", "Purpose"), F("dpia_required", "DPIA required", "bool"), F("owner", "Owner"), F("retention", "Retention period"), F("transfer_abroad", "Transferred outside Zimbabwe (ss.28-29)", "bool"), F("processor", "Processor or recipient"), F("notes", "Notes", "textarea", wide=True)]},
                                              "dpia": {"label": "DPIA", "plural": "DPIAs", "prefix": "DPI", "title_field": "activity", "statuses": ["Planned", "In progress", "Complete", "Not required"], "next": None, "colors": {"Complete": "good", "In progress": "warn", "Planned": "bad"}, "columns": ["activity", "status", "risk_level", "completed_on", "owner"], "fields": [F("activity", "System or activity assessed", req=True), F("risk_level", "Residual risk", "select", opts=["Low", "Medium", "High"]), F("completed_on", "Completed on", "date"), F("next_review", "Next review", "date"), F("owner", "Owner"), F("notes", "Findings", "textarea", wide=True)]},
                                              "request": {"label": "Subject request", "plural": "Subject requests", "prefix": "DSR", "title_field": "type", "statuses": ["received", "in progress", "extended", "completed", "refused"], "next": None, "colors": {"completed": "good", "refused": "warn"}, "columns": ["type", "received_on", "due_on", "completed_on", "status"], "derive": req_derive, "validate": req_validate, "fields": [F("type", "Request", "select", req=True, opts=["Access", "Correction", "Deletion", "Objection", "Portability", "Other"]), F("received_on", "Received on", "date", req=True, default=lambda: dbm.today().isoformat()), F("due_on", "Due on (30 days proposed)", "date"), F("completed_on", "Completed on", "date"), F("owner", "Owner"), F("notes", "Notes (no personal details)", "textarea", wide=True)]},
                                              "licence": {"label": "Licence", "plural": "Licence", "prefix": "LIC", "title_field": "title", "statuses": ["Not recorded", "Applied", "Registered", "Expired", "Not required"], "next": None, "colors": {"Registered": "good", "Expired": "bad"}, "columns": ["title", "licence_no", "status", "expires_on"], "fields": [F("title", "Licence", req=True), F("licence_no", "Licence number"), F("registered_on", "Registered on", "date"), F("expires_on", "Expires on", "date")]}}})

# =========================================================== Policy Hub
def pol_derive(db, it, today):
    nr = pd(it.get("next_review")); users = db.execute("SELECT COUNT(*) n FROM users WHERE status='active' AND deleted_at IS NULL").fetchone()["n"]
    att = db.execute("SELECT COUNT(DISTINCT json_extract(data,'$.username')) n FROM kit_items WHERE module='policy_hub' AND entity='attestation' AND deleted_at IS NULL AND json_extract(data,'$.policy_id')=? AND json_extract(data,'$.version')=?", (it["id"], it.get("version"))).fetchone()["n"]
    pols = {p["ref"]: p for p in [dict(ref=r["ref"], status=r["status"]) for r in db.execute("SELECT ref, status FROM kit_items WHERE module='policy_hub' AND entity='policy' AND deleted_at IS NULL")]}
    refs = [t for t in re.findall(r"POL-\d{4}", it.get("crossrefs") or "")] if True else []
    broken = [r for r in refs if r not in pols or pols[r]["status"] == "retired"]
    return {"due_for_review": bool(it["status"] != "retired" and ((nr and nr <= today) or it["status"] == "under review" or not nr)), "attested": att, "staff": users, "attest_pct": pct(att, users), "broken_refs": broken, "campaign_open": bool(it.get("campaign_due"))}


def pol_validate(db, c, d, old):
    if d.get("approved_on") and not d.get("next_review"):
        d["next_review"] = add_months(pd(d["approved_on"]), 12).isoformat()


def pol_rule(db, c, it, new, note):
    if new == "current" and not it.get("approved_on"):
        raise HTTPError(409, "rule", "Record the approval date before a policy is made current.")


def pol_attest(db, c, it, body):
    if it["status"] != "current" or not it.get("campaign_due"):
        raise HTTPError(409, "state", "No attestation campaign is open for this policy.")
    if db.execute("SELECT 1 FROM kit_items WHERE module='policy_hub' AND entity='attestation' AND deleted_at IS NULL AND json_extract(data,'$.policy_id')=? AND json_extract(data,'$.version')=? AND json_extract(data,'$.username')=?", (it["id"], it.get("version"), c.user["username"])).fetchone():
        return {"note": "already attested"}
    seed_item(db, "policy_hub", "attestation", {"policy_id": it["id"], "policy": it["title"], "version": it.get("version"), "username": c.user["username"], "full_name": c.user["full_name"], "at": now()}, "attested", c.user["username"])
    return {"note": "attested version %s" % it.get("version")}


def act_campaign(db, c, body):
    from . import kit
    r, it = kit.one(db, "policy_hub", "policy", int(body.get("id") or 0)); due = str(body.get("due") or "")[:10]
    if it["status"] != "current" or not due or due < dbm.today().isoformat():
        raise HTTPError(400, "validation", "A campaign needs a current policy and a due date in the future.")
    set_data(db, it["id"], campaign_due=due, campaign_started=now()); n = 0; base = (body.get("base_url") or "").rstrip("/")
    for u in db.execute("SELECT email FROM users WHERE status='active' AND deleted_at IS NULL AND email IS NOT NULL AND email != '' LIMIT 500"):
        outbox(db, u["email"], "Please read and attest: %s" % it["title"], "Please read the policy '%s' (version %s) and attest in Sentinel (Policy Hub) by %s.%s" % (it["title"], it.get("version"), due, (" " + base + "/app#/m/policy_hub") if base else ""), "policy"); n += 1
    hist(db, it["id"], c.user["username"], "attestation campaign opened", "due %s, %d people asked" % (due, n))
    return {"asked": n}


def pol_overview(db, c, today):
    ps = [p for p in load(db, "policy_hub", "policy", today) if p["status"] != "retired"]; n = len(ps); rev = [p for p in ps if not p["due_for_review"]]; cur = [p for p in ps if p["status"] == "current"]
    ap = [p for p in cur if p["campaign_open"]]; tot_a = sum(p["attested"] for p in ap); tot_s = sum(p["staff"] for p in ap)
    return [tiles(("Policies", n), ("Reviewed within 12 months", len(rev), "%s%%" % (pct(len(rev), n) or 0), GOOD), ("Attested", "%s%%" % (pct(tot_a, tot_s) if tot_s else 0), "across open campaigns", TEAL), ("Due or overdue for review", n - len(rev), "", BAD if n - len(rev) else GOOD)),
            panel("donut", "Policy status", 4, items=[{"label": "Current", "value": len(rev), "color": GOOD}, {"label": "Due for review", "value": n - len(rev), "color": BAD}], center="policies"),
            panel("bars", "Attestation: staff who have attested", 8, items=[{"label": p["title"][:40], "value": p["attest_pct"] or 0, "text": "%d of %d" % (p["attested"], p["staff"]), "color": TEAL} for p in ap] or [], empty="No attestation campaign is open. Open one from a policy."),
            panel("table", "Policy library", 12, cols=["Policy", "Version", "Owner", "Next review", "Attestation", "Cross-references"], rows=[[{"v": p["title"][:60]}, p.get("version") or "", p.get("owner") or "", {"v": p.get("next_review") or "SET A DATE", "chip": BAD if p["due_for_review"] else None}, ("%d%%" % p["attest_pct"]) if p["campaign_open"] and p["attest_pct"] is not None else "", {"v": ("broken: " + ", ".join(p["broken_refs"])) if p["broken_refs"] else "ok", "chip": BAD if p["broken_refs"] else None}] for p in ps[:25]], note="Each policy is reviewed annually (the owner is reminded by e-mail). Cross-references are checked automatically.")]


def pol_reminders(db, today, horizon):
    h = horizon.isoformat()
    return [due_item("Policy review", p, "title", "next_review", "owner", "#/m/policy_hub") for p in load(db, "policy_hub", "policy", today) if p["status"] != "retired" and p.get("next_review") and p["next_review"] <= h]


def pol_seed(db):
    seed_item(db, "policy_hub", "policy", {"title": "Governance, Risk and Compliance (GRC) Policy", "owner": "Head of Risk", "version": "1.0", "approved_on": "", "next_review": "", "document_ref": "EcoCash Private Limited GRC Policy", "obligations_ref": "Appendix II", "notes": "Seeded from the uploaded GRC Policy. Record the approval date and the next review."}, "current")


import re  # noqa: E402
register("policy_hub", {"perm": "policy_hub", "title": "Policy Hub", "crumb": "Compliance &amp; Privacy", "color": "#7C5CE0", "intro": "Policies with versions, annual reviews, attestation campaigns and links to the obligations and controls they support.", "tabs": [["overview", "Overview"], ["policy", "Policy library"], ["attestation", "Attestations"]], "overview": pol_overview, "seed": pol_seed, "reminders": pol_reminders,
                        "actions": [{"id": "campaign", "label": "Open an attestation campaign", "needs": "edit", "run": act_campaign}],
                        "entities": {"policy": {"label": "Policy", "plural": "Policies", "prefix": "POL", "title_field": "title", "statuses": ["draft", "current", "under review", "retired"], "next": {"draft": ["current"], "current": ["under review", "retired"], "under review": ["current", "retired"], "retired": []}, "colors": {"current": "good", "under review": "warn", "draft": "bad"}, "columns": ["title", "version", "owner", "status", "next_review"], "derive": pol_derive, "validate": pol_validate, "status_rule": pol_rule, "attest": pol_attest, "attest_who": "any", "attest_label": "I have read and attest", "attest_fields": [],
                                              "fields": [F("title", "Policy", req=True), F("owner", "Owner", req=True), F("version", "Version", default="1.0"), F("approved_on", "Approved on", "date"), F("next_review", "Next review (12 months after approval)", "date"), F("document_ref", "Document"), F("obligations_ref", "Obligations it supports"), F("risks_ref", "Risks it supports"), F("controls_ref", "Controls it supports"), F("crossrefs", "Refers to policies (POL-0001, ...)"), F("notes", "Notes", "textarea", wide=True)]},
                                 "attestation": {"label": "Attestation", "plural": "Attestations", "prefix": "ATT", "title_field": "policy", "readonly": True, "statuses": ["attested"], "next": None, "columns": ["policy", "version", "full_name", "at"], "fields": [F("policy", "Policy"), F("version", "Version"), F("full_name", "Staff member"), F("at", "When")]}}})
