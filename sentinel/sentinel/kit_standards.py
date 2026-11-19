"""Management-system modules on the kit: Standards Hub (ISO/IEC 27001, ISO 22301, ISO/IEC 42001 side by side), and the ISMS, BCMS and AIMS workspaces, which read the hub's records for their own standard."""
import datetime
import json
import re

from . import db as dbm, kit, xlsxbook
from .core import now
from .kit import (F, GOOD, WARN, BAD, BLUE, GREY, PURPLE, TEAL, SYS, hist, load, make_action, panel, pct, pd, register, seed_item, set_data, set_status, tiles, due_item)
from .web import HTTPError

S27, S22, S42 = "ISO/IEC 27001:2022", "ISO 22301:2019", "ISO/IEC 42001:2023"
STDS = [S27, S22, S42]
SHORT = {S27: "ISMS", S22: "BCMS", S42: "AIMS"}
COMMON = [("4.1", "Understanding the organization and its context"), ("4.2", "Understanding the needs and expectations of interested parties"), ("4.3", "Determining the scope of the management system"), ("4.4", "The management system"), ("5.1", "Leadership and commitment"), ("5.2", "Policy"), ("5.3", "Organizational roles, responsibilities and authorities"), ("6.1", "Actions to address risks and opportunities"), ("6.2", "Objectives and planning to achieve them"), ("6.3", "Planning of changes"),
          ("7.1", "Resources"), ("7.2", "Competence"), ("7.3", "Awareness"), ("7.4", "Communication"), ("7.5", "Documented information"), ("9.1", "Monitoring, measurement, analysis and evaluation"), ("9.2", "Internal audit"), ("9.3", "Management review")]
