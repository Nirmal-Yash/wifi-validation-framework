# EXP-P07-B implementation audit — Cisco Packet Tracer native project bridge

**Baseline:** `10d8288eb9c76d4abb5168118019ce6c2960e75e`  
**Implementation checkpoint:** native import, provenance and constrained source-based export  
**Requirement:** RQ-018  
**Acceptance status:** READY_FOR_CI; licensed Packet Tracer desktop acceptance remains pending

## Objective and architectural boundary

Packet Tracer is a native file-interoperability codec, not a network emulator provider. NetRegress remains authoritative for canonical topology definitions, immutable revisions, Project/Lab ownership and execution evidence. The original Packet Tracer file is retained as immutable provenance associated with the canonical profile and initial DRAFT revision.

This implementation does not emulate Packet Tracer or provision Packet Tracer objects through a remote controller.

## Implemented source behavior

- Strictly parses native `.pkt` input through the pinned MIT-licensed `pktlib` codec in a private temporary directory; uploaded content is never executed.
- Enforces a 3.5 MB source-file limit and a separate 24 MB expanded XML limit. The codec's authenticated container primitives are preflighted with bounded zlib decompression before the public parser is allowed to parse XML.
- Validates safe `.pkt` filenames, supported-version strict decoding and bounded canonical node/link/interface counts.
- Projects supported Packet Tracer devices, interfaces, supported IP/VLAN observations, coordinates and native link endpoint identities into the existing canonical `TopologyStudioService` model.
- Assigns no provider template IDs. The imported topology remains provider-independent until operators map each device to an observed compatible provider template.
- Creates a Project- or Lab-scoped profile, immutable DRAFT revision, original source bytes, SHA-256, source filename/version, codec name/version, original native object mapping and compatibility report in one database transaction.
- Audits profile creation, revision creation and native source import through the existing audit-events table.
- Blocks updates and deletion of native source records at the SQLite schema boundary.
- Lists provenance metadata without exposing source bytes.
- Exports the original bytes unchanged when there are no native-editable changes. For the initial serializer subset, device-name and canvas X/Y changes are written to a parsed copy of the original project. Node/device addition or removal, link mutation and interface/IP/VLAN/configuration changes are rejected as conflicts rather than silently discarded.
- Reopens serialized output through the codec and checks device identities/names and link endpoint signatures. The API reports that Packet Tracer desktop application reopening has **not** been verified.

## Codec qualification boundary

The selected dependency is `pktlib==0.2.2`, MIT-licensed and SHA-256 pinned in `requirements.txt` and `requirements.lock`. Upstream documentation identifies Packet Tracer 8.2.0 as its tested desktop version, states that it reads files from older Packet Tracer releases and writes the latest edition known to that codec. The upstream package is alpha software. NetRegress reports the detected source version and serializer output version rather than promising complete version-independent or lossless compatibility.

The distinct GPL-3.0 `packet-tracer-pkt-format` reference repository is not used as a runtime dependency. The bounded decompression preflight uses private codec primitives from the pinned version; the dependency must remain pinned and this guard must be requalified whenever the codec version changes.

## Persistence and API

Migration `20261123_17` adds the immutable `topology_native_sources` table, Project/profile/revision foreign keys, scope validation trigger, immutable update/delete triggers and provenance indexes. Schema metadata advances to version 27.

- `POST /api/v1/topologies/import/packet-tracer` — multipart upload; Project topology.manage permission; session/CSRF and existing POST idempotency boundary.
- `GET /api/v1/topologies/{profile_id}/native-sources` — Project topology.read permission; bytes excluded.
- `GET /api/v1/topologies/{profile_id}/native-sources/{source_id}/export?revision_id=...` — Project topology.manage permission; attachment download and base64url export report header.

## Frontend

Topology Studio exposes a Project/Lab-scoped `.pkt` import form, displays conversion warnings and retained source metadata, and allows export of the selected revision. Upload uses `FormData` without overriding the browser-generated multipart content type. Existing profile/revision and provider workflows remain in place.

## Verification plan and remaining gates

The added focused suite generates deterministic codec-native fixtures and covers import, source-byte/hash persistence, immutable source rows, Project/Lab scope, unsupported changes, no-op byte-identical export, name/coordinate serialization, codec reopen, bounded decompression, REST upload/list/download and source integrity. The existing NetRegress quality workflow is extended to run this suite.

The following are not established by hardware-free CI and remain external acceptance requirements:

1. Reopen exported files in a licensed Packet Tracer desktop installation.
2. Qualify representative native source files from each claimed Packet Tracer release.
3. Verify device models, modules, ports, link/cable semantics, drawings, notes, native layout and device configuration in Packet Tracer itself.
4. Expand native write support to model/device creation, links, interfaces and configuration only after explicit native mappings and round-trip tests exist.
5. Record exact Packet Tracer build, operating environment, test fixture provenance, execution timestamp, source commit and evidence hashes.

No licensed Packet Tracer desktop session or representative user-supplied project fixture was available to this source implementation. Accordingly, RQ-018 is not ACCEPTED and NetRegress must not advertise full Packet Tracer fidelity.
