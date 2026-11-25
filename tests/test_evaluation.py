from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from paperproof.evaluation import run_evals
from paperproof.ingest.ocr import tesseract_available


@pytest.mark.skipif(not tesseract_available(), reason="tesseract-ocr is not installed")
def test_golden_set_passes() -> None:
    result = run_evals()
    assert result.passed is True
    assert result.correct == result.cases
    assert result.citation_rate == 1.0
    assert result.exact == result.cited
    assert result.false_confidence == 0
    assert result.support_rate is None
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_private_case_set_with_support_labels(tmp_path: Path, sample_paths: list[Path]) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    shutil.copy2(sample_paths[1], docs_dir / sample_paths[1].name)
    cases_path = tmp_path / "cases.jsonl"
    cases = [
        {
            "doc": sample_paths[1].name,
            "field": "term_months",
            "value": 12,
            "support": True,
            "page": 3,
        },
        {
            "doc": sample_paths[1].name,
            "field": "notice_days",
            "value": 60,
            "support": True,
            "page": 4,
        },
    ]
    cases_path.write_text("\n".join(json.dumps(case) for case in cases) + "\n")
    report_path = tmp_path / "report.csv"

    result = run_evals(cases_path=cases_path, docs_dir=docs_dir, report_path=report_path)

    assert result.passed is True
    assert result.correct == 2
    assert result.support_labeled == 2
    assert result.support_rate == 1.0
    assert result.abstention_accuracy is None
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert report_path.exists()
    lines = report_path.read_text().strip().splitlines()
    assert len(lines) == 3
    assert "support_ok" in lines[0]


def test_private_case_set_fails_on_wrong_value(tmp_path: Path, sample_paths: list[Path]) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    shutil.copy2(sample_paths[1], docs_dir / sample_paths[1].name)
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "doc": sample_paths[1].name,
                "field": "term_months",
                "value": 99,
                "support": True,
            }
        )
        + "\n"
    )
    result = run_evals(cases_path=cases_path, docs_dir=docs_dir)
    assert result.passed is False
    assert result.accuracy == 0.0
    assert result.precision == 0.0
    assert result.recall == 0.0


def test_invalid_case_file_is_rejected(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text('{"doc": "x.pdf", "field": "term_months"}\n')
    with pytest.raises(ValueError, match="needs value"):
        run_evals(cases_path=cases_path, docs_dir=tmp_path)
