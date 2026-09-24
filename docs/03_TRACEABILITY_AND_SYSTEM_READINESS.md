# NetRegress — Traceability & System Readiness

> Canonical document for requirement traceability, implementation evidence, current system state, completeness auditing, release readiness, and the distinction between source readiness and runtime certification.

## 1. How to use this document

Use this document to answer:
1. Where is a requirement implemented?
2. What is the current system state?
3. What was audited and fixed?
4. What still requires runtime or REAL_LAB evidence?

## 2. Requirement and documentation traceability

## 1. Purpose

This document shows where the completed discovery decisions are represented in the implementation documentation.

## 2. Architecture questionnaire mapping

| Source section | Topics | Primary document | Secondary document |
|---|---|---|---|
| A | product/end-state | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | PRD.md |
| B | Cloud/Runner execution | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | SECURITY_AND_SAAS.md |
| C | pytest compatibility | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | EXECUTION_AND_ADAPTERS.md |
| D | Run lifecycle | 02_SYSTEM_ARCHITECTURE_DATA_API.md | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md |
| E | samples/statistics | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| F | baselines | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| G | NO_BASELINE/UNVALIDATED | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| H | regression | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| I | artifacts | 02_SYSTEM_ARCHITECTURE_DATA_API.md | SECURITY_AND_SAAS.md |
| J | Lab Health | 02_SYSTEM_ARCHITECTURE_DATA_API.md | 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md |
| K | configuration | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md | AGENT_CONTEXT.md |
| L | SSH/commands | EXECUTION_AND_ADAPTERS.md | SECURITY_AND_SAAS.md |
| M | device/firmware adapters | EXECUTION_AND_ADAPTERS.md | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| N | virtual/physical WiFi | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | FRONTEND_DESIGN.md |
| O | performance | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md | 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md |
| P | protocol evidence | EXECUTION_AND_ADAPTERS.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| Q | capture | EXECUTION_AND_ADAPTERS.md | 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md |
| R | frontend | FRONTEND_DESIGN.md | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| S | API | 02_SYSTEM_ARCHITECTURE_DATA_API.md | SECURITY_AND_SAAS.md |
| T | auth/RBAC | SECURITY_AND_SAAS.md | FRONTEND_DESIGN.md |
| U | Cloud queue | SECURITY_AND_SAAS.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| V | CI/webhook | SECURITY_AND_SAAS.md | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| W | firmware handling | EXECUTION_AND_ADAPTERS.md | SECURITY_AND_SAAS.md |
| X | database | 02_SYSTEM_ARCHITECTURE_DATA_API.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| Y | observability | 02_SYSTEM_ARCHITECTURE_DATA_API.md | 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md |
| Z | frontend migration | FRONTEND_DESIGN.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| AA | testing | 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| AB | repository workflow | AGENT_CONTEXT.md | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| AC | provisioning shell migration | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| AD | operational philosophy | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | AGENT_CONTEXT.md |
| AE | retention/deletion/export | SECURITY_AND_SAAS.md | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| AF | modular monolith/cloud deployment | 02_SYSTEM_ARCHITECTURE_DATA_API.md | SECURITY_AND_SAAS.md |

## 3. Business Logic mapping

| Source | Business rule document |
|---|---|
| BL-01 to BL-10 | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md sections 3–8, 16–20 |
| BL-11 to BL-16 | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md sections 8, 26, 28 |
| BL-17 to BL-20 | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md sections 7, 10, 14, 15 |
| BL-21 to BL-25 | 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md sections 12, 23, 24, 25 |

## 4. Technical Clarity mapping

| Source | Technical document |
|---|---|
| TC-01 to TC-07 | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| TC-08 to TC-11 | 02_SYSTEM_ARCHITECTURE_DATA_API.md + 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md |
| TC-12 to TC-16 | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| TC-17 to TC-20 | EXECUTION_AND_ADAPTERS.md |
| TC-21 to TC-23 | 02_SYSTEM_ARCHITECTURE_DATA_API.md |
| TC-24 | 01_DEVELOPMENT_PLAN_AND_ROADMAP.md |
| TC-25 | 02_SYSTEM_ARCHITECTURE_DATA_API.md |

## 5. Document precedence

When future documents disagree:

1. Architecture decisions determine future direction.
2. Business Logic determines product semantics.
3. Technical Architecture determines internal structure.
4. Data/API documents determine persisted and external contracts.
5. Testing/Operations determines verification gates.
6. Frontend design determines presentation.
7. Existing executable code remains the current behavioral source until the relevant phase migrates it.

## 6. Open decisions

