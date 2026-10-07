"""Create the configured sensor driver."""

from __future__ import annotations

from server_meter.config import SensorConfig
from server_meter.sensor.base import SensorDriver
from server_meter.sensor.bme690 import Bme690Driver
from server_meter.sensor.bme69x_python import Bme69xPythonDriver
from server_meter.sensor.mock import MockBme690Driver


def create_sensor_driver(config: SensorConfig) -> SensorDriver:
    if config.driver == "mock":
        return MockBme690Driver(config)
    if config.driver == "bme69x_python":
        return Bme69xPythonDriver(config)
    return Bme690Driver(config)
