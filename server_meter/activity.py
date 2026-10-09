"""RAM-only last-seen timestamps for authenticated web users.

Never written to SQLite, YAML, logs, or the SD card. Empty after process restart.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Dashboard polling should not rewrite the stamp on every request.
THROTTLE_SECONDS = 45.0

# Health, Nagios, and the monitoring token path are not interactive web use.
ACTIVITY_SKIP_PATHS = frozenset(
    {
        "/api/health",
        "/api/monitoring",
        "/api/nagios/check",
    }
)


def normalize_path(path: str) -> str:
    value = (path or "/").strip() or "/"
    if len(value) > 1:
        value = value.rstrip("/")
    return value


def should_record(path: str, user_id: int) -> bool:
    if user_id <= 0:
        return False
    return normalize_path(path) not in ACTIVITY_SKIP_PATHS


class ActivityTracker:
    """Map user_id -> UTC epoch seconds. Process memory only."""

    def __init__(
        self,
        *,
        throttle_seconds: float = THROTTLE_SECONDS,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._throttle = float(throttle_seconds)
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last: dict[int, float] = {}
        self._touched_mono: dict[int, float] = {}

    def touch(self, user_id: int) -> bool:
        if user_id <= 0:
            return False
        now_mono = self._monotonic()
        with self._lock:
            previous = self._touched_mono.get(user_id)
            if previous is not None and (now_mono - previous) < self._throttle:
                return False
            self._last[user_id] = float(self._clock())
            self._touched_mono[user_id] = now_mono
            return True

    def get(self, user_id: int) -> float | None:
        with self._lock:
            value = self._last.get(user_id)
            return float(value) if value is not None else None

    def snapshot(self) -> dict[int, float]:
        with self._lock:
            return {user_id: float(ts) for user_id, ts in self._last.items()}
