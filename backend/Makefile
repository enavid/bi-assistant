PYTEST  := uv run pytest
RUFF    := uv run ruff
ALEMBIC := uv run alembic
PYTHON  := uv run python

INPUT   ?= eval/questions_example.json
OUTPUT  ?=
FORMAT  ?= both
CONCURRENCY ?= 1

.DEFAULT_GOAL := help

.PHONY: help install run dev test eval trace-eval lint format check migrate shell

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install      sync dependencies (dev + prod)"
	@echo "  run          start the API server (production mode)"
	@echo "  dev          start the API server with hot-reload"
	@echo "  test         run unit/integration tests"
	@echo "  eval         run routing evaluation (golden test suite)"
	@echo "  trace-eval   run batch trace evaluation against a questions file"
	@echo "               INPUT=<path>  questions file, JSON or CSV (default: eval/questions_example.json)"
	@echo "               OUTPUT=<path> output base path without extension (optional)"
	@echo "               FORMAT=<fmt>  json | csv | both (default: both)"
	@echo "               CONCURRENCY=<n> parallel questions (default: 1)"
	@echo "  lint         check code with ruff"
	@echo "  format       auto-format code with ruff"
	@echo "  check        lint + test + eval (run before committing)"
	@echo "  migrate      apply database migrations"
	@echo "  shell        open Python REPL"

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

trace-eval:
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Trace Evaluation — Batch Pipeline Runner"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	$(PYTHON) eval/run_evaluation.py \
		--input "$(INPUT)" \
		$(if $(OUTPUT),--output "$(OUTPUT)",) \
		--format $(FORMAT) \
		--concurrency $(CONCURRENCY)
	@echo ""

lint:
	$(RUFF) check .
	$(RUFF) format --check .

format:
	$(RUFF) check . --fix
	$(RUFF) format .

check: lint
	-$(PYTEST) tests -q --ignore=tests/routing_eval
	$(PYTEST) tests/routing_eval -v --tb=short --no-header

migrate:
	$(ALEMBIC) upgrade head

shell:
	$(PYTHON)
