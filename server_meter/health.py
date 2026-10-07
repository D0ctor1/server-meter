"""Liveness and system-health snapshots. Reads RAM / config only — no I²C."""

from __future__ import annotations

import platform
import socket
import sys
import time
from typing import Any

from server_meter import __version__
from server_meter.config import AppConfig
from server_meter.models.measurement import SensorStatus
from server_meter.monitoring.memory import MemoryPressure
from server_meter.service import MeterService

LIVENESS = {"status": "healthy", "service": "server-meter"}

_RANK = {"ok": 0, "off": 0, "unknown": 1, "warning": 2, "critical": 3}


def liveness_payload() -> dict[str, str]:
    return dict(LIVENESS)


def _worst(statuses: list[str]) -> str:
    worst = "ok"
    for status in statuses:
        if _RANK.get(status, 0) > _RANK.get(worst, 0):
            worst = status
    return worst if worst != "off" else "ok"


def assemble_system_health(service: MeterService, config: AppConfig) -> dict[str, Any]:
    driver = service.driver.describe()
    sample = service.current
    age = service.sensor_age_seconds()
    max_age = config.nagios.sensor_max_age_seconds
    notifier = service.notifier
    pressure = service.memory_pressure()
    last_error = (service.stats.last_error or "").lower()

    if service.sensor_status == SensorStatus.OK and sample is not None:
        bme690 = "ok"
    elif service.sensor_status in {SensorStatus.UNAVAILABLE, SensorStatus.ERROR}:
        bme690 = "critical"
    elif service.sensor_status == SensorStatus.INITIALIZING:
        bme690 = "warning"
    else:
        bme690 = "unknown"

    i2c_hint = any(token in last_error for token in ("i2c", "errno 6", "remote i/o", "no such device"))
    if service.sensor_status == SensorStatus.OK:
        i2c = "ok"
    elif service.sensor_status in {SensorStatus.UNAVAILABLE, SensorStatus.ERROR} and (i2c_hint or sample is None):
        i2c = "critical"
    elif service.sensor_status == SensorStatus.INITIALIZING:
        i2c = "warning"
    else:
        i2c = "unknown"

    bsec_wanted = bool(config.sensor.bsec.enabled)
    bsec_loaded = bool(driver.get("bsec_loaded") or driver.get("bsec") == "simulated")
    if config.sensor.driver == "mock" and sample is not None and sample.iaq is not None:
        bsec = "ok"
    elif not bsec_wanted:
        bsec = "off"
    elif bsec_loaded and sample is not None and sample.iaq is not None:
        bsec = "ok"
    elif bsec_loaded:
        bsec = "warning"
    else:
        bsec = "critical"

    if age is None:
        sensor_data = "critical"
    elif age > max_age:
        sensor_data = "critical"
    elif age > max(5.0, max_age * 0.5):
        sensor_data = "warning"
    else:
        sensor_data = "ok"

    if not config.notifications.enabled or not config.notifications.email.enabled:
        smtp = "off"
    elif notifier.delivery_ok:
        smtp = "ok"
    else:
        smtp = "critical"

    if pressure in {MemoryPressure.EMERGENCY, MemoryPressure.CRITICAL}:
        ram = "critical"
    elif pressure == MemoryPressure.WARNING:
        ram = "warning"
    else:
        ram = "ok"

    items = {
        "bme690": {"status": bme690},
        "bsec": {
            "status": bsec,
            "loaded": bsec_loaded,
            "version": driver.get("bsec_version"),
            "enabled": bsec_wanted,
        },
        "i2c": {
            "status": i2c,
            "bus": f"/dev/i2c-{config.sensor.i2c.bus}",
            "address": hex(config.sensor.i2c.address),
        },
        "sensor_data": {"status": sensor_data, "age_seconds": age, "max_age_seconds": max_age},
        "smtp": {"status": smtp, "error": notifier.last_delivery_error},
        "ram_protection": {"status": ram, "pressure": pressure.value},
        "web_api": {"status": "ok"},
    }
    return {
        "overall": _worst([item["status"] for item in items.values()]),
        "items": items,
    }


def system_information(service: MeterService, config: AppConfig) -> dict[str, Any]:
    driver = service.driver.describe()
    sysm = service.system_snapshot()
    uname = platform.uname()
    return {
        "application_version": __version__,
        "python_version": sys.version.split()[0],
        "os": f"{uname.system} {uname.release}",
        "os_pretty": platform.platform(),
        "kernel": uname.release,
        "hostname": socket.gethostname(),
        "uptime_seconds": sysm.uptime_seconds,
        "app_uptime_seconds": round(service.uptime_seconds(), 1),
        "cpu_usage_percent": sysm.cpu_usage_percent,
        "cpu_load_1m": sysm.cpu_load_1m,
        "cpu_temperature_c": sysm.cpu_temperature_c,
        "ram_usage_percent": sysm.ram_usage_percent,
        "ram_used_bytes": sysm.ram_used_bytes,
        "ram_total_bytes": sysm.ram_total_bytes,
        "i2c_bus": f"/dev/i2c-{config.sensor.i2c.bus}",
        "bme690_address": hex(config.sensor.i2c.address),
        "bsec_enabled": bool(config.sensor.bsec.enabled),
        "bsec_loaded": bool(driver.get("bsec_loaded") or driver.get("bsec") == "simulated"),
        "bsec_version": driver.get("bsec_version") or driver.get("bsec"),
        "sensor_driver": service.driver.name,
        "collected_at": time.time(),
    }


def export_config(config: AppConfig) -> dict[str, Any]:
    payload = config.model_dump(by_alias=True)
    auth = payload.get("web", {}).get("auth", {})
    if isinstance(auth, dict):
        if "password" in auth:
            auth["password"] = "REDACTED"
        if "username" in auth:
            pass
    smtp = payload.get("notifications", {}).get("email", {}).get("smtp", {})
    if isinstance(smtp, dict) and "password" in smtp:
        smtp["password"] = "REDACTED" if smtp.get("password") else ""
    web = payload.get("web", {})
    if isinstance(web, dict):
        web.pop("monitoring_token", None)
    return payload
