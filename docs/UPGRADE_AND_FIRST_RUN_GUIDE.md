# NetRegress — Upgrade, Reinstall, First-Run and Operations Guide

This procedure upgrades an existing install or prepares a clean checkout of the current standalone Runner, from pulling current `main` through database migration, dashboard startup, test execution and release acceptance.

## 1. Understand the implementation phases

The phases are source history, not a sequence of installers:

- **Phase A** is the historical protected Wi-Fi behavioral baseline (`436026eba597b2c6ae2e291a9cd8054b70ebbf7c`, historically 11/11 real-lab tests). It is not a setup command and has not been re-certified on every later revision.
- **Phases B–N** are implemented source/CI slices covering Run and evidence correctness, canonical SQLite persistence, legacy migration, Alembic schema governance, process reliability, configuration/resource orchestration, protocol evidence, telemetry/performance, device/firmware lifecycle, security, API/dashboard/frontend, regression/release/offline operations and standalone packaging.
- **Phase O** full Cloud/SaaS remains future scope. The delivered bounded addition is local read-only sync-queue status only. There is no Cloud receiver, tenant database, PostgreSQL service, distributed sessions or inbound remote Runner control.
- **Phase P** repository organization and compatibility cleanup is delivered. Legacy command names remain as wrappers; history was not rewritten.

For an upgrade, pull `main`, install dependencies, run the canonical installer (Alembic upgrades the existing database), then run doctor and tests. Do **not** cherry-pick or manually replay every phase.

## 2. Runtime and compatibility

| Component | Supported boundary |
|---|---|
| OS | Linux for Runner/lab operation. Protected GNS3/mac80211_hwsim instructions target Ubuntu 22.04 in a VirtualBox guest. |
| Python | 3.11 or newer; hosted backend CI uses 3.12. Ubuntu 22.04 stock `python3` may be 3.10. Install/use a separate interpreter; do not replace the OS Python symlink. |
| Node.js | `frontend/package.json`: 22.22.2+, 24.15+ or 26+. CI uses 22.22.2. |
| UI | React 19, Vite 8, Vitest 5; npm is required to install/test/build. |
| Database | Local SQLite; Alembic is the only schema migration authority. Non-SQLite `DATABASE_URL` is not enabled in the standalone Runner. |
| Dashboard | Flask API at 127.0.0.1:5050 and Vite UI at 127.0.0.1:5173 by default. |

**Reproducibility gate:** release reproducibility requires exact Python direct pins, a hash-locked Python dependency graph, and a tracked npm lockfile whose root metadata and direct dependencies match `frontend/package.json`. A present-but-stale lockfile is rejected by the release manifest. Run `scripts/generate_dependency_locks.sh` to refresh both lockfiles; it backs up an existing local npm lock before regenerating it. The lockfiles must then be reviewed and committed. The manifest keeps `production_reproducible=false` until both are tracked and validated.

## 3. Upgrade an existing installation

### 3.1 Stop and preserve

Stop the dashboard with Ctrl+C; stop active Runner workers and pytest processes. Never migrate a database while a process may write to it.

Back up the SQLite database, any separate historical DB, private `.local/` auth/session files, private `.env`, SSH/firmware credentials, firmware images/signatures and important results/evidence. Store backups outside the source checkout or in a protected location. Do not copy secrets, DBs, PCAPs or logs into Git.

### 3.2 Pull current main safely

```bash
cd /path/to/wifi-validation-framework
git status --short
git remote -v
git branch --show-current

# Preserve/reconcile local changes before proceeding; do not reset --hard.
git fetch --prune origin
git pull --ff-only origin main
git rev-parse HEAD
git status --short
```

The supported branch is `main`. `--ff-only` prevents an implicit merge. If local modifications exist, preserve or reconcile them first; do not overwrite runtime data or private configuration.

Fresh checkout:

```bash
git clone https://github.com/Nirmal-Yash/wifi-validation-framework.git
cd wifi-validation-framework
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

Confirm the latest GitHub Actions run matches the exact HEAD you pulled; a prior green run does not validate later commits.

### 3.3 Back up the database before upgrade

After activating the supported Python virtual environment (Section 4), use the canonical DB resolver and create a new timestamped backup:

```bash
mkdir -p results/backups
python scripts/netregress_db.py status
python scripts/netregress_db.py backup \
  --output "results/backups/pre-upgrade-$(date -u +%Y%m%dT%H%M%SZ).sqlite"
