# NetRegress — Architecture Decision Record

Answers to the 206-question and 50-question discovery questionnaires. Default posture: decisive recommendation (**R**) everywhere the questionnaire allowed it, since these are engineering-judgment calls, not preference calls — flag back anything you'd decide differently and I'll adjust downstream answers that depend on it. A few items are genuinely business-decision-later items; those are marked **D (defer)**.

## How to read this

Answers are grouped exactly under the original lettered sections (A–AF, then BL, TC) so you can cross-reference by number against the source questionnaire. Every answer here is internally consistent with every other — where one decision constrains another, the later answer says so explicitly rather than silently assuming it.

## Core decisions that recur throughout

| Decision | Answer |
|---|---|
| Product name | **NetRegress** (platform/Cloud); this repo stays the validation engine underneath it |
| Run ID | ULID (DB key, sortable) + `RUN-YYYYMMDD-HHMMSS-XXXX` (human display) |
| Execution model | Hybrid — cloud control plane, local runner agent executes against the lab, outbound-only |
| Two separate status axes | **Lifecycle status** (mechanical: did it run — QUEUED/RUNNING/COMPLETED/FAILED/LAB_FAILED/CANCELLED) vs. **business outcome** (did it validate — VALIDATED/VALIDATED_WITH_WARNINGS/REJECTED/UNVALIDATED). Never conflate these. |
| Evidence invariant | A validation may never return PASS if required evidence collection failed, even if the raw assertion succeeded. This is the platform's single non-negotiable rule. |
| Deployment shape | Modular monolith — one repo, one app, one DB, clear internal service boundaries — through Phase 10b. No microservices until scale forces it. |

---

## A. Product and end-state

1. **Name:** NetRegress is the product/platform name. Keep "WiFi Validation Framework" as the internal description of the engine this repo contains.
2. **Boundary:** WiFi/network devices initially, but built on the `DeviceAdapter` abstraction so expansion doesn't require a redesign later — narrow scope now, extensible seams from day one.
3. **First physical target:** A Linux/OpenWRT-based AP or router. Smallest engineering distance from the current hostapd-based virtual lab — nearly a 1:1 port of what already works.
4. **Vendor strategy:** No vendor commitment yet. Recommend OpenWRT-compatible hardware (GL.iNet, TP-Link running OpenWRT, or a dev board) — gives SSH/API access without needing vendor cooperation, which was flagged as the "driver problem" risk from day one of this project.
5. **Multi-device scope:** One firmware → one device for Phase 9. Multi-device/SKU only after that single path is proven; avoids combinatorial test-matrix explosion in the MVP.
6. **Success criterion:** Yes — the release-engineer flow (`select firmware → flash → provision → run → inspect → accept/reject`) with no manual shell work is the correct definition of "production-level," but it's the Phase 10a end state, not a near-term requirement.

## B. Who actually runs the tests

7. **Execution model: C — Hybrid.** Cloud is the control plane; a local runner/agent executes against the customer's lab/device and uploads artifacts. This is the only model that works once physical/local hardware is involved — the cloud can't run a customer's Wi-Fi AP.
8. **Connectivity:** Outbound-only from the agent. Standard, correct pattern (GitHub Actions self-hosted runners, Datadog agent) — no inbound firewall rules required of the customer.
9. **Agent:** Yes, a permanent NetRegress Runner. It should own provisioning, execution, artifact upload, firmware receipt, health reporting, and must survive temporary cloud disconnection by queuing results locally and resyncing.
10. **Cloud independence:** Yes, a local lab should keep running/testing during a cloud outage — the runner is authoritative for raw execution.
11. **Source of truth:** Split it. **Runner** is authoritative for raw evidence (what actually happened). **Cloud** is authoritative for business decisions (baseline promotion, waivers, release approval). Neither owns both.
12. **Repo role:** This repository becomes the **Runner / Core Validation Engine** repo, consumed by a separate Cloud backend repo later — keep it focused on lab control, execution, and evidence, not multi-tenant business logic.

## C. Pytest compatibility

13. **Pytest stays canonical, indefinitely.** `Run Orchestrator → pytest → plugins/fixtures → adapters` is confirmed.
14. **CLI compatibility:** Yes, `pytest tests/ -v --firmware-version=v1.0` must keep working after Phase 1. Implement this by having a session-scoped `conftest.py` hook call `RunService.create_run()` transparently — the shell command stays the primary interface, it just gains a `run_id` under the hood.
15. **Node IDs:** Stay stable — don't rename `tests/test_ping.py::test_x` as part of this refactor.
16. **Stable semantic ID:** Yes, add `wifi.latency.threshold`-style IDs as declared test metadata, mapped 1:1 to the pytest node ID. Node ID for pytest mechanics, semantic ID for cross-version stability.
17. **Test metadata:** Yes, adopt the full proposed schema (`test_id/category/protocol/severity/equipment/direction/requires/destructive/estimated_duration`) — add `criticality` (BLOCKING/ADVISORY/INFORMATIONAL, see BL-03).
18–19. **Ordering/dependencies:** Refactor toward independently-executable tests, with an explicit lightweight dependency declaration (`requires: [dhcp]`) driving default order — not hard pytest fixture-order side effects. This dependency data doubles as BL-17's skip-on-prerequisite-failure input.
20. **Selection:** Yes — smoke/regression/performance/protocol/recovery/full-suite, all selectable through the same Run abstraction, backed by the category metadata.

