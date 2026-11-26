# Stage G — G02 Extended Native Topology Presentation and Provenance

**Date:** 2026-11-24  
**Repository:** Nirmal-Yash/wifi-validation-framework  
**Implementation base:** b2ac90174f9483238eb597bae0d45024fdda7b03  
**State at commit preparation:** INTEGRATION_IN_PROGRESS; exact-head automated CI is pending.  
**Migration:** 20261124_20, schema metadata version 30.  
**Scope:** additive topology presentation snapshots and generic native source/asset provenance. This package does not implement native GNS3/CML/EVE/Packet Tracer codecs or claim native-application fidelity.

## 1. Architectural decisions

1. Existing TopologyStudioService remains the only owner of canonical logical nodes, interfaces, links, Project/Lab ownership and immutable topology revisions.
2. Presentation is an associated immutable revision, not a second topology. Every presentation row is bound to the exact canonical topology_revision_id and topology_content_sha256.
3. A separate generic source-artifact store is introduced. The existing Packet Tracer table and API are retained unchanged; its format-specific constraint is not broadened.
4. Vendor-native fields are carried only in bounded, namespaced extension objects. The strict canonical topology validator remains strict.
5. A presentation with layout_origin=NATIVE must identify a generic source artifact and match its format ID, format version, Project/Profile/revision and topology hash. A NetRegress or manually edited layout may be captured without claiming vendor provenance.
6. Parsing, extraction and filesystem/archive handling remain responsibilities of future format codecs. G02 stores already-resolved asset bytes and portable relative paths; it does not extract archives or execute source files.
7. Published presentation and source/asset content is append-only. Only the state transition DRAFT → PUBLISHED is permitted for a presentation revision, and only after its pinned canonical topology revision is published.

## 2. Persistence and migration

Migration alembic/versions/20261124_20_native_topology_presentation.py follows 20261124_19 and adds three tables.

| Table | Purpose | Integrity boundary |
|---|---|---|
| topology_presentation_revisions | Versioned canvas/native presentation snapshots | Unique revision number per canonical topology revision; schema v1.0; presentation SHA-256; exact topology hash; optional source-artifact FK; Project/Profile/revision scope trigger; immutable identity/content; DRAFT-to-PUBLISHED transition only; published timestamp/actor required; no delete. |
| topology_source_artifacts | Generic native project source bytes and parser/codec provenance | Project/Profile/topology revision and topology hash; format/version; safe basename; SHA-256 and byte length; codec name/version; bounded metadata JSON; 50 MiB source limit; immutable/no-delete triggers. |
| topology_source_assets | Individual associated binary assets | Source FK, canonical relative POSIX path, MIME type, SHA-256 and byte length; max 20 MiB per asset; unique source/path; immutable/no-delete triggers. |

Service-level asset limits are 100 assets per source, 20 MiB per asset and 100 MiB combined. Source content is capped at 50 MiB. Source and asset bytes are re-hashed and length-checked when retrieved. Presentation JSON is re-canonicalized and its stored schema version and SHA-256 are verified on reads.

The migration advances schema metadata from version 29 to 30. Schema-contract tables, columns, indexes, foreign keys and trigger requirements are extended. The earlier Packet Tracer topology_native_sources table is preserved rather than copied, dropped or reinterpreted.

The migration intentionally refuses an in-place downgrade because the newly added source and presentation records are audit-bearing. Recovery uses the repository's verified database-backup/restore process.

## 3. Version 1.0 presentation model

The backend service lib/services/topology_presentation.py strictly validates and deterministically canonicalizes:

- **Provenance:** schema version, layout origin, native format ID/version and source artifact ID.
- **Coordinate space:** unit, origin, X/Y axis direction, scale and offsets.
- **Canvas/view:** canvas width/height/background; viewport X/Y/width/height/zoom; grid and snap settings.
- **Nodes:** canonical logical node ID, native object ID, X/Y, width/height, rotation, icon/template references, asset path, label, z-order and layer.
- **Ports:** interface name or adapter/port identity, anchor X/Y, side, native port ID, label and extensions. Supplied interface mapping must agree with the canonical logical interface.
- **Links:** canonical logical link ID, native link ID, direct/polyline/orthogonal/curved/native route style, control points, label, z-order and extensions.
- **Drawings/annotations:** rectangle, ellipse, line, freehand, text and image objects; geometry, text, asset path, layer, z-order and style.
- **Layers:** unique identity, visibility, lock and z-order.
- **Extensions:** at most 16 lowercase namespaces with bounded JSON payloads. Credential-like key names are rejected recursively.

Limits include 1 MiB canonical presentation JSON, 128 nodes, 512 links, 1,000 drawings, 64 layers, 64 ports per node, bounded route/drawing points, finite numeric geometry and coordinate limits. Unknown root/object properties are rejected; format codecs must put retained vendor-specific properties under their namespace rather than loosening the canonical schema.

The shared validator is in lib/services/topology_metadata.py. It also enforces portable relative asset paths and bounded canonical JSON depth, item count, string size and total bytes.

## 4. Service lifecycle and APIs

### Services

