from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from lib.domain import (
    Artifact,
    ArtifactType,
    Attempt,
    Criticality,
    EvidenceState,
    LifecycleEvent,
    Metric,
    Run,
    Sample,
    Severity,
    TestResult as DomainTestResult,
    TestResultStatus as DomainTestResultStatus,
)
from lib.repositories import (
    DatabaseConfigurationError,
    RepositoryConflictError,
    SQLiteAttemptRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
    resolve_database_path,
)
from lib.services import RunService


def test_sqlite_database_uses_canonical_environment_path(tmp_path, monkeypatch):
    from lib.repositories import database_config

    # Isolate this precedence test from the developer's private repository .env.
    monkeypatch.setattr(database_config, "_load_secure_dotenv", lambda root: None)

    expected = tmp_path / "runner.sqlite"
    monkeypatch.setenv("NETREGRESS_DATABASE_PATH", str(expected))
    monkeypatch.delenv("TEST_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert SQLiteDatabase().path == expected


def test_database_path_defaults_to_repository_results_directory(tmp_path):
    assert resolve_database_path(environ={}, project_root=tmp_path) == tmp_path / "results" / "test_results.db"


def test_explicit_database_path_overrides_environment(tmp_path):
    target = tmp_path / "explicit.sqlite"
    resolved = resolve_database_path(
        target,
        environ={
            "NETREGRESS_DATABASE_PATH": str(tmp_path / "canonical.sqlite"),
            "TEST_DB_PATH": str(tmp_path / "legacy.sqlite"),
            "DATABASE_URL": "postgresql://invalid/ignored",
        },
        project_root=tmp_path,
    )
    assert resolved == target


def test_canonical_path_and_legacy_alias_must_agree(tmp_path):
    with pytest.raises(DatabaseConfigurationError, match="point to different files"):
        resolve_database_path(
            environ={
                "NETREGRESS_DATABASE_PATH": str(tmp_path / "canonical.sqlite"),
                "TEST_DB_PATH": str(tmp_path / "legacy.sqlite"),
            },
            project_root=tmp_path,
        )


def test_canonical_and_legacy_paths_may_match(tmp_path):
    shared = tmp_path / "shared.sqlite"
    assert resolve_database_path(
        environ={
            "NETREGRESS_DATABASE_PATH": str(shared),
            "TEST_DB_PATH": str(shared),
        },
        project_root=tmp_path,
    ) == shared


def test_legacy_test_db_path_remains_supported(tmp_path):
    path = tmp_path / "legacy.sqlite"
    assert resolve_database_path(
        environ={"TEST_DB_PATH": str(path)}, project_root=tmp_path
    ) == path


def test_sqlite_database_url_is_used_as_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_database_path(
        environ={"DATABASE_URL": "sqlite:///results/netregress.sqlite"},
        project_root=tmp_path,
    ) == Path("results/netregress.sqlite")
    assert resolve_database_path(
        environ={"DATABASE_URL": "sqlite:////tmp/netregress.sqlite"},
        project_root=tmp_path,
    ) == Path("/tmp/netregress.sqlite")


def test_sqlite_pysqlite_url_is_supported():
    assert resolve_database_path(
        environ={"DATABASE_URL": "sqlite+pysqlite:///results/netregress.sqlite"}
    ) == Path("results/netregress.sqlite")


def test_sqlite_memory_url_is_rejected_for_independent_connection_model():
    with pytest.raises(DatabaseConfigurationError, match="in-memory SQLite is unsupported"):
        resolve_database_path(environ={"DATABASE_URL": "sqlite:///:memory:"})


def test_explicit_in_memory_database_path_is_rejected():
    with pytest.raises(DatabaseConfigurationError, match="in-memory SQLite is unsupported"):
        SQLiteDatabase(":memory:")


def test_non_sqlite_database_url_fails_closed():
    with pytest.raises(DatabaseConfigurationError, match="synchronous SQLite URL"):
        resolve_database_path(environ={"DATABASE_URL": "postgresql://localhost/netregress"})


def test_transaction_rolls_back_on_exception(tmp_path):
    database = SQLiteDatabase(tmp_path / "transaction.sqlite")
    database.initialize()

    with pytest.raises(RuntimeError, match="abort transaction"):
        with database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('rollback-probe', 'present')"
            )
            raise RuntimeError("abort transaction")

    with database.connection() as connection:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'rollback-probe'"
        ).fetchone()
    assert row is None


def _run(run_id: str, display_id: str) -> Run:
    return Run(
        run_id=run_id,
        display_id=display_id,
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=("tests/test_ping.py::test_ping",),
        test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
        resolved_config={},
        configuration_hash="a" * 64,
        repository_commit="commit-1",
        created_at=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc),
    )


