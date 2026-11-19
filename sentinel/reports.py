"""Data & Reports (BRD 9.23): the library of reports built from governed datasets. A report is a dataset, chosen columns, filters, a sort and an optional grouping; it can be run, downloaded
(Excel or CSV, logged and watermarked with the user and time), shared, scheduled (e-mailed with the file attached), deleted to a 90-day Deleted items tab and restored with its schedule and
history. Datasets respect the rights of whoever runs them (a dataset needs view rights on its module). Power BI reads the same datasets through a key from the Integration Hub."""
import csv
import datetime
import hashlib
import hmac
import io
import json

from . import analytics, db as dbm, kit, p2, xlsxbook
from .api import router, need
from .core import audit, now, role_names
from .p2 import xlsx_response
from .web import HTTPError, Response

OPS = ["=", "!=", "contains", ">", "<", ">=", "<=", "is empty", "is not empty"]
FN = ["count", "sum", "avg", "min", "max"]


def sql(perm, q, cols):
    def load(db, c):
        return [dict(r) for r in db.execute(q)]
    return {"perm": perm, "cols": cols, "load": load}


def risks_load(db, c):
    rows, _ = analytics.risk_rows(db, c); return [{k: r.get(k) for k in ("ref", "source_ref", "title", "category", "system", "owner", "res_l", "res_c", "rrr", "emv_i", "loa")} for r in rows]


def kpis_load(db, c):
    out = []
    for k in db.execute("SELECT * FROM kpis WHERE active=1 AND deleted_at IS NULL ORDER BY kind, code"):
        r = db.execute("SELECT period, value FROM kpi_readings WHERE kpi_id=? ORDER BY period DESC LIMIT 1", (k["id"],)).fetchone()
        out.append({"code": k["code"], "name": k["name"], "kind": k["kind"], "unit": k["unit"], "period": r["period"] if r else None, "value": r["value"] if r else None, "amber": k["amber"], "red": k["red"], "status": p2.status_of(k, r["value"]) if r else None})
    return out


def kitds(module, entity, perm=None):
    s = kit.SPECS[module]; e = s["entities"][entity]; cols = [("ref", "Ref", "text"), ("status", "Status", "text")] + [(f["key"], f["label"], "number" if f["type"] == "number" else "text") for f in e["fields"] if f["type"] not in ("textarea",)]
    return {"perm": perm or s["perm"], "cols": cols, "load": lambda db, c: [{k: ("yes" if i.get(k) is True else "no" if i.get(k) is False else i.get(k)) for k, _, _ in cols} for i in kit.load(db, module, entity)]}


