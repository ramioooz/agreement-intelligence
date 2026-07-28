SHELL := /bin/sh

NODE_VERSION ?= $(shell cat .node-version)
PYTHON_VERSION ?= $(shell cat .python-version)
PNPM_VERSION ?= $(shell node -p "require('./package.json').packageManager.split('@')[1]")

.PHONY: help check-toolchain setup dev dev-web dev-api dev-worker \
	format format-check lint typecheck test build check

help:
	@echo "Agreement Intelligence developer commands"
	@echo "  make setup         Verify tools and install locked dependencies"
	@echo "  make dev           Start web, API, and worker"
	@echo "  make dev-web       Start only the web application"
	@echo "  make dev-api       Start only the API"
	@echo "  make dev-worker    Start only the worker"
	@echo "  make format        Format TypeScript and Python"
	@echo "  make lint          Lint TypeScript and Python"
	@echo "  make typecheck     Type-check TypeScript and Python"
	@echo "  make test          Run JavaScript and Python tests"
	@echo "  make build         Build every application"
	@echo "  make check         Run all pre-review checks"

check-toolchain:
	@command -v node >/dev/null 2>&1 || { echo "Node.js is not installed."; exit 1; }
	@actual="$$(node --version)"; expected="v$(NODE_VERSION)"; \
		[ "$$actual" = "$$expected" ] || { \
			echo "Node.js version mismatch: expected $$expected, found $$actual."; \
			echo "Install or activate the version in .node-version."; \
			exit 1; \
		}
	@command -v pnpm >/dev/null 2>&1 || { echo "pnpm is not installed."; exit 1; }
	@actual="$$(pnpm --version)"; expected="$(PNPM_VERSION)"; \
		[ "$$actual" = "$$expected" ] || { \
			echo "pnpm version mismatch: expected $$expected, found $$actual."; \
			echo "Run: corepack install --global pnpm@$(PNPM_VERSION)"; \
			exit 1; \
		}
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed."; exit 1; }
	@echo "Toolchain versions are valid."

setup: check-toolchain
	uv python install $(PYTHON_VERSION)
	pnpm install --frozen-lockfile
	uv sync --all-packages --frozen

dev: check-toolchain
	pnpm dev

dev-web: check-toolchain
	pnpm --filter @agreement-intelligence/web dev

dev-api: check-toolchain
	uv run --package agreement-intelligence-api uvicorn \
		agreement_intelligence_api.main:app --reload --host 127.0.0.1 --port 8000

dev-worker: check-toolchain
	uv run --package agreement-intelligence-worker agreement-worker

format:
	pnpm format
	uv run ruff format apps/api apps/worker

format-check:
	pnpm format:check
	uv run ruff format --check apps/api apps/worker

lint:
	pnpm --filter @agreement-intelligence/web lint
	uv run ruff check apps/api apps/worker

typecheck:
	pnpm --filter @agreement-intelligence/web typecheck
	uv run mypy apps/api/src apps/api/tests apps/worker/src apps/worker/tests

test:
	pnpm --filter @agreement-intelligence/web test
	uv run pytest

build:
	pnpm --filter @agreement-intelligence/web build
	uv build --package agreement-intelligence-api --out-dir dist/api
	uv build --package agreement-intelligence-worker --out-dir dist/worker

check:
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) build
