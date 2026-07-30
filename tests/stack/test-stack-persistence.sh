#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

env_file=$(mktemp)
reset_output=$(mktemp)
cleanup() {
  STACK_ENV_FILE="$env_file" make stack-down >/dev/null 2>&1 || true
  rm -f "$env_file" "$reset_output"
}
trap cleanup EXIT INT TERM
sed 's/change-me/test-only-value/g' .env.example >"$env_file"

compose() {
  docker compose --project-name agreement-intelligence \
    --env-file "$env_file" "$@"
}

STACK_ENV_FILE="$env_file" make stack-reset CONFIRM=reset
compose exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --command "CREATE TABLE IF NOT EXISTS stack_persistence_marker (value text NOT NULL);"'
compose exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --command "TRUNCATE stack_persistence_marker; INSERT INTO stack_persistence_marker VALUES ('\''preserved'\'');"'

STACK_ENV_FILE="$env_file" make stack-down
STACK_ENV_FILE="$env_file" make stack-up

compose exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --tuples-only \
    --no-align \
    --command "SELECT value FROM stack_persistence_marker;"' \
  | grep -qx preserved

if STACK_ENV_FILE="$env_file" make stack-reset >"$reset_output" 2>&1; then
  echo "Unconfirmed reset unexpectedly succeeded"
  exit 1
fi
grep -q 'CONFIRM=reset' "$reset_output"

STACK_ENV_FILE="$env_file" make stack-reset CONFIRM=reset

if compose exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --tuples-only \
    --command "SELECT to_regclass('\''public.stack_persistence_marker'\'');"' \
  | grep -q stack_persistence_marker; then
  echo "Confirmed reset preserved the marker unexpectedly"
  exit 1
fi

STACK_ENV_FILE="$env_file" make stack-check