def datasets():
    t = lambda *a: [(k, l, "text") for k, l in a]
    return {"risks": dict({"label": "Risk register (assessed risks)"}, **{"perm": "risk_register", "cols": [("ref", "Ref", "text"), ("source_ref", "Source ref", "text"), ("title", "Title", "text"), ("category", "Category", "text"), ("system", "System", "text"), ("owner", "Owner", "text"), ("res_l", "Residual likelihood", "number"), ("res_c", "Residual consequence", "number"), ("rrr", "Residual rank", "number"), ("emv_i", "Inherent exposure ($)", "number"), ("loa", "Assurance", "number")], "load": risks_load}),
            "actions": dict({"label": "Actions"}, **sql("actions_issues", "SELECT ref,title,owner_name,priority,due_date,status,source FROM actions WHERE deleted_at IS NULL ORDER BY id DESC", [("ref", "Ref", "text"), ("title", "Title", "text"), ("owner_name", "Owner", "text"), ("priority", "Priority", "text"), ("due_date", "Due", "text"), ("status", "Status", "text"), ("source", "Source", "text")])),
            "indicators": dict({"label": "KRIs and KPIs: latest reading"}, **{"perm": "kri_monitor", "cols": [("code", "Code", "text"), ("name", "Name", "text"), ("kind", "Kind", "text"), ("unit", "Unit", "text"), ("period", "Period", "text"), ("value", "Latest value", "number"), ("amber", "Amber", "number"), ("red", "Red", "number"), ("status", "Status", "text")], "load": kpis_load}),
            "incidents": dict({"label": "Incidents and losses"}, **sql("incidents_losses", "SELECT ref,title,kind,category,severity,occurred_on,gross_loss,recovered,status,owner FROM incidents WHERE deleted_at IS NULL ORDER BY id DESC", [("ref", "Ref", "text"), ("title", "Title", "text"), ("kind", "Kind", "text"), ("category", "Category", "text"), ("severity", "Severity", "text"), ("occurred_on", "Occurred", "text"), ("gross_loss", "Gross loss ($)", "number"), ("recovered", "Recovered ($)", "number"), ("status", "Status", "text"), ("owner", "Owner", "text")])),
            "audit_findings": dict({"label": "Audit findings"}, **sql("audit_workspace", "SELECT ref,title,priority,owner_name,due_date,status FROM audit_findings WHERE deleted_at IS NULL ORDER BY id DESC", [("ref", "Ref", "text"), ("title", "Title", "text"), ("priority", "Priority", "text"), ("owner_name", "Owner", "text"), ("due_date", "Due", "text"), ("status", "Status", "text")])),
            "fraud_cases": dict({"label": "Fraud alerts and cases"}, **sql("fraud_intelligence", "SELECT ref,detected_at,typology,channel,agent_cluster,region,amount,loss,recovered,status FROM fraud_alerts WHERE deleted_at IS NULL ORDER BY id DESC", [("ref", "Ref", "text"), ("detected_at", "Detected", "text"), ("typology", "Typology", "text"), ("channel", "Channel", "text"), ("agent_cluster", "Agent cluster", "text"), ("region", "Region", "text"), ("amount", "Amount ($)", "number"), ("loss", "Loss ($)", "number"), ("recovered", "Recovered ($)", "number"), ("status", "Status", "text")])),
            "obligations": dict({"label": "Obligations"}, **kitds("obligations_hub", "obligation")), "regulatory_changes": dict({"label": "Regulatory changes"}, **kitds("regulatory_change", "change")), "policies": dict({"label": "Policies"}, **kitds("policy_hub", "policy")), "vendors": dict({"label": "Vendors"}, **kitds("third_party_risk", "vendor")),
            "vulnerabilities": dict({"label": "Vulnerabilities"}, **kitds("cyber_it_risk", "vuln")), "bia": dict({"label": "Business impact analysis"}, **kitds("bcm_studio", "process")), "nonconformities": dict({"label": "Nonconformities"}, **kitds("standards_hub", "nonconformity", "standards_hub")), "ai_systems": dict({"label": "AI systems"}, **kitds("standards_hub", "ai_system", "aims_iso_42001"))}


def rows_of(db, c, name):
    d = datasets().get(name)
    if not d:
        raise HTTPError(404, "not_found", "Unknown dataset.")
    if "view" not in c.perms.get(d["perm"], set()):
        raise HTTPError(403, "forbidden", "You do not have rights to this dataset (%s)." % d["label"])
    if d["perm"] in kit.SPECS:
        kit.ensure_seed(db, d["perm"])
    return d, d["load"](db, c)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def match(v, op, x):
    s = "" if v is None else str(v)
    if op == "is empty":
        return s == ""
    if op == "is not empty":
        return s != ""
    if op in ("=", "!="):
        return (s.lower() == str(x).lower()) == (op == "=")
    if op == "contains":
        return str(x).lower() in s.lower()
    a, b = num(v), num(x)
    if a is None or b is None:
        a, b = s, str(x)
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]


def run(db, c, dataset, spec):
    d, rows = rows_of(db, c, dataset); keys = [k for k, _, _ in d["cols"]]; labs = {k: l for k, l, _ in d["cols"]}
    cols = [k for k in (spec.get("columns") or keys) if k in keys] or keys
    for f in spec.get("filters") or []:
        if f.get("col") not in keys or f.get("op") not in OPS:
            raise HTTPError(400, "validation", "A filter names an unknown column or operator.")
        rows = [r for r in rows if match(r.get(f["col"]), f["op"], f.get("value"))]
    s = spec.get("sort") or {}
    if s.get("col") in keys:
        rows = sorted(rows, key=lambda r: (r.get(s["col"]) is None, num(r.get(s["col"])) if num(r.get(s["col"])) is not None else 0, str(r.get(s["col"]) or "")), reverse=s.get("dir") == "desc")
    g = spec.get("group") or {}
    if g.get("by") in keys:
        out = {}
        for r in rows:
            out.setdefault(r.get(g["by"]) if r.get(g["by"]) not in (None, "") else "(blank)", []).append(r)
        aggs = [a for a in (g.get("aggs") or []) if a.get("fn") in FN and (a["fn"] == "count" or a.get("col") in keys)] or [{"fn": "count"}]; head = [labs[g["by"]]] + [("Count" if a["fn"] == "count" else "%s of %s" % (a["fn"].capitalize(), labs[a["col"]])) for a in aggs]; table = []
        for k, rs in sorted(out.items(), key=lambda z: str(z[0])):
            row = [k]
            for a in aggs:
                vs = [num(r.get(a["col"])) for r in rs if num(r.get(a.get("col"))) is not None] if a["fn"] != "count" else []
                row.append(len(rs) if a["fn"] == "count" else (round(sum(vs), 2) if a["fn"] == "sum" else round(sum(vs) / len(vs), 2) if a["fn"] == "avg" and vs else (min(vs) if a["fn"] == "min" and vs else max(vs) if a["fn"] == "max" and vs else None)))
            table.append(row)
        return {"columns": head, "rows": table, "total": len(table), "source_rows": len(rows), "grouped": True}
    return {"columns": [labs[k] for k in cols], "rows": [[r.get(k) for k in cols] for r in rows[:2000]], "total": len(rows), "source_rows": len(rows), "grouped": False}


