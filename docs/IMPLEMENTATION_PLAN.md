
# NetRegress — Detailed Refactor & Implementation Plan

## 1. Purpose

This document converts the frozen Architecture Decision Record into an executable repository refactor sequence.

The objective is to evolve the proven WiFi validation engine into a run-scoped, evidence-driven, statistically rigorous, secure Runner core without rewriting the working GNS3/mac80211_hwsim laboratory.

## 2. Protected starting point

Behavioral baseline:

~~~text
436026eba597b2c6ae2e291a9cd8054b70ebbf7c
~~~

Observed validation:

~~~text
11 / 11 real-lab tests PASS
~~~

Protected behaviors:

- GNS3 topology and node roles.
- mac80211_hwsim AP/client placement.
- client management through eth1 while WiFi validation uses wlan0.
- DHCP service path.
- AP-side DHCP capture on br0.
- dedicated Paramiko tcpdump lifecycle.
- real DHCP traffic and SHA-256 PCAP verification.
- existing pytest node IDs.
- existing pytest CLI.
- existing provisioning CLI.
- real traffic only; no synthetic validation traffic.

## 3. Governing refactor rule

Every change follows:

~~~text
design
→ compatibility boundary
→ additive implementation
→ targeted verification
→ full real-lab regression
→ evidence inspection
→ documentation update
→ commit to main
~~~

No broad rewrite of a working subsystem is allowed merely because its current structure is imperfect.

## 4. Phase 0 — Baseline protection

### Work

1. Verify current main state.
2. Preserve the behavioral baseline SHA.
3. Record the 11-test execution command.
4. Verify runtime results remain gitignored.
5. Record baseline artifact locations.
6. Keep the existing shell invocation behavior unchanged.

### Gate

The real lab must pass all 11 current tests.

## 5. Phase 1 — Domain model and persistence foundation

### Target model

~~~text
Run
 ├── Attempt
 │    ├── TestResult
 │    │    ├── Metric[]
 │    │    │    └── Sample[]
 │    │    └── Artifact[]
 │    ├── lifecycle events
 │    └── diagnostics
 ├── EnvironmentSnapshot
 ├── ConfigSnapshot
 └── Run-level artifacts
~~~

### New package boundaries

~~~text
lib/domain/
lib/models/
lib/repositories/
lib/services/
~~~

Initial domain objects:

- Run
- Attempt
- TestResult
- Metric
- Sample
- Artifact
- EnvironmentSnapshot
- ConfigSnapshot
- LifecycleEvent
- Baseline
- Regression

Repositories:

- RunRepository
- AttemptRepository
- TestResultRepository
- ArtifactRepository
- BaselineRepository
- EventRepository

### Compatibility

The current db_helper functions remain temporarily and delegate to the new service/repository layer.

This prevents a destructive rewrite of existing callers.

### Run creation

The Run exists before the first test result.

The CLI remains:

~~~bash
pytest tests/ -v --firmware-version=v1.0
~~~

### Frozen Run snapshot

Record:

- run ID;
- display ID;
- firmware;
- lab ID;
- validation profile;
- selected tests;
- test-definition versions;
- resolved configuration;
- configuration hash;
- repository commit;
- environment fingerprint;
- thresholds;
- timestamps.

### Acceptance

- every test result has a run ID;
- the old CLI still works;
- legacy queries remain valid;
- historical DB migration works;
- the real 11-test suite remains green.

## 6. Phase 1A — Test Registry and RunContext

Introduce an explicit test registry containing semantic metadata.

Minimum metadata:

- test ID;
- test version;
- category;
- protocol;
- severity;
- criticality;
- equipment;
- direction;
- prerequisites;
- destructive flag;
- estimated duration;
- capability requirements;
- metric definitions;
- threshold definitions;
- evidence requirements.

Introduce a RunContext carrying:

- run ID;
- attempt ID;
- lab;
- device;
- resolved config;
- command runner;
- artifact service;
- logger.

Existing pytest fixtures remain compatible while new services are injected through the context.

## 7. Phase 1B — Multiple metrics and raw samples

Replace the single metric-value model with a Metric collection.

A TestResult may contain:

~~~text
latency
packet loss
jitter
throughput
CPU
memory
interface utilization
~~~

Raw samples are always preserved.

Retrying a measurement command is not the same as collecting another valid statistical sample.

## 8. Phase 1C — Artifact registry

Introduce ArtifactService.

Artifact lifecycle:

~~~text
create
→ verify
→ hash
→ register
→ available
~~~

Artifact metadata:

- artifact ID;
- Run ID;
- optional TestResult ID;
- type;
- physical path;
- display name;
- size;
- SHA-256;
- timestamp;
- evidence state;
- sensitivity classification;
- retention metadata.

