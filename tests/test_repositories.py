from datetime import datetime, timezone

import pytest

from lib.domain import (
    Artifact,
    ArtifactType,
    Attempt,
    Baseline,
    Criticality,
    EnvironmentHealthStatus,
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
    RepositoryConflictError,
    SQLiteArtifactRepository,
    SQLiteAttemptRepository,
    SQLiteBaselineRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
)


def make_run() -> Run:
    return Run(
        run_id="run-1",
        display_id="RUN-20260924-120000-0001",
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=("wifi.latency",),
        test_definition_versions={"wifi.latency": "1.0"},
        resolved_config={"threshold": 50},
        configuration_hash="a" * 64,
        repository_commit="commit-1",
        created_at=datetime.now(timezone.utc),
    )


def make_database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "results.db")
    database.initialize()
    return database


def test_initialize_preserves_legacy_tables(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "results.db")
    with database.connection() as connection:
        connection.execute("CREATE TABLE test_runs (id INTEGER PRIMARY KEY)")
        connection.commit()

    database.initialize()

    with database.connection() as connection:
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "test_runs" in names
    assert "runs" in names


def test_run_round_trip(tmp_path) -> None:
    database = make_database(tmp_path)
    repository = SQLiteRunRepository(database)
    expected = make_run()

    repository.save(expected)

    assert repository.get(expected.run_id) == expected


def test_attempt_and_result_round_trip_with_metric_sample_artifact(tmp_path) -> None:
    database = make_database(tmp_path)
    SQLiteRunRepository(database).save(make_run())
    SQLiteAttemptRepository(database).save(Attempt("a-1", "run-1", 1))

    captured_at = datetime.now(timezone.utc)
    metric = Metric(
        name="latency",
        unit="ms",
        samples=(
            Sample(
                value=42.5,
                captured_at=captured_at,
                metadata={"source": "test"},
            ),
        ),
        authoritative=True,
    )
    artifact = Artifact(
        artifact_id="art-1",
        run_id="run-1",
        artifact_type=ArtifactType.PCAP,
        path="results/a.pcap",
        sha256="b" * 64,
        size_bytes=100,
        test_result_id="tr-1",
    )
    result = DomainTestResult(
        test_result_id="tr-1",
        run_id="run-1",
        attempt_id="a-1",
        test_id="wifi.latency",
        node_id="tests/test_ping.py::test_latency",
        test_version="1.0",
        status=DomainTestResultStatus.PASS,
        criticality=Criticality.BLOCKING,
        severity=Severity.HIGH,
        evidence_state=EvidenceState.COMPLETE,
        metrics=(metric,),
        artifacts=(artifact,),
        started_at=captured_at,
        completed_at=captured_at,
        execution_metadata={"pytest": {"phase": "call", "outcome": "skipped"}},
    )

    SQLiteTestResultRepository(database).save(result)
    restored = SQLiteTestResultRepository(database).get("tr-1")

    assert restored is not None
    assert restored.metrics[0].samples[0].value == 42.5
    assert restored.metrics[0].samples[0].metadata == {"source": "test"}
    assert restored.execution_metadata == {"pytest": {"phase": "call", "outcome": "skipped"}}
    assert restored.artifacts[0] == artifact


def test_failure_metadata_and_snapshots_round_trip(tmp_path):
    database = make_database(tmp_path)
    run = make_run()
    from lib.domain import ConfigSnapshot, EnvironmentSnapshot, FailureClass
    run.config_snapshot = ConfigSnapshot("config-1", {"threshold": 10}, "f" * 64)
    run.environment = EnvironmentSnapshot(
        "env-1", "linux", "kernel", "python", "commit-1", "f" * 64, {"fingerprint": "e" * 64}
    )
    SQLiteRunRepository(database).save(run)
    SQLiteAttemptRepository(database).save(Attempt("a-1", "run-1", 1))
    restored_run = SQLiteRunRepository(database).get(run.run_id)
    assert restored_run is not None
    assert restored_run.config_snapshot is not None
    assert restored_run.environment is not None

    result = DomainTestResult(
        test_result_id="tr-failure",
        run_id="run-1",
        attempt_id="a-1",
        test_id="wifi.latency",
        node_id="tests/test_ping.py::test_latency",
        test_version="1.0",
        status=DomainTestResultStatus.FAIL,
        criticality=Criticality.BLOCKING,
        severity=Severity.HIGH,
        evidence_state=EvidenceState.COMPLETE,
        failure_class=FailureClass.PRODUCT_FAILED,
        failure_reason="threshold exceeded",
        execution_pid=123,
    )
    SQLiteTestResultRepository(database).save(result)
    restored = SQLiteTestResultRepository(database).get("tr-failure")
    assert restored is not None
    assert restored.failure_class is FailureClass.PRODUCT_FAILED
    assert restored.failure_reason == "threshold exceeded"
    assert restored.execution_pid == 123