def watermark(c):
    return "Downloaded by %s (%s) at %s. EcoCash Sentinel: handle according to your classification." % (c.user["full_name"], c.user["username"], now())


def render(db, c, name, res, fmt):
    wm = watermark(c)
    if fmt == "csv":
        out = io.StringIO(); out.write("# " + name + "\n# " + wm + "\n"); w = csv.writer(out); w.writerow(res["columns"]); w.writerows(res["rows"]); return out.getvalue().encode("utf-8-sig"), "text/csv", name.replace(" ", "_")[:60] + ".csv"
    rows = [[(name, 3)], [(wm, 4)], [], [(h, 1) for h in res["columns"]]] + [list(r) for r in res["rows"]] + [[], [(wm, 4)]]
    return xlsxbook.write([("Report", rows, [24] * len(res["columns"]))]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", name.replace(" ", "_")[:60] + ".xlsx"


def can_see(db, c, r):
    if r["system"] or r["owner_id"] == c.user["id"] or r["share"] == "everyone":
        return True
    return r["share"].startswith("role:") and r["share"][5:] in role_names(db, c.user["id"])


def card(db, c, r):
    sp = json.loads(r["spec"]); return {"id": r["id"], "name": r["name"], "dataset": r["dataset"], "spec": sp, "owner": r["owner_name"], "mine": r["owner_id"] == c.user["id"], "system": bool(r["system"]), "share": r["share"], "fmt": r["fmt"], "freq": r["freq"], "run_time": r["run_time"], "recipients": r["recipients"], "last_run": r["last_run"], "deleted_at": r["deleted_at"], "next_run": nxt(r)}


def nxt(r):
    if not r["freq"]:
        return None
    return {"daily": "every day", "weekly": "every Monday", "monthly": "on the 1st of each month"}.get(r["freq"], "") + " at " + (r["run_time"] or "07:30")


def seed(db):
    if db.execute("SELECT 1 FROM settings WHERE key='reports_seed'").fetchone():
        return
    std = [("Open actions by due date", "actions", {"columns": ["ref", "title", "owner_name", "priority", "due_date", "status"], "filters": [{"col": "status", "op": "!=", "value": "closed"}], "sort": {"col": "due_date", "dir": "asc"}}), ("Risks by category", "risks", {"group": {"by": "category", "aggs": [{"fn": "count"}, {"fn": "sum", "col": "emv_i"}]}}),
           ("Indicators outside appetite", "indicators", {"columns": ["code", "name", "kind", "period", "value", "amber", "red", "status"], "filters": [{"col": "status", "op": "is not empty"}, {"col": "status", "op": "!=", "value": "green"}, {"col": "status", "op": "!=", "value": "ok"}]}), ("Open audit findings", "audit_findings", {"filters": [{"col": "status", "op": "!=", "value": "closed"}]}), ("Incidents by category", "incidents", {"group": {"by": "category", "aggs": [{"fn": "count"}, {"fn": "sum", "col": "gross_loss"}]}}),
           ("Obligations needing attention", "obligations", {"columns": ["ref", "name", "regulator", "owner", "status", "next_due"], "filters": [{"col": "status", "op": "!=", "value": "compliant"}]}), ("Vendor register", "vendors", {"columns": ["ref", "name", "service", "tier", "owner", "assessment_score", "contract_end"]})]
    for n, ds, sp in std:
        db.execute("INSERT INTO report_defs(name,dataset,spec,owner_name,share,system,fmt,created_at) VALUES(?,?,?,?,?,1,'xlsx',?)", (n, ds, json.dumps(sp), "Sentinel", "everyone", now()))
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('reports_seed',?)", (now(),))


def purge(db):
    cut = (datetime.datetime.utcnow() - datetime.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"); db.execute("DELETE FROM report_defs WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cut,))


