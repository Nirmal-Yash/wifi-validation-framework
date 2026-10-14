# NetRegress Runner UI

The frontend is a production-oriented React + Vite presentation layer over the canonical /api/v1 Runner contract.

## Implemented application surface

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

The backend remains authoritative for authorization, CSRF, idempotency, evidence integrity, path confinement and release semantics.

## Development

Use Node.js 20.19+ or 22.12+.

Commands: npm install, npm run dev, npm run build, npm test.

Vite builds a static bundle into frontend/dist. The application expects the Runner API at /api/v1; in production, serve the built frontend from a host/path that proxies /api/v1 to the Runner.

## Contract boundary

The UI never invents validation results, converts UNVALIDATED to PASS, treats virtual WiFi as RF certification, or bypasses backend authorization.