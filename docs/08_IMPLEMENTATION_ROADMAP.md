# NetRegress Product Expansion — Implementation Roadmap

**Baseline:** `3b8e5504b3824401a22e774ff1e37b2b253474a6`  
**Programme:** Product expansion P00–P17 (called **EXP-P00–EXP-P17** in this repository to distinguish it from historical/Stage D phases that already use P00/P17–P37 names).

This is an additive programme layered over the existing Runner implementation. It does not replace the canonical B–P, Stage D P17–P24, Stage E P25–P29 or Stage F P30–P37 records in `01_DEVELOPMENT_PLAN_AND_ROADMAP.md`.

## Stage A — Product foundation and frontend

| Expansion phase | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| EXP-P00 | Requirements, repository baseline and architecture freeze | Current main and canonical docs | Inventory, approved decisions, requirement traceability and exact baseline |
| EXP-P01 | Unified design system and application shell | EXP-P00 | Existing routes work in the shared shell; tokens/theme/accessibility tests pass |
| EXP-P02 | Operational overview dashboard | EXP-P00, dashboard query/API contracts | Real Project/Lab/provider/device/pipeline/run metrics with provenance and RBAC |
| EXP-P03 | Complete visual Topology Studio over the existing canonical profile/revision domain | EXP-P00; provider actions remain aligned with EXP-P04/05 | Accessible node/link selection and inspectors; multi-select/group movement; undo/redo; copy/paste with logical-ID remapping; keyboard actions; canonical backend validation; immutable revision save/publish; read-only plan, reconciliation and explicit confirmed apply; Project RBAC and integration tests |

## Stage B — Topology and emulator providers

| Expansion phase | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| EXP-P04 | Common provider contract and capability registry | EXP-P00 | Contract tests and provider connection records; GNS3 passes |
| EXP-P05 | GNS3 consolidation behind the common contract | EXP-P04 | Existing mappings, apply, reconciliation and recovery regressions pass |
| EXP-P06 | Cisco Modeling Labs adapter | EXP-P04/05 | Authenticated catalog, lab/node lifecycle, topology translation and read-back |
| EXP-P07-A | EVE-NG adapter | EXP-P04/05 | Independent EVE-NG capability and lifecycle contract tests |
| EXP-P07-B | Packet Tracer compatibility bridge | Canonical topology/import schema | Provenance-preserving import/export subset and incompatibility report |

## Stage C — Multi-vendor network engineering

| Expansion phase | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| EXP-P08 | Canonical network intent and device capability model | EXP-P04; existing device/topology domains | Versioned vendor-neutral intent; unsupported features fail validation |
| EXP-P09-A | Linux and FRR configuration adapter | EXP-P08 | Intent validation, config diff, apply fixture and observed-state tests |
| EXP-P09-B | Cisco IOS/IOS-XE adapter | EXP-P08 | Platform/version-gated interfaces, VLAN, routes, OSPF/BGP and ACLs |
| EXP-P09-C | Arista EOS adapter | EXP-P08 | Platform/version-gated configuration and read-back tests |
| EXP-P09-D | Juniper Junos adapter | EXP-P08 | Hierarchical config and candidate/commit-check workflow where supported |
| EXP-P09-E | Palo Alto PAN-OS adapter | EXP-P08 | Zones, virtual routers, objects, security/NAT policy and verification |
| EXP-P10 | Ansible configuration automation | EXP-P08/09 | Scoped inventory, playbook validation, preview, approval, execution and read-back |

## Stage D — Infrastructure automation

| Expansion phase | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| EXP-P11 | OpenTofu workspaces and infrastructure automation | EXP-P04 | Isolated workspace, validate/plan/review/approve/apply/inspect/destroy tests |
| EXP-P12 | Infrastructure-resource lifecycle integration | EXP-P11 and existing Lab/topology domains | Resource mapping, drift, orphan detection and partial recovery |

## Stage E — Workflow and observability

| Expansion phase | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| EXP-P13 | Visual pipeline builder | Existing PipelineService and approved handler contracts | Visual draft/publish/execute/monitor/recover with no inert steps |
| EXP-P14 | Network observability and telemetry | Provider/device metric contracts | Provenance-aware metrics, packet capture and protocol evidence |
| EXP-P15 | Operations dashboard and evidence integration | EXP-P02, P13, P14 | Issue-to-device/provider/pipeline/evidence drill-down |

## Stage F — Qualification and release

| Expansion phase | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| EXP-P16 | Integrated end-to-end verification | All functional phases | Full workflow and failure/recovery matrix with provider/version declarations |
| EXP-P17 | Security, packaging, documentation and release certification | EXP-P16 | Secure, installable release with verified test/evidence and licence manifest |

## Dependency and parallel execution

- After EXP-P00, EXP-P01, EXP-P02 and EXP-P03 may proceed as separate workstreams. EXP-P02 backend aggregation must use real APIs; EXP-P03 provider-specific controls remain bounded by EXP-P04/05 contracts.
- EXP-P04 provider contract can proceed independently of EXP-P01/P02. EXP-P05 must wrap the current GNS3 implementation, not duplicate it.
- EXP-P08 model design may proceed while provider capability contracts are refined, but adapter implementation must use the approved capability schema.
- EXP-P11 infrastructure design can proceed after the provider/resource contract is stable. Do not let Ansible and OpenTofu own the same lifecycle.
- EXP-P13 canvas primitives can progress in parallel with handler implementation. A node is executable only after a tested backend handler is registered.
- EXP-P16/P17 begin only after functional workflows and recovery paths are present.