def clean_spec(b):
    sp = b.get("spec") or {}
    if not isinstance(sp, dict):
        raise HTTPError(400, "validation", "The report definition is not valid.")
    return {k: sp[k] for k in ("columns", "filters", "sort", "group") if sp.get(k)}


@router.route("GET", "/api/reports")
def lst(req):
    c = need(req, "data_reports", "view"); seed(req.db); purge(req.db); ds = datasets(); mine = c.perms.get("data_reports", set())
    avail = {k: {"label": d["label"], "cols": [{"key": a, "label": b, "type": t} for a, b, t in d["cols"]]} for k, d in ds.items() if "view" in c.perms.get(d["perm"], set())}
    rs = [r for r in req.db.execute("SELECT * FROM report_defs WHERE deleted_at IS NULL ORDER BY system DESC, id DESC") if can_see(req.db, c, r)]; mgr = "approve" in mine
    dl = [r for r in req.db.execute("SELECT * FROM report_defs WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC") if (r["owner_id"] == c.user["id"] or mgr)]
    return {"reports": [card(req.db, c, r) for r in rs], "datasets": avail, "deleted": [dict(card(req.db, c, r), deleted_by=r["deleted_by"]) for r in dl], "ops": OPS, "fns": FN, "roles": [r["name"] for r in req.db.execute("SELECT name FROM roles ORDER BY name")], "can": {k: k in mine for k in ("create", "edit", "delete", "export", "approve")},
            "powerbi": [{"dataset": k, "label": d["label"], "url": "/api/dataset/" + k} for k, d in ds.items()], "log": [dict(r) for r in req.db.execute("SELECT ts, username, action, detail FROM report_log ORDER BY id DESC LIMIT 25")]}


@router.route("POST", "/api/reports/preview")
def preview(req):
    c = need(req, "data_reports", "view"); b = req.json(); return run(req.db, c, b.get("dataset"), clean_spec(b))


@router.route("POST", "/api/reports")
def create(req):
    c = need(req, "data_reports", "create"); b = req.json(); name = str(b.get("name") or "").strip()[:120]; sp = clean_spec(b)
    if not name:
        raise HTTPError(400, "validation", "Name the report.")
    run(req.db, c, b.get("dataset"), sp); share = b.get("share") or "private"
    if share not in ("private", "everyone") and not share.startswith("role:"):
        raise HTTPError(400, "validation", "Share it privately, with everyone, or with a role.")
    rid = req.db.execute("INSERT INTO report_defs(name,dataset,spec,owner_id,owner_name,share,fmt,created_at) VALUES(?,?,?,?,?,?,?,?)", (name, b["dataset"], json.dumps(sp), c.user["id"], c.user["full_name"], share, "csv" if b.get("fmt") == "csv" else "xlsx", now())).lastrowid
    req.db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), rid, c.user["username"], "created", name)); audit(req.db, "report.create", c.user, "data_reports", "Report '%s' saved" % name, req.ip)
    return {"id": rid}


def mine_or_manager(db, c, rid, need_write=True):
    r = db.execute("SELECT * FROM report_defs WHERE id=?", (rid,)).fetchone()
    if not r or (r["deleted_at"] and need_write is True and False):
        raise HTTPError(404, "not_found", "Report not found.")
    if need_write and not ((r["owner_id"] == c.user["id"] and not r["system"]) or "approve" in c.perms.get("data_reports", set())):
        raise HTTPError(403, "forbidden", "Only the owner (or the Head of Risk) can change this report.")
    if not need_write and not can_see(db, c, r) and "approve" not in c.perms.get("data_reports", set()):
        raise HTTPError(403, "forbidden", "This report is not shared with you.")
    return r


