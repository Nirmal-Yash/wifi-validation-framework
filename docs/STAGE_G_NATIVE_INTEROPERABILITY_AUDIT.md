# Stage G — G01 Existing Implementation Audit and Gap Register

**Audit date:** 2026-11-24  
**Repository:** Nirmal-Yash/wifi-validation-framework  
**Audit baseline:** 3416d2ec5d6e3fa869975845b8d2629201e1acca (main)  
**Quality evidence:** [GitHub Actions 45368988732](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45368988732), exact baseline commit, completed successfully (backend, dashboard startup/session smoke, frontend tests and production build).  
**Phase state:** G01 = SPECIFICATION_COMPLETE; G02 = NOT_STARTED.  
**Acceptance boundary:** CI verifies only the software/fixture contracts that it executes. It does not establish live-provider, proprietary desktop application, physical-device or native-project round-trip acceptance.

## 1. Purpose and audit method

G01 establishes the real implementation boundary before native-interoperability work begins. It audits the current EXP-P06 through EXP-P10 source, migrations, APIs, frontend wiring, tests, quality workflow and phase audits. The repository is authoritative; historical completion statements are not substituted for current source evidence.

The audit distinguishes four separate concerns:

1. **Provider runtime adapters** communicate with live emulators/controllers and manage observed resources.
2. **Native project codecs** detect, parse, validate, map, serialize and round-trip vendor project files.
3. **Canonical NetRegress topology** owns logical nodes, interfaces, links, immutable revisions, Project/Lab scope and content hashes.
4. **Network configuration and execution** own desired network intent, vendor configuration output, device transport, Ansible runs, observed state and evidence.

A provider adapter is not a project-file codec. A generated configuration preview is not a device deployment. A codec reopening its own serialized output is not proof that the originating vendor desktop application can reopen and run the exported project.

The audit did not modify source code or database structures. It records the implementation gap register and next dependent package.

## 2. Current resumption point

| Area | Verified source state | Current state | Remaining acceptance |
|---|---|---|---|
| EXP-P06 — CML provider | Independent authenticated REST adapter, controller/version/health, labs, node definitions, image and compute/licensing observations, node lifecycle, interfaces, links and observed topology. | CI_VERIFIED by exact-main quality workflow; adapter tests are fixture-based. | Live CML controller, edition/licensing, actual image availability, node boot and topology read-back. |
| EXP-P07-A — EVE-NG provider | Independent authenticated REST adapter, authenticated-user-folder-scoped .unl workspace paths, template/image observations, Ethernet/serial interface inventory, bridge-backed Ethernet links, node lifecycle and partial link-failure cleanup. | CI_VERIFIED by exact-main quality workflow; adapter tests are fixture-based. | Live Community/Professional edition, controller version, installed images, lab/node operations and bridge attachment. |
| EXP-P07-B — Packet Tracer bridge | Native .pkt decoder using pinned pktlib, canonical projection, immutable source provenance, constrained serializer and codec-level read-back. | CI_VERIFIED for automated software contracts; not fully native-application accepted. | Representative vendor-produced .pkt fixtures across claimed versions, Packet Tracer desktop reopen, drawings/notes/configuration fidelity and actual lab behavior. |
| EXP-P08 — Network Intent | Strict versioned v1.0 intent model, immutable revisions pinned to topology hashes, append-only device capability observations and Project/Lab-scoped APIs/UI. | CI_VERIFIED for schema, lifecycle, authorization and fixture contracts. | Real provider/device capability observations for exact device/software versions. |
| EXP-P09 — Configuration compiler | Five deterministic compiler families: Linux/FRR, IOS/IOS-XE, Arista EOS, Juniper Junos and Palo Alto PAN-OS. Compilation is read-only and all-or-nothing. | CI_VERIFIED for compiler fixture contracts. | Native syntax validation and read-back on exact target software; candidate/commit checks and live deployment are outside P09. |
| EXP-P10 — Ansible automation | Hash-pinned plans from published P08/P09 revisions, static scoped inventory, Vault references, four-eyes approval, bounded execution, locks and limited per-device read-back. | CI_VERIFIED for exact-main quality workflow. | Live SSH/network_cli and target acceptance; broader execution profiles, transports and recovery remain G11. Linux desktop package run [45368016475](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45368016475) was still reported in_progress when checked. |

