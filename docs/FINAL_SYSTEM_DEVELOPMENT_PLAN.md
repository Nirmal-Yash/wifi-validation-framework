# NetRegress — Final System Development Plan

## 0. Purpose

This is the authoritative implementation plan for all development after the current Iteration 19 Runner state.

It consolidates the previously granular Iterations 20–36 into **8 larger, coherent implementation iterations**. Each iteration represents a complete architectural slice with an executable implementation scope, verification scope, and completion gate.

During development, this document is the primary iteration-context document. Existing architecture, business-logic, data-model, execution, security, frontend, testing, and operations documents remain authoritative for their respective contracts; this document determines implementation order and grouping.

The target is a certified production-grade standalone NetRegress Runner. Cloud/SaaS control-plane implementation is intentionally deferred until the standalone Runner is complete and certified.

---

## 1. Protected Baseline and Non-Negotiable Rules

### 1.1 Protected behavioral baseline

Baseline commit:

```
436026eba597b2c6ae2e291a9cd8054b70ebbf7c
```

Protected documented behavior:

- GNS3 topology and node roles.
- `mac80211_hwsim` placement: `phy0` AP, `phy1` client.
- Client management over `eth1`; WiFi validation over `wlan0`.
- DHCP service path.
- AP-side DHCP capture on `br0`.
- Dedicated Paramiko foreground SSH channel for protected tcpdump capture.
- Real PCAP retrieval and SHA-256 verification.
- Existing pytest node IDs.
- Existing pytest CLI invocation.
- Existing provisioning CLI and flags.
- Real traffic only; no synthetic traffic in real validation paths.

Canonical real-lab invocation remains:

```bash
pytest tests/ -v --firmware-version=v1.0
```

The documented historical reference is 11/11 real-lab tests passing. This baseline must be re-established whenever the execution environment permits before claiming completion of execution-affecting iterations.

### 1.2 Engineering rules

1. **Runner first:** finish and certify the standalone Runner before implementing Cloud.
2. **Evidence over assertions:** required evidence missing, invalid, or unverifiable means `UNVALIDATED`, never `PASS`.
3. **Fault isolation:** lab, infrastructure, worker, Runner, timeout, and synchronization faults do not become DUT product failures.
4. **No synthetic proof:** analyzers may derive facts from captured evidence but may never synthesize missing protocol traffic.
5. **No destructive silent retry:** firmware flash, lab mutation, validation tests, and other non-idempotent operations are never blindly retried.
6. **No credential leakage:** operational secrets are never committed to tracked configuration.
7. **No concurrent physical-lab execution:** exclusive labs/devices/resources are locked.
8. **Compatibility first:** existing CLI, pytest node IDs, provisioning behavior, and protected capture paths remain usable while internal ownership is migrated.
9. **Layering:** Controller -> Service -> Adapter/Repository. Tests consume contracts; they do not bypass production boundaries.
10. **Documentation/code synchronization:** every behavior, contract, schema, lifecycle, API, or architecture change updates the applicable documentation in the same implementation iteration.
11. **No placeholder production paths:** no stubs, TODO-only implementations, fake production behavior, or temporary bypasses may remain on a completion path.
12. **Runtime truth is separate from source implementation:** a feature is not called verified until its relevant execution gate has actually run.

---

## 2. Development and Git Workflow

### 2.1 Iteration workflow

Every iteration is executed completely before starting the next:

1. Read this plan plus the relevant architecture documents and current source.
2. Audit the existing implementation against the iteration requirements.
3. Write the implementation plan internally from the actual current state; do not assume the code matches documentation.
4. Implement the complete iteration, including code, tests, migrations, API/UI updates, and documentation.
5. Run targeted verification.
6. Run broader regression appropriate to the changed layers.
7. Run the real 11-test protected suite whenever execution, networking, provisioning, capture, adapters, orchestration, or persistence behavior is affected.
8. Inspect evidence/results rather than relying only on process exit codes.
9. Update documentation and status only after verification.
10. Do not move to the next iteration while a completion-gate requirement remains unresolved.

### 2.2 Commit policy

**No implementation commits are to be pushed during the execution of these iterations.**

All implementation work remains in the working tree until the complete program is finished and every final certification gate passes.

At the end of the entire plan:

- stage the complete final codebase;
- verify there are no unintended files;
- verify all required tests and certification scenarios;
- create **one single commit on `main`**;
- use this commit message:

```
feat(runner): complete production-grade validation platform
```

No intermediate iteration commits, micro-commits, scratch commits, or temporary implementation commits are to be pushed.

---

# ITERATION 20 — FOUNDATION FREEZE, SECURITY, AND ARCHITECTURAL RECONCILIATION

