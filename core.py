"""Core logic: catalog, roles and permissions, audit chain, sessions and the sign-in rules (BRD section 5)."""
import hashlib
import json
import os
import secrets

from . import config, db as dbm
from .db import now, plus, parse
from .security import hash_password, verify_password, DUMMY_HASH, check_password, new_token, hash_token, temp_password
from .web import HTTPError

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog.json"), encoding="utf-8") as _f:
    CATALOG = json.load(_f)
MODULES = {m["key"]: m for m in CATALOG["modules"]}
ACTIONS = ["view", "create", "edit", "delete", "approve", "export"]
SCOPES = ["own", "function", "business_unit", "all"]
LIVE = {"access_management", "administration", "command_center", "risk_register", "heat_map_portfolio", "performance_analytics", "daily_tracker", "risk_appetite", "assessment_studio", "board_hub", "weekly_kpi", "kri_monitor", "incidents_losses", "control_library_testing", "actions_issues", "ai_insights", "sentinel_copilot", "ai_governance", "strategy_map", "scenario_lab", "emerging_radar", "audit_workspace", "fraud_intelligence", "speak_up_cases", "obligations_hub", "regulatory_change", "privacy_breach_clock", "policy_hub", "standards_hub", "isms_iso_27001", "bcms_iso_22301", "aims_iso_42001", "bcm_studio", "third_party_risk", "cyber_it_risk", "crisis_room", "predictive_analytics", "document_intelligence", "workflow_designer", "integration_hub", "data_reports"}
ALL = list(ACTIONS)

# ------------------------------------------------------------------ roles
SEED_ROLES = [
    ("System Administrator", "Users, roles, sign-in policy, configuration, backups. No access to risk data by default (separation of duties).", {"access_management": ALL, "administration": ALL}),
    ("Head of Risk", "Methodology, approvals and all risk data.", {k: ALL for k in MODULES if k not in ("access_management", "administration")}),
    ("Risk Manager", "All risk data, no override.", {k: ["view", "create", "edit", "export"] for k in MODULES if k not in ("access_management", "administration")}),
    ("Risk Owner", "Own function.", {"command_center": ["view"], "daily_tracker": ["view", "create", "edit"], "risk_register": ["view", "create", "edit"], "assessment_studio": ["view", "create", "edit"], "heat_map_portfolio": ["view"],
                                    "actions_issues": ["view", "create", "edit"], "kri_monitor": ["view"], "incidents_losses": ["view", "create"], "control_library_testing": ["view"], "obligations_hub": ["view"]}),
    ("Control Owner", "Own controls.", {"command_center": ["view"], "daily_tracker": ["view", "create", "edit"], "control_library_testing": ["view", "edit"], "actions_issues": ["view", "create", "edit"], "risk_register": ["view"]}),
    ("Compliance Officer", "Obligations, privacy and incidents.", {k: ["view", "create", "edit", "export"] for k in ("obligations_hub", "regulatory_change", "privacy_breach_clock", "policy_hub", "incidents_losses", "standards_hub")} | {"command_center": ["view"], "daily_tracker": ["view", "create", "edit"]}),
    ("Auditor (read-only)", "Read and export everything except administration.", {k: ["view", "export"] for k in MODULES if k not in ("access_management", "administration")}),
    ("Executive and Board", "Dashboards and Board packs.", {k: ["view", "export"] for k in ("command_center", "performance_analytics", "board_hub", "strategy_map", "risk_appetite", "heat_map_portfolio", "kri_monitor")} | {"board_hub": ["view", "export", "approve"]}),
]


