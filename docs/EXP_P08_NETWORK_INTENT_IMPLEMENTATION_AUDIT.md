# EXP-P08 implementation audit — canonical Network Intent and Device Capability Model

**Baseline:** `0bd9a9efeca258d28cccf8b1d4295c2c6c5045d0`  
**Migration:** `20261123_18` (schema version 28)  
**Requirement:** RQ-021  
**Status:** READY_FOR_CI; exact-main CI pending

## Objective and domain boundary

P08 introduces a vendor-neutral desired-state domain independent of canonical visual topology profiles/revisions, existing Wi-Fi typed configuration schemas and profile lifecycle, provider-specific controller resource IDs, rendered vendor CLI/configuration, Ansible execution and OpenTofu infrastructure lifecycle.

A Network Intent profile is Project/topology-profile bound and inherits the topology's Project/Lab scope. A revision references one immutable topology revision and stores the topology SHA-256 at authoring time. The intent revision carries its own canonical SHA-256, schema version, provenance, parent revision and DRAFT/PUBLISHED lifecycle.

Published topology and intent revisions are immutable. Rollback creates a new DRAFT revision with a parent reference and source provenance; it never edits history.

## Schema v1.0

The strict v1.0 JSON model includes logical target bindings to managed Device records; IPv4/IPv6 segment CIDRs and VLAN identifiers; interface admin state, ROUTED/ACCESS/TRUNK mode, IPv4/IPv6 interface addresses and VLAN membership; IPv4/IPv6 static routes with same-family next hop, metric and optional interface; OSPF process/router ID/area/network definitions; BGP local ASN/router ID/neighbors and remote ASNs; LACP ACTIVE/PASSIVE interface aggregation; firewall zones bound to declared interfaces and basic ALLOW/DENY rules (ANY/TCP/UDP/ICMP, CIDRs, TCP/UDP destination ports); published Project-owned DHCP/DNS configuration profile/revision references; Linux bridge members and Linux VLAN interfaces.

Unknown fields and schema versions fail closed. Canonical ordering is normalized before hashing. Validation includes CIDR/IP-family checks, numeric bounds, unique identifiers, declared logical-node/interface/zone/segment cross-references, Project/Lab boundary checks, and rejection of inline secrets. Intent does not contain vendor commands, provider instance IDs or secret material.

## Capability observations

The additive `device_capability_reports` table stores immutable observations by Project and managed Device. Report content includes provider/platform/software version, adapter name/version, source type (PROVIDER_ADAPTER or DEVICE_DISCOVERY), normalized feature status/constraints, canonical SHA-256, observed/recorded timestamps and actor provenance.

The feature vocabulary used by v1.0 is:
`addressing.ipv4`, `addressing.ipv6`, `interfaces.admin_state`, `vlans.access`, `vlans.trunk`, `routing.static_ipv4`, `routing.static_ipv6`, `routing.ospf`, `routing.bgp`, `aggregation.lacp`, `firewall.zones`, `firewall.basic_acl`, `services.dhcp`, `services.dns`, `linux.bridge`, and `linux.vlan_interface`.

Only the internal service method `record_capability_report` writes these records. There is no public endpoint or UI control for a person to mark a capability as supported. A report without a provider identity for PROVIDER_ADAPTER source is rejected. The report is tied to an active Device in the declared Project.

Capability evaluation treats missing reports/features as UNKNOWN, explicitly unsupported features as INCOMPATIBLE, and blocks publication when a required feature is not observed as SUPPORTED. Observations older than seven days or more than five minutes in the future are treated as UNKNOWN. Capability report and intent-revision JSON hashes are checked when read. The report hash and exact adapter/platform/software provenance are retained for audit and future re-validation.

P09 provider/device adapters must call this service only after actual capability discovery. The P08 implementation does not claim that GNS3, CML, EVE-NG or physical network devices have already supplied live capability reports.

## Persistence and lifecycle

Migration `20261123_18` adds:
- `network_intent_profiles` — Project/topology binding, inherited scope, unique name and active/archive state;
- `network_intent_revisions` — strict schema version, topology revision ID/hash, canonical definition/hash, provenance, parent and immutable publication lifecycle;
- `device_capability_reports` — append-only adapter/discovery observations and hashes.

Foreign keys, CHECK constraints, indexes and triggers validate Project/topology/Lab scope, revision/topology binding, same-profile parent revision binding, immutable profile ownership, content immutability, published-revision immutability and no-delete policy. Schema contracts and legacy forward-migration fixtures are updated to schema version 28.

The existing topology/configuration domains are not rewritten. No CLI or device configuration is stored in P08.

## API and authorization

The backend routes are GET/POST `/api/v1/network-intent/profiles`, GET `/api/v1/network-intent/profiles/{profile_id}`, GET/POST `/api/v1/network-intent/profiles/{profile_id}/revisions`, POST `/api/v1/network-intent/validate`, POST `/api/v1/network-intent/profiles/{profile_id}/publish`, POST `/api/v1/network-intent/profiles/{profile_id}/rollback`, and GET `/api/v1/devices/{device_id}/capability-reports`.

RBAC permissions are `network_intent.read`, `network_intent.manage` and `network_intent.publish`; capability report reads use `devices.read`. Mutations use the established Project permission, session, CSRF, idempotency and audit-event boundaries. No public write route exists for capability observations.

## Frontend

The `/network-intent` page provides Project scope and topology-profile selection; profile creation and topology-revision selection; a JSON schema v1.0 editor with target logical-node → Device binding helper; structural and optional capability-aware validation diagnostics; immutable DRAFT save, publish and rollback-as-new-draft actions; read-only Device capability provenance/history; read-only RBAC behavior for viewers.

The user interface states explicitly that CLI generation and device changes are outside P08.

## Verification and remaining acceptance

The added `tests/test_network_intent.py` suite covers schema normalization, invalid fields/addresses/VLANs/routes/ASN/secrets, topology-hash pinning, immutable history, Project/Lab boundaries, capability observation provenance, missing/unsupported/stale feature blocking, publication prerequisites, rollback and API/idempotency behavior. The frontend suite exercises profile creation, target mapping, validation, draft/publish/rollback, capability history and read-only permissions. Existing topology, device, configuration, migration and provider tests remain in the central quality run.

Remaining P08/P09 integration gates:
1. Wire real GNS3/CML/EVE-NG/Linux-native discovery flows to `record_capability_report`; do not synthesize observations.
2. Qualify feature IDs and constraints against exact platform/software versions and live devices.
3. Preserve adapter name/version and source timestamp for every real observation.
4. P09 must implement vendor adapters and compare compiled configuration against observed state before any apply.
5. P10 Ansible execution remains out of scope here.

No network-device capability was asserted or fabricated by this P08 source package.