## Objective

Make the post-Iteration-19 repository internally coherent and safe before large implementation changes.

This iteration is a prerequisite for every subsequent iteration.

## 20.1 Establish the authoritative system state

Create:

```
docs/CURRENT_SYSTEM_STATE.md
```

It must classify every major subsystem as exactly one of:

- Implemented
- Partially Implemented
- Deferred
- Unverified
- Production Blocker

The file must identify, at minimum:

- domain/persistence;
- Run/Attempt lifecycle;
- TestRegistry/RunContext;
- CommandRunner/SecureCommandRunner;
- LabHealthService;
- configuration resolution;
- LabController;
- environment fingerprinting;
- protocol evidence;
- telemetry;
- regression intelligence;
- dashboard/API;
- authentication/RBAC;
- device/firmware adapters;
- release gate;
- offline synchronization;
- database migrations;
- frontend;
- real-lab verification.

## 20.2 Reconcile documentation drift

Audit and reconcile:

- `ARCHITECTURE_DECISIONS.md`
- `IMPLEMENTATION_PLAN.md`
- `IMPLEMENTATION_ROADMAP.md`
- `BUSINESS_LOGIC.md`
- `DATA_MODEL_AND_APIS.md`
- `EXECUTION_AND_ADAPTERS.md`
- `SECURITY_AND_SAAS.md`
- `TESTING_AND_OPERATIONS.md`
- `FRONTEND_DESIGN.md`
- `AGENT_CONTEXT.md`
- source tree;
- database schema;
- pytest fixtures;
- API routes;
- scripts;
- adapters.

Remove stale statements that identify older iterations as current work. Never mark implementation as verified merely because source code exists.

## 20.3 Security baseline cleanup

Remove operational credentials from tracked files.

Audit at minimum:

```
configs/
.env.example
tests/
scripts/
docs/
CI configuration
```

Use environment/secret resolution for runtime credentials.

Implement or normalize:

- secret redaction;
- credential loading boundary;
- secure storage boundary;
- authentication boundary;
- artifact authorization boundary;
- privileged-action audit events.

The repository scan must contain zero operational credentials.

## 20.4 Production security and RBAC foundation

Implement local authentication and authorization primitives needed by the remaining standalone platform.

Roles:

```
OWNER
ADMIN
OPERATOR
VIEWER
```

Authorization must be project-scoped for:

- runs;
- tests;
- devices;
- labs;
- artifacts;
- baselines;
- firmware operations;
- administrative settings.

Implement secure password hashing, session/token lifecycle, idle/absolute expiry, logout, and protected middleware.

State-changing operations must be authorization-gated, not merely hidden in UI.

## 20.5 Completion gate

Iteration 20 is complete only when:

- `CURRENT_SYSTEM_STATE.md` is accurate;
- documentation no longer contradicts the source tree;
- tracked configuration contains no operational secrets;
- protected routes have an authorization decision;
- existing CLI/provisioning behavior remains compatible;
- no architectural implementation work is started with unresolved contract drift.

---

# ITERATION 21 — DETERMINISTIC ORCHESTRATION, CONFIGURATION, LAB CONTROL, AND RESOURCE OWNERSHIP

## Objective

Move execution ownership out of pytest/session plumbing and shell-script-heavy behavior into deterministic Python orchestration while keeping compatibility boundaries intact.

## 21.1 ConfigurationResolver

Implement a first-class configuration subsystem with exact precedence:

```
Defaults
  ↓
Environment
  ↓
Lab
  ↓
Device
  ↓
Run
  ↓
Test Override
```

Requirements:

- typed configuration sources;
- deterministic merge;
- explicit conflict detection;
- no silent overwrite of incompatible values;
- immutable `ResolvedConfiguration`;
- deterministic `ConfigurationHash`;
- `ConfigurationProvenance` explaining every final value;
- persisted configuration snapshot attached to the Run;
- compatibility with current YAML configuration.

Test overrides may modify only fields explicitly permitted by the test definition.

## 21.2 EnvironmentFingerprintService

Create a dedicated service responsible for reproducible environment identity.

Fingerprint inputs should include, where applicable:

- lab identity;
- GNS3 project identity;
- topology;
- node roles/state;
- `mac80211_hwsim` topology and PHY state;
- interfaces and carrier state;
- kernel version;
- driver/module versions;
- device identity;
- firmware version;
- selected configuration;
- relevant service versions;
- environment class.

Produce:

```
EnvironmentFingerprint
EnvironmentSnapshot
FingerprintHash
```

The fingerprint is deterministic and persisted with the Run.

## 21.3 LabController

