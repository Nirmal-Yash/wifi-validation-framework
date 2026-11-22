# EXP-P03 — Visual Topology Studio Implementation Audit

## Phase context

- Repository: `Nirmal-Yash/wifi-validation-framework`
- Phase: EXP-P03 — Complete Visual Topology Studio
- Prerequisites: EXP-P00 architecture baseline, merged EXP-P01 application shell, merged EXP-P02 operational overview
- Target: Upgrade the existing SVG editor without replacing the canonical topology profile/revision domain or creating another provider client.
- AI/LLM/agent functionality: excluded.

## Existing domain retained

- `TopologyStudioService` remains the canonical Project/Lab profile, definition normalization and immutable revision service.
- `topology_profiles` and `topology_revisions.definition_json` remain the persistence authority.
- `content_sha256`, revision numbering, DRAFT/PUBLISHED lifecycle and immutable revision triggers remain intact.
- `TopologyApplyService` remains the GNS3 provider-operation authority and continues to own Lab binding, provider template conflict checks, resource locks, idempotent apply, observed-state reconciliation, mapping persistence and explicit node lifecycle.
- Existing topology RBAC permissions remain authoritative: `topology.read`, `topology.manage`, `topology.publish`, `topology.provider.manage`, `topology.provider.operate`, and `topology.apply`.
- Credential/configuration reference fields are scoped through `credentials.read` and `configurations.read`.

No new relational table or Alembic migration is introduced. The added fields are optional in the existing canonical JSON so historical revisions remain readable with their original values and hashes.

## Implemented visual workbench

### Canvas and editing

- Categorized device palette for Routers, Switches, Firewalls, Wireless, Servers, Endpoints and Network utilities.
- Palette click-to-add and browser drag/drop onto the canvas.
- Palette items create provider-independent logical nodes; they do not issue provider calls.
- Deterministic, graph-based auto-layout that groups connected components and bounds placement inside the canonical coordinate world.
- Existing canvas drag/group movement, pan, zoom, fit, search, multi-select, select-all, delete, copy/paste with new logical IDs and remapped internal links, undo and redo retained.
- New interface-port handles allow a source interface and destination interface to be selected to create a canonical link.
- Existing link selection, link inspection and editing retained and expanded.

### Structured logical node intent

Optional, normalized node fields:
- Vendor, operating system and image metadata.
- Optional provider-specific template ID. Empty means unmapped logical intent and remains valid for design/save/validate.
- CPU cores and memory MB with bounded integer validation.
- Management IP/prefix, default gateway and VLAN ID with IP/family/range validation.
- Up to 64 planned interfaces per node with unique names and adapter/port assignments, mode, IP/prefix, VLAN and description.
- Configuration profile ID and opaque Credential Vault reference ID.

The topology definition accepts a Vault reference ID only. It rejects secret-like fields in the legacy properties bag and never accepts or serializes the credential secret itself. Credential references must be active and Project-owned; configuration references must be published Project-owned profiles backed by active Project schemas. The API requires `credentials.read` or `configurations.read` only when the corresponding reference is supplied, at both validation and immutable revision creation.

### Structured logical links

Optional, normalized link fields:
- Source and target interface names.
- Link type (Ethernet, wireless, serial, tunnel or other).
- Network segment reference and VLAN association.

When an interface list exists, each named link interface must resolve to the logical endpoint node and match the declared adapter/port pair. Existing links without interface-name fields remain valid.

### Property inspector and observed state

- Node inspector covers identity/type, vendor/OS/image, template, CPU/memory, management IP/gateway, VLAN, interfaces/ports, configuration profile and credential reference.
- Interface fields support mode, adapter, port, IP and VLAN editing. A referenced interface cannot be removed until its link is removed or reassigned.
- Link inspector covers source/target nodes and interfaces, link type, network segment and VLAN.
- Provider resource IDs and operational states are read-only.
- Node/link mapping and status are populated from the existing provider mapping records and actual catalogue/reconciliation output. Without an observation the UI displays UNKNOWN / Not mapped; it does not imply connectivity or resource health.

## Bottom operational console

The editor includes six separate tabs:
1. **Validation** — canonical validation result/hash, save new immutable DRAFT and explicit publish action.
2. **Provider operations** — existing GNS3 Lab binding/catalogue/dry-run/apply controls.
3. **Logs** — browser-session editor activity only, explicitly not presented as the persistent audit log.
4. **Apply history** — persisted topology apply and recovery records.
5. **Reconciliation** — actual managed/unmanaged counts, missing/mismatched nodes/links and logical-to-provider mapping.
6. **Warnings** — unmapped templates, invalid local interface references and canonical validation errors.

## Canonical validation and provider safety

- `POST /api/v1/topologies/validate` invokes `TopologyStudioService.canonical_payload`, the same normalization and SHA-256 boundary as revision creation.
- Validation is read-only: it does not create a revision, update profile metadata, write an audit record or contact a provider.
- New fields are optional; old revision JSON remains valid.
- A logical-only node with empty `template_id` can be validated and saved, but a GNS3 dry-run reports a conflict until a compatible provider template is mapped.
- Reconciliation returns logical-to-provider node and link IDs from the existing mapping table and actual provider link/node snapshots. It is read-only and does not manufacture mappings.
- Apply remains limited to a published Lab-scoped revision, required Project permissions, conflict-free plan, resource locks/idempotency, and explicit confirmation bound to the planned revision SHA-256.
- Canvas edit, auto-layout, validation, draft save and publish do not call provider endpoints.

## Test coverage added or extended

Backend:
- Canonical normalization and order-independent hashes with optional node/link metadata.
- Invalid CPU/memory/IP/gateway/VLAN, repeated interface assignment and invalid interface-to-link references.
- Persisted draft revisions with logical nodes that do not yet have provider mappings.
- Credential/configuration reference Project-scope checks at validation and revision creation.
- Provider plan rejection for an unmapped template without provider mutation.
- Existing apply test asserts actual logical-to-provider node/link mappings and preserves apply/reconciliation behavior.

Frontend:
- Categorized palette, logical-only node add and provider template mapping inspector.
- Deterministic auto-layout action.
- Interface creation and interface-to-interface linking.
- Node/link property inspectors and observed-only mapping state.
- Six console tabs and session log labeling.
- Palette drag/drop, selection/clipboard/history and viewport behavior.
- Existing viewer read-only and canonical validate/save tests retained.

Contract/docs:
- OpenAPI describes typed node/interface/link metadata, reference ownership and provider-independent template state.
- Architecture, roadmap, traceability and README updated.
- This audit records implementation evidence without claiming live GNS3 or physical lab acceptance.

## Acceptance state

Implementation and focused tests are prepared for phase verification. EXP-P03 remains **IN_PROGRESS** until the exact PR commit passes the hosted backend, frontend/production-build and dashboard startup/session jobs. Interactive desktop viewport, keyboard/assistive-technology review and real GNS3 apply/recovery remain separate operator gates and are not claimed as performed here.
