# NetRegress — Testing and Operations Strategy

## 1. Purpose

This document defines the verification strategy for both the validation product and the framework refactor itself.

The framework must prove real system behavior, while the refactor must prove it did not silently weaken that validation.

## 2. Protected real-lab gate

The current GNS3/mac80211_hwsim suite remains mandatory for any change affecting execution, networking, provisioning, capture, adapters or orchestration.

Command:

~~~bash
pytest tests/ -v --firmware-version=v1.0
~~~

Expected baseline: 11/11 PASS.

## 3. Test layers

### Layer 1 — Unit

Pure business/domain logic.

Examples:

- Run lifecycle;
- classifier;
- sample aggregation;
- threshold calculation;
- configuration resolution;
- artifact hashing;
- capability matching.

### Layer 2 — Component

Service boundaries with fake dependencies.

Examples:

- RunService;
- LabHealthService;
- ArtifactService;
- CommandRunner;
- TestRegistry.

### Layer 3 — Adapter integration

Fake and local Linux adapters exercise orchestration without real hardware.

### Layer 4 — API contract

Validate request/response schemas and error contracts.

### Layer 5 — Migration

Load a copy of the historical SQLite database and verify migrated data and baselines.

### Layer 6 — Real lab

Real GNS3/mac80211_hwsim validation remains the acceptance gate for actual network behavior.

## 4. Current test inventory

Keep the existing tests and node IDs unchanged during Phase 1:

- WPA2 authentication;
- DHCP lease assignment;
- DHCP timing;
- DNS resolution;
- WiFi fault and recovery;
- real DHCP packet capture;
- ping reachability;
- packet loss;
- latency;
- SSID state;
- throughput.

## 5. Evidence requirements

Every test definition declares required evidence.

Examples:

| Test | Required evidence |
|---|---|
| WPA authentication | EAPOL evidence or explicitly defined state evidence |
| DHCP | correlated DORA evidence |
| DNS | query/response correlation |
| throughput | raw samples + aggregate metrics |
| fault recovery | fault action + disruption + recovery |

Required evidence failure produces UNVALIDATED, not PASS.

## 6. Statistical validation

Performance tests use:

- configurable sample count;
- warm-up iterations;
- raw sample persistence;
- median/p95 and other aggregates;
- explicit authoritative metric;
- retained outliers.

Do not silently discard samples or silently replace one failure with a successful retry.

## 6A. Statistical policy verification

Unit tests must verify:

- all configured initial aggregates;
- deterministic percentile interpolation;
- warm-up exclusion;
- exclusion of disallowed sample statuses;
- retry metadata does not duplicate observations;
- minimum sample enforcement;
- metric name/unit compatibility;
- explicit performance-test decision metrics.

The raw `Sample` collection must remain unchanged by aggregate evaluation.

## 7. Failure taxonomy tests

Explicitly inject and verify:

- GNS3 unavailable;
- hwsim unavailable;
- AP unreachable;
- client unreachable;
- router unavailable;
- SSH timeout;
- DHCP failure;
- DNS failure;
- capture failure;
- artifact copy failure;
- database unavailable;
- worker crash;
- Runner disconnect;
- command timeout;
- malformed firmware;
- incompatible firmware;
- reboot failure.

The expected classification must distinguish infrastructure failure from product failure.

## 8. Lab Health verification

Every Run records before/after Lab Health.

Health components must be independently testable.

Health checks are expected to verify both the check logic and the diagnostic artifact generated when a component fails. The component set includes GNS3/project nodes, Docker, libvirt, namespace-scoped hwsim PHYs, management SSH, AP/client/router/monitor interfaces, DHCP, DNS, iperf3, disk and clock/NTP. A required FAILED health result must block test execution and produce LAB_FAILED; DEGRADED/UNKNOWN must remain visible without triggering automatic repair.

## 9. CommandRunner verification

Test:

- structured command result parsing;
- exit code handling;
- stdout/stderr capture;
- timeout handling;
- idempotent retry;
- no retry for mutation;
- sudo handling;
- redaction;
- allow-list enforcement.

## 10. Command security acceptance

Security component tests must prove shell injection rejection, executable allow-list enforcement, destructive-command authorization, centralized sudo -n normalization, secret redaction in command/output/error material, COMMAND_EXECUTED audit events and Run-scoped COMMAND_OUTPUT artifact registration. Real-lab verification remains mandatory because standard pytest command routing changed.
## 11. Artifact verification

