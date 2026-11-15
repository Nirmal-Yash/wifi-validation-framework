# Stage C — Credentials, Configuration and Performance Management

Stage C starts from the accepted Stage B workspace authorization boundary and Stage A platform/secret-store contracts. Every managed resource is Project-scoped. Secret material must never be stored in SQLite, Run snapshots, configuration revisions, audit events, source YAML or API responses.

## P10 — Credential Vault Foundation

The Linux Secret Service adapter remains in place. Windows uses the native Credential Manager provider through the platform adapter. Stage D P17 closes the Windows private-directory ACL gap: new directories are created with inheritance disabled and one current-user Full Control rule; existing directories are accepted only after the protected owner/DACL is verified. Verification uses Windows PowerShell with argument-vector execution and fails closed when unavailable or unverified. The full Runner remains Linux-oriented for protected mac80211_hwsim operations; this ACL completion does not claim full Windows lab execution parity.

## P11 — Credential Management and Verification

Adds Project/device-scoped credential metadata, opaque OS-vault references, secret creation/rotation/revocation, append-only credential audit events, and read/manage/verify permission boundaries. SSH verification uses only configured devices and system-trusted host keys. Unknown hosts are rejected. Secret values and provider errors are not returned to the API.

## P12 — Configuration Schema Registry

Implemented: additive migration `20261113_08` (schema version 17), Project-scoped versioned schema definitions, a bounded JSON-Schema-like type registry, deterministic validation errors and `configurations.read/manage` permissions. The API supports listing and registering schema versions. Schemas reject unsupported keywords, open-ended object properties and sensitive credential-like property names. The existing configuration resolver remains unchanged; profile and revision lifecycle is P13.

## P13 — Configuration Revision and Resolution

Implemented: Project/Lab/Device-scoped profiles, validated draft revisions, canonical SHA-256 hashes, provenance, append-only revision content, publish, rollback as a new draft revision, target assignments, effective-value preview through the existing `ConfigurationResolver`, and safe YAML import with inline secret-field rejection. Assignment persists the selected published revision; it does not directly configure a physical device. Provider apply/reconciliation remains in Stage D.

## P14 — Configuration Management Frontend

Implemented: the React dashboard exposes Project-scoped credential records and lifecycle actions, schema registration, Project/Lab/Device configuration profiles, immutable revision history, publish/rollback, assignments, safe YAML import and effective-value/provenance preview. API client operations use the shared authenticated session, CSRF and idempotency handling. Assignment is not a provider deployment; the controlled provider apply/reconciliation is Stage D P24.

## P15 — Performance Policy Engine

Implemented: Project/Lab-scoped policy profiles, immutable versioned revisions, SHA-256 policy hashes, publish/assign lifecycle and an evaluator built on the existing `MeasurementPolicyEvaluator`. It enforces metric units, lower-/higher-is-better ordering, aggregate selection, minimum eligible samples, valid-status selection, retry policy and automatic warm-up exclusion. Evaluations return PASS/WARNING/FAIL/INSUFFICIENT_DATA/INVALID_DATA, effective thresholds and reasons. Physical Run snapshot integration remains a later end-to-end gate.

## P16 — Performance Policy Frontend

Implemented: the existing Performance page now retains metric history and adds a permission-gated Project/Lab policy workspace. Authorized users can create Project- or Lab-scoped profiles, edit JSON threshold definitions into draft revisions, inspect immutable history and hashes, publish revisions and assign them to Labs. The interface resolves the exact currently assigned published revision and displays its effective thresholds. Run launch can explicitly select the Lab-assigned revision; the API revalidates Project ownership, publication status and the exact Lab assignment, then passes the immutable revision ID and policy hash to the Runner environment and returns them in the accepted launch response. The frontend and API client use the existing session/CSRF/idempotency contract.

## Remaining cross-stage integration boundaries after P17–P18

- P10 now includes verified Windows private-directory ACL enforcement as well as Linux Secret Service and Windows Credential Manager storage.
- P13 assignment records desired configuration state; Stage D P24 closes the physical provider apply/reconciliation boundary with explicit, audited and non-destructive operations.
- P16 selects and pins the exact published policy revision/hash for a Run. Evaluation against collected Run metrics, persistence in Run snapshots and policy-result evidence remain the Stage E P28 integration gate; no synthetic result is claimed here.

## Continuity and acceptance

- Stage D P17/P18 device records remain Project/Lab-scoped and use the existing Stage B permission intersection.
- Stage B Project membership and Global/Project permission intersection remain the authority for access.
- Stage A secret-store, resolver, Run snapshot and telemetry contracts remain backward compatible.
- New migrations are additive and Alembic-managed; existing Runs and their config snapshots are not rewritten.
- CI acceptance is recorded separately from protected physical-lab verification.
