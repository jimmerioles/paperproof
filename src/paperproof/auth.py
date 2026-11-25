"""Local authentication primitives: passwords, sessions, CSRF, and limits."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from paperproof.config import Settings
from paperproof.db import new_id, one, utcnow

SESSION_COOKIE = "paperproof_session"
SESSION_SALT = "paperproof-session-v1"
CSRF_FIELD = "csrf_token"
MIN_PASSWORD_LENGTH = 12
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")

PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> tuple[bool, bool]:
    """Return (valid, needs_rehash)."""
    try:
        PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False
    return True, PASSWORD_HASHER.check_needs_rehash(password_hash)


def set_admin_password(
    conn: sqlite3.Connection,
    username: str,
    password: str,
) -> str:
    """Create or update an admin account. Returns 'created' or 'updated'."""
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 3 to 64 characters, letters, digits, dot, dash, or underscore."
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    password_hash = hash_password(password)
    existing = one(conn, "SELECT id FROM users WHERE username = ?", (username,))
    if existing:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, utcnow(), existing["id"]),
        )
        return "updated"
    conn.execute(
        "INSERT INTO users (id, username, password_hash, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (new_id("usr"), username, password_hash, utcnow(), utcnow()),
    )
    return "created"


def get_user_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return one(
        conn,
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (username.strip(),),
    )


def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return one(conn, "SELECT id, username FROM users WHERE id = ?", (user_id,))


def count_users(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])


@dataclass(frozen=True)
class SessionData:
    uid: str | None
    csrf: str
    issued_at: int


class SessionManager:
    def __init__(self, secret: str, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.serializer = URLSafeTimedSerializer(
            secret,
            salt=SESSION_SALT,
            signer_kwargs={"digest_method": hashlib.sha256},
        )

    def new(self, uid: str | None = None) -> SessionData:
        return SessionData(
            uid=uid,
            csrf=secrets.token_urlsafe(32),
            issued_at=int(time.time()),
        )

    def dumps(self, session: SessionData) -> str:
        return self.serializer.dumps(
            {
                "uid": session.uid,
                "csrf": session.csrf,
                "iat": session.issued_at,
            }
        )

    def loads(self, value: str) -> SessionData | None:
        try:
            payload = self.serializer.loads(value, max_age=self.ttl_seconds)
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(payload, dict):
            return None
        csrf = payload.get("csrf")
        uid = payload.get("uid")
        issued_at = payload.get("iat", 0)
        if not isinstance(csrf, str) or not csrf:
            return None
        if uid is not None and not isinstance(uid, str):
            return None
        if not isinstance(issued_at, int):
            issued_at = 0
        return SessionData(uid=uid, csrf=csrf, issued_at=issued_at)


def csrf_matches(expected: str, provided: str) -> bool:
    return bool(expected) and bool(provided) and secrets.compare_digest(expected, provided)


def safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def load_session_secret(settings: Settings) -> str:
    if settings.session_secret:
        return settings.session_secret
    path = settings.data_dir / "session-secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(secret)
    return secret


@dataclass
class _Attempt:
    failures: int = 0
    window_started: float = 0.0
    locked_until: float = 0.0


class LoginLimiter:
    """In-memory lockout for a single-process pilot.

    A multi-worker or multi-tenant deployment should move this to Redis or
    the database so every process shares the same counters.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 300,
        lockout_seconds: int = 300,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, _Attempt] = {}

    def _entry(self, key: str, now: float) -> _Attempt:
        entry = self._attempts.get(key)
        if entry is None:
            entry = _Attempt(window_started=now)
            self._attempts[key] = entry
        return entry

    def locked_for(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        entry = self._attempts.get(key)
        if entry is None or entry.locked_until <= now:
            return 0
        return max(1, int(entry.locked_until - now))

    def record_failure(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        entry = self._entry(key, now)
        if entry.locked_until > now:
            return max(1, int(entry.locked_until - now))
        if entry.window_started == 0 or now - entry.window_started > self.window_seconds:
            entry.window_started = now
            entry.failures = 0
        entry.failures += 1
        if entry.failures >= self.max_attempts:
            entry.locked_until = now + self.lockout_seconds
            entry.failures = 0
            return self.lockout_seconds
        return 0

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)
