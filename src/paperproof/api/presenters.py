"""View models for server-rendered pages."""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from urllib.parse import quote_plus

from paperproof.config import Settings
from paperproof.extract.templates import get_template
from paperproof.search.retrieve import Hit, make_snippet, query_terms, search

MONEY_FIELDS = {"monthly_rent", "security_deposit", "late_fee"}


def _page_map(conn: sqlite3.Connection, doc_id: str) -> dict[int, dict[str, Any]]:
    rows = conn.execute(
        "SELECT pdf_page, width, height, printed_label FROM pages WHERE doc_id = ?",
        (doc_id,),
    ).fetchall()
    return {
        int(row["pdf_page"]): {
            "width": float(row["width"]),
            "height": float(row["height"]),
            "printed_label": row["printed_label"],
        }
        for row in rows
    }


def boxes_percent(
    boxes: list[dict[str, float]], width: float, height: float
) -> list[dict[str, float]]:
    if width <= 0 or height <= 0:
        return []
    output: list[dict[str, float]] = []
    for box in boxes:
        output.append(
            {
                "left": round(max(0.0, box["x"] / width * 100), 3),
                "top": round(max(0.0, box["y"] / height * 100), 3),
                "width": round(min(100.0, box["w"] / width * 100), 3),
                "height": round(min(100.0, box["h"] / height * 100), 3),
            }
        )
    return output


def format_value(field: str, value: Any) -> str:
    if value is None:
        return "—"
    if field in MONEY_FIELDS:
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if field == "term_months":
        try:
            return f"{int(value)} months"
        except (TypeError, ValueError):
            return str(value)
    if field == "notice_days":
        try:
            return f"{int(value)} days"
        except (TypeError, ValueError):
            return str(value)
    if field == "subletting":
        return {
            "prohibited": "Prohibited",
            "allowed_with_consent": "Allowed with consent",
            "allowed": "Allowed without consent",
        }.get(str(value), str(value))
    return str(value)


def _source_url(doc_id: str, page: int | None, quote: str | None) -> str | None:
    if not page:
        return None
    url = f"/documents/{doc_id}/source?page={page}"
    if quote:
        url += f"&quote={quote_plus(quote)}"
    return url


def _record_view(
    row: sqlite3.Row,
    pages: dict[int, dict[str, Any]],
    selected_field: str | None,
    labels: dict[str, str],
) -> dict[str, Any]:
    boxes = json.loads(row["boxes_json"]) if row["boxes_json"] else []
    page = int(row["pdf_page"]) if row["pdf_page"] is not None else None
    meta = pages.get(page or 0, {"width": 612.0, "height": 792.0, "printed_label": None})
    percent = boxes_percent(boxes, float(meta["width"]), float(meta["height"]))
    quote = row["quote"]
    value = json.loads(row["value_json"]) if row["value_json"] else None
    label = row["printed_label"] or (str(page) if page else None)
    display = format_value(str(row["field"]), value)
    return {
        "id": row["id"],
        "field": row["field"],
        "label": labels.get(str(row["field"]), str(row["field"]).replace("_", " ").title()),
        "value": value,
        "value_display": display,
        "long_value": len(display) > 42,
        "quote": quote,
        "page": page,
        "pdf_page": page,
        "printed_label": label,
        "page_note": (
            f"Printed page {row['printed_label']} / PDF page {page}"
            if row["printed_label"] and str(row["printed_label"]) != str(page)
            else f"PDF page {page}"
        )
        if page
        else None,
        "boxes": percent,
        "boxes_json": json.dumps(percent),
        "confidence": float(row["confidence"] or 0),
        "confidence_pct": round(float(row["confidence"] or 0) * 100),
        "status": row["status"],
        "verifier": row["verifier"],
        "extractor": row["extractor"],
        "reason": row["reason"],
        "has_citation": bool(quote and page and percent),
        "source_url": _source_url(str(row["doc_id"]), page, quote),
        "is_selected": row["field"] == selected_field,
        "reviewed_at": row["reviewed_at"],
        "reviewer": row["reviewer"],
    }


