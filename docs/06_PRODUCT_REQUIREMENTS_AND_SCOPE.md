# NetRegress Product Requirements and Scope

**Programme baseline:** `3b8e5504b3824401a22e774ff1e37b2b253474a6`  
**Status:** Expansion programme P00 baseline prepared; detailed implementation phases remain staged.

## 1. Product direction

NetRegress is being extended from its existing local-first Wi-Fi/network validation Runner into a coherent network engineering, emulation and automation platform. This programme is additive. It does not replace the existing Runner or its established delivery history.

The expanded product should let an engineer organize Organizations, Projects and Labs; design topologies; connect supported emulator or Linux-native environments; provision nodes and links; manage devices and credentials; represent vendor-neutral network intent; generate vendor-specific configuration; orchestrate infrastructure and device automation; execute versioned workflows; and inspect live operational state, validation results and evidence.

The platform remains an API-first modular monolith in the existing Tauri + React + Flask application. SQLite and Alembic remain the local product persistence foundation. Provider and vendor differences are isolated behind service/adapter boundaries rather than duplicated in pages or the canonical domain.

## 2. Current programme scope

| Capability | Current programme treatment | Existing foundation at baseline |
|---|---|---|
| Identity, authentication and RBAC | Preserve and extend | Implemented |
| Organization / Project / Lab workspace | Preserve and make globally navigable | Implemented |
| Credential Vault | Preserve; adapters resolve opaque references only | Implemented |
| Device Inventory | Extend for engineering capabilities and observed state | Implemented |
| Configuration profiles and revisions | Extend with vendor-neutral intent binding | Implemented |
| Topology Studio | Upgrade visual editor; retain canonical model and immutable revisions | Implemented foundation |
| GNS3 | Retain as reference provider; consolidate behind common contract | Existing provider operations |
| CML | Add provider adapter after contract qualification | Planned |
| EVE-NG | Add provider adapter after contract qualification | Planned |
| Packet Tracer | Compatibility/import-export bridge, not presumed remote provider | Planned |
| Linux-native environments | Add supported adapter(s) with explicit capability reporting | Partial foundations exist |
| Vendor-neutral network intent | Introduce as a separate domain from CLI/config output | Planned |
| Vendor configuration adapters | Add independently testable adapter packages | Planned |
| Ansible | Device configuration/management execution engine | Planned |
| OpenTofu | Infrastructure lifecycle engine | Planned |
| Visual pipelines | Extend existing persistent PipelineService and handlers | Existing pipeline foundation |
| Telemetry, packet capture and evidence | Extend current provenance-aware services and immutable evidence | Existing foundation |
| Operations dashboard | Aggregate real Project/Lab/provider/device/pipeline/run observations | Read-only Project/Lab overview with source timestamps and subsystem RBAC; live provider health and performance remain unavailable until actually observed |
| AI/LLM/agent functions | Explicitly excluded from this programme | Future scope only |

## 3. Initial network and device coverage

The initial logical node palette should include routers, switches, firewalls, wireless access points, servers, endpoints and network utilities. Examples of logical implementations include Cisco, Arista, Juniper, FRR, VyOS, Open vSwitch, Linux firewall, OpenWrt, hostapd, Linux/Ubuntu, Windows clients, NAT, bridge, cloud and network segments.

A logical node type is not a provider template. The selected provider's catalogue and capability report determine whether a specific image/template can instantiate that logical node.

Initial network intent coverage is deliberately bounded:
- IPv4 and IPv6 addresses, subnets and gateways.
- VLANs, access/trunk ports and interface administration state.
- Static routing, basic OSPF and basic BGP where the target supports them.
- LACP/port aggregation where supported.
- Firewall zones and basic access rules.
- DHCP/DNS configuration references.
- Linux bridges and VLAN interfaces.

The programme must report platform/version capability rather than implying that every feature is portable to every vendor/model/image.

## 4. Product-wide acceptance principles

1. Existing working Run, Attempt, Evidence, Regression, performance, Wi-Fi capture, device inventory, topology revision and GNS3 workflows remain regression-protected.
2. NetRegress owns canonical topology and network-intent revisions. Provider IDs are mappings, never replacements for logical IDs.
3. Provider-specific behavior remains within provider adapters. Unsupported operations return typed capability errors.
4. Every interactive action uses a real backend contract. A visible control must not imply an operation that the backend cannot execute.
5. State changes require project/lab authorization, explicit confirmation where applicable, idempotency and audit.
6. Provider/controller state is read back after mutations. Uncertain outcomes require inspection and recovery, never blind retry.
7. Secrets remain in the existing Credential Vault/OS secret store. SQLite, topology JSON, pipeline definitions, generated files, browser state and logs contain references or redacted output only.
8. Definitions and revisions are immutable once published; plans, execution results and evidence are traceable to revisions and hashes.
9. Measurements retain source, unit, timestamp, environment identity and collection policy. Unknown values remain unavailable; no synthetic online state or fallback telemetry.
10. Prefer open-source components and legitimate free editions. Track image licensing, redistribution restrictions and tested versions; zero-cost does not grant rights to redistribute vendor images.
11. Hardware-free mocks validate contracts only. They never certify live providers, physical RF, device firmware or actual packet captures.

## 5. Explicit exclusions

No AI model runtime, inference package, LLM API, agent framework, AI-specific schema/table, Copilot, autonomous troubleshooting, AI-generated configuration or AI-driven terminal execution is to be added in P00–P17. No speculative AI placeholder interfaces are required.

No provider image, vendor OS image, Packet Tracer executable or commercial simulator licence may be redistributed unless its terms explicitly permit it.

## 6. Initial batch: product foundation

The first product-expansion batch is P00–P03:

- **P00 — Requirements and architecture freeze:** complete repository/module/API/test inventory, requirement traceability and decisions.
- **P01 — Unified design system and application shell:** reconcile tokens, typography, navigation and global Organization/Project/Lab/provider context without changing business logic.
- **P02 — Operational overview:** aggregate persisted Project/Lab/device/provider/pipeline/run observations with source timestamps; unavailable data remains unavailable.
- **P03 — Visual Topology Studio:** complete the existing editor with accessible node/link inspectors, multi-selection and group movement, adapter/port link editing, canvas search/navigation, copy/paste with stable logical-ID remapping, undo/redo, keyboard interaction and canonical backend validation. Retain the existing Project/Lab topology model, immutable revision/hash lifecycle and separate explicit provider plan/apply flow; editing, validation, saving and publishing must never provision or mutate provider resources.

P01–P03 are not accepted merely because the pages render. Their backend contracts, RBAC, loading/error/empty states, responsive behavior, integration tests and preservation tests must pass.

## 7. Requirement status vocabulary

Use only explicit statuses: `PLANNED`, `IN_PROGRESS`, `BACKEND_COMPLETE`, `FRONTEND_COMPLETE`, `INTEGRATION_COMPLETE`, `ACCEPTED`, `BLOCKED` and `DEFERRED`. Do not call a module complete until its defined acceptance evidence exists.
