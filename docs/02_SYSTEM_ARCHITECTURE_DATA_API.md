# NetRegress — System Architecture, Data Model & API

> Canonical document for backend architecture, service boundaries, execution flow, persistence model, data ownership, and API contracts.
>
> This document aggregates the former Technical Architecture and Data Model/API documents. The two source specifications are preserved as authoritative technical sections and are organized under one backend contract.

Companion canonical documents:
- docs/01_DEVELOPMENT_PLAN_AND_ROADMAP.md
- docs/02_SYSTEM_ARCHITECTURE_DATA_API.md
- docs/03_TRACEABILITY_AND_SYSTEM_READINESS.md
- docs/04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md
- docs/05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md

## 1. Backend contract

Runner responsibilities remain local and authoritative for execution facts:

configuration
→ Run / Attempt creation
→ lab/resource control
→ test execution
→ evidence collection
→ telemetry / metrics
→ persistence
→ regression evaluation
→ release decision
→ offline synchronization

Cloud/SaaS is deferred and, when introduced, owns business-control concerns rather than replacing raw execution authority.

## 2. Canonical technical architecture

## 1. Architecture goal

The target architecture separates test intent, orchestration, device control, evidence, persistence, regression and presentation while preserving the proven GNS3/mac80211_hwsim laboratory.

## 2. Target architecture

~~~text
CLI / Dashboard / CI
        |
     Run API / CLI
        |
   +----v-----+
   |RunService|
   +----+-----+
        |
   +----v------------------+
   | Run Orchestrator      |
   +--+----------+---------+
      |          |
 +----v----+ +---v--------+
 |LabHealth| | Test Engine|
 +----+----+ +------+-----+
      |             |
      |       +-----v-----+
      |       |TestRegistry|
      |       +-----+-----+
      |             |
      |       +-----v-----+
      +-------+ CommandRunner
              +-----+-----+
                    |
              DeviceAdapter
                    |
               lab/device
~~~

## 3. Layer ownership

API and CLI create Runs, query history and expose authorized operations.

Application services own lifecycle, policy and orchestration.

Domain models own Run, Attempt, TestResult, Metric, Sample, Artifact, LabHealth and Baseline semantics.

Execution owns pytest integration and test metadata.

Device adapters own vendor/device-specific behavior.

Infrastructure owns SSH, command execution, capture, traffic and lab control.

Repositories own persistence.

Presentation consumes versioned API contracts.

## 4. Current-to-target mapping

| Current component | Target responsibility |
|---|---|
| lib/db_helper.py | repository and service implementation |
| lib/connector.py | CommandRunner transports |
| lib/fault_injector.py | fault service using CommandRunner |
| lib/capture.py | CaptureService and capture transport |
| lib/wifi_analyzer.py | protocol evidence services |
| tests/conftest.py | pytest-to-Run integration |
| regression/fw_simulator.py | fake Device/Firmware adapters |
| dashboard/app.py | versioned API and UI integration |
| wifi_lab_reprovision_robust.sh | compatibility launcher over LabController |

## 5. Dependency rules

- Domain code does not import Flask.
- Tests do not directly open database connections.
- Adapters do not decide Run business outcomes.
- Repositories do not implement release policy.
- Dashboard does not query SQLite directly once version 1 APIs are active.

## 6. Dependency injection

New services receive explicit dependencies. Process-global singleton state is removed.

Each Run receives an isolated RunContext that is not reused across concurrent Runs.

## 7. RunContext

RunContext contains Run ID, Attempt ID, selected lab, device, resolved configuration, CommandRunner, ArtifactService, logger and timing context.

## 8. Test Registry

TestRegistry provides immutable semantic identity and metadata for every test.

Metadata covers test ID, version, categories, protocol, severity, criticality, capability requirements, prerequisites, thresholds and evidence requirements.

Pytest remains the physical execution engine.

## 8A. Statistical measurement policies

Statistical evaluation is separated from raw sample collection.

`MetricCollector` preserves every observed `Sample`. `MeasurementPolicy` defines the eligible sample population and authoritative aggregate. `MetricDefinition` binds the policy to a metric name/unit, and `StatisticSummary` contains all initial aggregates:

- count;
- minimum;
- maximum;
- mean;
- median;
- p90;
- p95;
- population standard deviation.

