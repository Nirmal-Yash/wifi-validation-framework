# EXP-P14 — Network observability, provider/device metrics and evidence

## Objective

Deliver one provenance-aware observability surface across registered network-emulator providers, managed devices and existing Run evidence. Preserve Project/Lab ownership, Credential Vault boundaries, source timestamps, units, integrity verification and independent read permissions. Measurements must originate from a real adapter/device or persisted test/evidence source; client-supplied metrics and synthetic health values are not accepted.

## Delivered

### Registered provider observations

- `ProviderObservationService` reuses `TopologyApplyService`'s registered provider registry and `ProviderSessionService`; it never creates a second provider client or accepts caller-supplied endpoint, provider id, token or measurement data.
- Collection runs through the adapter's read-only health, version and resource-availability contracts. A Lab's active Vault-backed provider binding is required.
- Provider snapshots preserve the provider id, source adapter, observed timestamp and timestamp provenance, health state, version, compute observations, explicitly reported numeric resource metrics and packet-capture capability declaration.
- Numeric metrics are only values explicitly returned by the adapter: GNS3 CPU/memory utilization percentages and EVE-NG total CPU cores/memory capacity where available. CML compute state and licensing observation status are retained without inventing utilization values.
- Packet-capture support is reported as adapter capability/readiness information only. It does not start a capture or claim that every link is capture-ready. Providers that do not declare packet-capture support are reported as `NOT_SUPPORTED`.
- If a provider cannot be contacted or returns an invalid observation, an immutable `UNAVAILABLE` snapshot records only the safe error type. Credentials, endpoint details and exception messages are not persisted.

### Managed-device network observations

- `DeviceObservationService` parses the fixed Linux `ip -s -j link show` output into per-interface RX/TX bytes, packets, errors and drops.
- Collection runs only through `SecureCommandRunner` with the fixed structured read-only command, USER privilege and bounded timeouts. Transport is `ParamikoExecRunner` with strict system-host-key verification.
- The API resolves only an active, same-Project, same-Device `SSH_PASSWORD` credential using `CredentialVaultService.use_secret`. Secret material remains inside the callback.
- Missing counters remain absent; genuine observed zeroes remain zero; malformed, negative, over-wide, oversized or unmeasurable outputs are rejected. No counter rates or health scores are inferred from one snapshot.

### Run evidence and unified query

- `DashboardQueryService.network_observability` unifies persisted test metrics/raw samples, Run-linked Wi-Fi telemetry, lab-health artifacts, PCAP artifact metadata and protocol-evidence JSON.
- Run metrics preserve test identity, metric name, unit, measurement policy and raw sample status/warm-up/retry/timestamp metadata.
- PCAP artifacts are included only as metadata with an explicit SHA-256 integrity state; binary PCAP bytes and local filesystem paths are never embedded in this API.
- Protocol-evidence JSON is returned only after the underlying artifact passes the existing confined-path and SHA-256 verification. Tampered or missing artifacts are marked unavailable and do not contribute evidence payloads.
- `GET /api/v1/runs/{run_id}/network-observability` requires `runs.read`. Performance sample access is independently gated by `performance.read`; telemetry, health and packet/protocol evidence are independently gated by `evidence.read`. Each child domain uses a stable restricted response shape.
- The Telemetry page surfaces Lab provider history and Run-level measurements, Wi-Fi telemetry, PCAP integrity and protocol summaries. The Device inventory page surfaces device counter observation history.

## Database

Alembic revision `20261124_23` (head after P14) adds append-only `device_observation_snapshots` and `provider_observation_snapshots` tables, indexes and Project/Lab/Device/provider-binding scope plus immutable/no-delete triggers. `schema_meta.version` advances from 32 to 33. Hashes are recomputed on reads; integrity-invalid content is never presented as verified evidence. The migration is audit-bearing and intentionally has no downgrade; restore a verified backup to reverse it.

## Compatibility and safety

- Existing Run-linked `WifiTelemetryService`, packet capture execution and `ProtocolEvidenceService` remain the source of truth. This phase aggregates their persisted evidence; it does not introduce a replacement capture engine or duplicate protocol parser.
- Existing provider adapters, provider session lifecycle, endpoint restrictions, OS Vault and Project/Lab permissions remain authoritative.
- No generic caller-defined command endpoint, shell/script execution, arbitrary provider client, caller-authored metric or fake RF/health metric is added.
- No credential values, provider endpoint URLs, binary capture data or local paths are included in provider/Run observation payloads.
- Virtual interface counters remain diagnostic network-behaviour evidence, not physical RF certification.
- Real provider health and compute values are reported only when the adapter returned them. Missing values remain unavailable.

## Verification scope

- Backend: `tests/test_device_observability.py`, `tests/test_topology_apply.py`, `tests/test_dashboard_api.py`, `tests/test_openapi_contract.py` and `tests/test_schema_migrations.py`.
- Existing PCAP/protocol contracts remain in `tests/test_packet_capture.py`, `tests/test_protocol_capture.py` and `tests/test_protocol_evidence.py`.
- Frontend: Pipeline graph tests, Device inventory and Telemetry page regression/build.
- Exact-head quality and path-relevant desktop checks run only after P13 and P14 commits are integrated.
- Real GNS3/CML/EVE controllers, host-key provisioning, protected Lab packet-capture readiness, physical Wi-Fi and target-device acceptance remain separate operator-owned gates.

## Files

- `lib/services/provider_observation.py`
- `lib/services/device_observation.py`
- `alembic/versions/20261124_23_device_observability.py`
- `lib/repositories/schema_contract.py`
- `dashboard/query.py`, `dashboard/api_v1.py`
- `frontend/src/api.js`, `frontend/src/pages/devices.jsx`, `frontend/src/pages/quality.jsx`
- `docs/openapi.yaml`
- `tests/test_device_observability.py`, `tests/test_topology_apply.py`, `tests/test_dashboard_api.py`

**Status at source checkpoint:** implementation integrated into the P14 commit; exact-head CI is deferred until both P13 and P14 are complete and pushed together.
