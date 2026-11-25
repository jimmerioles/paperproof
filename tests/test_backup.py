from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from paperproof.backup import (
    create_backup,
    read_manifest,
    restore_backup,
    run_restore_drill,
)
from paperproof.config import Settings
from paperproof.extract.service import extract_document
from paperproof.ingest.pipeline import ingest_file


def test_backup_and_restore_round_trip(
    settings: Settings,
    conn: sqlite3.Connection,
    sample_paths: list[Path],
    tmp_path: Path,
) -> None:
    ingested = ingest_file(conn, settings, sample_paths[0])
    extract_document(conn, settings, ingested.doc_id)
    conn.commit()

    backup_dir = tmp_path / "backup"
    info = create_backup(settings, backup_dir)
    assert info.counts["documents"] == 1
    assert info.counts["pages"] == 5
    assert info.counts["extractions"] == 7
    assert info.counts["uploads"] == 1
    manifest = read_manifest(backup_dir)
    assert manifest["format"] == "paperproof-backup"
    assert json.loads((backup_dir / "manifest.json").read_text())["version"] == 1

    restored_dir = tmp_path / "restored"
    restored = restore_backup(backup_dir, restored_dir)
    assert restored.counts["documents"] == 1
    restored_conn = sqlite3.connect(restored_dir / "paperproof.db")
    try:
        assert restored_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert restored_conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 5
        assert restored_conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0] == 7
        stored = restored_conn.execute("SELECT stored_path FROM documents").fetchone()[0]
    finally:
        restored_conn.close()
    assert (restored_dir / "uploads" / stored).exists()
    assert (restored_dir / "renders").is_dir()


def test_restore_refuses_a_non_empty_target(
    settings: Settings,
    conn: sqlite3.Connection,
    sample_paths: list[Path],
    tmp_path: Path,
) -> None:
    ingest_file(conn, settings, sample_paths[0])
    conn.commit()
    backup_dir = tmp_path / "backup"
    create_backup(settings, backup_dir)
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "keep.txt").write_text("do not overwrite")
    with pytest.raises(ValueError, match="must be empty"):
        restore_backup(backup_dir, target)
    assert (target / "keep.txt").read_text() == "do not overwrite"


def test_backup_refuses_the_data_directory(settings: Settings) -> None:
    with pytest.raises(ValueError, match="data directory"):
        create_backup(settings, settings.data_dir)


def test_restore_drill_passes() -> None:
    result = run_restore_drill()
    assert result.passed is True
    assert result.documents == 1
    assert result.pages == 5
    assert result.extractions == 7
