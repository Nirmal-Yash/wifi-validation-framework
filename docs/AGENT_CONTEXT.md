# NetRegress — Agent Context and Engineering Guardrails

## 1. Purpose

This is the primary repository context for future engineers and coding agents.

Read order:

1. ARCHITECTURE_DECISIONS.md
2. IMPLEMENTATION_PLAN.md
3. BUSINESS_LOGIC.md
4. TECHNICAL_ARCHITECTURE.md
5. DATA_MODEL_AND_APIS.md
6. EXECUTION_AND_ADAPTERS.md
7. SECURITY_AND_SAAS.md
8. TESTING_AND_OPERATIONS.md
9. FRONTEND_DESIGN.md
10. source files directly related to the change

## 2. Protected baseline

Behavioral baseline: 436026eba597b2c6ae2e291a9cd8054b70ebbf7c

Observed state: 11/11 real-lab tests pass.

Do not alter the working GNS3/mac80211_hwsim contract while introducing the new architecture.

## 3. Current product role

Repository role: Runner/Core Validation Engine.

Future NetRegress Cloud is a separate control plane.

Current execution remains local and pytest-based.

## 4. Topology

FRR router: 192.168.122.10.

AP: 192.168.122.20, hostapd, br0, wlan0.

Client WiFi: 192.168.122.30 on wlan0.

Client management: 10.10.10.30 on eth1.

Monitor: 192.168.122.40.

Host/libvirt gateway: 192.168.122.1.

mac80211_hwsim: phy0 AP, phy1 client.

Management remains separate from WiFi test traffic.

## 5. Current behavioral special case

DHCP packet capture is performed on the AP bridge br0.

The capture test uses a raw Paramiko SSH exec channel because prompt-based Netmiko execution previously caused terminal-control prompt issues.

tcpdump remains alive in a dedicated foreground SSH channel until DHCP traffic completes.

Real PCAP is transferred over SFTP and verified with SHA-256.

Do not replace this with synthetic packets.

## 6. Architecture direction

Target execution:

CLI/API → RunService → Run Orchestrator → pytest → TestRegistry → Test → CommandRunner/Adapter → Lab/Device → Metrics/Evidence.

Lifecycle state and business outcome are separate.

Evidence completeness is part of PASS eligibility.

## 7. Non-negotiable rules

1. Never weaken an assertion to create PASS.
2. Never synthesize traffic for real validation.
3. Never convert infrastructure failure into product failure.
4. Never silently retry a failed test.
5. Never report PASS when required evidence failed.
6. Never silently repair and rerun the lab.
7. Never keep operational credentials in tracked configuration.
8. Never run two Runs against the same physical lab concurrently.
9. Never compare incompatible test definitions without explicit acknowledgement.
10. Keep existing pytest node IDs stable.

## 8. Source ownership

Config → configs/ and future resolved configuration service.

Reusable execution → lib/.

Tests → tests/.

Baseline/regression → regression/.

API/UI → dashboard/.

Lab lifecycle → extracted LabController plus compatibility shell.

Architecture/product policy → docs/.

## 9. Refactor compatibility rules

Existing public commands remain valid during migration.

Legacy database helpers temporarily delegate to new repositories/services.

Legacy /api routes remain as compatibility wrappers until the Jinja dashboard is retired.

The provisioning shell retains all current CLI flags throughout its migration.

## 10. Security guardrails

Secrets come from environment/secret storage.

Commands go through CommandRunner.

Artifacts are accessed through authenticated authorization-aware APIs once remote access exists.

Privileged operations create audit events.

## 11. Real-lab verification

Any change touching execution, networking, provisioning, capture, device adapters, orchestration or result persistence requires the real 11-test suite.

If the lab cannot be run, say so. Do not represent unit/integration verification as real-lab validation.

## 12. Development workflow

Direct commits to main.

No feature branches.

One architectural slice per commit.

Update documentation with behavior/contract changes.

Tag stable milestones.

Runtime DBs, reports, PCAPs and logs remain gitignored.

## 13. Current next step

Iterations 6 through 12 are implemented on main. Local/unit execution and the required real-lab gates remain pending where documented because this execution environment cannot run the repository or GNS3/mac80211_hwsim lab.

Iteration 13 implementation is present on main: typed protocol evidence, DHCP transaction correlation, EAPOL four-way sequence detection, beacon RSN/security extraction, DNS query/response correlation and Run-scoped protocol-evidence artifacts. Local/unit and real-lab verification remain pending because this execution environment cannot run the repository or GNS3/mac80211_hwsim lab.

Iteration 14 implementation is present on main: typed WiFi telemetry points/snapshots, secured read-only collection through wpa_cli/iw, environment-class labeling, retry/failure counters where available and RunContext integration. Local/unit and real-lab verification remain pending because this execution environment cannot run the repository or GNS3/mac80211_hwsim lab.

The next architectural slice is Iteration 15: Regression Intelligence 2.0.

Legacy test result storage remains as compatibility storage until the migration is explicitly retired.

## 14. Iteration 6 status

Historical SQLite migration is implemented with deterministic legacy provenance and an idempotent migration ledger. Legacy source tables remain unchanged.


## 15. Iteration 7 status

TestRegistry and RunContext are implemented. Existing validation node IDs remain unchanged; semantic metadata is now attached to persisted Run-scoped TestResults.

## 16. Iteration 8 status

CommandRunner extraction is implemented with typed `CommandResult`, Netmiko/Paramiko/local transports, explicit shell execution, command redaction metadata and timeout/idempotency context. RunContext now carries a typed NetmikoRunner backed by the existing ConnectionPool. The dedicated DHCP tcpdump Paramiko foreground channel remains unchanged.

Verification is intentionally still pending: no local Python/unit execution or real 11/11 lab run was possible in this environment.


