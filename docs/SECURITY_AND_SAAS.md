# NetRegress — Security, Identity and SaaS Architecture

## 1. Security objective

NetRegress controls network devices, firmware and potentially sensitive validation evidence. Security protects device control, firmware integrity, customer evidence and release-decision integrity.

Security is a parallel gate beginning in Phase 1S.

## 2. Trust zones

~~~text
CI / Customer
     |
     | HTTPS + signed request
     v
NetRegress Cloud
     |
     | outbound authenticated runner channel
     v
NetRegress Runner
     |
     +--- Lab
     +--- Physical devices
     +--- Virtual devices
~~~

The customer lab does not require an inbound public firewall rule.

## 3. Authority split

The Runner is authoritative for raw execution facts: commands, device state, measurements, PCAPs, logs and environment snapshots.

The Cloud is authoritative for business control: identity, project policy, baseline promotion, waivers, release state and organization management.

## 4. Credential handling

Tracked YAML must not contain operational credentials.

Allowed credential sources are environment variables for local operation, managed secret stores, and short-lived Cloud-issued Runner credentials.

Existing lab credentials are development-only and must never become the SaaS credential pattern.

## 5. Secret redaction

Secrets are scrubbed from logs, command output, exceptions, diagnostics, API responses, artifact metadata and Cloud synchronization.

Secret classes include SSH passwords, WiFi PSKs, access tokens, webhook secrets, authorization headers and firmware signing material.

## 6. Authentication

Local deployments require authentication before a dashboard is exposed beyond localhost.

Initial Cloud methods are email/password and OIDC. Enterprise SAML is deferred until an actual requirement exists.

## 7. Authorization

Roles:

~~~text
OWNER
ADMIN
OPERATOR
VIEWER
~~~

Operator may execute validation, modify lab configuration and flash compatible firmware after explicit confirmation.

Admin and Owner may promote baselines, issue waivers and delete artifacts.

Viewer is read-only.

## 8. Project isolation

Organization contains Projects. Project is the primary authorization boundary for devices, labs, Runs, baselines, artifacts and release policy.

Artifact ACLs always check Project authorization, even when Projects share one Organization.

## 9. Audit events

Immutable audit events are generated for authentication, role changes, firmware operations, flashing, rollback, baseline promotion, waiver creation, artifact deletion, lab mutations and Run cancellation.

Audit events contain actor, target, timestamp, Project, action result and correlation identifiers.

## 10. API security

All future APIs use version 1 under the /api/v1 namespace.

State-changing endpoints require authentication. Browser state-changing actions require CSRF protection.

CI triggers use signed HMAC payloads and idempotency keys. Runner calls use short-lived credentials.

## 11. Artifact security

Artifacts are never exposed through arbitrary filesystem paths.

Access flow:

~~~text
authenticate
→ authorize Project
→ authorize Artifact
→ controlled response
→ audit where required
~~~

Object storage and short-lived signed download URLs are a later scalability layer.

## 12. Firmware security

Before flashing:

1. identify device;
2. validate firmware metadata;
3. verify SHA-256;
4. verify signature where available;
5. verify device compatibility;
6. require explicit authorization.

Reject incompatible or unverifiable firmware.

## 13. Dangerous operations

Never automatic:

- firmware flash;
- rollback;
- physical power cycle;
- topology reset;
- GNS3 project recreation.

Each requires explicit authorization and an audit record.

## 14. Command security

All remote commands use CommandRunner.

Controls include structured arguments, explicit shell mode, destructive-command allow lists, timeout classes, centralized privilege handling, output redaction, command IDs, audit correlation and declared idempotency.

## 15. Phase 1S command controls implemented in the Runner

The Runner now enforces a shared CommandSecurityPolicy before transport execution. The default path is structured execution with shell syntax rejected. The temporary compatibility policy used by the existing pytest suite permits only documented read/diagnostic commands plus explicitly allow-listed lab mutations. Privilege normalization uses non-interactive sudo -n, command and output secrets are scrubbed, and each Run emits COMMAND_EXECUTED audit events plus a sensitive COMMAND_OUTPUT artifact. This is a Runner-side technical control; future Cloud role/project authorization remains the higher-level business authorization boundary.
## 16. SaaS execution

Initial Cloud architecture is a modular Flask application with Celery workers, Redis and relational persistence.

Kubernetes and microservices are deferred until measured scale requires them.

