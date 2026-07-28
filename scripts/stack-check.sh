#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

compose() {
  docker compose --project-name agreement-intelligence \
    --env-file "${STACK_ENV_FILE:-.env}" "$@"
}

expected_running='api
keycloak
localstack
postgres
web
worker'

actual_running=$(compose ps --services --status running | sort)
test "$actual_running" = "$expected_running" || {
  echo "Unexpected running services:"
  printf '%s\n' "$actual_running"
  exit 1
}

for service in web api worker postgres localstack keycloak; do
  container_id=$(compose ps --quiet "$service")
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
    "$container_id")
  test "$status" = healthy || {
    echo "$service is not healthy: $status"
    exit 1
  }
done

for service in localstack-bootstrap keycloak-bootstrap; do
  container_id=$(compose ps --all --quiet "$service")
  exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$container_id")
  test "$exit_code" -eq 0 || {
    echo "$service failed with exit code $exit_code"
    exit 1
  }
done

compose exec -T postgres sh -c \
  'PGPASSWORD="$APP_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --tuples-only \
    --command "SELECT extversion FROM pg_extension WHERE extname = '\''vector'\'';"' \
  | grep -Eq '[0-9]+\.[0-9]+'

compose exec -T postgres sh -c \
  'PGPASSWORD="$KEYCLOAK_DB_PASSWORD" psql \
    --host 127.0.0.1 \
    --username "$KEYCLOAK_DB_USER" \
    --dbname "$KEYCLOAK_DB_NAME" \
    --tuples-only \
    --command "SELECT 1;"' \
  | grep -Eq '1'

compose run --rm --no-deps localstack-bootstrap verify
compose run --rm --no-deps keycloak-bootstrap verify

compose exec -T api python - <<'PY'
import json
from importlib.metadata import version
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8000/health/live", timeout=2) as response:
    payload = json.load(response)

assert payload == {
    "status": "ok",
    "service": "api",
    "version": version("agreement-intelligence-api"),
}

with urlopen("http://127.0.0.1:8000/docs", timeout=2) as response:
    assert response.status == 200
    assert "swagger-ui" in response.read().decode().lower()

with urlopen("http://127.0.0.1:8000/openapi.json", timeout=2) as response:
    schema = json.load(response)

assert "/health/live" in schema["paths"]
PY

compose exec -T web node -e "
fetch('http://127.0.0.1:3000')
  .then(async response => {
    const body = await response.text();
    if (!response.ok || !body.includes('API connected')) process.exit(1);
  })
  .catch(() => process.exit(1));
"

compose logs worker | grep -q '"event":"worker.started"'
echo "Agreement Intelligence stack is healthy."