def seed(db):
    """Create the system roles and the first administrator on a fresh database. Returns the admin temp password or None."""
    if db.execute("SELECT COUNT(*) c FROM roles").fetchone()["c"] == 0:
        for name, desc, perms in SEED_ROLES:
            db.execute("INSERT INTO roles(name,description,is_system,permissions,created_at) VALUES(?,?,1,?,?)", (name, desc, json.dumps(perms), now()))
    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0:
        pw = temp_password()
        pol = dbm.get_policy(db)
        uid = db.execute("INSERT INTO users(username,full_name,email,department,job_title,status,password_hash,must_change,temp_expires_at,created_at) VALUES('admin','System Administrator','admin@sentinel.local','IT','System Administrator','invited',?,1,?,?)",
                         (hash_password(pw), plus(hours=pol["temp_password_hours"]), now())).lastrowid
        rid = db.execute("SELECT id FROM roles WHERE name='System Administrator'").fetchone()["id"]
        db.execute("INSERT INTO user_roles(user_id,role_id) VALUES(?,?)", (uid, rid))
        audit(db, "system.first_run", None, "access_management", "First administrator created")
        db.commit()
        return pw
    db.commit()
    return None


def permissions_of(db, user_id):
    perms = {}
    for r in db.execute("SELECT r.permissions FROM roles r JOIN user_roles ur ON ur.role_id=r.id WHERE ur.user_id=?", (user_id,)):
        for mod, acts in json.loads(r["permissions"]).items():
            perms.setdefault(mod, set()).update(acts)
    return perms


def role_names(db, user_id):
    return [r["name"] for r in db.execute("SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id=r.id WHERE ur.user_id=? ORDER BY r.name", (user_id,))]


# ------------------------------------------------------------------ audit (hash chain)
def _audit_hash(prev, ts, uid, uname, event, module, detail, ip):
    payload = json.dumps([ts, uid, uname, event, module, detail, ip], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev + payload).encode("utf-8")).hexdigest()


def audit(db, event, user=None, module="", detail="", ip="", username=None):
    last = db.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = last["hash"] if last else "GENESIS"
    ts = now()
    uid = user["id"] if user is not None else None
    uname = username if username is not None else (user["username"] if user is not None else None)
    h = _audit_hash(prev, ts, uid, uname, event, module, detail, ip)
    db.execute("INSERT INTO audit(ts,user_id,username,event,module,detail,ip,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?,?)", (ts, uid, uname, event, module, detail, ip, prev, h))


def verify_audit(db):
    prev, n = "GENESIS", 0
    for r in db.execute("SELECT * FROM audit ORDER BY id"):
        if r["prev_hash"] != prev or r["hash"] != _audit_hash(prev, r["ts"], r["user_id"], r["username"], r["event"], r["module"], r["detail"], r["ip"]):
            return {"ok": False, "checked": n, "broken_at": r["id"]}
        prev = r["hash"]; n += 1
    return {"ok": True, "checked": n, "broken_at": None}


# A module added after a role was created gives that role the same actions as an existing sister module (so upgrades never lock people out).
NEW_MODULE_MIRRORS = {"weekly_kpi": ("kri_monitor", {"Executive and Board": ["view", "export"]}), "ai_insights": ("risk_register", {"Executive and Board": ["view"]})}


AI_ROLES = {  # who may use the Copilot, and who governs AI (BRD 13.31 and 13.34: AI owner, Head of Risk, CTO, auditors)
    "sentinel_copilot": {"Head of Risk": ["view", "create", "edit", "approve", "export"], "Risk Manager": ["view", "create", "edit", "export"], "Compliance Officer": ["view", "create", "edit", "export"], "Risk Owner": ["view", "create"], "Control Owner": ["view", "create"], "Auditor (read-only)": ["view", "create"], "Executive and Board": ["view", "create"]},
    "ai_governance": {"System Administrator": ["view", "edit", "approve", "export"], "Head of Risk": ["view", "export"], "Risk Manager": ["view"], "Auditor (read-only)": ["view", "export"], "Executive and Board": ["view"]},
}


