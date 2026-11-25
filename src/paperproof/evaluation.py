"""Golden-set evaluation for extraction and citation quality."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from paperproof.config import Settings
from paperproof.db import session
from paperproof.extract.service import ExtractionResult, extract_document
from paperproof.extract.verify import load_pages, verify_quote
from paperproof.ingest.pipeline import ingest_file
from paperproof.samples import generate_samples

console = Console()


def _cases_path() -> Path:
    candidates = [
        Path.cwd() / "evals" / "cases.jsonl",
        Path(__file__).resolve().parents[2] / "evals" / "cases.jsonl",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find evals/cases.jsonl. Run the eval from the repository root."
    )


@dataclass(frozen=True)
class EvalResult:
    passed: bool
    cases: int
    correct: int
    cited: int
    exact: int
    false_confidence: int
    citation_rate: float
    accuracy: float


def _load_cases() -> list[dict[str, Any]]:
    with _cases_path().open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _value_matches(result: ExtractionResult, case: dict[str, Any]) -> bool:
    if result.status in {"abstained", "failed"}:
        return False
    if "contains" in case:
        return str(case["contains"]).lower() in str(result.value or "").lower()
    expected = case.get("value")
    if isinstance(expected, (int, float)):
        try:
            return abs(float(result.value) - float(expected)) < 0.01
        except (TypeError, ValueError):
            return False
    return str(result.value) == str(expected)


def run_evals(use_llm: bool = False, keep: bool = False, verbose: bool = False) -> EvalResult:
    cases = _load_cases()
    temp_dir = Path(tempfile.mkdtemp(prefix="paperproof-eval-"))
    settings = Settings(
        data_dir=temp_dir,
        extractor="llm" if use_llm else "rules",
    )
    settings.ensure_dirs()

    if use_llm and not settings.llm_configured():
        console.print("[red]LLM eval requested but PAPERPROOF_LLM_BASE_URL is not set.[/red]")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return EvalResult(False, len(cases), 0, 0, 0, 0, 0.0, 0.0)

    samples = generate_samples(settings, force=True)
    with session(settings) as conn:
        ingest = {path.name: ingest_file(conn, settings, path) for path in samples}
        results: dict[tuple[str, str], ExtractionResult] = {}
        pages = {}
        for name, ingested in ingest.items():
            pages[name] = load_pages(conn, ingested.doc_id)
            for result in extract_document(conn, settings, ingested.doc_id):
                results[(name, result.field)] = result

        table = Table(title="Golden set", show_lines=False)
        table.add_column("Document", max_width=34)
        table.add_column("Field")
        table.add_column("Expected", max_width=26)
        table.add_column("Extracted", max_width=30)
        table.add_column("Status")
        table.add_column("Cited")
        table.add_column("Result")

        correct = 0
        cited = 0
        exact = 0
        expected_answers = sum(1 for case in cases if not case.get("abstain"))
        false_confidence = 0
        failures: list[str] = []

        for case in cases:
            name = str(case["doc"])
            field = str(case["field"])
            result = results.get((name, field))
            expected_abstain = bool(case.get("abstain"))
            expected = "abstain" if expected_abstain else case.get("contains", case.get("value"))
            citation_ok = False

            if result is None:
                correct_flag = False
                status = "missing"
                value_text = "—"
            else:
                status = result.status
                value_text = str(result.value) if result.value is not None else result.reason or "—"
                if expected_abstain:
                    correct_flag = result.status == "abstained"
                else:
                    correct_flag = _value_matches(result, case)
                    if result.quote and result.pdf_page:
                        verification = verify_quote(
                            pages.get(name, []), result.quote, result.pdf_page
                        )
                        citation_ok = (
                            verification is not None and verification.pdf_page == result.pdf_page
                        )
                        if citation_ok and verification is not None:
                            cited += 1
                            if verification.method == "exact":
                                exact += 1
                    if not correct_flag and result.confidence >= 0.7:
                        false_confidence += 1

            if correct_flag:
                correct += 1
            else:
                failures.append(f"{name} / {field}")
            table.add_row(
                name,
                field,
                str(expected)[:40],
                value_text[:60],
                status,
                "—" if expected_abstain else ("yes" if citation_ok else "no"),
                "[green]pass[/green]" if correct_flag else "[red]fail[/red]",
            )

        citation_rate = (cited / expected_answers) if expected_answers else 0.0
        accuracy = correct / len(cases) if cases else 0.0
        passed = correct == len(cases) and (expected_answers == 0 or citation_rate == 1.0)

    if verbose:
        console.print(table)
    summary = Table(title="Summary", show_header=False)
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Cases", str(len(cases)))
    summary.add_row("Correct", f"{correct} / {len(cases)}")
    summary.add_row("Answer accuracy", f"{accuracy * 100:.1f}%")
    summary.add_row("Citations independently verified", f"{cited} / {expected_answers}")
    summary.add_row("Exact (not fuzzy) citations", f"{exact} / {expected_answers}")
    summary.add_row("False confidence", str(false_confidence))
    summary.add_row("Extractor", "llm" if use_llm else "rules")
    console.print(summary)
    if failures:
        console.print("[red]Failures:[/red] " + ", ".join(failures))
    if keep:
        console.print(f"Kept eval database at [bold]{settings.db_path}[/bold]")
    else:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return EvalResult(
        passed=passed,
        cases=len(cases),
        correct=correct,
        cited=cited,
        exact=exact,
        false_confidence=false_confidence,
        citation_rate=citation_rate,
        accuracy=accuracy,
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_evals().passed else 1)
