"""The module kit: one engine for the register-style modules (obligations, policies, vendors, assets, plans, standards...).
Each module is a SPEC in Python (fields, statuses and transitions, rules, the panels of its overview); this file gives all of them the same behaviour:
  validated fields; a status workflow with history on every record; attestation by the owner (or by anyone, for policies); soft delete; Excel export; custom actions and downloads;
  reminders in the daily e-mail; and a published workflow (Workflow Designer) that can replace a module's transitions, with the version a record started on kept with it.
Business rules live in each module's hooks (validate, derive, after, status_rule, attest, seed), so each module's own rules are code that is tested."""
import datetime
import json
import re

from . import db as dbm, xlsxbook
from .api import router, need
from .core import audit, now, role_names
from .p2 import xlsx_response
from .web import HTTPError

SPECS = {}
GOOD, WARN, BAD, BLUE, GREY, PURPLE, TEAL = "#2FA84F", "#F0A04B", "#EF2B2B", "#2F6FD6", "#98A2B3", "#7C5CE0", "#0EA5A5"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def F(key, label, typ="text", req=False, opts=None, hint=None, default=None, table=False, wide=False):
    return {"key": key, "label": label, "type": typ, "req": req, "opts": opts, "hint": hint, "default": default, "table": table, "wide": wide}


def register(module, spec):
    SPECS[module] = spec


def dm(module):
    """The module whose rows a module reads: the three ISO workspaces read the Standards Hub's records, filtered to their standard."""
    return SPECS[module].get("data_module", module)


def get_spec(module, entity=None):
    s = SPECS.get(module)
    if not s:
        raise HTTPError(404, "not_found", "Unknown module.")
    if entity is None:
        return s
    e = s["entities"].get(entity)
    if not e:
        raise HTTPError(404, "not_found", "Unknown record type.")
    return s, e


# ---- panels: what an overview is made of
def tiles(*items):
    out = []
    for x in items:
        out.append({"label": x[0], "value": x[1], "sub": x[2] if len(x) > 2 else "", "color": x[3] if len(x) > 3 else BLUE})
    return {"type": "tiles", "w": 12, "items": out}


def panel(kind, title, w=6, **kw):
    return dict(type=kind, title=title, w=w, **kw)


def pct(a, b):
    return round(100.0 * a / b) if b else None


def hist(db, iid, user, action, detail=""):
    db.execute("INSERT INTO kit_history(item_id,ts,username,action,detail) VALUES(?,?,?,?,?)", (iid, now(), user, action, (detail or "")[:600]))


def owner_matches(db, user, text):
    """Does an owner name or title refer to this person? By mapping, full name, job title, user name, or a part of a compound ('Eric & Astor')."""
    t = re.sub(r"\s+", " ", (text or "").strip()).lower()
    if not t:
        return False
    me = {(user["full_name"] or "").lower(), (user["job_title"] or "").lower(), (user["username"] or "").lower()} - {""}
    first = ((user["full_name"] or "").split() or [""])[0].lower()
    for part in [t] + [p for p in re.split(r"\s*(?:&|/|,|;|\+|\band\b)\s*", t) if p]:
        if part in me or part == first:
            return True
        if db.execute("SELECT 1 FROM owner_aliases WHERE alias=? AND user_id=?", (part, user["id"])).fetchone():
            return True
    return False


# ---- records
def load(db, module, entity, today=None):
    s, e = get_spec(module, entity); today = today or dbm.today(); out = []
    for r in db.execute("SELECT * FROM kit_items WHERE module=? AND entity=? AND deleted_at IS NULL ORDER BY id DESC", (dm(module), entity)):
        out.append(view(db, r, e, today))
    cache = {}
    for i in out:  # a state with a time limit: say so when it is breached, and who it escalates to
        v = i.get("wf_version")
        if v:
            tr = cache.get(v) or cache.setdefault(v, transitions(db, module, entity, v)); lim = tr["sla"].get(i["status"])
            if lim and lim.get("hours"):
                try:
                    since = datetime.datetime.fromisoformat((i.get("updated_at") or i["created_at"]).replace("Z", "")[:19])
                    if (datetime.datetime.utcnow() - since).total_seconds() > lim["hours"] * 3600:
                        i["sla_breached"] = True; i["escalate_to"] = lim.get("escalate_to")
                except (ValueError, TypeError):
                    pass
    flt = s.get("filter")
    return [i for i in out if all(i.get(k) == v for k, v in flt.items())] if flt else out


