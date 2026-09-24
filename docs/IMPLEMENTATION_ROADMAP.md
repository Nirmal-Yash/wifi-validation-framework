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