```

Confirm the JSON reports `integrity_ok: true`. If the DB does not exist, continue with fresh initialization. The migration manager also takes an automatic pre-upgrade backup before modifying an existing database.

## 4. Set up Python and frontend environments

### 4.1 Python

Use Python 3.11+ (or 3.12):

```bash
python3.11 --version
python3.11 -m venv wifi-venv
source wifi-venv/bin/activate
python --version
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
python -m pip check
```

The `python` inside the activated venv must report 3.11 or newer. Do not use Ubuntu 22.04's default Python 3.10 or replace `/usr/bin/python3`. If you use Python 3.12, substitute `python3.12` when creating the venv.

### 4.2 Node and npm

```bash
node --version
npm --version
```

Use Node.js 22.22.2+, 24.15+ or 26+. Then:

```bash
cd frontend
npm ci --no-audit --no-fund
npm test
npm run build
cd ..
```

A valid, source-controlled `frontend/package-lock.json` is required. Do not bypass it with an unlocked install during normal setup. To refresh locks after intentionally changing dependencies, run `scripts/generate_dependency_locks.sh`, review the diff, and commit both generated lockfiles. The script stores a private backup of any existing local npm lock under `results/backups/`.

### 4.3 Regenerating dependency locks

Run from the repository root with the project virtual environment active and a supported Node/npm runtime:

```bash
./scripts/generate_dependency_locks.sh
```

The generator resolves Python dependencies for the CI baseline Python 3.12 with SHA-256 hashes, refreshes the npm lock from the exact committed package manifest, and preserves the previous local npm lock in `results/backups/`. Review the resulting lockfiles, then stage `requirements.lock` and force-add `frontend/package-lock.json` if a local Git exclude rule hides it. Never stage the backup.

## 5. Configuration and secrets

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` with only credentials needed by your lab. Device profiles use references like `__ENV__:WIFI_ROUTER1_PASSWORD`; populate corresponding `WIFI_*` values rather than putting plaintext in tracked YAML. Keep `.env` owner-readable only.

Important values:

- `NETREGRESS_DATABASE_PATH`: canonical SQLite file; default `results/test_results.db`.
- `TEST_DB_PATH`: backward-compatible alias; if both path variables exist, they must resolve to the same file.
- `FIRMWARE_VERSION`: default label is `v1.0`.
- `NETREGRESS_LOCAL_DIR`: optional private auth/session directory.
- `WIFI_ROUTER1_PASSWORD`, `WIFI_ROUTER2_PASSWORD`, `WIFI_AP_HOST_PASSWORD`, `WIFI_CLIENT_VM_PASSWORD`, `WIFI_MONITOR_VM_PASSWORD`, `WIFI_TEST_PSK`: populate only when required by your topology.
- `NETREGRESS_SYNC_URL` and `NETREGRESS_SYNC_TOKEN`: leave unset unless an approved HTTPS receiver exists and outbound sync is intended.

The launcher creates a random session secret and interactively prompts for the initial OWNER password. It stores a password hash and secret in owner-only `.local/` files, not plaintext password. Never commit `.env` or `.local/`.

## 6. Initialize or upgrade the database

From the repository root with the venv active:

```bash
python scripts/netregress_install.py
python scripts/netregress_db.py status
python scripts/netregress_db.py check
python scripts/netregress_doctor.py
```

The installer prepares runtime directories and upgrades the configured SQLite database to the single Alembic head. Review JSON output. Do not bypass Alembic, manually stamp unknown revisions or edit schema tables by hand.

After successful first-time initialization:

```bash
python scripts/netregress_install.py --check-only
```

First-run authentication can remain pending until you start the dashboard and create the OWNER account.

### 6.1 Import old legacy data only when necessary

If the old installation has legacy `test_runs` / `baselines` tables rather than the canonical Runner schema, preserve the source and run:

```bash
python scripts/netregress_migrate_legacy.py \
  --source /secure/backup/legacy-results.sqlite \
  --target "$NETREGRESS_DATABASE_PATH" \
  --source-identity wifi-runner-archive
```

