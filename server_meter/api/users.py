"""Admin user-management API. Sensor routes stay separate."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from server_meter.users import (
    AuthUser,
    DuplicateUserError,
    InvalidPasswordError,
    InvalidRoleError,
    InvalidUsernameError,
    LastAdminError,
    UserError,
    UserNotFoundError,
    UserStore,
)

logger = logging.getLogger("server_meter.users")


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": code, "message": message})


def _translate(exc: UserError) -> JSONResponse:
    if isinstance(exc, LastAdminError):
        return _error(409, exc.code, "Cannot remove or disable the last active administrator.")
    if isinstance(exc, DuplicateUserError):
        return _error(409, exc.code, "Username already exists.")
    if isinstance(exc, UserNotFoundError):
        return _error(404, exc.code, "User not found.")
    if isinstance(exc, InvalidUsernameError):
        return _error(400, exc.code, "Invalid username.")
    if isinstance(exc, InvalidPasswordError):
        return _error(400, exc.code, "Invalid password.")
    if isinstance(exc, InvalidRoleError):
        return _error(400, exc.code, "Invalid role.")
    return _error(400, getattr(exc, "code", "invalid_user"), str(exc) or "invalid user")


def _store(request: Request) -> UserStore:
    return request.app.state.users


def build_users_router(auth_dep, admin_dep) -> APIRouter:
    router = APIRouter()

    @router.get("/api/me")
    async def me(user: AuthUser = Depends(auth_dep)) -> dict[str, str]:
        return user.public_dict()

    @router.get("/api/admin/users")
    async def list_users(
        request: Request,
        _admin: AuthUser = Depends(admin_dep),
    ) -> dict[str, Any]:
        tracker = getattr(request.app.state, "activity", None)
        users = []
        for item in _store(request).list_users():
            payload = item.public_dict()
            payload["last_activity_at"] = tracker.get(item.id) if tracker is not None else None
            users.append(payload)
        return {"users": users}

    @router.post("/api/admin/users")
    async def create_user(
        request: Request,
        admin: AuthUser = Depends(admin_dep),
    ):
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(400, "invalid_user", "invalid user payload")
        try:
            user = _store(request).create(
                username=str(payload.get("username") or ""),
                password=str(payload.get("password") or ""),
                role=str(payload.get("role") or "user"),
                enabled=bool(payload.get("enabled", True)),
            )
        except UserError as exc:
            return _translate(exc)
        logger.info("%s created user %s role=%s", admin.username, user.username, user.role)
        return user.public_dict()

    @router.get("/api/admin/users/{user_id}")
    async def get_user(
        request: Request,
        user_id: int,
        _admin: AuthUser = Depends(admin_dep),
    ):
        record = _store(request).get(user_id)
        if record is None:
            return _error(404, "user_not_found", "User not found.")
        payload = record.public_dict()
        tracker = getattr(request.app.state, "activity", None)
        payload["last_activity_at"] = tracker.get(record.id) if tracker is not None else None
        return payload

    @router.put("/api/admin/users/{user_id}")
    async def update_user(
        request: Request,
        user_id: int,
        admin: AuthUser = Depends(admin_dep),
    ):
        payload = await request.json()
        if not isinstance(payload, dict):
            return _error(400, "invalid_user", "invalid user payload")
        kwargs: dict[str, Any] = {}
        if "username" in payload:
            kwargs["username"] = str(payload.get("username") or "")
        if "role" in payload:
            kwargs["role"] = str(payload.get("role") or "")
        if "enabled" in payload:
            kwargs["enabled"] = bool(payload.get("enabled"))
        if "password" in payload:
            kwargs["password"] = str(payload.get("password") or "")
        try:
            user = _store(request).update(user_id, **kwargs)
        except UserError as exc:
            return _translate(exc)
        logger.info("%s updated user %s", admin.username, user.username)
        return user.public_dict()

    @router.delete("/api/admin/users/{user_id}")
    async def delete_user(
        request: Request,
        user_id: int,
        admin: AuthUser = Depends(admin_dep),
    ):
        try:
            user = _store(request).delete(user_id)
        except UserError as exc:
            return _translate(exc)
        logger.info("%s deleted user %s", admin.username, user.username)
        return {"ok": True, "id": user.id, "username": user.username}

    return router