OPS = {S27: [("8.1", "Operational planning and control"), ("8.2", "Information security risk assessment"), ("8.3", "Information security risk treatment")], S22: [("8.1", "Operational planning and control"), ("8.2", "Business impact analysis and risk assessment"), ("8.3", "Business continuity strategies and solutions"), ("8.4", "Business continuity plans and procedures"), ("8.5", "Exercise programme")], S42: [("8.1", "Operational planning and control"), ("8.2", "AI risk assessment"), ("8.3", "AI risk treatment"), ("8.4", "AI system impact assessment")]}
IMPR = {S27: [("10.1", "Continual improvement"), ("10.2", "Nonconformity and corrective action")], S22: [("10.1", "Nonconformity and corrective action"), ("10.2", "Continual improvement")], S42: [("10.1", "Continual improvement"), ("10.2", "Nonconformity and corrective action")]}
A27 = """5.1 Policies for information security|5.2 Information security roles and responsibilities|5.3 Segregation of duties|5.4 Management responsibilities|5.5 Contact with authorities|5.6 Contact with special interest groups|5.7 Threat intelligence|5.8 Information security in project management|5.9 Inventory of information and other associated assets|5.10 Acceptable use of information and other associated assets|5.11 Return of assets|5.12 Classification of information|5.13 Labelling of information|5.14 Information transfer|5.15 Access control|5.16 Identity management|5.17 Authentication information|5.18 Access rights|5.19 Information security in supplier relationships|5.20 Addressing information security within supplier agreements|5.21 Managing information security in the ICT supply chain|5.22 Monitoring, review and change management of supplier services|5.23 Information security for use of cloud services|5.24 Information security incident management planning and preparation|5.25 Assessment and decision on information security events|5.26 Response to information security incidents|5.27 Learning from information security incidents|5.28 Collection of evidence|5.29 Information security during disruption|5.30 ICT readiness for business continuity|5.31 Legal, statutory, regulatory and contractual requirements|5.32 Intellectual property rights|5.33 Protection of records|5.34 Privacy and protection of PII|5.35 Independent review of information security|5.36 Compliance with policies, rules and standards for information security|5.37 Documented operating procedures
6.1 Screening|6.2 Terms and conditions of employment|6.3 Information security awareness, education and training|6.4 Disciplinary process|6.5 Responsibilities after termination or change of employment|6.6 Confidentiality or non-disclosure agreements|6.7 Remote working|6.8 Information security event reporting
7.1 Physical security perimeters|7.2 Physical entry|7.3 Securing offices, rooms and facilities|7.4 Physical security monitoring|7.5 Protecting against physical and environmental threats|7.6 Working in secure areas|7.7 Clear desk and clear screen|7.8 Equipment siting and protection|7.9 Security of assets off-premises|7.10 Storage media|7.11 Supporting utilities|7.12 Cabling security|7.13 Equipment maintenance|7.14 Secure disposal or re-use of equipment
8.1 User endpoint devices|8.2 Privileged access rights|8.3 Information access restriction|8.4 Access to source code|8.5 Secure authentication|8.6 Capacity management|8.7 Protection against malware|8.8 Management of technical vulnerabilities|8.9 Configuration management|8.10 Information deletion|8.11 Data masking|8.12 Data leakage prevention|8.13 Information backup|8.14 Redundancy of information processing facilities|8.15 Logging|8.16 Monitoring activities|8.17 Clock synchronization|8.18 Use of privileged utility programs|8.19 Installation of software on operational systems|8.20 Networks security|8.21 Security of network services|8.22 Segregation of networks|8.23 Web filtering|8.24 Use of cryptography|8.25 Secure development life cycle|8.26 Application security requirements|8.27 Secure system architecture and engineering principles|8.28 Secure coding|8.29 Security testing in development and acceptance|8.30 Outsourced development|8.31 Separation of development, test and production environments|8.32 Change management|8.33 Test information|8.34 Protection of information systems during audit testing"""
THEME27 = {"5": "Organizational", "6": "People", "7": "Physical", "8": "Technological"}
A42 = """A.2.2 AI policy|A.2.3 Alignment with other organizational policies|A.2.4 Review of the AI policy|A.3.2 AI roles and responsibilities|A.3.3 Reporting of concerns|A.4.2 Resource documentation|A.4.3 Data resources|A.4.4 Tooling resources|A.4.5 System and computing resources|A.4.6 Human resources|A.5.2 AI system impact assessment process|A.5.3 Documentation of AI system impact assessments|A.5.4 Assessing AI system impact on individuals or groups of individuals|A.5.5 Assessing societal impacts of AI systems|A.6.1.2 Objectives for responsible development of AI system|A.6.1.3 Processes for responsible AI system design and development|A.6.2.2 AI system requirements and specification|A.6.2.3 Documentation of AI system design and development|A.6.2.4 AI system verification and validation|A.6.2.5 AI system deployment|A.6.2.6 AI system operation and monitoring|A.6.2.7 AI system technical documentation|A.6.2.8 AI system recording of event logs|A.7.2 Data for development and enhancement of AI system|A.7.3 Acquisition of data|A.7.4 Quality of data for AI systems|A.7.5 Data provenance|A.7.6 Data preparation|A.8.2 System documentation and information for users|A.8.3 External reporting|A.8.4 Communication of incidents|A.8.5 Information for interested parties|A.9.2 Processes for responsible use of AI systems|A.9.3 Objectives for responsible use of AI system|A.9.4 Intended use of the AI system|A.10.2 Allocating responsibilities|A.10.3 Suppliers|A.10.4 Customers"""
AREA42 = {"2": "A.2 Policies related to AI", "3": "A.3 Internal organization", "4": "A.4 Resources for AI systems", "5": "A.5 Assessing impacts of AI systems", "6": "A.6 AI system life cycle", "7": "A.7 Data for AI systems", "8": "A.8 Information for interested parties", "9": "A.9 Use of AI systems", "10": "A.10 Third-party and customer relationships"}
AI_THEMES = ["Accountability", "AI expertise", "Availability and quality of training data", "Environmental impact", "Fairness", "Maintainability", "Privacy", "Robustness", "Safety", "Security", "Transparency and explainability"]  # ISO/IEC 42001 Annex C objectives


def clause_list(std):
    return COMMON[:15] + OPS[std] + COMMON[15:] + IMPR[std]


def controls27():
    return [(x.split(" ", 1)[0], x.split(" ", 1)[1], THEME27[x[0]]) for blk in A27.split("\n") for x in blk.split("|")]


def controls42():
    return [(x.split(" ", 1)[0], x.split(" ", 1)[1], AREA42[x.split(" ", 1)[0].split(".")[1]]) for x in A42.split("|")]


def seed(db):
    for std in STDS:
        for n, t in clause_list(std):
            seed_item(db, "standards_hub", "clause", {"standard": std, "clause": n, "title": t, "evidence": "", "owner": ""}, "not started")
    for cid, t, th in controls27():
        seed_item(db, "standards_hub", "control", {"standard": S27, "control_id": cid, "title": t, "theme": th, "justification": "", "owner": "", "evidence": ""}, "not implemented")
    for cid, t, th in controls42():
        seed_item(db, "standards_hub", "control", {"standard": S42, "control_id": cid, "title": t, "theme": th, "justification": "", "owner": "", "evidence": ""}, "not implemented")
    seed_item(db, "standards_hub", "ai_system", {"standard": S42, "name": "Sentinel Copilot: built-in engine", "purpose": "Answers questions, summarises documents and drafts risks and ratings for a named person to accept or reject.", "risk_rating": "Medium", "impact_assessment": "In progress", "human_oversight": "A named reviewer accepts, edits or rejects every draft; nothing is written without that decision.", "owner": "Head of Risk", "vendor": "Built in (runs on this computer)", "risk_themes": "Accountability, Fairness, Transparency and explainability", "accuracy": "", "drift_index": "", "notes": "The platform's own AI features are registered here. Complete the impact assessment, then move it to live."}, "testing")
    seed_item(db, "standards_hub", "ai_system", {"standard": S42, "name": "Sentinel Copilot: Claude (optional)", "purpose": "Optional generative engine for open-ended reasoning, switched on only by a System Administrator.", "risk_rating": "Medium", "impact_assessment": "Not started", "human_oversight": "Same decision rule; personal data is redacted before text is sent; an approved hosting is required.", "owner": "Head of Risk", "vendor": "Anthropic (external)", "risk_themes": "Privacy, Security, Accountability", "notes": "Not in use until a System Administrator approves the hosting."}, "idea")