Warm-up samples are always excluded from aggregates. Samples with disallowed status are excluded. A retried sample is still one measurement; retry metadata does not create additional statistical observations. Outliers are retained in the raw history and therefore remain reproducible.

Performance tests declare an explicit `decision_metric` in the `TestRegistry`. The evaluator exposes that metric's configured aggregate as the decision value. The current compatibility configuration uses a minimum of one sample so existing one-measurement tests retain their execution behavior; higher minimums can be declared per test without changing the collector contract.

## 9. DeviceAdapter

Generic responsibilities:

~~~text
connect
disconnect
health
diagnostics
capabilities
version
execute
execute_shell
wifi_state
network_state
~~~

No test case contains vendor-specific branching.

## 10. FirmwareAdapter

Generic operations:

~~~text
identify
validate_image
upload
prepare
flash
reboot
wait_ready
verify_version
rollback
~~~

The first physical adapter should target Linux/OpenWRT-compatible hardware.

## 11. CommandRunner

Implementations:

- NetmikoRunner;
- ParamikoExecRunner;
- LocalRunner.

CommandResult contains command ID, host, safe display command, exit code, stdout, stderr, duration, timeout information, privilege context and idempotency metadata.

## 12. Command execution contract

`CommandRunner` is the single structured execution seam for local and device commands. `NetmikoRunner` wraps the existing `ConnectionPool` without changing its connection/retry behavior; `ParamikoExecRunner` provides non-interactive SSH execution with explicit timeout metadata; `LocalRunner` executes without a shell unless `execute_shell()` is explicitly requested. Every execution returns a `CommandResult` carrying a command ID, target, safe display command, output, exit status when available, duration, timeout metadata, privilege/idempotency context and transport errors. The raw foreground Paramiko channel used by DHCP tcpdump remains outside this abstraction so its lifecycle behavior is preserved.

## 13. Command security and evidence

SecureCommandRunner decorates each transport with CommandSecurityPolicy enforcement. Structured execution is the default and rejects shell operators; shell execution is explicit and allow-listed. Destructive operations are authorized only by documented per-target policy prefixes. Privilege handling is normalized to non-interactive sudo -n. Command and output content is redacted before results, lifecycle events or artifacts are persisted. Each executed command produces a COMMAND_EXECUTED event and, for Run-scoped runners, contributes to a COMMAND_OUTPUT evidence artifact.

The existing pytest connection_pool fixture is now a compatibility facade over SecureCommandRunner, so legacy test code receives the same security controls without changing node IDs. The AP DHCP capture test retains its raw Paramiko foreground-channel escape hatch because its long-lived tcpdump lifecycle is a protected behavioral requirement.
## 14. CaptureService

Capture lifecycle:

~~~text
start
→ ready
→ trigger
→ stop
→ verify
→ transfer
→ hash
→ register
~~~

The current AP br0 DHCP capture remains the behavioral reference.

## 15. LabController

LabController gradually absorbs reusable provisioning logic:

- GNS3 communication;
- node discovery and lifecycle;
- hwsim placement/state;
- interface wiring;
- service readiness;
- client preparation;
- router service setup;
- AP readiness;
- controlled recovery.

## 16. LabHealthService

LabHealthService is a read-only infrastructure gate executed before and after each Run. It produces a typed `LabHealthSnapshot` containing per-component status, duration, diagnostics, evidence references and tool metadata. Coverage includes GNS3/project nodes, Docker, libvirt, hwsim PHY placement in the AP/client namespaces, management SSH, AP/client/router/monitor interfaces, DHCP, DNS, iperf3, disk capacity and clock synchronization.

Health states are `HEALTHY`, `DEGRADED`, `FAILED`, and `UNKNOWN`. A required component in `FAILED` state blocks execution and transitions the Run to `LAB_FAILED`. `DEGRADED` and `UNKNOWN` remain contextual health state and do not trigger repair. Every snapshot is registered as `LAB_HEALTH_SNAPSHOT`; unhealthy snapshots additionally register a `DIAGNOSTIC_BUNDLE`. The service never silently repairs or reprovisions the lab.

## 17. Environment fingerprint

Capture host OS/kernel, Python, tool versions, GNS3, Docker, hostapd, wpa_supplicant, FRR, hwsim state, repository commit and effective configuration hash.

## 18. Persistence

Services depend on repositories.

Phase 1 repositories use SQLite. Later they use SQLAlchemy/PostgreSQL without changing the service contracts.

