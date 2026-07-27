# Monorepo Foundation Implementation Plan

> Execute this plan task-by-task. Complete each verification step and commit
> before moving to the next task.

**Goal:** Deliver runnable Next.js, FastAPI, and Python worker applications
with pinned toolchains and one Make-based developer command surface.

**Architecture:** pnpm owns the TypeScript workspace, uv owns the Python
workspace, and Make delegates to both ecosystems. The web application performs
a bounded server-side API liveness check, while the worker remains a
queue-independent long-running process.

**Tech stack:** Node.js 22.23.1, pnpm 10.28.0, Next.js 16.2.12, React 19.2.8,
Python 3.13.14, uv, FastAPI 0.140.0, pytest, Vitest, ESLint, Prettier, Ruff,
mypy, Tailwind CSS, and GNU Make.

## Global Constraints

- Work only on `feat/monorepo-foundation`.
- Target `main` through a pull request; only the repository owner merges.
- Do not add assistant, vendor, or model-provider branding to delivery metadata.
- Do not add authentication, databases, containers, LocalStack, SQS, or document
  processing in this story.
- Lock all resolved JavaScript and Python dependencies.
- Use Conventional Commits and run the stated verification before each commit.

## Planned File Map

```text
.
├── .gitignore
├── .node-version
├── .python-version
├── Makefile
├── package.json
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── pyproject.toml
├── uv.lock
├── apps/
│   ├── web/
│   │   ├── .env.example
│   │   ├── eslint.config.mjs
│   │   ├── next-env.d.ts
│   │   ├── next.config.ts
│   │   ├── package.json
│   │   ├── postcss.config.mjs
│   │   ├── tsconfig.json
│   │   ├── vitest.config.ts
│   │   └── src/
│   │       ├── app/{globals.css,layout.tsx,page.tsx}
│   │       ├── components/{api-status.test.tsx,api-status.tsx}
│   │       ├── lib/{api-health.test.ts,api-health.ts}
│   │       └── test/setup.ts
│   ├── api/
│   │   ├── pyproject.toml
│   │   ├── src/agreement_intelligence_api/{__init__.py,health.py,main.py}
│   │   └── tests/test_health.py
│   └── worker/
│       ├── pyproject.toml
│       ├── src/agreement_intelligence_worker/
│       │   ├── __init__.py
│       │   ├── lifecycle.py
│       │   ├── logging_config.py
│       │   └── main.py
│       └── tests/{test_lifecycle.py,test_logging.py}
└── README.md
```

---

### Task 1: Configure the workspace and pinned toolchains

**Files:**

- Create: `.node-version`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `pyproject.toml`
- Create: `apps/web/package.json`
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/src/agreement_intelligence_api/__init__.py`
- Create: `apps/worker/pyproject.toml`
- Create: `apps/worker/src/agreement_intelligence_worker/__init__.py`
- Generate: `pnpm-lock.yaml`
- Generate: `uv.lock`

**Produces:**

- pnpm package `@agreement-intelligence/web`
- uv packages `agreement-intelligence-api` and
  `agreement-intelligence-worker`
- one locked environment for each ecosystem

- [ ] **Step 1: Activate the pinned Node.js version**

Install Node.js `22.23.1` with your preferred Node version manager or the
official installer, then verify:

```bash
node --version
pnpm --version
```

Expected:

```text
v22.23.1
10.28.0
```

- [ ] **Step 2: Create the runtime pins**

`.node-version`:

```text
22.23.1
```

`.python-version`:

```text
3.13.14
```

- [ ] **Step 3: Create the root JavaScript workspace**

`package.json`:

```json
{
  "name": "agreement-intelligence",
  "version": "0.1.0",
  "private": true,
  "packageManager": "pnpm@10.28.0",
  "engines": {
    "node": "22.23.1",
    "pnpm": "10.28.0"
  },
  "scripts": {
    "dev": "concurrently --kill-others-on-fail --names web,api,worker --prefix-colors blue,green,magenta \"pnpm --filter @agreement-intelligence/web dev\" \"uv run --package agreement-intelligence-api uvicorn agreement_intelligence_api.main:app --reload --host 127.0.0.1 --port 8000\" \"uv run --package agreement-intelligence-worker agreement-worker\"",
    "format": "prettier --write .",
    "format:check": "prettier --check ."
  },
  "devDependencies": {
    "concurrently": "10.0.4",
    "prettier": "3.9.6"
  },
  "pnpm": {
    "onlyBuiltDependencies": [
      "sharp",
      "unrs-resolver"
    ]
  }
}
```

`pnpm-workspace.yaml`:

```yaml
packages:
  - apps/web

