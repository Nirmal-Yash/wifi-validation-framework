# Stage B — Identity, Access Control and Workspace Administration

**Base:** Stage A + Stage B1 commit 1bd11565a8ee8b44acfbd70322a606b881766631  
**Target migration:** 20261113_06 · SQLite schema version 15  
**Stage B scope:** P04–P09

## Delivery contents

This implementation extends the Stage B1 Organization → Project → Lab and membership foundation with persistent identity, authorization, administration and browser workflows.

### P04 — Persistent identity and account lifecycle
- Database-backed user identities and Global/Project role assignments.
- Environment-configured local accounts retained as a first-login bootstrap path.
- Invitation, activation, password-reset and account-status transitions.
- Password hashes use Werkzeug scrypt; invitation and reset tokens are stored as SHA-256 hashes.
- Suspended/deactivated account and last-active Global Owner safeguards.

### P05 — Authentication and sessions
- Opaque random server-side session tokens; only token hashes are stored.
- Session expiry, sliding activity renewal, logout and server-side revocation.
- Account status and session validity checked on each authenticated API request.
- Existing HttpOnly/SameSite browser session and CSRF enforcement retained.

### P06 — Role and permission management
- Permission registry with Global and Project scopes.
- Built-in OWNER, ADMIN, OPERATOR and VIEWER role definitions.
- Custom role creation, permission assignment, role assignment and safe deletion policy.
- Effective Project permissions intersect with Global permissions; Project roles cannot elevate global authority.
- Built-in role definitions are immutable.

### P07 — Audit and administration
- Append-only audit records for account, role and administrative events.
- SQLite triggers reject audit-event updates and deletes.
- Account directory, invitations, status management, password reset issuance, session revocation and role administration APIs.
- The last active Global Owner cannot be suspended, deactivated or demoted.

### P08 — Organization, Project and Lab management
- Versioned APIs for Organization, Project, Lab and Project membership management.
- Persisted parent/child checks and Project ownership resolution for resource-bearing routes.
- Project membership is read during authorization; revocation affects the next API request.
- Project scope is applied to Run, test, telemetry, health, regression, artifact, baseline and firmware operations. Retry operations inherit the source Run's Project and Lab rather than silently falling back to the default Lab.
- The Run launch API requires Project and Lab identifiers for membership-scoped accounts, verifies the Lab belongs to the selected Project, and passes the identifiers into the pytest bootstrap. Wildcard local administrators retain the legacy unscoped API compatibility path.
- Historical Runs with no Project remain unowned; no synthetic workspace is assigned.

### P09 — Frontend administration
- Organization → Project → Lab workspace page.
- Project membership and custom Project role administration.
- Run launch selects an active Project and one of its active Labs; Run history exposes and filters by Project ID, while Run detail displays the ownership boundary.
- Dashboard launch and Run cancel/retry controls use effective permission codes, including custom roles, rather than only legacy role labels.
- Account invitation and lifecycle controls.
- Global role and permission editor, permission registry and audit history.
- Invitation activation and password-reset pages.
- Route visibility uses API-returned permission codes; backend remains authoritative.

## Migration and compatibility
- Revision 20261113_06 follows 20261112_05.
- Migration is forward-only. Take a verified SQLite backup with the existing migration manager before upgrade.
- Existing environment-configured local accounts bootstrap into persistent identity records on successful login.
- Wildcard bootstrap scope is persisted explicitly; named scopes migrate into Project memberships where their Projects exist.
- Existing Run, Attempt, TestResult, Artifact, baseline, CLI, pytest node ID, topology and capture contracts are intended to remain compatible.
- No cloud identity provider, email delivery provider, remote control plane or automatic GNS3 provisioning is introduced. Invitation/reset tokens are returned once for secure manual delivery.

## Verification gates
The acceptance suite covers account bootstrap and wildcard-scope persistence, invitation activation, token consumption, password reset, server-side session revocation, global and Project permission intersection, last Global/Project Owner safeguards, append-only audit events, membership revocation, Project/Lab Run launch validation, cross-Project denial, Run response ownership serialization and retry Project/Lab inheritance. Migration fixtures represent the historical schema being rewound and remove later-revision objects before resetting revision metadata.

**Hosted verification passed on 2026-11-13:** [workflow 43407044694](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/43407044694) completed all three quality jobs successfully. The backend correctness suite reported **398 passed, 7 skipped, 16 warnings**; API security boundary checks, strict source audit, frontend tests, production build, and dashboard startup/proxy/session smoke test also passed. The skipped tests remain outside the hardware-free hosted CI execution class. Hardware-dependent REAL_LAB/GNS3 and physical firmware evidence remains a separate protected validation gate.

## Operational note
Apply the normal database backup and Alembic upgrade procedure before running the new version against an existing SQLite database. Start with a configured Global Owner account, sign in once to bootstrap persistent identity, then create an Organization, Project and Lab before assigning scoped users.
