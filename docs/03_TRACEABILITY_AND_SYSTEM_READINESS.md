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

Current repository audit date: 2026-11-07. Phase G is being delivered on top of Phase F main head `6da7aa46e3a93fa4fbc7c0e3466b6c1851ddd2a6`. This is a source/history/hosted-CI audit; local pytest and protected REAL_LAB execution are not available in this session.

- Phase C: hosted workflow 41855004616 passed.
- Phase D: hosted workflow 41870444440 passed.
- Phase E: hosted workflow 42053712826 passed.
- Phase F: hosted workflow 42216004283 passed all three jobs (backend process/lifecycle contracts, frontend tests/build, and dashboard startup/proxy/session smoke test).

Phase G implementation and tests passed hosted workflow 42363358706 across backend, frontend/build and dashboard smoke jobs. Hosted CI does not certify protected REAL_LAB.

The prior release wave established the standalone Runner architecture, but this audit found several source-level contract gaps that had been overstated as complete. The completeness wave closes the identified implementation defects and separates **source implementation readiness** from **execution certification**.

## Consolidated implementation status

| Area | State | Audit interpretation |
|---|---|---|
| Domain / persistence | Implemented | Normalized Run/Attempt/TestResult/Artifact model plus the initial Organization/Project/Lab ownership model; Alembic head 20261111_04 governs SQLite schema version 13, with physical schema drift checks and pre-upgrade backup/recovery. Existing Runner records remain in place. |
| Run orchestration | Implemented | Run outcomes and completeness use the latest Attempt and an exact one-to-one match against selected tests; duplicate, missing and unexpected results remain unvalidated. |
| Evidence | Implemented | TestResult-owned, pytest-node/Attempt-owned, Attempt-wide and Run-wide evidence are scoped explicitly; evidence owned by another test/Attempt, soft-deleted, incomplete, invalid or hash-mismatched cannot satisfy a requirement. |
| DHCP protocol evidence | Completed in source | DORA, T1 renewal and T2 rebind transaction classification are now correlated from captured DHCP traffic. |
| EAPOL / Beacon / DNS evidence | Protected test paths source-wired; live acceptance pending | Parsers and protected capture tests are integrated with AP-side monitor/`br0` capture, SFTP/hash verification and Run-scoped evidence. Execute on the protected GNS3/mac80211_hwsim lab before claiming live acceptance. |
| Telemetry / measurement | Implemented; hosted source/contract verification | Typed immutable WiFi telemetry, source/environment provenance, raw warm-up/measured samples and deterministic statistical evaluation are covered by hosted tests; protected RF claims remain unverified until live lab evidence. |
| Device / firmware | Completed in source | Hash/model/signature validation, explicit authorization, firmware-operation exclusivity and explicit rollback are enforced. |
| API / security | Implemented | API authorization, CSRF, rate limiting, durable operational idempotency, SSRF/path confinement and structured readiness are present. |
| RBAC project scoping | Standalone single-project operation; multi-project deferred | Local roles and project-scope primitives support the standalone Runner. Durable multi-project ownership and tenant isolation remain full Phase O Cloud/SaaS future scope. |
| Regression / release gate | Hardened in Phase M source | Healthy completed baselines and valid evidence are required; missing classifications/non-PASS required tests fail closed; waiver exceptions are exact-scope and carry audit references. |
| Frontend | Phase L/M source integration delivered | React/Vite covers Run attempt/release-gate panels, policy-aware metrics, active waivers and admin offline queue visibility. Hosted launcher/proxy/session smoke passed; production reverse-proxy acceptance remains separate. |
| Offline synchronization | Hardened in Phase M source | Terminal-only snapshots, SHA-256 verification, atomic idempotency/claims, lease CAS, bounded lease recovery and ACK-safe audit behavior; external HTTPS endpoint acceptance remains separate. |
| Operational recovery | Implemented | Backup/restore, retention, stale-lock recovery, orphan Run recovery and audit-chain integrity services are present. |
| Documentation / release tooling | Source delivered; current runbooks reconciled | Roadmap through Iteration 30, standalone installer, doctor, source manifest, certification evaluator, O/P governance and operator procedures are present. |
| REAL_LAB certification | Unverified | Protected GNS3/mac80211_hwsim execution evidence must be run in the dedicated real-lab phase. |

## Phase B — Run and Evidence Correctness (2026-11-03)

The Phase B source changes establish the following correctness contracts:

