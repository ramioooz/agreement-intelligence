# Containerized Local Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one portable Docker Compose runtime that builds, starts,
bootstraps, verifies, and safely resets the complete Agreement Intelligence
application and its local dependencies.

**Architecture:** Docker Compose owns the only application runtime path and
groups every resource under the `agreement-intelligence` project. Multi-stage,
non-root web, API, and worker images depend on health-checked PostgreSQL,
LocalStack, and Keycloak services; one-shot bootstrap services converge AWS and
identity resources before the applications start.

**Tech Stack:** Docker Engine 29+, Docker Compose 2.24+, GNU Make, Node.js
22.23.1, pnpm 10.28.0, Next.js 16.2.12, Python 3.13.14, uv 0.11.32,
PostgreSQL 17 with pgvector 0.8.5, LocalStack 4.14.0, and Keycloak 26.7.0.

## Global Constraints

- The Compose project name is exactly `agreement-intelligence`.
- Do not use `container_name`.
- Docker Compose is the only supported application runtime path.
- Bind published ports only to `127.0.0.1`.
- Use exact image tags; do not use `latest`, `stable`, or major-only tags.
- Application containers run as non-root users with no new privileges.
- LocalStack 4.14.0 provides both S3 and SQS without paid features, activation
  tokens, or a Docker socket. This final upstream open-source release replaces
  the later calendar baseline, which required license activation at runtime.
- LocalStack is ephemeral; bootstrap recreates its S3 and SQS resources
  idempotently on every local stack start. Production AWS S3 and SQS provide
  deployed-workload durability.
- Keycloak imports version-controlled non-secret configuration.
- Demo users and all credentials come from ignored environment configuration.
- Normal shutdown preserves the PostgreSQL named volume and its Keycloak data.
- Destructive reset requires `CONFIRM=reset`.
- Support Linux ARM64 and Linux AMD64 images.
- Keep authentication integration, business migrations, queue consumption,
  telemetry, and AWS provisioning out of this story.
- Every task is implemented on a dedicated branch and delivered through a
  ready-for-review pull request targeting `main`.
- Tasks execute sequentially. Start Task N only after the repository owner
  merges Task N-1; update local `main`, then branch from that merged state.
- Only the repository owner merges to `main`.
- Do not include assistant, vendor, or model-provider branding in branches,
  commits, pull requests, code, or delivery metadata.

## Planned file map

```text
.
├── .dockerignore
├── .env.example
├── .gitignore
├── Makefile
├── README.md
├── compose.yaml
├── package.json
├── pnpm-lock.yaml
├── apps/
│   ├── api/Dockerfile
│   ├── web/
│   │   ├── Dockerfile
│   │   └── next.config.ts
│   └── worker/Dockerfile
├── docker/
│   ├── keycloak/
│   │   ├── bootstrap.sh
│   │   └── realm/agreement-intelligence-realm.json
│   ├── localstack/bootstrap.sh
│   └── postgres/init-databases.sh
├── scripts/
│   ├── stack-check.sh
│   └── validate-stack-env.sh
└── tests/stack/
    ├── test-application-images.sh
    ├── test-bootstrap-contracts.sh
    ├── test-compose-contract.sh
    └── test-stack-lifecycle.sh
```

---

### Task 1: Package the web, API, and worker as production-style images

**Files:**

- Create: `.dockerignore`
- Create: `apps/web/Dockerfile`
- Create: `apps/api/Dockerfile`
- Create: `apps/worker/Dockerfile`
- Create: `tests/stack/test-application-images.sh`
- Modify: `apps/web/next.config.ts`

**Interfaces:**

- Consumes: root pnpm and uv lockfiles; existing web, API, and worker entry
  points.
- Produces: images `agreement-intelligence-web:test`,
  `agreement-intelligence-api:test`, and
  `agreement-intelligence-worker:test`; web standalone server at
  `apps/web/server.js`; API on port `8000`; worker as a signal-aware PID 1.

**Branch:** After updating local `main`, create
`feat/application-container-images`. This task closes #77 and references #3.

- [ ] **Step 1: Add the failing image contract**

Create `tests/stack/test-application-images.sh`:

```sh
#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

for service in web api worker; do
  dockerfile="apps/$service/Dockerfile"
  test -f "$dockerfile" || {
    echo "Missing $dockerfile"
    exit 1
  }

  docker build \
    --file "$dockerfile" \
    --tag "agreement-intelligence-$service:test" \
    .

  uid=$(docker run --rm \
    --entrypoint sh \
    "agreement-intelligence-$service:test" \
    -c 'id -u')
  test "$uid" -ne 0 || {
    echo "$service image runs as root"
    exit 1
  }
done

api_id=$(docker run --detach --publish 127.0.0.1::8000 \
  agreement-intelligence-api:test)
worker_id=$(docker run --detach agreement-intelligence-worker:test)
web_id=$(docker run --detach \
  --env API_BASE_URL=http://127.0.0.1:9 \
  --publish 127.0.0.1::3000 \
  agreement-intelligence-web:test)

cleanup() {
  docker stop "$web_id" "$worker_id" "$api_id" >/dev/null 2>&1 || true
  docker rm "$web_id" "$worker_id" "$api_id" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

api_port=$(docker port "$api_id" 8000/tcp | awk -F: 'NR == 1 {print $NF}')
web_port=$(docker port "$web_id" 3000/tcp | awk -F: 'NR == 1 {print $NF}')

attempt=0
until curl --fail --silent "http://127.0.0.1:$api_port/health/live" \
  | grep -q '"status":"ok"'; do
  attempt=$((attempt + 1))
  test "$attempt" -lt 30 || {
    docker logs "$api_id"
    exit 1
  }
  sleep 1
done

attempt=0
until curl --fail --silent "http://127.0.0.1:$web_port/" \
  | grep -q 'Agreement Intelligence'; do
  attempt=$((attempt + 1))
  test "$attempt" -lt 30 || {
    docker logs "$web_id"
    exit 1
  }
  sleep 1
done

docker logs "$worker_id" | grep -q '"event":"worker.started"'
docker stop --time 10 "$worker_id" >/dev/null
docker logs "$worker_id" | grep -q '"event":"worker.stopped"'
```

Make it executable:

```bash
chmod +x tests/stack/test-application-images.sh
```

- [ ] **Step 2: Run the contract and confirm the expected failure**

Run:

```bash
tests/stack/test-application-images.sh
```

Expected: exit `1` with `Missing apps/web/Dockerfile`.

- [ ] **Step 3: Configure Next.js standalone output**

Replace `apps/web/next.config.ts` with:

```ts
import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(process.cwd(), "../.."),
};

export default nextConfig;
```

- [ ] **Step 4: Exclude local and sensitive files from build contexts**

Create `.dockerignore`:

```text
.git
.gitignore
.DS_Store
.env
.env.*
!.env.example
.venv
**/.venv
node_modules
**/node_modules
.next
**/.next
dist
**/dist
coverage
**/coverage
.pytest_cache
**/.pytest_cache
.mypy_cache
**/.mypy_cache
.ruff_cache
**/.ruff_cache
*.pyc
__pycache__
**/__pycache__
docs
.idea
.vscode
```

- [ ] **Step 5: Add the web image**

Create `apps/web/Dockerfile`:

```dockerfile
FROM node:22.23.1-bookworm-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable \
    && corepack prepare pnpm@10.28.0 --activate
WORKDIR /workspace

FROM base AS dependencies
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter @agreement-intelligence/web...

FROM dependencies AS build
COPY apps/web apps/web
RUN pnpm --filter @agreement-intelligence/web build

FROM node:22.23.1-bookworm-slim AS runtime
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node \
    /workspace/apps/web/.next/standalone ./
COPY --from=build --chown=node:node \
    /workspace/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
```

- [ ] **Step 6: Add the API image**

Create `apps/api/Dockerfile`:

```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.13.14-slim-bookworm AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
      --frozen \
      --no-dev \
      --no-editable \
      --package agreement-intelligence-api

FROM python:3.13.14-slim-bookworm AS runtime
ENV PATH=/workspace/.venv/bin:$PATH
ENV PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /workspace
COPY --from=build --chown=app:app /workspace/.venv /workspace/.venv
USER app
EXPOSE 8000
CMD ["uvicorn", "agreement_intelligence_api.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: Add the worker image**

Create `apps/worker/Dockerfile`:

```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.13.14-slim-bookworm AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
      --frozen \
      --no-dev \
      --no-editable \
      --package agreement-intelligence-worker