engineStrict: true
```

- [ ] **Step 4: Create the root Python workspace**

`pyproject.toml`:

```toml
[project]
name = "agreement-intelligence"
version = "0.1.0"
requires-python = "==3.13.*"
dependencies = []

[dependency-groups]
dev = [
  "httpx2==2.9.1",
  "mypy==2.3.0",
  "pytest==9.1.1",
  "ruff==0.16.0",
]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["apps/api", "apps/worker"]

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["B", "E", "F", "I", "SIM", "UP"]

[tool.pytest.ini_options]
addopts = "-ra --strict-config --strict-markers"
testpaths = ["apps/api/tests", "apps/worker/tests"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_unreachable = true
```

- [ ] **Step 5: Create the web package manifest**

Create `apps/web/package.json`:

```json
{
  "name": "@agreement-intelligence/web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "next": "16.2.12",
    "react": "19.2.8",
    "react-dom": "19.2.8"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "4.3.3",
    "@testing-library/jest-dom": "7.0.0",
    "@testing-library/react": "16.3.2",
    "@types/node": "22.20.1",
    "@types/react": "19.2.17",
    "@types/react-dom": "19.2.3",
    "@vitejs/plugin-react": "6.0.4",
    "eslint": "9.39.5",
    "eslint-config-next": "16.2.12",
    "jsdom": "29.1.1",
    "tailwindcss": "4.3.3",
    "typescript": "6.0.3",
    "vite": "8.1.5",
    "vitest": "4.1.10"
  }
}
```

- [ ] **Step 6: Create the Python package manifests**

`apps/api/pyproject.toml`:

```toml
[project]
name = "agreement-intelligence-api"
version = "0.1.0"
requires-python = "==3.13.*"
dependencies = [
  "fastapi==0.140.0",
  "pydantic==2.13.4",
  "uvicorn[standard]==0.51.0",
]

[build-system]
requires = ["uv_build==0.11.32"]
build-backend = "uv_build"
```

`apps/worker/pyproject.toml`:

```toml
[project]
name = "agreement-intelligence-worker"
version = "0.1.0"
requires-python = "==3.13.*"
dependencies = []

[project.scripts]
agreement-worker = "agreement_intelligence_worker.main:main"

[build-system]
requires = ["uv_build==0.11.32"]
build-backend = "uv_build"
```

- [ ] **Step 7: Create importable package roots**

`apps/api/src/agreement_intelligence_api/__init__.py`:

```python
__version__ = "0.1.0"
```

`apps/worker/src/agreement_intelligence_worker/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 8: Add generated-file exclusions**

Create `.gitignore`:

```gitignore
# JavaScript
node_modules/
.next/
out/

# Python
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Tests and builds
coverage/
htmlcov/
dist/

# Local configuration
.env
.env.local
.env.*.local

# Editors and operating systems
.DS_Store
.idea/
.vscode/
```

- [ ] **Step 9: Install and lock dependencies**

```bash
uv python install 3.13.14
pnpm install
uv lock
uv sync --all-packages
```

Expected: `pnpm-lock.yaml`, `uv.lock`, `node_modules`, and `.venv` are created;
only the two lockfiles appear as untracked output.

- [ ] **Step 10: Verify the workspace resolution**

```bash
pnpm --filter @agreement-intelligence/web exec next --version
uv run --package agreement-intelligence-api python --version
uv run --package agreement-intelligence-worker python --version
git diff --check
```

Expected: Next.js `16.2.12`, Python `3.13.14` for both packages, and no
whitespace errors.

- [ ] **Step 11: Commit the workspace**

