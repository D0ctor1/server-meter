"""In-RAM alarm models. Never serialized to disk."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AlarmState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int:
        return {self.NORMAL: 0, self.UNKNOWN: 1, self.WARNING: 2, self.CRITICAL: 3}[self]


AIR_QUALITY_METRICS = frozenset(
    {"iaq", "iaq_accuracy", "static_iaq", "eco2", "bvoc", "gas_resistance"}
)

METRIC_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "pressure": "hPa",
    "gas_resistance": "Ω",
    "iaq": "",
    "iaq_accuracy": "",
    "static_iaq": "",
    "eco2": "ppm",
    "bvoc": "ppm",
    "cpu_temperature": "°C",
    "cpu_usage": "%",
    "ram_usage": "%",
    "sensor_unavailable": "s",
}

METRIC_GETTERS = {
    "temperature": ("sample", "temperature"),
    "humidity": ("sample", "humidity"),
    "pressure": ("sample", "pressure"),
    "gas_resistance": ("sample", "gas_resistance"),
    "iaq": ("sample", "iaq"),
    "iaq_accuracy": ("sample", "iaq_accuracy"),
    "static_iaq": ("sample", "static_iaq"),
    "eco2": ("sample", "eco2"),
    "bvoc": ("sample", "bvoc"),
    "cpu_temperature": ("system", "cpu_temperature_c"),
    "cpu_usage": ("system", "cpu_usage_percent"),
    "ram_usage": ("system", "ram_usage_percent"),
}


@dataclass
class MetricAlarm:
    state: AlarmState = AlarmState.UNKNOWN
    since: float = 0.0
    pending: AlarmState | None = None
    pending_since: float = 0.0
    last_email_state: AlarmState | None = None
    last_email_at: float | None = None
    last_value: float | None = None
    last_reason: str = ""


@dataclass
class OutboundEmail:
    kind: str  # WARNING | CRITICAL | RECOVERY | TEST
    metric: str
    subject: str
    body: str
    recipients: list[str] = field(default_factory=list)
    from_address: str = ""
