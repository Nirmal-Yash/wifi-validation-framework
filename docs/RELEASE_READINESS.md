# NetRegress — Release Readiness

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