```bash
git add .node-version .python-version .gitignore package.json \
  pnpm-workspace.yaml pnpm-lock.yaml pyproject.toml uv.lock \
  apps/web/package.json apps/api/pyproject.toml \
  apps/api/src/agreement_intelligence_api/__init__.py \
  apps/worker/pyproject.toml \
  apps/worker/src/agreement_intelligence_worker/__init__.py
git commit -m "chore: configure monorepo toolchains"
```

---

### Task 2: Add the FastAPI liveness contract

**Files:**

- Create: `apps/api/src/agreement_intelligence_api/health.py`
- Create: `apps/api/src/agreement_intelligence_api/main.py`
- Create: `apps/api/tests/test_health.py`

**Produces:**

- ASGI application `agreement_intelligence_api.main:app`
- `GET /health/live`
- response contract `{status, service, version}`

- [ ] **Step 1: Write the failing API contract test**

`apps/api/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from agreement_intelligence_api.main import app


def test_liveness_contract() -> None:
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "version": "0.1.0",
    }
```

- [ ] **Step 2: Run the test and confirm the expected failure**

```bash
uv run pytest apps/api/tests/test_health.py -v
```

Expected: collection fails because `agreement_intelligence_api.main` does not
exist.

- [ ] **Step 3: Implement the minimum health contract**

`apps/api/src/agreement_intelligence_api/health.py`:

```python
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from agreement_intelligence_api import __version__

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["api"] = "api"
    version: str = __version__


@router.get("/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse()
```

`apps/api/src/agreement_intelligence_api/main.py`:

```python
from fastapi import FastAPI

from agreement_intelligence_api import __version__
from agreement_intelligence_api.health import router as health_router

app = FastAPI(
    title="Agreement Intelligence API",
    version=__version__,
)
app.include_router(health_router)
```

- [ ] **Step 4: Run the focused API checks**

```bash
uv run pytest apps/api/tests/test_health.py -v
uv run ruff check apps/api
uv run ruff format --check apps/api
uv run mypy apps/api/src apps/api/tests
uv build --package agreement-intelligence-api --out-dir dist/api
```

Expected: all commands pass and the API wheel and source distribution appear
under `dist/api`.

- [ ] **Step 5: Commit the API**

```bash
git add apps/api
git commit -m "feat(api): add liveness endpoint"
```

---

### Task 3: Add the long-running worker lifecycle

**Files:**

- Create: `apps/worker/src/agreement_intelligence_worker/lifecycle.py`
- Create: `apps/worker/src/agreement_intelligence_worker/logging_config.py`
- Create: `apps/worker/src/agreement_intelligence_worker/main.py`
- Create: `apps/worker/tests/test_lifecycle.py`
- Create: `apps/worker/tests/test_logging.py`

**Produces:**

- command `agreement-worker`
- coroutine `run_worker(stop_event: asyncio.Event) -> None`
- newline-delimited JSON lifecycle logs

- [ ] **Step 1: Write the failing lifecycle test**

`apps/worker/tests/test_lifecycle.py`:

```python
import asyncio
import logging

from _pytest.logging import LogCaptureFixture

from agreement_intelligence_worker.lifecycle import run_worker


def test_worker_waits_until_stop_is_requested(caplog: LogCaptureFixture) -> None:
    async def exercise() -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(run_worker(stop_event))

        await asyncio.sleep(0)
        assert not task.done()

        stop_event.set()
        await asyncio.wait_for(task, timeout=1)

    with caplog.at_level(logging.INFO, logger="agreement_intelligence.worker"):
        asyncio.run(exercise())

    events = [getattr(record, "event", None) for record in caplog.records]
    assert events == ["worker.started", "worker.stopped"]
```

- [ ] **Step 2: Run the test and confirm the expected failure**

```bash
uv run pytest apps/worker/tests/test_lifecycle.py -v
```

Expected: collection fails because the worker lifecycle module does not exist.

- [ ] **Step 3: Implement the lifecycle**

`apps/worker/src/agreement_intelligence_worker/lifecycle.py`:

```python
import asyncio
import logging

logger = logging.getLogger("agreement_intelligence.worker")


async def run_worker(stop_event: asyncio.Event) -> None:
    logger.info(
        "worker started",
        extra={"event": "worker.started", "service": "worker"},
    )
    await stop_event.wait()
    logger.info(
        "worker stopped",
        extra={"event": "worker.stopped", "service": "worker"},
    )
```

