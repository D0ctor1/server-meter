"""In-memory ring buffer for sensor history.

Sensor samples exist only in RAM. They are never written to disk, even when
the buffer is trimmed under memory pressure.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Iterable

from server_meter.config import HISTORY_HARD_MAX_SAMPLES
from server_meter.models.measurement import Measurement


class RamBuffer:
    """Thread-safe deque with max_samples, max_age, and emergency trim."""

    def __init__(
        self,
        max_samples: int,
        max_age_seconds: float,
        min_samples_keep: int = 64,
        hard_max: int = HISTORY_HARD_MAX_SAMPLES,
    ) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        cap = min(int(max_samples), int(hard_max))
        if cap < 1:
            cap = 1
        self._max_samples = cap
        self._hard_max = int(hard_max)
        self._max_age_seconds = float(max_age_seconds)
        self._min_samples_keep = max(1, min(int(min_samples_keep), cap))
        self._lock = threading.Lock()
        self._data: deque[Measurement] = deque(maxlen=cap)
        self._dropped_oldest = 0
        self._trim_events = 0

    @property
    def max_samples(self) -> int:
        return self._max_samples

    @property
    def dropped_oldest(self) -> int:
        return self._dropped_oldest

    @property
    def trim_events(self) -> int:
        return self._trim_events

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def append(self, sample: Measurement) -> None:
        with self._lock:
            if self._data.maxlen is not None and len(self._data) >= self._data.maxlen:
                self._dropped_oldest += 1
            self._data.append(sample)
            self._trim_age_locked(now=sample.timestamp)

    def oldest_timestamp(self) -> float | None:
        with self._lock:
            if not self._data:
                return None
            return self._data[0].timestamp

    def newest_timestamp(self) -> float | None:
        with self._lock:
            if not self._data:
                return None
            return self._data[-1].timestamp

    def latest(self) -> Measurement | None:
        with self._lock:
            if not self._data:
                return None
            return self._data[-1]

    def trim_oldest(self, count: int) -> int:
        """Remove the oldest `count` samples. Never writes them to disk."""
        if count <= 0:
            return 0
        with self._lock:
            return self._trim_oldest_locked(count)

    def trim_fraction(self, fraction: float) -> int:
        fraction = min(max(fraction, 0.0), 0.95)
        with self._lock:
            size = len(self._data)
            keep_floor = self._min_samples_keep
            removable = max(0, size - keep_floor)
            count = int(size * fraction)
            count = min(count, removable)
            return self._trim_oldest_locked(count)

    def enforce_limits(self, now: float | None = None) -> int:
        with self._lock:
            return self._trim_age_locked(now=now)

    def snapshot(
        self,
        *,
        seconds: float | None = None,
        limit: int | None = None,
        since: float | None = None,
    ) -> list[Measurement]:
        """Return a copy of selected samples (still RAM-only)."""
        with self._lock:
            samples: Iterable[Measurement] = self._data
            if seconds is not None and seconds > 0:
                cutoff = time.time() - float(seconds)
                samples = [s for s in samples if s.timestamp >= cutoff]
            elif since is not None:
                samples = [s for s in samples if s.timestamp > float(since)]
            else:
                samples = list(samples)
            result = list(samples)
        if limit is not None and limit >= 0:
            if limit == 0:
                return []
            if len(result) > limit:
                result = result[-limit:]
        return result

    def stats(self) -> dict[str, int | float | None]:
        now = time.time()
        # Approximate RAM cost of one Measurement (slots + Python object overhead).
        bytes_per_sample = 480
        with self._lock:
            count = len(self._data)
            oldest = self._data[0].timestamp if self._data else None
            newest = self._data[-1].timestamp if self._data else None
            return {
                "samples": count,
                "max_samples": self._max_samples,
                "hard_max_samples": self._hard_max,
                "max_age_seconds": self._max_age_seconds,
                "dropped_oldest": self._dropped_oldest,
                "trim_events": self._trim_events,
                "oldest_timestamp": oldest,
                "newest_timestamp": newest,
                "oldest_age_seconds": None if oldest is None else max(0.0, now - oldest),
                "newest_age_seconds": None if newest is None else max(0.0, now - newest),
                "memory_bytes": count * bytes_per_sample,
            }

    def _trim_oldest_locked(self, count: int) -> int:
        removed = 0
        while removed < count and self._data:
            if len(self._data) <= self._min_samples_keep and count < len(self._data):
                break
            self._data.popleft()
            removed += 1
            self._dropped_oldest += 1
        if removed:
            self._trim_events += 1
        return removed

    def _trim_age_locked(self, now: float | None = None) -> int:
        if self._max_age_seconds <= 0 or not self._data:
            return 0
        cutoff = (now if now is not None else time.time()) - self._max_age_seconds
        removed = 0
        while self._data and self._data[0].timestamp < cutoff:
            if len(self._data) <= 1:
                break
            self._data.popleft()
            removed += 1
            self._dropped_oldest += 1
        if removed:
            self._trim_events += 1
        return removed