- Run outcome evaluation considers only the latest Attempt and requires exactly one result for each selected pytest node or explicitly selected semantic test ID. Missing, extra, ambiguous and duplicate results produce UNVALIDATED rather than being hidden by a count comparison. A missing/unknown/failed health state cannot validate a Run, and a caller-supplied outcome cannot override persisted results. Retry API launches a new Run with its source_run_id persisted; it does not append results to or mutate the source Run.
- Pytest PASS, assertion FAIL, setup/teardown ERROR, SKIPPED, KNOWN_FAILURE (xfail), XPASS and inconclusive execution are persisted distinctly. The original setup/call/teardown reports, outcomes and xfail markers are retained in TestResult execution_metadata. An unclassified ERROR is UNVALIDATED rather than a product rejection; only an explicit PRODUCT_FAILED classification can reject it. Declared decision metrics are unit-checked and marked authoritative using TestRegistry metadata when results are recorded.
- Test-specific artifacts carry their persisted TestResult owner or a pytest-node plus Attempt owner before TestResult persistence. Attempt-wide command-audit artifacts can be shared only within that Attempt and use Attempt-specific files; the protected DHCP PCAP and derived JSON also use Attempt-specific files. Run-wide artifacts remain unowned and can be shared across Attempts. Required evidence must belong to the current test/Attempt (or be Attempt-/Run-wide), be complete, not soft-deleted, and pass hash verification.
- Sample values must be finite. Baseline promotion validates the latest Attempt, exact selected-test coverage, Run health/outcome, evidence, and declared authoritative measurement policies including the eligible sample minimum. Named-baseline replacement is an atomic SQLite transaction.

These are source-level correctness changes, not REAL_LAB certification. The hardware-backed protected suite and full combined verification must be executed before claiming runtime certification. The GitHub connector used for this phase cannot execute the repository's local Python/SQLite/pytest environment; therefore no local test pass is claimed here. The current green GitHub Actions run predates these pending source changes and is not evidence that this phase has passed CI.

## Iterations 20–30

Iterations 20–30 are source-implemented and the full core/release-readiness CI gates now pass. “Implemented” does not mean “runtime certified”: the real-lab execution class remains the authoritative proof for execution-sensitive behavior.

## Current B–P phase assessment — 2026-11-07

| Phase | Source state | Verification / remaining gate |
|---|---|---|
| A | Baseline/compatibility constraints documented | Re-establish protected baseline on current lab |
| B | Implemented | CI baseline passed historically; protected REAL_LAB remains separate |
| C | Implemented | Hosted workflow 41855004616 passed |
| D | Implemented | Hosted workflow 41870444440 passed; actual archive import remains operator-run |
| E | Implemented | Hosted workflow 42053712826 passed; schema/backup/rollback contracts included |
| F | Implemented | Owned process groups, PID identity validation, SIGTERM/SIGKILL cancellation, logs and cancellation intent; hosted workflow 42216004283 passed all three jobs; REAL_LAB separate |
| G | Implemented; hosted CI passed | Immutable layered configuration, stable fingerprints, persistent cross-process locks, safe stale recovery, lab/device/namespace leases, shared firmware exclusion and read-only launcher preflight; workflow 42363358706 passed; REAL_LAB separate |
| H | Source implementation delivered; protected execution pending | Hardened DHCP/EAPOL/Beacon/RSN/DNS correlation; EAPOL/Beacon/DNS foreground capture tests, SFTP/hash verification and Run-scoped artifacts added; protected live execution and DHCP T1/T2 capture remain pending |
| I | Source implementation present | Physical RF/performance/recovery evidence remains |
| J | Lifecycle hardened; hosted CI passed | Strict capabilities, OpenWrt profile defaults, env-backed SFTP credentials, image/path validation, full-scope device locking and expected-version rollback verification are source-covered; workflow 42472939649 passed all 3 jobs; real hardware certification remains outstanding |
| K | Security source hardening delivered; hosted CI passed | Global-address SSRF validation, strict source audit, API/RBAC/session tests and artifact sensitivity/remote-token download controls passed workflow 42511179934 (3/3 jobs); production proxy/secrets, independent dependency scan, DNS-rebinding review and threat-model acceptance remain |
| L | Source integration plus validation correction delivered | Combined hosted verification is attached to the Phase M workflow; browser/reverse-proxy and protected REAL_LAB acceptance remain |
| M | Source hardening delivered 2026-11-09 | Hosted workflow validation pending; actual HTTPS endpoint, protected REAL_LAB and human release approval remain separate |
| N | Certification tooling present | Clean installation and full protected 11-scenario REAL_LAB certification remain |
| O | Deferred | No production PostgreSQL repository adapter or tenant control plane claimed |
| P | Pending final phase | Repository-wide cleanup and final integrity freeze remain |

