"""FastAPI application factory. No measurement persistence."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from server_meter import __version__
from server_meter.api.auth import require_auth
from server_meter.api.routes import build_router, json_error
from server_meter.api.settings import build_settings_router
from server_meter.config import AppConfig
from server_meter.service import MeterService

WEB_ASSET_VERSION = f"{__version__}.ui3"


def resolve_web_root() -> Path:
    candidates = [
        Path("/opt/server-meter/web"),
        Path(__file__).resolve().parent.parent / "web",
        Path.cwd() / "web",
    ]
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return candidates[0]


WEB_ROOT = resolve_web_root()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, max_request_bytes: int) -> None:
        super().__init__(app)
        self._max_request_bytes = max_request_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self._max_request_bytes:
                    return json_error(413, "request too large")
            except ValueError:
                return json_error(400, "invalid content-length")
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-server-meter"] = __version__
        return response


def create_app(config: AppConfig, service: MeterService | None = None) -> FastAPI:
    docs_url = "/docs" if config.web.api_docs_enabled else None
    redoc_url = "/redoc" if config.web.api_docs_enabled else None
    openapi_url = "/openapi.json" if config.web.api_docs_enabled else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if config.application.environment != "test":
            app.state.service.start_background()
        yield
        await app.state.service.shutdown()

    app = FastAPI(
        title="server-meter",
        version=__version__,
        description="RAM-only BME690 monitoring for Raspberry Pi 5",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.service = service or MeterService(config)
    app.add_middleware(SecurityHeadersMiddleware, max_request_bytes=config.web.max_request_bytes)

    auth_dep = require_auth(config)
    app.include_router(build_router(auth_dep))
    app.include_router(build_settings_router(auth_dep))

    if WEB_ROOT.is_dir():
        vendor = WEB_ROOT / "vendor"
        css = WEB_ROOT / "css"
        js = WEB_ROOT / "js"
        if vendor.is_dir():
            app.mount("/vendor", StaticFiles(directory=str(vendor)), name="vendor")
        if css.is_dir():
            app.mount("/css", StaticFiles(directory=str(css)), name="css")
        if js.is_dir():
            app.mount("/js", StaticFiles(directory=str(js)), name="js")

    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        # HTML/JS/CSS are public so the login form can be localized.
        # Measurement APIs remain behind HTTP Basic Auth.
        template = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        locale = config.web.locale
        lang = "cs" if locale == "CZ" else "en"
        html = (
            template.replace("__LOCALE__", locale)
            .replace("__LANG__", lang)
            .replace("__ASSET__", WEB_ASSET_VERSION)
        )
        return HTMLResponse(content=html)

    if not config.web.health_public:
        # The public health route is already registered; replace it.
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/health"]

        @app.get("/api/health")
        async def protected_health(_user: str = Depends(auth_dep)) -> dict[str, str]:
            return {"status": "ok", "service": "server-meter"}

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        if exc.status_code in {401, 403}:
            return await http_exception_handler(request, exc)
        detail = exc.detail if isinstance(exc.detail, str) else "request failed"
        return json_error(exc.status_code, detail)

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, _exc: Exception):
        return JSONResponse(status_code=500, content={"error": "internal server error"})

    return app
