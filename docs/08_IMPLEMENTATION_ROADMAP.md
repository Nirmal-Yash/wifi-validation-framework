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
| EXP-P09-A | Linux and FRR configuration compiler | EXP-P08 | Deterministic systemd-networkd, FRR and nftables preview fixtures; explicit unsupported diagnostics; no configuration apply |
| EXP-P09-B | Cisco IOS/IOS-XE configuration compiler | EXP-P08 | Platform/version-gated routed/switchport interfaces, VLANs, routes, OSPF/OSPFv3, BGP, LACP and zone-firewall previews |
| EXP-P09-C | Arista EOS configuration compiler | EXP-P08 | EOS-native interface, VLAN, route, OSPFv4, BGP and LACP previews; unsupported zone firewall/OSPFv3 blocked |
| EXP-P09-D | Juniper Junos configuration compiler | EXP-P08 | Hierarchical set previews, IPv4/IPv6 RIB, OSPF/OSPFv3, BGP/LACP and SRX-scoped security; live candidate/commit-check deferred |
| EXP-P09-E | Palo Alto PAN-OS configuration compiler | EXP-P08 | Routed interfaces, IPv4/IPv6 static routes, OSPFv4/BGP/LACP, zones and security policy previews; unsupported L2/NAT semantics blocked or deferred |
| EXP-P10 | Ansible configuration automation | EXP-P08/09 | Published revision → deterministic compiler artifacts → Project/Lab/Device-scoped static inventory → syntax/collection validation → independent plan-hash approval → bounded execution → per-Device read-back and immutable audit evidence; stale plans and partial failures block automatic retry. Initial live transport: Linux/FRR SSH, IOS/IOS-XE and EOS network_cli; Junos/PAN-OS remain compile-only. |

## Stage G — Universal native vendor interoperability

**Programme extension:** G01–G12 is a major, additive interoperability stage. It extends EXP-P00–EXP-P17; it does not renumber, replace or silently redefine the existing Stage A–F phases. Stage G owns native project-file interoperability, vendor-native topology presentation and cross-format conversion. Existing provider adapters continue to own live controller operations.

| Package | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| G01 | Comprehensive P06–P10 implementation audit and gap register | Current main; source, migrations, APIs, frontend, tests and current exact-commit CI | Source-backed gap register; verified P06–P10 status; protected boundaries and external acceptance gates; next task selected. **Audit: SPECIFICATION_COMPLETE** in docs/STAGE_G_NATIVE_INTEROPERABILITY_AUDIT.md. |
| G02 | Extended native topology data model | G01; existing TopologyStudioService and immutable revisions | **Implementation integrated; exact-head quality verification pending.** Additive schema v30 / Alembic 20261124_20, immutable presentation revisions, generic source/asset provenance, bounded namespaced extensions, Project/Profile/topology hash binding, authorized idempotent presentation APIs, Topology Studio snapshot/viewport controls and migration/service/API regressions. Detailed audit: docs/STAGE_G_G02_PRESENTATION_MODEL_AUDIT.md. Native format codecs and full native renderer are subsequent G03–G08 packages. |
| G03 | Native format interoperability framework | G02 | Independent codec contracts/registry for detect, version, parse, validate, semantic/presentation extraction, asset resolution, canonical mapping, serialization, compatibility reports and codec round-trip verification; safe bounded parsing and typed diagnostics. |
| G04 | GNS3 native project interoperability | G02/G03; representative .gns3 files and associated assets | Native import, reconstruction, editing, export, provenance, asset manifest, reopen in declared GNS3 version and semantic/presentation round-trip report. Existing GNS3 provider and Wi-Fi paths remain unchanged. |
| G05 | Cisco Modeling Labs native interoperability | G02/G03; documented CML YAML versions and representative CML environment | YAML and supported legacy VIRL detection/import/export; node definitions, images, interfaces, links, annotations/layout mapping; exact-version validation and CML reopen report. |
| G06 | EVE-NG native interoperability | G02/G03; representative .unl projects and required assets | Safe file-level .unl parse/serialize, native identifiers, templates/images, nodes/interfaces/bridges/links/layout; Community/Professional differences and EVE reopen evidence. |
| G07 | Packet Tracer native interoperability expansion | Existing P07-B codec and provenance; G02/G03 | Extend beyond name/coordinate edits only where pktlib/native structure permits; broaden devices/ports/configuration/drawings/notes; retain exact unsupported-change diagnostics; version matrix and Packet Tracer desktop reopen tests. |
| G08 | Universal topology rendering and placement engine | G02; codec presentation mappings | Format-aware coordinate transforms, canvas/view state, node and port geometry, link routes, labels, icons/assets, annotations, drawings, layers and visibility; native placement preserved; auto-layout remains explicit. |
| G09 | Cross-vendor topology translation | G03–G08; provider capability/template catalogues | Bidirectional supported conversions and per-object mappings; actual missing-image/interface checks; unsupported/manual-map warnings; semantic, configuration, asset and presentation loss report; no false equivalence claims. |
| G10 | Advanced native vendor configuration | P08/P09; exact platform/version capability observations | Separate versioned vendor-native configuration path for advanced interface/routing/policy/VRF/security/NAT/API/CLI features; common intent remains portable and no unsupported semantics are silently dropped. |
| G11 | Extensible full-capability execution engine | P10; G10 transports; existing Vault, RBAC, audit, lock and recovery services | Configurable execution profiles; supported user playbooks, roles, collections, custom modules/runtimes and native operations; SSH/NETCONF/RESTCONF/HTTPS transports where qualified; validation, execution, verification and persistent evidence; policy-driven approvals without security bypass. |
| G12 | Unified reconciliation, recovery and evidence | G02–G11 and existing Run/artifact/audit/recovery services | Source provenance, import/export/conversion history, immutable config snapshots, actual provider observations, drift, asset integrity, partial-failure recovery, evidence hashes and restart-safe reconciliation. |

