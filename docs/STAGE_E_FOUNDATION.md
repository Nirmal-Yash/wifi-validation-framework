# Stage E — Provisioning, Pipelines and Run Integration

Stage E follows Stage D P17–P24. It moves repeatable lab setup into explicit
provider services, persists operator-authored workflows, and connects those
workflows to the existing Run, configuration and performance-policy services.
The existing Run/evidence engine remains authoritative.

## P25 — Provisioning Adapter Migration

P25 is implemented as a set of separately bounded adapters while retaining
the original shell entry point as a recovery fallback.

### GNS3 provider lifecycle

WiFiLabProvisioningService owns read-only discovery, reference-node and client
management-adapter validation, additive creation of a missing client management
link on an unoccupied Switch1 port, ordered node startup, provider read-back,
Project/Lab authorization, scoped vault credentials, audit and the shared Lab
resource lock. It never deletes nodes, stops a healthy topology or rewires an
existing link.

### Linux host network

LinuxLabHostNetworkService in lib/services/linux_lab_host_network.py validates
the existing libvirt default network and the protected virbr0 address contract:
192.168.122.1/24 and 10.10.10.1/24. It refuses unapproved bridge addresses,
deletes only default-network DHCP ranges/reservations using libvirt's live and
persistent update API, adds only missing approved addresses, and verifies
postconditions. It does not redefine the network, flush addresses, alter
routes or touch unrelated networks. Its deterministic tests are in
tests/test_linux_lab_host_network.py.

### Docker guests, Wi-Fi radios and services

LinuxWiFiGuestProvisioningService in
lib/services/linux_wifi_guest_provisioning.py owns the repeatable guest setup:

- Resolves the exact GNS3 Docker node containers and checks running state,
  container PID, required Ethernet interfaces and carrier without guessing a
  similarly named container.
- Installs only missing Alpine/Ubuntu packages, using CDN/archive fallback for
  the FRR Alpine repositories.
- Creates or updates the guest admin account and SSH service. Passwords are
  sent through stdin to chpasswd; sudoers and service configuration are written
  through private stdin-backed files.
- Reuses already placed AP/client mac80211_hwsim radios; loads the module when
  absent and moves only available host PHYs into the intended Docker network
  namespaces. It never unloads or recycles the hwsim module. A shortage or
  ambiguous placement stops for operator inspection.
- Configures the AP bridge and hostapd WPA2 network, then configures
  wpa_supplicant and verifies the client WPA association and SSID.
- Configures FRR dnsmasq with a 12-hour lease, gateway/DNS options and a
  deterministic reservation for the observed client WLAN MAC at 192.168.122.30.
  It verifies the DHCP address, preserves client management on eth1 at
  10.10.10.30, and verifies the default route remains on wlan0.
- Verifies the client-to-router and gateway paths, DNS resolution, admin SSH
  and passwordless sudo on all four nodes, plus tcpdump availability on the
  monitor guest.

The guest service uses bounded argument-vector commands with shell disabled,
non-interactive sudo only for host operations, a shared Lab resource lease,
explicit confirmation, stdin-only secret payloads, and read-back after
mutation. If a later operation fails after earlier mutations, it returns an
uncertain/partial-completion error; it does not blindly replay the workflow.

### Operator entry point

The explicit CLI joins the GNS3, host-network and Docker guest adapters:

    python scripts/netregress_lab_setup.py --lab-id <LAB_ID> --action plan

For apply, put the required guest credentials in an owner-only .env file
(chmod 600 .env) or a protected process environment, then run:

    python scripts/netregress_lab_setup.py --lab-id <LAB_ID> --action apply --confirm

The required variables are WIFI_ROUTER1_PASSWORD, WIFI_AP_HOST_PASSWORD,
WIFI_CLIENT_VM_PASSWORD, WIFI_MONITOR_VM_PASSWORD and WIFI_TEST_PSK. The
command refuses missing secrets; it has no shared/default passwords and does
not accept credentials as command-line arguments. Do not run it with sudo.
Apply starts GNS3 nodes through the bound provider first, then re-plans and
applies host/guest setup. It does not run pytest automatically; execute the
protected validation suite through the canonical Run/evidence workflow after
reviewing the provisioning result.

### Remaining compatibility and acceptance boundaries

The original wifi_lab_reprovision_robust.sh is retained and has not been
weakened or removed. It remains the fallback for the broader host readiness
sequence (Ubuntu package installation, Chrony synchronization, local source
and configuration repair/backup, repository-specific preflight), the
explicit destructive --repro-test reset mode, and direct invocation of the
protected test suite. The Python adapters do not perform a destructive GNS3
reset or claim that tcpdump package availability is proof of a successful
packet capture.

Hosted CI validates adapter contracts with fake Docker/host command runners.
It cannot validate the actual GNS3 project, physical Linux bridge, Docker
guest images, mac80211_hwsim namespace placement, WPA association, RF behavior,
physical OpenWrt devices or actual capture evidence. Before retiring the shell
fallback or declaring production P25 acceptance, the operator must run the
Python plan/apply on the protected lab, run the same protected Run/evidence
suite, inspect PCAP checksums and final topology/network state, and record the
actual commit, environment fingerprint and evidence. Those physical-lab
acceptance results remain distinct from hosted CI.

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

The Run environment snapshot retains the pipeline execution/revision identity,
selected published performance-policy revision/hash, configuration revision
values and hash, topology revision definition/hash, and successful preceding
provision/apply/deployment references. Project, Lab and Device configuration
profiles are resolved through their corresponding configuration layers. A
selected topology is reconciled against the bound GNS3 Lab and must be IN_SYNC
before validation starts. A selected managed Device must match the execution
Project/Lab and an active same-device SSH_PASSWORD vault credential; its
registered Runner adapter key must exist in configs/devices.yaml. The child
Run process resolves the secret from the OS Credential Vault and overlays the
managed Device endpoint without placing secret material in the pipeline
definition, process command line, environment or Run metadata.

The exact topology revision is included in the Run environment fingerprint.
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
The Python GNS3, libvirt and guest adapters have deterministic hosted contract
tests; host OS readiness, repository/config repair, the destructive compatibility
reset mode and direct protected-suite execution remain on the shell entry point.
The shell fallback must remain available until the Python path has been accepted
on the physical lab with matching Run/evidence and capture checksums.

## Safe worker operation

Run one step and exit:

    python scripts/netregress_pipeline_worker.py --once

Run as a supervised polling process:

    python scripts/netregress_pipeline_worker.py --poll-interval 5

The worker must run under a local OS account with access to the SQLite database
and OS credential store. It must not run with broader privileges than the
underlying provider operations require.
