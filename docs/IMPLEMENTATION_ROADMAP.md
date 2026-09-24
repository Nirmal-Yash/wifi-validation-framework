# NetRegress Implementation Roadmap

## Iteration 1 — Typed Domain Model ✅

Scope:
- [x] Add typed domain enums and entities for Run, Attempt, TestResult, Metric, Sample, Artifact, EnvironmentSnapshot and ConfigSnapshot.
- [x] Encode evidence/PASS and Run/Attempt ownership invariants.
- [x] Add domain unit tests.
- [x] Preserve existing pytest execution and runtime behavior; no legacy callers modified.
- [x] Update agent context.

Verification:
- [x] Python syntax compilation for changed Python files.
- [x] Domain unit tests: 8/8 passed.
- [ ] Real-lab 11/11 gate: not applicable; Iteration 1 does not modify execution/network behavior.

## Iteration 2 — Repository + SQLite Persistence ✅

Scope:
- [x] Add repository Protocol interfaces for Run, Attempt, TestResult, Artifact, Event and Baseline.
- [x] Add normalized SQLite persistence for run-scoped evidence, metrics/samples and snapshots.
- [x] Add additive schema bootstrap with a version marker.
- [x] Preserve legacy SQLite tables/data; no legacy callers modified.
- [x] Add repository round-trip and conflict tests.

Verification:
- [x] Python syntax compilation.
- [x] Repository tests: 6/6 passed.
- [x] Legacy-table preservation verified.
- [ ] Real-lab 11/11 gate: not applicable; execution/network behavior unchanged.

Next:
- Iteration 3 — Run/Attempt lifecycle service and pytest session integration.
