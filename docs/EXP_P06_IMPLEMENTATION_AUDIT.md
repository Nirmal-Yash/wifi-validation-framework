# EXP-P06 implementation audit — Cisco Modeling Labs adapter

## Delivered behavior

- Added the CML REST adapter as an independent ProviderAdapter implementation. It uses the shared bounded provider HTTP session, TLS verification, private/local endpoint policy, response-size bounds, strict timeouts, redirect rejection and disabled ambient proxy inheritance.
- Implements authentication, authenticated user/session verification, system version/health, user-visible lab catalogue and create/delete, node-definition catalogue, image-definition observations, compute-host/licensing observations, node CRUD, start/stop with state read-back, interface discovery, link create/delete and observed topology.
- The adapter uses CML's separate node-definition and image-definition concepts. Missing or permission-restricted compute, licensing or image details remain UNKNOWN/RESTRICTED observations; they are not inferred from an inaccessible API.
- Generalized the existing GNS3 binding record with provider identity and workspace ID while retaining the existing binding table and gns3_project_id compatibility alias. Credential material remains inside CredentialVaultService.use_secret.
- Topology planning, apply, node lifecycle, interface inspection, read-back and reconciliation use the selected provider ID and provider workspace through the existing immutable topology and lock boundaries.
- The application-scoped registry registers GNS3 and CML independently. Unsupported provider operations remain typed capability errors; state changes remain capability-gated and explicitly confirmed by the existing topology operation APIs.

## Compatibility and migration

- Additive Alembic migration 20261122_16 adds provider_id and provider_workspace_id columns to gns3_lab_bindings. Historical GNS3 rows are backfilled as provider_id=gns3 and provider_workspace_id=gns3_project_id. No second connection table is created.
- gns3_project_id remains mirrored for the older UI/client and existing database readers. New APIs accept provider_id/provider_workspace_id; GNS3 clients may continue to send gns3_project_id.
- GNS3 retains its original adapter, protected Wi-Fi provisioning and session contract.

## Verification and acceptance boundary

- Deterministic CML HTTP/session fixtures cover authentication, catalogues, resource/licensing/image observations, lab/node/link lifecycle, interface mapping, read-back and restricted/unknown observations.
- CI is the software acceptance mechanism. This audit does not claim connectivity to a live CML deployment, a licensed image catalogue, actual node boot or packet capture. Those require a controller URL, operator credential and licensed lab at runtime.