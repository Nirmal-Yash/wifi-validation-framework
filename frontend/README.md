# NetRegress Runner UI

The React/Vite client is the operational frontend for the Flask Runner's canonical `/api/v1` contract. Legacy Flask/Jinja routes remain in the repository; the React/Vite application is the canonical operational UI.

## One-command local setup

From the repository root on Ubuntu:

```bash
git status --short
git pull --ff-only origin main
./scripts/start_dashboard.sh
```

Stop previous Flask/Vite terminals with **Ctrl+C** first. Review any local changes before pulling; do not discard them to force an update.

The launcher uses `wifi-venv/bin/python` (or `.venv/bin/python`), checks ports, verifies the API health endpoint and starts Flask plus Vite together. It creates a local OWNER account on first launch and reuses the password hash on subsequent launches. Username: **`owner`**. The password is at least 12 characters and is never stored as plaintext. Credentials and the Flask signing secret are retained in the Git-ignored `.local/` directory with restricted permissions.

Open **http://127.0.0.1:5173**. Flask listens on **127.0.0.1:5050** by default; port **5000** is left for the local GNS3 service. To override either local service port, set both variables explicitly:

~~~bash
NETREGRESS_PORT=5051 NETREGRESS_FRONTEND_PORT=5174 ./scripts/start_dashboard.sh
~~~

Each launcher run writes a timestamped, permission-restricted verification log to the .local/logs/ directory. It records toolchain checks, port checks, dependency/auth checks, Flask health, Vite root and the API health response through the Vite proxy. Sensitive credential values are redacted.

Reset the owner password and rotate the signing secret (invalidating prior sessions) with:

```bash
./scripts/start_dashboard.sh --reset-owner
./scripts/start_dashboard.sh
```

## Frontend architecture

- **React 19 + Vite 8** for the application runtime and local development server.
- **Tailwind CSS v4** for the utility layer and central design tokens.
- **shadcn/ui-style component architecture**, configured by `components.json`, with Radix UI primitives for accessible Dialog, Dropdown Menu, Tabs, Tooltip and Slot behavior. Reusable project-owned components live under `src/components/ui`; they are source components, not a remote runtime dependency.
- **TanStack Query** for server-state caching, request refetching, mutation lifecycle and cache invalidation on sign-out.
- **Lucide React** for consistent icons and action affordances.
- A single responsive Sidebar/AppShell, shared form/card/table/status primitives, and a shared page-heading hierarchy. Dark/light themes persist only the non-sensitive visual preference.

## Authentication and session controls

The UI uses the Flask signed session cookie. It does **not** store passwords, session cookies, access tokens or CSRF tokens in localStorage/sessionStorage.

- The session is restored from `GET /api/v1/auth/me`; the API decides whether the cookie is authenticated.
- The cookie is named `netregress_session`, is HttpOnly, SameSite=Lax and refreshed on requests. Local HTTP development keeps Secure disabled; set `NETREGRESS_SESSION_COOKIE_SECURE=1` when serving behind HTTPS.
- CSRF tokens are fetched from `/api/v1/auth/csrf` and retained in memory only. State-changing requests include `X-CSRF-Token`; POST requests also carry an idempotency key. A stale CSRF token is refreshed once only after the API returns `CSRF_REQUIRED`.
- The client warns after 27 minutes of inactivity and signs out at 30 minutes. Flask independently enforces a 30-minute authenticated-request idle timeout and a 1-hour sliding permanent-cookie lifetime. Continue-session explicitly revalidates `/auth/me`; sign-out/expiry clears TanStack Query cache and in-memory CSRF state.
- A 401 on a protected API request triggers a global session-expired transition. API/connection errors are not presented as invalid passwords.
- Login attempts are rate-limited server-side. The UI does not replace that control.
- This standalone local Runner does not currently implement MFA, OIDC/SAML SSO, self-service user provisioning or a distributed session store. Do not describe those capabilities as enabled; add an identity provider and shared session/rate-limit infrastructure before multi-user or cloud deployment.

## RBAC and server authority

The frontend permission matrix mirrors the backend's roles:

| Role | View | Execute Runs / firmware operations | Admin baselines / waivers | Owner-only |
| --- | --- | --- | --- | --- |
| OWNER | Yes | Yes | Yes | Yes |
| ADMIN | Yes | Yes | Yes | No |
| OPERATOR | Yes | Yes | No | No |
| VIEWER | Yes | No | No | No |

The matrix hides unauthorized navigation and controls and provides a clear access-denied page. It is only a usability boundary: Flask's API remains authoritative for view, execute, admin, project-scope, CSRF and idempotency checks. Firmware/rollback actions and waiver creation require a confirmation step; release waiver controls are hidden from Operators and Viewers.

## Data presentation rules

- Lifecycle state, test status, evidence state, and business outcome remain separate fields.
- A pytest `PASS` is not shown as a release validation outcome.
- Dashboard distributions disclose their denominator (latest eight Runs) and keep missing/unrecognized outcomes visible.
- Metric charts do not mix different metric names or units. Summary means include only explicit `VALID`, finite numeric, non-warm-up samples. Raw observations remain accessible.
- Telemetry charts are split by metric/unit. Environment classification remains visible, and virtual WiFi is not represented as physical RF certification.
- Empty, loading, partial, and error states are distinct. Charts include accessible descriptions and supporting value tables.

## Development and verification

```bash
cd frontend
npm install
npm test
npm run build
npm run start
```

Node.js **22.12.0+ on 22.x**, **any 24.x**, or **26+** is required by the pinned Vite 8 / Vitest 5 toolchain. For normal use, prefer `./scripts/start_dashboard.sh`, which aligns the authenticated Flask backend and Vite proxy. Keep Flask and Vite processes on the same local host/port configuration. Production deployment must serve the built assets over HTTPS, set Secure cookies and retain the same-origin `/api/v1` proxy boundary.

Run the backend security contract tests after changes to session configuration:

```bash
cd ..
source wifi-venv/bin/activate
python -m pytest tests/test_auth_flow.py tests/test_rbac_auth.py tests/test_dashboard_rbac_matrix.py -q
```

Do not interpret a successful frontend build as proof of backend authorization or a successful REAL_LAB certification. Browser/manual verification is required before removing the Flask/Jinja compatibility UI.

## npm compatibility

The project-local `.npmrc` contains `legacy-peer-deps=true` to work around the previously observed npm Arborist `edgesOut` resolver crash. It is scoped to `frontend/`; it does not change global npm configuration. Run `npm test` and `npm run build` after any dependency update.

 
Project scopes fail closed. The current Run query/persistence contract has no project ID to filter on, so users configured with named projects (or an empty project list) are denied unscoped Run API access. The legacy Flask dashboard also rejects non-wildcard scopes. The default local OWNER uses the explicit wildcard scope `["*"]`. Do not assign restricted project scopes until project-aware Run queries and resource-level authorization are implemented.

The local session is a signed Flask cookie, not a shared server-side session service. The API validates the cookie, CSRF token, role and 30-minute idle timestamp; rotating the local signing secret invalidates all cookies. Before multi-worker, hosted or multi-tenant deployment, move sessions and login-rate limits to shared server-side stores with explicit per-session revocation.
