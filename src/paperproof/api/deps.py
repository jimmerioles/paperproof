"""FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Form, HTTPException, Request

from paperproof.auth import csrf_matches
from paperproof.config import Settings
from paperproof.db import session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    with session(settings) as conn:
        yield conn


def csrf_protect(request: Request, csrf_token: str = Form("")) -> None:
    settings: Settings = request.app.state.settings
    if settings.auth_disabled:
        return
    expected = str(getattr(request.state, "csrf_token", "") or "")
    if not csrf_matches(expected, csrf_token):
        raise HTTPException(
            status_code=403,
            detail="Invalid CSRF token. Reload the page and try again.",
        )
