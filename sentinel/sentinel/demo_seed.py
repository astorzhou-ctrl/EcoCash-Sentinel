"""Demonstration data (Step 17): invented, clearly tagged, removable.
Every row made here carries created_by = 'demo' (or the module's equivalent), so  remove()  takes out exactly what  load()  put in and never touches real records.
A module that already holds records of its own is topped up only when it has fewer than a handful, so a real register is never swamped."""
import datetime
import json

from . import db as dbm, kit
from .core import now, audit

TAG = "demo"


class _Ctx:
    def __init__(self):
        self.user = {"id": None, "username": TAG, "full_name": "Demonstration data"}
        self.perms = {}


def D(off):
    return str(dbm.today() + datetime.timedelta(days=off))


def DT(off, hh="09:30"):
    return "%sT%s" % (D(off), hh)


def _count(db, module, entity):
    return db.execute("SELECT COUNT(*) n FROM kit_items WHERE module=? AND entity=? AND deleted_at IS NULL AND created_by<>?", (module, entity, TAG)).fetchone()["n"]


def _kit(db, module, entity, rows, need_below=4):
    """Create rows through the kit engine (validation, history, derived values all apply). Skipped when real records exist."""
    if _count(db, module, entity) >= need_below:
        return 0
    n = 0
    for r in rows:
        try:
            kit.create(db, _Ctx(), module, entity, r)
            n += 1
        except Exception as e:  # a demo row that does not fit a rule is skipped, never fatal
            print("demo skipped %s.%s: %s" % (module, entity, getattr(e, "message", e)))
    return n


OWN = ["Head of Compliance and ML/CTF", "Chief Information Security Officer", "Head of Risk", "Head of Operations", "Head of Legal", "Chief Technology Officer", "Head of Finance", "Head of Customer Experience"]


