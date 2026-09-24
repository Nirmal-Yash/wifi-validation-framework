# NetRegress — Release Readiness

## Purpose

This is the source-of-truth release checklist for the standalone Runner. It distinguishes **source/repository readiness** from **runtime certification readiness**.

The current completeness audit was performed on 2026-09-24 against the pre-audit main release state `7ad58e0648fdb4eaa06b14c9c8d6db62358327fc`.

## Source completeness result

**94% source implementation completeness.**

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

The remaining source-level deductions are limited to the first-class multi-project domain model, complete live wiring of all protocol analyzers into protected execution tests, and fuller frontend coverage of administrative operations.

## Production-readiness assessment

### Overall

**Estimated production readiness: 88%.**

This percentage is an audit score, not a process exit code. It weights:
- source completeness and architecture: 50%;
- operational/security readiness: 25%;
- execution/certification evidence: 25%.

| Dimension | Assessment |
|---|---:|
| Architecture and domain integrity | 94% |
| Orchestration and failure handling | 94% |
| Evidence and measurement | 90% |
| Firmware/device lifecycle | 95% |
| API/security/release controls | 93% |
| Operations/recovery/synchronization | 92% |
| Frontend operational surface | 82% |
| Real execution certification evidence | 70% |
| **Overall production readiness** | **88%** |

## Post-audit CI dependency correction

The first post-push CI run failed during dependency installation because Netmiko 4.7.0 requires Paramiko >=3.5.0 while the repository had pinned Paramiko 3.4.0. The repository pin is now corrected to Paramiko 3.5.1; the source score below reflects the correction, while runtime certification remains a separate gate. citeturn124826search0turn124826search1

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
