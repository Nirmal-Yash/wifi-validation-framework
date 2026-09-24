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

Iterations 1–3 are complete on main. The next code slice is Iteration 4: Metrics + raw Samples persistence and collection, while preserving the existing pytest command and real-lab behavior.

The current pytest result recorder remains a compatibility path until Run-scoped TestResult persistence replaces it in later iterations.