### Stage G sequencing and dependency rules

- G01 is the mandatory audit baseline and must precede implementation.
- G02 establishes the shared presentation/provenance model. G03 consumes it; native codecs must not create format-specific parallel topology databases.
- G04–G07 are independent codec implementations only after G03 contracts and representative fixture strategy are stable. A codec may expose a partial support matrix; it must not claim universal fidelity.
- G08 consumes the native presentation model and codec mappings. It must not auto-layout an imported topology on import.
- G09 depends on codecs, canonical mapping and rendering metadata. Each conversion reports semantic, configuration, asset and presentation losses.
- G10 extends P08/P09 without forcing every advanced vendor feature into the portable schema.
- G11 extends P10; it must retain authentication, scoped authorization, Vault-only secrets, audit, process supervision, host identity checks and resource locking.
- G12 integrates the existing persistence/evidence owners. It must not duplicate Run, Artifact, Pipeline or provider state ownership.
- Stage D–F EXP-P11–EXP-P17 remain in the roadmap. G10/G11 may proceed in parallel only where their dependencies and execution ownership are explicit; release qualification must cover the full integrated workflow.
- AI/LLM/agent/model integration remains excluded from this implementation programme.

### Stage G implementation package contract

Each G package uses the four existing delivery packages: **A — Specification**, **B — Backend**, **C — Frontend**, **D — Integration and acceptance**. Every package records the exact source baseline, files/services to reuse, persistence/API contracts, Project/Lab authorization, failure/recovery behavior, representative native fixtures, test results, limitations and documentation/traceability updates.

A native format is not accepted merely because detection or parsing succeeds. Acceptance requires representative native sources, explicit version support, the full set of claimed semantic objects, presentation extraction, bounded asset handling, serialization, round-trip comparison, reopening in the originating application and documented losses. When external application or licensed environment access is unavailable, finish independent software work and retain the external gate as pending.

## Stage D — Infrastructure automation

| Expansion phase | Scope | Dependencies | Exit evidence |
|---|---|---|---|
| EXP-P11 | OpenTofu workspaces and infrastructure automation | EXP-P04 | Isolated workspace, validate/plan/review/approve/apply/inspect/destroy tests; source checkpoint documented in docs/EXP_P11_OPENTOFU_IMPLEMENTATION_AUDIT.md; exact CI deferred until P12 |
| EXP-P12 | Infrastructure-resource lifecycle integration | EXP-P11 and existing Lab/topology domains | Resource mapping, drift, orphan detection and partial recovery — source checkpoint documented in docs/EXP_P12_INFRASTRUCTURE_RESOURCE_LIFECYCLE_AUDIT.md; final CI deferred until integrated P12 commit |

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