# ---- rules
def clause_rule(db, c, it, new, note):
    if new == "conformant" and not (it.get("evidence") or "").strip():
        raise HTTPError(409, "rule", "Record the evidence before a clause is marked conformant.")


def control_rule(db, c, it, new, note):
    if new == "not applicable" and not (it.get("justification") or "").strip():
        raise HTTPError(409, "rule", "A control that does not apply needs a written justification (it goes into the Statement of Applicability).")
    if new == "implemented" and not (it.get("evidence") or "").strip():
        raise HTTPError(409, "rule", "Record the evidence before a control is marked implemented.")


def nc_after(db, c, it, event, old):
    if event != "create":
        return
    sev = it.get("severity"); upd = {"action_ref": make_action(db, c, "Nonconformity %s (%s): %s" % (it["ref"], SHORT.get(it.get("standard"), ""), (it.get("description") or "")[:80]), it.get("corrective_action") or it.get("description") or "", it.get("owner") or "Head of Risk", 30 if sev == "Major" else 60)}
    if it.get("control_id") and sev in ("Major", "Minor"):  # a nonconformity may lower a linked control's rating
        k = db.execute("SELECT id, ice FROM risk_controls WHERE id=?", (int(it["control_id"]),)).fetchone()
        if k and k["ice"] is not None:
            new = min(1.0, k["ice"] + (0.2 if sev == "Major" else 0.1)); db.execute("UPDATE risk_controls SET ice_prev=ice, ice=? WHERE id=?", (new, k["id"])); upd["control_lowered"] = "effectiveness %d%% to %d%%" % (round((1 - k["ice"]) * 100), round((1 - new) * 100))
    set_data(db, it["id"], **upd); hist(db, it["id"], c.user["username"], "action created", upd["action_ref"] + ("; control " + upd["control_lowered"] if upd.get("control_lowered") else ""))


def nc_rule(db, c, it, new, note):
    if new == "verified" and not (it.get("corrective_action") or "").strip():
        raise HTTPError(409, "rule", "Record the corrective action taken before it is verified.")


def ai_rule(db, c, it, new, note):
    if new == "live":
        miss = [l for k, l, ok in (("owner", "an owner", bool((it.get("owner") or "").strip())), ("risk_rating", "a risk rating", bool(it.get("risk_rating"))), ("impact_assessment", "a completed impact assessment", it.get("impact_assessment") == "Complete"), ("human_oversight", "defined human oversight", bool((it.get("human_oversight") or "").strip()))) if not ok]
        if miss:
            raise HTTPError(409, "rule", "No AI system goes live without %s. Missing: %s." % ("an owner, a risk rating, an impact assessment and defined human oversight", ", ".join(miss)))


def ai_derive(db, it, today):
    return {"board_review": bool(it.get("risk_rating") == "High" or it.get("fairness_failed"))}


def nc_derive(db, it, today):
    d = pd(it.get("due")); return {"overdue": bool(d and d < today and it["status"] in ("open", "action in progress"))}


def audit_derive(db, it, today):
    d = pd(it.get("planned_on")); return {"overdue": bool(d and d < today and it["status"] == "planned")}


def act_soa(db, c, body):
    ctl = [x for x in load(db, "standards_hub", "control") if x["standard"] == S27]; v = 1 + len(load(db, "standards_hub", "soa")); rows = [[x["control_id"], x["title"], x["theme"], "no" if x["status"] == "not applicable" else "yes", x["status"], x.get("justification") or "", x.get("owner") or ""] for x in sorted(ctl, key=lambda z: [int(p) for p in z["control_id"].split(".")])]
    seed_item(db, "standards_hub", "soa", {"version": v, "standard": S27, "generated_by": c.user["full_name"], "generated_at": now(), "controls": len(rows), "implemented": sum(1 for r in rows if r[4] == "implemented"), "not_applicable": sum(1 for r in rows if r[4] == "not applicable"), "rows": rows}, "issued", c.user["username"])
    return {"version": v, "controls": len(rows)}


