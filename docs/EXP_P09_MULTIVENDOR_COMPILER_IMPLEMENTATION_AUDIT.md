# EXP-P09 — Multi-Vendor Configuration Compilation and Adapter Architecture

## Implementation summary

P09 adds a dedicated configuration-compiler domain in `lib/network_config/`, independent from the existing emulator/topology provider registry. It compiles immutable P08 Network Intent revisions into deterministic, vendor-specific text previews. It does not configure devices.

## Architecture

- `contracts.py`: immutable adapter, artifact and diagnostic contracts plus a typed compiler protocol.
- `registry.py`: explicit platform-family recognition, Device vendor/model corroboration and software-version gates.
- `adapters.py`: five independent native rendering adapters.
- `NetworkIntentCompilerService`: published-revision/hash/capability validation, target resolution, atomic multi-target staging, output hashing, baseline diff and bounded artifact handling.
- API: adapter catalogue and immutable revision compile-preview endpoints.
- Frontend: catalogue, published-revision compile action, artifact and diff display, blocker diagnostics.

## Registered adapter matrix

| Adapter | Tested software range | v1.0 compiled scope | Explicit exclusions |
|---|---|---|---|
| Linux + FRRouting | FRR 7–10 | systemd-networkd interfaces, bridge/bond/VLAN, static routes, OSPF/OSPFv3, BGP, nftables zone rules | DHCP/DNS profile values unresolved |
| Cisco IOS/IOS-XE | IOS 15.x; IOS-XE 16.x–17.x | routed/access/trunk, VLAN, IPv4/IPv6 static route, OSPF/OSPFv3, BGP, LACP, basic zone firewall ACL policy | IPv6 ACL translation |
| Arista EOS | EOS 4.x | interfaces, VLANs, IPv4/IPv6 static routing, OSPFv4, BGP, LACP | OSPFv3 and stateful firewall zones |
| Juniper Junos | Junos 18.x–24.x | hierarchical set syntax, inet/inet6 static routes, OSPF/OSPFv3, BGP, LACP, SRX security zones/policies | non-SRX firewall; non-default canonical route metrics |
| Palo Alto PAN-OS | PAN-OS 10.x–12.x | routed Ethernet, IPv4/IPv6 static route, OSPFv4, BGP, aggregate Ethernet, zones/security rules | generic ACCESS/TRUNK, OSPFv3, unresolved DHCP/DNS; no NAT model |

The registry does not infer hardware capabilities from a product name alone. It requires the latest P08 adapter-observed capability report, then verifies platform family and software major version. It also corroborates Device vendor and Cisco model family. Required features must explicitly be reported SUPPORTED and must be part of the selected adapter's implemented feature set.

## Compilation contract

- Only an ACTIVE profile and immutable PUBLISHED intent revision can compile.
- P08 revalidation must report structural validity and `ready_for_compilation`.
- Intent SHA-256 and pinned topology content SHA-256 must match the stored immutable revision.
- Every bound target must be an ACTIVE Device in the same Project and have a current report.
- A blocker on any target or feature yields `status=BLOCKED` and `artifacts=[]`; no partial configuration set is returned.
- Successful preview is deterministic for the same revision, compiler version, adapter descriptors and output.
- Every artifact contains a confined relative path, text content, SHA-256, change classification and optional unified diff.
- Baseline paths, content size, secret-like content, number of artifacts and aggregate output size are bounded.
- The baseline is in-memory request data; no compilation/artifact is persisted.

## API and UI

- `GET /api/v1/network-intent/compiler/adapters?project_id=...`
- `POST /api/v1/network-intent/profiles/{profile_id}/revisions/{revision_id}/compile`
- Optional `baseline_artifacts` maps relative file paths to text for diff preview.
- Project RBAC is enforced by the backend (`network_intent.read` for catalogue; `network_intent.manage` for compilation).
- The Network Intent page shows all registered adapters and renders the compile result for the selected PUBLISHED revision.

## Safety and scope boundaries

This implementation opens no SSH, Telnet, HTTP API or provider session. It does not read credentials, execute generated commands, write configuration, perform commit/rollback, run a syntax checker against a device, read back running state, or claim an apply succeeded. Returned content is a preview only, with fixed `application_performed=false` and `ready_for_application=false`.

Real live capability collection, platform-native configuration syntax validation, Junos candidate/commit-check, device application, read-back/reconciliation, and P10 Ansible execution remain separate acceptance gates. The compiler currently relies on valid P08 adapter-observed capability reports; it does not manufacture or simulate them.

## Automated tests added

The focused `tests/test_network_intent.py` suite covers platform recognition, vendor/model corroboration, software gates, platform feature boundaries, deterministic IOS-XE compilation and baseline diff, refusal to compile drafts, all-or-nothing behavior, injection/path safety, Linux FRR IPv6/systemd previews, Arista/Junos/PAN-OS outputs and API previews. Frontend coverage exercises catalogue and published-revision compilation preview. This does not replace lab/hardware acceptance against each claimed OS release.
