"""Thin wrapper so `python -m evals.run` still works from the repository root."""

from __future__ import annotations

from paperproof.evaluation import run_evals

if __name__ == "__main__":
    raise SystemExit(0 if run_evals().passed else 1)