## D. Run model semantics

21. **Run creation:** `CLI/API → RunService → DB`, before pytest starts — not implicitly created by pytest. A thin plugin calls `RunService.create_run()` at session start.
22–23. **Run ID:** ULID as the DB primary key (sortable, no library-maturity risk unlike UUID7) plus a human-readable `RUN-YYYYMMDD-HHMMSS-XXXX` display ID.
24. **Lifecycle states:** `QUEUED → PREPARING → LAB_HEALTH_CHECK → RUNNING → COMPLETED | FAILED | LAB_FAILED | CANCELLED | ABORTED`. `UNVALIDATED` is **not** a lifecycle state — it's a business-outcome overlay on a `COMPLETED` run (see Core Decisions table).
25. **Overall PASS:** All BLOCKING tests PASS **and** lab health PASS **and** no infra error **and** evidence is complete for tests that require it.
26. **Partial run:** Yes, becomes `LAB_FAILED`, not `FAIL`, when the lab dies mid-run.
27. **Fixture failure:** `ERROR` at the TestResult level (distinct from FAIL). Rolls up to Run-level `LAB_FAILED` if infra-caused, `FAILED` if test-logic-caused — the exception taxonomy (TC-17/18) decides which.
28. **Skipped tests:** Don't count against Run validity unless BLOCKING (BL-03); a skipped BLOCKING test pushes the Run to `UNVALIDATED`, never silently ignored.
29. **XFAIL/XPASS:** Normalize into your own model but retain the raw pytest outcome as metadata. XFAIL → your own `KNOWN_FAILURE` concept, tied to BL-24 waivers. XPASS → flagged for review, not silently treated as PASS.
30–31. **Cancellation:** Yes, human-cancellable. Automatic cleanup (restore links/tc/DHCP/DNS, stop captures, release lab lock, mark artifacts incomplete) implemented as a try/finally at the orchestrator level so mid-test cancellation still cleans up.
32–33. **Retry/attempts:** Both — a brand-new Run is always allowed, and `Run → Attempt[1..n] → TestResults` is also supported. Implement `Attempt` from the start; retrofitting it later is expensive.

## E. TestResult / sample semantics

34–36. **Sample model:** One `TestResult` can contain multiple samples. **Persist raw samples plus derived aggregate statistics** — your instinct here is correct; aggregate-only data can't be reanalyzed later.
37. **Sample count:** Per-test configurable with a global default, exactly as the example YAML.
38. **Warm-up:** Yes, excluded from statistics but still logged as diagnostic data.
39. **Outliers:** Retained by default, not silently dropped. Use median/p95 (outlier-resistant) for the PASS/FAIL signal rather than mean alone, so outliers don't corrupt classification even though they're kept.
40. **Retry vs. sample:** Distinct. A failed measurement-command retry is tagged `sample_status: RETRIED`, not counted as a real statistical sample.
41. **Confidence stats:** Mean/median/min/max/p90/p95/stddev now. Defer p99/confidence intervals until N ≥ ~20 — small-N confidence intervals are misleading.
42. **Threshold evaluation:** On the aggregate metric (the percentile appropriate to that metric — e.g., p95 for latency), not every sample. Revisit if flakiness data (BL-23) demands sample-level checks later.
43–44. **Snapshot:** Yes, absolutely — freeze the exact threshold/config used **into the Run**, and freeze the full effective config (SSID/channel/thresholds/topology/device mapping/software versions/test selection). Without this, historical regression comparisons become meaningless the moment YAML changes.

## F. Baseline semantics

45. **Baseline identity:** Composite — device/device-family + firmware major line + test-suite version + environment/lab-class. Not tenant-scoped at the engine level; tenancy is layered on top by the Cloud org model.
46. **Selection:** Yes, a comparison references an explicit `baseline_run_id`, not a loose version string. The string becomes the human label; the pointer is a hard foreign key.
47. **Named baselines:** Yes ("Golden v1.0", etc.), stored alongside the entity.
48. **Promotion:** An explicit, role-gated `RunService.promote_baseline(run_id)` action — never automatic on a green run.
49. **Requirements:** Yes to all four — 100% BLOCKING tests pass, lab health pass, minimum sample count met, no UNVALIDATED results. A baseline promoted from weak evidence poisons every future comparison.
50. **Immutability:** Yes, immutable once promoted.
51. **Replacement:** Old baselines stay available historically — superseded, never deleted.

## G. NO_BASELINE and UNVALIDATED

52. **NO_BASELINE** means exactly "no comparable baseline exists" — a regression-classification concept only.
53. **UNVALIDATED causes:** Incomplete run, lab failure affecting that test, insufficient samples, missing/corrupt required evidence, failed environment snapshot. Explicitly **excludes** "test skipped" (its own state) and "baseline itself invalid" (surfaces as NO_BASELINE, not UNVALIDATED) — conflating these hides what actually went wrong.
54. **Three separate concepts, confirmed:** NO_BASELINE (regression layer) · UNVALIDATED (business-outcome layer) · lifecycle status (mechanical layer). Never merge them.
55–56. **CI gate:** Both NO_BASELINE and UNVALIDATED fail the release gate by default (fail-closed). Only an explicit waiver (BL-24) overrides.

