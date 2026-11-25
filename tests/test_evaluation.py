from __future__ import annotations

from paperproof.evaluation import run_evals


def test_golden_set_passes() -> None:
    result = run_evals()
    assert result.passed is True
    assert result.correct == result.cases
    assert result.citation_rate == 1.0
    assert result.exact == result.cited
    assert result.false_confidence == 0
