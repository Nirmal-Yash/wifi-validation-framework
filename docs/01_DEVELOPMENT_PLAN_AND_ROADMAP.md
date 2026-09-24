# NetRegress — Development Plan & Roadmap

> Canonical document for development order, implementation phases, historical implementation detail, current iterations, roadmap status, and completion gates.
>
> This document aggregates the previously separate development-plan and roadmap documents without deleting their technical detail. The current authoritative sequence is presented first; the historical phase detail and explicit roadmap checklist are preserved afterward.

Companion canonical documents:
- docs/01_DEVELOPMENT_PLAN_AND_ROADMAP.md
- docs/02_SYSTEM_ARCHITECTURE_DATA_API.md
- docs/03_TRACEABILITY_AND_SYSTEM_READINESS.md
- docs/04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md
- docs/05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md

## 1. Authority and development rules

- The development plan controls implementation order.
- The roadmap controls iteration/status visibility.
- The architecture, data/API, business, testing, and execution documents remain authoritative for their respective technical contracts.
- Existing executable code remains the current behavioral source until the relevant phase explicitly migrates that behavior.
- Protected behavioral baseline: 436026eba597b2c6ae2e291a9cd8054b70ebbf7c.
- Canonical real-lab invocation: pytest tests/ -v --firmware-version=v1.0.
- Real-lab evidence is never substituted by simulated or source-only evidence.

## 2. Current authoritative development plan

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
docs/03_TRACEABILITY_AND_SYSTEM_READINESS.md
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

- `05_ARCHITECTURE_DECISIONS_AND_05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md`
- `01_DEVELOPMENT_PLAN_AND_ROADMAP.md`
- `01_DEVELOPMENT_PLAN_AND_ROADMAP.md`
- `05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md`
- `02_SYSTEM_ARCHITECTURE_DATA_API.md`
- `EXECUTION_AND_ADAPTERS.md`
- `SECURITY_AND_SAAS.md`
- `04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md`
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

- `03_TRACEABILITY_AND_SYSTEM_READINESS.md` is accurate;
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

The production local dashboard is implemented under `frontend/` using React + Vite. The React UI is the canonical modern presentation layer over `/api/v1`. The Jinja dashboard remains as a compatibility presentation layer pending browser/runtime parity validation and retirement.

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

- `03_TRACEABILITY_AND_SYSTEM_READINESS.md`;
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
Package the completed implementation as one clean release state on main.

## 28.1 Freeze
- stop feature development;
- stop refactoring;
- do not introduce unrelated cleanup;
- do not alter protected behavior unless required by release-readiness evidence.

## 28.2 Final verification contract
The release tooling covers Python compilation, security/readiness auditing, certification-matrix generation, optional core release-policy tests, working-tree/tracked-artifact auditing, manifest generation and release invariants. Protected real-lab execution remains an execution-class gate.

## 28.3 Single commit
The complete release wave uses exactly one final commit on main with:

~~~text
feat(runner): complete production-grade validation platform
~~~

# ITERATION 29 — REPRODUCIBLE OPERATIONAL READINESS

## Objective
Make release consumption deterministic and diagnosable without a Cloud dependency or a parallel production execution path.

## Implementation
- ReleaseManifestService records branch, commit, tree, cleanliness, tracked-file inventory and SHA-256 hashes.
- RunnerDoctor checks interpreter/tool/path/authentication/database readiness.
- Release and doctor CLIs expose deterministic operational checks.
- SQLite integrity is inspected when a database exists.
- Generated manifests remain in ignored runtime output.

# ITERATION 30 — FINAL GOVERNANCE AND ARCHITECTURE FREEZE

## Objective
Freeze the standalone Runner as the coherent release unit and reconcile the operational contracts around it.

## Implementation
- Runner authority remains local for labs, devices, raw evidence and execution.
- Cloud/SaaS remains above the certified Runner and is not part of this release.
- Fake/simulated adapters remain verification seams only.
- REAL_LAB certification remains an explicit evidence class.
- API, security, release-gate, baseline, waiver and artifact invariants are frozen.
- Documentation is synchronized to the final architecture.
- No unrelated post-freeze feature is permitted.

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

~~~text
20 → 21 → 22 → 23 → 24 → 25 → 26 → 27 → 28 → 29 → 30 → ONE FINAL COMMIT ON main
~~~

