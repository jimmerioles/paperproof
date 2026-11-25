from __future__ import annotations

import sqlite3
from pathlib import Path

from paperproof.config import Settings
from paperproof.extract.service import extract_document, review_extraction
from paperproof.ingest.pipeline import ingest_file
from paperproof.search.retrieve import search


def test_ingest_is_idempotent(
    conn: sqlite3.Connection, settings: Settings, sample_paths: list[Path]
) -> None:
    first = ingest_file(conn, settings, sample_paths[0])
    second = ingest_file(conn, settings, sample_paths[0])
    assert first.duplicate is False
    assert second.duplicate is True
    assert second.doc_id == first.doc_id
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_search_finds_the_right_clause(
    conn: sqlite3.Connection, settings: Settings, ingested
) -> None:
    hits = search(conn, "subletting without consent", doc_id=ingested.doc_id, limit=5)
    assert hits
    assert any("sublet" in hit.text.lower() for hit in hits)


def test_extraction_verifies_every_citation(
    conn: sqlite3.Connection, settings: Settings, ingested
) -> None:
    results = extract_document(conn, settings, ingested.doc_id)
    assert len(results) == 7
    term = next(result for result in results if result.field == "term_months")
    assert term.value == 24
    assert term.status == "pending"
    assert term.verifier == "exact"
    assert term.pdf_page == 3
    assert term.quote and "twenty-four (24) months" in term.quote
    assert term.boxes
    assert all(result.quote for result in results)


def test_rerun_updates_without_duplicating(
    conn: sqlite3.Connection, settings: Settings, ingested
) -> None:
    extract_document(conn, settings, ingested.doc_id)
    extract_document(conn, settings, ingested.doc_id)
    count = conn.execute(
        "SELECT COUNT(*) FROM extractions WHERE doc_id = ?", (ingested.doc_id,)
    ).fetchone()[0]
    assert count == 7


def test_review_writes_audit_event(conn: sqlite3.Connection, settings: Settings, ingested) -> None:
    results = extract_document(conn, settings, ingested.doc_id)
    target = results[0]
    review_extraction(conn, target.id, "approved", reviewer="tester", note="looks right")
    row = conn.execute("SELECT * FROM extractions WHERE id = ?", (target.id,)).fetchone()
    assert row["status"] == "approved"
    assert row["reviewer"] == "tester"
    event = conn.execute(
        "SELECT * FROM audit_log WHERE action = 'extraction.approved' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert event is not None
    assert event["entity"] == target.id
