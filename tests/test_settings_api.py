from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.config import load_config
from server_meter.notification.smtp import SmtpError
from server_meter.service import MeterService
from tests.conftest import make_config


def _client(tmp_path, **notify):
    data = make_config().model_dump(by_alias=True)
    data["notifications"]["email"]["smtp"]["password"] = "smtp-secret-value"
    data["notifications"]["email"]["smtp"]["host"] = "smtp.example.com"
    data["notifications"]["email"]["smtp"]["username"] = "meter@example.com"
    data["notifications"]["email"]["from"] = "meter@example.com"
    data["notifications"]["email"]["to"] = ["admin@example.com"]
    data["notifications"].update(notify)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    cfg = load_config(path)
    service = MeterService(cfg)
    return TestClient(create_app(cfg, service=service)), cfg


def test_settings_and_monitoring_require_auth(tmp_path):
    client, _cfg = _client(tmp_path)
    with client:
        assert client.get("/api/settings").status_code == 401
        assert client.put("/api/settings", json={"enabled": True}).status_code == 401
        assert client.post("/api/settings/test-email").status_code == 401
        assert client.get("/api/monitoring").status_code == 401


def test_settings_hides_smtp_password(tmp_path, auth):
    client, _cfg = _client(tmp_path)
    with client:
        response = client.get("/api/settings", auth=auth)
        assert response.status_code == 200
        body = response.text
        assert "smtp-secret-value" not in body
        payload = response.json()
        assert "password" not in payload["email"]["smtp"]
        assert payload["email"]["smtp"]["password_set"] is True
        assert payload["email"]["smtp"]["host"] == "smtp.example.com"


def test_settings_put_keeps_password_when_blank(tmp_path, auth):
    client, cfg = _client(tmp_path)
    with client:
        payload = client.get("/api/settings", auth=auth).json()
        payload["email"]["smtp"]["password"] = ""
        payload["email"]["smtp"]["host"] = "smtp.other.example"
        payload["enabled"] = True
        saved = client.put("/api/settings", auth=auth, json=payload)
        assert saved.status_code == 200
        assert "smtp-secret-value" not in saved.text
        assert saved.json()["email"]["smtp"]["host"] == "smtp.other.example"
        assert saved.json()["email"]["smtp"]["password_set"] is True
        reloaded = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
        assert reloaded["notifications"]["email"]["smtp"]["password"] == "smtp-secret-value"
        assert cfg.notifications.email.smtp.password == "smtp-secret-value"
        history = yaml.safe_dump(reloaded)
        assert "temperature:" in history  # config, not samples
        assert "samples:" not in history


def test_monitoring_is_language_neutral(tmp_path, auth):
    client, cfg = _client(tmp_path)
    cfg.web.locale = "CZ"
    with client:
        payload = client.get("/api/monitoring", auth=auth).json()
        blob = str(payload)
        assert "teplota" not in blob.lower()
        assert payload["overall"] in {"OK", "WARNING", "CRITICAL", "UNKNOWN"}
        assert "temperature" in payload["sensor"]
        assert "cpu_temperature" in payload["system"]
        assert "thresholds" in payload
        assert payload["thresholds"]["temperature"]["warning_high"] == 45
        assert "password" not in blob


def test_test_email_returns_smtp_error_without_password(tmp_path, auth, monkeypatch):
    client, cfg = _client(tmp_path)

    def boom(_message, _config):
        raise SmtpError("SMTP authentication failed")

    cfg.web.locale = "CZ"
    with client:
        client.app.state.service.notifier._send = boom
        result = client.post("/api/settings/test-email", auth=auth).json()
        assert result["ok"] is False
        assert "smtp-secret-value" not in str(result)
        assert "authentication failed" in result["error"].lower() or "SMTP" in result["error"]
