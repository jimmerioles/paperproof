from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paperproof.extract.service import extract_document
from paperproof.ingest.ocr import tesseract_available
from paperproof.ingest.pipeline import ingest_file

requires_tesseract = pytest.mark.skipif(
    not tesseract_available(), reason="tesseract-ocr is not installed"
)


def test_dashboard_renders(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Terms with receipts." in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'self'")


def test_document_page_shows_verified_records(
    client: TestClient, conn: sqlite3.Connection, settings, ingested
) -> None:
    extract_document(conn, settings, ingested.doc_id)
    conn.commit()
    response = client.get(f"/documents/{ingested.doc_id}")
    assert response.status_code == 200
    assert "24 months" in response.text
    assert "Ready to review" in response.text
    assert "Subletting" in response.text
    assert "Allowed with consent" in response.text


def test_page_image_renders(
    client: TestClient, conn: sqlite3.Connection, settings, ingested
) -> None:
    extract_document(conn, settings, ingested.doc_id)
    conn.commit()
    response = client.get(f"/documents/{ingested.doc_id}/pages/3.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_source_view_verifies_quote(
    client: TestClient, conn: sqlite3.Connection, settings, ingested
) -> None:
    results = extract_document(conn, settings, ingested.doc_id)
    conn.commit()
    term = next(result for result in results if result.field == "term_months")
    response = client.get(
        f"/documents/{ingested.doc_id}/source",
        params={"page": term.pdf_page, "quote": term.quote},
    )
    assert response.status_code == 200
    assert "Verified on the page" in response.text
    assert "twenty-four (24) months" in response.text


def test_source_rejects_unverifiable_quote(
    client: TestClient, conn: sqlite3.Connection, settings, ingested
) -> None:
    extract_document(conn, settings, ingested.doc_id)
    conn.commit()
    response = client.get(
        f"/documents/{ingested.doc_id}/source",
        params={"page": 1, "quote": "The tenant may keep a dragon in the basement."},
    )
    assert response.status_code == 200
    assert "Not verifiable" in response.text


def test_search_returns_passages(
    client: TestClient, conn: sqlite3.Connection, settings, ingested
) -> None:
    extract_document(conn, settings, ingested.doc_id)
    conn.commit()
    response = client.get("/search", params={"q": "subletting consent"})
    assert response.status_code == 200
    assert "passages" in response.text
    assert "Subletting" in response.text


def test_review_advances_to_next_field(
    client: TestClient, conn: sqlite3.Connection, settings, ingested
) -> None:
    results = extract_document(conn, settings, ingested.doc_id)
    conn.commit()
    term = next(result for result in results if result.field == "term_months")
    response = client.post(
        f"/extractions/{term.id}/review",
        data={"decision": "approved"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Term approved." in response.text
    row = conn.execute("SELECT status FROM extractions WHERE id = ?", (term.id,)).fetchone()
    assert row["status"] == "approved"


def test_upload_ingests_pdf(
    client: TestClient, sample_paths: list[Path], conn: sqlite3.Connection
) -> None:
    path = sample_paths[1]
    with path.open("rb") as handle:
        response = client.post(
            "/documents",
            files={"files": (path.name, handle, "application/pdf")},
            follow_redirects=False,
        )
    assert response.status_code == 303
    dashboard = client.get("/").text
    assert "Apartment Lease" in dashboard


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@requires_tesseract
def test_scanned_document_shows_ocr(
    client: TestClient,
    conn: sqlite3.Connection,
    settings,
    sample_paths: list[Path],
) -> None:
    result = ingest_file(conn, settings, sample_paths[4])
    conn.commit()
    extract_document(conn, settings, result.doc_id)
    conn.commit()
    response = client.get(f"/documents/{result.doc_id}")
    assert response.status_code == 200
    assert "Text recovered with OCR" in response.text
    assert "12 months" in response.text
    assert "Prohibited" in response.text
    assert "OCR" in response.text


def test_html_404(client: TestClient) -> None:
    response = client.get("/missing", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert "Page not found." in response.text
