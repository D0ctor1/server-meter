"""Deterministic mock BME690/BSEC driver for development and tests. RAM-only."""

from __future__ import annotations

import math
import time

from server_meter.config import SensorConfig
from server_meter.models.measurement import Measurement, SensorStatus
from server_meter.sensor.base import SensorDriver


class MockBme690Driver(SensorDriver):
    name = "mock"

    def __init__(self, config: SensorConfig, fail_reads: int = 0) -> None:
        self._config = config
        self._t0 = time.time()
        self._opened = False
        self._fail_reads = fail_reads
        self._reads = 0

    def open(self) -> None:
        self._opened = True
        self._t0 = time.time()

    def close(self) -> None:
        self._opened = False

    def describe(self) -> dict[str, object]:
        return {
            "driver": self.name,
            "chip": "BME690-mock",
            "bsec": "simulated",
            "opened": self._opened,
        }

    def read(self) -> Measurement:
        if not self._opened:
            self.open()
        self._reads += 1
        if self._reads <= self._fail_reads:
            from server_meter.sensor.exceptions import SensorUnavailableError

            raise SensorUnavailableError("mock sensor forced failure")
        elapsed = time.time() - self._t0
        # Slow, realistic indoor ranges. No disk writes.
        temperature = 24.0 + 2.2 * math.sin(elapsed / 180.0)
        humidity = 48.0 + 8.0 * math.sin(elapsed / 240.0 + 0.4)
        pressure = 1012.5 + 3.5 * math.sin(elapsed / 600.0)
        gas = 85_000.0 + 12_000.0 * math.sin(elapsed / 420.0)
        iaq = 55.0 + 25.0 * (0.5 + 0.5 * math.sin(elapsed / 300.0))
        accuracy = 3 if elapsed > 90 else (2 if elapsed > 30 else (1 if elapsed > 10 else 0))
        eco2 = 520.0 + 80.0 * math.sin(elapsed / 260.0)
        bvoc = 0.45 + 0.12 * math.sin(elapsed / 200.0)
        return Measurement(
            timestamp=time.time(),
            temperature=round(temperature, 3),
            pressure=round(pressure, 3),
            humidity=round(max(0.0, min(100.0, humidity)), 3),
            gas_resistance=round(gas, 1),
            iaq=round(iaq, 2),
            iaq_accuracy=accuracy,
            static_iaq=round(iaq * 0.96, 2),
            static_iaq_accuracy=accuracy,
            co2_equivalent=round(eco2, 1),
            co2_accuracy=accuracy,
            breath_voc_equivalent=round(bvoc, 4),
            breath_voc_accuracy=accuracy,
            gas_percentage=round(12.0 + 5.0 * math.sin(elapsed / 150.0), 2),
            gas_percentage_accuracy=accuracy,
            tvoc_equivalent=round(0.18 + 0.05 * math.sin(elapsed / 190.0), 4),
            tvoc_accuracy=accuracy,
            raw_temperature=round(temperature + 0.6, 3),
            raw_humidity=round(humidity - 1.5, 3),
            raw_pressure=round(pressure, 3),
            stabilization_status=1 if elapsed > 20 else 0,
            run_in_status=1 if elapsed > 40 else 0,
            sensor_status=SensorStatus.OK,
        )