Phase 1 uses the local results directory.

## 9. Phase 1D — Historical database migration

The current SQLite file becomes migration input.

Historical rows without Run IDs are imported into synthetic historical Runs.

Do not invent missing information.

Imported historical records must carry a clear legacy/imported indicator so they cannot be confused with fully instrumented Runs.

Migration must be tested using a real copy of the current database.

## 10. Phase 1E — Security gate

The security gate runs alongside Phase 1.

Required:

- credentials removed from tracked YAML;
- environment/secret based credential resolution;
- secret scrubbing;
- authenticated local dashboard;
- role-aware authorization boundary;
- command construction audit;
- destructive-command allow list;
- safe artifact access;
- privileged-action audit logging.

A repository scan must find no operational credentials in tracked configuration.

## 11. Phase 1F — CommandRunner extraction

Current command execution is split across Netmiko, raw Paramiko, local subprocess, tests, fault injection and capture code.

Unify behind:

~~~text
CommandRunner
 ├── NetmikoRunner
 ├── ParamikoExecRunner
 └── LocalRunner
~~~

Command results must be structured:

- command ID;
- host/device;
- safe display command;
- stdout;
- stderr;
- exit code;
- duration;
- connect timeout;
- execution timeout;
- idle timeout where relevant;
- timed-out state;
- idempotent flag;
- privilege mode.

Retries are allowed only when explicitly safe.

State mutation commands such as link changes, traffic-control changes and DHCP mutations are not blindly retried.

## 12. Phase 2 — Lab Health and lab control

Create:

- LabHealthService;
- LabController;
- EnvironmentFingerprintService.

Extract provisioning logic incrementally from the current shell script.

First extraction order:

1. GNS3 connectivity.
2. GNS3 project discovery.
3. required node discovery.
4. management path validation.
5. hwsim PHY validation.
6. interface/carrier validation.
7. AP validation.
8. client validation.
9. router validation.
10. DHCP validation.
11. DNS validation.
12. iperf validation.
13. SSH validation.
14. disk space.
15. clock/NTP.

### Health states

~~~text
HEALTHY
DEGRADED
FAILED
UNKNOWN
~~~

Run behavior:

- FAILED before execution blocks the test set.
- DEGRADED may run but is recorded.
- mid-run infrastructure collapse becomes LAB_FAILED.
- every failed health component produces diagnostic evidence.

Automatic repair is not silent.

## 13. Phase 2B — Configuration normalization

Use:

~~~text
defaults
→ environment
→ lab
→ device
→ run
→ test override
~~~

YAML remains human-authored.

Shell constants migrate gradually into structured configuration.

The existing provisioning CLI stays operational during migration.

## 14. Phase 3 — Statistical rigor

### New concepts

- Sample;
- MetricDefinition;
- MeasurementPolicy;
- StatisticSummary.

### Initial statistics

- count;
- minimum;
- maximum;
- mean;
- median;
- p90;
- p95;
- standard deviation.

Warm-up samples remain diagnostic but are excluded from aggregates.

Outliers are retained, never silently discarded.

Each performance test declares the aggregate metric used for its decision.

## 15. Phase 4 — Functional WiFi expansion

Add:

- wrong PSK behavior;
- disconnect/reconnect;
- DHCP renewal;
- DHCP rebind;
- DNS failure/recovery;
- AP restart recovery;
- client restart recovery;
- DHCP server failure/recovery.

Every negative test proves both disruption and recovery.

~~~text
baseline
→ fault
→ expected disruption
→ evidence
→ restore
→ recovery
→ evidence
~~~

## 16. Phase 5 — Protocol evidence

Replace packet-count validation with transaction-aware protocol evidence.

DHCP:
- correlate DISCOVER → OFFER → REQUEST → ACK using transaction ID and client identity;
- preserve the assigned address and server identifier where available;
- do not treat independent message counts as a valid transaction.

EAPOL:
- identify the ordered WPA four-way handshake messages 1/4 through 4/4;
- correlate the exchange to the same endpoints and replay sequence.

Beacon checks:
- SSID;
- BSSID;
- channel;
- RSN presence;
- group/pairwise cipher;
- AKM;
- beacon interval;
- capabilities.

DNS:
- correlate query and response by transaction ID and question;
- preserve response/answer data;
- distinguish unmatched queries from correlated responses.

Protocol evidence is immutable Run-scoped derived evidence. The raw PCAP remains the source of truth. No analyzer may synthesize or repair missing protocol frames.

## 17. Phase 6 — WiFi telemetry

Initial fields:

- RSSI;
- SNR;
- channel;
- frequency;
- bitrate;
- PHY mode;
- retry counters where available.

Iteration 14 introduces a typed `WifiTelemetrySnapshot` made of immutable `TelemetryPoint` values. Every point carries the environment class, source command/derivation, interface, capture timestamp, unit and observed value.

