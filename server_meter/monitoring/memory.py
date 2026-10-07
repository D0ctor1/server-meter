"""RAM usage monitor and history shrinking. Deleted samples are discarded, never persisted."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from server_meter.config import MemoryProtectionConfig
from server_meter.monitoring.system import SystemMonitor
from server_meter.storage.ram_buffer import RamBuffer

logger = logging.getLogger("server_meter.memory")


class MemoryPressure(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass(slots=True)
class MemorySnapshot:
    ram_usage_percent: float | None
    pressure: MemoryPressure
    trimmed: int
    process_rss_bytes: int | None


class MemoryProtector:
    def __init__(self, config: MemoryProtectionConfig, buffer: RamBuffer, system: SystemMonitor) -> None:
        self._config = config
        self._buffer = buffer
        self._system = system
        self._last_check = 0.0
        self._last_trim_log = 0.0
        self._last_pressure = MemoryPressure.NORMAL

    def maybe_protect(self, now: float | None = None) -> MemorySnapshot:
        metrics = self._system.snapshot()
        usage = metrics.ram_usage_percent
        pressure = self.classify(usage)
        trimmed = 0
        ts = now if now is not None else time.monotonic()
        if self._config.enabled and usage is not None:
            due = (ts - self._last_check) >= self._config.check_interval_seconds
            if due or pressure in {MemoryPressure.CRITICAL, MemoryPressure.EMERGENCY}:
                self._last_check = ts
                trimmed = self._trim_for(pressure)
                if trimmed and (ts - self._last_trim_log) >= 30.0:
                    logger.warning(
                        "memory pressure=%s ram=%.1f%% trimmed_oldest=%d remaining=%d",
                        pressure.value,
                        usage,
                        trimmed,
                        len(self._buffer),
                    )
                    self._last_trim_log = ts
                elif pressure != self._last_pressure and pressure != MemoryPressure.NORMAL:
                    logger.warning("memory pressure changed to %s ram=%.1f%%", pressure.value, usage)
        if pressure == MemoryPressure.NORMAL and self._last_pressure != MemoryPressure.NORMAL:
            logger.info("memory pressure returned to normal")
        self._last_pressure = pressure
        return MemorySnapshot(
            ram_usage_percent=usage,
            pressure=pressure,
            trimmed=trimmed,
            process_rss_bytes=metrics.process_rss_bytes,
        )

    def classify(self, usage_percent: float | None) -> MemoryPressure:
        if usage_percent is None:
            return MemoryPressure.NORMAL
        if usage_percent >= self._config.emergency_percent:
            return MemoryPressure.EMERGENCY
        if usage_percent >= self._config.critical_percent:
            return MemoryPressure.CRITICAL
        if usage_percent >= self._config.warning_percent:
            return MemoryPressure.WARNING
        return MemoryPressure.NORMAL

    def _trim_for(self, pressure: MemoryPressure) -> int:
        if pressure == MemoryPressure.WARNING:
            return self._buffer.trim_fraction(self._config.warning_trim_fraction)
        if pressure == MemoryPressure.CRITICAL:
            return self._buffer.trim_fraction(self._config.critical_trim_fraction)
        if pressure == MemoryPressure.EMERGENCY:
            return self._buffer.trim_fraction(self._config.emergency_trim_fraction)
        return 0
