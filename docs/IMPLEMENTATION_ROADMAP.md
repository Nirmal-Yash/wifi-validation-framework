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

Next:
- Iteration 5 — ArtifactService and evidence registry integration.
