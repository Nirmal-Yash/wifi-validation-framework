# NetRegress Expansion Requirement Traceability

**Baseline:** `3b8e5504b3824401a22e774ff1e37b2b253474a6`  
**Status:** P00 initial source-to-requirement map. Planned expansion requirements remain unimplemented until explicitly tested.

## Status key

- **EXISTING:** relevant source capability is present; its current acceptance boundary still applies.
- **EXTEND:** an existing contract is present but the expansion requirement is not complete.
- **PLANNED:** no qualifying implementation has been identified at this baseline.
- **GATE:** requires operator/provider evidence beyond hardware-free CI.
- **IN_PROGRESS:** source integration and focused acceptance tests are implemented; hosted verification remains pending.
- **CI_VERIFIED:** implementation and focused/hosted automated quality gates pass on the recorded exact commit; separate real-provider and operator acceptance gates remain explicit.
- **READY_FOR_CI:** implementation, focused tests and CI wiring are integrated; the new exact-main hosted workflow has not yet reported its result.
- **EXTERNAL_ACCEPTANCE_PENDING:** source implementation and exact-commit automated quality gates pass, but a licensed native application, live provider or other declared external acceptance gate remains outstanding.

## Product foundation

| ID | Requirement | Current source / contract | Status | Next verification |
|---|---|---|---|---|
| RQ-001 | Tauri desktop host and local React UI | `src-tauri/`, `frontend/src/App.jsx`, `frontend/src/components/layout.jsx` | EXISTING | Keep package lifecycle and route tests green |
| RQ-002 | Flask API and API client | `dashboard/api_v1.py`, `frontend/src/api.js` | EXISTING | Document new endpoints before frontend use |
| RQ-003 | SQLite schema migrations | `alembic/versions/`, `alembic/env.py` | EXISTING | Run Alembic head/drift and upgrade tests locally |
| RQ-004 | Identity/RBAC and workspace boundaries | `lib/services/identity.py`, `lib/domain/resources.py`, workspace APIs | EXISTING | Every new endpoint receives Project/Lab RBAC tests |
| RQ-005 | Credential storage | `lib/services/credential_vault.py`, platform secret-store adapter | EXISTING | Secret references only; never serialize values |

## Workspace, devices and topology

| ID | Requirement | Current source / contract | Status | Next verification |
|---|---|---|---|---|
| RQ-010 | Organization, Project and Lab persistence | `lib/domain/resources.py`, SQLite workspace repositories, `/workspace/*` APIs | EXISTING | Shared shell selector must use authenticated visible scope |
| RQ-011 | Project/Lab device inventory | `lib/services/device_inventory.py`, `frontend/src/pages/devices.jsx` | EXISTING | Extend capabilities only via schema/API migration |
| RQ-012 | Canonical topology and immutable revisions | `lib/services/topology_studio.py`, `frontend/src/pages/topologies.jsx` | EXISTING | Preserve hash, logical IDs and published immutability |
| RQ-013 | Complete visual Topology Studio | `frontend/src/pages/topologies.jsx`, `frontend/src/topology-editor.js`, `TopologyStudioService`, `TopologyApplyService`, `docs/openapi.yaml` | CI_VERIFIED | Exact PR-head workflow `45022564639` on `e1e4519278e84015c96af10c22961764338adf84`: backend, frontend/build and startup/session jobs PASS. Real GNS3 apply/recovery and interactive desktop/accessibility remain RQ-042/RQ-044 operator gates |
| RQ-014 | Topology apply, reconciliation and recovery | `lib/services/topology_apply.py`, `/topologies/*/plan|apply|reconciliation` | EXISTING | No implicit prune; preserve lab lock/idempotency |
| RQ-015 | GNS3 provider operations | `GNS3Provider`, `ProviderRegistry`, `ProviderSessionService`, `TopologyApplyService`, `WiFiLabProvisioningService` | CI_VERIFIED | Exact-main quality workflow `45169392250` on `10d8288eb9c76d4abb5168118019ce6c2960e75e` passed all hosted quality jobs; live lab and Wi-Fi execution remain RQ-042 GATE |
| RQ-016 | CML provider | `lib/providers/cml.py`, `lib/providers/http.py`, `tests/test_stage_b_cml.py`, `TopologyApplyService` | READY_FOR_CI | CML adapter-specific fixture tests are now wired into the central quality workflow; verify them on the new exact-main commit. Live CML controller, licence, image availability and VM boot remain external acceptance |
| RQ-017 | EVE-NG provider | `lib/providers/eve_ng.py`, `lib/providers/http.py`, `lib/providers/registry.py`, `tests/test_stage_b_eve_ng.py` | READY_FOR_CI | EVE-NG adapter-specific fixture tests are now wired into the central quality workflow; verify them on the new exact-main commit. Live edition/licensing, template image availability and node execution remain external acceptance |
| RQ-018 | Packet Tracer native .pkt import, provenance and constrained export bridge | `lib/services/packet_tracer_interop.py`, `topology_native_sources`, multipart import/source/export APIs, `frontend/src/pages/topologies.jsx`, `tests/test_packet_tracer_interop.py` | READY_FOR_CI | P07-B software checkpoint adds bounded .pkt decoding, canonical device/link projection, immutable source-byte/hash provenance, codec read-back and a constrained name/coordinate serializer. Packet Tracer desktop reopen, representative native files from supported releases, full device/config/drawing fidelity and broader version qualification remain explicit external acceptance gates; JSON interchange is not advertised as native support. |