def load_kit(db):
    n = 0
    n += _kit(db, "obligations_hub", "obligation", [
        dict(name="Customer due diligence for mobile money wallets", regulator="RBZ FIU", citation="Money Laundering and Proceeds of Crime Act s.15", owner=OWN[0], frequency="Annual", next_due=D(40), material=True, evidence="CDD refresh report", status="compliant"),
        dict(name="Suspicious transaction reporting within 24 hours", regulator="RBZ FIU", citation="FIU Guideline 2/2019", owner=OWN[0], frequency="Event-driven", next_due=D(7), material=True, evidence="STR log", status="compliant"),
        dict(name="National Payment Systems returns", regulator="RBZ NPSD", citation="NPS Act s.12", owner=OWN[6], frequency="Quarterly", next_due=D(12), material=True, evidence="Signed return", status="partial"),
        dict(name="Cyber and Data Protection Act: registration with POTRAZ", regulator="POTRAZ", citation="Cyber and Data Protection Act s.8", owner=OWN[4], frequency="Annual", next_due=D(95), material=False, evidence="Registration certificate", status="compliant"),
        dict(name="Tier 1 agent KYC re-verification", regulator="RBZ NPSD", citation="Agent Guideline 4", owner=OWN[3], frequency="Annual", next_due=D(-9), material=False, evidence="Agent KYC file", status="exception"),
        dict(name="Annual penetration test of payment platform", regulator="RBZ NPSD", citation="Cyber Security Guideline 3.2", owner=OWN[1], frequency="Annual", next_due=D(60), material=True, evidence="Pentest report", status="partial"),
        dict(name="Sanctions screening of new customers", regulator="RBZ FIU", citation="UN Sanctions Regulations", owner=OWN[0], frequency="Event-driven", next_due=D(30), material=True, evidence="Screening logs", status="compliant"),
        dict(name="Consumer complaints reporting", regulator="RBZ Consumer Protection", citation="Consumer Protection Framework 5.1", owner=OWN[7], frequency="Quarterly", next_due=D(20), material=False, evidence="Complaints register", status="not assessed")], 6)
    n += _kit(db, "regulatory_change", "change", [
        dict(title="RBZ revised mobile money transaction limits", regulator="RBZ", reference="Circular 08/2026", received_on=D(-25), effective_date=D(35), impact="High", owner=OWN[0], summary="Daily wallet limits are revised and tiered by KYC level.", status="implementing"),
        dict(title="Cyber security guideline: incident reporting in 6 hours", regulator="RBZ NPSD", reference="Guideline CS-2026", received_on=D(-14), effective_date=D(60), impact="High", owner=OWN[1], summary="Material cyber incidents must be reported to the regulator within 6 hours.", status="assessing"),
        dict(title="POTRAZ data localisation clarification", regulator="POTRAZ", reference="Notice 17/2026", received_on=D(-6), effective_date=D(120), impact="Medium", owner=OWN[4], summary="Clarifies storage of personal data of Zimbabwean residents.", status="new"),
        dict(title="FIU risk-based approach update for agents", regulator="RBZ FIU", reference="Directive 03/2026", received_on=D(-60), effective_date=D(-10), impact="Medium", owner=OWN[0], summary="Agents above a monthly volume must be risk rated.", status="closed"),
        dict(title="ZIMRA digital services levy guidance", regulator="ZIMRA", reference="Public Notice 31/2026", received_on=D(-40), effective_date=D(15), impact="Low", owner=OWN[6], summary="Levy applies to fees on digital transactions.", status="assessed")], 4)
    n += _kit(db, "privacy_breach_clock", "breach", [
        dict(title="Misdirected statement e-mails to 38 customers", incident_ref="INC-0231", aware_at=DT(-3, "08:10"), risk_to_subjects="Medium", data_categories="Name, wallet number, balance", individuals=38, description="A batch job used a stale mailing list.", measures="Batch stopped, recipients asked to delete, vendor notified.", potraz_notice_at=DT(-2, "09:00"), owner=OWN[4], status="notified"),
        dict(title="Agent phone lost with customer registration forms", incident_ref="INC-0238", aware_at=DT(-1, "15:45"), risk_to_subjects="High", data_categories="National ID, address, phone", individuals=112, description="A field agent reported a stolen bag with paper forms.", measures="Agent suspended, customers flagged for monitoring.", owner=OWN[4], status="assessing"),
        dict(title="Test environment exposed sample data", incident_ref="INC-0219", aware_at=DT(-30, "10:00"), risk_to_subjects="Low", data_categories="Masked test records", individuals=0, description="Masked data in a public test link.", measures="Link removed, access logs reviewed.", owner=OWN[1], status="closed")], 3)
    n += _kit(db, "privacy_breach_clock", "processing", [
        dict(system="Wallet registration", data="Name, national ID, phone, address", lawful_basis="Legal obligation", purpose="Know your customer", dpia_required=True, owner=OWN[0], retention="7 years after closure", transfer_abroad=False, processor="In-house"),
        dict(system="Agent onboarding", data="Business details, owner ID, bank account", lawful_basis="Contract", purpose="Appointing agents", dpia_required=False, owner=OWN[3], retention="Contract term plus 7 years", transfer_abroad=False, processor="In-house"),
        dict(system="Customer care call recording", data="Voice, phone number", lawful_basis="Legitimate interests", purpose="Quality and dispute resolution", dpia_required=True, owner=OWN[7], retention="12 months", transfer_abroad=True, processor="Call-centre vendor"),
        dict(system="Marketing SMS", data="Phone number, usage segment", lawful_basis="Consent", purpose="Product offers", dpia_required=False, owner=OWN[7], retention="Until consent withdrawn", transfer_abroad=False, processor="Bulk SMS vendor")], 3)
    n += _kit(db, "privacy_breach_clock", "dpia", [
        dict(activity="Wallet registration", risk_level="Medium", completed_on=D(-120), next_review=D(245), owner=OWN[0], status="Complete"),
        dict(activity="Customer care call recording", risk_level="High", next_review=D(30), owner=OWN[7], status="In progress"),
        dict(activity="Credit scoring model", risk_level="High", next_review=D(75), owner=OWN[2], status="Planned")], 3)
    n += _kit(db, "privacy_breach_clock", "request", [
        dict(type="Access", received_on=D(-12), due_on=D(18), owner=OWN[4], status="in progress"),
        dict(type="Deletion", received_on=D(-35), due_on=D(-5), completed_on=D(-8), owner=OWN[4], status="completed"),
        dict(type="Correction", received_on=D(-3), due_on=D(27), owner=OWN[4], status="received"),
        dict(type="Portability", received_on=D(-20), due_on=D(10), owner=OWN[4], status="extended")], 3)
    n += _kit(db, "privacy_breach_clock", "licence", [
        dict(title="POTRAZ data controller licence", licence_no="DC-2026-0412", registered_on=D(-200), expires_on=D(165), status="Registered"),
        dict(title="RBZ payment system operator licence", licence_no="PSO-0007", registered_on=D(-700), expires_on=D(380), status="Registered")], 2)
    n += _kit(db, "policy_hub", "policy", [
        dict(title="Enterprise Risk Management Policy", owner=OWN[2], version="4.1", approved_on=D(-150), next_review=D(215), status="current"),
        dict(title="Information Security Policy", owner=OWN[1], version="3.0", approved_on=D(-300), next_review=D(65), status="current"),
        dict(title="Anti-Money Laundering and CFT Policy", owner=OWN[0], version="5.2", approved_on=D(-90), next_review=D(275), status="current"),
        dict(title="Business Continuity Policy", owner=OWN[3], version="2.3", approved_on=D(-400), next_review=D(-20), status="under review"),
        dict(title="Third-Party Risk Management Policy", owner=OWN[2], version="1.0", status="draft"),
        dict(title="Data Protection and Privacy Policy", owner=OWN[4], version="2.0", approved_on=D(-200), next_review=D(165), status="current")], 4)
    n += _kit(db, "third_party_risk", "vendor", [
        dict(name="Econet Wireless network", service="Mobile network and connectivity", tier="1", owner=OWN[5], contract_start=D(-900), contract_end=D(200), data_access=True, exit_plan="Documented", fourth_parties="Tower companies", incidents_12m=2, status="active"),
        dict(name="CloudHost Africa", service="Cloud and hosting", tier="1", owner=OWN[5], contract_start=D(-400), contract_end=D(330), data_access=True, exit_plan="Tested", exit_tested_on=D(-80), fourth_parties="Hyperscaler", incidents_12m=1, status="active"),
        dict(name="SwitchPay Processing", service="Payments and switching", tier="1", owner=OWN[6], contract_start=D(-600), contract_end=D(45), data_access=True, exit_plan="None", incidents_12m=4, status="under review"),
        dict(name="CashLink Logistics", service="Cash logistics", tier="2", owner=OWN[3], contract_start=D(-300), contract_end=D(430), data_access=False, exit_plan="Documented", incidents_12m=0, status="active"),
        dict(name="AgentNet Field Services", service="Agent services", tier="2", owner=OWN[3], contract_start=D(-250), contract_end=D(115), data_access=True, exit_plan="None", incidents_12m=1, status="active"),
        dict(name="BrightSMS Gateway", service="Software and platforms", tier="3", owner=OWN[7], contract_start=D(-100), contract_end=D(265), data_access=True, exit_plan="Documented", incidents_12m=0, status="active"),
        dict(name="Marsh & Co Advisory", service="Professional services", tier="3", owner=OWN[2], contract_start=D(-60), contract_end=D(305), data_access=False, exit_plan="None", incidents_12m=0, status="prospect")], 5)
    n += _kit(db, "cyber_it_risk", "asset", [
        dict(name="Mobile wallet core platform", type="Application", criticality="Critical", owner=OWN[5], internet_facing=True, mfa=True, in_scope=True),
        dict(name="USSD gateway", type="Application", criticality="Critical", owner=OWN[5], internet_facing=True, mfa=True, in_scope=True),
        dict(name="Customer database cluster", type="Database", criticality="Critical", owner=OWN[1], internet_facing=False, mfa=True, in_scope=True),
        dict(name="Agent mobile app backend", type="Cloud service", criticality="High", owner=OWN[5], internet_facing=True, mfa=True, in_scope=True),
        dict(name="Core network firewalls", type="Network", criticality="High", owner=OWN[1], internet_facing=True, mfa=False, in_scope=True),
        dict(name="Staff laptop fleet", type="Endpoint fleet", criticality="Medium", owner=OWN[1], internet_facing=False, mfa=True, in_scope=True),
        dict(name="Reporting data warehouse", type="Database", criticality="Medium", owner=OWN[6], internet_facing=False, mfa=False, in_scope=True),
        dict(name="Corporate e-mail", type="Cloud service", criticality="Medium", owner=OWN[1], internet_facing=True, mfa=True, in_scope=True)], 5)
    n += _kit(db, "cyber_it_risk", "vuln", [
        dict(title="Remote code execution in web framework", asset="Agent mobile app backend", severity="Critical", discovered_on=D(-9), due_on=D(-2), cve="CVE-2026-1182", source="Scanner", status="open"),
        dict(title="Outdated TLS configuration on USSD gateway", asset="USSD gateway", severity="High", discovered_on=D(-20), due_on=D(10), cve="", source="Pentest", status="open"),
        dict(title="Privilege escalation in database engine", asset="Customer database cluster", severity="High", discovered_on=D(-35), due_on=D(-5), patched_on=D(-6), cve="CVE-2026-0455", source="Scanner", status="patched"),
        dict(title="Default credentials on network appliance", asset="Core network firewalls", severity="Critical", discovered_on=D(-4), due_on=D(3), source="Red team", status="open"),
        dict(title="Missing disk encryption on 14 laptops", asset="Staff laptop fleet", severity="Medium", discovered_on=D(-50), due_on=D(25), source="Audit", status="accepted"),
        dict(title="Verbose error messages leak stack traces", asset="Mobile wallet core platform", severity="Low", discovered_on=D(-15), due_on=D(60), source="Pentest", status="open"),
        dict(title="Unpatched mail relay", asset="Corporate e-mail", severity="Medium", discovered_on=D(-28), due_on=D(-1), patched_on=D(-3), source="Scanner", status="patched")], 5)
    wk = [(-49, 9, 31, 78, 61, 9.5), (-42, 8, 29, 80, 63, 9.1), (-35, 8, 30, 81, 66, 8.4), (-28, 6, 27, 83, 70, 7.9), (-21, 6, 24, 85, 74, 7.2), (-14, 5, 22, 88, 79, 6.8), (-7, 4, 19, 90, 84, 6.1), (0, 3, 17, 92, 88, 5.6)]
    n += _kit(db, "cyber_it_risk", "snapshot", [dict(week=D(o), open_critical=c, open_high=h, patch_sla_pct=p, mfa_pct=m, mttd_hours=t) for o, c, h, p, m, t in wk], 3)
    n += _kit(db, "crisis_room", "contact", [
        dict(title="Crisis Commander", primary="Chief Executive Officer", phone="+263 77 100 0001", email="ceo@demo.invalid", deputy="Chief Operating Officer", deputy_phone="+263 77 100 0002", reachable="Yes", last_checked=D(-6)),
        dict(title="Technology lead", primary="Chief Technology Officer", phone="+263 77 100 0003", email="cto@demo.invalid", deputy="Head of IT Operations", deputy_phone="+263 77 100 0004", reachable="Yes", last_checked=D(-6)),
        dict(title="Communications lead", primary="Head of Corporate Affairs", phone="+263 77 100 0005", email="comms@demo.invalid", deputy="Brand Manager", deputy_phone="+263 77 100 0006", reachable="Unknown", last_checked=D(-95)),
        dict(title="Regulator liaison", primary="Head of Compliance and ML/CTF", phone="+263 77 100 0007", email="compliance@demo.invalid", deputy="Legal Counsel", deputy_phone="+263 77 100 0008", reachable="Yes", last_checked=D(-20)),
        dict(title="Finance and treasury", primary="Chief Financial Officer", phone="+263 77 100 0009", email="cfo@demo.invalid", deputy="Head of Treasury", deputy_phone="+263 77 100 0010", reachable="No", last_checked=D(-45))], 3)
    n += _kit(db, "crisis_room", "playbook", [
        dict(name="Platform outage", trigger="Wallet or USSD unavailable for 30 minutes", owner=OWN[5], last_tested=D(-70), steps="1. Declare level by impact.\n2. Fail over to the secondary site.\n3. Notify the regulator and customers.\n4. Hold hourly updates.\n5. Run the post-incident review."),
        dict(name="Cyber attack and data breach", trigger="Confirmed intrusion or data loss", owner=OWN[1], last_tested=D(-110), steps="1. Isolate affected systems.\n2. Preserve evidence.\n3. Start the 72-hour breach clock.\n4. Brief the Board.\n5. Notify customers if required."),
        dict(name="Fraud wave on agents", trigger="Fraud alerts exceed three times the daily norm", owner=OWN[0], last_tested=D(-40), steps="1. Tighten limits.\n2. Freeze high-risk clusters.\n3. Inform the RBZ.\n4. Recover funds with partner banks."),
        dict(name="Liquidity or float shortage", trigger="Float below 2 days of cash-out", owner=OWN[6], last_tested=D(-160), steps="1. Activate treasury lines.\n2. Rebalance agent float.\n3. Limit large cash-outs.")], 3)
    n += _kit(db, "crisis_room", "template", [
        dict(name="Message to customers: service disruption", audience="Customers", text="Dear customer, some EcoCash services are currently unavailable. Our teams are working to restore them. We apologise and will update you shortly."),
        dict(name="Message to staff: crisis declared", audience="Staff", text="A crisis has been declared. Follow the crisis playbook, keep communications within the crisis channel and refer media to Corporate Affairs."),
        dict(name="Notice to regulator", audience="Regulator", text="We notify you of an incident affecting our payment services. Initial assessment, impact and next steps are set out below."),
        dict(name="Holding statement for media", audience="Media", text="EcoCash is aware of an issue affecting some services and is working to resolve it. Customer funds are safe.")], 3)
    n += _kit(db, "bcm_studio", "process", [
        dict(name="Wallet payments and transfers", owner=OWN[5], criticality="Critical", rto_hours=1, rpo_hours=0, min_service="Peer-to-peer transfers and merchant payments", systems="Wallet core, USSD, switch", vendors="Econet, SwitchPay", achieved_rto_hours=1.5, achieved_rpo_hours=0, last_tested=D(-70)),
        dict(name="Agent cash-in and cash-out", owner=OWN[3], criticality="Critical", rto_hours=2, rpo_hours=1, min_service="Cash-out at top agents", systems="Agent app, float management", vendors="AgentNet, CashLink", achieved_rto_hours=1.8, achieved_rpo_hours=0.5, last_tested=D(-110)),
        dict(name="Customer care", owner=OWN[7], criticality="High", rto_hours=4, rpo_hours=4, min_service="Hotline and chat for blocked wallets", systems="CRM, telephony", vendors="Call-centre vendor", achieved_rto_hours=6, achieved_rpo_hours=2, last_tested=D(-200)),
        dict(name="Regulatory reporting", owner=OWN[0], criticality="Medium", rto_hours=24, rpo_hours=24, min_service="Statutory returns", systems="Data warehouse", vendors="None", achieved_rto_hours=20, achieved_rpo_hours=12, last_tested=D(-150)),
        dict(name="Payroll and treasury", owner=OWN[6], criticality="High", rto_hours=8, rpo_hours=4, min_service="Salary and settlement runs", systems="ERP, banking portal", vendors="Partner banks", achieved_rto_hours=12, achieved_rpo_hours=4, last_tested=D(-240))], 3)
    n += _kit(db, "bcm_studio", "plan", [
        dict(name="Wallet platform recovery plan", process="Wallet payments and transfers", owner=OWN[5], version="3.2", last_review=D(-80), next_review=D(100), status="current"),
        dict(name="Agent network continuity plan", process="Agent cash-in and cash-out", owner=OWN[3], version="2.0", last_review=D(-150), next_review=D(30), status="current"),
        dict(name="Customer care continuity plan", process="Customer care", owner=OWN[7], version="1.4", last_review=D(-300), next_review=D(-30), status="draft")], 2)
    n += _kit(db, "bcm_studio", "exercise", [
        dict(name="Q3 wallet failover test", type="Failover test", exercise_date=D(-70), process="Wallet payments and transfers", owner=OWN[5], result="Partial", achieved_rto_hours=1.5, achieved_rpo_hours=0, lessons="Switch-over took 30 minutes longer than the 1-hour target.", status="done"),
        dict(name="Cyber crisis tabletop", type="Tabletop", exercise_date=D(-110), process="Agent cash-in and cash-out", owner=OWN[1], result="Passed", lessons="Roles were clear; regulator call tree needs updating.", status="done"),
        dict(name="Customer care relocation walkthrough", type="Walkthrough", exercise_date=D(28), process="Customer care", owner=OWN[7], status="planned"),
        dict(name="Full simulation: data centre loss", type="Full simulation", exercise_date=D(75), process="Wallet payments and transfers", owner=OWN[5], status="planned")], 3)
    n += _kit(db, "standards_hub", "nonconformity", [
        dict(standard="ISO/IEC 27001:2022", clause="A.8.8", severity="Major", description="Critical vulnerabilities not patched within the 7-day target on two systems.", source="Internal audit", root_cause="Patch window clashed with month-end freeze.", corrective_action="Agree emergency patch exception and automate reporting.", due=D(21), owner=OWN[1], status="action in progress"),
        dict(standard="ISO/IEC 27001:2022", clause="A.5.19", severity="Minor", description="Supplier security reviews are overdue for three tier 2 vendors.", source="Management review", corrective_action="Complete reviews and add a tracker.", due=D(45), owner=OWN[2], status="open"),
        dict(standard="ISO 22301:2019", clause="8.5", severity="Minor", description="Customer care exercise not held in the last 12 months.", source="Internal audit", corrective_action="Hold relocation walkthrough.", due=D(28), owner=OWN[7], status="action in progress"),
        dict(standard="ISO/IEC 42001:2023", clause="A.6.2", severity="Observation", description="Impact assessment not yet completed for the credit scoring model.", source="Self-assessment", corrective_action="Complete before go-live.", due=D(60), owner=OWN[2], status="open"),
        dict(standard="ISO/IEC 27001:2022", clause="A.7.2", severity="Minor", description="Visitor logs incomplete at one regional office.", source="External audit", corrective_action="Retrain reception.", due=D(-10), owner=OWN[3], status="verified")], 3)
    n += _kit(db, "standards_hub", "audit", [
        dict(standard="ISO/IEC 27001:2022", type="Surveillance audit", planned_on=D(55), auditor="BSI", status="planned"),
        dict(standard="ISO/IEC 27001:2022", type="Internal audit", planned_on=D(-45), auditor="Internal Audit", result="Two minor findings and one major.", status="done"),
        dict(standard="ISO 22301:2019", type="Internal audit", planned_on=D(-20), auditor="Internal Audit", result="One minor finding.", status="done"),
        dict(standard="ISO/IEC 42001:2023", type="Stage 1 audit", planned_on=D(110), auditor="Certification body", status="planned"),
        dict(standard="ISO/IEC 27001:2022", type="Management review", planned_on=D(18), auditor="Executive Committee", status="planned")], 3)
    n += _kit(db, "standards_hub", "ai_system", [
        dict(standard="ISO/IEC 42001:2023", name="Fraud pattern detection", purpose="Scores transactions for unusual behaviour.", risk_rating="High", impact_assessment="Complete", human_oversight="Analyst reviews every blocked case.", owner=OWN[0], vendor="In-house", risk_themes="Bias, drift", accuracy="94%", drift_index="0.08", fairness_failed=False, last_monitored=D(-8), status="live"),
        dict(standard="ISO/IEC 42001:2023", name="Customer care assistant", purpose="Drafts replies for agents.", risk_rating="Medium", impact_assessment="Complete", human_oversight="Agent approves every reply.", owner=OWN[7], vendor="Cloud vendor", risk_themes="Hallucination, privacy", accuracy="91%", drift_index="0.12", fairness_failed=False, last_monitored=D(-15), status="live"),
        dict(standard="ISO/IEC 42001:2023", name="Credit scoring model", purpose="Scores micro-loan applicants.", risk_rating="High", impact_assessment="In progress", human_oversight="Credit officer decides.", owner=OWN[2], vendor="In-house", risk_themes="Bias, explainability", accuracy="88%", drift_index="0.21", fairness_failed=True, last_monitored=D(-3), status="testing"),
        dict(standard="ISO/IEC 42001:2023", name="Agent float forecast", purpose="Predicts float needs per cluster.", risk_rating="Low", impact_assessment="Not started", human_oversight="Operations approves rebalancing.", owner=OWN[3], vendor="In-house", risk_themes="Accuracy", status="development")], 3)
    n += _kit(db, "predictive_analytics", "model", [
        dict(name="KRI breach forecast", use="Forecasts when a key indicator will cross its red line.", method="forecast", owner=OWN[2], limits="Needs at least 8 readings.", accuracy=82, validated_on=D(-30), status="active"),
        dict(name="Transaction anomaly detector", use="Flags unusual daily volumes.", method="anomaly", owner=OWN[0], limits="Sensitive to holidays.", accuracy=88, validated_on=D(-45), status="active"),
        dict(name="Loss event likelihood", use="Estimates next-quarter loss frequency.", method="planned", owner=OWN[2], limits="Not yet built.", status="planned")], 2)
    return n


