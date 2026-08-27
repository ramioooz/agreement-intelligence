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

for provider_variable in OPENAI_API_KEY MODEL_GATEWAY_API_KEY; do
  test -z "$(effective_value "$provider_variable")" || {
    echo "The deterministic release gate requires $provider_variable to be empty."
    echo "Run provider-smoke separately with an ignored, authorized provider configuration."
    exit 1
  }
done

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

echo "[release] Audit production dependencies"
pnpm audit --prod --audit-level high
uv run pip-audit --ignore-vuln PYSEC-2026-3046 --ignore-vuln PYSEC-2026-2447

echo "[release] Scan reachable Git history for secrets (values redacted)"
gitleaks git . --log-opts=--all --no-banner --redact

echo "[release] Validate and provision/destroy emulated infrastructure"
make terraform-check
make terraform-provision-local

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