### Phase M — Regression Intelligence, Release Gate and Offline Operations (2026-11-09)

Phase M source hardening covers the key release and synchronization invariants:

- Baselines must be completed and backed by healthy-lab state. Baseline/current evidence must be COMPLETE or NOT_REQUIRED before metric comparison. Suite compatibility is checked after semantic TestRegistry ID normalization.
- Metric regression is expressed as degradation, independent of unit labels. Known metrics use explicit lower-/higher-is-better semantics; custom metrics need a persisted `regression.metric_directions` declaration. NaN/Infinity, invalid thresholds and undefined percentage deltas never produce a guessed PASS.
- Release Gate requires classification and PASS for every selected test, plus valid required evidence. Waivers are exact-scope by default; only RELEASE scope may intentionally apply to an entire release. Suppressed blockers remain visible with waiver ID and audit reference.
- Offline queue writes/claims/acks/failures are transactional and state/lease guarded. Reusing an idempotency key with changed content conflicts. Expired leases spend the retry budget; corrupt envelopes become BLOCKED before transport; remote acceptance is not undone by later local audit failure.
- Admin-only queue inspection returns summary and envelope metadata, never raw payload contents. Outbound sync remains manual and requires the configured HTTPS endpoint/token.

Hosted CI cannot replace protected GNS3/mac80211_hwsim execution, production proxy/authentication, external HTTPS sync or human release approval.

## Phase G implementation evidence and remaining acceptance## Phase G implementation evidence and remaining acceptance

Phase G source changes in this delivery:
- `lib/services/configuration.py`: declared precedence, deep copy, immutable nested results, per-leaf provenance, canonical hash and strict JSON/non-finite validation.
- `lib/services/environment_fingerprint.py`: stable identity digest with separately retained volatile observations and immutable payload.
- `lib/services/resource_lock.py`: stable collision-resistant inode, no symlink following, persistent lock file, renewal, idempotent release and ordered all-or-nothing resource groups.
- `lib/services/operational_recovery.py`: stale metadata is reclaimed only after acquiring the same advisory lock; the inode is preserved.
- `lib/services/run_orchestrator.py` and `lib/services/firmware_service.py`: shared lab/device/optional namespace leases and shared validation/firmware device scope.
- `lib/services/lab_controller.py`: launcher preflight, argument quoting, bounded timeout and fail-closed exit status. Provision/cleanup remain explicit.

Focused tests cover cross-process exclusion, inode stability, partial acquisition rollback, live-vs-stale recovery, lease renewal, configuration immutability/provenance, volatile observations, shell quoting/status handling and Run/firmware/namespace exclusion.

Phase G hosted workflow 42363358706 passed. The protected real-lab acceptance remains outstanding; verify the full GNS3/mac80211_hwsim suite on the lab host.

## Remaining gaps

1. **Future Cloud control plane:** a durable first-class Project entity, organization model and end-to-end multi-project ownership remain intentionally deferred to the future Cloud/SaaS control plane; the standalone Runner keeps local role/project primitives without inventing Cloud persistence.
2. **Protected protocol execution evidence:** the DHCP capture path remains intact; EAPOL/Beacon/RSN capture on the AP's existing PHY and DNS capture on AP `br0` are now wired as protected real-lab tests with verified PCAP and Run-scoped protocol JSON artifacts. These tests have not yet been run on the protected lab. The dnsmasq lease remains 12 hours, so live T1/T2 evidence requires a separately approved short-lease execution window; the pytest path does not alter DHCP service configuration.
3. **Runtime certification:** CI/source verification cannot replace GNS3/mac80211_hwsim, real-device firmware, authenticated browser/runtime, and production-like deployment evidence.

## Protected behavioral baseline

`436026eba597b2c6ae2e291a9cd8054b70ebbf7c`

## Architectural boundary

Runner remains authoritative for lab/device execution, evidence, regression analysis and local release decisions. Cloud/SaaS remains deferred above the standalone certified Runner.


## Final verification — 2026-09-24

The current main line includes the completed React/Vite frontend and subsequent backend test-fixture refinements. GitHub Actions Run #113 (`36002962762`) passed core, frontend build/test and release-readiness gates. The protected REAL_LAB job was intentionally skipped; therefore no current 11/11 real-lab certification is claimed.

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

