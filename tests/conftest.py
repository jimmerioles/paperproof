"""Shared fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperproof.api.factory import create_app
from paperproof.config import Settings
from paperproof.db import session
from paperproof.extract.service import extract_document
from paperproof.ingest.pipeline import ingest_file
from paperproof.samples import generate_samples


@pytest.fixture(scope="session")
def sample_paths(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    settings = Settings(data_dir=tmp_path_factory.mktemp("sample-corpus"))
    settings.ensure_dirs()
    return generate_samples(settings, force=True)


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    resolved = Settings(data_dir=tmp_path / "data")
    resolved.ensure_dirs()
    return resolved


@pytest.fixture()
def conn(settings: Settings) -> Iterator[sqlite3.Connection]:
    with session(settings) as connection:
        yield connection


@pytest.fixture()
def ingested(conn: sqlite3.Connection, settings: Settings, sample_paths: list[Path]):
    result = ingest_file(conn, settings, sample_paths[0])
    conn.commit()
    return result


@pytest.fixture()
def extracted(conn: sqlite3.Connection, settings: Settings, ingested):
    results = extract_document(conn, settings, ingested.doc_id)
    conn.commit()
    return results


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