ADV_MODULES = ("strategy_map", "scenario_lab", "emerging_radar", "audit_workspace", "fraud_intelligence", "speak_up_cases")
F, V, VE, VC = ["view", "create", "edit", "delete", "approve", "export"], ["view"], ["view", "export"], ["view", "create"]
ADV_RIGHTS = {  # who may do what in the six advanced modules (BRD 9.4, 9.9, 9.10, 9.13, 9.16, 9.17)
    "strategy_map": {"Head of Risk": ["view", "create", "edit", "delete", "export"], "Risk Manager": ["view", "edit", "export"], "Risk Owner": V, "Control Owner": V, "Compliance Officer": V, "Auditor (read-only)": V, "Internal Auditor": V, "Fraud Analyst": V, "Executive and Board": VE},
    "scenario_lab": {"Head of Risk": ["view", "create", "edit", "delete", "export"], "Risk Manager": ["view", "create", "edit", "export"], "Risk Owner": VC, "Compliance Officer": ["view", "create", "edit"], "Control Owner": V, "Auditor (read-only)": V, "Internal Auditor": V, "Fraud Analyst": V, "Executive and Board": VE},
    "emerging_radar": {"Head of Risk": F, "Risk Manager": ["view", "create", "edit", "export"], "Compliance Officer": VC, "Risk Owner": V, "Control Owner": V, "Auditor (read-only)": V, "Internal Auditor": V, "Fraud Analyst": V, "Executive and Board": VE},
    "audit_workspace": {"Internal Auditor": F, "Head of Risk": VE, "Risk Manager": V, "Risk Owner": V, "Control Owner": V, "Compliance Officer": V, "Auditor (read-only)": VE, "Executive and Board": VE},
    "fraud_intelligence": {"Compliance Officer": ["view", "create", "edit", "delete", "export"], "Fraud Analyst": ["view", "create", "edit", "delete", "export"], "Head of Risk": VE, "Risk Manager": V, "Auditor (read-only)": VE, "Internal Auditor": V, "Executive and Board": VE},
    "speak_up_cases": {"Case Officer": ["view", "create", "edit", "export"], "Head of Risk": ["view", "approve"], "Executive and Board": V, "Auditor (read-only)": V, "Internal Auditor": V},
}
NEW_ROLES = {"Internal Auditor": "Internal audit: manages the audit plan, findings and grades; read-only on the rest of the platform.", "Fraud Analyst": "Fraud analyst: works fraud alerts and cases; read-only on the rest of the platform.", "Case Officer": "Speak-up case officer: restricted access to tip-off cases only (also needs an access grant)."}


FULL, MGR, CE, VE, V0 = ["view", "create", "edit", "delete", "approve", "export"], ["view", "create", "edit", "export"], ["view", "create", "edit"], ["view", "export"], ["view"]
OWN = {"Risk Owner": V0, "Control Owner": V0, "Fraud Analyst": V0}  # read-only baseline for the working roles
AUD = {"Executive and Board": VE, "Auditor (read-only)": VE, "Internal Auditor": VE}


def _g(**kw):
    d = {}
    for k, v in kw.items():
        d[k.replace("_", " ")] = v
    return d


KIT_RIGHTS = {}
for _m in ("obligations_hub", "regulatory_change", "privacy_breach_clock", "policy_hub"):
    KIT_RIGHTS[_m] = dict(OWN, **AUD, **{"Compliance Officer": FULL, "Head of Risk": FULL, "Risk Manager": MGR})
KIT_RIGHTS["policy_hub"].update({"Case Officer": V0, "System Administrator": V0})  # every member of staff attests a policy
for _m in ("standards_hub", "isms_iso_27001", "bcms_iso_22301", "aims_iso_42001"):
    KIT_RIGHTS[_m] = dict(OWN, **AUD, **{"Head of Risk": FULL, "Risk Manager": MGR, "Compliance Officer": MGR})
