"""PDF parsing with layout, word coordinates, page labels, and rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING

import pdfplumber
import pypdfium2 as pdfium

if TYPE_CHECKING:
    from paperproof.ingest.ocr import OcrEngine

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
    ocr: bool = False


@dataclass
class Page:
    pdf_page: int
    width: float
    height: float
    text: str
    words: list[Word]
    printed_label: str | None
    lines: list[Line] = field(default_factory=list, repr=False)
    ocr: bool = False
    ocr_confidence: float | None = None
    ocr_engine: str | None = None


@dataclass
class ParsedDocument:
    title: str
    pages: list[Page]
    needs_ocr: bool
    ocr_pages: int = 0
    ocr_confidence: float | None = None
    ocr_low_confidence: bool = False
    ocr_errors: list[str] = field(default_factory=list)

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


def parse_pdf(
    path: Path,
    ocr_engine: OcrEngine | None = None,
    ocr_min_chars: int = 40,
    ocr_low_confidence: float = 60.0,
) -> ParsedDocument:
    """Parse a PDF into pages with text, line sizes, and word boxes.

    Pages with too little text are passed to ``ocr_engine`` when one is
    supplied. OCR failures are recorded and leave the page viewable.
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

    ocr_errors: list[str] = []
    if ocr_engine is not None:
        for page in pages:
            page_alnum = sum(1 for char in page.text if char.isalnum())
            if page_alnum >= ocr_min_chars:
                continue
            try:
                result = ocr_engine.ocr_page(path, page.pdf_page, page.width, page.height)
            except Exception as exc:
                ocr_errors.append(f"Page {page.pdf_page}: {exc}")
                continue
            if not result.text.strip():
                continue
            page.text = result.text
            page.words = result.words
            page.lines = result.lines
            page.ocr = True
            page.ocr_confidence = result.confidence
            page.ocr_engine = result.engine
            page.printed_label = _detect_printed_label(page.text.splitlines())

    alnum = sum(1 for page in pages for char in page.text if char.isalnum())
    needs_ocr = bool(pages) and (alnum / len(pages)) < 40
    ocr_pages = [page for page in pages if page.ocr]
    confidences = [
        float(page.ocr_confidence) for page in ocr_pages if page.ocr_confidence is not None
    ]
    ocr_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
    has_low_confidence = any(
        (page.ocr_confidence or 0.0) < ocr_low_confidence for page in ocr_pages
    )
    return ParsedDocument(
        title=title,
        pages=pages,
        needs_ocr=needs_ocr,
        ocr_pages=len(ocr_pages),
        ocr_confidence=ocr_confidence,
        ocr_low_confidence=has_low_confidence,
        ocr_errors=ocr_errors,
    )


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
