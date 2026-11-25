"""Ingestion pipeline: hash, store, parse, chunk, embed."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from paperproof.config import Settings
from paperproof.db import audit, new_id, one, utcnow
from paperproof.ingest.chunk import chunk_pages
from paperproof.ingest.pdf import parse_pdf
from paperproof.search.embed import get_embedder
from paperproof.search.index import index_chunks


@dataclass(frozen=True)
class IngestResult:
    doc_id: str
    duplicate: bool
    status: str
    page_count: int
    chunks: int
    needs_ocr: bool
    title: str
    filename: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ingest_file(
    conn: sqlite3.Connection,
    settings: Settings,
    source: Path,
    original_name: str | None = None,
) -> IngestResult:
    if source.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files are supported.")
    if not source.is_file():
        raise ValueError(f"File not found: {source}")

    filename = original_name or source.name
    checksum = sha256_file(source)
    existing = one(
        conn,
        "SELECT id, status, page_count, needs_ocr, title, filename FROM documents WHERE sha256 = ?",
        (checksum,),
    )
    if existing:
        return IngestResult(
            doc_id=str(existing["id"]),
            duplicate=True,
            status=str(existing["status"]),
            page_count=int(existing["page_count"]),
            chunks=0,
            needs_ocr=bool(existing["needs_ocr"]),
            title=str(existing["title"]),
            filename=str(existing["filename"]),
        )

    doc_id = new_id("doc")
    stored_name = f"{doc_id}.pdf"
    destination = settings.upload_dir / stored_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

    try:
        parsed = parse_pdf(destination)
        title = parsed.title or Path(filename).stem
        status = "needs_ocr" if parsed.needs_ocr else "indexed"

        conn.execute(
            "INSERT INTO documents "
            "(id, sha256, filename, stored_path, title, page_count, status, needs_ocr, "
            " meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                checksum,
                filename,
                stored_name,
                title,
                parsed.page_count,
                status,
                int(parsed.needs_ocr),
                "{}",
                utcnow(),
            ),
        )

        for page in parsed.pages:
            conn.execute(
                "INSERT INTO pages "
                "(doc_id, pdf_page, printed_label, width, height, text, words_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    page.pdf_page,
                    page.printed_label,
                    page.width,
                    page.height,
                    page.text,
                    json.dumps(
                        [word.as_dict() for word in page.words],
                        separators=(",", ":"),
                    ),
                ),
            )

        chunk_count = 0
        if not parsed.needs_ocr:
            drafts = chunk_pages(
                parsed.pages,
                chunk_chars=settings.chunk_chars,
                overlap_chars=settings.chunk_overlap_chars,
            )
            chunk_ids: list[int] = []
            for draft in drafts:
                cursor = conn.execute(
                    "INSERT INTO chunks (doc_id, ordinal, heading, text, page_start, page_end) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        doc_id,
                        draft.ordinal,
                        draft.heading,
                        draft.text,
                        draft.page_start,
                        draft.page_end,
                    ),
                )
                chunk_ids.append(int(cursor.lastrowid or 0))
            chunk_count = len(chunk_ids)
            if chunk_ids:
                index_chunks(
                    conn,
                    chunk_ids,
                    [draft.text for draft in drafts],
                    get_embedder(settings.embedder),
                )

        audit(
            conn,
            actor="system",
            action="document.ingested",
            entity=doc_id,
            detail={
                "filename": filename,
                "page_count": parsed.page_count,
                "chunks": chunk_count,
                "needs_ocr": parsed.needs_ocr,
            },
        )
        return IngestResult(
            doc_id=doc_id,
            duplicate=False,
            status=status,
            page_count=parsed.page_count,
            chunks=chunk_count,
            needs_ocr=parsed.needs_ocr,
            title=title,
            filename=filename,
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