## Network configuration and automation

| ID | Requirement | Current source / contract | Status | Next verification |
|---|---|---|---|---|
| RQ-020 | Existing Wi-Fi configuration profiles and deployment | `lib/services/configuration_profile_service.py`, `lib/services/configuration_deployer.py` | EXISTING | Keep current Wi-Fi schema and deployment behavior |
| RQ-021 | Canonical vendor-neutral network intent and observed device capability model | `lib/services/network_intent.py`, `network_intent_profiles`, `network_intent_revisions`, `device_capability_reports`, `/api/v1/network-intent/*`, `/api/v1/devices/{device_id}/capability-reports`, `frontend/src/pages/network-intent.jsx`, `tests/test_network_intent.py` | CI_VERIFIED | P08 schema v1.0, topology-hash-pinned immutable revisions, immutable capability evidence, seven-day freshness and typed UNKNOWN/INCOMPATIBLE diagnostics passed exact-main quality workflow `45230914785` at commit `2f601b5`. Live device capability collection remains a separately stated limitation; compilation consumes valid adapter-observed reports. |
| RQ-022 | Linux/FRR and network-vendor adapters | `lib/network_config/`, `lib/services/network_intent_compiler.py`, `POST /api/v1/network-intent/profiles/{profile_id}/revisions/{revision_id}/compile`, `GET /api/v1/network-intent/compiler/adapters`, Network Intent frontend preview, `tests/test_network_intent.py` | CI_VERIFIED | P09 compiler registry and all five adapter suites passed exact-main quality and Linux desktop packaging on commit `6655ad2` (runs `45333831657` and `45333831658`). Provides platform/version gates, feature blockers, immutable topology/intent hashes, deterministic output and all-or-nothing previews. Live platform syntax validation, Junos commit-check, PAN-OS API apply, device read-back and physical acceptance remain separate operator gates. |
| RQ-023 | Ansible playbook/inventory execution service | `lib/services/ansible_automation.py`, `ansible_automation_plans`, `ansible_automation_approvals`, `ansible_automation_executions`, P10 Ansible REST endpoints, Network Intent frontend, `tests/test_ansible_automation.py` | CI_VERIFIED | Exact-main commit `d845ea1f8d4d768c431cf45751a36865b499effa` passed full backend, API-security, frontend/build and dashboard/session quality jobs in run `45368016605`; all six focused P10 backend tests passed. Linux desktop packaging run `45368016475` is still pending at pinned Tauri CLI installation. External live-device operator acceptance remains separate. |
| RQ-024 | OpenTofu workspace/state/plan/apply service | No OpenTofu service identified | PLANNED | EXP-P11: protected per-Lab state, locking and approval |

## Operations, pipelines and observability