## 19. Transaction boundaries

TestResult, its metrics and artifact references should be committed atomically.

Physical artifacts are created and verified first. Orphan reconciliation handles files whose database registration failed.

## 19A. FaultService

`FaultService` is the controlled fault-injection boundary used by recovery tests. A `FaultDefinition` declares a stable fault ID, target, apply commands, restore commands and description. Apply/restore commands execute only through the Run's secured `CommandRunner`, so command authorization and audit evidence remain centralized.

The fault context always executes restoration, including when the fault application or validation body raises. Recovery tests therefore follow:

~~~text
baseline
→ apply fault
→ verify disruption
→ restore
→ verify recovery
~~~

The service does not decide whether disruption or recovery constitutes a product outcome; the test assertion and Run orchestration retain that responsibility.

## 19B. ProtocolEvidenceService

`ProtocolEvidenceService` consumes verified PCAP artifacts and derives typed protocol evidence without modifying the raw capture.

Supported correlation:
- DHCP transaction ID + client identity with ordered DORA detection;
- EAPOL endpoint grouping + four-way handshake key-message ordering;
- beacon SSID/BSSID/channel/RSN/cipher/AKM/beacon-interval/capability extraction;
- DNS transaction ID + question correlation.

The service writes JSON evidence only after packet parsing succeeds. The raw PCAP remains authoritative, and compatibility functions in `lib/wifi_analyzer.py` delegate to this service.

## 20. Lifecycle events

Persist significant events such as RUN_CREATED, RUN_STARTED, LAB_HEALTH_STARTED, LAB_HEALTH_COMPLETED, TEST_STARTED, TEST_COMPLETED, ARTIFACT_CREATED, BASELINE_PROMOTED, RUN_COMPLETED and RUN_CANCELLED.

## 21. Error taxonomy

~~~text
FrameworkError
 ├── ConfigurationError
 ├── DeviceError
 ├── LabError
 ├── TestExecutionError
 ├── ArtifactError
 ├── FirmwareError
 └── PersistenceError
~~~

Adapters raise technical exceptions. Run Orchestrator translates them into Run/Test business semantics.

## 22. Lifecycle translation

~~~text
SSH timeout
→ DeviceUnavailable
→ Lab Health FAILED
→ Run LAB_FAILED
~~~

~~~text
test assertion failure
→ TestResult FAIL
→ blocking policy evaluation
→ Run REJECTED
~~~

## 23. Concurrency

One physical lab may own only one active Run.

Device locks use two conceptual classes:

- DEVICE_EXCLUSIVE for flash, reboot and configuration mutation;
- NETWORK_CONCURRENT for compatible read, capture and measurement work.

## 24. Timeout model

Commands and jobs may define connection timeout, execution timeout, idle timeout and total timeout.

Timeout reason is persisted.

## 25. Retry model

Retry only when the operation is explicitly idempotent and the retry cannot hide state mutation.

Never blindly retry firmware flashing, tc mutation, interface state mutation, DHCP mutation or arbitrary shell commands.

## 26. Offline Runner

Runner stores raw execution state locally if Cloud is unavailable and synchronizes later.

Cloud disconnection must not alter a technical outcome already observed locally.

## 27. SaaS boundary

This repository remains the Runner/Core validation engine.

The future Cloud backend owns Organization, Project, identity, release policy, baseline promotion workflow, waivers and Cloud history.

The Runner owns lab/device execution and raw evidence.

### Test Registry and RunContext
The Runner maintains a semantic TestRegistry mapped 1:1 to stable pytest node IDs. Test definitions carry version, category, protocol, severity, criticality, equipment, direction, prerequisites, destructive flag, duration, capabilities, metric/threshold definitions and evidence requirements.

Each pytest session exposes a RunContext carrying Run/Attempt identity, lab/device, resolved configuration, TestRegistry, ArtifactService, a typed CommandRunner and structured logger. The existing pytest CLI and node IDs remain unchanged.


## 19C. WiFi telemetry

`WifiTelemetryService` provides a read-only measurement seam over the secured `CommandRunner`.

For a selected WiFi interface it observes:

- `wpa_cli signal_poll` for RSSI, noise, link speed and frequency when available;
- `iw dev <iface> link` for connection/frequency/signal and bitrate/PHY-mode details;
- `iw dev <iface> station dump` for observed transmit retry/failure counters and peer bitrate.