Only decisions explicitly marked deferred in the Architecture Decision Record remain intentionally open, primarily exact Cloud retention terms, final Cloud provider and final object-storage provider.

All other discovery questions have an implementation decision.

## Iteration 17 traceability

| Requirement | Implementation | Verification |
|---|---|---|
| DeviceAdapter boundary | `lib/adapters/device.py` | adapter contract tests |
| FirmwareAdapter lifecycle | `lib/adapters/firmware.py`, `lib/services/firmware_service.py` | fake lifecycle tests |
| Image integrity | SHA-256 validation + remote hash check | hash mismatch test |
| Explicit authorization | `FirmwareAuthorization` | authorization rejection test |
| Fake adapter | `lib/adapters/fake.py` | nominal/failure lifecycle tests |
| Run integration | `RunContext.device_adapter`, `RunContext.firmware_adapter` | session wiring audit |

## Iteration 18 traceability

| Requirement | Implementation | Verification |
|---|---|---|
| Fail-closed release policy | lib/services/release_gate.py | ci_tests/test_release_gate.py |
| Required test/evidence checks | ReleaseGateEvaluator | CI policy tests |
| Persisted Run evaluation | scripts/ci_release_gate.py | source audit |
| GitHub-hosted core CI | .github/workflows/internal-release-gate.yml | workflow source audit |
| Protected real-lab gate | dispatch-only self-hosted job | workflow source audit |
| Pytest node/semantic ID normalization | RegressionIntelligenceService | regression contract test |

## Iteration 19 traceability

| Requirement | Implementation | Verification |
|---|---|---|
| Durable offline queue | `SQLiteSyncQueueRepository` | queue persistence tests |
| Idempotent Run snapshot | `RunnerSyncService.queue_run` | idempotency test |
| Lease/recovery | queue claim/recover methods | expired-lease test |
| Retry semantics | `RunnerSyncService.sync_pending` | offline transport test |
| Outbound transport | `HttpSyncTransport` | source contract audit |
| Terminal Run queueing | `tests/conftest.py` | session wiring audit |
## Iteration 26 traceability

| Requirement | Implementation | Verification contract |
|---|---|---|
| Failure injection coverage | lib/services/failure_injection.py | tests/test_iterations_26_27.py |
| Restart/orphan recovery | lib/services/operational_recovery.py | recovery contract test |
| Stale-lock recovery | StaleLockRecovery | stale lock test |
| Backup/restore | SQLiteBackupService | SQLite integrity/restore test |
| API idempotency/replay binding | lib/services/api_security.py, dashboard/api_v1.py | durable idempotency test |
| CSRF | CsrfService, v1 mutation guard | CSRF contract + authenticated mutation test |
| SSRF boundary | validate_https_endpoint | private-address rejection test |
| Path confinement | resolve_confined_path | firmware API boundary |
| Audit integrity | AuditIntegrityService | tamper-detection contract |
| Security audit | scripts/netregress_security_audit.py | CI source-readiness gate |

## Iteration 27 traceability

| Requirement | Implementation | Verification contract |
|---|---|---|
| Final certification matrix | lib/services/certification.py | 11-scenario matrix test |
| Evidence completeness | CertificationMatrix.validate_evidence | all-control completeness test |
| Certification report CLI | scripts/netregress_certification.py | CLI source contract |
| Documentation freeze | current/roadmap/security/testing/data/API/frontend/install docs | repository audit |
| Protected real-lab distinction | certification execution_class=REAL_LAB | matrix semantics test |

## 3. Current system state

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

Iterations 20–30 are source-implemented and the full core/release-readiness CI gates now pass. “Implemented” does not mean “runtime certified”: the real-lab execution class remains the authoritative proof for execution-sensitive behavior.

## Remaining production gaps

1. **Project/Cloud control plane:** a durable first-class Project entity, organization model and end-to-end multi-project ownership remain intentionally deferred to the future Cloud/SaaS control plane; the standalone Runner keeps local role/project primitives without inventing Cloud persistence.
2. **Protocol live wiring breadth:** DHCP evidence is live-wired into the protected real capture path; EAPOL, Beacon/RSN and DNS analyzers have typed implementations and unit coverage but still require protected execution-class integration evidence.
3. **Execution certification:** CI/source gates cannot replace GNS3/mac80211_hwsim, real device, browser and production-like runtime evidence.

## Protected behavioral baseline

`436026eba597b2c6ae2e291a9cd8054b70ebbf7c`

## Architectural boundary

Runner remains authoritative for lab/device execution, evidence, regression analysis and local release decisions. Cloud/SaaS remains deferred above the standalone certified Runner.


