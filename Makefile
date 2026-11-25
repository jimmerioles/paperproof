.PHONY: setup demo serve test lint format type check eval samples synthetic restore-drill up down logs deploy-smoke clean

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

check: lint type test eval restore-drill

eval:
	uv run paperproof eval

restore-drill:
	uv run paperproof restore-drill

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app

deploy-smoke:
	uv run python scripts/smoke.py

samples:
	uv run paperproof samples --force

synthetic:
	uv run paperproof corpus --count 100 --out data/synthetic --force

clean:
	rm -rf data .pytest_cache .ruff_cache .coverage htmlcov
