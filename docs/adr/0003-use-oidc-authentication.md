# ADR 0003: Use OIDC Authentication

## Status

Accepted

## Context

The platform handles confidential legal documents and requires enterprise
identity controls such as MFA, account disabling, session expiry, and
federation. Building password storage, credential recovery, MFA, and identity
lifecycle management would add substantial security risk without
differentiating the product.

Local development must remain possible without a cloud account. Production
must support a managed identity service and enterprise federation.

## Decision

Use OpenID Connect with the authorization-code flow and PKCE. Authentication is
delegated to a standards-based identity provider.

The platform provides a branded sign-in entry page, but it does not store or
validate passwords. The identity provider handles credentials and MFA.

The web server completes the authorization-code exchange and maintains the
application session. Provider tokens remain outside browser JavaScript. Session
cookies are:

- HTTP-only;
- secure in non-local environments;
- protected with an appropriate same-site policy;
- rotated or invalidated at authentication boundaries; and
- limited by idle and absolute expiry.

Local development uses a containerized identity provider with seeded,
non-production accounts. The AWS reference environment uses a managed OIDC
identity service and supports federation with an enterprise identity system.

The platform identifies people using the provider issuer and immutable subject
identifier. Email address is profile data, not a stable authorization key.

Authentication claims establish identity only. Organization membership, roles,
workspace access, and agreement permissions are stored and evaluated by the
application.

Self-registration is disabled for the first release. An administrator invites
or provisions users and assigns application membership separately.

## Alternatives considered

### Application-owned passwords

This provides full UI control but makes the platform responsible for password
storage, recovery, MFA, breach response, and identity hardening. It is rejected.

### Social sign-in as the primary model

This is convenient for consumer applications but does not meet the initial
enterprise identity and lifecycle requirements.

### Cloud-only identity in every environment

This maximizes environment consistency but makes local development dependent on
network access, cloud configuration, and shared credentials.

### Browser-managed bearer tokens

This simplifies direct API access but exposes valuable tokens to browser
JavaScript and increases the impact of cross-site scripting.

## Consequences

### Positive

- The platform avoids handling user passwords.
- MFA and enterprise identity controls remain the provider's responsibility.
- A standard protocol permits local and managed provider implementations.
- Server-side sessions reduce browser token exposure.
- Identity and application authorization remain cleanly separated.

### Negative

- Local development requires an identity-provider container.
- Logout, refresh, invitation, disabled-user, and federation flows require
  integration testing.
- Provider configuration and claim mapping differ by environment.
- Operational outages at the identity provider can prevent new sessions.

### Required controls

- Validate issuer, audience, signature, expiry, nonce, and state.
- Use PKCE and defend authentication callbacks against replay.
- Rotate secrets and keep them outside source control.
- Test session expiry, logout, disabled accounts, and tenant switching.
- Never grant application roles from untrusted client-supplied claims.
- Audit membership and role changes.
