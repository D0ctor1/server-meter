"""Application runtime: measurement loop, recovery, graceful shutdown.

The HTTP server is independent of the sensor. A missing BME690 never stops
the web UI. History lives only in the RAM buffer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from server_meter.config import AppConfig
from server_meter.models.measurement import Measurement, SensorHealth, SensorStatus
from server_meter.monitoring.memory import MemoryPressure, MemoryProtector
from server_meter.monitoring.system import SystemMetrics, SystemMonitor
from server_meter.sensor.base import SensorDriver
from server_meter.sensor.exceptions import SensorError
from server_meter.sensor.factory import create_sensor_driver
from server_meter.storage.ram_buffer import RamBuffer

logger = logging.getLogger("server_meter.service")


@dataclass
class RuntimeStats:
    started_at: float = field(default_factory=time.time)
    measurement_successes: int = 0
    measurement_errors: int = 0
    consecutive_errors: int = 0
    sensor_recoveries: int = 0
    last_error: str | None = None
    last_error_at: float | None = None
    last_success_at: float | None = None
    last_recovery_at: float | None = None
    sensor_open: bool = False


class MeterService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.buffer = RamBuffer(
            max_samples=config.history.max_samples,
            max_age_seconds=config.history.max_age_seconds,
            min_samples_keep=config.history.min_samples_keep,
        )
        self.system = SystemMonitor()
        self.memory = MemoryProtector(config.memory_protection, self.buffer, self.system)
        self.driver: SensorDriver = create_sensor_driver(config.sensor)
        self.stats = RuntimeStats()
        self.current: Measurement | None = None
        self.sensor_status = SensorStatus.INITIALIZING
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._logged_down = False

    @property
    def sensor_health(self) -> SensorHealth:
        if self.sensor_status == SensorStatus.OK:
            return SensorHealth.HEALTHY
        if self.sensor_status in {SensorStatus.INITIALIZING, SensorStatus.UNKNOWN}:
            return SensorHealth.UNKNOWN
        if self.stats.consecutive_errors >= 3:
            return SensorHealth.FAILED
        return SensorHealth.DEGRADED

    def start_background(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is None or self._task.done():
            self._task = loop.create_task(self.run_forever(), name="server-meter-loop")

    async def run_forever(self) -> None:
        logger.info(
            "measurement loop starting driver=%s interval=%.1fs history_max=%d",
            self.driver.name,
            self.config.sensor.interval_seconds,
            self.buffer.max_samples,
        )
        await asyncio.to_thread(self._try_open_sensor)
        while not self._stop.is_set():
            loop_started = time.monotonic()
            await asyncio.to_thread(self._measure_once)
            elapsed = time.monotonic() - loop_started
            if self.stats.consecutive_errors:
                backoff = min(
                    self.config.sensor.retry_max_seconds,
                    self.config.sensor.retry_initial_seconds
                    * (2 ** min(self.stats.consecutive_errors - 1, 4)),
                )
                sleep_for = max(0.2, backoff)
            else:
                sleep_for = max(0.2, self.config.sensor.interval_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
            except TimeoutError:
                continue
        logger.info("measurement loop stopping")
        await asyncio.to_thread(self._shutdown_sensor)

    async def shutdown(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=8.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        else:
            await asyncio.to_thread(self._shutdown_sensor)
        self.buffer.clear()
        self.current = None
        logger.info("shutdown complete; RAM history discarded (nothing written to disk)")

    def _try_open_sensor(self) -> None:
        try:
            self.driver.open()
            self.stats.sensor_open = True
            self.sensor_status = SensorStatus.OK
            logger.info("sensor initialized (%s)", self.driver.name)
        except Exception as exc:
            self.stats.sensor_open = False
            self.sensor_status = SensorStatus.UNAVAILABLE
            self.stats.last_error = str(exc)
            self.stats.last_error_at = time.time()
            logger.error("sensor unavailable at startup: %s (web UI will still run)", exc)

    def _shutdown_sensor(self) -> None:
        try:
            self.driver.close()
        except Exception as exc:
            logger.warning("sensor close error: %s", exc)
        self.stats.sensor_open = False

    def _measure_once(self) -> None:
        try:
            if not self.stats.sensor_open:
                self.driver.recover()
                self.stats.sensor_open = True
                self.stats.sensor_recoveries += 1
                self.stats.last_recovery_at = time.time()
                if self._logged_down:
                    logger.info("sensor communication restored")
                    self._logged_down = False
            sample = self.driver.read()
        except SensorError as exc:
            self._on_sensor_error(exc)
            return
        except Exception as exc:  # noqa: BLE001 — isolate the HTTP process
            self._on_sensor_error(SensorError(str(exc)))
            return

        self.stats.measurement_successes += 1
        self.stats.consecutive_errors = 0
        self.stats.last_success_at = sample.timestamp
        self.sensor_status = SensorStatus.OK
        self.current = sample
        self.buffer.append(sample)
        self.buffer.enforce_limits(now=sample.timestamp)
        self.memory.maybe_protect()

    def _on_sensor_error(self, exc: SensorError) -> None:
        self.stats.measurement_errors += 1
        self.stats.consecutive_errors += 1
        self.stats.last_error = str(exc)
        self.stats.last_error_at = time.time()
        self.stats.sensor_open = False
        self.sensor_status = SensorStatus.UNAVAILABLE
        # Log on first failure and then at backoff boundaries, never per-sample values.
        if not self._logged_down or self.stats.consecutive_errors in {1, 3, 10, 50}:
            logger.error(
                "sensor error (%s consecutive): %s",
                self.stats.consecutive_errors,
                exc,
            )
            self._logged_down = True

    def system_snapshot(self) -> SystemMetrics:
        return self.system.snapshot()

    def memory_pressure(self) -> MemoryPressure:
        snap = self.system.snapshot()
        return self.memory.classify(snap.ram_usage_percent)

    def sensor_age_seconds(self) -> float | None:
        if self.stats.last_success_at is None:
            return None
        return max(0.0, time.time() - self.stats.last_success_at)

    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self.stats.started_at)