**Contract and capabilities:** The structural `ProviderAdapter` contract now covers connect/disconnect, health checks, capability reporting, project discovery, lab create/delete, template discovery, node create/delete/start/stop/state, link create/delete, interface discovery, observed-topology retrieval and packet-capture capability reporting. `CapabilityRegistry` maintains stable operation IDs with mutation and explicit-confirmation metadata; `ProviderRegistry` is instance-scoped, verifies every required adapter method and rejects unknown providers/capabilities with typed errors. GNS3 is the sole registered reference adapter for P04.

**Connection records:** P04 reuses existing `gns3_lab_bindings` Project/Lab-scoped persistence. `ProviderConnectionRecord` is a provider-neutral projection with provider ID, endpoint, provider workspace ID, controller Device, opaque Credential Vault reference and lifecycle metadata. It never contains a password, token or secret value. Existing binding persistence remains the single source of truth; no parallel connection table or migration is introduced.

**GNS3 adapter and integration:** The existing bounded REST client implements the complete common method contract using the documented GNS3 Controller API. `TopologyApplyService` establishes/closes the adapter lifecycle inside the Vault callback and consumes actual nodes/links through `get_observed_topology()`. Existing Lab locking, immutable apply history, revision-hash confirmation, idempotency, read-back, reconciliation and uncertain-operation recovery remain authoritative. Existing binding/catalogue/apply APIs remain compatible; `GET /api/v1/providers/registry?project_id=...` stays Project-scoped and read-only.

**Verification boundary:** A deterministic HTTP fixture exercises all adapter methods without contacting a live controller. The provider contract module is explicitly included in hosted quality-gates tests. This does not certify live GNS3, CML, EVE-NG, Packet Tracer or physical-lab operations; RQ-042 and provider-specific operator gates remain separate. Provider binding metadata is never treated as a health observation.



## EXP-P05 implementation checkpoint — GNS3 consolidation behind the common contract

**Single implementation and session ownership:** `lib/services/gns3_provider.py` remains the only GNS3 HTTP adapter. `ProviderSessionService` is the shared Vault-to-adapter boundary used by `TopologyApplyService` and the protected `WiFiLabProvisioningService`; the dashboard and pipeline runtime inject the same application-scoped `ProviderRegistry` and session service. Adapter construction happens only inside `CredentialVaultService.use_secret`, and connect/disconnect are paired even when a callback fails. No provider secret is placed in a binding projection, plan, interface response or audit record.

**Observed catalogue and readiness:** the GNS3 template projection is extended only with explicit template/compute/image metadata. `GET /v2/computes` is projected into bounded compute identity, connected state and valid CPU/RAM utilization percentages; hostnames and provider diagnostic strings are not exposed. For templates referenced by a published revision, the adapter reads the template detail and assigned compute's emulator image catalogue. Built-in templates report `NOT_REQUIRED`; an unavailable catalogue entry, unsupported emulator, missing compute assignment or incomplete image declaration remains `UNAVAILABLE`/`UNKNOWN` rather than being guessed. Confirmed missing images or an explicitly disconnected assigned compute block creation of that node, while already observed mapped nodes remain manageable. Apply repeats the readiness observation immediately before mutation.

**Topology operations:** dry-run plans return template/compute/image compatibility, provider compute observations and actual node lifecycle counts alongside the existing node/link plan and conflict report. `GET /api/v1/labs/{lab_id}/provider-nodes/{provider_node_id}/interfaces` verifies the node is part of the bound controller project and returns its actual adapter/port inventory. Provider project choices come from the observed catalogue after the initial binding is established. Existing mappings, safe resource adoption, immutable revisions, SHA-256 confirmation, Lab lease, apply history, actual read-back, reconciliation, partial-operation recovery and no-implicit-prune behavior remain owned by `TopologyApplyService`.

**Wi-Fi compatibility:** the existing incremental Wi-Fi provisioning service now uses the same registry and Vault session as topology operations. Its additive-only management-link behavior, free-port checks, start ordering, read-back, audit event and shared Lab lease are preserved. It still never deletes resources, stops nodes or rewires existing links. The protected Runner, Docker, mac80211_hwsim, capture and evidence contracts are not replaced.

