# Stage E — Provisioning, Pipelines and Run Integration

Stage E follows Stage D P17–P24. It moves repeatable lab setup into explicit
provider services, persists operator-authored workflows, and connects those
workflows to the existing Run, configuration and performance-policy services.
The existing Run/evidence engine remains authoritative.

## P25 — Provisioning Adapter Migration

The first migration slice is delivered by WiFiLabProvisioningService. It
performs read-only GNS3 discovery, verifies the protected reference nodes and
client management adapter, creates only a missing management link on an
unoccupied Switch1 port, starts nodes in dependency order and verifies provider
read-back. Its dashboard plan and apply routes use Project/Lab authorization,
CSRF, idempotency, explicit confirmation and the shared Lab resource lease.

This is intentionally incremental. wifi_lab_reprovision_robust.sh remains the
compatibility entry point for host network setup, Docker guest preparation,
mac80211_hwsim, hostapd/wpa_supplicant, DHCP/DNS and protected capture setup.
Those operations must be migrated one adapter at a time with isolated parity
tests and operator-run protected-lab acceptance before their legacy path is
retired.

## P26 — Persisted Pipeline Orchestration

Pipeline definitions and published revisions are immutable/audit-bearing.
Executions are scoped to an active Project and Lab and pin a published revision
hash. Each ordered step and every attempt is persisted. The initial allow-list
includes Wi-Fi GNS3 provisioning, topology apply, provider reconciliation,
OpenWrt Wi-Fi configuration deployment and validation Run requests.

A local worker claims one step at a time and persists its attempt record, lease
and result. Each step stores its timeout and retry policy. Automatic retry is
restricted to handlers explicitly classified as safe for retry; state-changing
operations are single-attempt by default. Ambiguous outcomes transition to
RECOVERY_REQUIRED. Recovery requires an operator to inspect actual provider
state and explicitly approve resumption. Cancellation never kills a provider
mutation already in flight; it prevents later steps from starting.

Timeout values govern worker leases and recovery deadlines. Provider handlers
must also use bounded network/SSH transport timeouts. An expired lease during an
active step is treated as uncertain and is not automatically replayed.

## P27 — Pipeline Management Frontend

The dashboard will support Project/Lab-scoped definition editing, publication,
explicit execution, step/attempt monitoring, cancellation and reviewed recovery.
Backend permission checks remain authoritative.

## P28 — Complete Run and Policy Integration

Validation steps will use the existing RunProcessManager and RunService. The
pipeline execution ID will be propagated to the test worker; when a Run is
created, it will be linked back to the execution under a same-Project/Lab
database guard. Performance policy selection will pin the published revision
and hash. Configuration and topology revisions remain immutable references;
their existing adapter services own verification and evidence.

## P29 — Qualification and Release Gate

Hosted CI verifies migration replay, schema contract, authorization, API
idempotency, worker leases, state transitions, retries, cancellation, recovery,
frontend build and dashboard startup. Hosted CI does not certify the protected
GNS3/mac80211_hwsim or physical OpenWrt lab; those require operator-run
acceptance using the established Stage D operations checklist.

## Safe worker operation

Run one step and exit:

    python scripts/netregress_pipeline_worker.py --once

Run as a supervised polling process:

    python scripts/netregress_pipeline_worker.py --poll-interval 5

The worker must run under a local OS account with access to the SQLite database
and OS credential store. It must not run with broader privileges than the
underlying provider operations require.
