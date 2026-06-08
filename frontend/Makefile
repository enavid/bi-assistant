NPM := npm

.DEFAULT_GOAL := help

.PHONY: help install dev build preview type-check test lint format check

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install      install dependencies"
	@echo "  dev          start dev server with hot-reload"
	@echo "  build        production build (type-check + bundle)"
	@echo "  preview      serve the production build locally"
	@echo "  type-check   TypeScript type checking (no emit)"
	@echo "  test         run unit/component tests (vitest)"
	@echo "  lint         check code with ESLint"
	@echo "  format       auto-format code (prettier + eslint --fix)"
	@echo "  check        lint + type-check + build (run before committing)"

install:
	$(NPM) install

dev:
	$(NPM) run dev

build:
	$(NPM) run build

preview:
	$(NPM) run preview

type-check:
	$(NPM) run type-check

test:
	$(NPM) run test

lint:
	$(NPM) run lint

format:
	$(NPM) run format

check: lint type-check build