def dl_soa(db, c):
    ctl = sorted([x for x in load(db, "standards_hub", "control") if x["standard"] == S27], key=lambda z: [int(p) for p in z["control_id"].split(".")]); v = len(load(db, "standards_hub", "soa"))
    rows = [[(h, 1) for h in ("Control", "Title", "Theme", "Applicable", "Status", "Justification", "Owner", "Evidence")]] + [[x["control_id"], x["title"], x["theme"], "no" if x["status"] == "not applicable" else "yes", x["status"], x.get("justification") or "", x.get("owner") or "", x.get("evidence") or ""] for x in ctl]
    return xlsxbook.write([("Statement of Applicability", [[("Statement of Applicability: ISO/IEC 27001:2022 Annex A", 3)], [("Version %d, generated %s" % (v + 1, now()), 4)], []] + rows, [10, 60, 16, 11, 16, 50, 22, 40])]), "Sentinel_Statement_of_Applicability.xlsx"


def group_of(clause):
    return clause.split(".")[0]


def conformance(db, std=None):
    cl = load(db, "standards_hub", "clause"); out = {}
    for x in cl:
        if std and x["standard"] != std:
            continue
        g = out.setdefault((x["standard"], group_of(x["clause"])), [0, 0]); 
        if x["status"] != "not applicable":
            g[1] += 1; g[0] += 1 if x["status"] == "conformant" else 0
    return out


def dl_review(db, c):
    cl = load(db, "standards_hub", "clause"); nc = load(db, "standards_hub", "nonconformity"); au = load(db, "standards_hub", "audit"); s1 = [[("Management review pack", 3)], [("Generated %s by %s" % (now(), c.user["full_name"]), 4)], [], [(h, 1) for h in ("Standard", "Clause group", "Applicable clauses", "Conformant", "Conformance %")]]
    for (std, g), (a, b) in sorted(conformance(db).items()):
        s1.append([std, g, b, a, round(100.0 * a / b) if b else ""])
    s2 = [[("Nonconformities", 3)], [], [(h, 1) for h in ("Ref", "Standard", "Clause", "Severity", "Status", "Due", "Action", "Description")]] + [[x["ref"], x["standard"], x.get("clause") or "", x.get("severity"), x["status"], x.get("due") or "", x.get("action_ref") or "", x.get("description") or ""] for x in nc]
    s3 = [[("Audits and reviews", 3)], [], [(h, 1) for h in ("Standard", "Type", "Planned", "Status", "Result")]] + [[x["standard"], x.get("type"), x.get("planned_on"), x["status"], x.get("result") or ""] for x in au]
    return xlsxbook.write([("Conformance", s1, [24, 14, 18, 12, 14]), ("Nonconformities", s2, [12, 24, 10, 12, 20, 12, 14, 60]), ("Audits", s3, [24, 22, 14, 12, 50])]), "Sentinel_management_review_pack.xlsx"


def risks_by_standard(db, c):
    try:
        from . import analytics, matrix as mx
        rows, _ = analytics.risk_rows(db, c)
    except Exception:
        return {}
    out = {}
    for r in rows:
        std = S27 if r.get("system") == "ISMS" else S22 if r.get("system") == "BCMS" else (S42 if (r.get("category") or "") == "Model / AI" else None)
        if std and r.get("res_l"):
            out.setdefault(std, {"Low": 0, "Medium": 0, "Significant": 0, "High": 0})[mx.level(mx.rank(r["res_l"], r["res_c"]))] += 1
    return out


