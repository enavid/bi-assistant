VENV   := venv
PYTHON := $(VENV)/bin/python3
PIP    := $(VENV)/bin/pip
UV     := $(VENV)/bin/uvicorn
PYTEST := $(VENV)/bin/pytest
RUFF   := $(VENV)/bin/ruff
ALEMBIC:= $(VENV)/bin/alembic

.DEFAULT_GOAL := help

.PHONY: help install run dev test lint format check migrate shell

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install   create venv and install dependencies"
	@echo "  run       start the API server (production mode)"
	@echo "  dev       start the API server with hot-reload"
	@echo "  test      run all tests"
	@echo "  lint      check code with ruff"
	@echo "  format    auto-format code with ruff"
	@echo "  check     lint + test (run before committing)"
	@echo "  migrate   apply database migrations"
	@echo "  shell     open Python REPL inside the venv"

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(UV) app.main:app --host 0.0.0.0 --port 8000

dev:
	$(UV) app.main:app --reload --host 0.0.0.0 --port 8000

test:
	$(PYTEST) tests -q

lint:
	$(RUFF) check .

format:
	$(RUFF) check . --fix
	$(RUFF) format .

check: lint test

migrate:
	$(ALEMBIC) upgrade head

shell:
	$(PYTHON)
