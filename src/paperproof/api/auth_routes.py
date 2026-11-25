"""Login and logout routes."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from paperproof.api.deps import csrf_protect, get_conn
from paperproof.api.templating import templates
from paperproof.auth import (
    SESSION_COOKIE,
    LoginLimiter,
    SessionData,
    SessionManager,
    count_users,
    get_user_by_username,
    hash_password,
    safe_next,
    verify_password,
)
from paperproof.config import Settings
from paperproof.db import audit, utcnow

router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(
    response: Response,
    settings: Settings,
    sessions: SessionManager,
    session: SessionData,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        sessions.dumps(session),
        max_age=sessions.ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


def _render_login(
    request: Request,
    conn: sqlite3.Connection,
    *,
    error: str | None = None,
    next_url: str = "/",
    status_code: int = 200,
):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": error,
            "next": safe_next(next_url),
            "has_admin": count_users(conn) > 0,
        },
        status_code=status_code,
    )


@router.get("/login")
def login_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    settings: Settings = request.app.state.settings
    if settings.auth_disabled:
        return RedirectResponse("/", status_code=303)
    return _render_login(
        request,
        conn,
        next_url=request.query_params.get("next", "/"),
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form("/", alias="next"),
    conn: sqlite3.Connection = Depends(get_conn),
    _: None = Depends(csrf_protect),
):
    settings: Settings = request.app.state.settings
    sessions: SessionManager | None = request.app.state.session_manager
    limiter: LoginLimiter | None = request.app.state.login_limiter
    if sessions is None or limiter is None:
        raise RuntimeError("Authentication is not configured.")

    ip = _client_ip(request)
    key = f"{ip}:{username.strip().lower()}"
    locked = limiter.locked_for(key)
    if locked:
        return _render_login(
            request,
            conn,
            error=f"Too many attempts. Try again in {locked} seconds.",
            next_url=next_url,
            status_code=429,
        )

    user = get_user_by_username(conn, username)
    valid = False
    needs_rehash = False
    if user is not None:
        valid, needs_rehash = verify_password(str(user["password_hash"]), password)

    if user is None or not valid:
        lock_seconds = limiter.record_failure(key)
        if lock_seconds:
            audit(
                conn,
                actor="anonymous",
                action="auth.lockout",
                entity=user["id"] if user is not None else None,
                detail={"username": username, "ip": ip},
            )
            return _render_login(
                request,
                conn,
                error=f"Too many attempts. Try again in {lock_seconds} seconds.",
                next_url=next_url,
                status_code=429,
            )
        return _render_login(
            request,
            conn,
            error="Invalid username or password.",
            next_url=next_url,
            status_code=401,
        )

    assert user is not None
    limiter.reset(key)
    if needs_rehash:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(password), utcnow(), user["id"]),
        )

    session = sessions.new(uid=str(user["id"]))
    response = RedirectResponse(safe_next(next_url), status_code=303)
    _set_session_cookie(response, settings, sessions, session)
    request.state.session_cookie_set = True
    audit(
        conn,
        actor=str(user["username"]),
        action="auth.login",
        entity=str(user["id"]),
        detail={"ip": ip},
    )
    return response


@router.post("/logout")
def logout(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    _: None = Depends(csrf_protect),
):
    user = getattr(request.state, "user", None) or {}
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    request.state.session_cookie_set = True
    audit(
        conn,
        actor=str(user.get("username", "anonymous")),
        action="auth.logout",
        entity=user.get("id"),
        detail={"ip": _client_ip(request)},
    )
    return response
