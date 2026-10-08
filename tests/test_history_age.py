"""Dynamic RAM history age: auto = max_samples × interval, timestamps are authority."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.config import (
    AppConfig,
    HistoryConfig,
    theoretical_history_age_seconds,
)
from server_meter.models.measurement import Measurement
from server_meter.service import MeterService
from server_meter.storage.ram_buffer import RamBuffer
from tests.conftest import make_config


@pytest.mark.parametrize(
    ("max_samples", "interval", "expected_seconds", "expected_days"),
    [
        (2_000_000, 5, 10_000_000, 10_000_000 / 86_400),
        (2_000_000, 10, 20_000_000, 20_000_000 / 86_400),
        (1_000_000, 5, 5_000_000, 5_000_000 / 86_400),
        (100_000, 5, 500_000, 500_000 / 86_400),
        (10_000, 5, 50_000, 50_000 / 86_400),
    ],
)
def test_theoretical_max_age_from_samples_and_interval(
    max_samples, interval, expected_seconds, expected_days
):
    age = theoretical_history_age_seconds(max_samples, interval)
    assert age == expected_seconds
    assert age / 86_400 == pytest.approx(expected_days, rel=1e-6)
    data = make_config().model_dump()
    data["history"]["max_samples"] = max_samples
    data["history"]["max_age_seconds"] = None
    data["sensor"]["interval_seconds"] = interval
    data["sensor"]["bsec"]["enabled"] = False
    cfg = AppConfig.model_validate(data)
    assert cfg.history.max_age_seconds is None
    assert cfg.resolved_history_max_age_seconds() == pytest.approx(expected_seconds)


def test_auto_and_omitted_max_age_are_the_same():
    assert HistoryConfig(max_age_seconds="auto").max_age_seconds is None
    assert HistoryConfig(max_age_seconds=None).max_age_seconds is None
    assert HistoryConfig().max_age_seconds is None


def test_explicit_max_age_is_used_for_trim():
    data = make_config().model_dump()
    data["history"]["max_samples"] = 2_000_000
    data["history"]["max_age_seconds"] = 3600
    data["sensor"]["interval_seconds"] = 5
    data["sensor"]["bsec"]["enabled"] = False
    cfg = AppConfig.model_validate(data)
    assert cfg.history.max_age_seconds == 3600
    assert cfg.theoretical_history_max_age_seconds() == pytest.approx(10_000_000)
    assert cfg.resolved_history_max_age_seconds() == 3600
    service = MeterService(cfg)
    assert service.buffer.stats()["max_age_seconds"] == 3600


def test_service_auto_age_matches_interval_times_cap():
    data = make_config().model_dump()
    data["history"]["max_samples"] = 2_000_000
    data["history"]["max_age_seconds"] = None
    data["sensor"]["interval_seconds"] = 5
    data["sensor"]["bsec"]["enabled"] = False
    cfg = AppConfig.model_validate(data)
    service = MeterService(cfg)
    stats = service.history_stats()
    assert stats["max_age_auto"] is True
    assert stats["theoretical_max_age_seconds"] == pytest.approx(10_000_000)
    assert stats["max_age_seconds"] == pytest.approx(10_000_000)


def test_actual_span_uses_timestamps_not_sample_count_times_interval():
    buf = RamBuffer(max_samples=100, max_age_seconds=10_000_000, min_samples_keep=1)
    buf.append(Measurement(timestamp=1_000.0, temperature=1.0))
    buf.append(Measurement(timestamp=1_005.0, temperature=2.0))
    buf.append(Measurement(timestamp=4_000.0, temperature=3.0))
    stats = buf.stats()
    assert stats["actual_span_seconds"] == pytest.approx(3_000.0)
    assert stats["samples"] == 3


def test_restarted_buffer_has_empty_actual_span():
    buf = RamBuffer(max_samples=2_000_000, max_age_seconds=10_000_000, min_samples_keep=1)
    assert buf.stats()["samples"] == 0
    assert buf.stats()["actual_span_seconds"] is None


def test_auto_age_does_not_drop_samples_inside_theoretical_span():
    interval = 5.0
    max_samples = 20
    age = theoretical_history_age_seconds(max_samples, interval)
    buf = RamBuffer(max_samples=max_samples, max_age_seconds=age, min_samples_keep=1)
    now = time.time()
    for i in range(max_samples):
        buf.append(Measurement(timestamp=now - (max_samples - 1 - i) * interval, temperature=float(i)))
    assert len(buf) == max_samples
    assert buf.snapshot()[0].temperature == 0.0


def test_api_all_is_not_capped_at_24h():
    data = make_config().model_dump()
    data["history"]["max_samples"] = 100_000
    data["history"]["max_age_seconds"] = None
    data["sensor"]["interval_seconds"] = 5
    data["sensor"]["bsec"]["enabled"] = False
    cfg = AppConfig.model_validate(data)
    service = MeterService(cfg)
    now = time.time()
    windows = (
        (now - 3 * 86_400, 0.0),
        (now - 36 * 3600, 10.0),
        (now - 600, 20.0),
    )
    for base, offset in windows:
        for i in range(10):
            service.buffer.append(
                Measurement(timestamp=base + i * 5, temperature=offset + i)
            )
    assert len(service.buffer) == 30
    span = service.buffer.stats()["actual_span_seconds"]
    assert span is not None and span > 86_400

    app = create_app(cfg, service=service)
    with TestClient(app) as client:
        auth = ("admin", "secret123")
        all_payload = client.get("/api/history?max_points=720", auth=auth).json()
        day_payload = client.get("/api/history?seconds=86400&max_points=720", auth=auth).json()
        six_payload = client.get("/api/history?seconds=21600&max_points=720", auth=auth).json()
        assert all_payload["count"] == 30
        assert all_payload["samples"][0]["temperature"] == 0.0
        assert all_payload["samples"][-1]["temperature"] == 29.0
        assert day_payload["count"] == 10
        assert day_payload["samples"][0]["temperature"] == 20.0
        assert six_payload["count"] == 10
        assert all_payload["count"] != day_payload["count"]


def test_frontend_all_window_does_not_send_seconds_86400():
    from pathlib import Path

    app_js = (Path(__file__).resolve().parent.parent / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'value="all"' not in app_js
    assert "/api/history?max_points=${MAX_POINTS}" in app_js
    assert "/api/history?seconds=${windowSec}&max_points=${MAX_POINTS}" in app_js
    html = (Path(__file__).resolve().parent.parent / "web" / "index.html").read_text(encoding="utf-8")
    assert 'option value="86400"' in html
    assert 'option value="all"' in html
