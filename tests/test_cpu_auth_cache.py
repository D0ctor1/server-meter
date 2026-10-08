"""Regression tests: Argon2 must not run on every dashboard/Nagios poll."""

from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.service import MeterService
from server_meter.users import UserStore
from tests.conftest import make_config


def test_repeated_authenticate_does_not_rehash_argon2(tmp_path):
    store = UserStore(str(tmp_path / "users.db"), test=False)
    try:
        store.create("admin", "secret123", "admin")
        real = store._verify
        calls = {"n": 0}

        def wrapped(password_hash, password):
            calls["n"] += 1
            return real(password_hash, password)

        store._verify = wrapped  # type: ignore[method-assign]
        assert store.authenticate("admin", "secret123") is not None
        first = calls["n"]
        assert first >= 1
        t0 = time.perf_counter()
        for _ in range(40):
            assert store.authenticate("admin", "secret123") is not None
        cached_s = time.perf_counter() - t0
        assert calls["n"] == first
        stats = store.auth_cache_stats()
        assert stats["hits"] >= 40
        assert cached_s < 0.05
    finally:
        store.close()


def test_password_change_invalidates_auth_cache(tmp_path):
    store = UserStore(str(tmp_path / "users.db"), test=False)
    try:
        user = store.create("admin", "secret123", "admin")
        assert store.authenticate("admin", "secret123") is not None
        store.update(user.id, password="newpass12")
        assert store.authenticate("admin", "secret123") is None
        assert store.authenticate("admin", "newpass12") is not None
    finally:
        store.close()


def test_failed_password_is_not_cached_as_success(tmp_path):
    store = UserStore(str(tmp_path / "users.db"), test=False)
    try:
        store.create("admin", "secret123", "admin")
        assert store.authenticate("admin", "wrongpass") is None
        assert store.authenticate("admin", "wrongpass") is None
        assert store.authenticate("admin", "secret123") is not None
    finally:
        store.close()


def test_http_polling_pattern_hits_auth_cache(tmp_path):
    cfg = make_config()
    cfg.web.users_db = str(tmp_path / "users.db")
    app = create_app(cfg, MeterService(cfg))
    with TestClient(app) as client:
        auth = ("admin", "secret123")
        store: UserStore = client.app.state.users
        real = store._verify
        calls = {"n": 0}

        def wrapped(password_hash, password):
            calls["n"] += 1
            return real(password_hash, password)

        store._verify = wrapped  # type: ignore[method-assign]
        assert client.get("/api/status", auth=auth).status_code == 200
        after_first = calls["n"]
        for _ in range(12):
            assert client.get("/api/status", auth=auth).status_code == 200
            assert client.get("/api/current", auth=auth).status_code == 200
            assert client.get("/api/monitoring", auth=auth).status_code == 200
        assert calls["n"] == after_first
        assert store.auth_cache_stats()["hits"] >= 30


def test_status_does_not_read_sensor_hardware(tmp_path, auth):
    cfg = make_config()
    cfg.web.users_db = str(tmp_path / "users.db")
    service = MeterService(cfg)
    reads = {"n": 0}
    original = service.driver.read

    def counted():
        reads["n"] += 1
        return original()

    service.driver.read = counted  # type: ignore[method-assign]
    app = create_app(cfg, service=service)
    with TestClient(app) as client:
        before = reads["n"]
        assert client.get("/api/status", auth=auth).status_code == 200
        assert client.get("/api/current", auth=auth).status_code == 200
        assert client.get("/api/monitoring", auth=auth).status_code == 200
        assert client.get("/api/system", auth=auth).status_code == 200
        assert reads["n"] == before


def test_start_background_starts_one_sensor_and_one_smtp_task():
    cfg = make_config()
    service = MeterService(cfg)

    async def _run():
        service.start_background()
        sensor = service._task
        smtp = service.notifier._task
        service.start_background()
        assert service._task is sensor
        assert service.notifier._task is smtp
        assert sensor is not None and not sensor.done()
        assert smtp is not None and not smtp.done()
        await service.shutdown()

    asyncio.run(_run())


def test_dashboard_polling_does_not_reopen_settings_every_tick():
    from pathlib import Path
    import re

    app_js = (Path(__file__).resolve().parent.parent / "web" / "js" / "app.js").read_text(encoding="utf-8")
    settings_js = (Path(__file__).resolve().parent.parent / "web" / "js" / "settings.js").read_text(encoding="utf-8")
    assert "lastRole" in app_js
    assert re.search(r"if \(state\.lastRole !== role\)", app_js)
    assert "if (overlayOpen) return false;" in settings_js
    assert "changed && wantsSettingsFromUrl()" in settings_js
