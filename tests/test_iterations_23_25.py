from datetime import datetime, timedelta, timezone

from lib.domain import (
    Criticality,
    EvidenceState,
    FailureClass,
    ReleaseWaiver,
    RegressionClass,
    RunLifecycle,
    TestResultStatus,
    WaiverScope,
)
from lib.repositories import SQLiteDatabase
from lib.services import RunService
from lib.services.release_gate import ReleaseGateEvaluator, ReleaseGateInput


def _service(tmp_path):
    return RunService.from_sqlite(SQLiteDatabase(tmp_path / "runner.db"))


def test_failure_class_is_persisted_for_cancel(tmp_path):
    service = _service(tmp_path)
    run, _ = service.create_run(
        firmware_version="v1.0",
        lab_id="lab",
        validation_profile="Full",
        selected_tests=["t"],
        test_definition_versions={"t": "1.0"},
        resolved_config={},
        repository_commit="abc",
    )
    service.cancel_run(run.run_id, actor="tester", reason="operator requested stop")
    stored = service.run_repository.get(run.run_id)
    assert stored.lifecycle is RunLifecycle.CANCELLED
    assert stored.failure_class is FailureClass.CANCELLED
    assert stored.failure_reason == "tester: operator requested stop"


def test_completed_run_can_be_promoted_to_baseline(tmp_path):
    service = _service(tmp_path)
    run, attempt = service.create_run(
        firmware_version="v1.0",
        lab_id="lab",
        validation_profile="Full",
        selected_tests=["t"],
        test_definition_versions={"t": "1.0"},
        resolved_config={"device_id": "client_vm"},
        repository_commit="abc",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id, __import__("lib.domain", fromlist=["EnvironmentHealthStatus"]).EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    service.record_test_result(
        run_id=run.run_id,
        attempt_id=attempt.attempt_id,
        test_id="t",
        node_id="tests/test_example.py::test_example",
        status=TestResultStatus.PASS,
        criticality=Criticality.BLOCKING,
        evidence_state=EvidenceState.COMPLETE,
    )
    service.complete_run(run.run_id)
    baseline = service.promote_baseline(
        run.run_id,
        name="Golden v1.0",
        promoted_by="admin",
    )
    assert baseline.status == "ACTIVE"
    assert baseline.baseline_run_id == run.run_id


def test_release_gate_uses_active_scope_waiver():
    waiver = ReleaseWaiver(
        waiver_id="w1",
        scope=WaiverScope.TEST,
        target_id="t1",
        issue_code="NON_PASSING_TEST",
        reason="approved exception",
        created_by="admin",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    decision = ReleaseGateEvaluator().evaluate(
        ReleaseGateInput(
            run_lifecycle="COMPLETED",
            lab_health="HEALTHY",
            baseline_available=True,
            required_test_ids=("t1",),
            observed_test_ids=("t1",),
            test_statuses={"t1": "FAIL"},
            evidence_states={"t1": "COMPLETE"},
            regression_classifications={"t1": RegressionClass.UNCHANGED.value},
            waivers=(waiver,),
        )
    )
    assert decision.accepted


def test_release_gate_remains_fail_closed_without_waiver():
    decision = ReleaseGateEvaluator().evaluate(
        ReleaseGateInput(
            run_lifecycle="COMPLETED",
            lab_health="HEALTHY",
            baseline_available=True,
            required_test_ids=("t1",),
            observed_test_ids=("t1",),
            test_statuses={"t1": "FAIL"},
            evidence_states={"t1": "COMPLETE"},
            regression_classifications={"t1": RegressionClass.UNCHANGED.value},
        )
    )
    assert not decision.accepted
    assert any(issue.code == "NON_PASSING_TEST" for issue in decision.issues)