**Verification boundary:** focused tests cover adapter image/compute observations, secret-safe session lifetime, shared registry/session reuse by the Wi-Fi provisioner, template-image conflict blocking, API RBAC/interface reads, mappings, repeatable apply, drift and uncertain-operation recovery. Hosted exact-commit CI is required before marking this checkpoint CI_VERIFIED. These hardware-free fixtures do not prove a live GNS3 compute image, real controller create/delete operation or physical Wi-Fi behavior; RQ-042 remains an external operator gate.


## EXP-P06 implementation checkpoint — Cisco Modeling Labs provider

The CML adapter is an independent implementation of the shared provider contract; it does not wrap or route requests through the GNS3 client. Its authenticated REST lifecycle covers user-visible labs, node definitions, image-definition associations, compute-host/licensing observations, node lifecycle, interface inventory, link lifecycle and observed topology. A single bounded HTTP transport enforces approved private/local controller endpoints, verified TLS, disabled environment proxy inheritance, redirects disabled, bounded connect/read timeouts and a bounded response body. Provider errors are sanitized.

The existing gns3_lab_bindings table remains the sole Project/Lab connection record. Additive migration 20261122_16 adds provider identity and provider_workspace_id, backfills historic GNS3 bindings, and keeps the old gns3_project_id as a mirrored compatibility field. TopologyApplyService resolves the provider from the application-scoped registry and uses the generic workspace ID for catalogue, dry-run, apply, node lifecycle, interfaces, read-back and reconciliation. The original GNS3 adapter and protected Wi-Fi provisioning path remain in place.

CML image-definition association is not treated as proof that the VM image is installed or bootable. Image readiness remains UNKNOWN unless CML explicitly reports installed/ready or missing state. The software acceptance suite uses deterministic HTTP/session fixtures. Live controller access, licensing, image readiness and actual node boot are separate operator acceptance evidence; no hosted mock test is reported as live CML certification.


## EXP-P07-A implementation checkpoint — EVE-NG provider

EVE-NG is registered as an independent adapter alongside GNS3 and CML through the same application-scoped ProviderRegistry and CredentialVault-backed ProviderSessionService. It uses the shared private-controller HTTPS transport with TLS verification, disabled environment proxy inheritance, no redirects, bounded response sizes/timeouts and sanitized JSend/API failures. Login is verified through the authenticated user and status endpoints; workspace discovery is restricted to the folder returned for that user and bounded by folder/lab limits. EVE-NG workspaces are validated absolute .unl paths; folder traversal and ambiguous paths fail closed.

Template discovery and per-template image choice use the EVE-NG template catalogue and image options. A missing image never becomes available merely because a template exists. Node summaries are enriched with the real Ethernet/serial interface endpoints. The EVE-NG topology edge list is translated into canonical node/link endpoint records; direct serial links remain observed-only. Ethernet links are created through an explicitly named bridge network followed by two native interface-to-network attachments. An attach failure triggers best-effort detach of already attached interfaces and network deletion; it is recorded as an error and is never reported as success. Node start/stop operations read back the resulting state. Packet capture and unsupported serial mutations are not advertised.

The adapter is integrated into the existing provider binding and topology apply service. No second topology schema or connection table is introduced. The EVE-NG workspace is stored in the provider-neutral workspace field while the historical GNS3 alias remains compatibility data. The frontend selector exposes EVE-NG and clarifies that its workspace is an absolute .unl path.

Deterministic fixtures cover folder-scoped listing, authentication and logout, lab create/read-back/delete, template/image catalogue, resource observations, interface and topology translation, bridge-link creation, partial-attach rollback, node lifecycle state read-back and unsafe path rejection. These tests prove the software contract only; live EVE-NG edition/licensing, installed image and actual lab/node execution remain controller-specific operator acceptance.


## EXP-P07-B implementation checkpoint — Cisco Packet Tracer native project bridge

The first P07-B software package is integrated through an independent native `.pkt` codec, not through the emulator ProviderRegistry. It uses existing Project/Lab topology profiles and immutable revisions. Imported source bytes, SHA-256, codec/version, original device/interface/link mapping and compatibility report are retained in `topology_native_sources`, linked to the canonical profile and initial DRAFT revision. Source records are immutable; metadata reads do not return source bytes.

