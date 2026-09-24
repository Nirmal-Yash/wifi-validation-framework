import json
from datetime import datetime,timedelta,timezone
from lib.domain import FailureClass,RunLifecycle,EnvironmentHealthStatus
from lib.repositories import SQLiteDatabase
from lib.services import (
    CERTIFICATION_SCENARIOS,CertificationMatrix,FailureInjectionCatalog,
    FailureInjectionHarness,InjectionResult,IdempotencyStore,RetentionService,
    SQLiteBackupService,StaleLockRecovery,CsrfService,validate_https_endpoint,
    RunRecoveryService,AuditIntegrityService,FailureInjectionObservation
)
from lib.services.run_process import RunProcessHandle,RunProcessManager
from lib.services.run_service import RunService

def _service(tmp_path): return RunService.from_sqlite(SQLiteDatabase(tmp_path/"runner.db"))

def _running_service(tmp_path):
    service=_service(tmp_path)
    run,_=service.create_run(firmware_version="v1.0",lab_id="lab",validation_profile="Full",selected_tests=["t"],test_definition_versions={"t":"1.0"},resolved_config={},repository_commit="abc")
    service.begin_lab_health_check(run.run_id);service.record_environment_health(run.run_id,EnvironmentHealthStatus.HEALTHY);service.start_run_after_health(run.run_id)
    return service,run

def test_failure_injection_matrix_is_complete():
    cases=FailureInjectionCatalog.all()
    assert len(cases)==27 and len({c.case_id for c in cases})==27
    assert {"worker_crash","runner_disconnect","command_timeout","artifact_corruption","duplicate_job_request"} <= {c.case_id for c in cases}

def test_failure_injection_harness_always_restores():
    calls=[]
    case=FailureInjectionCatalog.get("dns_failure")
    def inject(_): calls.append("apply")
    def observe(_): calls.append("observe"); return FailureInjectionObservation(case.case_id,InjectionResult.EXPECTED_FAILURE,FailureClass.LAB_FAILED,RunLifecycle.LAB_FAILED,True,True,True,True,True)
    def cleanup(_): calls.append("cleanup")
    result=FailureInjectionHarness().execute(case.case_id,inject=inject,observe=observe,cleanup=cleanup)
    assert result.passed and calls==["apply","observe","cleanup"]

def test_runner_failure_semantics_are_persisted(tmp_path):
    service,run=_running_service(tmp_path)
    stored=service.worker_crashed(run.run_id,"simulated worker loss")
    assert stored.lifecycle is RunLifecycle.ABORTED and stored.failure_class is FailureClass.WORKER_CRASHED
    assert stored.failure_reason=="simulated worker loss"

def test_lab_failure_is_not_product_failure(tmp_path):
    service,run=_running_service(tmp_path)
    stored=service.lab_fail_run(run.run_id,"simulated DHCP service loss")
    assert stored.lifecycle is RunLifecycle.LAB_FAILED and stored.failure_class is FailureClass.LAB_FAILED
    assert stored.outcome.value=="UNVALIDATED"

def test_certification_matrix_has_11_scenarios():
    matrix=CertificationMatrix();assert len(CERTIFICATION_SCENARIOS)==11
    assert matrix.validate_evidence({})==tuple(sorted(s.scenario_id for s in CERTIFICATION_SCENARIOS))

def test_certification_evidence_requires_all_controls():
    matrix=CertificationMatrix();evidence={s.scenario_id:{"controls":list(s.required_controls)} for s in CERTIFICATION_SCENARIOS}
    assert matrix.validate_evidence(evidence)==()

def test_sqlite_backup_restore(tmp_path):
    source=tmp_path/"runner.db";service=_service(tmp_path)
    run,_=service.create_run(firmware_version="v1.0",lab_id="lab",validation_profile="Full",selected_tests=["t"],test_definition_versions={"t":"1.0"},resolved_config={},repository_commit="abc")
    backup=tmp_path/"backup.db";assert SQLiteBackupService().backup(source,backup).integrity_ok
    restored=tmp_path/"restored.db";assert SQLiteBackupService().restore(backup,restored).integrity_ok
    assert RunService.from_sqlite(SQLiteDatabase(restored)).run_repository.get(run.run_id) is not None