No Cloud/SaaS implementation is introduced in this release wave.

## Final implementation status — Iterations 20–30
Iterations 20–27 are source-complete from the preceding consolidated passes. Iterations 28–30 are the final release wave: release integration, reproducible operational readiness and governance/architecture freeze. The final Git state is consolidated into one commit on main.


## Current-State Amendment — 2026-09-24

The post-release implementation audit traced completion gates into source and closed the identified defects in DHCP T1/T2 evidence, firmware-operation locking, firmware API validation metadata, scoped release waivers, operational mutation idempotency, readiness depth, frontend CSRF integration and OpenAPI synchronization. The subsequent React/Vite completion slice brought the documented frontend surface to source-complete status and added a CI frontend build/test gate.

The following remain deliberately execution-bound or deferred:
- first-class multi-project domain ownership in the future Cloud/SaaS control plane;
- complete live wiring of EAPOL, Beacon/RSN and DNS analyzers into protected validation tests;
- protected REAL_LAB and production-like runtime certification.

Therefore, “source implemented” and “runtime certified” remain separate completion states. No source manifest, fake adapter, simulated integration or unit fixture can satisfy the protected REAL_LAB gate.

## 3. Historical implementation phases and preserved design detail

The original detailed implementation plan is retained here as the historical implementation specification for Phases 0–11 and Iterations 15–19. Its exact technical details, compatibility constraints, acceptance criteria, and implementation ordering are preserved below.

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


## 19A. Iteration 16 implementation

Phase 8 is implemented as an additive, read-only API/UI layer over the Run/Attempt/TestResult/Artifact repositories.

Canonical versioned endpoints now cover:
- Runs and Run detail;
- Test results and test detail;
- metrics and historical samples;
- explicit Run-to-Run regression comparison;
- Run telemetry and inferred environment class;
- Run/lab health evidence;
- artifact metadata and constrained download;
- active baseline metadata.

Jinja pages consume these same contracts. Legacy /api routes and the existing firmware pass-rate/chart/export views remain compatibility views.

Artifact JSON is never trusted solely because its database record exists: the registered path must remain under the results root and its SHA-256 must still match before interpretation.


## 20A. Iteration 17 implementation

Iteration 17 makes Phase 9 executable through typed adapters rather than documentation-only interfaces.

Implemented:
- DeviceAdapter with profile-driven SSH execution.
- VirtualLinuxDeviceAdapter for the current GNS3/Linux device class.
- OpenWrtDeviceAdapter with OpenWrt-specific version and sysupgrade defaults.
- machine-readable capability declarations controlling firmware applicability.
- FirmwareImage SHA-256 validation and optional detached-signature verification.
- SFTP upload and remote SHA-256 verification.
- explicit authorization for upload, prepare, flash, reboot and rollback.
- staged FirmwareOperationService lifecycle with Run audit events.
- explicit rollback only; no automatic retry or rollback after uncertain state.
- deterministic fake Device/Firmware adapters for hardware-free lifecycle testing.

Real firmware mutation is not invoked by the current WiFi pytest suite.

## 21A. Iteration 18 implementation

The internal release gate is now a fail-closed policy boundary. Core CI performs source parsing and hardware-free release-policy contract tests. A separate dispatchable self-hosted job runs the protected GNS3/mac80211_hwsim suite using the existing provisioning script and canonical pytest command. Persisted Run/regression evaluation is available through scripts/ci_release_gate.py.

## 22A. Iteration 19 implementation

Iteration 19 implements the Runner-side offline synchronization seam as a durable SQLite outbox. A terminal Run is snapshotted locally into a deterministic envelope containing Run, Attempt, TestResult, metric/sample, artifact metadata and lifecycle facts. Artifact binaries remain local; the envelope carries immutable integrity metadata only.

Synchronization is outbound-only and transport-agnostic. `HttpSyncTransport` is a minimal HTTPS implementation for the future Cloud contract. Queue delivery is idempotent, lease-based and retryable. Cloud unavailability never changes an already persisted Run outcome.

## 4. Explicit roadmap and status checklist

The roadmap is preserved below as the implementation-status checklist so development order and completion status remain in one place.

## Iteration 1 — Typed Domain Model ✅
- [x] Typed domain entities and invariants.
- [x] Domain tests.