The parser uses strict decoding, a 3.5 MB source limit, and a bounded 24 MB expanded-XML preflight before the pinned codec parses the file. It maps supported device types, interfaces, IP/VLAN observations, layout coordinates and native link endpoints into canonical topology. Provider template IDs remain blank because Packet Tracer identities are not GNS3/CML/EVE-NG template IDs. Provider apply therefore remains blocked until an operator supplies a real compatible mapping.

The initial export subset preserves original bytes exactly when unchanged. For revisions that change only logical-device names or canvas coordinates, the codec serializes the native document and reads it back to verify device identity/name and link endpoints. Device/model addition/removal, link mutation and interface/configuration edits fail with an explicit unsupported-change conflict. No full-fidelity or Packet Tracer desktop-reopen claim is made. Codec output may upgrade older files to its latest known edition; source and output versions are reported.

Migration `20261123_17` adds immutable provenance persistence and schema contracts. REST endpoints and Topology Studio use existing Project permissions, session/CSRF and POST idempotency behavior. `pktlib==0.2.2` is MIT-licensed and hash-pinned; its upstream documents testing against Packet Tracer 8.2.0 and labels the package alpha.

The focused Packet Tracer suite is wired into the existing NetRegress quality workflow. Native Packet Tracer desktop reopen, representative files from each claimed version, complete visual-object fidelity and broader serializer qualification remain external acceptance gates. See `docs/EXP-P07B_PACKET_TRACER_IMPLEMENTATION_AUDIT.md` and RQ-018.


## EXP-P08 implementation checkpoint — canonical Network Intent v1.0

P08 adds a distinct vendor-neutral Network Intent service and relational persistence. Intent profiles bind to an existing canonical topology profile and inherit its Project/Lab scope. Each immutable intent revision is pinned to a specific immutable topology revision ID and content SHA-256; it has its own canonical SHA-256, schema version, provenance, parent reference and DRAFT/PUBLISHED lifecycle. Rollback creates a new DRAFT rather than rewriting history.

Schema v1.0 models IPv4/IPv6 addressing, VLANs, interface admin/modes, static routes, OSPF, BGP, LACP, firewall zones/basic ACLs, published DHCP/DNS configuration references, Linux bridges and VLAN interfaces. Validation rejects unknown schema fields, inline secrets, invalid values, duplicate IDs, dangling topology/interface/zone/segment references and cross-Project/Lab target bindings.

Device capability reports are immutable adapter/device-discovery observations with platform/software version, adapter identity/version, source type, feature status/constraints, SHA-256, observed time and recording provenance. No user-facing API can mark a capability SUPPORTED. Missing or stale (older than seven days) observations, observations more than five minutes in the future and explicit UNSUPPORTED reports are blocking for capability-aware publication. The internal recording service is the P09 adapter seam; P08 does not claim live GNS3/CML/EVE-NG/physical-device observations have been collected.

The REST API adds Project-scoped read/manage/publish operations for intent profiles and revisions, read-only structural/capability validation, rollback-as-new-draft, and a read-only capability-report history endpoint. The `/network-intent` React page exposes the schema editor, topology binding, target Device mapping, diagnostics, revision lifecycle and capability provenance.

Migration `20261123_18` advances the Alembic/schema contract to version 28. See `docs/EXP_P08_NETWORK_INTENT_IMPLEMENTATION_AUDIT.md` and RQ-021. P09 compilers and P10 Ansible remain separate downstream stages.


## EXP-P09 implementation checkpoint — multi-vendor configuration compiler v1.0

P09 introduces a configuration-compiler domain independent of the GNS3/CML/EVE-NG topology-provider registry. The compiler consumes only an immutable PUBLISHED P08 Network Intent revision, revalidates pinned topology and intent SHA-256 values, requires fresh adapter-observed capability reports for every target, corroborates observed platform/software version with managed Device vendor/model, then renders deterministic text artifacts.

Registered compiler families are Linux + FRRouting, Cisco IOS/IOS-XE, Arista EOS, Juniper Junos and Palo Alto PAN-OS. Adapter descriptors expose platform family, tested software-version range, output format and adapter version. Device model can further narrow a feature boundary (for example Junos firewall policy is exposed only for SRX models).

Compilation is read-only and all-or-nothing: a blocked target, unreported/unsupported capability, unknown platform/version, unsupported semantic or unsafe output produces diagnostics and no partial artifact collection. Artifacts include relative paths, SHA-256 hashes, content and optional unified baseline diffs. Baseline inputs are bounded, path-confined, secret-screened and never persisted. No CLI is executed, no SSH/HTTP device session is opened, no device configuration is written, and no successful-apply or observed-state claim is made.

