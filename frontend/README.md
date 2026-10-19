# NetRegress Runner UI

The modern operational UI is a React + Vite client over the canonical `/api/v1` contract. Flask remains the API/session host and the older Flask/Jinja page remains available as a compatibility dashboard.

## One-command setup and startup

From the repository root on Ubuntu:

```bash
git status --short
git pull --ff-only origin main
./scripts/start_dashboard.sh
```

Stop any old backend and Vite terminals first with **Ctrl+C**. Check `git status --short` before pulling; do not discard local modifications to force an update.

The launcher uses `wifi-venv/bin/python` (or `.venv/bin/python` when available), checks for port conflicts, installs frontend dependencies only if Vite is missing, creates the local OWNER credential on first run, verifies the Flask health endpoint, and starts the Vite UI. Press **Ctrl+C** to stop both services.

On first run, create and confirm an owner password of at least 12 characters. The username is **`owner`**. The password hash and Flask session secret are stored under the Git-ignored `.local/` directory with restricted file permissions; the plaintext password is never written to disk. Later starts reuse this account, so you keep the same login password. To reset it (and invalidate existing sessions), stop the running services and run:

```bash
./scripts/start_dashboard.sh --reset-owner
./scripts/start_dashboard.sh
```

Open **http://127.0.0.1:5173** for the React UI. By default, Flask listens on **127.0.0.1:5000** and Vite proxies `/api/*` to that same port. A shared `NETREGRESS_PORT` setting keeps the backend and frontend aligned. If port 5000 is already occupied, stop the conflicting service or use a free port for both, for example:

```bash
NETREGRESS_PORT=5050 ./scripts/start_dashboard.sh
```

The launcher refuses to start if the chosen backend port or Vite port 5173 is already occupied, instead of silently attaching to the wrong service. Do not open Flask's root page to sign in to the React UI; use the Vite URL above. Flask's root route is the legacy compatibility UI.

## Authentication behavior

- A successful login creates an HTTP-only Flask session cookie.
- A CSRF token is returned on login and attached to browser state-changing API requests.
- Invalid credentials remain on the login page with an explicit error.
- A stopped backend, proxy mismatch or non-JSON response shows a separate connection/setup screen and a retry action; it is not reported as a bad password.
- The launcher requires authentication. Do not disable authentication to work around a connection problem.

## UI surface

- authenticated login/session bootstrap/logout;
- role-aware navigation for OWNER, ADMIN, OPERATOR and VIEWER;
- Dashboard and Runner readiness;
- historical Run filtering, pagination and launch;
- Run detail with lifecycle/outcome context, tests, Lab Health, telemetry, evidence artifacts and configuration;
- Test detail with persisted execution contract, metrics/raw samples, failure semantics and evidence;
- Run-to-Run regression intelligence with comparison, classification filtering and drill-down;
- performance history with accessible SVG trend charts and tabular values;
- WiFi telemetry inspection with environment-class labeling;
- Lab Health inspection by Run or Lab;
- authenticated artifact browser and downloads;
- administrator baseline promotion;
- operator firmware update/rollback controls;
- administrator release-waiver creation;
- explicit confirmation for destructive Run actions;
- loading, empty, error and retry states;
- keyboard-accessible interactive tables;
- responsive navigation and layouts.

The dashboard KPIs use the domain's actual business outcomes (VALIDATED, VALIDATED_WITH_WARNINGS, REJECTED, UNVALIDATED) and disclose when counts cover only the latest eight Runs. They never infer a release PASS from a pytest status.

The backend remains authoritative for authorization, CSRF, idempotency, evidence integrity, path confinement and release semantics. UI role visibility is not a security boundary.

## Frontend commands

```bash
cd frontend
npm install
npm run start
npm run dev
npm test
npm run build
npm run preview
```

Use `./scripts/start_dashboard.sh` for normal local development because it configures authentication and keeps the backend/proxy ports aligned. Standalone Vite commands are intended for frontend-only work when the backend is already running on the configured port.

Vite builds a static bundle into `frontend/dist`. Production hosting must serve that bundle from a host/path that proxies `/api/v1` to the Runner. Runtime browser verification is still required before retiring the Flask/Jinja compatibility layer.

## npm install compatibility

This frontend pins its direct build/test toolchain in `package.json`. The project-local `.npmrc` enables `legacy-peer-deps` as a workaround for npm Arborist's `Cannot read properties of null (reading 'edgesOut')` crash observed with the Vite/Vitest optional peer graph on older distro-provided npm. This setting is scoped to `frontend/`; it is not a global npm setting. `@testing-library/react` v16 also requires `@testing-library/dom`, so both are explicitly pinned in the frontend's development dependencies. When updating Vite, the React plugin, Testing Library, or Vitest, run `npm test` and `npm run build` and review dependency compatibility explicitly.
