"""E-mail for Sentinel: links Sentinel to the company's mail server (SMTP) and sends, once a day, each person a digest of THEIR items that are due soon or overdue
(actions, tracker tasks, audit findings, control retests), plus a roll-up of everything overdue for the Head of Risk. Also delivers the messages other modules queue
(development briefs, two-step sign-in notices). Controlled only by a System Administrator (Administration > E-mail). Nothing is sent until it is switched on, and the
backlog queued before that moment is not sent. The password is stored encrypted. A quiet day sends nothing."""
import datetime
import json
import re
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage

from . import db as dbm, mfa
from .api import router, need, need_str
from .core import audit, now, outbox
from .web import HTTPError

DEFAULTS = {"enabled": False, "host": "", "port": 587, "security": "starttls", "username": "", "from_addr": "", "from_name": "EcoCash Sentinel", "base_url": "", "reminder_time": "07:30", "days_ahead": 3, "weekdays_only": True,
            "overdue": True, "digest_head": True, "head_roles": ["Head of Risk"], "allowed_domains": [], "max_per_run": 200, "enabled_at": None}
_lock = threading.Lock()


def settings(db):
    r = db.execute("SELECT value FROM settings WHERE key='mail'").fetchone()
    out = dict(DEFAULTS)
    try:
        out.update(json.loads(r["value"]) if r else {})
    except ValueError:
        pass
    return out


def save(db, cfg):
    db.execute("INSERT INTO settings(key,value) VALUES('mail',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(cfg),))


def password(db):
    r = db.execute("SELECT value FROM settings WHERE key='mail_password'").fetchone()
    try:
        return mfa.unseal(r["value"]) if r else None
    except Exception:
        return None


def ready(cfg):
    return bool(cfg["enabled"] and cfg["host"] and cfg["from_addr"])


# ------------------------------------------------------------------ sending
def deliver(cfg, pw, to, subject, body, attachments=None):
    """Sends one message. Raises with a plain reason; the password never appears in the message."""
    m = EmailMessage(); m["From"] = "%s <%s>" % (cfg["from_name"], cfg["from_addr"]) if cfg["from_name"] else cfg["from_addr"]; m["To"] = to; m["Subject"] = subject[:200]; m["X-Mailer"] = "EcoCash Sentinel"; m.set_content(body)
    for fn, data, mime in attachments or []:
        mt, st = mime.split("/", 1); m.add_attachment(data, maintype=mt, subtype=st, filename=fn)
    ctx = ssl.create_default_context()
    try:
        if cfg["security"] == "ssl":
            s = smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), timeout=25, context=ctx)
        else:
            s = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=25)
        with s:
            s.ehlo()
            if cfg["security"] == "starttls":
                s.starttls(context=ctx); s.ehlo()
            if cfg["username"]:
                s.login(cfg["username"], pw or "")
            s.send_message(m)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("the mail server refused the user name or password (some mail systems block password sign-in for programs: ask your mail administrator for an app password or an internal relay)")
    except smtplib.SMTPRecipientsRefused:
        raise RuntimeError("the mail server refused the recipient address")
    except smtplib.SMTPException as e:
        raise RuntimeError("the mail server reported: %s" % str(e)[:140])
    except (OSError, ssl.SSLError) as e:
        raise RuntimeError("could not connect to %s:%s (%s)" % (cfg["host"], cfg["port"], str(getattr(e, "reason", None) or e)[:100]))


def allowed(cfg, to):
    doms = [d.lower().lstrip("@") for d in cfg["allowed_domains"]]
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to or "")) and (not doms or to.lower().rsplit("@", 1)[1] in doms)