The exact-main quality workflow at the audit baseline completed successfully. Its backend command explicitly includes tests/test_stage_b_cml.py, tests/test_stage_b_eve_ng.py, tests/test_packet_tracer_interop.py, tests/test_network_intent.py, tests/test_ansible_automation.py, tests/test_provider_contract.py and tests/test_topology_apply.py. The frontend test/build and dashboard startup/session jobs also passed. This is automated software evidence, not live-provider qualification.

## 3. Existing architecture and behavior to preserve

G02 and later work must extend these established ownership boundaries rather than create competing services.

| Existing authority | Source of truth / implementation | Preservation requirement |
|---|---|---|
| Canonical topology and revisions | lib/services/topology_studio.py, topology tables and existing topology APIs | Keep logical identities, Project/Lab scope, canonical hashes, immutable published revisions and draft/publish lifecycle. Add associated, versioned presentation metadata; do not replace the semantic model. |
| Provider connection and lifecycle | lib/providers/contracts.py, lib/providers/registry.py, lib/providers/session.py and GNS3/CML/EVE adapters | Keep ProviderRegistry for live runtime operations. Native file codecs must not pretend to be remote ProviderAdapters. |
| GNS3 operations | lib/services/gns3_provider.py and lib/services/topology_apply.py | Preserve the sole GNS3 REST client, provider mappings, explicit apply, Lab/Device locks, idempotency, read-back, reconciliation and partial-operation recovery. Preserve Wi-Fi provisioning and GNS3/mac80211_hwsim behavior. |
| CML operations | lib/providers/cml.py | Preserve CML's distinct lab, node-definition, image-definition, compute and lifecycle semantics. Do not infer a CML YAML codec from the REST API. |
| EVE-NG operations | lib/providers/eve_ng.py | Preserve authenticated-user folder scoping, absolute .unl workspace validation, actual interface mappings and limited link semantics. Workspace path handling is not a native .unl serializer. |
| Packet Tracer provenance | lib/services/packet_tracer_interop.py, migration 20261123_17, topology_native_sources | Preserve byte-level SHA-256 provenance and existing API/UI behavior. The current table's format constraint is Packet-Tracer-specific; do not silently reuse it as a generic multi-format registry. |
| Network Intent and capability evidence | lib/services/network_intent.py, migration 20261123_18 | Keep intent distinct from topology and device-native configuration. Only actual adapter/device discovery may record SUPPORTED capabilities. Preserve freshness, hashes and unknown/unsupported blocking. |
| Vendor compilation | lib/network_config/, lib/services/network_intent_compiler.py | Preserve independent compiler adapters, per-platform feature gates, deterministic outputs, blocker diagnostics and all-or-nothing preview behavior. Compilation is not application success. |
| Ansible and credentials | lib/services/ansible_automation.py, Credential Vault, migration 20261124_19 | Preserve Project/Lab/Device scope, opaque Vault references, secret callback boundary, host-key verification, plan hash, independent approval, locks, bounded process and honest partial-failure semantics. |
| Evidence and audit | Existing audit, artifact, Run, pipeline and operational recovery services | Associate native imports, exports, conversions and verification with existing scope and immutable evidence; do not add a second execution-history owner. |

No change in this G01 package modifies these services or schemas.

## 4. Source-backed capability matrix

### 4.1 Emulator/provider runtime versus native project files

