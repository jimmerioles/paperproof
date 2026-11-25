"""Golden-set and real-document evaluation."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError, model_validator
from rich.console import Console
from rich.table import Table

from paperproof.config import Settings
from paperproof.db import session
from paperproof.extract.service import ExtractionResult, extract_document
from paperproof.extract.verify import load_pages, verify_quote
from paperproof.ingest.pipeline import ingest_file, sha256_file
from paperproof.samples import generate_samples

console = Console()


class EvalCase(BaseModel):
    doc: str
    field: str
    value: Any = None
    contains: str | None = None
    abstain: bool = False
    support: bool | None = None
    page: int | None = None
    quote_contains: str | None = None

    @model_validator(mode="after")
    def _needs_expectation(self) -> EvalCase:
        if not self.abstain and self.value is None and self.contains is None:
            raise ValueError("case needs value, contains, or abstain")
        return self


@dataclass
class FieldMetrics:
    total: int = 0
    correct: int = 0
    expected_answers: int = 0
    answered: int = 0
    cited: int = 0
    support_labeled: int = 0
    support_ok: int = 0
    abstain_cases: int = 0
    abstain_ok: int = 0


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
    support_rate: float | None
    support_labeled: int
    abstention_accuracy: float | None
    report_path: Path | None
    field_metrics: dict[str, FieldMetrics] = field(default_factory=dict)
    precision: float | None = None
    recall: float | None = None


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


def _load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        try:
            cases.append(EvalCase.model_validate(payload))
        except ValidationError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not cases:
        raise ValueError(f"{path} contains no cases.")
    return cases


def _value_matches(result: ExtractionResult, case: EvalCase) -> bool:
    if result.status in {"abstained", "failed"}:
        return False
    if case.contains is not None:
        return case.contains.lower() in str(result.value or "").lower()
    expected = case.value
    if isinstance(expected, (int, float)):
        try:
            return abs(float(result.value) - float(expected)) < 0.01
        except (TypeError, ValueError):
            return False
    return str(result.value) == str(expected)


def _expected_label(case: EvalCase) -> str:
    if case.abstain:
        return "abstain"
    if case.contains is not None:
        return case.contains
    return str(case.value)


def _write_report(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_evals(
    use_llm: bool = False,
    keep: bool = False,
    verbose: bool = False,
    cases_path: Path | None = None,
    docs_dir: Path | None = None,
    report_path: Path | None = None,
) -> EvalResult:
    cases = _load_cases(Path(cases_path) if cases_path else _cases_path())
    temp_dir = Path(tempfile.mkdtemp(prefix="paperproof-eval-"))
    settings = Settings(
        data_dir=temp_dir,
        extractor="llm" if use_llm else "rules",
    )
    settings.ensure_dirs()

    if use_llm and not settings.llm_configured():
        console.print("[red]LLM eval requested but PAPERPROOF_LLM_BASE_URL is not set.[/red]")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return EvalResult(
            passed=False,
            cases=len(cases),
            correct=0,
            cited=0,
            exact=0,
            false_confidence=0,
            citation_rate=0.0,
            accuracy=0.0,
            support_rate=None,
            support_labeled=0,
            abstention_accuracy=None,
            report_path=None,
        )

    if docs_dir is not None:
        docs = sorted(Path(docs_dir).rglob("*.pdf"))
        if not docs:
            raise ValueError(f"No PDFs found under {docs_dir}.")
    else:
        docs = generate_samples(settings, force=True)

    with session(settings) as conn:
        doc_ids: dict[str, str] = {}
        doc_names: dict[str, str] = {}
        for path in docs:
            ingested = ingest_file(conn, settings, path)
            doc_ids[path.name] = ingested.doc_id
            doc_ids[sha256_file(path)] = ingested.doc_id
            doc_names[ingested.doc_id] = path.name

        results: dict[tuple[str, str], ExtractionResult] = {}
        pages: dict[str, list[Any]] = {}
        for doc_id in doc_names:
            pages[doc_id] = load_pages(conn, doc_id)
            for result in extract_document(conn, settings, doc_id):
                results[(doc_id, result.field)] = result

        table = Table(title="Golden set", show_lines=False)
        table.add_column("Document", max_width=34)
        table.add_column("Field")
        table.add_column("Expected", max_width=26)
        table.add_column("Extracted", max_width=30)
        table.add_column("Status")
        table.add_column("Cited")
        table.add_column("Support")
        table.add_column("Result")

        correct = 0
        cited = 0
        exact = 0
        expected_answers = sum(1 for case in cases if not case.abstain)
        abstain_cases = sum(1 for case in cases if case.abstain)
        abstain_ok = 0
        support_labeled = 0
        support_ok_count = 0
        false_confidence = 0
        failures: list[str] = []
        report_rows: list[dict[str, Any]] = []
        field_metrics: dict[str, FieldMetrics] = {}

        for case in cases:
            doc_id = doc_ids.get(case.doc)
            result = results.get((doc_id, case.field)) if doc_id else None
            metrics = field_metrics.setdefault(case.field, FieldMetrics())
            metrics.total += 1
            if not case.abstain:
                metrics.expected_answers += 1
            citation_ok = False
            support_ok: bool | None = None
            page_ok: bool | None = None
            expected = _expected_label(case)

            if result is None:
                correct_flag = False
                status = "missing"
                value_text = "—"
            else:
                status = result.status
                value_text = str(result.value) if result.value is not None else result.reason or "—"
                if case.abstain:
                    correct_flag = result.status == "abstained"
                    metrics.abstain_cases += 1
                    if correct_flag:
                        metrics.abstain_ok += 1
                        abstain_ok += 1
                else:
                    correct_flag = _value_matches(result, case)
                    if result.status not in {"abstained", "failed"} and result.value is not None:
                        metrics.answered += 1
                    if result.quote and result.pdf_page:
                        verification = verify_quote(
                            pages.get(doc_id or "", []),
                            result.quote,
                            result.pdf_page,
                        )
                        citation_ok = (
                            verification is not None and verification.pdf_page == result.pdf_page
                        )
                        if case.page is not None:
                            page_ok = result.pdf_page == case.page
                            citation_ok = citation_ok and page_ok
                        if case.quote_contains is not None:
                            citation_ok = citation_ok and (
                                case.quote_contains.lower() in (result.quote or "").lower()
                            )
                        if citation_ok:
                            cited += 1
                            metrics.cited += 1
                            if verification is not None and verification.method == "exact":
                                exact += 1
                    if case.support is not None:
                        support_labeled += 1
                        metrics.support_labeled += 1
                        support_ok = citation_ok == case.support
                        if support_ok:
                            support_ok_count += 1
                            metrics.support_ok += 1
                    if not correct_flag and result.confidence >= 0.7:
                        false_confidence += 1

            if correct_flag:
                correct += 1
                metrics.correct += 1
            else:
                failures.append(f"{case.doc} / {case.field}")
            table.add_row(
                case.doc,
                case.field,
                str(expected)[:40],
                value_text[:60],
                status,
                "—" if case.abstain else ("yes" if citation_ok else "no"),
                "—" if support_ok is None else ("yes" if support_ok else "no"),
                "[green]pass[/green]" if correct_flag else "[red]fail[/red]",
            )
            report_rows.append(
                {
                    "doc": case.doc,
                    "field": case.field,
                    "expected": expected,
                    "extracted": value_text,
                    "status": status,
                    "citation_verified": citation_ok,
                    "support_expected": "" if case.support is None else str(case.support).lower(),
                    "support_ok": "" if support_ok is None else str(support_ok).lower(),
                    "page_expected": "" if case.page is None else case.page,
                    "page_actual": ""
                    if result is None or result.pdf_page is None
                    else result.pdf_page,
                    "correct": correct_flag,
                    "false_confidence": bool(
                        result is not None and not correct_flag and result.confidence >= 0.7
                    ),
                }
            )

        citation_rate = (cited / expected_answers) if expected_answers else 0.0
        accuracy = correct / len(cases) if cases else 0.0
        support_rate = (support_ok_count / support_labeled) if support_labeled else None
        abstention_accuracy = (abstain_ok / abstain_cases) if abstain_cases else None
        answer_correct = sum(
            metrics.correct - metrics.abstain_ok for metrics in field_metrics.values()
        )
        answered_total = sum(metrics.answered for metrics in field_metrics.values())
        precision = (answer_correct / answered_total) if answered_total else None
        recall = (answer_correct / expected_answers) if expected_answers else None
        passed = (
            correct == len(cases)
            and (expected_answers == 0 or citation_rate == 1.0)
            and (support_rate is None or support_rate >= 0.98)
        )

    if verbose:
        console.print(table)

    summary = Table(title="Summary", show_header=False)
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Cases", str(len(cases)))
    summary.add_row("Correct", f"{correct} / {len(cases)}")
    summary.add_row("Answer accuracy", f"{accuracy * 100:.1f}%")
    summary.add_row(
        "Answer precision",
        f"{precision * 100:.1f}%" if precision is not None else "—",
    )
    summary.add_row(
        "Answer recall",
        f"{recall * 100:.1f}%" if recall is not None else "—",
    )
    summary.add_row("Citations independently verified", f"{cited} / {expected_answers}")
    summary.add_row("Exact (not fuzzy) citations", f"{exact} / {expected_answers}")
    if support_rate is None:
        summary.add_row("Citation support (labeled)", "not labeled")
    else:
        summary.add_row(
            "Citation support (labeled)",
            f"{support_ok_count} / {support_labeled} ({support_rate * 100:.1f}%)",
        )
    if abstention_accuracy is None:
        summary.add_row("Abstention accuracy", "no abstain cases")
    else:
        summary.add_row(
            "Abstention accuracy",
            f"{abstain_ok} / {abstain_cases} ({abstention_accuracy * 100:.1f}%)",
        )
    summary.add_row("False confidence", str(false_confidence))
    summary.add_row("Extractor", "llm" if use_llm else "rules")
    console.print(summary)

    per_field = Table(title="Per field", show_header=True)
    per_field.add_column("Field")
    per_field.add_column("Cases", justify="right")
    per_field.add_column("Correct", justify="right")
    per_field.add_column("Precision", justify="right")
    per_field.add_column("Recall", justify="right")
    per_field.add_column("Citations", justify="right")
    per_field.add_column("Support", justify="right")
    for field_name, metrics in sorted(field_metrics.items()):
        support_text = (
            f"{metrics.support_ok}/{metrics.support_labeled}" if metrics.support_labeled else "—"
        )
        answer_correct = metrics.correct - metrics.abstain_ok
        precision_text = f"{answer_correct}/{metrics.answered}" if metrics.answered else "—"
        recall_text = (
            f"{answer_correct}/{metrics.expected_answers}" if metrics.expected_answers else "—"
        )
        per_field.add_row(
            field_name,
            str(metrics.total),
            f"{metrics.correct}/{metrics.total}",
            precision_text,
            recall_text,
            f"{metrics.cited}/{metrics.answered}",
            support_text,
        )
    console.print(per_field)

    if failures:
        console.print("[red]Failures:[/red] " + ", ".join(failures))

    written_report: Path | None = None
    if report_path is not None and report_rows:
        written_report = _write_report(Path(report_path), report_rows)
        console.print(f"Report written to [bold]{written_report}[/bold]")

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
        support_rate=support_rate,
        support_labeled=support_labeled,
        abstention_accuracy=abstention_accuracy,
        report_path=written_report,
        field_metrics=field_metrics,
        precision=precision,
        recall=recall,
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_evals().passed else 1)
