# Stage A — Architecture, Portability and Product Foundation

**Repository:** `Nirmal-Yash/wifi-validation-framework`  
**Baseline:** `fedb90a9837cebba670b6bd521ca066d6c3ca3c9` (`main`, 11 November 2026)  
**Stage:** A — P00 through P03  
**Status:** Foundation implementation recorded; provider, desktop and product workflows remain intentionally incomplete.

## 1. Purpose and scope

Stage A establishes the baseline and compatibility rules, creates platform and runtime boundaries, refreshes the React application shell, and introduces the first canonical workspace resource relationships:

```text
Organization
    └── Project
          └── Lab
                └── Topology (later phase)
```

The work is additive. It does not replace the current validation Runner, change its existing public commands, or migrate existing Linux-only provisioning and capture code to an abstraction prematurely.

## 2. P00 — Baseline and compatibility record

### Repository inventory at the baseline

The GitHub `main` reference pointed to `fedb90a9837cebba670b6bd521ca066d6c3ca3c9`. Its recursive Git tree contained 241 tracked files. The important implementation areas are:

| Area | Existing source of truth | Stage A treatment |
|---|---|---|
| Validation execution and Run lifecycle | `lib/services/run_service.py`, `run_orchestrator.py`, `run_process.py` | Preserved; no Runner lifecycle rewrite |
| Command security and device connectivity | `lib/services/command_runner.py`, `command_security.py`, `lib/adapters/` | Preserved; portable direct-child process contract is separate |
| Persistence | `lib/repositories/sqlite.py`, `database_migrations.py`, `schema_contract.py` | Additive migration and repositories |
| Identity and sessions | `lib/security/auth.py`, `dashboard/api_v1.py`, `frontend/src/auth/` | Existing static-role/session behavior preserved |
| Evidence and capture | `lib/capture.py`, `lib/services/protocol_evidence.py`, artifact services | Preserved; no capture workflow modification |
| Lab configuration | `configs/topology.yaml`, `configs/devices.yaml`, `configs/test_params.yaml` | Frozen in this stage |
| Operations | `scripts/start_dashboard.sh`, `scripts/netregress_install.py`, `wifi_lab_reprovision_robust.sh` | Preserved |
| React product interface | `frontend/src/App.jsx`, `components/layout.jsx`, pages and shared CSS | Existing routes and API contracts retained; shell and theme refreshed |

### Public command compatibility

The following root/CLI entry points remain the supported operational interface:

```bash
./run_all.sh
./scripts/start_dashboard.sh
python scripts/netregress_install.py
python scripts/netregress_doctor.py
python scripts/netregress_db.py status
python scripts/netregress_db.py check
python scripts/netregress_db.py upgrade
python scripts/netregress_reproduce.py <RUN_ID>
```

The documented test commands remain unchanged:

```bash
python -m pytest tests/ -v --firmware-version=v1.0
python -m pytest -m real_lab tests/ -v --firmware-version=v1.0
python -m pytest -m real_lab tests/ --collect-only -q
```

The protected `real_lab` command is for the approved lab host only. Stage A does not run or reset the physical/virtual Wi-Fi lab.

### Frozen topology and capture invariants

The current reference topology remains `WiFi Regression Lab`. The following node IDs and meanings are compatibility-critical:

| Node ID | Current role |
|---|---|
| `frr-router` | FRR router / iperf3 server |
| `hostapd-ap` | hostapd software access point |
| `wifi-client` | wpa_supplicant client VM |
| `monitor` | packet capture monitor |

The current links remain unchanged: router-to-AP Ethernet, AP-to-client simulated Wi-Fi through `mac80211_hwsim`, router-to-monitor Ethernet, and client-to-host management via the GNS3 Cloud/host bridge. Logical simulated Wi-Fi is not reinterpreted as an Ethernet link.

No Stage A change edits `configs/topology.yaml`, `configs/devices.yaml`, `wifi_lab_reprovision_robust.sh`, capture execution, protected PCAP paths, pytest collection or test node IDs. The existing Linux RunProcessManager remains authoritative for its `/proc` process-identity checks and process-group termination safeguards.

## 3. P01 — Cross-platform architecture foundation

### Added platform package

The new `lib/platform/` package defines:

- Platform family and capability reporting.
- Application path resolution for source checkouts and packaged Linux, Windows and macOS layouts.
- Protocol contracts for platform adapters, providers, process executors and secret stores.
- A shell-free `SubprocessExecutor` using argument vectors.
- A Linux Secret Service adapter using `secret-tool`; secret material is passed over standard input, not command-line arguments.
- Explicit Windows and unsupported-platform adapters that fail closed for secure state directories and secret storage until native ACL and Credential Manager integration exists.
- Provider-availability probing, including a check for the Linux `mac80211_hwsim` module.

### Path policy

For source checkouts, legacy paths remain the default:

- Private local state: repository `.local/`.
- Runtime results: repository `results/`.
- Database: `results/test_results.db`.
- Existing `NETREGRESS_LOCAL_DIR`, `NETREGRESS_DATABASE_PATH`, `TEST_DB_PATH` and SQLite `DATABASE_URL` semantics remain supported.

