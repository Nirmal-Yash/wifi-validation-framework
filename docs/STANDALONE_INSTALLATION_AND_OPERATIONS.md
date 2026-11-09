# NetRegress Standalone Installation and Operations

This guide describes the current standalone Runner behavior. SQLite remains the local persistence authority. Alembic owns schema changes. The local dashboard and Runner can operate without a Cloud/SaaS service.

## 1. Supported runtime and prerequisites

- Python 3.11 or newer.
- Node.js version permitted by frontend/package.json (currently ^22.22.2 || ^24.15.0 || >=26.0.0) and npm for the React/Vite dashboard.
- Git for source-bound release manifest operations.
- Linux is the supported environment for the protected GNS3/mac80211_hwsim lab and its operational scripts.
- Required Python packages are declared in requirements.txt.

Optional protected-lab programs include ip, iw, tcpdump, ssh, iperf3 and tshark. They are checked only when the doctor is invoked with --include-lab-tools; a workstation-only Runner does not need to pretend those checks were performed.

**Dependency reproducibility limitation:** this repository currently has neither a complete Python transitive lockfile nor a frontend npm lockfile. requirements.txt and frontend/package.json declare direct dependencies, but the resolved transitive graph is not fully frozen. The release manifest explicitly reports this as INCOMPLETE_TRANSITIVE_LOCKFILES and sets production_reproducible to false. Do not describe this checkout as fully reproducible until both lockfiles are committed and verified with clean-machine installs.

## 2. Clean installation

From the repository root:

~~~bash
python3 -m venv wifi-venv
source wifi-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/netregress_install.py
~~~

The installer validates that it is running from a NetRegress checkout, creates the results and private local-state directories, and upgrades the canonical SQLite database to the single Alembic head. Existing databases are backed up by the migration manager before schema mutation. Installer failures are reported as JSON and return a non-zero exit code.

For a non-mutating preflight:

~~~bash
python scripts/netregress_install.py --check-only
~~~

To prepare directories but defer database initialization:

~~~bash
python scripts/netregress_install.py --skip-database
~~~

Use --database /absolute/path/to/runner.sqlite to select an explicit SQLite database. The normal database resolver still applies when the option is omitted.

Install the frontend toolchain after Node/npm have been installed:

~~~bash
cd frontend
npm install --no-audit --no-fund
cd ..
~~~

The dashboard launcher also installs frontend dependencies when they are missing or stale. Because the npm lockfile is not present, this is not a transitive-lockfile reproducible install yet.

## 3. Configuration and first-time authentication

Copy .env.example to .env only when you are ready to configure the deployment. Populate secrets through a protected operator channel; never commit .env, session secrets, router passwords, firmware credentials or authentication hashes. Restrict .env to owner-only access.

The standard dashboard launcher reads NETREGRESS_LOCAL_DIR and the backend/frontend port settings from a private .env when the corresponding process environment variables are not set. The process environment takes precedence. The Python database resolver loads the same protected .env with override disabled, so database selection is consistent across the dashboard, installer and database CLI. The launcher rejects .env symlinks and files accessible by group/other users.

The standard dashboard launcher manages first-run local credentials:

~~~bash
./scripts/start_dashboard.sh
~~~

On first startup it prompts interactively for an OWNER password, writes only the password hash to .local/netregress-auth.json, generates .local/session-secret, and applies owner-only permissions. The launcher does not print either secret. Keep .local/ private and backed up only under your organization's secret-handling procedure.

To rotate the local OWNER password and signing secret:

~~~bash
./scripts/start_dashboard.sh --reset-owner
~~~

This command is interactive and invalidates existing signed sessions by rotating the session secret. Do not use non-interactive shell arguments or command history to pass passwords.

The dashboard defaults to Flask on 127.0.0.1:5050 and Vite on 127.0.0.1:5173. The launcher validates distinct, non-privileged ports, starts both processes, checks the API health endpoint and frontend/API proxy, and stops both on Ctrl+C. Do not bind this local development launcher to a public interface or expose it through an unreviewed reverse proxy.

## 4. Health diagnostics

Read-only environment and database diagnostics:

~~~bash
python scripts/netregress_doctor.py
~~~

Check the running local dashboard:

~~~bash
python scripts/netregress_doctor.py --check-dashboard
~~~

