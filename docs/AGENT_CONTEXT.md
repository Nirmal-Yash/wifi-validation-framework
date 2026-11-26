# NetRegress — Agent Context and Engineering Guardrails

## 1. Purpose

Current operator upgrade and first-run instructions: `docs/UPGRADE_AND_FIRST_RUN_GUIDE.md`.

This is the primary repository context for future engineers and coding agents.

Read order:
1. 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md
2. 01_DEVELOPMENT_PLAN_AND_ROADMAP.md
3. 02_SYSTEM_ARCHITECTURE_DATA_API.md
4. EXECUTION_AND_ADAPTERS.md
5. SECURITY_AND_SAAS.md
6. 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md
7. FRONTEND_DESIGN.md
8. 03_TRACEABILITY_AND_SYSTEM_READINESS.md
9. docs/STAGE_C_FOUNDATION.md
10. docs/STAGE_D_FOUNDATION.md
11. source files directly related to the change

## 2. Protected baseline

Behavioral baseline: 436026eba597b2c6ae2e291a9cd8054b70ebbf7c

Historical protected state: 11/11 real-lab tests passed at the protected behavioral baseline. Current main has not re-certified that baseline in this environment.

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

Work directly against the existing `main` branch. Do not create feature, review or temporary branches.

Work directly on `main`; do not create feature, review or temporary branches. Keep each phase free of per-file, micro or scratch commits. When a phase checkpoint is explicitly requested for delivery, package the entire completed phase in exactly one consolidated Conventional Commit on `main` and push once using a fast-forward update. Do not rewrite existing history. Phase L and Phase M source integration passed hosted workflow 42619327281 (backend, frontend/build and dashboard startup jobs 3/3); protected REAL_LAB and production deployment acceptance remain separate.

Update documentation with behavior, data-contract and API changes as each phase is implemented. Keep runtime databases, reports, PCAPs and logs gitignored.

## 13. Current phase sequence and next step

The authoritative B–P sequence is in `docs/01_DEVELOPMENT_PLAN_AND_ROADMAP.md`. B–N source implementation is delivered; the bounded O/P work is delivered on the single `main` branch. The latest verified pre-guide commit was `a87bfd136d9ca47bdb5495f5c7aee416da2d191a`; hosted workflow [42632716718](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/42632716718) passed all three jobs (backend 367 passed / 7 skipped, frontend 31 passed / build passed, dashboard smoke passed). Re-check current `main` and the exact-commit Actions run before later claims. Full Phase O Cloud/SaaS remains future scope; do not introduce a tenant model or inbound control plane in the standalone Runner.

**Phase H source implementation is delivered; its protected live-lab acceptance remains outstanding.** The protocol analyzers enforce DHCP transaction sequencing and destination-based T1/T2 classification, directional/replay-paired EAPOL four-way handshakes, target Beacon identity and valid RSN parsing, and DNS question/five-tuple/time correlation. Protected live capture tests collect EAPOL/Beacon on an AP-side monitor interface sharing the existing AP PHY and DNS on AP `br0`, using foreground Paramiko tcpdump, SFTP, remote/local SHA-256 checks and Run-scoped PCAP/protocol JSON artifacts.

The protected GNS3/mac80211_hwsim execution has not yet been performed in this environment. Phase I source/CI work and Phase J device/firmware lifecycle work may proceed while Phase H live evidence is pending; combined protected acceptance and physical RF/performance/recovery claims still require Phase H live evidence first. The current dnsmasq lease is 12 hours; live T1/T2 testing requires an explicit operator-approved short-lease window and must not mutate the normal lab configuration implicitly. Do not create synthetic evidence for live certification.

The established topology remains phy0=AP, phy1=client, management eth1, WiFi data path wlan0 and AP DHCP/DNS bridge br0. Existing DHCP foreground capture and pytest node IDs remain protected. Provisioning and cleanup remain explicit; no source/CI result substitutes for the real-lab gate. Cloud/SaaS remains deferred until standalone Runner certification. Phase P source/governance cleanup is complete. Remaining work is operational acceptance, not another source-phase replay: dependency lockfiles and clean-machine rehearsal, production reverse-proxy/secrets review, protected REAL_LAB evidence and (where applicable) physical target firmware certification. Follow `docs/UPGRADE_AND_FIRST_RUN_GUIDE.md` for current installation and upgrade.

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