def test_initial_run_attempt_and_events_are_persisted_as_one_bundle(tmp_path):
    database = SQLiteDatabase(tmp_path / "bundle.sqlite")
    database.initialize()
    run = _run("run-bundle", "RUN-BUNDLE")
    attempt = Attempt("attempt-bundle", run.run_id, 1)
    occurred_at = run.created_at
    events = (
        LifecycleEvent("event-run", run.run_id, "RUN_CREATED", occurred_at),
        LifecycleEvent(
            "event-attempt", run.run_id, "ATTEMPT_CREATED", occurred_at,
            attempt_id=attempt.attempt_id,
        ),
    )

    SQLiteRunRepository(database).save_initial_bundle(run, attempt, events)

    assert SQLiteRunRepository(database).get(run.run_id) == run
    assert SQLiteAttemptRepository(database).get(attempt.attempt_id) == attempt
    restored_events = SQLiteEventRepository(database).list_for_run(run.run_id)
    events_by_type = {event.event_type: event for event in restored_events}
    assert set(events_by_type) == {"RUN_CREATED", "ATTEMPT_CREATED"}
    assert events_by_type["RUN_CREATED"].attempt_id is None
    assert events_by_type["ATTEMPT_CREATED"].attempt_id == attempt.attempt_id


def test_initial_run_bundle_rolls_back_run_when_attempt_insert_conflicts(tmp_path):
    database = SQLiteDatabase(tmp_path / "bundle-rollback.sqlite")
    database.initialize()
    runs = SQLiteRunRepository(database)
    attempts = SQLiteAttemptRepository(database)
    events_repo = SQLiteEventRepository(database)
    existing = _run("existing-run", "RUN-EXISTING")
    runs.save(existing)
    attempts.save(Attempt("shared-attempt", existing.run_id, 1))

    candidate = _run("candidate-run", "RUN-CANDIDATE")
    candidate_attempt = Attempt("shared-attempt", candidate.run_id, 1)
    events = (
        LifecycleEvent("candidate-event-1", candidate.run_id, "RUN_CREATED", candidate.created_at),
        LifecycleEvent(
            "candidate-event-2", candidate.run_id, "ATTEMPT_CREATED", candidate.created_at,
            attempt_id=candidate_attempt.attempt_id,
        ),
    )

    with pytest.raises(RepositoryConflictError, match="attempt already exists"):
        runs.save_initial_bundle(candidate, candidate_attempt, events)

    assert runs.get(candidate.run_id) is None
    assert attempts.list_for_run(candidate.run_id) == []
    assert events_repo.list_for_run(candidate.run_id) == []


def test_initial_run_bundle_rolls_back_when_second_event_conflicts(tmp_path):
    database = SQLiteDatabase(tmp_path / "event-rollback.sqlite")
    database.initialize()
    runs = SQLiteRunRepository(database)
    attempts = SQLiteAttemptRepository(database)
    events_repo = SQLiteEventRepository(database)

    existing = _run("existing-event-run", "RUN-EXISTING-EVENT")
    runs.save(existing)
    existing_attempt = Attempt("existing-event-attempt", existing.run_id, 1)
    attempts.save(existing_attempt)
    events_repo.append(
        LifecycleEvent(
            "duplicate-event-id",
            existing.run_id,
            "EXISTING_EVENT",
            existing.created_at,
        )
    )

    candidate = _run("candidate-event-run", "RUN-CANDIDATE-EVENT")
    candidate_attempt = Attempt("candidate-event-attempt", candidate.run_id, 1)
    candidate_events = (
        LifecycleEvent("candidate-first-event", candidate.run_id, "RUN_CREATED", candidate.created_at),
        LifecycleEvent(
            "duplicate-event-id",
            candidate.run_id,
            "ATTEMPT_CREATED",
            candidate.created_at,
            attempt_id=candidate_attempt.attempt_id,
        ),
    )

    with pytest.raises(sqlite3.IntegrityError):
        runs.save_initial_bundle(candidate, candidate_attempt, candidate_events)

    assert runs.get(candidate.run_id) is None
    assert attempts.list_for_run(candidate.run_id) == []
    assert events_repo.list_for_run(candidate.run_id) == []
    assert events_repo.list_for_run(existing.run_id)[0].event_id == "duplicate-event-id"