def hub_overview(db, c, today):
    cl = load(db, "standards_hub", "clause"); nc = load(db, "standards_hub", "nonconformity", today); au = load(db, "standards_hub", "audit", today); conf = conformance(db); groups = ["4", "5", "6", "7", "8", "9", "10"]
    ap = [x for x in cl if x["status"] != "not applicable"]; cf = sum(1 for x in ap if x["status"] == "conformant"); opn = [x for x in nc if x["status"] != "closed"]
    heat = [[(round(100.0 * conf[(s, g)][0] / conf[(s, g)][1]) if conf.get((s, g)) and conf[(s, g)][1] else None) for g in groups] for s in STDS]
    rs = risks_by_standard(db, c); gantt = []
    for a in au:
        if a.get("planned_on") and a["planned_on"][:4] == str(today.year):
            m = int(a["planned_on"][5:7]); gantt.append({"label": "%s: %s" % (SHORT[a["standard"]], a.get("type")), "start": m, "end": m, "color": GOOD if a["status"] == "done" else (BAD if a["overdue"] else BLUE), "tip": a["planned_on"]})
    ncs = {}
    for x in nc:
        ncs[x["status"]] = ncs.get(x["status"], 0) + 1
    return [tiles(("Standards in scope", 3, ", ".join(SHORT[s] for s in STDS), PURPLE), ("Clause conformance", "%s%%" % (pct(cf, len(ap)) or 0), "%d of %d applicable clauses" % (cf, len(ap)), GOOD), ("Open nonconformities", len(opn), "%d overdue" % sum(1 for x in opn if x["overdue"]), BAD if opn else GOOD), ("Audits and reviews", "%d of %d" % (sum(1 for a in au if a["status"] == "done"), len(au)), "done of planned", BLUE)),
            panel("heat", "Clause conformance by standard (clauses 4 to 10)", 12, rows=[SHORT[s] + " " + s.split(" ")[-1] for s in STDS], cols=["Clause " + g for g in groups], cells=heat, note="Conformance is the share of applicable clauses marked conformant with evidence. A grey cell has no clause marked yet."),
            panel("stack", "Risks by standard, by residual level", 6, items=[{"label": SHORT[s], "parts": [{"key": k, "value": v, "color": col} for (k, v), col in zip(rs.get(s, {"Low": 0, "Medium": 0, "Significant": 0, "High": 0}).items(), (GOOD, "#FDB022", "#F97316", BAD))]} for s in STDS]),
            panel("bars", "Nonconformities by status", 6, items=[{"label": k, "value": v, "color": {"open": BAD, "action in progress": WARN, "verified": TEAL, "closed": GOOD}.get(k, GREY)} for k, v in ncs.items()], empty="No nonconformity is recorded."),
            panel("gantt", "Certification and audit calendar, %d" % today.year, 12, items=gantt, empty="No audit or management review is planned this year.")]


def isms_overview(db, c, today):
    ctl = [x for x in load(db, "standards_hub", "control") if x["standard"] == S27]; impl = [x for x in ctl if x["status"] == "implemented"]; applic = [x for x in ctl if x["status"] != "not applicable"]; th = {}
    for x in applic:
        g = th.setdefault(x["theme"], [0, 0]); g[1] += 1; g[0] += 1 if x["status"] == "implemented" else 0
    risks, dom = [], {}
    try:
        from . import analytics
        rows, _ = analytics.risk_rows(db, c); risks = [r for r in rows if r.get("system") == "ISMS"]
        for d in analytics.DOMAINS:
            vals = [1 - r["domains"][d]["ice"] for r in risks if r["domains"][d]["ice"] is not None]; dom[d] = round(100 * sum(vals) / len(vals)) if vals else 0
    except Exception:
        pass
    soa = load(db, "standards_hub", "soa"); emv = sum(r["emv_i"] or 0 for r in risks); loas = [r["loa"] for r in risks if r["loa"] is not None]
    return [tiles(("ISMS risks", len(risks), "from the workbook", BLUE), ("Inherent exposure", "$%.1fM" % (emv / 1e6), "EMV-i", PURPLE), ("Assurance", "%s%%" % (round(100 * sum(loas) / len(loas)) if loas else 0), "average level of assurance (target 80%)", TEAL), ("Annex A implemented", "%s%%" % (pct(len(impl), len(applic)) or 0), "%d of %d applicable; SoA version %d" % (len(impl), len(applic), len(soa)), GOOD)),
            panel("bars", "Statement of Applicability by Annex A theme (implemented)", 6, items=[{"label": k, "value": pct(v[0], v[1]) or 0, "text": "%d of %d" % (v[0], v[1]), "color": TEAL} for k, v in th.items()], max=100, percent=True),
            panel("bars", "Control effectiveness by P2ST2 domain (workbook)", 6, items=[{"label": k, "value": v, "text": "%d%%" % v, "color": GOOD if v >= 80 else WARN} for k, v in dom.items()], max=100, percent=True),
            panel("table", "ISMS risks with the largest exposure", 12, cols=["Risk", "Title", "Owner", "EMV-i", "Residual", "Assurance"], rows=[[r["source_ref"] or r["ref"], r["title"][:70], r.get("owner") or "", "$%.1fM" % ((r["emv_i"] or 0) / 1e6), {"v": "n/a" if r["rrr"] is None else "%.1f" % r["rrr"]}, "%d%%" % round(100 * (r["loa"] or 0))] for r in sorted(risks, key=lambda z: -(z["emv_i"] or 0))[:8]], note="Risks are assessed on the ranked matrix and linked to Annex A controls (clauses 6.1.2 and 6.1.3). Residual risk accepted above appetite needs the owner and, if High, the Board.")]


