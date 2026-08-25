#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

for file in scripts/backup-local.sh scripts/restore-local.sh; do
  test -x "$file" || {
    echo "$file must exist and be executable"
    exit 1
  }
done

for target in backup-local restore-local; do
  make -qp | grep -Eq "^${target}:" || {
    echo "Make target is missing: $target"
    exit 1
  }
done

test "${BACKUP_RESTORE_LIVE:-0}" = 1 || {
  echo "Set BACKUP_RESTORE_LIVE=1 to run the isolated destructive restore rehearsal."
  exit 1
}

test_root=$(mktemp -d)
project_name="agreement-intelligence-backup-test-$$"
env_file="$test_root/stack.env"
backup_dir="$test_root/backup"
tampered_dir="$test_root/tampered"
unconfirmed_output="$test_root/unconfirmed.log"
tampered_output="$test_root/tampered.log"

cleanup() {
  status=$?
  if test "$status" -ne 0; then
    compose ps -a >&2 || true
    compose logs --no-color --tail=200 api postgres >&2 || true
  fi
  docker compose --project-name "$project_name" --env-file "$env_file" \
    down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$test_root"
  exit "$status"
}
trap cleanup EXIT INT TERM

sed \
  -e 's/change-me/test-only-value/g' \
  -e 's/^POSTGRES_PORT=.*/POSTGRES_PORT=56432/' \
  -e 's/^KEYCLOAK_PORT=.*/KEYCLOAK_PORT=58080/' \
  -e 's/^LOCALSTACK_PORT=.*/LOCALSTACK_PORT=54566/' \
  -e 's/^REDIS_PORT=.*/REDIS_PORT=56379/' \
  -e 's/^OTEL_GRPC_PORT=.*/OTEL_GRPC_PORT=54317/' \
  -e 's/^OTEL_HTTP_PORT=.*/OTEL_HTTP_PORT=54318/' \
  -e 's/^MCP_PORT=.*/MCP_PORT=58001/' \
  -e 's/^WEB_PORT=.*/WEB_PORT=53000/' \
  -e 's/^API_PORT=.*/API_PORT=58000/' \
  -e 's#^WEB_PUBLIC_ORIGIN=.*#WEB_PUBLIC_ORIGIN=http://localhost:53000#' \
  -e 's#^AUTH_URL=.*#AUTH_URL=http://localhost:53000#' \
  -e 's#^OIDC_ISSUER=.*#OIDC_ISSUER=http://localhost:58080/realms/agreement-intelligence#' \
  .env.example >"$env_file"

compose() {
  docker compose --project-name "$project_name" --env-file "$env_file" "$@"
}

if ! STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" make stack-up; then
  compose logs --no-color keycloak-bootstrap localstack-bootstrap >&2
  exit 1
fi

compose exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql --host 127.0.0.1 --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" --command \
    "CREATE TABLE backup_restore_marker(value text PRIMARY KEY); INSERT INTO backup_restore_marker VALUES ('\''preserved'\'');"'

printf 'immutable-source-artifact\n' \
  | compose run --rm --no-deps --entrypoint sh localstack-bootstrap -c \
    'awslocal --endpoint-url http://localstack:4566 s3 cp - "s3://$S3_DOCUMENT_BUCKET/backup-test/source.txt" >/dev/null'

started=$(date +%s)
STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" \
  BACKUP_DIR="$backup_dir" make backup-local
backup_seconds=$(($(date +%s) - started))

for file in manifest.json postgres.dump objects.tar SHA256SUMS; do
  test -s "$backup_dir/$file"
done
test ! -e "$backup_dir/.env"
test ! -e "$backup_dir/stack.env"

if STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" \
  RESTORE_DIR="$backup_dir" make restore-local >"$unconfirmed_output" 2>&1; then
  echo "Restore unexpectedly succeeded without CONFIRM=restore"
  exit 1
fi
grep -q 'CONFIRM=restore' "$unconfirmed_output"

cp -R "$backup_dir" "$tampered_dir"
printf 'tampered' >>"$tampered_dir/postgres.dump"
if STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" \
  RESTORE_DIR="$tampered_dir" CONFIRM=restore make restore-local \
  >"$tampered_output" 2>&1; then
  echo "Restore unexpectedly accepted a checksum mismatch"
  exit 1
fi
grep -q 'checksum' "$tampered_output"

compose down --volumes --remove-orphans
STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" make stack-up

started=$(date +%s)
STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" \
  RESTORE_DIR="$backup_dir" CONFIRM=restore make restore-local
restore_seconds=$(($(date +%s) - started))

compose exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql --host 127.0.0.1 --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" --tuples-only --no-align \
    --command "SELECT value FROM backup_restore_marker;"' \
  | grep -qx preserved

compose run --rm --no-deps --entrypoint sh localstack-bootstrap -c \
  'awslocal --endpoint-url http://localstack:4566 s3 cp \
    "s3://$S3_DOCUMENT_BUCKET/backup-test/source.txt" -' \
  | grep -qx immutable-source-artifact

STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" make stack-check
echo "Backup completed in ${backup_seconds}s; restore completed in ${restore_seconds}s."