def view(db, r, e, today):
    d = json.loads(r["data"]); it = dict(d, id=r["id"], ref=r["ref"], status=r["status"], created_at=r["created_at"], updated_at=r["updated_at"], created_by=r["created_by"], wf_version=r["wf_version"]); it["title"] = d.get(e["title_field"]) or r["ref"]
    if e.get("derive"):
        it.update(e["derive"](db, it, today) or {})
    return it


def one(db, module, entity, iid):
    s, e = get_spec(module, entity); r = db.execute("SELECT * FROM kit_items WHERE id=? AND module=? AND entity=? AND deleted_at IS NULL", (iid, dm(module), entity)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Record not found.")
    return r, view(db, r, e, dbm.today())


def coerce(f, v):
    t = f["type"]
    if v is None or (isinstance(v, str) and not v.strip()):
        return None if t in ("date", "datetime", "number", "risk") else (False if t == "bool" else "")
    if t in ("text", "select", "textarea"):
        v = str(v).strip()[:(3000 if t == "textarea" else 400)]
        if t == "select" and f.get("opts") and v not in f["opts"]:
            raise HTTPError(400, "validation", "%s: choose one of %s." % (f["label"], ", ".join(f["opts"])))
        return v
    if t == "date":
        v = str(v).strip()[:10]
        if not DATE.match(v):
            raise HTTPError(400, "validation", "%s must be a date like 2026-12-31." % f["label"])
        return v
    if t == "datetime":
        v = str(v).strip().replace(" ", "T")[:16]
        if not re.match(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$", v):
            raise HTTPError(400, "validation", "%s must be a date and time like 2026-12-31T09:30." % f["label"])
        return v
    if t == "number":
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise HTTPError(400, "validation", "%s must be a number." % f["label"])
        if x < 0:
            raise HTTPError(400, "validation", "%s cannot be negative." % f["label"])
        return int(x) if x == int(x) else x
    if t == "bool":
        return bool(v) and str(v).lower() not in ("0", "false", "no")
    if t == "risk":
        try:
            return int(v)
        except (TypeError, ValueError):
            raise HTTPError(400, "validation", "%s must be a risk." % f["label"])
    return v


def clean(db, c, e, body, old=None):
    data = dict(old or {})
    for f in e["fields"]:
        k = f["key"]
        if k in body:
            data[k] = coerce(f, body[k])
        elif old is None and f.get("default") is not None:
            data[k] = f["default"]() if callable(f["default"]) else f["default"]
    for f in e["fields"]:
        if f.get("req") and data.get(f["key"]) in (None, "", False) and f["type"] != "bool":
            raise HTTPError(400, "validation", "%s is needed." % f["label"])
    if e.get("validate"):
        e["validate"](db, c, data, old)
    return data


def transitions(db, module, entity, version=None):
    """{status: [allowed next]} and role rules. A published workflow for module.entity replaces the default for NEW records; a record keeps the version it started on
    (version 0 means it started on the module's default lifecycle)."""
    s, e = get_spec(module, entity); target = "%s.%s" % (dm(module), entity)
    if version == 0:
        w = None
    elif version:
        w = db.execute("SELECT * FROM workflow_defs WHERE target=? AND version=? AND status IN ('published','superseded')", (target, version)).fetchone()
    else:
        w = db.execute("SELECT * FROM workflow_defs WHERE target=? AND status='published' ORDER BY version DESC LIMIT 1", (target,)).fetchone()
    if w:
        nxt, roles, req, sla = {}, {}, {}, {}
        for t in json.loads(w["transitions"]):
            nxt.setdefault(t["from"], []).append(t["to"]); roles[(t["from"], t["to"])] = t.get("roles") or []; req[(t["from"], t["to"])] = t.get("requires") or []
        for st in json.loads(w["states"]):
            sla[st["name"]] = {"hours": st.get("sla_hours"), "escalate_to": st.get("escalate_to")}
        return {"next": nxt, "roles": roles, "requires": req, "sla": sla, "version": w["version"], "states": [x["name"] for x in json.loads(w["states"])], "published": True}
    return {"next": e.get("next"), "roles": {}, "requires": {}, "sla": {}, "version": 0, "states": e.get("statuses") or [], "published": False}


def create(db, c, module, entity, body):
    s, e = get_spec(module, entity); body = dict(body, **s.get("filter", {})); data = clean(db, c, e, body); tr = transitions(db, module, entity)
    st = (body.get("status") if body.get("status") in tr["states"] else None) or (tr["states"][0] if tr["states"] else None)
    iid = db.execute("INSERT INTO kit_items(module,entity,status,data,wf_version,created_by,created_at) VALUES(?,?,?,?,?,?,?)", (dm(module), entity, st, json.dumps(data), tr["version"], c.user["username"], now())).lastrowid
    ref = "%s-%04d" % (e["prefix"], iid); db.execute("UPDATE kit_items SET ref=? WHERE id=?", (ref, iid)); hist(db, iid, c.user["username"], "created", data.get(e["title_field"]) or "")
    r, it = one(db, module, entity, iid)
    if e.get("after"):
        e["after"](db, c, it, "create", None)
    audit(db, "kit.create", c.user, s["perm"], "%s %s created: %s" % (e["label"], ref, (data.get(e["title_field"]) or "")[:80]), None)
    return one(db, module, entity, iid)[1]


# ---- routes
def meta(db, c, module):
    s = get_spec(module); perms = c.perms.get(s["perm"], set())
    ents = {}
    for k, e in s["entities"].items():
        tr = transitions(db, module, k)
        ents[k] = {"label": e["label"], "plural": e["plural"], "fields": [dict(f, default=f["default"]() if callable(f.get("default")) else f.get("default")) for f in e["fields"]], "statuses": tr["states"], "next": tr["next"], "colors": e.get("colors", {}), "columns": e.get("columns"), "attest": bool(e.get("attest")), "attest_label": e.get("attest_label", "Attest"), "attest_who": e.get("attest_who", "owner"), "readonly": bool(e.get("readonly")), "attest_fields": e.get("attest_fields"), "workflow": {"published": tr["published"], "version": tr["version"]}}
    return {"extras": s.get("extras"), "declare": s.get("declare"), "module": module, "title": s["title"], "crumb": s["crumb"], "color": s.get("color", BLUE), "intro": s.get("intro"), "entities": ents, "tabs": s["tabs"], "actions": [{"id": a["id"], "label": a["label"], "needs": a.get("needs", "edit")} for a in s.get("actions", [])],
            "downloads": [{"id": k, "label": v[0]} for k, v in s.get("downloads", {}).items()], "can": {k: k in perms for k in ("create", "edit", "delete", "export", "approve")}}


def ensure_seed(db, module):
    s = get_spec(module); key = "kit_seed_" + module
    if s.get("data_module") and s["data_module"] != module:
        ensure_seed(db, s["data_module"])
    if s.get("seed") and not db.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone():
        s["seed"](db); db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, now()))