Create the Python owner for lab lifecycle operations.

Responsibilities:

- GNS3 project discovery/validation;
- node discovery;
- topology validation;
- hwsim provisioning/validation;
- namespace/interface operations;
- AP/client/router/monitor readiness;
- service lifecycle operations required by tests;
- cleanup;
- controlled restoration.

Migration strategy:

1. preserve `wifi_lab_reprovision_robust.sh`;
2. move one responsibility at a time behind Python interfaces;
3. retain the shell script as a thin compatibility launcher;
4. do not duplicate conflicting provisioning logic in Python and shell;
5. delete obsolete duplicated implementation only after parity is demonstrated.

The protected DHCP Paramiko capture path is not replaced by a generic terminal mechanism.

## 21.4 Resource locking

Implement exclusive resource leases for:

- lab;
- device;
- network namespace/resource;
- firmware operation.

Each lock requires:

- resource identity;
- owner;
- acquisition timestamp;
- lease expiry;
- timeout;
- release;
- stale-lock detection;
- stale-lock recovery;
- audit event.

A second Run requiring an occupied exclusive resource must be deterministically rejected or queued.

## 21.5 RunOrchestrator

Create the concrete executable orchestration path:

```
CLI/API
  ↓
RunOrchestrator
  ↓
RunService
  ↓
ConfigurationResolver
  ↓
LabController
  ↓
LabHealthService
  ↓
EnvironmentFingerprintService
  ↓
pytest / TestRegistry
  ↓
RunContext
  ↓
CommandRunner / DeviceAdapter
  ↓
Metrics / Evidence / Telemetry / Artifacts
  ↓
Regression
  ↓
Release Gate
  ↓
Run finalization
```

Responsibilities:

- construct the Run;
- resolve configuration;
- lock resources;
- perform preflight health;
- fingerprint environment;
- launch selected tests;
- handle lifecycle transitions;
- finalize outcome;
- release resources;
- create diagnostics;
- queue offline synchronization.

`conftest.py` becomes an integration adapter, not the primary orchestration owner.

## 21.6 Completion gate

- documented architecture matches executable call flow;
- no duplicate orchestration owners remain;
- configuration precedence is deterministic and tested;
- two conflicting Runs cannot share a locked resource;
- provisioning shell remains compatible;
- failed preflight never starts product validation;
- lock release works on success, failure, cancellation, timeout, and crash recovery.

---

# ITERATION 22 — EVIDENCE ENFORCEMENT, PROTOCOL VALIDATION, TELEMETRY, AND PERFORMANCE MEASUREMENT

## Objective

Turn evidence, packet protocol validation, telemetry, and performance measurements into mandatory execution lifecycle components rather than optional services.

## 22.1 Evidence contract

Implement the full pipeline:

```
TestDefinition
  ↓
EvidenceRequirement[]
  ↓
EvidenceCollector
  ↓
EvidenceValidator
  ↓
EvidenceState
  ↓
PASS / FAIL / UNVALIDATED
```

Rules:

- required evidence must be declared by test definition;
- evidence collection occurs automatically at lifecycle points;
- evidence is Run/TestResult scoped;
- source artifact integrity is verified before interpretation;
- invalid/missing required evidence blocks PASS;
- evidence analyzers never invent data.

## 22.2 Protocol evidence

Complete live integration for DHCP, EAPOL/WPA, 802.11 Beacon/RSN, and DNS.

### DHCP

Validate real transaction behavior using captured traffic:

```
DISCOVER
→ OFFER
→ REQUEST
→ ACK
```

Also implement:

- transaction-ID correlation;
- client identity correlation;
- server identifier;
- T1 renewal;
- T2 rebind;
- REBINDING;
- ACK/NAK handling;
- negative cases;
- incomplete transaction classification.

No synthetic DHCP packets.

### EAPOL/WPA

Correlate the ordered four-way handshake:

```
1/4 → 2/4 → 3/4 → 4/4
```

Correlation must include endpoint identity and appropriate replay/sequence semantics.

### Beacon/RSN

Validate where required:

- SSID;
- BSSID;
- channel;
- RSN presence;
- group cipher;
- pairwise cipher;
- AKM;
- beacon interval;
- capabilities.

### DNS

Correlate:

- query/response by transaction ID;
- question;
- answer;
- unmatched queries;
- malformed/failed responses.

## 22.3 Required evidence policy

Define when a test result may be:

```
PASS
FAIL
UNVALIDATED
```

Examples:

