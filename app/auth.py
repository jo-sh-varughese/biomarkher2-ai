"""Accounts, sessions, roles and the security audit trail for the portal.

The portal used to have a sign-in screen that authenticated nothing: a demo
account compiled into the bundle and "accounts" kept in one browser's
localStorage. This module replaces that whenever the Python backend is
running. The browser-only demo sign-in survives only in the static Netlify
build, which has no server to authenticate against.

Standard library only, like the rest of app/:

- sqlite3 holds users, sessions, one-time password links, settings and the
  audit trail in one file (artifacts/biomark.db by default: gitignored, and
  inside the directory docker-compose already mounts read-write).
- Passwords are hashed with scrypt, salted per user, with the parameters
  stored beside each hash so they can be raised later without invalidating
  existing accounts. A password is never stored, logged or sent back.
- A session cookie carries a random 256-bit token. The database keeps only
  its SHA-256, so a copy of the database file cannot be replayed as a login.
  Every state-changing request must also carry the session's CSRF token.
- Failed sign-ins lock an account after a configurable number of attempts
  and are throttled per IP address. Unknown email addresses are throttled
  exactly like real ones, so the lockout message cannot be used to find out
  which addresses have accounts.

Roles are deliberately few and follow the clinical workflow:

    admin        everything a pathologist can do, plus the admin console
    pathologist  analyse fields, record assessments, mark regions
    viewer       analyse fields and download reports; never records a score
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import math
import re
import secrets
import sqlite3
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

ROLES = ("admin", "pathologist", "viewer")
STATUSES = ("active", "invited", "pending", "disabled")

# What each role may do. The HTTP handler checks this on every route. The
# portal reads the same list (via /api/auth/me) to hide controls a role
# cannot use, but hiding is a courtesy: the server check is the control.
PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"view", "analyze", "report", "review", "annotate", "admin"}),
    "pathologist": frozenset({"view", "analyze", "report", "review", "annotate"}),
    "viewer": frozenset({"view", "analyze", "report"}),
}

AVATAR_ACCENTS = ("violet", "teal", "amber", "rose", "sky", "lime")

DEFAULT_SETTINGS: dict[str, object] = {
    "site_name": "BioMarkHER2",
    "announcement": "",
    "session_idle_minutes": 60,
    "session_max_hours": 12,
    "allow_remember_me": True,
    "remember_me_days": 7,
    "password_min_length": 10,
    "lockout_threshold": 5,
    "lockout_minutes": 15,
    "allow_access_requests": True,
}

# (type, minimum, maximum) -- for strings the bounds are on length.
_SETTING_RULES: dict[str, tuple[type, int | None, int | None]] = {
    "site_name": (str, 1, 60),
    "announcement": (str, 0, 280),
    "session_idle_minutes": (int, 5, 24 * 60),
    "session_max_hours": (int, 1, 24 * 30),
    "allow_remember_me": (bool, None, None),
    "remember_me_days": (int, 1, 90),
    "password_min_length": (int, 8, 64),
    "lockout_threshold": (int, 3, 20),
    "lockout_minutes": (int, 1, 24 * 60),
    "allow_access_requests": (bool, None, None),
}

# Which audit actions each filter in the admin console's log shows.
AUDIT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "signin": (
        "auth.login", "auth.login_failed", "auth.login_blocked", "auth.locked",
        "auth.logout", "auth.session_revoked",
    ),
    "accounts": (
        "setup.completed", "user.created", "user.updated", "user.profile_updated",
        "user.approved", "user.deleted", "access.requested", "access.rejected",
        "access.duplicate",
    ),
    "security": (
        "auth.password_changed", "auth.password_reset", "user.password_set",
        "user.link_created", "user.unlocked", "user.sessions_revoked", "auth.locked",
    ),
    "settings": ("settings.updated",),
    "data": ("data.exported",),
}

PASSWORD_MAX_LENGTH = 256
INVITE_HOURS = 72
RESET_HOURS = 24
# A session's last-seen time is written at most this often, so an active
# page polling the API does not turn every request into a database write.
SESSION_TOUCH_SECONDS = 60
IP_FAILURE_LIMIT = 30
IP_FAILURE_WINDOW = timedelta(minutes=15)
REQUEST_LIMIT = 5
REQUEST_WINDOW = timedelta(hours=1)

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
# Marks an account that has no password yet (an invitation not yet
# accepted). It can never match: verify_password only accepts scrypt hashes.
UNUSABLE_PASSWORD = "!"

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_COMMON_PASSWORDS = frozenset("""
password password1 password12 password123 passw0rd p@ssw0rd 12345678 123456789
1234567890 qwerty123 qwertyuiop 1q2w3e4r5t iloveyou admin123 administrator
welcome1 welcome123 letmein letmein123 changeme changeme123 biomark
biomarkher2 her2demo her2her2 pathology pathologist hospital hospital123
abc12345 abcd1234 11111111 00000000 trustno1 sunshine monkey123 football123
""".split())


class AuthError(Exception):
    """A refusal to show the person: a stable `code` the portal translates,
    the HTTP status the handler sends, and any values the message needs."""

    def __init__(self, code: str, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra


# ------------------------------------------------------------- passwords --

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class _Throttle:
    """Timestamps of recent events per key, in memory. Used for failed
    sign-ins per IP, failed sign-ins for email addresses that have no
    account, and access requests per IP. It resets when the server
    restarts, which is acceptable for slowing down guessing."""

    def __init__(self):
        self._hits: dict[tuple, deque] = {}
        self._lock = threading.Lock()

    def hit(self, key: tuple, now: datetime) -> None:
        with self._lock:
            events = self._hits.setdefault(key, deque(maxlen=200))
            events.append(now)
            if len(self._hits) > 10_000:
                cutoff = now - timedelta(days=1)
                for stale in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
                    del self._hits[stale]

    def count(self, key: tuple, now: datetime, window: timedelta) -> int:
        with self._lock:
            events = self._hits.get(key)
            if not events:
                return 0
            cutoff = now - window
            while events and events[0] < cutoff:
                events.popleft()
            return len(events)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id                   TEXT PRIMARY KEY,
    email                TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name                 TEXT NOT NULL,
    role                 TEXT NOT NULL,
    status               TEXT NOT NULL,
    registration         TEXT NOT NULL DEFAULT '',
    title                TEXT NOT NULL DEFAULT '',
    accent               TEXT NOT NULL DEFAULT 'violet',
    password_hash        TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    request_note         TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    created_by           TEXT,
    updated_at           TEXT NOT NULL,
    last_login_at        TEXT,
    last_login_ip        TEXT,
    password_changed_at  TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id_hash      TEXT PRIMARY KEY,
    public_id    TEXT NOT NULL UNIQUE,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf         TEXT NOT NULL,
    remember     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    ip           TEXT,
    user_agent   TEXT
);
CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS links (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_by TEXT,
    used_at    TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    action       TEXT NOT NULL,
    actor_id     TEXT,
    actor_email  TEXT,
    actor_name   TEXT,
    target_id    TEXT,
    target_email TEXT,
    ip           TEXT,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS audit_by_action ON audit(action);
"""


