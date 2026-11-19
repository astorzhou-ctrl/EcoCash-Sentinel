"""Verified sources: how Sentinel visits external websites safely. Layers: a master switch (off by default); two-person verification of every site;
https only, approved host names, public addresses only (checked at connection time, defeating DNS tricks); no redirects to other hosts; size, time and content-type
limits; no cookies, scripts or credentials; every value found is only a PROPOSAL that a person approves; plausibility checks quarantine odd values; a changed
certificate or any security failure suspends the site automatically. Nothing fetched is ever executed or shown unescaped."""
import datetime
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
import urllib.parse
from html.parser import HTMLParser

from . import core, db as dbm, xlsx
from .api import router, need, need_str
from .core import audit, now
from .p2 import fnum, heads_of_risk_emails, parse_date, put_reading, check_alerts, status_of
from .web import HTTPError

OFFICIAL = ("rbz.co.zw", "zimstat.co.zw", "zera.co.zw", "zse.co.zw", "vfex.exchange", "potraz.gov.zw")
SECONDARY = ("techzim.co.zw", "stablecoindashboard.net")
COMMERCIAL = ("bloomberg.com", "reuters.com", "refinitiv.com")
ALLOWED_CT = ("text/html", "application/xhtml+xml", "text/plain", "text/csv", "application/json", "application/pdf")
MAX_BYTES, TIMEOUT, MAX_HOPS, DAILY_CAP, MIN_GAP_MIN = 3_000_000, 15, 3, 60, 5
TIERS = ("official", "secondary", "unverified")
RULES = ("watch", "csv", "json", "regex")
SEED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kpi_sources_seed.json")


class FetchError(Exception):
    def __init__(self, msg, security=False):
        super().__init__(msg)
        self.security = security


def loopback_ok():
    return os.environ.get("SENTINEL_ALLOW_LOOPBACK") == "1"  # development and tests only; never set in production


def host_of(url):
    return (urllib.parse.urlparse(url).hostname or "").lower()


def tier_of(host):
    for names, t in ((OFFICIAL, "official"), (SECONDARY, "secondary")):
        if any(host == d or host.endswith("." + d) for d in names):
            return t
    return "unverified"


def is_commercial(host):
    return any(host == d or host.endswith("." + d) for d in COMMERCIAL)


