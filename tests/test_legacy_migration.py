from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

import pytest

from lib.repositories import (
    SQLiteArtifactRepository,
    SQLiteBaselineRepository,
    SQLiteDatabase,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
)
from lib.services import LegacyDatabaseMigrationService


LEGACY_SCHEMA = """
CREATE TABLE test_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    status TEXT NOT NULL,
    firmware_version TEXT,
    duration_ms INTEGER,
    error_message TEXT,
    pcap_path TEXT,
    metric_value REAL,
    metric_unit TEXT,
    timestamp TEXT NOT NULL
);
CREATE TABLE baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_name TEXT NOT NULL,
    status TEXT NOT NULL,
    firmware_version TEXT,
    metric_value REAL,
    metric_unit TEXT,
    snapshot_time TEXT NOT NULL
);
"""


def make_legacy_source(path, *, pcap_path=None, status="PASS"):
    connection = sqlite3.connect(path)
    try:
        connection.executescript(LEGACY_SCHEMA)
        timestamp = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc).isoformat()
        connection.execute(
            """INSERT INTO test_runs(
               test_name, status, firmware_version, duration_ms, error_message,
               pcap_path, metric_value, metric_unit, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "tests/test_ping.py::test_ping",
                status,
                "v1.0",
                250,
                None,
                str(pcap_path) if pcap_path else None,
                12.5,
                "ms",
                timestamp,
            ),
        )
        connection.execute(
            """INSERT INTO baselines(
               test_name, status, firmware_version, metric_value, metric_unit, snapshot_time
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "tests/test_ping.py::test_ping",
                "PASS",
                "v1.0",
                10.0,
                "ms",
                timestamp,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_separate_source_is_read_only_and_migration_is_idempotent(tmp_path):
    source = tmp_path / "legacy-source.sqlite"
    target_path = tmp_path / "canonical-target.sqlite"
    make_legacy_source(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    target = SQLiteDatabase(target_path)

    service = LegacyDatabaseMigrationService(target, source)
    first = service.migrate()
    second = service.migrate()

    assert first["test_runs_imported"] == 1
    assert first["baselines_imported"] == 1
    assert first["failed"] == 0
    assert second["test_runs_imported"] == 0
    assert second["baselines_imported"] == 0
    assert second["skipped"] == 2
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before

    run_id = f"LEGACY-{service.source_prefix}-RUN-1"
    run = SQLiteRunRepository(target).get(run_id)
    assert run is not None
    assert run.provenance == "LEGACY_IMPORTED"
    assert run.outcome.value == "UNVALIDATED"
    assert run.environment_health.value == "UNKNOWN"

    results = SQLiteTestResultRepository(target).list_for_run(run_id)
    assert len(results) == 1
    assert results[0].status.value == "PASS"
    assert results[0].evidence_state.value == "INCOMPLETE"
    assert results[0].provenance == "LEGACY_IMPORTED"
    assert results[0].metrics[0].samples[0].value == 12.5
    assert results[0].metrics[0].authoritative is False

    baseline = SQLiteBaselineRepository(target).get(
        f"LEGACY-{service.source_prefix}-BASELINE-1"
    )
    assert baseline is not None
    assert baseline.status == "IMPORTED"
    assert baseline.provenance == "LEGACY_IMPORTED"
    assert SQLiteBaselineRepository(target).list_active() == []


def test_distinct_source_identity_prevents_row_id_collisions(tmp_path):
    source_a = tmp_path / "a.sqlite"
    source_b = tmp_path / "b.sqlite"
    make_legacy_source(source_a)
    make_legacy_source(source_b)
    target = SQLiteDatabase(tmp_path / "target.sqlite")

    first = LegacyDatabaseMigrationService(target, source_a).migrate()
    second = LegacyDatabaseMigrationService(target, source_b).migrate()

    assert first["test_runs_imported"] == 1
    assert second["test_runs_imported"] == 1
    with target.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM runs WHERE provenance='LEGACY_IMPORTED' AND validation_profile='LEGACY_IMPORTED'"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(DISTINCT source_table) FROM legacy_migration_records"
        ).fetchone()[0] == 4


def test_in_place_migration_preserves_legacy_rows_and_is_restartable(tmp_path):
    path = tmp_path / "combined.sqlite"
    make_legacy_source(path)
    database = SQLiteDatabase(path)

    first = LegacyDatabaseMigrationService(database).migrate()
    second = LegacyDatabaseMigrationService(database).migrate()

    assert first["test_runs_imported"] == 1
    assert first["baselines_imported"] == 1
    assert second["skipped"] == 2
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM test_runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM baselines").fetchone()[0] == 1


def test_existing_pcap_is_registered_and_missing_pcap_is_reported(tmp_path):
    pcap = tmp_path / "capture.pcap"
    pcap.write_bytes(b"verified legacy capture")
    source = tmp_path / "legacy.sqlite"
    make_legacy_source(source, pcap_path=pcap)
    target = SQLiteDatabase(tmp_path / "target.sqlite")
    service = LegacyDatabaseMigrationService(target, source)

    summary = service.migrate()
    run_id = f"LEGACY-{service.source_prefix}-RUN-1"
    artifacts = SQLiteArtifactRepository(target).list_for_run(run_id)

    assert summary["artifacts_registered"] == 1
    assert summary["artifacts_unavailable"] == 0
    assert len(artifacts) == 1
    assert artifacts[0].path == str(pcap.resolve())
    assert artifacts[0].evidence_state.value == "INCOMPLETE"
    assert artifacts[0].sha256 == hashlib.sha256(pcap.read_bytes()).hexdigest()

    missing_source = tmp_path / "missing-pcap-source.sqlite"
    make_legacy_source(missing_source, pcap_path=tmp_path / "not-present.pcap")
    missing_target = SQLiteDatabase(tmp_path / "missing-target.sqlite")
    missing = LegacyDatabaseMigrationService(missing_target, missing_source).migrate()
    assert missing["artifacts_unavailable"] == 1
    with missing_target.connection() as connection:
        event = connection.execute(
            "SELECT event_type FROM lifecycle_events WHERE event_type='LEGACY_ARTIFACT_UNAVAILABLE'"
        ).fetchone()
    assert event is not None
    unavailable_service = LegacyDatabaseMigrationService(missing_target, missing_source)
    unavailable_run_id = f"LEGACY-{unavailable_service.source_prefix}-RUN-1"
    unavailable_result = SQLiteTestResultRepository(missing_target).list_for_run(unavailable_run_id)[0]
    assert unavailable_result.execution_metadata["legacy"]["pcap_path"] == str(tmp_path / "not-present.pcap")


def test_import_row_and_ledger_marker_roll_back_together(tmp_path, monkeypatch):
    source = tmp_path / "legacy.sqlite"
    make_legacy_source(source)
    target = SQLiteDatabase(tmp_path / "target.sqlite")

    def fail_result_save(connection, result):
        raise RuntimeError("injected result insert failure")

    monkeypatch.setattr(
        "lib.services.legacy_migration.SQLiteTestResultRepository.save_in_transaction",
        fail_result_save,
    )
    summary = LegacyDatabaseMigrationService(target, source).migrate()

    assert summary["failed"] == 2
    with target.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM runs WHERE provenance='LEGACY_IMPORTED'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_migration_records"
        ).fetchone()[0] == 0


def test_missing_source_fails_without_materializing_source(tmp_path):
    target = SQLiteDatabase(tmp_path / "target.sqlite")
    missing = tmp_path / "does-not-exist.sqlite"
    with pytest.raises(Exception, match="does not exist"):
        LegacyDatabaseMigrationService(target, missing).migrate()
    assert not missing.exists()


def test_unrecognized_status_is_imported_unvalidated_and_reported_invalid(tmp_path):
    source = tmp_path / "unknown-status.sqlite"
    make_legacy_source(source, status="MYSTERY_STATE")
    target = SQLiteDatabase(tmp_path / "target.sqlite")
    service = LegacyDatabaseMigrationService(target, source)

    summary = service.migrate()
    assert summary["test_runs_imported"] == 1
    assert summary["invalid"] == 1
    assert summary["failed"] == 0

    result = SQLiteTestResultRepository(target).list_for_run(
        f"LEGACY-{service.source_prefix}-RUN-1"
    )[0]
    assert result.status.value == "UNVALIDATED"
    assert result.execution_metadata["legacy"]["raw_status"] == "MYSTERY_STATE"
