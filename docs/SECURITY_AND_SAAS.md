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

## 15. SaaS execution

Initial Cloud architecture is a modular Flask application with Celery workers, Redis and relational persistence.

Kubernetes and microservices are deferred until measured scale requires them.

## 16. Multi-tenant execution

The initial target is approximately 5–20 organizations with one lab each and low concurrent Run volume.

Tenant isolation is logical routing plus authorization.

A physical lab is an exclusive resource. Only one Run may own a lab at a time.

## 17. Runner disconnect

The Runner continues locally when the Cloud is temporarily unavailable. Raw execution state remains local and synchronizes later.

A Runner disconnect is infrastructure state, never a product regression.

## 18. Worker failure

Distinguish LAB_FAILED, RUNNER_DISCONNECTED, WORKER_CRASHED and TIMED_OUT from product-level failure.

An infrastructure fault must never contaminate product quality statistics.

## 19. Data lifecycle

Schema supports retain-until metadata, soft deletion, audit retention and contractual holds.

Exact commercial retention terms are deferred.

## 20. Data export

Project export should include Run metadata, TestResults, samples, statistics, baseline relationships, classifications, artifacts and evidence metadata.

## 21. Database isolation

Application-level tenant authorization is sufficient for the first Cloud release. Database-level isolation becomes a requirement only when compliance or scale justifies it.

## 22. Observability

New subsystems use structured JSON logging with request, Run, Attempt, TestResult, Device, Organization and Project correlation identifiers.

## 23. Security acceptance gate

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

## 24. Explicitly deferred security

Do not implement speculatively: enterprise SAML, HSMs, service mesh, database row-level isolation, multi-region infrastructure or advanced SIEM integration.