FROM python:3.13.14-slim-bookworm AS runtime
ENV PATH=/workspace/.venv/bin:$PATH
ENV PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /workspace
COPY --from=build --chown=app:app /workspace/.venv /workspace/.venv
USER app
CMD ["agreement-worker"]
```

- [ ] **Step 8: Run the image contract**

Run:

```bash
tests/stack/test-application-images.sh
```

Expected:

- all three images build;
- all runtime UIDs are non-zero;
- API liveness returns the expected contract;
- the web page renders;
- the worker logs start and stop events; and
- the script exits `0`.

- [ ] **Step 9: Run existing source-quality checks**

Run:

```bash
make check
git diff --check
```

Expected: both commands pass.

- [ ] **Step 10: Commit the image packaging**

```bash
git add \
  .dockerignore \
  apps/web/Dockerfile \
  apps/web/next.config.ts \
  apps/api/Dockerfile \
  apps/worker/Dockerfile \
  tests/stack/test-application-images.sh
git commit -m "build: package application containers"
```

- [ ] **Step 11: Publish the Task 1 review**

```bash
git push --set-upstream origin feat/application-container-images
gh pr create \
  --base main \
  --head feat/application-container-images \
  --title "Package application container images" \
  --body $'## Summary\n\n- package the web, API, and worker as pinned multi-stage images\n- run application processes as non-root users\n- add executable container contracts\n\n## Verification\n\n- make check\n- tests/stack/test-application-images.sh\n\nCloses #77\nRefs #3\n\nOnly the repository owner merges this pull request.'
```

Stop after the ready-for-review pull request is open. Task 2 starts only after
the repository owner merges it.

---

### Task 2: Define the health-checked core platform

**Files:**

- Create: `.env.example`
- Create: `compose.yaml`
- Create: `docker/postgres/init-databases.sh`
- Create: `scripts/validate-stack-env.sh`
- Create: `tests/stack/test-compose-contract.sh`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: exact image baselines from the approved design.
- Produces: Compose project `agreement-intelligence`; services `postgres`,
  `localstack`, and `keycloak`; persistent volume `postgres-data`; ephemeral
  LocalStack resources; `scripts/validate-stack-env.sh [ENV_FILE]`.

**Branch:** After Task 1 is merged and local `main` is updated, create
`feat/core-platform-services`. This task closes #78 and references #3.

- [ ] **Step 1: Add the failing Compose contract**

Create `tests/stack/test-compose-contract.sh`:

```sh
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
cleanup() {
  rm -f "$env_file" "$config_file"
}
trap cleanup EXIT INT TERM

sed 's/change-me/test-only-value/g' .env.example >"$env_file"
STACK_ENV_FILE="$env_file" scripts/validate-stack-env.sh
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" config >"$config_file"

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

cp "$env_file" "$config_file"
printf '%s\n' 'COMPOSE_PROJECT_NAME=another-project' >>"$config_file"
if STACK_ENV_FILE="$config_file" scripts/validate-stack-env.sh >/dev/null 2>&1; then
  echo "Conflicting Compose project name unexpectedly passed"
  exit 1
fi
```

Make it executable:

```bash
chmod +x tests/stack/test-compose-contract.sh
```

- [ ] **Step 2: Run the contract and confirm the expected failure**

Run:

```bash
tests/stack/test-compose-contract.sh
```

Expected: exit `1` with `Missing compose.yaml`.

- [ ] **Step 3: Define the safe environment template**

Create `.env.example`:

```dotenv
# Copy this file to .env and replace every change-me value.

POSTGRES_PORT=5432
POSTGRES_PASSWORD=change-me-postgres-password

APP_DB_NAME=agreement_intelligence
APP_DB_USER=agreement_app
APP_DB_PASSWORD=change-me-application-database-password

KEYCLOAK_PORT=8080
KEYCLOAK_DB_NAME=keycloak
KEYCLOAK_DB_USER=keycloak
KEYCLOAK_DB_PASSWORD=change-me-keycloak-database-password
KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=local-admin
KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD=change-me-keycloak-admin-password
KEYCLOAK_REALM=agreement-intelligence
OIDC_CLIENT_ID=agreement-intelligence-web
OIDC_CLIENT_SECRET=change-me-oidc-client-secret

DEMO_REVIEWER_USERNAME=legal.reviewer
DEMO_REVIEWER_EMAIL=legal.reviewer@example.test
DEMO_REVIEWER_FIRST_NAME=Legal
DEMO_REVIEWER_LAST_NAME=Reviewer
DEMO_REVIEWER_PASSWORD=change-me-reviewer-password
DEMO_ADMIN_USERNAME=platform.admin
DEMO_ADMIN_EMAIL=platform.admin@example.test
DEMO_ADMIN_FIRST_NAME=Platform
DEMO_ADMIN_LAST_NAME=Administrator
DEMO_ADMIN_PASSWORD=change-me-admin-password

LOCALSTACK_PORT=4566
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
S3_DOCUMENT_BUCKET=agreement-intelligence-documents
SQS_PROCESSING_QUEUE=agreement-intelligence-agreement-processing
SQS_PROCESSING_DLQ=agreement-intelligence-agreement-processing-dlq
SQS_EXPORT_QUEUE=agreement-intelligence-exports
SQS_EXPORT_DLQ=agreement-intelligence-exports-dlq
SQS_NOTIFICATION_QUEUE=agreement-intelligence-notifications
SQS_NOTIFICATION_DLQ=agreement-intelligence-notifications-dlq

WEB_PORT=3000
API_PORT=8000
```

- [ ] **Step 4: Validate configuration before Compose starts**

Create `scripts/validate-stack-env.sh`:

```sh
#!/bin/sh
set -eu

env_file=${1:-${STACK_ENV_FILE:-.env}}

test -f "$env_file" || {
  echo "Missing $env_file. Copy .env.example to .env and replace placeholders."
  exit 1
}

if test -n "${COMPOSE_PROJECT_NAME:-}" \
  && test "$COMPOSE_PROJECT_NAME" != agreement-intelligence; then
  echo "COMPOSE_PROJECT_NAME must be agreement-intelligence when set."
  exit 1
fi
file_project_name=$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' "$env_file" | tail -n 1)
if test -n "$file_project_name" \
  && test "$file_project_name" != agreement-intelligence; then
  echo "COMPOSE_PROJECT_NAME in $env_file must be agreement-intelligence."
  exit 1
fi

required_variables='
POSTGRES_PASSWORD
APP_DB_NAME
APP_DB_USER
APP_DB_PASSWORD
KEYCLOAK_DB_NAME
KEYCLOAK_DB_USER
KEYCLOAK_DB_PASSWORD
KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME
KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD
KEYCLOAK_REALM
OIDC_CLIENT_ID
OIDC_CLIENT_SECRET
DEMO_REVIEWER_USERNAME
DEMO_REVIEWER_EMAIL
DEMO_REVIEWER_FIRST_NAME
DEMO_REVIEWER_LAST_NAME
DEMO_REVIEWER_PASSWORD
DEMO_ADMIN_USERNAME
DEMO_ADMIN_EMAIL
DEMO_ADMIN_FIRST_NAME
DEMO_ADMIN_LAST_NAME
DEMO_ADMIN_PASSWORD
AWS_REGION
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
S3_DOCUMENT_BUCKET
SQS_PROCESSING_QUEUE
SQS_PROCESSING_DLQ
SQS_EXPORT_QUEUE
SQS_EXPORT_DLQ
SQS_NOTIFICATION_QUEUE
SQS_NOTIFICATION_DLQ
POSTGRES_PORT
KEYCLOAK_PORT
LOCALSTACK_PORT
WEB_PORT
API_PORT
'

for variable in $required_variables; do
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
  test -n "$value" || {
    echo "Missing required value: $variable"
    exit 1
  }
  case "$value" in
    *change-me*)
      echo "Replace placeholder value: $variable"
      exit 1
      ;;
  esac
done

