"""Password hashing (scrypt), the password policy and token helpers. Standard library only."""
import base64
import hashlib
import hmac
import re
import secrets

N, R, P = 2 ** 14, 8, 1


def _b(x):
    return base64.b64encode(x).decode()


HAS_SCRYPT = hasattr(hashlib, "scrypt")
PBKDF2_ROUNDS = 600000


def hash_password(pw):
    salt = secrets.token_bytes(16)
    if not HAS_SCRYPT:
        h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ROUNDS, 32)
        return "pbkdf2$%d$%s$%s" % (PBKDF2_ROUNDS, _b(salt), _b(h))
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=N, r=R, p=P, dklen=32, maxmem=64 * 1024 * 1024)
    return "scrypt$%d$%d$%d$%s$%s" % (N, R, P, _b(salt), _b(h))


def verify_password(pw, stored):
    try:
        if stored.startswith("pbkdf2$"):
            _, rounds, salt, h = stored.split("$")
            calc = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), base64.b64decode(salt), int(rounds), 32)
            return hmac.compare_digest(calc, base64.b64decode(h))
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt" or not HAS_SCRYPT:
            return False
        calc = hashlib.scrypt(pw.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing-only")


def new_token():
    return secrets.token_urlsafe(32)


def hash_token(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


SYMBOLS = r"""!@#$%&*+-=?_.,:;()[]{}<>^~/\|'"`"""


def check_password(pw, username, pol, history=()):
    """Return a list of policy problems (empty list means the password is acceptable)."""
    errs = []
    if len(pw) < pol["password_min_length"]:
        errs.append("at least %d characters" % pol["password_min_length"])
    if not re.search(r"[a-z]", pw):
        errs.append("a lower-case letter")
    if not re.search(r"[A-Z]", pw):
        errs.append("an upper-case letter")
    if not re.search(r"[0-9]", pw):
        errs.append("a number")
    if not re.search(r"[^A-Za-z0-9]", pw):
        errs.append("a symbol")
    if username and len(username) >= 3 and username.lower() in pw.lower():
        errs.append("must not contain the username")
    for h in history:
        if verify_password(pw, h):
            errs.append("must not be one of your last %d passwords" % pol["password_history"])
            break
    return errs


def temp_password():
    """A 14-character password that meets the default policy (no look-alike characters)."""
    up, lo, dg, sy = "ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!@#$%*+-=?"
    chars = [secrets.choice(up), secrets.choice(lo), secrets.choice(dg), secrets.choice(sy)]
    pool = up + lo + dg + sy
    chars += [secrets.choice(pool) for _ in range(10)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
