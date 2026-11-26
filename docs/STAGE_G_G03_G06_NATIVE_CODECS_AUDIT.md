# Stage G — G03–G06 Native File Codecs Implementation Audit

**Checkpoint:** 2026-11-26  
**Scope:** G03 codec framework, G04 GNS3 native project, G05 Cisco CML YAML/legacy VIRL, G06 EVE-NG .unl.  
**Source status:** CI_VERIFIED on exact commit `9ded2e3462c2a2a82b2979ed343e9e8ab726622a`. Exact-main quality workflow [45825419696](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45825419696) passed all three jobs: backend, frontend/build and dashboard/session smoke, including source/API security gates and repeated Linux reliability checks. Linux desktop package matrix remains a separate pending workflow; originating vendor application reopen/live controller qualification remains external.  
**Dependencies:** G02 schema 1.0, TopologyStudioService, TopologyPresentationService and TopologySourceArtifactService. No second topology authority or new migration is introduced.

## 1. Architecture and ownership

The native codec package is lib/native_topology. Its registry is intentionally independent of the live provider registry.

- Provider adapters connect to running emulator/controller services through authenticated runtime APIs.
- Native codecs parse and serialize user-supplied project files without connecting to controllers, starting nodes, provisioning compute, applying configurations or contacting external systems.
- TopologyStudioService remains the sole owner of canonical semantic nodes/interfaces/links, Project/Lab ownership and immutable topology revisions.
- TopologyPresentationService remains the owner of bounded vendor-aware layout, coordinates, port anchors, annotations, layers and namespaced extensions.
- TopologySourceArtifactService stores original source bytes, SHA-256, format/version, codec provenance and associated assets in the same Project/Profile/revision scope.
- NativeTopologyInteropService joins those services and enforces matching published topology and presentation revisions before export.
- Existing Packet Tracer-specific implementation, table and API are retained unchanged.

## 2. G03 codec framework

| Component | Responsibility |
|---|---|
| lib/native_topology/contracts.py | Typed decoded/encoded results, codec protocol, descriptor and error contract |
| lib/native_topology/registry.py | Unique codec registration, deterministic detection, descriptors and default registry |
| lib/native_topology/helpers.py | Bounded JSON/YAML/XML parsing, duplicate-key checks, coordinate/type mapping and identity validation |
| lib/services/native_topology_interop.py | Import/export lifecycle using immutable topology, presentation and source-artifact services |
| tests/test_native_topology_codecs.py | Format detection, schema projection, serialization, unsafe parser inputs, identity and API lifecycle tests |

The registry registers three native format families: GNS3_PROJECT, CML_LAB and EVE_NG_UNL. Legacy .virl is a supported input/export variant within the CML codec. Descriptors state declared scope and supported version families; a codec fixture is not evidence of vendor desktop reopening.

## 3. Format support matrix

| Package | Declared input family | Semantic extraction | Presentation extraction | Current export subset |
|---|---|---|---|---|
| G04 | GNS3 .gns3, file revisions 7/8/9 (GNS3 2.0/2.1/2.2) | Nodes, template/type identity, linked adapter/port endpoints and link identity | Native X/Y placement, node dimensions where present, canvas size, zoom, names and link labels | Node X/Y/name and link label; other source JSON fields retained |
| G05 | Cisco CML lab YAML schema 0.1.x | Nodes/node definitions, native interface IDs/labels, links and endpoint references | Native coordinates, labels, annotations (rectangle, ellipse, line, text) and mapped style | Node placement/label, link label and supported annotation geometry/text/style |
| G05 | Legacy VIRL XML schema 0.95, constrained SIMPLE-node subset | Top-level nodes, native interface order and src/dst interface XPath connections | Node locations and labels | Node location/label; XML reserialization may normalize whitespace/comments |
| G06 | EVE-NG .unl, declared file versions 1 and 2 | Devices, interfaces and network attachments | Device/network positions and labels | Device/network position and label |

### GNS3 details

The parser validates project type and file revision before mapping topology objects. It maps native node IDs to stable canonical IDs and resolves link endpoint node_id, adapter_number and port_number. It reads port names only when the source declares supported port-number metadata. Native SVG drawings and non-linked port metadata remain in the immutable source JSON and are not editable presentation objects. Compute bindings, template configuration, startup configuration and external asset files are not executed or fetched.

### Cisco CML and legacy VIRL details

CML YAML lab metadata, node definitions, interface IDs/labels, links and supported annotation shapes are mapped into canonical/G02 models. Configuration blocks remain in the immutable source and are never copied into canonical properties or executed. Legacy VIRL supports a constrained XML subset: top-level SIMPLE node declarations, native interface ordering, location coordinates and connection endpoints expressed as the supported node/interface XPath form. Unsupported VIRL node types or XPath forms fail closed.

### EVE-NG details

A .unl topology may have one shared network connected to multiple device interfaces, whereas the canonical topology model uses point-to-point links. The codec therefore represents every shared EVE network as an explicit logical segment node (SWITCH for bridge-like networks and CLOUD for external/NAT-like networks) and creates one canonical edge per attached interface. The original .unl remains authoritative for native network IDs and metadata. The codec maps declared node/network IDs and coordinates; it does not provision images, fetch image assets, boot nodes or connect to EVE-NG.

