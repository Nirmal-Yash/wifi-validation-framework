from __future__ import annotations

from lib import db_helper
from lib.repositories import SQLiteBaselineRepository, SQLiteDatabase, SQLiteRunRepository


def use_database(monkeypatch, tmp_path):
    path = tmp_path / "compat.sqlite"
    monkeypatch.setattr(db_helper, "DB_PATH", path)
    return SQLiteDatabase(path)


def test_legacy_helper_writes_only_to_canonical_tables(monkeypatch, tmp_path):
    database = use_database(monkeypatch, tmp_path)
    db_helper.init_db()
    run_id = db_helper.insert_result(
        "tests/test_ping.py::test_ping",
        "PASS",
        firmware_version="v1.0",
        duration_ms=125,
        metric_value=9.5,
        metric_unit="ms",
    )

    run = SQLiteRunRepository(database).get(run_id)
    assert run is not None
    assert run.provenance == "LEGACY_IMPORTED"
    assert run.outcome.value == "UNVALIDATED"
    assert run.environment_health.value == "UNKNOWN"
    latest = db_helper.get_latest_results("v1.0")
    assert latest[0]["metric_value"] == 9.5
    assert latest[0]["duration_ms"] == 125

    with database.connection() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "test_runs" not in tables
    assert "baselines" not in tables


def test_legacy_baseline_helper_stores_untrusted_snapshot_not_active_baseline(
    monkeypatch, tmp_path
):
    database = use_database(monkeypatch, tmp_path)
    db_helper.insert_result("test_ping", "PASS", firmware_version="v1.0", metric_value=10, metric_unit="ms")
    db_helper.insert_result("test_dns", "PASS", firmware_version="v1.0", metric_value=1, metric_unit="bool")

    assert db_helper.save_baseline_from_latest_passes("v1.0") == 2
    rows = db_helper.get_baseline("v1.0")
    assert len(rows) == 2
    assert {row["baseline_status"] for row in rows} == {"IMPORTED"}
    assert {row["baseline_provenance"] for row in rows} == {"LEGACY_IMPORTED"}
    assert SQLiteBaselineRepository(database).list_active() == []


def test_legacy_read_facade_returns_mapping_rows_and_latest_per_test(
    monkeypatch, tmp_path
):
    use_database(monkeypatch, tmp_path)
    db_helper.insert_result("test_ping", "PASS", firmware_version="v1.0", metric_value=10, metric_unit="ms")
    db_helper.insert_result("test_ping", "FAIL", firmware_version="v2.0", metric_value=20, metric_unit="ms")

    latest = db_helper.get_latest_results()
    assert len(latest) == 1
    assert latest[0]["status"] == "FAIL"
    assert latest[0]["firmware_version"] == "v2.0"
    assert isinstance(dict(latest[0]), dict)


def test_legacy_baseline_never_becomes_active_or_validated(monkeypatch, tmp_path):
    database = use_database(monkeypatch, tmp_path)
    db_helper.insert_result("test_ping", "PASS", firmware_version="v1.0")
    db_helper.save_baseline_from_latest_passes("v1.0")

    with database.connection() as connection:
        row = connection.execute(
            "SELECT baseline_run_id, status, provenance FROM run_baselines"
        ).fetchone()
        run = connection.execute(
            "SELECT outcome, environment_health, provenance FROM runs WHERE run_id=?",
            (row["baseline_run_id"],),
        ).fetchone()
    assert row["status"] == "IMPORTED"
    assert row["provenance"] == "LEGACY_IMPORTED"
    assert tuple(run) == ("UNVALIDATED", "UNKNOWN", "LEGACY_IMPORTED")
