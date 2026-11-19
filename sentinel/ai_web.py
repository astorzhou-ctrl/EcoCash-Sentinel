"""Web research for the Copilot without a paid service.
Search: DuckDuckGo (no key) and Wikipedia (no key) by default; Google Programmable Search if a System Administrator stores a key and engine id (a free
daily allowance exists); results are marked 'approved source' or 'not on the approved list'. Reading: Sentinel reads a page itself only from an approved
source (https, public address, small page); a page from any other site is read only when the System Administrator allows it, and the user can always open any
result in their own browser (Chrome, Edge, Firefox) with one click. Everything returned is untrusted text: it is summarised and cited, never obeyed."""
import datetime
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape

from . import ai_gov, ai_kb
from .core import now

UA = "Mozilla/5.0 (compatible; EcoCash-Sentinel/1.0; enterprise risk research)"
DDG = os.environ.get("SENTINEL_WEB_DDG") or "https://html.duckduckgo.com/html/"
WIKI = os.environ.get("SENTINEL_WEB_WIKI") or "https://en.wikipedia.org/w/api.php"
GOOGLE = os.environ.get("SENTINEL_WEB_GOOGLE") or "https://www.googleapis.com/customsearch/v1"
GNEWS = os.environ.get("SENTINEL_WEB_GNEWS") or "https://news.google.com/rss"
LABELS = {"duckduckgo": "DuckDuckGo", "wikipedia": "Wikipedia", "google_cse": "Google", "google_news": "Google News"}


class WebError(Exception):
    pass


