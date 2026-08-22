#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

test -f compose.yaml || {
  echo "Missing compose.yaml"
  exit 1
}

for pattern in \
  '!packages/' \
  '!packages/platform-core/' \
  '!packages/platform-core/pyproject.toml' \
  '!packages/platform-core/src/' \
  '!packages/platform-core/src/**'; do
  grep -Fqx -- "$pattern" .dockerignore || {
    echo ".dockerignore must include shared platform build context: $pattern"
    exit 1
  }
done

for dockerfile in apps/api/Dockerfile apps/worker/Dockerfile apps/mcp/Dockerfile; do
  grep -q 'COPY packages/platform-core/pyproject.toml packages/platform-core/pyproject.toml' \
    "$dockerfile" || {
    echo "$dockerfile must install the shared platform package metadata"
    exit 1
  }
  grep -q 'COPY packages/platform-core/src packages/platform-core/src' "$dockerfile" || {
    echo "$dockerfile must install the shared platform package source"
    exit 1
  }
done

env_file=$(mktemp)
config_file=$(mktemp)
json_file=$(mktemp)
profile_json_file=$(mktemp)
cleanup() {
  rm -f "$env_file" "$config_file" "$json_file" "$profile_json_file"
}
trap cleanup EXIT INT TERM

sed 's/change-me/test-only-value/g' .env.example >"$env_file"
STACK_ENV_FILE="$env_file" scripts/validate-stack-env.sh
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" config >"$config_file"
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" config --format json >"$json_file"
docker compose --project-name agreement-intelligence --profile local-model \
  --env-file "$env_file" config --format json >"$profile_json_file"

node - "$json_file" "$profile_json_file" <<'NODE'
const fs = require("node:fs");
const config = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const profileConfig = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

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

const localModel = profileConfig.services?.["llama-cpp"];
if (!localModel?.profiles?.includes("local-model")) {
  throw new Error("llama.cpp must remain behind the local-model profile");
}
if (!localModel?.image?.startsWith("ghcr.io/ggml-org/llama.cpp:server-")) {
  throw new Error("llama.cpp must use a pinned server image");
}
const modelMount = localModel?.volumes?.find((volume) => volume.target === "/models");
if (!modelMount || modelMount.read_only !== true || modelMount.type !== "bind") {
  throw new Error("llama.cpp must use a read-only user-supplied GGUF mount");
}
if ((localModel?.command ?? []).join(" ").includes("curl") || (localModel?.command ?? []).join(" ").includes("wget")) {
  throw new Error("llama.cpp must not download model weights during startup");
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

const localstackHealthcheck = localstack?.healthcheck?.test?.join(" ") ?? "";
for (const expectedState of ["available", "running"]) {
  if (!localstackHealthcheck.includes(expectedState)) {
    throw new Error(`LocalStack healthcheck must accept the ${expectedState} service state`);
  }
}

for (const [serviceName, expected] of Object.entries({
  api: [
    "APPLICATION_LOG_RETENTION_DAYS",
    "AUDIT_RETENTION_DAYS",
    "SQS_PROCESSING_QUEUE",
    "OIDC_ISSUER",
    "OIDC_INTERNAL_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "KEYCLOAK_SERVER_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME",
    "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD",
    "DEMO_REVIEWER_SUBJECT",
    "TELEMETRY_RETENTION_DAYS",
  ],
  web: ["API_ORGANIZATION_ID", "API_WORKSPACE_ID"],
  worker: [
    "APPLICATION_LOG_RETENTION_DAYS",
    "AUDIT_RETENTION_DAYS",
    "SQS_PROCESSING_QUEUE",
    "EMBEDDING_FALLBACK_MODEL",
    "TELEMETRY_RETENTION_DAYS",
  ],
  mcp: [
    "APPLICATION_LOG_RETENTION_DAYS",
    "AUDIT_RETENTION_DAYS",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "TELEMETRY_RETENTION_DAYS",
  ],
  "keycloak-bootstrap": ["DEMO_REVIEWER_SUBJECT"],
})) {
  const environment = config.services?.[serviceName]?.environment ?? {};
  for (const key of expected) {
    if (!Object.hasOwn(environment, key)) {
      throw new Error(`${serviceName} must receive ${key} for the local repository demo`);
    }
  }
}

const apiCommand = config.services?.api?.command?.join(" ") ?? "";
if (!apiCommand.includes("python -m agreement_intelligence_api.identity.local_demo")) {
  throw new Error("API startup must explicitly provision local demo identities");
}

const expectedRunningServices = [
  "api",
  "keycloak",
  "localstack",
  "mcp",
  "otel-collector",
  "postgres",
  "redis",
  "web",
  "worker",
];
for (const serviceName of expectedRunningServices) {
  if (!config.services?.[serviceName]) {
    throw new Error(`Stack topology is missing ${serviceName}`);
  }
}

if (!config.services?.redis?.healthcheck?.test?.length) {
  throw new Error("Redis must provide a Docker health check");
}

if (config.services?.["otel-collector"]?.healthcheck) {
  throw new Error("OpenTelemetry Collector must be checked as running, not through a Docker health check");
}
NODE

grep -q '^name: agreement-intelligence$' "$config_file"
! grep -q 'container_name:' compose.yaml

stack_check_services=$(awk '
  /^expected_running=/ { collecting = 1 }
  collecting { print }
  collecting && /'"'"'$/ { exit }
' scripts/stack-check.sh | sed "s/^expected_running='//; s/'$//")
for service in api keycloak localstack mcp otel-collector postgres redis web worker; do
  printf '%s\n' "$stack_check_services" | grep -qx "$service" || {
    echo "stack-check must account for the running $service service"
    exit 1
  }
done

for service in mcp redis; do
  grep -Eq "for service in .*\\b$service\\b" scripts/stack-check.sh || {
    echo "stack-check must verify $service Docker health"
    exit 1
  }
done

grep -q 'otel-collector is not running' scripts/stack-check.sh || {
  echo "stack-check must verify that the OpenTelemetry Collector is running"
  exit 1
}

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
  's/AUDIT_RETENTION_DAYS=2555/AUDIT_RETENTION_DAYS=0/' \
  's/TELEMETRY_RETENTION_DAYS=30/TELEMETRY_RETENTION_DAYS=-1/' \
  's/APPLICATION_LOG_RETENTION_DAYS=14/APPLICATION_LOG_RETENTION_DAYS=not-a-number/'; do
  sed "$replacement" "$env_file" >"$config_file"
  if STACK_ENV_FILE="$config_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
    echo "Invalid retention unexpectedly passed: $replacement"
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