for variable in APP_DB_NAME APP_DB_USER KEYCLOAK_DB_NAME KEYCLOAK_DB_USER; do
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
  printf '%s\n' "$value" | grep -Eq '^[a-z][a-z0-9_]*$' || {
    echo "$variable must use lowercase letters, digits, and underscores."
    exit 1
  }
done

port_variables='POSTGRES_PORT KEYCLOAK_PORT LOCALSTACK_PORT WEB_PORT API_PORT'
ports=
for variable in $port_variables; do
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
  printf '%s\n' "$value" | grep -Eq '^[0-9]+$' || {
    echo "$variable must be an integer from 1 through 65535."
    exit 1
  }
  test "$value" -ge 1 && test "$value" -le 65535 || {
    echo "$variable must be an integer from 1 through 65535."
    exit 1
  }
  ports="${ports}${value}
"
done

test "$(printf '%s\n' "$ports" | sort | uniq -d | wc -l | tr -d ' ')" -eq 0 || {
  echo "Local ports must be unique."
  exit 1
}

for variable in APP_DB_PASSWORD KEYCLOAK_DB_PASSWORD; do
  value=$(sed -n "s/^${variable}=//p" "$env_file" | tail -n 1)
  printf '%s\n' "$value" | grep -Eq '^[A-Za-z0-9._~-]+$' || {
    echo "$variable must contain only URI-safe letters, digits, ., _, ~, and -."
    exit 1
  }
done
```

Make it executable:

```bash
chmod +x scripts/validate-stack-env.sh
```

- [ ] **Step 5: Initialize PostgreSQL databases and pgvector**

Create `docker/postgres/init-databases.sh`:

```sh
#!/bin/sh
set -eu

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_db="$APP_DB_NAME" \
  --set=app_user="$APP_DB_USER" \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=keycloak_db="$KEYCLOAK_DB_NAME" \
  --set=keycloak_user="$KEYCLOAK_DB_USER" \
  --set=keycloak_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L',
  :'keycloak_user',
  :'keycloak_password'
)
WHERE NOT EXISTS (
  SELECT FROM pg_roles WHERE rolname = :'keycloak_user'
) \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_db') \gexec

SELECT format(
  'CREATE DATABASE %I OWNER %I',
  :'keycloak_db',
  :'keycloak_user'
)
WHERE NOT EXISTS (
  SELECT FROM pg_database WHERE datname = :'keycloak_db'
) \gexec
SQL

psql \
  --username "$POSTGRES_USER" \
  --dbname "$APP_DB_NAME" \
  --command 'CREATE EXTENSION IF NOT EXISTS vector;'
```

Make it executable:

```bash
chmod +x docker/postgres/init-databases.sh
```

- [ ] **Step 6: Define the core Compose platform**

Create `compose.yaml`:

```yaml
name: agreement-intelligence

services:
  postgres:
    image: pgvector/pgvector:0.8.5-pg17-bookworm
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?required}
      APP_DB_NAME: ${APP_DB_NAME:?required}
      APP_DB_USER: ${APP_DB_USER:?required}
      APP_DB_PASSWORD: ${APP_DB_PASSWORD:?required}
      KEYCLOAK_DB_NAME: ${KEYCLOAK_DB_NAME:?required}
      KEYCLOAK_DB_USER: ${KEYCLOAK_DB_USER:?required}
      KEYCLOAK_DB_PASSWORD: ${KEYCLOAK_DB_PASSWORD:?required}
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./docker/postgres/init-databases.sh:/docker-entrypoint-initdb.d/10-init-databases.sh:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 10s
    restart: unless-stopped

  localstack:
    image: localstack/localstack:4.14.0
    environment:
      SERVICES: s3,sqs
      AWS_DEFAULT_REGION: ${AWS_REGION:?required}
    ports:
      - "127.0.0.1:${LOCALSTACK_PORT:-4566}:4566"
    healthcheck:
      test:
        - CMD-SHELL
        - >-
          health="$$(curl --fail --silent
          http://127.0.0.1:4566/_localstack/health)"
          && printf '%s' "$$health" | grep -Eq '"s3":[[:space:]]*"available"'
          && printf '%s' "$$health" | grep -Eq '"sqs":[[:space:]]*"available"'
      interval: 5s
      timeout: 5s
      retries: 30
      start_period: 15s
    restart: unless-stopped

  keycloak:
    image: quay.io/keycloak/keycloak:26.7.0
    command: ["start-dev"]
    environment:
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/${KEYCLOAK_DB_NAME:?required}
      KC_DB_USERNAME: ${KEYCLOAK_DB_USER:?required}
      KC_DB_PASSWORD: ${KEYCLOAK_DB_PASSWORD:?required}
      KC_BOOTSTRAP_ADMIN_USERNAME: ${KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME:?required}
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD:?required}
      KC_HEALTH_ENABLED: "true"
      KC_HTTP_ENABLED: "true"
    ports:
      - "127.0.0.1:${KEYCLOAK_PORT:-8080}:8080"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test:
        - CMD-SHELL
        - >-
          exec 3<>/dev/tcp/127.0.0.1/9000;
          printf 'GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3;
          grep -q '200 OK' <&3
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 30s
    restart: unless-stopped

volumes:
  postgres-data:
```

- [ ] **Step 7: Explicitly ignore stack test environment files**

Append to `.gitignore`:

```text
.env.stack-test
```

- [ ] **Step 8: Run the static Compose contract**

Run:

```bash
tests/stack/test-compose-contract.sh
git diff --check
```

Expected: both commands pass.

- [ ] **Step 9: Start and inspect the core services**

Create a local `.env` without committing it:

```bash
cp .env.example .env
```

Replace every `change-me` value, then run:

```bash
scripts/validate-stack-env.sh
docker compose --project-name agreement-intelligence \
  up --detach --wait postgres localstack keycloak
docker compose --project-name agreement-intelligence ps
```

Expected:

- Docker Desktop groups all services under `agreement-intelligence`;
- `postgres`, `localstack`, and `keycloak` report healthy; and
- no service uses a hard-coded container name.

Stop while preserving volumes:

```bash
docker compose --project-name agreement-intelligence down
```

- [ ] **Step 10: Run source-quality checks**

```bash
make check
git status --short
```

Expected: `make check` passes and only intended task files are uncommitted.

- [ ] **Step 11: Commit the core platform**

```bash
git add \
  .env.example \
  .gitignore \
  compose.yaml \
  docker/postgres/init-databases.sh \
  scripts/validate-stack-env.sh \
  tests/stack/test-compose-contract.sh
git commit -m "feat(infra): add containerized platform services"
```

- [ ] **Step 12: Publish the Task 2 review**

```bash
git push --set-upstream origin feat/core-platform-services
gh pr create \
  --base main \
  --head feat/core-platform-services \
  --title "Define the health-checked core platform" \
  --body $'## Summary\n\n- define pinned PostgreSQL, LocalStack, and Keycloak services\n- validate safe local configuration before startup\n- add health, ephemeral LocalStack, and loopback-binding contracts\n\n## Verification\n\n- make check\n- tests/stack/test-compose-contract.sh\n\nCloses #78\nRefs #3\n\nOnly the repository owner merges this pull request.'
```

Stop after the ready-for-review pull request is open. Task 3 starts only after
the repository owner merges it.

---

### Task 3: Bootstrap LocalStack and Keycloak deterministically

**Files:**

- Create: `docker/localstack/bootstrap.sh`
- Create: `docker/keycloak/bootstrap.sh`
- Create: `docker/keycloak/ClientAttributes.java`
- Create: `docker/keycloak/realm/agreement-intelligence-realm.json`
- Create: `tests/stack/test-bootstrap-contracts.sh`
- Modify: `.env.example`
- Modify: `compose.yaml`
- Modify: `scripts/validate-stack-env.sh`

**Interfaces:**

- Consumes: healthy `localstack` and `keycloak` services plus the environment
  contract from Task 2.
- Produces: `localstack-bootstrap` and `keycloak-bootstrap` one-shot services;
  scripts accepting exactly `apply` or `verify`; private S3 bucket; three
  primary queues with DLQs and redrive policies; Keycloak realm, confidential
  web client, client secret, and two profile-complete seeded users whose
  configured passwords can be verified without enabling application-client
  direct grants.

**Branch:** After Task 2 is merged and local `main` is updated, create
`feat/platform-bootstrap`. This task closes #79 and references #3.

- [ ] **Step 1: Add the failing bootstrap contract**

Create `tests/stack/test-bootstrap-contracts.sh`:

```sh
#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$project_root"