## 4. Parser and data safety

| Input | Controls |
|---|---|
| All source files | Non-empty input; maximum 50 MiB; safe basename; no archive extraction |
| JSON | UTF-8 object root, duplicate-key rejection, non-finite number rejection, 64-level nesting limit and 250,000 parsed-item limit |
| YAML | SafeLoader only, duplicate mapping-key rejection, aliases rejected, 48-level nesting and 100,000 parsed-node limits |
| XML | DTD/entity declarations prohibited, 80,000 element limit and 64-level nesting limit |
| GNS3 | At most 128 nodes, 512 links and 256 port metadata items per node; endpoint references and duplicate native IDs/ports validated |
| CML YAML | At most 128 nodes, 512 links, 64 interfaces per node and 1,000 annotations; every link endpoint must resolve to a native node/interface |
| EVE-NG | At most 128 devices, 512 network segments, 64 interfaces per device and 64 attachments per shared network; all network references must resolve |

The codecs parse one native project file. They do not unpack project archives or search arbitrary filesystem paths. The generic G02 source-artifact service can store separately supplied assets, but this import UI currently uploads only one native file and the codecs do not import external disk images, icons, boot files or adjacent project directories. References to those resources remain in the native source file; their bytes are not copied into the application.

## 5. Import, provenance and export lifecycle

POST /api/v1/topologies/import/native accepts one .gns3, .yaml, .yml, .virl or .unl file plus Project and optional Lab scope. It detects exactly one codec, parses and projects the graph, validates canonical topology and G02 presentation before persistent writes, creates a new scoped topology profile and immutable DRAFT revision, records the original source bytes/hash, and creates a linked native presentation revision.

GET /api/v1/topologies/{profile_id}/native-artifacts exposes metadata without source bytes. GET /api/v1/topologies/{profile_id}/native-artifacts/{source_id}/export requires topology.manage, a PUBLISHED topology revision, a PUBLISHED presentation revision and exact source/revision/profile association. Source bytes are re-hashed before serialization. The export includes X-NetRegress-Native-Report with source/export hashes, sizes, losses and originating_application_reopen: NOT_VERIFIED.

## 6. Intentional limitations and acceptance boundaries

The implementation is native-file import plus a bounded presentation-edit/export bridge. It is not a general vendor-native editor.

- Adding/removing devices, changing link endpoints, changing interfaces/configuration, changing templates/images or changing semantic object identities is not silently serialized; native identity mismatch fails export.
- GNS3 SVG drawings and unlinked port metadata remain source-only.
- CML annotations are editable only for mapped shape/text/style fields. Unknown YAML fields are preserved semantically; comments and original formatting are not guaranteed.
- Legacy VIRL is constrained and XML serialization may normalize formatting.
- EVE shared networks are projected as explicit segment nodes; original native IDs/attachments remain in the immutable source.
- External disk images, icons, startup files and adjacent project directories are not imported.
- Codec parse-after-export tests verify the supported serialization path. They do not prove reopening the result in GNS3, Cisco CML/VM Maestro or EVE-NG.

Vendor application reopen tests, exact per-version lab samples, licensed image readiness, physical controller execution and cross-vendor conversion are operator/future acceptance tasks.

## 7. Verification added

tests/test_native_topology_codecs.py covers deterministic detection; GNS3/CML/VIRL/EVE mapping; source-field retention; shared EVE segment representation; export refusal on identity changes; duplicate JSON/YAML keys; YAML aliases; XML DTD/entities; unsupported GNS3 revisions; JSON depth/item/finite-number bounds; G02 canonical/presentation validation; immutable source/presentation creation; source-list redaction; publish-before-export and API response provenance. The test module is wired into the exact-head NetRegress quality workflow.

## 8. Format references

- GNS3 project-file/topology JSON: https://docs.gns3.com/docs/using-gns3/advanced/the-gns3-file-format/
- Cisco Modeling Labs documentation: https://developer.cisco.com/docs/modeling-labs/
- Cisco Modeling Labs community YAML examples: https://github.com/CiscoDevNet/cml-community
- EVE-NG documentation: https://www.eve-ng.net/index.php/documentation/


## 9. Exact-main automated verification record

- Source and fixture/API implementation commit: `9ded2e3462c2a2a82b2979ed343e9e8ab726622a`.
- NetRegress quality workflow: [45825419696](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45825419696) — SUCCESS, all 3 jobs, including backend, frontend production build and dashboard startup/proxy/session smoke.
- Backend job included strict source security audit, API security boundary tests, the full authentication/dashboard/Phase B–I correctness suite and repeated Linux locking/process/recovery contracts.
- NetRegress Linux desktop package matrix: [45825419789](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45825419789) was still running at the time this audit was updated; package artifacts are not claimed complete here.
- This CI result does not prove opening exported projects in licensed GNS3, CML/VM Maestro or EVE-NG desktop/controller versions. Those remain external acceptance.
