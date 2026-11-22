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
| RQ-015 | GNS3 provider operations | `GNS3Provider`, `ProviderRegistry`, `ProviderSessionService`, `TopologyApplyService`, `WiFiLabProvisioningService` | READY_FOR_CI | EXP-P05 consolidation preserves the single GNS3 adapter and uses one Vault-backed session lifecycle; live lab remains RQ-042 GATE |
| RQ-016 | CML provider | No CML adapter found in current source inventory | PLANNED | EXP-P04 contract first; API/license/version validation |
| RQ-017 | EVE-NG provider | No EVE-NG adapter found in current source inventory | PLANNED | EXP-P04 contract first; separate semantic adapter |
| RQ-018 | Packet Tracer compatibility bridge | No importer/exporter identified in current source inventory | PLANNED | Preserve original file provenance and report unsupported objects |

## Network configuration and automation

| ID | Requirement | Current source / contract | Status | Next verification |
|---|---|---|---|---|
| RQ-020 | Existing Wi-Fi configuration profiles and deployment | `lib/services/configuration_profile_service.py`, `lib/services/configuration_deployer.py` | EXISTING | Keep current Wi-Fi schema and deployment behavior |
| RQ-021 | Canonical vendor-neutral network intent | No separate intent domain found in current source inventory | PLANNED | Define schema/version/capability validation in EXP-P08 |
| RQ-022 | Linux/FRR and network-vendor adapters | Existing Runner/device adapters are not equivalent to network-intent compilers | PLANNED | Implement independent adapter test suites |
| RQ-023 | Ansible playbook/inventory execution service | No Ansible execution service identified | PLANNED | EXP-P10: scoped inventory, secret handling and audited subprocess |
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
| RQ-046 | All GNS3 consumers share one registry-backed, Vault-scoped provider session lifecycle | `lib/providers/session.py`, `TopologyApplyService`, `WiFiLabProvisioningService`, dashboard and pipeline runtime, `tests/test_provider_contract.py`, `tests/test_topology_apply.py` | READY_FOR_CI | Verify Vault scope, paired connect/disconnect, cleanup on callback failure, and both service consumers using the same registry/session object |
| RQ-047 | Actual GNS3 compute availability and mapped-template image compatibility | `GNS3Provider.get_resource_availability`, `get_template_image_availability`, topology dry-run/apply snapshots and compatibility report | READY_FOR_CI | Confirm safe bounded compute projection, AVAILABLE/MISSING/UNKNOWN image outcomes, fail-closed creation when the assigned compute is disconnected or required image is missing, and no false block for already observed mappings |
| RQ-048 | Actual provider interface discovery and project selection | `GET /labs/{lab_id}/provider-nodes/{provider_node_id}/interfaces`, provider catalogue UI, `docs/openapi.yaml` | READY_FOR_CI | Verify Lab Project RBAC, observed-node membership, adapter/port projection and selection from the discovered Project catalogue |
| RQ-049 | Preserve GNS3 apply, adoption, idempotency, reconciliation, partial recovery and Wi-Fi provisioning | `TopologyApplyService`, `WiFiLabProvisioningService`, `tests/test_topology_apply.py` | READY_FOR_CI | Exact hosted main workflow after the consolidated EXP-P05 commit; live GNS3/mac80211_hwsim acceptance remains RQ-042 |