def test_artifact_repository_round_trip(tmp_path) -> None:
    database = make_database(tmp_path)
    SQLiteRunRepository(database).save(make_run())
    artifact = Artifact(
        artifact_id="art-2",
        run_id="run-1",
        artifact_type=ArtifactType.SETUP_LOG,
        path="results/setup.log",
        sha256="c" * 64,
        size_bytes=10,
    )

    SQLiteArtifactRepository(database).save(artifact)

    assert SQLiteArtifactRepository(database).get("art-2") == artifact
    assert SQLiteArtifactRepository(database).list_for_run("run-1") == [artifact]


def test_event_round_trip(tmp_path) -> None:
    database = make_database(tmp_path)
    SQLiteRunRepository(database).save(make_run())
    event = LifecycleEvent(
        event_id="event-1",
        run_id="run-1",
        event_type="RUN_CREATED",
        occurred_at=datetime.now(timezone.utc),
        details={"source": "test"},
    )

    SQLiteEventRepository(database).append(event)

    assert SQLiteEventRepository(database).list_for_run("run-1") == [event]


def test_baseline_duplicate_is_rejected(tmp_path) -> None:
    database = make_database(tmp_path)
    SQLiteRunRepository(database).save(make_run())
    repository = SQLiteBaselineRepository(database)
    baseline = Baseline(
        baseline_id="baseline-1",
        name="Golden",
        baseline_run_id="run-1",
        status="ACTIVE",
        promoted_by="tester",
        promoted_at=datetime.now(timezone.utc),
    )

    repository.save(baseline)

    with pytest.raises(RepositoryConflictError):
        repository.save(baseline)


def test_legacy_artifact_schema_is_migrated(tmp_path):
    database = SQLiteDatabase(tmp_path / "legacy.db")
    with database.connection() as connection:
        connection.executescript("""
            CREATE TABLE runs (
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
                environment_snapshot_id TEXT,
                config_snapshot_id TEXT,
                created_at TEXT,
                started_at TEXT,
                completed_at TEXT
            );
            CREATE TABLE test_results (
                test_result_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
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
                provenance TEXT NOT NULL DEFAULT 'NATIVE',
                failure_class TEXT,
                failure_reason TEXT,
                execution_pid INTEGER
            );
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                test_result_id TEXT,
                artifact_type TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                evidence_state TEXT NOT NULL
            );
        """)
        connection.commit()

    database.initialize()
    with database.connection() as connection:
        run_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(runs)")
        }
        artifact_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(artifacts)")
        }
        result_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(test_results)")
        }
    assert "source_run_id" in run_columns
    assert {"test_node_id", "attempt_id"}.issubset(artifact_columns)
    assert "execution_metadata_json" in result_columns

    SQLiteRunRepository(database).save(make_run())
    artifact = Artifact(
        artifact_id="legacy-art",
        run_id="run-1",
        artifact_type=ArtifactType.SETUP_LOG,
        path="results/setup.log",
        sha256="d" * 64,
        size_bytes=4,
    )
    SQLiteArtifactRepository(database).save(artifact)
    restored = SQLiteArtifactRepository(database).get("legacy-art")
    assert restored is not None
    assert restored.display_name == "setup.log"
    assert restored.sensitivity_class == "INTERNAL"


def test_normalized_baseline_table_is_archived_for_legacy_compatibility(tmp_path):
    database = SQLiteDatabase(tmp_path / "normalized.db")
    with database.connection() as connection:
        connection.executescript("""
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY
            );
            INSERT INTO runs(run_id) VALUES ('run-old');
            CREATE TABLE baselines (
                baseline_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                baseline_run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                device_scope TEXT NOT NULL,
                firmware_major_scope TEXT NOT NULL,
                test_suite_version TEXT NOT NULL,
                lab_class TEXT NOT NULL,
                promoted_by TEXT NOT NULL,
                promoted_at TEXT NOT NULL,
                superseded_by TEXT
            );
            INSERT INTO baselines VALUES (
                'b-old', 'old', 'run-old', 'ACTIVE', '', '', '', '',
                'tester', '2026-09-24T12:00:00+00:00', NULL
            );
        """)
        connection.commit()

    database.initialize()

    with database.connection() as connection:
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "run_baselines" in names
    assert "legacy_baselines_archive" in names
    assert SQLiteBaselineRepository(database).get("b-old") is not None


def test_run_environment_health_round_trip(tmp_path):
    database = make_database(tmp_path)
    repository = SQLiteRunRepository(database)
    expected = make_run()
    expected.environment_health = EnvironmentHealthStatus.DEGRADED

    repository.save(expected)
    restored = repository.get(expected.run_id)

    assert restored is not None
    assert restored.environment_health is EnvironmentHealthStatus.DEGRADED


