# ADR 0004: Use Hybrid Authorization

## Status

Accepted

## Context

Role-based access control alone is too broad for confidential agreements. Two
legal reviewers may share a role while belonging to different organizations,
workspaces, matters, or approval stages. A user with an administrative role in
one organization must not receive the same access in another.

Pure attribute-based policies can express these relationships but are harder
to understand and administer for the first release. UI-only restrictions are
not security controls.

## Decision

Use a hybrid authorization model combining:

1. role-based permissions;
2. mandatory tenant equality;
3. workspace and resource membership;
4. resource attributes such as confidentiality classification;
5. assignment or ownership; and
6. workflow state and approval-stage eligibility.

Initial roles are:

| Role | Purpose |
| --- | --- |
| Platform administrator | Operate platform configuration without bypassing audit controls |
| Organization administrator | Manage organization members, workspaces, and settings |
| Legal administrator | Manage playbooks, clause positions, and approval policies |
| Legal reviewer | Review findings and make assigned legal decisions |
| Business user | Upload, search, and monitor permitted agreements |
| Auditor | Read approved records, evidence, decisions, and audit history |

Roles map to explicit permissions such as:

```text
members:manage
agreements:create
agreements:read
agreements:update
reviews:assign
reviews:decide
reviews:approve
playbooks:manage
search:query
audit:read
```

The API calls an application-owned policy service for every protected
operation. Policy inputs are typed and include actor, tenant, permission,
resource, relevant attributes, and workflow state. Authorization failures use
consistent responses that do not reveal hidden resources.

PostgreSQL row-level security reinforces tenant isolation for tenant-owned
tables. The application sets tenant context for each transaction. Row-level
security is defense in depth and does not replace policy evaluation.

Mutable protected records use optimistic locking so authorization is evaluated
against the version the user actually reviewed.

The web interface reflects permissions for usability but never acts as the
enforcement boundary.

## Alternatives considered

### RBAC only

This is easy to administer but cannot safely express workspace, assignment,
confidentiality, or workflow-stage constraints.

### Attribute-based access control only

This is expressive but makes common business roles harder to administer and
explain in the first release.

### Database row-level security only

This protects database rows but does not express every workflow action,
external artifact, or domain-specific transition.

### External policy decision service from the start

This centralizes policy and can support multiple services. It is deferred until
policy complexity or independent services justify another runtime dependency.

## Consequences

### Positive

- Roles remain understandable to organization administrators.
- Resource and workflow conditions prevent overly broad role access.
- Tenant isolation has application and database enforcement.
- Policy logic is testable independently from route handlers.
- The policy boundary can later move to a dedicated decision service.

### Negative

- Policy tests require combinations of roles, resources, and workflow states.
- Database tenant context must be set correctly for every transaction.
- Administrators need clear explanations when an action is unavailable.
- Role and permission changes require audit and cache-invalidation discipline.

### Required controls

- Default to deny.
- Test cross-tenant access for every tenant-owned resource type.
- Centralize policy evaluation; do not scatter ad hoc role checks.
- Audit membership, role, playbook, and approval-policy changes.
- Keep service identities distinct from human identities.
- Verify permissions again when asynchronous work executes.
- Record introduction of an external policy engine in a new ADR.
