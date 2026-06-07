NPM := npm

.DEFAULT_GOAL := help

.PHONY: help install dev build preview type-check check

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install     install dependencies"
	@echo "  dev         start dev server with hot-reload"
	@echo "  build       production build (type-check + bundle)"
	@echo "  preview     serve the production build locally"
	@echo "  type-check  TypeScript type checking (no emit)"
	@echo "  check       type-check + build (run before committing)"

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

check: type-check build