| Platform | Existing runtime implementation | Native project-file implementation found | Accurate current claim |
|---|---|---|---|
| GNS3 | Authenticated REST provider supports project/template/node/link/interface operations, observations and capture capability metadata. | No .gns3 project codec or project archive parser/serializer identified in current source. | Live provider adapter exists; native project import/edit/export is not implemented. |
| Cisco Modeling Labs | Independent REST provider supports labs, definitions, images, compute/licensing observations, nodes, interfaces, links and topology observations. | No CML native YAML or legacy VIRL import/export codec identified. | Live provider adapter exists; native file interoperability is not implemented. |
| EVE-NG | REST provider treats an absolute, folder-contained .unl path as a workspace identifier and observes/manages supported lab objects. | No .unl byte-level parser, asset resolver, serializer or reopen/round-trip codec identified. | Live provider adapter and workspace handling exist; native file interoperability is not implemented. |
| Cisco Packet Tracer | No remote provider API is claimed. | A real .pkt codec path exists through pinned pktlib, with bounded decode, canonical projection, source-byte provenance, no-op exact-byte export and constrained name/coordinate serialization. | Partial native codec support exists; broad editing and Packet Tracer desktop reopening are not accepted. |

### 4.2 Packet Tracer's actual v1 boundary

The current Packet Tracer implementation is materially more than a filename detector or JSON interchange. It:

- strictly decodes supported .pkt files with a 3.5 MB source limit and bounded expanded XML preflight;
- rejects DTD/entity declarations and malformed/oversized compressed input before normal XML parsing;
- maps supported devices, interface/IP/VLAN observations, node coordinates and native link endpoint identities into canonical topology;
- stores original source bytes, SHA-256, codec/version and mapping/compatibility metadata in an immutable Project/Lab-scoped provenance row;
- returns original bytes when no native-editable changes exist;
- serializes the supported device-name and X/Y coordinate subset and performs codec-level identity/name/link/coordinate read-back;
- explicitly refuses device addition/removal, link mutation and interface/configuration changes it cannot serialize.

The existing compatibility report states that native drawings and notes are retained in the source but are not editable canonical objects. Packet Tracer desktop application reopening has not been verified. The pinned codec is documented in the repository audit as alpha and tested upstream against Packet Tracer 8.2.0; output may upgrade older source files to the codec's known serialization edition. These limits must remain visible.

### 4.3 Canonical semantic and presentation data

TopologyStudioService.normalize_definition currently accepts a constrained root containing only nodes and links. It provides canonical logical IDs, node type/name/template mapping, bounded scalar properties, X/Y coordinates, interface names and adapter/port indices, selected interface metadata and link endpoints. The service produces deterministic canonical JSON and SHA-256 hashes and persists immutable topology revisions.

That is a sound semantic baseline, but it is not a native presentation document. The current canonical definition does not provide a versioned model for native canvas dimensions, coordinate origins/transforms, zoom/viewport, grid/snap, per-template node dimensions, icon/asset identity, port anchor geometry, label locations, link route geometry, annotation objects, drawings, layer visibility, arbitrary native object IDs or namespaced unknown source fields. Unknown root/node/interface/link fields are rejected rather than round-tripped.

G02 must add an associated, schema-versioned presentation/extension model without weakening the semantic validator into an unbounded JSON bag.

### 4.4 Native provenance persistence

Migration 20261123_17_packet_tracer_native_sources.py creates topology_native_sources with Project/profile/revision relationships, format/version, filename, SHA-256, size, original bytes, codec metadata and mapping/report JSON. Scope and immutable update/delete triggers protect the records.

The migration explicitly constrains format to CISCO_PACKET_TRACER_PKT. This is correct for P07-B but is not a generic GNS3/CML/EVE/Packet Tracer native source store. G02/G03 must select a backward-compatible generalization strategy: preserve Packet Tracer rows and API behavior, introduce a separate generalized source-artifact model or perform a tested additive migration with a safe copy/verification path. Do not drop/recreate the audit-bearing source table casually.

### 4.5 Network intent, compilers and execution

P08 is a distinct immutable vendor-neutral intent domain pinned to topology revisions. It covers selected portable network semantics and records adapter/device capability observations with platform/software and source provenance. It does not claim capabilities that have not actually been observed.

P09 registers five compiler families. It validates target platform/model/software against current capability evidence and compiles supported intent into deterministic previews. Unsupported semantics are rejected with diagnostics. The P09 audit explicitly states that compilation does not open SSH/HTTP sessions, apply configuration, read device state or establish drift.

