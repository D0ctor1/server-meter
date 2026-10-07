from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.config import AppConfig
from server_meter.service import MeterService


def test_config(**overrides) -> AppConfig:
    data = {
        "application": {"name": "server-meter", "environment": "test"},
        "web": {
            "host": "127.0.0.1",
            "port": 8080,
            "api_docs_enabled": True,
            "auth": {"enabled": True, "username": "admin", "password": "secret123"},
        },
        "sensor": {
            "type": "BME690",
            "driver": "mock",
            "interval_seconds": 5,
            "bsec": {"enabled": False},
        },
        "history": {"max_samples": 100, "max_age_seconds": 3600, "min_samples_keep": 8},
        "memory_protection": {
            "enabled": True,
            "warning_percent": 70,
            "critical_percent": 80,
            "emergency_percent": 90,
        },
        "nagios": {
            "enabled": True,
            "sensor_max_age_seconds": 30,
            "thresholds": {
                "cpu_temperature_warning": 70,
                "cpu_temperature_critical": 80,
                "ram_usage_warning": 70,
                "ram_usage_critical": 85,
            },
        },
        "logging": {"level": "WARNING", "access_log": False},
    }
    data.update(overrides)
    return AppConfig.model_validate(data)


@pytest.fixture
def config() -> AppConfig:
    return test_config()


@pytest.fixture
def service(config: AppConfig) -> MeterService:
    svc = MeterService(config)
    return svc


@pytest.fixture
def client(config: AppConfig, service: MeterService):
    app = create_app(config, service=service)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth() -> tuple[str, str]:
    return ("admin", "secret123")


@pytest.fixture
def example_yaml() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "config.mock.yaml"