class AuthStore:
    """The account database. One connection, guarded by a lock: at the
    scale of one department's reviewers that is simpler than a pool and
    never the bottleneck -- the model inference beside it is."""

    def __init__(self, path: str | Path, *, clock: Callable[[], datetime] | None = None):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', '1')")
        self._throttle = _Throttle()
        self._setup_token: str | None = None
        self._settings_cache: dict | None = None
        # Checked against when an email has no account, so a sign-in for an
        # unknown address costs the same time as one for a real account.
        self._dummy_hash = hash_password(secrets.token_urlsafe(18))

    # ------------------------------------------------------------ plumbing
    def now(self) -> datetime:
        return self._clock()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def _row(self, user_id: str) -> sqlite3.Row:
        rows = self._rows("SELECT * FROM users WHERE id = ?", (str(user_id),))
        if not rows:
            raise AuthError("not_found", "No such user.", 404)
        return rows[0]

    def _row_by_email(self, email: str) -> sqlite3.Row | None:
        rows = self._rows("SELECT * FROM users WHERE email = ?", (email,))
        return rows[0] if rows else None

    def _audit(self, db, action: str, *, actor: dict | None = None,
               target: tuple[str | None, str | None] | None = None,
               ip: str | None = None, **detail) -> None:
        target_id, target_email = target or (None, None)
        db.execute(
            "INSERT INTO audit (at, action, actor_id, actor_email, actor_name, target_id,"
            " target_email, ip, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _iso(self.now()), action,
                actor["id"] if actor else None,
                actor["email"] if actor else None,
                actor["name"] if actor else None,
                target_id, target_email, ip,
                json.dumps(detail, default=str) if detail else None,
            ),
        )

    def audit(self, action: str, **kwargs) -> None:
        with self._tx() as db:
            self._audit(db, action, **kwargs)

    def _public(self, row: sqlite3.Row) -> dict:
        locked_until = _parse(row["locked_until"])
        locked = bool(locked_until and locked_until > self.now())
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "role": row["role"],
            "status": row["status"],
            "registration": row["registration"],
            "title": row["title"],
            "accent": row["accent"],
            "must_change_password": bool(row["must_change_password"]),
            "has_password": row["password_hash"] != UNUSABLE_PASSWORD,
            "locked": locked,
            "locked_until": row["locked_until"] if locked else None,
            "failed_attempts": row["failed_attempts"] if not locked_until or locked else 0,
            "request_note": row["request_note"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
            "last_login_ip": row["last_login_ip"],
            "password_changed_at": row["password_changed_at"],
        }

    def _active_admins(self, db) -> int:
        return db.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()[0]

    # ----------------------------------------------------------- validation
    @staticmethod
    def _clean_email(email) -> str:
        email = str(email or "").strip().lower()
        if len(email) > 254 or not _EMAIL_RE.match(email):
            raise AuthError("email_invalid", "Enter a valid email address.")
        return email

    @staticmethod
    def _clean_name(name) -> str:
        name = " ".join(str(name or "").split())
        if not 2 <= len(name) <= 80:
            raise AuthError("name_invalid", "Enter a name between 2 and 80 characters.")
        return name

    @staticmethod
    def _clean_role(role) -> str:
        if role not in ROLES:
            raise AuthError("role_invalid", f"Role must be one of: {', '.join(ROLES)}.")
        return role

    @staticmethod
    def _clean_text(value, limit: int, field: str) -> str:
        value = " ".join(str(value or "").split())
        if len(value) > limit:
            raise AuthError(
                "field_too_long", f"{field.capitalize()} is too long (at most {limit} characters).",
                field=field, max=limit,
            )
        return value

    @staticmethod
    def _clean_accent(accent) -> str:
        if accent not in AVATAR_ACCENTS:
            raise AuthError("field_invalid", "Unknown avatar colour.", field="accent")
        return accent

    def check_password(self, password, *, email: str = "") -> None:
        """Raises unless `password` meets the policy. Length is the rule that
        matters (NIST SP 800-63B); composition rules are deliberately absent,
        and the rest only rejects passwords that are guessable in context."""
        if not isinstance(password, str):
            password = ""
        minimum = int(self.settings()["password_min_length"])
        if len(password) < minimum:
            raise AuthError("password_too_short", f"Use at least {minimum} characters.", min=minimum)
        if len(password) > PASSWORD_MAX_LENGTH:
            raise AuthError(
                "password_too_long", f"Use at most {PASSWORD_MAX_LENGTH} characters.",
                max=PASSWORD_MAX_LENGTH,
            )
        lowered = password.lower()
        if lowered in _COMMON_PASSWORDS or lowered.rstrip("0123456789!.@#") in _COMMON_PASSWORDS:
            raise AuthError("password_common", "That password is too common. Choose one that is harder to guess.")
        if email and lowered in {email.lower(), email.split("@", 1)[0].lower()}:
            raise AuthError("password_like_email", "The password can't be your email address.")
        if len(set(password)) < 4:
            raise AuthError("password_repetitive", "The password repeats too few different characters.")

    # ------------------------------------------------------------- settings
    def settings(self) -> dict:
        with self._lock:
            if self._settings_cache is None:
                merged = dict(DEFAULT_SETTINGS)
                for row in self._db.execute("SELECT key, value FROM settings").fetchall():
                    if row["key"] in DEFAULT_SETTINGS:
                        try:
                            merged[row["key"]] = json.loads(row["value"])
                        except json.JSONDecodeError:
                            pass
                self._settings_cache = merged
            return dict(self._settings_cache)

    def update_settings(self, changes, *, actor: dict | None, ip: str | None = None) -> dict:
        if not isinstance(changes, dict) or not changes:
            raise AuthError("nothing_to_change", "No settings were sent.")
        current = self.settings()
        clean: dict[str, object] = {}
        for key, value in changes.items():
            if key not in _SETTING_RULES:
                raise AuthError("setting_unknown", f"Unknown setting: {key}.", field=key)
            kind, low, high = _SETTING_RULES[key]
            if kind is bool:
                if not isinstance(value, bool):
                    raise AuthError("setting_invalid", f"{key} must be true or false.", field=key)
            elif kind is int:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
                    raise AuthError("setting_invalid", f"{key} must be a whole number.", field=key)
                value = int(value)
                if not low <= value <= high:
                    raise AuthError(
                        "setting_range", f"{key} must be between {low} and {high}.",
                        field=key, min=low, max=high,
                    )
            else:
                value = " ".join(str(value if value is not None else "").split())
                if not low <= len(value) <= high:
                    raise AuthError(
                        "setting_range", f"{key} must be {low} to {high} characters.",
                        field=key, min=low, max=high,
                    )
            if current.get(key) != value:
                clean[key] = value
        if not clean:
            return current
        with self._tx() as db:
            for key, value in clean.items():
                db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value)),
                )
            self._audit(
                db, "settings.updated", actor=actor, ip=ip,
                changes={k: {"from": current.get(k), "to": v} for k, v in clean.items()},
            )
            self._settings_cache = None
        return self.settings()

    # ---------------------------------------------------------------- setup
    def needs_setup(self) -> bool:
        return not self._rows(
            "SELECT 1 FROM users WHERE role = 'admin' AND status = 'active' LIMIT 1"
        )

    def setup_token(self) -> str | None:
        """The one-time token that authorises creating the first
        administrator, or None once one exists. It lives only in this
        process's memory and is printed to the console that started the
        server, so creating the first account needs access to that console,
        not merely a network path to the server."""
        with self._lock:
            if not self.needs_setup():
                self._setup_token = None
            elif self._setup_token is None:
                self._setup_token = secrets.token_urlsafe(24)
            return self._setup_token

    def complete_setup(self, *, token, name, email, password, ip=None, user_agent=None):
        with self._lock:
            if not self.needs_setup():
                raise AuthError("setup_done", "An administrator account already exists. Sign in instead.", 409)
            expected = self._setup_token
            if not expected or not isinstance(token, str) or not hmac.compare_digest(
                token.encode("utf-8"), expected.encode("utf-8")
            ):
                raise AuthError(
                    "setup_token_invalid",
                    "This setup link is not valid. Use the link the server printed when it started.",
                    403,
                )
            user = self.create_user(
                email=email, name=name, role="admin", password=password,
                actor=None, ip=ip, _action="setup.completed",
            )
            self._setup_token = None
        return self._start_session(user["id"], remember=False, ip=ip, user_agent=user_agent)

    # ---------------------------------------------------------------- users
    def create_user(self, *, email, name, role, password=None, status="active",
                    must_change_password=False, registration="", title="",
                    request_note="", actor: dict | None = None, ip=None,
                    _action="user.created") -> dict:
        email = self._clean_email(email)
        name = self._clean_name(name)
        role = self._clean_role(role)
        registration = self._clean_text(registration, 40, "registration").upper()
        title = self._clean_text(title, 80, "title")
        request_note = self._clean_text(request_note, 500, "note")
        if status not in STATUSES:
            raise AuthError("status_invalid", "Unknown account status.")
        if password is None:
            password_hash = UNUSABLE_PASSWORD
        else:
            self.check_password(password, email=email)
            password_hash = hash_password(password)
        now = _iso(self.now())
        user_id = "usr_" + secrets.token_hex(8)
        try:
            with self._tx() as db:
                if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                    raise AuthError("email_taken", "An account with this email already exists.", 409)
                db.execute(
                    "INSERT INTO users (id, email, name, role, status, registration, title,"
                    " password_hash, must_change_password, request_note, created_at, created_by,"
                    " updated_at, password_changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id, email, name, role, status, registration, title, password_hash,
                        int(bool(must_change_password) and password is not None), request_note,
                        now, actor["id"] if actor else None, now,
                        now if password is not None else None,
                    ),
                )
                self._audit(
                    db, _action, actor=actor, target=(user_id, email), ip=ip,
                    role=role, status=status,
                )
        except sqlite3.IntegrityError:
            raise AuthError("email_taken", "An account with this email already exists.", 409) from None
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict:
        return self._public(self._row(user_id))

    def find_user(self, email: str) -> dict | None:
        row = self._row_by_email(str(email or "").strip().lower())
        return self._public(row) if row else None

    def list_users(self, *, q: str = "", role: str = "", status: str = "") -> list[dict]:
        sql, params, where = "SELECT * FROM users", [], []
        if q:
            needle = "%" + str(q).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(email LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\'"
                         " OR registration LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
            params += [needle] * 4
        if role:
            where.append("role = ?")
            params.append(role)
        if status and status != "locked":
            where.append("status = ?")
            params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY name COLLATE NOCASE"
        users = [self._public(row) for row in self._rows(sql, tuple(params))]
        if status == "locked":
            users = [u for u in users if u["locked"]]
        return users

    def update_user(self, user_id: str, changes, *, actor: dict | None, ip=None) -> dict:
        row = self._row(user_id)
        if not isinstance(changes, dict) or not changes:
            raise AuthError("nothing_to_change", "No changes were sent.")
        allowed = {"name", "email", "role", "status", "registration", "title", "accent"}
        unknown = set(changes) - allowed
        if unknown:
            raise AuthError("field_unknown", f"These fields can't be changed here: {', '.join(sorted(unknown))}.")
        clean: dict[str, object] = {}
        if "name" in changes:
            clean["name"] = self._clean_name(changes["name"])
        if "email" in changes:
            clean["email"] = self._clean_email(changes["email"])
        if "role" in changes:
            clean["role"] = self._clean_role(changes["role"])
        if "status" in changes:
            status = changes["status"]
            if status not in ("active", "disabled"):
                raise AuthError("status_invalid", "An account can only be set to active or disabled.")
            if status == "active" and row["status"] == "pending":
                raise AuthError("use_approve", "Approve the access request instead.", 409)
            if status == "active" and row["status"] == "invited":
                raise AuthError(
                    "status_invalid",
                    "An invited account becomes active when its owner sets a password.",
                    409,
                )
            clean["status"] = status
        if "registration" in changes:
            clean["registration"] = self._clean_text(changes["registration"], 40, "registration").upper()
        if "title" in changes:
            clean["title"] = self._clean_text(changes["title"], 80, "title")
        if "accent" in changes:
            clean["accent"] = self._clean_accent(changes["accent"])
        diff = {k: v for k, v in clean.items() if row[k] != v}
        if not diff:
            return self._public(row)
        if actor and actor["id"] == user_id and ({"role", "status"} & set(diff)):
            raise AuthError(
                "self_change",
                "You can't change your own role or disable your own account. Ask another administrator.",
                409,
            )
        was_admin = row["role"] == "admin" and row["status"] == "active"
        stays_admin = diff.get("role", row["role"]) == "admin" and diff.get("status", row["status"]) == "active"
        with self._tx() as db:
            if was_admin and not stays_admin and self._active_admins(db) <= 1:
                raise AuthError(
                    "last_admin",
                    "This is the last active administrator. Make someone else an administrator first.",
                    409,
                )
            if "email" in diff and db.execute(
                "SELECT 1 FROM users WHERE email = ? AND id != ?", (diff["email"], user_id)
            ).fetchone():
                raise AuthError("email_taken", "An account with this email already exists.", 409)
            assignments = ", ".join(f"{column} = ?" for column in diff)
            db.execute(
                f"UPDATE users SET {assignments}, updated_at = ? WHERE id = ?",
                (*diff.values(), _iso(self.now()), user_id),
            )
            if diff.get("status") == "disabled":
                db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self._audit(
                db, "user.updated", actor=actor, target=(user_id, diff.get("email", row["email"])),
                ip=ip, changes={k: {"from": row[k], "to": v} for k, v in diff.items()},
            )
        return self.get_user(user_id)

    def update_profile(self, user_id: str, changes, *, ip=None) -> dict:
        """What a person may change about their own account: how they are
        named on a sign-off, not what they are allowed to do."""
        if not isinstance(changes, dict) or not changes:
            raise AuthError("nothing_to_change", "No changes were sent.")
        unknown = set(changes) - {"name", "registration", "title", "accent"}
        if unknown:
            raise AuthError("field_unknown", f"These fields can't be changed here: {', '.join(sorted(unknown))}.")
        row = self._row(user_id)
        clean: dict[str, object] = {}
        if "name" in changes:
            clean["name"] = self._clean_name(changes["name"])
        if "registration" in changes:
            clean["registration"] = self._clean_text(changes["registration"], 40, "registration").upper()
        if "title" in changes:
            clean["title"] = self._clean_text(changes["title"], 80, "title")
        if "accent" in changes:
            clean["accent"] = self._clean_accent(changes["accent"])
        diff = {k: v for k, v in clean.items() if row[k] != v}
        if not diff:
            return self._public(row)
        with self._tx() as db:
            assignments = ", ".join(f"{column} = ?" for column in diff)
            db.execute(
                f"UPDATE users SET {assignments}, updated_at = ? WHERE id = ?",
                (*diff.values(), _iso(self.now()), user_id),
            )
            self._audit(
                db, "user.profile_updated", actor=self._public(row), target=(user_id, row["email"]),
                ip=ip, changes={k: {"from": row[k], "to": v} for k, v in diff.items()},
            )
        return self.get_user(user_id)

    def approve_user(self, user_id: str, *, role, actor: dict | None, ip=None) -> dict:
        row = self._row(user_id)
        if row["status"] != "pending":
            raise AuthError("not_pending", "This account is not waiting for approval.", 409)
        role = self._clean_role(role)
        with self._tx() as db:
            db.execute(
                "UPDATE users SET status = 'active', role = ?, updated_at = ? WHERE id = ?",
                (role, _iso(self.now()), user_id),
            )
            self._audit(db, "user.approved", actor=actor, target=(user_id, row["email"]), ip=ip, role=role)
        return self.get_user(user_id)

    def delete_user(self, user_id: str, *, actor: dict | None, ip=None) -> None:
        row = self._row(user_id)
        if actor and actor["id"] == user_id:
            raise AuthError("self_delete", "You can't delete your own account.", 409)
        with self._tx() as db:
            if row["role"] == "admin" and row["status"] == "active" and self._active_admins(db) <= 1:
                raise AuthError(
                    "last_admin",
                    "This is the last active administrator. Make someone else an administrator first.",
                    409,
                )
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self._audit(
                db, "access.rejected" if row["status"] == "pending" else "user.deleted",
                actor=actor, target=(user_id, row["email"]), ip=ip, name=row["name"], role=row["role"],
            )

    def unlock_user(self, user_id: str, *, actor: dict | None, ip=None) -> dict:
        row = self._row(user_id)
        with self._tx() as db:
            db.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL, updated_at = ? WHERE id = ?",
                (_iso(self.now()), user_id),
            )
            self._audit(db, "user.unlocked", actor=actor, target=(user_id, row["email"]), ip=ip)
        return self.get_user(user_id)

    # ------------------------------------------------------------ passwords
    def admin_set_password(self, user_id: str, password, *, must_change: bool = True,
                           actor: dict | None, ip=None) -> dict:
        row = self._row(user_id)
        if actor and actor["id"] == user_id:
            raise AuthError("use_profile", "Change your own password from your profile.", 409)
        if row["status"] == "pending":
            raise AuthError("use_approve", "Approve the access request first.", 409)
        self.check_password(password, email=row["email"])
        digest = hash_password(password)
        now = _iso(self.now())
        with self._tx() as db:
            db.execute(
                "UPDATE users SET password_hash = ?, must_change_password = ?, failed_attempts = 0,"
                " locked_until = NULL, password_changed_at = ?, updated_at = ?,"
                " status = CASE WHEN status = 'invited' THEN 'active' ELSE status END WHERE id = ?",
                (digest, int(bool(must_change)), now, now, user_id),
            )
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            db.execute("UPDATE links SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (now, user_id))
            self._audit(
                db, "user.password_set", actor=actor, target=(user_id, row["email"]), ip=ip,
                must_change=bool(must_change),
            )
        return self.get_user(user_id)

    def change_password(self, user_id: str, *, current, new, keep_session: str | None = None,
                        ip=None) -> dict:
        row = self._row(user_id)
        if not verify_password(str(current or ""), row["password_hash"]):
            raise AuthError("wrong_current_password", "Your current password is incorrect.")
        if isinstance(new, str) and verify_password(new, row["password_hash"]):
            raise AuthError("password_reused", "Choose a password different from your current one.")
        self.check_password(new, email=row["email"])
        digest = hash_password(new)
        now = _iso(self.now())
        with self._tx() as db:
            db.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0,"
                " password_changed_at = ?, updated_at = ? WHERE id = ?",
                (digest, now, now, user_id),
            )
            # Every other session ends: a password change is what someone does
            # when they think a password has leaked.
            db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND id_hash != ?", (user_id, keep_session or "")
            )
            self._audit(
                db, "auth.password_changed", actor=self._public(row), target=(user_id, row["email"]), ip=ip
            )
        return self.get_user(user_id)

    # ---------------------------------------------------- one-time links
    def create_link(self, user_id: str, *, kind: str, actor: dict | None, ip=None) -> tuple[str, str]:
        """A single-use link that lets the account's owner choose their own
        password: an invitation for a new account, or a reset for an
        existing one. There is no email server, so the administrator copies
        the link and passes it on; the link, not the password, is what
        travels."""
        if kind not in ("invite", "reset"):
            raise AuthError("link_invalid", "Unknown link type.")
        row = self._row(user_id)
        if row["status"] in ("pending", "disabled"):
            raise AuthError("link_not_allowed", "Approve or re-enable this account first.", 409)
        token = secrets.token_urlsafe(32)
        now = self.now()
        expires = now + timedelta(hours=INVITE_HOURS if kind == "invite" else RESET_HOURS)
        with self._tx() as db:
            db.execute(
                "UPDATE links SET used_at = ? WHERE user_id = ? AND used_at IS NULL", (_iso(now), user_id)
            )
            db.execute(
                "INSERT INTO links (token_hash, user_id, kind, created_at, expires_at, created_by)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (_sha(token), user_id, kind, _iso(now), _iso(expires), actor["id"] if actor else None),
            )
            self._audit(
                db, "user.link_created", actor=actor, target=(user_id, row["email"]), ip=ip,
                kind=kind, expires_at=_iso(expires),
            )
        return token, _iso(expires)

    def _link(self, token) -> sqlite3.Row:
        rows = self._rows(
            "SELECT l.*, u.email, u.name, u.status AS user_status FROM links l"
            " JOIN users u ON u.id = l.user_id WHERE l.token_hash = ?",
            (_sha(str(token or "")),),
        )
        if (
            not rows
            or rows[0]["used_at"]
            or _parse(rows[0]["expires_at"]) <= self.now()
            or rows[0]["user_status"] in ("pending", "disabled")
        ):
            raise AuthError(
                "link_expired",
                "This link has expired or has already been used. Ask your administrator for a new one.",
                410,
            )
        return rows[0]

    def inspect_link(self, token) -> dict:
        link = self._link(token)
        return {"kind": link["kind"], "email": link["email"], "name": link["name"],
                "expires_at": link["expires_at"]}

    def use_link(self, token, password, *, ip=None, user_agent=None):
        link = self._link(token)
        self.check_password(password, email=link["email"])
        digest = hash_password(password)
        now = _iso(self.now())
        with self._tx() as db:
            fresh = db.execute(
                "SELECT used_at FROM links WHERE token_hash = ?", (link["token_hash"],)
            ).fetchone()
            if fresh is None or fresh["used_at"]:
                raise AuthError("link_expired", "This link has already been used.", 410)
            db.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0, failed_attempts = 0,"
                " locked_until = NULL, password_changed_at = ?, updated_at = ?,"
                " status = CASE WHEN status = 'invited' THEN 'active' ELSE status END WHERE id = ?",
                (digest, now, now, link["user_id"]),
            )
            db.execute("UPDATE links SET used_at = ? WHERE token_hash = ?", (now, link["token_hash"]))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (link["user_id"],))
            self._audit(
                db, "auth.password_reset", target=(link["user_id"], link["email"]), ip=ip, kind=link["kind"]
            )
        return self._start_session(link["user_id"], remember=False, ip=ip, user_agent=user_agent)

    # ---------------------------------------------------------- sign-in
    def _locked_error(self, remaining: timedelta) -> AuthError:
        minutes = max(1, math.ceil(remaining.total_seconds() / 60))
        return AuthError(
            "locked",
            f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''},"
            " or ask an administrator to unlock the account.",
            429, minutes=minutes,
        )

    def authenticate(self, email, password, *, ip=None, user_agent=None, remember=False):
        now = self.now()
        settings = self.settings()
        threshold = int(settings["lockout_threshold"])
        lock_for = timedelta(minutes=int(settings["lockout_minutes"]))
        ip_key = ("ip", ip or "?")
        if self._throttle.count(ip_key, now, IP_FAILURE_WINDOW) >= IP_FAILURE_LIMIT:
            raise AuthError(
                "rate_limited", "Too many failed sign-ins from this network. Wait a few minutes and try again.", 429
            )
        address = str(email or "").strip().lower()
        password = password if isinstance(password, str) else ""
        row = self._row_by_email(address) if address else None

        if row is None or row["password_hash"] == UNUSABLE_PASSWORD:
            verify_password(password, self._dummy_hash)
            self._throttle.hit(ip_key, now)
            email_key = ("email", address)
            self._throttle.hit(email_key, now)
            self.audit(
                "auth.login_failed", target=(row["id"] if row else None, address or None), ip=ip,
                reason="unknown_email" if row is None else "no_password",
            )
            if self._throttle.count(email_key, now, lock_for) >= threshold:
                raise self._locked_error(lock_for)
            raise AuthError("invalid_credentials", "Email or password is incorrect.", 401)

        locked_until = _parse(row["locked_until"])
        if locked_until and locked_until > now:
            verify_password(password, self._dummy_hash)
            self._throttle.hit(ip_key, now)
            raise self._locked_error(locked_until - now)

        if not verify_password(password, row["password_hash"]):
            self._throttle.hit(ip_key, now)
            # A lock that has run out starts the count again rather than
            # re-locking on the very next mistake.
            attempts = (0 if locked_until else row["failed_attempts"]) + 1
            lock = attempts >= threshold
            with self._tx() as db:
                db.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, _iso(now + lock_for) if lock else None, row["id"]),
                )
                self._audit(
                    db, "auth.login_failed", target=(row["id"], row["email"]), ip=ip,
                    reason="wrong_password", attempts=attempts,
                )
                if lock:
                    self._audit(
                        db, "auth.locked", target=(row["id"], row["email"]), ip=ip,
                        minutes=int(settings["lockout_minutes"]),
                    )
            if lock:
                raise self._locked_error(lock_for)
            raise AuthError("invalid_credentials", "Email or password is incorrect.", 401)

        # The password is right, so it is safe to say why the account can't
        # be used -- the person asking is its owner.
        if row["status"] == "disabled":
            self.audit("auth.login_blocked", target=(row["id"], row["email"]), ip=ip, reason="disabled")
            raise AuthError("account_disabled", "This account has been disabled. Contact your administrator.", 403)
        if row["status"] == "pending":
            raise AuthError(
                "account_pending", "Your access request is waiting for an administrator to approve it.", 403
            )
        user, token, session = self._start_session(row["id"], remember=remember, ip=ip, user_agent=user_agent)
        self.audit("auth.login", actor=user, target=(user["id"], user["email"]), ip=ip,
                   remember=bool(session["remember"]))
        return user, token, session

    def request_access(self, *, name, email, password, registration="", title="", note="",
                       ip=None) -> None:
        settings = self.settings()
        if not settings["allow_access_requests"] or self.needs_setup():
            raise AuthError(
                "requests_closed",
                "Access requests are turned off. Ask an administrator to create your account.",
                403,
            )
        now = self.now()
        key = ("request", ip or "?")
        if self._throttle.count(key, now, REQUEST_WINDOW) >= REQUEST_LIMIT:
            raise AuthError("rate_limited", "Too many requests from this network. Try again later.", 429)
        self._throttle.hit(key, now)
        address = self._clean_email(email)
        self._clean_name(name)
        self.check_password(password, email=address)
        if self._row_by_email(address):
            # The same answer as a new request: the form must not become a
            # way to test which addresses already have accounts.
            self.audit("access.duplicate", target=(None, address), ip=ip)
            return
        self.create_user(
            email=address, name=name, role="viewer", password=password, status="pending",
            registration=registration, title=title, request_note=note, actor=None, ip=ip,
            _action="access.requested",
        )

    # ------------------------------------------------------------- sessions
    def _start_session(self, user_id: str, *, remember, ip=None, user_agent=None):
        settings = self.settings()
        remember = bool(remember) and bool(settings["allow_remember_me"])
        now = self.now()
        lifetime = (
            timedelta(days=int(settings["remember_me_days"])) if remember
            else timedelta(hours=int(settings["session_max_hours"]))
        )
        token = secrets.token_urlsafe(32)
        session = {
            "id_hash": _sha(token),
            "public_id": "ses_" + secrets.token_hex(8),
            "user_id": user_id,
            "csrf": secrets.token_urlsafe(24),
            "remember": int(remember),
            "created_at": _iso(now),
            "last_seen_at": _iso(now),
            "expires_at": _iso(now + lifetime),
            "ip": ip,
            "user_agent": (user_agent or "")[:300],
        }
        with self._tx() as db:
            db.execute(
                "INSERT INTO sessions (id_hash, public_id, user_id, csrf, remember, created_at,"
                " last_seen_at, expires_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(session.values()),
            )
            db.execute(
                "UPDATE users SET last_login_at = ?, last_login_ip = ?, failed_attempts = 0,"
                " locked_until = NULL WHERE id = ?",
                (session["created_at"], ip, user_id),
            )
        return self.get_user(user_id), token, session

    def _expired(self, session, now: datetime, settings: dict) -> bool:
        if _parse(session["expires_at"]) <= now:
            return True
        idle = timedelta(minutes=int(settings["session_idle_minutes"]))
        return not session["remember"] and now - _parse(session["last_seen_at"]) > idle

    def resolve(self, token) -> tuple[dict, dict] | None:
        """The user and session behind a cookie token, or None when there is
        no such session, it has expired, or its account is no longer active."""
        if not token or not isinstance(token, str):
            return None
        digest = _sha(token)
        rows = self._rows(
            "SELECT s.*, u.status AS user_status FROM sessions s"
            " JOIN users u ON u.id = s.user_id WHERE s.id_hash = ?",
            (digest,),
        )
        if not rows:
            return None
        session = dict(rows[0])
        now = self.now()
        if self._expired(session, now, self.settings()) or session.pop("user_status") != "active":
            with self._tx() as db:
                db.execute("DELETE FROM sessions WHERE id_hash = ?", (digest,))
            return None
        if (now - _parse(session["last_seen_at"])).total_seconds() >= SESSION_TOUCH_SECONDS:
            session["last_seen_at"] = _iso(now)
            with self._tx() as db:
                db.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE id_hash = ?", (session["last_seen_at"], digest)
                )
        return self.get_user(session["user_id"]), session

    @staticmethod
    def public_session(session, *, current_hash: str | None = None) -> dict:
        return {
            "id": session["public_id"],
            "user_id": session["user_id"],
            "remember": bool(session["remember"]),
            "created_at": session["created_at"],
            "last_seen_at": session["last_seen_at"],
            "expires_at": session["expires_at"],
            "ip": session["ip"],
            "user_agent": session["user_agent"],
            "current": current_hash is not None and session["id_hash"] == current_hash,
        }

    def list_sessions(self, *, user_id: str | None = None, current_hash: str | None = None) -> list[dict]:
        now = self.now()
        settings = self.settings()
        rows = self._rows(
            "SELECT s.*, u.name AS user_name, u.email AS user_email, u.role AS user_role"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            + (" WHERE s.user_id = ?" if user_id else "")
            + " ORDER BY s.last_seen_at DESC",
            (user_id,) if user_id else (),
        )
        live, dead = [], []
        for row in rows:
            (dead if self._expired(row, now, settings) else live).append(row)
        if dead:
            with self._tx() as db:
                db.executemany("DELETE FROM sessions WHERE id_hash = ?", [(r["id_hash"],) for r in dead])
        return [
            {**self.public_session(r, current_hash=current_hash), "user_name": r["user_name"],
             "user_email": r["user_email"], "user_role": r["user_role"]}
            for r in live
        ]

    def revoke_session(self, public_id: str, *, actor: dict | None, ip=None,
                       owner_id: str | None = None) -> None:
        rows = self._rows(
            "SELECT s.*, u.email FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.public_id = ?",
            (str(public_id),),
        )
        if not rows or (owner_id and rows[0]["user_id"] != owner_id):
            raise AuthError("not_found", "No such session.", 404)
        with self._tx() as db:
            db.execute("DELETE FROM sessions WHERE public_id = ?", (str(public_id),))
            self._audit(
                db, "auth.session_revoked", actor=actor, target=(rows[0]["user_id"], rows[0]["email"]),
                ip=ip, session=public_id,
            )

    def revoke_user_sessions(self, user_id: str, *, actor: dict | None, ip=None,
                             keep_session: str | None = None) -> int:
        row = self._row(user_id)
        with self._tx() as db:
            count = db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND id_hash != ?", (user_id, keep_session or "")
            ).rowcount
            self._audit(
                db, "user.sessions_revoked", actor=actor, target=(user_id, row["email"]), ip=ip, count=count
            )
        return count

    def end_session(self, session: dict, *, ip=None) -> None:
        row = self._row(session["user_id"])
        with self._tx() as db:
            db.execute("DELETE FROM sessions WHERE id_hash = ?", (session["id_hash"],))
            self._audit(
                db, "auth.logout", actor=self._public(row), target=(row["id"], row["email"]), ip=ip
            )

    # ----------------------------------------------------------- reporting
    def list_audit(self, *, q: str = "", category: str = "", days: int | None = None,
                   user_id: str = "", before: int | None = None, limit: int = 100) -> dict:
        where, params = [], []
        if category:
            actions = AUDIT_CATEGORIES.get(category)
            if actions is None:
                raise AuthError("category_invalid", "Unknown activity category.")
            where.append(f"action IN ({', '.join('?' for _ in actions)})")
            params += list(actions)
        if q:
            needle = "%" + str(q).strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append(
                "(action LIKE ? ESCAPE '\\' OR actor_email LIKE ? ESCAPE '\\' OR actor_name LIKE ? ESCAPE '\\'"
                " OR target_email LIKE ? ESCAPE '\\' OR ip LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\')"
            )
            params += [needle] * 6
        if days:
            where.append("at >= ?")
            params.append(_iso(self.now() - timedelta(days=int(days))))
        if user_id:
            where.append("(actor_id = ? OR target_id = ?)")
            params += [user_id, user_id]
        if before:
            where.append("id < ?")
            params.append(int(before))
        limit = max(1, min(int(limit), 10_000))
        sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(where) if where else "")
        rows = self._rows(sql + " ORDER BY id DESC LIMIT ?", (*params, limit + 1))
        events = [
            {
                "id": r["id"], "at": r["at"], "action": r["action"],
                "actor": {"id": r["actor_id"], "email": r["actor_email"], "name": r["actor_name"]}
                if r["actor_id"] else None,
                "target": {"id": r["target_id"], "email": r["target_email"]}
                if (r["target_id"] or r["target_email"]) else None,
                "ip": r["ip"],
                "detail": json.loads(r["detail"]) if r["detail"] else {},
            }
            for r in rows[:limit]
        ]
        return {"events": events, "next": events[-1]["id"] if len(rows) > limit else None}

    def audit_csv(self, **filters) -> str:
        events = self.list_audit(**filters, limit=10_000)["events"]
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["time_utc", "action", "actor_email", "actor_name", "target_email", "ip", "detail"])
        for e in events:
            writer.writerow([
                e["at"], e["action"],
                e["actor"]["email"] if e["actor"] else "",
                e["actor"]["name"] if e["actor"] else "",
                e["target"]["email"] if e["target"] else "",
                e["ip"] or "",
                json.dumps(e["detail"], ensure_ascii=False) if e["detail"] else "",
            ])
        return out.getvalue()

    def users_csv(self) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["name", "email", "role", "status", "registration", "title", "created_at",
                         "last_login_at", "password_changed_at", "must_change_password", "locked"])
        for u in self.list_users():
            writer.writerow([
                u["name"], u["email"], u["role"], u["status"], u["registration"], u["title"],
                u["created_at"], u["last_login_at"] or "", u["password_changed_at"] or "",
                "yes" if u["must_change_password"] else "no", "yes" if u["locked"] else "no",
            ])
        return out.getvalue()

    def pending_count(self) -> int:
        return self._rows("SELECT COUNT(*) FROM users WHERE status = 'pending'")[0][0]

    def overview(self) -> dict:
        now = self.now()
        users = self.list_users()
        sessions = self.list_sessions()
        week = _iso(now - timedelta(days=7))
        fortnight = _iso(now - timedelta(days=14))
        logins = [r["at"] for r in self._rows(
            "SELECT at FROM audit WHERE action = 'auth.login' AND at >= ? ORDER BY id DESC LIMIT 5000",
            (fortnight,),
        )]
        failed_week = self._rows(
            "SELECT COUNT(*) FROM audit WHERE action = 'auth.login_failed' AND at >= ?", (week,)
        )[0][0]
        by_role = {role: sum(1 for u in users if u["role"] == role and u["status"] == "active") for role in ROLES}
        by_status = {status: sum(1 for u in users if u["status"] == status) for status in STATUSES}
        return {
            "users": {
                "total": len(users),
                "by_role": by_role,
                "by_status": by_status,
                "locked": sum(1 for u in users if u["locked"]),
                "must_change_password": sum(1 for u in users if u["must_change_password"]),
                "never_signed_in": sum(1 for u in users if u["status"] == "active" and not u["last_login_at"]),
            },
            "sessions": {
                "active": len(sessions),
                "users_online": len({s["user_id"] for s in sessions}),
            },
            "signins": {
                "last_14_days": logins,
                "week": sum(1 for at in logins if at >= week),
                "failed_week": failed_week,
            },
            "pending": [u for u in users if u["status"] == "pending"],
            "locked": [u for u in users if u["locked"]],
            "recent": self.list_audit(limit=8)["events"],
        }
