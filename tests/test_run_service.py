from datetime import datetime, timezone

import pytest

from lib.domain import EnvironmentHealthStatus, RunLifecycle
from lib.services import RunService, generate_ulid, redact_configuration
from lib.repositories import (
    RepositoryConflictError,
    SQLiteAttemptRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
)

def make_service(tmp_path, ids):
    database = SQLiteDatabase(tmp_path / "run.db")
    return RunService(
        SQLiteRunRepository(database),
        SQLiteAttemptRepository(database),
        SQLiteEventRepository(database),
        SQLiteTestResultRepository(database),
        clock=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        id_generator=iter(ids).__next__,
    ), database

def test_ulid_shape():
    value = generate_ulid(datetime(2026, 9, 24, tzinfo=timezone.utc))
    assert len(value) == 26
    assert all(ch in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for ch in value)

def test_configuration_redacts_secrets():
    source = {"wifi": {"password": "secret"}, "nested": [{"api_token": "x"}]}
    result = redact_configuration(source)
    assert result["wifi"]["password"] == "<redacted>"
    assert result["nested"][0]["api_token"] == "<redacted>"

def test_create_start_complete_run_lifecycle(tmp_path):
    service, database = make_service(
        tmp_path,
        [
            "01RUN00000000000000000000",
            "01ATTEMPT0000000000000000",
            "01EVENT000000000000000001",
            "01EVENT000000000000000002",
            "01EVENT000000000000000003",
            "01EVENT000000000000000004",
            "01EVENT000000000000000005",
            "01EVENT000000000000000006",
        ],
    )
    database.initialize()
    run, attempt = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=["wifi.test"],
        test_definition_versions={"wifi.test": "1.0"},
        resolved_config={"password": "secret", "threshold": 5},
        repository_commit="abc",
    )

    assert run.lifecycle is RunLifecycle.QUEUED
    assert attempt.number == 1
    assert run.resolved_config["password"] == "<redacted>"

    service.start_run(run.run_id)
    started = SQLiteRunRepository(database).get(run.run_id)
    assert started is not None
    assert started.lifecycle is RunLifecycle.RUNNING

    service.complete_run(run.run_id)
    completed = SQLiteRunRepository(database).get(run.run_id)
    assert completed is not None
    assert completed.lifecycle is RunLifecycle.COMPLETED
    assert completed.completed_at is not None

def test_invalid_transition_is_rejected(tmp_path):
    service, database = make_service(
        tmp_path,
        [
            "01RUN00000000000000000000",
            "01ATTEMPT0000000000000000",
            "01EVENT000000000000000001",
            "01EVENT000000000000000002",
            "01EVENT000000000000000003",
            "01EVENT000000000000000004",
            "01EVENT000000000000000005",
        ],
    )
    database.initialize()
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Full",
        selected_tests=["wifi.test"],
        test_definition_versions={"wifi.test": "1.0"},
        resolved_config={},
        repository_commit="abc",
    )
    with pytest.raises(Exception):
        service.complete_run(run.run_id)


def test_product_failure_sets_rejected_business_outcome(tmp_path):
    service, database = make_service(
        tmp_path,
        [
            "01RUN00000000000000000000",
            "01ATTEMPT0000000000000000",
            "01EVENT000000000000000001",
            "01EVENT000000000000000002",
            "01EVENT000000000000000003",
            "01EVENT000000000000000004",
            "01EVENT000000000000000005",
        ],
    )
    database.initialize()
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Full",
        selected_tests=["wifi.test"],
        test_definition_versions={"wifi.test": "1.0"},
        resolved_config={},
        repository_commit="abc",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    failed = service.fail_run(run.run_id, "assertion failed")
    assert failed.lifecycle is RunLifecycle.FAILED
    assert failed.outcome.value == "REJECTED"


def test_record_test_result_persists_samples(tmp_path):
    service, database = make_service(
        tmp_path,
        [
            "01RUN00000000000000000000",
            "01ATTEMPT0000000000000000",
            "01EVENT000000000000000001",
            "01EVENT000000000000000002",
            "01RESULT000000000000000001",
            "01EVENT000000000000000003",
        ],
    )
    database.initialize()
    run, attempt = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Performance",
        selected_tests=["wifi.latency"],
        test_definition_versions={"wifi.latency": "1.0"},
        resolved_config={},
        repository_commit="abc",
    )
    from lib.domain import Metric, Sample, TestResultStatus
    from lib.repositories import SQLiteTestResultRepository

    service.record_test_result(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id="wifi.latency",
        node_id="tests/test_ping.py::test_latency",
        status=TestResultStatus.PASS,
        metrics=(Metric(name="latency", unit="ms", samples=(Sample(value=10.0), Sample(value=12.0, warmup=True))),),
    )
    result = SQLiteTestResultRepository(database).list_for_attempt(attempt.attempt_id)
    assert len(result) == 1
    assert [sample.value for sample in result[0].metrics[0].samples] == [10.0, 12.0]


def test_health_gated_run_lifecycle(tmp_path):
    service, database = make_service(
        tmp_path,
        [
            "01RUN00000000000000000000",
            "01ATTEMPT0000000000000000",
            "01EVENT000000000000000001",
            "01EVENT000000000000000002",
            "01EVENT000000000000000003",
            "01EVENT000000000000000004",
            "01EVENT000000000000000005",
            "01EVENT000000000000000006",
        ],
    )
    database.initialize()
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=["wifi.test"],
        test_definition_versions={"wifi.test": "1.0"},
        resolved_config={},
        repository_commit="abc",
    )

    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.DEGRADED)
    service.start_run_after_health(run.run_id)

    restored = SQLiteRunRepository(database).get(run.run_id)
    assert restored is not None
    assert restored.lifecycle is RunLifecycle.RUNNING
    assert restored.environment_health is EnvironmentHealthStatus.DEGRADED
