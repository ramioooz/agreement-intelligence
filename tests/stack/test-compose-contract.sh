#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

test -f compose.yaml || {
  echo "Missing compose.yaml"
  exit 1
}

env_file=$(mktemp)
config_file=$(mktemp)
json_file=$(mktemp)
cleanup() {
  rm -f "$env_file" "$config_file" "$json_file"
}
trap cleanup EXIT INT TERM

sed 's/change-me/test-only-value/g' .env.example >"$env_file"
STACK_ENV_FILE="$env_file" scripts/validate-stack-env.sh
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" config >"$config_file"
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" config --format json >"$json_file"

node - "$json_file" <<'NODE'
const fs = require("node:fs");
const config = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

for (const serviceName of ["postgres", "localstack", "keycloak"]) {
  if (!config.services?.[serviceName]?.healthcheck?.test?.length) {
    throw new Error(`Missing health check for ${serviceName}`);
  }
}

if (config.services?.keycloak?.depends_on?.postgres?.condition !== "service_healthy") {
  throw new Error("Keycloak must wait for a healthy PostgreSQL service");
}

const workerHealthcheck = config.services?.worker?.healthcheck?.test?.join(" ") ?? "";
if (workerHealthcheck.includes("kill -0 1")) {
  throw new Error("Worker Compose healthcheck must not replace the image heartbeat check");
}

if (!config.volumes?.["postgres-data"]) {
  throw new Error("Missing named PostgreSQL volume");
}

if (!config.services?.postgres?.volumes?.some(
  (volume) => volume.type === "volume" && volume.source === "postgres-data",
)) {
  throw new Error("PostgreSQL must retain its named data volume");
}

const localstack = config.services?.localstack;
if (localstack?.image !== "localstack/localstack:4.14.0") {
  throw new Error("LocalStack must use the portable community image pin");
}

if (Object.hasOwn(localstack?.environment ?? {}, "ACTIVATE_PRO")) {
  throw new Error("LocalStack community image must not enable licensed activation");
}

if (Object.hasOwn(localstack?.environment ?? {}, "PERSISTENCE")) {
  throw new Error("LocalStack must run without licensed persistence");
}

if (localstack?.volumes?.some((volume) => volume.target === "/var/lib/localstack")) {
  throw new Error("LocalStack must not mount a durable data volume");
}

if (config.volumes?.["localstack-data"]) {
  throw new Error("LocalStack data volume must not be defined");
}
NODE

grep -q '^name: agreement-intelligence$' "$config_file"
! grep -q 'container_name:' compose.yaml

for service in postgres localstack keycloak; do
  docker compose --project-name agreement-intelligence \
    --env-file "$env_file" config --services \
    | grep -qx "$service"
done

grep -q 'pgvector/pgvector:0.8.5-pg17-bookworm' "$config_file"
grep -q 'localstack/localstack:4.14.0' "$config_file"
grep -q 'quay.io/keycloak/keycloak:26.7.0' "$config_file"
awk '
  /host_ip:/ {
    host_ip=$2
    gsub(/"/, "", host_ip)
    count += 1
    if (host_ip != "127.0.0.1") exit 1
  }
  END { if (count == 0) exit 1 }
' "$config_file"

if grep -Eq 'image: .*(latest|stable)([[:space:]]|$)' "$config_file"; then
  echo "Floating image tag found"
  exit 1
fi

for replacement in \
  's/API_PORT=8000/API_PORT=0/' \
  's/API_PORT=8000/API_PORT=70000/' \
  's/API_PORT=8000/API_PORT=not-a-port/' \
  's/API_PORT=8000/API_PORT=3000/' \
  's/APP_DB_PASSWORD=test-only-value/APP_DB_PASSWORD=unsafe@password/'; do
  sed "$replacement" "$env_file" >"$config_file"
  if STACK_ENV_FILE="$config_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
    echo "Invalid environment unexpectedly passed: $replacement"
    exit 1
  fi
done

for replacement in \
  's/KEYCLOAK_DB_NAME=keycloak/KEYCLOAK_DB_NAME=agreement_intelligence/' \
  's/KEYCLOAK_DB_USER=keycloak/KEYCLOAK_DB_USER=agreement_app/' \
  's/APP_DB_NAME=agreement_intelligence/APP_DB_NAME=postgres/' \
  's/KEYCLOAK_DB_NAME=keycloak/KEYCLOAK_DB_NAME=postgres/' \
  's/APP_DB_NAME=agreement_intelligence/APP_DB_NAME=template0/' \
  's/APP_DB_NAME=agreement_intelligence/APP_DB_NAME=template1/' \
  's/KEYCLOAK_DB_NAME=keycloak/KEYCLOAK_DB_NAME=template0/' \
  's/KEYCLOAK_DB_NAME=keycloak/KEYCLOAK_DB_NAME=template1/' \
  's/APP_DB_USER=agreement_app/APP_DB_USER=postgres/' \
  's/KEYCLOAK_DB_USER=keycloak/KEYCLOAK_DB_USER=postgres/'; do
  sed "$replacement" "$env_file" >"$config_file"
  if STACK_ENV_FILE="$config_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
    echo "Unsafe database identity unexpectedly passed: $replacement"
    exit 1
  fi
done

if APP_DB_NAME=postgres STACK_ENV_FILE="$env_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
  echo "Reserved database name exported override unexpectedly passed"
  exit 1
fi

if API_PORT=0 STACK_ENV_FILE="$env_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
  echo "Invalid port exported override unexpectedly passed"
  exit 1
fi

if APP_DB_PASSWORD=unsafe@password STACK_ENV_FILE="$env_file" \
  scripts/validate-stack-env.sh >/dev/null 2>&1; then
  echo "Unsafe password exported override unexpectedly passed"
  exit 1
fi

if APP_DB_NAME= STACK_ENV_FILE="$env_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
  echo "Empty database name exported override unexpectedly passed"
  exit 1
fi

cp "$env_file" "$config_file"
printf '%s\n' 'COMPOSE_PROJECT_NAME=another-project' >>"$config_file"
if STACK_ENV_FILE="$config_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
  echo "Conflicting Compose project name unexpectedly passed"
  exit 1
fi
