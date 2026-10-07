"""Admin operations: config export, system info, alarm history, monitoring token."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from server_meter.health import export_config, system_information
from server_meter.users import AuthUser, UserStore

logger = logging.getLogger("server_meter.ops")


def build_ops_router(auth_dep, admin_dep) -> APIRouter:
    router = APIRouter()

    @router.get("/api/admin/export")
    async def admin_export(
        request: Request,
        admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        logger.info("%s exported configuration", admin.username)
        return {
            "redacted": True,
            "config": export_config(request.app.state.config),
        }

    @router.get("/api/admin/system")
    async def admin_system(
        request: Request,
        _admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        return system_information(request.app.state.service, request.app.state.config)

    @router.get("/api/alarms/history")
    async def alarm_history(
        request: Request,
        _user: AuthUser = Depends(auth_dep),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        store: UserStore = request.app.state.users
        rows = store.alarms.list_recent(limit)
        return {"alarms": [row.public_dict() for row in rows], "persistent": True}

    @router.get("/api/admin/monitoring-token")
    async def token_status(
        request: Request,
        _admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        store: UserStore = request.app.state.users
        return store.tokens.status()

    @router.post("/api/admin/monitoring-token")
    async def token_generate(
        request: Request,
        admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        store: UserStore = request.app.state.users
        raw = store.tokens.generate()
        logger.info("%s generated a monitoring token", admin.username)
        return {"token": raw, "note": "shown once"}

    @router.delete("/api/admin/monitoring-token")
    async def token_revoke(
        request: Request,
        admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        store: UserStore = request.app.state.users
        revoked = store.tokens.revoke()
        logger.info("%s revoked monitoring token", admin.username)
        return {"revoked": revoked}

    return router


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})
