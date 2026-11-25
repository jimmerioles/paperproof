"""Deterministic rule baseline for lease extraction.

This is not the product's intelligence. It is a fast, offline, inspectable
baseline that proves the ingestion, retrieval, verification, and review loop.
The LLM extractor plugs into the same interface.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from paperproof.extract.base import Candidate
from paperproof.extract.templates import FieldSpec
from paperproof.search.retrieve import Hit

SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
MONEY = r"\$\s*([\d,]+(?:\.\d{2})?)"


@dataclass(frozen=True)
class RuleMatch:
    value: Any
    quote: str
    confidence: float


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_BREAK.split(text) if part.strip()]


def _money(value: str) -> float:
    return float(value.replace(",", ""))


def _parse_term(text: str) -> RuleMatch | None:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if "term" not in lowered:
            continue
        match = re.search(r"\((\d{1,2})\)\s*(months?|years?)", sentence, re.IGNORECASE)
        if not match:
            match = re.search(r"\b(\d{1,2})\s*(months?|years?)\b", sentence, re.IGNORECASE)
        if not match:
            continue
        amount = int(match.group(1))
        unit = match.group(2).lower()
        months = amount * 12 if unit.startswith("year") else amount
        return RuleMatch(value=months, quote=sentence, confidence=0.74)
    return None


def _parse_monthly_rent(text: str) -> RuleMatch | None:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if "rent" not in lowered:
            continue
        match = re.search(r"monthly rent[^.]{0,50}?" + MONEY, sentence, re.IGNORECASE)
        if not match:
            match = re.search(r"rent[^.]{0,30}?(?:of|is)\s*" + MONEY, sentence, re.IGNORECASE)
        if match:
            return RuleMatch(value=_money(match.group(1)), quote=sentence, confidence=0.74)
    return None


def _parse_security_deposit(text: str) -> RuleMatch | None:
    for sentence in _sentences(text):
        if "security deposit" not in sentence.lower():
            continue
        match = re.search(r"security deposit[^.]{0,120}?" + MONEY, sentence, re.IGNORECASE)
        if not match:
            match = re.search(MONEY + r"[^.]{0,100}?security deposit", sentence, re.IGNORECASE)
        if match:
            return RuleMatch(value=_money(match.group(1)), quote=sentence, confidence=0.78)
    return None


def _parse_notice(text: str) -> RuleMatch | None:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if "notice" not in lowered:
            continue
        if "renew" in lowered or "extension" in lowered:
            continue
        patterns = (
            r"(\d{1,3})\s*\(([a-z\- ]+)\)\s*days",
            r"([a-z\- ]+)\s*\((\d{1,3})\)\s*days",
            r"(\d{1,3})\s+days",
        )
        for index, pattern in enumerate(patterns):
            match = re.search(pattern, lowered)
            if not match:
                continue
            raw = match.group(2) if index == 1 else match.group(1)
            return RuleMatch(value=int(raw), quote=sentence, confidence=0.74)
    return None


def _parse_subletting(text: str) -> RuleMatch | None:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if "sublet" not in lowered and "sublease" not in lowered:
            continue
        if "prohibit" in lowered or re.search(
            r"(shall|may|will)\s+not\s+(sublet|sublease)", lowered
        ):
            return RuleMatch(value="prohibited", quote=sentence, confidence=0.7)
        if "may sublet" in lowered and re.search(r"without[^.]{0,60}consent", lowered):
            return RuleMatch(value="allowed", quote=sentence, confidence=0.66)
        if "consent" in lowered:
            return RuleMatch(value="allowed_with_consent", quote=sentence, confidence=0.68)
        if "may sublet" in lowered:
            return RuleMatch(value="allowed", quote=sentence, confidence=0.62)
    return None


def _parse_renewal(text: str) -> RuleMatch | None:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if "no renewal option" in lowered:
            return RuleMatch(value="No renewal option.", quote=sentence, confidence=0.7)
        if "renew" not in lowered and "extend" not in lowered:
            continue
        if len(sentence.split()) < 5:
            continue
        if "monthly rent" in lowered and "renewal term" in lowered:
            continue
        if "no option" in lowered or re.search(r"shall have no (option|right)", lowered):
            return RuleMatch(value="No renewal option.", quote=sentence, confidence=0.7)
        return RuleMatch(value=sentence, quote=sentence, confidence=0.64)
    return None


def _parse_late_fee(text: str) -> RuleMatch | None:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if "late fee" not in lowered and "late charge" not in lowered:
            continue
        match = re.search(MONEY, sentence, re.IGNORECASE)
        if match:
            return RuleMatch(value=_money(match.group(1)), quote=sentence, confidence=0.76)
    return None


PARSERS: dict[str, Callable[[str], RuleMatch | None]] = {
    "term_months": _parse_term,
    "monthly_rent": _parse_monthly_rent,
    "security_deposit": _parse_security_deposit,
    "notice_days": _parse_notice,
    "subletting": _parse_subletting,
    "renewal_option": _parse_renewal,
    "late_fee": _parse_late_fee,
}


class RuleExtractor:
    name = "rules"

    def extract(
        self,
        spec: FieldSpec,
        doc_title: str,
        hits: list[Hit],
        feedback: str | None = None,
    ) -> Candidate:
        parser = PARSERS.get(spec.name)
        if parser is None:
            return Candidate(abstained=True, reason="No rule parser for this field.")
        for hit in hits:
            match = parser(hit.text)
            if match is None and hit.heading:
                match = parser(f"{hit.heading} {hit.text}")
                if match is not None and len(hit.heading.split()) <= 6:
                    quote = match.quote
                    if quote.lower().startswith(hit.heading.lower()):
                        trimmed = quote[len(hit.heading) :].lstrip(" .:-")
                        if len(trimmed) >= 20:
                            match = replace(match, quote=trimmed)
            if match:
                return Candidate(
                    value=match.value,
                    quote=match.quote,
                    confidence=match.confidence,
                    page_hint=hit.page_start,
                    meta={"chunk_id": hit.chunk_id, "heading": hit.heading},
                )
        return Candidate(
            abstained=True,
            reason="No matching clause found in the retrieved passages.",
        )
