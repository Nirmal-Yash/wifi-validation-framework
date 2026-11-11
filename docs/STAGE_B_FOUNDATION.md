# Stage B — Project Ownership, Membership and Scoped Workspace

**Parent baseline:** Stage A commit `7d2037b5bc96f585ab3c07a4da3eb0a8818be769`  
**Stage B implementation order:** B1 → B2 → B3 → B4  
**Current checkpoint:** B1 — persistence and ownership foundation  
**Current Alembic head:** `20261112_05` (SQLite schema version 14)

## 1. Objective

Turn the Stage A Organization → Project → Lab entities into an enforceable local workspace boundary. Every new project-managed Run must be associated with a valid Project and Lab. Project membership must be durable, queryable and revocable. API authorization is enforced by the backend, and the React workspace presents the same scope without treating hidden controls as security.

This remains a local-first Runner. Stage B does not create a Cloud receiver, remote control plane, public ingress, PostgreSQL, a distributed task queue or automatic lab operations.

## 2. Bounded checkpoints

### B1 — Ownership persistence and migration (implemented checkpoint)

- Add `project_id` to the Run domain and SQLite persistence as a nullable, restrictive foreign key to Projects.
- Preserve all pre-existing Runs with `project_id = NULL`; never assign historical Runs to a made-up Project.
- Preserve Project ownership on retries; callers cannot move a retry into a different Project.
- Add durable `project_memberships` keyed by username and Project, with OWNER/ADMIN/OPERATOR/VIEWER role validation and actor/time provenance.
- Add repository methods for membership create/read/list/revoke.
- Advance Alembic to `20261112_05` and schema version 14 with a single forward-only revision.
- Add migration, ownership, membership and retry-lineage tests.
- Include Stage A platform/resource tests in the hosted backend gate.

### B2 — Authenticated workspace API and backend authorization

- Expose versioned Organization, Project, Lab and Project Membership API operations under `/api/v1`.
- Validate all parent/child relationships before writes: a Lab belongs to one Project and a Project belongs to one Organization.
- Resolve a user's Project membership on every authorization decision so membership revocation takes effect without waiting for the browser session to expire.
- Apply the existing OWNER/ADMIN/OPERATOR/VIEWER policy at both global and Project scope; project membership cannot elevate a user's global configured role.
- Enforce Project scope for Run lists/details, tests, metrics, regressions, health, artifacts/downloads, baselines, firmware operations and other resource-bearing endpoints.
- Keep old wildcard-scoped local accounts compatible. Unowned historical Runs are visible only to wildcard-scoped identities; named memberships cannot implicitly see records with no Project owner.
- Require CSRF and idempotency for state-changing browser API requests. Return consistent error envelopes and document schemas in OpenAPI.
- Test cross-Project denial, missing membership, role boundaries, revocation, ownership mismatch, CSRF, idempotent retries and legacy compatibility.

### B3 — Workspace and Project UI

- Add a project-aware workspace page and Project selector.
- Add Organization/Project/Lab and membership administration views for authorized users.
- Show the active Project context wherever Runs, evidence or lab resources are displayed.
- Clear or invalidate project-keyed cached data when the selected Project or session changes.
- Preserve existing URLs and feature pages; do not create duplicate dashboards or pretend unsupported GNS3/device workflows exist.
- Keep all write actions behind API authorization, CSRF, idempotency and explicit confirmation where appropriate.

### B4 — System integration and documentation freeze

- Update operational setup and upgrade documentation for the schema and first Project setup.
- Verify the API/OpenAPI contract, React build/tests, backend regression matrix and the existing CLI compatibility suite.
- Confirm that the protected topology, node identities, capture paths, Runner CLI and shell provisioning remain untouched.
- Record hosted CI separately from protected REAL_LAB certification; no source/CI test may stand in for physical or virtual lab evidence.

## 3. Data and ownership invariants

```text
Organization
  └── Project
        ├── ProjectMembership(username, role)
        ├── Lab
        └── Run(project_id)
              ├── Attempt
              ├── TestResult
              └── Artifact
```

1. A Project is owned by exactly one Organization.
2. A Lab is owned by exactly one Project.
3. A project-managed Run is owned by exactly one Project.
4. A project-managed Run can reference only a Lab in that same Project; the API verifies this before starting the Runner.
5. Project membership identifies a username and Project. Membership roles are constrained to the four supported roles.
6. Effective Project authority is never greater than the user's configured global role.
7. Revoked membership is denied by the next API authorization decision.
8. Historical Runs are not auto-assigned. Their NULL Project ownership is explicit legacy state.
9. A retry keeps the source Run's Project. Project ownership cannot be changed through retry.
10. Project scope applies to both metadata and artifact bytes. An artifact ID or filesystem path is never an alternate authorization route.

## 4. Compatibility boundaries

- Existing source checkout paths, CLI commands and root wrappers remain unchanged.
- Existing pytest node IDs and test selection semantics remain unchanged.
- Existing Runs, Attempts, TestResults, Artifacts and baseline records are preserved.
- The existing GNS3 node IDs and links, hwsim association and protected capture implementation remain frozen.
- `wifi_lab_reprovision_robust.sh` remains the current operator provisioning path.
- The new ownership layer does not replace Linux RunProcessManager supervision or infer Windows hwsim support.

## 5. Security boundaries

Project visibility is a backend decision. Frontend permission checks are only presentation. All API handlers that load project-owned data must authorize the actual persisted Project owner before returning it. Missing Project ownership is not treated as a wildcard. User-supplied project IDs, lab IDs and artifact IDs are untrusted until parent relationships and authorization are verified.

Local environment-configured OWNER/ADMIN identities remain the bootstrap authority for creating the first Organization and Project. Cloud identity, OIDC/SAML, short-lived Runner credentials, multi-instance sessions and remote commands remain deferred.

## 6. Completion evidence

A Stage B checkpoint is complete only when its focused tests and hosted CI gates pass and its docs describe the delivered source behavior accurately. Stage B overall is complete only after B1–B4 are verified. Protected GNS3/mac80211_hwsim execution and physical firmware qualification remain separate operator evidence gates.
