# Stage D — Device Management and Topology Studio

Stage D is the product-stage continuation established after Stage C. It introduces the managed Device Inventory and the topology authoring/provider boundary without changing the historical B–P phase meanings. In particular, the older Phase D in the historical roadmap remains the legacy compatibility and historical migration phase; it is not this Stage D.

Stage D is organized as eight deliverable phases, P17–P24. Each phase must preserve the current Runner, CLI, protected Wi-Fi test IDs, topology identifiers, capture lifecycle and explicit provisioning philosophy.

## Stage C completion carried into Stage D

- P10 Windows private-directory ACL enforcement is now implemented: new private directories receive a protected current-user-only ACL; existing paths are read and verified; unavailable PowerShell or any unverified ACL fails closed.
- P13's published configuration assignment continues to represent desired state. Stage D P24 supplies the explicit provider apply/reconciliation seam; no physical device is configured by merely viewing or assigning a profile.
- P16 publishes and pins the selected policy revision ID and SHA-256 hash at Run launch. Evaluation of collected Run metrics and persistent policy-result evidence remain the separate Stage E P28 integration gate.

## Phase definitions and status

| Phase | Scope | Exit criteria |
|---|---|---|
| P17 | Device Inventory Domain and API | Project/Lab-scoped records, validated endpoint/capability metadata, opaque credential references, archive lifecycle, audit and RBAC |
| P18 | Device Management Frontend | Project/Lab filtering, inventory CRUD/archive, capabilities, visible IDs and OS-vault credential linking |
| P19 | Canonical Topology Model | Versioned topology profiles and immutable revisions, validated nodes/ports/links, canonical JSON and SHA-256 |
| P20 | Visual Topology Canvas — Node Management | Read/write draft canvas, node palette, selection, labels and persisted coordinates |
| P21 | Interface, Port and Link Editor | Adapter/port-aware links, endpoint/port uniqueness, link validation and visual connection state |
| P22 | GNS3 Provider — Node Lifecycle | Local/private GNS3 endpoint binding, authenticated project/template/node discovery, explicit create/start/stop and sanitized errors |
| P23 | GNS3 Provider — Link Lifecycle | Port occupancy inspection and explicit, idempotent GNS3 link creation; no implicit disconnection or deletion |
| P24 | Topology Apply and Reconciliation | Dry-run plan, explicit confirmation, project/Lab lock, apply record, observed-vs-desired report and controlled configuration application |

### P17 — Device Inventory Domain and API

Delivered in the first Stage D source slice. Managed devices are separate from the legacy configs/devices.yaml inventory so existing test IDs, config keys and command-line behavior remain stable. Each record belongs to one Project and one Lab; keys are unique within that Lab. Hosts, ports, types, capability flags and metadata are validated. Secret-shaped metadata is rejected. An attached credential must be an ACTIVE managed credential for the same Project and exact Device ID. Database rows contain only the opaque credential reference.

### P18 — Device Management Frontend

Delivered in the first Stage D source slice. The React workspace filters inventory by Project and Lab, registers devices, displays full Device IDs, and archives records without deleting their audit history. Device credentials are created through the existing Credentials page and then linked by opaque ID. Registration never opens a network connection or changes device state.

### P19 — Canonical Topology Model

Implemented: additive Alembic migration `20261115_12` adds Project/Lab topology profiles and immutable revisions. Canonical JSON is normalized before hashing with SHA-256. Validation enforces stable logical node/link IDs, supported node types, provider template references, bounded coordinates, valid endpoints, adapter/port ranges, occupied-port uniqueness and secret-shaped property rejection. Published revision content cannot be edited or deleted; changes create a new draft revision. Topology JSON never contains a credential or secret.

### P20 — Visual Topology Canvas

Implemented: React Topology Studio provides a local SVG canvas, node palette, node selection, drag positioning, labels, template references and immutable revision save. Canvas edits remain local until a draft revision is saved. Opening, dragging, previewing and publishing do not contact GNS3. Stable logical node IDs remain independent of provider-generated IDs.

### P21 — Interface, Port and Link Editor

Implemented: the canvas includes an explicit link editor for source/target logical node, adapter and port. The canonical service validates both endpoints, rejects self-links and enforces one link per adapter/port. Link edits are part of the next immutable draft revision; published revisions remain unchanged.

### P22 — GNS3 Provider — Node Lifecycle

GNS3 is a provider adapter, not the topology authority. A Lab binding stores a private/local endpoint, remote GNS3 project ID and an opaque Credential Vault ID. No provider password or token is stored in SQLite, topology JSON, logs or API responses. Project/template/node discovery is read-only. Creating, starting or stopping nodes requires an explicit permission and action. The adapter uses argument-safe HTTP requests, bounded response sizes and sanitized errors.

### P23 — GNS3 Provider — Link Lifecycle

Before creating a link, the provider adapter observes current nodes/links and checks adapter/port occupancy. It creates only links missing from the observed state and treats already-present links as reconciled. It does not silently unlink, rewire or delete resources. Provider-generated IDs are stored only as mapping/evidence associated with the apply record, never substituted for stable logical IDs.

### P24 — Topology Apply and Reconciliation

Apply begins with a non-mutating plan showing the selected immutable revision, provider binding, missing nodes, missing links and unresolved conflicts. Applying requires Project-scoped topology.apply permission, a CSRF-protected idempotent mutation, explicit confirmation and a lab-scoped resource lease. The apply record captures the revision ID/hash, observed provider facts, operations and sanitized outcome. Reconciliation reports drift; it never prunes unowned provider resources or applies configuration simply because the dashboard loaded.

Configuration deployment is restricted to supported device/configuration adapters and validated schema IDs. Unsupported schema, device type, credential binding or command mapping fails before network writes. Device configuration apply is explicit, serialized per device and recorded for audit/verification; arbitrary YAML or shell-command interpolation is not a configuration transport.

## Security and compatibility invariants

1. Global and Project permissions remain intersected at the Flask API boundary; the UI is not an authorization boundary.
2. Credential values are resolved only at the adapter boundary from the OS vault. Secret values are never returned, serialized or logged.
3. Provider endpoints are restricted to loopback/private/link-local addresses, with no URL user-info, query or fragment credentials.
4. Browsing, editing, saving, publishing, previewing, or launching an ordinary validation Run never provisions GNS3 resources.
5. Apply is explicit, idempotent, audited and Lab-locked. Stop is explicit. No implicit destructive pruning or deletion exists.
6. wifi_lab_reprovision_robust.sh, pytest CLI commands, node IDs, protected captures and LabController remain compatible.
7. Hardware-free tests and mocked provider responses validate source behavior only. Protected GNS3/live Wi-Fi provider acceptance remains an operator-run lab gate.

## Current delivery checkpoint

- P17 Device Inventory Domain/API: implemented in Stage D commit 1.
- P18 Device Management Frontend: implemented in Stage D commit 1.
- P19 Canonical Topology Model: implemented and regression-tested.
- P20 Visual Topology Canvas: implemented as a local-only authoring surface.
- P21 Adapter/Port/Link Editor: implemented with server-side port-occupancy validation.
- P22–P24 GNS3 provider lifecycle, topology apply/reconciliation and controlled device configuration: implemented, including dashboard REST routes, frontend API methods, provider workflow UI, idempotency and route-level mocked integration coverage. CI validates the provider contracts and dashboard wiring; it does not substitute for live GNS3/OpenWrt hardware acceptance. Windows lock portability remains a separate platform-release gate.
