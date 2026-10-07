"""Nagios Core 4.4.5 check mapping. Always HTTP 200; state is in the body."""

from __future__ import annotations

from enum import IntEnum

from server_meter.config import AppConfig
from server_meter.models.measurement import SensorStatus
from server_meter.service import MeterService


class NagiosState(IntEnum):
    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3

    @property
    def label(self) -> str:
        return {0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "UNKNOWN"}[int(self)]


def evaluate_nagios(service: MeterService, config: AppConfig) -> tuple[NagiosState, str]:
    if not config.nagios.enabled:
        return NagiosState.UNKNOWN, "UNKNOWN - Nagios checks disabled"

    thresholds = config.nagios.thresholds
    sysm = service.system_snapshot()
    age = service.sensor_age_seconds()
    current = service.current
    worst = NagiosState.OK
    parts: list[str] = []

    def raise_state(state: NagiosState, message: str) -> None:
        nonlocal worst
        parts.append(message)
        if state > worst:
            worst = state

    if service.sensor_status in {SensorStatus.UNKNOWN, SensorStatus.INITIALIZING} and current is None:
        raise_state(NagiosState.UNKNOWN, "sensor state unknown")
    elif service.sensor_status == SensorStatus.UNAVAILABLE or current is None:
        raise_state(NagiosState.CRITICAL, "BME690 communication failure")
    elif age is not None and age > config.nagios.sensor_max_age_seconds:
        raise_state(
            NagiosState.CRITICAL,
            f"sensor data stale age={age:.0f}s (max {config.nagios.sensor_max_age_seconds:.0f}s)",
        )
    else:
        parts.append("BME690 reachable")

    if sysm.cpu_temperature_c is not None:
        if sysm.cpu_temperature_c >= thresholds.cpu_temperature_critical:
            raise_state(NagiosState.CRITICAL, f"Raspberry Pi CPU temperature {sysm.cpu_temperature_c:.1f}C")
        elif sysm.cpu_temperature_c >= thresholds.cpu_temperature_warning:
            raise_state(NagiosState.WARNING, f"Raspberry Pi CPU temperature {sysm.cpu_temperature_c:.1f}C")

    if sysm.ram_usage_percent is not None:
        if sysm.ram_usage_percent >= thresholds.ram_usage_critical:
            raise_state(NagiosState.CRITICAL, f"Raspberry Pi RAM usage {sysm.ram_usage_percent:.0f}%")
        elif sysm.ram_usage_percent >= thresholds.ram_usage_warning:
            raise_state(NagiosState.WARNING, f"Raspberry Pi RAM usage {sysm.ram_usage_percent:.0f}%")

    if sysm.cpu_load_1m is not None:
        if sysm.cpu_load_1m >= thresholds.cpu_load_critical:
            raise_state(NagiosState.CRITICAL, f"load1 {sysm.cpu_load_1m:.2f}")
        elif sysm.cpu_load_1m >= thresholds.cpu_load_warning:
            raise_state(NagiosState.WARNING, f"load1 {sysm.cpu_load_1m:.2f}")

    if sysm.throttle_flags and (
        sysm.throttle_flags.get("throttled")
        or sysm.throttle_flags.get("under_voltage")
        or sysm.throttle_flags.get("soft_temp_limit")
    ):
        raise_state(NagiosState.WARNING, "Raspberry Pi thermal/power throttle active")

    if current is not None and current.iaq is not None:
        if current.iaq >= thresholds.iaq_critical:
            raise_state(NagiosState.CRITICAL, f"IAQ {current.iaq:.1f}")
        elif current.iaq >= thresholds.iaq_warning:
            raise_state(NagiosState.WARNING, f"IAQ {current.iaq:.1f}")

    summary = _format_plugin_output(worst, parts, current, sysm, age)
    return worst, summary


def _fmt(value: float | None, suffix: str, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def _format_plugin_output(
    state: NagiosState,
    reasons: list[str],
    current,
    sysm,
    age: float | None,
) -> str:
    unique_reasons = []
    for item in reasons:
        if item not in unique_reasons:
            unique_reasons.append(item)
    detail = ", ".join(unique_reasons) if unique_reasons else "application running"
    extras = []
    if current is not None:
        extras.append(f"temperature={_fmt(current.temperature, 'C')}")
        extras.append(f"humidity={_fmt(current.humidity, '%')}")
        extras.append(f"pressure={_fmt(current.pressure, 'hPa')}")
        if current.gas_resistance is not None:
            extras.append(f"gas={current.gas_resistance / 1000.0:.1f}kOhm")
        if current.iaq is not None:
            extras.append(f"iaq={current.iaq:.1f}")
    extras.append(f"sensor_age={age:.0f}s" if age is not None else "sensor_age=n/a")
    extras.append(f"cpu_temp={_fmt(sysm.cpu_temperature_c, 'C')}")
    extras.append(f"ram={_fmt(sysm.ram_usage_percent, '%', 0)}")
    return f"{state.label} - {detail}; {', '.join(extras)}"
