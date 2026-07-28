#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

env_file=$(mktemp)
bootstrap_log=$(mktemp)
project_name="agreement-intelligence-bootstrap-test-$$"
cleanup() {
  docker compose --project-name "$project_name" \
    --env-file "$env_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file" "$bootstrap_log"
}
trap cleanup EXIT INT TERM

sed 's/change-me/test-only-value/g' .env.example >"$env_file"
compose() {
  docker compose --project-name "$project_name" \
    --env-file "$env_file" "$@"
}

for script in \
  docker/localstack/bootstrap.sh \
  docker/keycloak/bootstrap.sh; do
  test -x "$script" || {
    echo "Missing executable $script"
    exit 1
  }
done

test -f docker/keycloak/realm/agreement-intelligence-realm.json

for script in \
  docker/localstack/bootstrap.sh \
  docker/keycloak/bootstrap.sh; do
  for args in "" "invalid" "apply extra"; do
    # Invalid invocations must be rejected before any environment or network use.
    if "$script" $args >/dev/null 2>&1; then
      echo "$script unexpectedly accepted arguments: $args"
      exit 1
    fi
  done
done

compose config --services | grep -qx localstack-bootstrap
compose config --services | grep -qx keycloak-bootstrap

compose up --detach --wait postgres localstack keycloak
if ! compose up localstack-bootstrap keycloak-bootstrap \
  >"$bootstrap_log" 2>&1; then
  sed -n '1,240p' "$bootstrap_log"
  exit 1
fi

for prohibited in \
  test-only-value \
  local-admin \
  access_token; do
  if grep -Fq "$prohibited" "$bootstrap_log"; then
    echo "Bootstrap logs exposed prohibited credential material"
    exit 1
  fi
done

for service in localstack-bootstrap keycloak-bootstrap; do
  container_id=$(compose ps --all --quiet "$service")
  test -n "$container_id"
  test "$(docker inspect --format '{{.State.ExitCode}}' "$container_id")" -eq 0
done

compose run --rm --no-deps localstack-bootstrap verify
compose run --rm --no-deps keycloak-bootstrap verify

# A second complete apply must converge without duplicate-resource failures.
compose run --rm --no-deps localstack-bootstrap apply
compose run --rm --no-deps keycloak-bootstrap apply
compose run --rm --no-deps localstack-bootstrap verify
compose run --rm --no-deps keycloak-bootstrap verify
