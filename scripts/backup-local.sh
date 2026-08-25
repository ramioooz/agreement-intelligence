#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

env_file=${STACK_ENV_FILE:-.env}
project_name=${STACK_PROJECT_NAME:-agreement-intelligence}
backup_dir=${BACKUP_DIR:-}

test -n "$backup_dir" || {
  echo "BACKUP_DIR must name the backup destination."
  exit 1
}
test -f "$env_file" || {
  echo "Missing stack environment file: $env_file"
  exit 1
}

case "$backup_dir" in
  /*) destination=$backup_dir ;;
  *) destination="$project_root/$backup_dir" ;;
esac

case "$destination" in
  "$project_root"/artifacts/backups/* | /private/tmp/* | /tmp/* | /var/folders/*) ;;
  *)
    echo "BACKUP_DIR must be under artifacts/backups or the operating-system temporary directory."
    exit 1
    ;;
esac

test ! -e "$destination" || {
  echo "Refusing to overwrite existing backup: $destination"
  exit 1
}

staging="${destination}.partial.$$"
cleanup() {
  rm -rf "$staging"
}
trap cleanup EXIT INT TERM
mkdir -p "$staging/objects"
chmod 700 "$staging"

compose() {
  docker compose --project-name "$project_name" --env-file "$env_file" "$@"
}

checksum_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1"
  else
    shasum -a 256 "$1"
  fi
}

compose exec -T postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --host 127.0.0.1 \
    --username postgres --dbname "$APP_DB_NAME" --format=custom \
    --no-privileges' >"$staging/postgres.dump"

alembic_version=$(compose exec -T postgres sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql --host 127.0.0.1 \
    --username postgres --dbname "$APP_DB_NAME" --tuples-only --no-align \
    --command "SELECT version_num FROM alembic_version LIMIT 1;"' | tr -d '\r')

compose run --rm --no-deps --entrypoint sh \
  --volume "$staging/objects:/backup-objects" localstack-bootstrap -c \
  'awslocal --endpoint-url http://localstack:4566 s3 sync \
    "s3://$S3_DOCUMENT_BUCKET" /backup-objects --only-show-errors'

(cd "$staging/objects" && COPYFILE_DISABLE=1 tar --no-xattrs -cf ../objects.tar .)
rm -rf "$staging/objects"

database_name=$(sed -n 's/^APP_DB_NAME=//p' "$env_file" | tail -n 1)
bucket_name=$(sed -n 's/^S3_DOCUMENT_BUCKET=//p' "$env_file" | tail -n 1)
region=$(sed -n 's/^AWS_REGION=//p' "$env_file" | tail -n 1)
created_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

python3 - "$staging/manifest.json" "$staging/objects.tar" "$created_at" \
  "$database_name" "$alembic_version" "$bucket_name" "$region" <<'PY'
import json
import sys
import tarfile

path, objects_archive, created_at, database, alembic_version, bucket, region = sys.argv[1:]
with tarfile.open(objects_archive) as archive:
    object_keys = sorted(
        member.name.removeprefix("./")
        for member in archive.getmembers()
        if member.isfile()
    )
manifest = {
    "format_version": 1,
    "created_at": created_at,
    "database": {"name": database, "alembic_version": alembic_version},
    "object_store": {
        "bucket": bucket,
        "region": region,
        "object_count": len(object_keys),
        "object_keys": object_keys,
    },
    "included": ["postgres.dump", "objects.tar"],
    "excluded": ["environment files", "credentials", "access tokens", "model prompts"],
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

(
  cd "$staging"
  checksum_file postgres.dump
  checksum_file objects.tar
  checksum_file manifest.json
) >"$staging/SHA256SUMS"
chmod 600 "$staging"/*
mkdir -p "$(dirname -- "$destination")"
mv "$staging" "$destination"
trap - EXIT INT TERM
echo "Local backup created at $destination"