## 17. Iteration 9 status

Command execution security is now centralized through SecureCommandRunner and CommandSecurityPolicy. Strict structured execution rejects shell syntax by default; the explicit compatibility shell boundary is allow-listed and destructive operations require a Run policy that authorizes the documented lab mutation prefixes. Privilege normalization forces non-interactive sudo, command/output secrets are redacted before evidence, and each Run records COMMAND_EXECUTED lifecycle events plus a COMMAND_OUTPUT artifact. The raw DHCP capture Paramiko path remains an explicit protected exception.
## 18. Iteration 10 status

LabHealthService is integrated into the Run lifecycle. Every Run performs a read-only BEFORE health gate and an AFTER health check. Health covers GNS3/project nodes, Docker, libvirt, mac80211_hwsim PHY placement, management SSH, AP/client/router/monitor interfaces, DHCP, DNS, iperf3, disk capacity and clock synchronization. Health snapshots are typed, persisted as LAB_HEALTH_SNAPSHOT evidence, and unhealthy snapshots additionally produce DIAGNOSTIC_BUNDLE evidence. FAILED required health blocks test execution and marks the Run LAB_FAILED; DEGRADED and UNKNOWN remain contextual health states. No automatic repair is triggered.


## 19. Iteration 11 status

Statistical measurement policy is now a typed contract. `MeasurementPolicy` selects the authoritative aggregate and minimum sample count; `MetricDefinition` binds a policy to a named metric and unit; `StatisticSummary` exposes count, minimum, maximum, mean, median, p90, p95 and population standard deviation. Warm-up samples and non-allowed sample statuses are excluded from aggregates, while retried samples remain one measurement when included. Performance TestRegistry definitions now declare their decision metric and aggregate policy, while pytest metric logging automatically uses that semantic metric name when a single policy-driven metric exists.

Raw samples remain the source of truth. Aggregate evaluation is deterministic and does not discard or rewrite raw measurements.


## 21. Iteration 13 status

Protocol evidence is now separated from raw packet collection. `ProtocolEvidenceService` preserves the protected DHCP capture path while validating correlated DHCP DORA transactions, and it provides typed analyzers for EAPOL four-way handshakes, 802.11 beacons/RSN parameters and DNS transaction correlation. DHCP protocol evidence is emitted as a Run-scoped JSON artifact beside the verified PCAP.

Legacy `lib.wifi_analyzer` entry points remain available as compatibility wrappers and now expose the richer correlated evidence fields.


## 22. Iteration 14 status

WiFi telemetry is now a typed Runner service rather than an unstructured dashboard concern. `WifiTelemetryService` collects observed RSSI, SNR, channel, frequency, bitrate, PHY mode and available retry/failure counters through the secured read-only CommandRunner boundary.

Every point is explicitly labeled `VIRTUAL_WIFI` or `PHYSICAL_WIFI`. Missing source values remain unavailable and are never synthesized. RunContext now exposes the service and the session fixture constructs it for the current virtual lab.

Verification remains pending in this environment: local/unit execution, a real telemetry capture against mac80211_hwsim, and the protected real-lab regression suite were not executed.


## 23. Iteration 15 status

Regression Intelligence 2.0 is now implemented as a typed Run-to-Run service. It requires an explicit baseline Run ID, validates comparison context, evaluates multiple metrics using frozen measurement policies, supports per-test/per-metric regression thresholds, exposes composable regression dimensions and retains flaky-history diagnostics.

The older firmware-string regression CLI remains compatibility code rather than the canonical comparison source.

Verification remains pending in this environment: local/unit execution and the protected real-lab regression gate were not executed.


## 24. Iteration 16 status

Dashboard/API 2.0 is implemented as a real read-only integration layer. Flask now exposes versioned API contracts for Runs, Tests, Metrics, Regression, Telemetry, Lab Health, Artifacts and Baselines. Jinja pages consume those contracts for Run history/detail, Test detail, Regression, Performance, Telemetry, Lab Health and Artifact browsing.

Derived telemetry and health JSON is interpreted only after path containment and SHA-256 verification. Artifact downloads are restricted to the registered results root; local downloads work without a token, while remote downloads require NETREGRESS_DASHBOARD_TOKEN.

Legacy /api/* endpoints remain compatibility wrappers. The new /api/v1 surface is the canonical dashboard contract.

Runtime verification remains pending in this environment; no pytest or real GNS3/mac80211_hwsim gate was executed.


## 25. Iteration 17 status

Device/Firmware adapters are implemented under `lib/adapters`. The current GNS3/Linux class uses a `VirtualLinuxDeviceAdapter`; OpenWrt has an explicit firmware-capable profile. Firmware images are validated, uploaded through SFTP, remotely hash-verified, flashed through a target-specific secured runner, rebooted explicitly, readiness-polled and version-verified. Rollback is a separate explicit operation.

RunContext now carries optional DeviceAdapter and FirmwareAdapter instances. The pytest session constructs these adapters without performing firmware mutation.

No real hardware firmware flash, reboot or rollback was executed in this environment.

## 26. Iteration 18 status

Internal CI/release gating is implemented. Core CI is hardware-free and cannot claim the 11/11 real-lab baseline. A separate dispatch-only self-hosted netregress-lab job runs the existing provisioning and pytest flow. Regression Intelligence now normalizes persisted pytest node IDs to semantic TestRegistry IDs.

## 27. Iteration 19 status

A durable Runner offline queue is implemented. Run snapshots are stored locally in SQLite and can be synchronized later through an outbound HTTPS transport. The local Runner remains authoritative for raw facts, and synchronization failures do not alter Run/TestResult outcomes. Pytest session completion queues the terminal Run best-effort.

No external Cloud endpoint is configured or contacted in this environment.