env_file=$(mktemp)
cleanup() {
  docker compose --project-name agreement-intelligence \
    --env-file "$env_file" down --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file"
}
trap cleanup EXIT INT TERM

sed 's/change-me/test-only-value/g' .env.example >"$env_file"
compose() {
  docker compose --project-name agreement-intelligence \
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

compose config --services | grep -qx localstack-bootstrap
compose config --services | grep -qx keycloak-bootstrap

compose up --detach --wait postgres localstack keycloak
compose up localstack-bootstrap keycloak-bootstrap

for service in localstack-bootstrap keycloak-bootstrap; do
  container_id=$(compose ps --all --quiet "$service")
  test -n "$container_id"
  test "$(docker inspect --format '{{.State.ExitCode}}' "$container_id")" -eq 0
done

compose run --rm --no-deps localstack-bootstrap verify
compose run --rm --no-deps keycloak-bootstrap verify
```

Make it executable:

```bash
chmod +x tests/stack/test-bootstrap-contracts.sh
```

- [ ] **Step 2: Run the contract and confirm the expected failure**

Run:

```bash
tests/stack/test-bootstrap-contracts.sh
```

Expected: exit `1` with
`Missing executable docker/localstack/bootstrap.sh`.

- [ ] **Step 3: Define the non-secret Keycloak realm**

Create `docker/keycloak/realm/agreement-intelligence-realm.json`:

```json
{
  "realm": "agreement-intelligence",
  "enabled": true,
  "displayName": "Agreement Intelligence",
  "registrationAllowed": false,
  "resetPasswordAllowed": true,
  "rememberMe": false,
  "verifyEmail": false,
  "loginWithEmailAllowed": true,
  "duplicateEmailsAllowed": false,
  "clients": [
    {
      "clientId": "agreement-intelligence-web",
      "name": "Agreement Intelligence Web",
      "enabled": true,
      "protocol": "openid-connect",
      "clientAuthenticatorType": "client-secret",
      "publicClient": false,
      "standardFlowEnabled": true,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
      "redirectUris": [
        "http://localhost:3000/auth/callback"
      ],
      "webOrigins": [
        "http://localhost:3000"
      ],
      "attributes": {
        "post.logout.redirect.uris": "http://localhost:3000/*",
        "pkce.code.challenge.method": "S256"
      },
      "defaultClientScopes": [
        "web-origins",
        "acr",
        "roles",
        "profile",
        "email"
      ],
      "optionalClientScopes": [
        "address",
        "phone",
        "offline_access",
        "microprofile-jwt"
      ]
    }
  ]
}
```

Validate JSON:

```bash
python -m json.tool \
  docker/keycloak/realm/agreement-intelligence-realm.json \
  >/dev/null
```

- [ ] **Step 4: Add LocalStack apply and verify behavior**

Create `docker/localstack/bootstrap.sh`:

```sh
#!/bin/sh
set -eu

action=${1:-apply}
endpoint=${LOCALSTACK_ENDPOINT:-http://localstack:4566}

export AWS_DEFAULT_REGION=$AWS_REGION

aws_local() {
  awslocal --endpoint-url "$endpoint" "$@"
}

ensure_bucket() {
  if ! aws_local s3api head-bucket --bucket "$S3_DOCUMENT_BUCKET" \
    >/dev/null 2>&1; then
    aws_local s3api create-bucket --bucket "$S3_DOCUMENT_BUCKET" >/dev/null
  fi

  aws_local s3api put-public-access-block \
    --bucket "$S3_DOCUMENT_BUCKET" \
    --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
    >/dev/null
}

queue_url() {
  aws_local sqs get-queue-url \
    --queue-name "$1" \
    --query QueueUrl \
    --output text
}

ensure_queue() {
  aws_local sqs create-queue --queue-name "$1" >/dev/null
}

configure_redrive() {
  primary_name=$1
  dlq_name=$2
  primary_url=$(queue_url "$primary_name")
  dlq_url=$(queue_url "$dlq_name")
  dlq_arn=$(aws_local sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names QueueArn \
    --query Attributes.QueueArn \
    --output text)
  redrive="{\"deadLetterTargetArn\":\"$dlq_arn\",\"maxReceiveCount\":\"5\"}"
  attributes="{\"RedrivePolicy\":\"$redrive\"}"
  aws_local sqs set-queue-attributes \
    --queue-url "$primary_url" \
    --attributes "$attributes" \
    >/dev/null
}

verify_bucket() {
  aws_local s3api head-bucket --bucket "$S3_DOCUMENT_BUCKET" >/dev/null
  for setting in \
    BlockPublicAcls \
    IgnorePublicAcls \
    BlockPublicPolicy \
    RestrictPublicBuckets; do
    status=$(aws_local s3api get-public-access-block \
      --bucket "$S3_DOCUMENT_BUCKET" \
      --query "PublicAccessBlockConfiguration.$setting" \
      --output text)
    test "$status" = "True"
  done
}

verify_queue_pair() {
  primary_url=$(queue_url "$1")
  dlq_url=$(queue_url "$2")
  dlq_arn=$(aws_local sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names QueueArn \
    --query Attributes.QueueArn \
    --output text)
  redrive=$(aws_local sqs get-queue-attributes \
    --queue-url "$primary_url" \
    --attribute-names RedrivePolicy \
    --query Attributes.RedrivePolicy \
    --output text)
  python - "$redrive" "$dlq_arn" <<'PY'
import json
import sys

policy = json.loads(sys.argv[1])
assert policy == {
    "deadLetterTargetArn": sys.argv[2],
    "maxReceiveCount": "5",
}
PY
}

apply() {
  ensure_bucket
  for queue in \
    "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ" \
    "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ" \
    "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ"; do
    ensure_queue "$queue"
  done
  configure_redrive "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ"
  configure_redrive "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ"
  configure_redrive "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ"
}

verify() {
  verify_bucket
  verify_queue_pair "$SQS_PROCESSING_QUEUE" "$SQS_PROCESSING_DLQ"
  verify_queue_pair "$SQS_EXPORT_QUEUE" "$SQS_EXPORT_DLQ"
  verify_queue_pair "$SQS_NOTIFICATION_QUEUE" "$SQS_NOTIFICATION_DLQ"
}

case "$action" in
  apply)
    apply
    verify
    ;;
  verify)
    verify
    ;;
  *)
    echo "Usage: $0 apply|verify"
    exit 2
    ;;
esac
```

Make it executable:

```bash
chmod +x docker/localstack/bootstrap.sh
```

- [ ] **Step 5: Add Keycloak apply and verify behavior**

Create `docker/keycloak/ClientAttributes.java`. The bootstrap runs this
single-file source with Keycloak's bundled Jackson classpath so client
attribute names are decoded and serialized as JSON rather than interpolated
into shell expressions:

```java
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.regex.Pattern;

public final class ClientAttributes {
  private static final ObjectMapper JSON = new ObjectMapper();
  private static final Set<String> EXPECTED_KEYS =
      Set.of(
          "realm_client",
          "client.secret.creation.time",
          "post.logout.redirect.uris",
          "pkce.code.challenge.method");
  private static final Pattern DECIMAL = Pattern.compile("[0-9]+");

  private ClientAttributes() {}

  public static void main(String[] args) throws Exception {
    if (args.length != 1) {
      throw new IllegalArgumentException("Expected clear or verify action");
    }

    JsonNode root = JSON.readTree(System.in);
    JsonNode attributes = root.path("attributes");
    if (!attributes.isObject()) {
      throw new IllegalStateException("Missing client attributes object");
    }

    switch (args[0]) {
      case "clear" -> clear(root, attributes);
      case "verify" -> verify(attributes);
      default -> throw new IllegalArgumentException("Expected clear or verify action");
    }
  }