KIT_RIGHTS["bcm_studio"] = dict(OWN, **AUD, **{"Head of Risk": FULL, "Risk Manager": MGR, "Risk Owner": CE, "Control Owner": CE, "Compliance Officer": CE})
KIT_RIGHTS["crisis_room"] = dict(OWN, **AUD, **{"Head of Risk": FULL, "Risk Manager": MGR, "Risk Owner": CE, "Control Owner": CE, "Compliance Officer": CE})
KIT_RIGHTS["third_party_risk"] = dict(OWN, **AUD, **{"Head of Risk": FULL, "Risk Manager": MGR, "Risk Owner": CE, "Compliance Officer": MGR})
KIT_RIGHTS["cyber_it_risk"] = dict(OWN, **AUD, **{"Head of Risk": FULL, "Risk Manager": MGR, "Control Owner": CE, "Compliance Officer": V0})
KIT_RIGHTS["document_intelligence"] = {"Head of Risk": MGR, "Risk Manager": MGR, "Compliance Officer": CE, "Internal Auditor": CE, "Risk Owner": V0, "Control Owner": V0, "Auditor (read-only)": V0, "Executive and Board": V0}
KIT_RIGHTS["predictive_analytics"] = dict(OWN, **{"Head of Risk": FULL, "Risk Manager": MGR, "Compliance Officer": CE, "Executive and Board": V0, "Auditor (read-only)": V0, "Internal Auditor": V0})
KIT_RIGHTS["workflow_designer"] = {"Head of Risk": ["view", "create", "edit", "approve"], "System Administrator": ["view", "create", "edit"], "Risk Manager": V0}
KIT_RIGHTS["integration_hub"] = {"System Administrator": FULL, "Head of Risk": V0}
KIT_RIGHTS["data_reports"] = {r: ["view", "create", "edit", "delete", "export"] for r in ("Head of Risk", "Risk Manager", "Compliance Officer", "Risk Owner", "Control Owner", "Executive and Board", "Auditor (read-only)", "Internal Auditor", "Fraud Analyst")}
KIT_RIGHTS["data_reports"].update({"Head of Risk": FULL, "System Administrator": ["view", "create", "edit", "delete"]})


def migrate_kit_roles(db):
    """Once: each role's rights in the 17 modules built on the kit and the five platform and intelligence modules. A role not listed for a module loses it."""
    if db.execute("SELECT 1 FROM settings WHERE key='kit_roles_v1'").fetchone():
        return 0
    changed = 0
    for r in db.execute("SELECT id, name, permissions FROM roles").fetchall():
        perms = json.loads(r["permissions"]); dirty = False
        for m, rights in KIT_RIGHTS.items():
            want = rights.get(r["name"])
            if want is not None and sorted(perms.get(m, [])) != sorted(want):
                perms[m] = list(want); dirty = True
            elif want is None and m in perms and r["name"] != "System Administrator" or (want is None and m in perms and m in ("integration_hub", "workflow_designer", "data_reports") and r["name"] == "System Administrator"):
                perms.pop(m); dirty = True
        if dirty:
            db.execute("UPDATE roles SET permissions=? WHERE id=?", (json.dumps(perms), r["id"])); changed += 1
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('kit_roles_v1','1')")
    return changed


def migrate_adv_roles(db):
    """Once: the three new roles, and each role's rights in the six advanced modules."""
    if db.execute("SELECT 1 FROM settings WHERE key='adv_roles_v1'").fetchone():
        return 0
    base = db.execute("SELECT permissions FROM roles WHERE name='Auditor (read-only)'").fetchone()
    base = json.loads(base["permissions"]) if base else {}
    for name, desc in NEW_ROLES.items():
        if not db.execute("SELECT 1 FROM roles WHERE name=?", (name,)).fetchone():
            perms = {} if name == "Case Officer" else {k: ["view"] for k in base}
            db.execute("INSERT INTO roles(name,description,is_system,permissions,created_at) VALUES(?,?,1,?,?)", (name, desc, json.dumps(perms), now()))
    changed = 0
    for r in db.execute("SELECT id, name, permissions FROM roles").fetchall():
        perms = json.loads(r["permissions"]); dirty = False
        for m in ADV_MODULES:
            want = ADV_RIGHTS[m].get(r["name"])
            if want is None and m in perms and r["name"] not in ("System Administrator",) and m == "speak_up_cases":
                perms.pop(m); dirty = True; continue
            if want is not None and sorted(perms.get(m, [])) != sorted(want):
                perms[m] = list(want); dirty = True
            elif want is None and m in perms and m != "speak_up_cases":
                pass
        if dirty:
            db.execute("UPDATE roles SET permissions=? WHERE id=?", (json.dumps(perms), r["id"])); changed += 1
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('adv_roles_v1','1')")
    return changed