def bcms_overview(db, c, today):
    pr = load(db, "bcm_studio", "process", today); ex = load(db, "bcm_studio", "exercise", today); risks, loas, emv = [], [], 0
    try:
        from . import analytics
        rows, _ = analytics.risk_rows(db, c); risks = [r for r in rows if r.get("system") == "BCMS"]; loas = [r["loa"] for r in risks if r["loa"] is not None]; emv = sum(r["emv_i"] or 0 for r in risks)
    except Exception:
        pass
    bia = [p for p in pr if p.get("rto_hours") is not None]; yr = [e for e in ex if (e.get("exercise_date") or "")[:4] == str(today.year)]
    return [tiles(("BCMS risks", len(risks), "from the workbook", BLUE), ("Inherent exposure", "$%.1fM" % (emv / 1e6), "EMV-i", PURPLE), ("Assurance", "%s%%" % (round(100 * sum(loas) / len(loas)) if loas else 0), "average level of assurance", TEAL), ("BIA complete", "%s%%" % (pct(len(bia), len(pr)) or 0), "%d exercises in %d" % (len(yr), today.year), GOOD)),
            panel("table", "Business impact analysis: RTO and RPO against achieved", 12, cols=["Process", "Criticality", "RTO (h)", "Achieved", "RPO (h)", "Achieved", "Status"], rows=[[p["name"][:40], p.get("criticality") or "", p.get("rto_hours"), p.get("achieved_rto_hours") if p.get("achieved_rto_hours") is not None else "not tested", p.get("rpo_hours"), p.get("achieved_rpo_hours") if p.get("achieved_rpo_hours") is not None else "not tested", {"v": p["recovery_status"], "chip": {"meets": GOOD, "gap": BAD}.get(p["recovery_status"], GREY)}] for p in pr[:12]], note="Managed in BCM Studio. BIA results set the recovery targets used by plans and exercises (clauses 8.2 and 8.4)."),
            panel("table", "BCMS risks with the largest exposure", 12, cols=["Risk", "Title", "Owner", "EMV-i", "Residual"], rows=[[r["source_ref"] or r["ref"], r["title"][:70], r.get("owner") or "", "$%.1fM" % ((r["emv_i"] or 0) / 1e6), "n/a" if r["rrr"] is None else "%.1f" % r["rrr"]] for r in sorted(risks, key=lambda z: -(z["emv_i"] or 0))[:8]])]


def aims_overview(db, c, today):
    ai = load(db, "standards_hub", "ai_system", today); ctl = [x for x in load(db, "standards_hub", "control") if x["standard"] == S42]; app = [x for x in ctl if x["status"] != "not applicable"]; impl = [x for x in app if x["status"] == "implemented"]; areas = {}
    for x in app:
        g = areas.setdefault(x["theme"], [0, 0]); g[1] += 1; g[0] += 1 if x["status"] == "implemented" else 0
    themes = {t: sum(1 for s in ai if t.lower() in (s.get("risk_themes") or "").lower()) for t in AI_THEMES}
    try:
        from . import analytics, register
        rows, _ = analytics.risk_rows(db, c); above = sum(1 for r in rows if (r.get("category") == "Model / AI") and register.position(r) in ("Above appetite", "Above tolerance"))
    except Exception:
        above = 0
    return [tiles(("AI systems", len(ai), "%d live" % sum(1 for s in ai if s["status"] == "live"), PURPLE), ("Impact assessments", "%d of %d" % (sum(1 for s in ai if s.get("impact_assessment") == "Complete"), len(ai)), "complete", TEAL), ("Annex A implemented", "%s%%" % (pct(len(impl), len(app)) or 0), "%d of %d applicable" % (len(impl), len(app)), GOOD), ("AI risks above appetite", above, "", BAD if above else GOOD)),
            panel("table", "AI system inventory", 12, cols=["System", "Stage", "Risk", "Impact assessment", "Human oversight", "Owner", "Board review"], rows=[[s["name"][:50], s["status"], {"v": s.get("risk_rating") or "", "chip": {"High": BAD, "Medium": WARN, "Low": GOOD}.get(s.get("risk_rating"))}, s.get("impact_assessment") or "", (s.get("human_oversight") or "NONE DEFINED")[:50], s.get("owner") or "", {"v": "required" if s["board_review"] else "no", "chip": BAD if s["board_review"] else None}] for s in ai], note="No AI system goes live without an owner, risk rating, impact assessment and defined human oversight. A rating of High, or a failed fairness threshold, goes to the Board Risk Committee."),
            panel("bars", "AI risk themes (ISO/IEC 42001 Annex C objectives)", 6, items=[{"label": k, "value": v} for k, v in themes.items() if v] , empty="Tag AI systems with risk themes to see them here."),
            panel("bars", "Annex A coverage by the nine control areas", 6, items=[{"label": k, "value": pct(v[0], v[1]) or 0, "text": "%d of %d" % (v[0], v[1]), "color": TEAL} for k, v in sorted(areas.items(), key=lambda z: int(z[0].split(".")[1].split(" ")[0]))], max=100, percent=True),
            panel("table", "Model health", 12, cols=["System", "Accuracy", "Drift index", "Fairness threshold", "Last monitored"], rows=[[s["name"][:50], s.get("accuracy") or "not recorded", s.get("drift_index") or "not recorded", {"v": "FAILED" if s.get("fairness_failed") else "ok", "chip": BAD if s.get("fairness_failed") else None}, s.get("last_monitored") or ""] for s in ai])]


