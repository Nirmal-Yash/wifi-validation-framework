# EXP-P04 — Common Provider Contract and Capability Registry Audit

## Phase objective

Establish one provider-neutral adapter interface and explicit capability registry for topology/emulator providers. The phase is additive and must not replace topology, Project/Lab, credential, apply, lock, reconciliation or recovery ownership.

## Existing implementation reused

- \`lib/services/gns3_provider.py\` remains the bounded GNS3 Controller REST client. Private-endpoint restrictions, TLS verification, request timeouts, response-size limits, redirect rejection, safe identifier handling and sanitized transport errors are retained.
- \`TopologyApplyService\` remains the authority for Project/Lab binding, deterministic topology apply planning, revision-hash confirmation, Lab resource locking, immutable apply records, stable logical-to-provider mappings, provider read-back, reconciliation and recovery.
- \`gns3_lab_bindings\` remains the durable Project/Lab connection record. Its existing foreign keys, controller Device reference, Credential Vault reference, status constraints, scope triggers and audit events are reused.
- \`CredentialVaultService.use_secret\` remains the only boundary that supplies transient provider credential material to the adapter factory.
- No parallel provider-connection table or Alembic migration is introduced. \`ProviderConnectionRecord\` is a provider-neutral typed projection over the existing GNS3 binding; this avoids duplicating connection authority while P04 registers GNS3 as the sole reference adapter.

## Complete common adapter contract

The structural \`ProviderAdapter\` protocol now requires all operations in the approved P04 roadmap:

| Method | Responsibility | GNS3 adapter behavior |
|---|---|---|
| \`connect()\` | Establish/check a provider session | Performs a bounded authenticated controller health check; HTTP sessions remain short-lived |
| \`disconnect()\` | Close provider session | Closes the logical session; per-request HTTP sessions are already closed |
| \`health_check()\` | Check provider availability | Reads controller version and returns a timestamped observation |
| \`get_capabilities()\` | Report supported operations | Returns stable capability IDs and mutation/confirmation metadata |
| \`list_projects()\` | Discover provider projects | Reads controller project catalogue |
| \`create_lab()\` | Create a provider lab | Creates a GNS3 project with validated name/canvas dimensions |
| \`delete_lab()\` | Delete a provider lab after confirmation | Calls the GNS3 project deletion endpoint |
| \`list_templates()\` | Discover node templates | Reads controller template catalogue |
| \`create_node()\` / \`delete_node()\` | Create or remove a node | Uses template mapping and node lifecycle endpoints |
| \`start_node()\` / \`stop_node()\` | Change node state | Explicit start/stop calls; callers must read back actual state |
| \`get_node_state()\` | Observe a node | Reads the node record and bounded interface/port fields |
| \`create_link()\` / \`delete_link()\` | Create or remove a link | Uses provider-native link endpoints |
| \`get_interfaces()\` | Discover interfaces and ports | Projects actual node ports into a stable list |
| \`get_observed_topology()\` | Read actual nodes and links | Reads provider inventory without mutation |
| \`capture_support()\` | Report packet-capture capability | Reports GNS3 link capture support; per-link/compute readiness remains runtime-specific |

A provider must implement the complete interface. If a provider cannot perform an operation, it must raise a typed capability/unsupported-operation error; it must not return a success-shaped fallback.

## Capability model

- \`ProviderCapability\` carries a stable ID, display metadata, mutation classification and explicit-confirmation requirement.
- \`CapabilityRegistry\` owns the authoritative capability definitions and rejects duplicate or unknown IDs.
- \`ProviderRegistry\` owns application-scoped provider factories/descriptors, validates the full structural contract and returns typed errors for unknown providers or unsupported capabilities.
- Descriptors advertise capabilities explicitly; they are not inferred by switching on provider names.
- All destructive or state-changing capabilities (lab/node/link create/delete and node start/stop) are flagged as mutations requiring confirmation.
- GNS3 is the only registered provider in P04. CML, EVE-NG, Packet Tracer and Linux-native adapters are not claimed as implemented.

## Provider connection projection

\`ProviderConnectionRecord\` maps the existing GNS3 binding into provider-neutral fields: connection/provider IDs, Project/Lab IDs, endpoint, provider workspace ID, controller Device ID, opaque Credential Vault reference, status and audit timestamps/actors. It never includes a password, API token or secret value. Existing GNS3 persistence remains the single source of truth.

## Integration and API contract

- \`GET /api/v1/providers/registry?project_id=...\` requires \`topology.read\` for the Project and returns registered descriptors/capabilities plus safe connection projections.
- Existing \`GET/PUT/DELETE /api/v1/labs/{lab_id}/provider-binding\` routes preserve provider connection read/bind/update/archive behavior with Project/Lab authorization and idempotency.
- Existing provider catalogue and topology plan/apply/reconciliation/node lifecycle routes remain compatible.
- \`TopologyApplyService\` now establishes and closes the adapter lifecycle at the Credential Vault boundary and uses \`get_observed_topology()\` for its actual node/link snapshot.
- Apply continues to require a published immutable revision, matching SHA-256, explicit confirmation, conflict-free plan, Lab lease, idempotency, immutable history and actual provider read-back. The new contract does not bypass these protections.

## Security and safety

- The GNS3 adapter accepts only explicit localhost/private controller addresses; non-loopback HTTP is rejected and remote private endpoints require HTTPS.
- Provider IDs and resource IDs are validated and URL-encoded before path construction.
- Requests disable environment proxy inheritance, verify TLS, reject redirects, use bounded connect/read timeouts and cap response bytes.
- Secrets are supplied only inside the Vault callback and are never copied into connection records, adapter descriptors, generated responses or audit metadata.
- Registry discovery is local/read-only and does not contact providers or infer live health.
- Provider connection health is only reported from an actual authenticated health check. A stored binding is not a health observation.
- Destructive provider methods are marked confirmation-required in the capability metadata. Current topology apply/start/stop workflows retain their existing authorization, idempotency, explicit confirmation and recovery boundaries.

## Automated verification

\`tests/test_provider_contract.py\` covers stable/unique capability metadata, duplicate/unknown capability rejection, full adapter conformance, unknown providers, unsupported capabilities, GNS3 registration, safe connection projection and all GNS3 adapter operations through a deterministic in-memory HTTP fixture (no live controller required).

\`tests/test_topology_apply.py\` covers the existing GNS3 binding, Vault callback, Lab lock, idempotent apply, partial/uncertain outcomes, explicit node lifecycle, mappings, reconciliation and API compatibility.

The common provider contract test module is now included explicitly in \`.github/workflows/netregress-quality.yml\`; it is no longer dependent on an incidental import from another test.

## Acceptance boundary

This source phase is integrated as one additive provider-contract increment. Hosted CI for the resulting exact commit is the software acceptance gate. Hardware-free tests do not certify controller connectivity, real GNS3 node/link creation/deletion, packet capture, CML/EVE-NG or physical network behavior. Those must be qualified against the named provider edition/version and approved test Lab under later provider/operator acceptance (RQ-042 and subsequent provider-specific requirements).
