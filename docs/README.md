# NetRegress Documentation Index

## Authoritative decision and implementation documents

| Document | Purpose | Authority |
|---|---|---|
| ARCHITECTURE_DECISIONS.md | Frozen answers to the full discovery questionnaire and cross-cutting architecture decisions | Architecture decision source |
| IMPLEMENTATION_PLAN.md | Exact refactor phases, order, files, gates and acceptance criteria | Implementation sequence |
| BUSINESS_LOGIC.md | Run/test/baseline/release semantics and business invariants | Product semantics |
| TECHNICAL_ARCHITECTURE.md | Target code/service/layer architecture and dependency boundaries | Technical structure |
| DATA_MODEL_AND_APIS.md | Run-scoped persistence schema and /api/v1 contracts | Data/API contract |
| EXECUTION_AND_ADAPTERS.md | Pytest, CommandRunner, DeviceAdapter, FirmwareAdapter and capture execution contracts | Execution contract |
| SECURITY_AND_SAAS.md | Identity, RBAC, secrets, tenant isolation, Cloud and Runner security | Security contract |
| TESTING_AND_OPERATIONS.md | Testing pyramid, real-lab gate, migration verification and operations | Verification contract |
| FRONTEND_DESIGN.md | Flask/Jinja dashboard, API-first UI, React migration boundary | UX/UI contract |

## Current operational references

| Document | Purpose |
|---|---|
| WIFI_LAB_REPRODUCTION.md | Current GNS3 topology and practical reproduction |
| INSTALLATION_GUIDE.md | Historical/general installation background |

## Current source-of-truth hierarchy

1. Current executable source on main.
2. Current configuration.
3. Current operational documentation.
4. Recorded runtime evidence.
5. Historical installation material.

Future architecture decisions are frozen in ARCHITECTURE_DECISIONS.md.

## Recommended contributor workflow

Read the architecture decisions first.

Read the implementation phase relevant to the change.

Read business logic before changing classification/policy.

Read data/API contracts before changing persistence or dashboard behavior.

Read execution/adapter rules before changing network/device control.

Use TESTING_AND_OPERATIONS.md to select the appropriate verification gate.

Keep the protected 436026e behavioral baseline intact.