Protocol evidence is separated from raw packet collection. The DHCP analyzer validates DORA and distinguishes T1 unicast renewal from T2 limited-broadcast rebind only when a subsequent ACK is present. EAPOL completion requires correct AP/client direction and pairwise-key replay-counter relationships. Beacon evidence selects the expected SSID/BSSID, validates RSN structure and reports beacon interval in milliseconds. DNS correlation requires matching transaction/question, reversed IP/transport endpoints and response-after-query ordering; only correlated IP answers are retained.

The protected DHCP capture path remains unchanged. New real-lab EAPOL/Beacon and DNS capture tests preserve raw PCAPs, verify SFTP SHA-256 equality and register PCAP plus protocol JSON under the Run/TestResult. These tests have not yet been executed against GNS3/mac80211_hwsim in this environment. The current 12-hour dnsmasq lease also means live T1/T2 acceptance requires an operator-approved short-lease window.

Legacy `lib.wifi_analyzer` entry points remain available as compatibility wrappers and now expose the richer correlated evidence fields.


## 22. Iteration 14 status

WiFi telemetry is now a typed Runner service rather than an unstructured dashboard concern. `WifiTelemetryService` collects observed RSSI, SNR, channel, frequency, bitrate, PHY mode and available retry/failure counters through the secured read-only CommandRunner boundary.

Every point is explicitly labeled `VIRTUAL_WIFI` or `PHYSICAL_WIFI`. Missing source values remain unavailable and are never synthesized. RunContext now exposes the service and the session fixture constructs it for the current virtual lab.

Telemetry parser, provenance, immutability, statistics and fault-service unit tests are exercised in GitHub-hosted CI. A separate local run and real telemetry capture against mac80211_hwsim, together with the protected real-lab regression suite, have not been executed in this environment.


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

Device/Firmware adapters are implemented under `lib/adapters`. Phase J hardens configuration-derived capability parsing, OpenWrt firmware defaults, `__ENV__:` credential resolution for SFTP, image/hash/version validation, remote-path confinement, reboot capability checks, readiness polling and exclusive device locking across the entire update lifecycle. Explicit rollback now requires an expected version and independently verifies the restored version before completion is audited.

RunContext carries optional DeviceAdapter and FirmwareAdapter instances. Adapter construction does not perform firmware mutation. Provisioning, flashing, reboot and rollback remain explicit operator-authorized operations.

Hosted CI uses fake adapters and stubs for lifecycle contracts. No real hardware firmware flash, reboot or rollback was executed in this environment; target-specific certification remains outstanding.

## 26. Iteration 18 status

Internal CI/release gating is implemented. Core CI is hardware-free and cannot claim the 11/11 real-lab baseline. A separate dispatch-only self-hosted netregress-lab job runs the existing provisioning and pytest flow. Regression Intelligence now normalizes persisted pytest node IDs to semantic TestRegistry IDs.

## 27. Iteration 19 status

A durable Runner offline queue is implemented. Run snapshots are stored locally in SQLite and can be synchronized later through an outbound HTTPS transport. The local Runner remains authoritative for raw facts, and synchronization failures do not alter Run/TestResult outcomes. Pytest session completion queues the terminal Run best-effort.

Phase M keeps sync operator-triggered and outbound-only. No external Cloud endpoint is configured or contacted in this environment.

## 30. Phase L/M handoff — 2026-11-09

Phase L source integration is on `main` in `f160e3b`; a targeted validation correction is in `67c377d`. The first Phase L hosted workflow exposed a syntax defect and a malformed UI test grouping; both were corrected before combined Phase M verification.

Phase M hardens completed/healthy baseline and valid-evidence comparability; direction-aware metric deltas; required-test release classification and PASS requirements; auditable exact-scope waivers; atomic SQLite sync queue operations; lease/retry recovery; terminal-only snapshots; payload integrity; and admin-only offline queue inspection. Sync remains outbound-only and operator-triggered.

Do not claim Cloud delivery, human release approval, authenticated reverse-proxy runtime acceptance, or protected REAL_LAB certification without their respective evidence. Check the latest GitHub Actions run on `main` before describing hosted-CI verification.

## 28. Iterations 20–22 consolidated pass
Iterations 20–22 are source-implemented as the current Runner foundation: externalized credentials, local authentication/RBAC, deterministic configuration, environment fingerprinting, lab ownership, resource locking, Run orchestration, and mandatory evidence/protocol/telemetry/measurement boundaries. Runtime verification remains separate and is required before certification. Future implementation resumes at Iteration 23.


