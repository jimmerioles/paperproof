"""Session loading and the authentication gate."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from paperproof.auth import SESSION_COOKIE, SessionData, SessionManager, get_user_by_id
from paperproof.config import Settings
from paperproof.db import session as db_session

PUBLIC_PATHS = frozenset({"/login", "/healthz", "/favicon.ico"})
STATIC_PREFIX = "/static/"


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings, sessions: SessionManager | None) -> None:
        super().__init__(app)
        self.settings = settings
        self.sessions = sessions

    def _set_cookie(self, response: Response, session: SessionData) -> None:
        if self.sessions is None:
            return
        response.set_cookie(
            SESSION_COOKIE,
            self.sessions.dumps(session),
            max_age=self.sessions.ttl_seconds,
            httponly=True,
            samesite="lax",
            secure=self.settings.secure_cookies,
            path="/",
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith(STATIC_PREFIX):
            return await call_next(request)

        request.state.session = None
        request.state.csrf_token = ""
        request.state.user = None
        request.state.session_cookie_set = False

        if self.settings.auth_disabled:
            request.state.user = {"id": "dev", "username": "dev"}
            if path == "/login":
                return RedirectResponse("/", status_code=303)
            return await call_next(request)

        if self.sessions is None:
            raise RuntimeError("Authentication is enabled but no session manager is configured.")

        session: SessionData | None = None
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie:
            session = self.sessions.loads(cookie)
        new_cookie = session is None
        if session is None:
            session = self.sessions.new()

        user = None
        if session.uid:
            with db_session(self.settings) as conn:
                user = get_user_by_id(conn, session.uid)
            if user is None:
                session = self.sessions.new()
                new_cookie = True

        request.state.session = session
        request.state.csrf_token = session.csrf
        request.state.user = (
            {"id": str(user["id"]), "username": str(user["username"])} if user else None
        )

        public = path in PUBLIC_PATHS
        if user is None and not public:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Authentication required."}, status_code=401)
            next_url = path
            if request.url.query:
                next_url += f"?{request.url.query}"
            response = RedirectResponse(
                f"/login?next={quote(next_url, safe='')}",
                status_code=303,
            )
            if new_cookie:
                self._set_cookie(response, session)
            return response

        if user is not None and path == "/login":
            return RedirectResponse("/", status_code=303)

        response = await call_next(request)
        if new_cookie and not request.state.session_cookie_set:
            self._set_cookie(response, session)
        return response