- [ ] **Step 4: Add a failing structured-log test**

`apps/worker/tests/test_logging.py`:

```python
import json
import logging

from agreement_intelligence_worker.logging_config import JsonFormatter


def test_json_formatter_preserves_lifecycle_fields() -> None:
    record = logging.LogRecord(
        name="agreement_intelligence.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="worker started",
        args=(),
        exc_info=None,
    )
    setattr(record, "event", "worker.started")
    setattr(record, "service", "worker")

    payload = json.loads(JsonFormatter().format(record))

    assert payload == {
        "event": "worker.started",
        "level": "INFO",
        "message": "worker started",
        "service": "worker",
    }
```

Run:

```bash
uv run pytest apps/worker/tests/test_logging.py -v
```

Expected: collection fails because `logging_config` does not exist.

- [ ] **Step 5: Implement JSON logging and signal-aware startup**

`apps/worker/src/agreement_intelligence_worker/logging_config.py`:

```python
import json
import logging


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "event": getattr(record, "event", "log"),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": getattr(record, "service", "worker"),
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("agreement_intelligence.worker")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
```

`apps/worker/src/agreement_intelligence_worker/main.py`:

```python
import asyncio
import signal

from agreement_intelligence_worker.lifecycle import run_worker
from agreement_intelligence_worker.logging_config import configure_logging


async def serve() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    await run_worker(stop_event)


def main() -> None:
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the focused worker checks**

```bash
uv run pytest apps/worker/tests -v
uv run ruff check apps/worker
uv run ruff format --check apps/worker
uv run mypy apps/worker/src apps/worker/tests
uv build --package agreement-intelligence-worker --out-dir dist/worker
```

Expected: all commands pass and distributions appear under `dist/worker`.

- [ ] **Step 7: Manually verify shutdown**

```bash
uv run --package agreement-intelligence-worker agreement-worker
```

Expected: one JSON `worker.started` line appears. Press Control-C and confirm
that one JSON `worker.stopped` line appears and the process exits successfully.

- [ ] **Step 8: Commit the worker**

```bash
git add apps/worker
git commit -m "feat(worker): add graceful process lifecycle"
```

---

### Task 4: Add the Next.js application shell and API status

**Files:**

- Create: `apps/web/.env.example`
- Create: `apps/web/eslint.config.mjs`
- Create: `apps/web/next-env.d.ts`
- Create: `apps/web/next.config.ts`
- Create: `apps/web/postcss.config.mjs`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/lib/api-health.test.ts`
- Create: `apps/web/src/lib/api-health.ts`
- Create: `apps/web/src/components/api-status.test.tsx`
- Create: `apps/web/src/components/api-status.tsx`
- Create: `apps/web/src/app/globals.css`
- Create: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/app/page.tsx`

**Produces:**

- Next.js application on port `3000`
- `getApiConnectionStatus()` server-side health client
- accessible API connection status in the application shell

- [ ] **Step 1: Add Next.js, lint, TypeScript, and test configuration**

`apps/web/next-env.d.ts`:

```typescript
/// <reference types="next" />
/// <reference types="next/image-types/global" />

// This file is generated and maintained by Next.js.
```

`apps/web/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {};

