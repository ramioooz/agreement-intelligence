# Tenant-access incident

## Trigger and impact

A user can list, open, search, cite, review, download, or mutate a resource outside the
authorized organization/workspace. Treat even metadata-only exposure as a security
incident.

## Safe diagnostics

1. Capture the actor, organization/workspace IDs, resource type/ID, endpoint, time,
   correlation/trace ID, and expected permission.
2. Reproduce only with synthetic records in isolated tenants.
3. Inspect API, MCP, worker, and audit events by opaque identifiers. Never copy exposed
   document text into logs or tickets.
4. Confirm current role and workspace membership in the application database and
   identity-provider account separately.

## Containment and recovery

1. Revoke the affected workspace membership or disable the identity-provider account.
2. Stop API/MCP access if the scope is unknown and exposure is continuing.
3. Preserve append-only audit records and relevant safe logs.
4. Correct authorization/RLS only through a reviewed change; do not manually broaden
   database roles or disable row-level security.
5. Rotate credentials if token or session compromise is possible.

## Verification and evidence

Verify unauthorized browser, API, MCP, citation, package, and object requests fail;
authorized same-tenant access still works; RLS checks remain green; and audit history is
intact. Record affected IDs, time window, decisions, and verification evidence.

## Escalation and residual risk

Escalate immediately for confirmed disclosure or write access. Determine notification
obligations with the data owner; local testing cannot establish production legal duties.

