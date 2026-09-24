# NetRegress — Execution, Device Adapter and Firmware Adapter Design

## 1. Purpose

This document defines how a Run reaches real equipment without putting device-specific logic into tests or the future Cloud.

## 2. Execution chain

~~~text
CLI / API request
    ↓
RunService
    ↓
Run Orchestrator
    ↓
RunContext
    ↓
pytest session
    ↓
TestRegistry
    ↓
test implementation
    ↓
CommandRunner / DeviceAdapter / CaptureService / TrafficService
    ↓
real lab or fake adapter
    ↓
metrics + artifacts + events
~~~

## 3. Canonical pytest role

Pytest remains the canonical test execution engine.

Existing node IDs stay stable.

The Run system wraps pytest rather than replacing it.

## 4. RunContext contract

Every test should eventually receive:

- run ID;
- attempt ID;
- device identity;
- lab identity;
- resolved configuration;
- command runner;
- artifact service;
- logger;
- metric/sample collector;
- timing context.

Tests should not construct their own SSH pools, DB connections or artifact paths.

## 5. TestRegistry contract

TestRegistry exposes semantic metadata:

- test ID;
- version;
- title/description;
- categories;
- protocol;
- severity;
- criticality;
- prerequisites;
- device capabilities;
- destructive flag;
- sample policy;
- thresholds;
- required evidence;
- estimated duration;
- reproduction information.

## 6. Test selection

Selection flow:

~~~text
Validation Profile
        ↓
Project policy
        ↓
Device capabilities
        ↓
Prerequisites
        ↓
Executable test set
~~~

Unsupported tests are excluded with a recorded reason rather than failing due to impossible hardware assumptions.

## 7. DeviceAdapter

DeviceAdapter is the boundary between validation logic and target-specific implementation.

Operations:

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

Implementations may be:

- VirtualLinuxDeviceAdapter;
- OpenWrtDeviceAdapter;
- future vendor-specific adapters.

Tests depend on behavior contracts, not vendor names.

## 8. Device capabilities

Capabilities should be machine-readable.

Examples:

~~~text
supports_wpa2
supports_wpa3
supports_2ghz
supports_5ghz
supports_6ghz
supports_reboot
supports_firmware_flash
supports_rollback
supports_rssi
supports_packet_capture
supports_ssh
supports_tftp
~~~

Capability data controls test applicability and firmware compatibility.

## 9. FirmwareAdapter

Firmware operations:

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

Firmware flashing is deliberately separate from validation tests.

## 10. Firmware image validation

Before flashing:

1. identify device;
2. read firmware metadata;
3. verify checksum;
4. verify signature where available;
5. validate compatibility;
6. obtain explicit authorization.

## 11. Flash lifecycle

~~~text
FIRMWARE_SELECTED
    ↓
VALIDATED
    ↓
UPLOADED
    ↓
PREPARED
    ↓
FLASHING
    ↓
REBOOTING
    ↓
READY
    ↓
VERSION_VERIFIED
~~~

Failure at any stage produces a typed FirmwareError and audit evidence.

## 12. Rollback

Rollback is a first-class operation.

Rollback is never automatic.

Rollback capability is declared by the DeviceAdapter.

## 13. Fake adapters

fw_simulator becomes the reference fake adapter.

It must support deterministic scenarios:

- nominal device;
- DNS regression;
- DHCP regression;
- SSID regression;
- latency regression;
- flash success/failure;
- reboot failure;
- incompatible image.

The fake adapter is used for unit/integration testing of orchestration logic without requiring the physical lab.

## 14. CommandRunner integration

DeviceAdapter translates generic operations into commands and passes execution through CommandRunner.

Tests never construct shell strings for vendor-specific operations.

## 15. CommandResult

Structured result fields:

- command ID;
- target host/device;
- command category;
- safe display command;
- exit code;
- stdout;
- stderr;
- duration;
- timeout state;
- privilege state;
- idempotency;
- redaction state.

## 16. CommandRunner implementations

The current implementation provides three transports:

- `NetmikoRunner` wraps the established `ConnectionPool` so existing SSH retry/connection behavior remains compatible.
- `ParamikoExecRunner` provides structured non-interactive SSH execution with exit-status capture and timeout metadata.
- `LocalRunner` uses argv execution by default; shell parsing is opt-in through `execute_shell()`.

All transports return `CommandResult`. The result includes command ID, target, category, safe display command, stdout/stderr, exit code when the transport exposes one, duration, connection/execution/idle timeout metadata, timeout state, idempotency, privilege context, redaction state and transport errors.

Command execution itself adds no automatic retry policy. Existing Netmiko connection establishment retries remain in `ConnectionPool`; mutating operations remain non-retryable by caller policy.

The dedicated raw Paramiko foreground channel used for AP `br0` DHCP tcpdump is intentionally not replaced by `ParamikoExecRunner`, because that capture requires long-lived channel control and a specific stop/download lifecycle.

## 17. Retry semantics

Connection establishment may retry.

Idempotent reads may retry.

Mutating operations are not blindly retried.

Firmware flash must never be automatically retried after uncertain state.

## 18. Device locking

Exclusive operations require DEVICE_EXCLUSIVE ownership.

Examples:

- firmware flash;
- reboot;
- configuration mutation;
- factory reset.

Compatible read-only/network operations may use NETWORK_CONCURRENT when safe.

## 19. Capture integration

CaptureService is available through RunContext.

Tests request evidence by intent, for example:

~~~text
capture DHCP transaction on selected interface
~~~

Transport selection is handled by the capture layer.

The current AP br0 Paramiko path remains a transport implementation rather than a test-specific architectural rule.

## 20. Traffic integration

TrafficService should eventually provide:

- ping;
- TCP throughput;
- UDP throughput;
- DNS;
- jitter;
- packet loss;
- directional traffic.

Results are normalized into Metric/Sample objects.

## 21. Fault injection

FaultService uses CommandRunner and explicit fault definitions.

Each fault declares:

- target device;
- interface/service;
- apply command/action;
- verification;
- restore action;
- destructive level;
- cleanup requirement.

Fault lifecycle:

~~~text
prepare
→ inject
→ verify fault
→ execute test
→ restore
→ verify recovery
~~~

## 22. Cleanup guarantee

Run Orchestrator owns the final cleanup boundary.

try/finally behavior must ensure restoration of:

- link state;
- tc state;
- DHCP/DNS rules;
- captures;
- locks;
- temporary files;
- device sessions.

## 23. Physical versus virtual adapters

Both virtual and physical adapters use the same service contracts.

Every telemetry point identifies its environment class.

Virtual hwsim does not satisfy physical RF-certification claims.

## 24. Future vendor adapter pattern

Vendor adapter should contain:

- authentication;
- device discovery;
- command mapping;
- firmware mapping;
- capability mapping;
- telemetry mapping;
- reboot/rollback semantics.

The validation test itself should remain unchanged.

## 25. Acceptance tests for adapters

Every adapter requires:

1. capability tests;
2. health tests;
3. version tests;
4. command safety tests;
5. firmware compatibility tests;
6. flash success path;
7. flash failure path;
8. rollback path where supported;
9. timeout/disconnect behavior;
10. artifact/evidence verification.

## 26. Design invariant

Tests state what must be validated.

Adapters decide how a particular device performs the operation.

CommandRunner decides how a command is safely executed.

Run Orchestrator decides what the observed result means for the Run.
