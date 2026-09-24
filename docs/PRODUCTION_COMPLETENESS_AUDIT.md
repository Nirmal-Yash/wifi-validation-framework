# NetRegress — Production Completeness Audit

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
| Frontend security | React mutations did not supply CSRF or idempotency headers. | API client now obtains CSRF tokens and automatically sends CSRF/idempotency headers for mutations. |
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

- **Source completeness: 94%** — implementation contracts are substantially represented and the audited defects are closed, with the residual gaps above.
- **Operational/security readiness: 93%** — durable idempotency, CSRF, rate limiting, path confinement, release gates, recovery and readiness checks are present.
- **Execution certification readiness: 70%** — source and simulated controls are in place, but protected REAL_LAB and runtime/browser evidence is not established by this source audit.

**Overall production readiness: 88%.**

The system is therefore **source-complete enough for dedicated production certification**, but it should not be represented as fully runtime-certified until the protected execution gates are actually run and their evidence is persisted.