def document_view(
    conn: sqlite3.Connection,
    doc_id: str,
    selected_field: str | None = None,
) -> dict[str, Any] | None:
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if document is None:
        return None
    pages = _page_map(conn, doc_id)
    rows = conn.execute(
        "SELECT * FROM extractions WHERE doc_id = ? ORDER BY id",
        (doc_id,),
    ).fetchall()
    labels: dict[str, str] = {}
    order: dict[str, int] = {}
    if rows:
        try:
            template = get_template(str(rows[0]["template"]))
            labels = {field.name: field.label for field in template.fields}
            order = {field.name: index for index, field in enumerate(template.fields)}
        except ValueError:
            labels = {}
    rows = sorted(rows, key=lambda row: order.get(str(row["field"]), 999))

    records: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for row in rows:
        record = _record_view(row, pages, selected_field, labels)
        records.append(record)
    if selected_field:
        selected = next((record for record in records if record["field"] == selected_field), None)
    if selected is None:
        selected = next((record for record in records if record["has_citation"]), None)
    if selected is None and records:
        selected = records[0]
    if selected is not None:
        for record in records:
            record["is_selected"] = record["id"] == selected["id"]

    totals = {
        "total": len(records),
        "verified": sum(1 for record in records if record["quote"]),
        "pending": sum(1 for record in records if record["status"] == "pending"),
        "approved": sum(1 for record in records if record["status"] == "approved"),
        "rejected": sum(1 for record in records if record["status"] == "rejected"),
        "abstained": sum(1 for record in records if record["status"] == "abstained"),
        "failed": sum(1 for record in records if record["status"] == "failed"),
    }
    totals["settled"] = totals["approved"] + totals["rejected"]
    totals["needs_review"] = totals["pending"]

    page_count = int(document["page_count"])
    viewer_page = selected["page"] if selected and selected["page"] else 1
    viewer_page = max(1, min(viewer_page, page_count))
    viewer_meta = pages.get(viewer_page, {"width": 612.0, "height": 792.0, "printed_label": None})
    printed = viewer_meta["printed_label"]
    viewer = {
        "page": viewer_page,
        "page_count": page_count,
        "image_url": f"/documents/{doc_id}/pages/{viewer_page}.png",
        "boxes": selected["boxes"] if selected and selected["page"] == viewer_page else [],
        "quote": selected["quote"] if selected and selected["page"] == viewer_page else None,
        "printed_label": printed,
        "page_note": (
            f"Printed page {printed} / PDF page {viewer_page}"
            if printed and str(printed) != str(viewer_page)
            else f"PDF page {viewer_page}"
        ),
        "field": selected["field"] if selected else None,
        "field_label": selected["field"].replace("_", " ").title() if selected else None,
        "prev_page": max(1, viewer_page - 1),
        "next_page": min(page_count, viewer_page + 1),
        "page_width": round(float(viewer_meta["width"])),
        "page_height": round(float(viewer_meta["height"])),
    }

    return {
        "doc": {
            "id": document["id"],
            "title": document["title"],
            "display_title": str(document["title"]).partition(" - ")[0] or document["title"],
            "subtitle": str(document["title"]).partition(" - ")[2] or None,
            "filename": document["filename"],
            "page_count": page_count,
            "status": document["status"],
            "needs_ocr": bool(document["needs_ocr"]),
            "created_at": document["created_at"],
        },
        "records": records,
        "selected": selected,
        "viewer": viewer,
        "totals": totals,
        "has_extractions": bool(records),
    }


def dashboard_view(conn: sqlite3.Connection, settings: Settings) -> dict[str, Any]:
    stats = {
        "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "pages": conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
        "passages": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "pending": conn.execute(
            "SELECT COUNT(*) FROM extractions WHERE status = 'pending'"
        ).fetchone()[0],
        "approved": conn.execute(
            "SELECT COUNT(*) FROM extractions WHERE status = 'approved'"
        ).fetchone()[0],
    }
    documents = conn.execute(
        "SELECT d.*, "
        "(SELECT COUNT(*) FROM extractions e "
        "WHERE e.doc_id = d.id AND e.status = 'pending') AS pending, "
        "(SELECT COUNT(*) FROM extractions e "
        "WHERE e.doc_id = d.id AND e.status = 'approved') AS approved, "
        "(SELECT COUNT(*) FROM extractions e WHERE e.doc_id = d.id) AS fields "
        "FROM documents d ORDER BY d.created_at DESC, d.rowid DESC LIMIT 12"
    ).fetchall()
    items = []
    for row in documents:
        item = dict(row)
        display_title, _, subtitle = str(item["title"]).partition(" - ")
        item["display_title"] = display_title or item["title"]
        item["subtitle"] = subtitle or None
        items.append(item)
    return {
        "stats": stats,
        "documents": items,
        "mode": settings.llm_model if settings.use_llm() else "Rule baseline",
        "llm": settings.use_llm(),
        "empty": stats["documents"] == 0,
    }


def _best_sentence(text: str, terms: list[str]) -> str:
    import re

    sentences = re.split(r"(?<=[.!?])\s+", text)
    lowered_terms = [term.lower() for term in terms]
    for sentence in sentences:
        lowered = sentence.lower()
        if any(term in lowered for term in lowered_terms):
            return sentence.strip()
    return text[:350].strip()


def search_view(conn: sqlite3.Connection, query: str, settings: Settings) -> dict[str, Any]:
    terms = query_terms(query)
    hits: list[Hit] = (
        search(
            conn,
            query,
            limit=20,
            candidate_k=settings.candidate_k,
            embedder_name=settings.embedder,
        )
        if query.strip()
        else []
    )
    results = []
    for hit in hits:
        snippet = make_snippet(hit.text, terms)
        quote = _best_sentence(hit.text, terms)
        display_title, _, _ = hit.title.partition(" - ")
        results.append(
            {
                "doc_id": hit.doc_id,
                "title": display_title or hit.title,
                "filename": hit.filename,
                "heading": hit.heading,
                "page": hit.page_start,
                "score": hit.score,
                "snippet": snippet,
                "source_url": _source_url(hit.doc_id, hit.page_start, quote),
            }
        )
    return {"query": query, "terms": terms, "results": results, "count": len(results)}


def audit_view(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100").fetchall()
    events = []
    for row in rows:
        try:
            detail = json.loads(row["detail_json"])
        except json.JSONDecodeError:
            detail = {}
        events.append(
            {
                "at": str(row["at"]).replace("T", " ").replace("+00:00", " UTC"),
                "actor": row["actor"],
                "action": row["action"],
                "entity": row["entity"],
                "detail": detail,
                "detail_text": " / ".join(f"{key}: {value}" for key, value in detail.items()),
            }
        )
    return {"events": events}