def flush(db, limit=None):
    """Sends the queued messages. Returns (sent, failed, skipped)."""
    cfg = settings(db)
    if not ready(cfg):
        return 0, 0, 0
    pw = password(db); sent = failed = skipped = 0
    for r in db.execute("SELECT * FROM outbox WHERE status='queued' ORDER BY id LIMIT ?", (limit or cfg["max_per_run"],)).fetchall():
        if not allowed(cfg, r["to_addr"]):
            db.execute("UPDATE outbox SET status='skipped', error=? WHERE id=?", ("address not allowed or invalid", r["id"])); skipped += 1; continue
        try:
            deliver(cfg, pw, r["to_addr"], r["subject"], r["body"])
            db.execute("UPDATE outbox SET status='sent', sent_at=?, attempts=attempts+1, error=NULL WHERE id=?", (now(), r["id"])); sent += 1
        except RuntimeError as e:
            n = r["attempts"] + 1
            db.execute("UPDATE outbox SET status=?, attempts=?, error=? WHERE id=?", ("failed" if n >= 3 else "queued", n, str(e)[:240], r["id"])); failed += 1
            if "could not connect" in str(e) or "refused the user" in str(e):
                break  # no point trying the rest while the server is unreachable
    return sent, failed, skipped


# ------------------------------------------------------------------ who owns what
def owner_users(db, text, cache):
    """Active users with an e-mail address that an owner text refers to. Tried in this order: a mapping the administrator made, full name, job title, user name; then, for a text such as
    'Eric & Astor' or 'CTO / IT Operations', each part on its own, including a first name that belongs to exactly one user."""
    t = re.sub(r"\s+", " ", (text or "").strip()).lower()
    if not t or t in ("none", "n/a"):
        return []
    if t in cache:
        return cache[t]
    base = "SELECT id, full_name, email, job_title FROM users WHERE status='active' AND deleted_at IS NULL AND email IS NOT NULL AND email != ''"
    found = {}

    def look(x, first_name=False):
        for u in db.execute(base + " AND (id IN (SELECT user_id FROM owner_aliases WHERE alias=?) OR lower(full_name)=? OR lower(job_title)=? OR lower(username)=?)", (x, x, x, x)):
            found[u["id"]] = dict(u)
        if first_name and not found.get("_"):
            c = [u for u in db.execute(base) if (u["full_name"] or "").split()[:1] and u["full_name"].split()[0].lower() == x]
            if len(c) == 1:
                found[c[0]["id"]] = dict(c[0])
    look(t)
    if not found:
        for part in [p for p in re.split(r"\s*(?:&|/|,|;|\+|\band\b)\s*", t) if p]:
            look(part, True)
    cache[t] = list(found.values()); return cache[t]


def items(db, today, days_ahead):
    """Everything due soon or overdue, with its owner text and (when known) owner user: a list of dicts."""
    horizon = (today + datetime.timedelta(days=days_ahead)).isoformat(); td = today.isoformat(); out = []
    for r in db.execute("SELECT ref, title, owner_name, COALESCE(revised_due, due_date) due, esc_level, priority FROM actions WHERE deleted_at IS NULL AND status NOT IN ('closed','cancelled') AND COALESCE(revised_due, due_date) IS NOT NULL AND COALESCE(revised_due, due_date) <= ?", (horizon,)):
        out.append({"kind": "Action", "ref": r["ref"], "title": r["title"], "due": r["due"], "owner_text": r["owner_name"], "owner_id": None, "level": r["esc_level"], "url": "#/m/actions_issues"})
    action_refs = {x["ref"] for x in out}  # the tasks Sentinel creates for an action would list the same thing twice
    for r in db.execute("SELECT id, title, owner_text, owner_id, COALESCE(revised, deadline) due FROM tasks WHERE deleted_at IS NULL AND completed_at IS NULL AND COALESCE(assignment,'') NOT IN ('Cancelled') AND COALESCE(revised, deadline) IS NOT NULL AND COALESCE(revised, deadline) <= ?", (horizon,)):
        mt = re.match(r"^Action (ACT-\d+)", r["title"] or "")
        if mt and mt.group(1) in action_refs:
            continue
        out.append({"kind": "Task", "ref": "TASK-%d" % r["id"], "title": r["title"], "due": (r["due"] or "")[:10], "owner_text": r["owner_text"], "owner_id": r["owner_id"], "level": None, "url": "#/m/tracker"})
    for r in db.execute("SELECT ref, title, owner_name, owner_id, due_date FROM audit_findings WHERE deleted_at IS NULL AND status IN ('open','responded') AND due_date IS NOT NULL AND due_date <= ?", (horizon,)):
        out.append({"kind": "Audit finding", "ref": r["ref"], "title": r["title"], "due": r["due_date"], "owner_text": r["owner_name"], "owner_id": r["owner_id"], "level": None, "url": "#/m/audit_workspace"})
    for r in db.execute("SELECT k.ref, k.statement, k.owner, k.next_due FROM risk_controls k JOIN risks r ON r.id=k.risk_id WHERE r.deleted_at IS NULL AND (r.is_sample IS NULL OR r.is_sample=0) AND k.next_due IS NOT NULL AND k.next_due <= ? AND k.owner IS NOT NULL AND k.owner != '' AND lower(k.owner) != 'none'", (horizon,)):
        out.append({"kind": "Control test", "ref": r["ref"] or "control", "title": (r["statement"] or "Control retest")[:120], "due": r["next_due"], "owner_text": r["owner"], "owner_id": None, "level": None, "url": "#/m/control_library_testing"})
    try:  # due dates from the compliance, standards and resilience modules (policy reviews, vendor contracts, obligation statements, vulnerabilities...)
        from . import kit
        out += [x for x in kit.reminder_items(db, today, today + datetime.timedelta(days=days_ahead)) if x.get("due")]
    except Exception:
        pass
    for x in out:
        x["days"] = (datetime.date.fromisoformat(x["due"][:10]) - today).days if x["due"] else 0
    return out


