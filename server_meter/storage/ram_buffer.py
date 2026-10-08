"""In-memory ring buffer for sensor history.

Sensor samples exist only in RAM. They are never written to disk, even when
the buffer is trimmed under memory pressure.

The deque grows with real samples. `maxlen` is a ceiling, not a preallocation.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from server_meter.config import HISTORY_HARD_MAX_SAMPLES
from server_meter.models.measurement import Measurement

# slots Measurement + typical float payload + deque pointer. Calibrated by
# tests/test_history_scale.py (~281 B/sample RSS at 2M). Not a reservation.
BYTES_PER_SAMPLE_ESTIMATE = 280


def even_indices(n: int, k: int) -> list[int]:
    """Return k indices in 0..n-1 including both ends, spaced as evenly as possible."""
    if n <= 0 or k <= 0:
        return []
    if k >= n:
        return list(range(n))
    if k == 1:
        return [n - 1]
    raw = [round(i * (n - 1) / (k - 1)) for i in range(k)]
    out: list[int] = []
    seen: set[int] = set()
    for idx in raw:
        if idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


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
        # maxlen caps growth; CPython deque allocates blocks of 64 as needed.
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
        max_points: int | None = None,
    ) -> list[Measurement]:
        """Return selected samples without copying the whole ring unless needed.

        Time filters always address a suffix (timestamps are monotonic).
        `max_points` even-downsamples that suffix (keeps shape). `limit` keeps
        the newest N. `max_points` wins when both are set.
        """
        exclusive_since = seconds is None and since is not None
        cutoff: float | None = None
        if seconds is not None and seconds > 0:
            cutoff = time.time() - float(seconds)
        elif since is not None:
            cutoff = float(since)

        with self._lock:
            data = self._data
            n = len(data)
            if n == 0:
                return []
            matching = self._matching_suffix_len_locked(cutoff, exclusive_since)
            if matching <= 0:
                return []
            if max_points is not None:
                if max_points <= 0:
                    return []
                if matching <= max_points:
                    return self._collect_suffix_locked(matching)
                return self._even_suffix_locked(matching, max_points)
            if limit is not None:
                if limit <= 0:
                    return []
                take = min(limit, matching)
                return self._collect_newest_locked(take)
            return self._collect_suffix_locked(matching)

    def stats(self) -> dict[str, int | float | None]:
        now = time.time()
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
                "memory_bytes": count * BYTES_PER_SAMPLE_ESTIMATE,
            }

    def _matching_suffix_len_locked(self, cutoff: float | None, exclusive: bool) -> int:
        if cutoff is None:
            return len(self._data)
        matched = 0
        for sample in reversed(self._data):
            ts = sample.timestamp
            if exclusive:
                if ts <= cutoff:
                    break
            elif ts < cutoff:
                break
            matched += 1
        return matched

    def _collect_newest_locked(self, take: int) -> list[Measurement]:
        if take <= 0:
            return []
        if take >= len(self._data):
            return list(self._data)
        out: list[Measurement] = []
        for i, sample in enumerate(reversed(self._data)):
            if i >= take:
                break
            out.append(sample)
        out.reverse()
        return out

    def _collect_suffix_locked(self, matching: int) -> list[Measurement]:
        n = len(self._data)
        if matching >= n:
            return list(self._data)
        return self._collect_newest_locked(matching)

    def _even_suffix_locked(self, matching: int, k: int) -> list[Measurement]:
        wanted_rel = even_indices(matching, k)
        if not wanted_rel:
            return []
        wanted_from_right = {matching - 1 - idx for idx in wanted_rel}
        found: dict[int, Measurement] = {}
        for reverse_i, sample in enumerate(reversed(self._data)):
            if reverse_i >= matching:
                break
            if reverse_i not in wanted_from_right:
                continue
            found[matching - 1 - reverse_i] = sample
            if len(found) == len(wanted_rel):
                break
        return [found[idx] for idx in wanted_rel if idx in found]

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
