"""Backup, restore, and a repeatable restore drill."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperproof.config import Settings
from paperproof.db import connect, init_db, utcnow
from paperproof.extract.service import extract_document
from paperproof.ingest.pipeline import ingest_file
from paperproof.samples import generate_samples

BACKUP_FORMAT = "paperproof-backup"
BACKUP_VERSION = 1


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: str
    counts: dict[str, int]
    schema_version: int


@dataclass(frozen=True)
class DrillResult:
    passed: bool
    documents: int
    pages: int
    extractions: int
    backup_path: Path
    restored_path: Path


def _sqlite_counts(path: Path) -> tuple[dict[str, int], int]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        documents = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        pages = int(conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
        chunks = int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        extractions = int(conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0])
        schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()
    return (
        {
            "documents": documents,
            "pages": pages,
            "chunks": chunks,
            "extractions": extractions,
        },
        schema_version,
    )


def _integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return result == "ok"


def _file_count(directory: Path, suffix: str) -> int:
    if not directory.exists():
        return 0
    return sum(1 for path in directory.rglob(f"*{suffix}") if path.is_file())


def create_backup(settings: Settings, out_dir: Path, force: bool = False) -> BackupInfo:
    out = Path(out_dir)
    for protected in (settings.upload_dir, settings.render_dir):
        if out == protected or protected in out.parents:
            raise ValueError("Backup directory must be outside uploads and renders.")
    if out.exists() and any(out.iterdir()):
        if not force:
            raise ValueError("Backup directory is not empty. Use --force to replace it.")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    settings.ensure_dirs()

    source = connect(settings.db_path)
    destination = sqlite3.connect(out / "paperproof.db")
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    if not _integrity_ok(out / "paperproof.db"):
        raise RuntimeError("Backup database failed the integrity check.")

    for name, source_dir in (
        ("uploads", settings.upload_dir),
        ("renders", settings.render_dir),
    ):
        target_dir = out / name
        if source_dir.exists():
            shutil.copytree(source_dir, target_dir)
        else:
            target_dir.mkdir()

    counts, schema_version = _sqlite_counts(out / "paperproof.db")
    counts["uploads"] = _file_count(out / "uploads", ".pdf")
    counts["renders"] = _file_count(out / "renders", ".png")
    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": utcnow(),
        "schema_version": schema_version,
        "counts": counts,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return BackupInfo(
        path=out,
        created_at=str(manifest["created_at"]),
        counts=counts,
        schema_version=schema_version,
    )


def read_manifest(backup_dir: Path) -> dict[str, Any]:
    path = Path(backup_dir) / "manifest.json"
    if not path.exists():
        raise ValueError("Backup is missing manifest.json.")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Backup manifest is not valid JSON.") from exc
    if manifest.get("format") != BACKUP_FORMAT:
        raise ValueError("Backup manifest has an unknown format.")
    if manifest.get("version") != BACKUP_VERSION:
        raise ValueError(f"Unsupported backup version: {manifest.get('version')}")
    return manifest


def restore_backup(backup_dir: Path, target_data_dir: Path) -> BackupInfo:
    backup = Path(backup_dir)
    manifest = read_manifest(backup)
    database = backup / "paperproof.db"
    if not database.exists():
        raise ValueError("Backup is missing paperproof.db.")
    if not _integrity_ok(database):
        raise ValueError("Backup database failed the integrity check.")

    target = Path(target_data_dir)
    if backup == target or backup in target.parents:
        raise ValueError("Target data directory must be outside the backup.")
    if target.exists() and any(target.iterdir()):
        raise ValueError("Target data directory must be empty.")

    created_target = not target.exists()
    target.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(database, target / "paperproof.db")
        for name in ("uploads", "renders"):
            source_dir = backup / name
            if source_dir.exists():
                shutil.copytree(source_dir, target / name)
            else:
                (target / name).mkdir()
        if not _integrity_ok(target / "paperproof.db"):
            raise RuntimeError("Restored database failed the integrity check.")
    except Exception:
        if created_target:
            shutil.rmtree(target, ignore_errors=True)
        raise

    counts = {key: int(value) for key, value in dict(manifest.get("counts", {})).items()}
    return BackupInfo(
        path=target,
        created_at=str(manifest.get("created_at", "")),
        counts=counts,
        schema_version=int(manifest.get("schema_version", 0)),
    )


def run_restore_drill(keep: bool = False) -> DrillResult:
    root = Path(tempfile.mkdtemp(prefix="paperproof-drill-"))
    source = Settings(data_dir=root / "source", auth_disabled=True)
    source.ensure_dirs()
    paths = generate_samples(source, force=True)
    source_conn = connect(source.db_path)
    try:
        init_db(source_conn)
        ingested = ingest_file(source_conn, source, paths[0])
        extract_document(source_conn, source, ingested.doc_id)
        source_conn.commit()
    finally:
        source_conn.close()
    source_counts, _ = _sqlite_counts(source.db_path)

    backup = create_backup(source, root / "backup")
    restored = restore_backup(root / "backup", root / "restored")
    restored_conn = connect(root / "restored" / "paperproof.db")
    try:
        restored_counts, _ = _sqlite_counts(root / "restored" / "paperproof.db")
    finally:
        restored_conn.close()

    selected = ("documents", "pages", "chunks", "extractions")
    passed = all(source_counts[key] == restored_counts[key] for key in selected) and (
        backup.counts["documents"] == restored.counts["documents"]
    )

    result = DrillResult(
        passed=passed,
        documents=restored_counts["documents"],
        pages=restored_counts["pages"],
        extractions=restored_counts["extractions"],
        backup_path=backup.path,
        restored_path=restored.path,
    )
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return result
