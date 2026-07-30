# Local Auth Dashboard Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one Sprint 0 PR that lets seeded Keycloak users sign in, keep a server-side application session, open a protected dashboard shell, and sign out.

**Architecture:** The web app uses Auth.js with the existing Keycloak OIDC client. Browser-facing authorization uses the local Keycloak URL, while server-side token and profile calls can use the Compose-internal Keycloak URL. The dashboard shell is honest placeholder navigation only; domain data and role enforcement remain later work.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Auth.js / `next-auth` v5 beta, Keycloak 26, Docker Compose.

## Global Constraints

- One PR covers #5 and #6.
- Use the existing Keycloak realm and confidential OIDC client.
- Provider tokens must remain outside browser JavaScript.
- Session cookies must be HTTP-only, same-site protected, secure outside local development, and predictably expiring.
- Protected routes must reject unauthenticated requests.
- The dashboard must not show fake agreement data.
- Do not add Microsoft/Cognito federation, organization models, RBAC, API bearer-token authorization, or document workflows in this PR.
- Do not push to or merge into `main`.
- Do not include assistant, vendor, model-provider, or tool branding in branch names, commits, PR text, or delivery metadata.

---

### Task 1: Auth configuration and routes

**Files:**

- Modify: `apps/web/package.json`
- Modify: `pnpm-lock.yaml`
- Modify: `.env.example`
- Modify: `apps/web/.env.example`
- Modify: `compose.yaml`
- Create: `apps/web/src/auth.ts`
- Create: `apps/web/src/app/api/auth/[...nextauth]/route.ts`
- Create: `apps/web/src/proxy.ts`
- Create: `tests/web/test-auth-contract.sh`
- Modify: `Makefile`

**Produces:** `auth`, `signIn`, `signOut`, and `handlers` exports used by pages and routes.

- [x] Add `next-auth@5.0.0-beta.32`.
- [x] Configure Keycloak authorization-code flow with server-held client secret.
- [x] Add local and Compose OIDC environment variables.
- [x] Protect `/dashboard`.
- [x] Add a shell contract test that verifies route/config files exist and deferred scope is absent.

### Task 2: Sign-in and dashboard shell

**Files:**

- Modify: `apps/web/src/app/page.tsx`
- Create: `apps/web/src/app/sign-in/page.tsx`
- Create: `apps/web/src/app/dashboard/page.tsx`
- Create: `apps/web/src/components/sign-in-panel.tsx`
- Create: `apps/web/src/components/sign-in-panel.test.tsx`
- Create: `apps/web/src/components/dashboard-shell.tsx`
- Create: `apps/web/src/components/dashboard-shell.test.tsx`

**Consumes:** `signIn`, `signOut`, and `auth` exports from Task 1.

- [x] Build a public landing/sign-in experience that explains the product and delegates credentials to Keycloak.
- [x] Build a protected dashboard shell with account context and honest placeholder navigation.
- [x] Add logout that clears the application session and returns to `/sign-in`.
- [x] Add component tests for the sign-in and dashboard shell.

### Task 3: Verification and PR

**Files:**

- Modify: `README.md`

**Consumes:** completed auth and dashboard behavior.

- [x] Document local sign-in and logout in the stack instructions.
- [x] Run `make check`.
- [x] Run `tests/web/test-auth-contract.sh`.
- [x] Run `git diff --check`.
- [ ] Open one ready PR referencing #5 and #6.
