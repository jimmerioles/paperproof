"""FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from paperproof.config import Settings
from paperproof.db import session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    with session(settings) as conn:
        yield conn