def migrate_ai_roles(db):
    changed = 0
    if not db.execute("SELECT 1 FROM settings WHERE key='ai_roles_v2'").fetchone():  # once: AI is controlled by the System Administrator, not by business roles
        for r in db.execute("SELECT id, name, permissions FROM roles").fetchall():
            perms = json.loads(r["permissions"]); cur = perms.get("ai_governance")
            if cur is None:
                continue
            new = AI_ROLES["ai_governance"].get(r["name"]) if r["name"] in AI_ROLES["ai_governance"] else [a for a in cur if a in ("view", "export")]
            if r["name"] == "System Administrator":
                new = AI_ROLES["ai_governance"]["System Administrator"]
            if sorted(new or []) != sorted(cur):
                perms["ai_governance"] = new; db.execute("UPDATE roles SET permissions=? WHERE id=?", (json.dumps(perms), r["id"])); changed += 1
        for r in db.execute("SELECT id, name, permissions FROM roles").fetchall():  # everyone who may use the Copilot can ask it questions, even if an older role gave them view only
            want = AI_ROLES["sentinel_copilot"].get(r["name"])
            if want:
                perms = json.loads(r["permissions"]); cur = set(perms.get("sentinel_copilot", [])); new = sorted(cur | set(want))
                if sorted(cur) != new:
                    perms["sentinel_copilot"] = new; db.execute("UPDATE roles SET permissions=? WHERE id=?", (json.dumps(perms), r["id"])); changed += 1
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('ai_roles_v2','1')")
    for r in db.execute("SELECT id, name, permissions FROM roles").fetchall():
        perms = json.loads(r["permissions"]); dirty = False
        for mod, byrole in AI_ROLES.items():
            if mod not in perms and r["name"] in byrole:
                perms[mod] = byrole[r["name"]]; dirty = True
        if dirty:
            db.execute("UPDATE roles SET permissions=? WHERE id=?", (json.dumps(perms), r["id"])); changed += 1
    return changed


def migrate_roles(db):
    changed = 0
    for r in db.execute("SELECT id, name, permissions FROM roles").fetchall():
        perms = json.loads(r["permissions"]); dirty = False
        for key, (mirror, special) in NEW_MODULE_MIRRORS.items():
            if key not in perms and (mirror in perms or r["name"] in special):
                perms[key] = special.get(r["name"], perms.get(mirror)); dirty = True
        if dirty:
            db.execute("UPDATE roles SET permissions=? WHERE id=?", (json.dumps(perms), r["id"])); changed += 1
    return changed


def outbox(db, to, subject, body, kind):
    db.execute("INSERT INTO outbox(ts,to_addr,subject,body,kind) VALUES(?,?,?,?,?)", (now(), to, subject, body, kind))


# ------------------------------------------------------------------ users and password state
def get_user(db, username):
    return db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE AND deleted_at IS NULL", (username,)).fetchone()


def password_state(user, pol):
    """Return (days_left, expired). days_left is None when the password has never been set by the user."""
    ch = parse(user["password_changed_at"])
    if ch is None:
        return None, bool(user["must_change"])
    left = (ch + __import__("datetime").timedelta(days=pol["password_max_age_days"]) - parse(now())).days
    return left, left < 0


