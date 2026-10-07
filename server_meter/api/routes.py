"""REST routes. History is served from RAM only."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from server_meter.api.nagios import evaluate_nagios
from server_meter.models.measurement import iaq_accuracy_label
from server_meter.service import MeterService


def build_router(auth_dep) -> APIRouter:
    router = APIRouter()
    Auth = Annotated[str, Depends(auth_dep)]

    @router.get("/api/health")
    async def health(request: Request) -> dict[str, str]:
        # Liveness only. No history scan, no sensor I/O.
        _ = request.app.state.service
        return {"status": "ok", "service": "server-meter"}

    @router.get("/api/status")
    async def status(request: Request, _: Auth) -> dict[str, Any]:
        service: MeterService = request.app.state.service
        config = request.app.state.config
        sysm = service.system_snapshot()
        current = service.current
        return {
            "application": config.public_status_dict(),
            "uptime_seconds": round(service.uptime_seconds(), 1),
            "sensor": {
                "status": service.sensor_status.value,
                "health": service.sensor_health.value,
                "driver": service.driver.describe(),
                "last_success_at": service.stats.last_success_at,
                "last_error_at": service.stats.last_error_at,
                "last_error": service.stats.last_error,
                "age_seconds": service.sensor_age_seconds(),
                "successes": service.stats.measurement_successes,
                "errors": service.stats.measurement_errors,
                "recoveries": service.stats.sensor_recoveries,
            },
            "history": service.buffer.stats(),
            "memory": {
                "pressure": service.memory_pressure().value,
                "ram_usage_percent": sysm.ram_usage_percent,
                "process_rss_bytes": sysm.process_rss_bytes,
            },
            "system": {
                "cpu_temperature_c": sysm.cpu_temperature_c,
                "cpu_usage_percent": sysm.cpu_usage_percent,
                "cpu_load_1m": sysm.cpu_load_1m,
                "uptime_seconds": sysm.uptime_seconds,
                "ram_usage_percent": sysm.ram_usage_percent,
            },
            "last_measurement_timestamp": current.timestamp if current else None,
        }

    @router.get("/api/current")
    async def current(request: Request, _: Auth) -> dict[str, Any]:
        service: MeterService = request.app.state.service
        sample = service.current
        if sample is None:
            return {
                "timestamp": None,
                "sensor_status": service.sensor_status.value,
                "available": False,
            }
        payload = sample.to_api_dict()
        payload["available"] = True
        payload["iaq_accuracy_label"] = iaq_accuracy_label(sample.iaq_accuracy)
        return payload

    @router.get("/api/history")
    async def history(
        request: Request,
        _: Auth,
        seconds: Annotated[float | None, Query(gt=0, le=604800)] = None,
        limit: Annotated[int | None, Query(ge=1, le=20_000)] = None,
        since: Annotated[float | None, Query()] = None,
    ) -> dict[str, Any]:
        service: MeterService = request.app.state.service
        samples = service.buffer.snapshot(seconds=seconds, limit=limit, since=since)
        return {
            "count": len(samples),
            "source": "ram",
            "persistent": False,
            "samples": [s.to_api_dict() for s in samples],
        }

    @router.get("/api/system")
    async def system(request: Request, _: Auth) -> dict[str, Any]:
        service: MeterService = request.app.state.service
        return service.system_snapshot().to_api_dict()

    @router.get("/api/sensor")
    async def sensor(request: Request, _: Auth) -> dict[str, Any]:
        service: MeterService = request.app.state.service
        return {
            "status": service.sensor_status.value,
            "health": service.sensor_health.value,
            "driver": service.driver.describe(),
            "age_seconds": service.sensor_age_seconds(),
            "current": service.current.to_api_dict() if service.current else None,
            "successes": service.stats.measurement_successes,
            "errors": service.stats.measurement_errors,
            "recoveries": service.stats.sensor_recoveries,
            "last_error": service.stats.last_error,
        }

    @router.get("/api/nagios/check")
    async def nagios_check(request: Request, _: Auth) -> PlainTextResponse:
        service: MeterService = request.app.state.service
        config = request.app.state.config
        state, body = evaluate_nagios(service, config)
        return PlainTextResponse(
            content=body + "\n",
            status_code=200,
            headers={
                "X-Nagios-Status": str(int(state)),
                "X-Nagios-State": state.label,
                "Cache-Control": "no-store",
            },
            media_type="text/plain; charset=utf-8",
        )

    return router


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})
