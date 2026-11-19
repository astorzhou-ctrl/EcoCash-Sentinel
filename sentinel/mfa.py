"""Two-step sign-in (BRD: MFA). Standard time-based one-time codes (RFC 6238: HMAC-SHA1, 30 seconds, 6 digits), so any authenticator app works.
Secrets are encrypted at rest with a key kept in the data folder. A code can be used once. Eight single-use recovery codes are shown once at set-up.
Wrong codes count toward the same lock-out as wrong passwords (policy: 3 in a row)."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time

from . import config, core, db as dbm
from .api import router, need, need_str
from .core import audit, now, outbox
from .web import HTTPError

ISSUER = "EcoCash Sentinel"


# ------------------------------------------------------------------ crypto helpers
def _key():
    path = os.path.join(config.DATA, "mfa.key")
    if not os.path.isfile(path):
        with open(path, "wb") as f:
            f.write(os.urandom(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return open(path, "rb").read()


def _stream(key, nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(key, nonce + struct.pack(">I", i), hashlib.sha256).digest(); i += 1
    return out[:n]


def seal(text):
    key, nonce, raw = _key(), os.urandom(12), text.encode()
    ct = bytes(a ^ b for a, b in zip(raw, _stream(key, nonce, len(raw))))
    tag = hmac.new(key, b"mac" + nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + ct + tag).decode()


def unseal(blob):
    key, b = _key(), base64.b64decode(blob)
    nonce, ct, tag = b[:12], b[12:-16], b[-16:]
    if not hmac.compare_digest(tag, hmac.new(key, b"mac" + nonce + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("the stored secret has been altered")
    return bytes(a ^ b for a, b in zip(ct, _stream(key, nonce, len(ct)))).decode()


def hotp(secret_b32, counter, digits=6):
    h = hmac.new(base64.b32decode(secret_b32, casefold=True), struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)).zfill(digits)


def check_code(secret_b32, code, last_step=None, at=None):
    """The time step the code belongs to (within one step either side), or None. A step at or before last_step has been used already."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != 6:
        return None
    now_step = int((at if at is not None else time.time()) // 30)
    for off in (0, -1, 1):
        step = now_step + off
        if hmac.compare_digest(hotp(secret_b32, step), code) and step > (last_step or 0):
            return step
    return None


def new_secret():
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def new_recovery_codes():
    codes = []
    for _ in range(8):
        h = secrets.token_hex(5); codes.append(h[:5] + "-" + h[5:])
    return codes


def rhash(code):
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def group(s):
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


# ------------------------------------------------------------------ failures count toward the lock-out
def fail(db, user, ip, what):
    pol = dbm.get_policy(db); maxf = pol["max_failed_attempts"]
    n = user["failed_attempts"] + 1
    db.execute("UPDATE users SET failed_attempts=? WHERE id=?", (n, user["id"]))
    audit(db, "auth.mfa_failed", user, "access_management", "Wrong %s (%d of %d)" % (what, n, maxf), ip)
    if n >= maxf:
        db.execute("UPDATE users SET status='locked', locked_at=? WHERE id=?", (now(), user["id"]))
        db.execute("UPDATE sessions SET revoked_at=?, revoked_reason='locked' WHERE user_id=? AND revoked_at IS NULL", (now(), user["id"]))
        audit(db, "auth.locked", user, "access_management", "Account locked after %d failed attempts (second factor)" % maxf, ip)
        for a in db.execute("SELECT u.email FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name='System Administrator' AND u.status IN ('active','invited') AND u.email IS NOT NULL"):
            outbox(db, a["email"], "Sentinel: account locked (%s)" % user["username"], "The account %s was locked after %d wrong verification codes from %s. Unlock it under Access Management." % (user["username"], maxf, ip), "security")
        db.commit()
        raise HTTPError(423, "locked", "This account is locked.")
    db.commit()
    raise HTTPError(401, "bad_code", "That code is not correct.", attempts_remaining=maxf - n)


def fresh_user(db, c):
    return db.execute("SELECT * FROM users WHERE id=?", (c.user["id"],)).fetchone()


# ------------------------------------------------------------------ sign-in step
@router.route("POST", "/api/auth/mfa/verify")
def mfa_verify(req):
    c = need(req, allow_limited=True, allow_mfa=True)
    if c.mfa_state != "verify":
        raise HTTPError(409, "not_needed", "This session does not need a verification code.")
    u, d = fresh_user(req.db, c), req.json()
    rec = str(d.get("recovery") or "").strip()
    if rec:
        hs = json.loads(u["mfa_recovery"] or "[]"); h = rhash(rec)
        if h not in hs:
            fail(req.db, u, req.ip, "recovery code")
        hs.remove(h)
        req.db.execute("UPDATE users SET mfa_recovery=?, failed_attempts=0 WHERE id=?", (json.dumps(hs), u["id"]))
        audit(req.db, "auth.mfa", u, "access_management", "Second factor passed with a recovery code (%d left)" % len(hs), req.ip)
        left = len(hs)
    else:
        step = check_code(unseal(u["mfa_secret"]), d.get("code"), u["mfa_last_step"])
        if step is None:
            fail(req.db, u, req.ip, "verification code")
        req.db.execute("UPDATE users SET mfa_last_step=?, failed_attempts=0 WHERE id=?", (step, u["id"]))
        audit(req.db, "auth.mfa", u, "access_management", "Second factor passed", req.ip)
        left = len(json.loads(u["mfa_recovery"] or "[]"))
    req.db.execute("UPDATE sessions SET mfa_state='ok' WHERE id=?", (c.session["id"],))
    return {"ok": True, "recovery_left": left}


# ------------------------------------------------------------------ set-up, confirm, turn off
@router.route("POST", "/api/auth/mfa/setup")
def mfa_setup(req):
    c = need(req, allow_limited=True, allow_mfa=True)
    u = fresh_user(req.db, c)
    if c.mfa_state == "verify" or u["mfa_enabled"]:
        raise HTTPError(409, "already_on", "Two-step sign-in is already on for this account.")
    if not core.mfa_required(req.db, u, dbm.get_policy(req.db)):
        raise HTTPError(403, "admin_controlled", "Two-step sign-in is switched on by your System Administrator. Ask them to switch it on for you.")
    sec = new_secret()
    req.db.execute("UPDATE users SET mfa_secret=? WHERE id=?", (seal(sec), u["id"]))
    from urllib.parse import quote
    uri = "otpauth://totp/%s:%s?secret=%s&issuer=%s&algorithm=SHA1&digits=6&period=30" % (quote(ISSUER), quote(u["username"]), sec, quote(ISSUER))
    return {"secret": group(sec), "uri": uri, "account": u["username"], "issuer": ISSUER}


@router.route("POST", "/api/auth/mfa/confirm")
def mfa_confirm(req):
    c = need(req, allow_limited=True, allow_mfa=True)
    u = fresh_user(req.db, c)
    if c.mfa_state == "verify" or u["mfa_enabled"] or not u["mfa_secret"]:
        raise HTTPError(409, "no_setup", "Start the set-up first.")
    step = check_code(unseal(u["mfa_secret"]), req.json().get("code"), u["mfa_last_step"])
    if step is None:
        fail(req.db, u, req.ip, "verification code")
    codes = new_recovery_codes()
    req.db.execute("UPDATE users SET mfa_enabled=1, mfa_last_step=?, mfa_recovery=?, failed_attempts=0 WHERE id=?", (step, json.dumps([rhash(x) for x in codes]), u["id"]))
    req.db.execute("UPDATE sessions SET mfa_state='ok' WHERE id=?", (c.session["id"],))
    audit(req.db, "auth.mfa_enabled", u, "access_management", "Two-step sign-in turned on", req.ip)
    return {"ok": True, "recovery_codes": codes}


def reauth(req, c, d):
    """Turning it off or replacing recovery codes needs the password and a current code, even in a signed-in session."""
    u = fresh_user(req.db, c)
    if not u["mfa_enabled"]:
        raise HTTPError(409, "not_on", "Two-step sign-in is not on.")
    if not core.verify_password(str(d.get("password") or ""), u["password_hash"]):
        raise HTTPError(400, "bad_current", "The password is not correct.")
    step = check_code(unseal(u["mfa_secret"]), d.get("code"), u["mfa_last_step"])
    if step is None:
        fail(req.db, u, req.ip, "verification code")
    req.db.execute("UPDATE users SET mfa_last_step=? WHERE id=?", (step, u["id"]))
    return u


@router.route("POST", "/api/auth/mfa/disable")
def mfa_disable(req):
    c = need(req, allow_limited=True)
    raise HTTPError(403, "admin_controlled", "Two-step sign-in can only be switched off by a System Administrator.")


@router.route("POST", "/api/auth/mfa/recovery-codes")
def mfa_new_codes(req):
    c = need(req, allow_limited=True)
    u = reauth(req, c, req.json()); codes = new_recovery_codes()
    req.db.execute("UPDATE users SET mfa_recovery=? WHERE id=?", (json.dumps([rhash(x) for x in codes]), u["id"]))
    audit(req.db, "auth.mfa_codes", u, "access_management", "New recovery codes issued (the old ones no longer work)", req.ip)
    return {"recovery_codes": codes}


@router.route("GET", "/api/auth/mfa/status")
def mfa_status(req):
    c = need(req, allow_limited=True, allow_mfa=True)
    u = fresh_user(req.db, c)
    return {"enabled": bool(u["mfa_enabled"]), "required": core.mfa_required(req.db, u, dbm.get_policy(req.db)), "recovery_left": len(json.loads(u["mfa_recovery"] or "[]")), "state": c.mfa_state}


# ------------------------------------------------------------------ administrators: policy, coverage and reset
@router.route("GET", "/api/mfa/overview")
def mfa_overview(req):
    c = need(req, "access_management", "view")
    pol = dbm.get_policy(req.db); users = []
    for u in req.db.execute("SELECT * FROM users WHERE deleted_at IS NULL ORDER BY username"):
        req_ = core.mfa_required(req.db, u, pol)
        users.append({"id": u["id"], "username": u["username"], "full_name": u["full_name"], "roles": core.role_names(req.db, u["id"]), "status": u["status"], "enabled": bool(u["mfa_enabled"]), "required": req_,
                      "state": "on" if u["mfa_enabled"] else ("required, not set up" if req_ else "off"), "admin_on": bool(u["mfa_admin"])})
    return {"required_roles": pol.get("mfa_required_roles") or [], "roles": [r["name"] for r in req.db.execute("SELECT name FROM roles ORDER BY name")], "users": users,
            "enabled": sum(1 for x in users if x["enabled"]), "total": len(users), "gaps": sum(1 for x in users if x["required"] and not x["enabled"]), "can_edit": "edit" in c.perms.get("access_management", set())}


@router.route("PUT", "/api/mfa/policy")
def mfa_policy(req):
    c = need(req, "access_management", "edit")
    names = req.json().get("required_roles")
    valid = {r["name"] for r in req.db.execute("SELECT name FROM roles")}
    if not isinstance(names, list) or any(n not in valid for n in names):
        raise HTTPError(400, "validation", "Choose roles from the list.")
    r = req.db.execute("SELECT value FROM settings WHERE key='policy'").fetchone()
    cur = json.loads(r["value"]) if r else {}
    cur["mfa_required_roles"] = sorted(set(names))
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('policy',?)", (json.dumps(cur),))
    audit(req.db, "policy.mfa", c.user, "access_management", "Two-step sign-in required for: %s" % (", ".join(sorted(set(names))) or "no role"), req.ip)
    return {"required_roles": sorted(set(names))}


@router.route("POST", "/api/mfa/user")
def mfa_user(req):
    """The System Administrator switches two-step sign-in on or off for one person. On: they must set it up at once. Off: their second factor is removed."""
    c = need(req, "access_management", "edit"); b = req.json()
    u = req.db.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (int(b.get("user_id") or 0),)).fetchone()
    if not u:
        raise HTTPError(404, "not_found", "User not found.")
    on = bool(b.get("on"))
    if on:
        req.db.execute("UPDATE users SET mfa_admin=1 WHERE id=?", (u["id"],))
        if not u["mfa_enabled"]:
            req.db.execute("UPDATE sessions SET mfa_state='enroll' WHERE user_id=? AND mfa_state='ok'", (u["id"],))  # takes effect straight away, not at the next sign-in
            if u["email"]:
                outbox(req.db, u["email"], "Two-step sign-in has been switched on for your account", "Your System Administrator has switched on two-step sign-in for your Sentinel account. At your next step you will be asked to set it up with an authenticator app on your phone.", "mfa")
        audit(req.db, "auth.mfa_switched_on", c.user, "access_management", "Two-step sign-in switched ON for %s by the System Administrator" % u["username"], req.ip)
        return {"ok": True, "on": True}
    if u["id"] == c.user["id"]:
        raise HTTPError(409, "self", "You cannot switch off your own two-step sign-in. Ask another System Administrator, or use the console command on the computer.")
    if core.mfa_required(req.db, dict(u, mfa_admin=0), dbm.get_policy(req.db)):
        raise HTTPError(409, "required", "This person's role requires two-step sign-in. Change the role policy first.")
    req.db.execute("UPDATE users SET mfa_admin=0, mfa_enabled=0, mfa_secret=NULL, mfa_recovery=NULL, mfa_last_step=NULL WHERE id=?", (u["id"],))
    core.revoke_sessions(req.db, u["id"], "two-step sign-in switched off by the administrator")
    audit(req.db, "auth.mfa_switched_off", c.user, "access_management", "Two-step sign-in switched OFF for %s by the System Administrator" % u["username"], req.ip)
    return {"ok": True, "on": False}


@router.route("POST", "/api/mfa/reset")
def mfa_reset(req):
    c = need(req, "access_management", "edit")
    uid = int(req.json().get("user_id") or 0)
    u = req.db.execute("SELECT * FROM users WHERE id=? AND deleted_at IS NULL", (uid,)).fetchone()
    if not u:
        raise HTTPError(404, "not_found", "User not found.")
    if u["id"] == c.user["id"]:
        raise HTTPError(409, "self", "You cannot reset your own second factor. Ask another administrator, or use the console command on the computer.")
    req.db.execute("UPDATE users SET mfa_enabled=0, mfa_secret=NULL, mfa_recovery=NULL, mfa_last_step=NULL WHERE id=?", (u["id"],))
    core.revoke_sessions(req.db, u["id"], "second factor reset")
    audit(req.db, "auth.mfa_reset", c.user, "access_management", "Second factor of %s reset by an administrator" % u["username"], req.ip)
    if u["email"]:
        outbox(req.db, u["email"], "Sentinel: your two-step sign-in was reset", "An administrator reset the two-step sign-in on your account. You will be asked to set it up again at your next sign-in if your role requires it.", "security")
    return {"ok": True}
