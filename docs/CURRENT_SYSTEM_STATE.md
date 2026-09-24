# NetRegress — Current System State

## Consolidated implementation status

| Iteration | Source implementation |
|---|---|
| 20 | Complete |
| 21 | Complete |
| 22 | Complete |
| 23 | Complete |
| 24 | Complete |
| 25 | Complete |
| 26 | Next implementation scope |
| 27 | Certification scope after 26 |
| 28 | Final single release commit |

## Iteration 20
Security and architecture foundation: tracked secrets removed, local authentication/RBAC, protected API/dashboard boundaries, deterministic configuration and current-state reconciliation.

## Iteration 21
Deterministic orchestration: ConfigurationResolver, EnvironmentFingerprintService, LabController, exclusive resource locks, RunOrchestrator, pytest lifecycle integration and execution identity.

## Iteration 22
Evidence and measurement enforcement: required-evidence fail-closed semantics, protocol evidence, telemetry capture lifecycle and statistical measurement boundaries.

## Iteration 23
Device/firmware and failure control: explicit firmware state machine/audit events, TFTP transport seam, process lifecycle/cancellation, failure taxonomy, diagnostics and ReproductionManifest.

## Iteration 24
Operational product surface: authorized state-changing Runner API, OpenAPI contract, baseline promotion path, waiver creation boundary, React/Vite frontend shell and Alembic migration boundary.

## Iteration 25
Standalone Runner intelligence: baseline eligibility/immutability semantics, scoped waivers, release-gate waiver handling, durable offline sync retained as Runner authority, reproduction/diagnostic packaging and operational controls.

## Architectural boundary
Runner remains authoritative for lab/device execution and raw evidence. Cloud/SaaS remains deferred above the certified Runner.

## Protected baseline
436026eba597b2c6ae2e291a9cd8054b70ebbf7c
