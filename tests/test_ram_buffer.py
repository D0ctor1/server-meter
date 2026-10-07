from __future__ import annotations

import time

from server_meter.models.measurement import Measurement
from server_meter.storage.ram_buffer import HISTORY_HARD_MAX_SAMPLES, RamBuffer


def _sample(ts: float, temp: float = 20.0) -> Measurement:
    return Measurement(timestamp=ts, temperature=temp)


def test_max_samples_drops_oldest():
    buf = RamBuffer(max_samples=5, max_age_seconds=10_000, min_samples_keep=1)
    for i in range(8):
        buf.append(_sample(1000 + i, temp=float(i)))
    assert len(buf) == 5
    snap = buf.snapshot()
    assert snap[0].temperature == 3.0
    assert snap[-1].temperature == 7.0
    assert buf.dropped_oldest >= 3


def test_hard_max_caps_config():
    buf = RamBuffer(max_samples=HISTORY_HARD_MAX_SAMPLES * 4, max_age_seconds=10, min_samples_keep=8)
    assert buf.max_samples == HISTORY_HARD_MAX_SAMPLES


def test_max_age_removes_old_contiguous_tail():
    now = time.time()
    buf = RamBuffer(max_samples=50, max_age_seconds=60, min_samples_keep=1)
    buf.append(_sample(now - 120, 1.0))
    buf.append(_sample(now - 90, 2.0))
    buf.append(_sample(now - 10, 3.0))
    buf.append(_sample(now, 4.0))
    assert [s.temperature for s in buf.snapshot()] == [3.0, 4.0]


def test_trim_oldest_keeps_newest_contiguous():
    buf = RamBuffer(max_samples=10, max_age_seconds=10_000, min_samples_keep=2)
    for i in range(10):
        buf.append(_sample(i, float(i)))
    removed = buf.trim_oldest(3)
    assert removed == 3
    temps = [s.temperature for s in buf.snapshot()]
    assert temps == [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]


def test_trim_fraction_under_pressure():
    buf = RamBuffer(max_samples=100, max_age_seconds=10_000, min_samples_keep=10)
    for i in range(100):
        buf.append(_sample(i, float(i)))
    removed = buf.trim_fraction(0.25)
    assert removed == 25
    temps = [s.temperature for s in buf.snapshot()]
    assert temps[0] == 25.0
    assert temps[-1] == 99.0
    assert temps == list(range(25, 100))


def test_history_filters():
    buf = RamBuffer(max_samples=20, max_age_seconds=10_000, min_samples_keep=1)
    now = time.time()
    for i in range(10):
        buf.append(_sample(now - 9 + i, float(i)))
    recent = buf.snapshot(seconds=3)
    assert all(s.timestamp >= now - 3 for s in recent)
    limited = buf.snapshot(limit=2)
    assert len(limited) == 2
    incremental = buf.snapshot(since=now - 2)
    assert incremental[0].timestamp > now - 2


def test_clear_empties_ram_only_history():
    buf = RamBuffer(max_samples=10, max_age_seconds=100, min_samples_keep=1)
    buf.append(_sample(1.0))
    buf.clear()
    assert len(buf) == 0
    assert buf.snapshot() == []
