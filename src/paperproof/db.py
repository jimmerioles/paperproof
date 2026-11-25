"""SQLite storage: schema, connections, migrations, and small helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paperproof.config import Settings

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    title TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    needs_ocr INTEGER NOT NULL DEFAULT 0,
    ocr_pages INTEGER NOT NULL DEFAULT 0,
    ocr_confidence REAL,
    ocr_low_confidence INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    pdf_page INTEGER NOT NULL,
    printed_label TEXT,
    width REAL NOT NULL,
    height REAL NOT NULL,
    text TEXT NOT NULL,
    words_json TEXT NOT NULL,
    ocr INTEGER NOT NULL DEFAULT 0,
    ocr_confidence REAL,
    ocr_engine TEXT,
    PRIMARY KEY (doc_id, pdf_page)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    heading TEXT,
    text TEXT NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks(doc_id, ordinal);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    heading,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, heading) VALUES (new.id, new.text, new.heading);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading)
    VALUES ('delete', old.id, old.text, old.heading);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, heading)
    VALUES ('delete', old.id, old.text, old.heading);
    INSERT INTO chunks_fts(rowid, text, heading) VALUES (new.id, new.text, new.heading);
END;

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    template TEXT NOT NULL,
    field TEXT NOT NULL,
    value_json TEXT,
    quote TEXT,
    pdf_page INTEGER,
    printed_label TEXT,
    boxes_json TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    verifier TEXT,
    extractor TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewer TEXT,
    review_note TEXT,
    UNIQUE(doc_id, template, field)
);
CREATE INDEX IF NOT EXISTS extractions_doc_idx ON extractions(doc_id, field);
CREATE INDEX IF NOT EXISTS extractions_status_idx ON extractions(status);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_at_idx ON audit_log(at DESC);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE documents ADD COLUMN ocr_pages INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN ocr_confidence REAL",
        "ALTER TABLE documents ADD COLUMN ocr_low_confidence INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE pages ADD COLUMN ocr INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE pages ADD COLUMN ocr_confidence REAL",
        "ALTER TABLE pages ADD COLUMN ocr_engine TEXT",
    ],
    3: [
        "CREATE TABLE users ("
        "id TEXT PRIMARY KEY, "
        "username TEXT NOT NULL UNIQUE COLLATE NOCASE, "
        "password_hash TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")",
    ],
}


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {version} is newer than this build "
            f"({SCHEMA_VERSION}). Upgrade Paperproof."
        )
    if version == 0:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    elif version < SCHEMA_VERSION:
        for target in range(version + 1, SCHEMA_VERSION + 1):
            for statement in MIGRATIONS.get(target, []):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {target}")
    conn.commit()


@contextmanager
def session(settings: Settings) -> Iterator[sqlite3.Connection]:
    conn = connect(settings.db_path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def audit(
    conn: sqlite3.Connection,
    actor: str,
    action: str,
    entity: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, entity, detail_json) VALUES (?, ?, ?, ?, ?)",
        (utcnow(), actor, action, entity, json.dumps(detail or {}, default=str)),
    )


def one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def all_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())
