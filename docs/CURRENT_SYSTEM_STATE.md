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
| 26 | Complete |
| 27 | Complete |
| 28 | Complete |
| 29 | Complete |
| 30 | Complete |

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


## Iterations 26–27
Iteration 26 is source-complete for the failure-injection catalog/harness, failure-class preservation, recovery controls, security hardening boundaries, durable API idempotency, CSRF, rate limiting, SSRF/path confinement, backup/restore, retention, stale-lock recovery, audit-chain integrity, security audit tooling and CI readiness controls.

Iteration 27 is source-complete for the final 11-scenario certification matrix, evidence completeness rules, certification CLI, documentation freeze and repository-readiness checks. The protected real-lab scenario remains represented as an explicit certification class; its execution evidence belongs to the dedicated debugging/certification phase and is not replaced by simulation.

 
## Iteration 28
Final single-commit release integration: deterministic release manifest, source inventory, working-tree audit, syntax/readiness checks, release CLI and final CI integration.

## Iteration 29
Reproducible operational readiness: RunnerDoctor, database integrity inspection, release manifest content addressing and controlled release/doctor commands.

## Iteration 30
Final governance and architecture freeze: synchronized release documentation, explicit Runner/Cloud boundary, certification execution-class integrity and final release invariants.
