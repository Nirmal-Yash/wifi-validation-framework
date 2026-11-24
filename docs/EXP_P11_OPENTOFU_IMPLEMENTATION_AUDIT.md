# EXP-P11 — OpenTofu infrastructure automation

## Scope
P11 establishes OpenTofu as the infrastructure provisioning owner, separate from P10 Ansible device configuration and the existing emulator-provider lifecycle.

## Source integration
- lib/services/infrastructure_automation.py: OpenTofu CLI boundary, module catalogue, Lab-scoped workspaces, immutable module snapshots, binary plans, approvals, apply, inspection and audit.
- alembic/versions/20261124_21_opentofu_automation.py: schema v31 / revision 20261124_21: workspaces, plans, approvals, executions, RBAC and lifecycle/scope guards.
- dashboard/api_v1.py, docs/openapi.yaml and the Infrastructure page: scoped API and operator-facing workflow.
- tests/test_infrastructure_automation.py: private module snapshot, non-secret variables, independent approval, exact plan integrity, execution and failed-apply recovery state.

## Security and consistency
- Modules are operator-owned local files, not caller-submitted HCL. Only allow-listed module identifiers are accepted.
- Every workspace is bound to an active Project and Lab and receives a private state directory. Local state is stored outside the repository.
- Caller variables are bounded JSON; secret-like keys are rejected. Provider authentication may come only from the operator's selected process identity/allow-listed environment.
- The API never exposes raw state, variable files, plan binaries or credential values.
- The service reuses the existing shared Lab resource lock and adds a workspace lock. Approval is independent and tied to the binary plan SHA-256.
- Destroy and plans containing resource deletion require a separate destroy permission. Apply requires explicit confirmation and the exact approved hash.
- Partial or timed-out apply is not retried; it marks the workspace RECOVERY_REQUIRED.

## Deliberate limitations
P11 uses an isolated local backend only (tofu init -backend=false). It does not claim remote state, cloud-account qualification, cloud rollback, provider-side recovery or a hosted module registry. OpenTofu must be installed by the operator. Provider-specific module correctness and live provider behavior still require external qualification.
