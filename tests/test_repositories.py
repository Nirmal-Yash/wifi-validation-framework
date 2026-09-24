from datetime import datetime, timezone

import pytest

from lib.domain import (
    Artifact,
    ArtifactType,
    Attempt,
    Baseline,
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
    )

    SQLiteTestResultRepository(database).save(result)
    restored = SQLiteTestResultRepository(database).get("tr-1")

    assert restored is not None
    assert restored.metrics[0].samples[0].value == 42.5
    assert restored.metrics[0].samples[0].metadata == {"source": "test"}
    assert restored.artifacts[0] == artifact


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
