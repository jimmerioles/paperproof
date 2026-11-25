"""Application factory. Importing this module has no filesystem side effects."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from paperproof import __version__
from paperproof.api.auth_middleware import AuthMiddleware
from paperproof.api.auth_routes import router as auth_router
from paperproof.api.routes import router
from paperproof.api.templating import templates
from paperproof.auth import LoginLimiter, SessionManager, load_session_secret
from paperproof.config import Settings, get_settings
from paperproof.db import init_db, session

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    resolved.ensure_dirs()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        with session(resolved) as conn:
            init_db(conn)
        yield

    app = FastAPI(
        title="Paperproof",
        version=__version__,
        description="Document intelligence where every answer is page-checked.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = resolved
    if resolved.auth_disabled and resolved.env != "dev":
        raise ValueError("Authentication can only be disabled when PAPERPROOF_ENV=dev.")

    sessions: SessionManager | None = None
    limiter: LoginLimiter | None = None
    if not resolved.auth_disabled:
        sessions = SessionManager(
            load_session_secret(resolved),
            resolved.session_ttl_seconds,
        )
        limiter = LoginLimiter(
            max_attempts=resolved.login_max_attempts,
            window_seconds=resolved.login_window_seconds,
            lockout_seconds=resolved.login_lockout_seconds,
        )
    app.state.session_manager = sessions
    app.state.login_limiter = limiter

    app.add_middleware(AuthMiddleware, settings=resolved, sessions=sessions)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(auth_router)
    app.include_router(router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; font-src 'self'; connect-src 'self'"
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.headers.get("accept", "").startswith("text/html"):
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "active": "",
                    "status": exc.status_code,
                    "detail": str(exc.detail),
                },
                status_code=exc.status_code,
            )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app