def needs_password_change(user, pol):
    if user["must_change"]:
        return True
    left, expired = password_state(user, pol)
    return expired


def revoke_sessions(db, user_id, reason, except_id=None):
    db.execute("UPDATE sessions SET revoked_at=?, revoked_reason=? WHERE user_id=? AND revoked_at IS NULL AND id IS NOT ?", (now(), reason, user_id, except_id))


def create_session(db, user, ip, ua):
    pol = dbm.get_policy(db)
    rows = db.execute("SELECT id FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY id DESC", (user["id"], now())).fetchall()
    for r in rows[max(pol["max_sessions"] - 1, 0):]:
        db.execute("UPDATE sessions SET revoked_at=?, revoked_reason='replaced by a newer sign-in' WHERE id=?", (now(), r["id"]))
    token = new_token()
    db.execute("INSERT INTO sessions(user_id,token_hash,created_at,last_seen,expires_at,ip,user_agent,mfa_state) VALUES(?,?,?,?,?,?,?,?)",
               (user["id"], hash_token(token), now(), now(), plus(hours=pol["session_hours"]), ip, ua, mfa_state_for(db, user, pol)))
    return token


def mfa_required(db, user, pol):
    """Two-step sign-in is switched on for a person by the System Administrator, either for their role or for them alone. People cannot switch it on or off themselves."""
    if user["mfa_admin"]:
        return True
    need_roles = set(pol.get("mfa_required_roles") or [])
    return bool(need_roles and need_roles & set(role_names(db, user["id"])))


def mfa_state_for(db, user, pol):
    """'verify' when the user has a second factor, 'enroll' when policy requires one they have not set up, otherwise 'ok'. Every way of getting a session (password, reset link) goes through this."""
    if user["mfa_enabled"]:
        return "verify"
    return "enroll" if mfa_required(db, user, pol) else "ok"


def load_session(db, token):
    if not token:
        return None
    s = db.execute("SELECT * FROM sessions WHERE token_hash=?", (hash_token(token),)).fetchone()
    if not s or s["revoked_at"] or s["expires_at"] <= now():
        return None
    pol = dbm.get_policy(db)
    if (parse(now()) - parse(s["last_seen"])).total_seconds() > pol["idle_minutes"] * 60:
        db.execute("UPDATE sessions SET revoked_at=?, revoked_reason='idle timeout' WHERE id=?", (now(), s["id"]))
        db.commit()
        return None
    u = db.execute("SELECT * FROM users WHERE id=?", (s["user_id"],)).fetchone()
    if not u or u["deleted_at"] or u["status"] not in ("active", "invited"):
        return None
    if u["access_expires"] and u["access_expires"] < now()[:10]:
        return None
    if (parse(now()) - parse(s["last_seen"])).total_seconds() > 30:
        db.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now(), s["id"]))
        db.commit()
    return u, s


# ------------------------------------------------------------------ sign-in
def _fail(db, status, error, message, **extra):
    db.commit()  # keep the failed-attempt counters even though the request ends with an error
    raise HTTPError(status, error, message, **extra)