def _have(db, table, where="1=1"):
    return db.execute("SELECT COUNT(*) n FROM %s WHERE %s" % (table, where)).fetchone()["n"]


def load_other(db):
    n = 0
    ts = now()
    # ---- Strategy map: objectives linked to indicators
    if _have(db, "objectives", "code NOT LIKE 'D-%'") < 4:
        objs = [("D-F1", "Grow digital revenue sustainably", "Financial", "Chief Financial Officer", "Revenue growth 12% with loss ratio under 0.4%"),
                ("D-F2", "Keep fraud losses inside appetite", "Financial", "Head of Compliance and ML/CTF", "Fraud losses under 0.15% of transaction value"),
                ("D-C1", "Make every wallet journey reliable", "Customer", "Head of Customer Experience", "Availability 99.9%, complaints resolved in 3 days"),
                ("D-C2", "Protect customer trust and data", "Customer", "Chief Information Security Officer", "Zero reportable breaches"),
                ("D-P1", "Operate resilient, compliant processes", "Internal process", "Head of Operations", "All critical processes tested within 12 months"),
                ("D-P2", "Manage third parties proactively", "Internal process", "Head of Risk", "All tier 1 vendors reviewed annually"),
                ("D-L1", "Build a risk-aware culture", "Learning and growth", "Head of Risk", "100% attestation of key policies")]
        ks = [r["id"] for r in db.execute("SELECT id FROM kpis WHERE deleted_at IS NULL ORDER BY id LIMIT 14")]
        for i, (code, name, per, own, tgt) in enumerate(objs):
            if db.execute("SELECT 1 FROM objectives WHERE code=?", (code,)).fetchone():
                continue
            oid = db.execute("INSERT INTO objectives(code,name,perspective,owner,description,target_text,sort) VALUES(?,?,?,?,?,?,?)", (code, name, per, own, "Demonstration objective.", tgt, 100 + i)).lastrowid
            for kid in ks[i * 2:i * 2 + 2]:
                db.execute("INSERT OR IGNORE INTO objective_kpis(objective_id,kpi_id) VALUES(?,?)", (oid, kid))
            n += 1
    # ---- Scenario Lab
    if _have(db, "scenarios", "created_by<>'demo'") < 3:
        from . import scenario as sc
        for tid, nm, sco in (("sim_swap", "SIM-swap wave during festive season", (4, 5, 3)), ("platform_outage", "Two-day platform outage at month end", (3, 4, 4)), ("data_breach", "Customer data breach via a vendor", (2, 3, 2)), ("agent_float", "Float shortage in rural clusters", (3, 3, 4)), ("fx_shock", "Sharp ZiG depreciation", (4, 4, 5))):
            t = sc.TEMPLATES[tid]
            sid = db.execute("INSERT INTO scenarios(name,template,appetite_usd,created_by,created_at) VALUES(?,?,?,?,?)", (nm, tid, t["appetite"], TAG, ts)).lastrowid
            s = db.execute("SELECT * FROM scenarios WHERE id=?", (sid,)).fetchone()
            try:
                sc._save_version(db, s, sc.default_params(tid), "Demonstration values from the library.", TAG)
            except Exception as e:
                print("demo scenario skipped", e)
            for u, v in zip(("demo.a", "demo.b", "demo.c"), sco):
                db.execute("INSERT OR REPLACE INTO scenario_scores(scenario_id,username,score,ts) VALUES(?,?,?,?)", (sid, u, v, ts))
            n += 1
    # ---- Emerging Radar
    if _have(db, "signals", "created_by<>'demo' OR created_by IS NULL") < 4:
        sig = [("Central bank signals tighter e-money rules", "Regulatory", 0.7, 4, 3, 2, "new"), ("Rise in SIM-swap syndicates across the region", "Fraud", 0.8, 5, 4, 3, "watching"), ("New regional instant-payment scheme launched", "Competition", 0.6, 4, 2, 3, "watching"),
               ("Grid load-shedding extended to 18 hours", "Operations", 0.9, 4, 4, 5, "new"), ("Generative-AI voice cloning used in vishing", "Technology", 0.65, 4, 4, 3, "new"), ("Currency volatility on parallel market", "Economic", 0.75, 5, 3, 4, "promoted"), ("Mobile tower vandalism reports", "Operations", 0.5, 3, 2, 4, "dismissed")]
        for i, (t, th, cf, im, ve, pr, st) in enumerate(sig):
            db.execute("INSERT OR IGNORE INTO signals(ts,title,summary,source,theme,confidence,impact,velocity,proximity,status,origin,dedupe,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (D(-i * 3) + " 08:00:00", t, "Demonstration signal: " + t.lower() + ".", "Demonstration source", th, cf, im, ve, pr, st, "manual", "demo:%d" % i, TAG)); n += 1
        for th, ow in (("Regulatory", OWN[0]), ("Fraud", OWN[0]), ("Technology", OWN[5])):
            if not _have(db, "radar_watch", "theme='%s'" % th):
                db.execute("INSERT INTO radar_watch(theme,owner,review_date,notes) VALUES(?,?,?,?)", (th, ow, D(30), "Demonstration watch item."))
    # ---- Audit Workspace
    if _have(db, "audit_plan", "created_by<>'demo'") < 3:
        yr = dbm.today().year
        plan = [("Mobile money platform access controls", "Technology", 1, 3, "fieldwork", None), ("Agent onboarding and KYC", "Operations", 3, 5, "planned", None), ("Third-party payment switch resilience", "Third party", 5, 7, "planned", None), ("Fraud monitoring effectiveness", "Fraud", 9, 10, "reporting", "Needs improvement"), ("Regulatory returns accuracy", "Compliance", 2, 3, "closed", "Satisfactory")]
        pids = []
        for i, (t, area, a, b, st, gr) in enumerate(plan):
            pid = db.execute("INSERT INTO audit_plan(ref,year,title,area,scope,month_start,month_end,lead,status,grade,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("AP-D%02d" % (i + 1), yr, t, area, "Demonstration engagement.", a, b, "Head of Internal Audit", st, gr, TAG, ts)).lastrowid; pids.append(pid); n += 1
        fnd = [(0, "Dormant administrator accounts not disabled", "High", "open", 14), (0, "Privileged access reviews are late", "Medium", "responded", -5), (3, "Alert backlog exceeds service level", "High", "open", 21), (3, "Rule changes lack second approval", "Medium", "open", 40), (4, "Return reconciliation done manually", "Low", "closed", -30), (1, "Agent KYC files incomplete", "High", "responded", 10)]
        for i, (pi, t, pr, st, du) in enumerate(fnd):
            db.execute("INSERT INTO audit_findings(ref,engagement_id,title,condition_text,criteria,cause,effect,recommendation,priority,owner_name,due_date,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("AF-D%02d" % (i + 1), pids[pi], t, "Observed during fieldwork.", "Policy and control standard.", "Process gap.", "Elevated exposure.", "Fix the gap and evidence it.", pr, OWN[(i + 1) % len(OWN)], D(du), st, TAG, ts)); n += 1
    # ---- Fraud Intelligence
    if _have(db, "fraud_alerts", "created_by<>'demo' OR created_by IS NULL") < 8:
        from . import fraud as fr
        clusters = ["Harare CBD", "Bulawayo North", "Mutare East", "Gweru Central", "Masvingo Rural", "Chitungwiza"]
        regions = ["Harare", "Bulawayo", "Manicaland", "Midlands", "Masvingo", "Harare"]
        stat = ["detected", "investigating", "confirmed", "recovered", "closed", "false_positive"]
        for i in range(36):
            t = fr.TYPOLOGIES[(i * 7 + i // 3) % 6]; amt = 80 + (i * 137) % 2400; st = stat[i % 6]; cl = clusters[(i * 5) % 6]
            loss = round(amt * (0.8 if st in ("confirmed", "closed") else 0.2 if st == "recovered" else 0), 2)
            db.execute("INSERT INTO fraud_alerts(ref,detected_at,typology,channel,agent_cluster,region,amount,status,assigned_to,loss,recovered,source,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("FRD-D%03d" % (i + 1), D(-(i * 2) % 75) + " 10:00:00", t, fr.CHANNELS[i % 5], cl, regions[(i * 5) % 6], amt, st, "Fraud Analyst", loss, round(loss * 0.4, 2) if st == "recovered" else 0, "manual", TAG, ts)); n += 1
    # ---- Speak-Up
    if _have(db, "speakup_cases", "created_by<>'demo' OR created_by IS NULL") < 4:
        from . import speakup as su
        cases = [("Possible kickback in vendor selection", 0, 1, "investigating", "High"), ("Supervisor pressuring staff to work unpaid overtime", 2, 3, "triage", "Normal"), ("Agent charging customers extra fees", 0, 0, "substantiated", "Normal"), ("Gift offered during tender", 1, 4, "received", "Normal"), ("Customer data viewed without reason", 5, 1, "investigating", "High"), ("Safety hazard at regional office", 6, 2, "closed", "Low"), ("Conflict of interest in hiring", 3, 4, "unsubstantiated", "Normal")]
        for i, (s, th, ch, st, pr) in enumerate(cases):
            db.execute("INSERT INTO speakup_cases(ref,received_at,channel,theme,priority,summary,detail,anonymous,status,ack_due,close_due,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("SU-D%03d" % (i + 1), D(-i * 6) + " 11:00:00", su.CHANNELS[ch], su.THEMES[th], pr, s, "Demonstration case, invented.", 1, st, D(-i * 6 + 3), D(-i * 6 + 30), TAG)); n += 1
    # ---- Integration Hub: connectors seen recently, with a few events
    try:
        from . import integ
        integ.seed(db)
        if not _have(db, "integ_events", "detail LIKE 'demo%'"):
            for i, (c, rows, bad, stt) in enumerate((("wallet", 1440, 0, "ok"), ("siem", 96, 2, "ok"), ("vuln_scanner", 310, 0, "ok"), ("hr", 5200, 14, "ok"), ("finance", 180, 0, "ok"), ("directory", 640, 0, "ok"), ("wallet", 1388, 0, "ok"), ("siem", 0, 0, "error"))):
                db.execute("INSERT INTO integ_events(ts,connector,status,rows_in,rows_bad,detail) VALUES(?,?,?,?,?,?)", (D(-(i % 3)) + " %02d:15:00" % (6 + i), c, stt, rows, bad, "demo: " + ("connection refused" if stt == "error" else "scheduled load")))
            for c in ("wallet", "siem", "vuln_scanner", "hr", "finance", "directory"):
                db.execute("UPDATE integ_connectors SET enabled=1 WHERE key=? AND enabled=0 AND key_hash IS NULL", (c,))
            n += 8
    except Exception as e:
        print("demo integrations skipped", e)
    # ---- Copilot: horizon-watch briefs
    if not _have(db, "ai_briefs", "origin='demo'"):
        for i, (t, src, sev) in enumerate((("RBZ circular on mobile money limits", "RBZ", 4), ("Regional SIM-swap campaign targets wallets", "Industry alert", 4), ("POTRAZ publishes quarterly sector report", "POTRAZ", 2), ("Power utility announces extended load-shedding", "News", 3))):
            db.execute("INSERT OR IGNORE INTO ai_briefs(ts,topic,title,source,published,severity,summary,impact,status,dedupe,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (D(-i * 2) + " 07:00:00", "Horizon", t, src, D(-i * 2), sev, "Demonstration brief: " + t + ".", "May affect EcoCash operations and obligations; review with the owner.", "new", "demo:b%d" % i, "demo")); n += 1
    return n


def load(db):
    top = db.execute("SELECT COALESCE(MAX(id),0) m FROM actions").fetchone()["m"]
    n = load_kit(db) + load_other(db)
    made = [r["id"] for r in db.execute("SELECT id FROM actions WHERE id>?", (top,))]  # follow-up actions that the register rules raised: they go with the demonstration data
    old = db.execute("SELECT value FROM settings WHERE key='demo_actions'").fetchone()
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_actions',?)", (json.dumps((json.loads(old["value"]) if old else []) + made),))
    # the ISO workspaces: move some of the seeded Annex A controls and clauses on from their starting status, remembering which, so Remove can put them back
    moved = []
    for ent, frm, seq in (("control", "not implemented", ["implemented", "implemented", "implemented", "partial", "implemented", "implemented", "not applicable"]), ("clause", "not started", ["conformant", "conformant", "partial", "conformant", "conformant", "nonconformant"])):
        for i, r in enumerate(db.execute("SELECT id FROM kit_items WHERE module='standards_hub' AND entity=? AND status=? AND created_by<>? AND deleted_at IS NULL ORDER BY id", (ent, frm, TAG)).fetchall()):
            db.execute("UPDATE kit_items SET status=? WHERE id=?", (seq[i % len(seq)], r["id"])); moved.append([r["id"], frm])
    old = db.execute("SELECT value FROM settings WHERE key='demo_moved'").fetchone()
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_moved',?)", (json.dumps((json.loads(old["value"]) if old else []) + moved),))
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_loaded',?)", (now(),))
    audit(db, "demo.load", None, "administration", "Demonstration data loaded: %d records" % n, "", username=TAG)
    return n


def remove(db):
    """Take out exactly what load() added."""
    c = 0
    c += db.execute("DELETE FROM kit_items WHERE created_by=?", (TAG,)).rowcount
    r = db.execute("SELECT value FROM settings WHERE key='demo_actions'").fetchone()
    for aid in (json.loads(r["value"]) if r else []):
        c += db.execute("DELETE FROM actions WHERE id=?", (aid,)).rowcount
    db.execute("DELETE FROM settings WHERE key='demo_actions'")
    r = db.execute("SELECT value FROM settings WHERE key='demo_moved'").fetchone()
    for iid, frm in (json.loads(r["value"]) if r else []):
        db.execute("UPDATE kit_items SET status=? WHERE id=?", (frm, iid))
    db.execute("DELETE FROM settings WHERE key='demo_moved'")
    for t, w in (("scenarios", "created_by='demo'"), ("signals", "created_by='demo'"), ("audit_findings", "created_by='demo'"), ("audit_plan", "created_by='demo'"), ("fraud_alerts", "created_by='demo'"), ("speakup_cases", "created_by='demo'"),
                 ("ai_briefs", "origin='demo'"), ("integ_events", "detail LIKE 'demo%'"), ("objectives", "code LIKE 'D-%'")):
        try:
            c += db.execute("DELETE FROM %s WHERE %s" % (t, w)).rowcount
        except Exception:
            pass
    db.execute("DELETE FROM settings WHERE key='demo_loaded'")
    audit(db, "demo.remove", None, "administration", "Demonstration data removed: %d records" % c, "", username=TAG)
    return c


# ---- per module: where the demonstration records show up, so each page can offer its own Remove button
KIT_MODULES = {"obligations_hub": ["obligations_hub"], "regulatory_change": ["regulatory_change"], "privacy_breach_clock": ["privacy_breach_clock"], "policy_hub": ["policy_hub"], "third_party_risk": ["third_party_risk"],
               "cyber_it_risk": ["cyber_it_risk"], "crisis_room": ["crisis_room"], "bcm_studio": ["bcm_studio"], "predictive_analytics": ["predictive_analytics"],
               "standards_hub": ["standards_hub", "isms_iso_27001", "bcms_iso_22301", "aims_iso_42001"]}
OTHER = {"strategy_map": ("objectives", "code LIKE 'D-%'"), "scenario_lab": ("scenarios", "created_by='demo'"), "emerging_radar": ("signals", "created_by='demo'"), "audit_workspace": ("audit_plan", "created_by='demo'"),
         "fraud_intelligence": ("fraud_alerts", "created_by='demo'"), "speak_up_cases": ("speakup_cases", "created_by='demo'"), "integration_hub": ("integ_events", "detail LIKE 'demo%'"), "sentinel_copilot": ("ai_briefs", "origin='demo'")}


def summary(db):
    out = {}
    for src, pages in KIT_MODULES.items():
        n = db.execute("SELECT COUNT(*) n FROM kit_items WHERE module=? AND created_by=? AND deleted_at IS NULL", (src, TAG)).fetchone()["n"]
        if n:
            for p in pages:
                out[p] = n
    for page, (t, w) in OTHER.items():
        try:
            n = db.execute("SELECT COUNT(*) n FROM %s WHERE %s" % (t, w)).fetchone()["n"]
        except Exception:
            n = 0
        if n:
            out[page] = n
    n = db.execute("SELECT COUNT(*) n FROM kpi_readings WHERE method='seed'").fetchone()["n"]
    if n:
        out["weekly_kpi"] = n
    return out


def remove_module(db, page):
    """Remove the demonstration records that appear on one page. Returns how many."""
    c = 0
    for src, pages in KIT_MODULES.items():
        if page in pages:
            c += db.execute("DELETE FROM kit_items WHERE module=? AND created_by=?", (src, TAG)).rowcount
            if src in ("standards_hub", "bcm_studio"):  # the follow-up actions those registers raised, and the statuses the demonstration moved on
                r = db.execute("SELECT value FROM settings WHERE key='demo_actions'").fetchone()
                for aid in (json.loads(r["value"]) if r else []):
                    c += db.execute("DELETE FROM actions WHERE id=?", (aid,)).rowcount
                db.execute("DELETE FROM settings WHERE key='demo_actions'")
            if src == "standards_hub":
                r = db.execute("SELECT value FROM settings WHERE key='demo_moved'").fetchone()
                for iid, frm in (json.loads(r["value"]) if r else []):
                    db.execute("UPDATE kit_items SET status=? WHERE id=?", (frm, iid))
                db.execute("DELETE FROM settings WHERE key='demo_moved'")
    if page in OTHER:
        t, w = OTHER[page]
        if t == "audit_plan":
            c += db.execute("DELETE FROM audit_findings WHERE created_by='demo'").rowcount
        c += db.execute("DELETE FROM %s WHERE %s" % (t, w)).rowcount
    if page == "weekly_kpi":
        c += db.execute("DELETE FROM kpi_readings WHERE method='seed'").rowcount + db.execute("DELETE FROM kpi_deck").rowcount
        c += db.execute("DELETE FROM txn_daily WHERE uploaded_by='starter set'").rowcount + db.execute("DELETE FROM txn_hourly WHERE uploaded_by='starter set'").rowcount
    if not summary(db):
        db.execute("DELETE FROM settings WHERE key='demo_loaded'")
    return c