def test_run_service_uses_atomic_initial_bundle(tmp_path):
    database = SQLiteDatabase(tmp_path / "service-bundle.sqlite")
    database.initialize()
    existing = _run("existing-run", "RUN-EXISTING")
    SQLiteRunRepository(database).save(existing)
    SQLiteAttemptRepository(database).save(Attempt("duplicate-attempt", existing.run_id, 1))
    generated = iter(("candidate-run", "created-event", "duplicate-attempt", "attempt-event"))
    service = RunService(
        SQLiteRunRepository(database),
        SQLiteAttemptRepository(database),
        SQLiteEventRepository(database),
        id_generator=lambda: next(generated),
    )

    with pytest.raises(RepositoryConflictError, match="attempt already exists"):
        service.create_run(
            firmware_version="v1.0",
            lab_id="lab-1",
            validation_profile="Smoke",
            selected_tests=["tests/test_ping.py::test_ping"],
            test_definition_versions={"tests/test_ping.py::test_ping": "1.0"},
            resolved_config={},
            repository_commit="commit-1",
        )

    assert SQLiteRunRepository(database).get("candidate-run") is None
    assert SQLiteEventRepository(database).list_for_run("candidate-run") == []

def test_test_result_metrics_samples_and_artifacts_roll_back_together(tmp_path):
    database = SQLiteDatabase(tmp_path / "test-result-rollback.sqlite")
    database.initialize()
    run = _run("result-run", "RUN-RESULT")
    SQLiteRunRepository(database).save(run)
    attempt = Attempt("result-attempt", run.run_id, 1)
    SQLiteAttemptRepository(database).save(attempt)

    result = DomainTestResult(
        test_result_id="result-atomic",
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id="tests/test_ping.py::test_ping",
        node_id="tests/test_ping.py::test_ping",
        test_version="1.0",
        status=DomainTestResultStatus.PASS,
        criticality=Criticality.BLOCKING,
        severity=Severity.MEDIUM,
        evidence_state=EvidenceState.COMPLETE,
        metrics=(
            Metric(
                name="latency",
                unit="ms",
                samples=(Sample(value=12.5, captured_at=run.created_at),),
                authoritative=True,
            ),
        ),
        artifacts=(
            Artifact(
                artifact_id="invalid-artifact",
                run_id="missing-run",
                artifact_type=ArtifactType.PCAP,
                path="results/missing.pcap",
                sha256="b" * 64,
                size_bytes=1,
                evidence_state=EvidenceState.COMPLETE,
                test_result_id="result-atomic",
            ),
        ),
    )

    with pytest.raises(sqlite3.IntegrityError):
        SQLiteTestResultRepository(database).save(result)

    with database.connection() as connection:
        assert connection.execute(
            "SELECT 1 FROM test_results WHERE test_result_id = ?",
            (result.test_result_id,),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM metrics WHERE test_result_id = ?",
            (result.test_result_id,),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM samples WHERE sample_id = ?",
            ("result-atomic:latency:1",),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = ?",
            ("invalid-artifact",),
        ).fetchone() is None



def test_database_resolver_loads_secure_repository_dotenv(tmp_path, monkeypatch):
    expected = tmp_path / "dotenv-runner.sqlite"
    env_file = tmp_path / ".env"
    env_file.write_text(f"NETREGRESS_DATABASE_PATH={expected}\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.delenv("NETREGRESS_DATABASE_PATH", raising=False)
    monkeypatch.delenv("TEST_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert resolve_database_path(project_root=tmp_path) == expected


def test_database_resolver_does_not_override_process_environment_from_dotenv(tmp_path, monkeypatch):
    dotenv_path = tmp_path / "dotenv.sqlite"
    explicit_path = tmp_path / "process.sqlite"
    env_file = tmp_path / ".env"
    env_file.write_text(f"NETREGRESS_DATABASE_PATH={dotenv_path}\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("NETREGRESS_DATABASE_PATH", str(explicit_path))
    monkeypatch.delenv("TEST_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert resolve_database_path(project_root=tmp_path) == explicit_path


def test_database_resolver_rejects_insecure_dotenv_permissions(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("NETREGRESS_DATABASE_PATH=unsafe.sqlite\n", encoding="utf-8")
    env_file.chmod(0o644)
    monkeypatch.delenv("NETREGRESS_DATABASE_PATH", raising=False)
    monkeypatch.delenv("TEST_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(DatabaseConfigurationError, match="owner-readable only"):
        resolve_database_path(project_root=tmp_path)


def test_database_resolver_rejects_dotenv_symlink(tmp_path, monkeypatch):
    target = tmp_path / "secrets.env"
    target.write_text("NETREGRESS_DATABASE_PATH=runner.sqlite\n", encoding="utf-8")
    target.chmod(0o600)
    (tmp_path / ".env").symlink_to(target)
    monkeypatch.delenv("NETREGRESS_DATABASE_PATH", raising=False)
    monkeypatch.delenv("TEST_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(DatabaseConfigurationError, match="must be a regular file"):
        resolve_database_path(project_root=tmp_path)


def test_explicit_database_path_does_not_load_repository_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("NETREGRESS_DATABASE_PATH=unsafe.sqlite\n", encoding="utf-8")
    env_file.chmod(0o644)
    explicit = tmp_path / "explicit.sqlite"

    assert resolve_database_path(explicit, project_root=tmp_path) == explicit
