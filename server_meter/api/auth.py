"""HTTP Basic Authentication against the SQLite user store.

Passwords are never logged or returned. Browser clients keep using the
Authorization header (not cookies), so cross-site form CSRF does not apply.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from server_meter.config import AppConfig
from server_meter.sqlite_state import MONITORING_ROLE, MONITORING_USERNAME
from server_meter.users import ANONYMOUS, AuthUser, UserStore

_basic = HTTPBasic(auto_error=False)

MONITORING_USER = AuthUser(id=-1, username=MONITORING_USERNAME, role=MONITORING_ROLE, enabled=True)
MONITORING_PATHS = frozenset({"/api/monitoring"})


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    extra = request.headers.get("x-monitoring-token")
    if extra:
        return extra.strip() or None
    return None


def require_auth(config: AppConfig):
    async def dependency(
        request: Request,
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    ) -> AuthUser:
        if not config.web.auth.enabled:
            return ANONYMOUS
        token = _bearer_token(request)
        store: UserStore = request.app.state.users
        if token:
            if await asyncio.to_thread(store.tokens.authenticate, token):
                if request.url.path.rstrip("/") not in MONITORING_PATHS:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Forbidden",
                    )
                return MONITORING_USER
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic realm=\"server-meter\""},
            )
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Basic realm=\"server-meter\""},
            )
        record = await asyncio.to_thread(
            store.authenticate, credentials.username, credentials.password
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic realm=\"server-meter\""},
            )
        return AuthUser(
            id=record.id,
            username=record.username,
            role=record.role,
            enabled=record.enabled,
        )

    return dependency


def require_admin(auth_dep):
    async def dependency(user: AuthUser = Depends(auth_dep)) -> AuthUser:
        if not user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )
        return user

    return dependency
