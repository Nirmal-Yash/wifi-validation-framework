from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Mapping

from lib.domain import (
    Artifact,
    FailureClass,
    ReleaseWaiver,
    WaiverScope,
    ArtifactType,
    Attempt,
    Baseline,
    BusinessOutcome,
    EnvironmentHealthStatus,
    ConfigSnapshot,
    Criticality,
    EnvironmentSnapshot,
    EvidenceState,
    LifecycleEvent,
    Metric,
    Run,
    RunLifecycle,
    Sample,
    Severity,
    TestResult,
    TestResultStatus,
)
from .interfaces import RepositoryConflictError

SCHEMA_VERSION = "6"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS environment_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    host_os TEXT NOT NULL,
    kernel TEXT NOT NULL,
    python_version TEXT NOT NULL,
    repository_commit TEXT NOT NULL,
    configuration_hash TEXT NOT NULL,
    tools_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    resolved_config_json TEXT NOT NULL,
    configuration_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    display_id TEXT NOT NULL UNIQUE,
    firmware_version TEXT NOT NULL,
    lab_id TEXT NOT NULL,
    validation_profile TEXT NOT NULL,
    selected_tests_json TEXT NOT NULL,
    test_definition_versions_json TEXT NOT NULL,
    resolved_config_json TEXT NOT NULL,
    configuration_hash TEXT NOT NULL,
    repository_commit TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    outcome TEXT,
    environment_health TEXT,
    environment_snapshot_id TEXT REFERENCES environment_snapshots(snapshot_id),
    config_snapshot_id TEXT REFERENCES config_snapshots(snapshot_id),
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE',
    failure_class TEXT,
    failure_reason TEXT,
    execution_pid INTEGER
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(run_id, number)
);

CREATE TABLE IF NOT EXISTS test_results (
    test_result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id) ON DELETE CASCADE,
    test_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    test_version TEXT NOT NULL,
    status TEXT NOT NULL,
    criticality TEXT NOT NULL,
    severity TEXT NOT NULL,
    evidence_state TEXT NOT NULL,
    error_reason TEXT,
    started_at TEXT,
    completed_at TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE'
);