@router.route("PUT", "/api/reports/<int:rid>")
def edit(req):
    c = need(req, "data_reports", "edit"); r = mine_or_manager(req.db, c, int(req.params["rid"])); b = req.json(); sp = clean_spec(b) if "spec" in b else json.loads(r["spec"]); run(req.db, c, r["dataset"], sp)
    req.db.execute("UPDATE report_defs SET name=?, spec=?, share=?, fmt=? WHERE id=?", (str(b.get("name") or r["name"]).strip()[:120], json.dumps(sp), b.get("share") or r["share"], "csv" if b.get("fmt") == "csv" else "xlsx" if b.get("fmt") else r["fmt"], r["id"])); req.db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), r["id"], c.user["username"], "edited", r["name"]))
    return {"ok": True}


@router.route("POST", "/api/reports/<int:rid>/run")
def run_one(req):
    c = need(req, "data_reports", "view"); r = mine_or_manager(req.db, c, int(req.params["rid"]), False); return run(req.db, c, r["dataset"], json.loads(r["spec"]))


@router.route("GET", "/api/reports/<int:rid>/download")
def download(req):
    c = need(req, "data_reports", "export"); r = mine_or_manager(req.db, c, int(req.params["rid"]), False); fmt = "csv" if req.query.get("fmt") == "csv" else "xlsx"; res = run(req.db, c, r["dataset"], json.loads(r["spec"])); data, mime, fn = render(req.db, c, r["name"], res, fmt)
    req.db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), r["id"], c.user["username"], "downloaded " + fmt, "%d rows" % len(res["rows"]))); audit(req.db, "report.download", c.user, "data_reports", "Report '%s' downloaded as %s (%d rows), watermarked" % (r["name"], fmt, len(res["rows"])), req.ip)
    return Response(data, 200, mime, [("Content-Disposition", 'attachment; filename="%s"' % fn)])


@router.route("POST", "/api/reports/<int:rid>/schedule")
def schedule(req):
    c = need(req, "data_reports", "edit"); r = mine_or_manager(req.db, c, int(req.params["rid"])); b = req.json(); freq = b.get("freq") or None
    if freq not in (None, "daily", "weekly", "monthly"):
        raise HTTPError(400, "validation", "Choose daily, weekly, monthly or none.")
    t = str(b.get("run_time") or "07:30")[:5]; rec = ", ".join([x.strip() for x in str(b.get("recipients") or "").replace(";", ",").split(",") if "@" in x][:20])
    if freq and not rec:
        raise HTTPError(400, "validation", "Give at least one e-mail address to send it to.")
    try:
        datetime.time.fromisoformat(t)
    except ValueError:
        raise HTTPError(400, "validation", "The time must be like 07:30.")
    req.db.execute("UPDATE report_defs SET freq=?, run_time=?, recipients=?, fmt=? WHERE id=?", (freq, t, rec, "csv" if b.get("fmt") == "csv" else "xlsx", r["id"])); req.db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), r["id"], c.user["username"], "scheduled", "%s at %s to %s" % (freq, t, rec)))
    return {"ok": True}


@router.route("DELETE", "/api/reports/<int:rid>")
def delete(req):
    c = need(req, "data_reports", "delete"); r = mine_or_manager(req.db, c, int(req.params["rid"]))
    if r["system"]:
        raise HTTPError(403, "forbidden", "Standard reports cannot be deleted.")
    req.db.execute("UPDATE report_defs SET deleted_at=?, deleted_by=? WHERE id=?", (now(), c.user["username"], r["id"])); req.db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), r["id"], c.user["username"], "deleted", "kept 90 days")); audit(req.db, "report.delete", c.user, "data_reports", "Report '%s' moved to Deleted items (90 days)" % r["name"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/reports/<int:rid>/restore")
def restore(req):
    c = need(req, "data_reports", "edit"); r = mine_or_manager(req.db, c, int(req.params["rid"]))
    if not r["deleted_at"]:
        raise HTTPError(409, "state", "This report is not deleted.")
    req.db.execute("UPDATE report_defs SET deleted_at=NULL, deleted_by=NULL WHERE id=?", (r["id"],)); req.db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), r["id"], c.user["username"], "restored", "with its schedule and history")); audit(req.db, "report.restore", c.user, "data_reports", "Report '%s' restored" % r["name"], req.ip)
    return {"ok": True}