NC_FIELDS = [F("standard", "Standard", "select", req=True, opts=STDS), F("clause", "Clause"), F("severity", "Severity", "select", req=True, opts=["Major", "Minor", "Observation"], default="Minor"), F("description", "Nonconformity", "textarea", req=True, wide=True), F("source", "Found by", "select", opts=["Internal audit", "External audit", "Management review", "Incident", "Self-assessment"]), F("root_cause", "Root cause", "textarea", wide=True), F("corrective_action", "Corrective action", "textarea", wide=True), F("due", "Due", "date"), F("owner", "Owner"), F("control_id", "Linked control (id in the Control Library)", "number")]
ENT = {"clause": {"label": "Clause", "plural": "Clauses", "prefix": "CLS", "title_field": "title", "statuses": ["not started", "partial", "conformant", "nonconformant", "not applicable"], "next": None, "colors": {"conformant": "good", "partial": "warn", "nonconformant": "bad"}, "columns": ["standard", "clause", "title", "status", "owner", "evidence"], "status_rule": clause_rule, "fields": [F("standard", "Standard", "select", req=True, opts=STDS), F("clause", "Clause", req=True), F("title", "Title", req=True), F("owner", "Owner"), F("evidence", "Evidence (needed for conformant)", "textarea", wide=True), F("last_review", "Last reviewed", "date")]},
       "control": {"label": "Annex A control", "plural": "Annex A controls", "prefix": "CTL", "title_field": "title", "statuses": ["not implemented", "partial", "implemented", "not applicable"], "next": None, "colors": {"implemented": "good", "partial": "warn", "not implemented": "bad"}, "columns": ["standard", "control_id", "title", "theme", "status", "owner"], "status_rule": control_rule, "fields": [F("standard", "Standard", "select", req=True, opts=[S27, S42]), F("control_id", "Control", req=True), F("title", "Title", req=True), F("theme", "Theme or area"), F("owner", "Owner"), F("justification", "Justification (needed if it does not apply)", "textarea", wide=True), F("evidence", "Evidence (needed for implemented)", "textarea", wide=True)]},
       "nonconformity": {"label": "Nonconformity", "plural": "Nonconformities", "prefix": "NCF", "title_field": "description", "statuses": ["open", "action in progress", "verified", "closed"], "next": {"open": ["action in progress"], "action in progress": ["verified", "open"], "verified": ["closed", "action in progress"], "closed": []}, "colors": {"closed": "good", "verified": "good", "action in progress": "warn", "open": "bad"}, "columns": ["standard", "clause", "severity", "description", "status", "due"], "derive": nc_derive, "after": nc_after, "status_rule": nc_rule, "fields": NC_FIELDS},
       "audit": {"label": "Audit or review", "plural": "Audits and reviews", "prefix": "AUD", "title_field": "type", "statuses": ["planned", "done", "cancelled"], "next": None, "colors": {"done": "good"}, "columns": ["standard", "type", "planned_on", "status", "result"], "derive": audit_derive, "fields": [F("standard", "Standard", "select", req=True, opts=STDS), F("type", "Type", "select", req=True, opts=["Internal audit", "Stage 1 audit", "Stage 2 audit", "Surveillance audit", "Recertification audit", "Management review"]), F("planned_on", "Planned for", "date", req=True), F("auditor", "Auditor or body"), F("result", "Result", "textarea", wide=True)]},
       "ai_system": {"label": "AI system", "plural": "AI systems", "prefix": "AIS", "title_field": "name", "statuses": ["idea", "development", "testing", "live", "retired"], "next": None, "colors": {"live": "good", "retired": "warn"}, "columns": ["name", "status", "risk_rating", "impact_assessment", "owner"], "derive": ai_derive, "status_rule": ai_rule, "fields": [F("standard", "Standard", "select", opts=STDS, default=S42), F("name", "AI system", req=True), F("purpose", "Purpose", "textarea", wide=True), F("risk_rating", "Risk rating", "select", opts=["Low", "Medium", "High"]), F("impact_assessment", "Impact assessment", "select", opts=["Not started", "In progress", "Complete"], default="Not started"), F("human_oversight", "Human oversight", "textarea", wide=True), F("owner", "Owner"), F("vendor", "Built or bought from"), F("risk_themes", "Risk themes (Annex C), comma separated"), F("accuracy", "Accuracy"), F("drift_index", "Drift index"), F("fairness_failed", "Failed a fairness threshold", "bool"), F("last_monitored", "Last monitored", "date"), F("notes", "Notes", "textarea", wide=True)]},
       "soa": {"label": "SoA version", "plural": "Statement of Applicability versions", "prefix": "SOA", "title_field": "generated_at", "readonly": True, "statuses": ["issued"], "next": None, "columns": ["version", "generated_by", "generated_at", "controls", "implemented", "not_applicable"], "fields": [F("version", "Version"), F("generated_by", "By"), F("generated_at", "When"), F("controls", "Controls"), F("implemented", "Implemented"), F("not_applicable", "Not applicable")]}}


