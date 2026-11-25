"""PDF parsing with layout, word coordinates, page labels, and rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import pdfplumber
import pypdfium2 as pdfium

PAGE_LABEL_PATTERNS = (
    re.compile(r"^page\s+(\d{1,4})(?:\s+of\s+\d{1,4})?$", re.IGNORECASE),
    re.compile(r"^[-\u2013\u2014]?\s*(\d{1,4})\s*[-\u2013\u2014]?$"),
)


@dataclass(frozen=True)
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float

    def as_dict(self) -> dict[str, object]:
        return {"t": self.text, "x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class Line:
    text: str
    size: float
    pdf_page: int


@dataclass
class Page:
    pdf_page: int
    width: float
    height: float
    text: str
    words: list[Word]
    printed_label: str | None
    lines: list[Line] = field(default_factory=list, repr=False)


@dataclass
class ParsedDocument:
    title: str
    pages: list[Page]
    needs_ocr: bool

    @property
    def page_count(self) -> int:
        return len(self.pages)


def _clean_title(raw: object, fallback: str) -> str:
    if isinstance(raw, str):
        title = raw.replace("\x00", " ").strip()
        if title and title.lower() not in {"untitled", "none", "document"}:
            return title[:300]
    return fallback


def _line_size(line: dict[str, object]) -> float:
    raw_chars = line.get("chars")
    chars = raw_chars if isinstance(raw_chars, list) else []
    sizes = [float(c.get("size", 0.0)) for c in chars if isinstance(c, dict)]
    sizes = [s for s in sizes if s > 0]
    return max(sizes) if sizes else 0.0


def _detect_printed_label(lines: list[str]) -> str | None:
    edges = [ln.strip() for ln in lines[:2] + lines[-2:] if ln.strip()]
    for line in edges:
        for pattern in PAGE_LABEL_PATTERNS:
            match = pattern.match(line)
            if match:
                return str(int(match.group(1)))
    return None


def parse_pdf(path: Path) -> ParsedDocument:
    """Parse a PDF into pages with text, line sizes, and word boxes.

    Raises pdfplumber/pdfminer errors on malformed files.
    """
    pages: list[Page] = []
    with pdfplumber.open(path) as pdf:
        title = _clean_title((pdf.metadata or {}).get("Title"), path.stem)
        for index, raw_page in enumerate(pdf.pages, start=1):
            raw_lines = raw_page.extract_text_lines(strip=True, return_chars=True)
            lines = [
                Line(
                    text=str(line.get("text", "")).strip(),
                    size=_line_size(line),
                    pdf_page=index,
                )
                for line in raw_lines
                if str(line.get("text", "")).strip()
            ]

            raw_words = raw_page.extract_words(
                extra_attrs=["size"],
                keep_blank_chars=False,
                use_text_flow=False,
            )
            words = [
                Word(
                    text=str(word["text"]),
                    x=round(float(word["x0"]), 2),
                    y=round(float(word["top"]), 2),
                    w=round(float(word["x1"]) - float(word["x0"]), 2),
                    h=round(float(word["bottom"]) - float(word["top"]), 2),
                )
                for word in raw_words
                if str(word.get("text", "")).strip()
            ]

            page_text = "\n".join(line.text for line in lines)
            width = float(raw_page.width or 612)
            height = float(raw_page.height or 792)
            pages.append(
                Page(
                    pdf_page=index,
                    width=round(width, 2),
                    height=round(height, 2),
                    text=page_text,
                    words=words,
                    printed_label=_detect_printed_label(page_text.splitlines()),
                    lines=lines,
                )
            )

    alnum = sum(1 for page in pages for char in page.text if char.isalnum())
    needs_ocr = bool(pages) and (alnum / len(pages)) < 40
    return ParsedDocument(title=title, pages=pages, needs_ocr=needs_ocr)


def body_font_size(pages: list[Page]) -> float:
    sizes = [line.size for page in pages for line in page.lines if len(line.text) >= 25]
    return float(median(sizes)) if sizes else 0.0


def render_page_png(
    pdf_path: Path,
    pdf_page: int,
    out_path: Path,
    scale: int = 2,
) -> Path:
    """Render one page to a cached PNG. pdf_page is 1-based."""
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        if pdf_page < 1 or pdf_page > len(document):
            raise ValueError(f"page {pdf_page} out of range 1..{len(document)}")
        page = document[pdf_page - 1]
        bitmap = page.render(scale=scale)
        try:
            image = bitmap.to_pil()
        finally:
            bitmap.close()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".tmp.png")
        image.save(tmp_path, format="PNG", optimize=True)
        tmp_path.replace(out_path)
    finally:
        document.close()
    return out_path
