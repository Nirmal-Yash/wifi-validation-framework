# NetRegress — Technical Architecture

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
