from dataclasses import replace
import pytest

from lib.domain import Attempt, Criticality, EnvironmentHealthStatus, EvidenceState, Metric, Run, RunLifecycle, Severity, Sample, TestResult, TestResultStatus
from lib.services import RegressionIntelligenceService, RunService, TestRegistry

class R:
    def __init__(self): self.items={}
    def get(self,k): return self.items.get(k)
    def save(self,x): self.items[x.run_id]=x
    def update(self,x): self.items[x.run_id]=x

class A:
    def __init__(self): self.items={}
    def save(self,x): self.items[x.attempt_id]=x
    def update(self,x): self.items[x.attempt_id]=x
    def get(self,k): return self.items.get(k)
    def list_for_run(self,k): return sorted([x for x in self.items.values() if x.run_id==k], key=lambda x:x.number)

class T:
    def __init__(self): self.items={}
    def save(self,x): self.items[x.test_result_id]=x
    def get(self,k): return self.items.get(k)
    def list_for_attempt(self,k): return [x for x in self.items.values() if x.attempt_id==k]

class E:
    def append(self, event): pass

def run(run_id):
    return Run(
        run_id, run_id, "v1.0", "lab-1", "Performance",
        ("wifi.latency.threshold",), {"wifi.latency.threshold":"1.0"},
        {"regression":{"thresholds":{"wifi.latency.threshold":{"latency":10}}}},
        "cfg", "commit", lifecycle=RunLifecycle.COMPLETED,
        environment_health=EnvironmentHealthStatus.HEALTHY,
    )

def result(run_id, attempt_id, status, metric=None, evidence=EvidenceState.NOT_REQUIRED):
    metrics=(metric,) if metric else ()
    return TestResult(run_id+"-result", run_id, attempt_id, "wifi.latency.threshold", "node::latency", "1.0", status, Criticality.BLOCKING, Severity.HIGH, evidence, metrics)

def service(base_run, current_run, base_results, current_results):
    rr, ar, tr, er = R(), A(), T(), E()
    rr.items={base_run.run_id:base_run,current_run.run_id:current_run}
    for run_id, items in ((base_run.run_id,base_results),(current_run.run_id,current_results)):
        attempt=A()
        actual=Attempt(run_id+"-attempt",run_id,1)
        ar.save(actual)
        for item in items: tr.save(item)
    return RegressionIntelligenceService(run_service=RunService(rr,ar,er,tr), test_registry=TestRegistry.default())

def test_pass_fail_and_fail_pass():
    base=run("base"); current=run("current")
    svc=service(base,current,[result("base","base-attempt",TestResultStatus.PASS)],[result("current","current-attempt",TestResultStatus.FAIL)])
    report=svc.compare_runs(baseline_run_id="base",current_run_id="current",baseline_environment_class="VIRTUAL_WIFI",current_environment_class="VIRTUAL_WIFI")
    assert report.assessments[0].classification.value=="REGRESSION"

def test_metric_policy_threshold_and_improvement():
    base=run("base"); current=run("current")
    bm=Metric("latency","ms",(Sample(10),Sample(10),Sample(10)))
    cm=Metric("latency","ms",(Sample(12),Sample(12),Sample(12)))
    svc=service(base,current,[result("base","base-attempt",TestResultStatus.PASS,bm)],[result("current","current-attempt",TestResultStatus.PASS,cm)])
    report=svc.compare_runs(baseline_run_id="base",current_run_id="current",baseline_environment_class="VIRTUAL_WIFI",current_environment_class="VIRTUAL_WIFI")
    comp=report.assessments[0].metric_comparisons[0]
    assert report.assessments[0].classification.value=="SOFT_REGRESSION"
    assert comp.threshold_pct==10
    assert comp.delta_pct==20.0

def test_environment_mismatch_and_missing_current_are_not_guessed():
    base=run("base"); current=run("current")
    svc=service(base,current,[result("base","base-attempt",TestResultStatus.PASS)],[result("current","current-attempt",TestResultStatus.PASS)])
    report=svc.compare_runs(baseline_run_id="base",current_run_id="current",baseline_environment_class="VIRTUAL_WIFI",current_environment_class="PHYSICAL_WIFI")
    assert report.assessments[0].classification.value=="NO_BASELINE"
    report=service(base,current,[result("base","base-attempt",TestResultStatus.PASS)],[]).compare_runs(baseline_run_id="base",current_run_id="current",baseline_environment_class="VIRTUAL_WIFI",current_environment_class="VIRTUAL_WIFI")
    assert report.assessments[0].classification.value=="UNVALIDATED"

def test_invalid_evidence_and_flaky_history():
    base=run("base"); current=run("current")
    cur=result("current","current-attempt",TestResultStatus.UNVALIDATED,Metric("latency","ms",(Sample(10),)),EvidenceState.INVALID)
    svc=service(base,current,[result("base","base-attempt",TestResultStatus.PASS)],[cur])
    report=svc.compare_runs(baseline_run_id="base",current_run_id="current",baseline_environment_class="VIRTUAL_WIFI",current_environment_class="VIRTUAL_WIFI",flaky_history={"wifi.latency.threshold":["PASS","FAIL","PASS"]})
    assert report.assessments[0].classification.value=="UNVALIDATED"
    assert report.assessments[0].flaky_history.flagged is True