def test_retention_prunes_old_files(tmp_path):
    old=tmp_path/"old.log";old.write_text("old");fresh=tmp_path/"fresh.log";fresh.write_text("fresh")
    import os;os.utime(old,(1,1));assert RetentionService().prune(tmp_path,older_than_seconds=60,suffixes=(".log",)).removed_files==1
    assert not old.exists() and fresh.exists()

def test_idempotency_is_durable_and_replay_bound(tmp_path):
    db=SQLiteDatabase(tmp_path/"api.db");store=IdempotencyStore(db)
    record=store.put("/api/v1/runs","request-123","hash-a",{"data":{"process_id":123},"status":"STARTED"},202)
    again=IdempotencyStore(db).get("/api/v1/runs","request-123","hash-a")
    assert again is not None and again.response["status"]=="STARTED" and again.status_code==202
    import pytest
    with pytest.raises(ValueError): IdempotencyStore(db).get("/api/v1/runs","request-123","hash-b")

def test_csrf_and_ssrf_controls():
    session={};token=CsrfService.token(session);assert CsrfService.validate(session,token);assert not CsrfService.validate(session,"wrong")
    import pytest
    with pytest.raises(ValueError): validate_https_endpoint("https://127.0.0.1/sync")

def test_stale_lock_recovery(tmp_path):
    lock=tmp_path/"lab.lock";expired=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    lock.write_text(json.dumps({"resource_id":"lab","owner":"runner:999999:abc","expires_at":expired}))
    assert StaleLockRecovery().recover(tmp_path)==1

def test_run_recovery_classifies_dead_worker(tmp_path):
    service,run=_running_service(tmp_path)
    run.execution_pid=999999;service.run_repository.update(run)
    recovered=RunRecoveryService().recover_orphaned_runs(service)
    assert recovered==(run.run_id,)
    assert service.run_repository.get(run.run_id).failure_class is FailureClass.WORKER_CRASHED

def test_audit_integrity_chain_changes_when_event_changes(tmp_path):
    service,run=_running_service(tmp_path)
    events=service.event_repository.list_for_run(run.run_id)
    digest=AuditIntegrityService.digest(events)
    tampered=list(events);tampered[0]=__import__("lib.domain",fromlist=["LifecycleEvent"]).LifecycleEvent(tampered[0].event_id,tampered[0].run_id,tampered[0].event_type,tampered[0].occurred_at,tampered[0].attempt_id,tampered[0].test_result_id,{"tampered":True})
    assert digest!=AuditIntegrityService.digest(tampered)

def test_run_launch_is_idempotent(tmp_path,monkeypatch):
    import json as _json
    from dashboard.app import create_app
    from lib.security import AuthManager
    monkeypatch.setenv("NETREGRESS_AUTH_REQUIRED","1")
    monkeypatch.setenv("NETREGRESS_AUTH_USERS_JSON",_json.dumps([{"username":"admin","password_hash":AuthManager.password_hash("pw"),"role":"OWNER","projects":["*"]}]))
    monkeypatch.setenv("NETREGRESS_SESSION_SECRET","session-secret")
    calls=[]
    monkeypatch.setattr(RunProcessManager,"start",lambda self,**kwargs:(calls.append(1) or RunProcessHandle(123,("fake","pytest"))))
    client=create_app(tmp_path/"api.db").test_client()
    login=client.post("/api/v1/auth/login",json={"username":"admin","password":"pw"})
    csrf=login.get_json()["data"]["csrf_token"]
    headers={"X-CSRF-Token":csrf,"Idempotency-Key":"request-123"}
    first=client.post("/api/v1/runs",headers=headers,json={"firmware_version":"v1.0","tests":["t"]})
    second=client.post("/api/v1/runs",headers=headers,json={"firmware_version":"v1.0","tests":["t"]})
    assert first.status_code==202 and second.status_code==202 and first.get_json()==second.get_json() and len(calls)==1

def test_security_headers_are_present(tmp_path):
    from dashboard.app import create_app
    client=create_app(tmp_path/"headers.db").test_client()
    response=client.get("/api/v1/health")
    assert response.headers["X-Content-Type-Options"]=="nosniff"
    assert response.headers["X-Frame-Options"]=="DENY"