## 29. Iterations 23–25 consolidated pass
Iterations 20–25 are source-complete as the current Runner platform context. Iteration 23 owns failure semantics, firmware lifecycle control, cancellation, diagnostics and reproduction. Iteration 24 owns authorized state-changing API, OpenAPI, operational frontend and migration boundary. Iteration 25 owns baseline/release intelligence, scoped waivers and offline Runner continuity. Read 01_DEVELOPMENT_PLAN_AND_ROADMAP.md before continuing with Iteration 26.


## Iterations 26–27 status
Iteration 26 source implementation is complete: typed failure-injection coverage, recovery services, API replay/CSRF controls, SSRF/path confinement, audit-chain integrity, backup/restore, retention, stale-lock recovery and source security/readiness tooling are integrated with the existing Runner boundaries.

Iteration 27 source implementation is complete: the 11-scenario certification matrix, evidence completeness evaluator, certification CLI and documentation/repository freeze controls are integrated. Certification evidence must come from the appropriate execution class; the real-lab scenario is not satisfied by fake adapters.

## Iterations 28–30 final release wave
Iterations 28–30 are one coherent release slice. Iteration 28 owns final release integration and the single-commit rule; Iteration 29 owns reproducible operational readiness and release/doctor tooling; Iteration 30 owns governance and architecture freeze. Runner remains locally authoritative; Cloud/SaaS remains deferred above it. The release manifest is structural/source evidence and does not substitute for protected REAL_LAB execution evidence.
 
## 30. Current B–P execution handoff — 2026-11-07

Current `main` entering Phase H delivery: `64ff134690b03d6fd10c18eb6062a5c6c7a24aae`.

Phase G commit `64ff134` passed workflow 42363358706 across backend correctness tests, frontend tests/build and dashboard startup/proxy/session smoke tests.

**Phase H source implementation is delivered in this checkpoint.** Parser coverage now rejects false EAPOL handshakes using endpoint direction and replay counters, DNS cross-flow and duplicate response matching, malformed RSN elements, wrong Beacon identity, and DHCP ACKs that precede the renewal/rebind request. Protected capture tests were added for AP-side EAPOL/Beacon collection and AP-bridge DNS collection, with foreground Paramiko tcpdump, SFTP, remote/local SHA-256 verification and Run-scoped PCAP/protocol JSON artifacts. The original DHCP capture path and node ID are unchanged.

**The Phase H protected live acceptance is not yet complete.** These real-lab tests, the existing DHCP capture and the full protected suite must be executed on the established GNS3/mac80211_hwsim host. The current 12-hour dnsmasq lease means T1/T2 capture requires a separately approved short-lease window. Do not automatically alter lab lease configuration. Phase I source and hosted-CI implementation may proceed while Phase H live evidence is pending; Phase I protected RF/performance/recovery acceptance must remain gated until the Phase H live evidence is accepted. Cloud/SaaS remains after standalone certification; Phase P remains final cleanup.

## 31. Phase I delivery handoff — 2026-11-07

Phase I source implementation is delivered on the current single `main` branch. Telemetry snapshots and nested metadata are immutable; the read-only service records source/interface/environment/capture provenance and does not consume output from a known non-zero command. Netmiko exit status remains unavailable and is disclosed in the telemetry warning set rather than treated as verified command success.

Performance tests persist one warm-up plus three measured samples by default. TestRegistry governs the decision aggregate and requires at least three eligible samples: ping success MEAN, packet loss MEAN, latency P95 and throughput MEAN. Warm-ups remain in raw history but are excluded from decisions.

FaultService rejects known non-zero command results, attempts restore after partial apply or test failure, and preserves the original failure if restore also fails. Existing restore postconditions remain authoritative.

Hosted backend CI includes telemetry/statistics/fault contracts, baseline/regression consumers of the three-sample policy, and performance modules with the real-lab connection fixture skipped. Regression fixtures retain the three-eligible-sample minimum instead of lowering the policy to fit historical one-sample test data. Phase H protected live captures have not been performed here; Phase I live RF/performance/recovery certification remains pending after that prerequisite.


## 32. Phase J implementation handoff — 2026-11-08

