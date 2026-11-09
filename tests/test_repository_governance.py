from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from lib.domain import Run, SyncEnvelope
from lib.repositories import SQLiteDatabase, SQLiteRunRepository, SQLiteSyncQueueRepository
from scripts import netregress_sync


def _database_with_run(path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(path)
    database.initialize()
    SQLiteRunRepository(database).save(
        Run(
            run_id="run-sync-status",
            display_id="RUN-SYNC-STATUS",
            firmware_version="v1.0",
            lab_id="lab",
            validation_profile="Full",
            selected_tests=("test.sample",),
            test_definition_versions={"test.sample": "1.0"},
            resolved_config={},
            configuration_hash="a" * 64,
            repository_commit="commit",
        )
    )
    return database


def _envelope(index: int) -> SyncEnvelope:
    payload = json.dumps({"index": index}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return SyncEnvelope(
        envelope_id=hashlib.sha256(f"envelope-{index}".encode()).hexdigest()[:32],
        runner_id="runner-status",
        run_id="run-sync-status",
        kind="RUN_SNAPSHOT",
        schema_version="runner-sync.v1",
        idempotency_key=f"run-sync-status:{index}:{digest}",
        payload_json=payload,
        payload_sha256=digest,
        created_at=datetime.now(timezone.utc),
    )


def test_read_only_connection_rejects_schema_mutations(tmp_path):
    database = SQLiteDatabase(tmp_path / "readonly.sqlite")
    database.initialize()

    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        with database.read_only_connection() as connection:
            connection.execute("CREATE TABLE forbidden_write (value TEXT)")

    with database.read_only_connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forbidden_write'"
        ).fetchone()
    assert exists is None


def test_sync_status_reports_queue_states_without_remote_transport(tmp_path, monkeypatch, capsys):
    database = _database_with_run(tmp_path / "sync-status.sqlite")
    queue = SQLiteSyncQueueRepository(database)
    now = datetime.now(timezone.utc)

    queued = queue.enqueue(_envelope(1))
    in_flight = queue.enqueue(_envelope(2))
    acked = queue.enqueue(_envelope(3))
    failed = queue.enqueue(_envelope(4))
    blocked = queue.enqueue(_envelope(5))

    lease = queue.claim(in_flight.envelope.envelope_id, now, now + timedelta(minutes=2))
    assert lease is not None

    lease = queue.claim(acked.envelope.envelope_id, now, now + timedelta(minutes=2))
    assert lease is not None
    queue.ack(acked.envelope.envelope_id, now, expected_lease=lease.leased_at)

    lease = queue.claim(failed.envelope.envelope_id, now, now + timedelta(minutes=2))
    assert lease is not None
    queue.fail(
        failed.envelope.envelope_id,
        next_attempt_at=now + timedelta(minutes=1),
        error="temporary transport outage",
        updated_at=now,
        expected_lease=lease.leased_at,
    )

    lease = queue.claim(blocked.envelope.envelope_id, now, now + timedelta(minutes=2))
    assert lease is not None
    queue.fail(
        blocked.envelope.envelope_id,
        next_attempt_at=now,
        error="operator action required",
        updated_at=now,
        blocked=True,
        expected_lease=lease.leased_at,
    )

    def forbidden_transport(*args, **kwargs):
        raise AssertionError("status mode must not construct a remote transport")

    monkeypatch.setattr(netregress_sync, "HttpSyncTransport", forbidden_transport)
    result = netregress_sync.main([
        "--status",
        "--db", str(database.path),
        "--runner-id", "runner-status",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["status"] == "READY"
    assert payload["runner_id"] == "runner-status"
    assert payload["queue"] == {
        "total": 5,
        "QUEUED": 1,
        "IN_FLIGHT": 1,
        "ACKED": 1,
        "FAILED": 1,
        "BLOCKED": 1,
    }
    assert payload["pending_delivery"] == 3
    assert payload["blocked_attention"] == 1
    assert "read-only" in payload["message"]


def test_sync_status_does_not_create_a_missing_database(tmp_path, capsys):
    path = tmp_path / "not-initialized.sqlite"

    result = netregress_sync.main(["--status", "--db", str(path)])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["status"] == "NOT_INITIALIZED"
    assert not path.exists()


def test_sync_status_does_not_migrate_an_uninitialized_database(tmp_path, capsys):
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()

    result = netregress_sync.main(["--status", "--db", str(path)])
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["status"] == "SCHEMA_UNAVAILABLE"
    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    assert tables == []


def test_legacy_entry_points_delegate_to_canonical_commands():
    root = Path(__file__).resolve().parents[1]
    run_all = (root / "run_all.sh").read_text(encoding="utf-8")
    verify_system = (root / "verify_system.py").read_text(encoding="utf-8")

    assert "scripts/netregress_install.py" in run_all
    assert "scripts/start_dashboard.sh" in run_all
    assert "python3 dashboard/app.py" not in run_all
    assert "RUN_DASHBOARD" in run_all
    assert "scripts/netregress_release.py" in verify_system
    assert "verify_report.html" not in verify_system


def test_gitignore_covers_secret_database_and_runtime_patterns():
    root = Path(__file__).resolve().parents[1]
    lines = [
        line.strip()
        for line in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines.count(".robust-backups/") == 1
    assert {
        ".env.*",
        "!.env.example",
        "*.sqlite",
        "*.sqlite3",
        "*.pcapng",
        "*.log",
        "*.migration.lock",
        ".local/",
        "results/",
    } <= set(lines)


def test_documentation_index_includes_standalone_operations():
    root = Path(__file__).resolve().parents[1]
    index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    runbook = root / "docs" / "STANDALONE_INSTALLATION_AND_OPERATIONS.md"

    assert runbook.is_file()
    assert "STANDALONE_INSTALLATION_AND_OPERATIONS.md" in index
