from __future__ import annotations
import pytest
from datetime import datetime, timedelta, timezone
from lib.domain import ReleaseWaiver, WaiverScope
from lib.services.release_gate import ReleaseGateEvaluator, ReleaseGateInput

def base(**overrides):
    data=dict(run_lifecycle='COMPLETED',run_id='run-1',lab_health='HEALTHY',baseline_available=True,
      required_test_ids=('wifi.latency.threshold',),observed_test_ids=('wifi.latency.threshold',),
      test_statuses={'wifi.latency.threshold':'PASS'},evidence_states={'wifi.latency.threshold':'NOT_REQUIRED'},
      regression_classifications={'wifi.latency.threshold':'UNCHANGED'})
    data.update(overrides); return ReleaseGateInput(**data)

def test_accepts_clean_run(): assert ReleaseGateEvaluator().evaluate(base()).accepted
def test_rejects_no_baseline(): assert not ReleaseGateEvaluator().evaluate(base(baseline_available=False)).accepted
def test_rejects_missing_test_and_invalid_evidence():
    d=ReleaseGateEvaluator().evaluate(base(observed_test_ids=(),test_statuses={},evidence_states={}))
    codes={x.code for x in d.issues}; assert {'MISSING_REQUIRED_TEST','INVALID_REQUIRED_EVIDENCE'} <= codes
def test_rejects_regression_and_failed_test():
    d=ReleaseGateEvaluator().evaluate(base(test_statuses={'wifi.latency.threshold':'FAIL'},regression_classifications={'wifi.latency.threshold':'REGRESSION'}))
    codes={x.code for x in d.issues}; assert {'DISALLOWED_REGRESSION_CLASS','NON_PASSING_TEST'} <= codes
def test_rejects_unhealthy_or_incomplete_run():
    d=ReleaseGateEvaluator().evaluate(base(run_lifecycle='FAILED',lab_health='FAILED')); codes={x.code for x in d.issues}; assert {'RUN_NOT_COMPLETED','LAB_NOT_HEALTHY'} <= codes
def test_regression_selection_boundary_preserves_semantic_ids():
    from lib.domain import Run
    from lib.services import RegressionIntelligenceService, TestRegistry
    run = Run(
        'run', 'run', 'v1.0', 'lab-1', 'Full',
        ('wifi.latency.threshold', 'tests/test_ping.py::test_latency_within_threshold'),
        {'wifi.latency.threshold': '1.0', 'tests/test_ping.py::test_latency_within_threshold': '1.0'},
        {}, 'cfg', 'commit',
    )
    service = RegressionIntelligenceService(run_service=None, test_registry=TestRegistry.default())
    assert service._selected_test_ids(run) == ('wifi.latency.threshold',)
def test_waiver_scope_cannot_cross_issue_boundary():
    test_waiver = ReleaseWaiver(
        waiver_id="w-test",
        scope=WaiverScope.TEST,
        target_id="*",
        issue_code="NO_BASELINE",
        reason="test-only exception",
        created_by="admin",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    decision = ReleaseGateEvaluator().evaluate(
        base(baseline_available=False, waivers=(test_waiver,))
    )
    assert not decision.accepted
    assert any(issue.code == "NO_BASELINE" for issue in decision.issues)


def test_run_scoped_waiver_matches_only_the_selected_run():
    waiver = ReleaseWaiver(
        waiver_id="w-run",
        scope=WaiverScope.RUN,
        target_id="run-1",
        issue_code="RUN_NOT_COMPLETED",
        reason="approved run exception",
        created_by="admin",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    accepted = ReleaseGateEvaluator().evaluate(
        base(run_lifecycle="FAILED", waivers=(waiver,))
    )
    assert accepted.accepted

    rejected = ReleaseGateEvaluator().evaluate(
        base(run_lifecycle="FAILED", run_id="run-2", waivers=(waiver,))
    )
    assert not rejected.accepted
    assert any(issue.code == "RUN_NOT_COMPLETED" for issue in rejected.issues)

