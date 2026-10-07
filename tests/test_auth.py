from __future__ import annotations

from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.service import MeterService
from tests.conftest import make_config


def test_wrong_password(client):
    response = client.get("/api/status", auth=("admin", "wrong"))
    assert response.status_code == 401


def test_wrong_user(client):
    response = client.get("/api/status", auth=("root", "secret123"))
    assert response.status_code == 401


def test_auth_can_be_disabled_outside_production():
    cfg = make_config()
    cfg.web.auth.enabled = False
    with TestClient(create_app(cfg, MeterService(cfg))) as client:
        assert client.get("/api/status").status_code == 200


def test_ui_requires_auth(client):
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("admin", "secret123")).status_code == 200