def digests(db, today=None):
    """{email: {name, items}} and the Head of Risk roll-up, built but not sent. Returns (per_user, head_lines, unmatched)."""
    cfg = settings(db); today = today or dbm.today(); its = items(db, today, int(cfg["days_ahead"])); cache = {}; per = {}; unmatched = []
    for x in its:
        users = [u for u in [db.execute("SELECT id, full_name, email FROM users WHERE id=? AND status='active' AND email IS NOT NULL AND email != ''", (x["owner_id"],)).fetchone()] if u] if x["owner_id"] else []
        users = [dict(u) for u in users] or owner_users(db, x["owner_text"], cache)
        if not x["owner_id"] and not users:
            unmatched.append(x); continue
        for u in users:
            d = per.setdefault(u["email"], {"name": u["full_name"], "items": []}); d["items"].append(x)
    for d in per.values():
        d["items"].sort(key=lambda z: z["days"])
    return per, [x for x in its if x["days"] < 0], unmatched


def line(x):
    when = "OVERDUE by %d day%s" % (-x["days"], "" if x["days"] == -1 else "s") if x["days"] < 0 else ("due TODAY" if x["days"] == 0 else "due in %d day%s" % (x["days"], "" if x["days"] == 1 else "s"))
    return "  - [%s] %s: %s (%s, %s)" % (x["kind"], x["ref"], x["title"][:90], when, x["due"])


def compose(cfg, name, its):
    od = [x for x in its if x["days"] < 0]; soon = [x for x in its if x["days"] >= 0]; base = (cfg["base_url"] or "").rstrip("/")
    parts = ["Hello %s," % (name.split()[0] if name else "there"), ""]
    if cfg["overdue"] and od:
        parts += ["OVERDUE (%d):" % len(od)] + [line(x) for x in od[:25]] + [""]
    if soon:
        parts += ["DUE IN THE NEXT %d DAYS (%d):" % (cfg["days_ahead"], len(soon))] + [line(x) for x in soon[:25]] + [""]
    parts += ["Open Sentinel to update them: %s" % (base + "/app#/home" if base else "your Sentinel address"), "", "You receive this reminder because these items are assigned to you. A System Administrator controls it (Administration > E-mail).", "-- EcoCash Sentinel"]
    subj = "Sentinel reminder: %s" % ", ".join(p for p in ("%d overdue" % len(od) if od and cfg["overdue"] else "", "%d due soon" % len(soon) if soon else "") if p)
    return subj, "\n".join(parts)


