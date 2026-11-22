# NetRegress Product Expansion — Implementation Decisions

**Baseline:** `3b8e5504b3824401a22e774ff1e37b2b253474a6`  
**Decision status:** Initial P00 decisions; implementation-changing ADRs require review and traceability updates.

## EXP-ADR-001 — Additive programme, preserve the Runner

**Decision:** Implement the expanded network engineering platform as an additive layer on the current NetRegress Runner. Existing Run/Attempt, evidence, regression, firmware lifecycle, identity/RBAC, Credential Vault, Device Inventory, topology revisions, GNS3 apply/reconciliation and persisted pipeline behavior remain the compatibility baseline.

**Reason:** The repository already has working local-first validation behavior and explicit safety invariants. Rebuilding these subsystems would increase regression risk and fragment authority.

## EXP-ADR-002 — Runtime and persistence

**Decision:** Keep Tauri 2 + React/Vite + Flask + SQLite + Alembic. Use the existing service/repository architecture and add bounded modules to the existing modular monolith. Alembic remains the only schema migration authority.

**Reason:** The current desktop Runner, local data lifecycle and hosted package qualification are built around this stack. No second DB or microservice is justified in the first expansion stages.

## EXP-ADR-003 — AI excluded

**Decision:** No AI/LLM/agent runtime, inference dependencies, AI-specific data tables, frontend pages or API routes in EXP-P00–EXP-P17.

**Reason:** The approved product work is deterministic network engineering, provisioning, configuration, validation and evidence. AI remains future scope.

## EXP-ADR-004 — Provider-independent canonical topology

**Decision:** NetRegress logical topology is authoritative. Provider adapters translate logical node/link intent into provider-specific resource operations and maintain stable mappings. Provider capabilities are discovered and explicit. Unsupported operations fail with typed capability errors.

**Reason:** GNS3, CML, EVE-NG and Linux-native providers do not share identical lifecycle semantics, identifiers or feature coverage. A shared contract must not erase those differences.

## EXP-ADR-005 — GNS3 as reference adapter

**Decision:** Wrap/refactor the existing GNS3 operations behind a shared provider contract. Do not create a second GNS3 client or move topology authority into GNS3.

**Reason:** The present GNS3 apply/reconciliation path includes idempotency, conflict checking, resource locks, immutable apply records and recovery semantics.

## EXP-ADR-006 — Packet Tracer as compatibility bridge

**Decision:** Initial Packet Tracer support is import/export/compatibility reporting only. Imported objects are classified as fully supported, partially supported, unsupported or requiring manual mapping. Preserve source-file provenance. Do not claim remote provisioning without a supported API.

## EXP-ADR-007 — Separate network intent from vendor output

**Decision:** Add a versioned vendor-neutral network-intent domain. Keep vendor CLI/config structures inside independent adapters. Capability checks are platform/version-specific and happen before generation or deployment.

**Reason:** A vendor-neutral model should express desired network behavior rather than pretending that CLI syntax and feature sets are universal.

## EXP-ADR-008 — Separate infrastructure and device configuration

**Decision:** OpenTofu owns infrastructure resources; Ansible owns post-provision device/OS configuration. Both integrate through backend services and PipelineService typed handlers. Neither executes from the browser directly.

## EXP-ADR-009 — Preserve execution safety

**Decision:** State-changing provider/topology/configuration/infrastructure work requires scoped authorization, explicit plan/review/approval as appropriate, idempotency, audit, bounded timeouts, exclusive resource locks and read-back. An uncertain remote outcome enters recovery; it is never blindly retried.

## EXP-ADR-010 — Evidence-led observability

**Decision:** Every metric and provider health observation carries its source, timestamp, scope and units/capability context. Unknown is represented as unavailable. Mocks and synthesized fixture data cannot satisfy physical or real-provider acceptance.

## EXP-ADR-011 — Local-first, zero-cost-first, licence-aware

**Decision:** Initial operation stays local-first. Prefer open-source tools and free editions; verify software/API version, licence, commercial-use restrictions, image source, hardware needs and redistribution constraints for each integration. The product may reference user-provided licensed images but must not redistribute them without permission.

## EXP-ADR-012 — Phase namespace

**Decision:** The new roadmap phases are referred to as **EXP-P00–EXP-P17** in repository documentation. Existing historical phases and Stage D P17–P24 / Stage E P25–P29 / Stage F P30–P37 retain their established identifiers.

**Reason:** Reusing P17–P37 without a programme prefix would cause ambiguous traceability and acceptance records. The user-facing roadmap retains its P00–P17 names; EXP- is a documentation namespace only.

## EXP-ADR-013 — Frontend does not advertise unsupported modules

**Decision:** Navigation entries and action controls are introduced only when the corresponding backend contract, authorization and lifecycle are implemented and tested. A visual workflow node is not executable until its handler exists.

## Open decisions requiring evidence before expansion

- Provider authentication and supported API-version contract for CML and EVE-NG.
- Exact CML-Free resource limits and edition-specific capabilities.
- EVE-NG Community versus Professional differences.
- Packet Tracer file-format/tooling support and licence restrictions.
- Initial Linux-native virtualization target and supported OpenTofu provider.
- Network intent schema and feature capability versioning.
- Vendor adapter transport preference and exact image/OS support matrix.
- Runtime dependency installation/bundling and platform packaging implications for Ansible/OpenTofu.

These are research/specification tasks in the corresponding phase. Do not invent endpoint behavior or assume feature support before verification.


## EXP-ADR-014 — Common provider adapter contract and explicit capabilities

**Decision:** Provider integrations implement a structural `ProviderAdapter` contract and register through an application-scoped `ProviderRegistry`. Stable capability IDs are declared separately from adapter method names and are checked before discovery or mutation. Provider descriptors report only capabilities an adapter explicitly advertises. Unsupported operations fail closed with a typed capability error.

**Connection records:** Existing provider connection persistence remains authoritative. P04 projects GNS3's existing Project/Lab binding into a typed provider-neutral connection record and exposes the registry through an RBAC-protected read-only API. The record may include an opaque Credential Vault reference but must never expose credential material. Do not add parallel binding storage.

**Compatibility:** GNS3 remains the sole registered reference adapter. Its REST client is constructed through the registry, while existing topology services continue to own locks, apply confirmation, idempotency, history, read-back and recovery. Other adapters must prove their capability set and contract before registration; no CML/EVE-NG support is implied.
