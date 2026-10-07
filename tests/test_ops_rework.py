from __future__ import annotations

from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.config import NotificationsConfig
from server_meter.models.measurement import Measurement, SensorStatus
from server_meter.notification.engine import NotificationEngine
from server_meter.service import MeterService
from server_meter.storage.ram_buffer import RamBuffer
from tests.conftest import make_config
from tests.test_notifications import Clock, _sample, _system


def _client(tmp_path):
    cfg = make_config()
    cfg.web.users_db = str(tmp_path / "users.db")
    service = MeterService(cfg)
    return TestClient(create_app(cfg, service=service)), cfg, service


def test_health_is_liveness_only(tmp_path):
    client, _cfg, _service = _client(tmp_path)
    with client:
        payload = client.get("/api/health").json()
        assert payload["status"] == "healthy"
        assert "temperature_c" not in payload
        assert "sensor_age_seconds" not in payload


def test_status_system_health_and_ram_stats(tmp_path, auth):
    client, _cfg, service = _client(tmp_path)
    service.current = Measurement(timestamp=1_700_000_000.0, temperature=24.2, iaq=40.0)
    service.sensor_status = SensorStatus.OK
    service.stats.last_success_at = 1_700_000_000.0
    service.buffer.append(service.current)
    with client:
        status = client.get("/api/status", auth=auth).json()
        assert "system_health" in status
        assert status["system_health"]["overall"] in {"ok", "warning", "critical", "unknown"}
        assert status["system_health"]["items"]["bme690"]["status"]
        assert status["system_health"]["items"]["i2c"]["bus"].startswith("/dev/i2c-")
        assert status["history"]["memory_bytes"] >= 0
        assert "oldest_age_seconds" in status["history"]
        monitoring = client.get("/api/monitoring", auth=auth).json()
        assert "sensor_age_seconds" in monitoring
        assert monitoring["temperature_c"] == 24.2
        blob = str(monitoring)
        assert "teplota" not in blob.lower()


def test_export_redacts_secrets(tmp_path, auth):
    client, cfg, _service = _client(tmp_path)
    cfg.web.auth.password = "super-secret-pass"
    cfg.notifications.email.smtp.password = "smtp-secret-value"
    with client:
        response = client.get("/api/admin/export", auth=auth)
        assert response.status_code == 200
        body = response.text
        assert "super-secret-pass" not in body
        assert "smtp-secret-value" not in body
        assert "REDACTED" in body
        payload = response.json()
        assert payload["config"]["web"]["auth"]["password"] == "REDACTED"


def test_monitoring_token_reads_monitoring_not_admin(tmp_path, auth):
    client, _cfg, _service = _client(tmp_path)
    with client:
        created = client.post("/api/admin/monitoring-token", auth=auth)
        assert created.status_code == 200
        token = created.json()["token"]
        assert token.startswith("sm_")
        ok = client.get("/api/monitoring", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
        assert "temperature_c" in ok.json()
        forbidden = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert forbidden.status_code == 403
        status = client.get("/api/status", headers={"X-Monitoring-Token": token})
        assert status.status_code == 403
        basic = client.get("/api/monitoring", auth=auth)
        assert basic.status_code == 200
        revoked = client.delete("/api/admin/monitoring-token", auth=auth)
        assert revoked.status_code == 200
        denied = client.get("/api/monitoring", headers={"Authorization": f"Bearer {token}"})
        assert denied.status_code == 401


def test_alarm_history_records_state_changes(tmp_path, auth):
    client, cfg, service = _client(tmp_path)
    payload = cfg.notifications.model_dump(by_alias=True)
    payload["thresholds"]["temperature"]["min_duration_seconds"] = 0
    cfg.notifications = NotificationsConfig.model_validate(payload)
    clock = Clock(1000.0)
    service.notifier = NotificationEngine(cfg, send_fn=lambda *_a, **_k: None, time_fn=clock)
    service.notifier.set_history(client.app.state.users.alarms)
    with client:
        service.notifier.observe(_sample(temperature=52.0), _system(), SensorStatus.OK, 1.0)
        rows = client.get("/api/alarms/history", auth=auth).json()["alarms"]
        assert rows
        assert rows[0]["kind"] in {"WARNING", "CRITICAL"}
        assert rows[0]["metric"] == "temperature"
        assert "password" not in str(rows).lower()
        blob = client.get("/api/admin/export", auth=auth).text.lower()
        assert "sm_" not in blob or "redacted" in blob


def test_stale_sensor_age_is_exposed(tmp_path, auth):
    client, cfg, service = _client(tmp_path)
    service.current = Measurement(timestamp=1.0, temperature=24.0)
    service.sensor_status = SensorStatus.OK
    service.stats.last_success_at = 1.0
    with client:
        payload = client.get("/api/monitoring", auth=auth).json()
        assert payload["sensor_age_seconds"] is not None
        assert payload["sensor_age_seconds"] > cfg.nagios.sensor_max_age_seconds
        health = client.get("/api/status", auth=auth).json()["system_health"]
        assert health["items"]["sensor_data"]["status"] == "critical"


def test_ram_buffer_stats_include_memory(tmp_path):
    buf = RamBuffer(max_samples=10, max_age_seconds=100, min_samples_keep=1)
    buf.append(Measurement(timestamp=10.0, temperature=21.0))
    stats = buf.stats()
    assert stats["samples"] == 1
    assert stats["memory_bytes"] == 480
    assert stats["newest_timestamp"] == 10.0


def test_admin_system_info(tmp_path, auth):
    client, _cfg, _service = _client(tmp_path)
    with client:
        info = client.get("/api/admin/system", auth=auth)
        assert info.status_code == 200
        payload = info.json()
        assert "application_version" in payload
        assert "python_version" in payload
        assert payload["i2c_bus"].startswith("/dev/i2c-")
        assert payload["bme690_address"] in {"0x76", "0x77"}
