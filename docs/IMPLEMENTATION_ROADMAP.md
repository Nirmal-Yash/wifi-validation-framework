# NetRegress Implementation Roadmap

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

Next:
- Iteration 6 — Historical database migration and legacy Run attribution.


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

Next:
- Iteration 7 — Test Registry + RunContext semantic execution metadata.


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

Next:
- Iteration 9 — Execution security and command authorization/redaction hardening.


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

Next:
- Iteration 10 — LabHealthService and typed infrastructure health evidence.


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

Next:
- Iteration 11 — Statistical measurement policies and aggregate evaluation.


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

Next:
- Iteration 12 — Functional WiFi expansion and negative/recovery cases.


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

Next:
- Iteration 13 — Protocol-aware evidence and transaction correlation.

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

Next:
- Iteration 15 — Regression Intelligence 2.0.


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

Next:
- Iteration 16 — Dashboard/API regression and telemetry contracts.


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

Next:
- Iteration 17 — Device/Firmware Adapter production seam.


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

Next:
- Iteration 18 — Internal CI release gate.