## Iteration 2 — Repository + SQLite Persistence ✅
- [x] Repository interfaces and normalized SQLite persistence.
- [x] Legacy SQLite preservation.

## Iteration 3 — Run/Attempt Lifecycle + Pytest Integration ✅
- [x] ULID/display IDs, lifecycle transitions/events, Run + Attempt creation.
- [x] Existing CLI/node IDs and legacy result writes preserved.

## Iteration 4 — Metrics + Raw Samples ✅
- [x] Multi-sample MetricCollector with warmup/retry/status/metadata/timestamp support.
- [x] Backward-compatible metric_logger.log(value, unit).
- [x] Run-scoped TestResult persistence with Metric/Sample children.
- [x] Legacy single-metric persistence retained.
- [x] Unit/service verification added.

Verification:
- [ ] Python syntax compilation: not executable from this environment.
- [ ] MetricCollector multi-sample verification: not executable from this environment.
- [ ] Run-scoped sample persistence verification: not executable from this environment.
- [ ] Full real-lab 11/11 gate: unavailable in this environment.

## Iteration 5 — ArtifactService + Evidence Registry ✅
- [x] Artifact metadata: display name, creation time, sensitivity class, retention fields.
- [x] Migration-safe SQLite schema for new artifact metadata.
- [x] ArtifactService verifies file existence, expected size and SHA-256 before registration.
- [x] ARTIFACT_CREATED lifecycle events persisted.
- [x] Existing real DHCP PCAP producer registers the verified PCAP as Run-scoped evidence.
- [x] Artifact integrity verification and legacy-schema migration tests added.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Full real-lab 11/11 gate: required because the DHCP evidence path changed; unavailable in this environment.