P10 is a generated-playbook execution path, not an unrestricted Ansible authoring environment. It accepts a published P08 revision and P09-generated artifacts, generates a static Project/Lab/Device inventory and constrained playbook, requires pinned Ansible/collection versions, credential references from the Vault, independent approval of the exact plan hash and explicit execution. Current actual execution transports are Linux/FRR SSH, Cisco IOS/IOS-XE network_cli and Arista EOS network_cli. Junos remains compile-only pending a native NETCONF candidate/commit-check workflow; PAN-OS remains compile-only pending a scoped API implementation. User-supplied playbooks, arbitrary custom modules/collections/runtime environments, generalized CLI/API operations, full observed-state diffs, resumable workers and transactional multi-device compensation are not established P10 capabilities.

## 5. G01 implementation gap register

Priority P0 denotes a foundational dependency that must precede dependent codecs; P1 denotes core Stage G functionality; P2 denotes expansion/qualification work. These are gaps, not claims that no related functionality exists.

| Gap ID | Priority | Area | Evidence in current source | Exact gap and required treatment | Stage G package |
|---|---|---|---|---|---|
| G01-001 | P0 | Codec architecture | Provider contracts describe remote runtime methods; Packet Tracer owns a format-specific service. | No independent format registry/codec contract for detection, version, parse, validate, semantic/presentation extraction, assets, serialize, compatibility and round-trip verification. Build a dedicated codec framework; do not overload ProviderRegistry. | G03 |
| G01-002 | P0 | Native topology data model | Canonical topology is a strict nodes/links semantic model with basic X/Y and bounded properties. | No associated versioned native presentation model or namespaced unknown-field extension envelope. Add immutable presentation snapshots tied to existing topology revisions and hashes. | G02 |
| G01-003 | P0 | Generic native-source provenance | topology_native_sources is Packet-Tracer-specific by CHECK constraint. | Provenance cannot yet be recorded uniformly across all target formats. Add a backward-compatible generalized source-artifact contract and migrate/retain existing Packet Tracer provenance safely. | G02/G03 |
| G01-004 | P1 | GNS3 native project | GNS3 REST adapter is present; no native codec found. | No parsing/serialization of .gns3 project JSON, associated assets, node/link presentation or GNS3-specific metadata, nor native application reopen comparison. | G04 |
| G01-005 | P1 | CML native project | CML REST adapter and API observations are present; no YAML codec found. | No documented-version CML YAML parse/serialize path, legacy VIRL feasibility boundary, node-definition/image mapping, layout/annotation preservation or CML reopen test. | G05 |
| G01-006 | P1 | EVE-NG native lab | EVE REST adapter safely handles .unl workspace paths. | No file-level .unl parser/serializer, native lab metadata/layout preservation, asset resolution or EVE reopen test. | G06 |
| G01-007 | P1 | Packet Tracer fidelity | .pkt source and constrained serializer exist. | Native edit support is limited to names and coordinates; add/remove, link, interface and configuration edits are rejected. Drawings/notes and broad native properties are not editable. App reopen/version matrix is not accepted. | G07 |
| G01-008 | P1 | Semantic/presentation fidelity | Current topology canvas uses canonical node positions and links. | No common projection/render contract for native coordinate origins, scale/offset, canvas/view state, dimensions, port anchors, routed links, labels, icons, annotations, drawings, layers and visibility. Import must preserve placement, not silently auto-layout. | G02/G08 |
| G01-009 | P1 | Cross-vendor conversion | Provider adapters and Packet Tracer mapping are separate; no translation engine identified. | No bidirectional translation framework with object mapping, asset/image checks, configuration mapping, losses, unsupported objects, manual mapping and comparable conversion reports. | G09 |
| G01-010 | P1 | Vendor-native configuration | P08 intent and P09 compiler have explicit portable schemas and platform limits. | Common intent cannot represent every vendor-native feature. There is no complete native configuration archive/extension, native API/CLI operation model or broad per-version advanced configuration lifecycle. Preserve canonical intent and vendor-native configuration as separately versioned associated data. | G10 |
| G01-011 | P1 | Automation extensibility | P10 creates constrained generated playbooks and static inventory for three execution families. | Arbitrary user playbooks, roles/collections/custom modules, isolated execution environments, user-selected native operations, Junos NETCONF and PAN-OS API transports are not in current P10 acceptance. Expand with configurable policy, authorization, secret and audit controls; do not silently remove the existing approval/hash model. | G11 |
| G01-012 | P0 | Unified reconciliation/evidence | Existing topology apply, Ansible evidence, source provenance and audit services are separate workflows. | No unified contract yet ties native-source identity, import/export history, format conversion loss, asset integrity, provider observations, configuration snapshots and uncertain partial operations to a recoverable operational history. | G12 |
| G01-013 | P1 | Representative native fixtures | Existing native tests are strongest for Packet Tracer; CML/EVE tests target REST fixtures. | No complete representative native file fixture set and cross-version native application round-trip qualification is demonstrated for GNS3, CML and EVE-NG. Packet Tracer tests are codec-level fixtures, not desktop acceptance. | G04–G07 |
| G01-014 | P2 | Per-version support declaration | Provider/compiler descriptors exist; native codec catalogue does not. | No format/version/capability catalogue declares which objects, presentation semantics, assets, serializer operations and round-trip environments have actually been qualified. Add explicit per-version support matrices and loss reports. | G03/G12 |