Check prerequisites for the protected lab:

~~~bash
python scripts/netregress_doctor.py --include-lab-tools
~~~

Or use the corresponding python scripts/netregress_release.py doctor options.

Every check is reported as one of:

- PASS: the condition was executed and verified.
- WARNING: a non-blocking limitation or optional capability is absent.
- FAIL: a required condition is not satisfied.
- NOT_CHECKED: the operator did not request the check or the condition cannot be established from this invocation.

The doctor is read-only. It does not create runtime directories, initialize a database, migrate schema, repair permissions, start the dashboard, or repair the lab. It does not print credential contents. A zero exit code means no required check failed; it does not mean all optional or unrequested checks passed.

## 5. Database status, upgrade and recovery

Alembic is the only schema migration authority. Do not alter schema tables manually or stamp an unknown revision.

Inspect migration and physical schema status:

~~~bash
python scripts/netregress_db.py status
python scripts/netregress_db.py check
~~~

Apply pending revisions:

~~~bash
python scripts/netregress_db.py upgrade
~~~

The migration manager takes a consistent online SQLite backup before upgrading an existing database, verifies the migrated schema against the contract, and restores the backup when an upgrade fails. Retain the backup until application-level checks pass.

## 6. Backup and restore

Create a verified backup:

~~~bash
python scripts/netregress_db.py backup --output results/backups/manual.sqlite
~~~

The result includes source/destination, SQLite integrity result, byte size and SHA-256. The destination must not already exist.

Before restoring, stop all Runner, pytest and dashboard processes that can access the database. Then explicitly confirm the restore:

~~~bash
python scripts/netregress_db.py restore --backup results/backups/manual.sqlite --confirm
~~~

Restore verifies the backup's SQLite integrity and supported Alembic revision before replacing the configured database. It also creates a pre-restore backup of the current database when one exists. After restore, run:

~~~bash
python scripts/netregress_db.py check
python scripts/netregress_doctor.py
~~~

A successful file copy is not recovery acceptance. Confirm schema state, application initialization and the expected Run/evidence records. Preserve the pre-restore backup until this verification completes.

## 7. Upgrade procedure

For a source checkout, fetch and fast-forward the intended release; do not merge unrelated local work:

~~~bash
git fetch origin
git pull --ff-only origin main
~~~

With the supported virtual environment active, update the declared dependencies:

~~~bash
python -m pip install -r requirements.txt
cd frontend
npm install --no-audit --no-fund
cd ..
~~~

Review the release notes and current environment before upgrading a production or protected-lab operator. Stop the dashboard launcher, active Runner workers and pytest processes before schema maintenance; the migration lock serializes migrations but does not quiesce active product Runs. Create an explicit backup:

~~~bash
python scripts/netregress_db.py backup --output results/backups/pre-upgrade.sqlite
~~~

Then initialize/upgrade and verify:

~~~bash
python scripts/netregress_install.py
python scripts/netregress_db.py check
python scripts/netregress_doctor.py
~~~

The migration manager's automatic pre-migration backup is an additional safeguard, not a replacement for an operator-retained backup. If the migration fails, stop and inspect the JSON recovery result; do not bypass Alembic or manually repair revision metadata.

## 8. Release manifest and source readiness

Run the source release gate and emit the manifest:

~~~bash
python scripts/netregress_release.py verify
python scripts/netregress_release.py manifest
~~~

Verify the generated manifest against the current source checkout:

~~~bash
python scripts/netregress_release.py verify-manifest --manifest results/release-manifest.json
~~~

The manifest is source-bound: it includes the Git branch/commit/tree, clean-tree state, dependency/lockfile status, runtime compatibility, Alembic revision inventory, required source paths, forbidden tracked runtime items and SHA-256 digests for tracked files. It intentionally omits wall-clock generation time so an unchanged source checkout produces the same manifest content. The repository does not yet declare a separate Runner service version; application.version is therefore reported as NOT_DECLARED, while the frontend package version is listed separately. Do not treat the frontend package version as a Runner release version.

A manifest is not a signed release artifact and does not prove that dependencies were installed, the dashboard was deployed, the protected lab ran, or physical firmware was certified. The production_reproducible field remains false until the Python and frontend transitive lockfiles exist and are included in the release.

## 9. Standalone 11-scenario certification

