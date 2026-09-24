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
- [x] Final architecture, current-state, roadmap, security, testing and release documentation reconciled.
- [x] Final release-readiness invariants established.

Final release wave:
- Iterations 28–30 are implemented together as one release slice.
- Exactly one final implementation commit is permitted for this wave on main.
