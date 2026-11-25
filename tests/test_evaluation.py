from __future__ import annotations

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
