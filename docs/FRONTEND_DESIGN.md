# NetRegress — Frontend Architecture and Dashboard Design

## 1. Frontend strategy

Do not rewrite the current Flask/Jinja dashboard yet.

Flask/Jinja plus plain JavaScript remains the presentation layer through Phase 8 because the Run, evidence, regression and telemetry contracts are still being stabilized.

The canonical modern UI is React + Vite over the versioned `/api/v1` contract. The Flask/Jinja dashboard remains as a compatibility presentation layer while the React client is validated in deployment. Cloud/Project semantics remain backend concerns and are not duplicated in the browser.

## 2. API-first principle

Every new frontend capability is backed by a versioned /api/v1 contract.

Jinja must consume the same contracts intended for the future React client.

This makes the frontend migration a presentation change rather than a backend rewrite.

## 3. Primary user

The landing experience optimizes for the Release Engineer question:

> Is this firmware validated and safe to release according to the configured policy?

Network and validation engineers receive specialized detail pages.

## 4. Information architecture

~~~text
Home / Current Run
  ├── Release decision
  ├── Run status
  ├── Lab Health
  ├── Pass/fail summary
  └── Blocking issues

Runs
  ├── Historical runs
  └── Run detail

Tests
  └── Test detail

Quality
  └── Regression analysis

Performance
  └── Metric trends

Telemetry
  └── WiFi measurements

Lab Health
  └── Component health

Evidence
  └── Artifact browser
~~~

## 5. Historical Runs

Route: /runs

Columns:

- Run ID;
- firmware;
- device;
- lab;
- profile;
- lifecycle status;
- business outcome;
- pass/block/fail counts;
- evidence state;
- duration;
- timestamp.

Filters:

- project;
- firmware;
- device;
- lab;
- profile;
- status;
- outcome;
- date.

## 6. Run Detail

Route: /runs/{run_id}

Header:

- human Run ID;
- lifecycle status;
- business outcome;
- firmware;
- device;
- lab;
- duration.

Health strip:

- GNS3;
- hwsim;
- AP;
- client;
- router;
- DHCP;
- DNS;
- SSH;
- disk;
- clock.

Test section:

- blocking failures;
- advisory issues;
- all test results;
- progress during execution.

Evidence section:

- PCAP;
- pytest report;
- setup log;
- health snapshot;
- environment fingerprint;
- diagnostic bundles.

## 7. Test Detail

Route: /runs/{run_id}/tests/{test_result_id}

Must answer:

- what test ran;
- what test version;
- why it ran;
- what it required;
- functional result;
- metric result;
- baseline comparison;
- regression classification;
- sample statistics;
- evidence;
- failure reason;
- reproduction command.

## 8. Regression Analysis

Route: /regressions

Capabilities:

- baseline selection;
- current Run selection;
- compatibility warning;
- functional regressions;
- soft regressions;
- fixed results;
- improvements;
- NO_BASELINE;
- UNVALIDATED;
- filter/search;
- drill-down to Test Detail.

## 9. Performance

Route: /performance

Show historical trends for:

- throughput;
- latency;
- jitter;
- packet loss;
- CPU utilization;
- memory utilization.

Plots should expose the underlying sample/statistic in accessible text so the chart is never the only representation of the value.

## 10. Telemetry

Route: /telemetry

Show:

- RSSI;
- SNR;
- channel;
- frequency;
- bitrate;
- PHY mode;
- retry/failure counters when available;
- source and capture timestamp.

Every graph identifies whether data is VIRTUAL_WIFI or PHYSICAL_WIFI. Telemetry cards must preserve the same label at point level rather than relying only on a chart-level legend.

UI copy must explicitly state that virtual telemetry is not RF certification.

## 11. Lab Health

Route: /lab-health

Primary purpose: determine whether the environment is trustworthy before interpreting test results.

Each component shows:

- state;
- last checked;
- diagnostic summary;
- evidence link;
- version or identity;
- remediation guidance.

