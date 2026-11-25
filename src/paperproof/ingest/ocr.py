"""Local OCR for scanned PDF pages.

Tesseract is the default engine. It is local, offline, and leaves no data
outside the deployment. Cloud OCR would be a second adapter behind the same
protocol, with an explicit tenant opt-in.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Protocol, runtime_checkable

import pypdfium2 as pdfium
import pytesseract
from PIL import Image

from paperproof.config import Settings
from paperproof.ingest.pdf import Line, Word

OCR_DPI = 300
OCR_CONFIG = "--oem 1 --psm 3"


class OcrError(RuntimeError):
    """Raised when OCR cannot run or fails for a page."""


@dataclass(frozen=True)
class OcrPage:
    text: str
    words: list[Word]
    lines: list[Line]
    confidence: float
    engine: str


@runtime_checkable
class OcrEngine(Protocol):
    name: str

    def ocr_page(self, pdf_path: Path, pdf_page: int, width: float, height: float) -> OcrPage: ...


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


class TesseractOcrEngine:
    name = "tesseract"

    def __init__(self, dpi: int = OCR_DPI) -> None:
        if not tesseract_available():
            raise OcrError(
                "Tesseract is not installed. Install tesseract-ocr or set PAPERPROOF_OCR=off."
            )
        self.dpi = dpi
        self.scale = dpi / 72.0

    def _render(self, pdf_path: Path, pdf_page: int) -> Image.Image:
        document = pdfium.PdfDocument(str(pdf_path))
        try:
            if pdf_page < 1 or pdf_page > len(document):
                raise OcrError(f"page {pdf_page} out of range")
            page = document[pdf_page - 1]
            bitmap = page.render(scale=self.scale)  # pyright: ignore[reportArgumentType]
            try:
                image = bitmap.to_pil()
            finally:
                bitmap.close()
        finally:
            document.close()
        return image.convert("RGB")

    def ocr_page(self, pdf_path: Path, pdf_page: int, width: float, height: float) -> OcrPage:
        try:
            image = self._render(pdf_path, pdf_page)
            data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                config=OCR_CONFIG,
            )
        except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError) as exc:
            raise OcrError(f"Tesseract failed on page {pdf_page}: {exc}") from exc
        except Exception as exc:
            raise OcrError(f"Could not render page {pdf_page} for OCR: {exc}") from exc

        grouped: dict[tuple[int, int, int], list[Word]] = {}
        confidences: list[tuple[float, int]] = []
        count = len(data.get("text", []))
        for index in range(count):
            text = str(data["text"][index]).strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                confidence = -1.0
            if confidence < 0:
                continue
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
            word = Word(
                text=text,
                x=round(float(data["left"][index]) / self.scale, 2),
                y=round(float(data["top"][index]) / self.scale, 2),
                w=round(float(data["width"][index]) / self.scale, 2),
                h=round(float(data["height"][index]) / self.scale, 2),
            )
            grouped.setdefault(key, []).append(word)
            confidences.append((confidence, len(text)))

        lines: list[Line] = []
        for words in grouped.values():
            text = " ".join(word.text for word in words).strip()
            if not text:
                continue
            height_guess = median(word.h for word in words) if words else 0.0
            lines.append(Line(text=text, size=round(height_guess, 2), pdf_page=pdf_page, ocr=True))

        words = [word for group in grouped.values() for word in group]
        page_text = "\n".join(line.text for line in lines)
        total_weight = sum(weight for _, weight in confidences)
        confidence = (
            sum(value * weight for value, weight in confidences) / total_weight
            if total_weight
            else 0.0
        )
        return OcrPage(
            text=page_text,
            words=words,
            lines=lines,
            confidence=round(confidence, 2),
            engine=self.name,
        )


def get_ocr_engine(settings: Settings) -> OcrEngine | None:
    if settings.ocr == "off":
        return None
    if settings.ocr == "tesseract":
        return TesseractOcrEngine(dpi=settings.ocr_dpi)
    if settings.ocr == "auto":
        return TesseractOcrEngine(dpi=settings.ocr_dpi) if tesseract_available() else None
    raise ValueError(f"Unknown OCR mode {settings.ocr!r}. Use 'auto', 'tesseract', or 'off'.")
