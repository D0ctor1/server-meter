"""SQLite extras on the user database: alarm history and monitoring tokens.

Sensor samples stay in RAM. This module never stores passwords, SMTP
credentials, hashes, or session material in alarm rows.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any

from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

logger = logging.getLogger("server_meter.sqlite_state")

ALARM_MAX_RECORDS = 500
MONITORING_ROLE = "monitoring"
MONITORING_USERNAME = "monitoring-token"

_ALARM_SQL = """
CREATE TABLE IF NOT EXISTS alarm_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    kind TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL DEFAULT '',
    threshold TEXT NOT NULL DEFAULT '',
    duration_seconds INTEGER,
    hostname TEXT NOT NULL DEFAULT ''
);
"""

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

_ALARM_INDEX = "CREATE INDEX IF NOT EXISTS alarm_history_created_at ON alarm_history (created_at DESC);"


@dataclass(frozen=True)
class AlarmRecord:
    id: int
    created_at: float
    kind: str
    metric: str
    value: float | None
    unit: str
    threshold: str
    duration_seconds: int | None
    hostname: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "kind": self.kind,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "threshold": self.threshold,
            "duration_seconds": self.duration_seconds,
            "hostname": self.hostname,
        }


class AlarmHistory:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock, *, max_records: int = ALARM_MAX_RECORDS) -> None:
        self._conn = conn
        self._lock = lock
        self._max_records = max(50, int(max_records))

    def initialize(self) -> None:
        with self._lock:
            self._conn.execute(_ALARM_SQL)
            self._conn.execute(_ALARM_INDEX)
            self._conn.commit()

    def append(
        self,
        *,
        kind: str,
        metric: str,
        value: float | None,
        unit: str = "",
        threshold: str = "",
        duration_seconds: int | None = None,
        hostname: str = "",
        created_at: float | None = None,
    ) -> None:
        lowered = f"{kind} {metric} {threshold} {hostname}".lower()
        if any(word in lowered for word in ("password", "token", "smtp", "secret", "hash")):
            logger.warning("refusing to persist alarm history row that looks like a secret")
            return
        kind = str(kind or "")[:32]
        metric = str(metric or "")[:64]
        unit = str(unit or "")[:16]
        threshold = str(threshold or "")[:80]
        hostname = str(hostname or "")[:128]
        now = float(created_at if created_at is not None else time.time())
        with self._lock:
            self._conn.execute(
                "INSERT INTO alarm_history "
                "(created_at, kind, metric, value, unit, threshold, duration_seconds, hostname) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now, kind, metric, value, unit, threshold, duration_seconds, hostname),
            )
            extra = self._conn.execute("SELECT COUNT(*) AS n FROM alarm_history").fetchone()
            count = int(extra["n"] if extra else 0)
            overflow = count - self._max_records
            if overflow > 0:
                self._conn.execute(
                    "DELETE FROM alarm_history WHERE id IN ("
                    "SELECT id FROM alarm_history ORDER BY id ASC LIMIT ?"
                    ")",
                    (overflow,),
                )
            self._conn.commit()

    def list_recent(self, limit: int = 100) -> list[AlarmRecord]:
        cap = max(1, min(int(limit), self._max_records))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, kind, metric, value, unit, threshold, "
                "duration_seconds, hostname FROM alarm_history "
                "ORDER BY id DESC LIMIT ?",
                (cap,),
            ).fetchall()
        return [
            AlarmRecord(
                id=int(row["id"]),
                created_at=float(row["created_at"]),
                kind=str(row["kind"]),
                metric=str(row["metric"]),
                value=None if row["value"] is None else float(row["value"]),
                unit=str(row["unit"] or ""),
                threshold=str(row["threshold"] or ""),
                duration_seconds=None if row["duration_seconds"] is None else int(row["duration_seconds"]),
                hostname=str(row["hostname"] or ""),
            )
            for row in rows
        ]


class MonitoringTokens:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock, hasher) -> None:
        self._conn = conn
        self._lock = lock
        self._hasher = hasher
        self._dummy = hasher.hash("timing-dummy-token")

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
        logger.info("issued a new read-only monitoring token")
        return raw

    def revoke(self) -> bool:
        with self._lock:
            cursor = self._conn.execute("UPDATE monitoring_tokens SET revoked = 1 WHERE revoked = 0")
            self._conn.commit()
            changed = int(cursor.rowcount or 0)
        if changed:
            logger.info("revoked monitoring token")
        return changed > 0

    def authenticate(self, token: str) -> bool:
        if not token or not token.startswith("sm_"):
            self._verify(self._dummy, token or "x")
            return False
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
        return True

    def _verify(self, token_hash: str, token: str) -> bool:
        try:
            return bool(self._hasher.verify(token_hash, token))
        except (VerifyMismatchError, VerificationError, InvalidHash):
            return False
