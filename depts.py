"""EcoCash departments, taken from the FY26 YTD Fintech ERCO presentation (shared services and functions), and the rules that place a control or risk
owner (a job title in the risk assessment workbook) in a department. Fraud sits under Compliance and ML/CTF: EcoCash has no Head of Fraud."""
import re

# code, name, owner as named in the ERCO report, keywords (matched against the first owner named, then the whole text); earlier departments win
DEPARTMENTS = [
    ("CYB", "Cyber Security", "C. Mutanga", ("cyber", "is security", "it security", "information security", "infosec", "soc", "ciso", "security operations", "vulnerab")),
    ("CMP", "Compliance and ML/CTF", "M. Rupondo", ("compliance", "dpo", "data protection", "money laundering", "mlro", "ctf", "aml", "fraud", "regulatory")),
    ("RSK", "Risk", "T. Nyemba", ("chief risk", "enterprise risk", "head risk", "risk", "grc", "erm")),
    ("BCM", "Business Continuity", "R. Muchecheterwa", ("bcms", "business continuity", "bcp", "crisis", "resilien", "exercise management")),
    ("ASS", "Business Assurance", "R. Rusike", ("internal audit", "assurance", "audit")),
    ("LEG", "Legal and Company Secretarial", "R. Mhlanga", ("legal", "company secretary", "litigation")),
    ("SHE", "Safety, Health and Environment", "K. Nyathi", ("hse", "safety", "health", "environment")),
    ("SEC", "Security and Forensics", "K. Ncube", ("physical security", "forensic", "investigation", "bribery", "security")),
    ("PNC", "People and Culture", "R. Zhou", ("people & culture", "people and culture", "people &", "hr", "human", "training", "talent")),
    ("FIN", "Finance", "T. Nyasha", ("finance", "treasury", "procurement", "tax", "accounting", "cfo")),
    ("CXE", "Customer Experience", "S. Ndoro", ("customer", "cxe", "contact cent", "call cent", "operations")),
    ("COM", "Commercial", "G. Tsongorera", ("commercial", "merchant", "product", "marketing", "communications", "corporate affairs", "sales", "partnership", "agent")),
    ("TEC", "Technical Services", "E. Chaduka", ("cto", "it operations", "cloud", "infrastructure", "network", "vendor management", "pmo", "project management", "change management", "technical", "platform", "architect", "devops", "it ")),
]
UNASSIGNED = "Unassigned"
NAMES = [d[1] for d in DEPARTMENTS]


def _first(text):
    return re.split(r"\s*/\s*", text.strip())[0] if text else ""


def dept_of(owner):
    """The department for an owner written as a job title. 'CTO / IT Operations' is judged by its first part ('CTO'); if that matches nothing the whole text is tried."""
    t = re.sub(r"\s+", " ", str(owner or "")).strip().lower()
    if not t or t in ("none", "n/a", "-"):
        return UNASSIGNED
    segs = [x.strip() for x in re.split(r"\s*/\s*", t)]
    if "it" in segs and _first(t) in ("facilities", "it"):  # 'Facilities / IT' is run by IT
        return "Technical Services"
    for part in (_first(t), t):
        padded = " " + part + " "
        if "it operations" in part or part.startswith("it ") or part in ("it", "cto"):  # 'IT Operations' is Technical Services even though it contains 'operations'
            return "Technical Services"
        for code, name, _, keys in DEPARTMENTS:
            if any((" " + k + " " in padded or k in part) if len(k) > 4 else re.search(r"\b" + re.escape(k) + r"\b", part) for k in keys):
                return name
    return UNASSIGNED


def dept_for_control(owner, ref, ref_dept, risk_owner):
    """(department, reason) for one control row. 1) its own owner; 2) the department of the same control owned in another risk; 3) the owner of the risk it protects.
    Every control therefore finds a department, and the reason says how, so nothing is left Unassigned without an explanation."""
    d = dept_of(owner)
    if d != UNASSIGNED:
        return d, "owner"
    if ref and ref_dept.get(ref):
        return ref_dept[ref], "same control owned elsewhere"
    d = dept_of(risk_owner)
    if d != UNASSIGNED:
        return d, "risk owner"
    return UNASSIGNED, "no owner anywhere"


def ref_departments(rows):
    """ref -> the most common department among rows of that control that have an owner. rows: (owner, ref)."""
    from collections import Counter
    c = {}
    for owner, ref in rows:
        d = dept_of(owner)
        if d != UNASSIGNED and ref:
            c.setdefault(ref, Counter())[d] += 1
    return {r: v.most_common(1)[0][0] for r, v in c.items()}


def seed(db):
    for i, (code, name, owner, _) in enumerate(DEPARTMENTS):
        db.execute("INSERT OR IGNORE INTO departments(code,name,owner,grp,sort) VALUES(?,?,?,?,?)", (code, name, owner, "ERCO functions and shared services", i))
