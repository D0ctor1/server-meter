from __future__ import annotations

import time
import tracemalloc

from server_meter.config import HISTORY_HARD_MAX_SAMPLES
from server_meter.models.measurement import Measurement
from server_meter.storage.ram_buffer import RamBuffer, even_indices


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


def test_history_never_exceeds_max_samples():
    buf = RamBuffer(max_samples=1000, max_age_seconds=10_000, min_samples_keep=1)
    for i in range(2500):
        buf.append(_sample(float(i), float(i)))
    assert len(buf) == 1000
    assert buf.snapshot()[0].temperature == 1500.0
    assert buf.snapshot()[-1].temperature == 2499.0


def test_hard_max_caps_config():
    buf = RamBuffer(max_samples=HISTORY_HARD_MAX_SAMPLES * 4, max_age_seconds=10, min_samples_keep=8)
    assert buf.max_samples == HISTORY_HARD_MAX_SAMPLES
    assert buf.max_samples == 2_000_000


def test_empty_buffer_does_not_preallocate_two_million():
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    buf = RamBuffer(max_samples=2_000_000, max_age_seconds=10_000, min_samples_keep=1)
    buf.append(_sample(1.0, 20.0))
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    assert len(buf) == 1
    assert after - before < 2_000_000


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


def test_new_buffer_starts_empty_after_restart():
    buf = RamBuffer(max_samples=2_000_000, max_age_seconds=86_400, min_samples_keep=64)
    assert len(buf) == 0
    assert buf.snapshot() == []
    assert buf.stats()["samples"] == 0
    assert buf.stats()["max_samples"] == 2_000_000


def test_even_indices_include_ends():
    idx = even_indices(1000, 10)
    assert idx[0] == 0
    assert idx[-1] == 999
    assert len(idx) == 10
    assert idx == sorted(set(idx))


def test_snapshot_even_downsample_keeps_shape_ends():
    buf = RamBuffer(max_samples=100, max_age_seconds=10_000, min_samples_keep=1)
    for i in range(100):
        buf.append(_sample(1000 + i, float(i)))
    snap = buf.snapshot(max_points=10)
    assert len(snap) == 10
    assert snap[0].temperature == 0.0
    assert snap[-1].temperature == 99.0


def test_snapshot_limit_does_not_copy_unneeded_tail_only():
    buf = RamBuffer(max_samples=500, max_age_seconds=10_000, min_samples_keep=1)
    for i in range(400):
        buf.append(_sample(float(i), float(i)))
    snap = buf.snapshot(limit=5)
    assert [s.temperature for s in snap] == [395.0, 396.0, 397.0, 398.0, 399.0]


def test_snapshot_max_points_wins_over_limit():
    buf = RamBuffer(max_samples=50, max_age_seconds=10_000, min_samples_keep=1)
    for i in range(40):
        buf.append(_sample(float(i), float(i)))
    snap = buf.snapshot(limit=5, max_points=4)
    assert len(snap) == 4
    assert snap[0].temperature == 0.0
    assert snap[-1].temperature == 39.0


def test_append_stays_fast_when_ring_is_full():
    n = 20_000
    buf = RamBuffer(max_samples=n, max_age_seconds=1e9, min_samples_keep=1)
    t0 = time.perf_counter()
    for i in range(n):
        buf.append(_sample(float(i), float(i)))
    fill_s = time.perf_counter() - t0
    t1 = time.perf_counter()
    for i in range(n, n * 2):
        buf.append(_sample(float(i), float(i)))
    wrap_s = time.perf_counter() - t1
    assert len(buf) == n
    assert fill_s < 3.0
    assert wrap_s < fill_s * 4 + 0.5
