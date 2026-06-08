VENV   := venv
PYTHON := $(VENV)/bin/python3
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff
ALEMBIC:= $(VENV)/bin/alembic

.DEFAULT_GOAL := help

.PHONY: help install run dev test eval lint format check migrate shell

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install   create venv and install dependencies"
	@echo "  run       start the API server (production mode)"
	@echo "  dev       start the API server with hot-reload"
	@echo "  test      run unit/integration tests"
	@echo "  eval      run routing evaluation (golden test suite)"
	@echo "  lint      check code with ruff"
	@echo "  format    auto-format code with ruff"
	@echo "  check     lint + test + eval (run before committing)"
	@echo "  migrate   apply database migrations"
	@echo "  shell     open Python REPL inside the venv"

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

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
	$(PYTEST) tests/routing_eval -v --tb=short --no-header -q
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
