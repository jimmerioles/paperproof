"""Quote verification: prove a quote exists before showing it.

This module is the trust boundary. Model output is never displayed as a quote
until the exact words are found in the source page and mapped to highlight
boxes. Fuzzy matching tolerates OCR and line-break noise, and is marked as such.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from paperproof.ingest.pdf import Word

TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00ad": "",
        "\u00a0": " ",
    }
)


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class PageRecord:
    pdf_page: int
    printed_label: str | None
    width: float
    height: float
    words: list[Word]


@dataclass(frozen=True)
class Verification:
    quote: str
    pdf_page: int
    printed_label: str | None
    boxes: list[Box]
    method: str
    score: float


@dataclass(frozen=True)
class _Ref:
    word: Word
    token: str
    start: int
    end: int


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(TRANSLATION)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def match_token(value: str) -> str:
    token = normalize_text(value).casefold()
    token = token.strip("\"'\u201c\u201d\u2018\u2019")
    token = token.strip(",.;:!?)]}")
    token = token.lstrip("([{")
    return token


def load_pages(conn: sqlite3.Connection, doc_id: str) -> list[PageRecord]:
    rows = conn.execute(
        "SELECT pdf_page, printed_label, width, height, words_json "
        "FROM pages WHERE doc_id = ? ORDER BY pdf_page",
        (doc_id,),
    ).fetchall()
    pages: list[PageRecord] = []
    for row in rows:
        raw_words = json.loads(row["words_json"])
        words = [
            Word(
                text=str(item["t"]),
                x=float(item["x"]),
                y=float(item["y"]),
                w=float(item["w"]),
                h=float(item["h"]),
            )
            for item in raw_words
        ]
        pages.append(
            PageRecord(
                pdf_page=int(row["pdf_page"]),
                printed_label=row["printed_label"],
                width=float(row["width"]),
                height=float(row["height"]),
                words=words,
            )
        )
    return pages


def _page_refs(page: PageRecord) -> tuple[str, list[_Ref]]:
    parts: list[str] = []
    refs: list[_Ref] = []
    position = 0
    for word in page.words:
        token = match_token(word.text)
        if not token:
            continue
        if parts:
            position += 1
        start = position
        parts.append(token)
        position += len(token)
        refs.append(_Ref(word=word, token=token, start=start, end=position))
    return " ".join(parts), refs


def _join_words(words: list[Word]) -> str:
    output = ""
    for word in words:
        text = word.text
        if not output:
            output = text
        elif text[:1] in ".,;:!?)]}%":
            output += text
        else:
            output += " " + text
    return output


def _boxes_for(words: list[Word]) -> list[Box]:
    if not words:
        return []
    ordered = sorted(words, key=lambda word: (round(word.y, 1), word.x))
    lines: list[list[Word]] = []
    current: list[Word] = []
    line_y: float | None = None
    for word in ordered:
        if line_y is None or abs(word.y - line_y) <= 3.0:
            current.append(word)
            line_y = word.y if line_y is None else line_y
        else:
            lines.append(current)
            current = [word]
            line_y = word.y
    if current:
        lines.append(current)

    boxes: list[Box] = []
    for line in lines:
        x0 = min(word.x for word in line)
        y0 = min(word.y for word in line)
        x1 = max(word.x + word.w for word in line)
        y1 = max(word.y + word.h for word in line)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            continue
        boxes.append(
            Box(
                x=round(x0, 2),
                y=round(y0, 2),
                w=round(x1 - x0, 2),
                h=round(y1 - y0, 2),
            )
        )
    return boxes[:20]


def _quote_text(quote: str) -> str:
    tokens = (match_token(part) for part in normalize_text(quote).split())
    return " ".join(token for token in tokens if token)


def _exact(page: PageRecord, quote: str) -> Verification | None:
    page_text, refs = _page_refs(page)
    if not page_text or not quote:
        return None
    start = page_text.find(quote)
    if start < 0:
        return None
    end = start + len(quote)
    matched = [ref for ref in refs if ref.start < end and ref.end > start]
    if not matched:
        return None
    return Verification(
        quote=_join_words([ref.word for ref in matched]),
        pdf_page=page.pdf_page,
        printed_label=page.printed_label,
        boxes=_boxes_for([ref.word for ref in matched]),
        method="exact",
        score=1.0,
    )


def _fuzzy(page: PageRecord, quote: str) -> Verification | None:
    _, refs = _page_refs(page)
    if not refs:
        return None
    quote_tokens = [token for token in (match_token(part) for part in quote.split()) if token]
    if len(quote_tokens) < 3:
        return None
    page_tokens = [ref.token for ref in refs]
    matcher = SequenceMatcher(None, page_tokens, quote_tokens, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size > 0]
    if not blocks:
        return None

    # Merge nearby matching blocks so a single OCR error in the middle of a
    # clause does not split the match into two useless fragments.
    clusters: list[tuple[int, int, int]] = []
    p_start = blocks[0].a
    p_end = blocks[0].a + blocks[0].size
    q_end = blocks[0].b + blocks[0].size
    matched = blocks[0].size
    for block in blocks[1:]:
        gap_q = block.b - q_end
        gap_p = block.a - p_end
        if 0 <= gap_q <= 2 and 0 <= gap_p <= 2:
            p_end = block.a + block.size
            q_end = block.b + block.size
            matched += block.size
        else:
            clusters.append((p_start, p_end, matched))
            p_start = block.a
            p_end = block.a + block.size
            q_end = block.b + block.size
            matched = block.size
    clusters.append((p_start, p_end, matched))

    start, end, matched = max(clusters, key=lambda cluster: cluster[2])
    coverage = matched / len(quote_tokens)
    if matched < 3 or coverage < 0.8:
        return None
    if end - start > len(quote_tokens) + 3:
        return None

    matched_words = [ref.word for ref in refs[start:end]]
    return Verification(
        quote=_join_words(matched_words),
        pdf_page=page.pdf_page,
        printed_label=page.printed_label,
        boxes=_boxes_for(matched_words),
        method="fuzzy",
        score=round(coverage, 4),
    )


def verify_quote(
    pages: list[PageRecord],
    quote: str | None,
    hint_page: int | None = None,
) -> Verification | None:
    normalized = _quote_text(quote or "")
    if len(normalized) < 8:
        return None

    ordered = list(pages)
    if hint_page is not None:
        ordered.sort(key=lambda page: (page.pdf_page != hint_page, page.pdf_page))

    for page in ordered:
        result = _exact(page, normalized)
        if result:
            return result

    for page in ordered:
        result = _fuzzy(page, normalized)
        if result:
            return result
    return None
