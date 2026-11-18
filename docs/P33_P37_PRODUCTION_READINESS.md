# NetRegress P33–P37 — Linux Production Readiness Programme

This document is the acceptance register for completing Stage F as a robust standalone Linux product. It distinguishes source implementation, hosted CI evidence, and operator-owned execution evidence. A green workflow is never treated as proof of a protected Wi-Fi lab or physical firmware operation.

## Release invariant

A production release must be bound to one clean Git commit and one application version. Required Run evidence must be present, owned by the correct Run/Attempt/TestResult, complete and hash-verified. Infrastructure failures remain separate from product failures. Uncertain provider mutations require explicit inspection and recovery; they are never automatically replayed.

The current four hosted checks are the three jobs in `.github/workflows/netregress-quality.yml` and the Linux package qualification workflow `.github/workflows/desktop-linux.yml`. The release-readiness workflow refuses to prepare a packet unless successful runs exist for both workflows on the exact checked-out commit.

## P33 — Linux workstation qualification

**Implemented:** The desktop package workflow independently builds and exercises Debian and AppImage packages on Ubuntu 22.04 and 24.04. Both OS legs retain separate packages, checksums and lifecycle logs.

**Hosted evidence:** Xvfb launch, visible desktop-window title/geometry, keyboard focus probe and retained XWD window screenshots; sidecar health, first Owner creation, authentication, restart, persisted identity/database, packaged setup/pipeline contract tests, pipeline-worker dispatch, Debian package-version upgrade/downgrade and removal/data retention. The Debian version transition is a package-manager contract test over the same application payload; physical clean-machine release upgrades remain operator acceptance.

**Operator acceptance still required:**
- Clean Ubuntu 22.04 and 24.04 installations on supported desktop sessions.
- Interactive GUI rendering, navigation, keyboard/focus, desktop launcher/menu and icon integration.
- User-facing errors when the backend cannot start or initialize its database.
- Upgrade, reinstall, rollback, package-manager and data-retention checks on real machines; hosted CI now covers Debian package-version upgrade/downgrade using the same payload.
- Process supervision and graceful shutdown/restart under active user sessions.

Debian 12 and distributions outside this matrix are not certified.

## P34 — Supply-chain and build reproducibility

**Implemented:** Production Python dependency audit, frontend production dependency audit, weekly Dependabot coverage for Python/npm/Cargo/GitHub Actions, pinned Tauri CLI, SHA-256 package verification, SPDX source SBOM generation, high-severity Grype scanning of the Python/npm/Cargo application dependency SBOM, GitHub package provenance/SBOM attestations, and automated resolution plus hash-locking of the Python runtime, PyInstaller build and Rust/Cargo dependency graphs. The lock generator uses Python 3.11/pip-tools, Node/npm and a pinned Rust 1.100.0 toolchain. The desktop build consumes the hash-locked PyInstaller graph and Cargo uses the committed lockfile.

**Release invariant:** the release manifest validates all runtime and build lockfiles and must report `COMPLETE` with `production_reproducible=true`. Lock generation is followed by a guarded fast-forward-only commit to main; if main changes while resolution is running, the automation refuses to push stale lock data. Required quality and desktop qualification workflows are explicitly dispatched against the lock commit.

The exact-commit readiness packet now independently verifies package checksums and GitHub attestations and includes an SPDX license inventory. Unresolved license declarations remain marked for human review. Before GA, complete manual license compatibility approval and document packaged/system runtime coverage and the supported toolchain.

## P35 — Reliability, concurrency and recovery qualification

**Implemented:** The hosted quality workflow repeats a 108-test Linux reliability suite twice. It covers resource locks, process ownership/cancellation, fake-runner fault apply/restore compensation, Alembic migration and backup restoration, private desktop runtime state, desktop startup/display/focus diagnostics, pipeline orchestration and leases, sync queue recovery and standalone operations. The hardware-free repeat gate deliberately excludes `tests/test_negative_recovery.py`, which is marked REAL_LAB and requires protected Wi-Fi credentials; those protected fault/recovery scenarios remain operator acceptance, not hosted CI.

