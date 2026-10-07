"""Optional adapter for the community BME69x Python wrapper (BSEC 3.2.1.0).

This is NOT bundled. If the operator compiled
https://github.com/mcalisterkm/bme69x-python-library-bsec3.2.1.0 against a
Bosch BSEC 3.x zip, `from bme69x import BME69X` becomes available.

We never call save-state helpers from that library.
"""

from __future__ import annotations

import logging
import time

from server_meter.config import SensorConfig
from server_meter.models.measurement import Measurement, SensorStatus
from server_meter.sensor.base import SensorDriver
from server_meter.sensor.exceptions import SensorUnavailableError

logger = logging.getLogger("server_meter.bme69x_python")


class Bme69xPythonDriver(SensorDriver):
    name = "bme69x_python"

    def __init__(self, config: SensorConfig) -> None:
        self._config = config
        self._dev = None
        self._opened = False

    def open(self) -> None:
        try:
            from bme69x import BME69X
        except ImportError as exc:
            raise SensorUnavailableError(
                "Python module bme69x is not installed. Build it against Bosch BSEC 3.2+ "
                "or use sensor.driver: bme690"
            ) from exc
        # Signature from the 3.2.1.0 wrapper: BME69X(i2c_addr, i2c_bus, sensor_id)
        self._dev = BME69X(self._config.i2c.address, self._config.i2c.bus, 0)
        try:
            self._dev.set_heatr_conf(1, self._config.heater_temperature_c, self._config.heater_duration_ms, 1)
        except Exception as exc:
            raise SensorUnavailableError(f"bme69x set_heatr_conf failed: {exc}") from exc
        self._opened = True
        logger.info("bme69x Python wrapper opened (BSEC state will not be saved to disk)")

    def close(self) -> None:
        self._dev = None
        self._opened = False

    def describe(self) -> dict[str, object]:
        return {
            "driver": self.name,
            "chip": "BME690",
            "wrapper": "bme69x",
            "i2c_address": hex(self._config.i2c.address),
            "opened": self._opened,
        }

    def read(self) -> Measurement:
        if self._dev is None:
            raise SensorUnavailableError("bme69x wrapper is not open")
        try:
            data = self._dev.get_data()
        except Exception as exc:
            raise SensorUnavailableError(f"bme69x get_data failed: {exc}") from exc
        if not isinstance(data, dict):
            raise SensorUnavailableError("bme69x get_data returned no sample")
        pressure = data.get("raw_pressure")
        if pressure is not None and pressure > 2000:
            pressure = pressure / 100.0
        temperature = data.get("temperature", data.get("raw_temperature"))
        humidity = data.get("humidity", data.get("raw_humidity"))
        return Measurement(
            timestamp=time.time(),
            temperature=_f(temperature),
            pressure=_f(pressure),
            humidity=_f(humidity),
            gas_resistance=_f(data.get("raw_gas")),
            iaq=_f(data.get("iaq")),
            iaq_accuracy=_i(data.get("iaq_accuracy")),
            static_iaq=_f(data.get("static_iaq")),
            static_iaq_accuracy=_i(data.get("static_iaq_accuracy")),
            co2_equivalent=_f(data.get("co2_equivalent")),
            co2_accuracy=_i(data.get("co2_accuracy")),
            breath_voc_equivalent=_f(data.get("breath_voc_equivalent")),
            breath_voc_accuracy=_i(data.get("breath_voc_accuracy")),
            gas_percentage=_f(data.get("gas_percentage")),
            gas_percentage_accuracy=_i(data.get("gas_percentage_accuracy")),
            tvoc_equivalent=_f(data.get("tvoc") or data.get("tvoc_equivalent")),
            tvoc_accuracy=_i(data.get("tvoc_accuracy")),
            raw_temperature=_f(data.get("raw_temperature")),
            raw_humidity=_f(data.get("raw_humidity")),
            raw_pressure=_f(pressure),
            stabilization_status=_i(data.get("stabilization_status")),
            run_in_status=_i(data.get("run_in_status")),
            sensor_status=SensorStatus.OK,
        )


def _f(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
