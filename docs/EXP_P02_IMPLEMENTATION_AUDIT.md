# EXP-P02 — Operational Overview Implementation Audit

## Repository and phase context

- Repository: `Nirmal-Yash/wifi-validation-framework`
- Required predecessor: P01 unified design system and application shell
- Phase: P02 — Operational Overview Dashboard
- Delivery model: additive read-only query contract, shared shell, existing SQLite/Alembic schema and existing API/RBAC.
- AI/LLM/agent functionality: excluded from this implementation programme.

## Existing implementation retained

- Existing `DashboardQueryService` and versioned Flask API.
- Existing Organization/Project/Lab workspace context and dashboard React route.
- Existing topology profile/revision/apply schema and provider binding records.
- Existing configuration deployment history.
- Existing PipelineService execution and step history.
- Existing typed `WifiTelemetrySnapshot` artifacts and artifact integrity verification.
- Existing Run/Attempt/TestResult/Metric/Sample/Evidence storage.
- Existing identity permission registry and Project-scoped RBAC.

No new tables or migrations are required. The read model uses existing persisted sources only.

## API contract

`GET /api/v1/dashboard/operations-overview?project_id=<project-id>&lab_id=<optional-lab-id>`

The caller must have `workspace.read` for the Project. A selected Lab must belong to that Project. Project-wide `labs.total` is preserved under Lab filtering; `in_scope` and child summaries reflect the Lab filter.

Each subsystem is checked independently:
- `devices.read`
- `topology.read`
- `pipelines.read`
- `runs.read`
- `configurations.read`
- `evidence.read`
- `performance.read`

A restricted section returns `access=RESTRICTED`, null aggregate and distribution fields, and withheld source/freshness fields. Other authorized sections remain visible. Topology denial also removes provider identifiers and topology version values from Lab summaries.

## Persisted data surfaced

| Dashboard section | Existing source | Shown data |
|---|---|---|
| Organization / Project / Lab | `organizations`, `projects`, `labs` | Current scope, Project-wide Lab total, selected-scope Lab count and lifecycle distribution |
| Devices | `devices` | Total, active, archived and status distribution |
| Topology | `topology_profiles`, `topology_revisions`, `topology_apply_records` | Profile/revision/apply totals and distributions, latest published revisions |
| Provider | `labs`, `gns3_lab_bindings` | Provider identity, saved binding state, binding provenance |
| Pipelines | `pipeline_definitions`, `pipeline_executions`, `pipeline_steps` | Definition and execution status distributions; QUEUED, RUNNING, CANCELLING and recovery-required; step status and recovery counts |
| Runs | `runs` | Lifecycle and business-outcome distributions, persisted active total |
| Configuration deployment | `device_configuration_deployments` | Deployment totals/statuses and latest deployment identity/outcome |
| Evidence | `artifacts`, `runs` and existing artifact read/verification boundary | Non-deleted TELEMETRY and LAB_HEALTH_SNAPSHOT counts; integrity-verified numeric Wi-Fi points grouped by metric/unit/interface with sample count, mean/min/max/latest, timestamp, interface and environment provenance |
| Performance | `runs`, `attempts`, `test_results`, `metrics`, `samples` | Mean/min/max/latest metric sample per name/unit from latest Run attempt; valid, finite, non-warmup, non-retried samples with an actual capture timestamp; sample count, unit and source Run/test identity |
| Action items | Topology apply, configuration deployment and pipeline execution sources | Failed/partial apply and deployment counts, separate recovery-required pipeline execution and step counts (not conflated or double-counted) |

## Truthful unavailability rules

The following are not inferred from persisted configuration or historical activity:

- Provider health: `UNKNOWN` until a real authorized probe result is persisted.
- Device reachability: `UNAVAILABLE` until an actual Project/Lab probe is persisted.
- Configuration drift: `UNAVAILABLE` until desired-versus-observed configuration state is compared and persisted.
- Infrastructure resource state: `UNAVAILABLE` until OpenTofu/provider inventory observations exist.
- Blocking regression totals: `UNAVAILABLE` until an explicit baseline/current Run comparison is performed.
- Provider synchronization errors: `UNAVAILABLE` until a separate current synchronization observation is recorded.
- Performance: `UNAVAILABLE` when no valid, finite, timestamped sample exists; no default or fabricated value is supplied.
- Wi-Fi telemetry points are included only when the associated artifact exists beneath the approved results root and its stored SHA-256 matches the bytes read. Invalid, missing or malformed artifacts do not contribute sample values.

Configuration deployment history is not a live drift check. A saved provider binding is not a connectivity check. A query observation timestamp is not a provider-health timestamp.

## Frontend completion

The Network Operations panel consumes the same versioned API and shared Project/Lab workspace context. It now presents:
- Organization, Project, selected Lab and Project-wide Lab totals.
- Device, topology, pipeline execution and pipeline step distributions.
- Latest published topology revisions and provider binding provenance.
- Configuration deployment outcomes and latest deployment.
- Persisted telemetry/lab-health artifact counts.
- Valid timestamped performance samples with their units and Run/test provenance.
- Network health availability and action-item states.
- Independent Run-list loading/error/retry behavior; the Run-list request is Project-scoped and is not allowed to block the operations overview.
- Explicit restricted, empty and unavailable states.

No Run request is made until a Project is selected. Query dependencies include active Project and Lab so changing scope causes a new data read.

## Tests added or extended

Backend:
- Persisted aggregation for configuration deployments, topology applies, pipeline steps, Runs, evidence and real metric samples.
- Integrity-verified Wi-Fi telemetry artifact parsing, typed points, units, interface/environment provenance and group summaries; missing/corrupt artifact content is ignored as measurement evidence.
- Stable null aggregates and source withholding for all restricted sections.
- Independent Project-scoped RBAC including `runs.read`, `configurations.read`, `evidence.read` and `performance.read`.
- Read-only row-count invariance and consistent observation timestamps.
- Existing membership, Lab ownership, authentication, provider redaction and Run lifecycle tests retained.

Frontend:
- Render all new persisted sections and source values.
- Project/Lab transition triggers the corresponding scoped overview/Run requests.
- No Project means no unscoped Run query.
- Run-list error does not hide the operations view.
- Restricted sections do not render missing aggregates as zero.
- Existing loading/error/retry and provider-health truthfulness assertions retained.

Contract/docs:
- OpenAPI entry for the versioned endpoint, required/optional query parameters, access semantics and error responses.
- Architecture/API contract and implementation roadmap updated.
- RQ-034 remains `IN_PROGRESS` until exact-commit verification evidence is recorded.

## Acceptance state

Source and test changes are prepared for consolidated phase review. P02 is not accepted solely because code or tests have been authored. The exact feature commit must pass the complete relevant hosted backend, frontend and build workflows. A red quality gate blocks merge. Manual viewport/keyboard review and live provider/physical lab qualification remain separate; this phase does not claim those external tests have been performed.
