from datetime import datetime, timezone

from lib.repositories import (
    SQLiteArtifactRepository,
    SQLiteBaselineRepository,
    SQLiteDatabase,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
)
from lib.services import LegacyDatabaseMigrationService


def make_legacy_database(tmp_path):
    database = SQLiteDatabase(tmp_path / "legacy.db")
    database.initialize()
    with database.connection() as connection:
        connection.executescript(
            """
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
        )
        connection.commit()
    return database


def test_legacy_rows_migrate_idempotently(tmp_path):
    database = make_legacy_database(tmp_path)
    pcap = tmp_path / "legacy.pcap"
    pcap.write_bytes(b"legacy-pcap")
    timestamp = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc).isoformat()

    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO test_runs(
                test_name, status, firmware_version, duration_ms,
                error_message, pcap_path, metric_value, metric_unit, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "tests/test_ping.py::test_ping",
                "PASS",
                "v1.0",
                250,
                None,
                str(pcap),
                12.5,
                "ms",
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO baselines(
                test_name, status, firmware_version, metric_value,
                metric_unit, snapshot_time
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
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

    service = LegacyDatabaseMigrationService(database)
    first = service.migrate()
    second = service.migrate()

    assert first["test_runs"] == 1
    assert first["baselines"] == 1
    assert first["artifacts"] == 1
    assert second == {
        "test_runs": 0,
        "baselines": 0,
        "artifacts": 0,
        "artifact_unavailable": 0,
    }

    run = SQLiteRunRepository(database).get("LEGACY-RUN-1")
    assert run is not None
    assert run.provenance == "LEGACY_IMPORTED"
    assert run.lifecycle.value == "COMPLETED"
    assert run.outcome.value == "UNVALIDATED"

    results = SQLiteTestResultRepository(database).list_for_attempt(
        "LEGACY-ATTEMPT-1"
    )
    assert len(results) == 1
    assert results[0].status.value == "PASS"
    assert results[0].evidence_state.value == "INCOMPLETE"
    assert results[0].provenance == "LEGACY_IMPORTED"
    assert results[0].metrics[0].samples[0].value == 12.5

    artifacts = SQLiteArtifactRepository(database).list_for_run("LEGACY-RUN-1")
    assert len(artifacts) == 1
    assert artifacts[0].provenance == "LEGACY_IMPORTED"

    baselines = SQLiteBaselineRepository(database).list_active()
    assert len(baselines) == 1
    assert baselines[0].provenance == "LEGACY_IMPORTED"
    assert baselines[0].baseline_run_id == "LEGACY-BASELINE-RUN-1"

    with database.connection() as connection:
        legacy_row = connection.execute(
            "SELECT test_name, metric_value FROM test_runs WHERE id=1"
        ).fetchone()
        legacy_baseline = connection.execute(
            "SELECT test_name, metric_value FROM baselines WHERE id=1"
        ).fetchone()
    assert tuple(legacy_row) == ("tests/test_ping.py::test_ping", 12.5)
    assert tuple(legacy_baseline) == ("tests/test_ping.py::test_ping", 10.0)