Lab Health must not silently trigger repair.

## 12. Artifact Browser

Route: /artifacts

Searchable by:

- Run;
- test;
- artifact type;
- firmware;
- device;
- timestamp;
- checksum status.

Artifact download uses authenticated API access.

Never expose arbitrary filesystem paths.

## 13. Live run behavior

Continue using ten-second polling during early phases.

While a Run is RUNNING, the page displays:

- completed tests;
- active test;
- elapsed time;
- Lab Health;
- artifact count;
- warnings/failures.

Move to SSE/WebSocket only if actual UX needs justify it.

## 14. Accessibility

Status is never conveyed by color alone.

Charts provide accessible text/table values.

Tables support keyboard navigation.

Errors are explicit rather than silently swallowed.

UTC timestamps are clearly labeled, with local display conversion at the UI boundary.

## 15. Security UX

Before operator actions exist, the dashboard is read-only.

Later state-changing controls require role authorization and explicit confirmation.

Dangerous actions display device, firmware and target scope before confirmation.

## 16. React component model

Implemented components include:

- RunSummary;
- ReleaseDecision;
- LabHealthStrip;
- TestResultTable;
- TestDetail;
- RegressionSummary;
- MetricTrendChart;
- TelemetryChart;
- ArtifactList;
- RunTimeline;
- DeviceCard;
- FirmwareCard;
- PolicyBadge.

These are conceptual components and do not justify an early SPA rewrite.

## 17. React + Vite implementation

The React client now preserves the documented URL semantics for Dashboard, Runs, Run Detail, Test Detail, Regression, Performance, Telemetry, Lab Health, Artifacts, Baselines, Operations and Runner Readiness. It reuses the canonical `/api/v1` contracts and delegates authorization, CSRF, idempotency, artifact integrity and release semantics to the backend. The Jinja dashboard remains available as a compatibility presentation layer until browser/runtime parity is independently validated and the retirement decision is made.

## 18. Frontend invariants

1. UI is a view of persisted evidence.
2. UI never invents missing results.
3. UI never converts UNVALIDATED into PASS.
4. UI never exposes unauthorized artifacts.
5. UI never claims virtual WiFi is physical RF certification.
6. UI must always make the distinction between lifecycle status and business outcome visible.

## 19. React implementation status

The React UI is now the implemented modern Runner presentation layer. It covers authenticated Run operations, filtering and pagination, Run/Test inspection, regression analysis, performance trends, telemetry, Lab Health, artifact browsing, baseline administration, firmware operations, waiver administration and structured Runner readiness. State-changing controls remain RBAC-aware in the UI while API authorization remains authoritative. Browser/runtime verification remains a separate acceptance gate.

Telemetry, regression, evidence, lifecycle and environment semantics are rendered from persisted API facts and never inferred into PASS states.


## 8. React/Vite implementation
The Runner includes a React + Vite operational application consuming `/api/v1`. The implementation is componentized into routed pages, reusable tables/status cards/forms, semantic badges, accessible charts, confirmation dialogs, loading/error/empty states and role-aware navigation. API authorization remains authoritative; UI visibility is not a security control.

## 20. Iterations 26–27 security and certification UX
The operational API remains the authority for mutation authorization, CSRF, idempotency and artifact boundaries. Browser state changes now require a session-bound CSRF token. The UI may surface the certification matrix and release/readiness status, but it must never infer certification from the presence of a generated matrix alone.

Certification scenario records must distinguish execution class, especially REAL_LAB, from hardware-free and simulated evidence. The frontend must preserve lifecycle/failure classification and must not convert LAB_FAILED, UNVALIDATED or Runner failures into product PASS states.


## 21. Local development and presentation update