export default nextConfig;
```

`apps/web/postcss.config.mjs`:

```javascript
export default {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
```

`apps/web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": [
    "next-env.d.ts",
    ".next/types/**/*.ts",
    ".next/dev/types/**/*.ts",
    "**/*.ts",
    "**/*.tsx"
  ],
  "exclude": ["node_modules"]
}
```

`apps/web/eslint.config.mjs`:

```javascript
import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypeScript,
  globalIgnores([".next/**", "out/**", "next-env.d.ts"]),
]);
```

`apps/web/vitest.config.ts`:

```typescript
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(projectRoot, "src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

`apps/web/src/test/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

Create `apps/web/.env.example`:

```dotenv
API_BASE_URL=http://127.0.0.1:8000
```

Do not create or commit `.env.local`; the code has the same safe local default.

- [ ] **Step 2: Write failing health-client tests**

`apps/web/src/lib/api-health.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";

import { getApiConnectionStatus } from "@/lib/api-health";

describe("getApiConnectionStatus", () => {
  it("returns connected for the expected healthy contract", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({ status: "ok", service: "api", version: "0.1.0" }),
        { status: 200 },
      ),
    );

    await expect(getApiConnectionStatus({ fetcher })).resolves.toBe("connected");
  });

  it("returns unavailable when the API cannot be reached", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new TypeError("connection refused"));

    await expect(getApiConnectionStatus({ fetcher })).resolves.toBe("unavailable");
  });

  it("returns unavailable for an invalid health response", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(JSON.stringify({ status: "ok" })));

    await expect(getApiConnectionStatus({ fetcher })).resolves.toBe("unavailable");
  });
});
```

- [ ] **Step 3: Run the tests and confirm the expected failure**

```bash
pnpm --filter @agreement-intelligence/web test -- src/lib/api-health.test.ts
```

Expected: the test fails because `api-health.ts` does not exist.

- [ ] **Step 4: Implement the bounded health client**

`apps/web/src/lib/api-health.ts`:

```typescript
export type ApiConnectionStatus = "connected" | "unavailable";

type HealthPayload = {
  status: "ok";
  service: "api";
  version: string;
};

type HealthOptions = {
  baseUrl?: string;
  fetcher?: typeof fetch;
  timeoutMs?: number;
};

function isHealthPayload(value: unknown): value is HealthPayload {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    payload.status === "ok" &&
    payload.service === "api" &&
    typeof payload.version === "string"
  );
}

export async function getApiConnectionStatus({
  baseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000",
  fetcher = fetch,
  timeoutMs = 1500,
}: HealthOptions = {}): Promise<ApiConnectionStatus> {
  try {
    const response = await fetcher(`${baseUrl}/health/live`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });

    if (!response.ok || !isHealthPayload(await response.json())) {
      return "unavailable";
    }

    return "connected";
  } catch {
    return "unavailable";
  }
}
```

Run the focused test again and expect all three cases to pass.

- [ ] **Step 5: Write failing component tests**

`apps/web/src/components/api-status.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiStatus } from "@/components/api-status";

describe("ApiStatus", () => {
  it("announces a connected API", () => {
    render(<ApiStatus status="connected" />);
    expect(screen.getByRole("status")).toHaveTextContent("API connected");
  });

  it("announces an unavailable API", () => {
    render(<ApiStatus status="unavailable" />);
    expect(screen.getByRole("status")).toHaveTextContent("API unavailable");
  });
});
```

Run:

```bash
pnpm --filter @agreement-intelligence/web test -- src/components/api-status.test.tsx
```

Expected: the test fails because `api-status.tsx` does not exist.

- [ ] **Step 6: Implement the status component**

`apps/web/src/components/api-status.tsx`:

```tsx
import type { ApiConnectionStatus } from "@/lib/api-health";

type ApiStatusProps = {
  status: ApiConnectionStatus;
};

