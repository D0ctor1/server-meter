"""Alarm and notification history is RAM-only and empty after a new process."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from server_meter.alarm_history import ALARM_MAX_RECORDS, AlarmHistory
from server_meter.app import create_app
from server_meter.config import NotificationsConfig
from server_meter.models.measurement import SensorStatus
from server_meter.notification.engine import NotificationEngine
from server_meter.notification.smtp import SmtpError
from server_meter.service import MeterService
from tests.conftest import make_config
from tests.test_notifications import Clock, _sample, _system


def _app(tmp_path, *, password="secret123"):
    cfg = make_config()
    cfg.web.auth.password = password
    cfg.web.users_db = str(tmp_path / "users.db")
    payload = cfg.notifications.model_dump(by_alias=True)
    payload["enabled"] = True
    payload["email"]["enabled"] = True
    payload["email"]["cooldown_seconds"] = 60
    payload["email"]["notify_recovery"] = True
    payload["email"]["from"] = "meter@example.com"
    payload["email"]["to"] = ["admin@example.com"]
    payload["email"]["smtp"]["host"] = "smtp.example.com"
    payload["email"]["smtp"]["password"] = "smtp-secret-value"
    payload["thresholds"]["temperature"]["min_duration_seconds"] = 0
    cfg.notifications = NotificationsConfig.model_validate(payload)
    service = MeterService(cfg)
    return create_app(cfg, service=service), cfg, service


def test_alarm_event_appears_in_history(tmp_path):
    app, cfg, service = _app(tmp_path)
    clock = Clock(1000.0)
    service.notifier = NotificationEngine(cfg, send_fn=lambda *_a, **_k: None, time_fn=clock)
    with TestClient(app) as client:
        service.notifier.set_history(client.app.state.users.alarms)
        service.notifier.observe(_sample(temperature=52.0), _system(), SensorStatus.OK, 1.0)
        first = client.get("/api/alarms/history", auth=("admin", "secret123")).json()
        assert first["persistent"] is False
        assert first["source"] == "ram"
        assert first["alarms"]
        assert first["alarms"][0]["kind"] in {"WARNING", "CRITICAL", "EMAIL_OK"}
        second = client.get("/api/alarms/history", auth=("admin", "secret123")).json()
        assert [row["id"] for row in first["alarms"]] == [row["id"] for row in second["alarms"]]


def test_email_notification_appears_in_history(tmp_path):
    app, cfg, service = _app(tmp_path)
    clock = Clock(1000.0)
    service.notifier = NotificationEngine(cfg, send_fn=lambda *_a, **_k: None, time_fn=clock)
    with TestClient(app) as client:
        service.notifier.set_history(client.app.state.users.alarms)
        service.notifier.observe(_sample(temperature=52.0), _system(), SensorStatus.OK, 1.0)
        kinds = {row["kind"] for row in client.get("/api/alarms/history", auth=("admin", "secret123")).json()["alarms"]}
        assert "EMAIL_OK" in kinds
        assert kinds & {"WARNING", "CRITICAL"}


def test_new_process_history_is_empty_and_does_not_read_sqlite(tmp_path):
    db = tmp_path / "users.db"
    app, cfg, service = _app(tmp_path)
    clock = Clock(1000.0)
    service.notifier = NotificationEngine(cfg, send_fn=lambda *_a, **_k: None, time_fn=clock)
    with TestClient(app) as client:
        service.notifier.set_history(client.app.state.users.alarms)
        service.notifier.observe(_sample(temperature=52.0), _system(), SensorStatus.OK, 1.0)
        assert client.get("/api/alarms/history", auth=("admin", "secret123")).json()["alarms"]
        smtp = cfg.notifications.email.smtp.host
        assert smtp == "smtp.example.com"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS alarm_history ("
            "id INTEGER PRIMARY KEY, created_at REAL, kind TEXT, metric TEXT, "
            "value REAL, unit TEXT, threshold TEXT, duration_seconds INTEGER, hostname TEXT)"
        )
        conn.execute(
            "INSERT INTO alarm_history "
            "(created_at, kind, metric, value, unit, threshold, duration_seconds, hostname) "
            "VALUES (1, 'CRITICAL', 'temperature', 99.0, 'C', 'stale', 1, 'old-host')"
        )
        conn.commit()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()
    assert "users" in tables
    leftover = sqlite3.connect(str(db))
    try:
        leftover_count = leftover.execute("SELECT COUNT(*) FROM alarm_history").fetchone()[0]
    finally:
        leftover.close()
    assert leftover_count == 1
    app2 = create_app(cfg, service=MeterService(cfg))
    with TestClient(app2) as client:
        payload = client.get("/api/alarms/history", auth=("admin", "secret123")).json()
        assert payload["alarms"] == []
        assert payload["persistent"] is False
        assert payload["source"] == "ram"
        users = client.get("/api/admin/users", auth=("admin", "secret123")).json()["users"]
        assert {item["username"] for item in users} == {"admin"}
        settings = client.get("/api/settings", auth=("admin", "secret123")).json()
        assert settings["email"]["smtp"]["host"] == "smtp.example.com"
        assert settings["email"]["smtp"]["password_set"] is True
        assert "smtp-secret-value" not in str(settings)
    still = sqlite3.connect(str(db))
    try:
        still_count = still.execute("SELECT COUNT(*) FROM alarm_history").fetchone()[0]
        still_kind = still.execute("SELECT kind FROM alarm_history").fetchone()[0]
    finally:
        still.close()
    assert still_count == 1
    assert still_kind == "CRITICAL"


def test_history_drops_oldest_at_limit():
    history = AlarmHistory(max_records=50)
    for index in range(60):
        history.append(kind="WARNING", metric="temperature", value=float(index), created_at=float(index))
    rows = history.list_recent(500)
    assert len(history) == 50
    assert len(rows) == 50
    assert rows[-1].value == 10.0
    assert rows[0].value == 59.0


def test_alarm_can_fire_again_after_restart(tmp_path):
    app, cfg, service = _app(tmp_path)
    clock = Clock(1000.0)
    service.notifier = NotificationEngine(cfg, send_fn=lambda *_a, **_k: None, time_fn=clock)
    with TestClient(app) as client:
        service.notifier.set_history(client.app.state.users.alarms)
        service.notifier.observe(_sample(temperature=52.0), _system(), SensorStatus.OK, 1.0)
        assert client.get("/api/alarms/history", auth=("admin", "secret123")).json()["alarms"]
    app2 = create_app(cfg, service=MeterService(cfg))
    clock2 = Clock(2000.0)
    app2.state.service.notifier = NotificationEngine(cfg, send_fn=lambda *_a, **_k: None, time_fn=clock2)
    with TestClient(app2) as client:
        empty = client.get("/api/alarms/history", auth=("admin", "secret123")).json()["alarms"]
        assert empty == []
        app2.state.service.notifier.set_history(client.app.state.users.alarms)
        app2.state.service.notifier.observe(_sample(temperature=52.0), _system(), SensorStatus.OK, 1.0)
        rows = client.get("/api/alarms/history", auth=("admin", "secret123")).json()["alarms"]
        assert rows
        assert rows[0]["metric"] == "temperature"


def test_smtp_failure_stays_in_ram_and_does_not_crash(tmp_path):
    app, cfg, service = _app(tmp_path)

    def boom(*_a, **_k):
        raise SmtpError("SMTP host is not configured")

    clock = Clock(1000.0)
    service.notifier = NotificationEngine(cfg, send_fn=boom, time_fn=clock)
    with TestClient(app) as client:
        service.notifier.set_history(client.app.state.users.alarms)
        service.notifier.observe(_sample(temperature=52.0), _system(), SensorStatus.OK, 1.0)
        payload = client.get("/api/alarms/history", auth=("admin", "secret123")).json()
        kinds = {row["kind"] for row in payload["alarms"]}
        assert "EMAIL_FAIL" in kinds
        assert service.notifier.last_delivery_error
        raw = Path(tmp_path / "users.db").read_bytes()
        assert b"EMAIL_FAIL" not in raw
        assert b"smtp-secret-value" not in raw
        assert client.get("/api/status", auth=("admin", "secret123")).status_code == 200


def test_smtp_error_with_password_still_records_in_ram():
    history = AlarmHistory()
    history.append(
        kind="EMAIL_FAIL",
        metric="temperature",
        value=None,
        threshold="535 Username and Password not accepted",
        hostname="secret-host",
    )
    rows = history.list_recent()
    assert len(rows) == 1
    assert rows[0].kind == "EMAIL_FAIL"
    assert "password" not in rows[0].threshold.lower()
    assert rows[0].hostname == ""
    history.append(kind="password", metric="temperature", value=1.0)
    assert len(history) == 1


def test_sensor_history_stays_in_ram_and_empty_after_new_process(tmp_path):
    app, cfg, service = _app(tmp_path)
    service.buffer.append(_sample(temperature=24.0))
    with TestClient(app) as client:
        hist = client.get("/api/history", auth=("admin", "secret123")).json()
        assert hist["source"] == "ram"
        assert hist["persistent"] is False
        assert hist["count"] == 1
    app2 = create_app(cfg, service=MeterService(cfg))
    with TestClient(app2) as client:
        hist = client.get("/api/history", auth=("admin", "secret123")).json()
        assert hist["count"] == 0
        assert hist["source"] == "ram"
        assert hist["persistent"] is False
        alarms = client.get("/api/alarms/history", auth=("admin", "secret123")).json()
        assert alarms["alarms"] == []


def test_frontend_does_not_cache_alarm_history():
    root = Path(__file__).resolve().parent.parent
    app_js = (root / "web" / "js" / "app.js").read_text(encoding="utf-8")
    index = (root / "web" / "index.html").read_text(encoding="utf-8")
    assert "localStorage" not in app_js
    assert "indexedDB" not in app_js
    assert "renderAlarmHistory" in app_js
    assert "body.innerHTML = \"\"" in app_js or "body.innerHTML = ''" in app_js
    assert 'data-i18n="dashboard.alarm_history_hint"' in index
    assert "alarms.empty" in app_js
    assert "email_fail" in app_js
    assert ALARM_MAX_RECORDS == 500