@router.route("GET", "/api/kit/<module>")
def kit_overview(req):
    module = req.params["module"]; s = get_spec(module); c = need(req, s["perm"], "view"); ensure_seed(req.db, module); m = meta(req.db, c, module); today = dbm.today()
    if s.get("sync"):
        s["sync"](req.db, c)
    m["panels"] = s["overview"](req.db, c, today); m["today"] = today.isoformat()
    return m


@router.route("GET", "/api/kit/<module>/<entity>")
def kit_list(req):
    module, entity = req.params["module"], req.params["entity"]; s, e = get_spec(module, entity); c = need(req, s["perm"], "view"); ensure_seed(req.db, module)
    if s.get("sync"):
        s["sync"](req.db, c)
    its = load(req.db, module, entity); q = (req.query.get("q") or "").lower(); st = req.query.get("status")
    if st:
        its = [i for i in its if i["status"] == st]
    if q:
        its = [i for i in its if q in " ".join(str(v) for k, v in i.items() if isinstance(v, (str, int, float))).lower()]
    counts = {}
    for i in load(req.db, module, entity):
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    return {"items": its[:600], "total": len(its), "counts": counts}


@router.route("POST", "/api/kit/<module>/<entity>")
def kit_create(req):
    module, entity = req.params["module"], req.params["entity"]; s, e = get_spec(module, entity); c = need(req, s["perm"], "create")
    if e.get("readonly"):
        raise HTTPError(409, "readonly", "These records are made by other steps, not typed in.")
    return create(req.db, c, module, entity, req.json())