## H. Regression model

57. **Threshold location:** Test metadata/config YAML, per-test override over a global default — as your example shows.
58. **Threshold types:** Percentage and absolute (min/max) now. Percentile and statistical-significance thresholds deferred until sample counts meaningfully support them.
59. **Independence:** Yes — functional PASS/FAIL is independent of performance regression; a result can be functionally PASS with a SOFT_REGRESSION tag on top.
60. **Hierarchy:** Functional FAIL always dominates the Run's blocking outcome. Within one TestResult, functional status is primary; degradation is a secondary, non-competing tag.
61. **Multiple metrics:** Yes, one TestResult holds a `metrics[]` collection (latency_ms, packet_loss_pct, jitter_ms, each independently classified) — a real schema change from today's single `metric_value` column.
62. **Composable categories:** Yes — `PERFORMANCE + AVAILABILITY` simultaneously. Store as a set, not a single enum.

## I. Artifact architecture

63. **Storage (Phase 1):** Local filesystem under `results/`, DB stores metadata/paths/checksums only. Don't build object-storage abstraction yet.
64. **Ownership:** Every artifact belongs to a Run always, TestResult optionally, typed via an `ArtifactType` enum.
65. **Types:** Adopt the proposed list, add `LAB_HEALTH_SNAPSHOT` and `ENV_FINGERPRINT`.
66. **Naming:** Content-addressed (SHA-256-based) internal filename + human-readable metadata in the DB.
67. **Integrity:** SHA-256 remains the permanent baseline hash — no need to upgrade without a specific threat model.
68. **Dedup:** Defer to the Cloud phase — premature for a single local lab.
69. **Compression:** Defer to Cloud phase; local disk is cheap today.
70. **Retention:** Indefinite locally. For tenants, make it a configurable `retain_until` field per plan/contract — design the field now even though the number isn't decided (**D**).
71. **Sensitive evidence:** Yes — PCAPs/command logs can contain credentials, PSKs, MACs, customer IPs. Redaction is a hard requirement before any Cloud exposure, not optional polish.
72. **Access:** Always through an authenticated API endpoint, never raw static file serving, once auth exists. This is what makes artifact ACLs (Q142) enforceable at all.

## J. Lab Health model

73. **Timing:** Before and after every run at minimum, plus on-demand. Continuous background polling is a Cloud-phase nicety, not now.
74. **Checks:** The proposed list (GNS3/Docker/libvirt/hwsim/AP/Client/Router/Management/DHCP/DNS/iperf/SSH) is right — add **disk space** on the lab host (silent killer for PCAP-heavy runs) and **NTP/clock sync** (matters for later correlation).
75. **Severity:** `HEALTHY/DEGRADED/FAILED/UNKNOWN` per component, rolled up into `Run.environment_health`.
76. **Diagnostics:** Yes, any unhealthy component auto-captures a diagnostic bundle — what makes `LAB_FAILED` actionable instead of just a red dot.
77. **Auto-remediation:** Never fully automatic. The reprovision script may be operator-invoked as an explicit "repair and retry" action; Lab Health should never silently trigger it (ties to AD-193).
78. **Degraded execution:** Tests still run, but the Run is tagged `environment_health: DEGRADED` so results are contextualized, not silently trusted. `FAILED` blocks the run entirely.
79. **Fingerprint:** Yes, capture the full environment fingerprint (OS/kernel/python/pytest/GNS3/Docker image/hostapd/wpa_supplicant/FRR versions/hwsim state/git commit) per Run — cheap, and invaluable for "why did this regress" months later.
80. **Multiple labs:** Yes, inevitable under NetRegress Cloud — add `lab_id` as a first-class Run field from Phase 2 onward, even with one lab today, so Phase 10b doesn't force another migration.

## K. Configuration refactor

81. Yes, move duplicated shell constants into structured config over time (Phase 2 scope).
82. Yes, adopt the `defaults → environment → lab → device → run → test-override` hierarchy exactly as proposed.
83. YAML stays human-authored; don't move to generated config without a real GUI-editor need.
84. Yes, credentials only in env vars/secret manager, never tracked YAML — non-negotiable, part of the Phase 1S security gate.
85. Yes, invalid config blocks Run creation entirely — fail fast rather than wasting lab time on a run that's guaranteed to break mid-execution.
86. Yes, store the exact config version/hash in the Run — this is what makes the config snapshot (Q43–44) actually traceable.

## L. SSH / command execution refactor