- TopologyPresentationService: normalizes, hashes, creates, lists, reads and publishes immutable presentation revisions. It verifies source-artifact scope, hash, format and version and confirms referenced assets belong to that source record.
- TopologySourceArtifactService: records immutable original bytes, format/version, filename, parser/codec identity, bounded metadata and associated binary assets; exposes metadata/listing and integrity-checked byte retrieval for future codec services.
- topology_metadata.py: common canonicalization, bounded JSON, extension namespace and path validation helpers.

### HTTP API

- GET /api/v1/topologies/{profile_id}/revisions/{topology_revision_id}/presentation-revisions — requires topology.read; returns an empty list for legacy topology revisions with no associated presentation.
- POST /api/v1/topologies/{profile_id}/revisions/{topology_revision_id}/presentation-revisions — requires topology.manage; creates a DRAFT snapshot; uses the existing POST idempotency contract.
- POST /api/v1/topologies/{profile_id}/presentation-revisions/{presentation_id}/publish — requires topology.publish; only publishes after the pinned canonical topology revision is already published; uses the existing idempotency contract.

Routes verify profile/revision ownership before creating or publishing and return not-found for cross-profile IDs. The source-artifact service is intentionally a backend codec-facing persistence API; G02 does not add a public raw-source upload endpoint before G03 defines codec and safe-upload contracts.

OpenAPI documents the presentation schema and API lifecycle in docs/openapi.yaml.

## 5. Frontend integration

The existing Topology Studio now:

- loads presentation revisions for the selected canonical topology revision through the real API;
- captures an immutable NetRegress presentation snapshot only when the editor definition still matches the selected persisted canonical revision (unsaved semantic edits must first be saved as a new topology revision);
- stores the current viewport and canonical node placement/basic link presentation;
- displays presentation revision number, origin, content hash and lifecycle;
- restores a stored viewport;
- exposes Publish for draft presentation snapshots only when the underlying canonical topology revision is already published;
- shows loading and error/retry states.

The canvas UI does not yet expose editors for native ports, route control points, layers, drawings, imported assets or arbitrary vendor extensions. Those model fields are present and tested for codecs and subsequent renderer work; this UI must not imply those advanced fields are already editable. Import, export and native-application reopen remain G03–G08 responsibilities.

## 6. Focused verification added

tests/test_topology_presentation.py covers:

1. Native presentation source/format/hash binding; node and port geometry; route points; drawing, layer, vendor extension and asset persistence; deterministic hash; source/asset byte retrieval; publish gating; and SQL immutability/no-delete triggers.
2. Rejection of NATIVE layouts without source provenance, credential-like extension fields, unknown root keys, unknown layers and unsafe asset paths.
3. Source artifact Project/Profile/topology revision scoping and read-time SHA-256 tamper detection.
4. Profile-scoped API behavior, idempotent create, list, and publish transition.
5. Canonical presentation read-time SHA-256 integrity checking after a deliberately controlled test-only tamper.
6. Safe relative path validation for absolute paths, parent traversal, repeated separators and dot segments.

tests/test_schema_migrations.py now targets Alembic head 20261124_20 and schema metadata version 30, including the pre-Alembic preservation path. Its historical rewind fixture explicitly drops G02 triggers, indexes and tables before replaying the old migration chain, avoiding false table-exists failures. The central quality workflow includes the new focused test module. Existing topology, Packet Tracer, GNS3, provider, P08/P09/P10, API security, frontend production build and dashboard smoke suites remain enabled.

**Verification status:** no exact-head G02 CI result is claimed until the implementation commit's path-triggered workflow completes. Local Python/desktop/vendor environments were not available through the connected repository interface during this commit preparation.

## 7. Explicitly not claimed

- No GNS3 .gns3, CML YAML/VIRL, EVE .unl or expanded Packet Tracer codec is implemented here.
- No native desktop application has reopened an exported project.
- No universal coordinate conversion/rendering or new auto-layout behavior is implemented.
- No vendor configuration, Ansible execution, provider lifecycle or pipeline behavior is altered.
- No public generic source upload endpoint exists yet; future codecs call the scoped source-artifact service after safe parsing and canonical mapping.
- No live emulator/device/physical-lab acceptance is implied.
- No AI/LLM/model/agent dependency is introduced.

## 8. Next resumption point

**G02 implementation is integrated; exact-head CI is the remaining G02 software gate.** If the G02 quality run passes, record RQ-055 as CI_VERIFIED and proceed to G03 — Native Format Interoperability Framework. If it fails, fix the failing implementation/test without weakening assertions, create a focused corrective commit and re-check the exact new main SHA. G03 must consume the G02 v1.0 schema and keep codec registry separate from ProviderRegistry.


## 10. G02 completion update — 2026-11-26

G02 presentation schema and generic source provenance are now consumed by the G03–G06 import/export lifecycle. The codecs produce native G02 presentation snapshots, and source bytes remain immutable and SHA-256 verified. Topology Studio exposes native file import, source-artifact history and published-revision export for GNS3, CML and EVE-NG. Exact-head CI remains the verification gate. Vendor GUI/controller reopen and imported external asset qualification remain external.
