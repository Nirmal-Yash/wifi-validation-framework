# NetRegress — Data Model and Versioned API

## 1. Data model objective

The persistence model changes from latest-row semantics to explicit Run-scoped evidence.

Core relationship:

~~~text
Organization
  └─ Project
      ├─ Lab
      ├─ Device
      ├─ Firmware
      ├─ Baseline
      └─ Run
          └─ Attempt
              └─ TestResult
                  ├─ Metric
                  │   └─ Sample
                  └─ Artifact
~~~

## 2. Run

Required fields:

| Field | Meaning |
|---|---|
| run_id | ULID primary identity |
| display_id | human readable Run ID |
| project_id | owning Project when Cloud exists |
| lab_id | selected lab |
| device_id | selected target |
| firmware_version | human label |
| firmware_artifact_id | exact firmware reference when available |
| profile | validation profile |
| lifecycle_status | mechanical Run state |\n| environment_health | latest observed lab health rollup |
| business_outcome | validation decision |
| evidence_state | completeness of evidence |
| started_at | UTC start |
| completed_at | UTC completion |
| config_hash | effective configuration identity |
| environment_hash | environment identity |
| repository_commit | code version |
| created_at | Run creation time |

## 3. Attempt

Attempt separates explicit reruns from one logical Run.

Fields:

- attempt_id;
- run_id;
- sequence_number;
- lifecycle status;
- start/end times;
- failure reason;
- worker/runner identity;
- environment snapshot reference.

## 4. TestResult

Fields:

- test_result_id;
- attempt_id;
- semantic test_id;
- pytest node ID;
- test version;
- status;
- criticality;
- severity;
- classification set;
- error code/message;
- started_at;
- completed_at;
- evidence state;
- reproduction command/reference.

## 5. Metric

One TestResult may contain multiple metrics.

Fields:

- metric_id;
- test_result_id;
- metric name;
- unit;
- aggregation policy;
- decision value;
- baseline value;
- delta percentage;
- regression classification.
- measurement policy and authoritative decision aggregate.
- derived decision value from the configured aggregate.

## 6. Sample

Raw measurement history is preserved.

Fields:

- sample_id;
- metric_id;
- sequence;
- sample status;
- raw value;
- unit;
- started_at;
- completed_at;
- warmup flag;
- retry count;
- raw command reference;
- diagnostic metadata.

Valid statistical samples are distinguished from RETRIED or failed measurements.

## 6A. Statistical measurement policy

`MeasurementPolicy` is immutable run/test-definition metadata containing the authoritative statistic, minimum eligible sample count, allowed sample statuses and retry inclusion rule.

`StatisticSummary` is derived from raw samples and includes count, minimum, maximum, mean, median, p90, p95 and population standard deviation. Warm-up samples are excluded from the eligible population, outliers are retained, and retry metadata never multiplies the sample count.

Historical raw samples remain authoritative. Aggregate values are derived from the frozen test-definition/policy version rather than silently replacing the original sample history.

## 7. Artifact

Fields:

- artifact_id;
- run_id;
- optional test_result_id;
- type;
- storage key/path;
- display name;
- size bytes;
- SHA-256;
- created_at;
- evidence state;
- sensitivity class;
- retain_until;
- soft_deleted_at.

Artifact types:

- PCAP;
- PYTEST_REPORT;
- DIFF_REPORT;
- SETUP_LOG;
- AUDIT_LOG;
- COMMAND_OUTPUT;
- CONFIG_SNAPSHOT;
- LAB_HEALTH_SNAPSHOT;
- ENV_FINGERPRINT;
- DIAGNOSTIC_BUNDLE;
- FIRMWARE_REFERENCE.

## 8. LabHealth

Each health snapshot contains component observations.

Component fields:

- component;
- status (`HEALTHY/DEGRADED/FAILED/UNKNOWN`);
- required flag;
- duration;
- diagnostic summary;
- details;
- evidence artifact;
- observed_at;
- tool/version metadata.

A Run records the worst observed health rollup across its BEFORE and AFTER snapshots. Health snapshots themselves remain immutable Run-scoped artifacts.

## 9. EnvironmentSnapshot

Frozen per Run.

Includes OS, kernel, Python, pytest, repository commit, GNS3, Docker, hostapd, wpa_supplicant, FRR, hwsim state, package versions and configuration hash.

## 10. ConfigSnapshot

Stores the fully resolved configuration rather than only the original YAML file.

Include:

- WiFi parameters;
- network addresses;
- thresholds;
- selected profile;
- selected tests;
- device mapping;
- capture configuration;
- statistics policy;
- release policy version where relevant.

