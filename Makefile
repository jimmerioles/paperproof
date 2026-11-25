.PHONY: setup demo serve test lint format type check eval samples clean

setup:
	uv sync

demo:
	uv run paperproof demo --force

serve:
	uv run paperproof serve

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

type:
	uv run pyright

check: lint type test eval

eval:
	uv run paperproof eval

samples:
	uv run paperproof samples --force

clean:
	rm -rf data .pytest_cache .ruff_cache .coverage htmlcov