@router.route("GET", "/api/kit/<module>/<entity>/<int:iid>")
def kit_get(req):
    module, entity, iid = req.params["module"], req.params["entity"], int(req.params["iid"]); s, e = get_spec(module, entity); need(req, s["perm"], "view"); r, it = one(req.db, module, entity, iid)
    return {"item": it, "history": [dict(h) for h in req.db.execute("SELECT ts, username, action, detail FROM kit_history WHERE item_id=? ORDER BY id DESC LIMIT 40", (iid,))]}


@router.route("PUT", "/api/kit/<module>/<entity>/<int:iid>")
def kit_edit(req):
    module, entity, iid = req.params["module"], req.params["entity"], int(req.params["iid"]); s, e = get_spec(module, entity); c = need(req, s["perm"], "edit"); r, old = one(req.db, module, entity, iid)
    if e.get("readonly"):
        raise HTTPError(409, "readonly", "These records are made by other steps and cannot be edited.")
    body = dict(req.json()); body.pop("status", None); data = clean(req.db, c, e, body, json.loads(r["data"]))
    changed = [k for k in data if json.loads(r["data"]).get(k) != data[k]]
    req.db.execute("UPDATE kit_items SET data=?, updated_at=? WHERE id=?", (json.dumps(data), now(), iid)); hist(req.db, iid, c.user["username"], "edited", "changed: " + ", ".join(changed[:8]))
    r2, it = one(req.db, module, entity, iid)
    if e.get("after"):
        e["after"](req.db, c, it, "update", old)
    audit(req.db, "kit.edit", c.user, s["perm"], "%s %s edited" % (e["label"], r["ref"]), req.ip)
    return it


@router.route("POST", "/api/kit/<module>/<entity>/<int:iid>/status")
def kit_status(req):
    module, entity, iid = req.params["module"], req.params["entity"], int(req.params["iid"]); s, e = get_spec(module, entity); c = need(req, s["perm"], "edit"); r, it = one(req.db, module, entity, iid); b = req.json(); new = str(b.get("status") or ""); note = str(b.get("note") or "").strip()[:500]
    tr = transitions(req.db, module, entity, r["wf_version"] or 0)
    if new not in tr["states"]:
        raise HTTPError(400, "validation", "That is not a status of this record.")
    nxt = tr["next"]
    if nxt is not None and new != r["status"] and new not in nxt.get(r["status"], []):
        raise HTTPError(409, "state", "From %s a record can move to: %s." % (r["status"], ", ".join(nxt.get(r["status"], [])) or "nowhere (it is final)"))
    rl = tr["roles"].get((r["status"], new))
    if rl and not (set(rl) & set(role_names(req.db, c.user["id"]))):
        raise HTTPError(403, "forbidden", "Only %s can make this change (set in the workflow)." % " or ".join(rl))
    for k in tr["requires"].get((r["status"], new), []):
        if it.get(k) in (None, "", False):
            raise HTTPError(400, "validation", "'%s' must be filled in before this change." % k)
    if e.get("status_rule"):
        e["status_rule"](req.db, c, it, new, note)
    req.db.execute("UPDATE kit_items SET status=?, updated_at=? WHERE id=?", (new, now(), iid)); hist(req.db, iid, c.user["username"], "status %s \u2192 %s" % (r["status"], new), note)
    r2, it2 = one(req.db, module, entity, iid)
    if e.get("after"):
        e["after"](req.db, c, it2, "status", it)
    audit(req.db, "kit.status", c.user, s["perm"], "%s %s: %s \u2192 %s" % (e["label"], r["ref"], r["status"], new), req.ip)
    return it2