- assertion PASS + valid required evidence -> PASS;
- assertion PASS + missing required PCAP -> UNVALIDATED;
- assertion PASS + corrupt PCAP -> UNVALIDATED;
- assertion PASS + insufficient telemetry -> UNVALIDATED when telemetry is required;
- product assertion FAIL + valid evidence -> FAIL;
- lab failure -> LAB_FAILED, not product FAIL.

## 22.4 Telemetry lifecycle

Collect automatically at appropriate lifecycle points:

1. pre-test baseline;
2. in-test polling;
3. post-test state;
4. recovery state after negative/recovery tests.

Typed telemetry must include:

- RSSI;
- SNR;
- channel;
- frequency;
- bitrate/PHY rate;
- PHY mode;
- retries;
- failure counters;
- CPU;
- memory;
- interface drops/utilization;
- performance-tool context where applicable.

Every point must preserve:

- environment class;
- source command/derivation;
- interface;
- timestamp;
- unit;
- observed value.

No synthetic values.

Virtual lab telemetry must remain clearly classified as `VIRTUAL_WIFI`; it must never be presented as calibrated RF certification.

## 22.5 Performance measurement

Implement the complete matrix:

```
Downlink
Uplink
Bidirectional

TCP
UDP

Throughput
Latency
Jitter
Packet Loss
```

Use:

- warm-up samples;
- N measurement samples;
- raw-sample preservation;
- explicit measurement policy;
- deterministic aggregate selection;
- resource telemetry during measurement;
- environment fingerprint association.

Differentiate DUT regressions from host/resource starvation.

## 22.6 Negative/recovery validation

Every fault test proves:

```
baseline
→ inject fault
→ expected disruption
→ capture evidence
→ restore
→ recovery
→ capture recovery evidence
```

Coverage must include:

- wrong PSK;
- disconnect/reconnect;
- DHCP renewal;
- DHCP T2/rebind;
- DHCP server failure/recovery;
- DNS failure/recovery;
- AP restart;
- client WiFi restart;
- link flap.

Passing only recovery is insufficient; the expected disruption itself must also be proven.

## 22.7 Completion gate

- missing required evidence can never produce PASS;
- DHCP rebind/T2 is implemented and tested;
- protocol analyzers are live-wired into declared tests;
- telemetry automatically appears where required;
- performance statistics are deterministic;
- negative/recovery tests prove both fault and recovery;
- protected real-lab regression remains green for execution-affecting changes.

---

# ITERATION 23 — DEVICE/FIRMWARE OPERATIONS, FAILURE SEMANTICS, CANCELLATION, AND DIAGNOSTICS

## Objective

Finish physical-device lifecycle management and make all execution failure paths explicit, recoverable, auditable, and operationally useful.

## 23.1 Firmware artifact model

Implement complete firmware metadata:

- version;
- device model;
- hardware revision;
- architecture;
- SHA-256;
- signature;
- compatibility range;
- source/build provenance;
- release metadata.

Firmware image validation occurs before any upload.

## 23.2 Transport adapters

Unified firmware transport abstraction supporting:

- SSH/SCP/SFTP current implementation;
- TFTP implementation.

Transport choice must be adapter/configuration driven, never embedded in business logic.

## 23.3 Firmware state machine

Implement:

```
REGISTERED
→ VALIDATED
→ COMPATIBLE
→ AUTHORIZED
→ UPLOADING
→ UPLOADED
→ READY_TO_FLASH
→ FLASHING
→ REBOOTING
→ VERIFYING
→ VALIDATED
```

Failure:

```
FAILED
```

Every transition is persisted and audited.

Flash prerequisites:

- compatible device;
- validated image;
- checksum;
- signature where configured;
- explicit authorization;
- exclusive firmware-operation lock.

## 23.4 Firmware rollback

Rollback is explicit and authorized:

```
authorize
→ prepare rollback
→ rollback
→ reboot
→ readiness check
→ verify version
→ audit
```

Never automatically rollback after uncertain state.

Never silently retry firmware mutation.

## 23.5 Failure taxonomy

Separate:

```
PRODUCT_FAILED
LAB_FAILED
RUNNER_DISCONNECTED
WORKER_CRASHED
TIMED_OUT
CANCELLED
ABORTED
```

Lifecycle classification must distinguish product behavior, infrastructure/lab behavior, Runner behavior, worker behavior, timeout, and operator cancellation.

These classifications must not contaminate DUT-quality statistics.

## 23.6 Cancellation and timeout

Implement:

- per-test timeout;
- per-Run timeout;
- explicit cancellation;
- SIGINT handling;
- child-process termination;
- lock release;
- namespace cleanup;
- temporary-artifact cleanup;
- deterministic final state;
- partial-evidence retention.

A cancelled/timeout Run must not remain indefinitely in a transitional state.

## 23.7 Observability