The service derives SNR only when both RSSI and noise are actually observed, and channel only from an observed frequency. Missing fields remain absent with warnings.

Every `TelemetryPoint` carries `VIRTUAL_WIFI` or `PHYSICAL_WIFI` plus source, interface and timestamp. The current lab is configured as `VIRTUAL_WIFI`; the schema is intentionally identical for future physical adapters.

Telemetry is contextual evidence and does not become an authoritative PASS metric unless a future TestRegistry definition explicitly opts into it. Virtual hwsim telemetry never represents RF certification.


## 19D. RegressionIntelligenceService

`RegressionIntelligenceService` is the canonical Run-to-Run comparison seam for Phase 7.

It:
- resolves an explicit baseline Run by ID;
- reads the latest Attempt from baseline and current Runs;
- verifies profile/lab/test-definition/environment comparability;
- evaluates functional status transitions;
- evaluates multiple metrics through the TestRegistry's frozen MeasurementPolicy;
- applies explicit per-test/per-metric percentage overrides;
- emits typed `NO_BASELINE` and `UNVALIDATED` classifications;
- retains flaky history as diagnostic context.

The legacy `regression/regression_classifier.py` and firmware-string diff CLI remain compatibility paths and are intentionally not repointed in this slice.


## 19E. DashboardQueryService

DashboardQueryService is the read-only presentation boundary between persisted repositories and Flask/Jinja/API consumers. It does not execute tests, mutate Runs, trigger lab health, or repair infrastructure.

It resolves the latest Attempt for Run detail, serializes TestResult/Metric/Sample/Artifact state, and provides derived telemetry/health views only after artifact path containment and SHA-256 verification.

The legacy dashboard remains available; /api/v1 is the canonical contract for new consumers.


## 28. Device/Firmware adapter implementation

`lib/adapters` is the Phase 9 execution seam. Device-specific behavior stays out of pytest tests.

`DeviceCapabilities` is machine-readable and includes firmware, reboot, WiFi and transport capabilities. Unsupported firmware operations are rejected by capability rather than by an accidental command failure.

`FirmwareImage` is immutable image metadata. `SSHFirmwareAdapter` verifies image integrity before upload and remote SHA-256 after upload. Optional detached GPG signatures are fatal when supplied but unverifiable.

`FirmwareOperationService` translates adapter stages into immutable lifecycle events. It never assigns Run business outcomes and never performs implicit rollback.

RunContext now exposes optional `device_adapter` and `firmware_adapter` instances. The current pytest session constructs them without performing firmware mutation.

## 29. Internal CI / release gate

The CI boundary has two execution classes: GitHub-hosted core CI for source and policy contracts, and self-hosted lab CI for the protected topology. ReleaseGateEvaluator consumes normalized Run/regression facts rather than raw output and never executes device commands.

## 30. Offline Runner synchronization

`RunnerSyncService` is the Runner-side outbox boundary. `SyncEnvelope` snapshots persisted facts without exposing local filesystem paths. `SyncQueueRepository` stores durable state in SQLite, including idempotency key, attempts, lease expiry and last error.

A transport failure affects only synchronization state. It never mutates Run/TestResult business outcomes and never reruns validation. Expired in-flight leases become retryable. After the configured retry budget, an item becomes `BLOCKED` for intervention.

The explicit `scripts/netregress_sync.py` command performs outbound synchronization when connectivity is available.

## 3. Canonical data model and API contract

## 1. Data model objective

The persistence model changes from latest-row semantics to explicit Run-scoped evidence.

Core relationship:

~~~text
Organization
  └─ Project
      ├─ Lab
      ├─ Device
      ├─ Firmware
      ├─ Baseline
      └─ Run
          └─ Attempt
              └─ TestResult
                  ├─ Metric
                  │   └─ Sample
                  └─ Artifact
~~~

## 2. Run

Required fields:

| Field | Meaning |
|---|---|
| run_id | ULID primary identity |
| display_id | human readable Run ID |
| project_id | owning Project when Cloud exists |
| lab_id | selected lab |
| device_id | selected target |
| firmware_version | human label |
| firmware_artifact_id | exact firmware reference when available |
| profile | validation profile |
| lifecycle_status | mechanical Run state |\n| environment_health | latest observed lab health rollup |
| business_outcome | validation decision |
| evidence_state | completeness of evidence |
| started_at | UTC start |
| completed_at | UTC completion |
| config_hash | effective configuration identity |
| environment_hash | environment identity |
| repository_commit | code version |
| created_at | Run creation time |

