"""Extraction orchestration: retrieve, extract, verify, persist, audit."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from paperproof.config import Settings
from paperproof.db import audit, new_id, one, utcnow
from paperproof.extract.base import Candidate, Extractor
from paperproof.extract.llm import LLMExtractor
from paperproof.extract.rules import RuleExtractor
from paperproof.extract.templates import Template, get_template
from paperproof.extract.verify import Verification, load_pages, verify_quote
from paperproof.search.retrieve import search


@dataclass(frozen=True)
class ExtractionResult:
    id: str
    doc_id: str
    template: str
    field: str
    label: str
    value: Any
    quote: str | None
    pdf_page: int | None
    printed_label: str | None
    boxes: list[dict[str, float]]
    confidence: float
    status: str
    verifier: str | None
    extractor: str
    reason: str | None


def choose_extractor(settings: Settings) -> Extractor:
    if settings.use_llm():
        return LLMExtractor(settings)
    if settings.extractor == "llm":
        raise RuntimeError(
            "PAPERPROOF_EXTRACTOR=llm but PAPERPROOF_LLM_BASE_URL is not configured."
        )
    return RuleExtractor()


def _row_to_result(row: sqlite3.Row, template: Template) -> ExtractionResult:
    labels = {field.name: field.label for field in template.fields}
    return ExtractionResult(
        id=str(row["id"]),
        doc_id=str(row["doc_id"]),
        template=str(row["template"]),
        field=str(row["field"]),
        label=labels.get(str(row["field"]), str(row["field"])),
        value=json.loads(row["value_json"]) if row["value_json"] else None,
        quote=row["quote"],
        pdf_page=int(row["pdf_page"]) if row["pdf_page"] is not None else None,
        printed_label=row["printed_label"],
        boxes=json.loads(row["boxes_json"]) if row["boxes_json"] else [],
        confidence=float(row["confidence"] or 0),
        status=str(row["status"]),
        verifier=row["verifier"],
        extractor=str(row["extractor"]),
        reason=row["reason"],
    )


def _upsert(
    conn: sqlite3.Connection,
    doc_id: str,
    template_id: str,
    field_name: str,
    value: Any,
    quote: str | None,
    verification: Verification | None,
    confidence: float,
    status: str,
    extractor: str,
    reason: str | None,
) -> None:
    conn.execute(
        "INSERT INTO extractions "
        "(id, doc_id, template, field, value_json, quote, pdf_page, printed_label, "
        " boxes_json, confidence, status, verifier, extractor, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(doc_id, template, field) DO UPDATE SET "
        " value_json=excluded.value_json, quote=excluded.quote, pdf_page=excluded.pdf_page, "
        " printed_label=excluded.printed_label, boxes_json=excluded.boxes_json, "
        " confidence=excluded.confidence, status=excluded.status, verifier=excluded.verifier, "
        " extractor=excluded.extractor, reason=excluded.reason, created_at=excluded.created_at, "
        " reviewed_at=NULL, reviewer=NULL, review_note=NULL",
        (
            new_id("ext"),
            doc_id,
            template_id,
            field_name,
            json.dumps(value) if value is not None else None,
            quote,
            verification.pdf_page if verification else None,
            verification.printed_label if verification else None,
            json.dumps([box.as_dict() for box in verification.boxes]) if verification else None,
            confidence,
            status,
            verification.method if verification else None,
            extractor,
            reason,
            utcnow(),
        ),
    )


def extract_document(
    conn: sqlite3.Connection,
    settings: Settings,
    doc_id: str,
    template_id: str = "lease",
) -> list[ExtractionResult]:
    document = one(conn, "SELECT * FROM documents WHERE id = ?", (doc_id,))
    if document is None:
        raise ValueError(f"Document not found: {doc_id}")
    template = get_template(template_id)
    pages = load_pages(conn, doc_id)
    extractor = choose_extractor(settings)
    rules = RuleExtractor()
    needs_ocr = bool(document["needs_ocr"])
    llm_error: str | None = None
    verified_count = 0
    abstained_count = 0
    failed_count = 0

    try:
        for field in template.fields:
            hits = (
                []
                if needs_ocr
                else search(
                    conn,
                    field.search_query(),
                    doc_id=doc_id,
                    limit=settings.top_k,
                    candidate_k=settings.candidate_k,
                    embedder_name=settings.embedder,
                )
            )
            page_hint = hits[0].page_start if hits else None
            extractor_used = extractor.name
            fallback_note: str | None = None

            if needs_ocr:
                candidate = Candidate(
                    abstained=True,
                    reason="Scanned document: OCR is required before extraction.",
                )
            elif not hits:
                candidate = Candidate(
                    abstained=True,
                    reason="No indexed passages matched this field.",
                )
            elif extractor.name == "llm" and llm_error is not None:
                candidate = rules.extract(field, document["title"], hits)
                extractor_used = "rules-fallback"
                fallback_note = llm_error
            else:
                try:
                    candidate = extractor.extract(field, document["title"], hits)
                except Exception as exc:
                    if extractor.name != "llm":
                        raise
                    llm_error = str(exc)[:400]
                    candidate = rules.extract(field, document["title"], hits)
                    extractor_used = "rules-fallback"
                    fallback_note = llm_error

            verification: Verification | None = None
            status = "abstained"
            value: Any = None
            confidence = 0.0
            reason = candidate.reason

            if not candidate.abstained and candidate.value is not None and candidate.quote:
                verification = verify_quote(
                    pages, candidate.quote, candidate.page_hint or page_hint
                )
                if (
                    verification is None
                    and extractor.name == "llm"
                    and llm_error is None
                    and settings.llm_retries > 0
                ):
                    try:
                        retry = extractor.extract(
                            field,
                            document["title"],
                            hits,
                            feedback=(
                                "The previous quote was not found verbatim in the document. "
                                "Copy an exact substring from the passages, preserving "
                                "capitalization and punctuation."
                            ),
                        )
                        if not retry.abstained and retry.quote:
                            retry_verification = verify_quote(
                                pages, retry.quote, retry.page_hint or page_hint
                            )
                            if retry_verification is not None:
                                candidate = retry
                                verification = retry_verification
                    except Exception as exc:
                        reason = f"Quote retry failed: {str(exc)[:200]}"

                if verification is not None:
                    status = "pending"
                    value = candidate.value
                    confidence = candidate.confidence
                    if verification.method == "fuzzy":
                        confidence = round(confidence * 0.85, 3)
                    verified_count += 1
                else:
                    status = "failed"
                    reason = (
                        "Extractor returned a quote that could not be found in the "
                        "document. Nothing is shown as a citation."
                    )
                    failed_count += 1
            else:
                if candidate.value is None and not candidate.abstained:
                    reason = candidate.reason or "Extractor returned no value."
                abstained_count += 1

            if fallback_note:
                reason = (
                    f"LLM unavailable ({fallback_note}). Used the rule baseline. {reason or ''}"
                ).strip()

            _upsert(
                conn,
                doc_id,
                template.id,
                field.name,
                value,
                verification.quote if verification else None,
                verification,
                round(confidence, 3),
                status,
                extractor_used,
                reason,
            )
    finally:
        if isinstance(extractor, LLMExtractor):
            extractor.close()

    audit(
        conn,
        actor="system",
        action="document.extracted",
        entity=doc_id,
        detail={
            "template": template.id,
            "extractor": extractor.name,
            "verified": verified_count,
            "abstained": abstained_count,
            "failed": failed_count,
        },
    )

    rows = conn.execute(
        "SELECT * FROM extractions WHERE doc_id = ? AND template = ?",
        (doc_id, template.id),
    ).fetchall()
    by_field = {str(row["field"]): row for row in rows}
    return [
        _row_to_result(by_field[field.name], template)
        for field in template.fields
        if field.name in by_field
    ]


def review_extraction(
    conn: sqlite3.Connection,
    extraction_id: str,
    decision: str,
    reviewer: str = "local",
    note: str | None = None,
) -> None:
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    row = one(conn, "SELECT * FROM extractions WHERE id = ?", (extraction_id,))
    if row is None:
        raise ValueError(f"Extraction not found: {extraction_id}")
    conn.execute(
        "UPDATE extractions SET status = ?, reviewed_at = ?, reviewer = ?, review_note = ? "
        "WHERE id = ?",
        (decision, utcnow(), reviewer, note, extraction_id),
    )
    audit(
        conn,
        actor=reviewer,
        action=f"extraction.{decision}",
        entity=extraction_id,
        detail={
            "doc_id": row["doc_id"],
            "field": row["field"],
            **({"note": note} if note else {}),
        },
    )
