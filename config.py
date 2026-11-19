"""Sentinel configuration. Everything here can be overridden with environment variables."""
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("SENTINEL_DATA") or os.path.join(BASE, "data")
STATIC = os.path.join(BASE, "static")
DB_PATH = os.path.join(DATA, "sentinel.db")
HOST = os.environ.get("SENTINEL_HOST", "127.0.0.1")
PORT = int(os.environ.get("SENTINEL_PORT", "8000"))
VERSION = "0.22.1"
BUILD = "Step 23: Power BI-style KRI pages, traffic lights, edit and delete of KRI figures"
COOKIE = "sentinel_session"
TZ_HOURS = 2  # Africa/Harare (CAT, no daylight saving)

# Policy defaults (BRD section 5). Editable at run time in Access Management > Sign-in policy.
DEFAULT_POLICY = {
    "password_max_age_days": 90,      # password changes every 90 days
    "password_warn_days": 14,         # warning shown from 14 days before expiry
    "password_min_length": 12,
    "password_history": 5,            # cannot reuse the last 5 passwords
    "max_failed_attempts": 3,         # account locks after 3 failed attempts in a row
    "idle_minutes": 30,               # sign out after 30 minutes idle
    "session_hours": 12,              # absolute session life
    "max_sessions": 2,                # concurrent sessions per user
    "temp_password_hours": 48,        # temporary passwords valid 48 hours
    "reset_link_minutes": 30,         # e-mail reset link valid 30 minutes
    "recycle_days": 90,               # deleted items restorable for 90 days
    "mfa_required_roles": [],         # roles that must use a second factor at sign-in (set under Administration > Sign-in security)
    "self_service_reset": True,       # users may reset a forgotten or locked password by e-mail link
    "unknown_user_window_minutes": 15,
    "ip_fail_limit": 40,              # failures per address per 10 minutes before throttling
}
POLICY_LIMITS = {
    "password_max_age_days": (30, 365), "password_warn_days": (1, 60), "password_min_length": (8, 64), "password_history": (0, 24),
    "max_failed_attempts": (3, 10), "idle_minutes": (5, 240), "session_hours": (1, 72), "max_sessions": (1, 5),
    "temp_password_hours": (1, 168), "reset_link_minutes": (5, 240), "recycle_days": (7, 365),
}