## 3. Attempt

Attempt separates explicit reruns from one logical Run.

Fields:

- attempt_id;
- run_id;
- sequence_number;
- lifecycle status;
- start/end times;
- failure reason;
- worker/runner identity;
- environment snapshot reference.

## 4. TestResult

Fields:

- test_result_id;
- attempt_id;
- semantic test_id;
- pytest node ID;
- test version;
- status;
- criticality;
- severity;
- classification set;
- error code/message;
- started_at;
- completed_at;
- evidence state;
- reproduction command/reference.

## 5. Metric

One TestResult may contain multiple metrics.

Fields:

- metric_id;
- test_result_id;
- metric name;
- unit;
- aggregation policy;
- decision value;
- baseline value;
- delta percentage;
- regression classification.
- measurement policy and authoritative decision aggregate.
- derived decision value from the configured aggregate.

## 6. Sample

Raw measurement history is preserved.

Fields:

- sample_id;
- metric_id;
- sequence;
- sample status;
- raw value;
- unit;
- started_at;
- completed_at;
- warmup flag;
- retry count;
- raw command reference;
- diagnostic metadata.

Valid statistical samples are distinguished from RETRIED or failed measurements.

## 6A. Statistical measurement policy

`MeasurementPolicy` is immutable run/test-definition metadata containing the authoritative statistic, minimum eligible sample count, allowed sample statuses and retry inclusion rule.

`StatisticSummary` is derived from raw samples and includes count, minimum, maximum, mean, median, p90, p95 and population standard deviation. Warm-up samples are excluded from the eligible population, outliers are retained, and retry metadata never multiplies the sample count.

Historical raw samples remain authoritative. Aggregate values are derived from the frozen test-definition/policy version rather than silently replacing the original sample history.

## 7. Artifact

Fields:

- artifact_id;
- run_id;
- optional test_result_id;
- type;
- storage key/path;
- display name;
- size bytes;
- SHA-256;
- created_at;
- evidence state;
- sensitivity class;
- retain_until;
- soft_deleted_at.

Artifact types:

- PCAP;
- PYTEST_REPORT;
- DIFF_REPORT;
- SETUP_LOG;
- AUDIT_LOG;
- COMMAND_OUTPUT;
- CONFIG_SNAPSHOT;
- LAB_HEALTH_SNAPSHOT;
- ENV_FINGERPRINT;
- DIAGNOSTIC_BUNDLE;
- FIRMWARE_REFERENCE;
- PROTOCOL_EVIDENCE;
- TELEMETRY.

## 7A. Protocol evidence

`PROTOCOL_EVIDENCE` is a derived Run-scoped artifact linked to the original raw PCAP.

The derived JSON records correlation facts such as:
- DHCP transaction IDs, client identities, ordered DORA state and assigned address;
- EAPOL handshake key-message sequence and replay counters;
- beacon security/identity fields;
- DNS transaction IDs, questions, correlated response counts and answers.

Derived evidence never replaces the raw PCAP and is reproducible from that artifact.

## 7B. WiFi telemetry

A telemetry artifact contains an immutable `WifiTelemetrySnapshot` and one `TelemetryPoint` per observed measurement.

Each point stores:

- metric;
- value;
- unit;
- `VIRTUAL_WIFI` or `PHYSICAL_WIFI` environment class;
- source;
- interface;
- UTC capture timestamp;
- diagnostic metadata.

Current metric names include `rssi_dbm`, `snr_db`, `channel`, `frequency_mhz`, `bitrate_mbps`, `phy_mode`, `tx_retries_total` and `tx_failed_total`.

The raw source command output remains preserved through normal command auditing; the telemetry JSON is derived context and does not replace the underlying observation.

## 8. LabHealth

Each health snapshot contains component observations.

Component fields:

- component;
- status (`HEALTHY/DEGRADED/FAILED/UNKNOWN`);
- required flag;
- duration;
- diagnostic summary;
- details;
- evidence artifact;
- observed_at;
- tool/version metadata.

A Run records the worst observed health rollup across its BEFORE and AFTER snapshots. Health snapshots themselves remain immutable Run-scoped artifacts.

## 9. EnvironmentSnapshot

