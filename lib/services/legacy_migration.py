from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.domain import (
    ArtifactType,
    Attempt,
    Baseline,
    BusinessOutcome,
    Criticality,
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
from lib.repositories import (
    SQLiteArtifactRepository,
    SQLiteAttemptRepository,
    SQLiteBaselineRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
)
from .artifact_service import ArtifactService


LEGACY_PROVENANCE = "LEGACY_IMPORTED"
LEGACY_PROFILE = "LEGACY_IMPORTED"
LEGACY_LAB = "LEGACY_UNKNOWN"
LEGACY_VERSION = "LEGACY_UNVERSIONED"


class LegacyDatabaseMigrationService:
    """Migrate legacy SQLite facts without inferring missing Run boundaries."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def migrate(self) -> dict[str, int]:
        self.database.initialize()
        summary = {
            "test_runs": 0,
            "baselines": 0,
            "artifacts": 0,
            "artifact_unavailable": 0,
        }
        with self.database.connection() as connection:
            test_runs = (
                connection.execute("SELECT * FROM test_runs ORDER BY id").fetchall()
                if self._table_exists(connection, "test_runs")
                else []
            )
            baselines = (
                connection.execute("SELECT * FROM baselines ORDER BY id").fetchall()
                if self._table_exists(connection, "baselines")
                else []
            )

        for row in test_runs:
            row_id = int(row["id"])
            if self._already_imported("test_runs", row_id):
                continue
            state = self._migrate_test_run(row)
            summary["test_runs"] += 1
            if state == "registered":
                summary["artifacts"] += 1
            elif state == "unavailable":
                summary["artifact_unavailable"] += 1

        for row in baselines:
            row_id = int(row["id"])
            if self._already_imported("baselines", row_id):
                continue
            self._migrate_baseline(row)
            summary["baselines"] += 1

        return summary

    @staticmethod
    def _table_exists(connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    @staticmethod
    def _value(row, name: str, default=None):
        return row[name] if name in row.keys() else default

    def _already_imported(self, source_table: str, row_id: int) -> bool:
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT 1 FROM legacy_migration_records WHERE source_table=? AND source_row_id=?",
                (source_table, row_id),
            ).fetchone() is not None

    def _mark(self, source_table: str, row_id: int, run_id: str, result_id: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO legacy_migration_records(
                   source_table, source_row_id, target_run_id, target_result_id, imported_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (
                    source_table,
                    row_id,
                    run_id,
                    result_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()

    def _migrate_test_run(self, row) -> str:
        row_id = int(row["id"])
        run_id = f"LEGACY-RUN-{row_id}"
        attempt_id = f"LEGACY-ATTEMPT-{row_id}"
        result_id = f"LEGACY-RESULT-{row_id}"
        timestamp = self._parse_timestamp(self._value(row, "timestamp"))
        duration_ms = self._value(row, "duration_ms")
        started = (
            timestamp - timedelta(milliseconds=int(duration_ms))
            if timestamp is not None and duration_ms is not None
            else None
        )
        test_name = str(row["test_name"])
        firmware = str(self._value(row, "firmware_version") or "UNKNOWN")
        raw_status = str(self._value(row, "status") or "UNVALIDATED").upper()
        status = self._status(raw_status)
        error_reason = self._value(row, "error_message")
        notes = ["legacy imported; evidence completeness was not recorded"]
        metric_value = self._value(row, "metric_value")
        metric_unit = self._value(row, "metric_unit")
        if metric_value is not None and not metric_unit:
            notes.append(f"legacy metric value preserved only as raw fact: {metric_value}")
        base_error = str(error_reason) if error_reason else ""
        error_reason = "; ".join(([base_error] if base_error else []) + notes)

        config_hash = hashlib.sha256(
            f"legacy:test_runs:{row_id}".encode("utf-8")
        ).hexdigest()
        run = Run(
            run_id=run_id,
            display_id=run_id,
            firmware_version=firmware,
            lab_id=LEGACY_LAB,
            validation_profile=LEGACY_PROFILE,
            selected_tests=(test_name,),
            test_definition_versions={test_name: LEGACY_VERSION},
            resolved_config={},
            configuration_hash=config_hash,
            repository_commit="LEGACY_UNKNOWN",
            lifecycle=RunLifecycle.COMPLETED,
            outcome=BusinessOutcome.UNVALIDATED,
            created_at=started or timestamp,
            started_at=started,
            completed_at=timestamp,
            provenance=LEGACY_PROVENANCE,
        )

        run_repo = SQLiteRunRepository(self.database)
        attempt_repo = SQLiteAttemptRepository(self.database)
        result_repo = SQLiteTestResultRepository(self.database)
        if run_repo.get(run_id) is None:
            run_repo.save(run)
        if attempt_repo.get(attempt_id) is None:
            attempt_repo.save(
                Attempt(
                    attempt_id=attempt_id,
                    run_id=run_id,
                    number=1,
                    started_at=started,
                    completed_at=timestamp,
                )
            )

        metrics: tuple[Metric, ...] = ()
        if metric_value is not None and metric_unit:
            metrics = (
                Metric(
                    name="legacy_metric",
                    unit=str(metric_unit),
                    samples=(
                        Sample(
                            value=float(metric_value),
                            captured_at=timestamp,
                            metadata={"source": "test_runs", "legacy_row_id": row_id},
                        ),
                    ),
                ),
            )
        result = TestResult(
            test_result_id=result_id,
            run_id=run_id,
            attempt_id=attempt_id,
            test_id=test_name,
            node_id=test_name,
            test_version=LEGACY_VERSION,
            status=status,
            criticality=Criticality.INFORMATIONAL,
            severity=Severity.LOW,
            evidence_state=EvidenceState.INCOMPLETE,
            metrics=metrics,
            error_reason=error_reason,
            started_at=started,
            completed_at=timestamp,
            provenance=LEGACY_PROVENANCE,
        )
        if result_repo.get(result_id) is None:
            result_repo.save(result)

        artifact_state = "none"
        pcap_path = self._value(row, "pcap_path")
        if pcap_path:
            path = Path(str(pcap_path))
            artifact_id = f"LEGACY-ARTIFACT-{row_id}"
            if path.is_file():
                artifact_repo = SQLiteArtifactRepository(self.database)
                if artifact_repo.get(artifact_id) is None:
                    artifact_service = ArtifactService(
                        artifact_repo,
                        run_repo,
                        SQLiteEventRepository(self.database),
                        id_generator=iter([artifact_id, f"LEGACY-ARTIFACT-EVENT-{row_id}"]).__next__,
                    )
                    artifact_service.register_file(
                        run_id=run_id,
                        path=path,
                        artifact_type=ArtifactType.PCAP,
                        test_result_id=result_id,
                        display_name=path.name,
                        provenance=LEGACY_PROVENANCE,
                    )
                artifact_state = "registered"
            else:
                self._record_event(
                    run_id,
                    attempt_id,
                    result_id,
                    "LEGACY_ARTIFACT_UNAVAILABLE",
                    timestamp,
                    {"path": str(pcap_path)},
                    f"LEGACY-EVENT-{row_id}",
                )
                artifact_state = "unavailable"

        self._mark("test_runs", row_id, run_id, result_id)
        return artifact_state

    def _migrate_baseline(self, row) -> None:
        row_id = int(row["id"])
        run_id = f"LEGACY-BASELINE-RUN-{row_id}"
        attempt_id = f"LEGACY-BASELINE-ATTEMPT-{row_id}"
        result_id = f"LEGACY-BASELINE-RESULT-{row_id}"
        baseline_id = f"LEGACY-BASELINE-{row_id}"
        timestamp = self._parse_timestamp(self._value(row, "snapshot_time"))
        test_name = str(row["test_name"])
        firmware = str(self._value(row, "firmware_version") or "UNKNOWN")
        status_raw = str(self._value(row, "status") or "UNVALIDATED").upper()
        status = self._status(status_raw)
        run = Run(
            run_id=run_id,
            display_id=run_id,
            firmware_version=firmware,
            lab_id=LEGACY_LAB,
            validation_profile=LEGACY_PROFILE,
            selected_tests=(test_name,),
            test_definition_versions={test_name: LEGACY_VERSION},
            resolved_config={},
            configuration_hash=hashlib.sha256(
                f"legacy:baselines:{row_id}".encode("utf-8")
            ).hexdigest(),
            repository_commit="LEGACY_UNKNOWN",
            lifecycle=RunLifecycle.COMPLETED,
            outcome=BusinessOutcome.UNVALIDATED,
            created_at=timestamp,
            completed_at=timestamp,
            provenance=LEGACY_PROVENANCE,
        )
        run_repo = SQLiteRunRepository(self.database)
        attempt_repo = SQLiteAttemptRepository(self.database)
        result_repo = SQLiteTestResultRepository(self.database)
        if run_repo.get(run_id) is None:
            run_repo.save(run)
        if attempt_repo.get(attempt_id) is None:
            attempt_repo.save(Attempt(attempt_id, run_id, 1, started_at=timestamp, completed_at=timestamp))
        metric_value = self._value(row, "metric_value")
        metric_unit = self._value(row, "metric_unit")
        metrics: tuple[Metric, ...] = ()
        if metric_value is not None and metric_unit:
            metrics = (
                Metric(
                    name="legacy_metric",
                    unit=str(metric_unit),
                    samples=(Sample(value=float(metric_value), captured_at=timestamp, metadata={"source": "baselines", "legacy_row_id": row_id}),),
                ),
            )
        result = TestResult(
            test_result_id=result_id,
            run_id=run_id,
            attempt_id=attempt_id,
            test_id=test_name,
            node_id=test_name,
            test_version=LEGACY_VERSION,
            status=status,
            criticality=Criticality.INFORMATIONAL,
            severity=Severity.LOW,
            evidence_state=EvidenceState.INCOMPLETE,
            metrics=metrics,
            error_reason="legacy baseline import; evidence completeness was not recorded",
            completed_at=timestamp,
            provenance=LEGACY_PROVENANCE,
        )
        if result_repo.get(result_id) is None:
            result_repo.save(result)
        baseline_repo = SQLiteBaselineRepository(self.database)
        if baseline_repo.get(baseline_id) is None:
            baseline_repo.save(
                Baseline(
                    baseline_id=baseline_id,
                    name=f"legacy/{firmware}/{row_id}",
                    baseline_run_id=run_id,
                    status=str(self._value(row, "status") or "IMPORTED"),
                    promoted_by="LEGACY_IMPORT",
                    promoted_at=timestamp or datetime.now(timezone.utc),
                    firmware_major_scope=firmware,
                    provenance=LEGACY_PROVENANCE,
                )
            )
        self._mark("baselines", row_id, run_id, result_id)

    def _record_event(
        self, run_id, attempt_id, result_id, event_type, occurred_at, details, event_id
    ) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO lifecycle_events(
                    event_id, run_id, attempt_id, test_result_id, event_type,
                    occurred_at, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    run_id,
                    attempt_id,
                    result_id,
                    event_type,
                    (occurred_at or datetime.now(timezone.utc)).isoformat(),
                    json.dumps(details, sort_keys=True, separators=(",", ":")),
                ),
            )
            connection.commit()

    @staticmethod
    def _parse_timestamp(value) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _status(value: str) -> TestResultStatus:
        try:
            return TestResultStatus(value)
        except ValueError:
            return TestResultStatus.UNVALIDATED
