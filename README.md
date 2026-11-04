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

Supporting contracts remain separate:
- docs/EXECUTION_AND_ADAPTERS.md
- docs/SECURITY_AND_SAAS.md
- docs/FRONTEND_DESIGN.md
- docs/PRD.md
- docs/AGENT_CONTEXT.md

## Current quick start

~~~bash
python3 -m venv wifi-venv
source wifi-venv/bin/activate
pip install -r requirements.txt
pytest tests/ -v --firmware-version=v1.0
~~~

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

## Lab provisioning

~~~bash
./wifi_lab_reprovision_robust.sh
./wifi_lab_reprovision_robust.sh --setup-only
./wifi_lab_reprovision_robust.sh --repro-test
~~~

Run the provisioning script as the normal Ubuntu user, not with sudo.

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