Frozen per Run.

Includes OS, kernel, Python, pytest, repository commit, GNS3, Docker, hostapd, wpa_supplicant, FRR, hwsim state, package versions and configuration hash.

## 10. ConfigSnapshot

Stores the fully resolved configuration rather than only the original YAML file.

Include:

- WiFi parameters;
- network addresses;
- thresholds;
- selected profile;
- selected tests;
- device mapping;
- capture configuration;
- statistics policy;
- release policy version where relevant.

## 11. Baseline

Fields:

- baseline_id;
- project scope;
- name;
- baseline_run_id;
- device/device-family scope;
- firmware major scope;
- test suite version;
- lab class/environment scope;
- status;
- promoted_by;
- promoted_at;
- superseded_by.

Promoted records are immutable.

## 12. Regression

Regression comparison is attached to a baseline/current pair.

Fields:

- regression_id;
- baseline_run_id;
- current_run_id;
- test_result ID;
- dimension;
- classification;
- baseline metric;
- current metric;
- delta;
- threshold used;
- comparability status;
- explanation.

## 13. Event

Important lifecycle transitions become persistent events.

Minimum events:

- RUN_CREATED;
- RUN_STARTED;
- LAB_HEALTH_STARTED;
- LAB_HEALTH_COMPLETED;
- TEST_STARTED;
- TEST_COMPLETED;
- ARTIFACT_CREATED;
- BASELINE_PROMOTED;
- RUN_COMPLETED;
- RUN_CANCELLED;
- WAIVER_CREATED;
- FIRMWARE_FLASH_STARTED;
- FIRMWARE_FLASH_COMPLETED.

## 14. SQL migration direction

Phase 1 stays SQLite but uses repository interfaces.

Historical database migration must preserve available facts and explicitly mark missing information.

Future Cloud/PostgreSQL implementation uses SQLAlchemy and Alembic.

## 15. Data integrity rules

1. all internal timestamps are UTC;
2. lifecycle and business outcome are separate fields;
3. metric values have explicit units;
4. Run ID is mandatory for new TestResults;
5. artifact SHA-256 is mandatory for registered binary evidence;
6. promoted baselines are immutable;
7. evidence state cannot silently change to complete;
8. deleted artifacts retain an audit trail;
9. legacy records are identifiable as imported;
10. comparison always records which baseline Run was used.

## 16. Versioned API

New endpoints use /api/v1.

### Runs

GET /api/v1/runs

Filter by project, lab, device, firmware, status, outcome, profile and date.

POST /api/v1/runs

Creates/queues a Run. Supports idempotency key.

GET /api/v1/runs/{run_id}

Returns lifecycle, outcome, progress, health, tests, counts and evidence summary.

POST /api/v1/runs/{run_id}/cancel

Authorized cancellation.

POST /api/v1/runs/{run_id}/retry

Creates an explicit new Attempt or Run according to policy.

### Test results

GET /api/v1/runs/{run_id}/tests

Returns TestResult collection with metrics, evidence state and classifications.

GET /api/v1/runs/{run_id}/tests/{test_result_id}

Returns complete test detail.

### Metrics

GET /api/v1/tests/{test_id}/metrics

Historical metric data across Runs, subject to Project authorization.

GET /api/v1/runs/{run_id}/metrics

Run-wide measurement summary.

### Regression

GET /api/v1/regressions

Supports baseline/current run filtering.

GET /api/v1/runs/{run_id}/regressions

Returns classifications for one Run.

### Artifacts

GET /api/v1/artifacts

Searchable artifact metadata.

GET /api/v1/artifacts/{artifact_id}

Metadata and controlled download response.

### Telemetry

GET /api/v1/runs/{run_id}/telemetry

Returns Run-scoped WiFi telemetry snapshots with explicit environment class. Virtual and physical measurements use the same schema and remain distinguishable to every consumer.

### Lab Health

GET /api/v1/labs/{lab_id}/health

Latest health snapshot.

GET /api/v1/runs/{run_id}/health

Run-associated environment health.

### Baselines

GET /api/v1/baselines

POST /api/v1/baselines

Promote an eligible Run to baseline.

GET /api/v1/baselines/{baseline_id}

Retrieve immutable baseline metadata.

## 17. API error contract

Every API error uses:

~~~json
{
  "error": {
    "code": "EXAMPLE_CODE",
    "message": "Human-readable explanation",
    "details": {}
  }
}
~~~

