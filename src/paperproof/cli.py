"""Command line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from paperproof.api.presenters import format_value
from paperproof.auth import count_users, set_admin_password
from paperproof.backup import create_backup, restore_backup, run_restore_drill
from paperproof.config import get_settings
from paperproof.db import audit, init_db, session
from paperproof.extract.service import extract_document
from paperproof.ingest.pipeline import ingest_file
from paperproof.samples import generate_samples
from paperproof.search.retrieve import make_snippet, query_terms, search
from paperproof.synthetic import generate_synthetic_corpus

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Paperproof: document intelligence where every answer is page-checked.",
)
auth_app = typer.Typer(no_args_is_help=True, help="Manage the local admin account.")
app.add_typer(auth_app, name="auth")
console = Console()


@auth_app.command("set-password")
def auth_set_password(
    username: str = typer.Option("admin", "--username", "-u"),
    password_stdin: bool = typer.Option(
        False, "--password-stdin", help="Read the password from standard input."
    ),
) -> None:
    """Create the admin account or change its password."""
    settings = get_settings()
    settings.ensure_dirs()
    if password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = typer.prompt(
            "New password",
            hide_input=True,
            confirmation_prompt=True,
        )
    try:
        with session(settings) as conn:
            action = set_admin_password(conn, username, password)
            audit(
                conn,
                actor="cli",
                action=f"auth.password_{action}",
                detail={"username": username},
            )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"Admin [bold]{username}[/bold] {action}. Sign in at http://{settings.host}:{settings.port}/login"
    )


@auth_app.command("status")
def auth_status() -> None:
    """Show whether an admin account exists."""
    settings = get_settings()
    with session(settings) as conn:
        rows = conn.execute("SELECT username, updated_at FROM users ORDER BY username").fetchall()
    if not rows:
        console.print("No admin account. Run [bold]paperproof auth set-password[/bold].")
        return
    table = Table(title="Admin accounts")
    table.add_column("Username")
    table.add_column("Password updated")
    for row in rows:
        table.add_row(str(row["username"]), str(row["updated_at"]))
    console.print(table)


@app.command()
def init() -> None:
    """Create the data directory and database."""
    settings = get_settings()
    settings.ensure_dirs()
    with session(settings) as conn:
        init_db(conn)
    console.print(f"Ready. Database: [bold]{settings.db_path}[/bold]")


@app.command()
def samples(
    force: bool = typer.Option(False, "--force", help="Regenerate the PDF corpus."),
    extract: bool = typer.Option(
        True, "--extract/--no-extract", help="Run extraction after ingest."
    ),
) -> None:
    """Generate and ingest the five-lease sample corpus."""
    settings = get_settings()
    settings.ensure_dirs()
    paths = generate_samples(settings, force=force)
    with session(settings) as conn:
        results = [ingest_file(conn, settings, path) for path in paths]
        if extract:
            for result in results:
                if not result.needs_ocr:
                    extract_document(conn, settings, result.doc_id)
    table = Table(title="Sample corpus", show_lines=False)
    table.add_column("Document")
    table.add_column("Pages", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("Status")
    table.add_column("ID", style="dim")
    for result in results:
        table.add_row(
            result.filename,
            str(result.page_count),
            str(result.chunks),
            "needs OCR"
            if result.needs_ocr
            else ("OCR + indexed" if result.ocr_pages else "indexed"),
            result.doc_id,
        )
    console.print(table)
    console.print("Open the review desk with [bold]paperproof serve[/bold]")


@app.command()
def corpus(
    count: int = typer.Option(100, "--count", "-n", min=1, max=500),
    out: Path = typer.Option(Path("data/synthetic"), "--out", "-o"),
    seed: int = typer.Option(7, "--seed"),
    scan_rate: float = typer.Option(0.1, "--scan-rate", min=0.0, max=1.0),
    force: bool = typer.Option(False, "--force", help="Replace a non-empty corpus directory."),
) -> None:
    """Generate a larger synthetic corpus with known labels."""
    settings = get_settings()
    settings.ensure_dirs()
    try:
        result = generate_synthetic_corpus(
            settings,
            out,
            count=count,
            seed=seed,
            scan_rate=scan_rate,
            force=force,
        )
    except (OSError, ValueError) as exc:
        console.print(f"[red]Corpus generation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"Synthetic corpus ready at [bold]{result.path}[/bold]: "
        f"{result.documents} documents, {result.cases} cases, "
        f"{result.scanned} scans, {result.amendments} amendments, "
        f"{result.silent_cases} abstentions."
    )
    console.print(
        "Evaluate it with:\n"
        f"[bold]paperproof eval --cases {result.cases_path} --docs {result.path} "
        f"--report {result.path / 'report.csv'}[/bold]"
    )


@app.command()
def ingest(paths: list[Path] = typer.Argument(..., help="PDF files or directories.")) -> None:
    """Ingest PDFs into the library."""
    settings = get_settings()
    settings.ensure_dirs()
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.pdf")))
        elif path.is_file():
            files.append(path)
        else:
            console.print(f"[red]Not found:[/red] {path}")
    if not files:
        raise typer.Exit(code=1)

    table = Table(title="Ingested")
    table.add_column("Document")
    table.add_column("Pages", justify="right")
    table.add_column("Chunks", justify="right")
    table.add_column("Status")
    table.add_column("Note")
    with session(settings) as conn:
        for path in files:
            try:
                result = ingest_file(conn, settings, path)
            except Exception as exc:
                console.print(f"[red]{path.name}:[/red] {exc}")
                continue
            table.add_row(
                result.filename,
                str(result.page_count),
                str(result.chunks),
                result.status,
                "duplicate"
                if result.duplicate
                else (f"OCR {result.ocr_pages}p" if result.ocr_pages else ""),
            )
    console.print(table)


@app.command()
def extract(
    doc_id: str = typer.Argument(..., help="Document ID."),
    template: str = typer.Option("lease", "--template", "-t"),
) -> None:
    """Run field extraction and citation verification for one document."""
    settings = get_settings()
    with session(settings) as conn:
        results = extract_document(conn, settings, doc_id, template)
    table = Table(title=f"Extraction: {doc_id}", show_lines=True)
    table.add_column("Field")
    table.add_column("Value", max_width=42)
    table.add_column("Status")
    table.add_column("Page", justify="right")
    table.add_column("Quote", max_width=60)
    for result in results:
        status_style = {
            "pending": "yellow",
            "approved": "green",
            "rejected": "red",
            "abstained": "dim",
            "failed": "red",
        }.get(result.status, "")
        table.add_row(
            result.label,
            format_value(result.field, result.value),
            f"[{status_style}]{result.status}[/{status_style}]" if status_style else result.status,
            result.printed_label or (str(result.pdf_page) if result.pdf_page else "—"),
            (result.quote or result.reason or "")[:300],
        )
    console.print(table)


@app.command("search")
def search_command(
    query: str = typer.Argument(..., help="Search phrase."),
    doc: str | None = typer.Option(None, "--doc", help="Limit to one document ID."),
    limit: int = typer.Option(8, "--limit", "-n"),
) -> None:
    """Search passages with hybrid keyword and embedding retrieval."""
    settings = get_settings()
    with session(settings) as conn:
        hits = search(conn, query, doc_id=doc, limit=limit)
    if not hits:
        console.print("No passages found.")
        return
    table = Table(title=f"Search: {query}")
    table.add_column("Score", justify="right")
    table.add_column("Document")
    table.add_column("Section")
    table.add_column("Page", justify="right")
    table.add_column("Passage", max_width=70)
    for hit in hits:
        table.add_row(
            f"{hit.score:.3f}",
            hit.filename,
            hit.heading or "—",
            str(hit.page_start),
            make_snippet(hit.text, query_terms(query), width=180),
        )
    console.print(table)


@app.command()
def stats() -> None:
    """Show library and review counts."""
    settings = get_settings()
    with session(settings) as conn:
        counts = {
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "pages": conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0],
            "passages": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "extractions": conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0],
            "ready": conn.execute(
                "SELECT COUNT(*) FROM extractions WHERE status = 'pending'"
            ).fetchone()[0],
            "approved": conn.execute(
                "SELECT COUNT(*) FROM extractions WHERE status = 'approved'"
            ).fetchone()[0],
            "abstained": conn.execute(
                "SELECT COUNT(*) FROM extractions WHERE status = 'abstained'"
            ).fetchone()[0],
        }
    console.print(
        Panel(
            " / ".join(f"[bold]{value}[/bold] {key}" for key, value in counts.items()),
            title="Paperproof",
        )
    )


@app.command()
def backup(
    out: Path = typer.Option(..., "--out", "-o", help="Empty directory for the backup."),
    force: bool = typer.Option(False, "--force", help="Replace a non-empty backup directory."),
) -> None:
    """Back up the database, uploads, and rendered pages."""
    settings = get_settings()
    try:
        info = create_backup(settings, out, force=force)
    except (OSError, ValueError, RuntimeError) as exc:
        console.print(f"[red]Backup failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"Backup written to [bold]{info.path}[/bold] "
        f"({info.counts['documents']} documents, {info.counts['extractions']} extractions)."
    )


@app.command()
def restore(
    from_dir: Path = typer.Option(..., "--from", help="Backup directory to restore."),
    data_dir: Path = typer.Option(..., "--data-dir", help="Empty target data directory."),
) -> None:
    """Restore a backup into an empty data directory."""
    try:
        info = restore_backup(from_dir, data_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        console.print(f"[red]Restore failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"Restored [bold]{info.path}[/bold] "
        f"({info.counts.get('documents', 0)} documents). "
        f"Start the app with PAPERPROOF_DATA_DIR set to that path."
    )


@app.command("restore-drill")
def restore_drill(
    keep: bool = typer.Option(False, "--keep", help="Keep the drill directories."),
) -> None:
    """Create, back up, restore, and compare a throwaway library."""
    result = run_restore_drill(keep=keep)
    style = "green" if result.passed else "red"
    console.print(
        f"[{style}]Restore drill {'passed' if result.passed else 'failed'}.[/{style}] "
        f"{result.documents} documents, {result.pages} pages, "
        f"{result.extractions} extractions."
    )
    if keep:
        console.print(f"Backup: {result.backup_path}")
        console.print(f"Restored: {result.restored_path}")
    if not result.passed:
        raise typer.Exit(code=1)


@app.command()
def demo(force: bool = typer.Option(False, "--force")) -> None:
    """Build the sample corpus, OCR and extract it, and print IDs."""
    settings = get_settings()
    settings.ensure_dirs()
    paths = generate_samples(settings, force=force)
    with session(settings) as conn:
        results = [ingest_file(conn, settings, path) for path in paths]
        for result in results:
            if not result.needs_ocr:
                extract_document(conn, settings, result.doc_id)
        has_admin = count_users(conn) > 0
    table = Table(title="Demo ready")
    table.add_column("Document")
    table.add_column("Status")
    table.add_column("Open")
    for result in results:
        table.add_row(
            result.filename,
            "needs OCR"
            if result.needs_ocr
            else ("OCR + extracted" if result.ocr_pages else "indexed + extracted"),
            f"http://127.0.0.1:{settings.port}/documents/{result.doc_id}",
        )
    console.print(table)
    if not settings.auth_disabled and not has_admin:
        console.print(
            "No admin account yet. Run [bold]paperproof auth set-password[/bold] before signing in."
        )
    console.print("Run [bold]paperproof serve[/bold], then open the URLs above.")


@app.command("eval")
def eval_command(
    llm: bool = typer.Option(False, "--llm", help="Use the configured LLM extractor."),
    keep: bool = typer.Option(False, "--keep", help="Keep the temporary eval database."),
    verbose: bool = typer.Option(False, "--verbose", help="Print every case."),
    cases: Path | None = typer.Option(
        None, "--cases", help="JSONL case file. Defaults to evals/cases.jsonl."
    ),
    docs: Path | None = typer.Option(
        None, "--docs", help="Directory of PDFs to evaluate. Defaults to the sample corpus."
    ),
    report: Path | None = typer.Option(
        None, "--report", help="Write a per-case CSV report to this path."
    ),
) -> None:
    """Run the golden set or a private real-document set."""
    from paperproof.evaluation import run_evals

    try:
        result = run_evals(
            use_llm=llm,
            keep=keep,
            verbose=verbose,
            cases_path=cases,
            docs_dir=docs,
            report_path=report,
        )
    except (OSError, ValueError) as exc:
        console.print(f"[red]Eval failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    raise typer.Exit(code=0 if result.passed else 1)


@app.command()
def serve(
    host: str = typer.Option(None, "--host", help="Bind address."),
    port: int = typer.Option(None, "--port", help="Port."),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the review desk."""
    import uvicorn

    settings = get_settings()
    if not settings.auth_disabled:
        with session(settings) as conn:
            has_admin = count_users(conn) > 0
        if not has_admin:
            console.print(
                "[yellow]No admin account yet. Run[/yellow] "
                "[bold]paperproof auth set-password[/bold] "
                "[yellow]before signing in.[/yellow]"
            )
    uvicorn.run(
        "paperproof.api.app:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_config=None,
    )


if __name__ == "__main__":
    app()