## 6. Architectural decisions and constraints for G02+

1. **Keep provider adapters and file codecs independent.** ProviderRegistry remains for authenticated controller/runtime operations. A separate native format registry owns file codecs.
2. **Canonical topology remains authoritative.** Native documents are associated representations. Do not create a parallel vendor topology database or replace Project/Lab/revision ownership.
3. **Separate semantics from presentation.** Keep logical node/interface/link identity in canonical topology. Store vendor presentation and vendor-native extension fields in versioned associated snapshots pinned to the same immutable revision.
4. **Preserve provenance.** Retain source bytes or an immutable artifact reference with SHA-256, format/version, codec/parser version, import actor/time, owning scope, source identifiers, asset manifest and compatibility/loss report.
5. **Unknown fields must not be silently lost.** Use a bounded namespaced extension strategy where the native format permits it. Do not weaken the canonical semantic validator to accept arbitrary nested properties.
6. **Safe parsing is mandatory.** Enforce size, expansion, recursion, object-count and asset limits; prevent path traversal, symlink escape, archive bombs, DTD/entity expansion and unintended execution. Resolve assets only within a bounded import workspace.
7. **Import must retain native placement.** Coordinate transforms are format-specific and explicit. Preserve native viewport and canvas metadata. Automatic layout remains a separate user command.
8. **No false native-support claims.** Each format/version declaration must be based on representative source files, codec read-back and reopening in the originating application where required by the claim.
9. **Keep network intent and native configuration dual.** Portable behavior belongs in Network Intent; advanced vendor-specific configuration remains separately associated and versioned. Never silently flatten unsupported semantics.
10. **Do not weaken P10 security.** Broader automation is not a bypass for authentication, authorization, Vault isolation, execution audit, host identity checks, process supervision, Lab/Device locking or recovery after uncertain remote outcomes.
11. **No AI in this programme.** No LLM, agent, model, inference, embedding or AI dependency is introduced.
12. **Preserve legacy regressions.** GNS3/mac80211_hwsim, Wi-Fi provisioning, existing test node IDs, topology APIs and Packet Tracer endpoints/source rows remain compatible.

## 7. Exact next implementation task — G02

G02 — Extended Native Topology Data Model — is the next package. G03 codec contracts must consume its stable versioned objects; individual format parsers must not invent independent presentation schemas.

### G02 package A — specification

Define:

- versioned presentation schema and immutable presentation revision relationship;
- native coordinate space, origin, units, scale/offset and canvas/view metadata;
- node size, rotation, icon/template/asset references, z-order and labels;
- interface port anchors and port display metadata;
- link route geometry, control points, labels and routing style;
- drawing/annotation objects, layers, visibility and ordering;
- original vendor object identifiers and scoped identity mappings;
- namespaced extension fields with byte/depth/item limits;
- generic source-file/asset provenance without invalidating existing Packet Tracer rows;
- hash, immutability, Project/Lab ownership, migration and rollback rules.

