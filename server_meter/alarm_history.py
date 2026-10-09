"""RAM-only alarm and notification event history.

Never written to SQLite, YAML, JSON, or the SD card. Empty after process restart.
The unused `alarm_history` table in existing users.db files is not read.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("server_meter.alarm_history")

ALARM_MAX_RECORDS = 500
_SECRET_MARKERS = ("password", "passwd", "token", "secret", "hash", "argon2", "bearer", "authorization")


def _contains_secret(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _SECRET_MARKERS)


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
    """Bounded deque of alarm/notification events. Process memory only."""

    def __init__(self, *, max_records: int = ALARM_MAX_RECORDS) -> None:
        self._max_records = max(50, int(max_records))
        self._lock = threading.Lock()
        self._items: deque[AlarmRecord] = deque(maxlen=self._max_records)
        self._next_id = 1

    def initialize(self) -> None:
        return

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
        kind = str(kind or "")[:32]
        metric = str(metric or "")[:64]
        unit = str(unit or "")[:16]
        threshold = str(threshold or "")[:80]
        hostname = str(hostname or "")[:128]
        if _contains_secret(f"{kind} {metric}"):
            logger.warning("refusing to keep an alarm history row that looks like a secret")
            return
        if _contains_secret(threshold):
            threshold = "delivery failed"
        if _contains_secret(hostname):
            hostname = ""
        now = float(created_at if created_at is not None else time.time())
        with self._lock:
            record = AlarmRecord(
                id=self._next_id,
                created_at=now,
                kind=kind,
                metric=metric,
                value=None if value is None else float(value),
                unit=unit,
                threshold=threshold,
                duration_seconds=None if duration_seconds is None else int(duration_seconds),
                hostname=hostname,
            )
            self._next_id += 1
            self._items.append(record)

    def list_recent(self, limit: int = 100) -> list[AlarmRecord]:
        cap = max(1, min(int(limit), self._max_records))
        with self._lock:
            items = list(self._items)
        items.reverse()
        return items[:cap]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
