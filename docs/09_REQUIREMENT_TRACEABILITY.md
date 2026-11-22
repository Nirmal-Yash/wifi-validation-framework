# NetRegress Expansion Requirement Traceability

**Baseline:** `3b8e5504b3824401a22e774ff1e37b2b253474a6`  
**Status:** P00 initial source-to-requirement map. Planned expansion requirements remain unimplemented until explicitly tested.

## Status key

- **EXISTING:** relevant source capability is present; its current acceptance boundary still applies.
- **EXTEND:** an existing contract is present but the expansion requirement is not complete.
- **PLANNED:** no qualifying implementation has been identified at this baseline.
- **GATE:** requires operator/provider evidence beyond hardware-free CI.

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
| RQ-013 | Visual editing, drag positioning and port-aware links | `frontend/src/pages/topologies.jsx`, topology service validation | EXISTING | Add canvas interaction tests for new UX |
| RQ-014 | Topology apply, reconciliation and recovery | `lib/services/topology_apply.py`, `/topologies/*/plan|apply|reconciliation` | EXISTING | No implicit prune; preserve lab lock/idempotency |
| RQ-015 | GNS3 provider operations | Existing topology apply/provider services and `/labs/*/provider-*` | EXISTING | Consolidate, do not duplicate; live lab remains GATE |
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
| RQ-034 | Cross-domain operations overview | `DashboardQueryService` and `frontend/src/pages/dashboard.jsx` currently focus on Runs/readiness | EXTEND | Real Project/Lab/provider/device/pipeline aggregates with source timestamps |
| RQ-035 | Shared Organization/Project/Lab shell context | Workspace APIs exist; global selectors are not in current shell | EXTEND | Persist selection safely; enforce server-side permissions |

## Acceptance and evidence

| ID | Requirement | Verification source | Status |
|---|---|---|---|
| RQ-040 | Current exact-commit hosted quality gates | Actions run `44359150673` on baseline commit; 3/3 jobs PASS | EXISTING |
| RQ-041 | Current exact-commit Linux package matrix | Actions run `44359156671`; Ubuntu 22.04 and 24.04 PASS | EXISTING |
| RQ-042 | Live GNS3/mac80211_hwsim/provider acceptance | Protected lab operator evidence and checksums | GATE |
| RQ-043 | Physical firmware/provider acceptance | Approved target/device evidence | GATE |
| RQ-044 | Clean-machine interactive desktop and restore qualification | Operator installation/recovery records | GATE |

This register is intentionally conservative. A source file or mocked contract test proves only the behavior it actually exercises; it does not mark an external provider, physical device or user workstation as accepted.
