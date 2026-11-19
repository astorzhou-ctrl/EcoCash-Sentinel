"""EcoCash Sentinel DEMO mode: a separate copy filled with INVENTED data, safe to show reviewers or put behind a public tunnel.

    py demo.py            start (the first time it builds the demo data, then serves)
    py demo.py --fresh    throw the demo data away and build it again

It never touches your real data folder: everything lives in the folder  demo_data  next to this file.
The sign-in details are printed and saved in  demo_data/DEMO_LOGINS.txt  (new random passwords each time the demo data is built)."""
import datetime
import http.cookiejar
import json
import os
import random
import secrets
import shutil
import sqlite3
import string
import sys
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(ROOT, "demo_data")
sys.path.insert(0, ROOT)
if "--fresh" in sys.argv and os.path.isdir(DEMO):
    shutil.rmtree(DEMO)
os.environ["SENTINEL_DATA"] = DEMO  # must be set before the application reads its settings
os.environ.setdefault("SENTINEL_NO_BROWSER", "1")
from sentinel import config, server  # noqa: E402

TODAY = datetime.date.today()
D = lambda n: str(TODAY + datetime.timedelta(days=n))


def gen_pw():
    while True:
        p = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits + "#$%&*+-=?") for _ in range(16))
        if any(c.islower() for c in p) and any(c.isupper() for c in p) and sum(c.isdigit() for c in p) >= 2 and any(c in "#$%&*+-=?" for c in p) and not p[0] in "#$%&*+-=?":
            return p