Supported environment classes are:

~~~text
VIRTUAL_WIFI
PHYSICAL_WIFI
~~~

The current virtual GNS3/mac80211_hwsim lab is labeled `VIRTUAL_WIFI`. Physical adapters can emit the same schema with `PHYSICAL_WIFI`.

Virtual hwsim measurements are diagnostic/network-behavior telemetry only. They are never presented as RF certification or as proof of calibrated physical radio performance.

Telemetry collection is read-only and must execute through `SecureCommandRunner`. No telemetry value is synthesized when its source observation is unavailable.

## 18. Phase 7 — Regression Intelligence 2.0

Required improvements:

- explicit baseline Run reference;
- per-test thresholds;
- multiple metrics;
- environment comparability;
- NO_BASELINE;
- UNVALIDATED;
- composable regression dimensions;
- flaky-test history.

Automatic comparison is rejected when evidence, test definition or environment compatibility is insufficient.

## 19. Phase 8 — Dashboard 2.0

Keep Flask/Jinja.

New API-first routes:

~~~text
/runs
/runs/<run_id>
/runs/<run_id>/tests/<test_result_id>
/regressions
/performance
/telemetry
/lab-health
/artifacts
~~~

The dashboard must answer:

- what ran;
- firmware;
- lab;
- environment;
- pass/fail;
- failure cause;
- baseline;
- regression classification;
- evidence;
- reproduction information.

Continue ten-second polling initially.

## 20. Phase 9 — Device and Firmware adapters

Introduce DeviceAdapter and FirmwareAdapter.

Reference fake implementation:

~~~text
fw_simulator
~~~

Real first transport:

~~~text
SSH/SCP
~~~

Optional second:

~~~text
TFTP
~~~

Firmware lifecycle:

~~~text
identify
→ validate image
→ compatibility check
→ upload
→ prepare
→ flash
→ reboot
→ wait ready
→ verify version
→ validate
→ optional authorized rollback
~~~

No automatic flash or rollback.

## 21. Phase 10a — Internal CI gate

~~~text
commit
→ configuration validation
→ Lab Health
→ Run
→ evidence
→ regression
→ release gate
~~~

Default fail-closed conditions:

- blocking regression;
- disallowed soft regression;
- NO_BASELINE;
- UNVALIDATED;
- missing required test;
- invalid required evidence.

## 22. Phase 10b — NetRegress Cloud

Cloud owns:

- organizations;
- projects;
- identities;
- policies;
- baselines;
- waivers;
- release decisions;
- CI integration.

Runner owns:

- labs;
- devices;
- execution;
- raw evidence;
- offline queue;
- synchronization.

Cloud jobs initially use Celery/Redis.

Labs are exclusive resources and cannot run two concurrent Runs.

## 23. Phase 11 — PostgreSQL

Only move beyond SQLite once multi-tenant concurrency is real.

Use:

- SQLAlchemy;
- Alembic;
- PostgreSQL.

Move large evidence to object storage only when retention and scale justify it.

## 24. Completion gate

A phase is complete only when:

1. documentation and implementation agree;
2. targeted tests pass;
3. failure paths are verified;
4. database migrations are verified where relevant;
5. APIs satisfy their contract where relevant;
6. affected artifacts are inspected;
7. real 11-test validation remains green whenever execution/network behavior changed.

## 25. Immediate implementation sequence

1. Preserve/tag behavioral baseline.
2. Add typed domain models.
3. Add repository interfaces.
4. Add Run and Attempt.
5. Integrate conftest without CLI breakage.
6. Add Metric and Sample collections.
7. Add ArtifactService.
8. Add historical DB migration.
9. Extract CommandRunner.
10. Apply Phase 1S security controls.
11. Extract LabHealthService.
12. Add statistical policies.

Only then expand functional WiFi coverage.


## 18A. Iteration 15 — Regression Intelligence 2.0

The new regression path is Run-scoped and requires an explicit `baseline_run_id`. Firmware version strings remain only a compatibility lookup for the legacy CLI.

Comparability is fail-closed:
- validation profile must match;
- lab identity must match;
- selected tests and frozen test-definition versions must match;
- both environment classes must be supplied and equal.

A comparable baseline is never inferred from the nearest firmware run.

For PASS→PASS results, each metric is evaluated independently using its declared `MeasurementPolicy`. Per-test/per-metric percentage thresholds may be supplied under the Run's `regression.thresholds` configuration; the existing 20% behavior remains the compatibility default.

The evaluator emits composable regression dimensions, explicit `NO_BASELINE`/ `UNVALIDATED` states and optional flaky-history diagnostics. Flaky history never erases the underlying Attempt/result.
