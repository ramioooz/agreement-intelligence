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
$compose run --rm --no-deps api python -c "from sqlalchemy import create_engine,text; import os; u=os.environ['DATABASE_URL'].replace('postgresql://','postgresql+psycopg://'); c=create_engine(u).connect(); c.execute(text('select 1')); c.close()"
$compose stop postgres
if $compose run --rm --no-deps api python -c "from sqlalchemy import create_engine,text; import os; u=os.environ['DATABASE_URL'].replace('postgresql://','postgresql+psycopg://'); c=create_engine(u,pool_pre_ping=True).connect(); c.execute(text('select 1'))" 2>/dev/null; then
  echo "Database operation unexpectedly succeeded during interruption." >&2
  exit 1
fi
started=$(date +%s)
$compose start postgres >/dev/null
while ! $compose run --rm --no-deps api python -c "from sqlalchemy import create_engine,text; import os; u=os.environ['DATABASE_URL'].replace('postgresql://','postgresql+psycopg://'); c=create_engine(u,pool_pre_ping=True).connect(); c.execute(text('select 1')); c.close()" 2>/dev/null; do
  [ $(( $(date +%s) - started )) -lt 45 ] || { echo "Database did not recover." >&2; exit 1; }
  sleep 1
done
echo "Database-dependent operations recovered in $(( $(date +%s) - started )) seconds."
