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

Implemented through the canonical Run engine. A VALIDATION_RUN step resolves
only registered semantic test IDs or registered pytest node IDs, then starts
pytest through RunProcessManager with the same database, Project and Lab.
The pytest session creates its Run/Attempt through RunService; the execution
ID is propagated to the child and the new Run is linked back under a strict
same-Project/Lab database guard.

The Run environment snapshot retains the pipeline execution/revision identity
and the selected published performance-policy revision/hash. Optional
configuration and topology references must be supplied as profile/revision
pairs; the worker verifies they are published and belong to the execution's
Project/Lab, then carries their immutable hashes into the Run environment.
After the process group exits, the worker reads the terminal canonical Run and
evaluates the pinned policy against metrics from the latest Run Attempt. The
pipeline result retains the Run ID, business outcome, policy hash and
evaluation.

A pipeline revision currently supports at most one VALIDATION_RUN step,
matching the single canonical linked_run_id on a pipeline execution.
Validation steps are single-attempt. A deadline or uncertain process/Run
association transitions to RECOVERY_REQUIRED; the process is not killed and
the step is not automatically replayed. An operator must inspect the process
log, Run and Lab state before approving recovery.

## P29 — Qualification and Release Gate

Hosted qualification covers migration replay/schema contract, Project/Lab RBAC,
API idempotency, immutable revisions, registered test selection, canonical Run
association, policy hash pinning/evaluation, process-group wait/timeout behavior,
worker leases, transitions, cancellation, recovery, frontend tests/build and
dashboard startup. The focused coverage lives in
tests/test_pipeline_runtime.py, tests/test_pipeline_orchestration.py and
tests/test_run_process.py.

Hosted CI does not certify the protected GNS3/mac80211_hwsim Lab or physical
OpenWrt devices. Before production enablement, operators must complete the
Stage D GNS3/OpenWrt acceptance checklist and the protected Run/evidence suite.
The remaining host-network, Docker guest, radio placement, hostapd/wpa_supplicant,
DHCP/DNS and capture portions of P25 remain on the compatibility script until
each Python adapter has parity tests and operator-run protected-Lab acceptance.

## Safe worker operation

Run one step and exit:

    python scripts/netregress_pipeline_worker.py --once

Run as a supervised polling process:

    python scripts/netregress_pipeline_worker.py --poll-interval 5

The worker must run under a local OS account with access to the SQLite database
and OS credential store. It must not run with broader privileges than the
underlying provider operations require.
