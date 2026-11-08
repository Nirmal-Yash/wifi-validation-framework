import pytest
from lib.domain import (
    BusinessOutcome, Criticality, DomainValidationError, EnvironmentHealthStatus,
    EvidenceState, Metric, Sample, Severity, TestResultStatus,
)
from lib.repositories import SQLiteDatabase
from lib.services import RunService


NODE_ID = "tests/test_ping.py::test_latency_within_threshold"
TEST_ID = "wifi.latency.threshold"


def ready_service(tmp_path):
    return RunService.from_sqlite(SQLiteDatabase(tmp_path / "baseline.db"))


def completed_latency_run(service, *, samples):
    run, attempt = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Performance",
        selected_tests=[NODE_ID],
        test_definition_versions={NODE_ID: "1.0"},
        resolved_config={"device_id": "client_vm"},
        repository_commit="abc",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    service.record_test_result(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id=TEST_ID,
        node_id=NODE_ID,
        status=TestResultStatus.PASS,
        criticality=Criticality.BLOCKING,
        severity=Severity.MEDIUM,
        evidence_state=EvidenceState.NOT_REQUIRED,
        metrics=(Metric(name="latency", unit="ms", samples=tuple(samples), authoritative=True),),
    )
    service.complete_run(run.run_id)
    return run


def test_baseline_promotion_requires_eligible_authoritative_samples(tmp_path):
    service = ready_service(tmp_path)
    run = completed_latency_run(service, samples=[Sample(value=12.0, warmup=True)])

    with pytest.raises(DomainValidationError, match="authoritative measurement policy"):
        service.promote_baseline(run.run_id, name="Golden", promoted_by="owner")


def test_baseline_promotion_uses_latest_attempt_and_supersedes_atomically(tmp_path):
    service = ready_service(tmp_path)
    first = completed_latency_run(service, samples=[Sample(value=12.0), Sample(value=12.5), Sample(value=11.5)])
    original = service.promote_baseline(first.run_id, name="Golden", promoted_by="owner")

    second = completed_latency_run(service, samples=[Sample(value=10.0), Sample(value=11.0), Sample(value=10.5)])
    replacement = service.promote_baseline(second.run_id, name="Golden", promoted_by="owner")

    stored_original = service.baseline_repository.get(original.baseline_id)
    assert stored_original.superseded_by == replacement.baseline_id
    assert [item.baseline_id for item in service.baseline_repository.list_active()] == [replacement.baseline_id]


def test_baseline_promotion_rejects_stale_validated_outcome_for_incomplete_test_set(tmp_path):
    service = ready_service(tmp_path)
    run, attempt = service.create_run(
        firmware_version="v1.0", lab_id="lab-1", validation_profile="Smoke",
        selected_tests=[NODE_ID, "tests/test_ping.py::test_ping_success"],
        test_definition_versions={NODE_ID: "1.0", "tests/test_ping.py::test_ping_success": "1.0"},
        resolved_config={}, repository_commit="abc",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    service.record_test_result(
        run_id=run.run_id, attempt_id=attempt.attempt_id, test_id=TEST_ID,
        node_id=NODE_ID, status=TestResultStatus.PASS, criticality=Criticality.BLOCKING,
        severity=Severity.MEDIUM, evidence_state=EvidenceState.NOT_REQUIRED,
    )
    service.complete_run(run.run_id)

    # Simulate a stale/corrupt persisted outcome to verify promotion independently
    # rechecks selected-test completeness instead of trusting the Run summary.
    persisted = service.run_repository.get(run.run_id)
    persisted.outcome = BusinessOutcome.VALIDATED
    service.run_repository.update(persisted)

    with pytest.raises(
        DomainValidationError,
        match="does not match currently persisted TestResult/evidence facts",
    ):
        service.promote_baseline(run.run_id, name="Golden", promoted_by="owner")


def test_baseline_promotion_rejects_missing_declared_decision_metric(tmp_path):
    service = ready_service(tmp_path)
    run, attempt = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Performance",
        selected_tests=[NODE_ID],
        test_definition_versions={NODE_ID: "1.0"},
        resolved_config={},
        repository_commit="abc",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    service.record_test_result(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id=TEST_ID,
        node_id=NODE_ID,
        status=TestResultStatus.PASS,
        criticality=Criticality.BLOCKING,
        severity=Severity.MEDIUM,
        evidence_state=EvidenceState.NOT_REQUIRED,
        metrics=(),
    )
    service.complete_run(run.run_id)

    with pytest.raises(DomainValidationError, match="decision metric missing"):
        service.promote_baseline(run.run_id, name="Golden", promoted_by="owner")