**Remaining operator qualification:**
- Run a controlled long-duration soak on the target Linux class.
- Exercise concurrent users and concurrent Run requests against one and multiple Labs.
- Test process kill, application crash, host reboot, lock-owner death, full disk and interrupted database migration.
- Verify backups while idle, restore to a clean installation, and validate the restored Run/evidence history.
- Record recovery time, data-loss bound, disk/CPU/memory pressure and any unresolved process/lease state.

Do not invent an enterprise SLA until this evidence has been collected.

## P36 — Packaged end-to-end business workflow

**Implemented:** Both Debian and AppImage package lifecycle paths execute the frozen backend's first-run and persisted-Project workflow contracts across ten core product test modules: desktop setup, Project scope, credential vault, device inventory, configuration profiles, performance policy, topology apply, configuration deployment, pipeline orchestration and pipeline runtime. The packaged smoke also runs the artifact-verification contract test as an additional supply-chain module. They then dispatch the packaged worker against an isolated empty queue. On each supported Ubuntu CI image the packaged suite reports 77 passed and the worker reports `IDLE`. Providers are simulated in hosted CI; these results do not substitute for protected REAL_LAB evidence.

**Remaining operator acceptance:** Execute the full business workflow on the protected lab:
1. Create or select Organization, Project and Lab.
2. Register devices, credentials and capabilities.
3. Publish configuration, performance-policy and topology revisions.
4. Plan, approve and apply provisioning/topology changes.
5. Execute a persisted pipeline and canonical validation Run.
6. Verify the latest Attempt, selected-test coverage, metrics, telemetry, PCAP/protocol evidence and hashes.
7. Evaluate performance policy, regression and release gate.
8. Verify failure classification, cleanup, recovery, audit and export.

The shell recovery entrypoint remains available until the Python provisioning route has real-lab parity. Do not substitute fake adapters or synthetic PCAPs for protected lab evidence.

## P37 — Release certification

**Implemented:** `.github/workflows/linux-release-readiness.yml` verifies both hosted workflows on the exact commit, downloads the two OS package artifacts from that exact desktop run, checks SHA-256 sums and verifies provenance plus SPDX SBOM attestations against the repository, signer workflow and source commit before generating the source-bound manifest and 11-scenario matrix. It requires a clean release-ready checkout, a declared Runner version, matching manifest/matrix commit IDs and `dependencies.status=COMPLETE` with `production_reproducible=true`. Its artifact is explicitly labelled `PRE_CERTIFICATION`; a matrix alone never counts as scenario evidence.

**Required before Linux GA:**
- Supply scenario-keyed evidence to `python scripts/netregress_certification.py --evidence results/certification-evidence.json`.
- Pass all 11 scenarios against the intended release commit, including HARDWARE_FREE, REAL_LAB and PROTECTED_TARGET execution classes where required.
- Include timestamp, environment fingerprint, exact command, evidence type, SHA-256 and required operator/approval attestations.
- Complete interactive desktop, clean-machine upgrade/backup/restore, protected GNS3/mac80211_hwsim and applicable physical firmware acceptance.
- Complete the manual SPDX license compatibility review, confirm packaged/system runtime dependency coverage, and approve the final release manifest.

The release-readiness workflow does not publish a GA release and cannot certify the protected lab. The final certification evaluator remains fail-closed.

## Current hard blockers

1. Human approval of the generated license inventory and review of unresolved SPDX declarations, plus verification of packaged/system runtime dependency coverage. Source dependency SBOM vulnerability scanning and exact-commit consumer checksum/attestation checks are automated.
2. Interactive Ubuntu desktop qualification and clean-machine upgrade/rollback/backup/restore evidence are operator tasks.
3. Protected GNS3/mac80211_hwsim provisioning, real captures and the 11-scenario REAL_LAB evidence are not established by hosted CI.
4. Physical firmware flash/reboot/rollback evidence requires the approved physical target where that scenario applies.
5. The reliability soak and recovery objectives must be measured on target equipment before declaring an SLA.

## Explicit non-goals for Linux GA

Windows packaging, Cloud/SaaS, centralized tenant control, PostgreSQL, Kubernetes, microservices, multi-region operation and enterprise SAML remain separate programmes. They must not delay a focused, correctly certified local-first Linux Runner.