def test_baseline_must_be_completed_and_healthy():
    base = replace(run("base"), lifecycle=RunLifecycle.RUNNING)
    current = run("current")
    svc = service(base, current, [result("base","base-attempt",TestResultStatus.PASS)],
                  [result("current","current-attempt",TestResultStatus.PASS)])
    report = svc.compare_runs(
        baseline_run_id="base", current_run_id="current",
        baseline_environment_class="VIRTUAL_WIFI", current_environment_class="VIRTUAL_WIFI",
    )
    assert report.comparability.value == "INCOMPATIBLE"
    assert report.assessments[0].classification.value == "NO_BASELINE"

    base = replace(run("base"), environment_health=EnvironmentHealthStatus.FAILED)
    svc = service(base, current, [result("base","base-attempt",TestResultStatus.PASS)],
                  [result("current","current-attempt",TestResultStatus.PASS)])
    report = svc.compare_runs(
        baseline_run_id="base", current_run_id="current",
        baseline_environment_class="VIRTUAL_WIFI", current_environment_class="VIRTUAL_WIFI",
    )
    assert report.comparability.value == "INCOMPATIBLE"


def test_missing_baseline_test_result_is_not_classified_as_new_pass():
    base = run("base")
    current = run("current")
    svc = service(
        base,
        current,
        [],
        [result("current", "current-attempt", TestResultStatus.PASS)],
    )
    report = svc.compare_runs(
        baseline_run_id="base",
        current_run_id="current",
        baseline_environment_class="VIRTUAL_WIFI",
        current_environment_class="VIRTUAL_WIFI",
    )
    assessment = report.assessments[0]
    assert report.comparability.value == "COMPARABLE"
    assert assessment.classification.value == "NO_BASELINE"
    assert "no persisted TestResult" in assessment.reason


def test_invalid_baseline_evidence_cannot_anchor_regression():
    base = run("base")
    current = run("current")
    invalid = result("base","base-attempt",TestResultStatus.FAIL,evidence=EvidenceState.INVALID)
    svc = service(base,current,[invalid],[result("current","current-attempt",TestResultStatus.PASS)])
    report = svc.compare_runs(
        baseline_run_id="base",current_run_id="current",
        baseline_environment_class="VIRTUAL_WIFI",current_environment_class="VIRTUAL_WIFI",
    )
    assert report.assessments[0].classification.value == "NO_BASELINE"
    assert "baseline evidence" in report.assessments[0].reason


def test_missing_registered_decision_metric_is_unvalidated():
    base = run("base")
    current = run("current")
    svc = service(
        base,
        current,
        [result("base", "base-attempt", TestResultStatus.PASS)],
        [result("current", "current-attempt", TestResultStatus.PASS)],
    )
    report = svc.compare_runs(
        baseline_run_id="base",
        current_run_id="current",
        baseline_environment_class="VIRTUAL_WIFI",
        current_environment_class="VIRTUAL_WIFI",
    )
    assessment = report.assessments[0]
    assert assessment.classification.value == "UNVALIDATED"
    assert assessment.metric_comparisons[0].classification.value == "UNVALIDATED"
    assert assessment.metric_comparisons[0].metric_name == "latency"


def test_ping_success_metric_direction_is_higher_is_better():
    svc = RegressionIntelligenceService(run_service=None, test_registry=TestRegistry.default())
    assert svc._metric_direction(run("base"), "wifi.ping.success", "ping_success") == "HIGHER_IS_BETTER"


def test_metric_direction_is_explicit_and_zero_baseline_is_not_guessed():
    from lib.services.regression_intelligence import RegressionIntelligenceError
    assert RegressionIntelligenceService._delta(100, 110, "LOWER_IS_BETTER") == 10.0
    assert RegressionIntelligenceService._delta(100, 110, "HIGHER_IS_BETTER") == -10.0
    assert RegressionIntelligenceService._delta(0, 0, "LOWER_IS_BETTER") == 0.0
    assert RegressionIntelligenceService._delta(0, 1, "LOWER_IS_BETTER") is None
    svc = RegressionIntelligenceService(run_service=None, test_registry=TestRegistry.default())
    with pytest.raises(RegressionIntelligenceError):
        svc._metric_direction(run("base"), "wifi.latency.threshold", "custom_score")


def test_suite_signature_normalizes_semantic_and_pytest_node_selection():
    semantic_run = run("base")
    node_run = Run(
        "node-run", "node-run", "v1.0", "lab-1", "Performance",
        ("tests/test_ping.py::test_latency_within_threshold",),
        {"tests/test_ping.py::test_latency_within_threshold":"1.0"},
        {}, "cfg", "commit", lifecycle=RunLifecycle.COMPLETED,
        environment_health=EnvironmentHealthStatus.HEALTHY,
    )
    svc = RegressionIntelligenceService(run_service=None, test_registry=TestRegistry.default())
    assert svc._suite_signature(semantic_run) == svc._suite_signature(node_run)
