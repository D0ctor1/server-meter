from __future__ import annotations

import pytest

from server_meter.config import AppConfig, ConfigError, load_config
from tests.conftest import test_config


def test_example_mock_yaml_loads(example_yaml):
    cfg = load_config(example_yaml)
    assert cfg.sensor.driver == "mock"
    assert cfg.application.environment == "development"


def test_i2c_address_hex_and_int():
    for raw in (0x76, 0x77, "0x76", "0x77", 118, 119):
        cfg = test_config()
        data = cfg.model_dump()
        data["sensor"]["i2c"]["address"] = raw
        parsed = AppConfig.model_validate(data)
        assert parsed.sensor.i2c.address in {0x76, 0x77}


def test_invalid_i2c_address():
    data = test_config().model_dump()
    data["sensor"]["i2c"]["address"] = 0x50
    with pytest.raises(ConfigError):
        try:
            AppConfig.model_validate(data)
        except Exception as exc:
            raise ConfigError(str(exc)) from exc


def test_production_rejects_change_me():
    data = test_config().model_dump()
    data["application"]["environment"] = "production"
    data["web"]["auth"]["password"] = "CHANGE_ME"
    data["web"]["api_docs_enabled"] = False
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_production_rejects_docs():
    data = test_config().model_dump()
    data["application"]["environment"] = "production"
    data["web"]["auth"]["password"] = "a-real-password"
    data["web"]["api_docs_enabled"] = True
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_production_rejects_auth_disabled():
    data = test_config().model_dump()
    data["application"]["environment"] = "production"
    data["web"]["auth"]["enabled"] = False
    data["web"]["auth"]["password"] = "a-real-password"
    data["web"]["api_docs_enabled"] = False
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_bsec_lp_rejects_one_second_interval():
    data = test_config().model_dump()
    data["sensor"]["interval_seconds"] = 1
    data["sensor"]["bsec"]["enabled"] = True
    data["sensor"]["bsec"]["sample_rate"] = "lp"
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_invalid_port():
    data = test_config().model_dump()
    data["web"]["port"] = 70000
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_threshold_order():
    data = test_config().model_dump()
    data["nagios"]["thresholds"]["ram_usage_warning"] = 90
    data["nagios"]["thresholds"]["ram_usage_critical"] = 80
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_memory_threshold_order():
    data = test_config().model_dump()
    data["memory_protection"]["warning_percent"] = 90
    data["memory_protection"]["critical_percent"] = 80
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_public_status_hides_password():
    cfg = test_config()
    public = cfg.public_status_dict()
    blob = str(public)
    assert "secret123" not in blob
    assert "password" not in blob
    assert public["auth_enabled"] is True


def test_bsec_persist_state_forbidden():
    data = test_config().model_dump()
    data["sensor"]["bsec"]["persist_state"] = True
    with pytest.raises(Exception):
        AppConfig.model_validate(data)


def test_missing_config_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")
