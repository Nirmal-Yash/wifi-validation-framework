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
