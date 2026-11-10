# NetRegress Validation Engine

NetRegress is an evidence-driven WiFi/network validation and regression engine. This repository is the Runner/Core layer that executes real validation against the GNS3/mac80211_hwsim lab today and is designed to control physical devices through adapters later.

## Protected behavioral baseline

~~~text
commit: 436026eba597b2c6ae2e291a9cd8054b70ebbf7c
historical result: 11 / 11 real-lab tests PASS
~~~

That is the historical network-behavior baseline. The current test suite is much larger because it now includes hardware-free Runner, persistence, security, evidence, recovery, API and release-contract tests.

Use these scopes explicitly:

~~~bash
# Full repository verification suite
pytest tests/ -v --firmware-version=v1.0

# Protected GNS3/mac80211_hwsim tests only
pytest -m real_lab tests/ -v --firmware-version=v1.0

# See the current REAL_LAB test count without executing
pytest -m real_lab tests/ --collect-only -q
~~~

The historical 11/11 result must not be interpreted as the expected collection count of the current full suite.

## Current capabilities

- real WPA2 state validation;
- DHCP lease and timing validation;
- DNS resolution;
- ping, loss and latency;
- iperf3 throughput;
- real DHCP PCAP capture;
- fault injection and recovery;
- SQLite persistence;
- firmware-version comparison;
- Flask dashboard and production React/Vite UI;
- automated GNS3 laboratory provisioning.

## Canonical documentation

Read the canonical documents in this order:

1. docs/01_DEVELOPMENT_PLAN_AND_ROADMAP.md — development order, historical phases and roadmap
2. docs/02_SYSTEM_ARCHITECTURE_DATA_API.md — backend architecture, data model and API
3. docs/03_TRACEABILITY_AND_SYSTEM_READINESS.md — traceability, audit and readiness
4. docs/04_WIFI_LAB_REPRODUCTION_TESTING_OPERATIONS.md — installation, exact lab reproduction and operations
5. docs/05_ARCHITECTURE_DECISIONS_AND_BUSINESS_LOGIC.md — architecture decisions and business invariants
6. docs/STANDALONE_INSTALLATION_AND_OPERATIONS.md — standalone installation, maintenance, recovery and certification operations
7. docs/UPGRADE_AND_FIRST_RUN_GUIDE.md — upgrade an existing checkout, pull current main, migrate the database, and operate the upgraded Runner

Supporting contracts remain separate:
- docs/EXECUTION_AND_ADAPTERS.md
- docs/SECURITY_AND_SAAS.md
- docs/FRONTEND_DESIGN.md
- docs/PRD.md
- docs/AGENT_CONTEXT.md

## Standalone installation and first startup

Supported Python runtime: 3.11 or newer. The dashboard frontend also requires a Node.js release matching frontend/package.json (currently Node.js 22.22.2+, 24.15+, or 26+).

~~~bash
python3.11 -m venv wifi-venv
source wifi-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Prepare runtime directories and upgrade the canonical SQLite schema.
python scripts/netregress_install.py

# Read-only environment and database diagnostics.
python scripts/netregress_doctor.py

# Start the authenticated local dashboard (first run prompts for OWNER credentials).
./scripts/start_dashboard.sh
~~~