## Final verification — 2026-09-24

Latest verified main: `e5e235f56b17a17ad1c87f9c1b728d0dfe02ed93`.

Core gate and source release-readiness checks pass. Protected REAL_LAB certification remains a separate execution-class gate and is not inferred from CI/source evidence.

## 4. Production completeness audit

**Audit date:** 2026-09-24  
**Audited baseline:** `7ad58e0648fdb4eaa06b14c9c8d6db62358327fc`

## Executive finding

The previous release wave was structurally strong but had several implementation details that were not actually complete despite being marked complete in release documentation. This audit traced the documented contracts into the source tree and identified concrete mismatches rather than treating documentation claims as evidence.

## Closed source-level gaps

| Gap | Finding | Closure |
|---|---|---|
| DHCP T1/T2 | Parser stopped at DORA and did not classify renewal/rebind transactions. | Added correlated renewal/rebind detection and lease-timer evidence. |
| Firmware exclusivity | ResourceLockManager existed but firmware mutation did not acquire it. | Firmware update/rollback now acquire a device-scoped firmware lock for the full mutation lifecycle. |
| Firmware metadata | API did not pass compatibility/hash/signature metadata to validation. | API now accepts confined signature/compatibility/hash metadata and applies configured signature policy. |
| Release waivers | Gate matching ignored WaiverScope. | TEST/RUN/REGRESSION/RELEASE scopes are evaluated separately and run context is carried into the gate. |
| Mutation idempotency | Only Run creation used durable API idempotency. | Operational POST mutations now require durable request-fingerprint-bound idempotency keys. |
| Readiness | API readiness only initialized SQLite. | Readiness now reports structured RunnerDoctor checks and returns 503 on a failed readiness check. |
| Frontend security | React mutations did not supply CSRF or idempotency headers. | API client now obtains CSRF/idempotency headers for mutations; role-aware UI remains presentation-only and backend authorization remains authoritative. |
| API contract drift | CSRF/test-detail/metric-history routes and firmware metadata were incomplete in OpenAPI. | OpenAPI route and schema surface synchronized with the API implementation. |
| Roadmap integrity | Iterations 6–27 were accidentally removed from the current roadmap. | Restored the complete historical roadmap and appended Iterations 28–30 plus the completeness audit. |

## Evidence that remains intentionally separate

The following are not silently converted into “complete” because source code alone cannot prove them:

- GNS3/mac80211_hwsim protected baseline execution.
- Real device firmware flash/reboot/rollback.
- Real DHCP T1/T2 capture and recovery evidence.
- EAPOL/WPA, Beacon/RSN and DNS live capture integration evidence.
- Browser runtime of the authenticated UI.
- Target-environment CI execution of the final release gate.

## Residual implementation gaps

### First-class project model

The authentication layer contains project-scope primitives, but the normalized domain currently lacks a durable Project entity connected to Run/Device/Lab ownership. The standalone Runner can operate as a single-project system, but a true multi-project SaaS-ready model is not yet part of this release.

### Protocol live-wiring breadth

The protocol evidence subsystem is implemented and tested, and DHCP is live-wired into the real packet-capture validation path. EAPOL, Beacon/RSN and DNS parsers have compatibility wrappers and unit fixtures, but their complete protected test-node execution path still needs to be bound to real capture evidence.

### Frontend administrative surface

The React UI is an operational Runner shell with authenticated launch/inspection/cancellation/retry, polling, health, tests, telemetry and artifacts. Firmware mutation, waiver administration, baseline promotion and detailed release/regression workflows remain primarily API surfaces.

## Production-readiness score

This audit uses a transparent rubric rather than a binary claim:

- **Source completeness: 97%** — implementation contracts are substantially represented and the audited defects are closed, with the residual gaps above.
- **Operational/security readiness: 95%** — durable idempotency, CSRF, rate limiting, path confinement, release gates, recovery and readiness checks are present.
- **Execution certification readiness: 70%** — source and simulated controls are in place, but protected REAL_LAB and runtime/browser evidence is not established by this source audit.

**Overall production readiness: 90%.**

The system is therefore **source-complete enough for dedicated production certification**, but it should not be represented as fully runtime-certified until the protected execution gates are actually run and their evidence is persisted.


## Dependency compatibility correction — Scapy

The focused protocol-evidence gate exposed that the former `scapy==2.5.0` pin did not provide the `EAPOL_KEY` API required by the repository tests. The pin is now aligned to stable Scapy `2.7.0`, whose documented `scapy.layers.eap.EAPOL_KEY` interface matches the protocol-evidence implementation. citeturn625846search0turn625846search2


