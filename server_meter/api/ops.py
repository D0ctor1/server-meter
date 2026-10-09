"""Admin operations: config export, system info, alarm history, monitoring token."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse

from server_meter.health import export_config, system_information
from server_meter.system_actions import (
    CONFIRM_REBOOT_HOST,
    CONFIRM_RESTART_SERVICE,
    UnknownSystemAction,
)
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

    @router.post("/api/admin/restart-service")
    async def restart_service(
        request: Request,
        background: BackgroundTasks,
        admin: AuthUser = Depends(admin_dep),
    ):
        return await _accepted_system_action(
            request,
            background,
            admin,
            expected_confirm=CONFIRM_RESTART_SERVICE,
        )

    @router.post("/api/admin/reboot-host")
    async def reboot_host(
        request: Request,
        background: BackgroundTasks,
        admin: AuthUser = Depends(admin_dep),
    ):
        return await _accepted_system_action(
            request,
            background,
            admin,
            expected_confirm=CONFIRM_REBOOT_HOST,
        )

    return router


def _confirm_token(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("confirm")
    if not isinstance(value, str):
        return None
    return value


async def _accepted_system_action(
    request: Request,
    background: BackgroundTasks,
    admin: AuthUser,
    *,
    expected_confirm: str,
) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        payload = None
    token = _confirm_token(payload)
    if token != expected_confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_confirm", "message": "confirmation required"},
        )
    actions = getattr(request.app.state, "system_actions", None)
    if actions is None:
        return JSONResponse(
            status_code=503,
            content={"error": "unavailable", "message": "system actions are not configured"},
        )

    def _run() -> None:
        try:
            unit = actions.start(expected_confirm)
            logger.info("%s requested %s (%s)", admin.username, expected_confirm, unit)
        except UnknownSystemAction:
            logger.error("refused unknown system action %s", expected_confirm)
        except Exception:
            logger.exception("system action %s failed", expected_confirm)

    background.add_task(_run)
    return JSONResponse(
        status_code=202,
        content={"ok": True, "accepted": True, "action": expected_confirm},
    )


def json_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})
