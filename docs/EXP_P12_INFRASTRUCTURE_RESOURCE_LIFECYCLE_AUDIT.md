# EXP-P12 — Infrastructure resource lifecycle, drift and recovery

## Scope
P12 extends the P11 OpenTofu owner with canonical topology bindings, safe provider-state reconciliation, drift/orphan/missing classification and an explicit recovery-plan lifecycle. It does not replace the existing topology provider/apply lifecycle or Ansible device configuration.

## Implemented components
- lib/services/infrastructure_automation.py validates topology profiles and published revisions, verifies live state addresses, preserves immutable mapping history, creates refresh-only reconciliation snapshots, hashes state and plan artifacts, and prepares reconciliation-pinned recovery plans.
- alembic/versions/20261124_22_infrastructure_reconciliation.py adds schema v32 and revision 20261124_22: resource bindings, immutable reconciliation evidence, recovery-plan references, active-mapping uniqueness and Project/Lab scope guards.
- dashboard/api_v1.py adds resource mapping, reconciliation history, state reconciliation and explicit recovery preparation routes with scoped permissions and idempotency controls.
- docs/openapi.yaml documents the resource and recovery contracts.
- frontend/src/pages/infrastructure.jsx adds published-topology mapping, binding history, reconciliation observations and recovery-plan creation.
- tests/test_infrastructure_reconciliation.py covers exact topology/revision validation, cross-Lab rejection, mapping replacement, drift/orphan/missing detection, state-value non-disclosure, immutable reconciliation evidence and stale recovery-plan rejection.

## Mapping semantics
Each active Lab workspace can map an observed OpenTofu resource address to one logical node in an active topology profile and immutable PUBLISHED topology revision. The mapping must match the workspace Project/Lab. A resource must already exist in the workspace state. Rebinding uses compare-and-swap: the caller supplies the current binding ID, the prior record becomes SUPERSEDED, the replacement becomes ACTIVE, and all old mapping records remain immutable. A partial unique index enforces at most one active mapping per workspace/resource address.

## Reconciliation semantics
Reconciliation uses the shared Lab and workspace locks and an OpenTofu refresh-only plan. It compares saved-state resource addresses/types and provider drift entries against active topology bindings. It distinguishes PRESENT, DRIFTED, ORPHANED, DRIFTED_ORPHANED and MISSING observations and persists aggregate counts. Reconciliation details contain resource addresses, types, action names, binding IDs and topology references only. Raw state values, provider attributes, output values and credentials are never returned or persisted in the reconciliation summary. Canonical state and refresh-plan artifacts are represented by SHA-256 digests.

## Recovery semantics
A failed or timed-out apply enters RECOVERY_REQUIRED and is never automatically retried. Recovery requires a fresh reconciliation, a new RECOVERY plan bound to the latest reconciliation ID, independent approval of the exact binary plan SHA-256 and explicit apply confirmation. A newer reconciliation invalidates an unapplied recovery plan. A failed recovery remains RECOVERY_REQUIRED; no automatic replay or cloud rollback is claimed.

## Bounded behavior and known limits
- Operator-managed local modules and local backend only; no remote backend or module registry.
- Maximum 100,000 state resources, active resource bindings and drift observations for reconciliation.
- Maximum 2,000 resource summaries per API view; aggregate counts cover all bounded state resources.
- Maximum 4 MiB persisted reconciliation detail JSON.
- Resource mapping is an operator-reviewed association; P12 does not auto-discover cloud-to-topology equivalence.
- Refresh-only planning observes provider drift but does not apply it. A successful OpenTofu apply is not proof of application-level service health.
