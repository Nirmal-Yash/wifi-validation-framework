# NetForge Execution Platform

## Purpose

The execution platform makes every validation run a persistent, queryable object. A run records the firmware version, environment, suite, active topology version, topology content hash, command, lifecycle phase, aggregate results, child test results, events, and later metrics/regressions.

## Lifecycle

The database keeps the original stable execution status contract:

`QUEUED -> RUNNING -> PASSED | FAILED | ERROR | CANCELLED`

A separate `phase` field provides operational detail:

`QUEUED -> PROVISIONING -> RUNNING -> COLLECTING -> ANALYZING -> terminal`

This preserves compatibility with the existing SQLite schema while exposing useful execution progress.

## API

### List executions

`GET /api/executions?limit=50&status=FAILED`

### Create execution

`POST /api/executions`

Example:

```json
{
  "firmware_version": "1.3.0",
  "suite_name": "tier1-live",
  "environment": "tier1",
  "triggered_by": "dashboard",
  "notes": "candidate firmware",
  "pytest_args": ["tests/", "-m", "live", "-v"]
}
```

The API returns `202 Accepted` with an execution ID. The orchestrator owns the Pytest subprocess; the Flask process does not execute individual tests inline.

### Execution detail

`GET /api/executions/{id}`

The response includes aggregate execution data, normalized test results, metrics, and lifecycle events.

### Cancel

`POST /api/executions/{id}/cancel`

Cancellation is cooperative at the execution boundary and terminates the managed Pytest subprocess when it is running.

### Analyze

`POST /api/executions/{id}/analyze`

Optional body:

```json
{"threshold_percent": 10}
```

The regression engine intentionally suppresses alerts until at least five historical samples exist for the metric.

### Regressions

`GET /api/regressions`

or:

`GET /api/regressions?execution_id=123`

## Reproducibility

At execution creation time NetForge snapshots the current `config/devices.yaml` content and records its SHA-256 hash. If an active `TopologyVersion` exists, its database ID is also attached to the execution.

This prevents later topology edits from silently changing the evidence associated with an execution.

## Worker model

The current implementation intentionally uses one local daemon thread and one managed Pytest subprocess. It is deliberately simpler than Celery/Redis and is appropriate for the current single-host Tier-1 target. The API boundary is stable enough to replace the worker implementation later.

## JUnit normalization

The worker invokes Pytest with `--junitxml` and normalizes testcase results into `test_results`. The existing live-test `test_logs` table remains intact for backward compatibility.

## Regression model

`execution_metrics` stores numeric measurements as rows rather than JSON blobs. The baseline engine calculates a rolling mean and standard deviation from recent successful executions. A minimum sample count of five prevents noisy first-run alerts.

## Important limitation

The current live test suite does not yet emit every performance measurement as structured `execution_metrics`. The execution model and API are ready for those metrics; individual tests should be migrated incrementally to record explicit metrics such as throughput, authentication latency, DHCP lease time, packet loss, and roaming handoff time.