def _get(url, timeout=15, max_bytes=2_000_000, headers=None):
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA, "Accept-Language": "en", "Accept": "text/html,application/json,application/xml,text/plain"}, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(max_bytes + 1)
            return r.status, raw[:max_bytes], (r.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        raise WebError("the service answered %d" % e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise WebError("could not be reached (%s)" % (getattr(e, "reason", None) or e))


def _plain(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# ------------------------------------------------------------------ providers
def parse_duckduckgo(html):
    """Results from DuckDuckGo's HTML page: [{title, url, snippet}]. Raises WebError when the page is a block or a challenge instead of results."""
    out, snippets = [], [_plain(m.group(1)) for m in re.finditer(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', html, re.S)]
    for i, m in enumerate(re.finditer(r'<a\b([^>]*class="[^"]*result__a[^"]*"[^>]*)>(.*?)</a>', html, re.S)):
        h = re.search(r'href="([^"]+)"', m.group(1))
        if not h:
            continue
        href = unescape(h.group(1))
        if href.startswith("//"):
            href = "https:" + href
        q = urllib.parse.urlparse(href)
        if "duckduckgo.com" in (q.hostname or "") and q.path.startswith("/l/"):
            real = urllib.parse.parse_qs(q.query).get("uddg")
            if not real:
                continue
            href = real[0]
        if not href.startswith("http"):
            continue
        out.append({"title": _plain(m.group(2)), "url": href, "snippet": snippets[i] if i < len(snippets) else ""})
    if not out and re.search(r"(?i)anomaly|captcha|unusual traffic|are you a robot", html):
        raise WebError("DuckDuckGo asked for a human check and refused the automated search. Use 'Open in Google' to search in your own browser, or try again later")
    return out


def search_duckduckgo(q, n):
    status, raw, _ = _get(DDG + "?" + urllib.parse.urlencode({"q": q, "kl": "wt-wt"}))
    return parse_duckduckgo(raw.decode("utf-8", "replace"))[:n]


def parse_wikipedia(j):
    return [{"title": x.get("title", ""), "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote((x.get("title") or "").replace(" ", "_")), "snippet": _plain(x.get("snippet", ""))} for x in (j.get("query") or {}).get("search", [])]


def search_wikipedia(q, n):
    status, raw, _ = _get(WIKI + "?" + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": n, "utf8": 1}))
    return parse_wikipedia(json.loads(raw.decode("utf-8", "replace")))[:n]


def parse_google(j):
    if j.get("error"):
        raise WebError("Google answered: %s" % (j["error"].get("message") or "an error")[:160])
    return [{"title": x.get("title", ""), "url": x.get("link", ""), "snippet": _plain(x.get("snippet", ""))} for x in j.get("items", []) if x.get("link")]


def search_google(q, n, key, cx):
    if not (key and cx):
        raise WebError("a Google key and search engine id have not been stored")
    status, raw, _ = _get(GOOGLE + "?" + urllib.parse.urlencode({"key": key, "cx": cx, "q": q, "num": min(10, n)}))
    return parse_google(json.loads(raw.decode("utf-8", "replace")))[:n]


def parse_google_news(xml):
    """Headlines from a Google News RSS page. Each names its real publisher and the publisher's address, which is what is checked against the approved sources."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise WebError("Google News did not return a readable page.")
    out = []
    for it in root.iter("item"):
        g = lambda t: (it.find(t).text if it.find(t) is not None else "") or ""
        src = it.find("source"); sname = (src.text or "").strip() if src is not None else ""; surl = (src.get("url") or "") if src is not None else ""
        title = _plain(g("title")); title = title[:-len(sname) - 3].rstrip() if sname and title.endswith(" - " + sname) else title
        if title and g("link"):
            out.append({"title": title[:240], "url": g("link").strip(), "snippet": ("%s, %s" % (sname, g("pubDate")[:16].strip())).strip(", "), "source_url": surl, "source": sname, "published": g("pubDate").strip()[:40]})
    return out


def search_google_news(q, n):
    status, raw, _ = _get(GNEWS + "/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}))
    return parse_google_news(raw)[:n]


def browser_links(q):
    """Links that open the search in the person's own browser."""
    e = urllib.parse.quote_plus(q)
    return {"google": "https://www.google.com/search?q=" + e, "duckduckgo": "https://duckduckgo.com/?q=" + e, "bing": "https://www.bing.com/search?q=" + e}


def google_key(db):
    from . import mfa
    r = db.execute("SELECT value FROM settings WHERE key='ai_google_key'").fetchone()
    try:
        return mfa.unseal(r["value"]) if r else None
    except Exception:
        return None


def cached(db, key, hours, make):
    """A short-lived cache so a repeated question does not hit the sources again. Returns (payload, from_cache)."""
    r = db.execute("SELECT ts, payload FROM ai_web_cache WHERE key=?", (key,)).fetchone()
    if r and r["ts"] >= (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"):
        return json.loads(r["payload"]), True
    out = make()
    if out.get("results") or out.get("items"):
        db.execute("INSERT INTO ai_web_cache(key,ts,payload) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET ts=excluded.ts, payload=excluded.payload", (key, now(), json.dumps(out)))
        db.execute("DELETE FROM ai_web_cache WHERE ts < ?", ((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    return out, False


def search(db, q, limit=None, use_cache=False):
    """{results, errors, used, links}. Tries the providers in the order the System Administrator chose; one failing never stops the others."""
    if use_cache:
        import hashlib
        out, hit = cached(db, "s:" + hashlib.sha256((q.lower() + "|" + ",".join(ai_gov.settings(db)["web"]["providers"])).encode()).hexdigest()[:24], 3, lambda: search(db, q, limit))
        out["cached"] = hit; return out
    st = ai_gov.settings(db); n = limit or st["web"]["max_results"]; res, errs, used, seen = [], {}, [], set()
    for p in st["web"]["providers"]:
        try:
            if p == "duckduckgo":
                got = search_duckduckgo(q, n)
            elif p == "wikipedia":
                got = search_wikipedia(q, n)
            elif p == "google_cse":
                got = search_google(q, n, google_key(db), st["web"]["google_cx"])
            elif p == "google_news":
                got = search_google_news(q, n)
            else:
                continue
        except (WebError, ValueError) as e:
            errs[LABELS.get(p, p)] = str(e); continue
        used.append(LABELS.get(p, p))
        for x in got:
            if x["url"] in seen:
                continue
            seen.add(x["url"]); x["provider"] = LABELS.get(p, p); real = x.get("source_url") or x["url"]; x["domain"] = ai_gov.domain_of(real); x["trusted"] = ai_gov.trust_tier(st, real) == "trusted"; res.append(x)
    order = {id(x): i for i, x in enumerate(res)}
    res.sort(key=lambda x: (not x["trusted"], order[id(x)]))  # approved sources first, otherwise the search engine's own order
    return {"results": res[:n], "errors": errs, "used": used, "links": browser_links(q), "query": q}


# ------------------------------------------------------------------ reading a page
def _public(host):
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    for i in infos:
        ip = ipaddress.ip_address(i[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return bool(infos)


class _Check(urllib.request.HTTPRedirectHandler):
    def __init__(self, fn):
        self.fn = fn

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.fn(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(st, url, allow_unlisted=False):
    p = urllib.parse.urlparse(url or "")
    if p.scheme != "https" or not p.hostname:
        raise WebError("Only https addresses can be opened.")
    if p.username or p.password:
        raise WebError("Addresses with a user name or password are not allowed.")
    if ai_gov.trust_tier(st, url) != "trusted" and not allow_unlisted:
        raise WebError("%s is not one of the approved sources, so Sentinel will not read it itself. Open it in your own browser, or ask a System Administrator to add it in AI Governance." % p.hostname)
    if not _public(p.hostname):
        raise WebError("That address does not resolve to a public internet host.")


def page_date(raw):
    m = re.search(r'(?i)(?:article:published_time|datePublished|"date"|pubdate)["\s:=]+(?:content=)?"?(\d{4}-\d{2}-\d{2})', raw[:60000]) or re.search(r"(\d{4}-\d{2}-\d{2})", raw[:3000])
    return m.group(1) if m else None


def read_page(db, url, allow_unlisted=None):
    """{url, title, text, date, trusted, note}. Raises WebError with a plain reason."""
    st = ai_gov.settings(db); allow = st["web"]["read_unlisted"] if allow_unlisted is None else allow_unlisted
    check_url(st, url, allow)
    opener = urllib.request.build_opener(_Check(lambda u: check_url(st, u, allow)))
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,text/plain,application/pdf"}), timeout=20) as r:
            ctype = (r.headers.get("Content-Type") or "").lower(); raw = r.read(3_000_001)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise WebError("The page could not be opened (%s)." % (getattr(e, "reason", None) or e))
    if len(raw) > 3_000_000:
        raise WebError("The page is larger than 3 MB.")
    note = ""
    if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
        text, _ = ai_kb.pdf_text(raw); text = text if ai_kb.quality_of(text) == "good" else ""; title = url.rsplit("/", 1)[-1]
        note = "" if text else "The PDF text could not be read; download it and upload it in Documents."
        date = None
    else:
        body = raw.decode("utf-8", "replace"); text = ai_kb.html_text(body); date = page_date(body)
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", body[:30000]); title = _plain(m.group(1))[:160] if m else url
    red, _ = ai_gov.redact(text[:40000])
    return {"url": url, "title": title, "text": red, "date": date, "trusted": ai_gov.trust_tier(st, url) == "trusted", "note": note, "retrieved": now(), "flags": ai_gov.injection_flags(text)}


# ------------------------------------------------------------------ RSS and Atom
def parse_feed(xml):
    """[{title, url, summary, published}] from an RSS 2.0 or Atom feed."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise WebError("That address is not a readable RSS or Atom feed.")
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        d = {c.tag.split("}")[-1]: c for c in it}
        def first(*keys):  # an element with no children is 'false' in Python, so test for None explicitly
            for k in keys:
                if d.get(k) is not None:
                    return d[k]
            return None
        lk = first("link"); link = ((lk.get("href") or lk.text or "").strip()) if lk is not None else ""
        tt = first("title"); title = _plain((tt.text if tt is not None else "") or "")
        sm = first("description", "summary", "content"); summ = _plain((sm.text if sm is not None else "") or "")
        pb = first("pubDate", "published", "updated"); pub = (pb.text if pb is not None else "") or ""
        if title and link:
            out.append({"title": title[:240], "url": link, "summary": summ[:600], "published": pub.strip()[:40]})
    return out


def read_feed(db, url):
    st = ai_gov.settings(db); check_url(st, url, st["web"]["read_unlisted"])
    status, raw, _ = _get(url)
    return parse_feed(raw)


def headlines(db, n=14):
    """What is in the news now: Google News top stories plus the news feeds an administrator switched on for the Emerging Radar. Each headline names its publisher; approved publishers are marked."""
    def make():
        items, errs = [], {}
        try:
            status, raw, _ = _get(GNEWS + "?" + urllib.parse.urlencode({"hl": "en-US", "gl": "US", "ceid": "US:en"}))
            for x in parse_google_news(raw)[:20]:
                items.append(dict(x, via="Google News"))
        except WebError as e:
            errs["Google News"] = str(e)
        for f in db.execute("SELECT name, url FROM radar_feeds WHERE active=1"):
            try:
                for x in parse_feed(_get(f["url"])[1])[:12]:
                    items.append({"title": x["title"], "url": x["url"], "snippet": x["summary"][:160], "source": f["name"], "source_url": x["url"], "published": x["published"], "via": f["name"]})
            except WebError as e:
                errs[f["name"]] = str(e)
        return {"items": items, "errors": errs}
    out, hit = cached(db, "headlines", 1, make); st = ai_gov.settings(db)
    for x in out["items"]:
        x["domain"] = ai_gov.domain_of(x.get("source_url") or x["url"]); x["trusted"] = ai_gov.trust_tier(st, x.get("source_url") or x["url"]) == "trusted"
    out["cached"] = hit; out["items"] = out["items"][:n * 2]; return out
