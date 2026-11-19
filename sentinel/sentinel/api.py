"""All HTTP endpoints. Handlers return dicts (sent as JSON) or raise HTTPError."""
import os
import json
import re

from . import config, core, db as dbm
from .core import MODULES, CATALOG, ACTIONS, SCOPES, audit, now
from .db import plus, parse
from .web import Router, HTTPError, Response, jr, static_response

router = Router()
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,39}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ------------------------------------------------------------------ helpers
class Ctx:
    def __init__(self, user, session, perms, limited):
        self.user, self.session, self.perms, self.limited = user, session, perms, limited


def need(req, module=None, action="view", allow_limited=False, allow_mfa=False):
    """Authenticate the request. Returns Ctx or raises 401/403. A user who must change the password has a limited session."""
    if req.ctx is None:
        got = core.load_session(req.db, req.cookies.get(config.COOKIE))
        if not got:
            raise HTTPError(401, "auth_required", "Please sign in.")
        user, sess = got
        pol = dbm.get_policy(req.db)
        req.ctx = Ctx(user, sess, core.permissions_of(req.db, user["id"]), core.needs_password_change(user, pol))
    c = req.ctx
    c.mfa_state = c.session["mfa_state"]
    if c.mfa_state != "ok" and not allow_mfa:  # until the second factor is done, a session can do nothing else, not even change the password
        raise HTTPError(403, "mfa_required" if c.mfa_state == "verify" else "mfa_enroll_required", "Finish the two-step sign-in first." if c.mfa_state == "verify" else "Your role requires two-step sign-in. Set it up to continue.")
    if c.limited and not allow_limited:
        raise HTTPError(403, "password_change_required", "You must change your password before continuing.")
    if module and action not in c.perms.get(module, set()):
        raise HTTPError(403, "forbidden", "You do not have permission to do this.")
    return c


def user_public(db, u, pol=None):
    pol = pol or dbm.get_policy(db)
    left, expired = core.password_state(u, pol)
    d = {k: u[k] for k in ("id", "username", "full_name", "email", "phone", "department", "job_title", "status", "last_login_at", "last_login_ip", "access_expires", "data_scope", "timezone", "created_at", "locked_at", "must_change", "failed_attempts", "deleted_at", "mfa_enabled", "delete_reason", "avatar")}
    d["roles"] = core.role_names(db, u["id"])
    d["role_ids"] = [r["role_id"] for r in db.execute("SELECT role_id FROM user_roles WHERE user_id=?", (u["id"],))]
    d["password_days_left"] = left
    d["password_expired"] = bool(expired and u["status"] != "invited")
    d["password_age_days"] = None if left is None else pol["password_max_age_days"] - left
    return d


def need_str(data, key, label, maxlen=200, required=True):
    v = data.get(key)
    v = ("" if v is None else str(v)).strip()
    if required and not v:
        raise HTTPError(400, "validation", "%s is required." % label)
    if len(v) > maxlen:
        raise HTTPError(400, "validation", "%s is too long." % label)
    return v


def admin_count(db, excluding=None):
    return db.execute("""SELECT COUNT(DISTINCT u.id) c FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id
                         WHERE r.name='System Administrator' AND u.status IN ('active','invited') AND u.deleted_at IS NULL AND u.id IS NOT ?""", (excluding,)).fetchone()["c"]


def is_admin_user(db, uid):
    return db.execute("SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=? AND r.name='System Administrator'", (uid,)).fetchone() is not None


# ------------------------------------------------------------------ pages and static
@router.route("GET", "/")
def page_root(req):
    return Response(b"", 302, headers=[("Location", "/app" if core.load_session(req.db, req.cookies.get(config.COOKIE)) else "/login")])


@router.route("GET", "/login")
def page_login(req):
    return static_response("login.html")


@router.route("GET", "/app")
def page_app(req):
    return static_response("app.html")


@router.route("GET", "/favicon.ico")
def favicon(req):
    return static_response("img/favicon.png")


@router.route("GET", "/static/<path>")
def static_file(req):
    return static_response(req.params["path"])


@router.route("GET", "/static/<a>/<b>")
def static_file2(req):
    return static_response(req.params["a"] + "/" + req.params["b"])


# ------------------------------------------------------------------ public
@router.route("GET", "/api/public/policy")
def public_policy(req):
    p = dbm.get_policy(req.db)
    return {k: p[k] for k in ("password_min_length", "password_max_age_days", "max_failed_attempts", "password_history", "reset_link_minutes", "self_service_reset")} | {"version": config.VERSION}


# ------------------------------------------------------------------ authentication
@router.route("POST", "/api/auth/login")
def auth_login(req):
    d = req.json()
    user, token = core.authenticate(req.db, str(d.get("username", "")), str(d.get("password", "")), req.ip, req.ua)
    req.set_cookie(config.COOKIE, token)
    pol = dbm.get_policy(req.db)
    left, expired = core.password_state(user, pol)
    must = core.needs_password_change(user, pol)
    return {"ok": True, "mfa": core.mfa_state_for(req.db, user, pol), "must_change_password": must, "reason": ("temporary" if user["must_change"] else "expired") if must else None, "password_days_left": left,
            "warn": (left is not None and 0 <= left <= pol["password_warn_days"]), "user": {"username": user["username"], "full_name": user["full_name"]}}