Phase J hardening is delivered on the single main branch. Device capability booleans are strict, OpenWrt defaults are applied when profiles are loaded from configs/devices.yaml, and SFTP credential fields resolve configured environment markers instead of passing marker text to Paramiko. Firmware image versions/hashes and remote upload paths are validated; the update holds the same device-exclusive resource lock through final version verification.

Rollback is not considered complete merely because the command returned or the device became reachable. Each rollback request must identify the expected restored version, and the Runner verifies that version after readiness before recording rollback completion. The API and OpenAPI contract require that expected version.

Hosted CI remains hardware-free. Physical flash/reboot/rollback certification must be performed on the approved target device and must never be inferred from fake adapters or GNS3 virtual Wi-Fi.


## 33. Phase K implementation handoff — 2026-11-09

Phase J verification: main commit `ed236db0291ec717ad67c82d4b7ecc1e71968854`; hosted workflow [42472939649](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/42472939649) passed all three jobs. Physical firmware flash/reboot/rollback certification remains outstanding.

Phase K audit confirmed the existing auth/RBAC, session/CSRF, command policy/redaction/audit, durable idempotency, artifact integrity/sensitivity, path confinement and operational recovery foundations. This delivery hardens outbound HTTPS destination validation (complete globally-routable DNS answer set, no empty/mixed answer acceptance), adds IPv4/IPv6/security-boundary regression tests, and executes the strict source security audit plus focused API/RBAC/session tests in hosted CI. Hosted workflow [42510776806](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/42510776806) passed 3/3 jobs.

Remaining K acceptance: HTTPS reverse-proxy cookie/HSTS and trusted client-IP verification; real deployment secret configuration; independent dependency scan and threat-model review; DNS rebinding/connection-time resolution analysis. The source audit reports optional scanner availability; it does not run Bandit, Semgrep or pip-audit itself. Do not imply production deployment or penetration-test certification.

Phase L and Phase M are delivered in the current main history. The next active slice is Phase N — Standalone Packaging and Production Certification; Phase O Cloud/SaaS remains deferred until standalone acceptance, and Phase P remains the final repository organization/cleanup phase.


### Phase K artifact download authorization

The v1 artifact download route now enforces the stored sensitivity label: PUBLIC/INTERNAL uses the authenticated view contract; SENSITIVE and unrecognized labels require admin authorization. Remote downloads require a configured `NETREGRESS_DASHBOARD_TOKEN` and constant-time bearer-token comparison even when application session auth is disabled. Local authenticated sessions remain usable. Download containment and SHA-256 checks are unchanged. Regression tests cover remote token and OPERATOR/ADMIN role behavior. Reverse-proxy source-IP trust must be verified in deployment; never trust arbitrary forwarded-IP headers.


Phase K's artifact download authorization correction is verified by workflow [42511179934](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/42511179934): PUBLIC/INTERNAL artifacts retain the authenticated-view route; SENSITIVE and unknown classifications require admin; remote clients require a configured bearer token. The backend, frontend and dashboard jobs passed. Remaining deployment checks are trusted-proxy source-IP configuration, cookie/HSTS behavior, production secrets, independent dependency scanning, DNS rebinding and threat-model acceptance.


## Current combined Phase O/P handoff — 2026-11-09

Phase N is delivered in commit 80831042d8f2f6b86562a0b6ac951cbfe87bceaf; hosted workflow 42629371133 passed all 3 jobs. Backend correctness: 360 passed, 7 skipped; API security: 35 passed; frontend: 31 passed; dashboard launcher/proxy/session smoke: passed. Protected real-lab and physical firmware tests were not run by hosted CI.

Phase O full Cloud/SaaS expansion is future scope by user direction. Do not add tenant tables, PostgreSQL, Celery/Redis, inbound Runner control, distributed sessions or Cloud deployment speculatively. The only small integration in the combined O/P slice is python scripts/netregress_sync.py --status, a local read-only queue inspection over the existing outbound-only synchronization queue. It reports aggregate delivery counts without a URL/token, migrations, network requests or payload/error disclosure.

Phase P cleanup retains run_all.sh and verify_system.py as compatibility wrappers, aligns them to canonical install/release/dashboard commands, strengthens .gitignore, indexes the standalone operations runbook and extends release manifest required paths plus CI tests. Do not delete these compatibility entry points without a separate reference audit. Do not rewrite history or delete remote branches without verified ownership and a safe cleanup plan.