  private static void clear(JsonNode root, JsonNode attributes) throws Exception {
    JsonNode clientId = root.get("clientId");
    if (clientId == null || !clientId.isTextual()) {
      throw new IllegalStateException("Missing client identifier");
    }

    ObjectNode update = JSON.createObjectNode();
    update.set("clientId", clientId);
    ObjectNode clearedAttributes = update.putObject("attributes");
    Iterator<String> keys = attributes.fieldNames();
    while (keys.hasNext()) {
      String key = keys.next();
      if (EXPECTED_KEYS.contains(key)) {
        clearedAttributes.set(key, attributes.get(key));
      } else {
        clearedAttributes.putNull(key);
      }
    }
    JSON.writeValue(System.out, update);
  }

  private static void verify(JsonNode attributes) {
    Set<String> actualKeys = new HashSet<>();
    attributes.fieldNames().forEachRemaining(actualKeys::add);
    if (!actualKeys.equals(EXPECTED_KEYS)) {
      throw new IllegalStateException("Client attribute keys do not match the approved set");
    }

    expectValue(attributes, "realm_client", "false");
    expectValue(
        attributes, "post.logout.redirect.uris", "http://localhost:3000/*");
    expectValue(attributes, "pkce.code.challenge.method", "S256");

    String creationTime = attributes.path("client.secret.creation.time").asText("");
    if (!DECIMAL.matcher(creationTime).matches()) {
      throw new IllegalStateException("Client secret creation time is not numeric");
    }
  }

  private static void expectValue(
      JsonNode attributes, String key, String expectedValue) {
    if (!expectedValue.equals(attributes.path(key).asText(null))) {
      throw new IllegalStateException("Client attribute value is incorrect");
    }
  }
}
```

Create `docker/keycloak/bootstrap.sh`:

```sh
#!/bin/sh
set -eu

action=${1:-apply}
server=${KEYCLOAK_SERVER_URL:-http://keycloak:8080}
kcadm=/opt/keycloak/bin/kcadm.sh

login() {
  "$kcadm" config credentials \
    --server "$server" \
    --realm master \
    --user "$KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME" \
    --password "$KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD" \
    >/dev/null
}

single_id() {
  resource=$1
  shift
  "$kcadm" get "$resource" "$@" \
    --fields id \
    --format csv \
    --noquotes \
    | sed -n '1p'
}

client_id() {
  single_id clients -r "$KEYCLOAK_REALM" -q clientId="$OIDC_CLIENT_ID"
}

user_id() {
  single_id users -r "$KEYCLOAK_REALM" -q username="$1"
}

ensure_client() {
  id=$(client_id)
  if test -z "$id"; then
    "$kcadm" create clients \
      -r "$KEYCLOAK_REALM" \
      -s clientId="$OIDC_CLIENT_ID" \
      >/dev/null
    id=$(client_id)
  fi

  "$kcadm" update "clients/$id" \
    -r "$KEYCLOAK_REALM" \
    -s name="Agreement Intelligence Web" \
    -s enabled=true \
    -s protocol=openid-connect \
    -s clientAuthenticatorType=client-secret \
    -s publicClient=false \
    -s standardFlowEnabled=true \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s 'redirectUris=["http://localhost:3000/auth/callback"]' \
    -s 'webOrigins=["http://localhost:3000"]' \
    -s 'attributes={"post.logout.redirect.uris":"http://localhost:3000/*","pkce.code.challenge.method":"S256"}' \
    -s 'defaultClientScopes=["web-origins","acr","roles","profile","email"]' \
    -s 'optionalClientScopes=["address","phone","offline_access","microprofile-jwt"]' \
    -s secret="$OIDC_CLIENT_SECRET" \
    >/dev/null
}

ensure_user() {
  username=$1
  email=$2
  password=$3
  id=$(user_id "$username")

  if test -z "$id"; then
    "$kcadm" create users \
      -r "$KEYCLOAK_REALM" \
      -s username="$username" \
      -s email="$email" \
      -s enabled=true \
      -s emailVerified=true \
      >/dev/null
    id=$(user_id "$username")
  else
    "$kcadm" update "users/$id" \
      -r "$KEYCLOAK_REALM" \
      -s email="$email" \
      -s enabled=true \
      -s emailVerified=true \
      >/dev/null
  fi

  "$kcadm" set-password \
    -r "$KEYCLOAK_REALM" \
    --userid "$id" \
    --new-password "$password" \
    --temporary=false \
    >/dev/null
}

apply() {
  "$kcadm" update "realms/$KEYCLOAK_REALM" \
    -s enabled=true \
    -s displayName="Agreement Intelligence" \
    -s registrationAllowed=false \
    -s resetPasswordAllowed=true \
    -s rememberMe=false \
    -s verifyEmail=false \
    -s loginWithEmailAllowed=true \
    -s duplicateEmailsAllowed=false \
    >/dev/null

  ensure_client
  ensure_user \
    "$DEMO_REVIEWER_USERNAME" \
    "$DEMO_REVIEWER_EMAIL" \
    "$DEMO_REVIEWER_PASSWORD"
  ensure_user \
    "$DEMO_ADMIN_USERNAME" \
    "$DEMO_ADMIN_EMAIL" \
    "$DEMO_ADMIN_PASSWORD"
}

verify() {
  id=$(client_id)
  test -n "$id"
  client_json=$("$kcadm" get "clients/$id" -r "$KEYCLOAK_REALM")
  for expected in \
    'http://localhost:3000/auth/callback' \
    'http://localhost:3000' \
    'pkce.code.challenge.method' \
    'S256'; do
    printf '%s' "$client_json" | grep -q "$expected"
  done
  current_secret=$("$kcadm" get "clients/$id/client-secret" \
    -r "$KEYCLOAK_REALM" \
    --fields value \
    --format csv \
    --noquotes \
    | sed -n '1p')
  test "$current_secret" = "$OIDC_CLIENT_SECRET"
  test -n "$(user_id "$DEMO_REVIEWER_USERNAME")"
  test -n "$(user_id "$DEMO_ADMIN_USERNAME")"
}

login
case "$action" in
  apply)
    apply
    verify
    ;;
  verify)
    verify
    ;;
  *)
    echo "Usage: $0 apply|verify"
    exit 2
    ;;
esac
```

Make it executable:

```bash
chmod +x docker/keycloak/bootstrap.sh
```

- [ ] **Step 6: Mount the realm and add bootstrap services**

Change the Keycloak command and add its realm volume in `compose.yaml`.
The import creates a missing realm on the first boot; the bootstrap script
reapplies every mutable realm, client, and user setting on every run so
persisted identity state converges after version-controlled changes:

```yaml
    command: ["start-dev", "--import-realm"]
    volumes:
      - ./docker/keycloak/realm:/opt/keycloak/data/import:ro