The modern local development flow runs Flask on 127.0.0.1:5050 and React/Vite on 127.0.0.1:5173; port 5000 remains available for the local GNS3 service. Vite proxies /api/* to Flask so the browser uses one origin for the API session and CSRF workflow. Configure a local OWNER using NETREGRESS_AUTH_REQUIRED=1, NETREGRESS_SESSION_SECRET, and NETREGRESS_AUTH_USERS_JSON as shown in frontend/README.md; do not add a default password to the repository. The Vite development host is loopback-only by default.

The dashboard presentation now uses an operational hero, explicit refresh context, consistent action links, refined spacing/surface hierarchy, responsive layouts, reduced-motion support, and a skip-to-main-content link. KPI labels are domain-aware: total Runs are separated from latest-eight activity, and validated outcomes are counted from VALIDATED and VALIDATED_WITH_WARNINGS; REJECTED and UNVALIDATED remain visible as items needing review. No frontend number maps pytest PASS directly to business release validation.

The API remains authoritative for authorization, CSRF, idempotency, artifact containment and release-policy semantics. The browser must be exercised against the live Flask API before the React client is considered runtime-verified or the Jinja compatibility pages are retired.


## Full React application and session lifecycle

The canonical application uses React 19, Vite 8, Tailwind CSS v4, Radix primitives wrapped in project-owned shadcn-style components, Lucide icons and TanStack Query. Shared components live under `src/components/ui`; Sidebar/AppShell, modal, menu, tab, tooltip, card, table, form and status primitives share design tokens. Route changes animate into the content area; dialogs and menus use Radix focus handling; reduced-motion is respected. Navigation collapses to a mobile drawer.

Authentication is restored from the same-origin Flask session via `GET /api/v1/auth/me`. The signed cookie is named `netregress_session`, HttpOnly, SameSite=Lax, and Secure in HTTPS deployment. It is never read by JavaScript. CSRF material is requested from `/auth/csrf` and kept only in memory; mutation calls send the CSRF header and idempotency key. A stale CSRF token is refreshed at most once when the Runner returns `CSRF_REQUIRED`. No session or CSRF credential is put into localStorage or sessionStorage.

The browser warns after 27 minutes without interaction and requires explicit continuation; local sign-out occurs at 30 minutes. The API separately enforces a 30-minute authenticated-request idle timeout. Cross-tab activity/logout/login events are synchronized with BroadcastChannel; only event types are broadcast, never credentials. Query cache and CSRF memory are cleared on sign-out and 401.

The frontend permission matrix is OWNER (view/execute/admin/owner), ADMIN (view/execute/admin), OPERATOR (view/execute), VIEWER (view). Route visibility and action controls mirror the server matrix. Flask API guards remain authoritative for every route, including baseline promotion, waivers, run execution, firmware flash and rollback. High-impact actions require a confirmation dialog; confirmations are UX safeguards, not substitutes for server authorization.

The current Run query/persistence contract still has no project identifier. Therefore, the backend now treats empty and named project scopes fail-closed on unscoped Run APIs. The default local OWNER's explicit `["*"]` scope remains supported. Named-project query filtering must be implemented before assigning project-scoped accounts to operational workloads.


### Scope and deployment limitations

This local Runner uses Flask's signed session cookie with HttpOnly, SameSite and HTTPS-aware Secure configuration. It does not currently use a shared server-side session/revocation store or a distributed login-rate-limit store. Cookie signing-secret rotation invalidates existing local sessions. A hosted multi-worker deployment must add shared server-side session persistence/revocation and distributed rate limiting. MFA and OIDC/SAML are not currently implemented; do not represent them as active controls.

The Run model has no project ID, so the API and legacy Flask interface both fail closed for named/empty project scopes. The default locally provisioned OWNER is explicitly wildcard-scoped. Project-scoped users must not be provisioned until project-aware filtering and resource-level authorization are available.


See the Dashboard Startup, Port Mapping and Verification Audit in DASHBOARD_VERIFICATION_AUDIT.md for the canonical Node engine range, service map, runtime log location and startup smoke-test contract.
