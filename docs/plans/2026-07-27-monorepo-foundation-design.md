# Monorepo Foundation Design

## Status

Approved for implementation on 2026-07-27.

## Context

The repository needs a runnable foundation for the Agreement Intelligence
product before infrastructure and business capabilities are introduced. GitHub
Issue #2 requires independently runnable web, API, and worker applications,
pinned JavaScript and Python toolchains, and one repeatable command surface for
development and verification.

This design deliberately excludes authentication, persistence, messaging,
document processing, and cloud deployment. Those capabilities belong to later
delivery stories and should build on the boundaries established here.

## Goals

- Create runnable applications under `apps/web`, `apps/api`, and `apps/worker`.
- Manage JavaScript dependencies with a pnpm workspace.
- Manage Python dependencies with a uv workspace.
- Pin supported Node.js, pnpm, and Python versions.
- Provide a Makefile as the repository-wide developer command surface.
- Start all three applications with one command while retaining independent
  application commands.
- Establish repeatable formatting, linting, type-checking, testing, and build
  commands.
- Demonstrate a minimal web-to-API connection.
- Keep the worker a long-running Python process without inventing an HTTP
  interface or queue integration.

## Non-goals

- Authentication or authorization.
- PostgreSQL, database migrations, or vector storage.
- LocalStack, SQS, object storage, or queue consumers.
- Document upload, parsing, OCR, extraction, retrieval, or model operations.
- Container images, Docker Compose, or AWS infrastructure.
- Production telemetry, dashboards, or alerting.
- A complete product interface or design system.

## Runtime Baselines

The repository pins these runtime and package-manager versions:

| Runtime or tool | Version |
| --- | --- |
| Node.js | 22.23.1 |
| pnpm | 10.28.0 |
| Python | 3.13.14 |

Node.js is pinned in `.node-version`, Python is pinned in `.python-version`,
and pnpm is pinned through the root `package.json` `packageManager` field.
Package versions are resolved into `pnpm-lock.yaml` and `uv.lock`.

The toolchain check fails early with an actionable message when the active
Node.js or pnpm version differs from the pinned version. uv is responsible for
installing or selecting the pinned Python runtime during setup.

## Repository Structure

```text
agreement-intelligence/
├── apps/
│   ├── web/
│   ├── api/
│   └── worker/
├── docs/
│   └── plans/
├── Makefile
├── package.json
├── pnpm-workspace.yaml
├── pyproject.toml
├── pnpm-lock.yaml
├── uv.lock
├── .node-version
└── .python-version
```

The root pnpm workspace owns JavaScript and TypeScript packages. The root uv
workspace owns Python packages. The Makefile coordinates both ecosystems but
does not replace their native commands or lockfiles.

## Application Boundaries

### Web application

`apps/web` is a Next.js App Router application written in TypeScript and styled
with Tailwind CSS. It runs on port `3000` in local development.

The initial homepage provides a minimal Agreement Intelligence application
shell. A server-side health client requests the API health endpoint and renders
either `API connected` or `API unavailable`. The request uses a short timeout,
disables response caching, and converts network failures into the unavailable
state instead of failing the page render.

The web application contains presentation and integration code only. Business
logic remains outside Next.js route handlers and server actions.

### API application

`apps/api` is an installable Python package using a `src` layout. FastAPI runs
on `127.0.0.1:8000` in local development and publishes its generated OpenAPI
documentation.

The initial API exposes `GET /health/live`. The endpoint returns a small typed
response identifying the API and its healthy state. It does not query databases
or external services because liveness must describe the process itself.

### Worker application

`apps/worker` is an installable Python package using a `src` layout. It runs as
a long-lived process rather than an HTTP server.

The initial worker logs structured lifecycle events, waits for future work, and
shuts down cleanly after `SIGINT` or `SIGTERM`. Queue polling and processing are
deferred until the messaging infrastructure exists. The process structure must
make the waiting loop independently testable without sending operating-system
signals from unit tests.

## Developer Command Surface

The Makefile exposes the following public targets:

| Target | Responsibility |
| --- | --- |
| `make help` | Describe the supported developer commands. |
| `make setup` | Verify pinned tools and install locked dependencies. |
| `make dev` | Start web, API, and worker with labelled output. |
| `make dev-web` | Start only the Next.js development server. |
| `make dev-api` | Start only FastAPI with reload enabled. |
| `make dev-worker` | Start only the Python worker. |
| `make format` | Apply TypeScript and Python formatting. |
| `make lint` | Run ESLint and Ruff. |
| `make typecheck` | Run the TypeScript compiler and mypy. |
| `make test` | Run Vitest and pytest suites. |
| `make build` | Build the web application and Python packages. |
| `make check` | Run formatting checks, linting, type-checking, tests, and builds. |

The JavaScript workspace includes a lightweight concurrent process runner.
`make dev` uses it to label output from `web`, `api`, and `worker`, forward
interrupt signals, and terminate the remaining processes when one exits
unexpectedly.

Each Make target delegates to visible pnpm or uv commands. A developer can run
the underlying application commands directly when debugging a single runtime.

## Configuration

Local defaults allow `make dev` to run without secrets. The web application
uses an environment variable for the server-side API base URL and defaults to
`http://127.0.0.1:8000` in local development.

An example environment file documents supported variables without containing
credentials. Machine-specific paths, generated environments, dependency
directories, coverage output, and local environment files are ignored by Git.

## Error Handling

- Toolchain validation stops setup before dependency installation when an
  active version is incorrect and prints the expected and actual versions.
- The web health client applies a bounded timeout and treats non-success
  responses, invalid response bodies, and connection failures as unavailable.
- The API liveness endpoint has no dependency calls and remains deterministic.
- The worker records startup and shutdown and exits successfully after a normal
  termination request.
- The combined development command terminates sibling processes if any process
  fails, preventing a partially running local environment from appearing
  healthy.

## Quality Tooling

The web application uses:

- ESLint for linting;
- TypeScript for static type-checking;
- Vitest for test execution; and
- React Testing Library for component behavior.

The Python applications use:

- Ruff for formatting and linting;
- mypy for static type-checking; and
- pytest for test execution.

Tool configuration is centralized at the nearest shared workspace root unless
an application requires an explicit local override.

## Verification Strategy

Automated verification includes:

- a web test for the connected API state;
- a web test for the unavailable API state;
- an API contract test for `GET /health/live`;
- worker tests for startup, waiting, and graceful shutdown behavior;
- TypeScript and Python formatting checks;
- linting and type-checking across both ecosystems;
- independent production builds for the web, API, and worker; and
- the aggregate `make check` target.

Manual verification runs `make dev`, opens the web application at
`http://localhost:3000`, confirms that it reports the API as connected, inspects
the API documentation at `http://localhost:8000/docs`, verifies the worker
startup log, and confirms that one interrupt stops all three processes cleanly.

## Delivery

Implementation occurs on `feat/monorepo-foundation`. Changes are submitted
through a pull request targeting `main`, and the pull request includes the
automated and manual verification evidence. Only the repository owner merges
the pull request.
