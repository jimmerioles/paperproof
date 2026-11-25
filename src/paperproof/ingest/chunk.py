"""Section-aware chunking that preserves page ranges."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from paperproof.ingest.pdf import PAGE_LABEL_PATTERNS, Line, Page

NUMBERED_HEADING = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+[A-Z]")
TOC_LINE = re.compile(r"(?:\.\s*){3,}\s*\d{1,4}\s*$|(?:…\s*){2,}\d{1,4}\s*$")
HEADING_MAX_CHARS = 90


@dataclass
class ChunkDraft:
    ordinal: int
    heading: str | None
    text: str
    page_start: int
    page_end: int


@dataclass
class _Section:
    heading: str | None
    lines: list[Line] = field(default_factory=list)


def _is_furniture(line: Line) -> bool:
    text = line.text.strip()
    return any(pattern.match(text) for pattern in PAGE_LABEL_PATTERNS)


def _is_toc_page(page: Page) -> bool:
    matches = sum(1 for line in page.lines if TOC_LINE.search(line.text))
    return matches >= 2


def _is_heading(line: Line, body_size: float) -> bool:
    text = line.text.strip()
    if not text or len(text) > HEADING_MAX_CHARS:
        return False
    if not line.ocr and body_size and line.size >= body_size + 1.6:
        return True
    if len(text.split()) > 10:
        return False
    if NUMBERED_HEADING.match(text):
        return True
    letters = [char for char in text if char.isalpha()]
    return bool(len(letters) >= 4 and all(char.isupper() for char in letters) and len(text) <= 70)


def _join_lines(lines: list[Line]) -> str:
    parts: list[str] = []
    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        if parts and not parts[-1].endswith("-"):
            parts.append(" ")
        parts.append(text)
    return "".join(parts).strip()


def _split_sections(pages: list[Page], body_size: float) -> list[_Section]:
    sections: list[_Section] = []
    current = _Section(heading=None)
    for page in pages:
        if _is_toc_page(page):
            continue
        for line in page.lines:
            if _is_furniture(line):
                continue
            if _is_heading(line, body_size):
                if current.lines:
                    sections.append(current)
                current = _Section(heading=line.text.strip())
            else:
                current.lines.append(line)
    if current.lines:
        sections.append(current)
    return sections


def _flush(
    chunks: list[ChunkDraft],
    lines: list[Line],
    heading: str | None,
    ordinal: int,
) -> int:
    if not lines:
        return ordinal
    text = _join_lines(lines)
    if len(text) < 20:
        return ordinal
    chunks.append(
        ChunkDraft(
            ordinal=ordinal,
            heading=heading,
            text=text,
            page_start=min(line.pdf_page for line in lines),
            page_end=max(line.pdf_page for line in lines),
        )
    )
    return ordinal + 1


def chunk_pages(
    pages: list[Page],
    body_size: float | None = None,
    chunk_chars: int = 900,
    overlap_chars: int = 160,
) -> list[ChunkDraft]:
    """Cut sections into overlapping windows without crossing headings."""
    if body_size is None:
        sizes = [line.size for page in pages for line in page.lines if len(line.text) >= 25]
        body_size = float(sorted(sizes)[len(sizes) // 2]) if sizes else 0.0

    chunks: list[ChunkDraft] = []
    ordinal = 0
    for section in _split_sections(pages, body_size):
        buffer: list[Line] = []
        size = 0
        for line in section.lines:
            addition = len(line.text) + 1
            if buffer and size + addition > chunk_chars:
                ordinal = _flush(chunks, buffer, section.heading, ordinal)
                overlap: list[Line] = []
                overlap_size = 0
                for previous in reversed(buffer):
                    if overlap and overlap_size + len(previous.text) + 1 > overlap_chars:
                        break
                    overlap.append(previous)
                    overlap_size += len(previous.text) + 1
                buffer = list(reversed(overlap))
                size = overlap_size
            buffer.append(line)
            size += addition
        ordinal = _flush(chunks, buffer, section.heading, ordinal)
    return chunks