@router.route("POST", "/api/auth/logout")
def auth_logout(req):
    c = need(req, allow_limited=True, allow_mfa=True)
    req.db.execute("UPDATE sessions SET revoked_at=?, revoked_reason='signed out' WHERE id=?", (now(), c.session["id"]))
    audit(req.db, "auth.logout", c.user, "access_management", "Signed out", req.ip)
    req.set_cookie(config.COOKIE, "", 0)
    return {"ok": True}


@router.route("GET", "/api/auth/ping")
def auth_ping(req):
    need(req, allow_limited=True, allow_mfa=True)
    return {"ok": True}


@router.route("POST", "/api/auth/change-password")
def auth_change_password(req):
    c = need(req, allow_limited=True)
    d = req.json()
    cur, new = str(d.get("current_password", "")), str(d.get("new_password", ""))
    if not core.verify_password(cur, c.user["password_hash"]):
        raise HTTPError(400, "bad_current", "The current password is not correct.")
    core.set_password(req.db, c.user, new, req.ip, "auth.password_changed")
    core.revoke_sessions(req.db, c.user["id"], "password changed", except_id=c.session["id"])
    if c.user["username"] == "admin":
        try:
            import os
            os.remove(os.path.join(config.DATA, "FIRST_RUN_ADMIN.txt"))
        except OSError:
            pass
    return {"ok": True}


@router.route("POST", "/api/auth/forgot")
def auth_forgot(req):
    core.request_reset(req.db, str(req.json().get("identifier", "")), req.ip, req.base_url)
    return {"ok": True, "message": "If an account matches, a reset link has been sent to its registered e-mail address. The link is valid for %d minutes." % dbm.get_policy(req.db)["reset_link_minutes"]}