def compose_head(cfg, overdue, unmatched):
    base = (cfg["base_url"] or "").rstrip("/"); by = {}
    for x in overdue:
        by.setdefault(x["owner_text"] or "no owner", []).append(x)
    parts = ["Overdue across Sentinel today: %d item(s) with %d owner(s)." % (len(overdue), len(by)), ""]
    for o, xs in sorted(by.items(), key=lambda z: -len(z[1]))[:15]:
        parts.append("%s (%d): %s" % (o, len(xs), "; ".join("%s %s (%dd)" % (x["kind"], x["ref"], -x["days"]) for x in sorted(xs, key=lambda z: z["days"])[:4])))
    if unmatched:
        parts += ["", "%d item(s) are owned by a name or title that matches no Sentinel user with an e-mail address, so no reminder reached anyone: %s" % (len(unmatched), "; ".join(sorted({(x["owner_text"] or "no owner") for x in unmatched})[:8]))]
    parts += ["", "Open Sentinel: %s" % (base + "/app#/m/actions_issues" if base else "your Sentinel address"), "-- EcoCash Sentinel"]
    return "Sentinel: %d overdue item(s) need attention" % len(overdue), "\n".join(parts)


def queue_daily(db, today=None):
    """Queues today's reminders. Returns a summary. Quiet when there is nothing to say."""
    cfg = settings(db); per, overdue, unmatched = digests(db, today); n = 0
    for email, d in per.items():
        subj, body = compose(cfg, d["name"], d["items"])
        outbox(db, email, subj, body, "reminder"); n += 1
    head = 0
    if cfg["digest_head"] and (overdue or unmatched):
        q = ",".join("?" for _ in cfg["head_roles"]) or "''"
        for u in db.execute("SELECT DISTINCT u.email FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.name IN (%s) AND u.status='active' AND u.deleted_at IS NULL AND u.email IS NOT NULL AND u.email != ''" % q, cfg["head_roles"]).fetchall():
            subj, body = compose_head(cfg, overdue, unmatched); outbox(db, u["email"], subj, body, "reminder_head"); head += 1
    try:
        from . import integ
        integ.alert_admins(db)  # connectors that are failed or delayed, and keys due for rotation
    except Exception:
        pass
    return {"people": n, "head": head, "items": sum(len(d["items"]) for d in per.values()), "overdue": len(overdue), "unmatched": len(unmatched)}


def run_daily(db, force=False):
    cfg = settings(db)
    if not ready(cfg):
        return None
    today = dbm.today(); last = db.execute("SELECT value FROM settings WHERE key='mail_last_run'").fetchone()
    if not force:
        hh, mm = [int(x) for x in (cfg["reminder_time"] + ":0").split(":")[:2]]
        local = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=dbm.config.TZ_HOURS)
        if (local.hour, local.minute) < (hh, mm) or (last and last["value"] == today.isoformat()) or (cfg["weekdays_only"] and today.weekday() >= 5):
            return None
    res = queue_daily(db, today); db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('mail_last_run',?)", (today.isoformat(),)); res["sent"], res["failed"], res["skipped"] = flush(db)
    return res


def scheduler():
    time.sleep(45)
    while True:
        if _lock.acquire(blocking=False):
            try:
                c = dbm.connect()
                try:
                    from . import web
                    with web.hold("mailer #1"):
                        run_daily(c); flush(c)
                        try:
                            from . import reports
                            reports.run_due(c)  # scheduled reports
                        except Exception:
                            pass
                        c.commit()
                finally:
                    c.close()
            except Exception:
                pass
            finally:
                _lock.release()
        time.sleep(60)


def start_scheduler():
    t = threading.Thread(target=scheduler, name="sentinel-mail", daemon=True); t.start(); return t