## 11. Baseline

Fields:

- baseline_id;
- project scope;
- name;
- baseline_run_id;
- device/device-family scope;
- firmware major scope;
- test suite version;
- lab class/environment scope;
- status;
- promoted_by;
- promoted_at;
- superseded_by.

Promoted records are immutable.

## 12. Regression

Regression comparison is attached to a baseline/current pair.

Fields:

- regression_id;
- baseline_run_id;
- current_run_id;
- test_result ID;
- dimension;
- classification;
- baseline metric;
- current metric;
- delta;
- threshold used;
- comparability status;
- explanation.

## 13. Event

Important lifecycle transitions become persistent events.

Minimum events:

- RUN_CREATED;
- RUN_STARTED;
- LAB_HEALTH_STARTED;
- LAB_HEALTH_COMPLETED;
- TEST_STARTED;
- TEST_COMPLETED;
- ARTIFACT_CREATED;
- BASELINE_PROMOTED;
- RUN_COMPLETED;
- RUN_CANCELLED;
- WAIVER_CREATED;
- FIRMWARE_FLASH_STARTED;
- FIRMWARE_FLASH_COMPLETED.

## 14. SQL migration direction

Phase 1 stays SQLite but uses repository interfaces.

Historical database migration must preserve available facts and explicitly mark missing information.

Future Cloud/PostgreSQL implementation uses SQLAlchemy and Alembic.

## 15. Data integrity rules

1. all internal timestamps are UTC;
2. lifecycle and business outcome are separate fields;
3. metric values have explicit units;
4. Run ID is mandatory for new TestResults;
5. artifact SHA-256 is mandatory for registered binary evidence;
6. promoted baselines are immutable;
7. evidence state cannot silently change to complete;
8. deleted artifacts retain an audit trail;
9. legacy records are identifiable as imported;
10. comparison always records which baseline Run was used.

## 16. Versioned API

New endpoints use /api/v1.

### Runs

GET /api/v1/runs

Filter by project, lab, device, firmware, status, outcome, profile and date.

POST /api/v1/runs

Creates/queues a Run. Supports idempotency key.

GET /api/v1/runs/{run_id}

Returns lifecycle, outcome, progress, health, tests, counts and evidence summary.

POST /api/v1/runs/{run_id}/cancel

Authorized cancellation.

POST /api/v1/runs/{run_id}/retry

Creates an explicit new Attempt or Run according to policy.

### Test results

GET /api/v1/runs/{run_id}/tests

Returns TestResult collection with metrics, evidence state and classifications.

GET /api/v1/runs/{run_id}/tests/{test_result_id}

Returns complete test detail.

### Metrics

GET /api/v1/tests/{test_id}/metrics

Historical metric data across Runs, subject to Project authorization.

GET /api/v1/runs/{run_id}/metrics

Run-wide measurement summary.

### Regression

GET /api/v1/regressions

Supports baseline/current run filtering.

GET /api/v1/runs/{run_id}/regressions

Returns classifications for one Run.

### Artifacts

GET /api/v1/artifacts

Searchable artifact metadata.

GET /api/v1/artifacts/{artifact_id}

Metadata and controlled download response.

### Lab Health

GET /api/v1/labs/{lab_id}/health

Latest health snapshot.

GET /api/v1/runs/{run_id}/health

Run-associated environment health.

### Baselines

GET /api/v1/baselines

POST /api/v1/baselines

Promote an eligible Run to baseline.

GET /api/v1/baselines/{baseline_id}

Retrieve immutable baseline metadata.

## 17. API error contract

Every API error uses:

~~~json
{
  "error": {
    "code": "EXAMPLE_CODE",
    "message": "Human-readable explanation",
    "details": {}
  }
}
~~~

## 18. Pagination

Collection endpoints support limit, cursor/page, sort and filter fields.

Large artifact lists are never returned unbounded.

## 19. Idempotency

POST /api/v1/runs accepts an idempotency key.

Repeated CI delivery of the same request must not create duplicate Runs.

## 20. OpenAPI

Commit an OpenAPI specification after the first stable v1 implementation.

Pydantic models should generate or validate the API schema.

## 21. Legacy routes

Existing /api routes remain during the Flask/Jinja transition.

They become compatibility wrappers around the new v1 services rather than separate implementations.

## 22. API invariants

1. APIs never fabricate missing tests.
2. APIs never convert LAB_FAILED to product FAIL.
3. APIs never promote partial evidence into PASS.
4. APIs return persisted evidence-derived state.
5. authorization happens before artifact access.
6. API responses remain compatible within the v1 contract.
