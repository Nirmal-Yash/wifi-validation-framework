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

## Current production-readiness programme

See [P33–P37 Linux Production Readiness](P33_P37_PRODUCTION_READINESS.md) for current desktop qualification, supply-chain, recovery, packaged business workflow and release certification gates.

## Product expansion programme

The additive P00–P17 network-engineering programme is documented in:
- [Product Requirements and Scope](06_PRODUCT_REQUIREMENTS_AND_SCOPE.md)
- [Target Architecture](07_TARGET_ARCHITECTURE.md)
- [Implementation Roadmap](08_IMPLEMENTATION_ROADMAP.md)
- [Requirement Traceability](09_REQUIREMENT_TRACEABILITY.md)
- [Implementation Decisions](10_IMPLEMENTATION_DECISIONS.md)

The new expansion phases are prefixed **EXP-** in repository traceability to distinguish them from historical Stage D/E/F phase IDs. The current first batch is EXP-P00–EXP-P03.

Implementation audit records for the first batch:
- [EXP-P01 Design System and Application Shell Audit](EXP_P01_IMPLEMENTATION_AUDIT.md)
- [EXP-P02 Operational Overview Audit](EXP_P02_IMPLEMENTATION_AUDIT.md)
- [EXP-P03 Visual Topology Studio Audit](EXP_P03_IMPLEMENTATION_AUDIT.md)

These audit records document existing functionality retained, additive changes, source-of-truth and RBAC rules, test evidence and the remaining exact-commit acceptance gates. They do not replace the canonical roadmap or requirement traceability register.


## EXP-P13/P14 implementation audits

- [EXP-P13 Pipeline DAG Authoring and Conditional Execution](EXP_P13_IMPLEMENTATION_AUDIT.md)
- [EXP-P14 Network Observability, Provider/Device Metrics and Evidence](EXP_P14_IMPLEMENTATION_AUDIT.md)

P13 extends the durable Pipeline worker with backward-compatible graph dependencies and a visual editor. P14 unifies registered-provider observations, managed-device counters and integrity-verified Run metrics/telemetry/PCAP/protocol evidence without replacing existing adapters or capture engines.


## Stage G native interoperability

- [G01 Existing Implementation Audit and Gap Register](STAGE_G_NATIVE_INTEROPERABILITY_AUDIT.md)
- [G02 Extended Presentation Model and Provenance](STAGE_G_G02_PRESENTATION_MODEL_AUDIT.md)
- [G03–G06 Native GNS3, CML/VIRL and EVE-NG Codec Implementation](STAGE_G_G03_G06_NATIVE_CODECS_AUDIT.md)

These audits distinguish native file codecs from live provider adapters and record supported format subsets, source preservation, parser limits and external vendor-application acceptance gates.
