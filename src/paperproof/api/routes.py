"""HTTP routes for the review desk."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from paperproof.api.deps import csrf_protect, get_conn
from paperproof.api.presenters import (
    audit_view,
    boxes_percent,
    dashboard_view,
    document_view,
    search_view,
)
from paperproof.api.templating import templates
from paperproof.db import one
from paperproof.extract.service import extract_document, review_extraction
from paperproof.extract.templates import get_template
from paperproof.extract.verify import load_pages, verify_quote
from paperproof.ingest.pdf import render_page_png
from paperproof.ingest.pipeline import ingest_file
from paperproof.samples import generate_samples

router = APIRouter()


def _redirect(url: str, notice: str | None = None, error: str | None = None) -> RedirectResponse:
    params = {}
    if notice:
        params["notice"] = notice
    if error:
        params["error"] = error
    if params:
        base, _, fragment = url.partition("#")
        separator = "&" if "?" in base else "?"
        url = f"{base}{separator}{urlencode(params)}"
        if fragment:
            url += f"#{fragment}"
    return RedirectResponse(url, status_code=303)


def _next_pending_field(
    conn: sqlite3.Connection, doc_id: str, template_id: str, fallback: str
) -> str:
    rows = conn.execute(
        "SELECT field FROM extractions WHERE doc_id = ? AND status = 'pending'",
        (doc_id,),
    ).fetchall()
    if not rows:
        return fallback
    try:
        order = {field.name: index for index, field in enumerate(get_template(template_id).fields)}
    except ValueError:
        return str(rows[0]["field"])
    return min((str(row["field"]) for row in rows), key=lambda field: order.get(field, 999))


@router.get("/")
def dashboard(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    context = dashboard_view(conn, settings)
    context.update(
        {
            "active": "documents",
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.post("/documents")
def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    conn: sqlite3.Connection = Depends(get_conn),
    _: None = Depends(csrf_protect),
):
    settings = request.app.state.settings
    max_bytes = settings.max_upload_mb * 1024 * 1024
    temp_dir = settings.data_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    ingested: list[str] = []
    duplicates = 0
    errors: list[str] = []

    for upload in files:
        name = upload.filename or "upload.pdf"
        if not name.lower().endswith(".pdf"):
            errors.append(f"{name}: only PDF files are supported.")
            continue
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".pdf", delete=False) as handle:
                temp_path = Path(handle.name)
                size = 0
                while chunk := upload.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"File is larger than {settings.max_upload_mb} MB.")
                    handle.write(chunk)
            result = ingest_file(conn, settings, temp_path, original_name=name)
            conn.commit()
            if result.duplicate:
                duplicates += 1
            else:
                ingested.append(result.doc_id)
        except Exception as exc:
            conn.rollback()
            errors.append(f"{name}: {exc}")
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    if ingested and not errors:
        message = "Ingested 1 document."
        if len(ingested) > 1:
            message = f"Ingested {len(ingested)} documents."
        if duplicates:
            message += f" Skipped {duplicates} duplicate."
        return _redirect(f"/documents/{ingested[0]}", notice=message)
    if ingested:
        message = f"Ingested {len(ingested)} document."
        if duplicates:
            message += f" Skipped {duplicates} duplicate."
        return _redirect("/", notice=message, error=" ".join(errors))
    if duplicates:
        return _redirect("/", notice=f"Those documents are already in the library ({duplicates}).")
    return _redirect("/", error=" ".join(errors) or "No files received.")


@router.post("/samples")
def load_samples(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    _: None = Depends(csrf_protect),
):
    settings = request.app.state.settings
    try:
        paths = generate_samples(settings)
        results = [ingest_file(conn, settings, path) for path in paths]
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return _redirect("/", error=f"Could not build the sample corpus: {exc}")

    failures = 0
    for result in results:
        if result.needs_ocr:
            continue
        try:
            extract_document(conn, settings, result.doc_id)
            conn.commit()
        except Exception:
            conn.rollback()
            failures += 1

    first = results[0].doc_id
    message = f"Loaded {len(results)} sample leases and extracted the text-based ones."
    if failures:
        message += f" {failures} extraction run(s) failed."
    return _redirect(f"/documents/{first}", notice=message)


@router.get("/documents/{doc_id}")
def document_page(
    request: Request,
    doc_id: str,
    field: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    context = document_view(conn, doc_id, field)
    if context is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    context.update(
        {
            "active": "documents",
            "llm": request.app.state.settings.use_llm(),
            "mode": request.app.state.settings.llm_model,
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
        }
    )
    return templates.TemplateResponse(request=request, name="document.html", context=context)


@router.post("/documents/{doc_id}/extract")
def run_extraction(
    request: Request,
    doc_id: str,
    template_id: str = Form("lease"),
    conn: sqlite3.Connection = Depends(get_conn),
    _: None = Depends(csrf_protect),
):
    settings = request.app.state.settings
    try:
        results = extract_document(conn, settings, doc_id, template_id)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return _redirect(f"/documents/{doc_id}", error=str(exc)[:400])
    verified = sum(1 for result in results if result.quote)
    abstained = sum(1 for result in results if result.status == "abstained")
    failed = sum(1 for result in results if result.status == "failed")
    message = f"Extracted {len(results)} fields. {verified} citations verified."
    if abstained:
        message += f" {abstained} not addressed."
    if failed:
        message += f" {failed} unverified."
    return _redirect(f"/documents/{doc_id}", notice=message)


@router.post("/extractions/{extraction_id}/review")
def review(
    request: Request,
    extraction_id: str,
    decision: str = Form(...),
    note: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
    _: None = Depends(csrf_protect),
):
    row = one(conn, "SELECT * FROM extractions WHERE id = ?", (extraction_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Extraction not found.")
    try:
        review_extraction(conn, extraction_id, decision, note=note or None)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return _redirect(f"/documents/{row['doc_id']}", error=str(exc))

    target_field = _next_pending_field(
        conn, str(row["doc_id"]), str(row["template"]), str(row["field"])
    )
    try:
        label = next(
            field.label
            for field in get_template(str(row["template"])).fields
            if field.name == row["field"]
        )
    except (ValueError, StopIteration):
        label = str(row["field"]).replace("_", " ")
    verb = "approved" if decision == "approved" else "rejected"
    return _redirect(
        f"/documents/{row['doc_id']}?field={target_field}#record-{target_field}",
        notice=f"{label} {verb}.",
    )


@router.get("/documents/{doc_id}/pages/{page}.png")
def page_image(
    request: Request,
    doc_id: str,
    page: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    settings = request.app.state.settings
    document = one(conn, "SELECT stored_path FROM documents WHERE id = ?", (doc_id,))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    page_row = one(
        conn, "SELECT pdf_page FROM pages WHERE doc_id = ? AND pdf_page = ?", (doc_id, page)
    )
    if page_row is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    pdf_path = settings.upload_dir / str(document["stored_path"])
    out_path = settings.render_dir / doc_id / f"page_{page}_{settings.render_scale:g}.png"
    try:
        render_page_png(pdf_path, page, out_path, scale=settings.render_scale)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Could not render page: {exc}") from exc
    return FileResponse(
        out_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/documents/{doc_id}/source")
def source_page(
    request: Request,
    doc_id: str,
    page: int = 1,
    quote: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
):
    document = one(conn, "SELECT * FROM documents WHERE id = ?", (doc_id,))
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    page_count = int(document["page_count"])
    page = max(1, min(page, page_count))
    pages = load_pages(conn, doc_id)
    verification = verify_quote(pages, quote, page) if quote else None
    target_page = verification.pdf_page if verification else page
    page_meta = next((item for item in pages if item.pdf_page == target_page), None)
    if page_meta is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    boxes = (
        boxes_percent(
            [box.as_dict() for box in verification.boxes],
            page_meta.width,
            page_meta.height,
        )
        if verification
        else []
    )
    context = {
        "active": "documents",
        "doc": dict(document),
        "display_title": str(document["title"]).partition(" - ")[0] or document["title"],
        "subtitle": str(document["title"]).partition(" - ")[2] or None,
        "page": target_page,
        "page_count": page_count,
        "image_url": f"/documents/{doc_id}/pages/{target_page}.png",
        "printed_label": page_meta.printed_label,
        "page_note": (
            f"Printed page {page_meta.printed_label} / PDF page {target_page}"
            if page_meta.printed_label and str(page_meta.printed_label) != str(target_page)
            else f"PDF page {target_page}"
        ),
        "boxes": boxes,
        "quote": verification.quote if verification else None,
        "verified": bool(verification),
        "requested_quote": quote if not verification else None,
        "prev_page": max(1, target_page - 1),
        "next_page": min(page_count, target_page + 1),
        "page_width": round(page_meta.width),
        "page_height": round(page_meta.height),
        "page_ocr": page_meta.ocr,
        "page_ocr_confidence": page_meta.ocr_confidence,
        "back_url": f"/documents/{doc_id}",
    }
    return templates.TemplateResponse(request=request, name="source.html", context=context)


@router.get("/search")
def search_page(
    request: Request,
    q: str = "",
    conn: sqlite3.Connection = Depends(get_conn),
):
    settings = request.app.state.settings
    context = search_view(conn, q, settings)
    context.update({"active": "search"})
    return templates.TemplateResponse(request=request, name="search.html", context=context)


@router.get("/audit")
def audit_page(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    context = audit_view(conn)
    context.update({"active": "audit"})
    return templates.TemplateResponse(request=request, name="audit.html", context=context)


@router.get("/healthz")
def healthz(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    settings = request.app.state.settings
    checks = {"database": "ok", "renders": "ok", "disk": "ok"}
    healthy = True
    try:
        conn.execute("SELECT 1").fetchone()
    except sqlite3.Error:
        checks["database"] = "error"
        healthy = False
    try:
        with tempfile.NamedTemporaryFile(dir=settings.render_dir, prefix=".health-"):
            pass
    except OSError:
        checks["renders"] = "error"
        healthy = False
    try:
        free_mb = shutil.disk_usage(settings.data_dir).free / (1024 * 1024)
        if free_mb < settings.health_min_free_mb:
            checks["disk"] = "low"
            healthy = False
    except OSError:
        checks["disk"] = "error"
        healthy = False
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
