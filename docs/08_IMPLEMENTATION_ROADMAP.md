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

The operational overview reuses the existing SQLite workspace, device, topology/provider-binding, configuration deployment, pipeline/step, Run, artifact and metric sample records. The endpoint is read-only and Project/Lab scoped. Project-wide Lab totals remain stable when a single Lab filter is applied, while `in_scope` and child metrics reflect the selected Lab. Each subsystem has an independent read permission and a stable restricted response shape with null aggregates and withheld provenance. The dashboard shows deployment and pipeline step outcomes and distinct execution-level/step-level recovery counts, latest published topology revisions, historical telemetry/health artifacts, integrity-verified typed Wi-Fi telemetry points with interface/environment provenance, and mean/min/max/latest summaries from valid timestamped Run metric samples. Missing or hash-invalid artifact files do not contribute measurement values. `RUNNING` and `CANCELLING` executions are separate. Provider configuration is distinguished from live health: connection health remains `UNKNOWN`; reachability, live drift, infrastructure state, regressions and provider sync errors remain `UNAVAILABLE` until the platform has the actual scoped observation or comparison source.

The dashboard surfaces Project/Organization/Lab scope, persisted distributions, active Run totals, section freshness, configuration outcomes, evidence counts, measured performance observations and explicit unavailable/restricted states. Backend tests exercise Project/Lab ownership, RBAC for every child domain, aggregation, cancellation/step states, source timestamps and read-only behavior. Frontend tests exercise successful rendering, Project/Lab transitions, no-Project behavior, independent Run-list failure, and overview error/retry. OpenAPI documents the complete GET contract. This checkpoint does not certify live external-provider or physical network health.


## EXP-P03 implementation checkpoint — visual Topology Studio

The completed implementation extends the existing `TopologyStudioService`, Project/Lab profile ownership, immutable revision hashes, GNS3 provider adapter and `TopologyApplyService`. It does not create a parallel topology schema, revision repository or provider controller client.

**Visual authoring:** the categorized palette covers Routers (Cisco/Arista/Juniper/FRR/VyOS), Switches (Cisco/Arista/Open vSwitch), Firewalls (Palo Alto/Linux), Wireless (OpenWrt/hostapd), Servers (Linux/Ubuntu/Docker), Endpoints (Linux/Windows) and Network utilities (NAT/bridge/cloud/network segment). Entries may be dragged onto the canvas or clicked to add logical nodes. Provider template IDs remain a separate mapping step and can be selected from the actual discovered provider catalogue. A deterministic graph-based auto-layout arranges connected components, while pan/zoom/fit, node search, group move, multi-select, copy/paste with fresh logical IDs, delete and bounded undo/redo remain local editor operations.

**Node and link intent:** node inspector covers logical identity, vendor/OS/image, provider template mapping, CPU/memory, management IP/gateway, VLAN, interfaces/adapter/port assignments, configuration profile and opaque Credential Vault reference. Interface definitions include name, adapter/port, mode, IP, VLAN and description. Link inspector covers source/destination node and interface, link type, network segment and VLAN association. All new fields are optional within the existing immutable JSON definition, preserving readability of historical revisions. The canonical backend validates bounds, IP values, duplicate interface ports and link/interface consistency. Credential values are never accepted or stored.

**Validation, revisions and provider operations:** `POST /api/v1/topologies/validate` requires `topology.manage` for the Project and uses the same canonical normalizer/hash as revision creation; it does not write a revision or contact a provider. A logical-only node can be saved and validated before a provider mapping exists, but provider dry-run planning returns a conflict until a valid template is mapped. Saving re-validates and creates a new immutable DRAFT revision; publication remains explicit and separate. Provider binding/catalogue inspection, dry-run, reconciliation, start/stop, confirmed apply and history remain in the bottom operational console with existing capability/RBAC checks, read-back, resource lock, idempotency and the revision SHA-256 confirmation boundary.

**Observed-only data:** provider resource IDs and node/link operational state are populated only from the existing mapping records and actual provider catalogue/reconciliation responses. Missing observations display as unknown/unmapped; no template or link status is guessed. The console tabs are Validation, Provider operations, Logs, Apply history, Reconciliation and Warnings; session Logs are explicitly not represented as persistent Audit history.

**Verification:** backend tests cover optional structured node/link fields, invalid CPU/memory/IP/VLAN/interface/link combinations, persisted logical-only revisions, provider-plan rejection for missing templates, actual logical-to-provider node/link mappings and unchanged apply safety. Frontend tests cover categorized palette, click/drag-add, auto-layout, interface editing/port-to-port linking, node/link inspectors, six console tabs, read-only viewers, multi-select/history/clipboard and viewport bounds. OpenAPI documents the typed JSON contract. Hosted exact-commit CI passed on PR head `e1e4519278e84015c96af10c22961764338adf84` in run `45022564639` on 2026-11-22: backend correctness/reliability, frontend tests/production build, and dashboard startup/session smoke all PASS. The software implementation is CI-verified; interactive desktop/assistive-technology and real GNS3 apply/recovery tests remain separate operator acceptance gates (RQ-042/RQ-044).


## EXP-P04 implementation checkpoint — common provider contract and capability registry

**Contract and capabilities:** A shared structural `ProviderAdapter` contract now defines controller-version, project/template discovery, node/link inventory, node/link creation and explicit node lifecycle operations. Stable `ProviderCapability` identifiers are maintained by an explicit `CapabilityRegistry`; `ProviderRegistry` owns adapter factories, descriptor discovery, structural conformance checks and typed unsupported-capability failures. The registry is instance-scoped rather than process-global. GNS3 is the only registered provider in this phase and remains the reference implementation.

**Connection records:** P04 reuses existing `gns3_lab_bindings` Project/Lab-scoped persistence and its Vault-reference, status, foreign-key, audit and no-delete constraints. `ProviderConnectionRecord` is a provider-neutral projection of that record (provider ID, endpoint, provider workspace ID, controller Device, opaque Credential Vault reference and lifecycle metadata). It never contains a password, token or secret value. No parallel connection table or database migration is introduced.

**Integration and API:** `TopologyApplyService` constructs the existing GNS3 client through the common registry, checks declared discovery/mutation capabilities, and retains the existing Vault `use_secret` boundary, Lab lock, immutable apply history, explicit revision-hash confirmation, idempotency, actual provider read-back and reconciliation/recovery behavior. Existing GNS3 binding/catalogue/apply APIs remain compatible; catalogue responses add provider descriptor and safe connection metadata. `GET /api/v1/providers/registry?project_id=...` is Project-scoped under `topology.read` and strictly read-only; it does not contact a controller or infer live health. OpenAPI documents the route.

**Verification boundary:** Contract/unit tests and the existing mocked GNS3 topology lifecycle/regression tests cover adapter conformance, capability enforcement, connection projection, and preserved apply/reconciliation behavior. Hosted exact-commit CI is the automated software gate. These tests do not claim that a live GNS3 controller was contacted or that physical/network lab acceptance occurred; RQ-042 remains an external operator gate. CML/EVE-NG adapters are not registered or claimed in P04. Exact hosted verification: quality workflow [45028046927](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45028046927) on commit `13fd8df0d5326a1fe34adff65938c076eeabc5c0` completed successfully with all three jobs PASS. Backend correctness: 584 passed, 7 skipped; repeated locking/process/recovery reliability: 108 passed. Frontend tests/build and dashboard startup/session smoke also PASS.
