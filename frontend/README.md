# NetRegress Runner UI

The modern operational UI is a React + Vite client over the canonical /api/v1 contract. Flask remains the API/session host and the older Flask/Jinja page remains available as a compatibility dashboard.

## Start the dashboard locally

Use two terminals from the repository root. Node.js 20.19+ (or 22.12+) is required.

### Terminal 1 — authenticated Flask API

```bash
source wifi-venv/bin/activate

export NETREGRESS_AUTH_REQUIRED=1
export NETREGRESS_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"

read -r -s -p "Dashboard password for owner: " DASHBOARD_PASSWORD
printf '\n'
export NETREGRESS_AUTH_USERS_JSON="$(DASHBOARD_PASSWORD="$DASHBOARD_PASSWORD" python -c 'import json,os; from lib.security import AuthManager; print(json.dumps([{"username":"owner","password_hash":AuthManager.password_hash(os.environ["DASHBOARD_PASSWORD"]),"role":"OWNER","projects":["*"]}]))')"
unset DASHBOARD_PASSWORD

python dashboard/app.py
```

The API stays bound to 127.0.0.1:5000. Keep this terminal open.

### Terminal 2 — React/Vite UI

```bash
cd frontend
npm install
npm run start
```

Open **http://127.0.0.1:5173** and sign in with username **owner** and the password entered in Terminal 1. Both `npm run start` and `npm run dev` launch the Vite development server, which proxies /api/* to the local Flask server. The frontend dev server binds to loopback by default.

Legacy Flask/Jinja compatibility UI: **http://127.0.0.1:5000**.

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
npm install
npm run start
npm run dev
npm test
npm run build
npm run preview
```

Vite builds a static bundle into frontend/dist. Production hosting must serve that bundle from a host/path that proxies /api/v1 to the Runner. Runtime browser verification is still required before retiring the Flask/Jinja compatibility layer.

## npm install compatibility

This frontend pins its direct build/test toolchain in `package.json`. The project-local `.npmrc` enables `legacy-peer-deps` as a workaround for npm Arborist's `Cannot read properties of null (reading 'edgesOut')` crash observed with the Vite/Vitest optional peer graph on older distro-provided npm. This setting is scoped to `frontend/`; it is not a global npm setting. `@testing-library/react` v16 also requires `@testing-library/dom`, so both are explicitly pinned in the frontend's development dependencies rather than relying on npm's peer-dependency auto-install. When updating Vite, the React plugin, Testing Library, or Vitest, run `npm test` and `npm run build` and review dependency compatibility explicitly.
