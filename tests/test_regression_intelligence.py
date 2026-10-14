from lib.domain import Attempt, Criticality, EvidenceState, Metric, Run, Severity, Sample, TestResult, TestResultStatus
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
    return Run(run_id, run_id, "v1.0", "lab-1", "Performance", ("wifi.latency.threshold",), {"wifi.latency.threshold":"1.0"}, {"regression":{"thresholds":{"wifi.latency.threshold":{"latency":10}}}}, "cfg", "commit")

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
    bm=Metric("latency","ms",(Sample(10),Sample(10)))
    cm=Metric("latency","ms",(Sample(12),Sample(12)))
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