def authenticate(db, username, password, ip, ua):
    pol = dbm.get_policy(db)
    username = (username or "").strip()
    if not username or not password:
        raise HTTPError(400, "missing", "Enter your username and password.")
    maxf = pol["max_failed_attempts"]
    # throttle by address
    ipk = "ip:" + ip
    row = db.execute("SELECT * FROM login_attempts WHERE key=?", (ipk,)).fetchone()
    if row and row["count"] >= pol["ip_fail_limit"] and row["last_at"] > dbm.minus(minutes=10):
        raise HTTPError(429, "throttled", "Too many failed sign-ins from this device. Try again in a few minutes.")
    user = get_user(db, username)
    if user is None:
        verify_password(password, DUMMY_HASH)  # same time as a real check
        key = "u:" + hashlib.sha256((ip + "|" + username.lower()).encode()).hexdigest()
        r = db.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
        window = dbm.minus(minutes=pol["unknown_user_window_minutes"])
        count = (r["count"] + 1) if (r and r["first_at"] > window) else 1
        first = r["first_at"] if (r and r["first_at"] > window) else now()
        db.execute("INSERT OR REPLACE INTO login_attempts(key,count,first_at,last_at) VALUES(?,?,?,?)", (key, count, first, now()))
        _ip_fail(db, ipk)
        audit(db, "auth.login_failed", None, "access_management", "Unknown username", ip, username)
        if count >= maxf:
            _fail(db, 423, "locked", "This account is locked.")
        _fail(db, 401, "bad_credentials", "Incorrect password.", attempts_remaining=maxf - count)
    ok = verify_password(password, user["password_hash"])
    if user["status"] == "locked":
        audit(db, "auth.login_blocked", user, "access_management", "Attempt on a locked account", ip)
        _fail(db, 423, "locked", "This account is locked.")
    if not ok:
        n = user["failed_attempts"] + 1
        db.execute("UPDATE users SET failed_attempts=? WHERE id=?", (n, user["id"]))
        _ip_fail(db, ipk)
        audit(db, "auth.login_failed", user, "access_management", "Wrong password (%d of %d)" % (n, maxf), ip)
        if n >= maxf:
            db.execute("UPDATE users SET status='locked', locked_at=? WHERE id=?", (now(), user["id"]))
            audit(db, "auth.locked", user, "access_management", "Account locked after %d failed attempts" % maxf, ip)
            for a in db.execute("SELECT u.email FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name='System Administrator' AND u.status IN ('active','invited') AND u.deleted_at IS NULL AND u.email IS NOT NULL"):
                outbox(db, a["email"], "Sentinel: account locked (%s)" % user["username"], "The account %s was locked at %s after %d failed sign-in attempts from %s. Unlock it or reset the password in Access Management." % (user["username"], now(), maxf, ip), "alert")
            _fail(db, 423, "locked", "This account is locked.")
        _fail(db, 401, "bad_credentials", "Incorrect password.", attempts_remaining=maxf - n)
    # password correct: now report account problems
    if user["status"] == "deactivated":
        _fail(db, 403, "inactive", "This account is not active. Contact your administrator.")
    if user["access_expires"] and user["access_expires"] < now()[:10]:
        _fail(db, 403, "access_expired", "Access to this account has expired. Contact your administrator.")
    if user["must_change"] and user["temp_expires_at"] and user["temp_expires_at"] < now():
        _fail(db, 403, "temp_expired", "The temporary password has expired. Ask your administrator to reset it.")
    db.execute("UPDATE users SET failed_attempts=0, last_login_at=?, last_login_ip=? WHERE id=?", (now(), ip, user["id"]))
    db.execute("DELETE FROM login_attempts WHERE key=?", (ipk,))
    token = create_session(db, user, ip, ua)
    audit(db, "auth.login", user, "access_management", "Signed in", ip)
    user = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return user, token


def _ip_fail(db, ipk):
    r = db.execute("SELECT * FROM login_attempts WHERE key=?", (ipk,)).fetchone()
    if r and r["last_at"] > dbm.minus(minutes=10):
        db.execute("UPDATE login_attempts SET count=count+1,last_at=? WHERE key=?", (now(), ipk))
    else:
        db.execute("INSERT OR REPLACE INTO login_attempts(key,count,first_at,last_at) VALUES(?,1,?,?)", (ipk, now(), now()))