The Python and frontend transitive dependency lockfiles remain missing; do not fabricate them or mark production reproducibility true. Clean-machine install/upgrade/backup/restore, production reverse-proxy/secrets review, protected 11-scenario REAL_LAB and physical firmware acceptance remain open. Phase O Cloud receiver/tenant control plane remains deferred.


## 34. NetRegress expansion resumption handoff — 2026-11-24

Current remote integration baseline: main commit 3416d2ec5d6e3fa869975845b8d2629201e1acca. The exact-main quality workflow [45368988732](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45368988732) completed successfully: backend correctness/security, dashboard startup/proxy/session smoke, frontend tests and production build all passed.

EXP-P08 Network Intent, EXP-P09 multi-vendor compilation and EXP-P10 Ansible source integration are present and covered by the exact-main quality workflow. P10 uses generated plans/playbooks and static inventory from published intent/compiler artifacts; it is not yet a general arbitrary-playbook execution environment. Its currently enabled live transport families are Linux/FRR SSH, Cisco IOS/IOS-XE network_cli and Arista EOS network_cli. Junos/PAN-OS remain compile-only. The P10 audit and RQ-023 retain the external live-device and desktop-package acceptance boundary; Linux desktop package run [45368016475](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45368016475) later completed successfully on its exact source commit d845ea1f8d4d768c431cf45751a36865b499effa; that is desktop packaging evidence for that commit, not for later Stage G changes.

Stage G is an additive native-interoperability programme; it does not replace provider, topology, Network Intent, compiler or Ansible ownership. The G01 source audit is recorded in docs/STAGE_G_NATIVE_INTEROPERABILITY_AUDIT.md. Important distinction: GNS3/CML/EVE-NG have live REST provider adapters, but GNS3 .gns3, CML YAML/VIRL and EVE-NG .unl file codecs are not yet present. Packet Tracer has a bounded .pkt codec and immutable provenance, but serializer coverage and Packet Tracer desktop reopening remain incomplete. The canonical topology currently has semantic nodes/links and basic X/Y positions, not a full vendor presentation/unknown-field model.

**G01 = SPECIFICATION_COMPLETE. Next implementation package = G02 — Extended Native Topology Data Model.** Reuse TopologyStudioService, immutable topology revisions and existing source provenance. Add a versioned presentation model pinned to canonical revision hashes, bounded namespaced extensions and backward-compatible generic provenance. Do not create a second topology database, place unbounded vendor fields in the strict semantic validator, or reinterpret provider APIs as native codecs.

Preserve the original GNS3/mac80211_hwsim and Wi-Fi provisioning contracts, current Packet Tracer provenance/API compatibility, Project/Lab authorization, Credential Vault secret boundaries, compiler/Ansible approval and recovery semantics, existing Run/Artifact/Pipeline ownership and all existing regression tests. Keep AI/LLM/agent/model integration excluded. Do not enable or manually trigger phase workflows before a phase is complete; preserve existing path-triggered CI behavior and verify exact-head results after the documentation/source checkpoint.


## 35. NetRegress G02 resumption — 2026-11-24

G01 audit commit: b2ac90174f9483238eb597bae0d45024fdda7b03. Its exact-head quality workflow 45371470050 passed. The earlier Linux desktop package workflow 45368016475 also completed successfully on d845ea1f8d4d768c431cf45751a36865b499effa; it is not evidence for later code commits.

G02 implementation adds Alembic 20261124_20 (schema version 30), topology_presentation_revisions, topology_source_artifacts, and topology_source_assets; shared bounded metadata validation; SHA-256-verified presentation and source/asset services; Project/Profile/topology hash binding; presentation lifecycle API endpoints; OpenAPI; Topology Studio presentation snapshot/viewport controls; and dedicated migration/service/API tests. Existing Packet Tracer source table/endpoints, canonical topology, provider runtime adapters, GNS3 Wi-Fi behavior, Network Intent, P09 compilers, P10 approval/Vault execution and Run/Artifact/Pipeline ownership are preserved.

**G02 state at this checkpoint: INTEGRATION_IN_PROGRESS pending the exact-main quality workflow.** Detailed scope and explicit UI/native-codec limitations are recorded in docs/STAGE_G_G02_PRESENTATION_MODEL_AUDIT.md. The G02 canvas currently captures viewport, canonical node positions and basic link presentation; advanced ports, routes, layers, annotations, imported assets and vendor extensions are stored by the backend schema but not editable from the canvas UI yet.