Implement structured JSON logs with:

```
request_id
run_id
attempt_id
test_result_id
test_id
device_id
lab_id
severity
timestamp
event_type
```

Implement:

```
/api/v1/health
/api/v1/readiness
```

Health responses must expose component-level status without leaking secrets.

## 23.8 Diagnostic bundles

For abnormal Runs automatically capture relevant:

- structured logs;
- health snapshots;
- configuration snapshot;
- environment fingerprint;
- command audit;
- test lifecycle;
- exception/stack context;
- relevant PCAPs;
- telemetry;
- firmware-operation evidence.

Create a deterministic bundle manifest and integrity hash.

## 23.9 ReproductionManifest

Generate a machine-readable manifest containing:

- firmware;
- device;
- lab;
- environment fingerprint;
- configuration hash;
- test selection;
- test-definition versions;
- thresholds;
- dependencies;
- required artifacts.

Provide a CLI command that reconstructs the executable reproduction request without silently executing disruptive operations.

## 23.10 Completion gate

- injected crash produces `WORKER_CRASHED`;
- missing Runner/connection produces `RUNNER_DISCONNECTED`;
- timeout produces `TIMED_OUT`;
- cancellation cleans the lab;
- firmware incompatibility blocks before flash;
- corrupt firmware blocks before flash;
- real/fake adapter workflows follow the same state machine;
- every abnormal Run has usable diagnostics and reproduction metadata.

---

# ITERATION 24 — API CONTRACT, AUTHORIZED STATE CHANGES, FRONTEND, AND PERSISTENCE HARDENING

## Objective

Turn the current read-oriented dashboard/API into the complete local operational product while preserving authorization at the API layer.

## 24.1 OpenAPI contract

Create the canonical OpenAPI 3 specification for:

- authentication;
- projects;
- users/roles;
- labs;
- devices;
- firmware;
- Runs;
- Attempts;
- TestResults;
- metrics;
- telemetry;
- artifacts;
- baselines;
- regression;
- release gates;
- health;
- audit.

The API contract must define:

- request schemas;
- response schemas;
- standard error format;
- pagination;
- filtering;
- sorting;
- correlation IDs;
- idempotency;
- optimistic concurrency where needed;
- HTTP status conventions;
- versioning policy.

## 24.2 State-changing API

Implement and authorize:

```
POST /api/v1/runs
POST /api/v1/runs/{id}/cancel
POST /api/v1/runs/{id}/retry
POST /api/v1/baselines
POST /api/v1/baselines/{id}/promote
POST /api/v1/firmware/operations
POST /api/v1/firmware/{id}/rollback
```

Operation semantics must be idempotent where practical.

Retry endpoint must never mean blind re-execution of unsafe operations.

## 24.3 Contract testing

Use OpenAPI contract tests to verify:

- every route schema;
- request validation;
- response schema;
- status codes;
- auth/RBAC;
- pagination;
- error responses;
- idempotency behavior.

Hardware-free contract tests remain separate from real-lab execution.

## 24.4 React/Vite frontend

Build the production local dashboard using React + Vite.

Required product views:

- login;
- project selection;
- run launch;
- Run monitor;
- test results;
- evidence/PCAP inspection;
- telemetry;
- performance;
- regression;
- lab health;
- devices;
- firmware;
- baselines;
- release gate;
- audit;
- administration.

The UI may hide or disable unavailable actions based on role, but API authorization remains authoritative.

## 24.5 Real-time execution UX

Implement a polling or event stream contract that shows:

- Run lifecycle;
- current test;
- completed tests;
- evidence state;
- telemetry status;
- health state;
- failures;
- resource-lock state.

The initial implementation may use reliable polling; event streaming must not be introduced merely for visual effect.

## 24.6 Persistence hardening

Establish SQLAlchemy repository implementations behind stable repository interfaces.

Support:

- SQLite with WAL where appropriate;
- PostgreSQL-compatible model/schema;
- Alembic as the sole migration authority.

Index major query paths:

- project/run;
- run/test result;
- telemetry/run;
- artifact/run;
- baseline;
- regression;
- timestamp;
- device;
- firmware;
- environment fingerprint.

Historical migrations must preserve facts and provenance.

## 24.7 Completion gate

- OpenAPI is canonical;
- all state-changing routes are authorization-protected;
- contract tests cover every route;
- dashboard can launch/cancel/inspect a Run through the API;
- persistence schema is migration-controlled;
- legacy compatibility routes remain only where required and no longer own the new implementation.

---

# ITERATION 25 — BASELINE/REGRESSION/RELEASE INTELLIGENCE AND OFFLINE RUNNER FINALIZATION

## Objective

