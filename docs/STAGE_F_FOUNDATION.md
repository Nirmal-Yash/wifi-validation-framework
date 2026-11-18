# Stage F — Linux Desktop Foundation

Stage F introduces a packaged Linux desktop application while keeping the existing local-first Runner architecture and service contracts. The target experience is install, launch, create the first Owner account, and operate the Runner without cloning the repository, creating a virtual environment, installing Node.js, or manually launching Flask.

## Implemented foundation

### P30 — Tauri desktop shell

- Tauri 2 hosts the existing React production build from `frontend/dist`.
- The shell starts a bundled Python Runner sidecar during application setup.
- The backend binds only to `127.0.0.1` on an automatically selected free port.
- The shell waits for the Runner's health endpoint before presenting the application.
- The sidecar is terminated when the desktop application exits.
- The webview receives the local API base URL through a narrow Tauri command; it does not guess a port or use a wildcard CORS origin.
- The Content Security Policy allows the frontend assets, Tauri IPC, and the loopback API only.

### P31 — packaged backend runtime

- PyInstaller bundles the Python backend and its runtime dependencies.
- The bundle includes the Alembic migrations, runtime configuration, test definitions, pytest tree, compatibility pipeline worker, and the existing Wi-Fi provisioning script as read-only application resources.
- The frozen executable dispatches the Runner's pytest and pipeline-worker child-process commands, preserving the existing execution model without requiring a system Python installation.
- Run process logs are redirected into the persistent user-data area rather than the temporary PyInstaller extraction directory.
- The backend initializes or upgrades its SQLite database before serving requests.
- The application-data, configuration, cache, state, log, runtime, result, capture, backup, and process directories are private to the current Linux user.
- The Flask session key is generated once, stored as a 0600 file, checked for symlink/ownership/permission problems, and reused across restarts.
- The packaged runtime enforces authentication and does not depend on a pre-seeded JSON password file.

### First-run identity

- A loopback-only setup status endpoint determines whether the persistent identity store has any accounts.
- First-run setup creates the first Global Owner atomically inside a SQLite immediate transaction.
- The bootstrap route rejects remote clients and untrusted browser origins, applies the login-attempt limiter, enforces the existing username/password policy, and becomes permanently unavailable after the first account is committed.
- The React login route presents a first-run Owner account form and confirms the password before submission.
- Existing account login and server-side RBAC enforcement remain the authority after bootstrap.

## Linux package build

The CI workflow `.github/workflows/desktop-linux.yml` builds a PyInstaller sidecar, the React production UI, and Tauri Linux packages on **Ubuntu 22.04 and Ubuntu 24.04**. Each OS leg independently exercises the generated installers under Xvfb:

- Install the generated Debian package and launch its installed executable.
- Wait for the packaged sidecar health endpoint, create the first Global Owner through the local-only setup route, and authenticate.
- Shut down and restart the desktop app, then verify the Owner account and persistent SQLite database survive.
- Remove the Debian package and verify user data is retained.
- Launch the AppImage through its extracted runtime, repeat first-run creation/login/restart checks, and retain smoke logs with the package artifacts.

Expected release artifacts are a Debian `.deb` package and an AppImage per qualified OS leg, accompanied by SHA-256 checksums. The initial automated Linux desktop qualification matrix is Ubuntu 22.04 and Ubuntu 24.04. This is an explicit support target, not a claim of compatibility with every Linux distribution or desktop environment. Debian 12 is not yet in the hosted qualification matrix.

Build prerequisites for contributors are the Tauri v2 Linux system packages, Rust 1.100.0, Python 3.12, Node.js 22.22.2, and the pinned frontend, Python runtime and Python desktop-build dependencies. See the Tauri documentation for the platform dependency matrix and Debian/AppImage runtime requirements.

## Persistent user data

The desktop shell passes the OS-resolved application data and configuration locations to the backend. SQLite data, logs, session material, validation process logs, captures and backups are held outside the installed application tree. Updating or uninstalling the application must not silently remove these user files.

## Qualification boundaries

The hosted package workflow builds the PyInstaller/Tauri bundles and runs the Debian/AppImage lifecycle smoke test in Xvfb on Ubuntu 22.04. The Debian test installs the package, starts the installed desktop executable, verifies the local sidecar health check, creates the first Owner, authenticates, restarts, verifies the same account/database, removes the package and checks user-data retention. Both package paths also invoke the frozen backend directly to run the embedded first-run, persisted pipeline orchestration and pipeline-to-canonical-Run/policy integration tests in explicit hardware-free CI mode (without real lab credentials or device provisioning), and execute the bundled pipeline worker against an empty smoke database. This checks the business-logic contracts inside the PyInstaller runtime, not only in the source Python environment. The AppImage test checks the same first-run and restart path. These are automated CI checks; they do not execute real GNS3/OpenWrt provisioning, replace interactive rendering, or certify a customer target machine.

### P33 — Linux workstation qualification

Implemented in source/CI: the Debian and AppImage package build plus first-run/restart/removal lifecycle now run independently on Ubuntu 22.04 and Ubuntu 24.04. Each matrix leg uploads OS-labelled packages and lifecycle evidence. The automated check uses Xvfb and verifies the visible X11 window title/geometry, keyboard focus probe and XWD screenshots, alongside process launch, backend health, Owner bootstrap, restart persistence, Debian package-version upgrade/downgrade and package removal behaviour. It still does not certify interactive rendering quality, launcher/menu integration or desktop-session behaviour on a real user workstation.

Remaining operator acceptance: install on clean physical/VM machines for both supported Ubuntu releases; inspect the rendered interface, launcher/menu integration, keyboard/focus behaviour, desktop-session process supervision and user-facing error paths; exercise upgrade/reinstall/rollback and verify user data retention. Do not advertise Debian 12 or other distributions until their own package/runtime matrix is green.

The live protected GNS3/mac80211_hwsim/physical OpenWrt lab remains a
separate operator acceptance gate from hosted CI. Stage E's Python GNS3,
host-readiness, libvirt and Docker guest provisioning adapters are implemented
with deterministic hosted contract tests; the shell entry point remains a
recovery fallback for repository/config repair, destructive reset, direct
protected-suite and capture/evidence operations until real-lab parity is
recorded. No destructive protected-lab reset is part of desktop startup.

## Future targets

- Windows packaging remains a separate W1 qualification target. Windows uses the Windows Credential Manager and a Linux remote Runner for hwsim-specific operations.
- SaaS control-plane work remains a separate S1 target and is not introduced by this local desktop package.