# ------------------------------------------------------------------ administrator screens
def public(db):
    cfg = settings(db); cfg.pop("enabled_at", None)
    c = db.execute("SELECT status, COUNT(*) n FROM outbox GROUP BY status").fetchall(); last = db.execute("SELECT value FROM settings WHERE key='mail_last_run'").fetchone()
    return {"settings": cfg, "password_set": bool(password(db)), "counts": {r["status"]: r["n"] for r in c}, "last_run": last["value"] if last else None, "ready": ready(settings(db)), "enabled_at": settings(db)["enabled_at"],
            "recent": [dict(r) for r in db.execute("SELECT id, ts, to_addr, subject, kind, status, sent_at, error, attempts FROM outbox ORDER BY id DESC LIMIT 25")]}


@router.route("GET", "/api/mail")
def mail_get(req):
    need(req, "administration", "view")
    return public(req.db)


@router.route("POST", "/api/mail/settings")
def mail_settings(req):
    c = need(req, "administration", "edit"); b = req.json(); cfg = settings(req.db); was = cfg["enabled"]
    for k in ("host", "username", "from_addr", "from_name", "base_url", "reminder_time"):
        if k in b:
            cfg[k] = str(b[k] or "").strip()[:200]
    if "port" in b:
        try:
            cfg["port"] = max(1, min(65535, int(b["port"])))
        except (TypeError, ValueError):
            raise HTTPError(400, "validation", "The port must be a number.")
    if b.get("security") in ("starttls", "ssl", "none"):
        cfg["security"] = b["security"]
    for k in ("weekdays_only", "overdue", "digest_head"):
        if k in b:
            cfg[k] = bool(b[k])
    if "days_ahead" in b:
        cfg["days_ahead"] = max(0, min(30, int(b["days_ahead"])))
    if not re.match(r"^\d{1,2}:\d{2}$", cfg["reminder_time"]) or int(cfg["reminder_time"].split(":")[0]) > 23 or int(cfg["reminder_time"].split(":")[1]) > 59:
        raise HTTPError(400, "validation", "The reminder time must look like 07:30.")
    if cfg["from_addr"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", cfg["from_addr"]):
        raise HTTPError(400, "validation", "The sender address does not look like an e-mail address.")
    if isinstance(b.get("allowed_domains"), list):
        cfg["allowed_domains"] = sorted({re.sub(r"[^a-z0-9.-]", "", str(d).lower().lstrip("@")) for d in b["allowed_domains"] if str(d).strip()})[:20]
    if isinstance(b.get("head_roles"), list):
        cfg["head_roles"] = [str(r)[:60] for r in b["head_roles"]][:6]
    if b.get("password"):
        req.db.execute("INSERT INTO settings(key,value) VALUES('mail_password',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mfa.seal(str(b["password"])),))
    if "enabled" in b:
        on = bool(b["enabled"])
        if on and not (cfg["host"] and cfg["from_addr"]):
            raise HTTPError(409, "incomplete", "Enter the mail server and the sender address first.")
        if on and not was:  # the backlog queued before e-mail was linked is not sent: only what happens from now on
            req.db.execute("UPDATE outbox SET status='skipped', error='queued before e-mail was linked' WHERE status='queued'"); cfg["enabled_at"] = now()
            hh, mm = [int(x) for x in (cfg["reminder_time"] + ":0").split(":")[:2]]; local = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=dbm.config.TZ_HOURS)
            if (local.hour, local.minute) >= (hh, mm):  # switched on after today's time: nobody is surprised by a burst of reminders; the first digest goes at the next scheduled time
                req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('mail_last_run',?)", (dbm.today().isoformat(),))
        cfg["enabled"] = on
    save(req.db, cfg)
    audit(req.db, "mail.settings", c.user, "administration", "E-mail settings changed (%s, server %s:%s, reminders %s)" % ("ON" if cfg["enabled"] else "off", cfg["host"] or "-", cfg["port"], cfg["reminder_time"]), req.ip)
    return public(req.db)


@router.route("POST", "/api/mail/test")
def mail_test(req):
    c = need(req, "administration", "edit"); to = need_str(req.json(), "to", "Address", 200); cfg = settings(req.db)
    if not (cfg["host"] and cfg["from_addr"]):
        raise HTTPError(409, "incomplete", "Enter the mail server and the sender address first.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to):
        raise HTTPError(400, "validation", "That does not look like an e-mail address.")
    try:
        deliver(cfg, password(req.db), to, "Sentinel test message", "This is a test message from EcoCash Sentinel.\n\nIf you can read it, Sentinel is linked to your mail server and can send reminders.\nSent by %s on %s.\n" % (c.user["full_name"], now()))
    except RuntimeError as e:
        raise HTTPError(502, "mail_failed", "The test message was not sent: %s." % e)
    audit(req.db, "mail.test", c.user, "administration", "Test e-mail sent to %s" % to, req.ip)
    return {"ok": True}


@router.route("GET", "/api/mail/preview")
def mail_preview(req):
    need(req, "administration", "view"); cfg = settings(req.db); per, overdue, unmatched = digests(req.db)
    return {"people": [{"email": e, "name": d["name"], "overdue": sum(1 for x in d["items"] if x["days"] < 0), "soon": sum(1 for x in d["items"] if x["days"] >= 0)} for e, d in sorted(per.items())], "overdue_total": len(overdue), "unmatched_owners": sorted({(x["owner_text"] or "no owner") for x in unmatched})[:20], "days_ahead": cfg["days_ahead"]}


@router.route("POST", "/api/mail/remind-now")
def mail_remind_now(req):
    c = need(req, "administration", "edit"); cfg = settings(req.db)
    if not ready(cfg):
        raise HTTPError(409, "not_ready", "Switch e-mail on first (server, sender address and the On switch).")
    res = run_daily(req.db, force=True)
    audit(req.db, "mail.remind_now", c.user, "administration", "Reminders sent now: %d people, %d sent, %d failed" % (res["people"], res["sent"], res["failed"]), req.ip)
    return res


@router.route("GET", "/api/mail/aliases")
def aliases_get(req):
    """Owner names that are not a user's name, and the mappings that make a reminder reach a person."""
    need(req, "administration", "view"); today = dbm.today(); cfg = settings(req.db); per, overdue, unmatched = digests(req.db, today)
    users = [{"id": u["id"], "name": u["full_name"], "email": u["email"]} for u in req.db.execute("SELECT id, full_name, email FROM users WHERE status='active' AND deleted_at IS NULL AND email IS NOT NULL AND email != '' ORDER BY full_name")]
    owners = {}
    for x in unmatched:
        owners[(x["owner_text"] or "no owner")] = owners.get((x["owner_text"] or "no owner"), 0) + 1
    return {"aliases": [{"alias": r["alias"], "user_id": r["user_id"], "name": r["full_name"]} for r in req.db.execute("SELECT a.alias, a.user_id, u.full_name FROM owner_aliases a JOIN users u ON u.id=a.user_id ORDER BY a.alias")], "users": users, "unmatched": [{"owner": k, "items": v} for k, v in sorted(owners.items(), key=lambda z: -z[1])]}


@router.route("POST", "/api/mail/aliases")
def aliases_set(req):
    """Maps an owner name (for example 'CTO / IT Operations') to a person, or removes the mapping (user_id empty)."""
    c = need(req, "administration", "edit"); b = req.json(); alias = re.sub(r"\s+", " ", need_str(b, "alias", "Owner name", 120)).lower()
    if not b.get("user_id"):
        req.db.execute("DELETE FROM owner_aliases WHERE alias=?", (alias,)); audit(req.db, "mail.alias_remove", c.user, "administration", "Owner name '%s' unmapped" % alias, req.ip); return {"ok": True}
    u = req.db.execute("SELECT full_name, email FROM users WHERE id=? AND status='active' AND deleted_at IS NULL", (int(b["user_id"]),)).fetchone()
    if not u or not (u["email"] or "").strip():
        raise HTTPError(400, "validation", "Choose an active user who has an e-mail address.")
    req.db.execute("INSERT INTO owner_aliases(alias,user_id) VALUES(?,?) ON CONFLICT(alias) DO UPDATE SET user_id=excluded.user_id", (alias, int(b["user_id"]))); audit(req.db, "mail.alias", c.user, "administration", "Owner name '%s' mapped to %s" % (alias, u["full_name"]), req.ip)
    return {"ok": True}
