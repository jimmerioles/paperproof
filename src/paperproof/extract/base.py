"""Shared extraction types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from paperproof.extract.templates import FieldSpec
from paperproof.search.retrieve import Hit


@dataclass
class Candidate:
    value: Any = None
    quote: str | None = None
    confidence: float = 0.0
    abstained: bool = False
    reason: str | None = None
    page_hint: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Extractor(Protocol):
    name: str

    def extract(
        self,
        spec: FieldSpec,
        doc_title: str,
        hits: list[Hit],
        feedback: str | None = None,
    ) -> Candidate: ...
