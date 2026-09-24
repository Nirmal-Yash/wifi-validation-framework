# NetRegress — Frontend Architecture and Dashboard Design

## 1. Frontend strategy

Do not rewrite the current Flask/Jinja dashboard yet.

Flask/Jinja plus plain JavaScript remains the presentation layer through Phase 8 because the Run, evidence, regression and telemetry contracts are still being stabilized.

The eventual migration target is React + Vite only after:

1. the versioned API is stable;
2. authentication and RBAC exist;
3. Cloud/Project semantics are implemented.

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

## 16. Future React component model

Potential components:

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

## 17. Migration to React + Vite

When API and Cloud auth are stable:

1. preserve URL semantics;
2. reuse API contracts;
3. reproduce current workflows;
4. migrate page-by-page;
5. run old and new frontends against the same API during transition;
6. retire Jinja only after feature parity and security validation.

## 18. Frontend invariants

1. UI is a view of persisted evidence.
2. UI never invents missing results.
3. UI never converts UNVALIDATED into PASS.
4. UI never exposes unauthorized artifacts.
5. UI never claims virtual WiFi is physical RF certification.
6. UI must always make the distinction between lifecycle status and business outcome visible.

## 19. Iteration 16 implementation status

Phase 8 is now API-backed rather than documentation-only. Jinja pages consume the same /api/v1 contracts intended for a future React client. The dashboard remains read-only until an authentication/RBAC boundary is implemented for state-changing actions.

Telemetry and regression pages preserve environment/evidence semantics rather than presenting inferred values as facts.


## 8. React/Vite implementation
The Runner now includes a React + Vite operational shell consuming /api/v1 for authenticated Run launch/list/detail, cancellation, retry, lifecycle/test inspection, health and artifact inspection. API authorization remains authoritative; UI visibility is not a security control.

## 20. Iterations 26–27 security and certification UX
The operational API remains the authority for mutation authorization, CSRF, idempotency and artifact boundaries. Browser state changes now require a session-bound CSRF token. The UI may surface the certification matrix and release/readiness status, but it must never infer certification from the presence of a generated matrix alone.

Certification scenario records must distinguish execution class, especially REAL_LAB, from hardware-free and simulated evidence. The frontend must preserve lifecycle/failure classification and must not convert LAB_FAILED, UNVALIDATED or Runner failures into product PASS states.
