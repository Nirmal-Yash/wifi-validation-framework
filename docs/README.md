# NetRegress Documentation Index

## Canonical documentation set

| Document | Purpose | Authority |
|---|---|---|
| STAGE_A_FOUNDATION.md | P00–P03 baseline audit, compatibility rules, platform foundation, product-shell redesign and initial resource persistence | Stage A implementation/compatibility record |
| STAGE_B_FOUNDATION.md | Project ownership, persisted memberships, Project-scoped Runner access, workspace API/UI checkpoints and acceptance gates | Stage B scope and checkpoint status |
| 01_DEVELOPMENT_PLAN_AND_ROADMAP.md | Implementation order, historical phases, current iterations, roadmap and completion gates | Development order/status |
| 02_SYSTEM_ARCHITECTURE_DATA_API.md | Backend architecture, persistence model, data ownership and API contracts | Technical/data/API contract |
| 03_TRACEABILITY_AND_SYSTEM_READINESS.md | Requirement traceability, current state, completeness audit and release readiness | Verification/readiness |
| 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md | Installation, exact lab reproduction, testing, operations, troubleshooting and recovery | Operator/runtime procedure |
| 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | Frozen architecture decisions, product semantics and business invariants | Upstream design/business semantics |
| STANDALONE_INSTALLATION_AND_OPERATIONS.md | Standalone install, configuration, health, backup/restore, release and certification operations | Standalone operator runbook |
| UPGRADE_AND_FIRST_RUN_GUIDE.md | Safe upgrade from older checkouts, current-main pull, installation, database migration, first startup, execution and real-world operations | Upgrade / first-run procedure |

## Separate contracts

| Document | Purpose |
|---|---|
| EXECUTION_AND_ADAPTERS.md | Pytest, CommandRunner, DeviceAdapter, FirmwareAdapter and capture execution contracts |
| SECURITY_AND_SAAS.md | Identity, RBAC, secrets, tenant isolation, Cloud and Runner security |
| FRONTEND_DESIGN.md | React/Vite UI and presentation architecture |
| PRD.md | Product requirements and product scope |
| AGENT_CONTEXT.md | Working context and current implementation handoff |

## Documentation hierarchy

~~~text
Architecture Decisions & Business Logic
                 ↓
System Architecture + Data/API
                 ↓
Development Plan + Roadmap
                 ↓
Implementation
                 ↓
Traceability + Readiness
                 ↓
Lab Reproduction + Testing + Operations
~~~

Executable source on main remains the current behavioral authority until the corresponding planned migration or contract is fully applied.

Legacy consolidated-document files have been removed. The canonical documents above are the authoritative locations to edit.