@router.route("POST", "/api/kit/<module>/<entity>/<int:iid>/attest")
def kit_attest(req):
    module, entity, iid = req.params["module"], req.params["entity"], int(req.params["iid"]); s, e = get_spec(module, entity); c = need(req, s["perm"], "view"); r, it = one(req.db, module, entity, iid)
    if not e.get("attest"):
        raise HTTPError(409, "state", "This record is not attested.")
    if e.get("attest_who", "owner") == "owner" and not (owner_matches(req.db, c.user, it.get(e.get("owner_field") or "owner")) or "edit" in c.perms.get(s["perm"], set())):
        raise HTTPError(403, "forbidden", "Only the owner (%s), or the compliance team, can attest this." % (it.get(e.get("owner_field") or "owner") or "not set"))
    res = e["attest"](req.db, c, it, req.json()) or {}
    hist(req.db, iid, c.user["username"], "attested", res.get("note", "")); audit(req.db, "kit.attest", c.user, s["perm"], "%s %s attested" % (e["label"], r["ref"]), req.ip)
    return dict(one(req.db, module, entity, iid)[1], _result=res)


@router.route("DELETE", "/api/kit/<module>/<entity>/<int:iid>")
def kit_delete(req):
    module, entity, iid = req.params["module"], req.params["entity"], int(req.params["iid"]); s, e = get_spec(module, entity); c = need(req, s["perm"], "delete"); r, it = one(req.db, module, entity, iid)
    req.db.execute("UPDATE kit_items SET deleted_at=? WHERE id=?", (now(), iid)); hist(req.db, iid, c.user["username"], "deleted", ""); audit(req.db, "kit.delete", c.user, s["perm"], "%s %s deleted" % (e["label"], r["ref"]), req.ip)
    return {"ok": True}


@router.route("POST", "/api/kit/<module>/do/<action>")
def kit_action(req):
    module, aid = req.params["module"], req.params["action"]; s = get_spec(module); a = next((x for x in s.get("actions", []) if x["id"] == aid), None)
    if not a:
        raise HTTPError(404, "not_found", "Unknown action.")
    c = need(req, s["perm"], a.get("needs", "edit")); ensure_seed(req.db, module); res = a["run"](req.db, c, req.json()) or {}
    audit(req.db, "kit.action", c.user, s["perm"], "%s: %s" % (s["title"], a["label"]), req.ip)
    return res


@router.route("GET", "/api/kit/<module>/download/<name>")
def kit_download(req):
    module, name = req.params["module"], req.params["name"]; s = get_spec(module); c = need(req, s["perm"], "export"); ensure_seed(req.db, module); d = s.get("downloads", {}).get(name)
    if not d:
        raise HTTPError(404, "not_found", "Unknown download.")
    data, fn = d[1](req.db, c); audit(req.db, "kit.download", c.user, s["perm"], "%s downloaded" % fn, req.ip)
    return xlsx_response(data, fn)


