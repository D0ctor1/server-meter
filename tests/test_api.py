from __future__ import annotations

from server_meter.models.measurement import Measurement, SensorStatus


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_endpoints_require_auth(client):
    for path in ("/api/status", "/api/current", "/api/history", "/api/system", "/api/sensor", "/api/nagios/check"):
        response = client.get(path)
        assert response.status_code == 401, path


def test_status_hides_secrets(client, auth):
    response = client.get("/api/status", auth=auth)
    assert response.status_code == 200
    body = response.text
    assert "secret123" not in body
    payload = response.json()
    assert "password" not in payload["application"]
    assert payload["application"]["auth_enabled"] is True
    assert payload["application"]["default_password_active"] is False
    assert payload["history"]["samples"] >= 0


def test_current_and_history_from_ram(client, auth, service):
    service.current = Measurement(
        timestamp=1_700_000_000.0,
        temperature=24.2,
        pressure=1008.2,
        humidity=45.3,
        gas_resistance=123456.0,
        iaq=42.1,
        iaq_accuracy=3,
        co2_equivalent=600.0,
        breath_voc_equivalent=0.4,
        sensor_status=SensorStatus.OK,
    )
    service.buffer.append(service.current)
    service.sensor_status = SensorStatus.OK
    current = client.get("/api/current", auth=auth).json()
    assert current["temperature"] == 24.2
    assert current["eco2"] == 600.0
    assert current["bvoc"] == 0.4
    history = client.get("/api/history?limit=10", auth=auth).json()
    assert history["source"] == "ram"
    assert history["persistent"] is False
    assert history["count"] == 1


def test_history_since_and_seconds(client, auth, service):
    for ts in (100.0, 200.0, 300.0):
        service.buffer.append(Measurement(timestamp=ts, temperature=ts / 10.0))
    payload = client.get("/api/history?since=150", auth=auth).json()
    assert [s["timestamp"] for s in payload["samples"]] == [200.0, 300.0]


def test_sensor_unavailable_does_not_fail_api(client, auth, service):
    service.sensor_status = SensorStatus.UNAVAILABLE
    service.current = None
    response = client.get("/api/sensor", auth=auth)
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    current = client.get("/api/current", auth=auth)
    assert current.status_code == 200
    assert current.json()["available"] is False


def test_nagios_headers(client, auth, service):
    service.sensor_status = SensorStatus.UNAVAILABLE
    service.current = None
    response = client.get("/api/nagios/check", auth=auth)
    assert response.status_code == 200
    assert response.headers["X-Nagios-Status"] == "2"
    assert response.text.startswith("CRITICAL")


def test_docs_disabled_in_factory():
    from tests.conftest import make_config
    from server_meter.app import create_app
    from server_meter.service import MeterService
    from fastapi.testclient import TestClient

    cfg = make_config()
    cfg.web.api_docs_enabled = False
    with TestClient(create_app(cfg, MeterService(cfg))) as client:
        assert client.get("/docs").status_code == 404