class _Feed:
    """The context a Power BI key reads datasets with: every dataset, read-only, all data."""
    user = {"id": 0, "username": "powerbi", "full_name": "Power BI feed", "job_title": "", "department": "", "data_scope": "all"}
    perms = {"risk_register": {"view"}, "actions_issues": {"view"}, "kri_monitor": {"view"}, "incidents_losses": {"view"}, "audit_workspace": {"view"}, "fraud_intelligence": {"view"}, "obligations_hub": {"view"}, "regulatory_change": {"view"}, "policy_hub": {"view"}, "third_party_risk": {"view"}, "cyber_it_risk": {"view"}, "bcm_studio": {"view"}, "standards_hub": {"view"}, "aims_iso_42001": {"view"}}


@router.route("GET", "/api/dataset/<name>")
def dataset(req):
    """A governed dataset as CSV: for a signed-in user with rights to it, or for Power BI with the Power BI connector's key (header X-Api-Key). Every read is logged."""
    name = req.params["name"]; key = req.headers.get("X-Api-Key")
    if key:
        r = req.db.execute("SELECT * FROM integ_connectors WHERE key='power_bi'").fetchone()
        if not r or not r["enabled"] or not r["key_hash"] or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), r["key_hash"]):
            raise HTTPError(401, "unauthorized", "The key is wrong or the Power BI connector is switched off.")
        c = _Feed(); who = "Power BI key"
    else:
        c = need(req, "data_reports", "export"); who = c.user["username"]
    d, rows = rows_of(req.db, c, name); out = io.StringIO(); w = csv.writer(out); w.writerow([l for _, l, _ in d["cols"]]); w.writerows([[r.get(k) for k, _, _ in d["cols"]] for r in rows])
    req.db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), None, who, "dataset read", "%s, %d rows" % (name, len(rows))))
    if key:
        req.db.execute("INSERT INTO integ_events(ts,connector,status,rows_in,rows_bad,detail) VALUES(?,?,?,?,?,?)", (now(), "power_bi", "ok", len(rows), 0, "dataset " + name)); req.db.execute("UPDATE integ_connectors SET last_sync=? WHERE key='power_bi'", (now(),))
    return Response(out.getvalue().encode("utf-8-sig"), 200, "text/csv; charset=utf-8", [("Content-Disposition", 'inline; filename="%s.csv"' % name)])


def run_due(db):
    """Scheduled reports: sent once a day at their time (weekly on Monday, monthly on the 1st), as an attachment, using the mail link from Administration > E-mail."""
    from . import mailer
    cfg = mailer.settings(db)
    if not mailer.ready(cfg):
        return 0
    today = dbm.today(); local = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=dbm.config.TZ_HOURS); n = 0
    for r in db.execute("SELECT * FROM report_defs WHERE freq IS NOT NULL AND deleted_at IS NULL"):
        hh, mm = [int(x) for x in (r["run_time"] or "07:30").split(":")[:2]]
        if (local.hour, local.minute) < (hh, mm) or r["last_run"] == today.isoformat() or (r["freq"] == "weekly" and today.weekday() != 0) or (r["freq"] == "monthly" and today.day != 1):
            continue
        owner = db.execute("SELECT * FROM users WHERE id=?", (r["owner_id"],)).fetchone()
        try:
            class Ctx:  # run with the owner's rights, so a schedule cannot show more than its owner may see
                user = dict(owner) if owner else _Feed.user; perms = {}
            from .core import permissions_of
            Ctx.perms = permissions_of(db, Ctx.user["id"]) if owner else _Feed.perms
            res = run(db, Ctx, r["dataset"], json.loads(r["spec"])); data, mime, fn = render(db, Ctx, r["name"], res, r["fmt"]); sent = 0
            for to in [x.strip() for x in (r["recipients"] or "").split(",") if x.strip()]:
                mailer.deliver(cfg, mailer.password(db), to, "Sentinel report: %s" % r["name"], "Attached: %s (%d rows). Generated %s." % (r["name"], len(res["rows"]), now()), [(fn, data, mime)]); sent += 1
            db.execute("UPDATE report_defs SET last_run=? WHERE id=?", (today.isoformat(), r["id"])); db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), r["id"], "scheduler", "sent", "%d recipient(s), %d rows" % (sent, len(res["rows"])))); n += 1
        except Exception as e:
            db.execute("INSERT INTO report_log(ts,report_id,username,action,detail) VALUES(?,?,?,?,?)", (now(), r["id"], "scheduler", "failed", str(e)[:200]))
    return n