Finish the business decision layer inside the standalone Runner without mixing technical evidence with human release authorization.

## 25.1 Baseline lifecycle

Implement:

```
CANDIDATE
→ VALIDATED
→ ACTIVE
→ SUPERSEDED
```

Promoted baselines are immutable.

Promotion is an authorized action.

Historical baselines remain queryable.

## 25.2 Baseline comparability

Comparison requires compatible:

- project;
- device/device family;
- hardware revision;
- firmware scope;
- selected tests;
- frozen test-definition versions;
- validation profile;
- lab/environment class;
- relevant configuration;
- region/band/SKU where applicable.

A comparable baseline is never guessed from the nearest Run.

## 25.3 Regression evaluation

Maintain independent regression dimensions:

```
FUNCTIONAL
PERFORMANCE
CONFIGURATION
PROTOCOL
AVAILABILITY
RECOVERY
```

Maintain classifications:

```
REGRESSION
SOFT_REGRESSION
FIXED
IMPROVED
UNCHANGED
NEW_FAILURE
NEW_PASS
NO_BASELINE
UNVALIDATED
```

Keep functional outcome independent from metric regression.

## 25.4 Measurement-policy enforcement

Use frozen Run/test configuration for regression.

Every decision metric must identify:

- metric;
- unit;
- aggregate;
- minimum sample count;
- threshold;
- source samples.

Raw samples stay immutable.

Outliers remain retained and visible.

## 25.5 Release gate

Separate the three decisions:

1. Technical classification.
2. Automated release policy.
3. Human release approval.

The release gate must fail closed for:

- blocking regression;
- disallowed soft regression;
- missing required tests;
- invalid required evidence;
- `UNVALIDATED`;
- `NO_BASELINE` where baseline is required;
- incomplete Run;
- unhealthy required lab state.

Waivers are explicit, scoped, audited, and expiration-capable.

## 25.6 Offline Runner finalization

The existing durable sync queue becomes a stable Runner subsystem.

Requirements:

- terminal Run snapshot;
- deterministic content-addressed envelope;
- idempotency;
- lease/recovery;
- bounded retry;
- BLOCKED state;
- outbound-only synchronization;
- synchronization never changes the recorded technical result;
- artifacts remain locally authoritative until separate controlled transfer exists.

## 25.7 Completion gate

- baseline promotion rules work;
- regression comparison is fail-closed;
- release decision is deterministic;
- waiver use is explicit/audited;
- offline queue survives process restart and transport outage;
- synchronized and unsynchronized Runs have identical local technical outcomes.

---

# ITERATION 26 — FULL FAILURE INJECTION, MULTI-LAYER INTEGRATION, SECURITY HARDENING, AND RELEASE READINESS

## Objective

Prove the complete standalone platform behaves correctly under failure before final certification.

## 26.1 Failure injection matrix

Automate tests for:

- SSH timeout;
- device unavailable;
- DUT restart/crash;
- DHCP failure;
- DHCP recovery;
- DNS failure;
- GNS3 process unavailable;
- GNS3 project corruption/unavailability;
- hwsim missing;
- hwsim topology mismatch;
- interface/carrier failure;
- disk exhaustion;
- clock/NTP failure;
- command timeout;
- worker crash;
- Runner disconnect;
- network partition;
- synchronization endpoint unavailable;
- artifact corruption;
- database interruption;
- firmware checksum failure;
- firmware signature failure;
- firmware incompatibility;
- rollback failure;
- stale lock;
- duplicate job request;
- duplicate synchronization request.

For every injection verify:

- failure class;
- Run state;
- artifact preservation;
- cleanup;
- lock recovery;
- statistics isolation;
- ability to diagnose/reproduce.

## 26.2 Three-layer test architecture

### Layer 1 — Hardware-free

Run:

- domain tests;
- repository tests;
- service tests;
- configuration resolver tests;
- lock tests;
- orchestration tests;
- API/OpenAPI tests;
- RBAC tests;
- fake device/firmware adapter tests;
- regression tests;
- migration tests;
- sync queue tests.

### Layer 2 — Simulated integration

Use:

- fake lab;
- fake devices;
- fake firmware;
- network namespaces;
- controlled command failures;
- end-to-end orchestration.

Validate complete state transitions without physical hardware.

### Layer 3 — Real lab

Use:

- GNS3;
- `mac80211_hwsim`;
- real DHCP;
- real DNS;
- real iperf3;
- real traffic;
- real PCAP;
- real fault/recovery;
- protected capture path.

Synthetic fixtures must never be accepted by the real validation path.

## 26.3 Security hardening

Run and resolve:

