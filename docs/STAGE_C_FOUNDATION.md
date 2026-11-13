# Stage C — Credentials, Configuration and Performance Management

Stage C starts from the accepted Stage B workspace authorization boundary and Stage A platform/secret-store contracts. Every managed resource is Project-scoped. Secret material must never be stored in SQLite, Run snapshots, configuration revisions, audit events, source YAML or API responses.

## P10 — Credential Vault Foundation

The Linux Secret Service adapter remains in place. Windows uses the native Credential Manager provider through the platform adapter. The Windows private-directory ACL adapter remains fail-closed pending its separate implementation. Hosted verification for the P10 integration correction: [workflow 43409741994](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/43409741994), all three jobs passed.

## P11 — Credential Management and Verification

Adds Project/device-scoped credential metadata, opaque OS-vault references, secret creation/rotation/revocation, append-only credential audit events, and read/manage/verify permission boundaries. SSH verification uses only configured devices and system-trusted host keys. Unknown hosts are rejected. Secret values and provider errors are not returned to the API.

## P12 — Configuration Schema Registry

Implemented: additive migration `20261113_08` (schema version 17), Project-scoped versioned schema definitions, a bounded JSON-Schema-like type registry, deterministic validation errors and `configurations.read/manage` permissions. The API supports listing and registering schema versions. Schemas reject unsupported keywords, open-ended object properties and sensitive credential-like property names. The existing configuration resolver remains unchanged; profile and revision lifecycle is P13.

## P13 — Configuration Revision and Resolution

Implemented: Project/Lab/Device-scoped profiles, validated draft revisions, canonical SHA-256 hashes, provenance, append-only revision content, publish, rollback as a new draft revision, target assignments, effective-value preview through the existing `ConfigurationResolver`, and safe YAML import with inline secret-field rejection. Assignment persists the selected published revision; it does not directly configure a physical device. Provider apply/reconciliation remains in Stage D.

## P14 — Configuration Management Frontend

Planned: Project/device/lab configuration workflows using the existing React shell, session and CSRF API client.

## P15 — Performance Policy Engine

Implemented: Project/Lab-scoped policy profiles, immutable versioned revisions, SHA-256 policy hashes, publish/assign lifecycle and an evaluator built on the existing `MeasurementPolicyEvaluator`. It enforces metric units, lower-/higher-is-better ordering, aggregate selection, minimum eligible samples, valid-status selection, retry policy and automatic warm-up exclusion. Evaluations return PASS/WARNING/FAIL/INSUFFICIENT_DATA/INVALID_DATA, effective thresholds and reasons. Physical Run snapshot integration remains a later end-to-end gate.

## P16 — Performance Policy Frontend

Planned: editable topology-specific policy profiles, effective-threshold preview and Run selection integration. The existing historic performance view remains available.

## Continuity and acceptance

- Stage B Project membership and Global/Project permission intersection remain the authority for access.
- Stage A secret-store, resolver, Run snapshot and telemetry contracts remain backward compatible.
- New migrations are additive and Alembic-managed; existing Runs and their config snapshots are not rewritten.
- CI acceptance is recorded separately from protected physical-lab verification.
