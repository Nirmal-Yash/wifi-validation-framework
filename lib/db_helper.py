"""Backward-compatible legacy database API over canonical repositories.

No function in this module creates or writes the historical test_runs/baselines
tables. Historical imports are explicit through scripts/netregress_migrate_legacy.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from lib.domain import (
    Attempt, Baseline, BusinessOutcome, Criticality, EnvironmentHealthStatus,
    EvidenceState, LifecycleEvent, Metric, Run, RunLifecycle, Severity, TestResult,
)
from lib.repositories import (
    SQLiteBaselineRepository, SQLiteDatabase, SQLiteRunRepository,
    SQLiteTestResultRepository, resolve_database_path,
)
from lib.services.legacy_migration import (
    LEGACY_PROVENANCE, LEGACY_VERSION, LegacyCompatibilityService,
)
from lib.services.run_service import generate_ulid


ROOT = Path(__file__).resolve().parent.parent
# Kept as a patchable compatibility attribute for older scripts.
DB_PATH = resolve_database_path(project_root=ROOT)


def _database() -> SQLiteDatabase:
    return SQLiteDatabase(DB_PATH)


def init_db() -> None:
    """Initialize only the canonical Runner schema; never create legacy tables."""
    _database().initialize()


def insert_result(
    test_name,
    status,
    firmware_version="v1.0",
    duration_ms=None,
    error_message=None,
    pcap_path=None,
    metric_value=None,
    metric_unit=None,
):
    """Compatibility writer that creates an untrusted LEGACY_IMPORTED Run."""
    return LegacyCompatibilityService(_database()).insert_result(
        test_name=test_name,
        status=status,
        firmware_version=firmware_version,
        duration_ms=duration_ms,
        error_message=error_message,
        pcap_path=pcap_path,
        metric_value=metric_value,
        metric_unit=metric_unit,
    )


def _result_query(*, run_ids=None, include_baseline_snapshots=False, initialize=True):
    database = _database()
    if initialize:
        database.initialize()
    exclusions = () if include_baseline_snapshots else (
        "LEGACY_BASELINE_SNAPSHOT", "LEGACY_IMPORTED_BASELINE",
    )
    sql = """
        SELECT
            tr.rowid AS id,
            tr.test_result_id,
            tr.run_id,
            COALESCE(NULLIF(tr.node_id, ''), tr.test_id) AS test_name,
            tr.status,
            r.firmware_version,
            CASE
                WHEN tr.started_at IS NOT NULL AND tr.completed_at IS NOT NULL
                THEN CAST(ROUND((julianday(tr.completed_at) - julianday(tr.started_at)) * 86400000) AS INTEGER)
                ELSE NULL
            END AS duration_ms,
            COALESCE(tr.error_reason, tr.failure_reason) AS error_message,
            (
                SELECT a.path FROM artifacts a
                WHERE a.test_result_id = tr.test_result_id AND a.artifact_type = 'PCAP'
                ORDER BY a.created_at, a.artifact_id LIMIT 1
            ) AS pcap_path,
            (
                SELECT s.value FROM metrics m JOIN samples s ON s.metric_id = m.metric_id
                WHERE m.test_result_id = tr.test_result_id
                ORDER BY m.authoritative DESC, m.metric_id, s.sequence LIMIT 1
            ) AS metric_value,
            (
                SELECT m.unit FROM metrics m JOIN samples s ON s.metric_id = m.metric_id
                WHERE m.test_result_id = tr.test_result_id
                ORDER BY m.authoritative DESC, m.metric_id, s.sequence LIMIT 1
            ) AS metric_unit,
            COALESCE(tr.completed_at, r.completed_at, r.created_at) AS timestamp,
            tr.started_at,
            tr.completed_at,
            tr.provenance,
            tr.execution_metadata_json,
            r.provenance AS run_provenance,
            r.validation_profile
        FROM test_results tr
        JOIN runs r ON r.run_id = tr.run_id
    """
    clauses = []
    params = []
    if exclusions:
        clauses.append("r.validation_profile NOT IN (?, ?)")
        params.extend(exclusions)
    if run_ids is not None:
        run_ids = tuple(run_ids)
        if not run_ids:
            return []
        clauses.append("tr.run_id IN (" + ",".join("?" for _ in run_ids) + ")")
        params.extend(run_ids)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY timestamp DESC, tr.rowid DESC"
    with database.connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    output = []
    for stored in rows:
        row = dict(stored)
        try:
            legacy = json.loads(row.get("execution_metadata_json") or "{}").get("legacy", {})
        except (TypeError, ValueError):
            legacy = {}
        row["pcap_path"] = row.get("pcap_path") or legacy.get("pcap_path") or legacy.get("pcap_path_unverified")
        output.append(row)
    return output


def save_baseline_from_latest_passes(firmware_version="v1.0"):
    """Store a historical comparison snapshot as LEGACY_IMPORTED, never as active.

    This preserves the old helper's observable behavior for local comparison,
    while canonical release baselines still require RunService promotion.
    """
    database = _database()
    database.initialize()
    rows = [
        row for row in _result_query()
        if row["firmware_version"] == firmware_version
    ]
    latest = {}
    for row in rows:
        latest.setdefault(row["test_name"], row)
    selected = list(latest.values())
    if not selected:
        return 0

    source_repository = SQLiteTestResultRepository(database)
    source_results = [source_repository.get(row["test_result_id"]) for row in selected]
    now = datetime.now(timezone.utc)
    run_id = f"LEGACY-BASELINE-SNAPSHOT-{generate_ulid(now)}"
    attempt_id = f"{run_id}-ATTEMPT-1"
    test_names = tuple(row["test_name"] for row in selected)
    run = Run(
        run_id=run_id,
        display_id=run_id,
        firmware_version=str(firmware_version),
        lab_id="LEGACY_UNKNOWN",
        validation_profile="LEGACY_BASELINE_SNAPSHOT",
        selected_tests=test_names,
        test_definition_versions={name: LEGACY_VERSION for name in test_names},
        resolved_config={},
        configuration_hash=hashlib.sha256(
            f"legacy-baseline:{firmware_version}:{run_id}".encode("utf-8")
        ).hexdigest(),
        repository_commit="LEGACY_UNKNOWN",
        lifecycle=RunLifecycle.COMPLETED,
        outcome=BusinessOutcome.UNVALIDATED,
        environment_health=EnvironmentHealthStatus.UNKNOWN,
        created_at=now,
        started_at=now,
        completed_at=now,
        provenance=LEGACY_PROVENANCE,
    )
    attempt = Attempt(
        attempt_id=attempt_id,
        run_id=run_id,
        number=1,
        started_at=now,
        completed_at=now,
    )
    events = (
        LifecycleEvent(
            event_id=generate_ulid(now),
            run_id=run_id,
            event_type="RUN_CREATED",
            occurred_at=now,
            details={"provenance": LEGACY_PROVENANCE},
        ),
        LifecycleEvent(
            event_id=generate_ulid(now),
            run_id=run_id,
            attempt_id=attempt_id,
            event_type="ATTEMPT_CREATED",
            occurred_at=now,
            details={"provenance": LEGACY_PROVENANCE},
        ),
    )

    copied_results = []
    for index, source in enumerate(source_results, start=1):
        if source is None:
            continue
        metrics = tuple(
            Metric(
                name=metric.name,
                unit=metric.unit,
                samples=metric.samples,
                authoritative=False,
            )
            for metric in source.metrics
        )
        copied_results.append(
            TestResult(
                test_result_id=f"{run_id}-RESULT-{index}",
                run_id=run_id,
                attempt_id=attempt_id,
                test_id=source.test_id,
                node_id=source.node_id,
                test_version=LEGACY_VERSION,
                status=source.status,
                criticality=Criticality.INFORMATIONAL,
                severity=Severity.LOW,
                evidence_state=EvidenceState.INCOMPLETE,
                metrics=metrics,
                error_reason="legacy comparison snapshot; not eligible for release baseline decisions",
                started_at=source.started_at,
                completed_at=source.completed_at,
                provenance=LEGACY_PROVENANCE,
                execution_metadata={
                    "legacy_baseline_source_result_id": source.test_result_id,
                    "source_run_id": source.run_id,
                },
            )
        )
    if not copied_results:
        return 0

    baseline = Baseline(
        baseline_id=generate_ulid(now),
        name=f"legacy-imported/{firmware_version}/{run_id}",
        baseline_run_id=run_id,
        status="IMPORTED",
        promoted_by="LEGACY_COMPATIBILITY",
        promoted_at=now,
        firmware_major_scope=str(firmware_version),
        provenance=LEGACY_PROVENANCE,
    )
    with database.transaction(immediate=True) as connection:
        SQLiteRunRepository.save_initial_bundle_in_transaction(
            connection, run, attempt, events
        )
        for result in copied_results:
            SQLiteTestResultRepository.save_in_transaction(connection, result)
        SQLiteBaselineRepository.save_in_transaction(connection, baseline)
    return len(copied_results)


def save_baseline(firmware_version="v1.0"):
    return save_baseline_from_latest_passes(firmware_version)


def _baseline_rows(firmware_version):
    database = _database()
    database.initialize()
    with database.connection() as connection:
        baselines = connection.execute(
            """
            SELECT DISTINCT b.baseline_run_id, b.baseline_id, b.status,
                            b.provenance, b.promoted_at
            FROM run_baselines b
            JOIN runs r ON r.run_id = b.baseline_run_id
            WHERE r.firmware_version = ?
              AND b.superseded_by IS NULL
              AND (
                  (b.status = 'ACTIVE' AND b.provenance = 'NATIVE')
                  OR (b.status = 'IMPORTED' AND b.provenance = 'LEGACY_IMPORTED')
              )
            ORDER BY CASE WHEN b.status = 'ACTIVE' AND b.provenance = 'NATIVE' THEN 0 ELSE 1 END,
                     b.promoted_at DESC
            """,
            (firmware_version,),
        ).fetchall()
    output = []
    for baseline in baselines:
        rows = _result_query(
            run_ids=[baseline["baseline_run_id"]],
            include_baseline_snapshots=True,
            initialize=False,
        )
        for row in rows:
            row["baseline_id"] = baseline["baseline_id"]
            row["baseline_status"] = baseline["status"]
            row["baseline_provenance"] = baseline["provenance"]
            row["baseline_promoted_at"] = baseline["promoted_at"]
            row["snapshot_time"] = baseline["promoted_at"]
            row["baseline_status"] = baseline["status"]
            output.append(row)
    output.sort(key=lambda row: str(row.get("baseline_promoted_at") or ""), reverse=True)
    output.sort(key=lambda row: 0 if row.get("baseline_status") == "ACTIVE" and row.get("baseline_provenance") == "NATIVE" else 1)
    latest = {}
    for row in output:
        latest.setdefault(row["test_name"], row)
    return sorted(latest.values(), key=lambda row: row["test_name"])


def get_baseline(firmware_version="v1.0"):
    """Return native active baselines and imported history for legacy readers.

    Imported entries are display/comparison history only; they are never listed
    as active by SQLiteBaselineRepository.list_active().
    """
    return _baseline_rows(firmware_version)


def get_latest_results(firmware_version=None):
    rows = _result_query()
    if firmware_version is not None:
        rows = [row for row in rows if row["firmware_version"] == firmware_version]
    latest = {}
    for row in rows:
        latest.setdefault(row["test_name"], row)
    return sorted(latest.values(), key=lambda row: row["test_name"])


def get_metric_history(test_name):
    rows = [
        row for row in _result_query()
        if row["test_name"] == test_name and row["metric_value"] is not None
    ]
    rows.sort(key=lambda row: str(row.get("timestamp") or ""))
    return rows


def get_pass_rate_by_firmware():
    totals = {}
    for row in _result_query():
        version = row["firmware_version"]
        item = totals.setdefault(
            version, {"firmware_version": version, "total": 0, "passed": 0}
        )
        item["total"] += 1
        if row["status"] == "PASS":
            item["passed"] += 1
    return [totals[key] for key in sorted(totals)]


def get_all_results(limit=500):
    rows = _result_query()
    try:
        limit = max(0, int(limit))
    except (TypeError, ValueError):
        raise ValueError("limit must be a non-negative integer")
    return rows[:limit]
