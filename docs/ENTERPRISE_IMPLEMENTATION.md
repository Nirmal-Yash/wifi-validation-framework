# NetForge Enterprise Implementation

This document records the implementation program that moves NetForge from a validation test collection toward a network validation control plane.

## Iteration 1 — Enterprise 802.1X

Implemented the privileged validation harness at `scripts/validate_enterprise_8021x.py`.

The harness requires the real Tier-1 Linux host, root privileges, a Wi-Fi interface, and explicit environment credentials. It observes WPA completion and IP acquisition; it never manufactures a PASS.

Environment variables:

- `NETFORGE_WIFI_IFACE`
- `NETFORGE_ENTERPRISE_SSID`
- `NETFORGE_8021X_IDENTITY`
- `NETFORGE_8021X_PASSWORD`
- `NETFORGE_8021X_TIMEOUT`

**Important:** repository-side implementation is complete, but the live pass criterion remains a physical/privileged environment gate.

## Iteration 2 — Structured Metrics

Managed executions now receive test duration metrics through the pytest hook in `conftest.py`. The database supports arbitrary numeric measurements with units. The API can also record explicit metrics.

Recommended production metrics include throughput, authentication latency, DHCP lease time, roaming handoff duration, packet loss, DNS latency and retry counts.

## Iteration 3 — Execution Dashboard

`/operations` is an operations console with:

- execution queue
- lifecycle phase
- aggregate result counts
- execution detail
- topology hash/version
- metrics
- artifacts
- events
- retry
- cancel
- analysis

## Iteration 4 — Analytics / Regression

`/analytics` provides outcome and metric charts and a regression table. The regression engine uses successful historical samples, excludes the candidate execution, and requires five samples before emitting a regression finding.

## Iteration 5 — Authentication / RBAC

`dashboard/auth.py` implements session authentication, password hashing and roles:

- admin
- operator
- viewer

The first admin is bootstrapped only when `NETFORGE_ADMIN_PASSWORD` is explicitly supplied. There is no production default password.

POST control-plane APIs require the session CSRF token.

## Iteration 6 — Artifact Management

Execution logs and JUnit output are copied under `artifacts/executions/<execution-id>/` and indexed in the `evidence` table with SHA-256 checksums. The control plane exposes authenticated artifact retrieval.

## Iteration 7 — Topology / Execution Integration

Execution creation snapshots the active topology version and hashes the current `config/devices.yaml`. This makes a historical run reproducible even if the working topology changes later.

The existing topology versioning system remains the source of truth for topology identity.

## Iteration 8 — Retry / Recovery / Worker Hardening

Managed execution supports:

- cancellation
- retry
- subprocess isolation
- timeout
- worker identifiers
- terminal state persistence
- event history
- artifact indexing

The worker is deliberately single-host today. This is a controlled boundary for later worker-pool adoption.

## Iteration 9 — Audit / Security

Important execution and user-management operations create audit events. API command arguments reject common shell operators because execution is performed through argv rather than a shell.

Security posture includes:

- password hashing
- RBAC
- CSRF tokens
- HTTP-only SameSite sessions
- no default production password
- artifact path containment
- bounded execution runtime
- explicit Tier-2 adapter requirement

A reverse proxy with TLS is recommended for production.

## Iteration 10 — Physical / Tier-2 Abstraction

`engine/infrastructure.py` defines a stable adapter boundary. Tier-1 maps to the local simulated environment. Tier-2 currently refuses implicit physical changes until a concrete lab adapter is configured. This is intentional: enterprise safety is preferable to silently running destructive device operations.

## Iteration 11 — Production Deployment

Included:

- `Dockerfile`
- `docker-compose.yml`
- systemd service
- environment template
- Nginx reverse proxy example
- backup utility
- health endpoint

The recommended production WSGI entry point is:

`dashboard.enterprise_app:app`

## Iteration 12 — Release / Validation

CI validates database bootstrap and the non-live test suite. The release gate must additionally run the privileged Tier-1 Enterprise 802.1X harness and the full live suite on the actual lab host.

## Architecture

```text
Browser
  |
  v
Nginx / TLS
  |
  v
Gunicorn
  |
  v
NetForge Control Plane
  |-- Authentication / RBAC
  |-- Execution API
  |-- Topology API
  |-- Analytics API
  |-- Artifact API
  |-- Audit API
  |
  +--> Execution Orchestrator --> Pytest --> Tier-1 Linux lab
  |
  +--> SQLite domain store
  |
  +--> Artifacts / evidence
```

## What is intentionally not faked

The following cannot be truthfully certified from GitHub Actions alone:

1. WPA_COMPLETED against the actual Enterprise PEAP/MSCHAPv2 lab.
2. Physical Tier-2 device behavior.
3. RF/roaming behavior against real AP/client hardware.

NetForge contains the execution and evidence infrastructure to certify those items when the real lab is available.
