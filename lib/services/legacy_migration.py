from __future__ import annotations

import hashlib
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from lib.domain import (
    Artifact, ArtifactType, Attempt, Baseline, BusinessOutcome, Criticality,
    EnvironmentHealthStatus, EvidenceState, LifecycleEvent, Metric, Run,
    RunLifecycle, Sample, Severity, TestResult, TestResultStatus,
)
from lib.repositories import (
    SQLiteBaselineRepository, SQLiteDatabase, SQLiteEventRepository,
    SQLiteRunRepository, SQLiteTestResultRepository,
)
from .run_service import generate_ulid


LEGACY_PROVENANCE = "LEGACY_IMPORTED"
LEGACY_PROFILE = "LEGACY_IMPORTED"
LEGACY_LAB = "LEGACY_UNKNOWN"
LEGACY_VERSION = "LEGACY_UNVERSIONED"
BASELINE_PROFILE = "LEGACY_IMPORTED_BASELINE"


class LegacyMigrationError(RuntimeError):
    """Raised when a legacy source cannot be read safely."""


def _parse_timestamp(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _status(value: str | None) -> TestResultStatus:
    raw = str(value or "UNVALIDATED").strip().upper()
    raw = {
        "SKIP": "SKIPPED",
        "XFAIL": "KNOWN_FAILURE",
        "NOTRUN": "SKIPPED",
        "NOT_RUN": "SKIPPED",
        "PASSED": "PASS",
        "FAILED": "FAIL",
    }.get(raw, raw)
    try:
        return TestResultStatus(raw)
    except ValueError:
        return TestResultStatus.UNVALIDATED


def _is_known_status(value) -> bool:
    raw = str(value or "UNVALIDATED").strip().upper()
    raw = {
        "SKIP": "SKIPPED",
        "XFAIL": "KNOWN_FAILURE",
        "NOTRUN": "SKIPPED",
        "NOT_RUN": "SKIPPED",
        "PASSED": "PASS",
        "FAILED": "FAIL",
    }.get(raw, raw)
    return raw in {status.value for status in TestResultStatus}


def _legacy_metric(value, unit, captured_at, source: str, row_id: int):
    if value is None or not unit:
        return ()
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return ()
    if not math.isfinite(numeric):
        return ()
    return (
        Metric(
            name="legacy_metric",
            unit=str(unit),
            samples=(
                Sample(
                    value=numeric,
                    captured_at=captured_at,
                    metadata={"source": source, "legacy_row_id": row_id},
                ),
            ),
            authoritative=False,
        ),
    )


def _started_at(timestamp: datetime | None, duration_ms) -> datetime | None:
    if timestamp is None or duration_ms is None:
        return None
    try:
        duration = int(duration_ms)
    except (TypeError, ValueError, OverflowError):
        return None
    if duration < 0:
        return None
    return timestamp - timedelta(milliseconds=duration)


def _initial_events(run_id: str, attempt_id: str, occurred_at: datetime):
    return (
        LifecycleEvent(
            event_id=generate_ulid(occurred_at),
            run_id=run_id,
            event_type="RUN_CREATED",
            occurred_at=occurred_at,
            details={"provenance": LEGACY_PROVENANCE},
        ),
        LifecycleEvent(
            event_id=generate_ulid(occurred_at),
            run_id=run_id,
            attempt_id=attempt_id,
            event_type="ATTEMPT_CREATED",
            occurred_at=occurred_at,
            details={"attempt_number": 1, "provenance": LEGACY_PROVENANCE},
        ),
    )


def _insert_import_event(
    connection,
    *,
    run_id: str,
    attempt_id: str,
    event_type: str,
    occurred_at: datetime,
    details: dict,
) -> None:
    SQLiteEventRepository.append_in_transaction(
        connection,
        LifecycleEvent(
            event_id=generate_ulid(occurred_at),
            run_id=run_id,
            attempt_id=attempt_id,
            event_type=event_type,
            occurred_at=occurred_at,
            details=details,
        ),
    )


class LegacyDatabaseMigrationService:
    """Import legacy SQLite facts into canonical repositories, one atomic row at a time.

    A separate source is opened read-only. In-place migration reads old tables
    from the target database but never updates or deletes their rows. The
    existing migration-ledger shape is reused with a source-specific namespace
    in source_table so row IDs from different source files cannot collide.
    """

    def __init__(
        self,
        database: SQLiteDatabase,
        source_database: SQLiteDatabase | str | Path | None = None,
        *,
        source_identity: str | None = None,
    ) -> None:
        self.database = database
        supplied_path = (
            source_database.path
            if isinstance(source_database, SQLiteDatabase)
            else source_database
        )
        self.source_path = Path(supplied_path or database.path).expanduser().resolve()
        self._in_place = self.source_path == database.path.expanduser().resolve()
        identity = (source_identity or str(self.source_path)).strip()
        if not identity:
            raise ValueError("source_identity must not be empty")
        self.source_identity = identity
        self.source_prefix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12].upper()

    @contextmanager
    def _source_connection(self) -> Iterator[sqlite3.Connection]:
        if not self.source_path.is_file():
            raise LegacyMigrationError(f"legacy source database does not exist: {self.source_path}")
        if self._in_place:
            with self.database.connection() as connection:
                yield connection
            return
        uri = f"file:{quote(str(self.source_path))}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            row["name"]
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        }

    @staticmethod
    def _value(row, name: str, default=None):
        return row[name] if name in row.keys() else default

    def _ledger_key(self, source_table: str) -> str:
        return f"source:{self.source_prefix}:{source_table}"

    def _already_imported(self, connection, source_table: str, row_id: int) -> bool:
        namespaced = self._ledger_key(source_table)
        found = connection.execute(
            "SELECT 1 FROM legacy_migration_records WHERE source_table=? AND source_row_id=?",
            (namespaced, row_id),
        ).fetchone()
        if found:
            return True
        # Recognize markers written by the first-generation in-place importer.
        if self._in_place:
            return connection.execute(
                "SELECT 1 FROM legacy_migration_records WHERE source_table=? AND source_row_id=?",
                (source_table, row_id),
            ).fetchone() is not None
        return False

    def _reject_unledgered_first_generation_records(
        self, connection, source_table: str, row_id: int
    ) -> None:
        if not self._in_place:
            return
        if source_table == "test_runs":
            legacy_run_id = f"LEGACY-RUN-{row_id}"
            legacy_result_id = f"LEGACY-RESULT-{row_id}"
            legacy_attempt_id = f"LEGACY-ATTEMPT-{row_id}"
        else:
            legacy_run_id = f"LEGACY-BASELINE-RUN-{row_id}"
            legacy_result_id = f"LEGACY-BASELINE-RESULT-{row_id}"
            legacy_attempt_id = f"LEGACY-BASELINE-ATTEMPT-{row_id}"
        existing = connection.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (legacy_run_id,)
        ).fetchone()
        orphan_result = connection.execute(
            "SELECT 1 FROM test_results WHERE test_result_id = ?",
            (legacy_result_id,),
        ).fetchone()
        orphan_attempt = connection.execute(
            "SELECT 1 FROM attempts WHERE attempt_id = ?",
            (legacy_attempt_id,),
        ).fetchone()
        if existing or orphan_result or orphan_attempt:
            raise LegacyMigrationError(
                f"unledgered first-generation import exists for {source_table}[{row_id}]; "
                "inspect and reconcile it before retrying to avoid duplicate history"
            )

    def _write_ledger(
        self, connection, source_table: str, row_id: int, run_id: str, result_id: str
    ) -> None:
        connection.execute(
            """INSERT INTO legacy_migration_records(
               source_table, source_row_id, target_run_id, target_result_id, imported_at
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                self._ledger_key(source_table),
                row_id,
                run_id,
                result_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def _run_and_attempt(
        self,
        *,
        run_id: str,
        attempt_id: str,
        test_names: tuple[str, ...],
        firmware: str,
        profile: str,
        configuration_hash: str,
        started: datetime | None,
        completed: datetime,
    ) -> tuple[Run, Attempt]:
        run = Run(
            run_id=run_id,
            display_id=run_id,
            firmware_version=firmware,
            lab_id=LEGACY_LAB,
            validation_profile=profile,
            selected_tests=test_names,
            test_definition_versions={name: LEGACY_VERSION for name in test_names},
            resolved_config={},
            configuration_hash=configuration_hash,
            repository_commit="LEGACY_UNKNOWN",
            lifecycle=RunLifecycle.COMPLETED,
            outcome=BusinessOutcome.UNVALIDATED,
            environment_health=EnvironmentHealthStatus.UNKNOWN,
            created_at=started or completed,
            started_at=started,
            completed_at=completed,
            provenance=LEGACY_PROVENANCE,
        )
        attempt = Attempt(
            attempt_id=attempt_id,
            run_id=run_id,
            number=1,
            started_at=started,
            completed_at=completed,
        )
        return run, attempt

    def _resolve_artifact_path(self, value) -> Path | None:
        if not value:
            return None
        raw = Path(str(value)).expanduser()
        candidates = [raw] if raw.is_absolute() else [
            Path.cwd() / raw,
            self.source_path.parent / raw,
        ]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if resolved.is_file():
                    return resolved
            except OSError:
                continue
        return None

    @staticmethod
    def _file_digest(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def migrate(self) -> dict:
        self.database.initialize()
        summary = {
            "source_identity": self.source_identity,
            "source_path": str(self.source_path),
            "target_path": str(self.database.path),
            "test_runs_imported": 0,
            "baselines_imported": 0,
            "artifacts_registered": 0,
            "artifacts_unavailable": 0,
            "skipped": 0,
            "invalid": 0,
            "failed": 0,
            "errors": [],
        }
        with self._source_connection() as source:
            test_runs = []
            if self._table_exists(source, "test_runs"):
                columns = self._columns(source, "test_runs")
                if {"id", "test_name", "status"}.issubset(columns):
                    test_runs = source.execute("SELECT * FROM test_runs ORDER BY id").fetchall()

            baseline_table = None
            for candidate in ("baselines", "legacy_baselines_archive"):
                if self._table_exists(source, candidate):
                    columns = self._columns(source, candidate)
                    if {"id", "test_name", "status"}.issubset(columns):
                        baseline_table = candidate
                        break
            baselines = []
            if baseline_table:
                baselines = source.execute(
                    f'SELECT * FROM "{baseline_table}" ORDER BY id'
                ).fetchall()

        for row in test_runs:
            row_id = int(row["id"])
            if not _is_known_status(self._value(row, "status")):
                summary["invalid"] += 1
            try:
                state = self._import_test_run(row, row_id)
                if state == "skipped":
                    summary["skipped"] += 1
                else:
                    summary["test_runs_imported"] += 1
                    if state == "registered":
                        summary["artifacts_registered"] += 1
                    elif state == "unavailable":
                        summary["artifacts_unavailable"] += 1
            except Exception as exc:
                summary["failed"] += 1
                if isinstance(exc, (LegacyMigrationError, ValueError, TypeError, OverflowError)):
                    summary["invalid"] += 1
                summary["errors"].append(
                    f"test_runs[{row_id}]: {type(exc).__name__}: {str(exc)[:400]}"
                )

        baseline_ledger_table = "baselines" if baseline_table == "legacy_baselines_archive" else baseline_table
        for row in baselines:
            row_id = int(row["id"])
            if not _is_known_status(self._value(row, "status")):
                summary["invalid"] += 1
            try:
                state = self._import_baseline(row, row_id, baseline_ledger_table)
                if state == "skipped":
                    summary["skipped"] += 1
                else:
                    summary["baselines_imported"] += 1
            except Exception as exc:
                summary["failed"] += 1
                if isinstance(exc, (LegacyMigrationError, ValueError, TypeError, OverflowError)):
                    summary["invalid"] += 1
                summary["errors"].append(
                    f"{baseline_table}[{row_id}]: {type(exc).__name__}: {str(exc)[:400]}"
                )
        return summary

    def _import_test_run(self, row, row_id: int) -> str:
        table = "test_runs"
        with self.database.transaction(immediate=True) as connection:
            if self._already_imported(connection, table, row_id):
                return "skipped"
            self._reject_unledgered_first_generation_records(connection, table, row_id)

            timestamp = _parse_timestamp(self._value(row, "timestamp"))
            completed = timestamp or datetime.now(timezone.utc)
            started = _started_at(completed, self._value(row, "duration_ms"))
            test_name = str(self._value(row, "test_name", "")).strip()
            if not test_name:
                raise LegacyMigrationError("legacy test_name is empty")
            firmware = str(self._value(row, "firmware_version") or "UNKNOWN")
            raw_status = str(self._value(row, "status") or "UNVALIDATED")
            status = _status(raw_status)
            metric_value = self._value(row, "metric_value")
            metric_unit = self._value(row, "metric_unit")
            metrics = _legacy_metric(metric_value, metric_unit, completed, table, row_id)
            raw_error = self._value(row, "error_message")
            error_reason = str(raw_error) if raw_error else ""
            error_reason = (error_reason + "; " if error_reason else "") + (
                "legacy import; evidence completeness and environment health were not recorded"
            )

            run_id = f"LEGACY-{self.source_prefix}-RUN-{row_id}"
            attempt_id = f"LEGACY-{self.source_prefix}-ATTEMPT-{row_id}"
            result_id = f"LEGACY-{self.source_prefix}-RESULT-{row_id}"
            config_hash = hashlib.sha256(
                f"{self.source_identity}:{table}:{row_id}".encode("utf-8")
            ).hexdigest()
            run, attempt = self._run_and_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                test_names=(test_name,),
                firmware=firmware,
                profile=LEGACY_PROFILE,
                configuration_hash=config_hash,
                started=started,
                completed=completed,
            )
            SQLiteRunRepository.save_initial_bundle_in_transaction(
                connection, run, attempt, _initial_events(run_id, attempt_id, completed)
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
                completed_at=completed,
                provenance=LEGACY_PROVENANCE,
                execution_metadata={
                    "legacy": {
                        "source_identity": self.source_identity,
                        "source_table": table,
                        "source_row_id": row_id,
                        "raw_status": raw_status,
                        "raw_metric_value": metric_value,
                        "raw_metric_unit": metric_unit,
                        "raw_timestamp": self._value(row, "timestamp"),
                        "pcap_path": self._value(row, "pcap_path"),
                    }
                },
            )
            SQLiteTestResultRepository.save_in_transaction(connection, result)

            artifact_state = "none"
            raw_pcap = self._value(row, "pcap_path")
            if raw_pcap:
                path = self._resolve_artifact_path(raw_pcap)
                if path is not None:
                    try:
                        sha256, size_bytes = self._file_digest(path)
                    except OSError:
                        path = None
                if path is None:
                    artifact_state = "unavailable"
                    _insert_import_event(
                        connection,
                        run_id=run_id,
                        attempt_id=attempt_id,
                        event_type="LEGACY_ARTIFACT_UNAVAILABLE",
                        occurred_at=completed,
                        details={"legacy_path": str(raw_pcap)},
                    )
                else:
                    artifact = Artifact(
                        artifact_id=f"LEGACY-{self.source_prefix}-ARTIFACT-{row_id}",
                        run_id=run_id,
                        test_result_id=result_id,
                        test_node_id=test_name,
                        attempt_id=attempt_id,
                        artifact_type=ArtifactType.PCAP,
                        path=str(path),
                        sha256=sha256,
                        size_bytes=size_bytes,
                        evidence_state=EvidenceState.INCOMPLETE,
                        display_name=path.name,
                        created_at=completed,
                        provenance=LEGACY_PROVENANCE,
                    )
                    SQLiteTestResultRepository._insert_artifact(connection, artifact)
                    artifact_state = "registered"
                    _insert_import_event(
                        connection,
                        run_id=run_id,
                        attempt_id=attempt_id,
                        event_type="LEGACY_ARTIFACT_REGISTERED",
                        occurred_at=completed,
                        details={"artifact_id": artifact.artifact_id, "path": str(path)},
                    )
            self._write_ledger(connection, table, row_id, run_id, result_id)
            return artifact_state

    def _import_baseline(self, row, row_id: int, table: str) -> str:
        with self.database.transaction(immediate=True) as connection:
            if self._already_imported(connection, table, row_id):
                return "skipped"
            self._reject_unledgered_first_generation_records(connection, table, row_id)

            timestamp = _parse_timestamp(self._value(row, "snapshot_time"))
            completed = timestamp or datetime.now(timezone.utc)
            test_name = str(self._value(row, "test_name", "")).strip()
            if not test_name:
                raise LegacyMigrationError("legacy baseline test_name is empty")
            firmware = str(self._value(row, "firmware_version") or "UNKNOWN")
            raw_status = str(self._value(row, "status") or "UNVALIDATED")
            status = _status(raw_status)
            metric_value = self._value(row, "metric_value")
            metric_unit = self._value(row, "metric_unit")
            metrics = _legacy_metric(metric_value, metric_unit, completed, table, row_id)

            run_id = f"LEGACY-{self.source_prefix}-BASELINE-RUN-{row_id}"
            attempt_id = f"LEGACY-{self.source_prefix}-BASELINE-ATTEMPT-{row_id}"
            result_id = f"LEGACY-{self.source_prefix}-BASELINE-RESULT-{row_id}"
            baseline_id = f"LEGACY-{self.source_prefix}-BASELINE-{row_id}"
            config_hash = hashlib.sha256(
                f"{self.source_identity}:{table}:{row_id}".encode("utf-8")
            ).hexdigest()
            run, attempt = self._run_and_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                test_names=(test_name,),
                firmware=firmware,
                profile=BASELINE_PROFILE,
                configuration_hash=config_hash,
                started=timestamp,
                completed=completed,
            )
            SQLiteRunRepository.save_initial_bundle_in_transaction(
                connection, run, attempt, _initial_events(run_id, attempt_id, completed)
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
                completed_at=completed,
                provenance=LEGACY_PROVENANCE,
                execution_metadata={
                    "legacy": {
                        "source_identity": self.source_identity,
                        "source_table": table,
                        "source_row_id": row_id,
                        "raw_status": raw_status,
                        "raw_metric_value": metric_value,
                        "raw_metric_unit": metric_unit,
                    }
                },
            )
            SQLiteTestResultRepository.save_in_transaction(connection, result)
            baseline = Baseline(
                baseline_id=baseline_id,
                name=f"legacy-imported/{firmware}/{self.source_prefix}/{row_id}",
                baseline_run_id=run_id,
                status="IMPORTED",
                promoted_by="LEGACY_IMPORT",
                promoted_at=completed,
                firmware_major_scope=firmware,
                provenance=LEGACY_PROVENANCE,
            )
            SQLiteBaselineRepository.save_in_transaction(connection, baseline)
            _insert_import_event(
                connection,
                run_id=run_id,
                attempt_id=attempt_id,
                event_type="LEGACY_BASELINE_IMPORTED",
                occurred_at=completed,
                details={"baseline_id": baseline_id, "baseline_eligible": False},
            )
            self._write_ledger(connection, table, row_id, run_id, result_id)
            return "imported"


class LegacyCompatibilityService:
    """Preserve the historical insert_result API without writing legacy tables."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def insert_result(
        self,
        test_name: str,
        status: str,
        firmware_version: str = "v1.0",
        duration_ms: int | None = None,
        error_message: str | None = None,
        pcap_path: str | None = None,
        metric_value=None,
        metric_unit: str | None = None,
    ) -> str:
        self.database.initialize()
        now = datetime.now(timezone.utc)
        test_name = str(test_name).strip()
        if not test_name:
            raise ValueError("test_name must not be empty")
        started = _started_at(now, duration_ms)
        run_id = f"LEGACY-COMPAT-RUN-{generate_ulid(now)}"
        attempt_id = f"LEGACY-COMPAT-ATTEMPT-{generate_ulid(now)}"
        result_id = f"LEGACY-COMPAT-RESULT-{generate_ulid(now)}"
        config_hash = hashlib.sha256(
            f"legacy-compat:{run_id}:{test_name}".encode("utf-8")
        ).hexdigest()
        run = Run(
            run_id=run_id,
            display_id=run_id,
            firmware_version=str(firmware_version or "UNKNOWN"),
            lab_id=LEGACY_LAB,
            validation_profile="LEGACY_COMPATIBILITY",
            selected_tests=(test_name,),
            test_definition_versions={test_name: LEGACY_VERSION},
            resolved_config={},
            configuration_hash=config_hash,
            repository_commit="LEGACY_UNKNOWN",
            lifecycle=RunLifecycle.COMPLETED,
            outcome=BusinessOutcome.UNVALIDATED,
            environment_health=EnvironmentHealthStatus.UNKNOWN,
            created_at=started or now,
            started_at=started,
            completed_at=now,
            provenance=LEGACY_PROVENANCE,
        )
        attempt = Attempt(
            attempt_id=attempt_id,
            run_id=run_id,
            number=1,
            started_at=started,
            completed_at=now,
        )
        metrics = _legacy_metric(metric_value, metric_unit, now, "compatibility_write", 0)
        result = TestResult(
            test_result_id=result_id,
            run_id=run_id,
            attempt_id=attempt_id,
            test_id=test_name,
            node_id=test_name,
            test_version=LEGACY_VERSION,
            status=_status(status),
            criticality=Criticality.INFORMATIONAL,
            severity=Severity.LOW,
            evidence_state=EvidenceState.INCOMPLETE,
            metrics=metrics,
            error_reason=(
                (str(error_message) + "; ") if error_message else ""
            ) + "legacy compatibility write; evidence and environment were not certified",
            started_at=started,
            completed_at=now,
            provenance=LEGACY_PROVENANCE,
            execution_metadata={
                "legacy": {
                    "write_api": "lib.db_helper.insert_result",
                    "duration_ms": duration_ms,
                    "pcap_path_unverified": pcap_path,
                    "raw_metric_value": metric_value,
                    "raw_metric_unit": metric_unit,
                }
            },
        )
        with self.database.transaction(immediate=True) as connection:
            SQLiteRunRepository.save_initial_bundle_in_transaction(
                connection, run, attempt, _initial_events(run_id, attempt_id, now)
            )
            SQLiteTestResultRepository.save_in_transaction(connection, result)
            _insert_import_event(
                connection,
                run_id=run_id,
                attempt_id=attempt_id,
                event_type="LEGACY_COMPATIBILITY_RESULT_RECORDED",
                occurred_at=now,
                details={"test_name": test_name, "baseline_eligible": False},
            )
        return run_id
