# Stage C — Credentials, Configuration and Performance Management

Stage C starts from the accepted Stage B workspace authorization boundary and Stage A platform/secret-store contracts. Every managed resource is Project-scoped. Secret material must never be stored in SQLite, Run snapshots, configuration revisions, audit events, source YAML or API responses.

## P10 — Credential Vault Foundation

The Linux Secret Service adapter remains in place. Windows uses the native Credential Manager provider through the platform adapter. The Windows private-directory ACL adapter remains fail-closed pending its separate implementation. Hosted verification for the P10 integration correction: [workflow 43409741994](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/43409741994), all three jobs passed.

## P11 — Credential Management and Verification

Adds Project/device-scoped credential metadata, opaque OS-vault references, secret creation/rotation/revocation, append-only credential audit events, and read/manage/verify permission boundaries. SSH verification uses only configured devices and system-trusted host keys. Unknown hosts are rejected. Secret values and provider errors are not returned to the API.

## P12 — Configuration Schema Registry

Planned: registered typed schemas, schema versioning, value validation and compatibility with the existing resolver. Profiles must not embed secrets; they may reference credential IDs.

## P13 — Configuration Revision and Resolution

Planned: immutable hash-addressed revisions, validated publishing, provenance, safe rollback as a new revision, deterministic resolution and legacy YAML import with inline-secret rejection.

## P14 — Configuration Management Frontend

Planned: Project/device/lab configuration workflows using the existing React shell, session and CSRF API client.

## P15 — Performance Policy Engine

Planned: Project/lab-scoped versioned thresholds and deterministic evaluation over eligible measurements. Metric units, threshold direction, sample sufficiency and warm-up exclusion remain explicit.

## P16 — Performance Policy Frontend

Planned: editable topology-specific policy profiles, effective-threshold preview and Run selection integration. The existing historic performance view remains available.

## Continuity and acceptance

- Stage B Project membership and Global/Project permission intersection remain the authority for access.
- Stage A secret-store, resolver, Run snapshot and telemetry contracts remain backward compatible.
- New migrations are additive and Alembic-managed; existing Runs and their config snapshots are not rewritten.
- CI acceptance is recorded separately from protected physical-lab verification.