| ID | Requirement | Current source / contract | Status | Next verification |
|---|---|---|---|---|
| RQ-030 | Persisted pipeline definitions/executions | `lib/services/pipeline_service.py`, pipeline worker and pipeline pages | EXISTING | Extend only with typed/versioned handler contracts |
| RQ-031 | Visual topology-style pipeline canvas | Existing pipeline management page is not yet a full visual workflow editor | EXTEND | Build canvas; do not expose unimplemented steps |
| RQ-032 | Existing Run/Attempt, evidence and regression | `lib/services/run_service.py`, repositories and dashboard query layer | EXISTING | No rewrite; maintain baseline and ownership checks |
| RQ-033 | Existing Wi-Fi telemetry and capture evidence | Existing telemetry/capture/artifact services | EXISTING | Add metrics only with real observation provenance |
| RQ-034 | Cross-domain operations overview | `DashboardQueryService.operations_overview`, `GET /api/v1/dashboard/operations-overview`, `docs/openapi.yaml`, `frontend/src/pages/dashboard.jsx`, `docs/EXP_P02_IMPLEMENTATION_AUDIT.md` | CI_VERIFIED | P02 implementation merged on `1f242cdd7e7c0a6b4634e30840c36ed2e13649b7`; follow-up regression fixes on `dcb8e4ab88b819fef4723c66500d8915942c2bff`; exact current-main quality workflow `45028391952` on `1de4dbbf2a586148aa00352d3f4004e81b1d8354` passes all 3 jobs. Read-only Project/Lab aggregation, independent child-domain RBAC, restricted null shapes, telemetry artifact integrity/provenance and measured sample timestamps are covered. Live provider health, reachability, drift, infrastructure and uncomputed regressions remain UNKNOWN/UNAVAILABLE until observed.
| RQ-035 | Shared Organization/Project/Lab shell context | `frontend/src/components/workspace-context.jsx`, `frontend/src/components/layout.jsx`, existing workspace APIs | EXISTING | Keep per-user reset, cross-page context adoption and Project/Lab scope tests green |

## Acceptance and evidence

| ID | Requirement | Verification source | Status |
|---|---|---|---|
| RQ-040 | Current exact-commit hosted quality gates | Actions run `44359150673` on baseline commit; 3/3 jobs PASS | EXISTING |
| RQ-041 | Current exact-commit Linux package matrix | Actions run `44359156671`; Ubuntu 22.04 and 24.04 PASS | EXISTING |
| RQ-042 | Live GNS3/mac80211_hwsim/provider acceptance | Protected lab operator evidence and checksums | GATE |
| RQ-043 | Physical firmware/provider acceptance | Approved target/device evidence | GATE |
| RQ-044 | Clean-machine interactive desktop and restore qualification | Operator installation/recovery records | GATE |

This register is intentionally conservative. A source file or mocked contract test proves only the behavior it actually exercises; it does not mark an external provider, physical device or user workstation as accepted.

| RQ-036 | Unified design tokens and accessible shared shell | `frontend/src/styles/tokens.css`, `frontend/src/styles.css`, `frontend/src/styles/product-shell.css`, AppShell frontend tests | EXISTING | Maintain light/dark, responsive, focus, navigation landmark and reduced-motion checks |


## Visual Topology Studio — additional P03 acceptance

| ID | Requirement | Verification source | Status | Next verification |
|---|---|---|---|---|
| RQ-037 | Canonical, read-only topology draft validation | `POST /api/v1/topologies/validate`, `TopologyStudioService.canonical_payload`, `tests/test_topology_studio.py` | CI_VERIFIED | Exact PR-head backend workflow passed: hash/count response, no revision write, invalid-definition behavior, Project ownership, topology.manage and credential/configuration reference scope checks |
| RQ-038 | Complete visual authoring interactions | `frontend/src/pages/topologies.jsx`, `frontend/src/topology-editor.js`, `frontend/src/test/topologies.test.jsx`, editor/viewport tests | CI_VERIFIED | Exact PR-head frontend test and production-build job passed: palette categories, click/drag/drop, auto-layout bounds/determinism, inspectors, port linking, console tabs, keyboard/clipboard/history, and viewer restrictions. Interactive desktop/accessibility review remains an operator gate |


## Common provider contract — EXP-P04

| ID | Requirement | Verification source | Status | Next verification |
|---|---|---|---|---|
| RQ-039 | Complete common provider adapter contract and capability registry | `lib/providers/contracts.py`, `lib/providers/registry.py`, `lib/services/gns3_provider.py`, `tests/test_provider_contract.py`, `tests/test_topology_apply.py`, hosted quality workflow | CI_VERIFIED | Exact-main quality workflow `45045554536` for `235adde2dfdc7206546ca1f85aab9036ad69ceb3` passed backend, frontend/build and dashboard smoke jobs. The contract requires connect/disconnect, health, capability discovery, project/lab lifecycle, template/node/link lifecycle, node state, interface and observed-topology reads, and packet-capture capability reporting; all mutation capabilities are confirmation-required. Live provider qualification remains separate |
| RQ-045 | Project/Lab-scoped provider connection projection and registry discovery | Existing `gns3_lab_bindings`, `ProviderConnectionRecord`, `GET /api/v1/providers/registry`, OpenAPI contract tests | CI_VERIFIED | Exact-head workflow `45028046927` verifies Project-scoped read-only registry discovery and Vault-secret-safe projection. Live controller reachability remains RQ-042 |



