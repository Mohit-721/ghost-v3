.PHONY: dev install test lint typecheck format clean run stop

# ─── Development Setup ──────────────────────────────────────────────────────
dev:
	pip install -e ".[dev]"

install:
	pip install -e .

# ─── Quality ────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --tb=short --cov=ghost --cov-report=term-missing

lint:
	ruff check src/ tests/

typecheck:
	mypy src/ghost/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# ─── Run ────────────────────────────────────────────────────────────────────
run:
	ghost start

stop:
	ghost stop

status:
	ghost status

# ─── Clean ──────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov dist build