### G02 package B — backend implementation

Extend existing topology persistence additively. Introduce typed validation and canonical serialization for presentation snapshots. Tie each snapshot to its canonical topology revision and content hash. Ensure update/publish rules are immutable and that reading older revisions without presentation data yields a deterministic legacy/default presentation, never a fabricated vendor layout. Add database constraints/triggers and migration tests.

### G02 package C — API and frontend integration

Expose scoped read/write operations for draft presentation metadata through existing topology permissions, CSRF/idempotency and audit conventions. Integrate presentation data into existing Topology Studio without replacing canonical topology APIs. Provide explicit imported-native origin/fidelity indicators. Keep auto-layout separate from import.

### G02 package D — verification and acceptance

Test schema versioning, canonical hashes, immutability, ownership, malformed/bounded extension data, unknown-property preservation, migration/restore safety, legacy profile rendering, frontend editor state and existing topology/provider regressions. Do not claim native format fidelity until G04–G07 native application round-trip evidence exists.

### G02 Definition of Done

- One authoritative, documented presentation schema version exists.
- Presentation snapshots are immutably pinned to canonical topology revision/hash.
- No duplicate topology ownership or regression in existing APIs.
- Namespaced extension fields are bounded, hash-covered and preserved.
- Existing records migrate/read without synthetic vendor metadata.
- Project/Lab authorization and audit are enforced.
- Topology Studio uses real backend presentation APIs and handles legacy, loading, empty and error states.
- Focused backend, migration, frontend and exact-main quality tests pass.
- GNS3/mac80211_hwsim and existing Packet Tracer behavior remains protected.
- Desktop/vendor/live acceptance is recorded separately.

## 8. External acceptance gates that remain separate

| Acceptance gate | Required evidence | What current CI does not prove |
|---|---|---|
| GNS3 native | Representative .gns3 project and asset bundles; versioned import/export; open exported project in declared GNS3 desktop/controller version; compare nodes, interfaces, links and layout. | Current provider REST fixture tests do not verify native project files. |
| CML native | Representative YAML and supported legacy VIRL files; exact CML release/edition; import/reopen and compare node definitions, image references, topology and layout. | Current CML REST fixtures do not verify YAML/VIRL interchange or licensing. |
| EVE-NG native | Representative .unl with related assets; exact Community/Professional version; reopen in EVE-NG and inspect nodes, networks, interfaces and layout. | Current .unl workspace path tests do not parse or serialize file bytes. |
| Packet Tracer native | Vendor-produced .pkt files from each claimed version; export then reopen in Packet Tracer desktop; compare device identity, ports, links, configuration, drawings and notes. | pktlib self-read-back does not establish desktop application acceptance. |
| Vendor configuration/execution | Exact device family, OS/API version, image/licence, supported feature and validated command/API outcome, before/after read-back and recovery evidence. | Compiler and fake Ansible runner tests do not prove live network convergence or physical device behavior. |
| Protected legacy Wi-Fi | Approved GNS3/mac80211_hwsim host, protected 11-scenario suite and actual PCAP/evidence hashes. | Hosted CI and fixture-based Stage G tests cannot replace the protected live lab. |

## 9. G01 completion record

- [x] Current remote main and exact HEAD identified.
- [x] Current exact-main quality workflow and job outcomes inspected.
- [x] P06–P10 source, migrations, API/UI, test and audit documents reviewed.
- [x] Existing provider, topology, intent, compiler, automation and evidence ownership boundaries recorded.
- [x] Native format and presentation gaps recorded without conflating provider APIs with codecs.
- [x] External acceptance gates separated from CI results.
- [x] Roadmap, requirement traceability and agent resumption context updated in the G01 documentation commit.

**G01 result:** SPECIFICATION_COMPLETE.  
**Next:** begin G02 package A/B — extended native topology presentation/provenance model. No G02 source implementation is claimed by this audit.
