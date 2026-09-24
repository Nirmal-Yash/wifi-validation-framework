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

Next:
- Iteration 2 — Repository interfaces and SQLite persistence adapters.
