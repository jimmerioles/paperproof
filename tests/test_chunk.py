from __future__ import annotations

from paperproof.ingest.chunk import chunk_pages
from paperproof.ingest.pdf import Line, Page


def make_page(number: int, lines: list[tuple[str, float]]) -> Page:
    return Page(
        pdf_page=number,
        width=612,
        height=792,
        text="\n".join(text for text, _ in lines),
        words=[],
        printed_label=str(number - 1),
        lines=[Line(text=text, size=size, pdf_page=number) for text, size in lines],
    )


def test_headings_split_sections_and_toc_is_skipped() -> None:
    pages = [
        make_page(1, [("Residential Lease Agreement", 22)]),
        make_page(
            2,
            [
                ("Contents", 16),
                ("1. Term .......... 3", 10),
                ("2. Rent .......... 4", 10),
                ("3. Subletting .......... 5", 10),
            ],
        ),
        make_page(
            3,
            [
                ("1. Term", 13),
                ("The term of this Lease is twelve (12) months and begins in 2026.", 10),
                ("2. Rent", 13),
                ("Tenant shall pay rent monthly without offset.", 10),
                ("Page 2 of 3", 8),
            ],
        ),
    ]
    chunks = chunk_pages(pages, body_size=10.0, chunk_chars=200, overlap_chars=40)
    headings = [chunk.heading for chunk in chunks]
    assert "1. Term" in headings
    assert "2. Rent" in headings
    assert all("...." not in (heading or "") for heading in headings)
    assert all("Page 2 of 3" not in chunk.text for chunk in chunks)
    assert all(1 <= chunk.page_start <= 3 for chunk in chunks)
    assert all(chunk.page_start <= chunk.page_end for chunk in chunks)


def test_long_section_splits_with_page_ranges() -> None:
    long_line = "Tenant shall keep the Premises in good repair and promptly report any damage. "
    lines = [("1. Maintenance", 13.0)]
    for _ in range(30):
        lines.append((long_line, 10.0))
    page = make_page(1, lines)
    chunks = chunk_pages([page], body_size=10.0, chunk_chars=300, overlap_chars=80)
    assert len(chunks) > 3
    assert all(chunk.heading == "1. Maintenance" for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)