## Readiness position

The repository is source-implemented across the documented standalone Runner surface and CI-verified for the hardware-free release gates. The remaining gaps are the intentionally deferred Cloud/SaaS control plane, protected live protocol execution evidence, and runtime certification.

Do not describe the current state as fully production-certified until the protected REAL_LAB and authenticated runtime/browser evidence are actually executed and persisted.

## Dependency compatibility correction — Scapy

The focused protocol-evidence gate exposed that the former `scapy==2.5.0` pin did not provide the `EAPOL_KEY` API required by the repository tests. The pin is now aligned to stable Scapy `2.7.0`, whose documented `scapy.layers.eap.EAPOL_KEY` interface matches the protocol-evidence implementation. 


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


## Phase K security hardening — 2026-11-09

The source audit confirmed the pre-existing standalone security controls: backend role authorization, project-scope primitives, password hashing, session expiry, CSRF, login throttling, security headers, durable idempotency fingerprints, command allowlists/destructive-operation policy, command/output redaction and audit evidence, artifact integrity/sensitivity metadata, confined firmware paths and recovery/audit services.

The new source change strengthens `validate_https_endpoint`, which is consumed by the synchronization transport. The validator now rejects malformed URL forms, embedded credentials, fragments, resolution errors, empty answers and every DNS answer that is not globally routable; mixed public/private DNS results are rejected. New API boundary tests cover IPv4 and IPv6 special-use ranges and valid public addresses.

The existing quality workflow now runs the strict source audit and focused API/RBAC/session tests. Hosted workflow [42510776806](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/42510776806) completed successfully; all three jobs passed, including both new security-specific steps.

Remaining: verify trusted client-IP handling, secure-cookie/HSTS policy behind the real reverse proxy; production secret provisioning; independent dependency scanning; DNS-rebinding/connection-time resolution review; and an independent threat-model assessment. Optional scanner presence in the source-audit output is not evidence that those scanners ran. No production deployment or penetration-test certification is claimed.


### Artifact download authorization hardening — 2026-11-09

The Phase K artifact route now uses persisted `sensitivity_class`: PUBLIC/INTERNAL downloads use the standard authenticated-viewer route; SENSITIVE or unknown classifications require admin authorization. Remote downloads require a configured `NETREGRESS_DASHBOARD_TOKEN` with constant-time bearer comparison even when `NETREGRESS_AUTH_REQUIRED=0`. Results-root containment and SHA-256 verification remain required. Focused route tests cover absent/incorrect/correct remote tokens and OPERATOR-vs-ADMIN authorization. Hosted workflow [42511179934](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/42511179934) passed 3/3 jobs, including the full backend API test suite. Reverse-proxy client-IP provenance still requires target deployment verification.


## Phase N — Standalone packaging and production certification (2026-11-09)

Phase N source delivery is commit 80831042d8f2f6b86562a0b6ac951cbfe87bceaf. Exact-commit hosted workflow 42629371133 completed successfully: all 3 jobs passed. Backend correctness completed with 360 passed and 7 skipped; API security boundary tests completed with 35 passed; frontend completed with 31 passed across 8 files and a successful production build; the dashboard launcher/proxy/authenticated-session smoke test passed.

The seven skips are protected real-lab operations (DHCP, EAPOL/Beacon, DNS capture, ping/loss/latency and throughput) and are not source/CI acceptance.

Source implementation includes the standalone installer, read-only doctor, deterministic source manifest, evidence-aware 11-scenario certification evaluator, secure repository .env resolution and the canonical operations runbook. Existing Alembic/SQLite recovery remains authoritative.

**Open production acceptance:** no Python transitive lockfile or frontend npm lockfile exists, the Runner application version is not separately declared, clean-machine install/upgrade/backup/restore has not been rehearsed, production reverse-proxy/secrets acceptance is outstanding, and protected REAL_LAB/physical firmware evidence remains outstanding. The release manifest must continue to report production reproducibility as false.

## Combined Phase O/P — bounded integration and repository governance (2026-11-09)

The full Cloud/SaaS programme remains future scope. The combined O/P source slice adds one narrow operational seam: scripts/netregress_sync.py --status reads the existing SQLite sync queue without an endpoint, token, network request or migration. The queue summary now uses a strictly read-only SQLite connection. Missing database and missing schema states remain distinct. Existing outbound HTTPS delivery and idempotent queue behavior are unchanged.