## 18. Pagination

Collection endpoints support limit, cursor/page, sort and filter fields.

Large artifact lists are never returned unbounded.

## 19. Idempotency

POST /api/v1/runs accepts an idempotency key.

Repeated CI delivery of the same request must not create duplicate Runs.

## 20. OpenAPI

Commit an OpenAPI specification after the first stable v1 implementation.

Pydantic models should generate or validate the API schema.

## 21. Legacy routes

Existing /api routes remain during the Flask/Jinja transition.

They become compatibility wrappers around the new v1 services rather than separate implementations.

## 22. API invariants

1. APIs never fabricate missing tests.
2. APIs never convert LAB_FAILED to product FAIL.
3. APIs never promote partial evidence into PASS.
4. APIs return persisted evidence-derived state.
5. authorization happens before artifact access.
6. API responses remain compatible within the v1 contract.


## 13A. Regression comparison contract

The Runner's new regression service returns a derived `RunRegressionReport` containing:
- `baseline_run_id`;
- `current_run_id`;
- comparability status and reason;
- one `RegressionAssessment` per selected test;
- composable regression dimensions;
- one `RegressionMetricComparison` per compared metric;
- threshold used and percentage delta;
- optional flaky-history diagnostics.

This is derived analysis, not mutable source-of-truth test data. The source Run, Attempt, TestResult and Sample records remain authoritative.


## 24. Dashboard query and transport contract

The dashboard queries persisted Run/Attempt/TestResult/Artifact repositories rather than arbitrary filesystem paths. Derived telemetry and health JSON is consumed only after registered-path containment and SHA-256 verification.

Versioned API responses use:
- success: {data: ...};
- error: {error: {code, message, details}}.

The Phase 8 dashboard is read-only. State-changing Run/baseline operations remain service-layer capabilities until authenticated/RBAC API actions are introduced.


## 24A. Phase 8 collection behavior

Collection responses are paginated where historical growth can become unbounded, including Runs and Artifacts. Versioned API consumers must use the page/limit fields rather than assuming an unbounded result set.

Artifact metadata never exposes arbitrary filesystem content. Binary download is constrained to registered paths under the Results root and re-verifies SHA-256 before serving.


## 23. Runner synchronization envelope

`SyncEnvelope` is a content-addressed snapshot of Runner-authoritative facts. Fields include envelope ID, Runner ID, Run ID, schema version, idempotency key, payload SHA-256 and creation timestamp.

`SyncQueueItem` adds local delivery state: QUEUED, IN_FLIGHT, ACKED, FAILED or BLOCKED, attempt count, retry time, lease timestamp/expiry, and last error.

The v1 Cloud endpoint for these envelopes is intentionally not fixed in Iteration 19; only the Runner-side transport protocol and deterministic payload contract are established.

## 21. Iterations 23–25 additions
Run now carries explicit failure classification, failure reason and execution process identity. Firmware operations emit lifecycle state transitions. Release waivers are scoped and expiring. Canonical state-changing endpoints include Run launch/cancel/retry, baseline promotion, firmware update/rollback and waiver creation. docs/openapi.yaml is the versioned API contract.

## 25. Iterations 26–27 additions
State-changing v1 Run creation is now durable-idempotent: an Idempotency-Key is bound to a request fingerprint and cannot be replayed against a different payload. Authenticated browser mutations require CSRF protection. API responses expose security headers and constrained request sizes through the Flask boundary.

Runner operational controls now include SQLite backup/restore, stale-lock recovery, retention support and audit-chain integrity metadata in diagnostic bundles. Outbound synchronization applies HTTPS plus destination-address restrictions, and firmware mutation paths are confined to an explicit firmware root.

Iteration 27 adds a versioned certification matrix for the 11 final scenarios. The matrix records the execution class and required evidence controls without treating hardware-free fixtures as real-lab evidence.

## 4. Contract boundaries

- Domain: lifecycle and business invariants.
- Repositories: persistence contracts and transaction boundaries.
- Services: orchestration, policy, evidence, telemetry, regression, release, recovery.
- Adapters: device, firmware, command, lab and transport boundaries.
- API: authenticated, authorized and versioned external control/query contract.
- Artifacts: raw evidence remains authoritative; derived evidence never replaces it.
- Frontend: presentation over the canonical API, not the execution authority.
