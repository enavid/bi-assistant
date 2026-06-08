PYTEST  := uv run pytest
RUFF    := uv run ruff
ALEMBIC := uv run alembic
PYTHON  := uv run python

.DEFAULT_GOAL := help

.PHONY: help install run dev test eval lint format check migrate shell

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install   sync dependencies (dev + prod)"
	@echo "  run       start the API server (production mode)"
	@echo "  dev       start the API server with hot-reload"
	@echo "  test      run unit/integration tests"
	@echo "  eval      run routing evaluation (golden test suite)"
	@echo "  lint      check code with ruff"
	@echo "  format    auto-format code with ruff"
	@echo "  check     lint + test + eval (run before committing)"
	@echo "  migrate   apply database migrations"
	@echo "  shell     open Python REPL"

install:
	uv sync --group dev

run:
	$(PYTHON) run.py

dev:
	$(PYTHON) run.py --reload

test:
	$(PYTEST) tests -q --ignore=tests/routing_eval

eval:
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Routing Evaluation — Golden Test Suite"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	$(PYTEST) tests/routing_eval -v --tb=short --no-header
	@echo ""

lint:
	$(RUFF) check .

format:
	$(RUFF) check . --fix
	$(RUFF) format .

check: lint test eval

migrate:
	$(ALEMBIC) upgrade head

shell:
	$(PYTHON)