After exact-head CI passes, set RQ-055/G02 to CI_VERIFIED and proceed to G03 — Native Format Interoperability Framework. If it fails, resume the failed test or implementation first. Keep provider adapters separate from file codecs. Preserve the generic source-artifact store as the future codec provenance boundary and do not re-purpose the Packet Tracer-specific table. No native GNS3/CML/EVE codec or native desktop round-trip should be claimed until later packages demonstrate it. Continue excluding all AI/LLM/agent/model integration.


## 36. P13/P14 implementation handoff — 2026-11-24

P13 introduces backward-compatible immutable dependency graphs for existing Pipeline revisions. Missing depends_on remains sequential; explicit empty arrays permit independent roots; supported edges are SUCCESS, FAILURE and COMPLETED; all cycles and invalid edges are rejected. The existing durable worker executes dependency-ready nodes and preserves branch history. RECOVERY_REQUIRED halts the graph. A visual node/edge editor replaces raw full-pipeline JSON authoring while retaining operation input JSON for bounded typed data.

P14 introduces three linked observation surfaces without replacing existing providers or capture engines: (1) registered provider health/version/resource/capture-capability snapshots through the shared registry/Vault provider session, (2) append-only Project/Lab/Device interface counters captured only by ip -s -j link show through SecureCommandRunner and ParamikoExecRunner with system host-key verification plus a same-device active SSH_PASSWORD CredentialVaultService.use_secret callback, and (3) a Run network-observability query joining persisted metric samples, Wi-Fi telemetry, health, PCAP metadata and ProtocolEvidenceService JSON. The query applies independent performance.read/evidence.read redaction, verifies each evidence artifact SHA-256 before returning protocol JSON, and never returns PCAP bytes or local paths. No arbitrary commands, caller-supplied metrics, guessed zeroes or one-sample rates are accepted. Alembic head becomes 20261124_23/schema_meta version 33 with immutable device/provider snapshot history.

Source audit documents: docs/EXP_P13_IMPLEMENTATION_AUDIT.md and docs/EXP_P14_IMPLEMENTATION_AUDIT.md. P13/P14 implementation is committed as two sequential commits, then fast-forwarded to main once; exact-head quality checks are held until both batches are integrated. If CI fails, repair the failing check before claiming the batch complete. Keep existing Stage G native-interoperability scope and all prior provider, credential, pipeline, Run, evidence and workspace boundaries unchanged. AI/LLM/agent/model integration remains excluded.


## 37. Stage G G02–G06 implementation continuation — 2026-11-26

G02–G06 source is implemented as an additive native-file interoperability layer on TopologyStudioService, G02 TopologyPresentationService and TopologySourceArtifactService. G03 uses lib/native_topology and stays independent of the live provider registry. G04 supports GNS3 .gns3 revisions 7/8/9; G05 supports CML lab YAML 0.1.x plus a constrained legacy VIRL 0.95 XML subset; G06 supports EVE-NG .unl versions 1/2, representing each shared EVE network as a canonical segment node.

Native imports create a new Project/Lab-scoped topology profile and immutable DRAFT topology/presentation revisions, then persist the original native source and SHA-256. Exports require both revisions to be published and bound to the exact source artifact. Only mapped presentation fields (layout/labels and supported CML annotation data) are serialized. Semantic graph edits, configuration execution, live provider/controller contact and external image loading are not part of this path. Source documents and unknown fields remain preserved where supported; associated project directories/images are not imported. Vendor GUI/controller reopen has not been verified.

New API routes: GET /api/v1/topologies/native-codecs, POST /api/v1/topologies/import/native, GET /api/v1/topologies/{profile_id}/native-artifacts, and GET /api/v1/topologies/{profile_id}/native-artifacts/{source_id}/export. Topology Studio exposes native import, immutable source history and guarded export. Tests are wired into the NetRegress quality workflow.

RQ-055–RQ-059 remain IMPLEMENTED_PENDING_CI until the exact final-main source and CI gates pass. Continue with G07 Packet Tracer fidelity only after G02–G06 exact-head CI is green. G08–G12 remain separate packages. Preserve P08–P14 provider, credential, compiler, Ansible, pipeline, Run, evidence and recovery boundaries. Keep AI/LLM/agent/model integration excluded.