## Implementation chunk contract

Every phase is delivered in four work packages (combine for a genuinely small phase):

1. **Specification:** objective, current code to reuse, files, dependencies, business rules, data/API contracts and security boundaries.
2. **Backend:** model/service/migration/API/validation and focused unit/contract tests.
3. **Frontend:** real API integration, authorization-aware controls, inspector, loading/error/empty states and accessibility.
4. **Integration:** E2E/regression tests, exact acceptance evidence, documentation and review.

Every work item must specify objective, current state, file scope, dependencies, behavior, data model, API contract, frontend state, security, tests, acceptance criteria and docs. Scope expansion requires an explicit decision, not silent drift.

## Definition of Done

- Requirements and business logic are implemented.
- Additive migration exists only when persisted state is required.
- API request/response, authorization and typed error behavior are documented.
- Credential handling and state-changing boundaries are tested.
- Frontend uses real API data and handles loading/error/empty/permission states.
- Unit, integration, existing regression and applicable E2E tests pass.
- Existing Wi-Fi Run/evidence/GNS3 tests remain green.
- End-to-end workflow is verified against the declared environment class.
- Documentation and requirement traceability are updated.
- No unresolved critical defects remain.

## Git and release controls

Follow the current repository's `docs/AGENT_CONTEXT.md`: integrate on the established `main` branch using the repository's single-main-branch discipline, small logical commits and fast-forward-only updates. Never rewrite history or force-push. Do not commit credentials, database files, private keys, OpenTofu state, PCAPs or generated runtime artifacts. Do not mark mocked-provider tests as real provider acceptance.


## EXP-P02 implementation checkpoint — operational overview

The operational overview reuses the existing SQLite workspace, device, topology/provider-binding, configuration deployment, pipeline/step, Run, artifact and metric sample records. The endpoint is read-only and Project/Lab scoped. Project-wide Lab totals remain stable when a single Lab filter is applied, while `in_scope` and child metrics reflect the selected Lab. Each subsystem has an independent read permission and a stable restricted response shape with null aggregates and withheld provenance. The dashboard shows deployment and pipeline step outcomes, latest published topology revisions, historical telemetry/health artifacts, integrity-verified typed Wi-Fi telemetry points with interface/environment provenance, and mean/min/max/latest summaries from valid timestamped Run metric samples. Missing or hash-invalid artifact files do not contribute measurement values. `RUNNING` and `CANCELLING` executions are separate. Provider configuration is distinguished from live health: connection health remains `UNKNOWN`; reachability, live drift, infrastructure state, regressions and provider sync errors remain `UNAVAILABLE` until the platform has the actual scoped observation or comparison source.

The dashboard surfaces Project/Organization/Lab scope, persisted distributions, active Run totals, section freshness, configuration outcomes, evidence counts, measured performance observations and explicit unavailable/restricted states. Backend tests exercise Project/Lab ownership, RBAC for every child domain, aggregation, cancellation/step states, source timestamps and read-only behavior. Frontend tests exercise successful rendering, Project/Lab transitions, no-Project behavior, independent Run-list failure, and overview error/retry. OpenAPI documents the complete GET contract. This checkpoint does not certify live external-provider or physical network health.


## EXP-P03 implementation checkpoint — visual Topology Studio

The visual editor reuses `TopologyStudioService`, the existing Project/Lab profile ownership rules, canonical topology definition, immutable revision hashes and provider-apply service. No parallel topology schema, revision store or provider controller client is introduced.

**Local editing workflow:** select a profile and revision; add, inspect, rename, reposition and remove logical nodes; select one or multiple nodes; move a selected group together; add, select, edit and remove adapter/port links; search nodes; pan, zoom and fit the canvas; select all; copy/paste a selection with fresh logical IDs and remapped internal links; delete a selection; undo/redo local editing commands. History is in-memory and bounded; changing Project/profile/revision resets the working history and selection.

**Canonical validation:** `POST /api/v1/topologies/validate` authorizes `topology.manage` for the Project and invokes the same canonical normalizer/hash function used by immutable revision creation. It is read-only: it returns canonical node/link counts and the SHA-256 digest without writing a revision, changing a provider or making a controller request. Invalid definitions return `422 INVALID_TOPOLOGY`; an optional profile must be active and belong to the supplied Project.

**Revision and provider boundaries:** saving validates again before creating a new immutable DRAFT revision. Publishing remains an explicit action permitted only for a DRAFT revision. Provider binding/catalogue inspection, dry-run planning, reconciliation, apply history and node start/stop retain their existing capability/RBAC gates. A plan does not mutate GNS3. Apply is possible only for a published Lab-scoped revision, after a conflict-free dry-run and explicit user confirmation bound to the planned revision hash. No provider operation is triggered by canvas editing, validation, revision creation or publishing.

**Verification included:** canonical helper tests for group movement, bounded undo/redo, copy/paste ID remapping, connected-link handling and delete behavior; backend tests for validation hash, read-only behavior, port-conflict errors, Project scope and RBAC; frontend tests for accessible canvas controls, selection, keyboard commands, link editing, validation/save and read-only viewer behavior; OpenAPI route coverage. Hosted exact-commit verification and operator review remain required before marking the phase ACCEPTED.
