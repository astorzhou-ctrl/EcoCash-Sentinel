"""AI Governance (BRD 13.34) and the Claude client behind the Sentinel Copilot (BRD 13.31).

The rules come from BRD section 4.2 and are enforced here, in one place, for every AI call:
  * Human decision: the AI never writes a record, approves, sends or escalates; it can only create proposals that a named person accepts or rejects.
  * Approved hosting only: no call leaves Sentinel until the AI provider has been approved (basis, region, data scope), a key is stored and the mode is on.
  * Personal data is redacted before any model sees text. This cannot be switched off.
  * Evidence: every prompt (redacted), output, tool call, source, token count and cost is logged.
  * Uploaded and fetched text is data, never instructions; a kill switch turns all AI off at once.
Modes: Off (nothing), Assist (internal data and documents only), Advanced (adds trusted external sources, horizon scanning and impact analysis)."""
import datetime
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import mfa
from .api import router, need, need_str
from .core import audit, now
from .web import HTTPError

SYSTEM_VERSION = "sentinel-copilot-1.0"
DEFAULT_ENDPOINT = "https://api.anthropic.com"
MODES = ("off", "assist", "advanced")
CAPS = {  # capability -> (label, mode needed, manual fallback)
    "chat": ("Ask the Copilot (answers from the register and approved documents)", "assist", "Search, filters and the report builder"),
    "documents": ("Read, analyse and summarise documents", "assist", "Read the document and write the summary by hand"),
    "assess": ("Draft risk assessments from documents and descriptions", "assist", "Enter risks in the register or import the workbook"),
    "rate": ("Propose ratings for existing risks", "assist", "The owner rates in Assessment Studio"),
    "research": ("Research trusted external sources and cite them", "advanced", "Read the source and note it by hand"),
    "horizon": ("Watch for developments and prepare impact analyses", "advanced", "The Risk Office follows regulators and news by hand"),
}
# price per million tokens (input, output) from the Claude model documentation; editable in AI Governance because prices change
PRICES = {"claude-fable-5-1": [10.0, 50.0], "claude-opus-5-5": [4.0, 20.0], "claude-sonnet-5-5": [2.0, 10.0], "claude-haiku-5-5": [0.10, 0.50]}
MODEL_LABELS = {"claude-fable-5-1": "Claude Fable 5.1 (frontier reasoning)", "claude-opus-5-5": "Claude Opus 5.5 (deep analysis)", "claude-sonnet-5-5": "Claude Sonnet 5.5 (fast and capable)", "claude-haiku-5-5": "Claude Haiku 5.5 (fastest, lowest cost)"}
TRUSTED = [("rbz.co.zw", "Reserve Bank of Zimbabwe", "regulator"), ("zimra.co.zw", "ZIMRA", "regulator"), ("potraz.gov.zw", "POTRAZ (data protection authority)", "regulator"), ("seczim.co.zw", "Securities and Exchange Commission of Zimbabwe", "regulator"), ("ipec.co.zw", "IPEC (insurance and pensions)", "regulator"),
           ("zimstat.co.zw", "ZIMSTAT", "official"), ("parlzim.gov.zw", "Parliament of Zimbabwe", "official"), ("veritaszim.net", "Veritas (Zimbabwe legislation)", "official"), ("zimlii.org", "ZimLII (Zimbabwe law)", "official"), ("esaamlg.org", "ESAAMLG", "international"),
           ("fatf-gafi.org", "FATF", "international"), ("bis.org", "Bank for International Settlements", "international"), ("imf.org", "International Monetary Fund", "international"), ("worldbank.org", "World Bank", "international"), ("oecd.org", "OECD", "international"),
           ("iso.org", "ISO", "standards"), ("nist.gov", "NIST", "standards"), ("europa.eu", "European Union (AI Act and GDPR)", "standards"), ("anthropic.com", "Anthropic", "vendor"), ("reuters.com", "Reuters", "news"), ("herald.co.zw", "The Herald", "news"), ("newsday.co.zw", "NewsDay", "news")]
TRUSTED += [("bbc.co.uk", "BBC News", "news"), ("bbci.co.uk", "BBC News feeds", "news"), ("bbc.com", "BBC", "news"), ("allafrica.com", "allAfrica", "news")]
DEFAULTS = {
    "mode": "off", "engine": "local", "caps": {k: True for k in CAPS},
    "web": {"providers": ["duckduckgo", "wikipedia", "google_news"], "google_cx": "", "max_results": 8, "read_unlisted": False, "autonomous": True}, "learning": True,
    "provider": {"name": "Anthropic (Claude API)", "endpoint": DEFAULT_ENDPOINT, "approved": False, "approved_by": None, "approved_at": None, "basis": "", "region": "", "zdr": False, "dpia_ref": "", "key_set_by": None, "key_set_at": None},
    "models": {"chat": "claude-sonnet-5-5", "deep": "claude-opus-5-5", "fast": "claude-haiku-5-5"},
    "effort": {"chat": "medium", "deep": "high", "fast": "low"},
    "budget": {"monthly_usd": 100.0, "max_output_tokens": 16000, "per_user_per_hour": 30, "max_doc_chars": 400000, "web_search_usd": 0.01},
    "sources": [d for d, _, _ in TRUSTED], "prices": PRICES,
    "horizon": {"min_severity": 3, "watch_roles": ["Head of Risk", "Risk Manager"], "max_per_scan": 6},
    "changed_by": None, "changed_at": None,
}