## GNS3 consolidation — EXP-P05

| ID | Requirement | Verification source | Status | Next verification |
|---|---|---|---|---|
| RQ-046 | All GNS3 consumers share one registry-backed, Vault-scoped provider session lifecycle | `lib/providers/session.py`, `TopologyApplyService`, `WiFiLabProvisioningService`, dashboard and pipeline runtime, `tests/test_provider_contract.py`, `tests/test_topology_apply.py` | CI_VERIFIED | Exact-head quality workflow `45048993181` on `dc726a18400cb8d7e3442c8a7c5e6b7c155f85f9` passed provider session, topology apply, Wi-Fi provisioning, backend, frontend/build and dashboard smoke checks |
| RQ-047 | Actual GNS3 compute availability and mapped-template image compatibility | `GNS3Provider.get_resource_availability`, `get_template_image_availability`, topology dry-run/apply snapshots and compatibility report | CI_VERIFIED | Exact-head quality workflow `45048993181` passed bounded compute/image projection, missing-image conflict, unknown observations and mapped-node recovery regressions |
| RQ-048 | Actual provider interface discovery and project selection | `GET /labs/{lab_id}/provider-nodes/{provider_node_id}/interfaces`, provider catalogue UI, `docs/openapi.yaml` | CI_VERIFIED | Exact-head quality workflow `45048993181` passed Project/Lab RBAC, observed-node membership, provider interface projection, catalogue and frontend coverage |
| RQ-049 | Preserve GNS3 apply, adoption, idempotency, reconciliation, partial recovery and Wi-Fi provisioning | `TopologyApplyService`, `WiFiLabProvisioningService`, `tests/test_topology_apply.py` | CI_VERIFIED | Exact-head quality workflow `45048993181` passed backend/frontend/dashboard gates; live GNS3/mac80211_hwsim acceptance remains RQ-042 |


## Cisco Modeling Labs adapter — EXP-P06

| ID | Requirement | Verification source | Status | Next verification |
|---|---|---|---|---|
| RQ-050 | Independent authenticated CML adapter implements the shared provider lifecycle contract | `lib/providers/cml.py`, `lib/providers/http.py`, `lib/providers/registry.py`, `tests/test_stage_b_cml.py` | READY_FOR_CI | The standalone CML adapter suite is now included in the central quality workflow; exact-main hosted verification is pending. Live CML controller, licence/image readiness and VM boot remain operator gates |
| RQ-051 | Existing Project/Lab topology binding and apply pipeline support CML workspaces without a second topology authority | `20261122_16_multivendor_provider_bindings.py`, `TopologyApplyService`, provider binding API, `tests/test_topology_apply.py`, OpenAPI | READY_FOR_CI | Generic topology/provider binding tests are present; CML adapter-specific tests are now included in the central quality workflow and require exact-main verification. Live CML execution remains external |


## EVE-NG provider — EXP-P07-A

| ID | Requirement | Verification source | Status | Next verification |
|---|---|---|---|---|
| RQ-052 | Independent EVE-NG adapter implements the shared provider lifecycle with native authentication, folder scope, catalogue and safe workspace paths | `lib/providers/eve_ng.py`, `lib/providers/http.py`, `lib/providers/registry.py`, `tests/test_stage_b_eve_ng.py` | READY_FOR_CI | The standalone EVE-NG adapter suite is now included in the central quality workflow; exact-main hosted verification is pending. Live edition/licence and installed-image qualification remain external |
| RQ-053 | EVE-NG topology observation and controlled mutation use actual interface names and bridge-backed Ethernet links with partial-failure rollback | `EVENGProvider.list_nodes/list_links/get_interfaces/create_link`, shared `TopologyApplyService`, `tests/test_stage_b_eve_ng.py`, `tests/test_topology_apply.py` | READY_FOR_CI | The standalone EVE-NG adapter suite and shared topology regressions are now included in the central workflow; exact-main hosted verification is pending. Live bridge attach and node lifecycle remain external |
