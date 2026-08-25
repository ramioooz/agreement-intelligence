SHELL := /bin/sh

NODE_VERSION ?= $(shell cat .node-version)
PYTHON_VERSION ?= $(shell cat .python-version)
PNPM_VERSION ?= $(shell node -p "require('./package.json').packageManager.split('@')[1]")
STACK_ENV_FILE ?= .env
COMPOSE := docker compose --project-name agreement-intelligence --env-file $(STACK_ENV_FILE)

.PHONY: help check-toolchain check-container-toolchain setup \
	stack-build stack-up stack-down stack-status stack-logs stack-check stack-reset \
	format format-check lint typecheck test build check provider-smoke retrieval-eval version-comparison-eval
	performance-local resilience-local

help:
	@echo "Agreement Intelligence developer commands"
	@echo "  make setup          Verify source tools and install locked dependencies"
	@echo "  make stack-build    Build application container images"
	@echo "  make stack-up       Build, start, and wait for the complete stack"
	@echo "  make stack-down     Stop containers while preserving project data"
	@echo "  make stack-status   Show project containers and health"
	@echo "  make stack-logs     Follow logs for the complete stack"
	@echo "  make stack-check    Verify services and bootstrapped resources"
	@echo "  make stack-reset    Recreate the stack and volumes with CONFIRM=reset"
	@echo "  make format         Format TypeScript and Python"
	@echo "  make format-check   Check TypeScript and Python formatting"
	@echo "  make lint           Lint TypeScript and Python"
	@echo "  make typecheck      Type-check TypeScript and Python"
	@echo "  make test           Run JavaScript and Python tests"
	@echo "  make build          Build every application"
	@echo "  make check          Run all pre-review source checks"
	@echo "  make provider-smoke Run an opt-in configured-provider smoke check"
	@echo "  make retrieval-eval Evaluate retrieval and grounded-answer results"
	@echo "  make version-comparison-eval Evaluate agreement-version comparison results"
	@echo "  make performance-local Run opt-in synthetic local performance checks"
	@echo "  make resilience-local Run opt-in isolated local recovery checks"

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
	@echo "Source toolchain versions are valid."

check-container-toolchain:
	@command -v docker >/dev/null 2>&1 || { echo "Docker is not installed."; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "Docker is not running."; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "Docker Compose is unavailable."; exit 1; }
	@version="$$(docker compose version --short | sed 's/^v//')"; \
		major="$${version%%.*}"; rest="$${version#*.}"; minor="$${rest%%.*}"; \
		[ "$$major" -gt 2 ] || { [ "$$major" -eq 2 ] && [ "$$minor" -ge 24 ]; } || { \
			echo "Docker Compose 2.24 or newer is required; found $$version."; \
			exit 1; \
		}
	@echo "Container toolchain is valid."

setup: check-toolchain
	uv python install $(PYTHON_VERSION)
	pnpm install --frozen-lockfile
	uv sync --all-packages --frozen

stack-build: check-container-toolchain
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	$(COMPOSE) build

stack-up: check-container-toolchain
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	$(COMPOSE) up --detach --build --wait --wait-timeout 180

stack-down: check-container-toolchain
	$(COMPOSE) down --remove-orphans

stack-status: check-container-toolchain
	$(COMPOSE) ps --all

stack-logs: check-container-toolchain
	$(COMPOSE) logs --follow

stack-check: check-container-toolchain
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/stack-check.sh

stack-reset: check-container-toolchain
	@[ "$(CONFIRM)" = "reset" ] || { \
		echo "Refusing to delete project volumes. Re-run with CONFIRM=reset."; \
		exit 1; \
	}
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	@$(COMPOSE) config --quiet
	$(COMPOSE) down --volumes --remove-orphans
	$(MAKE) stack-up STACK_ENV_FILE="$(STACK_ENV_FILE)"

format:
	pnpm format
	uv run ruff format apps/api apps/mcp apps/worker

format-check:
	pnpm format:check
	uv run ruff format --check apps/api apps/mcp apps/worker

lint:
	pnpm --filter @agreement-intelligence/web lint
	uv run ruff check apps/api apps/mcp apps/worker

typecheck:
	pnpm --filter @agreement-intelligence/web typecheck
	uv run mypy apps/api/src apps/api/tests apps/mcp/src apps/mcp/tests apps/worker/src apps/worker/tests

test:
	pnpm --filter @agreement-intelligence/web test
	uv run pytest
	tests/ci/test-ci-workflow.sh
	tests/web/test-auth-contract.sh

build:
	pnpm --filter @agreement-intelligence/web build
	uv build --package agreement-intelligence-api --out-dir dist/api
	uv build --package agreement-intelligence-mcp --out-dir dist/mcp
	uv build --package agreement-intelligence-worker --out-dir dist/worker

check:
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) build

terraform-check:
	./tests/infra/test-terraform-contract.sh

provider-smoke:
	uv run --env-file "$(STACK_ENV_FILE)" python -m agreement_intelligence_worker.provider_smoke

retrieval-eval:
	@[ -n "$(RETRIEVAL_EVAL_RESULTS)" ] || { \
		echo "RETRIEVAL_EVAL_RESULTS must name an evaluation results JSON file."; exit 1; \
	}
	uv run --package agreement-intelligence-worker python -m agreement_intelligence_worker.retrieval_evaluation --results "$(RETRIEVAL_EVAL_RESULTS)"

version-comparison-eval:
	@[ -n "$(VERSION_COMPARISON_EVAL_RESULTS)" ] || { \
		echo "VERSION_COMPARISON_EVAL_RESULTS must name an evaluation results JSON file."; exit 1; \
	}
	uv run --package agreement-intelligence-worker python -m agreement_intelligence_worker.version_comparison_evaluation --results "$(VERSION_COMPARISON_EVAL_RESULTS)"

performance-local:
	@[ "$(PERFORMANCE_TEST_CONFIRM)" = "synthetic" ] || { \
		echo "Refusing to run. Re-run with PERFORMANCE_TEST_CONFIRM=synthetic."; exit 1; \
	}
	@$(MAKE) check-container-toolchain
	@tests/performance/run-local.sh

resilience-local:
	@[ "$(RESILIENCE_TEST_CONFIRM)" = "isolated" ] || { \
		echo "Refusing to run. Re-run with RESILIENCE_TEST_CONFIRM=isolated."; exit 1; \
	}
	@$(MAKE) check-container-toolchain
	@uv run python tests/resilience/test-duplicate-delivery.py
	@uv run python tests/resilience/test-provider-timeout.py
	@tests/resilience/test-worker-restart.sh
	@tests/resilience/test-queue-backlog.sh
	@tests/resilience/test-database-interruption.sh