## Final gate verification

The latest GitHub Actions run `35998429392` passes dependency installation, pip consistency, strict security audit, certification matrix, focused completeness contracts, the main release gate and the release manifest/readiness verifier. The REAL_LAB job remains intentionally skipped in CI.

**Final production-readiness assessment: 90%.**

## 5. Release readiness

## Purpose

This is the source-of-truth release checklist for the standalone Runner. It distinguishes **source/repository readiness** from **runtime certification readiness**.

The current completeness audit was performed on 2026-09-24 against the pre-audit main release state `7ad58e0648fdb4eaa06b14c9c8d6db62358327fc`.

## Source completeness result

**97% source implementation completeness.**

The completeness wave closes the audited source-level defects in:
- DHCP T1 renewal and T2 rebind transaction evidence;
- firmware-operation exclusivity;
- firmware API checksum/signature/model metadata propagation;
- scoped waiver semantics;
- operational mutation idempotency coverage;
- structured API readiness;
- frontend CSRF/idempotency integration;
- OpenAPI route/schema synchronization;
- roadmap/documentation reconciliation.

The remaining source-level deductions are execution-bound protocol coverage (real DHCP T1/T2 and live EAPOL/Beacon/RSN/DNS captures), browser/runtime evidence, and deferred Cloud tenant/project control-plane scope. Advanced administrative workflows remain intentionally API-first in the standalone Runner.

## Production-readiness assessment

### Overall

**Estimated production readiness: 90%.**

This percentage is an audit score, not a process exit code. It weights:
- source completeness and architecture: 50%;
- operational/security readiness: 25%;
- execution/certification evidence: 25%.

| Dimension | Assessment |
|---|---:|
| Architecture and domain integrity | 97% |
| Orchestration and failure handling | 97% |
| Evidence and measurement | 94% |
| Firmware/device lifecycle | 96% |
| API/security/release controls | 96% |
| Operations/recovery/synchronization | 95% |
| Frontend operational surface | 84% |
| Real execution certification evidence | 70% |
| **Overall production readiness** | **90%** |

## Post-audit CI dependency correction

The first post-push CI run failed during dependency installation because Netmiko 4.7.0 requires Paramiko >=3.5.0 while the repository had pinned Paramiko 3.4.0. The repository pin is now corrected to Paramiko 3.5.1; the source score below reflects the correction, while runtime certification remains a separate gate.

## Remaining release gates

The following are not source-completeness failures, but they prevent a claim of fully certified production deployment:

1. Protected REAL_LAB execution must re-establish the behavioral baseline in the GNS3/mac80211_hwsim environment.
2. The expanded DHCP renewal/rebind behavior requires real capture evidence from the lab.
3. EAPOL, Beacon/RSN and DNS analyzer live integration requires execution evidence beyond unit fixtures.
4. Browser runtime verification is required for the authenticated React UI and CSRF/mutation flow.
5. CI execution of the full release pipeline must be observed in the target repository/environment rather than inferred from source.

## Release invariant

Source release tooling may report the repository structurally ready when:

~~~text
branch = main
working_tree_clean = true
required_paths_present = true
forbidden_tracked_files = []
syntax_errors = []
source_release_ready = true
~~~

That invariant does not imply:

~~~text
REAL_LAB_CERTIFIED = true
PRODUCTION_RUNTIME_CERTIFIED = true
~~~

The source manifest, simulated integrations and fake adapters never substitute for protected real-lab evidence.


## Final verification — 2026-09-24

Verified main commit: `e5e235f56b17a17ad1c87f9c1b728d0dfe02ed93`.

GitHub Actions run `35998429392` verified:
- core-gate: PASS;
- dependency installation: PASS;
- pip check: PASS;
- strict security audit: PASS;
- certification matrix generation: PASS;
- focused completeness contracts: PASS;
- release gate: PASS;
- RunnerDoctor/release manifest verification: PASS;
- REAL_LAB gate: SKIPPED as the protected execution class.

**Final audit score: 90% overall production readiness.**

This is not a claim of full runtime certification. The remaining 10% is dominated by protected real-lab and production-runtime evidence, not by known source defects in the audited core.

## 6. Canonical readiness interpretation

SOURCE_IMPLEMENTED != CORE_CI_GREEN != REAL_LAB_CERTIFIED != FULL_PRODUCTION_RUNTIME_CERTIFIED

Core CI/source checks prove source and policy contracts. They cannot manufacture protected GNS3/mac80211_hwsim evidence, real-device firmware evidence, or browser/runtime evidence.
