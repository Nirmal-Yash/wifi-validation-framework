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
