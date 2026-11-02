# Dashboard Startup, Port Mapping and Verification Audit

## 1. Canonical local service map

| Layer | Address | Responsibility |
|---|---|---|
| Browser | http://127.0.0.1:5173 | React/Vite dashboard UI |
| Vite API proxy | http://127.0.0.1:5173/api/* | Same-origin browser API boundary |
| Flask Runner API | http://127.0.0.1:5050 | Versioned /api/v1 API and session authority |
| GNS3 local service | http://127.0.0.1:5000 | Separate GNS3 service; not managed by NetRegress |

The browser calls relative paths under /api/v1. Vite proxies the /api prefix to Flask, preserving the complete /api/v1/... path. The launcher explicitly sets the proxy target to http://127.0.0.1:5050 by default. Flask and Vite bind to loopback; this local workflow does not expose either service on a LAN interface.

NETREGRESS_PORT changes the Flask port and proxy target together. NETREGRESS_FRONTEND_PORT changes the Vite UI port. Defaults are 5050 and 5173 respectively. Port 5000 is deliberately not selected by the dashboard launcher.

## 2. Node.js compatibility contract

The supported frontend engine expression is:

~~~text
^22.12.0 || ^24.0.0 || >=26.0.0
~~~

This is aligned across frontend/package.json and scripts/start_dashboard.sh. Vitest 5 declares Node ^22.12.0 || ^24.0.0 || >=26.0.0; Vite 8 and @vitejs/plugin-react support Node >=22.12.0 on the 22.x line. Node 22.22.1 therefore satisfies the declared dependency engine range and is no longer rejected by an unnecessarily high patch-level gate. Node 23.x and 25.x are intentionally excluded by the package engine expression.

## 3. Runtime verification log

Every normal launcher invocation creates a private, timestamped log under:

~~~text
.local/logs/dashboard-startup-<UTC timestamp>-<PID>.log
~~~

The directory is mode 0700; each log is mode 0600. The log includes timestamped PASS/FAIL/INFO events and captures launcher, Flask, npm and Vite stdout/stderr. It records versions, selected ports, dependency checks, auth-file validation, service health, UI availability, API proxy verification and shutdown status. Passwords, password hashes, session secrets and serialized auth configuration values are never intentionally written to the log.

The startup sequence verifies, in order:

1. Selected Python runtime and imports of Flask and AuthManager.
2. Node.js and npm availability, reported versions and Node engine compatibility.
3. Backend and frontend port syntax, allowed range, non-collision and current availability.
4. Frontend dependency presence/freshness; dependency installation when required.
5. Local OWNER record structure and session-secret presence/permissions.
6. Flask process liveness and GET /api/v1/health response envelope directly on the backend port.
7. React/Vite root document availability and root mount element.
8. Same-origin GET /api/v1/health through Vite, requiring the canonical JSON data envelope. This detects a missing or incorrect proxy target rather than mistaking Vite's HTML fallback for an API response.
9. Both service processes are stopped when the launcher exits.

The scripts/test_dashboard_startup.sh smoke test exercises the real launcher with isolated temporary credentials and a temporary SQLite database. It then tests the browser-facing UI and session path through Vite: unauthenticated session restore, OWNER login, cookie flags, CSRF retrieval, CSRF-protected activity, logout and post-logout session rejection. GitHub Actions uploads the per-run startup log as a workflow artifact.

## 4. Port and route traceability

| Contract | Source of truth | Verification |
|---|---|---|
| Flask default is 5050 | dashboard/app.py | tests/test_dashboard_port_contract.py |
| Flask port override | NETREGRESS_PORT | tests/test_dashboard_port_contract.py |
| Vite UI default is 5173 | frontend/vite.config.js | launcher UI-root smoke check |
| Vite proxy default target is Flask 5050 | frontend/vite.config.js | launcher proxied health check |
| Launcher selects the matching proxy target | scripts/start_dashboard.sh | launcher end-to-end health check |
| API prefix is /api/v1 | frontend/src/api.js and dashboard/api_v1.py | browser-facing proxy and auth smoke test |
| GNS3 remains on port 5000 | external GNS3 configuration | launcher does not bind, stop or rewrite port 5000 |

## 5. Verification boundaries

GET /api/v1/health confirms that the Flask API process responds and that the configured Vite proxy reaches it. It does not establish that the database is operationally ready, that GNS3/mac80211_hwsim is healthy, or that a physical WiFi test has passed. The authenticated /api/v1/readiness endpoint, lab-health evidence and REAL_LAB tests remain separate gates.

This audit is limited to dashboard startup, Node compatibility, port configuration, frontend-to-backend routing and the authentication/session path. It must not be cited as evidence of physical RF certification or a successful REAL_LAB execution.