- credential scanning;
- dependency vulnerability scans;
- Bandit;
- Semgrep;
- input validation;
- command-injection defenses;
- SSRF defenses;
- path traversal defenses;
- secure artifact handling;
- upload validation;
- rate limiting;
- replay protection;
- idempotency;
- secure cookies/tokens;
- CSRF protection where applicable;
- secure HTTP headers;
- audit integrity;
- encryption at rest/in transit where applicable;
- database access controls;
- backup/restore procedures.

No high/critical security finding may remain open for certification.

## 26.4 Operational hardening

Verify:

- graceful shutdown;
- restart recovery;
- database recovery;
- queue recovery;
- stale lock recovery;
- diagnostic bundle generation;
- log rotation/retention;
- result retention;
- artifact retention;
- export and deletion semantics;
- health/readiness behavior.

## 26.5 Completion gate

All failure-injection cases are classified correctly with no orphan processes, stale locks, dangling namespaces, corrupt final states, or contaminated product metrics.

All three test layers are green to the extent permitted by the available lab/hardware.

---

# ITERATION 27 — FINAL END-TO-END RUNNER CERTIFICATION AND DOCUMENTATION FREEZE

## Objective

Certify the complete standalone Runner as one coherent product.

No new features are introduced in this iteration. Only defects required to pass certification are fixed.

## 27.1 Certification scenario 1 — Healthy Run

Expected:

```
Run completed
→ all required tests pass
→ evidence complete
→ telemetry complete where required
→ regression policy satisfied
→ PASS / VALIDATED
```

Verify complete Run/Attempt/TestResult/Metric/Sample/Artifact lineage.

## 27.2 Certification scenario 2 — Real product failure

Introduce a controlled DUT/product failure.

Expected:

```
FAIL
```

Verify:

- evidence proves failure;
- product metrics reflect the failure;
- infrastructure statistics remain clean;
- Run lifecycle is complete.

## 27.3 Certification scenario 3 — Missing evidence

Cause an assertion to succeed while required evidence is unavailable or corrupt.

Expected:

```
UNVALIDATED
```

PASS must be impossible.

## 27.4 Certification scenario 4 — Lab failure

Break a required lab dependency.

Expected:

```
LAB_FAILED
```

Verify no product-quality contamination.

## 27.5 Certification scenario 5 — Runner failure

Simulate Runner/worker loss.

Expected:

```
RUNNER_DISCONNECTED
```

or

```
WORKER_CRASHED
```

with deterministic cleanup and recoverable diagnostics.

## 27.6 Certification scenario 6 — Timeout/cancellation

Trigger test timeout, Run timeout, and user cancellation.

Verify:

- deterministic final state;
- child cleanup;
- resource unlock;
- preserved evidence.

## 27.7 Certification scenario 7 — Concurrent execution

Start two Runs against the same exclusive lab/device.

Expected:

- one owns the resource;
- second Run is safely queued or rejected;
- no concurrent destructive access;
- no race-created inconsistent state.

## 27.8 Certification scenario 8 — Firmware lifecycle

Against supported target hardware or protected virtual target:

```
register
→ validate
→ compatibility check
→ authorize
→ upload
→ flash
→ reboot
→ verify
→ rollback if explicitly requested
```

Verify hashes, state transitions, audit trail, and failure safety.

## 27.9 Certification scenario 9 — Offline operation

Disconnect synchronization endpoint during Run.

Expected:

- Runner continues;
- Run result remains unchanged;
- terminal Run is queued;
- retry later succeeds;
- duplicate delivery is idempotent.

## 27.10 Certification scenario 10 — Restart recovery

Restart the application/worker after:

- Run creation;
- lock acquisition;
- test execution;
- terminal Run;
- sync claim.

Verify recovery without duplicate destructive operations.

## 27.11 Certification scenario 11 — Real-lab protected baseline

Execute the canonical 11-test real-lab suite and inspect:

- test outcomes;
- Run lifecycle;
- evidence state;
- DHCP PCAP;
- protocol evidence;
- telemetry;
- metrics;
- artifact hashes;
- lab health;
- environment fingerprint.

The protected baseline behavior must remain intact.

## 27.12 Final documentation freeze

Update and reconcile:

- `CURRENT_SYSTEM_STATE.md`;
- `AGENT_CONTEXT.md`;
- architecture documents;
- implementation roadmap;
- data/API documentation;
- security documentation;
- testing/operations documentation;
- frontend documentation;
- installation/run instructions.

Document the final Runner architecture and all verification results.

No document may claim a feature is verified when it was only source-audited.

## 27.13 Final repository audit

Before the final commit:

