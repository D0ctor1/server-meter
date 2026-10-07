"""HTTP Basic Authentication. Password is never logged or returned."""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from server_meter.config import AppConfig

_basic = HTTPBasic(auto_error=False)


def require_auth(config: AppConfig):
    async def dependency(
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    ) -> str:
        if not config.web.auth.enabled:
            return "anonymous"
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Basic realm=\"server-meter\""},
            )
        user_ok = hmac.compare_digest(
            credentials.username.encode("utf-8"),
            config.web.auth.username.encode("utf-8"),
        )
        pass_ok = hmac.compare_digest(
            credentials.password.encode("utf-8"),
            config.web.auth.password.encode("utf-8"),
        )
        if not (user_ok and pass_ok):
            # Dummy compare to reduce timing leaks when lengths differ.
            secrets.compare_digest(b"invalid-password", b"invalid-password")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic realm=\"server-meter\""},
            )
        return credentials.username

    return dependency
