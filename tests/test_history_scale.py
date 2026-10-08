"""Safe scale tests for a 2_000_000-sample RAM ring.

The full 2M fill runs only when the process has enough free RAM so a
developer laptop / CI runner cannot be OOM-killed by this file.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.config import HISTORY_HARD_MAX_SAMPLES, AppConfig
from server_meter.models.measurement import Measurement
from server_meter.service import MeterService
from server_meter.storage.ram_buffer import RamBuffer
from tests.conftest import make_config

CHECKPOINTS = (100_000, 500_000, 1_000_000, 2_000_000)
# Typical live BME690 + BSEC sample (TVOC, no bVOC on 3.3 IAQ).
_SAMPLE_KW = dict(
    temperature=24.2,
    pressure=1008.4,
    humidity=45.1,
    gas_resistance=120000.0,
    iaq=42.0,
    iaq_accuracy=3,
    static_iaq=40.0,
    static_iaq_accuracy=3,
    co2_equivalent=610.0,
    co2_accuracy=3,
    tvoc_equivalent=125.0,
    tvoc_accuracy=3,
    cpu_temperature=47.0,
    cpu_load=0.21,
    ram_usage=31.0,
)


def _rss_bytes() -> int:
    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


def _avail_bytes() -> int:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
    except (ValueError, OSError):
        return 0


def _sample(ts: float) -> Measurement:
    return Measurement(timestamp=ts, **_SAMPLE_KW)


def test_hard_max_constant():
    assert HISTORY_HARD_MAX_SAMPLES == 2_000_000


@pytest.mark.skipif(
    os.environ.get("SKIP_HISTORY_SCALE") == "1",
    reason="SKIP_HISTORY_SCALE=1",
)
def test_fill_two_million_samples_safely(tmp_path):
    avail = _avail_bytes()
    # ~1 GB history + headroom for OS copies during downsample.
    if avail and avail < 1_500_000_000:
        pytest.skip(f"only {avail} bytes free; refusing 2M fill")

    buf = RamBuffer(max_samples=2_000_000, max_age_seconds=10_000_000, min_samples_keep=64)
    assert len(buf) == 0

    before = _rss_bytes()
    stats: dict[int, dict[str, float | int]] = {}
    t_origin = time.perf_counter()
    next_ts = 0
    for target in CHECKPOINTS:
        t0 = time.perf_counter()
        cpu0 = time.process_time()
        for i in range(next_ts, target):
            buf.append(_sample(float(i)))
        elapsed = time.perf_counter() - t0
        cpu = time.process_time() - cpu0
        rss = _rss_bytes()
        stats[target] = {
            "count": len(buf),
            "elapsed_s": elapsed,
            "cpu_s": cpu,
            "rss_bytes": rss,
            "rss_delta_bytes": max(0, rss - before),
            "bytes_per_sample": (rss - before) / target if rss > before else 0,
        }
        next_ts = target
        assert len(buf) == target

    assert len(buf) == 2_000_000
    oldest_before = buf.snapshot(limit=1)[0].timestamp
    buf.append(_sample(2_000_000.0))
    assert len(buf) == 2_000_000
    assert buf.snapshot(limit=1)[0].timestamp > oldest_before

    t_down = time.perf_counter()
    down = buf.snapshot(max_points=720)
    downsample_s = time.perf_counter() - t_down
    assert len(down) == 720
    assert down[0].timestamp == buf.oldest_timestamp()
    assert down[-1].timestamp == buf.newest_timestamp()

    t_tail = time.perf_counter()
    tail = buf.snapshot(limit=2000)
    tail_s = time.perf_counter() - t_tail
    assert len(tail) == 2000

    data = make_config().model_dump()
    data["history"]["max_samples"] = 2_000_000
    data["history"]["max_age_seconds"] = 10_000_000
    cfg = AppConfig.model_validate(data)
    service = MeterService(cfg)
    service.buffer = buf
    app = create_app(cfg, service=service)
    with TestClient(app) as client:
        t_api = time.perf_counter()
        payload = client.get(
            "/api/history?max_points=720",
            auth=("admin", "secret123"),
        ).json()
        api_s = time.perf_counter() - t_api
        unbounded = client.get("/api/history", auth=("admin", "secret123")).json()

    assert payload["count"] == 720
    assert payload["persistent"] is False
    assert unbounded["count"] == 2000
    assert unbounded["count"] < 2_000_000

    total_s = time.perf_counter() - t_origin
    rss_2m = int(stats[2_000_000]["rss_delta_bytes"])
    # Must stay well under a 4 GB Pi after OS/Uvicorn/BSEC (~1.5–2 GB budget).
    assert rss_2m < 2_500_000_000
    assert downsample_s < 5.0
    assert tail_s < 1.0
    assert api_s < 5.0

    report = tmp_path / "history-scale-report.txt"
    lines = [
        f"rss_before={before}",
        f"total_s={total_s:.3f}",
        f"downsample_720_s={downsample_s:.3f}",
        f"tail_2000_s={tail_s:.3f}",
        f"api_max_points_720_s={api_s:.3f}",
        f"api_default_count={unbounded['count']}",
    ]
    for n, row in stats.items():
        lines.append(
            f"n={n} count={row['count']} elapsed_s={row['elapsed_s']:.3f} "
            f"cpu_s={row['cpu_s']:.3f} rss_delta={row['rss_delta_bytes']} "
            f"bytes_per_sample={row['bytes_per_sample']:.1f}"
        )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