Open the local Vite URL printed by the launcher (default http://127.0.0.1:5173). Press Ctrl+C to stop both frontend and API processes. See docs/STANDALONE_INSTALLATION_AND_OPERATIONS.md for upgrades, backup/restore, release metadata, certification evidence and recovery procedures.

Preflight without creating directories or changing the database:

~~~bash
python scripts/netregress_install.py --check-only
~~~


## Test execution

Run the full repository test suite from the activated virtual environment:

~~~bash
python -m pytest tests/ -v --firmware-version=v1.0
~~~

Run the protected GNS3/mac80211_hwsim suite only on the approved lab host:

~~~bash
python -m pytest -m real_lab tests/ -v --firmware-version=v1.0
~~~

Collect protected tests without executing them:

~~~bash
python -m pytest -m real_lab tests/ --collect-only -q
~~~

Hardware-free CI, fake-adapter tests and synthetic PCAP fixtures do not replace the protected real-lab execution.

## Database path configuration

The Runner uses one SQLite database path across the dashboard, pytest session orchestration, health checks and operational CLI tools. Resolution order is:

1. An explicit path passed to `SQLiteDatabase(path)` or a CLI `--db` / `--database` option.
2. `NETREGRESS_DATABASE_PATH`.
3. The backward-compatible `TEST_DB_PATH` alias.
4. A SQLite `DATABASE_URL` (`sqlite:///` or `sqlite+pysqlite:///`).
5. The repository default `results/test_results.db`.

When both `NETREGRESS_DATABASE_PATH` and `TEST_DB_PATH` are set, they must resolve to the same file or startup fails closed. Non-SQLite `DATABASE_URL` values are not enabled by the standalone Runner. Use `NETREGRESS_DATABASE_PATH` for new deployments; retain `TEST_DB_PATH` only while migrating existing environments.

~~~bash
export NETREGRESS_DATABASE_PATH="$PWD/results/test_results.db"
python scripts/netregress_sync.py --url "$NETREGRESS_SYNC_URL"
python scripts/netregress_reproduce.py <RUN_ID>
~~~

## Legacy database migration

The legacy lib.db_helper API remains available as a facade over canonical Run/Attempt/TestResult repositories. It no longer writes the historical test_runs or baselines tables. Compatibility records are explicitly unvalidated and cannot become release baselines.

Import legacy tables already present in the configured database:

~~~bash
python scripts/netregress_migrate_legacy.py
~~~

Or import from a separate read-only historical database:

~~~bash
python scripts/netregress_migrate_legacy.py --source /path/to/historical-results.db --target results/test_results.db --source-identity wifi-lab-archive-2024
~~~

Review the JSON summary and reconcile imported, skipped, invalid, failed and unavailable-artifact counts before retiring the source backup. The command is idempotent; failed rows remain retryable. Legacy baseline snapshots remain imported comparison history only. Promote trusted baselines through python regression/baseline_runner.py --version v1.0, which requires a native validated Run and healthy lab state.

## Schema migrations and database recovery

Alembic is the schema migration authority. Application initialization upgrades the configured SQLite database to the single repository head and refuses to run if the physical schema drifts from the required contract. An existing database is backed up before upgrade; failed upgrades restore that backup.

Inspect the database without changing it:

~~~bash
python scripts/netregress_db.py status
python scripts/netregress_db.py check
~~~

Apply pending revisions and verify the result:

~~~bash
python scripts/netregress_db.py upgrade
~~~

Create and restore an explicit backup:

~~~bash
python scripts/netregress_db.py backup --output results/backups/manual.sqlite
~~~

Stop every Runner, pytest and dashboard process before restoring:

~~~bash
python scripts/netregress_db.py restore --backup results/backups/manual.sqlite --confirm
~~~

A restore creates a verified pre-restore copy of the current database. Schema downgrades do not drop data; use a verified backup to roll back. Keep automatic pre-migration backups until the upgraded database passes the operator's integrity and application checks.

## Lab provisioning

Run as the normal Ubuntu user, not with sudo. The default provisions and validates the lab but does not start pytest. Select one test mode explicitly:

~~~bash
./wifi_lab_reprovision_robust.sh
./wifi_lab_reprovision_robust.sh --run-ci-tests
./wifi_lab_reprovision_robust.sh --run-real-lab-tests
./wifi_lab_reprovision_robust.sh --run-full-suite
~~~

--repro-test is a separate destructive recovery operation: it stops GNS3 nodes, resets runtime Wi-Fi state and runs the complete suite. Use it only with explicit lab-maintenance approval.

## Engineering rules

- develop directly on main;
- no feature branches;
- one architectural slice per commit;
- preserve existing pytest node IDs;
- never weaken assertions to make a test pass;
- never use synthetic traffic in real validation;
- never convert lab failure into product failure;
- never return PASS when required evidence failed;
- keep runtime results gitignored.

## Release verification

~~~bash
python scripts/netregress_release.py verify
python scripts/netregress_release.py doctor
python scripts/netregress_release.py manifest
~~~

The release manifest and GitHub Actions gates are source/CI readiness evidence. They do not substitute for protected GNS3/mac80211_hwsim execution or authenticated browser/runtime certification.

## Standalone release and certification

The standalone Runner remains locally authoritative; Cloud/SaaS is not required for local execution. Use the release tools to inspect source readiness and generate a source-bound manifest:

~~~bash
python scripts/netregress_release.py doctor
python scripts/netregress_release.py verify
python scripts/netregress_release.py manifest
python scripts/netregress_release.py verify-manifest --manifest results/release-manifest.json
python scripts/netregress_certification.py
~~~

The manifest is deterministic for an unchanged Git checkout and records the tracked-file inventory and SHA-256 digests. Its production_reproducible field remains false until both Python and frontend transitive dependency lockfiles exist. The current repository does not contain those lockfiles; the direct dependency declarations alone are not a complete lock.

The 11-scenario certification matrix is an execution/evidence gate. Generate the matrix with python scripts/netregress_certification.py; evaluate a scenario-keyed evidence JSON with --evidence. Each required execution must identify the current source commit, a 64-character environment fingerprint, a timezone-aware timestamp, its command, and SHA-256-verified evidence files below results/. REAL_LAB and PROTECTED_TARGET records additionally require operator and approval-reference attestations. A matrix listing or passing hardware-free CI does not certify the protected lab or physical firmware.


## Offline synchronization status

Inspect local delivery state without configuring or contacting a remote endpoint:

~~~bash
python scripts/netregress_sync.py --status
~~~

This read-only command reports QUEUED, IN_FLIGHT, ACKED, FAILED and BLOCKED counts. It does not initialize/migrate the database, transmit data, or expose payloads or stored error text. Synchronize only after an approved HTTPS endpoint and credential have been configured:

~~~bash
python scripts/netregress_sync.py --url "$NETREGRESS_SYNC_URL"
~~~

The historical root entry points remain available as compatibility wrappers: run_all.sh uses the canonical installer, test suite and authenticated dashboard launcher; verify_system.py delegates to the canonical release gate.