Packaged builds can resolve to user-specific OS locations: XDG directories on Linux, Local/Roaming AppData on Windows, and Application Support/Preferences/Caches on macOS. Resolution is read-only; it does not create directories.

### Process and platform safety boundary

The new executor starts only a direct child process, with `shell=False`, and controls only that child. It is not a drop-in replacement for `RunProcessManager`: it does not provide the Linux process-group manifest, PID-reuse checks or recovery semantics. Existing protected Run supervision is not weakened or redirected through this new interface.

Windows is an architectural target, not a supported native Wi-Fi simulation environment yet. `mac80211_hwsim` remains Linux-kernel functionality. The Windows adapter therefore reports hwsim unavailable and directs that workload to a Linux Runner or remote Linux lab. Windows ACL enforcement and Credential Manager are explicitly unavailable and fail closed.

## 4. P02 — Frontend visual system and shell

The existing React/Vite application remains the frontend. Stage A does not introduce a second frontend, replace routing, invent API endpoints, or expose unfinished product pages.

The shell changes include:

- Product-oriented identity: **Network Lab Platform**.
- Clearer Workspace, Quality and Governance grouping.
- Updated navigation labels while retaining every existing URL and page.
- A local runtime context and revised application footer.
- Light theme as the first-run visual default; a previously saved explicit light/dark choice is retained.
- Shared design tokens for shell geometry, spacing, surfaces, radii, focus treatment and shadows.
- Responsive layout refinements for desktop, tablet and narrow screens.
- Reduced-motion handling for the new page entrance effect.

The current feature screens remain Runner-backed: Overview, Validation Runs, Run detail, Test detail, Evidence Library, System Readiness, Regression Analysis, Performance, Wi-Fi Telemetry, Lab Health, Baselines and Operations. New project, device, credential and topology pages are not claimed as implemented in Stage A.

## 5. P03 — Backend domain and persistence foundation

### Initial resource domain

New immutable domain entities provide the initial ownership hierarchy:

- `Organization`: unique global slug and lifecycle status.
- `Project`: owned by one organization; slug unique within that organization.
- `Lab`: owned by one project; lab name unique within the project; identifies a provider and topology revision.

Identifiers are UUID strings generated by `new_resource_id()`. Domain constructors validate non-empty identities, valid resource status, timestamps and positive topology versions.

### Database migration

A new Alembic revision, `20261111_04`, follows `20261105_03`. It adds only:

- `organizations`
- `projects` with a restrictive organization foreign key
- `labs` with a restrictive project foreign key
- Ownership indexes and uniqueness constraints

The canonical SQLite schema metadata advances from version 12 to version 13. Earlier revisions remain unchanged. Existing Runner tables, Runs, Attempts, test results, artifacts, baselines and evidence are not rewritten by this migration.

### Repositories

SQLite repositories implement save, update, read and parent-scoped list operations for organizations, projects and labs. Duplicate/unique conflicts and missing parent references are translated to `RepositoryConflictError`. The canonical schema-drift contract includes the new tables, indexes and foreign keys.

This is a persistence/domain foundation only. Account membership, authorization scopes, organization administration APIs, project/lab CRUD endpoints and UI are scheduled for Stage B.

## 6. Verification and acceptance

The new automated coverage includes:

- Source-checkout and packaged path resolution.
- Windows and Linux host capability reporting.
- Fail-closed handling of unavailable Windows credential and ACL adapters.
- Argument-vector process execution and direct-child termination.
- Secret Service use of stdin rather than argv.
- Cross-platform network-interface enumeration for environment fingerprints.
- Resource identity/validation, ownership persistence, duplicate conflicts and missing-parent rejection.
- Alembic head/schema-drift verification against version 13.

The expected verification commands are:

```bash
python -m pytest tests/test_platform_foundation.py tests/test_product_resources.py tests/test_environment_fingerprint.py -v
python -m pytest tests/test_schema_migrations.py tests/test_repositories.py -v
python -m pytest tests/ -v --firmware-version=v1.0
(cd frontend && npm test && npm run build)
```

The protected real-lab test command is intentionally not part of routine Stage A CI. A source change or passing fake-provider test is not a substitute for operator-approved protected lab qualification.

## 7. Explicitly deferred

Stage A does not deliver:

- Native Windows installation, desktop packaging or Credential Manager.
- A Tauri desktop shell or bundled backend runtime.
- A Windows replacement for Linux process-group identity supervision.
- Native Windows `mac80211_hwsim`, hostapd or wpa_supplicant lab simulation.
- GNS3 node/link lifecycle management or topology reconciliation.
- Organization/project/lab APIs, account membership and dynamic RBAC.
- Dashboard-driven credential, device, configuration or performance-policy workflows.
- A migration of the legacy shell provisioning script to provider services.

These are later product phases. The current Runner remains operationally authoritative until each corresponding migration is completed and certified.

## 8. Stage A compatibility statement

Stage A is accepted only when existing CLI and route contracts remain available, the original lab topology and capture implementation are unchanged, all schema changes are additive and Alembic-managed, resource ownership constraints are enforced by SQLite, and new platform adapters fail closed instead of simulating unsupported OS security behavior.

CI status and protected lab acceptance must be recorded separately; neither should be inferred from the other.
