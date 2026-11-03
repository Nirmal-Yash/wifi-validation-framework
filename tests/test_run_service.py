from datetime import datetime, timezone

import pytest

from lib.domain import (
    Attempt, BusinessOutcome, Criticality, DomainValidationError,
    EnvironmentHealthStatus, EvidenceState, FailureClass, RunLifecycle,
    Severity, TestResultStatus,
)
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
            "01EVENT000000000000000007",
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
            "01EVENT000000000000000006",
            "01EVENT000000000000000007",
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
            "01EVENT000000000000000006",
            "01EVENT000000000000000007",
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


def _running_run(service, *, selected_tests):
    run, attempt = service.create_run(
        firmware_version="v1.0",
        lab_id="lab-1",
        validation_profile="Smoke",
        selected_tests=selected_tests,
        test_definition_versions={item: "1.0" for item in selected_tests},
        resolved_config={},
        repository_commit="abc",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    return run, attempt


def _record(service, run, attempt, *, test_id, node_id, status, criticality=Criticality.BLOCKING, evidence=EvidenceState.NOT_REQUIRED, failure_class=None):
    return service.record_test_result(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id=test_id,
        node_id=node_id,
        status=status,
        criticality=criticality,
        severity=Severity.HIGH,
        evidence_state=evidence,
        failure_class=failure_class,
    )


def test_business_outcome_uses_only_latest_attempt(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "latest-attempt.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, first = _running_run(service, selected_tests=[selected])
    _record(service, run, first, test_id="wifi.ping.success", node_id=selected, status=TestResultStatus.FAIL)
    second = Attempt("attempt-2", run.run_id, 2)
    service.attempt_repository.save(second)
    _record(service, run, second, test_id="wifi.ping.success", node_id=selected, status=TestResultStatus.PASS)

    completed = service.complete_run(run.run_id)

    assert completed.outcome is BusinessOutcome.VALIDATED


def test_business_outcome_requires_exact_selected_node_set(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "selection.db"))
    selected = [
        "tests/test_ping.py::test_ping_success",
        "tests/test_ping.py::test_latency_within_threshold",
    ]
    run, attempt = _running_run(service, selected_tests=selected)
    _record(service, run, attempt, test_id="wifi.ping.success", node_id=selected[0], status=TestResultStatus.PASS)
    _record(service, run, attempt, test_id="wifi.ping.success", node_id="tests/test_other.py::test_extra", status=TestResultStatus.PASS)

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.UNVALIDATED


def test_business_outcome_rejects_duplicate_result_for_selected_node(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "duplicates.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(service, run, attempt, test_id="wifi.ping.success", node_id=selected, status=TestResultStatus.PASS)
    _record(service, run, attempt, test_id="wifi.ping.success", node_id=selected, status=TestResultStatus.PASS)

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.UNVALIDATED


def test_business_outcome_does_not_accept_blocking_xpass(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "xpass.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(service, run, attempt, test_id="wifi.ping.success", node_id=selected, status=TestResultStatus.XPASS)

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.UNVALIDATED


def test_advisory_skip_is_a_warning_not_a_validated_pass(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "advisory.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(service, run, attempt, test_id="wifi.ping.success", node_id=selected, status=TestResultStatus.SKIPPED, criticality=Criticality.ADVISORY)

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.VALIDATED_WITH_WARNINGS


def test_record_test_result_marks_declared_decision_metric_authoritative(tmp_path):
    from lib.domain import Metric, Sample
    from lib.services import TestRegistry

    registry = TestRegistry.default()
    service = RunService.from_sqlite(
        SQLiteDatabase(tmp_path / "decision-metric.db"), test_registry=registry
    )
    selected = "tests/test_ping.py::test_latency_within_threshold"
    run, attempt = _running_run(service, selected_tests=[selected])

    result = service.record_test_result(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id="wifi.latency.threshold",
        node_id=selected,
        status=TestResultStatus.PASS,
        criticality=Criticality.BLOCKING,
        severity=Severity.MEDIUM,
        evidence_state=EvidenceState.NOT_REQUIRED,
        metrics=(Metric(name="latency", unit="ms", samples=(Sample(value=8.0),)),),
    )

    assert result.metrics[0].authoritative is True


def test_record_test_result_rejects_decision_metric_unit_mismatch(tmp_path):
    from lib.domain import DomainValidationError, Metric, Sample
    from lib.services import TestRegistry

    service = RunService.from_sqlite(
        SQLiteDatabase(tmp_path / "decision-metric-unit.db"),
        test_registry=TestRegistry.default(),
    )
    selected = "tests/test_ping.py::test_latency_within_threshold"
    run, attempt = _running_run(service, selected_tests=[selected])

    with pytest.raises(DomainValidationError, match="decision metric unit mismatch"):
        service.record_test_result(
            run_id=run.run_id,
            attempt_id=attempt.attempt_id,
            test_id="wifi.latency.threshold",
            node_id=selected,
            status=TestResultStatus.PASS,
            criticality=Criticality.BLOCKING,
            severity=Severity.MEDIUM,
            evidence_state=EvidenceState.NOT_REQUIRED,
            metrics=(Metric(name="latency", unit="seconds", samples=(Sample(value=8.0),)),),
        )


def test_advisory_unvalidated_result_makes_run_unvalidated(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "advisory-unvalidated.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(
        service, run, attempt,
        test_id="wifi.ping.success", node_id=selected,
        status=TestResultStatus.UNVALIDATED,
        criticality=Criticality.ADVISORY,
        evidence=EvidenceState.INCOMPLETE,
    )

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.UNVALIDATED


def test_complete_run_cannot_override_unvalidated_persisted_facts(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "outcome-override.db"))
    run, _ = service.create_run(
        firmware_version="v1.0", lab_id="lab-1", validation_profile="Smoke",
        selected_tests=["wifi.ping.success"],
        test_definition_versions={"wifi.ping.success": "1.0"},
        resolved_config={}, repository_commit="abc",
    )

    with pytest.raises(DomainValidationError, match="cannot override persisted"):
        service.complete_run(run.run_id, BusinessOutcome.VALIDATED)


def test_missing_environment_health_cannot_validate_run(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "missing-health.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = service.create_run(
        firmware_version="v1.0", lab_id="lab-1", validation_profile="Smoke",
        selected_tests=[selected],
        test_definition_versions={selected: "1.0"},
        resolved_config={}, repository_commit="abc",
    )
    _record(
        service, run, attempt,
        test_id="wifi.ping.success", node_id=selected,
        status=TestResultStatus.PASS,
    )

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.UNVALIDATED


def test_blocking_error_without_product_classification_is_unvalidated(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "fixture-error.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(
        service, run, attempt,
        test_id="wifi.ping.success", node_id=selected,
        status=TestResultStatus.ERROR,
    )

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.UNVALIDATED


def test_blocking_error_explicitly_classified_as_product_failure_is_rejected(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "product-error.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(
        service, run, attempt,
        test_id="wifi.ping.success", node_id=selected,
        status=TestResultStatus.ERROR,
        failure_class=FailureClass.PRODUCT_FAILED,
    )

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.REJECTED


def test_fail_run_without_classification_uses_persisted_outcome(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "fixture-error-finalize.db"))
    selected = "tests/test_example.py::test_example"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(
        service, run, attempt,
        test_id="wifi.test", node_id=selected,
        status=TestResultStatus.ERROR,
    )

    failed = service.fail_run(run.run_id, "fixture failed", failure_class=None)

    assert failed.lifecycle is RunLifecycle.FAILED
    assert failed.outcome is BusinessOutcome.UNVALIDATED
    assert failed.failure_class is None


def test_fail_run_downgrades_validated_with_warnings_when_process_failed(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "warning-process-failed.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(
        service, run, attempt,
        test_id="wifi.ping.success", node_id=selected,
        status=TestResultStatus.SKIPPED,
        criticality=Criticality.ADVISORY,
    )
    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.VALIDATED_WITH_WARNINGS

    failed = service.fail_run(run.run_id, "pytest process exited non-zero", failure_class=None)

    assert failed.lifecycle is RunLifecycle.FAILED
    assert failed.outcome is BusinessOutcome.UNVALIDATED


def test_retry_run_records_source_lineage_without_mutating_source(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "retry-lineage.db"))
    source, source_attempt = service.create_run(
        firmware_version="v1.0", lab_id="lab-1", validation_profile="Smoke",
        selected_tests=["wifi.test"], test_definition_versions={"wifi.test": "1.0"},
        resolved_config={}, repository_commit="abc",
    )
    from lib.domain import Criticality, Severity
    service.begin_lab_health_check(source.run_id)
    service.record_environment_health(source.run_id, EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(source.run_id)
    service.record_test_result(
        run_id=source.run_id,
        attempt_id=source_attempt.attempt_id,
        test_id="wifi.test",
        node_id="tests/test_example.py::test_example",
        status=TestResultStatus.PASS,
        criticality=Criticality.BLOCKING,
        severity=Severity.HIGH,
        evidence_state=EvidenceState.NOT_REQUIRED,
    )
    service.complete_run(source.run_id)
    retry, retry_attempt = service.create_run(
        firmware_version=source.firmware_version,
        lab_id=source.lab_id,
        validation_profile=source.validation_profile,
        selected_tests=list(source.selected_tests),
        test_definition_versions=source.test_definition_versions,
        resolved_config=source.resolved_config,
        repository_commit="def",
        source_run_id=source.run_id,
    )

    stored_source = service.run_repository.get(source.run_id)
    stored_retry = service.run_repository.get(retry.run_id)
    assert stored_source.source_run_id is None
    assert stored_retry.source_run_id == source.run_id
    assert source_attempt.number == 1
    assert retry_attempt.number == 1
    assert [item.attempt_id for item in service.attempt_repository.list_for_run(source.run_id)] == [source_attempt.attempt_id]


def test_create_retry_run_rejects_unknown_source_run(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "retry-lineage-missing.db"))
    with pytest.raises(DomainValidationError, match="source Run does not exist"):
        service.create_run(
            firmware_version="v1.0", lab_id="lab-1", validation_profile="Smoke",
            selected_tests=["wifi.test"], test_definition_versions={"wifi.test": "1.0"},
            resolved_config={}, repository_commit="abc", source_run_id="missing-run",
        )


def test_create_retry_run_rejects_nonterminal_source_run(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "retry-lineage-active.db"))
    source, _ = service.create_run(
        firmware_version="v1.0", lab_id="lab-1", validation_profile="Smoke",
        selected_tests=["wifi.test"], test_definition_versions={"wifi.test": "1.0"},
        resolved_config={}, repository_commit="abc",
    )

    with pytest.raises(DomainValidationError, match="only terminal Runs"):
        service.create_run(
            firmware_version="v1.0", lab_id="lab-1", validation_profile="Smoke",
            selected_tests=["wifi.test"], test_definition_versions={"wifi.test": "1.0"},
            resolved_config={}, repository_commit="def", source_run_id=source.run_id,
        )


def test_blocked_blocking_test_keeps_rejected_outcome(tmp_path):
    service = RunService.from_sqlite(SQLiteDatabase(tmp_path / "blocked-result.db"))
    selected = "tests/test_ping.py::test_ping_success"
    run, attempt = _running_run(service, selected_tests=[selected])
    _record(
        service, run, attempt,
        test_id="wifi.ping.success", node_id=selected,
        status=TestResultStatus.BLOCKED,
    )

    assert service.derive_business_outcome(run.run_id) is BusinessOutcome.REJECTED
