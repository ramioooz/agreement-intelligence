#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

env_file=${STACK_ENV_FILE:-.env}
project_name=${STACK_PROJECT_NAME:-agreement-intelligence}
restore_dir=${RESTORE_DIR:-}

test "${CONFIRM:-}" = restore || {
  echo "Refusing restore. Re-run with CONFIRM=restore."
  exit 1
}
test -n "$restore_dir" || {
  echo "RESTORE_DIR must name the backup to restore."
  exit 1
}
test -d "$restore_dir" || {
  echo "Restore directory does not exist: $restore_dir"
  exit 1
}

for file in manifest.json postgres.dump objects.tar SHA256SUMS; do
  test -s "$restore_dir/$file" || {
    echo "Backup is incomplete: $file"
    exit 1
  }
done

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$restore_dir" && sha256sum --check SHA256SUMS) >/dev/null || {
    echo "Backup checksum verification failed."
    exit 1
  }
else
  (cd "$restore_dir" && shasum -a 256 --check SHA256SUMS) >/dev/null || {
    echo "Backup checksum verification failed."
    exit 1
  }
fi

database_name=$(sed -n 's/^APP_DB_NAME=//p' "$env_file" | tail -n 1)
bucket_name=$(sed -n 's/^S3_DOCUMENT_BUCKET=//p' "$env_file" | tail -n 1)

python3 - "$restore_dir/manifest.json" "$restore_dir/objects.tar" \
  "$database_name" "$bucket_name" <<'PY'
import json
import sys
import tarfile

path, objects_archive, expected_database, expected_bucket = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    manifest = json.load(handle)
if manifest.get("format_version") != 1:
    raise SystemExit("Unsupported backup format version.")
if manifest.get("database", {}).get("name") != expected_database:
    raise SystemExit("Backup database does not match the configured application database.")
if manifest.get("object_store", {}).get("bucket") != expected_bucket:
    raise SystemExit("Backup bucket does not match the configured document bucket.")
with tarfile.open(objects_archive) as archive:
    archived_keys = sorted(
        member.name.removeprefix("./")
        for member in archive.getmembers()
        if member.isfile()
    )
recorded_keys = manifest.get("object_store", {}).get("object_keys")
if recorded_keys != archived_keys:
    raise SystemExit("Backup object inventory does not match the object archive.")
PY

tar -tf "$restore_dir/objects.tar" | while IFS= read -r member; do
  case "$member" in
    /* | ../* | */../* | */..) echo "Unsafe object archive path: $member"; exit 1 ;;
  esac
done

compose() {
  docker compose --project-name "$project_name" --env-file "$env_file" "$@"
}

compose stop web mcp worker api >/dev/null
restart_services() {
  compose up --detach --wait --wait-timeout 180 api worker mcp web >/dev/null 2>&1 || true
}
trap restart_services EXIT INT TERM

compose exec -T postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --host 127.0.0.1 \
    --username postgres --dbname "$APP_DB_NAME" --clean --if-exists \
    --single-transaction --no-privileges' <"$restore_dir/postgres.dump"

compose run --rm --no-deps --entrypoint sh \
  --volume "$restore_dir/objects.tar:/objects.tar:ro" localstack-bootstrap -c \
  'mkdir -p /restore-objects && rm -rf /restore-objects/* && \
   tar -xf /objects.tar -C /restore-objects && \
   awslocal --endpoint-url http://localstack:4566 s3 sync /restore-objects \
     "s3://$S3_DOCUMENT_BUCKET" --delete --only-show-errors'

compose run --rm --no-deps api alembic -c apps/api/alembic.ini upgrade head
compose up --detach --wait --wait-timeout 180 api worker mcp web >/dev/null
trap - EXIT INT TERM

STACK_PROJECT_NAME="$project_name" STACK_ENV_FILE="$env_file" scripts/stack-check.sh
echo "Local restore completed from $restore_dir"