The v1.0 feature boundaries are intentionally explicit:
- Linux/FRR: systemd-networkd interfaces, bridge/bond/VLAN netdevs, static routes, OSPF/OSPFv3, BGP and nftables zone rules. DHCP/DNS profile references are unresolved and block output.
- Cisco IOS/IOS-XE: routed/access/trunk interfaces, VLANs, IPv4/IPv6 routes, OSPF/OSPFv3, BGP, LACP and basic zone-based ACL policy. IPv6 ACL translation is not yet supported and blocks.
- Arista EOS: interface/VLAN, IPv4/IPv6 static routing, OSPFv4, BGP and LACP. OSPFv3 and P08 zone-based stateful firewall semantics are explicitly blocked rather than flattened into stateless ACLs.
- Juniper Junos: hierarchical set syntax, inet/inet6 static routes, OSPF/OSPFv3, BGP, LACP and SRX zone/policy statements. Firewall compilation is limited to SRX models; non-default canonical static-route metrics are blocked because Junos preference semantics differ.
- Palo Alto PAN-OS: routed Ethernet, IPv4/IPv6 static routes, OSPFv4, BGP, aggregate Ethernet, zones and security rules. Generic ACCESS/TRUNK switchport semantics, OSPFv3 and DHCP/DNS profile translation are not represented.

No platform-specific configuration parser, device read-back, candidate commit-check, deployment workflow, secret injection into generated configuration, NAT model or Ansible execution is claimed by P09 v1.0. Those require separate contracts and validation against real OS versions. P10 remains the separate Ansible execution/approval boundary.

Automated evidence is deterministic fixture/unit coverage for adapter discovery, version/platform mismatch, output rendering, protocol-family edge cases, injection/path safety, all-or-nothing output, revision/hash binding and API/frontend preview. It does not replace physical/device-in-the-loop acceptance tests.


## EXP-P10 implementation checkpoint — approval-gated Ansible automation

P10 adds a separate Ansible domain over published P08 Network Intent and P09 compiler outputs. Ansible never accepts user-supplied arbitrary playbooks, dynamic inventory sources, modules or shell commands. NetRegress generates a constrained playbook and static inventory from the exact P09 SHA-256 artifacts. Every target Device is Project-scoped, and a Lab-scoped intent additionally requires that each target belongs to that Lab. Project-wide intent acquires the locks for every target Lab and Device during execution.

Plan creation uses active same-Device OS Credential Vault references of type SSH_PASSWORD or SSH_PRIVATE_KEY; it never accepts a password/private-key value. Secret material is resolved only via `CredentialVaultService.use_secret` during execution, placed into private temporary inventory/key files and removed with the temporary workspace. Inventory previews, persisted plans, approval records and result summaries do not contain credential material. SSH host-key verification is enabled; an operator must trust each target host key first. Linux execution uses non-interactive sudo for non-root accounts.

An optional local Ansible runtime is pinned separately from NetRegress' default install: Ansible Core 2.21.6, `ansible.netcommon` 8.7.1, `cisco.ios` 11.6.0 and `arista.eos` 12.3.0. Run `scripts/netregress_ansible_setup.sh` from the same activated Python environment used by NetRegress. Plan validation fails closed when the exact runtime/collections are absent or unpinned. P10 does not silently install Ansible when the application starts.

Only Linux/FRR over SSH, Cisco IOS/IOS-XE and Arista EOS over network_cli have a generated execution path in this checkpoint. Junos compiles through P09 but remains blocked from P10 until a qualified NETCONF workflow exists. PAN-OS compiles through P09 but remains blocked until a qualified API transport exists. A compiled preview is not evidence that a live target is reachable or configured.

Plan lifecycle is `PREVIEWED → APPROVED → EXECUTING → SUCCEEDED/FAILED`, with `STALE` as an explicit rejection when the source revision, topology pin, current capabilities or compiler output changes after approval. The plan creator cannot approve their own change; an independent authorized administrator must approve the exact plan SHA-256. Execution repeats compiler/capability validation immediately before opening a Device connection, takes all relevant Lab and Device locks, and stores immutable execution/read-back evidence. If some hosts change before a later host fails, the result is FAILED, partial changes are possible, and reconciliation is required. No automatic retry, implicit rollback or all-target atomicity is claimed.