@router.route("POST", "/api/auth/reset")
def auth_reset(req):
    d = req.json()
    core.complete_reset(req.db, str(d.get("token", "")), str(d.get("new_password", "")), req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ session context for the application shell
@router.route("GET", "/api/me")
def me(req):
    c = need(req, allow_limited=True)
    pol = dbm.get_policy(req.db)
    u = user_public(req.db, c.user, pol)
    return {"user": u, "must_change_password": c.limited, "perms": {k: sorted(v) for k, v in c.perms.items()}, "policy": {"idle_minutes": pol["idle_minutes"], "password_warn_days": pol["password_warn_days"], "password_min_length": pol["password_min_length"], "max_sessions": pol["max_sessions"], "max_failed_attempts": pol["max_failed_attempts"]},
            "version": config.VERSION, "build": config.BUILD, "demo": bool(req.db.execute("SELECT 1 FROM settings WHERE key='demo_mode'").fetchone()) and not os.environ.get("SENTINEL_HIDE_DEMO")}


@router.route("GET", "/api/nav")
def nav(req):
    c = need(req)
    suites = []
    from . import ai_gov
    ai_off = ai_gov.settings(req.db)["mode"] == "off"  # BRD 13.31: the Copilot is hidden when AI is off; users use search, filters and reports
    for s in CATALOG["suites"]:
        mods = [{"key": m["key"], "name": m["name"], "phase": m["phase"], "live": m["key"] in core.LIVE} for m in CATALOG["modules"] if m["suite"] == s["name"] and "view" in c.perms.get(m["key"], set()) and not (ai_off and m["key"] == "sentinel_copilot")]
        if mods:
            suites.append({"name": s["name"], "color": s["color"], "modules": mods})
    return {"suites": suites}


@router.route("GET", "/api/modules/<key>")
def module_info(req):
    k = req.params["key"]
    c = need(req, k, "view")
    m = MODULES.get(k)
    if not m:
        raise HTTPError(404, "not_found", "Unknown module")
    return dict(m, live=k in core.LIVE, actions=sorted(c.perms.get(k, set())))


# ------------------------------------------------------------------ profile
@router.route("GET", "/api/profile")
def profile_get(req):
    c = need(req, allow_limited=True)
    u = user_public(req.db, c.user)
    u["prefs"] = json.loads(c.user["prefs"] or "{}")
    return u


@router.route("PUT", "/api/profile")
def profile_put(req):
    c = need(req)
    d = req.json()
    name = need_str(d, "full_name", "Full name", 120)
    email = need_str(d, "email", "E-mail", 200)
    if not EMAIL_RE.match(email):
        raise HTTPError(400, "validation", "Enter a valid e-mail address.")
    phone = need_str(d, "phone", "Phone", 40, False)
    tz = need_str(d, "timezone", "Time zone", 60, False) or "Africa/Harare"
    req.db.execute("UPDATE users SET full_name=?, email=?, phone=?, timezone=? WHERE id=?", (name, email, phone, tz, c.user["id"]))
    audit(req.db, "profile.updated", c.user, "access_management", "Profile details updated", req.ip)
    return {"ok": True}


@router.route("PUT", "/api/profile/preferences")
def profile_prefs(req):
    c = need(req)
    d = req.json()
    prefs = json.loads(c.user["prefs"] or "{}")
    notif = d.get("notifications") or {}
    prefs["notifications"] = {k: bool(notif.get(k)) for k in ("digest", "red_kri", "approvals", "sms_breach")}
    dl = d.get("delegate") or {}
    deleg = {}
    if dl.get("username"):
        du = core.get_user(req.db, str(dl["username"]).strip())
        if not du or du["id"] == c.user["id"]:
            raise HTTPError(400, "validation", "Choose another existing user as delegate.")
        deleg = {"username": du["username"], "from": str(dl.get("from", ""))[:10], "to": str(dl.get("to", ""))[:10]}
    prefs["delegate"] = deleg
    req.db.execute("UPDATE users SET prefs=? WHERE id=?", (json.dumps(prefs), c.user["id"]))
    audit(req.db, "profile.preferences", c.user, "access_management", "Notification and delegation settings updated", req.ip)
    return {"ok": True}


@router.route("PUT", "/api/profile/avatar")
def profile_avatar(req):
    c = need(req)
    data = str(req.json().get("data", ""))
    import re as _re
    if not _re.match(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$", data) or len(data) > 300000:
        raise HTTPError(400, "bad_image", "Choose a PNG, JPEG or WebP picture (it is resized to fit automatically).")
    req.db.execute("UPDATE users SET avatar=? WHERE id=?", (data, c.user["id"]))
    audit(req.db, "profile.avatar", c.user, "access_management", "Profile picture changed", req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/profile/avatar")
def profile_avatar_remove(req):
    c = need(req)
    req.db.execute("UPDATE users SET avatar=NULL WHERE id=?", (c.user["id"],))
    return {"ok": True}


@router.route("GET", "/api/profile/sessions")
def profile_sessions(req):
    c = need(req)
    rows = req.db.execute("SELECT id,created_at,last_seen,ip,user_agent FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>? ORDER BY id DESC", (c.user["id"], now())).fetchall()
    return {"sessions": [dict(r, current=(r["id"] == c.session["id"])) for r in rows]}


@router.route("POST", "/api/profile/sessions/<int:sid>/revoke")
def profile_session_revoke(req):
    c = need(req)
    r = req.db.execute("UPDATE sessions SET revoked_at=?, revoked_reason='signed out by user' WHERE id=? AND user_id=? AND revoked_at IS NULL", (now(), int(req.params["sid"]), c.user["id"]))
    audit(req.db, "session.revoked", c.user, "access_management", "Session %s signed out" % req.params["sid"], req.ip)
    return {"ok": r.rowcount > 0}


@router.route("POST", "/api/profile/signout-everywhere")
def profile_signout_all(req):
    c = need(req)
    core.revoke_sessions(req.db, c.user["id"], "signed out everywhere")
    audit(req.db, "session.signout_everywhere", c.user, "access_management", "Signed out of all sessions", req.ip)
    req.set_cookie(config.COOKIE, "", 0)
    return {"ok": True}


# ------------------------------------------------------------------ users (Access Management)
@router.route("GET", "/api/meta")
def meta(req):
    need(req)
    roles = [dict(id=r["id"], name=r["name"]) for r in req.db.execute("SELECT id,name FROM roles ORDER BY name")]
    mods = [{"key": m["key"], "name": m["name"], "suite": m["suite"]} for m in CATALOG["modules"]]
    return {"roles": roles, "actions": ACTIONS, "scopes": SCOPES, "modules": mods, "suites": CATALOG["suites"]}


def _validate_user_fields(db, d, uid=None):
    name = need_str(d, "full_name", "Full name", 120)
    email = need_str(d, "email", "E-mail", 200)
    if not EMAIL_RE.match(email):
        raise HTTPError(400, "validation", "Enter a valid e-mail address.")
    scope = d.get("data_scope") or "own"
    if scope not in SCOPES:
        raise HTTPError(400, "validation", "Choose a valid data scope.")
    exp = (d.get("access_expires") or "").strip() or None
    if exp and not DATE_RE.match(exp):
        raise HTTPError(400, "validation", "Access expiry must be a date (YYYY-MM-DD).")
    role_ids = d.get("role_ids")
    if not isinstance(role_ids, list) or not role_ids:
        raise HTTPError(400, "validation", "Choose at least one role.")
    ids = []
    for r in role_ids:
        if not isinstance(r, int) or not db.execute("SELECT 1 FROM roles WHERE id=?", (r,)).fetchone():
            raise HTTPError(400, "validation", "Unknown role selected.")
        ids.append(r)
    return dict(full_name=name, email=email, phone=need_str(d, "phone", "Phone", 40, False), department=need_str(d, "department", "Department", 120, False),
                job_title=need_str(d, "job_title", "Job title", 120, False), data_scope=scope, access_expires=exp), sorted(set(ids))


@router.route("GET", "/api/users")
def users_list(req):
    c = need(req, "access_management", "view")
    q = (req.query.get("q") or "").strip().lower()
    status = req.query.get("status") or ""
    deleted = req.query.get("deleted") == "1"
    pol = dbm.get_policy(req.db)
    rows = req.db.execute("SELECT * FROM users WHERE deleted_at IS %s ORDER BY full_name COLLATE NOCASE" % ("NOT NULL" if deleted else "NULL")).fetchall()
    out = []
    for u in rows:
        d = user_public(req.db, u, pol)
        if q and q not in (u["username"] + " " + u["full_name"] + " " + (u["email"] or "") + " " + (u["department"] or "")).lower():
            continue
        if status == "expired":
            if not d["password_expired"]:
                continue
        elif status and u["status"] != status:
            continue
        out.append(d)
    allu = [user_public(req.db, u, pol) for u in req.db.execute("SELECT * FROM users WHERE deleted_at IS NULL")]
    soon = (parse(now()) + __import__("datetime").timedelta(days=30)).strftime("%Y-%m-%d")
    stats = {"total": len(allu), "active": sum(1 for x in allu if x["status"] == "active"), "locked": sum(1 for x in allu if x["status"] == "locked"), "invited": sum(1 for x in allu if x["status"] == "invited"),
             "deactivated": sum(1 for x in allu if x["status"] == "deactivated"), "expired_password": sum(1 for x in allu if x["password_expired"]), "access_expiring": sum(1 for x in allu if x["access_expires"] and x["access_expires"] <= soon),
             "in_bin": req.db.execute("SELECT COUNT(*) c FROM users WHERE deleted_at IS NOT NULL").fetchone()["c"]}
    return {"users": out, "stats": stats}


@router.route("POST", "/api/users")
def users_create(req):
    c = need(req, "access_management", "create")
    d = req.json()
    username = need_str(d, "username", "Username", 40)
    if not USERNAME_RE.match(username):
        raise HTTPError(400, "validation", "Username: 3 to 40 letters, numbers, dot, dash or underscore, starting with a letter or number.")
    if req.db.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone():
        raise HTTPError(409, "exists", "That username is already in use (it may be in the Recycle Bin).")
    f, role_ids = _validate_user_fields(req.db, d)
    pol = dbm.get_policy(req.db)
    if d.get("password_mode") == "manual":
        pw = str(d.get("manual_password") or "")
        errs = core.check_password(pw, username, pol)
        if errs:
            raise HTTPError(400, "weak_password", "The temporary password does not meet the policy: " + "; ".join(errs) + ".", problems=errs)
    else:
        pw = core.temp_password()
    uid = req.db.execute("""INSERT INTO users(username,full_name,email,phone,department,job_title,status,password_hash,must_change,temp_expires_at,data_scope,access_expires,created_at,created_by)
                            VALUES(?,?,?,?,?,?,'invited',?,1,?,?,?,?,?)""", (username, f["full_name"], f["email"], f["phone"], f["department"], f["job_title"], core.hash_password(pw),
                                                                        plus(hours=pol["temp_password_hours"]), f["data_scope"], f["access_expires"], now(), c.user["id"])).lastrowid
    for r in role_ids:
        req.db.execute("INSERT INTO user_roles(user_id,role_id) VALUES(?,?)", (uid, r))
    core.outbox(req.db, f["email"], "Welcome to Sentinel", "Your account has been created.\nUsername: %s\nTemporary password: %s\nSign in at %s/login. You must choose a new password at first sign-in; the temporary password is valid for %d hours." % (username, pw, req.base_url, pol["temp_password_hours"]), "invitation")
    audit(req.db, "user.created", c.user, "access_management", "Created %s (roles: %s)" % (username, ", ".join(core.role_names(req.db, uid))), req.ip)
    u = req.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return {"user": user_public(req.db, u, pol), "temp_password": pw}


def _target(req, action="edit", deleted=False):
    c = need(req, "access_management", action)
    u = req.db.execute("SELECT * FROM users WHERE id=?", (int(req.params["uid"]),)).fetchone()
    if not u or (bool(u["deleted_at"]) != deleted):
        raise HTTPError(404, "not_found", "User not found")
    return c, u


@router.route("GET", "/api/users/<int:uid>")
def users_get(req):
    c, u = _target(req, "view")
    d = user_public(req.db, u)
    d["recent"] = [dict(r) for r in req.db.execute("SELECT ts,event,detail,ip FROM audit WHERE user_id=? ORDER BY id DESC LIMIT 15", (u["id"],))]
    d["sessions"] = [dict(r) for r in req.db.execute("SELECT id,created_at,last_seen,ip,user_agent FROM sessions WHERE user_id=? AND revoked_at IS NULL AND expires_at>?", (u["id"], now()))]
    return d


@router.route("PUT", "/api/users/<int:uid>")
def users_update(req):
    c, u = _target(req, "edit")
    f, role_ids = _validate_user_fields(req.db, req.json(), u["id"])
    admin_role = req.db.execute("SELECT id FROM roles WHERE name='System Administrator'").fetchone()["id"]
    if is_admin_user(req.db, u["id"]) and admin_role not in role_ids and admin_count(req.db, u["id"]) == 0:
        raise HTTPError(409, "last_admin", "At least one active System Administrator must remain.")
    before = core.role_names(req.db, u["id"])
    req.db.execute("UPDATE users SET full_name=?,email=?,phone=?,department=?,job_title=?,data_scope=?,access_expires=? WHERE id=?",
                   (f["full_name"], f["email"], f["phone"], f["department"], f["job_title"], f["data_scope"], f["access_expires"], u["id"]))
    req.db.execute("DELETE FROM user_roles WHERE user_id=?", (u["id"],))
    for r in role_ids:
        req.db.execute("INSERT INTO user_roles(user_id,role_id) VALUES(?,?)", (u["id"], r))
    after = core.role_names(req.db, u["id"])
    audit(req.db, "user.updated", c.user, "access_management", "Updated %s%s" % (u["username"], (" (roles: %s -> %s)" % (", ".join(before), ", ".join(after))) if before != after else ""), req.ip)
    return {"user": user_public(req.db, req.db.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone())}


def _guard_self_admin(req, c, u, what):
    if u["id"] == c.user["id"]:
        raise HTTPError(409, "self", "You cannot %s your own account." % what)
    if is_admin_user(req.db, u["id"]) and admin_count(req.db, u["id"]) == 0:
        raise HTTPError(409, "last_admin", "At least one active System Administrator must remain.")


@router.route("POST", "/api/users/<int:uid>/deactivate")
def users_deactivate(req):
    c, u = _target(req, "edit")
    _guard_self_admin(req, c, u, "deactivate")
    req.db.execute("UPDATE users SET status='deactivated' WHERE id=?", (u["id"],))
    core.revoke_sessions(req.db, u["id"], "account deactivated")
    audit(req.db, "user.deactivated", c.user, "access_management", "Deactivated %s" % u["username"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/users/<int:uid>/reactivate")
def users_reactivate(req):
    c, u = _target(req, "edit")
    st = "invited" if not u["last_login_at"] else "active"
    req.db.execute("UPDATE users SET status=?, failed_attempts=0, locked_at=NULL WHERE id=?", (st, u["id"]))
    audit(req.db, "user.reactivated", c.user, "access_management", "Reactivated %s" % u["username"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/users/<int:uid>/unlock")
def users_unlock(req):
    c, u = _target(req, "edit")
    st = "invited" if not u["last_login_at"] else "active"
    req.db.execute("UPDATE users SET status=?, failed_attempts=0, locked_at=NULL WHERE id=?", (st, u["id"]))
    req.db.execute("DELETE FROM login_attempts WHERE key LIKE 'u:%'")
    audit(req.db, "user.unlocked", c.user, "access_management", "Unlocked %s" % u["username"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/users/<int:uid>/reset-password")
def users_reset_password(req):
    c, u = _target(req, "edit")
    pw = core.issue_temp_password(req.db, u, c.user, req.ip, "user.password_reset")
    pol = dbm.get_policy(req.db)
    if u["email"]:
        core.outbox(req.db, u["email"], "Sentinel: your password was reset", "An administrator reset your password.\nUsername: %s\nTemporary password: %s\nIt is valid for %d hours and must be changed at your next sign-in." % (u["username"], pw, pol["temp_password_hours"]), "reset")
    return {"temp_password": pw}


@router.route("POST", "/api/users/<int:uid>/force-logout")
def users_force_logout(req):
    c, u = _target(req, "edit")
    core.revoke_sessions(req.db, u["id"], "forced sign-out by administrator")
    audit(req.db, "user.force_logout", c.user, "access_management", "Ended all sessions of %s" % u["username"], req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/users/<int:uid>")
def users_delete(req):
    c, u = _target(req, "delete")
    reason = need_str(req.json(), "reason", "A reason", 300)
    if len(reason) < 3:
        raise HTTPError(400, "validation", "Give a reason of at least 3 characters.")
    _guard_self_admin(req, c, u, "delete")
    pol = dbm.get_policy(req.db)
    req.db.execute("UPDATE users SET deleted_at=?, deleted_by=?, delete_reason=?, status='deleted' WHERE id=?", (now(), c.user["id"], reason, u["id"]))
    core.revoke_sessions(req.db, u["id"], "account deleted")
    req.db.execute("INSERT INTO recycle(entity_type,entity_id,title,module,deleted_by,deleted_by_name,deleted_at,reason,purge_at,payload) VALUES('user',?,?,?,?,?,?,?,?,?)",
                   (u["id"], "%s (%s)" % (u["full_name"], u["username"]), "Access Management", c.user["id"], c.user["username"], now(), reason, plus(days=pol["recycle_days"]), json.dumps({"previous_status": u["status"]})))
    audit(req.db, "user.deleted", c.user, "access_management", "Deleted %s: %s" % (u["username"], reason), req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ roles
def _role_dict(db, r):
    return {"id": r["id"], "name": r["name"], "description": r["description"], "is_system": bool(r["is_system"]), "permissions": json.loads(r["permissions"]),
            "user_count": db.execute("SELECT COUNT(*) c FROM user_roles ur JOIN users u ON u.id=ur.user_id WHERE ur.role_id=? AND u.deleted_at IS NULL", (r["id"],)).fetchone()["c"]}


def _clean_perms(p):
    if not isinstance(p, dict):
        raise HTTPError(400, "validation", "Permissions must be an object.")
    out = {}
    for k, acts in p.items():
        if k not in MODULES or not isinstance(acts, list):
            raise HTTPError(400, "validation", "Unknown module in permissions.")
        a = [x for x in ACTIONS if x in acts]
        if a:
            out[k] = a
    return out


@router.route("GET", "/api/roles")
def roles_list(req):
    need(req, "access_management", "view")
    return {"roles": [_role_dict(req.db, r) for r in req.db.execute("SELECT * FROM roles ORDER BY is_system DESC, name")]}


@router.route("POST", "/api/roles")
def roles_create(req):
    c = need(req, "access_management", "create")
    d = req.json()
    name = need_str(d, "name", "Role name", 60)
    if req.db.execute("SELECT 1 FROM roles WHERE name=? COLLATE NOCASE", (name,)).fetchone():
        raise HTTPError(409, "exists", "A role with that name already exists.")
    rid = req.db.execute("INSERT INTO roles(name,description,is_system,permissions,created_at) VALUES(?,?,0,?,?)", (name, need_str(d, "description", "Description", 300, False), json.dumps(_clean_perms(d.get("permissions") or {})), now())).lastrowid
    audit(req.db, "role.created", c.user, "access_management", "Created role %s" % name, req.ip)
    return {"role": _role_dict(req.db, req.db.execute("SELECT * FROM roles WHERE id=?", (rid,)).fetchone())}


@router.route("PUT", "/api/roles/<int:rid>")
def roles_update(req):
    c = need(req, "access_management", "edit")
    r = req.db.execute("SELECT * FROM roles WHERE id=?", (int(req.params["rid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Role not found")
    if r["name"] == "System Administrator":
        raise HTTPError(409, "locked_role", "The System Administrator role is fixed so that the administrator cannot gain access to risk data.")
    d = req.json()
    perms = _clean_perms(d.get("permissions") or {})
    name = r["name"] if (r["is_system"] or "name" not in d) else need_str(d, "name", "Role name", 60)
    if not r["is_system"] and req.db.execute("SELECT 1 FROM roles WHERE name=? COLLATE NOCASE AND id<>?", (name, r["id"])).fetchone():
        raise HTTPError(409, "exists", "A role with that name already exists.")
    req.db.execute("UPDATE roles SET name=?, description=?, permissions=? WHERE id=?", (name, need_str(d, "description", "Description", 300, False) if "description" in d else r["description"], json.dumps(perms), r["id"]))
    audit(req.db, "role.updated", c.user, "access_management", "Permissions changed for role %s (takes effect at next sign-in)" % name, req.ip)
    return {"role": _role_dict(req.db, req.db.execute("SELECT * FROM roles WHERE id=?", (r["id"],)).fetchone())}


@router.route("DELETE", "/api/roles/<int:rid>")
def roles_delete(req):
    c = need(req, "access_management", "delete")
    r = req.db.execute("SELECT * FROM roles WHERE id=?", (int(req.params["rid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Role not found")
    if r["is_system"]:
        raise HTTPError(409, "system_role", "System roles cannot be deleted.")
    if req.db.execute("SELECT 1 FROM user_roles WHERE role_id=?", (r["id"],)).fetchone():
        raise HTTPError(409, "in_use", "Remove this role from its users first.")
    req.db.execute("DELETE FROM roles WHERE id=?", (r["id"],))
    audit(req.db, "role.deleted", c.user, "access_management", "Deleted role %s" % r["name"], req.ip)
    return {"ok": True}


# ------------------------------------------------------------------ administration
@router.route("GET", "/api/admin/settings")
def settings_get(req):
    need(req, "administration", "view")
    return {"policy": dbm.get_policy(req.db), "limits": config.POLICY_LIMITS}


@router.route("PUT", "/api/admin/settings")
def settings_put(req):
    c = need(req, "administration", "edit")
    d = req.json().get("policy") or {}
    cur = dbm.get_policy(req.db)
    new = dict(cur)
    for k, v in d.items():
        if k not in config.DEFAULT_POLICY:
            continue
        if isinstance(config.DEFAULT_POLICY[k], bool):
            new[k] = bool(v)
        else:
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise HTTPError(400, "validation", "%s must be a whole number." % k.replace("_", " "))
            lo, hi = config.POLICY_LIMITS.get(k, (0, 10 ** 6))
            if not lo <= v <= hi:
                raise HTTPError(400, "validation", "%s must be between %d and %d." % (k.replace("_", " "), lo, hi))
            new[k] = v
    changes = ["%s: %s -> %s" % (k, cur[k], new[k]) for k in new if new[k] != cur[k]]
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('policy',?)", (json.dumps(new),))
    if changes:
        audit(req.db, "settings.updated", c.user, "administration", "Sign-in policy changed: " + "; ".join(changes), req.ip)
    return {"policy": new, "changed": changes}


@router.route("GET", "/api/admin/audit")
def audit_list(req):
    need(req, "administration", "view")
    q = req.query
    where, args = [], []
    if q.get("q"):
        where.append("(event LIKE ? OR detail LIKE ? OR username LIKE ?)"); args += ["%" + q["q"] + "%"] * 3
    if q.get("user"):
        where.append("username=? COLLATE NOCASE"); args.append(q["user"])
    if q.get("event"):
        where.append("event LIKE ?"); args.append(q["event"] + "%")
    if q.get("from"):
        where.append("ts>=?"); args.append(q["from"] + "T00:00:00Z")
    if q.get("to"):
        where.append("ts<=?"); args.append(q["to"] + "T23:59:59Z")
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = req.db.execute("SELECT COUNT(*) c FROM audit" + w, args).fetchone()["c"]
    page = max(int(q.get("page") or 1), 1)
    rows = req.db.execute("SELECT id,ts,username,event,module,detail,ip,hash FROM audit" + w + " ORDER BY id DESC LIMIT 50 OFFSET ?", args + [(page - 1) * 50]).fetchall()
    return {"total": total, "page": page, "pages": max((total + 49) // 50, 1), "rows": [dict(r) for r in rows]}


@router.route("POST", "/api/admin/audit/verify")
def audit_verify(req):
    c = need(req, "administration", "view")
    res = core.verify_audit(req.db)
    audit(req.db, "audit.verified", c.user, "administration", "Audit chain verified: %s (%d entries)" % ("intact" if res["ok"] else "BROKEN at %s" % res["broken_at"], res["checked"]), req.ip)
    return res


@router.route("GET", "/api/admin/recycle")
def recycle_list(req):
    need(req, "administration", "view")
    rows = req.db.execute("SELECT * FROM recycle WHERE restored_at IS NULL ORDER BY id DESC").fetchall()
    return {"items": [dict(r, days_left=max((parse(r["purge_at"]) - parse(now())).days, 0)) for r in rows], "retention_days": dbm.get_policy(req.db)["recycle_days"]}


@router.route("POST", "/api/admin/recycle/<int:rid>/restore")
def recycle_restore(req):
    c = need(req, "administration", "edit")
    r = req.db.execute("SELECT * FROM recycle WHERE id=? AND restored_at IS NULL", (int(req.params["rid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Item not found in the Recycle Bin")
    if r["entity_type"] == "user":
        req.db.execute("UPDATE users SET deleted_at=NULL, deleted_by=NULL, delete_reason=NULL, status='deactivated' WHERE id=?", (r["entity_id"],))
    if r["entity_type"] == "risk":
        req.db.execute("UPDATE risks SET deleted_at=NULL, deleted_by=NULL, delete_reason=NULL WHERE id=?", (r["entity_id"],))
    if r["entity_type"] == "workbook":
        from . import workbooks
        workbooks.restore(req.db, r, c.user)
    if r["entity_type"] == "ai_doc":
        req.db.execute("UPDATE ai_docs SET deleted_at=NULL WHERE id=?", (r["entity_id"],))
    if r["entity_type"] == "task":
        req.db.execute("UPDATE tasks SET deleted_at=NULL, deleted_by=NULL, delete_reason=NULL WHERE id=?", (r["entity_id"],))
    if r["entity_type"] == "incident":
        req.db.execute("UPDATE incidents SET deleted_at=NULL, deleted_by=NULL, delete_reason=NULL WHERE id=?", (r["entity_id"],))
    req.db.execute("UPDATE recycle SET restored_at=? WHERE id=?", (now(), r["id"]))
    audit(req.db, "recycle.restored", c.user, r["module"] or "administration", "Restored %s %s (reactivate it in Access Management after checking the roles)" % (r["entity_type"], r["title"]), req.ip)
    return {"ok": True}


@router.route("GET", "/api/admin/outbox")
def outbox_list(req):
    need(req, "administration", "view")
    return {"messages": [dict(r) for r in req.db.execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 200")], "note": "Messages Sentinel sends or queues. Link a mail server in Administration > E-mail and they are delivered; until then they wait here and are not sent."}


@router.route("GET", "/api/home")
def home(req):
    c = need(req)
    pol = dbm.get_policy(req.db)
    u = user_public(req.db, c.user, pol)
    out = {"user": u, "password_days_left": u["password_days_left"], "password_warn": u["password_days_left"] is not None and u["password_days_left"] <= pol["password_warn_days"]}
    if "view" in c.perms.get("administration", set()) or "view" in c.perms.get("access_management", set()):
        d = req.db
        since = dbm.minus(hours=24)
        users = [user_public(d, x, pol) for x in d.execute("SELECT * FROM users WHERE deleted_at IS NULL")]
        out["stats"] = {"users": len(users), "active": sum(1 for x in users if x["status"] == "active"), "locked": sum(1 for x in users if x["status"] == "locked"), "invited": sum(1 for x in users if x["status"] == "invited"),
                        "expired_password": sum(1 for x in users if x["password_expired"]), "sessions": d.execute("SELECT COUNT(*) c FROM sessions WHERE revoked_at IS NULL AND expires_at>?", (now(),)).fetchone()["c"],
                        "signins_24h": d.execute("SELECT COUNT(*) c FROM audit WHERE event='auth.login' AND ts>=?", (since,)).fetchone()["c"],
                        "failed_24h": d.execute("SELECT COUNT(*) c FROM audit WHERE event='auth.login_failed' AND ts>=?", (since,)).fetchone()["c"],
                        "in_bin": d.execute("SELECT COUNT(*) c FROM recycle WHERE restored_at IS NULL").fetchone()["c"], "audit_24h": d.execute("SELECT COUNT(*) c FROM audit WHERE ts>=?", (since,)).fetchone()["c"]}
    return out


def purge_expired(db):
    """Remove Recycle Bin items past retention. Runs at start-up and hourly."""
    n = 0
    for r in db.execute("SELECT * FROM recycle WHERE restored_at IS NULL AND purge_at<?", (now(),)).fetchall():
        if r["entity_type"] == "user":
            db.execute("DELETE FROM users WHERE id=? AND deleted_at IS NOT NULL", (r["entity_id"],))
        elif r["entity_type"] == "risk":
            db.execute("DELETE FROM risks WHERE id=? AND deleted_at IS NOT NULL", (r["entity_id"],))
        elif r["entity_type"] == "workbook":
            db.execute("DELETE FROM wb_store WHERE id=? AND deleted_at IS NOT NULL", (r["entity_id"],))
        elif r["entity_type"] == "ai_doc":
            db.execute("DELETE FROM ai_docs WHERE id=? AND deleted_at IS NOT NULL", (r["entity_id"],))
        elif r["entity_type"] == "task":
            db.execute("DELETE FROM tasks WHERE id=? AND deleted_at IS NOT NULL", (r["entity_id"],))
        elif r["entity_type"] == "incident":
            db.execute("DELETE FROM incidents WHERE id=? AND deleted_at IS NOT NULL", (r["entity_id"],))
        db.execute("DELETE FROM recycle WHERE id=?", (r["id"],))
        audit(db, "recycle.purged", None, r["module"] or "administration", "Purged %s after retention" % r["title"], "", "system")
        n += 1
    db.commit()
    return n


from . import risks  # noqa: E402,F401  (registers the Risk Register, Heat Map and Command Center endpoints)

from . import analytics  # noqa: E402,F401  (registers the Performance Analytics endpoint)

from . import register  # noqa: E402,F401  (the risk assessment register in the template format)

from . import dq  # noqa: E402,F401  (data quality: workbook and taxonomy reconciliation)

from . import workbooks  # noqa: E402,F401  (saved workbooks, delete and restore)

from . import ai_gov, ai_kb, ai_agent, ai_horizon  # noqa: E402,F401  (Sentinel Copilot and AI Governance)
from . import mailer, strategy, scenario, radar, auditws, fraud, speakup, kit, kit_compliance, kit_standards, kit_resilience, predict, docint, wfdesign, integ, reports  # noqa: E402,F401  (e-mail reminders, Strategy Map, Scenario Lab)

from . import live_data  # noqa: E402,F401  (live market data for the KPIs)
from . import kpi_tools  # noqa: E402,F401  (import batches and starter-set removal)
from . import kpi_auto  # noqa: E402,F401  (weekly KPI research updates)
from . import kriq  # noqa: E402,F401  (quarterly KRIs from the BoT and RISCO reports)
from . import kriq_report  # noqa: E402,F401  (report format, chart edits, checks)

from . import p1  # noqa: E402,F401  (Daily Tracker and Risk Appetite endpoints)

from . import p1b  # noqa: E402,F401  (Assessment Studio and Board Hub endpoints)

from . import p2  # noqa: E402,F401  (Weekly KPI and KRI Monitor endpoints)

from . import p2b  # noqa: E402,F401  (Incidents and Losses endpoints)

from . import p3s  # noqa: E402,F401  (verified sources)

from . import p3  # noqa: E402,F401  (report charts, PowerPoint, transaction upload)

from . import p5  # noqa: E402,F401  (controls, actions, backups)

from . import mfa  # noqa: E402,F401  (two-step sign-in)

from . import ai  # noqa: E402,F401  (AI Insights: similarity and anomaly signals)
from . import p4  # noqa: E402,F401  (September report format: slide text, hourly data, Excel deck)
