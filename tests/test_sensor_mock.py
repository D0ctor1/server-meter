from __future__ import annotations

import pytest

from server_meter.models.measurement import SensorStatus
from server_meter.sensor.bme690 import (
    Bme69xCalib,
    calc_gas_resistance,
    calc_gas_wait,
    calc_humidity,
    calc_temperature,
    parse_calib,
)
from server_meter.sensor.exceptions import SensorUnavailableError
from server_meter.sensor.factory import create_sensor_driver
from server_meter.sensor.mock import MockBme690Driver
from tests.conftest import test_config


def test_factory_mock():
    driver = create_sensor_driver(test_config().sensor)
    assert isinstance(driver, MockBme690Driver)


def test_mock_generates_realistic_ranges():
    driver = MockBme690Driver(test_config().sensor)
    driver.open()
    sample = driver.read()
    assert sample.sensor_status is SensorStatus.OK
    assert 20 <= sample.temperature <= 30
    assert 30 <= sample.humidity <= 70
    assert 990 <= sample.pressure <= 1030
    assert sample.gas_resistance > 1000
    assert sample.iaq is not None
    assert sample.co2_equivalent is not None
    assert sample.breath_voc_equivalent is not None
    driver.close()


def test_mock_can_fail_then_recover():
    driver = MockBme690Driver(test_config().sensor, fail_reads=1)
    driver.open()
    with pytest.raises(SensorUnavailableError):
        driver.read()
    sample = driver.read()
    assert sample.temperature is not None


def test_gas_wait_and_resistance_formulas():
    assert calc_gas_wait(150) < 0xFF
    assert calc_gas_wait(10_000) == 0xFF
    gas = calc_gas_resistance(512, 0)
    assert gas > 0


def test_parse_calib_length():
    with pytest.raises(Exception):
        parse_calib(b"short")


def test_temperature_formula_finite():
    calib = Bme69xCalib(par_t1=1000, par_t2=20000, par_t3=3)
    value = calc_temperature(300_000, calib)
    assert isinstance(value, float)


def test_humidity_clamped():
    calib = Bme69xCalib(par_h1=0, par_h5=0)
    assert calc_humidity(0, 25.0, calib) == 0.0