def set_password(db, user, new_pw, ip, event, actor=None):
    """Validate against the policy and history, then store. Raises HTTPError(400) with a list of problems."""
    pol = dbm.get_policy(db)
    hist = [user["password_hash"]] + [r["hash"] for r in db.execute("SELECT hash FROM password_history WHERE user_id=? ORDER BY id DESC LIMIT ?", (user["id"], max(pol["password_history"], 1)))]
    errs = check_password(new_pw, user["username"], pol, hist[:pol["password_history"]])
    if errs:
        raise HTTPError(400, "weak_password", "The password does not meet the policy: " + "; ".join(errs) + ".", problems=errs)
    db.execute("INSERT INTO password_history(user_id,hash,created_at) VALUES(?,?,?)", (user["id"], user["password_hash"], now()))
    db.execute("DELETE FROM password_history WHERE user_id=? AND id NOT IN (SELECT id FROM password_history WHERE user_id=? ORDER BY id DESC LIMIT 24)", (user["id"], user["id"]))
    new_status = "active" if user["status"] in ("invited", "locked", "active") else user["status"]
    db.execute("UPDATE users SET password_hash=?, password_changed_at=?, must_change=0, temp_expires_at=NULL, failed_attempts=0, locked_at=NULL, status=? WHERE id=?",
               (hash_password(new_pw), now(), new_status, user["id"]))
    audit(db, event, actor or user, "access_management", "Password set for %s" % user["username"], ip)


def issue_temp_password(db, user, actor, ip, event):
    """Admin reset / invitation: new one-time password, forced change, unlocked, other sessions ended."""
    pol = dbm.get_policy(db)
    pw = temp_password()
    status = "invited" if not user["last_login_at"] else "active"
    if user["status"] == "deactivated":
        status = "deactivated"
    db.execute("UPDATE users SET password_hash=?, must_change=1, temp_expires_at=?, failed_attempts=0, locked_at=NULL, status=? WHERE id=?",
               (hash_password(pw), plus(hours=pol["temp_password_hours"]), status, user["id"]))
    revoke_sessions(db, user["id"], "password reset by administrator")
    audit(db, event, actor, "access_management", "Temporary password issued to %s (valid %d hours)" % (user["username"], pol["temp_password_hours"]), ip)
    return pw


def request_reset(db, identifier, ip, base_url):
    """Always silent about whether the account exists (SEC-08). Returns nothing."""
    pol = dbm.get_policy(db)
    identifier = (identifier or "").strip()
    if not identifier or not pol["self_service_reset"]:
        return
    u = db.execute("SELECT * FROM users WHERE deleted_at IS NULL AND (username=? COLLATE NOCASE OR email=? COLLATE NOCASE) LIMIT 1", (identifier, identifier)).fetchone()
    if not u or u["status"] not in ("active", "invited", "locked") or not u["email"]:
        audit(db, "auth.reset_requested", None, "access_management", "Reset requested (no matching active account)", ip, identifier)
        return
    db.execute("UPDATE reset_tokens SET used_at=? WHERE user_id=? AND used_at IS NULL", (now(), u["id"]))
    token = new_token()
    db.execute("INSERT INTO reset_tokens(user_id,token_hash,created_at,expires_at) VALUES(?,?,?,?)", (u["id"], hash_token(token), now(), plus(minutes=pol["reset_link_minutes"])))
    outbox(db, u["email"], "Sentinel: reset your password", "Use this link within %d minutes (single use):\n%s/login?reset=%s\nIf you did not ask for this, ignore this message." % (pol["reset_link_minutes"], base_url, token), "reset")
    audit(db, "auth.reset_requested", u, "access_management", "Reset link issued", ip)


def complete_reset(db, token, new_pw, ip):
    t = db.execute("SELECT * FROM reset_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?", (hash_token(token or ""), now())).fetchone()
    if not t:
        raise HTTPError(400, "bad_token", "This reset link is invalid or has expired. Request a new one.")
    u = db.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (t["user_id"],)).fetchone()
    if not u or u["status"] not in ("active", "invited", "locked"):
        raise HTTPError(400, "bad_token", "This reset link is invalid or has expired. Request a new one.")
    set_password(db, u, new_pw, ip, "auth.reset_completed")
    db.execute("UPDATE reset_tokens SET used_at=? WHERE id=?", (now(), t["id"]))
    revoke_sessions(db, u["id"], "password reset")