class Client:
    def __init__(self, port):
        self.port = port; self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, data=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=json.dumps(data).encode() if data is not None else None, headers={"Content-Type": "application/json", "X-Sentinel": "1"})
        try:
            with self.op.open(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    def ok(self, method, path, data=None, what=""):
        s, d = self.call(method, path, data)
        if s != 200:
            print("  ! %s failed (%s): %s" % (what or path, s, d.get("message") or d))
        return d if s == 200 else None


RISKS = [  # title, category, owner, inherent L,C, residual L,C, final status, root cause, treatment, treatment date offset (days)
    ("SIM-swap takeover of customer wallets", "Fraud", "Head of Compliance and ML/CTF", 5, 5, 4, 4, "approved", "Weak identity checks at SIM replacement", "Add a cooling-off period and out-of-band confirmation for SIM replacements", 45),
    ("Agent float shortage in rural areas", "Operational", "Head of Agent Network", 4, 4, 3, 4, "approved", "Late float top-ups and uneven agent coverage", "Automate float alerts and add two super-agents", 60),
    ("Core payments platform outage", "Technology", "Head of Technology", 4, 5, 3, 4, "approved", "Single data-centre dependency", "Test the failover quarterly and add a second site", 90),
    ("Ransomware on corporate systems", "Cyber", "Head of IT Security", 4, 5, 3, 3, "approved", "Unpatched servers and weak email filtering", "Patch within 14 days and enforce phishing-resistant sign-in", 30),
    ("Late regulatory returns", "Regulatory", "Head of Compliance", 3, 4, 2, 3, "approved", "Manual preparation across teams", "Create a returns calendar with owners and escalation", 20),
    ("Third-party payment gateway failure", "Third party", "Head of Partnerships", 4, 4, 3, 4, "approved", "No tested exit or fallback", "Contract a secondary gateway and test it", 75),
    ("Customer data leak by an insider", "Cyber", "Head of IT Security", 3, 5, 3, 4, "reviewed", "Broad access to customer records", "Role-based access and monthly access reviews", 50),
    ("Exchange-rate losses on settlements", "Financial", "Head of Treasury", 4, 3, 3, 3, "reviewed", "Settlement timing mismatch", "Hedge daily settlement exposure", 40),
    ("Loss of key people in risk and fraud teams", "People", "Head of HR", 3, 3, 2, 3, "submitted", "Few successors identified", "Succession plans for ten key roles", 120),
    ("Social-media misinformation about the wallet", "Reputation", "Head of Communications", 3, 3, 2, 2, "submitted", "Slow response to rumours", "Rapid-response playbook and monitoring", 25),
    ("Model drift in fraud-scoring rules", "Model / AI", "Head of Compliance and ML/CTF", 3, 4, 3, 3, "draft", "Rules not revalidated after product changes", "Quarterly model validation", 90),
    ("Product launch without a risk review", "Strategic", "Head of Product", 3, 3, 2, 3, "draft", "No gate in the launch process", "Add a risk sign-off to the launch checklist", 60),
]
CONTROLS = [  # statement, domain, type, owner
    ("Out-of-band confirmation for SIM replacement", "Fraud", "Preventive", "Head of Compliance and ML/CTF"), ("Real-time transaction monitoring rules", "Fraud", "Detective", "ML/CTF Analytics Lead"),
    ("Daily agent float reconciliation", "Operations", "Detective", "Head of Agent Network"), ("Quarterly failover test of the payments platform", "Technology", "Corrective", "Head of Technology"),
    ("Monthly privileged-access review", "Technology", "Detective", "Head of IT Security"), ("Backups tested and restored each quarter", "Technology", "Corrective", "Head of Technology"),
    ("Regulatory returns calendar with sign-off", "Compliance", "Preventive", "Head of Compliance"), ("Vendor performance and exit review", "Third party", "Detective", "Head of Partnerships"),
]
SCORES = [2, 3, 2, 5, 3, 8, 1, 4, 3, 9, 2, 5, 6, 2, 3, 7]


def populate(port, logins, tmp):
    adm = Client(port)
    s, d = adm.call("POST", "/api/auth/login", {"username": "admin", "password": tmp}); assert s == 200, d
    logins["admin"] = gen_pw(); assert adm.call("POST", "/api/auth/change-password", {"current_password": tmp, "new_password": logins["admin"]})[0] == 200
    roles = {r["name"]: r["id"] for r in adm.ok("GET", "/api/roles")["roles"]}
    people = [("reviewer", "Demo Reviewer (read-only)", "Auditor (read-only)", "all"), ("demo.head", "Hannah Head (demo)", "Head of Risk", "all"), ("demo.head2", "Henry Head (demo)", "Head of Risk", "all"), ("demo.manager", "Maria Manager (demo)", "Risk Manager", "all")]
    cl = {}
    for u, name, role, scope in people:
        r = adm.ok("POST", "/api/users", dict(full_name=name, username=u, email=u.replace(".", "_") + "@demo.invalid", role_ids=[roles[role]], data_scope=scope, department="Risk Office"), "create " + u)
        c = Client(port); assert c.call("POST", "/api/auth/login", {"username": u, "password": r["temp_password"]})[0] == 200
        logins[u] = gen_pw(); assert c.call("POST", "/api/auth/change-password", {"current_password": r["temp_password"], "new_password": logins[u]})[0] == 200; cl[u] = c
    head, head2, mgr = cl["demo.head"], cl["demo.head2"], cl["demo.manager"]
    ids = {}
    for n_, (t, cat, own, il, ic, rl, rc, final, rcse, trt, off) in enumerate(RISKS):
        emv = [2400000, 1500000, 3200000, 2800000, 450000, 1900000, 1700000, 900000, 350000, 280000, 600000, 400000][n_]
        r = mgr.ok("POST", "/api/risks", dict(title=t, category=cat, owner_name=own, root_cause=rcse, treatment=trt, action_date=D(off), inh_l=il, inh_c=ic, res_l=rl, res_c=rc, emv_i=emv), t)
        if not r:
            continue
        rid = r["risk"]["id"]; ids[t] = rid; path = ["submitted", "reviewed", "approved"][:{"draft": 0, "submitted": 1, "reviewed": 2, "approved": 3}[final]]
        for to in path:
            who = mgr if to == "submitted" else head if to == "reviewed" else head2
            who.ok("POST", "/api/risks/%d/status" % rid, {"to": to, "comment": "Approved for the demo register; the Board is informed of any risk above appetite."}, "%s -> %s" % (t[:25], to))
    for i, (t, rid) in enumerate(list(ids.items())[:8]):  # two controls per risk for the first eight risks
        for j in range(2):
            c = CONTROLS[(i + j) % len(CONTROLS)]
            r = head.ok("POST", "/api/controls", dict(risk_id=rid, ref="DEMO-%02d%d" % (i + 1, j + 1), statement=c[0], domain=c[1], ctype=c[2], owner=c[3], ice=round(random.choice([0.4, 0.5, 0.6]), 1)), "control")
            if r:
                sc = SCORES[(i * 2 + j) % len(SCORES)]
                head2.ok("POST", "/api/controls/%d/tests" % r["id"], dict(ttype="operating" if j == 0 else "design", tested_on=D(-random.randint(3, 40)), score=sc, evidence="Sample of 25 items re-performed; %d exception(s) found (invented demo evidence)." % (0 if sc <= 3 else sc - 3)), "test")
    for title, owner, due, pr in [("Issue replacement SIM cooling-off policy", "Head of Compliance and ML/CTF", 14, "High"), ("Close audit finding on access reviews", "Head of IT Security", 21, "Medium"), ("Brief the Board on ransomware readiness", "Head of Risk", 10, "Medium"), ("Complete the returns calendar", "Head of Compliance", 7, "Low")]:
        head.ok("POST", "/api/actions", dict(title=title, description="Invented demo action.", source="board" if "Board" in title else "audit", owner_name=owner, due_date=D(due), priority=pr), title)
    head.ok("POST", "/api/actions/convert-treatments")
    con = sqlite3.connect(os.path.join(DEMO, "sentinel.db"))  # make a few actions late so escalation and ageing have something to show
    con.execute("UPDATE actions SET due_date=? WHERE id IN (SELECT id FROM actions WHERE status='open' ORDER BY id LIMIT 2)", (D(-4),)); con.execute("UPDATE actions SET due_date=? WHERE id IN (SELECT id FROM actions WHERE status='open' ORDER BY id DESC LIMIT 1)", (D(-9),)); con.commit(); con.close()
    head.ok("POST", "/api/actions/escalate")
    aid = (head.ok("GET", "/api/actions?status=open")["actions"] or [{}])[-1].get("id")
    if aid:
        mgr.ok("POST", "/api/actions/%d/status" % aid, {"to": "awaiting_verification", "evidence": "Policy issued and communicated to all agents (invented demo evidence)."}, "submit action"); head2.ok("POST", "/api/actions/%d/status" % aid, {"to": "closed"}, "close action")
    # indicators with twelve weeks of invented history, one KRI that is red
    rnd = random.Random(7)
    kpis = [("D_SUCCESS", "Transaction success rate", "Operations", "%", "up", 96, lambda i: 95.5 + rnd.random() * 1.2 if i < 11 else 88.9), ("D_FRAUD", "Fraud cases per week", "Fraud", "cases", "down", 40, lambda i: 55 - i * 1.2 + rnd.random() * 6),
            ("D_FLOAT", "Agent float days of cover", "Operations", "days", "up", 3, lambda i: 2.2 + i * 0.07 + rnd.random() * 0.4), ("D_UPTIME", "Platform availability", "Technology", "%", "up", 99.9, lambda i: 99.2 + rnd.random() * 0.75), ("D_PATCH", "Critical patches applied in 14 days", "Technology", "%", "up", 95, lambda i: 78 + i * 1.3 + rnd.random() * 3)]
    for code, name, grp, unit, better, target, f in kpis:
        head.ok("POST", "/api/kpi/catalog", dict(code=code, name=name, grp=grp, unit=unit, freq="weekly", better=better, target=target, decimals=1, source="Invented demo data"), code)
        for i in range(12):
            head.ok("POST", "/api/kpi/readings", dict(code=code, period=D(-7 * (11 - i)), value=round(f(i), 1)), code)
    for code, name, unit, better, amber, red, f in [("D_KRI_SIMSWAP", "SIM-swap attempts per week", "cases", "down", 25, 40, lambda i: 12 + i * 2.2 + rnd.random() * 1.5), ("D_KRI_LOGIN", "Failed admin sign-ins per day", "count", "down", 30, 60, lambda i: 18 + rnd.random() * 8)]:
        head.ok("POST", "/api/kpi/catalog", dict(code=code, kind="kri", name=name, grp="Fraud" if "SIM" in code else "Technology", unit=unit, freq="weekly", better=better, amber=amber, red=red, decimals=0, source="Invented demo data"), code)
        for i in range(12):
            head.ok("POST", "/api/kpi/readings", dict(code=code, period=D(-7 * (11 - i)), value=round(f(i))), code)
    for grp, title, codes, ct in [("Operations", "Transaction success rate (%)", ["D_SUCCESS"], "line"), ("Operations", "Agent float days of cover", ["D_FLOAT"], "column"), ("Fraud", "Fraud cases per week", ["D_FRAUD"], "column"), ("Technology", "Availability and patching (%)", ["D_UPTIME", "D_PATCH"], "line")]:
        head.ok("POST", "/api/kpi/charts", dict(grp=grp, title=title, codes=codes, ctype=ct, mode="series", periods=12), title)
    for t, kind, cat, sev, off, loss, rec, pdb in [("Wallet takeover after SIM swap (3 customers)", "loss", "Fraud", "High", 3, 1800, 600, 0), ("Mobile app slowdown during salary day", "incident", "Technology", "Medium", 6, 0, 0, 0), ("Agent mis-keyed a customer's number (caught before payout)", "near_miss", "Operational", "Low", 2, 0, 0, 0), ("Staff laptop lost with unencrypted customer file", "incident", "Personal data", "High", 1, 0, 0, 1)]:
        head.ok("POST", "/api/incidents", dict(title=t, kind=kind, category=cat, severity=sev, occurred_on=D(-off), description="Invented demo event.", owner="Head of Risk", gross_loss=loss, recovered=rec, pdb=pdb, risk_id=ids.get("SIM-swap takeover of customer wallets") if cat == "Fraud" else None), t)
    head.ok("POST", "/api/tracker/sync")
    con = sqlite3.connect(os.path.join(DEMO, "sentinel.db")); con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('demo_mode','1')"); con.commit(); con.close()  # marks the system as a demo (a red label in the top bar)
    return logins


def main():
    port = config.PORT
    first = server.prepare()
    marker = os.path.join(DEMO, ".demo_ready")
    logins = {}
    if not os.path.exists(marker):
        print("Building the demo data (invented risks, controls, actions, indicators and incidents). This takes about a minute...")
        srv = server.make("127.0.0.1", 0); tp = srv.server_address[1]; threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            populate(tp, logins, first)
            from sentinel import db as _dbm, demo_seed
            _c = _dbm.connect(); demo_seed.load(_c); _c.commit(); _c.close()  # every module section gets invented records, tagged 'demo'
        finally:
            srv.shutdown(); srv.server_close()
        try:
            os.remove(os.path.join(DEMO, "FIRST_RUN_ADMIN.txt"))
        except OSError:
            pass
        with open(os.path.join(DEMO, "DEMO_LOGINS.txt"), "w") as f:
            f.write("ECOCASH SENTINEL DEMO: sign-in details (all data is invented)\n\nReviewers (read-only):   reviewer      password: %s\nFull access (can change): demo.head    password: %s\nSecond approver:          demo.head2   password: %s\nRisk Manager:             demo.manager password: %s\nAdministrator:            admin        password: %s\n" % tuple(logins[k] for k in ("reviewer", "demo.head", "demo.head2", "demo.manager", "admin")))
        open(marker, "w").write("ready")
    print("=" * 72); print(" EcoCash Sentinel DEMO (invented data)  -  http://%s:%d/login" % (config.HOST, port), flush=True); print("-" * 72)
    print(open(os.path.join(DEMO, "DEMO_LOGINS.txt")).read().strip()); print("-" * 72)
    print(" The logins are also saved in demo_data\\DEMO_LOGINS.txt. Press Ctrl+C to stop."); print("=" * 72)
    try:
        server.serve()
    except KeyboardInterrupt:
        print("\nDemo stopped.")


if __name__ == "__main__":
    main()
