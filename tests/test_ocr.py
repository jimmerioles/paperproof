from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from paperproof.config import Settings
from paperproof.db import init_db
from paperproof.ingest.ocr import (
    OcrPage,
    TesseractOcrEngine,
    get_ocr_engine,
    tesseract_available,
)
from paperproof.ingest.pdf import Line, Word, parse_pdf

requires_tesseract = pytest.mark.skipif(
    not tesseract_available(), reason="tesseract-ocr is not installed"
)


class FakeOcrEngine:
    name = "fake"

    def ocr_page(self, pdf_path: Path, pdf_page: int, width: float, height: float) -> OcrPage:
        text = "Fake OCR text for this page with enough characters to clear the threshold."
        words = [
            Word(text="Fake", x=72.0, y=100.0, w=30.0, h=10.0),
            Word(text="OCR", x=106.0, y=100.0, w=24.0, h=10.0),
        ]
        lines = [Line(text=text, size=10.0, pdf_page=pdf_page, ocr=True)]
        return OcrPage(text=text, words=words, lines=lines, confidence=88.0, engine="fake")


def test_fake_ocr_replaces_empty_pages(sample_paths: list[Path]) -> None:
    parsed = parse_pdf(sample_paths[4], ocr_engine=FakeOcrEngine())
    assert parsed.needs_ocr is False
    assert parsed.ocr_pages == 2
    assert parsed.ocr_confidence == 88.0
    assert parsed.ocr_low_confidence is False
    assert all(page.ocr for page in parsed.pages)
    assert parsed.pages[0].words
    assert "Fake OCR" in parsed.pages[0].text


@requires_tesseract
def test_tesseract_reads_scanned_lease(sample_paths: list[Path]) -> None:
    engine = TesseractOcrEngine()
    parsed = parse_pdf(sample_paths[4], ocr_engine=engine)
    assert parsed.needs_ocr is False
    assert parsed.ocr_pages == 2
    assert parsed.ocr_confidence is not None
    assert parsed.ocr_confidence > 70
    text = "\n".join(page.text for page in parsed.pages)
    assert "twelve (12) months" in text
    assert "security deposit of $2,900.00" in text
    assert parsed.pages[0].words
    assert parsed.pages[0].ocr_engine == "tesseract"


def test_ocr_mode_off_disables_engine(settings: Settings) -> None:
    assert get_ocr_engine(settings.model_copy(update={"ocr": "off"})) is None


@requires_tesseract
def test_ocr_mode_tesseract_returns_engine(settings: Settings) -> None:
    engine = get_ocr_engine(settings.model_copy(update={"ocr": "tesseract"}))
    assert engine is not None
    assert engine.name == "tesseract"


def test_v1_database_migrates_to_ocr_schema(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "v1.db")
    conn.executescript(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            title TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            status TEXT NOT NULL,
            needs_ocr INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            meta_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE TABLE pages (
            doc_id TEXT NOT NULL,
            pdf_page INTEGER NOT NULL,
            printed_label TEXT,
            width REAL NOT NULL,
            height REAL NOT NULL,
            text TEXT NOT NULL,
            words_json TEXT NOT NULL,
            PRIMARY KEY (doc_id, pdf_page)
        );
        PRAGMA user_version = 1;
        """
    )
    init_db(conn)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    document_columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    page_columns = {row[1] for row in conn.execute("PRAGMA table_info(pages)")}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert version == 3
    assert {"ocr_pages", "ocr_confidence", "ocr_low_confidence"} <= document_columns
    assert {"ocr", "ocr_confidence", "ocr_engine"} <= page_columns
    assert "users" in tables
