"""A small WSGI micro-framework: requests, JSON responses, routing, static files and security headers."""
import http.cookies
import json
import mimetypes
import os
import re
import threading
import time
import traceback
import urllib.parse

from . import config, db as dbm

WRITE_LOCK = threading.RLock()
LOCK_WAIT = 25  # seconds a request waits for its turn to write before it answers "busy"
LOCK_INFO = {}  # who holds the write lock now, for the slow-task log and /api/health


import contextlib


@contextlib.contextmanager
def hold(name):
    """The write lock for background jobs, labelled so a slow one is easy to find."""
    with WRITE_LOCK:
        prev = dict(LOCK_INFO)
        LOCK_INFO.update(who=name, since=time.time())
        try:
            yield
        finally:
            LOCK_INFO.clear(); LOCK_INFO.update(prev)


def watchdog():
    """Writes a line to data/slow.log whenever one task keeps everyone else waiting for more than 10 seconds."""
    said = None
    while True:
        time.sleep(5)
        w, t = LOCK_INFO.get("who"), LOCK_INFO.get("since")
        if w and t and time.time() - t > 10 and said != (w, t):
            said = (w, t); _slow_log("%s has held the write lock for more than 10 seconds" % w)


def _slow_log(msg):
    try:
        from . import config
        import datetime
        with open(os.path.join(config.DATA, "slow.log"), "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass
MAX_BODY = 16 * 1024 * 1024


class HTTPError(Exception):
    def __init__(self, status, error, message="", **extra):
        super().__init__(message or error)
        self.status, self.error, self.message, self.extra = status, error, message or error, extra


class Request:
    def __init__(self, environ):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        raw = environ.get("PATH_INFO", "/")
        try:
            self.path = raw.encode("latin-1").decode("utf-8")
        except Exception:
            self.path = raw
        self.query = dict(urllib.parse.parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True))
        self.headers = {k[5:].replace("_", "-").title(): v for k, v in environ.items() if k.startswith("HTTP_")}
        self.cookies = {}
        if environ.get("HTTP_COOKIE"):
            try:
                c = http.cookies.SimpleCookie(); c.load(environ["HTTP_COOKIE"])
                self.cookies = {k: m.value for k, m in c.items()}
            except Exception:
                pass
        self.ip = environ.get("REMOTE_ADDR", "")
        self.ua = environ.get("HTTP_USER_AGENT", "")[:200]
        self.https = environ.get("wsgi.url_scheme") == "https" or environ.get("HTTP_X_FORWARDED_PROTO") == "https"
        self.host = environ.get("HTTP_HOST", "")
        self.params = {}
        self.db = None
        self.ctx = None
        self.set_cookies = []
        self._body = None

    @property
    def base_url(self):
        return ("https://" if self.https else "http://") + (self.host or "127.0.0.1:%d" % config.PORT)

    def body(self):
        if self._body is None:
            try:
                n = int(self.environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                n = 0
            if n > MAX_BODY:
                raise HTTPError(413, "too_large", "Request too large")
            self._body = self.environ["wsgi.input"].read(n) if n else b""
        return self._body

    def json(self):
        raw = self.body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise HTTPError(400, "bad_json", "The request body is not valid JSON")
        if not isinstance(data, dict):
            raise HTTPError(400, "bad_json", "A JSON object is expected")
        return data

    def set_cookie(self, name, value, max_age=None):
        parts = ["%s=%s" % (name, value), "Path=/", "HttpOnly", "SameSite=Strict"]
        if max_age is not None:
            parts.append("Max-Age=%d" % max_age)
        if self.https:
            parts.append("Secure")
        self.set_cookies.append("; ".join(parts))


class Response:
    def __init__(self, body=b"", status=200, ctype="application/json; charset=utf-8", headers=None):
        self.status, self.body, self.ctype, self.headers = status, body, ctype, headers or []


def jr(data, status=200):
    return Response(json.dumps(data, ensure_ascii=False).encode("utf-8"), status)


REASONS = {200: "OK", 201: "Created", 204: "No Content", 301: "Moved Permanently", 302: "Found", 304: "Not Modified", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
           404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large", 423: "Locked", 429: "Too Many Requests", 500: "Internal Server Error"}


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, handler):
        def conv(m):
            return ("(?P<%s>\\d+)" if m.group(1) else "(?P<%s>[^/]+)") % m.group(2)
        rx = re.sub(r"<(int:)?(\w+)>", conv, pattern)
        self.routes.append((method, re.compile("^" + rx + "$"), handler))

    def route(self, method, pattern):
        def deco(fn):
            self.add(method, pattern, fn)
            return fn
        return deco

    def match(self, method, path):
        allowed = False
        for m, rx, h in self.routes:
            mo = rx.match(path)
            if mo:
                if m == method or (m == "GET" and method == "HEAD"):
                    return h, mo.groupdict()
                allowed = True
        if allowed:
            raise HTTPError(405, "method_not_allowed", "Method not allowed")
        return None, {}


SEC_HEADERS = [
    ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
    ("Cache-Control", "no-store"),
]
STATIC_ROOT = os.path.realpath(config.STATIC)


def static_response(rel):
    full = os.path.realpath(os.path.join(STATIC_ROOT, rel.lstrip("/\\")))
    if not (full == STATIC_ROOT or full.startswith(STATIC_ROOT + os.sep)) or not os.path.isfile(full):
        raise HTTPError(404, "not_found", "Not found")
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
        ctype += "; charset=utf-8"
    with open(full, "rb") as f:
        data = f.read()
    cache = "public, max-age=86400" if full.lower().endswith((".png", ".jpg", ".jpeg", ".ico", ".svg")) else "no-cache"
    return Response(data, 200, ctype, [("Cache-Control", cache)])


class App:
    def __init__(self, router):
        self.router = router

    def __call__(self, environ, start_response):
        req = Request(environ)
        res = None
        try:
            res = self.dispatch(req)
        except HTTPError as e:
            res = jr(dict({"error": e.error, "message": e.message}, **e.extra), e.status)
        except Exception:
            traceback.print_exc()
            res = jr({"error": "server_error", "message": "Something went wrong. The error was logged."}, 500)
        finally:
            if req.db is not None:
                try:
                    req.db.close()
                except Exception:
                    pass
        headers = [("Content-Type", res.ctype), ("Content-Length", str(len(res.body)))] + SEC_HEADERS
        if req.ctx is not None:
            res.headers = list(res.headers) + [("X-Sentinel-User", req.ctx.user["username"])]  # lets each browser tab notice a change of signed-in user
        names = {h[0] for h in res.headers}
        headers = [h for h in headers if h[0] not in names] + res.headers + [("Set-Cookie", c) for c in req.set_cookies]
        start_response("%d %s" % (res.status, REASONS.get(res.status, "OK")), headers)
        return [b"" if req.method == "HEAD" else res.body]

    def dispatch(self, req):
        path = req.path
        if req.method in ("POST", "PUT", "DELETE", "PATCH") and path.startswith("/api/") and not path.startswith("/api/inbound/"):  # inbound feeds use an API key, never the browser session this rule protects
            if req.headers.get("X-Sentinel") != "1":
                raise HTTPError(403, "csrf", "Missing request header")
            origin = req.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).netloc != req.host:
                raise HTTPError(403, "csrf", "Cross-site request refused")
        handler, params = self.router.match(req.method, path)
        if handler is None:
            if path.startswith("/api/"):
                raise HTTPError(404, "not_found", "Unknown API endpoint")
            raise HTTPError(404, "not_found", "Page not found")
        req.params = params
        req.db = dbm.connect()
        if req.method in ("GET", "HEAD") or getattr(handler, "nolock", False):  # nolock: the handler waits on the internet, so it takes the write lock itself, briefly
            out = handler(req)
            req.db.commit()
        else:
            if not WRITE_LOCK.acquire(timeout=LOCK_WAIT):  # never leave a person staring at "Please wait" for ever
                holder = LOCK_INFO.get("who", "another task")
                _slow_log("write lock busy for %ds; held by %s" % (LOCK_WAIT, holder))
                raise HTTPError(503, "busy", "Sentinel is finishing another task. Please try again in a moment.")
            LOCK_INFO.update(who="%s %s" % (req.method, path), since=time.time())
            try:
                try:
                    out = handler(req)
                    req.db.commit()
                except BaseException:
                    req.db.rollback()
                    raise
            finally:
                LOCK_INFO.clear()
                WRITE_LOCK.release()
        if isinstance(out, Response):
            return out
        return jr(out)
