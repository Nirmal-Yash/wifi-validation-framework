# EXP-P13 — Pipeline DAG authoring and conditional execution

## Objective

Extend the durable Project/Lab pipeline engine from a fixed ordered list into an immutable directed acyclic graph (DAG). Provide a visual graph editor while retaining revision hashes, worker leases, step attempts, Run ownership, provider safety, bounded retry/cancellation and operator-reviewed recovery.

## Delivered

- `PipelineService.normalize_definition` validates unique step keys, dependency references, duplicate/self edges, supported edge outcomes and cycles. Forward references are supported.
- Historical definitions which omit `depends_on` retain their previous sequential dependency (`SUCCESS` on the prior step). An explicit empty dependency array is a true independent root. Invalid or null dependency values are rejected.
- The supported conditions are `SUCCESS`, `FAILURE` and `COMPLETED`. Multiple incoming dependencies use AND semantics.
- The existing immutable Pipeline revision JSON and persisted execution/step/attempt tables remain the source of truth; no parallel graph database or duplicate scheduler was added.
- The durable worker resolves conditional branches, records unmatched branches as `SKIPPED`, and executes only dependency-ready work. A successful failure-handling branch does not erase the originating failure.
- `RECOVERY_REQUIRED` halts the entire graph, including independent roots. Resumption remains subject to the existing explicit recovery operation.
- The Pipeline page now contains a deterministic layered node-and-edge editor with node selection, operation type/input, timeout, attempts, dependency checkboxes and edge-condition selectors. The backend remains authoritative for graph and operation validation.
- The existing Pipeline lifecycle remains connected to the same revisions and executions: create/edit draft revisions, publish immutable revisions, enqueue execution, monitor persisted execution/step/attempt state, and use the existing cancellation and explicit recovery controls. The graph editor replaces only the authoring surface; it does not introduce a separate execution path.
- Frontend graph utility tests and backend graph validation/worker tests cover legacy sequential definitions, independent roots, forward references, success/failure/completed paths, invalid edges, cycle rejection and recovery halt.

## Compatibility and safety decisions

- Existing persisted revisions without dependency metadata remain executable using historical sequential semantics.
- No arbitrary shell, command, script or user-authored execution node was added.
- The operation type allow-list, typed operation inputs, opaque credential references and explicit confirmation controls remain unchanged.
- No automatic retry was added for state-changing provider actions or validation Runs.
- The worker remains single-step-per-invocation; P13 does not claim concurrent fan-out or distributed graph scheduling.
- Graph visualization is a presentation layer; it does not bypass publication checks, resource locks, Project/Lab scope, command security or recovery requirements.

## Verification scope

- Backend: `tests/test_pipeline_orchestration.py` and existing `tests/test_pipeline_runtime.py`.
- Frontend: `frontend/src/test/pipeline-graph.test.js`, pipeline management tests and production build.
- Exact-head quality checks run after P13 and P14 are integrated together.
- Provider/controller, live Lab and physical Wi-Fi acceptance remain operator-owned.

## Files

- `lib/services/pipeline_service.py`
- `frontend/src/pipeline-graph.js`
- `frontend/src/components/pipeline-graph-editor.jsx`
- `frontend/src/pages/pipelines.jsx`
- `frontend/src/styles.css`
- `tests/test_pipeline_orchestration.py`
- `frontend/src/test/pipeline-graph.test.js`

**Status at source checkpoint:** implementation is assigned to the P13 commit. CI verification is intentionally deferred until the P14 commit is integrated.
