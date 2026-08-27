# Getting started from a fresh clone

This path starts the complete containerized application with synthetic identities. Run the
no-provider-key path first; provider use is a separate, explicit opt-in.

## Contents

- [1. Check prerequisites](#1-check-prerequisites)
- [2. Clone and configure](#2-clone-and-configure)
- [3. Start and verify](#3-start-and-verify)
- [4. Sign in](#4-sign-in)
- [5. Verify no-key behavior](#5-verify-no-key-behavior)
- [6. Opt in to provider mode](#6-opt-in-to-provider-mode)
- [7. Stop safely](#7-stop-safely)
- [8. Troubleshoot](#8-troubleshoot)
- [9. Verify source and release gates](#9-verify-source-and-release-gates)

## 1. Check prerequisites

Required for the container stack:

```bash
docker --version
docker compose version
make --version
zip -v
docker info
```

Docker must be running, Docker Compose must be 2.24 or newer, and `zip` must be available
for deterministic DOCX fixture generation. A current desktop browser is required;
automated browser coverage uses Playwright Chromium.

Source/release work additionally uses the versions pinned in the repository:

```bash
cat .node-version
node --version
node -p "require('./package.json').packageManager"
cat .python-version
uv --version
terraform version
```

Expected repository pins are Node.js 22.23.1, pnpm 10.28.0, Python 3.13.14, uv 0.11.32
in CI, and Terraform 1.12.2 in CI. `make setup` installs locked dependencies after the
source toolchain is active.

[Back to contents](#contents)

## 2. Clone and configure

```bash
git clone https://github.com/ramioooz/agreement-intelligence.git
cd agreement-intelligence
cp .env.example .env
git status --short
```

`.env` is ignored and must remain untracked. Replace every `change-me` value with a
unique local value. Database passwords allow URI-safe letters, digits, `.`, `_`, `~`,
and `-`; use long random values without shell interpolation. Keep the test-only LocalStack
`AWS_ACCESS_KEY_ID=test` and `AWS_SECRET_ACCESS_KEY=test`; they cannot authorize AWS.

For the first run:

```dotenv
OPENAI_API_KEY=
MODEL_GATEWAY_API_KEY=
MODEL_GATEWAY_FALLBACK_MODE=
```

Do not paste a real key into a terminal command, shell history, screenshot, exported API
collection, log, trace, or evidence file.

Validate without starting containers:

```bash
scripts/validate-stack-env.sh .env
docker compose --project-name agreement-intelligence --env-file .env config --quiet
```

The validator rejects missing files, placeholders, required empty values, unsafe database
identifiers/passwords, duplicate or invalid ports, malformed issuer/origin URLs, and a web
origin that does not match `WEB_PORT`.

[Back to contents](#contents)

## 3. Start and verify

```bash
make stack-up
make stack-check
make stack-status
```

`stack-up` builds, starts, and waits up to 180 seconds. `stack-check` confirms:

- nine running services: API, web, worker, PostgreSQL, Redis, LocalStack, Keycloak, MCP,
  and the OpenTelemetry Collector;
- healthy containers and successful Keycloak/LocalStack bootstrap jobs;
- application and Keycloak databases plus pgvector;
- S3 bucket and processing/export/notification queues with dead-letter queues;
- Keycloak realm, client, callbacks, and three demo identities;
- API liveness, OpenAPI/Swagger, web-to-API connectivity, and worker startup.

Default endpoints:

| Purpose | URL |
| --- | --- |
| Web/sign-in | <http://localhost:3000/sign-in> |
| Dashboard | <http://localhost:3000/dashboard> |
| API liveness/readiness | <http://localhost:8000/health/live>, <http://localhost:8000/health/ready> |
| API Swagger/OpenAPI | <http://localhost:8000/docs>, <http://localhost:8000/openapi.json> |
| MCP | <http://localhost:8001/mcp> |
| Keycloak | <http://localhost:8080> |
| LocalStack | <http://localhost:4566> |

All published default ports bind to `127.0.0.1`.

[Back to contents](#contents)

## 4. Sign in

Use the usernames below and the password values you assigned in `.env`:

| Username | Role/use |
| --- | --- |
| `platform.admin` | Full demo administration, audit, policy/playbook, assignment, deletion |
| `legal.reviewer` | Legal reviewer plus business-user upload/update/search permissions |
| `business.approver` | Read/search and eligible business approval |

The home page links to sign-in. Keycloak authenticates; the API owns memberships and
permissions. Sign out through the application to clear both local session and Keycloak
single-sign-on state.

[Back to contents](#contents)

## 5. Verify no-key behavior

1. Sign in as `legal.reviewer`.
2. Open **Repository** and upload a text-bearing synthetic PDF or DOCX from
   [Test data](testing/test-data.md).
3. Confirm immediate list visibility and a processing status, then wait for the terminal
   result.
4. Inspect deterministic classification/analysis and source citations.
5. Open **Search**, query a distinctive synthetic term, and confirm lexical results.
6. Ask a grounded question and confirm the UI/API reports the provider-backed answer as
   unavailable rather than fabricating one.
7. Confirm repository, versions, playbooks, comparison, review, approval, audit, and package
   workflows remain accessible according to the signed-in role.

Expected: no key is needed for stack health, deterministic parsing/rules, lexical search,
or business workflow. Embeddings, semantic results, and provider-generated answers are
explicitly unavailable/degraded. Image-only documents may report `ocr_required`; no OCR
engine is installed.

[Back to contents](#contents)

## 6. Opt in to provider mode

Only the operator can authorize external provider use. Confirm that the synthetic document
may be processed under the provider's privacy, retention, region, quota, and cost terms.

Add the key to ignored `.env` without printing it, then restart the API and worker so they
receive the updated environment:

```bash
docker compose --project-name agreement-intelligence --env-file .env up \
  --detach --no-deps --force-recreate api worker
make provider-smoke
make stack-check
```

Process a new synthetic document or manually retry/requeue an authorized failed job. Verify
provider/model/configuration provenance, validated enrichment, embedding state, semantic
retrieval, and a cited grounded answer. Never record provider response bodies or the key.

If provider smoke fails, return to no-key mode or follow the
[provider-outage runbook](operations/runbooks/provider-outage.md). Historical failed
enrichment is not automatically backfilled.

[Back to contents](#contents)

## 7. Stop safely

```bash
make stack-down
```

This removes containers/network while preserving the PostgreSQL named volume. LocalStack is
ephemeral and recreates resources on startup. Use
[backup and restore](operations/backup-restore.md) before any destructive rehearsal.

Do not use the reset command for ordinary shutdown. `make stack-reset CONFIRM=reset`
deletes the selected Compose project's local volumes.

[Back to contents](#contents)

## 8. Troubleshoot

Use non-destructive commands first:

```bash
make stack-status
docker compose --project-name agreement-intelligence --env-file .env logs --tail 200 <service>
make stack-check
```

- **Port already allocated:** change the matching `*_PORT`. For `WEB_PORT`, update
  `WEB_PUBLIC_ORIGIN` and `AUTH_URL` to the same origin/port before recreating web and
  Keycloak bootstrap.
- **Keycloak/bootstrap failure:** inspect `keycloak` and `keycloak-bootstrap`; verify
  issuer/client/origin and database credentials. A database credential changed after first
  initialization may require an intentional backup/reset.
- **Stale sign-in/logout:** sign out in-app; clear only localhost site data; confirm the
  browser and `OIDC_ISSUER` use the same host.
- **Queued/stuck processing:** inspect safe worker/API logs and queue depth; use the
  [stuck-processing](operations/runbooks/stuck-processing.md) and
  [queue-backlog](operations/runbooks/queue-backlog.md) runbooks.
- **Provider unavailable:** lexical/deterministic behavior remains. Verify account/model/
  quota/network without exposing the key; manually reprocess after recovery.
- **`ocr_required`:** use a text-bearing fixture or integrate an approved OCR boundary;
  this project does not include one.
- **Missing Terraform tools:** install the pinned CI versions. Terraform checks fail rather
  than silently claiming LocalStack coverage.

[Back to contents](#contents)

## 9. Verify source and release gates

Install locked source dependencies:

```bash
make setup
```

The full source gate requires a disposable PostgreSQL URL for forced-RLS integration.
Create the ignored `.env.release-test.local` in an editor, restrict it to the current user,
and place the variable there (never in a command argument):

```dotenv
AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL=postgresql://USER:PASSWORD@127.0.0.1:PORT/agreement_intelligence_test
```

```bash
chmod 600 .env.release-test.local
set -a
. ./.env.release-test.local
set +a
make check
unset AGREEMENT_INTELLIGENCE_TEST_POSTGRES_URL
```

Never point that variable at retained or production data. Run documentation contracts:

```bash
node scripts/check-doc-links.mjs
tests/docs/test-documentation-contract.sh
```

The complete non-destructive release gate and its explicit prerequisites are documented in
[Release evidence](testing/release-evidence.md). Manual execution uses the
[Manual QA plan](testing/manual-test-plan.md).

[Back to top](#getting-started-from-a-fresh-clone)