Test:

- registration;
- SHA-256;
- file existence;
- corrupted artifact detection;
- missing artifact detection;
- orphan reconciliation;
- authorization on download;
- soft deletion and audit trail.

## 12. Database migration verification

Use the actual current SQLite schema/data as a migration fixture.

Verify:

- all historical test results preserved;
- firmware labels preserved;
- metrics preserved;
- baseline history recoverable;
- imported records clearly marked;
- new Run IDs created only where justified;
- no invented evidence;
- indexes present;
- post-migration queries return expected results.

## 13. Regression verification

Classifier tests must cover:

- PASS to FAIL;
- FAIL to PASS;
- PASS to PASS degradation;
- PASS to PASS improvement;
- no baseline;
- unvalidated evidence;
- incompatible test version;
- multiple metrics;
- per-test thresholds;
- environment mismatch.

## 14. Flaky-test verification

Generate controlled sequences where outcomes alternate under unchanged conditions.

Verify the framework flags inconsistency without replacing raw history with the eventual PASS.

## 15. API contract verification

Every versioned endpoint must have schema validation for:

- success response;
- validation error;
- authorization failure;
- not found;
- infrastructure failure;
- pagination;
- filtering;
- idempotency.

## 16. Security tests

Verify:

- no credential leakage;
- secret redaction;
- dashboard authentication;
- Project-level authorization;
- artifact ACL;
- command injection resistance;
- path traversal resistance;
- HMAC verification;
- idempotency-key behavior;
- audit event generation.

## 17. Real-lab change gate

Any code change affecting these areas requires the 11-test gate:

- connector;
- fault injection;
- capture;
- traffic;
- WiFi analyzer;
- pytest fixtures;
- reprovisioning;
- device adapters;
- Run orchestration.

If the physical lab is unavailable, state that limitation explicitly. Do not claim the real-lab gate passed.

## 18. Operational run modes

### Full validation
Provision lab, run health, execute full test suite, collect evidence.

### Setup only
Provision and validate environment without running tests.

### Repro-test
Reset runtime WiFi state, reprovision and run the full suite.

### Configuration normalization
Explicitly rewrite configuration only when requested.

Existing shell flags remain supported during migration.

## 19. Operational evidence

Expected runtime directories:

~~~text
results/test_results.db
results/reports/
results/captures/
results/setup-logs/
~~~

Runtime evidence remains gitignored.

## 20. Acceptance gates by phase

### Phase 1
- new Run IDs present;
- existing CLI works;
- legacy DB migration passes;
- 11/11 real-lab suite.

### Phase 1S
- security checks pass;
- credentials removed from tracked config;
- authentication/authorization active.

### Phase 2
- Lab Health distinguishes healthy/degraded/failed;
- diagnostic bundle generated;
- real suite remains green.

### Phase 3
- raw samples and aggregates persisted;
- statistical thresholds work;
- performance suite remains valid.

### Phase 7
- NO_BASELINE and UNVALIDATED are distinct;
- richer classification works;
- incompatible comparisons are blocked.

### Phase 8
- dashboard uses v1 APIs;
- run detail and evidence pages work;
- read-only behavior remains secure.

### Phase 9
- fake adapter integration suite passes;
- physical adapter can identify/flash/verify where available;
- rollback path tested if supported.

## 21. Regression-proof refactor rule

The framework is itself a system under validation.

Every functional refactor must prove:

~~~text
old intended behavior preserved
+
new behavior correctly evidenced
+
no weakened assertion
~~~


## 22. Iteration 12 recovery validation

The expanded functional suite contains explicit disruption/recovery cases for:

- WPA2 wrong-PSK rejection and recovery;
- WiFi disconnect/reconnect;
- DHCP renewal;
- DHCP service interruption and lease recovery;
- DNS failure/recovery;
- AP hostapd restart/recovery;
- client wpa_supplicant restart/recovery.

Each destructive case preserves the management path and must prove both the fault and the restored data/control path. Fault application and restoration are audited through CommandRunner, and FaultService restores state in a finalization boundary.

The original 11 validation tests remain the protected behavioral subset. Because Iteration 12 adds real network-mutating tests, both the protected subset and the expanded recovery suite require execution on the GNS3/mac80211_hwsim lab before this iteration can be considered runtime-verified.