def public_ip(ip):
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified or (a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10")))


def resolve(host):
    """Resolve and validate: every address must be public (loopback is allowed only in test mode). Returns the address to connect to."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        raise FetchError("The host name could not be resolved.")
    ips = sorted({i[4][0] for i in infos}, key=lambda x: (":" in x, x))
    if not ips:
        raise FetchError("The host name could not be resolved.")
    for ip in ips:
        if not public_ip(ip) and not (loopback_ok() and ipaddress.ip_address(ip).is_loopback):
            raise FetchError("The host name points to a non-public address (%s), which is refused." % ip, True)
    return ips[0]


def check_url(url, allow):
    if len(url) > 2000 or re.search(r"[\x00-\x20\x7f\\]", url):
        raise FetchError("The link contains characters that are not allowed.", True)
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    if p.username or p.password:
        raise FetchError("Links with a user name or password are refused.", True)
    local = loopback_ok() and host in ("localhost", "127.0.0.1", "::1")
    if p.scheme != "https" and not (local and p.scheme == "http"):
        raise FetchError("Only https links are accepted.", True)
    if p.port not in (None, 443) and not local:
        raise FetchError("Only the standard https port is accepted.", True)
    if not re.match(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", host) or (not local and ("." not in host or re.match(r"^[0-9.]+$", host))):
        raise FetchError("A host name is required (addresses are refused).", True)
    if host not in allow:
        raise FetchError("The host %s is not on the approved list." % host, True)
    return p, host, local


class _Text(HTMLParser):
    """Visible text and document links only. Nothing is executed or rendered."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.skip, self.size = [], [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.skip += 1
        if tag == "a" and len(self.links) < 300:
            h = dict(attrs).get("href") or ""
            if re.search(r"\.(pdf|xlsx?|csv|docx?)(\?|$)", h, re.I):
                self.links.append(h.strip()[:300])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip and self.size < 600_000:
            self.parts.append(d); self.size += len(d)


def page_text(body, ctype):
    if ctype in ("text/html", "application/xhtml+xml"):
        t = _Text()
        try:
            t.feed(body.decode("utf-8", errors="replace")[:1_500_000])
        except Exception:
            pass
        return re.sub(r"\s+", " ", " ".join(t.parts)).strip(), sorted(set(t.links))
    if ctype == "application/pdf":
        return "", []
    return re.sub(r"\s+", " ", body.decode("utf-8", errors="replace")[:600_000]).strip(), []


def safe_get(url, allow):
    """The only door to the outside world. Returns dict(status, ctype, body, fp, ip, ms, url)."""
    t0, cur = time.time(), url
    for hop in range(MAX_HOPS + 1):
        p, host, local = check_url(cur, allow)
        ip = resolve(host)
        port = p.port or (80 if p.scheme == "http" else 443)
        left = TIMEOUT - (time.time() - t0)
        if left <= 0:
            raise FetchError("The source took too long.")
        try:
            if p.scheme == "https":
                ctx = ssl.create_default_context()  # verifies the certificate chain and that the name matches
                raw = socket.create_connection((ip, port), timeout=left)
                sock = ctx.wrap_socket(raw, server_hostname=host)
                fp = hashlib.sha256(sock.getpeercert(True)).hexdigest()
                conn = http.client.HTTPSConnection(host, port, timeout=left, context=ctx); conn.sock = sock
            else:
                fp = None
                conn = http.client.HTTPConnection(host, port, timeout=left); conn.sock = socket.create_connection((ip, port), timeout=left)
            path = (p.path or "/") + ("?" + p.query if p.query else "")
            conn.request("GET", path, headers={"Host": host + ("" if port in (80, 443) else ":%d" % port), "User-Agent": "Sentinel-ERM/1.0 (+risk monitoring)", "Accept": ", ".join(ALLOWED_CT), "Accept-Encoding": "identity", "Connection": "close"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                loc = r.getheader("Location") or ""
                conn.close()
                if hop == MAX_HOPS or not loc:
                    raise FetchError("Too many redirects.", True)
                cur = urllib.parse.urljoin(cur, loc)
                continue  # the next loop re-validates scheme, host and address
            if r.status != 200:
                conn.close()
                raise FetchError("The source answered %d." % r.status)
            ctype = (r.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in ALLOWED_CT:
                conn.close()
                raise FetchError("The source returned a type of content that is not accepted (%s)." % (ctype or "unknown"), True)
            cl = r.getheader("Content-Length")
            if cl and cl.isdigit() and int(cl) > MAX_BYTES:
                conn.close()
                raise FetchError("The page is larger than %d MB." % (MAX_BYTES // 1_000_000), True)
            body = b""
            while len(body) <= MAX_BYTES:
                chunk = r.read(65536)
                if not chunk:
                    break
                body += chunk
                if time.time() - t0 > TIMEOUT:
                    raise FetchError("The source took too long.")
            conn.close()
            if len(body) > MAX_BYTES:
                raise FetchError("The page is larger than %d MB." % (MAX_BYTES // 1_000_000), True)
            return {"status": 200, "ctype": ctype, "body": body, "fp": fp, "ip": ip, "ms": int((time.time() - t0) * 1000), "url": cur}
        except ssl.SSLError as e:
            raise FetchError("The security certificate could not be verified (%s)." % str(e)[:60], True)
        except (socket.timeout, TimeoutError):
            raise FetchError("The source took too long.")
        except OSError as e:
            raise FetchError("The source could not be reached (%s)." % str(e)[:60])
    raise FetchError("Too many redirects.", True)


# ------------------------------------------------------------------ rules: how a value is read from a page
def safe_pattern(p):
    if not p or len(p) > 200 or re.search(r"\\[1-9]|\(\?P=|\(\?[<=!]|\)\s*[+*]|\)\s*\{|\.\*.*\.\*.*\.\*", p):
        raise HTTPError(400, "validation", "That pattern is not allowed (too long, or uses features that can hang the system). Keep it simple, for example: Policy rate[^0-9]{0,40}([0-9.]+)")
    try:
        c = re.compile(p, re.I)
    except re.error:
        raise HTTPError(400, "validation", "The pattern is not valid.")
    if c.groups < 1:
        raise HTTPError(400, "validation", "The pattern needs one group in brackets around the value.")
    return c


def clean_rule(rt, rule):
    if rt not in RULES:
        raise HTTPError(400, "validation", "Choose how the value is read: watch only, csv, json or text pattern.")
    r = {}
    if rt == "regex":
        r["pattern"] = (rule.get("pattern") or "").strip(); safe_pattern(r["pattern"])
        if rule.get("date_pattern"):
            r["date_pattern"] = rule["date_pattern"].strip(); safe_pattern(r["date_pattern"])
    elif rt in ("csv", "json"):
        r["keys"] = need_str(rule, "keys", "Columns", 80, False) or "date,value"
    for k in ("min", "max", "max_jump_pct", "scale"):
        v = fnum(rule.get(k), k, False)
        if v is not None:
            r[k] = v
    return r


def extract(rt, rule, body, ctype):
    """Returns [(period, value, snippet)]. Only numbers leave this function."""
    text, _ = page_text(body, ctype)
    out = []
    scale = rule.get("scale") or 1.0
    if rt == "regex":
        m = safe_pattern(rule["pattern"]).search(text[:600_000])
        if m:
            try:
                v = float(m.group(1).replace(",", "").replace("%", "")) * scale
            except ValueError:
                return []
            period = str(dbm.today())
            if rule.get("date_pattern"):
                d = safe_pattern(rule["date_pattern"]).search(text[:600_000])
                period = (parse_date(d.group(1)) if d else None) or period
            out.append((period, v, text[max(0, m.start() - 30): m.end() + 30][:140]))
    elif rt in ("csv", "json"):
        import csv, io
        dk, vk = [x.strip().lower() for x in (rule.get("keys") or "date,value").split(",")[:2]] if "," in (rule.get("keys") or "date,value") else ("date", "value")
        items = []
        try:
            if rt == "json":
                j = json.loads(body.decode("utf-8-sig"))
                j = j.get("data", j.get("readings", [j])) if isinstance(j, dict) else j
                items = [(i.get(dk), i.get(vk)) for i in j if isinstance(i, dict)]
            else:
                for r in csv.DictReader(io.StringIO(body.decode("utf-8-sig"))):
                    low = {str(a or "").strip().lower(): b for a, b in r.items()}
                    items.append((low.get(dk), low.get(vk)))
        except Exception:
            return []
        for dt, v in items[-60:]:
            p = parse_date(dt)
            try:
                out.append((p, float(str(v).replace(",", "").replace("%", "")) * scale, "%s = %s" % (dt, v)))
            except (TypeError, ValueError):
                continue
        out = [o for o in out if o[0]]
    return out


def plausibility(db, k, rule, period, value):
    """Returns a list of reasons the value looks wrong (empty means it looks sensible)."""
    bad = []
    if value != value or abs(value) == float("inf"):
        bad.append("not a number")
    if "min" in rule and value < rule["min"]:
        bad.append("below the allowed minimum %s" % rule["min"])
    if "max" in rule and value > rule["max"]:
        bad.append("above the allowed maximum %s" % rule["max"])
    if period and datetime.date.fromisoformat(period) > dbm.today():
        bad.append("dated in the future")
    prev = db.execute("SELECT value FROM kpi_readings WHERE kpi_id=? AND period<? ORDER BY period DESC LIMIT 1", (k["id"], period)).fetchone()
    jump = rule.get("max_jump_pct", 30.0)
    if prev and prev["value"] and abs(value - prev["value"]) / abs(prev["value"]) * 100 > jump:
        bad.append("moved more than %g%% from the previous value %s" % (jump, prev["value"]))
    return bad


# ------------------------------------------------------------------ settings and the visit itself
def outbound(db):
    r = db.execute("SELECT value FROM settings WHERE key='outbound'").fetchone()
    return json.loads(r["value"]) if r else {"enabled": False}


def visits_today(db):
    return db.execute("SELECT COUNT(*) c FROM source_log WHERE ts>=?", (str(dbm.today()),)).fetchone()["c"]


def log(db, sid, ok, outcome, msg, status=None, nbytes=None, ms=None):
    db.execute("INSERT INTO source_log(ts,source_id,ok,status_code,bytes,ms,outcome,message) VALUES(?,?,?,?,?,?,?,?)", (now(), sid, int(ok), status, nbytes, ms, outcome, msg[:300]))


def suspend(db, s, why, security=False, who="system"):
    db.execute("UPDATE kpi_sources SET status='suspended', last_status=? WHERE id=?", (why[:200], s["id"]))
    audit(db, "source.suspended", None, "weekly_kpi", "%s suspended%s: %s" % (s["name"], " (security)" if security else "", why[:160]), "", who)
    for e in heads_of_risk_emails(db):
        core.outbox(db, e, "Sentinel: data source suspended", "%s (%s) was suspended automatically: %s. It will not be visited again until a person re-verifies it in Weekly KPI > Sources." % (s["name"], s["url"], why), "source")


def visit(db, s, who="system", force=False):
    """One controlled visit. Returns (ok, message, proposals_created)."""
    if not outbound(db).get("enabled"):
        return False, "Outbound visits are switched off (Weekly KPI > Sources and automation).", 0
    if s["status"] != "active" or s["manual_only"] or s["deleted_at"]:
        return False, "This site is not active (%s)." % ("manual only" if s["manual_only"] else s["status"]), 0
    if visits_today(db) >= DAILY_CAP:
        return False, "The daily limit of %d visits has been reached." % DAILY_CAP, 0
    if s["last_checked"] and s["last_checked"] > dbm.minus(minutes=MIN_GAP_MIN):
        return False, "Visited a moment ago; please wait a few minutes.", 0
    db.execute("UPDATE kpi_sources SET last_checked=? WHERE id=?", (now(), s["id"]))
    try:
        r = safe_get(s["url"], {s["host"]})
    except FetchError as e:
        log(db, s["id"], False, "security" if e.security else "failed", str(e))
        fails = s["fail_count"] + 1
        db.execute("UPDATE kpi_sources SET fail_count=?, last_status=? WHERE id=?", (fails, str(e)[:200], s["id"]))
        if e.security or fails >= 3:
            suspend(db, s, str(e), e.security, who)
        return False, str(e), 0
    text, links = page_text(r["body"], r["ctype"])
    chash = hashlib.sha256(("L:" + "|".join(links) if links else "T:" + text if text else "B:").encode() + (r["body"] if not (links or text) else b"")).hexdigest()
    changed = bool(s["content_hash"]) and s["content_hash"] != chash
    cert_new = bool(s["cert_fp"]) and r["fp"] and s["cert_fp"] != r["fp"]
    db.execute("UPDATE kpi_sources SET fail_count=0, last_status='ok', last_bytes=?, content_hash=?, cert_fp=COALESCE(cert_fp, ?), cert_changed=CASE WHEN ? THEN 1 ELSE cert_changed END, changed_at=CASE WHEN ? THEN ? ELSE changed_at END WHERE id=?",
               (len(r["body"]), chash, r["fp"], int(bool(cert_new)), int(changed), now(), s["id"]))
    log(db, s["id"], True, "changed" if changed else "ok", "%s, %d bytes%s%s" % (r["ctype"], len(r["body"]), ", content changed" if changed else "", ", CERTIFICATE CHANGED" if cert_new else ""), 200, len(r["body"]), r["ms"])
    if cert_new:
        audit(db, "source.certificate_changed", None, "weekly_kpi", "%s presented a different security certificate: values are held for review" % s["name"], "", who)
    made = 0
    s2 = db.execute("SELECT * FROM kpi_sources WHERE id=?", (s["id"],)).fetchone()
    for lk in db.execute("SELECT l.*, k.code FROM kpi_source_links l JOIN kpis k ON k.id=l.kpi_id WHERE l.source_id=? AND l.rule_type!='watch' AND k.deleted_at IS NULL", (s["id"],)).fetchall():
        k = db.execute("SELECT * FROM kpis WHERE id=?", (lk["kpi_id"],)).fetchone(); rule = json.loads(lk["rule"] or "{}")
        for period, value, snip in extract(lk["rule_type"], rule, r["body"], r["ctype"]):
            if db.execute("SELECT 1 FROM kpi_readings WHERE kpi_id=? AND period=? AND value=?", (k["id"], period, value)).fetchone():
                continue
            bad = plausibility(db, k, rule, period, value)
            if s2["cert_changed"]:
                bad.append("the site's security certificate changed since it was verified")
            if s2["tier"] != "official" and not bad:
                pass
            try:
                pid = db.execute("INSERT INTO kpi_proposals(kpi_id,source_id,period,value,snippet,checks,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (k["id"], s["id"], period, value, snip, json.dumps(bad), "quarantined" if bad else "pending", now())).lastrowid
            except Exception:
                continue
            made += 1
            if s2["auto_accept"] and s2["tier"] == "official" and not bad:
                accept(db, pid, "system", "Accepted automatically: official source, all checks passed")
    return True, "visited; %d value(s) proposed%s" % (made, "; the page has changed" if changed else ""), made


def accept(db, pid, who, note):
    p = db.execute("SELECT * FROM kpi_proposals WHERE id=?", (pid,)).fetchone()
    k = db.execute("SELECT * FROM kpis WHERE id=?", (p["kpi_id"],)).fetchone(); s = db.execute("SELECT name FROM kpi_sources WHERE id=?", (p["source_id"],)).fetchone()
    put_reading(db, k, p["period"], p["value"], "source", "Verified source: %s" % s["name"], who)
    db.execute("UPDATE kpi_proposals SET status='accepted', decided_by=?, decided_at=?, note=? WHERE id=?", (who, now(), note, pid))
    check_alerts(db, k, who)


def visit_due(db):
    n = 0
    if not outbound(db).get("enabled"):
        return 0
    for s in db.execute("SELECT * FROM kpi_sources WHERE status='active' AND manual_only=0 AND deleted_at IS NULL").fetchall():
        gap = 20 if s["freq"] and "daily" in s["freq"].lower() else 6.5 * 24
        if not s["last_checked"] or s["last_checked"] < dbm.minus(hours=int(gap)):
            if visit(db, s)[0]:
                n += 1
    return n


# ------------------------------------------------------------------ endpoints
def sdict(db, s):
    d = {k: s[k] for k in ("id", "name", "url", "host", "provider", "tier", "freq", "note", "status", "manual_only", "auto_accept", "proposed_by", "proposed_at", "verified_by", "verified_at", "verify_note", "cert_changed", "last_checked", "last_status", "last_bytes", "fail_count", "changed_at", "reviewed_at")}
    d["links"] = [dict(code=r["code"], name=r["name"], kpi_id=r["kpi_id"], link_id=r["id"], rule_type=r["rule_type"], rule=json.loads(r["rule"] or "{}")) for r in db.execute("SELECT l.id, l.kpi_id, l.rule_type, l.rule, k.code, k.name FROM kpi_source_links l JOIN kpis k ON k.id=l.kpi_id WHERE l.source_id=?", (s["id"],))]
    d["change_pending"] = bool(s["changed_at"]) and (not s["reviewed_at"] or s["reviewed_at"] < s["changed_at"])
    d["pending"] = db.execute("SELECT COUNT(*) c FROM kpi_proposals WHERE source_id=? AND status IN ('pending','quarantined')", (s["id"],)).fetchone()["c"]
    return d


def clean_source(d):
    name, url = need_str(d, "name", "Name", 160), (d.get("url") or "").strip()
    if len(url) > 2000 or not re.match(r"^https://[^\s/@]+(/[^\s]*)?$", url) and not (loopback_ok() and re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?(/\S*)?$", url)):
        raise HTTPError(400, "validation", "The link must start with https:// and must not contain a user name, password or spaces.")
    host = host_of(url)
    if not host or (re.match(r"^[0-9.]+$", host) and not (loopback_ok() and host == "127.0.0.1")):
        raise HTTPError(400, "validation", "Use a host name, not an address.")
    tier = tier_of(host)
    return {"name": name, "url": url, "host": host, "provider": need_str(d, "provider", "Provider", 80, False) or None, "freq": need_str(d, "freq", "Frequency", 30, False) or None, "note": need_str(d, "note", "Note", 400, False) or None, "tier": tier,
            "manual_only": 1 if (d.get("manual_only") or is_commercial(host)) else 0}


@router.route("GET", "/api/sources")
def src_list(req):
    c = need(req, "weekly_kpi", "view")
    rows = [sdict(req.db, s) for s in req.db.execute("SELECT * FROM kpi_sources WHERE deleted_at IS NULL ORDER BY CASE status WHEN 'proposed' THEN 0 WHEN 'review' THEN 1 WHEN 'suspended' THEN 2 ELSE 3 END, name")]
    o = outbound(req.db)
    return {"sources": rows, "outbound": o, "visits_today": visits_today(req.db), "daily_cap": DAILY_CAP, "pending": req.db.execute("SELECT COUNT(*) c FROM kpi_proposals WHERE status IN ('pending','quarantined')").fetchone()["c"],
            "kpis": [dict(id=k["id"], code=k["code"], name=k["name"]) for k in req.db.execute("SELECT id, code, name FROM kpis WHERE kind='kpi' AND deleted_at IS NULL ORDER BY grp, name")], "can": {a: a in c.perms.get("weekly_kpi", set()) for a in core.ACTIONS}}


@router.route("PUT", "/api/sources/outbound")
def src_outbound(req):
    c = need(req, "weekly_kpi", "approve")
    en = bool(req.json().get("enabled"))
    req.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('outbound',?)", (json.dumps({"enabled": en, "by": c.user["username"], "at": now()}),))
    audit(req.db, "source.outbound", c.user, "weekly_kpi", "Outbound visits to verified sources switched %s" % ("ON" if en else "OFF"), req.ip)
    return {"enabled": en}


@router.route("POST", "/api/sources")
def src_propose(req):
    c = need(req, "weekly_kpi", "create")
    f = clean_source(req.json())
    if req.db.execute("SELECT 1 FROM kpi_sources WHERE url=? AND deleted_at IS NULL", (f["url"],)).fetchone():
        raise HTTPError(409, "exists", "That link is already in the list.")
    cols = list(f) + ["proposed_by", "proposed_at", "status"]
    sid = req.db.execute("INSERT INTO kpi_sources(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), list(f.values()) + [c.user["username"], now(), "proposed"]).lastrowid
    audit(req.db, "source.proposed", c.user, "weekly_kpi", "Source proposed: %s (%s, tier %s)" % (f["name"], f["host"], f["tier"]), req.ip)
    return {"id": sid, "tier": f["tier"]}


@router.route("POST", "/api/sources/<int:sid>/verify")
def src_verify(req):
    c = need(req, "weekly_kpi", "approve")
    s = req.db.execute("SELECT * FROM kpi_sources WHERE id=? AND deleted_at IS NULL", (int(req.params["sid"]),)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Source not found")
    d = req.json()
    note = need_str(d, "note", "Your verification note", 400)
    if len(note) < 10:
        raise HTTPError(400, "validation", "Say how you checked the site (at least 10 characters), for example: opened the link, it is the official RBZ domain, the page shows the quarterly report.")
    if s["status"] == "proposed" and s["proposed_by"] == c.user["username"]:
        raise HTTPError(409, "same_person", "A different person must verify a site you proposed (two-person rule).")
    if d.get("decision") == "reject":
        req.db.execute("UPDATE kpi_sources SET status='rejected', verified_by=?, verified_at=?, verify_note=? WHERE id=?", (c.user["username"], now(), note, s["id"]))
        audit(req.db, "source.rejected", c.user, "weekly_kpi", "%s rejected: %s" % (s["name"], note[:100]), req.ip)
        return {"status": "rejected"}
    if s["manual_only"]:
        raise HTTPError(409, "manual_only", "This is a commercial or manual-only site: Sentinel will not visit it automatically. Enter its values by hand.")
    tier = d.get("tier") if d.get("tier") in TIERS else s["tier"]
    if tier == "official" and tier_of(s["host"]) != "official":
        raise HTTPError(409, "validation", "Only the known official domains can be marked official.")
    req.db.execute("UPDATE kpi_sources SET status='active', tier=?, verified_by=?, verified_at=?, verify_note=?, cert_changed=0, fail_count=0, cert_fp=CASE WHEN status IN ('review','suspended') THEN NULL ELSE cert_fp END WHERE id=?", (tier, c.user["username"], now(), note, s["id"]))
    audit(req.db, "source.verified", c.user, "weekly_kpi", "%s verified as %s by %s: %s" % (s["name"], tier, c.user["username"], note[:100]), req.ip)
    return {"status": "active", "tier": tier}


@router.route("POST", "/api/sources/<int:sid>/state")
def src_state(req):
    c = need(req, "weekly_kpi", "approve")
    s = req.db.execute("SELECT * FROM kpi_sources WHERE id=? AND deleted_at IS NULL", (int(req.params["sid"]),)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Source not found")
    d = req.json()
    if d.get("auto_accept") is not None:
        if d["auto_accept"] and s["tier"] != "official":
            raise HTTPError(409, "validation", "Automatic acceptance is only allowed for official sources.")
        req.db.execute("UPDATE kpi_sources SET auto_accept=? WHERE id=?", (1 if d["auto_accept"] else 0, s["id"]))
        audit(req.db, "source.auto_accept", c.user, "weekly_kpi", "%s automatic acceptance %s" % (s["name"], "ON" if d["auto_accept"] else "OFF"), req.ip)
    if d.get("state") == "suspend":
        suspend(req.db, s, "suspended by %s" % c.user["username"], False, c.user["username"])
    elif d.get("state") == "resume":
        raise HTTPError(409, "reverify", "A suspended site must be verified again by a different person before it is visited (use Verify).")
    return {"ok": True}


@router.route("DELETE", "/api/sources/<int:sid>")
def src_delete(req):
    c = need(req, "weekly_kpi", "delete")
    s = req.db.execute("SELECT name FROM kpi_sources WHERE id=? AND deleted_at IS NULL", (int(req.params["sid"]),)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Source not found")
    req.db.execute("UPDATE kpi_sources SET deleted_at=?, status='rejected' WHERE id=?", (now(), int(req.params["sid"])))
    audit(req.db, "source.removed", c.user, "weekly_kpi", "%s removed" % s["name"], req.ip)
    return {"ok": True}


@router.route("POST", "/api/sources/<int:sid>/links")
def src_link(req):
    c = need(req, "weekly_kpi", "create")
    s = req.db.execute("SELECT * FROM kpi_sources WHERE id=? AND deleted_at IS NULL", (int(req.params["sid"]),)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Source not found")
    d = req.json()
    k = req.db.execute("SELECT * FROM kpis WHERE id=? AND deleted_at IS NULL", (d.get("kpi_id") or 0,)).fetchone()
    if not k:
        raise HTTPError(404, "not_found", "Indicator not found")
    rt = (d.get("rule_type") or "watch").strip()
    rule = clean_rule(rt, d.get("rule") or {})
    req.db.execute("INSERT INTO kpi_source_links(source_id,kpi_id,rule_type,rule) VALUES(?,?,?,?) ON CONFLICT(source_id,kpi_id) DO UPDATE SET rule_type=excluded.rule_type, rule=excluded.rule", (s["id"], k["id"], rt, json.dumps(rule)))
    audit(req.db, "source.linked", c.user, "weekly_kpi", "%s linked to %s (%s)" % (s["name"], k["code"], rt), req.ip)
    return {"ok": True}


@router.route("DELETE", "/api/sources/<int:sid>/links/<int:lid>")
def src_unlink(req):
    c = need(req, "weekly_kpi", "edit")
    req.db.execute("DELETE FROM kpi_source_links WHERE id=? AND source_id=?", (int(req.params["lid"]), int(req.params["sid"])))
    return {"ok": True}


@router.route("POST", "/api/sources/<int:sid>/check")
def src_check(req):
    c = need(req, "weekly_kpi", "create")
    s = req.db.execute("SELECT * FROM kpi_sources WHERE id=? AND deleted_at IS NULL", (int(req.params["sid"]),)).fetchone()
    if not s:
        raise HTTPError(404, "not_found", "Source not found")
    ok, msg, n = visit(req.db, s, c.user["username"], True)
    audit(req.db, "source.visited", c.user, "weekly_kpi", "%s: %s" % (s["name"], msg[:120]), req.ip)
    return {"ok": ok, "message": msg, "proposals": n}


@router.route("POST", "/api/sources/<int:sid>/reviewed")
def src_reviewed(req):
    c = need(req, "weekly_kpi", "edit")
    req.db.execute("UPDATE kpi_sources SET reviewed_at=? WHERE id=?", (now(), int(req.params["sid"])))
    return {"ok": True}


@router.route("GET", "/api/sources/log")
def src_log(req):
    need(req, "weekly_kpi", "view")
    return {"log": [dict(r) for r in req.db.execute("SELECT l.*, s.name FROM source_log l LEFT JOIN kpi_sources s ON s.id=l.source_id ORDER BY l.id DESC LIMIT 60")]}


@router.route("GET", "/api/proposals")
def prop_list(req):
    need(req, "weekly_kpi", "view")
    st = req.query.get("status") or "open"
    q = "SELECT p.*, k.code, k.name, k.unit, k.decimals, s.name src, s.tier, s.cert_changed FROM kpi_proposals p JOIN kpis k ON k.id=p.kpi_id JOIN kpi_sources s ON s.id=p.source_id WHERE " + ("p.status IN ('pending','quarantined')" if st == "open" else "1=1") + " ORDER BY p.id DESC LIMIT 200"
    out = []
    for p in req.db.execute(q):
        prev = req.db.execute("SELECT period, value FROM kpi_readings WHERE kpi_id=? AND period<=? ORDER BY period DESC LIMIT 1", (p["kpi_id"], p["period"])).fetchone()
        out.append(dict(dict(p), checks=json.loads(p["checks"] or "[]"), previous=dict(prev) if prev else None))
    return {"proposals": out}


@router.route("POST", "/api/proposals/<int:pid>/decide")
def prop_decide(req):
    c = need(req, "weekly_kpi", "approve")
    p = req.db.execute("SELECT * FROM kpi_proposals WHERE id=? AND status IN ('pending','quarantined')", (int(req.params["pid"]),)).fetchone()
    if not p:
        raise HTTPError(404, "not_found", "No open proposal with that number")
    d = req.json()
    note = need_str(d, "note", "Note", 300, False)
    if d.get("decision") == "reject":
        req.db.execute("UPDATE kpi_proposals SET status='rejected', decided_by=?, decided_at=?, note=? WHERE id=?", (c.user["username"], now(), note, p["id"]))
        audit(req.db, "source.value_rejected", c.user, "weekly_kpi", "Proposed value %s for kpi %d rejected" % (p["value"], p["kpi_id"]), req.ip)
        return {"status": "rejected"}
    if p["status"] == "quarantined" and len(note) < 10:
        raise HTTPError(400, "override_required", "This value failed a check (%s). To accept it anyway, say why (at least 10 characters)." % "; ".join(json.loads(p["checks"] or "[]")))
    accept(req.db, p["id"], c.user["username"], note or "Accepted")
    audit(req.db, "source.value_accepted", c.user, "weekly_kpi", "Proposed value %s for kpi %d accepted" % (p["value"], p["kpi_id"]), req.ip)
    return {"status": "accepted"}


def parse_links_sheet(rows, kpi_map):
    """Rows of the sites workbook (#, KRI, Frequency, Source, SITE) -> sources merged by link, with the indicator codes they feed."""
    hi = next((i for i, r in enumerate(rows[:6]) if r and any(str(c or "").strip().lower() == "site" for c in r)), None)
    if hi is None:
        raise HTTPError(400, "bad_file", "No header row with a SITE column was found.")
    head = [str(c or "").strip().lower() for c in rows[hi]]
    ix = {n: head.index(n) for n in ("#", "kri", "frequency", "source", "site") if n in head}
    out, manual = {}, []
    for r in rows[hi + 1:]:
        r = list(r) + [None] * 6
        num, kri, freq, src, site = [(str(r[ix[n]]).strip() if n in ix and r[ix[n]] is not None else "") for n in ("#", "kri", "frequency", "source", "site")]
        if not kri:
            continue
        urls = re.findall(r"https://[^\s,;<>\"]+", site)
        codes = kpi_map.get(num, [])
        if not urls:
            manual.append({"kri": kri, "source": src, "note": "No website to visit: update by hand", "codes": codes}); continue
        for u in urls:
            u = u.rstrip(".)")
            e = out.setdefault(u, {"url": u, "names": [], "freq": freq, "provider": src, "codes": [], "kris": []})
            e["kris"].append(kri); e["codes"] += [c for c in codes if c not in e["codes"]]
    srcs = []
    for u, e in out.items():
        host = host_of(u)
        srcs.append({"name": "%s: %s" % (e["provider"] or host, "; ".join(e["kris"][:3]) + ("..." if len(e["kris"]) > 3 else "")), "url": u, "provider": e["provider"], "freq": e["freq"], "tier": tier_of(host), "codes": e["codes"], "kris": e["kris"], "manual_only": is_commercial(host)})
    return srcs, manual


KPI_MAP = {"1": ["MM_VAL_SHARE"], "2": ["MM_VOL_SHARE"], "3": ["INF_USD_M", "INF_USD_FOOD", "INF_USD_NONFOOD"], "4": ["INF_ZWG_M"], "5": ["FX_INTERBANK", "FXD_USD", "FXD_GBP", "FXD_BWP"], "6": ["FX_PARALLEL", "FX_PREMIUM"], "7": ["USD_SETTLE"], "8": ["EXPORTS", "IMPORTS"],
           "9": ["REMIT_FY", "REMIT_Q"], "10": ["ZSE_CAP", "VFEX_CAP"], "11": ["FUEL_PETROL", "FUEL_DIESEL"], "12": ["CPI_USD"], "13": ["CAR"], "14": ["NPL"], "16": ["MM_LINES_ECONET", "MM_LINES_NETONE", "MM_LINES_TELECEL", "MM_SHARE_ECONET", "MM_SHARE_NETONE", "MM_SHARE_TELECEL"],
           "17": ["POLICY_RATE", "LENDING_RATE"], "18": ["GDP", "GDP_PROJ"], "19": ["EMP_FORMAL", "EMP_INFORMAL", "EMP_HOUSEHOLD", "EMP_AGRICULTURE"], "20": ["CROP_MAIZE", "CROP_TOBACCO", "CROP_SORGHUM", "CROP_SOYABEANS", "CROP_COTTON"], "21": ["PLATINUM", "PALLADIUM", "GOLD"],
           "22": ["PEG_USDC", "PEG_USDT", "PEG_DAI", "PEG_USDP"], "23": ["M1", "M2", "M3"]}


@router.route("POST", "/api/sources/load")
def src_load(req):
    """Body: the sites workbook (.xlsx) or empty to use the list shipped with Sentinel. Everything is created as PROPOSED: nothing is visited until verified."""
    c = need(req, "weekly_kpi", "create")
    data = req.body()
    if data[:2] != b"PK":
        data = b""  # anything that is not a workbook means: use the list shipped with Sentinel
    if data:
        try:
            srcs, manual = parse_links_sheet(next(iter(xlsx.read(data).values())), KPI_MAP)
        except HTTPError:
            raise
        except Exception:
            raise HTTPError(400, "bad_file", "The workbook could not be read.")
    else:
        j = json.load(open(SEED_FILE, encoding="utf-8")); srcs, manual = j["sources"], j["manual"]
    added = 0
    for s in srcs:
        try:
            f = clean_source({"name": s["name"], "url": s["url"], "provider": s.get("provider"), "freq": s.get("freq"), "note": "Imported from the sites list", "manual_only": s.get("manual_only")})
        except HTTPError:
            continue
        sid = req.db.execute("SELECT id FROM kpi_sources WHERE url=? AND deleted_at IS NULL", (f["url"],)).fetchone()
        if not sid:
            cols = list(f) + ["proposed_by", "proposed_at", "status"]
            sid = {"id": req.db.execute("INSERT INTO kpi_sources(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), list(f.values()) + [c.user["username"], now(), "proposed"]).lastrowid}; added += 1
        for code in s.get("codes", []):
            k = req.db.execute("SELECT id FROM kpis WHERE code=? AND deleted_at IS NULL", (code,)).fetchone()
            if k:
                req.db.execute("INSERT OR IGNORE INTO kpi_source_links(source_id,kpi_id,rule_type,rule) VALUES(?,?,'watch','{}')", (sid["id"], k["id"]))
    audit(req.db, "source.loaded", c.user, "weekly_kpi", "Sites list loaded: %d new source(s) proposed, %d manual-only indicator(s)" % (added, len(manual)), req.ip)
    return {"added": added, "manual": manual}