The source is opened read-only; the import is idempotent. Reconcile imported, skipped, invalid, failed and unavailable-artifact counts. Legacy-imported Runs/baselines preserve provenance but remain unvalidated and cannot become trusted release baselines. Do not run this unnecessarily against an already canonical DB.

## 7. Start and use the dashboard

```bash
./scripts/start_dashboard.sh
```

On first startup, interactively create the OWNER password (at least 12 characters); username is `owner`. The launcher starts Flask and Vite and checks the local API/proxy. Defaults:

- UI: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:5050`

Press Ctrl+C in the launcher terminal to stop both processes. Do not expose this localhost development launcher directly to the Internet or bind it to `0.0.0.0`. Production needs reviewed HTTPS reverse-proxy, secure-cookie/HSTS, trusted-proxy client-IP and secrets configuration; hosted smoke tests do not certify those.

Reset OWNER and rotate the session secret (invalidates existing sessions):

```bash
./scripts/start_dashboard.sh --reset-owner
./scripts/start_dashboard.sh
python scripts/netregress_doctor.py --check-dashboard
```

## 8. Execute and validate

### 8.1 Hardware-free regression

```bash
python -m pytest tests/ -v --firmware-version="${FIRMWARE_VERSION:-v1.0}"
```

Frontend tests/build are separate:

```bash
cd frontend && npm test && npm run build && cd ..
```

Convenience compatibility command:

```bash
RUN_DASHBOARD=0 ./run_all.sh
```

It installs dependencies, calls the canonical installer, runs pytest and writes `results/reports/report.html`; `RUN_DASHBOARD=0` stops after tests. Ensure system `python3` is 3.11+ before using it; explicit venv commands are safer on multi-Python systems. Hardware-free CI skips protected lab cases when their lab fixtures are unavailable; SKIPPED is not PASS.

### 8.2 Protected GNS3/mac80211_hwsim lab

Collect before execution:

```bash
python -m pytest -m real_lab tests/ --collect-only -q
```

Run only on the approved Ubuntu lab host:

```bash
python -m pytest -m real_lab tests/ -v --firmware-version="${FIRMWARE_VERSION:-v1.0}"
```

Topology compatibility:

- Router `192.168.122.10`; AP `192.168.122.20`; client `192.168.122.30`; monitor `192.168.122.40`.
- `phy0` is AP, `phy1` is client; AP/client data path uses `wlan0`; management remains separate on `eth1` / `10.10.10.30`.
- DHCP/DNS capture remains on AP bridge `br0`.

Provisioning remains explicit, never automatic on Run preparation. The default (or the compatibility --setup-only option) provisions and validates without running pytest:

```bash
./wifi_lab_reprovision_robust.sh --setup-only
./wifi_lab_reprovision_robust.sh --run-ci-tests
./wifi_lab_reprovision_robust.sh --run-real-lab-tests
./wifi_lab_reprovision_robust.sh --run-full-suite
```

Run as the normal Ubuntu user, not with sudo. --repro-test stops GNS3 nodes and resets runtime Wi-Fi state before running the full suite; use it only with explicit lab-maintenance approval. Preserve foreground Paramiko tcpdump, SFTP transfer and SHA-256 PCAP verification. Do not change the normal 12-hour DHCP lease; T1/T2 capture needs an approved isolated short-lease window and restoration.

### 8.3 Firmware operations

Fake adapters validate software contracts only. Flashing changes target state. Require approval, exact target identity, model/version compatibility, image hash/signature, maintenance window, recovery path and rollback image before any flash. Physical flash/reboot/version/rollback evidence must be collected from the approved device. hwsim is not physical RF evidence.

## 9. Backup, restore and offline queue

Create a verified backup at a new path:

```bash
python scripts/netregress_db.py backup --output results/backups/manual.sqlite
```

Before restore stop dashboard, workers and pytest:

```bash
python scripts/netregress_db.py restore --backup results/backups/manual.sqlite --confirm
python scripts/netregress_db.py check
python scripts/netregress_doctor.py
```

Restore verifies DB integrity/revision and keeps a pre-restore copy when a current DB exists. Preserve it until application startup and expected records are confirmed. Back up `.env`, `.local/`, firmware and important artifacts separately.

Read local queue state without remote access:

```bash
python scripts/netregress_sync.py --status
```

This is read-only and does not migrate or contact Cloud. Actual synchronization is manual, outbound-only and needs an approved HTTPS URL/token; sync failure never changes local technical Run outcome.

## 10. Release and certification commands

```bash
python scripts/netregress_release.py verify
python scripts/netregress_release.py manifest
python scripts/netregress_release.py verify-manifest --manifest results/release-manifest.json
python scripts/netregress_release.py doctor
python scripts/netregress_release.py doctor --check-dashboard
python scripts/netregress_release.py doctor --include-lab-tools
python scripts/netregress_certification.py
python scripts/netregress_certification.py --evidence results/certification-evidence.json
```

The release manifest is source/structure evidence, not a signed release and not lab/deployment certification. Certification evidence must be tied to the exact source commit, environment fingerprint, timezone-aware timestamp, actual command and SHA-256-verified files under `results/`. REAL_LAB/PROTECTED_TARGET also require operator and approval references. Never manufacture evidence or substitute CI for it.

## 11. How the system works

1. **Request/config:** CLI/API or dashboard selects firmware, lab/device context and registered tests; configuration resolves defaults, environment, lab, device, Run and test overrides with provenance.
2. **Run orchestration:** RunService creates a Run and Attempt, acquires exclusive resources and takes a read-only BEFORE health snapshot.
3. **Execution:** pytest remains the engine. TestRegistry supplies semantic identity, versions, prerequisites, capability requirements, severity, thresholds, decision metrics and evidence requirements. Secure CommandRunner/device adapters perform approved actions.
4. **Evidence/telemetry:** packet captures, command outputs, health, measured samples and artifacts are persisted with ownership, metadata and SHA-256 integrity. Raw samples remain available; warm-up data is excluded from decision aggregates.
5. **Persistence/recovery:** repositories write Runs, Attempts, TestResults, artifacts, metrics and lifecycle events to SQLite. Alembic owns schema migration; process supervision, locks, cancellation and recovery protect lifecycle integrity.
6. **Regression/release:** only the latest Attempt counts and must exactly cover selected tests. Missing/duplicate/unexpected results, unhealthy environment, invalid evidence or incompatible baselines fail closed. Baseline promotion requires healthy validated Runs and eligible samples; waivers are scoped and audited.
7. **Presentation/offline:** authenticated dashboard reads API-backed persisted data. Local queue status is inspectable offline; delivery is manual and outbound-only.

Infrastructure failure and product failure are distinct. An unreachable AP or missing capture must not be reported as a product rejection. The result may be `LAB_FAILED` or `UNVALIDATED`. Missing required evidence must never become PASS.

## 12. Compatibility and real-world use

- Operate the standalone SQLite Runner on one controlled host/VM; do not share an active SQLite file among multiple independent hosts or treat it as distributed storage.
- Protect DBs, PCAPs, firmware, reports and credentials; define retention, access, backup and audit policies. Preserve the exact source commit and environment fingerprint for release decisions.
- Separate management and Wi-Fi validation networks; use least privilege, SSH keys/secrets, firewall allowlists and a dedicated lab.
- Use representative conditions, explicit firmware/build identity and repeated measurements. Virtual hwsim is valuable for functional tests/repeatability but does not represent all chipsets, regulatory domains, antennas, interference or real RF.
- Appropriate application: pre-release qualification/regression of AP/router firmware and Wi-Fi behavior (WPA2/handshake, DHCP/DNS, throughput, latency/loss, fault recovery and evidence capture), after lab and hardware acceptance.
- This is not yet a general-purpose network monitoring platform, multi-tenant SaaS or remote firmware fleet manager. Full Cloud/tenant/remote control stays future Phase O.

## 13. Operator checklist

- [ ] Preserve DB, `.env`, `.local/`, firmware and evidence; stop active processes.
- [ ] Pull latest `origin/main` with `git pull --ff-only` and record `git rev-parse HEAD`.
- [ ] Use Python 3.11+ and supported Node version for UI.
- [ ] Install dependencies; run `python -m pip check`.
- [ ] Back up DB; run installer, DB status/check and doctor.
- [ ] Run backend pytest suite, frontend tests/build and dashboard smoke.
- [ ] Execute protected tests only on approved lab/target hardware.
- [ ] Complete proxy, real-lab, firmware and certification gates before production acceptance.