Protocol-accurate DHCP T2 rebind is not inferred from a generic lease reacquisition. That assertion is reserved for the later transaction-aware DHCP evidence phase.

## 23. Iteration 13 protocol evidence validation

Protocol analyzer tests must verify:

- DHCP correlation by transaction ID and client identity;
- DORA ordering rather than independent packet counts;
- EAPOL four-way message ordering;
- beacon RSN/cipher/AKM extraction;
- DNS query/response transaction correlation;
- raw PCAP remains unchanged after analysis;
- derived protocol evidence can be serialized and registered as Run-scoped evidence.

The real DHCP capture test must continue using the protected AP `br0` tcpdump + SFTP + SHA-256 path while its assertion is upgraded from packet count/ACK presence to correlated DORA evidence.

## 24. Iteration 14 telemetry validation

Telemetry unit tests must verify:

- parsing of `wpa_cli signal_poll`, `iw link` and `iw station dump`;
- RSSI/SNR/frequency/channel/bitrate extraction;
- PHY-mode extraction only from observed driver bitrate data;
- retry/failure counters remain explicitly labeled as counters;
- environment class is present on the snapshot and every point;
- invalid interfaces are rejected before command execution;
- completely missing source observations are not converted into fabricated measurements;
- JSON serialization preserves environment class on every point.

The telemetry service uses read-only commands through `SecureCommandRunner`; it does not alter the protected DHCP capture or validation traffic paths.


## 25. Iteration 15 regression-intelligence validation

Targeted tests must verify:
- explicit baseline Run identity;
- incompatible environment/profile/lab/test-definition context is blocked;
- missing comparison context is never guessed;
- PASS→FAIL and FAIL→PASS classification;
- multiple metrics use declared statistical decision values;
- per-test/per-metric thresholds override the compatibility default;
- missing current results become `UNVALIDATED`;
- invalid current evidence becomes `UNVALIDATED`;
- baseline-side invalid evidence prevents comparison;
- new tests remain explicitly visible as `NEW_PASS`/`NEW_FAILURE`;
- flaky history is retained without mutating the primary classification.

The legacy firmware-string regression path remains a compatibility boundary and is not treated as the authoritative Phase 7 engine.


## 26. Iteration 16 dashboard/API validation

Targeted verification must cover:
- /api/v1 success and error envelope consistency;
- Run filters and pagination;
- Run/Test detail from persisted Run/Attempt/TestResult state;
- explicit-baseline regression comparison;
- visible incompatible/missing comparison context;
- performance sample history;
- telemetry environment/source/timestamp presentation;
- health snapshot display without repair;
- artifact SHA-256 verification before JSON interpretation;
- artifact download containment under results/;
- legacy /api/* compatibility routes.


## 27. Iteration 17 adapter validation

Adapter tests cover capability declarations, Linux/OpenWrt profile behavior, version parsing, image hash/model validation, explicit authorization, nominal lifecycle, flash failure, reboot failure without implicit rollback and explicit rollback.

Operational acceptance still requires real-hardware flash/reboot/rollback tests against the supported device family before production firmware control is enabled. Those physical operations were not executed in this environment.

## 28. Iteration 18 CI gate

The always-on GitHub-hosted job is hardware-free and runs ci_tests outside the real-lab pytest conftest. The protected lab job is explicitly dispatchable on a self-hosted netregress-lab runner. The persisted release evaluator rejects missing or invalid release evidence instead of treating unavailable infrastructure as a product PASS.

## 29. Iteration 19 offline operation

At Run completion, the pytest session attempts to enqueue a local snapshot. Queue failure emits a warning and does not change the Run outcome.

Synchronization is explicit through `python scripts/netregress_sync.py --url https://...`. Temporary connectivity failures remain retryable. Stale in-flight leases are recoverable. Repeated delivery uses the same idempotency key so the future Cloud can safely deduplicate accepted envelopes.

The current environment has no configured Cloud endpoint, so no external synchronization was attempted.

## Iterations 23–25 operational implementation
Failure taxonomy, process cancellation, diagnostic bundle generation, reproduction manifests, explicit firmware lifecycle and release/baseline controls are implemented as Runner operational paths. The dedicated Debugging Phase is the validation stage for real execution, lab behavior and fault-injection scenarios; implementation work should not add alternate fake production paths to satisfy that phase.