See `docs/EXP_P10_ANSIBLE_AUTOMATION_IMPLEMENTATION_AUDIT.md` and RQ-023. Hosted fixtures use an injected fake Ansible runner and in-memory secret store; they do not certify live SSH connectivity, target OS state, command semantics, network convergence or rollback safety.


## EXP-P11 implementation checkpoint — OpenTofu infrastructure automation

P11 establishes OpenTofu as the infrastructure provisioning owner, separate from P10 Ansible device configuration and the existing emulator-provider lifecycle. OpenTofu modules are installed and maintained by the local operator under NETREGRESS_OPENTOFU_MODULE_ROOT. The API selects an approved module key and bounded non-secret JSON variables; it never accepts caller-authored HCL, arbitrary CLI arguments, backend settings or provider executable paths. Module files are copied into an immutable per-workspace snapshot and pinned by SHA-256.

Each active Lab receives an isolated local workspace under NETREGRESS_OPENTOFU_STATE_ROOT (default ~/.local/state/netregress/opentofu). Workspace directories and sensitive variable/plan files use owner-only permissions. The local backend is selected explicitly by using tofu init -backend=false; remote backends and cloud/remote execution are not enabled in P11. Provider authentication is sourced only from an operator-configured process environment allow-list or platform identity; API variables cannot carry secret values. No state file, plan binary or credential value is returned by REST APIs or stored in the repository.

The lifecycle is format/init/validate/plan, review, independent hash-pinned approval, and explicit apply. Destroy plans require the separate infrastructure.destroy permission. Every plan is persisted by its binary SHA-256 and only a bounded resource-action summary is exposed. Apply verifies that same binary immediately before execution while holding the shared Lab lock and a workspace lock. A timeout or non-zero apply outcome is never retried automatically: the workspace enters RECOVERY_REQUIRED and must be reconciled in P12. Immutable workspace, plan, approval and execution records are protected by SQLite constraints/triggers and privileged actions produce audit events.

P11 does not claim live cloud-account qualification, remote backend support, cloud rollback, module registry downloads or provider-side resource recovery. The CLI is operator-installed and must satisfy the declared OpenTofu version gate. P12 adds topology resource mapping, observed state, drift/orphan analysis and reviewed recovery planning.


## EXP-P12 implementation checkpoint — topology resource lifecycle, drift and recovery

P12 connects OpenTofu resources to the existing canonical topology model. A binding is accepted only when the resource address exists in the selected Lab workspace state, the topology profile is active, the revision is immutable and published, and the logical node belongs to that exact revision. Mappings are versioned: a compare-and-swap replacement requires the current binding ID, moves the previous mapping to SUPERSEDED, and retains it as immutable history while maintaining one active mapping per workspace/resource address. Lab-scoped profiles must match the workspace Lab; Project-scoped profiles are permitted only inside the owning Project. Bindings are immutable and append-only.

Reconciliation acquires the shared Lab/workspace lock, verifies the immutable module/variable snapshot, prepares the operator-managed module, creates a private refresh-only OpenTofu plan, and compares saved-state resource addresses/types with resource drift and topology bindings. It classifies present, drifted, orphaned, drifted-orphaned and missing resources. Reconciliation records contain only addresses, resource types, action names, binding/node references and aggregate counts; raw Terraform state values, provider attributes, outputs and credentials are not copied into the API response or stored in the reconciliation detail JSON. A SHA-256 of the canonical full state snapshot and refresh-plan binary is persisted as integrity evidence.

Recovery from a failed or timed-out P11 apply is an explicit sequence: run refresh-only reconciliation, create a new normal RECOVERY plan pinned to the latest reconciliation ID, review the resource-action summary, obtain independent approval of that plan's binary SHA-256, and explicitly apply. A newer reconciliation invalidates the earlier recovery plan. No automatic retry, replay or rollback is claimed; unsuccessful recovery remains RECOVERY_REQUIRED.

P12 does not claim that refresh-only planning applies provider drift, that topology bindings discover every cloud resource automatically, or that a successful OpenTofu apply proves application-level service health. Mapping remains operator-reviewed against a published topology revision. Provider-specific resource and cloud-account qualifications remain separate acceptance work.
