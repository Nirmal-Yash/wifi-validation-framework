from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lib.repositories import SQLiteDatabase
from lib.repositories.database_migrations import (
    DatabaseMigrationError,
    DatabaseMigrationManager,
    DatabaseSchemaDriftError,
    MultipleMigrationHeadsError,
)
from lib.services.operational_recovery import SQLiteBackupService


def test_fresh_database_is_created_only_through_single_alembic_head(tmp_path):
    path = tmp_path / "fresh.sqlite"
    database = SQLiteDatabase(path)

    database.initialize()
    status = DatabaseMigrationManager(path).check()

    assert status.current_revision == status.head_revision
    assert status.current_revision == "20261113_07"
    assert status.is_up_to_date
    assert status.schema.is_clean

    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()[0]
        authority = connection.execute(
            "SELECT value FROM schema_meta WHERE key='migration_authority'"
        ).fetchone()[0]
        assert version == "16"
        assert authority == "alembic"


def _create_pre_alembic_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta(key,value) VALUES ('version','11');

            CREATE TABLE environment_snapshots(
                snapshot_id TEXT PRIMARY KEY, host_os TEXT NOT NULL, kernel TEXT NOT NULL,
                python_version TEXT NOT NULL, repository_commit TEXT NOT NULL,
                configuration_hash TEXT NOT NULL, tools_json TEXT NOT NULL
            );
            CREATE TABLE config_snapshots(
                snapshot_id TEXT PRIMARY KEY, resolved_config_json TEXT NOT NULL,
                configuration_hash TEXT NOT NULL
            );
            CREATE TABLE runs(
                run_id TEXT PRIMARY KEY, display_id TEXT NOT NULL UNIQUE,
                firmware_version TEXT NOT NULL, lab_id TEXT NOT NULL,
                validation_profile TEXT NOT NULL, selected_tests_json TEXT NOT NULL,
                test_definition_versions_json TEXT NOT NULL, resolved_config_json TEXT NOT NULL,
                configuration_hash TEXT NOT NULL, repository_commit TEXT NOT NULL,
                lifecycle TEXT NOT NULL, outcome TEXT,
                environment_health TEXT,
                environment_snapshot_id TEXT REFERENCES environment_snapshots(snapshot_id),
                config_snapshot_id TEXT REFERENCES config_snapshots(snapshot_id),
                created_at TEXT, started_at TEXT, completed_at TEXT
            );
            CREATE TABLE attempts(
                attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                number INTEGER NOT NULL, started_at TEXT, completed_at TEXT,
                UNIQUE(run_id, number)
            );
            CREATE TABLE test_results(
                test_result_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
                test_id TEXT NOT NULL, node_id TEXT NOT NULL, test_version TEXT NOT NULL,
                status TEXT NOT NULL, criticality TEXT NOT NULL, severity TEXT NOT NULL,
                evidence_state TEXT NOT NULL, error_reason TEXT, started_at TEXT, completed_at TEXT
            );
            CREATE TABLE artifacts(
                artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                test_result_id TEXT REFERENCES test_results(test_result_id),
                artifact_type TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, evidence_state TEXT NOT NULL, created_at TEXT
            );
            CREATE TABLE baselines(
                baseline_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                baseline_run_id TEXT NOT NULL REFERENCES runs(run_id), status TEXT NOT NULL,
                device_scope TEXT NOT NULL, firmware_major_scope TEXT NOT NULL,
                test_suite_version TEXT NOT NULL, lab_class TEXT NOT NULL,
                promoted_by TEXT NOT NULL, promoted_at TEXT NOT NULL, superseded_by TEXT
            );
            """
        )
        connection.execute(
            """INSERT INTO runs(
                run_id,display_id,firmware_version,lab_id,validation_profile,
                selected_tests_json,test_definition_versions_json,resolved_config_json,
                configuration_hash,repository_commit,lifecycle,outcome,environment_health,
                created_at,started_at,completed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "pre-alembic-run", "RUN-PRE-ALEMBIC", "v1.0", "lab",
                "Full", '{"tests":["test_ping"]}', '{"test_ping":"1"}', "{}",
                "a" * 64, "old-commit", "COMPLETED", "UNVALIDATED", "UNKNOWN",
                "2026-09-24T10:00:00+00:00", None, None,
            ),
        )
        connection.execute(
            """INSERT INTO baselines(
                baseline_id,name,baseline_run_id,status,device_scope,
                firmware_major_scope,test_suite_version,lab_class,promoted_by,
                promoted_at,superseded_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "legacy-baseline-1", "old-golden", "pre-alembic-run",
                "IMPORTED", "", "v1", "suite-1", "lab",
                "historical-operator", "2026-09-24T10:00:00+00:00", None,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_pre_alembic_v11_database_is_backed_up_upgraded_and_preserved(tmp_path):
    path = tmp_path / "pre-alembic.sqlite"
    _create_pre_alembic_database(path)
    manager = DatabaseMigrationManager(path)

    result = manager.upgrade()

    assert result.current_revision == result.head_revision == "20261113_07"
    assert result.is_up_to_date
    assert result.last_backup is not None
    assert result.last_backup.is_file()
    with sqlite3.connect(result.last_backup) as backup:
        assert backup.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()[0] == "11"
        assert backup.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone() is None

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT run_id FROM runs WHERE run_id='pre-alembic-run'"
        ).fetchone()[0] == "pre-alembic-run"
        assert connection.execute(
            "SELECT baseline_id FROM run_baselines WHERE baseline_id='legacy-baseline-1'"
        ).fetchone()[0] == "legacy-baseline-1"
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_baselines_archive'"
        ).fetchone() is not None
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()[0] == "16"


def test_schema_drift_is_reported_without_silent_repair(tmp_path):
    path = tmp_path / "drift.sqlite"
    SQLiteDatabase(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX idx_events_run")
        connection.commit()

    status = DatabaseMigrationManager(path).check()
    assert not status.is_up_to_date
    assert "idx_events_run" in status.schema.missing_indexes

    # A normal application initialization refuses to run against drift. It
    # does not silently recreate the missing index outside a migration.
    with pytest.raises(DatabaseMigrationError, match="Alembic upgrade failed"):
        SQLiteDatabase(path).initialize()
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_events_run'"
        ).fetchone()
    assert exists is None


def test_failed_upgrade_restores_pre_migration_database_and_keeps_backup(tmp_path):
    path = tmp_path / "rollback.sqlite"
    _create_pre_alembic_database(path)
    manager = DatabaseMigrationManager(path)

    def fail_after_partial_ddl(target="head"):
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE injected_partial_state(id INTEGER)")
            connection.commit()
        raise RuntimeError("injected Alembic failure")

    manager._run_alembic_upgrade = fail_after_partial_ddl
    with pytest.raises(DatabaseMigrationError, match="restored from"):
        manager.upgrade()

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()[0] == "11"
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='injected_partial_state'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT run_id FROM runs WHERE run_id='pre-alembic-run'"
        ).fetchone()[0] == "pre-alembic-run"

    backups = list((tmp_path / "backups").glob("*.pre-migration-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_restore_is_verified_and_restore_preserves_current_copy(tmp_path):
    path = tmp_path / "data.sqlite"
    database = SQLiteDatabase(path)
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO schema_meta(key,value) VALUES('restore-probe','before')"
        )

    manager = DatabaseMigrationManager(path)
    backup = manager.backup(tmp_path / "manual-backup.sqlite")
    assert backup.integrity_ok
    assert len(backup.sha256) == 64

    with database.transaction() as connection:
        connection.execute(
            "UPDATE schema_meta SET value='after' WHERE key='restore-probe'"
        )
    restored = manager.restore(backup.destination)

    assert restored["integrity_ok"]
    assert Path(restored["pre_restore_backup"]).is_file()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='restore-probe'"
        ).fetchone()[0] == "before"


def test_backup_refuses_to_overwrite_existing_backup(tmp_path):
    source = tmp_path / "source.sqlite"
    SQLiteDatabase(source).initialize()
    backup = tmp_path / "backup.sqlite"
    service = SQLiteBackupService()
    service.backup(source, backup)
    with pytest.raises(FileExistsError):
        service.backup(source, backup)


def test_repository_with_multiple_alembic_heads_fails_closed(tmp_path, monkeypatch):
    manager = DatabaseMigrationManager(tmp_path / "multi.sqlite")

    class FakeScript:
        def get_heads(self):
            return ["head-a", "head-b"]

    monkeypatch.setattr(
        "lib.repositories.database_migrations.ScriptDirectory.from_config",
        lambda config: FakeScript(),
    )
    with pytest.raises(MultipleMigrationHeadsError, match="expected one Alembic head"):
        manager._script()


def test_unknown_database_revision_fails_closed(tmp_path):
    path = tmp_path / "unknown-revision.sqlite"
    SQLiteDatabase(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE alembic_version SET version_num='unknown-revision'"
        )
        connection.commit()

    with pytest.raises(DatabaseMigrationError, match="not present in this repository"):
        DatabaseMigrationManager(path).check()


def test_existing_20260924_02_database_gets_forward_schema_reconciliation(tmp_path):
    path = tmp_path / "previous-alembic-head.sqlite"
    SQLiteDatabase(path).initialize()
    with sqlite3.connect(path) as connection:
        # Recreate a genuine pre-Stage-B 20260924_02 database. The helper
        # starts from the current schema so every later table, index and
        # trigger must be removed before rewinding the recorded Alembic head.
        connection.execute("DROP TRIGGER trg_audit_events_no_update")
        connection.execute("DROP TRIGGER trg_audit_events_no_delete")
        connection.execute("DROP TABLE audit_events")
        connection.execute("DROP TABLE password_reset_tokens")
        connection.execute("DROP TABLE invitation_tokens")
        connection.execute("DROP TABLE user_sessions")
        connection.execute("DROP TABLE role_assignments")
        connection.execute("DROP TABLE role_permissions")
        connection.execute("DROP TABLE permissions")
        connection.execute("DROP TABLE roles")
        connection.execute("DROP TABLE users")
        connection.execute("DROP INDEX idx_project_memberships_project")
        connection.execute("DROP TABLE project_memberships")
        connection.execute("DROP INDEX idx_runs_project_created")
        connection.execute("DROP TRIGGER trg_runs_project_scope_insert")
        connection.execute("DROP TRIGGER trg_runs_project_scope_update")
        connection.execute("DROP TRIGGER trg_projects_prevent_delete_with_runs")
        connection.execute("ALTER TABLE runs DROP COLUMN project_id")
        connection.execute("DROP TABLE labs")
        connection.execute("DROP TABLE projects")
        connection.execute("DROP TABLE organizations")
        connection.execute("DROP TABLE legacy_migration_records")
        connection.execute(
            "UPDATE alembic_version SET version_num='20260924_02'"
        )
        connection.execute(
            "UPDATE schema_meta SET value='11' WHERE key='version'"
        )
        connection.execute(
            "DELETE FROM schema_meta WHERE key='migration_authority'"
        )
        connection.execute(
            "DELETE FROM schema_meta WHERE key='alembic_revision'"
        )
        connection.commit()

    status = DatabaseMigrationManager(path).upgrade()
    assert status.current_revision == status.head_revision == "20261113_07"
    assert status.is_up_to_date
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_migration_records'"
        ).fetchone() is not None
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key='version'"
        ).fetchone()[0] == "16"


def test_database_operator_cli_commands(tmp_path):
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    cli = root / "scripts" / "netregress_db.py"
    database = tmp_path / "operator.sqlite"
    backup = tmp_path / "operator-backup.sqlite"

    def invoke(*args):
        return subprocess.run(
            [sys.executable, str(cli), "--database", str(database), *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        )

    upgraded = invoke("upgrade")
    assert json.loads(upgraded.stdout)["is_up_to_date"] is True
    assert json.loads(invoke("status").stdout)["is_up_to_date"] is True
    assert json.loads(invoke("check").stdout)["is_up_to_date"] is True

    backup_result = invoke("backup", "--output", str(backup))
    assert json.loads(backup_result.stdout)["integrity_ok"] is True
    assert backup.is_file()

    restored = invoke("restore", "--backup", str(backup), "--confirm")
    assert json.loads(restored.stdout)["integrity_ok"] is True
    assert Path(json.loads(restored.stdout)["pre_restore_backup"]).is_file()
    assert json.loads(invoke("check").stdout)["is_up_to_date"] is True
