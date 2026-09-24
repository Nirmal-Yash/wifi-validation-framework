# NetRegress — Current System State

## Audit basis

Current source audit date: 2026-09-24. Repository baseline for this audit: `7ad58e0648fdb4eaa06b14c9c8d6db62358327fc` before the current completeness wave.

The prior release wave established the standalone Runner architecture, but this audit found several source-level contract gaps that had been overstated as complete. The completeness wave closes the identified implementation defects and separates **source implementation readiness** from **execution certification**.

## Consolidated implementation status

| Area | State | Audit interpretation |
|---|---|---|
| Domain / persistence | Implemented | Stable normalized Run/Attempt/TestResult/Artifact model with additive SQLite migrations and integrity controls. |
| Run orchestration | Implemented | Deterministic orchestration, resource ownership, process lifecycle and failure classification are present. |
| Evidence | Implemented | Required evidence remains fail-closed; protocol evidence is persisted and integrity-checked. |
| DHCP protocol evidence | Completed in source | DORA, T1 renewal and T2 rebind transaction classification are now correlated from captured DHCP traffic. |
| EAPOL / Beacon / DNS evidence | Partially operational | Parsers and compatibility wrappers exist with unit coverage; complete production-test live wiring still requires execution-class validation. |
| Telemetry / measurement | Implemented | Typed WiFi telemetry, raw samples and deterministic statistical evaluation are present; RF claims remain environment-class aware. |
| Device / firmware | Completed in source | Hash/model/signature validation, explicit authorization, firmware-operation exclusivity and explicit rollback are enforced. |
| API / security | Implemented | API authorization, CSRF, rate limiting, durable operational idempotency, SSRF/path confinement and structured readiness are present. |
| RBAC project scoping | Partially operational | Role/project primitives exist, but a durable multi-project entity and end-to-end Run/Device/Lab project association are not yet modeled. |
| Regression / release gate | Completed in source | Fail-closed release evaluation and scope-aware waivers are implemented. |
| Frontend | Operational shell | Launch/cancel/retry/inspection, polling, health/tests/telemetry/artifact views and CSRF-aware mutations are present; advanced release/firmware/waiver workflows remain API-first. |
| Offline synchronization | Implemented | Durable local queue, lease/retry/idempotency semantics remain Runner-authoritative. |
| Operational recovery | Implemented | Backup/restore, retention, stale-lock recovery, orphan Run recovery and audit-chain integrity services are present. |
| Documentation / release tooling | Reconciled | Roadmap is restored through Iteration 30 and release/doctor tooling is source-addressed. |
| REAL_LAB certification | Unverified | Protected GNS3/mac80211_hwsim execution evidence must be run in the dedicated real-lab phase. |

## Iterations 20–30

Iterations 20–30 are source-implemented. “Implemented” does not mean “runtime certified”: the real-lab execution class remains the authoritative proof for execution-sensitive behavior.

## Remaining production gaps

1. **Project-scoped authorization model:** RBAC currently has project identifiers as an authorization primitive, but the persisted domain does not yet model a first-class Project entity and propagate project ownership through Runs, Devices and Labs.
2. **Protocol live wiring breadth:** DHCP evidence is live-wired into the protected real capture path; EAPOL, Beacon/RSN and DNS analyzers still require explicit execution-class integration evidence.
3. **Advanced frontend operations:** firmware mutation, waiver administration, baseline administration and detailed regression/release workflows remain primarily API-driven rather than fully represented in the React shell.
4. **Execution certification:** CI/source gates cannot replace GNS3/mac80211_hwsim, real device, browser and production-like runtime evidence.

## Protected behavioral baseline

`436026eba597b2c6ae2e291a9cd8054b70ebbf7c`

## Architectural boundary

Runner remains authoritative for lab/device execution, evidence, regression analysis and local release decisions. Cloud/SaaS remains deferred above the standalone certified Runner.