CREATE TABLE IF NOT EXISTS metrics (
    metric_id TEXT PRIMARY KEY,
    test_result_id TEXT NOT NULL REFERENCES test_results(test_result_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    authoritative INTEGER NOT NULL,
    UNIQUE(test_result_id, name)
);

CREATE TABLE IF NOT EXISTS samples (
    sample_id TEXT PRIMARY KEY,
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    value REAL NOT NULL,
    status TEXT NOT NULL,
    warmup INTEGER NOT NULL,
    retried INTEGER NOT NULL,
    captured_at TEXT,
    metadata_json TEXT NOT NULL,
    UNIQUE(metric_id, sequence)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    test_result_id TEXT REFERENCES test_results(test_result_id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    evidence_state TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    sensitivity_class TEXT NOT NULL DEFAULT 'INTERNAL',
    retain_until TEXT,
    soft_deleted_at TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE'
);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    attempt_id TEXT REFERENCES attempts(attempt_id),
    test_result_id TEXT REFERENCES test_results(test_result_id),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_baselines (
    baseline_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    baseline_run_id TEXT NOT NULL REFERENCES runs(run_id),
    status TEXT NOT NULL,
    device_scope TEXT NOT NULL,
    firmware_major_scope TEXT NOT NULL,
    test_suite_version TEXT NOT NULL,
    lab_class TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    promoted_at TEXT NOT NULL,
    superseded_by TEXT,
    provenance TEXT NOT NULL DEFAULT 'NATIVE'
);

CREATE TABLE IF NOT EXISTS legacy_migration_records (
    source_table TEXT NOT NULL,
    source_row_id INTEGER NOT NULL,
    target_run_id TEXT NOT NULL,
    target_result_id TEXT,
    imported_at TEXT NOT NULL,
    PRIMARY KEY(source_table, source_row_id)
);

CREATE INDEX IF NOT EXISTS idx_attempts_run ON attempts(run_id);
CREATE INDEX IF NOT EXISTS idx_results_attempt ON test_results(attempt_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_events_run ON lifecycle_events(run_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_active_baseline_name
    ON run_baselines(name) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS sync_queue (
    envelope_id TEXT PRIMARY KEY,
    runner_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    leased_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_queue_ready
    ON sync_queue(state, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_sync_queue_run
    ON sync_queue(run_id);

CREATE TABLE IF NOT EXISTS release_waivers (
    waiver_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    target_id TEXT NOT NULL,
    issue_code TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    audit_reference TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_waivers_target ON release_waivers(target_id, active, expires_at);
"""


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _json(value: Mapping) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class SQLiteDatabase:
    """SQLite connection factory and additive schema bootstrap."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _migrate_schema(connection: sqlite3.Connection) -> None:
        table_additions = {
            "runs": {
                "provenance": "TEXT NOT NULL DEFAULT 'NATIVE'",
                "environment_health": "TEXT",
                "failure_class": "TEXT",
                "failure_reason": "TEXT",
                "execution_pid": "INTEGER",
            },
            "test_results": {"provenance": "TEXT NOT NULL DEFAULT 'NATIVE'"},
            "artifacts": {
                "display_name": "TEXT NOT NULL DEFAULT ''",
                "created_at": "TEXT",
                "sensitivity_class": "TEXT NOT NULL DEFAULT 'INTERNAL'",
                "retain_until": "TEXT",
                "soft_deleted_at": "TEXT",
                "provenance": "TEXT NOT NULL DEFAULT 'NATIVE'",
            },
        }
        for table, additions in table_additions.items():
            columns = {
                row["name"]
                for row in connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"
                    )

        baseline_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(baselines)"
            ).fetchall()
        }
        if baseline_columns and "baseline_id" in baseline_columns:
            if "provenance" in baseline_columns:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO run_baselines(
                        baseline_id, name, baseline_run_id, status, device_scope,
                        firmware_major_scope, test_suite_version, lab_class,
                        promoted_by, promoted_at, superseded_by, provenance
                    )
                    SELECT baseline_id, name, baseline_run_id, status, device_scope,
                           firmware_major_scope, test_suite_version, lab_class,
                           promoted_by, promoted_at, superseded_by, provenance
                    FROM baselines
                    """
                )
            else:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO run_baselines(
                        baseline_id, name, baseline_run_id, status, device_scope,
                        firmware_major_scope, test_suite_version, lab_class,
                        promoted_by, promoted_at, superseded_by, provenance
                    )
                    SELECT baseline_id, name, baseline_run_id, status, device_scope,
                           firmware_major_scope, test_suite_version, lab_class,
                           promoted_by, promoted_at, superseded_by, 'NATIVE'
                    FROM baselines
                    """
                )
            archive_name = "legacy_baselines_archive"
            suffix = 2
            while connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (archive_name,),
            ).fetchone():
                archive_name = f"legacy_baselines_archive_{suffix}"
                suffix += 1
            connection.execute(
                f'ALTER TABLE baselines RENAME TO "{archive_name}"'
            )

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            self._migrate_schema(connection)
            connection.execute(
                """INSERT INTO schema_meta(key, value)
                   VALUES ('version', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (SCHEMA_VERSION,),
            )
            connection.commit()


class SQLiteRunRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, run: Run) -> None:
        with self.database.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone():
                raise RepositoryConflictError(f"run already exists: {run.run_id}")

            if run.environment:
                connection.execute(
                    """INSERT INTO environment_snapshots
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run.environment.snapshot_id,
                        run.environment.host_os,
                        run.environment.kernel,
                        run.environment.python_version,
                        run.environment.repository_commit,
                        run.environment.configuration_hash,
                        _json(run.environment.tools),
                    ),
                )

            if run.config_snapshot:
                connection.execute(
                    """INSERT INTO config_snapshots
                       VALUES (?, ?, ?)""",
                    (
                        run.config_snapshot.snapshot_id,
                        _json(run.config_snapshot.resolved_config),
                        run.config_snapshot.configuration_hash,
                    ),
                )

            connection.execute(
                """INSERT INTO runs (
                    run_id, display_id, firmware_version, lab_id,
                    validation_profile, selected_tests_json,
                    test_definition_versions_json, resolved_config_json,
                    configuration_hash, repository_commit, lifecycle, outcome,
                    environment_health, environment_snapshot_id, config_snapshot_id,
                    created_at, started_at, completed_at, provenance, failure_class, failure_reason, execution_pid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    run.display_id,
                    run.firmware_version,
                    run.lab_id,
                    run.validation_profile,
                    _json({"tests": list(run.selected_tests)}),
                    _json(run.test_definition_versions),
                    _json(run.resolved_config),
                    run.configuration_hash,
                    run.repository_commit,
                    run.lifecycle.value,
                    run.outcome.value if run.outcome else None,
                    run.environment_health.value if run.environment_health else None,
                    run.environment.snapshot_id if run.environment else None,
                    run.config_snapshot.snapshot_id if run.config_snapshot else None,
                    _dt(run.created_at),
                    _dt(run.started_at),
                    _dt(run.completed_at),
                    run.provenance,
                    run.failure_class.value if run.failure_class else None,
                    run.failure_reason,
                    run.execution_pid,
                ),
            )
            connection.commit()

    def update(self, run: Run) -> None:
        with self.database.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run.run_id,)
            ).fetchone():
                raise RepositoryConflictError(f"run does not exist: {run.run_id}")
            connection.execute(
                """UPDATE runs
                   SET lifecycle = ?, outcome = ?, environment_health = ?, started_at = ?, completed_at = ?, failure_class = ?, failure_reason = ?, execution_pid = ?
                   WHERE run_id = ?""",
                (
                    run.lifecycle.value,
                    run.outcome.value if run.outcome else None,
                    run.environment_health.value if run.environment_health else None,
                    _dt(run.started_at),
                    _dt(run.completed_at),
                    run.failure_class.value if run.failure_class else None,
                    run.failure_reason,
                    run.execution_pid,
                    run.run_id,
                ),
            )
            connection.commit()

    def get(self, run_id: str) -> Run | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                return None

            environment = None
            if row["environment_snapshot_id"]:
                snapshot = connection.execute(
                    "SELECT * FROM environment_snapshots WHERE snapshot_id = ?",
                    (row["environment_snapshot_id"],),
                ).fetchone()
                if snapshot:
                    environment = EnvironmentSnapshot(
                        snapshot_id=snapshot["snapshot_id"],
                        host_os=snapshot["host_os"],
                        kernel=snapshot["kernel"],
                        python_version=snapshot["python_version"],
                        repository_commit=snapshot["repository_commit"],
                        configuration_hash=snapshot["configuration_hash"],
                        tools=json.loads(snapshot["tools_json"]),
                    )

            config_snapshot = None
            if row["config_snapshot_id"]:
                snapshot = connection.execute(
                    "SELECT * FROM config_snapshots WHERE snapshot_id = ?",
                    (row["config_snapshot_id"],),
                ).fetchone()
                if snapshot:
                    config_snapshot = ConfigSnapshot(
                        snapshot_id=snapshot["snapshot_id"],
                        resolved_config=json.loads(snapshot["resolved_config_json"]),
                        configuration_hash=snapshot["configuration_hash"],
                    )

            return Run(
                run_id=row["run_id"],
                display_id=row["display_id"],
                firmware_version=row["firmware_version"],
                lab_id=row["lab_id"],
                validation_profile=row["validation_profile"],
                selected_tests=tuple(
                    json.loads(row["selected_tests_json"])["tests"]
                ),
                test_definition_versions=json.loads(
                    row["test_definition_versions_json"]
                ),
                resolved_config=json.loads(row["resolved_config_json"]),
                configuration_hash=row["configuration_hash"],
                repository_commit=row["repository_commit"],
                lifecycle=RunLifecycle(row["lifecycle"]),
                outcome=(
                    BusinessOutcome(row["outcome"]) if row["outcome"] else None
                ),
                environment_health=(
                    EnvironmentHealthStatus(row["environment_health"])
                    if row["environment_health"]
                    else None
                ),
                environment=environment,
                config_snapshot=config_snapshot,
                created_at=_parse_dt(row["created_at"]),
                started_at=_parse_dt(row["started_at"]),
                completed_at=_parse_dt(row["completed_at"]),
                provenance=row["provenance"] or "NATIVE",
                failure_class=(FailureClass(row["failure_class"]) if row["failure_class"] else None),
                failure_reason=row["failure_reason"],
                execution_pid=row["execution_pid"],
            )

    
    def list(self) -> list[Run]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs ORDER BY created_at DESC, run_id DESC"
            ).fetchall()
        return [run for row in rows if (run := self.get(row["run_id"])) is not None]


class SQLiteAttemptRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, attempt: Attempt) -> None:
        with self.database.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM attempts WHERE attempt_id = ?",
                (attempt.attempt_id,),
            ).fetchone():
                raise RepositoryConflictError(
                    f"attempt already exists: {attempt.attempt_id}"
                )
            connection.execute(
                """INSERT INTO attempts(
                       attempt_id, run_id, number, started_at, completed_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    attempt.attempt_id,
                    attempt.run_id,
                    attempt.number,
                    _dt(attempt.started_at),
                    _dt(attempt.completed_at),
                ),
            )
            connection.commit()

    def update(self, attempt: Attempt) -> None:
        with self.database.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM attempts WHERE attempt_id = ?", (attempt.attempt_id,)
            ).fetchone():
                raise RepositoryConflictError(
                    f"attempt does not exist: {attempt.attempt_id}"
                )
            connection.execute(
                """UPDATE attempts
                   SET started_at = ?, completed_at = ?
                   WHERE attempt_id = ?""",
                (
                    _dt(attempt.started_at),
                    _dt(attempt.completed_at),
                    attempt.attempt_id,
                ),
            )
            connection.commit()

    def get(self, attempt_id: str) -> Attempt | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        if not row:
            return None
        return Attempt(
            attempt_id=row["attempt_id"],
            run_id=row["run_id"],
            number=row["number"],
            started_at=_parse_dt(row["started_at"]),
            completed_at=_parse_dt(row["completed_at"]),
        )

    def list_for_run(self, run_id: str) -> list[Attempt]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM attempts WHERE run_id = ? ORDER BY number",
                (run_id,),
            ).fetchall()
        return [
            Attempt(
                attempt_id=row["attempt_id"],
                run_id=row["run_id"],
                number=row["number"],
                started_at=_parse_dt(row["started_at"]),
                completed_at=_parse_dt(row["completed_at"]),
            )
            for row in rows
        ]


class SQLiteTestResultRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, result: TestResult) -> None:
        with self.database.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM test_results WHERE test_result_id = ?",
                (result.test_result_id,),
            ).fetchone():
                raise RepositoryConflictError(
                    f"test result already exists: {result.test_result_id}"
                )

            connection.execute(
                """INSERT INTO test_results(
                    test_result_id, run_id, attempt_id, test_id, node_id,
                    test_version, status, criticality, severity, evidence_state,
                    error_reason, started_at, completed_at, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.test_result_id,
                    result.run_id,
                    result.attempt_id,
                    result.test_id,
                    result.node_id,
                    result.test_version,
                    result.status.value,
                    result.criticality.value,
                    result.severity.value,
                    result.evidence_state.value,
                    result.error_reason,
                    _dt(result.started_at),
                    _dt(result.completed_at),
                    result.provenance,
                ),
            )

            for metric in result.metrics:
                metric_id = f"{result.test_result_id}:{metric.name}"
                connection.execute(
                    """INSERT INTO metrics(
                           metric_id, test_result_id, name, unit, authoritative
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        metric_id,
                        result.test_result_id,
                        metric.name,
                        metric.unit,
                        int(metric.authoritative),
                    ),
                )
                for sequence, sample in enumerate(metric.samples, start=1):
                    connection.execute(
                        """INSERT INTO samples(
                            sample_id, metric_id, sequence, value, status,
                            warmup, retried, captured_at, metadata_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            f"{metric_id}:{sequence}",
                            metric_id,
                            sequence,
                            float(sample.value),
                            sample.status,
                            int(sample.warmup),
                            int(sample.retried),
                            _dt(sample.captured_at),
                            _json(sample.metadata),
                        ),
                    )

            for artifact in result.artifacts:
                self._insert_artifact(connection, artifact)

            connection.commit()

    def get(self, test_result_id: str) -> TestResult | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM test_results WHERE test_result_id = ?",
                (test_result_id,),
            ).fetchone()
            if not row:
                return None
            return self._to_domain(connection, row)

    def list_for_attempt(self, attempt_id: str) -> list[TestResult]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM test_results WHERE attempt_id = ? "
                "ORDER BY test_result_id",
                (attempt_id,),
            ).fetchall()
            return [self._to_domain(connection, row) for row in rows]
    
    def list_for_run(self, run_id: str) -> list[TestResult]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM test_results WHERE run_id = ? ORDER BY completed_at, test_result_id",
                (run_id,),
            ).fetchall()
            return [self._to_domain(connection, row) for row in rows]


    @staticmethod
    def _insert_artifact(
        connection: sqlite3.Connection, artifact: Artifact
    ) -> None:
        connection.execute(
            """INSERT INTO artifacts(
                artifact_id, run_id, test_result_id, artifact_type, path,
                sha256, size_bytes, evidence_state, display_name, created_at,
                sensitivity_class, retain_until, soft_deleted_at, provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact.artifact_id,
                artifact.run_id,
                artifact.test_result_id,
                artifact.artifact_type.value,
                artifact.path,
                artifact.sha256,
                artifact.size_bytes,
                artifact.evidence_state.value,
                artifact.display_name,
                _dt(artifact.created_at),
                artifact.sensitivity_class,
                _dt(artifact.retain_until),
                _dt(artifact.soft_deleted_at),
                artifact.provenance,
            ),
        )

    @classmethod
    def _to_domain(
        cls, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> TestResult:
        metrics: list[Metric] = []
        metric_rows = connection.execute(
            "SELECT * FROM metrics WHERE test_result_id = ? ORDER BY metric_id",
            (row["test_result_id"],),
        ).fetchall()

        for metric_row in metric_rows:
            samples = tuple(
                Sample(
                    value=sample_row["value"],
                    status=sample_row["status"],
                    warmup=bool(sample_row["warmup"]),
                    retried=bool(sample_row["retried"]),
                    captured_at=_parse_dt(sample_row["captured_at"]),
                    metadata=json.loads(sample_row["metadata_json"]),
                )
                for sample_row in connection.execute(
                    "SELECT * FROM samples WHERE metric_id = ? ORDER BY sequence",
                    (metric_row["metric_id"],),
                ).fetchall()
            )
            metrics.append(
                Metric(
                    name=metric_row["name"],
                    unit=metric_row["unit"],
                    samples=samples,
                    authoritative=bool(metric_row["authoritative"]),
                )
            )

        artifacts = tuple(
            Artifact(
                artifact_id=artifact_row["artifact_id"],
                run_id=artifact_row["run_id"],
                artifact_type=ArtifactType(artifact_row["artifact_type"]),
                path=artifact_row["path"],
                sha256=artifact_row["sha256"],
                size_bytes=artifact_row["size_bytes"],
                evidence_state=EvidenceState(artifact_row["evidence_state"]),
                test_result_id=artifact_row["test_result_id"],
                display_name=artifact_row["display_name"] or artifact_row["path"].rsplit("/", 1)[-1],
                created_at=_parse_dt(artifact_row["created_at"]),
                sensitivity_class=artifact_row["sensitivity_class"] or "INTERNAL",
                retain_until=_parse_dt(artifact_row["retain_until"]),
                soft_deleted_at=_parse_dt(artifact_row["soft_deleted_at"]),
            )
            for artifact_row in connection.execute(
                "SELECT * FROM artifacts WHERE test_result_id = ? "
                "ORDER BY artifact_id",
                (row["test_result_id"],),
            ).fetchall()
        )

        return TestResult(
            test_result_id=row["test_result_id"],
            run_id=row["run_id"],
            attempt_id=row["attempt_id"],
            test_id=row["test_id"],
            node_id=row["node_id"],
            test_version=row["test_version"],
            status=TestResultStatus(row["status"]),
            criticality=Criticality(row["criticality"]),
            severity=Severity(row["severity"]),
            evidence_state=EvidenceState(row["evidence_state"]),
            metrics=tuple(metrics),
            artifacts=artifacts,
            error_reason=row["error_reason"],
            started_at=_parse_dt(row["started_at"]),
            completed_at=_parse_dt(row["completed_at"]),
        )


class SQLiteArtifactRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, artifact: Artifact) -> None:
        with self.database.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM artifacts WHERE artifact_id = ?",
                (artifact.artifact_id,),
            ).fetchone():
                raise RepositoryConflictError(
                    f"artifact already exists: {artifact.artifact_id}"
                )
            SQLiteTestResultRepository._insert_artifact(connection, artifact)
            connection.commit()

    def get(self, artifact_id: str) -> Artifact | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        return self._to_domain(row)

    def list_for_run(self, run_id: str) -> list[Artifact]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY artifact_id",
                (run_id,),
            ).fetchall()
        return [self._to_domain(row) for row in rows]
    
    def list_all(self) -> list[Artifact]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts ORDER BY created_at DESC, artifact_id DESC"
            ).fetchall()
            return [self._to_domain(row) for row in rows]


    @staticmethod
    def _to_domain(row: sqlite3.Row | None) -> Artifact | None:
        if not row:
            return None
        return Artifact(
            artifact_id=row["artifact_id"],
            run_id=row["run_id"],
            artifact_type=ArtifactType(row["artifact_type"]),
            path=row["path"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            evidence_state=EvidenceState(row["evidence_state"]),
            test_result_id=row["test_result_id"],
            display_name=row["display_name"] or row["path"].rsplit("/", 1)[-1],
            created_at=_parse_dt(row["created_at"]),
            sensitivity_class=row["sensitivity_class"] or "INTERNAL",
            retain_until=_parse_dt(row["retain_until"]),
            soft_deleted_at=_parse_dt(row["soft_deleted_at"]),
            provenance=row["provenance"] or "NATIVE",
        )


class SQLiteEventRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def append(self, event: LifecycleEvent) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO lifecycle_events(
                    event_id, run_id, attempt_id, test_result_id, event_type,
                    occurred_at, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.run_id,
                    event.attempt_id,
                    event.test_result_id,
                    event.event_type,
                    _dt(event.occurred_at),
                    _json(event.details),
                ),
            )
            connection.commit()

    def list_for_run(self, run_id: str) -> list[LifecycleEvent]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM lifecycle_events WHERE run_id = ? "
                "ORDER BY occurred_at, event_id",
                (run_id,),
            ).fetchall()
        return [
            LifecycleEvent(
                event_id=row["event_id"],
                run_id=row["run_id"],
                event_type=row["event_type"],
                occurred_at=_parse_dt(row["occurred_at"]),
                attempt_id=row["attempt_id"],
                test_result_id=row["test_result_id"],
                details=json.loads(row["details_json"]),
            )
            for row in rows
        ]


class SQLiteSyncQueueRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def enqueue(self, envelope):
        now = datetime.now().astimezone()
        with self.database.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM sync_queue WHERE idempotency_key = ?",
                (envelope.idempotency_key,),
            ).fetchone()
            if existing:
                return self._to_domain(existing)
            connection.execute(
                """INSERT INTO sync_queue(
                    envelope_id, runner_id, run_id, kind, schema_version,
                    idempotency_key, payload_json, payload_sha256, state,
                    attempt_count, next_attempt_at, leased_at, last_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL, ?, ?)""",
                (
                    envelope.envelope_id, envelope.runner_id, envelope.run_id,
                    envelope.kind, envelope.schema_version, envelope.idempotency_key,
                    envelope.payload_json, envelope.payload_sha256, "QUEUED",
                    _dt(now), _dt(now), _dt(now),
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM sync_queue WHERE envelope_id = ?",
                (envelope.envelope_id,),
            ).fetchone()
        return self._to_domain(row)

    def get(self, envelope_id):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sync_queue WHERE envelope_id = ?", (envelope_id,)
            ).fetchone()
        return self._to_domain(row) if row else None

    def list_ready(self, now, limit=20):
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM sync_queue
                   WHERE state IN ('QUEUED','FAILED')
                     AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   ORDER BY created_at, envelope_id
                   LIMIT ?""",
                (_dt(now), limit),
            ).fetchall()
        return [self._to_domain(row) for row in rows]

    def claim(self, envelope_id, leased_at, lease_until):
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sync_queue WHERE envelope_id = ?", (envelope_id,)
            ).fetchone()
            if not row or row["state"] not in {"QUEUED", "FAILED"}:
                return None
            connection.execute(
                """UPDATE sync_queue
                   SET state = 'IN_FLIGHT', leased_at = ?, updated_at = ?
                   WHERE envelope_id = ?""",
                (_dt(lease_until), _dt(lease_until), envelope_id),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM sync_queue WHERE envelope_id = ?", (envelope_id,)
            ).fetchone()
        return self._to_domain(updated)

    def ack(self, envelope_id, updated_at):
        with self.database.connection() as connection:
            connection.execute(
                """UPDATE sync_queue
                   SET state = 'ACKED', leased_at = NULL, next_attempt_at = NULL,
                       last_error = NULL, updated_at = ?
                   WHERE envelope_id = ?""",
                (_dt(updated_at), envelope_id),
            )
            connection.commit()

    def fail(self, envelope_id, *, next_attempt_at, error, updated_at, blocked=False):
        state = "BLOCKED" if blocked else "FAILED"
        with self.database.connection() as connection:
            connection.execute(
                """UPDATE sync_queue
                   SET state = ?, attempt_count = attempt_count + 1,
                       next_attempt_at = ?, leased_at = NULL, last_error = ?,
                       updated_at = ?
                   WHERE envelope_id = ?""",
                (state, _dt(next_attempt_at), error[:2000], _dt(updated_at), envelope_id),
            )
            connection.commit()

    def recover_expired(self, now):
        with self.database.connection() as connection:
            cursor = connection.execute(
                """UPDATE sync_queue
                   SET state = 'FAILED', leased_at = NULL,
                       next_attempt_at = ?, last_error = COALESCE(last_error, 'lease expired'),
                       updated_at = ?
                   WHERE state = 'IN_FLIGHT' AND leased_at IS NOT NULL AND leased_at <= ?""",
                (_dt(now), _dt(now), _dt(now)),
            )
            connection.commit()
            return cursor.rowcount

    def list_for_run(self, run_id):
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sync_queue WHERE run_id = ? ORDER BY created_at, envelope_id",
                (run_id,),
            ).fetchall()
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row):
        from lib.domain import SyncEnvelope, SyncQueueItem, SyncState
        return SyncQueueItem(
            envelope=SyncEnvelope(
                envelope_id=row["envelope_id"],
                runner_id=row["runner_id"],
                run_id=row["run_id"],
                kind=row["kind"],
                schema_version=row["schema_version"],
                idempotency_key=row["idempotency_key"],
                payload_json=row["payload_json"],
                payload_sha256=row["payload_sha256"],
                created_at=_parse_dt(row["created_at"]),
            ),
            state=SyncState(row["state"]),
            attempt_count=row["attempt_count"],
            next_attempt_at=_parse_dt(row["next_attempt_at"]),
            leased_at=_parse_dt(row["leased_at"]),
            last_error=row["last_error"],
            updated_at=_parse_dt(row["updated_at"]),
        )


class SQLiteBaselineRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, baseline: Baseline) -> None:
        if baseline.superseded_by is not None:
            raise RepositoryConflictError(
                "a newly persisted baseline cannot already be superseded"
            )
        with self.database.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM run_baselines WHERE baseline_id = ?",
                (baseline.baseline_id,),
            ).fetchone():
                raise RepositoryConflictError(
                    f"baseline already exists: {baseline.baseline_id}"
                )
            connection.execute(
                """INSERT INTO run_baselines(
                    baseline_id, name, baseline_run_id, status, device_scope,
                    firmware_major_scope, test_suite_version, lab_class,
                    promoted_by, promoted_at, superseded_by, provenance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    baseline.baseline_id,
                    baseline.name,
                    baseline.baseline_run_id,
                    baseline.status,
                    baseline.device_scope,
                    baseline.firmware_major_scope,
                    baseline.test_suite_version,
                    baseline.lab_class,
                    baseline.promoted_by,
                    _dt(baseline.promoted_at),
                    baseline.provenance,
                ),
            )
            connection.commit()

    def get(self, baseline_id: str) -> Baseline | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM run_baselines WHERE baseline_id = ?", (baseline_id,)
            ).fetchone()
        return self._to_domain(row)

    def list_active(self) -> list[Baseline]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM run_baselines WHERE superseded_by IS NULL "
                "ORDER BY promoted_at DESC"
            ).fetchall()
        return [self._to_domain(row) for row in rows]

    def supersede(self, baseline_id: str, replacement_id: str) -> None:
        with self.database.connection() as connection:
            cursor = connection.execute(
                "UPDATE run_baselines SET superseded_by = ?, status = 'SUPERSEDED' "
                "WHERE baseline_id = ? AND superseded_by IS NULL",
                (replacement_id, baseline_id),
            )
            if cursor.rowcount != 1:
                raise RepositoryConflictError(f"baseline is not active: {baseline_id}")
            connection.commit()

    def list_all(self) -> list[Baseline]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM run_baselines ORDER BY promoted_at DESC"
            ).fetchall()
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: sqlite3.Row | None) -> Baseline | None:
        if not row:
            return None
        return Baseline(
            baseline_id=row["baseline_id"],
            name=row["name"],
            baseline_run_id=row["baseline_run_id"],
            status=row["status"],
            promoted_by=row["promoted_by"],
            promoted_at=_parse_dt(row["promoted_at"]),
            device_scope=row["device_scope"],
            firmware_major_scope=row["firmware_major_scope"],
            test_suite_version=row["test_suite_version"],
            lab_class=row["lab_class"],
            superseded_by=row["superseded_by"],
            provenance=row["provenance"] or "NATIVE",
        )

class SQLiteWaiverRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save(self, waiver) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO release_waivers(waiver_id,scope,target_id,issue_code,reason,created_by,created_at,expires_at,audit_reference,active) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    waiver.waiver_id,
                    waiver.scope.value,
                    waiver.target_id,
                    waiver.issue_code,
                    waiver.reason,
                    waiver.created_by,
                    _dt(waiver.created_at),
                    _dt(waiver.expires_at),
                    waiver.audit_reference,
                    1 if waiver.active else 0,
                ),
            )
            connection.commit()

    def list_active(self, target_id: str | None = None):
        query = "SELECT * FROM release_waivers WHERE active = 1"
        params = []
        if target_id is not None:
            query += " AND target_id = ?"
            params.append(target_id)
        query += " ORDER BY created_at DESC"
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            ReleaseWaiver(
                waiver_id=row["waiver_id"],
                scope=WaiverScope(row["scope"]),
                target_id=row["target_id"],
                issue_code=row["issue_code"],
                reason=row["reason"],
                created_by=row["created_by"],
                created_at=_parse_dt(row["created_at"]),
                expires_at=_parse_dt(row["expires_at"]),
                audit_reference=row["audit_reference"],
                active=bool(row["active"]),
            )
            for row in rows
        ]
