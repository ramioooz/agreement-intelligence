#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

env_file=$(mktemp)
reset_output=$(mktemp)
help_output=$(mktemp)
cleanup() {
  STACK_ENV_FILE="$env_file" make stack-down >/dev/null 2>&1 || true
  rm -f "$env_file" "$reset_output" "$help_output"
}
trap cleanup EXIT INT TERM
sed 's/change-me/test-only-value/g' .env.example >"$env_file"
make help >"$help_output"

for target in \
  stack-build stack-up stack-down stack-status stack-logs stack-check stack-reset; do
  grep -q "make $target" "$help_output" || {
    echo "Missing Make target: $target"
    exit 1
  }
done

for removed in dev dev-web dev-api dev-worker; do
  if grep -q "make $removed " "$help_output"; then
    echo "Host runtime target still published: $removed"
    exit 1
  fi
done

if STACK_ENV_FILE="$env_file" make stack-reset >"$reset_output" 2>&1; then
  echo "Unconfirmed reset unexpectedly succeeded"
  exit 1
fi
grep -q 'CONFIRM=reset' "$reset_output"

STACK_ENV_FILE="$env_file" make stack-reset CONFIRM=reset
STACK_ENV_FILE="$env_file" make stack-check

docker compose --project-name agreement-intelligence \
  --env-file "$env_file" exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --command "CREATE TABLE IF NOT EXISTS stack_lifecycle_sentinel (id text PRIMARY KEY); INSERT INTO stack_lifecycle_sentinel(id) VALUES ('\''preserved-volume'\'') ON CONFLICT DO NOTHING;"'

for service in web api worker postgres localstack keycloak; do
  docker compose --project-name agreement-intelligence \
    --env-file "$env_file" ps --services --status running \
    | grep -qx "$service"
done

sed 's/API_PORT=8000/API_PORT=not-a-port/' "$env_file" >"$reset_output"
if STACK_ENV_FILE="$reset_output" make stack-reset CONFIRM=reset >/dev/null 2>&1; then
  echo "Reset with invalid configuration unexpectedly succeeded"
  exit 1
fi
STACK_ENV_FILE="$env_file" make stack-check

STACK_ENV_FILE="$env_file" make stack-down
test -z "$(docker compose --project-name agreement-intelligence \
  --env-file "$env_file" ps --all --quiet)"

STACK_ENV_FILE="$env_file" make stack-up
STACK_ENV_FILE="$env_file" make stack-check
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --tuples-only \
    --no-align \
    --command "SELECT count(*) FROM stack_lifecycle_sentinel WHERE id = '\''preserved-volume'\'';"' \
  | grep -qx '1'
STACK_ENV_FILE="$env_file" make stack-down
test -z "$(docker compose --project-name agreement-intelligence \
  --env-file "$env_file" ps --all --quiet)"