87. Yes, a single `CommandRunner` abstraction (`NetmikoRunner`/`ParamikoExecRunner`/`LocalRunner`) — directly fixes the inconsistency between `fault_injector`'s shell-string construction and `capture`'s raw Paramiko path.
88. Yes, argument-safe execution by default; shell-string mode reserved for the narrow cases (AP capture's prompt handling) that genuinely need it, explicitly marked.
89. Yes, allow-list destructive commands (`ip link`, `tc`, `iptables`, `systemctl`, `pkill`, `dhclient`) per adapter/device.
90. Yes, `sudo` handling belongs in the execution layer, not hand-rolled per call — centralizes and makes it auditable.
91. Yes, log executed commands and outputs into Run evidence as a `COMMAND_OUTPUT` artifact type.
92. Yes, automatic secret scrubbing (passwords/PSKs/tokens/auth headers) on command logs — mandatory, ties to Q71.
93. Yes, per-command connect/execution/idle/total timeouts — the current mostly-fixed timeout is a known fragility source per your own troubleshooting docs.
94. Retry connection establishment and idempotent operations only. Never blind-retry a command that may have partially mutated state (`tc`, `dhclient`). Command metadata declares `idempotent: true/false`.

## M. Device adapter architecture

95. The proposed operations are right; add `capabilities()` (ties to TC-25) and a distinct `execute_shell(cmd)` alongside structured `execute()`.
96. Yes to the proposed firmware operations; add `rollback()` as first-class (see Q99).
97. SSH/SCP first (zero new infra), then TFTP (common for embedded/router flashing). Defer serial/vendor-API/bootloader/USB until a specific device family demands it.
98. Not for MVP — software reboot via SSH is sufficient. Physical power-cycle (smart PDU) becomes necessary only once a device can hang/brick without it.
99. First-class from the start — a firmware validation tool with no rollback path is a real support/safety liability the moment it touches real hardware.
100. Yes, adopt the capability-declaration list exactly — this is what BL-15/16's conditional/capability-driven testing runs on.
101. Yes — `fw_simulator.py` becomes the reference fake Device/FirmwareAdapter, used for both framework self-tests and a hardware-free demo mode.

## N. Physical RF vs. virtual WiFi

102. Yes, formalize `VIRTUAL_WIFI / PHYSICAL_WIFI / RF_CERTIFICATION` as an explicit label on every telemetry point and in the UI — protects against ever overclaiming what hwsim proves.
103. Yes, design the telemetry API to accept real physical measurements later (RSSI/noise floor/channel utilization/MCS/PHY rate/retry rate), same schema, labeled `PHYSICAL_WIFI`.
104. Yes, RF calibration is permanently out of scope — that's a different business (an accredited test chamber), not this product.

## O. Performance testing

105–107. Yes to downlink/uplink/bidirectional, yes TCP+UDP, yes jitter as first-class for UDP.
108. Yes, duration is config-driven per test.
109. Yes, warmup + N independent runs + aggregate stats, matching the plan exactly.
110. Yes, capture CPU/memory/interface utilization during performance tests — cheap, and it prevents a whole class of false-positive regressions (resource contention mistaken for network regression).

## P. Protocol evidence

111. Confirmed absolute: real captured traffic/state only, never synthetic — matches the existing product invariant permanently.
112. Correlate to **all** of Run + TestResult + client MAC + AP BSSID + transaction ID + timestamp window — each answers a different debugging question.
113. Yes, full DORA transaction correlation, not packet counting.
114. Yes, identify actual EAPOL message numbers (1/2/3/4 of the 4-way handshake), not ">=4 packets" — the current approach could false-pass on duplicate/out-of-order packets.
115. Yes, full beacon field validation (SSID/BSSID/channel/RSN/cipher/AKM/interval/capabilities).
116. Yes, full DNS query→response→transaction-ID→answer correlation.

## Q. Capture architecture

117. Yes, `lib/capture.py` becomes the universal capture service; AP-specific Paramiko mechanics move into a `CaptureTransportAdapter` — resolves the inconsistency your own TECH_ARCH doc already flags.
118. Yes, capture location driven from topology/config, not hardcoded to `ap_host/br0`.
119. Yes, adopt the `CaptureSession` lifecycle (start/ready/trigger/stop/verify/transfer/hash/register) exactly as proposed.
120. **UNVALIDATED**, not FAIL and not silent PASS. The functional behavior may be fine, but the evidence invariant means "can't prove it" must never quietly become "PASS."

## R. Dashboard behavior

121. Optimize the default landing view for the **Release Engineer** question ("is this firmware safe to release") — highest-stakes, most time-pressured. The other three roles get dedicated pages, not a shared landing screen.
122. Yes, `/` becomes the current active Run view (or most recent Run).
123. Yes, arbitrary run-to-run comparison, not just baseline-vs-current-firmware.
124. All listed filters are first-class; `tenant` applies only once multi-tenancy exists (Phase 10b).
125. Polling is fine through Phase 8. Move to SSE/WebSocket only if live-progress becomes a real UX complaint — not preemptively.
126. Yes eventually (start/cancel/retry/select), but strictly gated behind Q127.
127. Yes, dashboard is strictly read-only until operator auth/roles exist — no exceptions.

## S. API design

128. Yes, commit an OpenAPI spec once `/api/v1` exists — cheap if generated from Pydantic models (Q130).
129. Flask stays through Phase 8; the recommendation is internal structure (typed models, consistent errors), not a framework swap. Don't add FastAPI/Django until Phase 10b's needs actually force it.
130. Pydantic — best fit with Flask, gives typed models and auto OpenAPI, and matches the stack you already use on Nirikshan.
131. Yes, a consistent `{error:{code,message,details}}` contract on every `/api/v1` endpoint from day one — retrofitting this later breaks every client.
132. Yes, pagination/sorting/filtering as a baseline capability on every collection endpoint from the start.
133. Yes, idempotency-key support on `POST /api/v1/runs` — prevents the double-webhook-double-run failure mode common in real CI retries.
134. Consumer order: dashboard first, then CLI, then CI (10a/10b), then external customers/SDK/React later. Design the contract for the full list now, even though only the dashboard uses it first.

## T. Authentication and authorization

135. Yes, even the local single-user dashboard gets basic auth in Phase 1S — cheap now, means "add SaaS auth" later is a provider swap, not a rebuild.
136. Email/password + OIDC (Google/GitHub login) as the initial pair. Defer SAML/enterprise SSO until an actual enterprise customer requires it (usually sales-negotiated).
137–138. Yes to both — `Organization → Users/Labs/Devices/Projects/Runs`, with `Project` as the right unit for "one firmware line."
139. `Owner/Admin/Operator/Viewer` is sufficient — don't add roles speculatively.
140. Operator: execute tests, flash firmware (with confirmation), modify lab config. Admin-only: delete artifacts, promote baselines — higher blast-radius actions deserve a stricter gate.
141. Yes, immutable audit events for every security-sensitive action — the platform should hold itself to the same evidentiary standard it demands of firmware.
142. Yes, hard artifact ACL scoped to Project, enforced even within the same Organization (matters for an MSP running multiple clients under one account).

## U. SaaS execution / queue

143. Treat Celery/Redis as the working assumption, revisit only if a specific durability requirement forces a change — don't block on a "perfect" choice.
144. Logical routing by tenant within a shared queue, not a literal per-tenant broker queue — a dedicated queue per tenant doesn't scale operationally and routing + concurrency limits already give the isolation that matters.
145. Realistic initial target: 5–20 orgs, one lab each, low concurrent-run count. Design for correctness and easy horizontal scaling, not 1,000 tenants on day one.
146. Confirmed: no, two Runs cannot safely share one physical lab simultaneously — enforce a lab lock (TC-22).
147. Jobs exceeding expected duration become `TIMED_OUT` (sub-state of FAILED/LAB_FAILED depending on where the hang occurred), with the same automatic cleanup as cancellation.
148. Distinguished via the exception taxonomy: SSHTimeout/DeviceUnavailable → `LAB_FAILED`; worker process death → `WORKER_CRASHED` (detected via Celery heartbeat, never silently retried); runner/cloud disconnection → `RUNNER_DISCONNECTED` (its own distinct state, so it's clear this isn't the firmware's fault).
149. Infra/orchestration jobs may auto-retry with backoff; test-execution jobs must not — a silently-retried test that then passes hides real flakiness (BL-23 handles inconsistency properly instead).

## V. CI / webhook integration

150. GitHub Actions first (highest install base among likely early customers), a generic HTTP webhook built simultaneously as the universal fallback. Defer GitLab CI/Jenkins/Azure DevOps to demand.
151. Yes, adopt the proposed trigger payload exactly, plus an idempotency key.
152. Return "queued" with a `run_id` and status-polling URL immediately; also accept an optional webhook callback URL for push-based completion. Covers both simple and sophisticated CI integration without forcing synchronous waits that would time out most runners.
153. Three separate decision points: the platform decides technical classification; CI enforces it as a release gate; human approval (BL-06) sits on top only for promoting a firmware version to "released," not per individual run.
154. Signed payload (HMAC shared-secret) for inbound CI triggers; short-lived tokens for the runner agent's own calls to the cloud — different mechanisms for different actors, correctly.

## W. Firmware artifact handling

155. Temporary signed download URL preferred over long-term cloud storage — lower liability/cost, matches how most CI systems already publish build artifacts. Revisit only if customers specifically need firmware history retained by you.
156. Yes, mandatory SHA-256 (and signature where the vendor provides one) before flashing — non-negotiable, flashing unverified firmware onto real hardware is safety-critical.
157. Yes, adopt the full metadata list.
158. Yes, reject incompatible firmware-device pairings, checked against device capability declarations (Q100) and firmware metadata (Q157).
159. Yes, adopt the lifecycle states — mirrors the Baseline lifecycle's rigor applied to the firmware artifact itself.

## X. Database architecture

160. Keep raw SQLite for Phase 1, but introduce a thin repository/DAO layer now (`RunRepository`, `ArtifactRepository`, etc.) so Phase 11's Postgres swap only touches the repository implementation — cheap now, expensive to retrofit later.
161. SQLAlchemy once Postgres lands — mature, works across SQLite/Postgres during transition, integrates with Alembic.
162. Yes, Alembic from the point SQLAlchemy is introduced; simple versioned scripts before that.
163. `results/test_results.db` becomes a one-time migration source into the new schema, then retired.
164. Yes, migrate historical history into the new model — a bounded, one-time effort, and losing it is an unnecessary cost.
165. Orphaned pre-migration rows become synthetic imported Runs (one per distinct historical firmware_version label), preserving queryability with weaker environment metadata (acceptable — clearly historical).
166. Yes, TestResult + metrics + artifact references commit as one atomic transaction — avoids the orphaned-artifact problem (TC-16).
167. Yes, index run_id/firmware/timestamp/device/test_name/classification now — cheap at creation time, expensive under load later, and these are already your known dashboard filter columns.

## Y. Observability

168. Yes, structured JSON logging via Python `logging` from Phase 1S onward — bundle with redaction (Q92), they're naturally implemented together.
169. Yes, correlation IDs (`request_id/run_id/test_result_id/device_id/tenant_id`) on every log line — makes multi-tenant Cloud debugging tractable at all.
170. Defer Prometheus-style metrics to Phase 10b — not useful for a single local lab.
171. Yes, `/api/v1/health` and `/api/v1/readiness` once 10b/11 exist — standard deployment-platform convention.
172. Yes, every failure auto-produces a diagnostic bundle — extends the Lab Health diagnostic idea (Q76) to all failure types.

## Z. Frontend migration boundary

173. React + Vite specifically, not Next.js — this is an authenticated internal tool, no SSR/SEO need, and Vite matches your existing project patterns.
174. Reuse actual components (auth flows, RBAC-gated UI, dashboard shells, table/filter components) from Sentinel AI/Nirikshan where the domain genuinely overlaps, not just as inspiration.
175. Yes, a small internal component library — pays for itself once Dashboard 2.0's eight pages need consistent styling.
176. Desktop-first only — this is an operational engineering tool, not a consumer app.

## AA. Testing the refactor itself

177. Yes, unit-test every new service — this is now the actual business logic layer, and untested business logic in a validation product undermines the product's own credibility claim.
178. Yes, integration tests using fake adapters (the `fw_simulator.py`-as-mock-adapter from Q101) so CI validates the framework without needing the real lab.
179. Yes, automated schema/contract tests once OpenAPI exists.
180. Yes, migration tests against the real historical `test_results.db` as a fixture — the only way to be confident Q164 doesn't silently corrupt data.
181. Yes to the full failure-injection list — this is what proves the LAB_FAILED/UNVALIDATED/WORKER_CRASHED distinctions actually work, not just documented.
182. Confirmed, strongly agree: the real 11-test GNS3 suite stays a mandatory acceptance gate for any change touching execution/network behavior. This is your actual regression-proof for the refactor itself.

## AB. Repository / development model

183. Yes, continue committing directly to `main`, no PRs — matches your existing constraint and working style.
184. Yes, one commit per architectural slice — makes `git bisect` useful once the system is more complex, costs nothing extra.
185. Yes, tag stable milestones (`baseline-436026`, `phase-1-complete`, ...) — cheap, gives a hard rollback point.
186. Keep old `/api/...` routes alongside `/api/v1/...` until the Jinja dashboard itself is retired, not until React exists — don't break the current live consumer for a future one.
187. Yes, update docs in the same commit as code — the discipline that produced your excellent existing docs is worth preserving formally.
188. Yes, reports/DBs/PCAPs/logs stay gitignored always, no exceptions — already correctly established.

## AC. The provisioning shell script

189. **C — gradually move provisioning logic into Python services**, shell script becomes a thin launcher over time. The script already duplicates logic (GNS3 API calls, hwsim management, validation) that Phase 2's LabHealthService and Phase 9's DeviceAdapter need to own in Python — leaving it in shell is the same config-triplication problem in code form. Migrate function by function, driven by what each Python service actually needs first (Lab Health needs the hwsim-PHY-check logic first).
190. Yes, Lab Health calls into a shared Python lab-control layer, not the raw script directly — the natural first extraction.
191. Yes, willing to refactor substantially over time — but always incrementally, always re-validated against the 11-test gate (Q182), never a single risky rewrite.
192. Yes, every existing invocation (`--setup-only`, `--repro-test`, `--force-normalize-config`, bare) keeps working throughout — the script becoming a thin launcher means it still accepts the same flags.

## AD. Operational philosophy

193. **Detect → stop → report → operator decides**, as the default. Automatic repair-and-retry is a later, trust-earned capability — a validation product that silently self-heals its own test environment undermines its own "prove what happened" premise.
194. Never-automatic: firmware flash, rollback, device reboot, topology reset, GNS3 project recreation. All irreversible-or-disruptive enough to require an explicit, logged, authorized action, always.
195–196. Yes, every Run captures enough metadata (config snapshot, environment fingerprint, test selection, firmware reference) to support a future `Reproduce Run` operation — build the data capture now, the feature itself later.
197. **No — confirmed, absolute policy.** A validation never returns PASS if required evidence collection failed, even if the assertion nominally succeeded. This is the single most load-bearing answer in the whole document — it's the same rule as DATA_MODEL §16 and PRD §17, now made an unconditional platform policy. `UNVALIDATED` is always the correct outcome instead.

## AE. Data retention / customer boundaries

198–199. **D (defer exact terms)** — but design the schema for it now: retention as a per-plan/contract configurable field (`retain_until`), tenants can request deletion of their own history subject to any contractual hold.
200. Yes, soft-delete for evidence/artifacts — an audit trail that can itself be silently hard-deleted defeats its own purpose. Hard-delete only after a defined grace period.
201. Application-level authorization is sufficient for the Phase 10b MVP; hard DB-level tenant isolation (schema-per-tenant/RLS) only once a specific compliance requirement demands it — don't over-engineer ahead of an actual customer ask.
202. Yes, full project export (history + evidence) should exist — both a trust feature and a practical need (tenants handing evidence to their own auditors).

## AF. Final architectural preference

203. Confirmed, strongly agree: modular monolith through the 1–10b range. No service split until an actual scale/team pain point forces it.
204. **D (leave open)** — if forced, AWS as the safest default (broadest managed Postgres/S3/ECS maturity), but revisit with real cost/ops data rather than deciding from first principles now.
205. Yes, Docker containerization from the start of Phase 10b, even without Kubernetes — nearly free given your existing Docker comfort from the GNS3 lab stack.
206. Yes, Celery workers share the same repo/codebase initially — modular-monolith principle applied to background jobs too.
207. **D (leave open)** — if forced, S3 (or MinIO for local-dev/self-hosted parity), broadest tooling support and no AWS lock-in during development.

---

## BL. Business Logic

**BL-01.** Yes, predefined Validation Profiles (Smoke/Standard/Performance/Full/Custom), selectable at Run creation — same concept as Q20, named for the business layer.
**BL-02.** Yes, per-project release policies, living as Project-level config rather than a global platform rule.
**BL-03.** Yes, `BLOCKING/ADVISORY/INFORMATIONAL` per test. This is what defines "required" in Q25's overall-PASS rule — add `criticality` to the Q17 test-metadata schema.
**BL-04.** Yes to severity, and yes it influences release decisions — but through the BLOCKING/ADVISORY mechanism rather than a second overlapping axis (CRITICAL/HIGH default to BLOCKING, MEDIUM/LOW default to ADVISORY, overridable per project).
**BL-05.** Yes, firmware lifecycle (`DRAFT/UNDER_VALIDATION/VALIDATED/REJECTED/RELEASED/DEPRECATED`) — keep this, the Baseline lifecycle, and the firmware-artifact lifecycle (W-159) conceptually distinct even though related.
**BL-06.** Yes, human approval can sit on top of a technically-passing Run before "VALIDATED"/"RELEASED."
**BL-07.** Yes, multiple baselines per project scoped by hardware revision/region/config/band/SKU — extends Q45's composite identity.
**BL-08.** Automatic selection for the common case (environment/device/config uniquely determines it); explicit operator selection only when genuinely ambiguous.
**BL-09.** Comparable = same hardware, topology/lab-class, test profile, major software versions — not necessarily identical config (BL-10 is a related but distinct question). Compute and display an "environment similarity" flag rather than silently assuming comparability.
**BL-10.** Yes, a config-only change (firmware unchanged) creates a new Run and, if it materially affects tested behavior, a separate baseline lineage.
**BL-11.** Historical Runs retain the old test definition permanently, frozen at execution time — never reinterpret old results under a new test's semantics.
**BL-12.** Yes, tests are versioned (`wifi.throughput v1`/`v2`) — this is what makes BL-11's frozen semantics actually explainable, not just inert.
**BL-13.** Yes, the regression engine refuses automatic comparison across a significant test-version boundary and requires explicit operator acknowledgment.
**BL-14.** Layered, not single-owner: platform defines the catalog → project/profile selects from it → device capability further constrains (BL-16) → operator can override within that envelope.
**BL-15/16.** Yes to both — conditional tests driven by declared device capabilities, and the framework auto-constructs the executable set from those capabilities rather than requiring manual per-device curation.
**BL-17.** `SKIP` (not silent NOT_RUN, not a misleading execute-and-fail) when a prerequisite fails, with the skip reason naming the failed prerequisite explicitly.
**BL-18.** No — do not auto-retry after a recoverable failure and substitute the rerun's result silently. Conflicts directly with Q149's no-silent-retry rule and with BL-23's flaky detection, which needs the raw inconsistent outcomes visible.
**BL-19.** Yes, certain tests require specific evidence types to be PASS-eligible (DHCP→DORA, Auth→EAPOL) — operationalizes the evidence invariant per test.
**BL-20.** Yes, `EVIDENCE_COMPLETE/PARTIAL/INVALID` as an explicit Run-level state — the natural home for the Q120 scenario, generalized.
**BL-21.** Yes, `VALIDATED/VALIDATED_WITH_WARNINGS/REJECTED/UNVALIDATED` as the final business result, explicitly separate from raw technical PASS/FAIL — the "business outcome" axis from the Core Decisions table, now fully named.
**BL-22.** Project-configurable (BL-02), default N=1 (a single validated Run is sufficient), raisable per project.
**BL-23.** Yes, flaky-test auto-detection — a test with inconsistent outcomes under unchanged firmware/config gets flagged `FLAKY` instead of repeatedly reported as regression noise. High-value for earning trust over time; lands naturally after Phase 7.
**BL-24.** Yes, Admin/Owner-role waivers with a required reason field, itself an audit event.
**BL-25.** Default scope: test + firmware-version granularity (the most common real case). Project-wide or time-bound waivers only if a real use case demands it later.

## TC. Technical Clarity

**TC-01.** Combination: Python source for test logic (pytest stays canonical), YAML for parameters/thresholds, DB for the frozen Run-time record of what was actually declared/executed.
**TC-02.** Yes, an explicit `TestRegistry.register(...)`, decorator-based, still discovered normally by pytest underneath — this is what makes metadata, capability-driven selection, and versioning queryable.
**TC-03/04.** Yes to both — a structured `RunContext` (run_id/device/lab/config/logger/artifact_manager/command_runner) injected into every test, replacing ad-hoc fixture access. Standard DI discipline, supports TC-05.
**TC-05.** Yes, eliminate the `ConnectionPool` singleton and other global state now — far cheaper to fix while there's one execution path than to retrofit once concurrent Runs (10b) exist.
**TC-06.** Yes, adopt the proposed service boundaries exactly — clean decomposition, matches the phase-by-phase build order already agreed.
**TC-07.** Yes, typed domain models — dataclasses pre-SQLAlchemy, migrating to SQLAlchemy models once Postgres lands.
**TC-08.** Yes, type hints + static checking (mypy/pyright) in CI from the first Phase 1 commit.
**TC-09.** Yes, canonical JSON serialization independent of DB representation — keeps the API layer and DB layer independently evolvable.
**TC-10/11.** Yes, timezone-aware UTC everywhere internally, local conversion only at the UI boundary (matches your existing rule, now made explicit for new code). Millisecond precision is sufficient — microsecond only if you start correlating against hardware-timestamped captures.
**TC-12/13.** Yes, explicit lifecycle events, persisted (not log-only) — implements TC-25's shared diagnostic contract and BL's audit trail without requiring log-scraping to reconstruct history.
**TC-14.** Idempotent: lab health, artifact registration, firmware verification, baseline creation. Run creation is idempotent with respect to the idempotency key (Q133), not idempotent in the "calling twice does nothing" sense — two genuinely distinct runs is a valid outcome.
**TC-15/16.** Yes, TestResult+metrics+artifact-refs as one atomic commit (matches Q166). Yes, orphaned artifacts get automatically reconciled by a periodic consistency-check job — build this as part of Phase 1, not deferred.
**TC-17.** The Run Orchestrator is the right layer for infra-exception→business-state translation. Adapters raise typed exceptions (TC-18); the orchestrator decides what it means for the Run. Keeping this in one place is what makes the lifecycle semantics consistent.
**TC-18.** Yes, adopt the proposed exception hierarchy exactly — matches the TC-06 service boundaries one-to-one.
**TC-19/20.** Yes, every remote command returns a structured `CommandResult` (exit_code/stdout/stderr/duration/timed_out/host/command_id), with a separate redacted log representation — the concrete implementation of Q91–92.
**TC-21.** Yes, cache device state within one Run's scope — reduces redundant SSH round-trips, safe as long as it's never reused across Runs.
**TC-22.** Local file/DB lock initially (matches Q146); distributed locking only once Phase 11's multi-node deployment makes a single-process lock insufficient.
**TC-23.** Two-tier lock: `DEVICE_EXCLUSIVE` operations (flash/reboot/config change) block everything else on that device; `NETWORK_CONCURRENT`-safe operations (fault injection, capture, performance tests) can coexist with each other.
**TC-24.** Yes, compatibility wrappers for Phase 1 — `insert_result(...)` internally delegates to `RunService.record_test_result(...)`. This is what lets Q14's CLI-compatibility guarantee hold while internals change. Remove the wrapper only once nothing calls the old API.
**TC-25.** Yes, a shared `health()/diagnostics()/capabilities()/version()` contract across Lab Health, adapters, and services — lets the dashboard and future monitoring treat all subsystems uniformly.

---

## What this unlocks

Every phase in the merged refactor plan from our last exchange can now be implemented against a fixed contract instead of an assumption. The one item worth flagging before code starts: **TC-05 (kill the `ConnectionPool` singleton) and Q87 (unify command execution) both touch the same files as Phase 1's `Run` model work** — sequence them together rather than as separate slices, since doing Phase 1 first and then discovering the singleton blocks multi-tenancy later means touching `connector.py` twice.

If you want the next artifact to be the actual `Run`/`TestResult`/`Artifact` SQLAlchemy-or-dataclass schema plus the `conftest.py` fixture rewrite implementing TC-24's compatibility wrapper, that's the cleanest place to start — it's the one piece every other phase depends on.

## N.1 Telemetry implementation boundary

Iteration 14 standardizes the telemetry contract around immutable typed points rather than UI-specific fields. The initial Runner implementation collects RSSI, SNR, channel, frequency, bitrate, PHY mode and available transmit retry/failure counters from read-only `wpa_cli`/`iw` observations.

Every point is labeled `VIRTUAL_WIFI` or `PHYSICAL_WIFI`. The Runner does not emit RF-certification telemetry, and virtual hwsim observations are never promoted to physical RF claims.


## 20A. Iteration 17 implementation decisions

1. SSH/SFTP is the first physical transport because it requires no new infrastructure and matches the existing runner boundary.
2. Linux/GNS3 remains a non-firmware reference device class; OpenWrt is the first concrete firmware-capable specialization.
3. Firmware SHA-256 validation is mandatory when an expected digest is provided. A supplied detached signature must verify.
4. Firmware mutation requires explicit scoped authorization. Uncertain flash state is never automatically retried or rolled back.
5. The fake adapter is the reference hardware-free implementation and covers both success and failure semantics.
6. Multi-device/SKU orchestration remains deferred; one image targets one device in this phase.

## 20B. Iteration 18 CI/release-gate decisions

1. GitHub-hosted CI validates source integrity and hardware-free policy contracts on every push/PR.
2. Real GNS3/mac80211_hwsim execution is dispatch-only on a self-hosted runner labeled netregress-lab; generic CI must not claim lab validation.
3. The release gate defaults to fail-closed for NO_BASELINE, UNVALIDATED, REGRESSION, SOFT_REGRESSION, NEW_FAILURE, missing required tests, invalid required evidence, incomplete Runs and unhealthy labs.
4. Existing pytest node IDs remain protected; regression comparison normalizes them to semantic TestRegistry IDs.