def test_baseline_replacement_rolls_back_when_supersede_fails(tmp_path):
    import sqlite3

    database = make_database(tmp_path)
    SQLiteRunRepository(database).save(make_run())
    repository = SQLiteBaselineRepository(database)
    original = Baseline(
        baseline_id="baseline-original",
        name="Golden",
        baseline_run_id="run-1",
        status="ACTIVE",
        promoted_by="tester",
        promoted_at=datetime.now(timezone.utc),
    )
    repository.save(original)
    with database.connection() as connection:
        connection.execute(
            """CREATE TRIGGER reject_baseline_supersede
               BEFORE UPDATE ON run_baselines
               BEGIN SELECT RAISE(ABORT, 'forced supersede failure'); END"""
        )
        connection.commit()

    replacement = Baseline(
        baseline_id="baseline-replacement",
        name="Golden",
        baseline_run_id="run-1",
        status="ACTIVE",
        promoted_by="tester",
        promoted_at=datetime.now(timezone.utc),
    )
    with pytest.raises(sqlite3.IntegrityError, match="forced supersede failure"):
        repository.save_replacing_active(replacement)

    assert repository.get("baseline-original").superseded_by is None
    assert repository.get("baseline-replacement") is None
    assert [item.baseline_id for item in repository.list_active()] == ["baseline-original"]


def test_node_owned_artifacts_do_not_leak_between_runs_with_same_pytest_node(tmp_path):
    database = make_database(tmp_path)
    run_one = make_run()
    run_two = Run(
        run_id="run-2",
        display_id="RUN-20261103-120000-0002",
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=("wifi.latency",),
        test_definition_versions={"wifi.latency": "1.0"},
        resolved_config={},
        configuration_hash="b" * 64,
        repository_commit="commit-2",
    )
    SQLiteRunRepository(database).save(run_one)
    SQLiteRunRepository(database).save(run_two)
    attempts = SQLiteAttemptRepository(database)
    attempts.save(Attempt("a-1", "run-1", 1))
    attempts.save(Attempt("a-2", "run-2", 1))
    results = SQLiteTestResultRepository(database)
    for result_id, run_id, attempt_id in (
        ("tr-1", "run-1", "a-1"),
        ("tr-2", "run-2", "a-2"),
    ):
        results.save(
            DomainTestResult(
                test_result_id=result_id,
                run_id=run_id,
                attempt_id=attempt_id,
                test_id="wifi.latency",
                node_id="tests/test_ping.py::test_latency",
                test_version="1.0",
                status=DomainTestResultStatus.PASS,
                criticality=Criticality.BLOCKING,
                severity=Severity.HIGH,
                evidence_state=EvidenceState.COMPLETE,
            )
        )

    artifacts = SQLiteArtifactRepository(database)
    artifacts.save(
        Artifact(
            artifact_id="art-run-two",
            run_id="run-2",
            artifact_type=ArtifactType.PCAP,
            path="results/run-two.pcap",
            sha256="e" * 64,
            size_bytes=100,
            test_node_id="tests/test_ping.py::test_latency",
            attempt_id="a-2",
        )
    )
    artifacts.save(
        Artifact(
            artifact_id="art-global-two",
            run_id="run-2",
            artifact_type=ArtifactType.SETUP_LOG,
            path="results/run-two-setup.log",
            sha256="f" * 64,
            size_bytes=20,
        )
    )
    artifacts.save(
        Artifact(
            artifact_id="art-attempt-two",
            run_id="run-2",
            artifact_type=ArtifactType.COMMAND_OUTPUT,
            path="results/run-two-command.log",
            sha256="a" * 64,
            size_bytes=30,
            attempt_id="a-2",
        )
    )

    assert results.get("tr-1").artifacts == ()
    assert {artifact.artifact_id for artifact in results.get("tr-2").artifacts} == {
        "art-run-two", "art-global-two", "art-attempt-two"
    }


def test_baseline_replacement_rolls_back_when_insert_fails_after_supersede(tmp_path):
    import sqlite3

    database = make_database(tmp_path)
    SQLiteRunRepository(database).save(make_run())
    repository = SQLiteBaselineRepository(database)
    original = Baseline(
        baseline_id="baseline-original",
        name="Golden",
        baseline_run_id="run-1",
        status="ACTIVE",
        promoted_by="tester",
        promoted_at=datetime.now(timezone.utc),
    )
    repository.save(original)
    with database.connection() as connection:
        connection.execute(
            """CREATE TRIGGER reject_baseline_replacement_insert
               BEFORE INSERT ON run_baselines
               WHEN NEW.baseline_id = 'baseline-replacement'
               BEGIN SELECT RAISE(ABORT, 'forced replacement insert failure'); END"""
        )
        connection.commit()

    replacement = Baseline(
        baseline_id="baseline-replacement",
        name="Golden",
        baseline_run_id="run-1",
        status="ACTIVE",
        promoted_by="tester",
        promoted_at=datetime.now(timezone.utc),
    )
    with pytest.raises(sqlite3.IntegrityError, match="forced replacement insert failure"):
        repository.save_replacing_active(replacement)

    assert repository.get("baseline-original").superseded_by is None
    assert repository.get("baseline-replacement") is None
    assert [item.baseline_id for item in repository.list_active()] == ["baseline-original"]