```

Add these services before the `volumes` section:

```yaml
  localstack-bootstrap:
    image: localstack/localstack:4.14.0
    entrypoint: ["/bootstrap.sh"]
    command: ["apply"]
    environment:
      LOCALSTACK_ENDPOINT: http://localstack:4566
      AWS_REGION: ${AWS_REGION:?required}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:?required}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:?required}
      S3_DOCUMENT_BUCKET: ${S3_DOCUMENT_BUCKET:?required}
      SQS_PROCESSING_QUEUE: ${SQS_PROCESSING_QUEUE:?required}
      SQS_PROCESSING_DLQ: ${SQS_PROCESSING_DLQ:?required}
      SQS_EXPORT_QUEUE: ${SQS_EXPORT_QUEUE:?required}
      SQS_EXPORT_DLQ: ${SQS_EXPORT_DLQ:?required}
      SQS_NOTIFICATION_QUEUE: ${SQS_NOTIFICATION_QUEUE:?required}
      SQS_NOTIFICATION_DLQ: ${SQS_NOTIFICATION_DLQ:?required}
    volumes:
      - ./docker/localstack/bootstrap.sh:/bootstrap.sh:ro
    depends_on:
      localstack:
        condition: service_healthy
    restart: "no"

  keycloak-bootstrap:
    image: quay.io/keycloak/keycloak:26.7.0
    entrypoint: ["/bootstrap.sh"]
    command: ["apply"]
    environment:
      KEYCLOAK_SERVER_URL: http://keycloak:8080
      KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME: ${KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME:?required}
      KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD: ${KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD:?required}
      KEYCLOAK_REALM: ${KEYCLOAK_REALM:?required}
      OIDC_CLIENT_ID: ${OIDC_CLIENT_ID:?required}
      OIDC_CLIENT_SECRET: ${OIDC_CLIENT_SECRET:?required}
      DEMO_REVIEWER_USERNAME: ${DEMO_REVIEWER_USERNAME:?required}
      DEMO_REVIEWER_EMAIL: ${DEMO_REVIEWER_EMAIL:?required}
      DEMO_REVIEWER_FIRST_NAME: ${DEMO_REVIEWER_FIRST_NAME:?required}
      DEMO_REVIEWER_LAST_NAME: ${DEMO_REVIEWER_LAST_NAME:?required}
      DEMO_REVIEWER_PASSWORD: ${DEMO_REVIEWER_PASSWORD:?required}
      DEMO_ADMIN_USERNAME: ${DEMO_ADMIN_USERNAME:?required}
      DEMO_ADMIN_EMAIL: ${DEMO_ADMIN_EMAIL:?required}
      DEMO_ADMIN_FIRST_NAME: ${DEMO_ADMIN_FIRST_NAME:?required}
      DEMO_ADMIN_LAST_NAME: ${DEMO_ADMIN_LAST_NAME:?required}
      DEMO_ADMIN_PASSWORD: ${DEMO_ADMIN_PASSWORD:?required}
    volumes:
      - ./docker/keycloak/bootstrap.sh:/bootstrap.sh:ro
      - ./docker/keycloak/ClientAttributes.java:/ClientAttributes.java:ro
    depends_on:
      keycloak:
        condition: service_healthy
    restart: "no"
```

- [ ] **Step 7: Run the bootstrap contract**

Run:

```bash
tests/stack/test-bootstrap-contracts.sh
```

Expected:

- both bootstrap services exit `0`;
- the bucket is private;
- all queues and redrive policies exist;
- the realm, client secret, and users exist; and
- explicit verification runs exit `0`.

- [ ] **Step 8: Verify idempotency**

Run:

```bash
env_file=$(mktemp)
cleanup_bootstrap_test() {
  docker compose --project-name agreement-intelligence \
    --env-file "$env_file" down --remove-orphans \
    >/dev/null 2>&1 || true
  rm -f "$env_file"
}
trap cleanup_bootstrap_test EXIT INT TERM
sed 's/change-me/test-only-value/g' .env.example >"$env_file"

docker compose --project-name agreement-intelligence \
  --env-file "$env_file" up --detach \
  localstack-bootstrap keycloak-bootstrap
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" wait \
  localstack-bootstrap keycloak-bootstrap
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" run --rm --no-deps \
  localstack-bootstrap verify
docker compose --project-name agreement-intelligence \
  --env-file "$env_file" run --rm --no-deps \
  keycloak-bootstrap verify
cleanup_bootstrap_test
trap - EXIT INT TERM
```

Expected: repeat apply and verify commands exit `0` without duplicate-resource
errors.

- [ ] **Step 9: Run existing checks and stop the platform**

```bash
make check
docker compose --project-name agreement-intelligence down
git diff --check
```

Expected: all commands pass and named volumes remain.

- [ ] **Step 10: Commit deterministic bootstrap**

```bash
git add \
  compose.yaml \
  docker/localstack/bootstrap.sh \
  docker/keycloak/ClientAttributes.java \
  docker/keycloak/bootstrap.sh \
  docker/keycloak/realm/agreement-intelligence-realm.json \
  tests/stack/test-bootstrap-contracts.sh
git commit -m "feat(infra): bootstrap local cloud and identity"
```

- [ ] **Step 11: Publish the Task 3 review**

```bash
git push --set-upstream origin feat/platform-bootstrap
gh pr create \
  --base main \
  --head feat/platform-bootstrap \
  --title "Bootstrap local cloud and identity services" \
  --body $'## Summary\n\n- provision private S3 and SQS resources idempotently\n- converge Keycloak realm, client, and demo users\n- verify repeated bootstrap execution\n\n## Verification\n\n- make check\n- tests/stack/test-bootstrap-contracts.sh\n\nCloses #79\nRefs #3\n\nOnly the repository owner merges this pull request.'
```

Stop after the ready-for-review pull request is open. Task 4 starts only after
the repository owner merges it.

---

### Task 4: Orchestrate and verify the complete containerized stack

**Files:**

- Create: `scripts/stack-check.sh`
- Create: `tests/stack/test-stack-lifecycle.sh`
- Modify: `compose.yaml`
- Modify: `Makefile`
- Modify: `package.json`
- Modify: `pnpm-lock.yaml`

**Interfaces:**

- Consumes: application images from Task 1 and platform/bootstrap contracts
  from Tasks 2 and 3.
- Produces: services `web`, `api`, and `worker`; commands `make stack-build`,
  `stack-up`, `stack-down`, `stack-status`, `stack-logs`, `stack-check`, and
  `stack-reset CONFIRM=reset`; one complete container runtime.

**Branch:** After Task 3 is merged and local `main` is updated, create
`feat/containerized-stack`. This task closes #80 and references #3.

- [ ] **Step 1: Add the failing lifecycle contract**

Create `tests/stack/test-stack-lifecycle.sh`:

```sh
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

for target in \
  stack-build stack-up stack-down stack-status stack-logs stack-check stack-reset; do
  make help | grep -q "make $target" || {
    echo "Missing Make target: $target"
    exit 1
  }
done

for removed in dev dev-web dev-api dev-worker; do
  if make help | grep -q "make $removed "; then
    echo "Host runtime target still published: $removed"
    exit 1
  fi
done

STACK_ENV_FILE="$env_file" make stack-up
STACK_ENV_FILE="$env_file" make stack-check

for service in web api worker postgres localstack keycloak; do
  docker compose --project-name agreement-intelligence \
    --env-file "$env_file" ps --services --status running \
    | grep -qx "$service"
done

if STACK_ENV_FILE="$env_file" make stack-reset >"$reset_output" 2>&1; then
  echo "Unconfirmed reset unexpectedly succeeded"
  exit 1
fi
grep -q 'CONFIRM=reset' "$reset_output"

sed 's/API_PORT=8000/API_PORT=not-a-port/' "$env_file" >"$reset_output"
if STACK_ENV_FILE="$reset_output" make stack-reset CONFIRM=reset >/dev/null 2>&1; then
  echo "Reset with invalid configuration unexpectedly succeeded"
  exit 1
fi
STACK_ENV_FILE="$env_file" make stack-check

STACK_ENV_FILE="$env_file" make stack-down
test -z "$(docker compose --project-name agreement-intelligence \
  --env-file "$env_file" ps --all --quiet)"