## Iteration 6 — Historical Database Migration + Legacy Run Attribution ✅
- [x] Deterministic legacy-to-Run/Attempt/TestResult attribution.
- [x] Explicit \`LEGACY_IMPORTED\` provenance on migrated Run/TestResult/Artifact/Baseline records.
- [x] Raw legacy metrics preserved where units are available.
- [x] Existing PCAP paths registered only when the file actually exists; unavailable paths produce explicit lifecycle evidence.
- [x] Legacy baseline-table naming collision isolated from normalized \`run_baselines\`.
- [x] Migration ledger makes repeated execution idempotent.
- [x] Legacy source tables remain intact.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Full real-lab 11/11 gate: required; result persistence/schema changes require the gate and it is unavailable here.



## Iteration 7 — Test Registry + RunContext ✅
- [x] Stable semantic IDs mapped 1:1 to existing pytest node IDs.
- [x] Full test-definition metadata and deterministic internal fallback definitions.
- [x] RunContext introduced with Run/Attempt, lab/device, resolved config, TestRegistry and ArtifactService.
- [x] Semantic test metadata integrated into Run-scoped TestResult persistence.
- [x] Existing pytest CLI and node IDs preserved.
- [x] Unit tests added for registry and context behavior.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Full real-lab 11/11 gate: required; unavailable in this environment.

## Iteration 8 — CommandRunner Extraction + Structured Command Results ✅
- [x] Typed CommandRunner protocol and immutable CommandResult contract.
- [x] NetmikoRunner wraps the existing ConnectionPool without altering protected connection behavior.
- [x] ParamikoExecRunner added for structured non-interactive SSH execution.
- [x] LocalRunner added with shell execution available only through explicit execute_shell().
- [x] Command timeout, idempotency, privilege and redaction metadata captured for each result.
- [x] Common command-secret redaction for display/logging implemented.
- [x] RunContext now carries a typed CommandRunner instance.
- [x] Existing raw Paramiko DHCP tcpdump lifecycle remains untouched.
- [x] Unit tests added for redaction, structured Netmiko results, local execution and RunContext integration.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Full real-lab 11/11 gate: required because execution plumbing changed; unavailable in this environment.



## Iteration 9 — Execution Security + Command Authorization/Redaction ✅
- [x] Central CommandSecurityPolicy with per-target executable and destructive-operation allow lists.
- [x] Strict structured execution rejects shell operators and command substitution by default.
- [x] Explicit compatibility shell execution supports only the existing limited validation grammar (semicolon, double-pipe, /dev/null redirection).
- [x] Destructive lab operations require explicit policy authorization and remain limited to documented prefixes: dhclient, ip link set, iptables, pkill, systemctl start/stop and tc qdisc.
- [x] Privilege normalization centralizes sudo handling and uses non-interactive sudo -n.
- [x] Command and output redaction covers passwords, PSKs, tokens, authorization headers and sensitive query values.
- [x] SecureCommandRunner wraps all standard pytest remote-command compatibility calls without changing existing test node IDs or CLI behavior.
- [x] COMMAND_EXECUTED lifecycle audit events include command IDs, safe commands, transport, privilege and outcome metadata without raw secrets.
- [x] Run-scoped COMMAND_OUTPUT evidence is registered through ArtifactService at session close.
- [x] Local command compatibility and protected DHCP raw Paramiko capture boundaries remain explicit.
- [x] Security-focused unit tests added for injection resistance, destructive allow-list enforcement, privilege normalization, redaction and audit evidence.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Full real-lab 11/11 gate: required because execution security and pytest command routing changed; unavailable in this environment.



## Iteration 10 — LabHealthService + Typed Infrastructure Health Evidence ✅
- [x] Added typed EnvironmentHealthStatus, HealthObservation and LabHealthSnapshot domain models.
- [x] Added Run.environment_health with SQLite persistence and additive schema migration.
- [x] Added LabHealthService with read-only checks for GNS3, Docker, libvirt, hwsim PHY placement, management SSH, AP/client/router/monitor, DHCP, DNS, iperf3, disk and clock/NTP.
- [x] GNS3 health validates API reachability, configured project discovery and required node availability/state.
- [x] hwsim health validates PHY visibility inside the AP/client namespaces, matching the protected topology rather than relying on host-only PHY visibility.
- [x] FAILED required health blocks validation before tests execute and marks the Run LAB_FAILED.
- [x] DEGRADED/UNKNOWN health is retained as Run context without silently repairing the lab.
- [x] BEFORE and AFTER health snapshots are executed around the pytest Run.
- [x] Every health snapshot is registered as LAB_HEALTH_SNAPSHOT evidence; unhealthy snapshots also register DIAGNOSTIC_BUNDLE evidence.
- [x] LAB_HEALTH_STARTED and LAB_HEALTH_COMPLETED lifecycle events are emitted.
- [x] Component/unit tests cover healthy, failed and degraded health paths plus Run persistence.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Full real-lab 11/11 gate: required because orchestration, SSH health checks and pytest gating changed; unavailable in this environment.



## Iteration 11 — Statistical Measurement Policies + Aggregate Evaluation ✅
- [x] Added typed `StatisticKind`, `MeasurementPolicy`, `MetricDefinition` and `StatisticSummary` contracts.
- [x] Added deterministic evaluator for count, minimum, maximum, mean, median, p90, p95 and population standard deviation.
- [x] Warm-up samples and disallowed sample statuses are excluded from aggregates.
- [x] Retried measurements retain explicit retry metadata without multiplying statistical observations.
- [x] Added minimum-sample enforcement and metric name/unit validation.
- [x] Extended TestRegistry so performance tests declare a semantic `decision_metric` and aggregate policy.
- [x] Added semantic metric naming in the pytest collector when a test has one policy-driven metric, without changing existing test node IDs or CLI behavior.
- [x] Added unit coverage for statistics, policy enforcement and registry metadata.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Full real-lab 11/11 gate: required because pytest metric collection and result semantics changed; unavailable in this environment.



## Iteration 12 — Functional WiFi Negative + Recovery Validation ✅
- [x] Added typed `FaultDefinition`/`FaultService` over the secured `CommandRunner`.
- [x] Fault contexts restore unconditionally, including when fault application or validation raises.
- [x] Added real wrong-PSK rejection and recovery validation.
- [x] Added explicit WiFi disconnect/reconnect recovery validation.
- [x] Added DHCP lease renewal validation.
- [x] Added DHCP service-loss and lease recovery validation using the real FRR/dnsmasq service.
- [x] Added DNS failure/recovery validation using a real client firewall fault.
- [x] Added AP hostapd restart recovery validation.
- [x] Added client wpa_supplicant restart recovery validation while management remains on eth1.
- [x] Registered all new recovery cases with semantic TestRegistry metadata and destructive classification.
- [x] Added recovery marker and FaultService unit coverage.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Protected original 11-test real-lab subset: unavailable in this environment.
- [ ] Full expanded recovery suite real-lab execution: unavailable in this environment.
- [ ] Protocol-accurate DHCP T2 rebind evidence: deferred to the transaction-aware protocol-evidence phase.


## Iteration 13 — Protocol-Aware Evidence + Transaction Correlation ✅
- [x] Added typed DHCP, EAPOL, beacon and DNS evidence models.
- [x] Added `ProtocolEvidenceService` with transaction-aware DHCP DORA correlation.
- [x] DHCP correlation uses transaction ID and client identity instead of independent packet counts.
- [x] Added ordered WPA2/EAPOL four-way handshake detection.
- [x] Added beacon SSID/BSSID/channel/RSN/cipher/AKM/beacon-interval/capability extraction.
- [x] Added DNS query/response correlation by transaction ID and question.
- [x] Preserved `lib.wifi_analyzer` compatibility entry points as wrappers over the new service.
- [x] Upgraded real DHCP PCAP validation to require correlated DORA evidence.
- [x] Registered derived DHCP protocol JSON as Run-scoped `PROTOCOL_EVIDENCE` while preserving the verified raw PCAP.
- [x] Added parser/component tests covering correlation failures that packet counts alone would incorrectly accept.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Protected original 11-test real-lab gate: unavailable in this environment.
- [ ] Real DHCP capture + protocol-evidence gate: unavailable in this environment.

## Iteration 14 — WiFi Telemetry + Environment-Class-Aware Measurements ✅
- [x] Added typed `TelemetryEnvironmentClass`, `TelemetryMetric`, `TelemetryPoint` and `WifiTelemetrySnapshot` contracts.
- [x] Added `WifiTelemetryService` using only secured read-only `wpa_cli`/`iw` observations.
- [x] Added RSSI, SNR, frequency, derived channel, bitrate, PHY-mode and available retry/failure telemetry parsing.
- [x] Every telemetry point carries explicit `VIRTUAL_WIFI` or `PHYSICAL_WIFI` environment class.
- [x] Missing measurements remain unavailable; no synthetic or inferred RF values are emitted.
- [x] Added Run-scoped `TELEMETRY` artifact support and JSON serialization.
- [x] Wired telemetry service into `RunContext` and the pytest session fixture without changing protected test node IDs, topology or traffic/capture paths.
- [x] Added parser/service tests for environment labeling, missing-source behavior, interface validation and JSON provenance.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Real-lab telemetry capture: unavailable in this environment.
- [ ] Protected original 11-test real-lab gate: unavailable in this environment.



## Iteration 15 — Regression Intelligence 2.0 ✅
- [x] Added typed comparability, regression-dimension, metric-comparison, assessment and Run-report contracts.
- [x] Added explicit Run-to-Run comparison keyed by baseline Run ID.
- [x] Added fail-closed profile/lab/test-definition/environment comparability checks.
- [x] Added multi-metric PASS→PASS evaluation through the declared MeasurementPolicy.
- [x] Added per-test/per-metric threshold overrides with the existing 20% compatibility default.
- [x] Added `NO_BASELINE` and `UNVALIDATED` handling.
- [x] Added composable regression dimensions and flaky-history diagnostics.
- [x] Preserved the legacy firmware-string regression path as compatibility code.
- [x] Added focused regression-intelligence tests.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Protected real-lab gate: unavailable in this environment.



## Iteration 16 — Dashboard/API 2.0 + Regression/Telemetry Integration ✅
- [x] Added read-only repository collection methods for Runs, TestResults and Artifacts.
- [x] Added DashboardQueryService as the presentation/query boundary.
- [x] Added versioned /api/v1 success/error envelopes.
- [x] Implemented Run/Test/Metrics/Regression/Telemetry/Lab Health/Artifact/Baseline endpoints.
- [x] Integrated Iteration 15 regression intelligence into the canonical dashboard.
- [x] Integrated persisted Iteration 14 telemetry and environment-class evidence.
- [x] Added integrity-checked JSON artifact interpretation.
- [x] Added constrained artifact downloads.
- [x] Added Jinja pages for Runs, Run Detail, Test Detail, Regression, Performance, Telemetry, Lab Health and Artifacts.
- [x] Preserved legacy /api/* compatibility endpoints.
- [ ] Local/unit execution: unavailable in this environment.
- [ ] Browser/API runtime verification: unavailable in this environment.
- [ ] Protected real-lab gate: unavailable in this environment.



## Iteration 17 — Device/Firmware Adapter Production Seam ✅
- [x] Added typed DeviceAdapter/FirmwareAdapter contracts.
- [x] Added VirtualLinux and OpenWrt SSH adapter implementations.
- [x] Added machine-readable device capabilities.
- [x] Added FirmwareImage SHA-256 and optional detached-signature validation.
- [x] Added SFTP upload plus remote integrity verification.
- [x] Added explicit authorization for firmware mutation stages.
- [x] Added staged firmware lifecycle orchestration and Run audit events.
- [x] Added explicit rollback as a separate operation; no automatic retry/rollback.
- [x] Added deterministic fake adapters and failure-path tests.
- [x] Wired adapters into RunContext without changing protected validation traffic.
- [x] Migrated `regression/fw_simulator.py` to the fake adapter boundary.
- [ ] Real hardware flash/reboot/rollback execution: unavailable in this environment.
- [ ] Protected 11-test real-lab gate: unavailable in this environment.


## Iteration 18 — Internal CI Release Gate ✅
- [x] Added fail-closed ReleaseGateEvaluator.
- [x] Rejects NO_BASELINE, UNVALIDATED, REGRESSION, SOFT_REGRESSION, NEW_FAILURE, missing required tests and invalid required evidence.
- [x] Requires completed Run and healthy lab by default.
- [x] Added persisted Run/regression evaluation CLI.
- [x] Added GitHub Actions core gate on main/PR.
- [x] Added dispatch-only protected real-lab gate for self-hosted netregress-lab runners.
- [x] Fixed pytest-node-ID versus semantic-test-ID normalization in RegressionIntelligenceService.
- [ ] GitHub Actions execution: unavailable in this environment.
- [ ] Protected real-lab execution: unavailable in this environment.


## Iteration 19 — Runner Offline Execution + Synchronization ✅
- [x] Added typed sync envelope and durable SQLite queue.
- [x] Added deterministic Run snapshot and idempotency key.
- [x] Added lease-based in-flight recovery.
- [x] Added bounded retry and BLOCKED state after repeated failures.
- [x] Added outbound HTTPS transport seam with optional bearer token.
- [x] Added explicit sync CLI.
- [x] Queued terminal Runs from pytest without changing Run outcomes on queue failure.
- [x] Added queue/service contract tests.
- [ ] External Cloud synchronization: unavailable/not configured in this environment.
- [ ] Protected 11-test real-lab gate: unavailable in this environment.


## Iterations 20–22 — Consolidated implementation pass
- [x] Iteration 20: secret externalization, local authentication/RBAC, API/dashboard protection, state reconciliation.
- [x] Iteration 21: deterministic configuration, environment fingerprinting, LabController boundary, exclusive resource locking, RunOrchestrator and pytest integration.
- [x] Iteration 22: evidence/protocol/telemetry/statistical contracts retained as mandatory Runner lifecycle boundaries; required evidence remains fail-closed.
- [ ] Runtime/unit execution in the available environment.
- [ ] Protected 11-test GNS3/mac80211_hwsim verification.

Next: Iteration 23 — Device/Firmware operations, failure semantics, cancellation and diagnostics.


## Iterations 23–25 — Consolidated implementation pass

### Iteration 23 — Device/Firmware Operations + Failure Semantics ✅
- [x] Explicit firmware lifecycle state transitions and audit events.
- [x] Image SHA-256/signature/model validation remains mandatory before mutation.
- [x] SSH/SFTP and TFTP transport seams.
- [x] Explicit cancellation, process-group termination and Run execution PID persistence.
- [x] PRODUCT_FAILED/LAB_FAILED/RUNNER_DISCONNECTED/WORKER_CRASHED/TIMED_OUT/CANCELLED/ABORTED classification.
- [x] Diagnostic ZIP/manifest generation.
- [x] ReproductionManifest generation and CLI.

### Iteration 24 — API/OpenAPI + Operational Frontend + Persistence Boundary ✅
- [x] Authorized POST Run/cancel/retry/baseline/firmware operations.
- [x] Scoped waiver creation boundary.
- [x] Canonical OpenAPI 3 contract.
- [x] React + Vite operational UI shell.
- [x] Alembic/SQLAlchemy migration boundary added while retaining SQLite compatibility.

### Iteration 25 — Baseline/Regression/Release + Offline Runner ✅
- [x] Explicit baseline promotion with blocking-test/evidence/health requirements.
- [x] Active-baseline supersession semantics.
- [x] Scoped, expiring, audited waiver model.
- [x] Release-gate waiver filtering remains fail-closed.
- [x] Durable outbound sync/idempotency/lease retry path remains the Runner synchronization authority.
- [x] Diagnostic/reproduction evidence remains locally authoritative.



## Iteration 26 — Full Failure Injection, Multi-Layer Integration, Security Hardening & Release Readiness ✅
- [x] Added a 27-case typed failure-injection matrix covering device, lab, network, runner, persistence, evidence, firmware, concurrency, API and synchronization failure classes.
- [x] Added a failure-injection harness with unconditional cleanup semantics and explicit product-statistics isolation expectations.
- [x] Added restart/orphan Run recovery, stale-lock inspection/recovery, SQLite backup/restore and retention controls.
- [x] Added durable API idempotency/replay protection with request-fingerprint binding.
- [x] Added CSRF enforcement for authenticated state-changing API calls, login rate limiting and secure response headers.
- [x] Added outbound HTTPS SSRF/IP-range validation and firmware-path confinement.
- [x] Added audit event chain integrity digesting into diagnostic evidence.
- [x] Added source security/readiness audit and CI integration.
- [x] Preserved the existing fake-adapter boundary for hardware-free integration; no synthetic path replaces real validation.

## Iteration 27 — Final Runner Certification & Documentation Freeze ✅
- [x] Added the canonical 11-scenario certification matrix.
- [x] Added evidence-completeness evaluation and certification report CLI.
- [x] Added certification contract tests covering healthy, failure, evidence, lab, Runner, concurrency, firmware, offline and recovery semantics.
- [x] Reconciled current-state, roadmap, security, testing, data/API, frontend, installation, traceability and README documentation.
- [x] Added final source/readiness CI checks without claiming real-lab execution from source-only gates.


 
## Iteration 28 — Final Single-Commit Release Integration ✅
- [x] Deterministic release manifest with commit/tree/file inventory and SHA-256 content addressing.
- [x] Final main-branch/source inventory audit.
- [x] Release CLI with verify/manifest/doctor modes.
- [x] Final CI release-readiness integration.
- [x] Generated runtime reports remain outside tracked source.

## Iteration 29 — Reproducible Operational Readiness ✅
- [x] RunnerDoctor for Python, toolchain, directory, authentication and SQLite readiness.
- [x] Database integrity inspection before operational consumption.
- [x] Reproducible release inventory and documentation hashes.
- [x] Controlled operational commands for verification and manifest generation.

## Iteration 30 — Final Governance + Architecture Freeze ✅
- [x] Standalone Runner authority boundary frozen.
- [x] API/security/certification invariants and execution-class distinctions frozen.
- [x] Final architecture, current-state, roadmap, security, testing, data/API and release documentation reconciled.

## Completeness Audit — 2026-09-24
The post-release source audit identified implementation gaps in DHCP T1/T2 transaction evidence, firmware operation locking, firmware API validation metadata, scoped release-waiver enforcement, mutation idempotency coverage, API readiness depth, frontend CSRF integration and API/OpenAPI synchronization. These are being closed in the current completeness wave.

Production readiness is intentionally split into source completeness and execution certification:
- source implementation readiness can be assessed from repository evidence;
- REAL_LAB certification still requires the protected GNS3/mac80211_hwsim execution class and is not inferred from simulation or source scans.

## 5. Canonical completion rule

1. Implementation and documentation agree.
2. Targeted tests pass.
3. Failure paths are verified.
4. Database migrations are verified where relevant.
5. APIs satisfy their contracts where relevant.
6. Affected artifacts are inspected.
7. Real 11-test validation remains green whenever execution/network behavior changed.
8. Source readiness is never misrepresented as protected REAL_LAB certification.
