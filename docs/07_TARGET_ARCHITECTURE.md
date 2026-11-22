# NetRegress Target Architecture

**Baseline:** `3b8e5504b3824401a22e774ff1e37b2b253474a6`  
**Architecture style:** local-first modular monolith with typed adapters and durable execution.

## 1. Runtime architecture

The existing runtime remains the product host:

- **Desktop shell:** Tauri 2.
- **Frontend:** React + Vite, using the shared API client and authenticated Flask contracts.
- **Backend:** Flask API and existing service layer.
- **Persistence:** SQLite with Alembic as the only schema migration authority.
- **Secrets:** existing OS Credential Vault abstraction; application tables store opaque references.
- **Execution:** existing Run/Attempt services, PipelineService, supervised workers and process-management boundaries.
- **Evidence:** existing artifact/evidence services, immutable metadata, provenance and SHA-256 verification.

New functionality is added as domain services and adapters inside this application. Do not introduce microservices, a second database, a second authorization framework or another execution engine for the same responsibility.

## 2. Logical subsystem boundaries

| Subsystem | Owns | Must not own |
|---|---|---|
| Workspace and identity | Organization, Project, Lab, membership, role and permissions | Provider credentials or device configuration |
| Device inventory | Stable managed device identity, endpoint metadata, capabilities, credential reference | Secret material or provider topology ownership |
| Topology domain | Canonical logical nodes/links, drafts, immutable revisions, validation and hashes | Provider-generated IDs or live mutations |
| Provider adapters | Connection, provider catalogues, provider resource lifecycle, observed topology and capabilities | Canonical topology truth or cross-provider business rules |
| Network intent | Vendor-neutral network objects, validation, capability requirements and revisions | Vendor CLI syntax |
| Vendor adapters | Device identification, capability report, intent compilation, config validation, diff and read-back | Canonical intent ownership |
| Ansible service | Inventory resolution, playbook validation and controlled device execution | Infrastructure resource provisioning |
| OpenTofu service | Workspace, format/init/validate/plan/apply/state and resource lifecycle | Device running-configuration management |
| Pipeline service | Immutable workflow definitions, executions, step/attempt lifecycle, worker leases, approvals and recovery | Unbounded arbitrary scripting |
| Observability/evidence | Measurements, captures, telemetry, source provenance, artifacts and evidence verification | Synthetic health claims |
| Dashboard query layer | Read-only aggregation and drill-down links | Mutations or new source-of-truth tables for derived KPIs |

## 3. Provider contract

A provider adapter should expose a versioned typed contract for:
- connect/disconnect and bounded health check;
- discover projects/labs and templates/node definitions;
- capability discovery;
- create/select lab;
- create/delete node and start/stop node where supported;
- create/delete link where supported;
- discover interfaces/ports;
- retrieve observed topology and resource state;
- packet-capture capability and capture operations where available.

Provider capability is explicit data, not a switch on provider name. Unsupported operations return a typed `CapabilityNotSupported` (or equivalent domain exception). The contract must not silently report success or emulate unsupported semantics.

GNS3 remains the first reference adapter. Wrap/refactor the existing implementation; do not create a duplicate GNS3 provider. CML and EVE-NG receive independent adapters and tests because their authentication, identifiers, lifecycle and API semantics differ. Packet Tracer starts as a bounded compatibility bridge: import/parse supported artifacts, map known objects, export a documented subset and produce an incompatibility report. Do not label it a full remote provider without a supported automation API.

## 4. Canonical identifiers and persistence

- Organization, Project, Lab, Device, topology profile/revision, logical node/link, network-intent object, pipeline/revision/execution and infrastructure workspace receive stable NetRegress identities.
- Provider-generated identifiers are persisted as scoped mappings tied to provider, Lab, logical identity and apply/revision record.
- Published topology, network-intent, configuration and pipeline revisions are immutable and content-hashed.
- Resource ownership is Project/Lab-scoped and checked at the API boundary.
- Additive Alembic migrations are introduced only when durable state is required.
- No secret is included in topology, intent, pipeline input, OpenTofu plans/artifacts or Ansible inventory output. Runtime credential resolution happens at the adapter boundary.

## 5. Automation boundaries

**OpenTofu** owns infrastructure lifecycle (VMs, virtual networks, bridges, storage and supported hypervisor resources). Its local state is isolated by Project/Lab, protected by filesystem permissions and exclusive workspace locking. Plan and apply are separate; apply uses an approved plan and explicit authorization. State-changing applies are never automatically retried.

**Ansible** owns configuration and management of operating systems/network devices after the target exists. Inventory is derived from authorized managed Device records and Lab scope. Playbooks are versioned and validated. Check mode/diff support is reported accurately per module/collection; it is not universally a true dry run. Secrets are not placed in command-line arguments, frontend state or durable generated inventories.

The two tools integrate through services and typed PipelineService steps, not directly from React components.

## 6. Workflow execution

The existing PipelineService remains authoritative. New steps are versioned, validated against an allow-list and backed by actual handlers before being exposed as executable UI nodes.

All step executions persist their definition revision/hash, execution, ordered step, attempt, start/end, status, output references and sanitized error. Worker leases and recovery semantics remain. Retry is permitted only for operations explicitly classified safe; topology apply, infrastructure apply and device configuration are single-attempt by default. If a timeout leaves the remote result uncertain, mark recovery required and inspect actual state before resumption.

## 7. Frontend architecture

The shell owns global Organization/Project/Lab selection and passes the current context to feature routes. Feature pages remain presentation and orchestration clients of backend APIs. Shared components cover tables, forms, inspectors, status, confirmations, loading, error and empty states.

Navigation items appear only when their backend workflow exists and the current user can access them. Provider connection status must include the provider, observation time and source; it must never be a static “connected” label.

The topology canvas and visual pipeline builder share interaction conventions (selection, pan/zoom, keyboard affordances, undo/redo and property inspector) but retain separate domain schemas and services.

## 8. Security and operational constraints

- Existing global and Project permission checks remain authoritative; frontend hiding is not authorization.
- Mutations use existing session/CSRF/idempotency/audit conventions.
- Restrict provider endpoints using the established private/local endpoint policy and bounded timeouts/responses.
- Never leak controller response bodies, credentials or secret-bearing subprocess output.
- Confine filesystem paths and temporary files; set restrictive permissions.
- Prevent concurrent operations against one Lab/device/workspace with resource leases.
- Destructive operations require explicit, scoped approval and confirmation.
- Keep the Wi-Fi Runner command line, test node IDs, capture workflow and protected lab behavior compatible.

## 9. Deployment and cost model

The current standalone Linux Tauri package is the host. OpenTofu, Ansible and emulator runtimes should initially use system-installed or explicitly provisioned runtimes with version/capability checks. Do not bundle or redistribute external executables or vendor images without supply-chain, licence and redistribution review.

Cloud/SaaS, centralized tenant control, PostgreSQL, Kubernetes and AI integrations remain outside this implementation programme.
