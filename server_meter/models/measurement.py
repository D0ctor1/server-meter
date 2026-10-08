"""In-memory measurement model.

Field names and units follow Bosch BME690 SensorAPI / BSEC 3.x:
temperature °C, pressure hPa (converted from Pa), humidity %RH,
gas_resistance Ohm, IAQ 0-500, co2_equivalent ppm, breath_voc_equivalent ppm.
Unavailable values are None — never invented.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import Enum
from typing import Any


class SensorStatus(str, Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    INITIALIZING = "initializing"
    ERROR = "error"
    UNKNOWN = "unknown"


class SensorHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Measurement:
    """One sample stored only in RAM. Never serialized to disk by the application."""

    timestamp: float
    temperature: float | None = None
    pressure: float | None = None
    humidity: float | None = None
    gas_resistance: float | None = None
    iaq: float | None = None
    iaq_accuracy: int | None = None
    static_iaq: float | None = None
    static_iaq_accuracy: int | None = None
    co2_equivalent: float | None = None
    co2_accuracy: int | None = None
    breath_voc_equivalent: float | None = None
    breath_voc_accuracy: int | None = None
    gas_percentage: float | None = None
    gas_percentage_accuracy: int | None = None
    tvoc_equivalent: float | None = None
    tvoc_accuracy: int | None = None
    raw_temperature: float | None = None
    raw_humidity: float | None = None
    raw_pressure: float | None = None
    stabilization_status: int | None = None
    run_in_status: int | None = None
    sensor_status: SensorStatus = SensorStatus.OK
    cpu_temperature: float | None = None
    cpu_load: float | None = None
    ram_usage: float | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """JSON-friendly dict. Includes spec aliases eco2 / bvoc."""
        payload = asdict(self)
        payload["sensor_status"] = self.sensor_status.value
        payload["eco2"] = self.co2_equivalent
        payload["bvoc"] = self.breath_voc_equivalent
        payload["tvoc"] = self.tvoc_equivalent
        return payload

    def numeric_fields(self) -> dict[str, float | int | None]:
        skip = {"timestamp", "sensor_status"}
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in skip}


IAQ_ACCURACY_LABELS = {
    0: "stabilizing",
    1: "low",
    2: "medium",
    3: "high",
}


def iaq_accuracy_label(value: int | None) -> str | None:
    if value is None:
        return None
    return IAQ_ACCURACY_LABELS.get(int(value), "unknown")