export function ApiStatus({ status }: ApiStatusProps) {
  const connected = status === "connected";

  return (
    <p
      className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-medium ${
        connected
          ? "bg-emerald-100 text-emerald-800"
          : "bg-amber-100 text-amber-900"
      }`}
      role="status"
    >
      {connected ? "API connected" : "API unavailable"}
    </p>
  );
}
```

- [ ] **Step 7: Build the minimal application shell**

`apps/web/src/app/globals.css`:

```css
@import "tailwindcss";

:root {
  color-scheme: light;
  background: #f8fafc;
}

body {
  margin: 0;
  background:
    radial-gradient(circle at top left, rgb(226 232 240 / 70%), transparent 38%),
    #f8fafc;
  color: #0f172a;
  font-family: Arial, Helvetica, sans-serif;
}
```

`apps/web/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@/app/globals.css";

export const metadata: Metadata = {
  title: "Agreement Intelligence",
  description: "Human-controlled intelligence for financial agreements.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

`apps/web/src/app/page.tsx`:

```tsx
import { ApiStatus } from "@/components/api-status";
import { getApiConnectionStatus } from "@/lib/api-health";

export default async function Home() {
  const apiStatus = await getApiConnectionStatus();

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
      <p className="mb-4 text-sm font-semibold uppercase tracking-widest text-slate-500">
        Agreement Intelligence
      </p>
      <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-slate-950">
        Review financial agreements with traceable, human-controlled intelligence.
      </h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
        The application foundation is running. Document workflows will be added
        in the next delivery iterations.
      </p>
      <div className="mt-8">
        <ApiStatus status={apiStatus} />
      </div>
    </main>
  );
}
```

- [ ] **Step 8: Run the complete web checks**

```bash
pnpm --filter @agreement-intelligence/web lint
pnpm --filter @agreement-intelligence/web typecheck
pnpm --filter @agreement-intelligence/web test
pnpm --filter @agreement-intelligence/web build
```

Expected: all commands pass.

- [ ] **Step 9: Commit the web application**

```bash
git add apps/web
git commit -m "feat(web): add application shell and API status"
```

---

### Task 5: Add the Make command surface

**Files:**

- Create: `Makefile`
- Create: `.prettierignore`

**Produces:**

- public targets specified in the approved design
- early Node.js, pnpm, and uv validation
- one command that starts all three applications

- [ ] **Step 1: Add Prettier exclusions**

Create `.prettierignore`:

```text
.next
.venv
dist
docs
*.md
node_modules
pnpm-lock.yaml
uv.lock
apps/api
apps/worker
```

- [ ] **Step 2: Create the Makefile**

Create `Makefile` with literal tab characters before every recipe command:

<!-- markdownlint-disable MD010 -->

```make
SHELL := /bin/sh

NODE_VERSION ?= $(shell cat .node-version)
PYTHON_VERSION ?= $(shell cat .python-version)
PNPM_VERSION ?= $(shell node -p "require('./package.json').packageManager.split('@')[1]")

.PHONY: help check-toolchain setup dev dev-web dev-api dev-worker \
	format format-check lint typecheck test build check

help:
	@echo "Agreement Intelligence developer commands"
	@echo "  make setup         Verify tools and install locked dependencies"
	@echo "  make dev           Start web, API, and worker"
	@echo "  make dev-web       Start only the web application"
	@echo "  make dev-api       Start only the API"
	@echo "  make dev-worker    Start only the worker"
	@echo "  make format        Format TypeScript and Python"
	@echo "  make lint          Lint TypeScript and Python"
	@echo "  make typecheck     Type-check TypeScript and Python"
	@echo "  make test          Run JavaScript and Python tests"
	@echo "  make build         Build every application"
	@echo "  make check         Run all pre-review checks"

check-toolchain:
	@command -v node >/dev/null 2>&1 || { echo "Node.js is not installed."; exit 1; }
	@actual="$$(node --version)"; expected="v$(NODE_VERSION)"; \
		[ "$$actual" = "$$expected" ] || { \
			echo "Node.js version mismatch: expected $$expected, found $$actual."; \
			echo "Install or activate the version in .node-version."; \
			exit 1; \
		}
	@command -v pnpm >/dev/null 2>&1 || { echo "pnpm is not installed."; exit 1; }
	@actual="$$(pnpm --version)"; expected="$(PNPM_VERSION)"; \
		[ "$$actual" = "$$expected" ] || { \
			echo "pnpm version mismatch: expected $$expected, found $$actual."; \
			echo "Run: corepack install --global pnpm@$(PNPM_VERSION)"; \
			exit 1; \
		}
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed."; exit 1; }
	@echo "Toolchain versions are valid."

setup: check-toolchain
	uv python install $(PYTHON_VERSION)
	pnpm install --frozen-lockfile
	uv sync --all-packages --frozen

dev: check-toolchain
	pnpm dev

dev-web: check-toolchain
	pnpm --filter @agreement-intelligence/web dev

dev-api:
	uv run --package agreement-intelligence-api uvicorn \
		agreement_intelligence_api.main:app --reload --host 127.0.0.1 --port 8000

dev-worker:
	uv run --package agreement-intelligence-worker agreement-worker

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

- [ ] **Step 3: Verify target discovery and version failure behavior**

```bash
make help
make check-toolchain
```

Expected: `help` lists every public target and `check-toolchain` confirms the
pinned Node.js and pnpm versions plus uv availability.

Temporarily run with an incorrect expected value without editing files:

```bash
make check-toolchain NODE_VERSION=0.0.0
```

Expected: non-zero exit and a message that shows expected `v0.0.0`, the actual
Node.js version, and how to activate the pinned version.

- [ ] **Step 4: Run the aggregate verification**

```bash
make setup
make check
```

Expected: both commands pass from the repository root.

- [ ] **Step 5: Commit the command surface**

```bash
git add Makefile .prettierignore
git commit -m "chore: add developer command surface"
```

---

### Task 6: Document and smoke-test the walking skeleton

**Files:**

- Modify: `README.md`

**Produces:**

- clone-to-run instructions
- documented application URLs and command table
- recorded manual verification for the pull request

- [ ] **Step 1: Update the README**

Add this section before the existing Architecture section:

````markdown
## Local development

### Prerequisites

- Node.js 22.23.1
- pnpm 10.28.0
- Python 3.13.14, installed automatically by uv
- uv
- GNU Make

Install the locked dependencies and start all applications:

```bash
make setup
make dev
```

The local applications are available at:

- Web application: <http://localhost:3000>
- API liveness: <http://localhost:8000/health/live>
- API documentation: <http://localhost:8000/docs>

The worker starts as a long-running Python process and logs its lifecycle. It
does not consume messages until the queue infrastructure is delivered.

| Command | Purpose |
| --- | --- |
| `make help` | List supported commands. |
| `make setup` | Verify tools and install locked dependencies. |
| `make dev` | Start web, API, and worker. |
| `make dev-web` | Start only the web application. |
| `make dev-api` | Start only the API. |
| `make dev-worker` | Start only the worker. |
| `make format` | Format TypeScript and Python. |
| `make lint` | Lint TypeScript and Python. |
| `make typecheck` | Type-check TypeScript and Python. |
| `make test` | Run JavaScript and Python tests. |
| `make build` | Build every application. |
| `make check` | Run all pre-review checks. |

See the
[monorepo foundation design](docs/plans/2026-07-27-monorepo-foundation-design.md)
for the accepted scope and boundaries.
````

- [ ] **Step 2: Verify documentation formatting**

```bash
git diff --check
pnpm dlx markdownlint-cli2@0.23.1 README.md \
  docs/plans/2026-07-27-monorepo-foundation-design.md \
  docs/plans/2026-07-27-monorepo-foundation-implementation.md
```

Expected: both commands pass.

- [ ] **Step 3: Run the complete automated verification**

```bash
make check
git status --short
```

Expected: `make check` passes. Only the intended README change is uncommitted;
generated build output remains ignored.

- [ ] **Step 4: Run the manual business demonstration**

```bash
make dev
```

Verify:

1. `http://localhost:3000` displays the application shell and `API connected`.
2. `http://localhost:8000/health/live` returns the expected JSON contract.
3. `http://localhost:8000/docs` displays the OpenAPI interface.
4. The terminal includes a structured `worker.started` log.
5. Control-C stops web, API, and worker without leaving child processes.

Capture a screenshot of the application shell for the pull request.

- [ ] **Step 5: Commit the documentation**

```bash
git add README.md
git commit -m "docs: add local development guide"
```

- [ ] **Step 6: Perform the pre-review audit**

```bash
git diff --check origin/main...HEAD
git log --oneline origin/main..HEAD
git status --short --branch
make check
```

Expected:

- no whitespace errors;
- only Issue #2 commits are present;
- the working tree is clean; and
- the complete check passes immediately before push.

- [ ] **Step 7: Push and open a draft pull request**

Push only the feature branch:

```bash
git push -u origin feat/monorepo-foundation
```

Open a draft pull request targeting `main` with:

- title `Build the polyglot monorepo foundation`;
- `Closes #2`;
- a summary of the web, API, worker, and Make deliverables;
- exact automated verification commands and results;
- manual smoke-test results;
- the application screenshot; and
- confirmation that infrastructure and business capabilities remain deferred.

Move Issue #2 to `In review`. Do not merge the pull request.
