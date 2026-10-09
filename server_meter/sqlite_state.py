"""SQLite extras on the user database: monitoring tokens only.

Sensor samples and alarm/notification history stay in RAM. This module never
stores passwords, SMTP credentials, or alarm events.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
import time
from typing import Any

from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

logger = logging.getLogger("server_meter.sqlite_state")

MONITORING_ROLE = "monitoring"
MONITORING_USERNAME = "monitoring-token"

_TOKEN_SQL = """
CREATE TABLE IF NOT EXISTS monitoring_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL,
    revoked INTEGER NOT NULL DEFAULT 0
);
"""


class MonitoringTokens:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock, hasher) -> None:
        self._conn = conn
        self._lock = lock
        self._hasher = hasher
        self._dummy = hasher.hash("timing-dummy-token")
        self._ok_until = 0.0
        self._ok_token = ""

    def initialize(self) -> None:
        with self._lock:
            self._conn.execute(_TOKEN_SQL)
            self._conn.commit()

    def status(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, created_at, last_used_at FROM monitoring_tokens "
                "WHERE revoked = 0 ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return {"configured": False, "created_at": None, "last_used_at": None}
        return {
            "configured": True,
            "created_at": float(row["created_at"]),
            "last_used_at": None if row["last_used_at"] is None else float(row["last_used_at"]),
        }

    def generate(self) -> str:
        raw = "sm_" + secrets.token_urlsafe(32)
        token_hash = self._hasher.hash(raw)
        now = time.time()
        with self._lock:
            self._conn.execute("UPDATE monitoring_tokens SET revoked = 1 WHERE revoked = 0")
            self._conn.execute(
                "INSERT INTO monitoring_tokens (name, token_hash, created_at, last_used_at, revoked) "
                "VALUES (?, ?, ?, NULL, 0)",
                ("nagios", token_hash, now),
            )
            self._conn.commit()
        self._ok_until = 0.0
        self._ok_token = ""
        logger.info("issued a new read-only monitoring token")
        return raw

    def revoke(self) -> bool:
        with self._lock:
            cursor = self._conn.execute("UPDATE monitoring_tokens SET revoked = 1 WHERE revoked = 0")
            self._conn.commit()
            changed = int(cursor.rowcount or 0)
        if changed:
            self._ok_until = 0.0
            self._ok_token = ""
            logger.info("revoked monitoring token")
        return changed > 0

    def authenticate(self, token: str) -> bool:
        if not token or not token.startswith("sm_"):
            self._verify(self._dummy, token or "x")
            return False
        now_mono = time.monotonic()
        if token == self._ok_token and now_mono < self._ok_until:
            return True
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, token_hash, last_used_at FROM monitoring_tokens WHERE revoked = 0"
            ).fetchall()
        matched = None
        for row in rows:
            if self._verify(str(row["token_hash"]), token):
                matched = row
                break
        if matched is None:
            if not rows:
                self._verify(self._dummy, token)
            return False
        now = time.time()
        last_used = matched["last_used_at"]
        if last_used is None or (now - float(last_used)) >= 300:
            with self._lock:
                self._conn.execute(
                    "UPDATE monitoring_tokens SET last_used_at = ? WHERE id = ?",
                    (now, int(matched["id"])),
                )
                self._conn.commit()
        self._ok_token = token
        self._ok_until = now_mono + 30.0
        return True

    def _verify(self, token_hash: str, token: str) -> bool:
        try:
            return bool(self._hasher.verify(token_hash, token))
        except (VerifyMismatchError, VerificationError, InvalidHash):
            return False