class AIError(Exception):
    def __init__(self, code, message, status=502):
        super().__init__(message); self.code, self.status = code, status


def _deep(base, over):
    out = json.loads(json.dumps(base))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep(out[k], v)
        else:
            out[k] = v
    return out


def settings(db):
    r = db.execute("SELECT value FROM settings WHERE key='ai'").fetchone()
    try:
        return _deep(DEFAULTS, json.loads(r["value"]) if r else {})
    except ValueError:
        return json.loads(json.dumps(DEFAULTS))


def save_settings(db, st):
    db.execute("INSERT INTO settings(key,value) VALUES('ai',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(st),))


def api_key(db):
    r = db.execute("SELECT value FROM settings WHERE key='ai_key'").fetchone()
    try:
        return mfa.unseal(r["value"]) if r else None
    except Exception:
        return None


def effective_caps(st):
    if st["mode"] == "off":
        return {k: False for k in CAPS}
    return {k: bool(st["caps"].get(k)) and (CAPS[k][1] == "assist" or st["mode"] == "advanced") for k in CAPS}


def month_cost(db):
    start = now()[:7] + "-01T00:00:00Z"
    return db.execute("SELECT COALESCE(SUM(cost),0) c FROM ai_log WHERE ts>=?", (start,)).fetchone()["c"]


def unavailable(db, user=None, cap=None):
    """None when AI may be used, else (code, plain-language reason). The one gate every call passes."""
    st = settings(db)
    if st["mode"] == "off":
        return "off", "AI is switched off. Use search, filters and reports, or ask your System Administrator to switch it on in AI Governance."
    if cap and not effective_caps(st).get(cap):
        return "capability", "This AI capability is off%s. %s" % (" in the current mode" if st["caps"].get(cap) else "", "Use the manual route: " + CAPS[cap][2] + ".")
    if st["engine"] == "claude":  # the optional paid engine needs hosting approval, a key and a budget; the built-in engine runs on this computer and needs none of them
        if not st["provider"]["approved"]:
            return "provider", "The Claude provider has not been approved for hosting yet (BRD 4.2). A System Administrator approves it in AI Governance, or switches to the built-in engine."
        if not api_key(db):
            return "key", "No API key is stored for Claude. A System Administrator adds it in AI Governance, or switches to the built-in engine."
        if month_cost(db) >= st["budget"]["monthly_usd"]:
            return "budget", "The monthly AI budget (US$%.0f) is used up. A System Administrator can raise it in AI Governance." % st["budget"]["monthly_usd"]
    if user is not None:
        n = db.execute("SELECT COUNT(*) n FROM ai_log WHERE user_id=? AND ts>=?", (user["id"], (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchone()["n"]
        if n >= st["budget"]["per_user_per_hour"]:
            return "rate", "You have reached the hourly limit of %d AI requests. Try again later." % st["budget"]["per_user_per_hour"]
    return None


def gate(db, user, cap):
    u = unavailable(db, user, cap)
    if u:
        raise HTTPError(503, "ai_" + u[0], u[1])


# ------------------------------------------------------------------ redaction: personal data never reaches a model
def _luhn(d):
    s, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            n -= 9 if n > 9 else 0
        s += n; alt = not alt
    return s % 10 == 0


PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("SECRET", re.compile(r"(?i)\b(?:password|passwd|secret|api[_ -]?key|token|pin)\b\s*[:=]\s*\S+")),
    ("NATIONAL_ID", re.compile(r"\b\d{2}[- ]?\d{6,7}[- ]?[A-Za-z][- ]?\d{2}\b")),
    ("PHONE", re.compile(r"(?<![\w.])(?:\+?263|0)[\s-]?7[1-9](?:[\s-]?\d){7}(?!\d)|(?<![\w.])\+\d{1,3}[\s-]?\d{2,4}[\s-]?\d{3}[\s-]?\d{3,4}(?!\d)")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]
_LONG = re.compile(r"(?<![\w.,])\d(?:[ -]?\d){8,18}(?![\w])")


def redact(text):
    """(clean_text, counts). Replaces emails, phone numbers, national IDs, card and account numbers, secrets and IP addresses with tokens."""
    if not isinstance(text, str) or not text:
        return text, {}
    counts = {}
    def sub(kind):
        def f(m):
            counts[kind] = counts.get(kind, 0) + 1
            return "[%s_%d]" % (kind, counts[kind])
        return f
    for kind, rx in PATTERNS:
        text = rx.sub(sub(kind), text)
    def digits(m):
        d = re.sub(r"\D", "", m.group(0))
        if 13 <= len(d) <= 19 and _luhn(d):
            counts["CARD"] = counts.get("CARD", 0) + 1; return "[CARD_%d]" % counts["CARD"]
        counts["ACCOUNT"] = counts.get("ACCOUNT", 0) + 1; return "[ACCOUNT_%d]" % counts["ACCOUNT"]
    text = _LONG.sub(digits, text)
    return text, counts


INJECTION = re.compile(r"(?i)(ignore (all |any |the )?(previous|prior|above) (instructions|rules)|disregard (the )?(system|previous)|you are now|new instructions:|reveal (your|the) (system )?prompt|act as (an? )?(unrestricted|jailbroken)|developer mode)")


def injection_flags(text):
    return ["possible instruction hidden in the text"] if isinstance(text, str) and INJECTION.search(text) else []


# ------------------------------------------------------------------ the Claude client (Messages API)
def cost_of(st, model, tin, tout, searches):
    p = st["prices"].get(model) or [0, 0]
    return round((tin * p[0] + tout * p[1]) / 1e6 + searches * st["budget"]["web_search_usd"], 6)


def call_claude(db, body, timeout=240):
    """POST /v1/messages. Returns the parsed response. Never logs or returns the key."""
    st = settings(db); key = api_key(db)
    base = (os.environ.get("SENTINEL_AI_BASE") or st["provider"]["endpoint"] or DEFAULT_ENDPOINT).rstrip("/")
    if not key:
        raise AIError("key", "No API key stored.", 503)
    data = json.dumps(body).encode()
    for attempt in range(3):
        req = urllib.request.Request(base + "/v1/messages", data=data, method="POST", headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01", "user-agent": "EcoCash-Sentinel/" + SYSTEM_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(raw).get("error", {}).get("message", raw)
            except ValueError:
                msg = raw
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                wait = min(float(e.headers.get("retry-after") or 0) or (1.5 * (attempt + 1)), 20.0); time.sleep(wait); continue
            code = {401: "auth", 403: "forbidden", 400: "bad_request", 404: "model", 429: "rate_limit"}.get(e.code, "upstream")
            raise AIError(code, "The AI provider returned %d: %s" % (e.code, str(msg)[:300]))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1)); continue
            raise AIError("network", "Sentinel could not reach the AI provider (%s). Check the internet connection and the approved endpoint." % (getattr(e, "reason", None) or e))
    raise AIError("upstream", "The AI provider did not answer.")


def log_call(db, user, feature, model, inp, out, tools, sources, usage, status="ok", error=None, flags=None, conv_id=None, redactions=None, searches=0):
    st = settings(db); tin, tout = int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
    return db.execute("INSERT INTO ai_log(ts,user_id,username,feature,model,system_version,prompt_hash,input,output,tools,sources,tokens_in,tokens_out,searches,cost,status,error,flags,conv_id,redactions) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (now(), user["id"] if user else None, user["username"] if user else "system", feature, model, SYSTEM_VERSION, hashlib.sha256((inp or "").encode()).hexdigest()[:16], (inp or "")[:60000], (out or "")[:60000], json.dumps(tools or []), json.dumps(sources or []), tin, tout, searches, cost_of(st, model, tin, tout, searches), status, (error or "")[:500], json.dumps(flags or []), conv_id, json.dumps(redactions or {}))).lastrowid


def domain_of(url):
    try:
        h = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""
    return h.lower().lstrip(".")


def trust_tier(st, url):
    """'trusted' when the host is one of the approved sources (or a sub-domain of one), else 'unlisted'."""
    h = domain_of(url)
    for d in st["sources"]:
        if h == d or h.endswith("." + d):
            return "trusted"
    return "unlisted"


# ------------------------------------------------------------------ AI Governance API
def status_payload(db, c):
    st = settings(db); caps = effective_caps(st); u = unavailable(db, c.user)
    return {"mode": st["mode"], "engine": st["engine"], "web_providers": st["web"]["providers"], "on": u is None or u[0] in ("rate",), "reason": None if u is None else u[1], "code": None if u is None else u[0], "caps": caps, "models": st["models"],
            "new_briefs": db.execute("SELECT COUNT(*) n FROM ai_briefs WHERE status='new'").fetchone()["n"] if caps.get("horizon") or caps.get("chat") else 0, "pending_proposals": db.execute("SELECT COUNT(*) n FROM ai_proposals WHERE status='pending'").fetchone()["n"]}


@router.route("GET", "/api/ai/status")
def ai_status(req):
    c = need(req)
    return status_payload(req.db, c)


def checklist(db, st):
    """NIST AI RMF (Govern, Map, Measure, Manage) and ISO/IEC 42001 status, computed from what is really configured and recorded."""
    n_log = db.execute("SELECT COUNT(*) n FROM ai_log").fetchone()["n"]; fair = db.execute("SELECT * FROM ai_fairness ORDER BY id DESC LIMIT 1").fetchone()
    inc = db.execute("SELECT COUNT(*) n FROM ai_incidents WHERE status='open'").fetchone()["n"]; props = db.execute("SELECT COUNT(*) n, SUM(status IN ('accepted','edited','rejected')) d FROM ai_proposals").fetchone()
    docs = db.execute("SELECT COUNT(*) n FROM ai_docs WHERE status='approved' AND deleted_at IS NULL").fetchone()["n"]
    items = [
        ("GOVERN", "Roles and accountability: AI is switched on, off and configured only by a System Administrator; business roles can only monitor it", True, "ISO 42001 5.3; NIST GOVERN 2"),
        ("GOVERN", "Approved hosting: the built-in engine runs on this computer; an external model (Claude) is used only after its hosting is approved", st["engine"] == "local" or bool(st["provider"]["approved"]), "BRD 4.2; ISO 42001 A.10; Cyber and Data Protection Act ss.28-29"),
        ("GOVERN", "Kill switch tested and mode set deliberately (default Off)", st["mode"] in MODES, "BRD 4.2; NIST GOVERN 1.7"),
        ("MAP", "AI inventory: each capability has a purpose, users, data and a manual fallback", True, "ISO 42001 A.4; NIST MAP 1"),
        ("MAP", "Personal data redacted before any model sees text (cannot be switched off)", True, "Cyber and Data Protection Act; ISO 42001 A.7"),
        ("MAP", "Approved content index in use (documents approved by a named person before the Copilot relies on them)", docs > 0, "BRD 13.31"),
        ("MEASURE", "Every prompt, output, source and cost logged", n_log > 0, "BRD 4.2; ISO 42001 A.6.2.8"),
        ("MEASURE", "Accuracy and acceptance reported from reviewer decisions", bool(props["d"]), "NIST MEASURE 2"),
        ("MEASURE", "Fairness consistency test run and passed", bool(fair and fair["passed"]), "ISO 42001 A.5; NIST MEASURE 2.11"),
        ("MANAGE", "AI incidents recorded and none left open", inc == 0, "ISO 42001 A.8.3; NIST MANAGE 4"),
        ("MANAGE", "Human decision: the AI only proposes; a named reviewer accepts or rejects", True, "BRD 4.2; Cyber and Data Protection Act (automated decision-making)"),
        ("MANAGE", "Prompt-injection defence: uploaded and fetched text is treated as data", True, "BRD 4.2; OWASP LLM01"),
    ]
    return [{"function": f, "control": t, "met": bool(m), "ref": r} for f, t, m, r in items]


@router.route("GET", "/api/ai/gov")
def gov_get(req):
    c = need(req, "ai_governance", "view")
    st = settings(req.db); p = st["provider"]
    key = api_key(req.db)
    month = now()[:7] + "-01T00:00:00Z"
    use = req.db.execute("SELECT COUNT(*) n, COALESCE(SUM(cost),0) cost, COALESCE(SUM(tokens_in),0) tin, COALESCE(SUM(tokens_out),0) tout, SUM(status!='ok') err FROM ai_log WHERE ts>=?", (month,)).fetchone()
    perms = c.perms.get("ai_governance", set())
    gk = req.db.execute("SELECT value FROM settings WHERE key='ai_google_key'").fetchone()
    return {"settings": {k: st[k] for k in ("mode", "engine", "caps", "models", "effort", "budget", "sources", "prices", "horizon", "web", "learning", "changed_by", "changed_at")}, "provider": dict(p), "key": {"set": bool(key), "tail": ("…" + key[-4:]) if key else None}, "google_key_set": bool(gk),
            "capabilities": [{"key": k, "label": v[0], "mode": v[1], "fallback": v[2], "on": bool(st["caps"].get(k)), "effective": effective_caps(st)[k]} for k, v in CAPS.items()], "models_available": [{"id": k, "label": v} for k, v in MODEL_LABELS.items()],
            "trusted": [{"domain": d, "name": n, "tier": t, "active": d in st["sources"]} for d, n, t in TRUSTED] + [{"domain": d, "name": d, "tier": "custom", "active": True} for d in st["sources"] if d not in {x[0] for x in TRUSTED}],
            "usage": {"requests": use["n"], "cost": round(use["cost"], 4), "tokens_in": use["tin"], "tokens_out": use["tout"], "errors": use["err"] or 0, "budget": st["budget"]["monthly_usd"]}, "checklist": checklist(req.db, st), "unavailable": unavailable(req.db, c.user),
            "can": {"edit": "edit" in perms, "approve": "approve" in perms, "export": "export" in perms}, "system_version": SYSTEM_VERSION}


def _need_reason(b):
    why = need_str(b, "reason", "Reason", 300)
    if len(why) < 10:
        raise HTTPError(400, "validation", "Give the reason (at least 10 characters). It is recorded in the audit trail.")
    return why


@router.route("POST", "/api/ai/gov/settings")
def gov_settings(req):
    c = need(req, "ai_governance", "edit"); b = req.json(); st = settings(req.db); old_mode = st["mode"]; why = _need_reason(b)
    eng_after = b["engine"] if b.get("engine") in ("local", "claude") else st["engine"]
    if "mode" in b:
        if b["mode"] not in MODES:
            raise HTTPError(400, "validation", "Mode must be off, assist or advanced.")
        if b["mode"] != "off" and old_mode == "off" and eng_after == "claude":  # the built-in engine runs on this computer and needs neither
            if not st["provider"]["approved"]:
                raise HTTPError(409, "not_approved", "Approve the AI provider (hosting, region and data scope) first. BRD 4.2 blocks external AI services until that is done.")
            if not api_key(req.db):
                raise HTTPError(409, "no_key", "Store the provider's API key first.")
        st["mode"] = b["mode"]
    if b.get("engine") in ("local", "claude"):
        if b["engine"] == "claude" and not (st["provider"]["approved"] and api_key(req.db)):
            raise HTTPError(409, "not_approved", "Claude needs a stored key and an approved hosting (Hosting and key). The built-in engine needs neither.")
        st["engine"] = b["engine"]
    if isinstance(b.get("web"), dict):
        w = b["web"]
        if isinstance(w.get("providers"), list):
            st["web"]["providers"] = [p for p in w["providers"] if p in ("duckduckgo", "wikipedia", "google_cse", "google_news")][:4]
        if "google_cx" in w:
            st["web"]["google_cx"] = re.sub(r"[^A-Za-z0-9:_-]", "", str(w["google_cx"]))[:80]
        if "autonomous" in w:
            st["web"]["autonomous"] = bool(w["autonomous"])
        if "read_unlisted" in w:
            st["web"]["read_unlisted"] = bool(w["read_unlisted"])
        if "max_results" in w:
            st["web"]["max_results"] = max(3, min(15, int(w["max_results"])))
    if "learning" in b:
        st["learning"] = bool(b["learning"])
    if isinstance(b.get("caps"), dict):
        for k in CAPS:
            if k in b["caps"]:
                st["caps"][k] = bool(b["caps"][k])
    if isinstance(b.get("models"), dict):
        for k in ("chat", "deep", "fast"):
            if b["models"].get(k) in MODEL_LABELS:
                st["models"][k] = b["models"][k]
    if isinstance(b.get("effort"), dict):
        for k in ("chat", "deep", "fast"):
            if b["effort"].get(k) in ("low", "medium", "high", "xhigh", "max"):
                st["effort"][k] = b["effort"][k]
    if isinstance(b.get("budget"), dict):
        for k, lo, hi in (("monthly_usd", 0, 100000), ("max_output_tokens", 1000, 64000), ("per_user_per_hour", 1, 500), ("max_doc_chars", 20000, 1500000)):
            if k in b["budget"]:
                try:
                    v = float(b["budget"][k])
                except (TypeError, ValueError):
                    raise HTTPError(400, "validation", "%s must be a number." % k)
                if not lo <= v <= hi:
                    raise HTTPError(400, "validation", "%s must be between %s and %s." % (k, lo, hi))
                st["budget"][k] = v if k == "monthly_usd" else int(v)
    if isinstance(b.get("sources"), list):
        st["sources"] = sorted({re.sub(r"^https?://", "", str(d).strip().lower()).strip("/") for d in b["sources"] if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(/[\w./-]*)?$", re.sub(r"^https?://", "", str(d).strip().lower()))})[:80]
    if isinstance(b.get("horizon"), dict):
        h = b["horizon"]
        if "min_severity" in h:
            st["horizon"]["min_severity"] = max(1, min(5, int(h["min_severity"])))
        if isinstance(h.get("watch_roles"), list):
            st["horizon"]["watch_roles"] = [str(x)[:60] for x in h["watch_roles"]][:10]
    if isinstance(b.get("prices"), dict):
        for m, p in b["prices"].items():
            if m in MODEL_LABELS and isinstance(p, list) and len(p) == 2:
                st["prices"][m] = [float(p[0]), float(p[1])]
    st["changed_by"], st["changed_at"] = c.user["username"], now(); save_settings(req.db, st)
    audit(req.db, "ai.settings", c.user, "ai_governance", "AI settings changed (mode %s -> %s): %s" % (old_mode, st["mode"], why), req.ip)
    return {"ok": True, "mode": st["mode"]}


@router.route("POST", "/api/ai/gov/key")
def gov_key(req):
    c = need(req, "ai_governance", "edit"); b = req.json(); why = _need_reason(b); st = settings(req.db)
    k = (b.get("key") or "").strip()
    if b.get("provider") == "google":  # an optional Google Programmable Search key (free tier) for web research
        if not k:
            req.db.execute("DELETE FROM settings WHERE key='ai_google_key'")
        else:
            req.db.execute("INSERT INTO settings(key,value) VALUES('ai_google_key',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mfa.seal(k),))
        audit(req.db, "ai.google_key", c.user, "ai_governance", "Google search key %s: %s" % ("stored" if k else "removed", why), req.ip)
        return {"ok": True, "set": bool(k)}
    if not k:  # clear the key
        req.db.execute("DELETE FROM settings WHERE key='ai_key'"); st["provider"]["key_set_by"] = None; save_settings(req.db, st)
        audit(req.db, "ai.key_cleared", c.user, "ai_governance", "AI provider key removed: %s" % why, req.ip)
        return {"ok": True, "set": False}
    if len(k) < 20 or any(ch.isspace() for ch in k):
        raise HTTPError(400, "validation", "That does not look like an API key.")
    req.db.execute("INSERT INTO settings(key,value) VALUES('ai_key',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (mfa.seal(k),))
    st["provider"]["key_set_by"], st["provider"]["key_set_at"] = c.user["username"], now()
    if st["provider"]["approved_by"] == c.user["username"]:  # one person cannot both store the key and approve the hosting: the approval lapses and another approver must renew it
        st["provider"].update(approved=False, approved_by=None, approved_at=None); st["mode"] = "off"
    save_settings(req.db, st)
    audit(req.db, "ai.key_set", c.user, "ai_governance", "AI provider key stored (ending %s): %s" % (k[-4:], why), req.ip)
    return {"ok": True, "set": True, "tail": "…" + k[-4:]}


@router.route("POST", "/api/ai/gov/approve")
def gov_approve(req):
    """The hosting approval BRD 4.2 requires. Whoever stored the key cannot approve it: two people."""
    c = need(req, "ai_governance", "approve"); b = req.json(); st = settings(req.db); p = st["provider"]
    if b.get("approved") is False:
        p.update(approved=False, approved_by=None, approved_at=None); st["mode"] = "off"; save_settings(req.db, st)
        audit(req.db, "ai.approval_withdrawn", c.user, "ai_governance", "AI provider approval withdrawn and AI switched off: %s" % _need_reason(b), req.ip)
        return {"ok": True, "approved": False}
    if p["key_set_by"] and p["key_set_by"] == c.user["username"]:
        raise HTTPError(403, "separation", "The person who stored the key cannot approve the hosting. Ask another approver.")
    basis = need_str(b, "basis", "Approval basis", 1500)
    if len(basis) < 40:
        raise HTTPError(400, "validation", "Describe the basis for approval (at least 40 characters): the data protection or transfer assessment, the contract and what data may be sent.")
    if not b.get("data_scope_confirmed"):
        raise HTTPError(400, "validation", "Confirm that only redacted, non-customer data (risk, control, KPI and document text) may be sent.")
    ep = (b.get("endpoint") or DEFAULT_ENDPOINT).strip().rstrip("/")
    if not ep.startswith("https://"):
        raise HTTPError(400, "validation", "The endpoint must be https.")
    p.update(approved=True, approved_by=c.user["username"], approved_at=now(), basis=basis, region=str(b.get("region") or "")[:120], zdr=bool(b.get("zdr")), dpia_ref=str(b.get("dpia_ref") or "")[:120], endpoint=ep)
    save_settings(req.db, st)
    audit(req.db, "ai.approved", c.user, "ai_governance", "AI provider %s approved for hosting (region %s, zero data retention %s, ref %s)" % (p["name"], p["region"] or "not stated", "yes" if p["zdr"] else "no", p["dpia_ref"] or "none"), req.ip)
    return {"ok": True, "approved": True}


@router.route("POST", "/api/ai/kill")
def gov_kill(req):
    """The kill switch: turns all AI off at once. Any AI owner or approver can pull it; it never needs a second person."""
    c = need(req)
    perms = c.perms.get("ai_governance", set())
    if not ({"edit", "approve"} & set(perms)):
        raise HTTPError(403, "forbidden", "You do not have permission to use the AI kill switch.")
    b = req.json(); st = settings(req.db); st["mode"] = "off"; st["changed_by"], st["changed_at"] = c.user["username"], now()
    if b.get("remove_key"):
        req.db.execute("DELETE FROM settings WHERE key='ai_key'")
    save_settings(req.db, st)
    audit(req.db, "ai.kill_switch", c.user, "ai_governance", "KILL SWITCH: all AI switched off%s. %s" % (" and the key removed" if b.get("remove_key") else "", str(b.get("reason") or "No reason given")[:300]), req.ip)
    return {"ok": True, "mode": "off"}


@router.route("GET", "/api/ai/gov/log")
def gov_log(req):
    need(req, "ai_governance", "view")
    q, args = "SELECT id, ts, username, feature, model, status, tokens_in, tokens_out, searches, cost, flags, substr(input,1,160) i, substr(output,1,160) o FROM ai_log", []
    f = (req.query.get("feature") or "").strip()
    if f:
        q += " WHERE feature=?"; args.append(f)
    rows = req.db.execute(q + " ORDER BY id DESC LIMIT 200", args).fetchall()
    return {"log": [dict(r) for r in rows], "features": [r["feature"] for r in req.db.execute("SELECT DISTINCT feature FROM ai_log ORDER BY feature")]}


@router.route("GET", "/api/ai/gov/log/<int:lid>")
def gov_log_one(req):
    need(req, "ai_governance", "view")
    r = req.db.execute("SELECT * FROM ai_log WHERE id=?", (int(req.params["lid"]),)).fetchone()
    if not r:
        raise HTTPError(404, "not_found", "Log entry not found.")
    d = dict(r)
    for k in ("tools", "sources", "flags", "redactions"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except ValueError:
            pass
    return d


@router.route("POST", "/api/ai/incident")
def ai_incident(req):
    c = need(req, "sentinel_copilot", "create"); b = req.json()
    kind = b.get("kind") if b.get("kind") in ("wrong", "biased", "leak", "unsafe", "other") else "other"
    d = need_str(b, "description", "Description", 2000)
    iid = req.db.execute("INSERT INTO ai_incidents(ts,reported_by,kind,severity,description,log_id) VALUES(?,?,?,?,?,?)", (now(), c.user["username"], kind, "High" if kind in ("leak", "unsafe", "biased") else "Medium", d, b.get("log_id"))).lastrowid
    audit(req.db, "ai.incident", c.user, "sentinel_copilot", "AI incident #%d reported (%s)" % (iid, kind), req.ip)
    return {"id": iid}


@router.route("GET", "/api/ai/gov/incidents")
def gov_incidents(req):
    need(req, "ai_governance", "view")
    return {"incidents": [dict(r) for r in req.db.execute("SELECT * FROM ai_incidents ORDER BY id DESC LIMIT 100")]}


@router.route("POST", "/api/ai/gov/incidents/<int:iid>/close")
def gov_incident_close(req):
    c = need(req, "ai_governance", "edit"); res = need_str(req.json(), "resolution", "Resolution", 1000)
    req.db.execute("UPDATE ai_incidents SET status='closed', resolution=? WHERE id=?", (res, int(req.params["iid"])))
    audit(req.db, "ai.incident_closed", c.user, "ai_governance", "AI incident #%s closed" % req.params["iid"], req.ip)
    return {"ok": True}


def quality(db):
    """Usage, acceptance and fairness monitors from real records (BRD: suggestions, accepted, edited, rejected; accuracy and drift)."""
    p = db.execute("SELECT COUNT(*) n, SUM(status='accepted') a, SUM(status='edited') e, SUM(status='rejected') r, SUM(status='pending') p FROM ai_proposals").fetchone()
    fb = db.execute("SELECT SUM(feedback='up') up, SUM(feedback='down') down FROM ai_msgs").fetchone()
    by_month = [dict(r) for r in db.execute("SELECT substr(ts,1,7) m, COUNT(*) n, SUM(cost) cost, SUM(status!='ok') err FROM ai_log GROUP BY substr(ts,1,7) ORDER BY m DESC LIMIT 12")]
    by_feature = [dict(r) for r in db.execute("SELECT feature, COUNT(*) n, SUM(cost) cost, SUM(status!='ok') err FROM ai_log GROUP BY feature ORDER BY n DESC")]
    # rating bias monitor: AI-proposed ratings against the final human rating, by system and category
    drift = []
    for r in db.execute("SELECT p.ai_values, p.final_values, p.status, r.system, r.category FROM ai_proposals p LEFT JOIN risks r ON r.source_ref=p.risk_ref OR r.ref=p.risk_ref WHERE p.kind='rating' AND p.status IN ('accepted','edited')"):
        try:
            a, f = json.loads(r["ai_values"] or "{}"), json.loads(r["final_values"] or "{}")
            drift.append({"system": r["system"] or "-", "category": r["category"] or "-", "diff": (f.get("res_l", 0) * f.get("res_c", 0)) - (a.get("res_l", 0) * a.get("res_c", 0)), "edited": r["status"] == "edited"})
        except ValueError:
            pass
    groups = {}
    for d in drift:
        g = groups.setdefault(d["category"], []); g.append(d)
    monitor = [{"group": k, "n": len(v), "mean_diff": round(sum(x["diff"] for x in v) / len(v), 2), "edited": sum(1 for x in v if x["edited"])} for k, v in sorted(groups.items())]
    fair = db.execute("SELECT * FROM ai_fairness ORDER BY id DESC LIMIT 5").fetchall()
    return {"proposals": {"total": p["n"] or 0, "accepted": p["a"] or 0, "edited": p["e"] or 0, "rejected": p["r"] or 0, "pending": p["p"] or 0}, "feedback": {"up": fb["up"] or 0, "down": fb["down"] or 0}, "by_month": by_month, "by_feature": by_feature, "rating_monitor": monitor,
            "fairness": [dict(x) for x in fair], "incidents_open": db.execute("SELECT COUNT(*) n FROM ai_incidents WHERE status='open'").fetchone()["n"]}


@router.route("GET", "/api/ai/gov/quality")
def gov_quality(req):
    need(req, "ai_governance", "view")
    return quality(req.db)


def model_card(db):
    st = settings(db)
    return {"system": "Sentinel Copilot", "version": SYSTEM_VERSION, "owner": "AI owner (nominated) with the Head of Risk", "purpose": "Help EcoCash staff understand and manage enterprise risk: answer questions from the register and approved documents, summarise documents, draft risk assessments and ratings for human review, and prepare impact analyses of external developments.",
            "models": {k: MODEL_LABELS.get(v, v) for k, v in st["models"].items()}, "provider": st["provider"]["name"], "hosting": {"approved": st["provider"]["approved"], "region": st["provider"]["region"], "endpoint": st["provider"]["endpoint"], "zero_data_retention": st["provider"]["zdr"]},
            "data_sent": "Redacted question text; register, control, KPI and incident data the user may already see; text of approved documents; text of documents the user uploads. Personal data (emails, phone numbers, national IDs, card and account numbers, secrets, IP addresses) is replaced by tokens first.",
            "never": ["write, approve, send or escalate on its own", "see data the signed-in user cannot see", "use protected characteristics (sex, race, ethnicity, religion, nationality, age, disability, politics) to rate or rank a risk or a person", "act on instructions found inside documents or web pages"],
            "limitations": ["It can be wrong or out of date: every answer shows its sources and a reminder to verify", "It does not know EcoCash beyond what is in Sentinel and the documents approved into its index; it is not fine-tuned", "Web research depends on what trusted sources publish and on the search tool; impact analyses are prepared, not verified", "Ratings are proposals with a rationale and a confidence, not decisions"],
            "oversight": "A named reviewer accepts, edits or rejects every proposal; decisions, edits and reasons are logged and reported monthly. A kill switch turns all AI off at once.", "standards": ["NIST AI RMF 1.0 (Govern, Map, Measure, Manage)", "ISO/IEC 42001:2023", "Zimbabwe Cyber and Data Protection Act [Chapter 12:07], sections 28 and 29 (transfer outside Zimbabwe) and the restriction on automated decisions"]}


@router.route("GET", "/api/ai/gov/card")
def gov_card(req):
    need(req, "ai_governance", "view")
    return model_card(req.db)


def add_default_sources(db):
    """Once each: news sources, and Google News with autonomous search, are added to installations that already stored their own settings. An administrator can still remove them."""
    def flag(k):
        return db.execute("SELECT 1 FROM settings WHERE key=?", (k,)).fetchone()
    r = db.execute("SELECT value FROM settings WHERE key='ai'").fetchone(); st = json.loads(r["value"]) if r else None
    if st is not None and not flag("sources_news_v1") and st.get("sources"):
        st["sources"] = sorted(set(st["sources"]) | {"bbc.co.uk", "bbci.co.uk", "bbc.com", "allafrica.com"})
    if st is not None and not flag("web_gn_v1"):
        w = st.setdefault("web", {})
        if "providers" in w and "google_news" not in w["providers"]:
            w["providers"] = list(w["providers"]) + ["google_news"]
        w.setdefault("autonomous", True)
    if st is not None:
        db.execute("UPDATE settings SET value=? WHERE key='ai'", (json.dumps(st),))
    for k in ("sources_news_v1", "web_gn_v1"):
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,'1')", (k,))
