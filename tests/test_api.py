from __future__ import annotations

import subprocess

from server_meter.models.measurement import Measurement, SensorStatus

# Keep in sync with install.sh test_api() grep of `curl -D -` output.
_INSTALLER_NAGIOS_GREP = ("grep", "-qiE", r"X-Nagios-Status:[[:space:]]*[0-3]")


def _installer_sees_nagios_header(text: str) -> bool:
    return subprocess.run(_INSTALLER_NAGIOS_GREP, input=text, text=True, check=False).returncode == 0


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
    assert response.headers["x-nagios-status"] == "2"
    assert response.headers["X-Nagios-State"] == "CRITICAL"
    assert response.text.startswith("CRITICAL")
    dumped = "\n".join(f"{key}: {value}" for key, value in response.headers.items())
    assert _installer_sees_nagios_header(dumped)


def test_installer_grep_accepts_uvicorn_lowercase_nagios_headers():
    wire = (
        "HTTP/1.1 200 OK\r\n"
        "content-type: text/plain; charset=utf-8\r\n"
        "x-nagios-status: 3\r\n"
        "x-nagios-state: UNKNOWN\r\n"
        "\r\n"
        "UNKNOWN - sensor state unknown; sensor_age=n/a\n"
    )
    assert _installer_sees_nagios_header(wire)
    assert "X-Nagios-Status:" not in wire  # case-sensitive bash glob would miss this
    title = wire.replace("x-nagios-status", "X-Nagios-Status")
    assert _installer_sees_nagios_header(title)
    assert not _installer_sees_nagios_header("HTTP/1.1 200 OK\n\nUNKNOWN - no header\n")


def test_nagios_evaluation_error_is_unknown(client, auth, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr("server_meter.api.routes.evaluate_nagios", _boom)
    response = client.get("/api/nagios/check", auth=auth)
    assert response.status_code == 200
    assert response.headers["x-nagios-status"] == "3"
    assert response.text.startswith("UNKNOWN")


def test_docs_disabled_in_factory():
    from tests.conftest import make_config
    from server_meter.app import create_app
    from server_meter.service import MeterService
    from fastapi.testclient import TestClient

    cfg = make_config()
    cfg.web.api_docs_enabled = False
    with TestClient(create_app(cfg, MeterService(cfg))) as client:
        assert client.get("/docs").status_code == 404