Generate the certification matrix:

~~~bash
python scripts/netregress_certification.py
~~~

The emitted matrix documents each scenario's objective, preconditions, execution method, expected behavior, required controls, evidence types, verification criteria and required execution class.

Evidence is supplied as a scenario-keyed JSON object. Each scenario record includes:

~~~json
{
  "status": "PASS",
  "lifecycle": "COMPLETED",
  "outcome": "VALIDATED",
  "controls": ["required_tests", "required_evidence"],
  "executions": [
    {
      "execution_id": "unique-execution-id",
      "execution_class": "HARDWARE_FREE",
      "status": "PASS",
      "executed_at": "2026-11-09T12:00:00+00:00",
      "source_commit": "full-40-character-git-commit",
      "environment_fingerprint": "64-character-sha256",
      "command": "exact command that was executed",
      "evidence": [
        {
          "type": "RUN_SNAPSHOT",
          "path": "results/certification-evidence/run.json",
          "sha256": "64-character-sha256-of-the-file"
        }
      ]
    }
  ]
}
~~~

Every required execution class must have a passing execution bound to the current Git commit, timezone-aware execution timestamp, environment fingerprint, command and at least one file whose SHA-256 is verified beneath results/. REAL_LAB and PROTECTED_TARGET records additionally require operator and approval-reference attestations. Evidence types required by each scenario must all be present.

Evaluate the complete matrix:

~~~bash
python scripts/netregress_certification.py --evidence results/certification-evidence.json
~~~

The command exits non-zero when evidence is missing, stale, malformed, outside results/, hash-invalid, or from the wrong execution class. The JSON evidence remains an operator/Runner attestation; it is not cryptographically signed by this CLI. Protect the evidence source and review attestations before accepting certification.

The real_lab_baseline scenario requires the REAL_LAB execution class. Hardware-free tests, synthetic PCAPs, fake adapters, source compilation and hosted CI cannot satisfy it. The firmware scenario separately requires a PROTECTED_TARGET execution. Do not claim the matrix is complete unless the evaluator passes against the intended release commit and every external acceptance record is valid.

## 10. Offline operation and shutdown

Offline sync remains operator-triggered and outbound-only:

~~~bash
python scripts/netregress_sync.py --url "$NETREGRESS_SYNC_URL"
~~~

No Cloud endpoint is required for local Runner operation. A sync failure must not alter local Run/TestResult outcomes. Keep the endpoint configured only when an approved remote service exists and its HTTPS destination passes the Runner's security validation.

For a graceful dashboard stop, press Ctrl+C in the launcher terminal. Confirm the API and frontend ports are released before restarting. Do not kill arbitrary processes by port/PID without first verifying process ownership.

## 11. Protected Wi-Fi lab and physical firmware boundary

The existing GNS3/mac80211_hwsim topology, management path, Wi-Fi validation path, DHCP capture on br0, monitor-interface ownership, Paramiko foreground tcpdump/SFTP workflow, pytest node IDs and provisioning CLI are protected compatibility boundaries.

- Run the canonical real-lab suite only on the approved protected host.
- Do not automatically change the normal 12-hour DHCP lease to accelerate T1/T2 tests.
- A shortened DHCP lease requires a separately approved isolated test window and restoration of the normal configuration.
- Virtual hwsim telemetry is virtual evidence, not physical RF certification.
- Fake firmware adapters validate code contracts only. Physical flashing, reboot, version verification and rollback require the approved target hardware and operator authorization.
- Do not replace live capture or hardware evidence with generated/synthetic artifacts.

## 12. Phase N completion status

Source implementation and hosted CI are distinct from operational certification. The following remain separate acceptance items until actual evidence exists:

- Python and frontend transitive dependency lockfiles, followed by clean-machine install verification.
- A clean-machine install/upgrade/backup/restore rehearsal.
- Authenticated browser/reverse-proxy deployment verification using production secrets and trusted proxy configuration.
- Protected GNS3/mac80211_hwsim 11-scenario REAL_LAB evidence.
- Physical firmware target flash/reboot/rollback evidence where that scenario applies.
- Production deployment, independent dependency scanning and threat-model acceptance.

Phase O Cloud/SaaS remains deferred until the standalone Runner is operationally certified. Phase P remains the final repository-wide organization and cleanup phase.
