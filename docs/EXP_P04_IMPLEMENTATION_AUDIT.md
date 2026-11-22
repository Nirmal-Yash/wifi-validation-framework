# EXP-P04 — Common Provider Contract and Capability Registry Audit

## Phase objective

Establish one provider-neutral adapter contract and explicit capability registry for topology/emulator providers. The phase is additive to the existing Runner and must not replace topology, Project/Lab, credential, apply, lock or reconciliation ownership.

## Existing implementation reused

- \`lib/services/gns3_provider.py\` remains the bounded GNS3 Controller REST client. Endpoint restrictions, TLS verification, timeouts, response-size limit, redirect handling and sanitized transport errors are retained.
- \`TopologyApplyService\` remains the authority for Project/Lab binding, topology apply planning, revision-hash confirmation, resource locking, immutable apply records, provider mappings, read-back, reconciliation and recovery.
- \`gns3_lab_bindings\` remains the durable connection record with Project/Lab foreign keys, Device and Credential Vault references, status constraints, scope triggers and audit events.
- \`CredentialVaultService.use_secret\` remains the only boundary that supplies provider credential material to the adapter factory.

## Contract and registry

- \`ProviderAdapter\` defines controller version, project/template discovery, node/link reads, node/link creation and explicit node lifecycle methods.
- \`ProviderCapability\` declares stable capability ID, display metadata, mutation classification and confirmation requirement.
- \`CapabilityRegistry\` owns the known capability definitions; \`ProviderRegistry\` owns application-scoped descriptors/factories, checks adapter method conformance and rejects unregistered providers or unsupported capabilities with typed errors.
- GNS3 is the only registered adapter. The contract does not claim support for CML, EVE-NG or Packet Tracer.

## Capability set

| Capability | GNS3 in this phase |
|---|---|
| controller.version.read | Supported |
| projects.read | Supported |
| templates.read | Supported |
| topology.nodes.read | Supported |
| topology.links.read | Supported |
| topology.nodes.create | Supported; explicit apply boundary retained |
| topology.links.create | Supported; explicit apply boundary retained |
| topology.nodes.start | Supported; read-back required |
| topology.nodes.stop | Supported; read-back required |

The registry is a declaration of tested adapter operations, not a statement that a controller is currently reachable or that a particular Lab is healthy.

## Provider connection projection

\`ProviderConnectionRecord\` maps the existing GNS3 binding into provider-neutral names: connection ID, provider ID, Project/Lab IDs, endpoint, provider workspace ID, controller Device ID, opaque Credential Vault reference, status and audit timestamps/actors. No password, API token or secret field is copied. There is no parallel table and no P04 database migration.

## API contract

- \`GET /api/v1/providers/registry?project_id=...\` requires \`topology.read\` for the selected Project.
- Response contains registered provider descriptors/capabilities and persisted connection projections visible in that Project.
- Discovery is local/read-only. It does not contact a provider controller, resolve a Vault secret or infer connection health.
- Existing \`/labs/{lab_id}/provider-binding\` and \`/labs/{lab_id}/provider-catalog\` routes remain compatible. Provider catalogue adds descriptor/connection metadata.

## Security and safety

- Adapter construction uses the existing transient Vault secret callback.
- The API response only contains an opaque credential reference ID.
- Adapter operations are capability-checked.
- Topology apply still requires the existing published-revision SHA-256 and explicit confirmation, holds the existing Lab lease, records uncertain/partial outcomes, and reconciles actual provider read-back.
- Project authorization remains server-enforced; registry discovery does not widen provider or Lab access.

## Automated verification

\`tests/test_provider_contract.py\` covers stable capability metadata, duplicate/unknown capability handling, unknown providers, missing contract methods, GNS3 reference registration and secret-free connection projections. Existing \`tests/test_topology_apply.py\` continues to exercise the mocked GNS3 lifecycle, idempotent apply, conflicts, recovery, reconciliation and API behavior. OpenAPI tests assert the new read-only Project-scoped route.

Hosted quality status is determined from the exact commit's GitHub Actions results. These software tests do not replace live GNS3 Controller acceptance, which remains a separately evidenced operator gate (RQ-042).

## Exact hosted verification record

- Commit: `13fd8df0d5326a1fe34adff65938c076eeabc5c0`
- Quality workflow: [45028046927](https://github.com/Nirmal-Yash/wifi-validation-framework/actions/runs/45028046927) — completed successfully, 3/3 jobs PASS
- Backend correctness/session/RBAC/API contract suite: **584 passed, 7 skipped**
- Repeated Linux locking/process/recovery reliability suite: **108 passed**
- Frontend tests and production build: PASS
- Dashboard launcher/proxy/authenticated-session smoke: PASS
- No live GNS3 controller or physical Lab was operated; external acceptance remains explicitly gated under RQ-042.
