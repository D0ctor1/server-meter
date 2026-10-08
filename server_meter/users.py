"""Persistent user accounts in SQLite. Sensor history stays in RAM."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

from server_meter.config import DEFAULT_PASSWORD_PLACEHOLDER, AppConfig
from server_meter.sqlite_state import AlarmHistory, MonitoringTokens

logger = logging.getLogger("server_meter.users")

ROLES = frozenset({"admin", "user"})
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MIN_PASSWORD_LENGTH = 8
DEFAULT_USERS_DB = "/var/lib/server-meter/users.db"
MIGRATED_PASSWORD_MARKER = "MIGRATED"
# Dashboard + Nagios poll Basic Auth many times per minute. Argon2id is
# intentionally expensive (~tens of ms); cache successful verifications in RAM
# so polling does not re-hash the same password on every request.
AUTH_CACHE_TTL_SECONDS = 30.0
AUTH_CACHE_MAX_ENTRIES = 128


class _CredentialCache:
    """Process-local HMAC cache of successful credential checks. Never persisted."""

    def __init__(self, ttl_seconds: float = AUTH_CACHE_TTL_SECONDS, max_entries: int = AUTH_CACHE_MAX_ENTRIES) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._secret = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._items: OrderedDict[bytes, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def digest(self, username: str, secret: str) -> bytes:
        payload = f"{username}\0{secret}".encode("utf-8")
        return hmac.new(self._secret, payload, hashlib.sha256).digest()

    def get(self, digest: bytes) -> tuple[Any, bool]:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(digest)
            if item is None:
                self.misses += 1
                return None, False
            expires, value = item
            if expires <= now:
                self._items.pop(digest, None)
                self.misses += 1
                return None, False
            self._items.move_to_end(digest)
            self.hits += 1
            return value, True

    def put(self, digest: bytes, value: Any) -> None:
        now = time.monotonic()
        with self._lock:
            while len(self._items) >= self._max:
                self._items.popitem(last=False)
            self._items[digest] = (now + self._ttl, value)
            self._items.move_to_end(digest)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.hits = 0
            self.misses = 0

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


class UserError(ValueError):
    code = "invalid_user"


class DuplicateUserError(UserError):
    code = "duplicate_username"


class LastAdminError(UserError):
    code = "last_admin"


class UserNotFoundError(UserError):
    code = "user_not_found"


class InvalidUsernameError(UserError):
    code = "invalid_username"


class InvalidPasswordError(UserError):
    code = "invalid_password"


class InvalidRoleError(UserError):
    code = "invalid_role"


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    password_hash: str
    role: str
    enabled: bool
    created_at: float
    updated_at: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    role: str
    enabled: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict[str, str]:
        return {"username": self.username, "role": self.role}


ANONYMOUS = AuthUser(id=0, username="anonymous", role="admin", enabled=True)


def resolve_users_db_path(config: AppConfig) -> str:
    configured = (config.web.users_db or "").strip()
    if configured:
        return configured
    if config.application.environment == "test":
        return ":memory:"
    if config.application.environment != "production" and config._source_path is not None:
        return str(config._source_path.parent / "users.db")
    return DEFAULT_USERS_DB


def validate_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.fullmatch(value):
        raise InvalidUsernameError("invalid username")
    return value


def validate_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value not in ROLES:
        raise InvalidRoleError("invalid role")
    return value


def validate_password(password: str, *, required: bool) -> str | None:
    if password is None:
        password = ""
    if not password:
        if required:
            raise InvalidPasswordError("password is required")
        return None
    if len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidPasswordError("password is too short")
    return password


def _hasher(*, test: bool) -> PasswordHasher:
    if test:
        return PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def _row(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=int(row["id"]),
        username=str(row["username"]),
        password_hash=str(row["password_hash"]),
        role=str(row["role"]),
        enabled=bool(row["enabled"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


class UserStore:
    def __init__(self, path: str, *, test: bool = False) -> None:
        self._path = path
        self._test = test
        self._hasher = _hasher(test=test)
        self._dummy_hash = self._hasher.hash("timing-dummy")
        self._factory_password: bool | None = None
        self._auth_cache = _CredentialCache()
        self._lock = threading.Lock()
        uri = path == ":memory:"
        self._conn = sqlite3.connect(
            path,
            check_same_thread=False,
            uri=uri,
            timeout=5.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:" and not test:
            self._conn.execute("PRAGMA journal_mode = WAL")
        self.alarms = AlarmHistory(self._conn, self._lock)
        self.tokens = MonitoringTokens(self._conn, self._lock, self._hasher)
        self.initialize()

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def initialize(self) -> None:
        with self._lock:
            self._conn.execute(_CREATE_SQL)
            self._conn.commit()
        self.alarms.initialize()
        self.tokens.initialize()
        self._secure_file()

    def _secure_file(self) -> None:
        if self._path == ":memory:":
            return
        db_path = Path(self._path)
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(db_path, 0o600)
        except OSError:
            logger.warning("cannot set users database mode 600")

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def count(self) -> int:
        with self._lock:
            row = self._execute("SELECT COUNT(*) AS n FROM users").fetchone()
            return int(row["n"] if row else 0)

    def list_users(self) -> list[UserRecord]:
        with self._lock:
            rows = self._execute(
                "SELECT id, username, password_hash, role, enabled, created_at, updated_at "
                "FROM users ORDER BY username COLLATE NOCASE"
            ).fetchall()
        return [_row(row) for row in rows]

    def get(self, user_id: int) -> UserRecord | None:
        with self._lock:
            row = self._execute(
                "SELECT id, username, password_hash, role, enabled, created_at, updated_at "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return _row(row) if row else None

    def get_by_username(self, username: str) -> UserRecord | None:
        with self._lock:
            row = self._execute(
                "SELECT id, username, password_hash, role, enabled, created_at, updated_at "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        return _row(row) if row else None

    def _active_admin_count(self, exclude_id: int | None = None) -> int:
        if exclude_id is None:
            row = self._execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND enabled = 1"
            ).fetchone()
        else:
            row = self._execute(
                "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND enabled = 1 AND id != ?",
                (exclude_id,),
            ).fetchone()
        return int(row["n"] if row else 0)

    def _guard_last_admin(self, current: UserRecord, *, new_role: str, new_enabled: bool) -> None:
        would_remain_admin = new_role == "admin" and new_enabled
        if current.role == "admin" and current.enabled and not would_remain_admin:
            if self._active_admin_count(exclude_id=current.id) < 1:
                raise LastAdminError("Cannot remove or disable the last active administrator.")

    def create(self, username: str, password: str, role: str, enabled: bool = True) -> UserRecord:
        username = validate_username(username)
        role = validate_role(role)
        password = validate_password(password, required=True) or ""
        now = time.time()
        password_hash = self._hasher.hash(password)
        with self._lock:
            try:
                cursor = self._execute(
                    "INSERT INTO users (username, password_hash, role, enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (username, password_hash, role, 1 if enabled else 0, now, now),
                )
                self._conn.commit()
                user_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError as exc:
                raise DuplicateUserError("username already exists") from exc
        created = self.get(user_id)
        if created is None:
            raise UserError("failed to load created user")
        self._factory_password = None
        self._auth_cache.clear()
        logger.info("created user %s role=%s enabled=%s", created.username, created.role, created.enabled)
        return created

    def update(
        self,
        user_id: int,
        *,
        username: str | None = None,
        password: str | None = None,
        role: str | None = None,
        enabled: bool | None = None,
    ) -> UserRecord:
        with self._lock:
            row = self._execute(
                "SELECT id, username, password_hash, role, enabled, created_at, updated_at "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise UserNotFoundError("user not found")
            current = _row(row)
            new_username = validate_username(username) if username is not None else current.username
            new_role = validate_role(role) if role is not None else current.role
            new_enabled = current.enabled if enabled is None else bool(enabled)
            self._guard_last_admin(current, new_role=new_role, new_enabled=new_enabled)
            new_hash = current.password_hash
            if password:
                checked = validate_password(password, required=False)
                if checked:
                    new_hash = self._hasher.hash(checked)
            now = time.time()
            try:
                self._execute(
                    "UPDATE users SET username = ?, password_hash = ?, role = ?, enabled = ?, updated_at = ? "
                    "WHERE id = ?",
                    (new_username, new_hash, new_role, 1 if new_enabled else 0, now, user_id),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise DuplicateUserError("username already exists") from exc
        updated = self.get(user_id)
        if updated is None:
            raise UserNotFoundError("user not found")
        changes: list[str] = []
        if updated.username != current.username:
            changes.append(f"username {current.username}->{updated.username}")
        if updated.role != current.role:
            changes.append(f"role {current.role}->{updated.role}")
        if updated.enabled != current.enabled:
            changes.append("enabled" if updated.enabled else "disabled")
        if new_hash != current.password_hash:
            changes.append("password")
        self._factory_password = None
        self._auth_cache.clear()
        logger.info("updated user %s (%s)", updated.username, ", ".join(changes) or "no field changes")
        return updated

    def delete(self, user_id: int) -> UserRecord:
        with self._lock:
            row = self._execute(
                "SELECT id, username, password_hash, role, enabled, created_at, updated_at "
                "FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise UserNotFoundError("user not found")
            current = _row(row)
            self._guard_last_admin(current, new_role="user", new_enabled=False)
            self._execute("DELETE FROM users WHERE id = ?", (user_id,))
            self._conn.commit()
        self._factory_password = None
        self._auth_cache.clear()
        logger.info("deleted user %s", current.username)
        return current

    def _verify(self, password_hash: str, password: str) -> bool:
        try:
            return bool(self._hasher.verify(password_hash, password))
        except (VerifyMismatchError, VerificationError, InvalidHash):
            return False

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        digest = self._auth_cache.digest(username or "", password or "")
        cached, hit = self._auth_cache.get(digest)
        if hit:
            return cached
        record = self.get_by_username(username)
        if record is None:
            self._verify(self._dummy_hash, password)
            return None
        if not self._verify(record.password_hash, password):
            return None
        if not record.enabled:
            return None
        self._auth_cache.put(digest, record)
        return record

    def auth_cache_stats(self) -> dict[str, int]:
        with self._auth_cache._lock:
            return {
                "hits": self._auth_cache.hits,
                "misses": self._auth_cache.misses,
                "size": len(self._auth_cache._items),
            }

    def has_factory_password(self) -> bool:
        if self._factory_password is not None:
            return self._factory_password
        found = False
        for user in self.list_users():
            if user.enabled and self._verify(user.password_hash, DEFAULT_PASSWORD_PLACEHOLDER):
                found = True
                break
        self._factory_password = found
        return found


def migrate_yaml_admin(store: UserStore, config: AppConfig) -> bool:
    """Create the first admin from YAML once. Never duplicates existing users."""
    if store.count() > 0:
        return False
    username = (config.web.auth.username or "admin").strip() or "admin"
    password = config.web.auth.password or DEFAULT_PASSWORD_PLACEHOLDER
    if password == MIGRATED_PASSWORD_MARKER:
        password = DEFAULT_PASSWORD_PLACEHOLDER
    store.create(username, password, "admin", enabled=True)
    logger.info("migrated YAML account %s into the user database", username)
    return True
