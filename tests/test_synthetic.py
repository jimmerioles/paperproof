from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperproof.config import Settings
from paperproof.evaluation import run_evals
from paperproof.ingest.ocr import tesseract_available
from paperproof.synthetic import generate_synthetic_corpus

requires_tesseract = pytest.mark.skipif(
    not tesseract_available(), reason="tesseract-ocr is not installed"
)


def test_generate_small_corpus(settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "synthetic"
    result = generate_synthetic_corpus(settings, out, count=6, seed=11, scan_rate=0, force=True)
    assert result.documents == 6
    assert result.cases == 42
    assert len(list(out.glob("*.pdf"))) == 6
    cases = [json.loads(line) for line in result.cases_path.read_text().splitlines()]
    assert len(cases) == 42
    assert any(case.get("abstain") for case in cases)
    assert all("support" in case for case in cases if not case.get("abstain"))
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["format"] == "paperproof-synthetic-corpus"
    assert manifest["documents"] == 6
    assert manifest["cases"] == 42


def test_synthetic_corpus_eval_passes(settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "synthetic"
    result = generate_synthetic_corpus(settings, out, count=5, seed=4, scan_rate=0, force=True)
    report = tmp_path / "report.csv"
    ev = run_evals(
        cases_path=result.cases_path,
        docs_dir=out,
        report_path=report,
    )
    assert ev.passed is True
    assert ev.correct == ev.cases
    assert ev.support_rate == 1.0
    assert ev.precision == 1.0
    assert ev.recall == 1.0
    assert report.exists()


@requires_tesseract
def test_scanned_synthetic_corpus_passes(settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "scanned"
    result = generate_synthetic_corpus(settings, out, count=2, seed=5, scan_rate=1.0, force=True)
    assert result.scanned == 2
    ev = run_evals(cases_path=result.cases_path, docs_dir=out)
    assert ev.passed is True
    assert ev.correct == ev.cases


def test_corpus_refuses_non_empty_directory(settings: Settings, tmp_path: Path) -> None:
    out = tmp_path / "existing"
    out.mkdir()
    (out / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="not empty"):
        generate_synthetic_corpus(settings, out, count=2, scan_rate=0)
    assert (out / "keep.txt").read_text() == "keep"