## 17. Multi-tenant execution

The initial target is approximately 5–20 organizations with one lab each and low concurrent Run volume.

Tenant isolation is logical routing plus authorization.

A physical lab is an exclusive resource. Only one Run may own a lab at a time.

## 18. Runner disconnect

The Runner continues locally when the Cloud is temporarily unavailable. Raw execution state remains local and synchronizes later.

A Runner disconnect is infrastructure state, never a product regression.

## 19. Worker failure

Distinguish LAB_FAILED, RUNNER_DISCONNECTED, WORKER_CRASHED and TIMED_OUT from product-level failure.

An infrastructure fault must never contaminate product quality statistics.

## 20. Data lifecycle

Schema supports retain-until metadata, soft deletion, audit retention and contractual holds.

Exact commercial retention terms are deferred.

## 21. Data export

Project export should include Run metadata, TestResults, samples, statistics, baseline relationships, classifications, artifacts and evidence metadata.

## 22. Database isolation

Application-level tenant authorization is sufficient for the first Cloud release. Database-level isolation becomes a requirement only when compliance or scale justifies it.

## 23. Observability

New subsystems use structured JSON logging with request, Run, Attempt, TestResult, Device, Organization and Project correlation identifiers.

## 24. Security acceptance gate

Before Cloud exposure:

- no tracked operational secrets;
- authentication enabled;
- Project authorization tested;
- artifact path traversal prevented;
- shell construction audited;
- command injection tested;
- redaction tested;
- privileged actions audited;
- CI signatures verified;
- Runner credentials short-lived.

## 25. Explicitly deferred security

Do not implement speculatively: enterprise SAML, HSMs, service mesh, database row-level isolation, multi-region infrastructure or advanced SIEM integration.


## 12A. Phase 9 firmware controls implemented

The Runner now enforces firmware-specific technical controls below the future Project/RBAC authority boundary:
- image SHA-256 verification before upload;
- optional detached signature verification;
- device-model compatibility checks;
- remote SHA-256 verification after upload;
- explicit authorization scope for every mutating firmware stage;
- firmware-specific destructive-command allowlisting;
- no automatic flash retry;
- no automatic rollback;
- lifecycle audit events for firmware stages.

Cloud/operator authorization remains the higher-level business authority and is not replaced by adapter-side checks.

## 18A. Iteration 19 Runner synchronization controls

The Runner never uploads arbitrary filesystem paths. Synchronization envelopes include artifact identifiers, display names, type, size, SHA-256, evidence state and sensitivity metadata; binary transfer remains a separate controlled capability.

The HTTPS transport requires an `https://` endpoint and sends the queue idempotency key as an HTTP idempotency header. Bearer-token support is optional and is supplied externally; credentials are not persisted in the queue.

Synchronization retries are transport retries only. They never retry device commands, firmware flashes or validation tests.

## 26. Iterations 20–22 Runner security/orchestration status
Tracked operational credentials are externalized through environment markers and resolved only at the connection boundary. Local authentication/RBAC is enforced at the dashboard API boundary. Deterministic configuration, environment fingerprinting, exclusive lab locking and Run orchestration are implemented. Cloud remains the higher-level business authority and is deferred until standalone Runner certification.


## 27. Iterations 23–25 security and control status
The Runner now records explicit failure classes, controls firmware mutation through authorization/state transitions, scopes exclusive execution through process and lab ownership, exposes state-changing APIs only behind RBAC, restricts release exceptions to explicit expiring waivers, and preserves raw execution evidence locally through outbound-only synchronization.


## 28. Iterations 26–27 security hardening
The Runner now has a durable idempotency store for state-changing API requests, bound to a request fingerprint to reject replayed keys with different payloads. Authenticated browser state changes require a session-bound CSRF token, login attempts are rate-limited, response security headers are applied centrally, and request bodies have a configured size limit.

Outbound synchronization requires HTTPS and rejects endpoints resolving to loopback/private/link-local/multicast/unspecified addresses. Firmware operation paths are confined to an explicit firmware root. Diagnostic bundles carry a deterministic audit-event chain digest. Operational recovery includes SQLite backup/restore, stale-lock recovery and retention controls.

Security audit tooling performs Python syntax, tracked-secret-pattern, shell-invocation and production TODO/FIXME checks, while CI also runs dependency consistency validation before the release policy gate.
