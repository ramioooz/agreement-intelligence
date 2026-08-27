#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

stack_env_file=${STACK_ENV_FILE:-.env}
stack_project_name=${STACK_PROJECT_NAME:-agreement-intelligence}
test_database_url=${RELEASE_TEST_POSTGRES_URL:-}

test -n "$test_database_url" || {
  echo "RELEASE_TEST_POSTGRES_URL must name an explicit disposable PostgreSQL database."
  exit 1
}
case "$test_database_url" in
  *agreement_intelligence_test* | *public_release*) ;;
  *)
    echo "RELEASE_TEST_POSTGRES_URL must visibly identify a test/public_release database."
    exit 1
    ;;
esac

test -f "$stack_env_file" || {
  echo "Missing $stack_env_file. Copy .env.example to an ignored .env and replace placeholders."
  exit 1
}

effective_value() {
  variable=$1
  if value=$(printenv "$variable"); then
    printf '%s\n' "$value"
  else
    sed -n "s/^${variable}=//p" "$stack_env_file" | tail -n 1
  fi
}

scripts/validate-release-no-key.sh "$stack_env_file"

for command in gitleaks terraform tflocal checkov; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Missing release tool: $command"
    exit 1
  }
done

export AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL=$test_database_url
export STACK_ENV_FILE=$stack_env_file
export STACK_PROJECT_NAME=$stack_project_name
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_REGION=$(effective_value AWS_REGION)
export AWS_DEFAULT_REGION=$AWS_REGION
export AWS_EC2_METADATA_DISABLED=true
export LOCALSTACK_ENDPOINT="http://127.0.0.1:$(effective_value LOCALSTACK_PORT)"
export AGREEMENT_INTELLIGENCE_TEST_LOCALSTACK_URL=$LOCALSTACK_ENDPOINT
export AWS_ENDPOINT_URL=$LOCALSTACK_ENDPOINT
export REDIS_URL="redis://127.0.0.1:$(effective_value REDIS_PORT)/0"

echo "[release] Validate toolchains and local environment"
make check-toolchain
make check-container-toolchain
scripts/validate-stack-env.sh

echo "[release] Validate public documentation and collection contracts"
tests/docs/test-documentation-contract.sh

echo "[release] Run source formatting, lint, types, tests, and builds"
make check

echo "[release] Audit production dependencies and reviewed Python development-tool exceptions"
pnpm audit --prod --audit-level high
uv run pip-audit --ignore-vuln PYSEC-2026-3046 --ignore-vuln PYSEC-2026-2447

echo "[release] Scan reachable Git history for secrets (values redacted)"
gitleaks git . --log-opts=--all --no-banner --redact

echo "[release] Validate and provision/destroy emulated infrastructure"
make terraform-check
make terraform-provision-local

echo "[release] Recreate and inspect the effective no-key application containers"
docker compose --project-name "$stack_project_name" --env-file "$stack_env_file" \
  up --detach --build --force-recreate --no-deps --wait --wait-timeout 180 api worker
for service in api worker; do
  docker compose --project-name "$stack_project_name" --env-file "$stack_env_file" \
    exec -T "$service" python -c '
import os
import sys

mode = os.environ.get("MODEL_GATEWAY_MODE", "openai")
provider_values = (
    os.environ.get("OPENAI_API_KEY", ""),
    os.environ.get("MODEL_GATEWAY_API_KEY", ""),
    os.environ.get("MODEL_GATEWAY_BASE_URL", ""),
    os.environ.get("MODEL_GATEWAY_FALLBACK_MODE", ""),
    os.environ.get("MODEL_GATEWAY_FALLBACK_MODEL", ""),
)
if mode == "openai-compatible" or any(provider_values):
    print("Effective container configuration is provider-enabled.", file=sys.stderr)
    raise SystemExit(1)
'
done

echo "[release] Verify the running no-key stack and OpenAPI-linked collection"
make stack-check
api_port=$(effective_value API_PORT)
OPENAPI_URL="http://127.0.0.1:${api_port}/openapi.json" node scripts/check-doc-links.mjs

echo "[release] Run deterministic AI evaluation"
make ai-eval

echo "[release] Run the single-worker critical browser journey"
uv run --env-file "$stack_env_file" pnpm --filter @agreement-intelligence/web exec \
  playwright test --project release

echo "Public-release gate passed. Provider smoke and owner manual QA remain separate opt-in gates."
