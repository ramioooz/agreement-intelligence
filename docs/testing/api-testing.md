# API and Insomnia testing

The FastAPI contract is available at <http://localhost:8000/openapi.json> and Swagger UI
at <http://localhost:8000/docs>. The checked-in Insomnia collection contains placeholders
only and must never be exported after adding private values.

## Contents

- [Prerequisites and safety](#prerequisites-and-safety)
- [Import and private environment](#import-and-private-environment)
- [Acquire a bearer token safely](#acquire-a-bearer-token-safely)
- [Scope and common headers](#scope-and-common-headers)
- [Request groups and contracts](#request-groups-and-contracts)
- [Negative and tenant-isolation testing](#negative-and-tenant-isolation-testing)
- [Collection/OpenAPI verification](#collectionopenapi-verification)
- [Cleanup](#cleanup)

## Prerequisites and safety

1. Start the full stack and run `make stack-check`.
2. Generate only synthetic fixtures from [Test data](test-data.md).
3. Import [`agreement-intelligence.yaml`](insomnia/agreement-intelligence.yaml).
4. Create a **private local sub-environment**. Do not save its values into the base
   environment or export it.
5. Use the seeded identities and ignored local password values. Never paste browser cookies,
   provider keys, production tokens, real emails, or documents into Insomnia.

The API uses bearer authentication plus `organization_id` and `workspace_id` query
parameters on scoped routes. A resource UUID is not authorization.

[Back to contents](#contents)

## Import and private environment

Set these values only in a private local sub-environment:

| Variable | Local value |
| --- | --- |
| `base_url` | `http://localhost:8000` |
| `authorize_url` | `http://localhost:8080/realms/agreement-intelligence/protocol/openid-connect/auth` |
| `token_url` | `http://localhost:8080/realms/agreement-intelligence/protocol/openid-connect/token` |
| `client_id` | Value of `OIDC_CLIENT_ID` |
| `client_secret` | Value of `OIDC_CLIENT_SECRET`; private, never exported |
| `username` / `password` | Selected demo identity and ignored local password; used only on the Keycloak page |
| `organization_id` | `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` |
| `workspace_id` | `bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb` |
| `access_token` | Short-lived OAuth result; private, clear after testing |
| Resource IDs | Copy synthetic IDs from prior responses only |
| `document_path` | Absolute path to a generated ignored synthetic fixture; never export |

Leave every resource ID empty until the creating/list request returns it. Use unique
`MQA-*` names and do not reuse IDs from another run.

[Back to contents](#contents)

## Acquire a bearer token safely

The default Keycloak web client intentionally enables authorization-code flow with PKCE and
disables password/direct-access and service-account grants. Do not weaken those settings or
send a password to the token endpoint.

Insomnia's OAuth callback URI varies by release. For a local manual run:

1. In Insomnia, choose OAuth 2.0 **Authorization Code**, PKCE **S256**, scope
   `openid profile email`, and note the exact callback URI Insomnia displays.
2. Open the local Keycloak admin console at <http://localhost:8080> and sign in with the
   ignored bootstrap-admin values.
3. In realm `agreement-intelligence`, client `agreement-intelligence-web`, append that exact
   callback URI to **Valid redirect URIs**. Preserve the existing web callback and do not
   add a wildcard.
4. Configure Insomnia with `authorize_url`, `token_url`, `client_id`, private
   `client_secret`, PKCE S256, and the displayed callback. Fetch a token and sign in on
   Keycloak with the selected seeded username/password.
5. Store the short-lived token only in the private environment as `access_token`.
6. After the run, revoke/clear the token and remove the temporary callback. `make
   stack-check` verifies the client is restored to the exact checked-in callback contract.

If the client/UI does not support this flow, mark bearer-dependent API cases Blocked with
the exact Insomnia version. Do not enable password grants as a workaround.

[Back to contents](#contents)

## Scope and common headers

Authenticated requests use:

```http
Authorization: Bearer {{ _.access_token }}
Accept: application/json
Content-Type: application/json
```

Multipart upload sets its own boundary. Most domain URLs include:

```text
?organization_id={{ _.organization_id }}&workspace_id={{ _.workspace_id }}
```

Expected denial semantics:

- `401`: missing, malformed, expired, unavailable, or wrong-client bearer;
- `403`: authenticated principal lacks a permission for a non-hidden action;
- `404`: resource/scope is hidden or absent, including many cross-tenant lookups;
- `409`: duplicate, illegal transition, optimistic conflict, or idempotency conflict;
- `422`: malformed UUID/query/body/file metadata rejected by validation;
- `429`: applicable tenant/rate/budget limit is exceeded.

Use the OpenAPI response definition for the exact route. Do not assume every authorization
denial uses the same status when resource existence must be hidden.

[Back to contents](#contents)

## Request groups and contracts

The collection includes these representative requests:

| Group/request | Method/path | Success | Denial/conflict and cleanup |
| --- | --- | ---: | --- |
| Health/liveness | `GET /health/live` | 200 without bearer | No cleanup |
| Health/readiness | `GET /health/ready` | 200 when dependencies ready | 503 when not ready; no cleanup |
| Identity/capabilities | `GET /identity/organizations/{organization_id}/workspaces/{workspace_id}/capabilities` | 200 | 401 invalid bearer; hidden denial for inaccessible scope |
| Agreements/list | `GET /agreements` | 200 | 401/hidden denial; read-only |
| Agreements/create | `POST /agreements` | 201 | 403/422; archive or permanently delete synthetic record |
| Documents/upload | `POST /documents` multipart | 201 | 409 duplicate, 415/type failure, 422 invalid scope; delete owning synthetic agreement |
| Processing/submit | `POST /agreements/{agreement_id}/processing-jobs` | 202 | 404/409; do not submit duplicate terminal work |
| Versions/list | `GET /agreements/{agreement_id}/versions` | 200 | 404 hidden/absent; read-only |
| Comparison/create | `POST /agreements/{agreement_id}/version-comparisons` | 202 | 404/409/422; keep only synthetic result |
| Playbooks/list | `GET /playbooks` | 200 | 401/hidden denial; read-only |
| Findings/evaluations | `GET /agreements/{agreement_id}/playbook-evaluations` | 200 | 404 hidden/absent; read-only |
| Search | `GET /search` | 200 | 401/hidden denial/422; read-only |
| Q&A/thread | `POST /questions/threads` | 201 | 401/403/422; synthetic thread may remain until stack cleanup |
| Q&A/turn | `POST /questions/threads/{thread_id}/turns` | 201 | 404 hidden/absent, 422; no provider success in no-key mode |
| Approval policies/list | `GET /approval-policies` | 200 for authorized scope | 401/hidden denial; read-only |
| Reviews/inbox | `GET /reviews/inbox` | 200 | 401/hidden denial; read-only |
| Reviews/timeline | `GET /reviews/{review_id}/timeline` | 200 | 404 hidden/absent; read-only |
| Final package | `GET /reviews/{review_id}/final-package` | 200 after terminal package exists | 404/409 before eligible state; read-only |
| Audit | `GET /audit-events` | 200 for audit permission | 403/hidden denial; read-only |
| Negative/cross scope | `GET /agreements` with `00000000-0000-4000-8000-000000000000` workspace | Hidden/empty denial per route | Never creates data |

Create Agreement body:

```json
{
  "title": "MQA-API-002 synthetic agreement",
  "agreement_type": "client_agreement",
  "status": "draft",
  "parties": [
    {"name": "Northstar Demo Markets Ltd", "role": "client"},
    {"name": "Cedar Demo Trading LLC", "role": "counterparty"}
  ],
  "files": [],
  "processing_state": "pending",
  "audit_metadata": {"source": "manual_qa"}
}
```

Processing body is `{"profile":"baseline"}`. Comparison body supplies the returned
`baseline_version_id` and `target_version_id` plus
`"analysis_version":"version-comparison.v1"`. Question-thread body optionally includes
`agreement_ids`; turn body is `{"question":"What termination notice is stated?"}`.

For mutating requests, send once, capture status/ID, repeat once only when testing the
documented duplicate/idempotency contract, and clean up using the UI or authorized API
workflow. Never delete shared/demo policy records.

[Back to contents](#contents)

## Negative and tenant-isolation testing

Run each request with:

1. no `Authorization` header;
2. `Authorization: Bearer invalid` (synthetic literal, not a token);
3. an expired/revoked short-lived token;
4. a valid business-approver token against an admin-only operation;
5. a valid token with a random organization/workspace UUID;
6. a valid token with a synthetic agreement/review ID from a second temporary workspace;
7. malformed UUID/body/query values; and
8. a duplicate checksum or illegal state transition where the contract supports it.

The response must not reveal another tenant's title, parties, filename, citation text,
status, package metadata, trace details, or existence. Inspect application audit evidence
with the authorized administrator; do not query the database as a substitute for API
authorization testing.

[Back to contents](#contents)

## Collection/OpenAPI verification

With the stack running:

```bash
OPENAPI_URL=http://localhost:8000/openapi.json node scripts/check-doc-links.mjs
tests/docs/test-documentation-contract.sh
```

The checker validates relative documentation targets/anchors and verifies each collection
API path against the running OpenAPI schema. The documentation contract rejects committed
bearer values, provider-key patterns, cookies, placeholders such as insecure default
secrets, and real-looking email domains.

Insomnia request/response history and private environments are local application data. Do
not commit or attach an export after executing requests.

[Back to contents](#contents)

## Cleanup

1. Delete/archive only `MQA-*` synthetic records according to the case.
2. Revoke/clear `access_token` and all private environment values.
3. Remove the temporary Insomnia redirect URI from Keycloak.
4. Run `make stack-check` to prove the web-client redirect contract is restored.
5. Delete local Insomnia request history/export files and generated fixtures when evidence
   is recorded.
6. Run `git status --short` and confirm no environment, token, cookie, or API export is
   tracked.

See [Manual QA](manual-test-plan.md), [Test data](test-data.md), and
[Evidence template](evidence-template.md).

[Back to top](#api-and-insomnia-testing)