def sub(keys, std):
    return {k: dict(ENT[k]) for k in keys}


def std_spec(perm, title, std, tabs, overview, ents, extra=None):
    d = {"perm": perm, "title": title, "crumb": "Management Systems", "color": "#C2418F", "data_module": "standards_hub", "filter": {"standard": std}, "tabs": tabs, "overview": overview, "entities": {k: dict(ENT[k]) for k in ents}}
    d.update(extra or {}); return d


register("standards_hub", {"perm": "standards_hub", "title": "Standards Hub", "crumb": "Management Systems", "color": "#C2418F", "intro": "One view of the three management systems (ISO/IEC 27001, ISO 22301, ISO/IEC 42001). They share the clause structure 4 to 10, so conformance, audits, nonconformities and certification are seen side by side, with one audit trail, one action tracker and one document control. A nonconformity creates an action and may lower a linked control's rating.", "seed": seed, "overview": hub_overview,
                           "tabs": [["overview", "Cross-standard view"], ["clause", "Clauses"], ["nonconformity", "Nonconformities"], ["audit", "Audits and reviews"], ["control", "Annex A controls"], ["ai_system", "AI systems"], ["soa", "SoA versions"]], "downloads": {"review": ("Management review pack (Excel)", dl_review), "soa": ("Statement of Applicability (Excel)", dl_soa)}, "actions": [{"id": "soa", "label": "Issue a new Statement of Applicability version", "needs": "edit", "run": act_soa}], "entities": {k: dict(v) for k, v in ENT.items()},
                           "reminders": lambda db, today, horizon: [due_item("Nonconformity", x, "description", "due", "owner", "#/m/standards_hub") for x in load(db, "standards_hub", "nonconformity", today) if x["status"] in ("open", "action in progress") and x.get("due") and x["due"] <= horizon.isoformat()]})
register("isms_iso_27001", std_spec("isms_iso_27001", "ISMS (ISO 27001)", S27, [["overview", "Overview"], ["control", "Annex A controls"], ["clause", "Clauses 4 to 10"], ["nonconformity", "Nonconformities"], ["audit", "Audits"], ["soa", "SoA versions"]], isms_overview, ["clause", "control", "nonconformity", "audit", "soa"], {"intro": "The workspace for the information security management system: risk assessment, treatment and the Statement of Applicability against ISO 27001:2022 Annex A (93 controls in four themes), using the 18 ISMS risks from the workbook.", "downloads": {"soa": ("Statement of Applicability (Excel)", dl_soa)}, "actions": [{"id": "soa", "label": "Issue a new Statement of Applicability version", "needs": "edit", "run": act_soa}]}))
register("bcms_iso_22301", std_spec("bcms_iso_22301", "BCMS (ISO 22301)", S22, [["overview", "Overview"], ["clause", "Clauses 4 to 10"], ["nonconformity", "Nonconformities"], ["audit", "Audits"]], bcms_overview, ["clause", "nonconformity", "audit"], {"intro": "The workspace for the business continuity management system against ISO 22301:2019, using the 15 BCMS risks from the workbook. The business impact analysis, plans and exercises are kept in BCM Studio and shown here."}))
register("aims_iso_42001", std_spec("aims_iso_42001", "AIMS (ISO 42001)", S42, [["overview", "Overview"], ["ai_system", "AI systems"], ["control", "Annex A controls"], ["clause", "Clauses 4 to 10"], ["nonconformity", "Nonconformities"], ["audit", "Audits"]], aims_overview, ["clause", "control", "nonconformity", "audit", "ai_system"], {"intro": "The workspace for the AI management system: the inventory of every AI system EcoCash builds or buys, AI risk and impact on people, and the 38 Annex A controls of ISO/IEC 42001:2023. The platform's own AI features are registered here."}))
