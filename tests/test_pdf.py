from __future__ import annotations

from pathlib import Path

from paperproof.ingest.pdf import parse_pdf


def test_parse_sample_lease(sample_paths: list[Path]) -> None:
    parsed = parse_pdf(sample_paths[0])
    assert parsed.page_count == 5
    assert parsed.needs_ocr is False
    assert "Alder Court" in parsed.title
    assert parsed.pages[0].printed_label is None
    assert parsed.pages[1].printed_label == "1"
    assert parsed.pages[2].printed_label == "2"
    assert parsed.pages[2].words
    assert any("Subletting" in line.text for page in parsed.pages for line in page.lines)


def test_scanned_pdf_is_flagged(sample_paths: list[Path]) -> None:
    parsed = parse_pdf(sample_paths[4])
    assert parsed.needs_ocr is True
    assert parsed.page_count >= 1
    assert sum(len(page.text) for page in parsed.pages) == 0