Repository governance cleanup modernizes the legacy run_all.sh and verify_system.py entry points without deleting their names, aligns them to canonical install/release/dashboard commands, strengthens .gitignore, indexes the standalone operator runbook, adds required source/test paths to the release manifest and introduces regression tests for read-only status/cleanup contracts.

Do not claim Cloud receiver, tenant authorization, PostgreSQL, distributed identity/session infrastructure, remote release control or artifact binary transfer. Those remain future Phase O work. Do not claim that transitive dependency locks or clean-machine/REAL_LAB production certification are complete.


## Current repository and acceptance audit — 2026-11-09

> **Authority note:** This section supersedes older readiness snapshots and historical gap statements above where they conflict. Historical audit scores and implementation snapshots are retained for traceability; they are not current certification results.

### Current source and hosted-CI state

- The B–P source programme is present on the single `main` branch. Phase A is the historical protected behavioral baseline, not a separate upgrade/install command. Phases B–N are implemented as source/CI slices; Phase O's full Cloud/SaaS control plane remains intentionally deferred; Phase P repository governance is delivered.
- The bounded Phase O addition is local read-only sync queue status only. Synchronization delivery remains manual, outbound-only, and requires a separately configured approved HTTPS receiver. No Cloud receiver, tenant database, PostgreSQL repository, distributed session service or inbound remote Runner control is included.
- The latest completed workflow before this documentation reconciliation was [42632716718](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/42632716718) on commit `a87bfd136d9ca47bdb5495f5c7aee416da2d191a`: all 3 jobs passed; backend 367 passed / 7 skipped / 16 warnings; frontend 31 passed across 8 files and production build passed; dashboard launcher, Vite proxy and authenticated session smoke passed.
- The seven skipped cases are protected real-lab operations. Their skip status is not a PASS and does not certify GNS3/mac80211_hwsim, physical RF or firmware.
- Protected DHCP, EAPOL/Beacon/RSN and DNS capture paths are source-integrated. DHCP T1/T2 still requires a separately approved short-lease lab window; the normal 12-hour lease must not be altered by ordinary setup or CI. EAPOL/Beacon and DNS capture paths still require protected live-lab execution.
- Phase L/M browser source integration has hosted smoke coverage. That does not verify a production HTTPS reverse proxy, HSTS, secure-cookie behavior, trusted forwarded client IP, production secrets or an independent threat-model review.

### Remaining acceptance work (not represented as source completion)

1. **Dependency reproducibility:** there is no tracked complete Python transitive lockfile or a frontend npm lockfile. Several Python direct dependencies are declared by ranges. The release manifest must continue to set `production_reproducible=false`. Lockfiles must be generated and reviewed for an explicitly supported platform/runtime, followed by clean-machine installs and CI; do not invent a resolver snapshot.
2. **Clean-machine rehearsal:** install from a clean Ubuntu host, upgrade a copy of an older database, verify automatic and explicit pre-upgrade backups, and rehearse restore with all Runner processes stopped.
3. **Production deployment/security acceptance:** deploy only behind an independently reviewed HTTPS reverse proxy; validate secure cookies, HSTS, trusted-proxy client-IP configuration, secret provisioning/rotation, firewall boundaries, backups and an independent dependency/threat-model review.
4. **Protected lab certification:** run the current required real-lab suite on the approved GNS3/mac80211_hwsim host, retain original PCAP/hash/evidence, and complete the operator-approved DHCP renewal/rebind window. Do not substitute synthetic PCAPs or hosted CI.
5. **Physical target certification:** where a real device adapter is in scope, run authorized image verification, flash, reboot, version verification and rollback on the specified hardware; retain operator and approval evidence. Fake adapters are contract tests only.
6. **Runner version identity:** the release manifest still reports the Runner application version as not declared. The frontend package version is not a Runner release version.
7. **Cloud/SaaS:** full Phase O remains future scope until standalone operational acceptance is complete. The standalone Runner does not require Cloud to execute locally.

### Readiness interpretation

`SOURCE_IMPLEMENTED`, `HOSTED_CI_GREEN`, `CLEAN_MACHINE_REHEARSED`, `REAL_LAB_CERTIFIED`, `PHYSICAL_TARGET_CERTIFIED` and `PRODUCTION_RUNTIME_CERTIFIED` are separate states. A release may be source/CI verified while remaining uncertified for live lab, physical target or production deployment.