```

Make it executable:

```bash
chmod +x tests/stack/test-stack-lifecycle.sh
```

- [ ] **Step 2: Run the contract and confirm the expected failure**

Run:

```bash
tests/stack/test-stack-lifecycle.sh
```

Expected: exit `1` with `Missing Make target: stack-build`.

- [ ] **Step 3: Add the application services to Compose**

Add these services before the bootstrap services in `compose.yaml`:

```yaml
  api:
    build:
      context: .
      dockerfile: apps/api/Dockerfile
    environment:
      DATABASE_URL: postgresql://${APP_DB_USER}:${APP_DB_PASSWORD}@postgres:5432/${APP_DB_NAME}
      AWS_REGION: ${AWS_REGION:?required}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:?required}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:?required}
      AWS_ENDPOINT_URL: http://localstack:4566
      S3_DOCUMENT_BUCKET: ${S3_DOCUMENT_BUCKET:?required}
    ports:
      - "127.0.0.1:${API_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_healthy
      localstack-bootstrap:
        condition: service_completed_successfully
      keycloak-bootstrap:
        condition: service_completed_successfully
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - >-
          import json,urllib.request;
          data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=2));
          assert data['status']=='ok'
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 10s
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    restart: unless-stopped

  worker:
    build:
      context: .
      dockerfile: apps/worker/Dockerfile
    environment:
      DATABASE_URL: postgresql://${APP_DB_USER}:${APP_DB_PASSWORD}@postgres:5432/${APP_DB_NAME}
      AWS_REGION: ${AWS_REGION:?required}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:?required}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:?required}
      AWS_ENDPOINT_URL: http://localstack:4566
      S3_DOCUMENT_BUCKET: ${S3_DOCUMENT_BUCKET:?required}
      SQS_PROCESSING_QUEUE: ${SQS_PROCESSING_QUEUE:?required}
    depends_on:
      postgres:
        condition: service_healthy
      localstack-bootstrap:
        condition: service_completed_successfully
      keycloak-bootstrap:
        condition: service_completed_successfully
    healthcheck:
      test: ["CMD-SHELL", "kill -0 1"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 5s
    stop_grace_period: 15s
    init: true
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    restart: unless-stopped

  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
    environment:
      API_BASE_URL: http://api:8000
    ports:
      - "127.0.0.1:${WEB_PORT:-3000}:3000"
    depends_on:
      api:
        condition: service_healthy
    healthcheck:
      test:
        - CMD
        - node
        - -e
        - >-
          fetch('http://127.0.0.1:3000')
          .then(r=>{if(!r.ok)process.exit(1)})
          .catch(()=>process.exit(1))
      interval: 5s
      timeout: 5s
      retries: 20
      start_period: 10s
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    restart: unless-stopped
```

- [ ] **Step 4: Add the full stack verification script**

Create `scripts/stack-check.sh`:

```sh
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
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8000/health/live", timeout=2) as response:
    payload = json.load(response)

assert payload == {
    "status": "ok",
    "service": "api",
    "version": "0.1.0",
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
```

Make it executable:

```bash
chmod +x scripts/stack-check.sh
```

- [ ] **Step 5: Replace host runtime commands with stack commands**

Remove the root `dev` script and the `concurrently` dependency:

```bash
pnpm remove --save-dev concurrently
```

Replace `Makefile` with:

<!-- markdownlint-disable MD010 -->

```make
SHELL := /bin/sh

NODE_VERSION ?= $(shell cat .node-version)
PYTHON_VERSION ?= $(shell cat .python-version)
PNPM_VERSION ?= 10.28.0
STACK_ENV_FILE ?= .env
COMPOSE := docker compose --project-name agreement-intelligence --env-file $(STACK_ENV_FILE)

.PHONY: help check-toolchain check-container-toolchain setup \
	stack-build stack-up stack-down stack-status stack-logs stack-check stack-reset \
	format format-check lint typecheck test build check

help:
	@echo "Agreement Intelligence developer commands"
	@echo "  make setup          Verify source tools and install locked dependencies"
	@echo "  make stack-build    Build application container images"
	@echo "  make stack-up       Build, start, and wait for the complete stack"
	@echo "  make stack-down     Stop containers while preserving project data"
	@echo "  make stack-status   Show project containers and health"
	@echo "  make stack-logs     Follow logs for the complete stack"
	@echo "  make stack-check    Verify services and bootstrapped resources"
	@echo "  make stack-reset    Recreate the stack and volumes with CONFIRM=reset"
	@echo "  make format         Format TypeScript and Python"
	@echo "  make format-check   Check TypeScript and Python formatting"
	@echo "  make lint           Lint TypeScript and Python"
	@echo "  make typecheck      Type-check TypeScript and Python"
	@echo "  make test           Run JavaScript and Python tests"
	@echo "  make build          Build every application"
	@echo "  make check          Run all pre-review source checks"

check-toolchain:
	@command -v node >/dev/null 2>&1 || { echo "Node.js is not installed."; exit 1; }
	@actual="$$(node --version)"; expected="v$(NODE_VERSION)"; \
		[ "$$actual" = "$$expected" ] || { \
			echo "Node.js version mismatch: expected $$expected, found $$actual."; \
			exit 1; \
		}
	@command -v pnpm >/dev/null 2>&1 || { echo "pnpm is not installed."; exit 1; }
	@actual="$$(pnpm --version)"; expected="$(PNPM_VERSION)"; \
		[ "$$actual" = "$$expected" ] || { \
			echo "pnpm version mismatch: expected $$expected, found $$actual."; \
			exit 1; \
		}
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed."; exit 1; }
	@echo "Source toolchain versions are valid."

check-container-toolchain:
	@command -v docker >/dev/null 2>&1 || { echo "Docker is not installed."; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "Docker is not running."; exit 1; }
	@docker compose version >/dev/null 2>&1 || { echo "Docker Compose is unavailable."; exit 1; }
	@version="$$(docker compose version --short | sed 's/^v//')"; \
		major="$${version%%.*}"; rest="$${version#*.}"; minor="$${rest%%.*}"; \
		[ "$$major" -gt 2 ] || { [ "$$major" -eq 2 ] && [ "$$minor" -ge 24 ]; } || { \
			echo "Docker Compose 2.24 or newer is required; found $$version."; \
			exit 1; \
		}
	@echo "Container toolchain is valid."

setup: check-toolchain
	uv python install $(PYTHON_VERSION)
	pnpm install --frozen-lockfile
	uv sync --all-packages --frozen

stack-build: check-container-toolchain
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	$(COMPOSE) build

stack-up: check-container-toolchain
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	$(COMPOSE) up --detach --build --wait --wait-timeout 180

stack-down: check-container-toolchain
	$(COMPOSE) down --remove-orphans

stack-status: check-container-toolchain
	$(COMPOSE) ps --all

stack-logs: check-container-toolchain
	$(COMPOSE) logs --follow

stack-check: check-container-toolchain
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/stack-check.sh

stack-reset: check-container-toolchain
	@[ "$(CONFIRM)" = "reset" ] || { \
		echo "Refusing to delete project volumes. Re-run with CONFIRM=reset."; \
		exit 1; \
	}
	@STACK_ENV_FILE="$(STACK_ENV_FILE)" scripts/validate-stack-env.sh
	@$(COMPOSE) config --quiet
	$(COMPOSE) down --volumes --remove-orphans
	$(MAKE) stack-up STACK_ENV_FILE="$(STACK_ENV_FILE)"

format:
	pnpm format
	uv run ruff format apps/api apps/worker

format-check:
	pnpm format:check
	uv run ruff format --check apps/api apps/worker

lint:
	pnpm --filter @agreement-intelligence/web lint
	uv run ruff check apps/api apps/worker

typecheck:
	pnpm --filter @agreement-intelligence/web typecheck
	uv run mypy apps/api/src apps/api/tests apps/worker/src apps/worker/tests

test:
	pnpm --filter @agreement-intelligence/web test
	uv run pytest

build:
	pnpm --filter @agreement-intelligence/web build
	uv build --package agreement-intelligence-api --out-dir dist/api
	uv build --package agreement-intelligence-worker --out-dir dist/worker

check:
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) build
```

<!-- markdownlint-enable MD010 -->

- [ ] **Step 6: Run the focused lifecycle contract**

Run:

```bash
tests/stack/test-stack-lifecycle.sh
```

Expected:

- `make stack-up` builds and starts the complete stack;
- `make stack-check` passes;
- all six runtime services are running;
- reset without confirmation is rejected;
- `make stack-down` removes every project container; and
- the script exits `0`.

- [ ] **Step 7: Verify no host runtime command remains**

Run:

```bash
rg -n 'make dev|dev-web|dev-api|dev-worker|pnpm dev|concurrently' \
  Makefile package.json README.md
```

Expected: README references may remain for Task 5 to update, but Makefile and
`package.json` contain no host runtime command or `concurrently` dependency.

- [ ] **Step 8: Run the complete automated verification**

```bash
make check
make stack-check
git diff --check
```

Expected: all commands pass.

- [ ] **Step 9: Commit complete stack orchestration**

```bash
git add \
  compose.yaml \
  Makefile \
  package.json \
  pnpm-lock.yaml \
  scripts/stack-check.sh \
  tests/stack/test-stack-lifecycle.sh
git commit -m "feat(infra): orchestrate containerized application stack"
```

- [ ] **Step 10: Publish the Task 4 review**

```bash
git push --set-upstream origin feat/containerized-stack
gh pr create \
  --base main \
  --head feat/containerized-stack \
  --title "Orchestrate the complete containerized stack" \
  --body $'## Summary\n\n- run the web, API, and worker through Docker Compose\n- add deterministic lifecycle and verification commands\n- protect destructive reset behind confirmation and configuration validation\n\n## Verification\n\n- make check\n- make stack-check\n- tests/stack/test-stack-lifecycle.sh\n\nCloses #80\nRefs #3\n\nOnly the repository owner merges this pull request.'
```

Stop after the ready-for-review pull request is open. Task 5 starts only after
the repository owner merges it.

---

### Task 5: Document and demonstrate the portable stack

**Files:**

- Modify: `README.md`
- Create: `docs/assets/containerized-stack.jpg`
- Create: `tests/stack/test-stack-persistence.sh`

**Interfaces:**

- Consumes: the complete stack and Make command surface from Tasks 1–4.
- Produces: clone-to-run documentation, PostgreSQL persistence and reset
  evidence, and a business-visible screenshot showing the grouped project and
  healthy application. LocalStack resources are recreated idempotently because
  the emulator is ephemeral.

**Branch:** After Task 4 is merged and local `main` is updated, create
`docs/portable-stack-guide`. This task closes #81 and references #3.

- [ ] **Step 1: Add the persistence and reset contract**

Create `tests/stack/test-stack-persistence.sh`:

```sh
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

STACK_ENV_FILE="$env_file" make stack-up
compose exec -T postgres sh -c \
  'psql \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --command "CREATE TABLE IF NOT EXISTS stack_persistence_marker (value text NOT NULL);"'
compose exec -T postgres sh -c \
  'psql \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --command "TRUNCATE stack_persistence_marker; INSERT INTO stack_persistence_marker VALUES ('\''preserved'\'');"'

