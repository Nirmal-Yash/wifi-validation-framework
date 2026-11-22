# EXP-P05 — GNS3 Provider Consolidation Audit

## Phase objective

Make the existing GNS3 integration the first production-shaped implementation of the common provider contract. Reuse the single bounded GNS3 HTTP adapter and existing topology/apply and Wi-Fi provisioning behavior. Do not introduce a second GNS3 client, a parallel binding table, a second topology authority or an alternate secret path.

## Existing implementation retained

- `lib/services/gns3_provider.py` remains the sole GNS3 Controller HTTP implementation. Its private/local endpoint policy, remote-private HTTPS requirement, TLS verification, disabled environment-proxy inheritance, bounded timeouts and response size, redirect rejection, safe identifier encoding and sanitized transport errors remain unchanged.
- `TopologyApplyService` remains the authority for Project/Lab binding, immutable logical topology revisions, provider template mapping, conflict-safe adoption, resource locking, revision SHA-256, idempotent apply, actual read-back, reconciliation, apply history and partial/uncertain-operation recovery.
- `gns3_lab_bindings` remains the only persisted provider connection authority. No migration or duplicate connection/resource mapping table is introduced.
- `CredentialVaultService.use_secret` remains the only boundary that supplies provider credential material. Only opaque Credential Vault references remain in persisted binding metadata and provider connection projections.

## Common session lifecycle

`lib/providers/session.py` introduces `ProviderSessionService`. It uses the application-scoped `ProviderRegistry` to construct the selected adapter inside the Vault callback, passes the transient credential only to the adapter constructor, calls `connect()`, invokes the operation, and pairs it with `disconnect()`. A cleanup failure does not mask the original provider or operation exception.

`TopologyApplyService` delegates provider work to this service. Dashboard construction injects the same registry and session-service instance into `WiFiLabProvisioningService`; the pipeline runtime also shares the topology service's objects. The Wi-Fi path no longer instantiates a standalone GNS3 client or calls the Vault independently. Its existing additive-only management-link operation, port selection, start order, node-state read-back, audit event, Lab lock and postcondition check are retained.

## Adapter readiness and observations

The GNS3 adapter now returns the explicit template metadata required to identify template type, assigned compute and declared image fields. It adds two read-only common-contract operations:

| Operation | Controller read | Projection / behavior |
|---|---|---|
| `get_resource_availability()` | `GET /v2/computes` | Compute ID/name, nullable connected observation, valid bounded CPU/RAM utilization percentages and timestamp. Host details and provider error strings are not returned |
| `get_template_image_availability(template_id)` | `GET /v2/templates/{template_id}`, then `GET /v2/computes/{compute_id}/{emulator}/images` where supported | Built-ins are `NOT_REQUIRED`; required images are compared by filename; explicit missing images are `MISSING`; incomplete or unsupported metadata stays `UNKNOWN` |

Unknown values are never promoted to available. A template not in the observed catalogue is represented as unavailable without attempting a detail lookup. Dry-run compatibility reports contain logical node, provider template, assigned compute connection state, image status and any missing-image names. A node slated for creation is blocked when its assigned compute is explicitly disconnected or its required image is explicitly missing. Existing observed mapped nodes are not falsely blocked solely because template image metadata is unknown or no longer needed for recreation. The confirmed apply path repeats the resource and image observation immediately before mutation.

The provider snapshot also includes a node-lifecycle count and adapter-level capture support. Capture support is capability metadata only; actual capture readiness remains link/compute-specific and no capture is claimed as executed.

## Project, template, interface and UI integration

- Provider catalogue continues to return actual projects, templates, nodes and links and now adds compute availability, lifecycle counts and capture capability.
- After the initial manual controller binding, the binding form can select a project from the discovered controller catalogue; manual project-ID entry remains available for initial bootstrap.
- Dry-run console shows per-node template, compute and image compatibility, clearly retaining `UNKNOWN` states and missing-image blockers.
- A read-only `GET /api/v1/labs/{lab_id}/provider-nodes/{provider_node_id}/interfaces` route verifies the provider node exists in the bound project before returning observed adapter and port values. It requires Project-scoped `topology.read`.
- Existing provider synchronization status is the actual dry-run/reconciliation result. Existing `/topologies/{profile_id}/applies` history remains the durable record of provider topology apply and recovery operations; browser session logs are not represented as audit history.

## Security and mutation controls

- Binding reads and writes remain Project/Lab scoped and use the existing controller Device and API_TOKEN Credential Vault references.
- Catalogue, compute, image and interface discovery are read-only.
- Provider IDs are resolved through the common registry. Unsupported capabilities fail through the registry contract rather than silently succeeding.
- Node/link creation still requires the existing dry-run conflict-free plan, published revision, unchanged SHA-256, explicit confirmation, resource lease, idempotency and provider read-back.
- Existing topology apply does not gain any delete/prune behavior.
- Wi-Fi provisioning still never deletes resources, stops nodes or disconnects/rewires an existing link.
- Only bounded provider observation fields are serialized; no credential value, controller hostname or provider diagnostic text is returned by the new resource-availability projection.

## Files and focused verification

Implementation touches the provider contract/registry/session service, the existing GNS3 adapter, topology and Wi-Fi provisioning services, dashboard/pipeline composition, topology API and frontend, OpenAPI, and provider/apply contract tests. No database migration is required.

Focused automated coverage verifies:
- the expanded structural adapter contract and stable capability metadata;
- authenticated template detail, compute inventory and image availability reads through a deterministic HTTP fixture;
- omission of provider host/error details from compute projections;
- the Vault callback, adapter creation, connect/callback/disconnect order and disconnect on callback failure;
- shared registry/session use by topology and Wi-Fi provisioning;
- missing image blocks new node creation without mutating the controller;
- template and compute compatibility is visible in dry-run; unknown readiness remains unknown;
- observed interfaces require an actual node in the bound provider project;
- Project/Lab-scoped interface API access and safe responses;
- existing apply, repeatability, logical/provider mappings, safe resource adoption, link-port conflicts, hash confirmation, drift detection, node lifecycle read-back and partial timeout recovery.

The hosted quality-gates workflow explicitly runs the provider-contract, topology-apply and OpenAPI contract suites. The exact Phase 5 commit result is recorded in the final implementation checkpoint after CI completes.

## Acceptance boundary

A green hardware-free workflow proves software contract, integration and regression behavior only. It does not prove connectivity to a user's live GNS3 controller, that a particular compute has its required disk image, actual node/link creation or deletion, packet capture, a working existing live lab after upgrade, or physical Wi-Fi/mac80211_hwsim operation. Live controller and Wi-Fi qualification must run in the approved environment and remain RQ-042; no live provider acceptance is asserted by this audit.