- scan for credentials;
- scan for debug code;
- scan for TODO/FIXME on production paths;
- scan for dead duplicate implementations;
- scan for stale compatibility paths;
- scan for untracked generated runtime data;
- scan for unexpected binary artifacts;
- verify migrations;
- verify API schemas;
- verify test inventory;
- verify documentation links;
- verify no accidental external endpoint dependency;
- verify no production feature depends on fake adapters.

---

# ITERATION 28 — FINAL SINGLE-COMMIT RELEASE INTEGRATION

## Objective

Package the entire completed implementation as one clean release commit on `main`.

This is a release-integration iteration only.

## 28.1 Freeze

After Iteration 27 certification:

- stop feature development;
- stop refactoring;
- do not introduce unrelated cleanup;
- do not alter protected behavior unless required by certification evidence.

## 28.2 Full verification

Run the complete available verification stack in final order:

1. static compilation/type checking;
2. linting;
3. unit tests;
4. service/repository tests;
5. API/OpenAPI contract tests;
6. migration tests;
7. security scans;
8. failure-injection suite;
9. simulated integration suite;
10. protected real-lab suite;
11. final documentation consistency check;
12. credential/secrets scan.

Record exact commands and results.

## 28.3 Working-tree audit

Require:

- only intended source/docs/config/test changes;
- no runtime databases;
- no logs;
- no PCAPs;
- no result dumps;
- no local credentials;
- no temporary files.

## 28.4 Single commit

Stage the entire finished implementation and create exactly one commit on `main`:

```
feat(runner): complete production-grade validation platform
```

Do not create any additional implementation commit after this point.

The final commit should contain the full completed standalone Runner implementation, frontend, APIs, persistence, tests, documentation, security hardening, and certification changes as one coherent release state.

---

# FINAL TARGET ARCHITECTURE

The completed standalone system must converge to:

```
                 ┌──────────────────────────────────────┐
                 │          Local NetRegress UI         │
                 │       React / Vite Operational UI    │
                 └──────────────────┬───────────────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────────┐
                 │             Versioned API             │
                 │ Auth / RBAC / Runs / Tests / Evidence│
                 │ Telemetry / Regression / Firmware    │
                 └──────────────────┬───────────────────┘
                                    │
                                    ▼
                 ┌──────────────────────────────────────┐
                 │            RunOrchestrator            │
                 │ Configuration / Locks / Lifecycle     │
                 └───────────────┬──────────────────────┘
                                 │
          ┌──────────────────────┼──────────────────────────┐
          ▼                      ▼                          ▼
   ConfigurationResolver   LabController          EnvironmentFingerprint
          │                      │                          │
          └──────────────────────┼──────────────────────────┘
                                 ▼
                        ┌──────────────────┐
                        │ LabHealthService │
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │ pytest/TestRegistry │
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │    RunContext    │
                        └────────┬─────────┘
                                 ▼
           ┌─────────────────────┼──────────────────────┐
           ▼                     ▼                      ▼
   CommandRunner         DeviceAdapter          FirmwareAdapter
           │                     │                      │
           └─────────────────────┼──────────────────────┘
                                 ▼
          ┌────────────────────────────────────────────────┐
          │ Evidence / Protocol / Telemetry / Metrics     │
          └───────────────────────┬────────────────────────┘
                                  ▼
          ┌────────────────────────────────────────────────┐
          │ Regression Intelligence / Baselines / Gate    │
          └───────────────────────┬────────────────────────┘
                                  ▼
          ┌────────────────────────────────────────────────┐
          │ SQLite / SQLAlchemy / PostgreSQL-compatible   │
          │ Artifact Registry / Durable Offline Outbox    │
          └────────────────────────────────────────────────┘
```

The future Cloud control plane remains a separate layer above the certified Runner. It must not bypass the Runner's local authority over labs, devices, raw evidence, and execution.

---

# FINAL IMPLEMENTATION ORDER

The only permitted development order is:

```
20
Foundation / Security / Contract Freeze
        ↓
21
Orchestration / Configuration / Lab Control / Locking
        ↓
22
Evidence / Protocol / Telemetry / Performance
        ↓
23
Firmware / Failure Semantics / Diagnostics
        ↓
24
API / Frontend / Persistence
        ↓
25
Baseline / Regression / Release Intelligence / Offline Runner
        ↓
26
Failure Injection / Integration / Security Hardening
        ↓
27
Final End-to-End Certification / Documentation Freeze
        ↓
28
Single Final Commit on main
```

No Cloud/SaaS implementation is permitted before Iteration 27 certification.

No iteration is complete merely because code exists. Completion requires implementation, tests, failure-path verification, documentation synchronization, and the applicable real-lab gate.
