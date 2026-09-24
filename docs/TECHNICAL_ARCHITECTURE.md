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

## 12. CaptureService

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

## 13. LabController

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

## 14. LabHealthService

LabHealthService diagnoses environment health and captures evidence. It does not silently repair a failing lab.

Health coverage includes GNS3, Docker, libvirt, hwsim, AP, client, router, management, DHCP, DNS, iperf3, SSH, disk and clock synchronization.

## 15. Environment fingerprint

Capture host OS/kernel, Python, tool versions, GNS3, Docker, hostapd, wpa_supplicant, FRR, hwsim state, repository commit and effective configuration hash.

## 16. Persistence

Services depend on repositories.

Phase 1 repositories use SQLite. Later they use SQLAlchemy/PostgreSQL without changing the service contracts.

## 17. Transaction boundaries

TestResult, its metrics and artifact references should be committed atomically.

Physical artifacts are created and verified first. Orphan reconciliation handles files whose database registration failed.

## 18. Lifecycle events

Persist significant events such as RUN_CREATED, RUN_STARTED, LAB_HEALTH_STARTED, LAB_HEALTH_COMPLETED, TEST_STARTED, TEST_COMPLETED, ARTIFACT_CREATED, BASELINE_PROMOTED, RUN_COMPLETED and RUN_CANCELLED.

## 19. Error taxonomy

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

## 20. Lifecycle translation

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

## 21. Concurrency

One physical lab may own only one active Run.

Device locks use two conceptual classes:

- DEVICE_EXCLUSIVE for flash, reboot and configuration mutation;
- NETWORK_CONCURRENT for compatible read, capture and measurement work.

## 22. Timeout model

Commands and jobs may define connection timeout, execution timeout, idle timeout and total timeout.

Timeout reason is persisted.

## 23. Retry model

Retry only when the operation is explicitly idempotent and the retry cannot hide state mutation.

Never blindly retry firmware flashing, tc mutation, interface state mutation, DHCP mutation or arbitrary shell commands.

## 24. Offline Runner

Runner stores raw execution state locally if Cloud is unavailable and synchronizes later.

Cloud disconnection must not alter a technical outcome already observed locally.

## 25. SaaS boundary

This repository remains the Runner/Core validation engine.

The future Cloud backend owns Organization, Project, identity, release policy, baseline promotion workflow, waivers and Cloud history.

The Runner owns lab/device execution and raw evidence.

### Test Registry and RunContext
The Runner maintains a semantic TestRegistry mapped 1:1 to stable pytest node IDs. Test definitions carry version, category, protocol, severity, criticality, equipment, direction, prerequisites, destructive flag, duration, capabilities, metric/threshold definitions and evidence requirements.

Each pytest session exposes a RunContext carrying Run/Attempt identity, lab/device, resolved configuration, TestRegistry, ArtifactService, a future CommandRunner slot and structured logger. The existing pytest CLI and node IDs remain unchanged.