@router.route("GET", "/api/kit/<module>/all/export.xlsx")
def kit_export(req):
    module = req.params["module"]; s = get_spec(module); c = need(req, s["perm"], "export"); sheets = []
    for k, e in s["entities"].items():
        rows = load(req.db, module, k); cols = [f["key"] for f in e["fields"]]
        body = [[(h, 1) for h in ["Ref", "Status"] + [f["label"] for f in e["fields"]]]] + [[i["ref"], i["status"]] + [("yes" if i.get(x) is True else "no" if i.get(x) is False else i.get(x)) for x in cols] for i in rows]
        sheets.append((e["plural"][:30], [[(s["title"] + ": " + e["plural"], 3)], []] + body, [14, 16] + [24] * len(cols)))
    audit(req.db, "kit.export", c.user, s["perm"], "%s exported to Excel" % s["title"], req.ip)
    return xlsx_response(xlsxbook.write(sheets), "Sentinel_%s.xlsx" % module)


def reminder_items(db, today, horizon):
    """Due and overdue items from every module that defines reminders, for the daily e-mail."""
    out = []
    for module, s in SPECS.items():
        if s.get("reminders"):
            try:
                out += s["reminders"](db, today, horizon)
            except Exception:
                pass
    return out


# ---- small shared helpers for the module specs
def pd(x):
    return datetime.date.fromisoformat(x[:10]) if x else None


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12); y += d.year; m += 1
    return datetime.date(y, m, min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]))


def harare_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=dbm.config.TZ_HOURS)


class _Sys:
    user = {"id": 0, "username": "system", "full_name": "Sentinel", "job_title": "", "department": "Risk"}
    perms = {}


SYS = _Sys()


def seed_item(db, module, entity, data, status=None, by="seed"):
    s, e = get_spec(module, entity); iid = db.execute("INSERT INTO kit_items(module,entity,status,data,wf_version,created_by,created_at) VALUES(?,?,?,?,0,?,?)", (module, entity, status or (e.get("statuses") or [None])[0], json.dumps(data), by, now())).lastrowid
    db.execute("UPDATE kit_items SET ref=? WHERE id=?", ("%s-%04d" % (e["prefix"], iid), iid)); hist(db, iid, by, "created", "seeded")
    return iid


def set_data(db, iid, **kv):
    r = db.execute("SELECT data FROM kit_items WHERE id=?", (iid,)).fetchone(); d = json.loads(r["data"]); d.update(kv)
    db.execute("UPDATE kit_items SET data=?, updated_at=? WHERE id=?", (json.dumps(d), now(), iid)); return d


def set_status(db, iid, status):
    db.execute("UPDATE kit_items SET status=?, updated_at=? WHERE id=?", (status, now(), iid))


def make_action(db, c, title, desc, owner, days, risk_id=None):
    from . import p5
    out = p5.make_action(db, c, {"title": title[:200], "description": (desc or "")[:600], "owner_name": owner or "Head of Risk", "due_date": (dbm.today() + datetime.timedelta(days=days)).isoformat(), "risk_id": risk_id, "source": "manual", "priority": "High"})
    return out["ref"]


def make_incident(db, c, title, desc, category, severity, owner):
    iid = db.execute("INSERT INTO incidents(title,kind,category,severity,occurred_on,detected_at,description,status,owner,created_at,created_by) VALUES(?,?,?,?,?,?,?,'open',?,?,?)", (title[:200], "incident", category, severity, dbm.today().isoformat(), now(), desc[:1500], owner or "Head of Compliance and ML/CTF", now(), c.user["id"] or None)).lastrowid
    ref = "INC-%03d" % iid; db.execute("UPDATE incidents SET ref=? WHERE id=?", (ref, iid)); return ref


def due_item(kind, it, title_key, due_key, owner_key, url):
    return {"kind": kind, "ref": it["ref"], "title": str(it.get(title_key) or "")[:120], "due": it.get(due_key), "owner_text": it.get(owner_key), "owner_id": None, "level": None, "url": url}
