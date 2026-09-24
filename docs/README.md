# NetRegress Documentation Index

## Canonical documentation set

| Document | Purpose | Authority |
|---|---|---|
| 01_DEVELOPMENT_PLAN_AND_ROADMAP.md | Implementation order, historical phases, current iterations, roadmap and completion gates | Development order/status |
| 02_SYSTEM_ARCHITECTURE_DATA_API.md | Backend architecture, persistence model, data ownership and API contracts | Technical/data/API contract |
| 03_TRACEABILITY_AND_SYSTEM_READINESS.md | Requirement traceability, current state, completeness audit and release readiness | Verification/readiness |
| 04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md | Installation, exact lab reproduction, testing, operations, troubleshooting and recovery | Operator/runtime procedure |
| 05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md | Frozen architecture decisions, product semantics and business invariants | Upstream design/business semantics |

## Separate contracts

| Document | Purpose |
|---|---|
| EXECUTION_AND_ADAPTERS.md | Pytest, CommandRunner, DeviceAdapter, FirmwareAdapter and capture execution contracts |
| SECURITY_AND_SAAS.md | Identity, RBAC, secrets, tenant isolation, Cloud and Runner security |
| FRONTEND_DESIGN.md | API-first UI and presentation architecture |
| PRD.md | Product requirements and product scope |
| AGENT_CONTEXT.md | Working context and historical implementation state |

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

Legacy merged-document paths remain as compatibility pointers. The canonical documents above are the locations to edit.
