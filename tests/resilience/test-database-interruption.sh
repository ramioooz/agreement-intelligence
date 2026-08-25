#!/bin/sh
set -eu

[ "${RESILIENCE_TEST_CONFIRM:-}" = "isolated" ] || {
  echo "Set RESILIENCE_TEST_CONFIRM=isolated." >&2
  exit 1
}

repo_root=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
project="ai-resilience-database-$$"
env_file=$(mktemp "${TMPDIR:-/tmp}/ai-resilience-database.XXXXXX")
base=$((42000 + ($$ % 10000)))
cleanup() {
  docker compose --project-name "$project" --env-file "$env_file" -f "$repo_root/compose.yaml" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file"
}
trap cleanup EXIT INT TERM

sed \
  -e 's/change-me-/test-/' \
  -e "s/^POSTGRES_PORT=.*/POSTGRES_PORT=$base/" \
  -e "s/^KEYCLOAK_PORT=.*/KEYCLOAK_PORT=$((base + 1))/" \
  -e "s#^OIDC_ISSUER=.*#OIDC_ISSUER=http://localhost:$((base + 1))/realms/agreement-intelligence#" \
  -e "s/^LOCALSTACK_PORT=.*/LOCALSTACK_PORT=$((base + 2))/" \
  -e "s/^REDIS_PORT=.*/REDIS_PORT=$((base + 3))/" \
  -e "s/^OTEL_GRPC_PORT=.*/OTEL_GRPC_PORT=$((base + 4))/" \
  -e "s/^OTEL_HTTP_PORT=.*/OTEL_HTTP_PORT=$((base + 5))/" \
  -e "s/^WEB_PORT=.*/WEB_PORT=$((base + 6))/" \
  -e "s/^API_PORT=.*/API_PORT=$((base + 7))/" \
  -e "s#^WEB_PUBLIC_ORIGIN=.*#WEB_PUBLIC_ORIGIN=http://localhost:$((base + 6))#" \
  -e "s#^AUTH_URL=.*#AUTH_URL=http://localhost:$((base + 6))#" \
  "$repo_root/.env.example" > "$env_file"

compose="docker compose --project-name $project --env-file $env_file -f $repo_root/compose.yaml"
$compose up --detach --wait --wait-timeout 120 postgres
$compose build api >/dev/null
$compose run --rm --no-deps api alembic -c apps/api/alembic.ini upgrade head >/dev/null
api_container=$($compose run --detach --no-deps \
  --publish "$((base + 7)):8000" \
  -e READINESS_CHECK_DATABASE_CONNECTIVITY=true \
  api uvicorn agreement_intelligence_api.main:app --host 0.0.0.0 --port 8000)
api_url="http://127.0.0.1:$((base + 7))/health/ready"
started=$(date +%s)
while ! curl --fail --silent "$api_url" >/dev/null 2>&1; do
  [ $(( $(date +%s) - started )) -lt 30 ] || {
    echo "API did not become ready before the interruption." >&2
    docker logs "$api_container" >&2 || true
    exit 1
  }
  sleep 1
done
$compose stop postgres
readiness_code=$(curl --silent --output /dev/null --write-out '%{http_code}' "$api_url")
if [ "$readiness_code" != "503" ]; then
  echo "API readiness returned $readiness_code while PostgreSQL was unavailable; expected 503." >&2
  exit 1
fi
started=$(date +%s)
$compose start postgres >/dev/null
while ! curl --fail --silent "$api_url" >/dev/null 2>&1; do
  [ $(( $(date +%s) - started )) -lt 45 ] || { echo "Database did not recover." >&2; exit 1; }
  sleep 1
done
echo "API readiness detected the database interruption and recovered in $(( $(date +%s) - started )) seconds."
