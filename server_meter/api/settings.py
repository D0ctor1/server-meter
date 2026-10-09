"""Authenticated notification settings. SMTP passwords never leave the server."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from server_meter.config import AppConfig, ConfigError, NotificationsConfig
from server_meter.config_io import save_notifications
from server_meter.notification.models import METRIC_UNITS, AlarmState
from server_meter.notification.smtp import SmtpError
from server_meter.users import AuthUser

THRESHOLD_KEYS = frozenset(
    {
        "enabled",
        "warning_high",
        "critical_high",
        "warning_low",
        "critical_low",
        "warning_clear_high",
        "critical_clear_high",
        "warning_clear_low",
        "critical_clear_low",
        "hysteresis",
        "min_duration_seconds",
    }
)

logger = logging.getLogger("server_meter.settings")

KEEP_PASSWORD = frozenset({None, "", "********"})
SETTINGS_KEYS = frozenset({"enabled", "max_queue_size", "email", "thresholds"})


def build_settings_router(admin_dep) -> APIRouter:
    router = APIRouter()

    @router.get("/api/settings")
    async def get_settings(
        request: Request,
        _admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        config: AppConfig = request.app.state.config
        notifier = request.app.state.service.notifier
        return public_settings(config, notifier)

    @router.put("/api/settings")
    async def put_settings(
        request: Request,
        admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            return JSONResponse(status_code=400, content={"error": "invalid settings payload"})
        config: AppConfig = request.app.state.config
        try:
            apply_settings_payload(config, payload)
        except (ConfigError, ValueError, ValidationError) as exc:
            return JSONResponse(status_code=400, content={"error": _safe_error(exc)})
        try:
            if config._source_path is not None:
                save_notifications(config)
        except OSError as exc:
            logger.error("cannot persist notification configuration: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": "cannot write configuration file (check permissions, e.g. chmod 660)"},
            )
        except ConfigError as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})
        request.app.state.service.notifier.replace_config(config)
        logger.info("%s changed notification configuration", admin.username)
        return public_settings(config, request.app.state.service.notifier)

    @router.post("/api/settings/test-email")
    async def test_email(
        request: Request,
        admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        notifier = request.app.state.service.notifier
        try:
            await asyncio.to_thread(notifier.send_test_now)
        except SmtpError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            logger.exception("test email failed")
            return {"ok": False, "error": "SMTP delivery failed"}
        logger.info("%s sent a test email", admin.username)
        return {"ok": True}

    return router


def public_settings(config: AppConfig, notifier) -> dict[str, Any]:
    email = config.notifications.email
    smtp = email.smtp
    return {
        "enabled": config.notifications.enabled,
        "max_queue_size": config.notifications.max_queue_size,
        "email": {
            "enabled": email.enabled,
            "cooldown_seconds": email.cooldown_seconds,
            "notify_recovery": email.notify_recovery,
            "from": email.from_address,
            "to": list(email.to),
            "web_url": email.web_url,
            "smtp": {
                "host": smtp.host,
                "port": smtp.port,
                "security": smtp.security,
                "username": smtp.username,
                "password_set": bool(smtp.password),
                "timeout_seconds": smtp.timeout_seconds,
            },
        },
        "thresholds": _public_thresholds(config),
        "delivery_ok": notifier.delivery_ok,
        "delivery_error": notifier.last_delivery_error,
        "writable": config._source_path is not None,
    }


def apply_settings_payload(config: AppConfig, payload: dict[str, Any]) -> None:
    current = config.notifications.model_dump(by_alias=True)
    incoming = {key: value for key, value in payload.items() if key in SETTINGS_KEYS}
    if "email" in incoming and isinstance(incoming["email"], dict):
        email_in = dict(incoming["email"])
        smtp_in = dict(email_in.get("smtp") or {})
        smtp_in.pop("password_set", None)
        if smtp_in.get("password", "") in KEEP_PASSWORD:
            smtp_in.pop("password", None)
        email_in["smtp"] = {**current["email"]["smtp"], **smtp_in}
        if "to" in email_in and isinstance(email_in["to"], str):
            email_in["to"] = [part.strip() for part in email_in["to"].split(",") if part.strip()]
        incoming["email"] = {**current["email"], **email_in}
    if "thresholds" in incoming and isinstance(incoming["thresholds"], dict):
        merged = dict(current["thresholds"])
        for name, spec in incoming["thresholds"].items():
            cleaned = {k: v for k, v in spec.items() if k in THRESHOLD_KEYS} if isinstance(spec, dict) else spec
            if name in merged and isinstance(cleaned, dict) and isinstance(merged[name], dict):
                merged[name] = {**merged[name], **cleaned}
            else:
                merged[name] = cleaned
        incoming["thresholds"] = merged
    merged_all = {**current, **incoming}
    config.notifications = NotificationsConfig.model_validate(merged_all)


def _public_thresholds(config: AppConfig) -> dict[str, Any]:
    payload = config.notifications.thresholds.model_dump()
    for name, spec in payload.items():
        spec["unit"] = METRIC_UNITS.get(name, "")
    return payload


def monitoring_payload(request) -> dict[str, Any]:
    import socket

    service = request.app.state.service
    config: AppConfig = request.app.state.config
    sample = service.current
    sysm = service.system_snapshot()
    notifier = service.notifier
    overall = notifier.overall_state()
    nagios_word = {
        AlarmState.NORMAL: "OK",
        AlarmState.WARNING: "WARNING",
        AlarmState.CRITICAL: "CRITICAL",
        AlarmState.UNKNOWN: "UNKNOWN",
    }[overall]
    sensor = {
        "status": service.sensor_status.value,
        "age_seconds": service.sensor_age_seconds(),
        "temperature": sample.temperature if sample else None,
        "humidity": sample.humidity if sample else None,
        "pressure": sample.pressure if sample else None,
        "gas_resistance": sample.gas_resistance if sample else None,
        "iaq": sample.iaq if sample else None,
        "iaq_accuracy": sample.iaq_accuracy if sample else None,
        "static_iaq": sample.static_iaq if sample else None,
        "eco2": sample.co2_equivalent if sample else None,
        "bvoc": sample.breath_voc_equivalent if sample else None,
        "tvoc": sample.tvoc_equivalent if sample else None,
        "available": sample is not None,
    }
    thresholds: dict[str, Any] = {}
    for name, spec in config.notifications.thresholds.model_dump().items():
        thresholds[name] = {
            "enabled": spec["enabled"],
            "warning_high": spec["warning_high"],
            "critical_high": spec["critical_high"],
            "warning_low": spec["warning_low"],
            "critical_low": spec["critical_low"],
            "hysteresis": spec["hysteresis"],
            "min_duration_seconds": spec["min_duration_seconds"],
            "unit": METRIC_UNITS.get(name, ""),
        }
    th = config.notifications.thresholds
    return {
        "hostname": socket.gethostname(),
        "status": nagios_word,
        "overall": nagios_word,
        "overall_state": overall.value,
        "sensor_available": sample is not None,
        "sensor_age_seconds": service.sensor_age_seconds(),
        "temperature_c": sample.temperature if sample else None,
        "humidity_percent": sample.humidity if sample else None,
        "pressure_hpa": sample.pressure if sample else None,
        "gas_resistance_ohm": sample.gas_resistance if sample else None,
        "iaq": sample.iaq if sample else None,
        "iaq_accuracy": sample.iaq_accuracy if sample else None,
        "static_iaq": sample.static_iaq if sample else None,
        "static_iaq_accuracy": sample.static_iaq_accuracy if sample else None,
        "eco2_ppm": sample.co2_equivalent if sample else None,
        "bvoc_ppm": sample.breath_voc_equivalent if sample else None,
        "tvoc_ppb": sample.tvoc_equivalent if sample else None,
        "cpu_temperature_c": sysm.cpu_temperature_c,
        "cpu_load_percent": sysm.cpu_usage_percent,
        "ram_used_percent": sysm.ram_usage_percent,
        "uptime_seconds": sysm.uptime_seconds,
        "temperature_warning": th.temperature.warning_high,
        "temperature_critical": th.temperature.critical_high,
        "humidity_warning": th.humidity.warning_high,
        "humidity_critical": th.humidity.critical_high,
        "iaq_warning": th.iaq.warning_high,
        "iaq_critical": th.iaq.critical_high,
        "eco2_warning": th.eco2.warning_high,
        "eco2_critical": th.eco2.critical_high,
        "bvoc_warning": th.bvoc.warning_high,
        "bvoc_critical": th.bvoc.critical_high,
        "cpu_temperature_warning": th.cpu_temperature.warning_high,
        "cpu_temperature_critical": th.cpu_temperature.critical_high,
        "cpu_load_warning": th.cpu_usage.warning_high,
        "cpu_load_critical": th.cpu_usage.critical_high,
        "ram_warning": th.ram_usage.warning_high,
        "ram_critical": th.ram_usage.critical_high,
        "sensor_age_warning": th.sensor_unavailable.warning_high,
        "sensor_age_critical": th.sensor_unavailable.critical_high,
        "sensor": sensor,
        "system": {
            "cpu_temperature": sysm.cpu_temperature_c,
            "cpu_usage_percent": sysm.cpu_usage_percent,
            "ram_usage_percent": sysm.ram_usage_percent,
            "uptime_seconds": sysm.uptime_seconds,
        },
        "alarms": notifier.snapshot_alarms(),
        "thresholds": thresholds,
    }


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "password" in lowered or "passwd" in lowered:
        return "invalid notification settings"
    return text[:300]