STACK_ENV_FILE="$env_file" make stack-down
STACK_ENV_FILE="$env_file" make stack-up

compose exec -T postgres sh -c \
  'psql \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --tuples-only \
    --command "SELECT value FROM stack_persistence_marker;"' \
  | grep -q preserved

if STACK_ENV_FILE="$env_file" make stack-reset >"$reset_output" 2>&1; then
  echo "Unconfirmed reset unexpectedly succeeded"
  exit 1
fi

STACK_ENV_FILE="$env_file" make stack-reset CONFIRM=reset

if compose exec -T postgres sh -c \
  'psql \
    --username "$APP_DB_USER" \
    --dbname "$APP_DB_NAME" \
    --tuples-only \
    --command "SELECT to_regclass('\''public.stack_persistence_marker'\'');"' \
  | grep -q stack_persistence_marker; then
  echo "Confirmed reset preserved the marker unexpectedly"
  exit 1
fi

STACK_ENV_FILE="$env_file" make stack-check
```

Make it executable:

```bash
chmod +x tests/stack/test-stack-persistence.sh
```

- [ ] **Step 2: Run the lifecycle evidence contract**

Run:

```bash
tests/stack/test-stack-persistence.sh
```

Expected:

- normal down/up preserves the marker;
- unconfirmed reset is rejected;
- confirmed reset removes the marker;
- required platform resources are recreated; and
- final `make stack-check` passes.

- [ ] **Step 3: Replace README runtime documentation**

Replace the current `## Local development` section with:

````markdown
## Run the complete application

### Prerequisites

- Docker Engine with Docker Compose 2.24 or newer
- GNU Make

Copy the safe environment template and replace every `change-me` value:

```bash
cp .env.example .env
```

Build and start the complete application:

```bash
make stack-up
make stack-check
```

Docker groups every container, network, and volume under the
`agreement-intelligence` Compose project.

The local applications are available at:

- Web application: <http://localhost:3000>
- API liveness: <http://localhost:8000/health/live>
- API documentation: <http://localhost:8000/docs>
- Keycloak: <http://localhost:8080>
- LocalStack gateway: <http://localhost:4566>

The stack contains the web application, API, worker, PostgreSQL with pgvector,
LocalStack for S3 and SQS, and Keycloak. Authentication integration and
document-processing workflows are delivered in later iterations.

| Command | Purpose |
| --- | --- |
| `make help` | List supported commands. |
| `make stack-build` | Build application container images. |
| `make stack-up` | Build, start, and wait for the complete stack. |
| `make stack-down` | Stop containers while preserving project data. |
| `make stack-status` | Show project containers and health state. |
| `make stack-logs` | Follow logs for the complete stack. |
| `make stack-check` | Verify services and bootstrapped resources. |
| `make stack-reset CONFIRM=reset` | Delete project volumes and recreate the stack. |

The reset command permanently deletes local project data and refuses to run
without the explicit confirmation value.

### Source-quality commands

Contributors changing source code also use the pinned Node.js, pnpm, Python,
and uv toolchains:

| Command | Purpose |
| --- | --- |
| `make setup` | Install locked source dependencies. |
| `make format` | Format TypeScript and Python. |
| `make format-check` | Check formatting without changing files. |
| `make lint` | Lint TypeScript and Python. |
| `make typecheck` | Type-check TypeScript and Python. |
| `make test` | Run JavaScript and Python tests. |
| `make build` | Build every application outside Docker. |
| `make check` | Run all pre-review source checks. |
````

- [ ] **Step 4: Run documentation verification**

```bash
pnpm dlx markdownlint-cli2@0.23.1 README.md
git diff --check
```

Expected: both commands pass.

- [ ] **Step 5: Perform the manual business demonstration**

Run:

```bash
make stack-reset CONFIRM=reset
make stack-check
make stack-status
```

Verify:

1. Docker Desktop shows one `agreement-intelligence` project group.
2. The group contains web, API, worker, PostgreSQL, LocalStack, Keycloak, and
   the completed bootstrap services.
3. The web page displays `API connected`.
4. API liveness returns the expected JSON.
5. Swagger UI exposes `GET /health/live`.
6. PostgreSQL exposes pgvector.
7. LocalStack contains the private bucket and six queues.
8. Keycloak contains the realm, client, and two seeded users.
9. The worker has a structured `worker.started` log.

Capture `docs/assets/containerized-stack.jpg` showing the grouped project and
the web application without exposing `.env` values or credentials.

- [ ] **Step 6: Run final automated verification**

```bash
make check
make stack-check
tests/stack/test-application-images.sh
tests/stack/test-compose-contract.sh
tests/stack/test-bootstrap-contracts.sh
tests/stack/test-stack-lifecycle.sh
tests/stack/test-stack-persistence.sh
git diff --check
```

Expected: every command passes.

- [ ] **Step 7: Stop the stack and verify cleanup**

```bash
make stack-down
docker compose --project-name agreement-intelligence ps --all --quiet
```

Expected: the second command prints nothing.

- [ ] **Step 8: Commit documentation and demonstration evidence**

```bash
git add \
  README.md \
  docs/assets/containerized-stack.jpg \
  tests/stack/test-stack-persistence.sh
git commit -m "docs: add portable stack guide"
```

- [ ] **Step 9: Perform the story pre-review audit**

```bash
git diff --check origin/main...HEAD
git log --oneline origin/main..HEAD
git status --short --branch
make check
```

Expected:

- no whitespace errors;
- only story #3 task commits are present;
- the working tree is clean; and
- source checks pass immediately before publication.

- [ ] **Step 10: Publish the Task 5 review**

Push only `docs/portable-stack-guide` and open a ready-for-review pull request
targeting `main`:

```bash
git push --set-upstream origin docs/portable-stack-guide
gh pr create \
  --base main \
  --head docs/portable-stack-guide \
  --title "Document and demonstrate the portable stack" \
  --body $'## Summary\n\n- document the Docker-only application runtime\n- prove persistence and confirmed reset behavior\n- add the grouped-stack business demonstration\n\n## Verification\n\n- make check\n- make stack-check\n- tests/stack/test-application-images.sh\n- tests/stack/test-compose-contract.sh\n- tests/stack/test-bootstrap-contracts.sh\n- tests/stack/test-stack-lifecycle.sh\n- tests/stack/test-stack-persistence.sh\n\nCloses #81\nRefs #3\n\nOnly the repository owner merges this pull request.'
```

The pull request description must also include:

- its child task closure;
- a reference to story #3;
- exact image pins;
- automated verification results;
- persistence and reset evidence;
- the application and Docker project screenshot;
- deferred-scope confirmation; and
- confirmation that only the repository owner merges.

Do not merge the pull request.
