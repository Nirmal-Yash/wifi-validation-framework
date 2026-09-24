from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Any,Callable
from functools import wraps
from flask import Blueprint,jsonify,request,session,send_file
from lib.repositories import SQLiteDatabase
from lib.services import RunProcessManager, WaiverService, FirmwareOperationService, IdempotencyStore, CsrfService, LoginRateLimiter, RequestSecurityError, resolve_confined_path
from lib.adapters import DeviceProfile, OpenWrtDeviceAdapter, SSHFirmwareAdapter, VirtualLinuxDeviceAdapter
from lib.connector import load_devices, ConnectionPool
from lib.services.command_security import CommandSecurityPolicy, SecureCommandRunner
from lib.services.command_runner import NetmikoRunner
from lib.security import AuthManager,AuthConfigurationError,AuthenticatedUser,Role
from lib.domain import WaiverScope
from .query import DashboardQueryError,DashboardQueryService

def create_api_blueprint(query:DashboardQueryService,auth_manager:AuthManager|None=None)->Blueprint:
    api=Blueprint("api_v1",__name__,url_prefix="/api/v1"); auth=auth_manager or AuthManager.from_env()
    idempotency_store=IdempotencyStore(query.database)
    login_limiter=LoginRateLimiter()
    def ok(data:Any): return jsonify({"data":data})
    def error(code,message,status,details=None): return jsonify({"error":{"code":code,"message":message,"details":details or {}}}),status
    def guarded(fn):
        try:return fn()
        except DashboardQueryError as exc:return error("NOT_FOUND",str(exc),404)
        except (ValueError,TypeError) as exc:return error("INVALID_REQUEST",str(exc),400)
        except Exception as exc:return error("INTERNAL_ERROR","Dashboard query failed",500,{"type":type(exc).__name__})
    def require(action="view",project_id=None):
        raw=session.get("netregress_user")
        if raw is None:
            if auth.required:return error("UNAUTHENTICATED","authentication required",401)
            actor=AuthenticatedUser("local",Role.OWNER,("*",))
        else:
            try:actor=AuthenticatedUser(raw["username"],Role(raw["role"]),tuple(raw.get("projects") or ("*",)))
            except (KeyError,ValueError):session.clear();return error("UNAUTHENTICATED","invalid session",401)
            if request.method in {"POST","PUT","PATCH","DELETE"} and request.path != "/api/v1/auth/login" and not CsrfService.validate(session,request.headers.get("X-CSRF-Token")):
                return error("CSRF_REQUIRED","valid X-CSRF-Token header required for browser state changes",403)
        return None if auth.authorize(actor,action,project_id) else error("FORBIDDEN","authorization denied",403)
    @api.get("/health")
    def health():return ok({"status":"ok"})
    @api.get("/readiness")
    def readiness():
        try:query.database.initialize();return ok({"status":"ready"})
        except Exception as exc:return error("NOT_READY","database is not ready",503,{"type":type(exc).__name__})
    @api.post("/auth/login")
    def login():
        payload=request.get_json(silent=True) or {}
        username=str(payload.get("username","")).strip()
        if not login_limiter.allow(f"{request.remote_addr or 'unknown'}:{username}"):
            return error("RATE_LIMITED","too many login attempts",429)
        try:auth.require_configured()
        except AuthConfigurationError as exc:return error("AUTH_NOT_CONFIGURED",str(exc),503)
        user=auth.authenticate(username,str(payload.get("password","")))
        if user is None:return error("INVALID_CREDENTIALS","invalid credentials",401)
        session.clear();session["netregress_user"]={"username":user.username,"role":user.role.value,"projects":list(user.projects)};session.permanent=True
        return ok({**session["netregress_user"],"csrf_token":CsrfService.token(session)})
    @api.get("/auth/csrf")
    def csrf():
        denied=require("view")
        if denied is not None:return denied
        return ok({"csrf_token":CsrfService.token(session)})
    @api.post("/auth/logout")
    def logout():
        denied=require("view")
        if denied is not None:return denied
        session.clear();return ok({"logged_out":True})
    @api.get("/auth/me")
    def me():
        raw=session.get("netregress_user");return ok(raw) if raw else error("UNAUTHENTICATED","authentication required",401)
    def protected(fn:Callable):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            denied=require("view");return denied if denied is not None else fn(*args,**kwargs)
        return wrapper
    @api.post("/runs")
    def launch_run():
        denied=require("execute")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        firmware=str(payload.get("firmware_version","v1.0"))
        tests=tuple(str(x) for x in (payload.get("tests") or ()))
        try:key=IdempotencyStore.validate_key(request.headers.get("Idempotency-Key",""))
        except RequestSecurityError as exc:return error("INVALID_IDEMPOTENCY_KEY",str(exc),400)
        request_hash=hashlib.sha256(json.dumps({"firmware_version":firmware,"tests":list(tests)},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        try:
            cached=idempotency_store.get("/api/v1/runs",key,request_hash)
        except RequestSecurityError as exc:return error("IDEMPOTENCY_KEY_REUSE",str(exc),409)
        if cached is not None:return jsonify(cached.response),cached.status_code
        manager=RunProcessManager(Path(__file__).resolve().parents[1])
        handle=manager.start(tests=tests or None,firmware_version=firmware,env={"NETREGRESS_RUN_REQUESTED_BY":session.get("netregress_user",{}).get("username","local")})
        response={"data":{"process_id":handle.pid,"command":list(handle.command),"status":"STARTED"}}
        idempotency_store.put("/api/v1/runs",key,request_hash,response,202)
        return jsonify(response),202

    @api.get("/runs")
    @protected
    def runs():return guarded(lambda:ok(query.runs(firmware=request.args.get("firmware"),lab=request.args.get("lab"),profile=request.args.get("profile"),status=request.args.get("status"),outcome=request.args.get("outcome"),page=int(request.args.get("page","1")),limit=int(request.args.get("limit","50")))))
    @api.post("/runs/<run_id>/cancel")
    def cancel_run(run_id):
        denied=require("execute")
        if denied is not None: return denied
        run=query.run_repository.get(run_id)
        if run is None: return error("NOT_FOUND","Run not found",404)
        actor=session.get("netregress_user",{}).get("username","operator")
        query.run_service.cancel_run(run_id,actor=actor,reason=str((request.get_json(silent=True) or {}).get("reason","Cancelled by operator")))
        if run.execution_pid:
            try: RunProcessManager(Path(__file__).resolve().parents[1]).cancel(run.execution_pid)
            except ProcessLookupError: pass
        return ok({"run_id":run_id,"status":"CANCELLED"})

    @api.post("/runs/<run_id>/retry")
    def retry_run(run_id):
        denied=require("execute")
        if denied is not None: return denied
        run=query.run_repository.get(run_id)
        if run is None: return error("NOT_FOUND","Run not found",404)
        manager=RunProcessManager(Path(__file__).resolve().parents[1])
        handle=manager.start(tests=tuple(run.selected_tests),firmware_version=run.firmware_version)
        return ok({"source_run_id":run_id,"process_id":handle.pid,"command":list(handle.command),"status":"STARTED"}),202

    @api.get("/runs/<run_id>")
    @protected
    def run_detail(run_id):return guarded(lambda:ok(query.get_run(run_id)))
    @api.get("/runs/<run_id>/tests")
    @protected
    def run_tests(run_id):return guarded(lambda:ok({"items":query.tests(run_id)}))
    @api.get("/runs/<run_id>/tests/<test_result_id>")
    @protected
    def run_test_detail(run_id,test_result_id):return guarded(lambda:ok(query.test(run_id,test_result_id)))
    @api.get("/runs/<run_id>/metrics")
    @protected
    def run_metrics(run_id):return guarded(lambda:ok({"items":query.metrics_for_run(run_id)}))
    @api.get("/tests/<path:test_id>/metrics")
    @protected
    def test_metrics(test_id):return guarded(lambda:ok({"items":query.metrics_history(test_id)}))
    @api.get("/regressions")
    @protected
    def regressions():
        b=request.args.get("baseline_run_id");c=request.args.get("current_run_id")
        if not b or not c:return error("MISSING_PARAMETER","baseline_run_id and current_run_id are required",400)
        return guarded(lambda:ok(query.regression(b,c)))
    @api.get("/runs/<run_id>/regressions")
    @protected
    def run_regressions(run_id):
        b=request.args.get("baseline_run_id")
        if not b:return error("MISSING_PARAMETER","baseline_run_id is required",400)
        return guarded(lambda:ok(query.regression(b,run_id)))
    @api.get("/runs/<run_id>/telemetry")
    @protected
    def run_telemetry(run_id):return guarded(lambda:ok({"environment_class":query.environment_class(run_id),"items":query.telemetry(run_id)}))
    @api.get("/runs/<run_id>/health")
    @protected
    def run_health(run_id):return guarded(lambda:ok({"items":query.health(run_id)}))
    @api.get("/labs/<lab_id>/health")
    @protected
    def lab_health(lab_id):return guarded(lambda:ok({"item":query.latest_lab_health(lab_id)}))
    @api.get("/artifacts")
    @protected
    def artifacts():
        try:page=max(1,int(request.args.get("page","1")));limit=min(200,max(1,int(request.args.get("limit","50"))))
        except ValueError:return error("INVALID_REQUEST","page and limit must be integers",400)
        return guarded(lambda:ok(query.artifacts(run_id=request.args.get("run_id"),artifact_type=request.args.get("artifact_type"),page=page,limit=limit)))
    @api.get("/artifacts/<artifact_id>")
    @protected
    def artifact_detail(artifact_id):return guarded(lambda:ok(query.serialize_artifact(query.artifact(artifact_id))))
    @api.get("/artifacts/<artifact_id>/download")
    @protected
    def artifact_download(artifact_id):
        try:
            artifact=query.artifact(artifact_id);token=os.getenv("NETREGRESS_DASHBOARD_TOKEN");remote=request.remote_addr not in {"127.0.0.1","::1"}
            if token and request.headers.get("Authorization")!="Bearer "+token:return error("FORBIDDEN","valid bearer token required",403)
            if not token and remote and auth.required:return error("FORBIDDEN","remote artifact download requires NETREGRESS_DASHBOARD_TOKEN",403)
            path=query._safe_artifact_path(artifact)
            if path is None:return error("ARTIFACT_UNAVAILABLE","artifact is missing or failed integrity verification",404)
            return send_file(path,as_attachment=True,download_name=artifact.display_name)
        except DashboardQueryError as exc:return error("NOT_FOUND",str(exc),404)
    @api.post("/baselines")
    def create_baseline():
        denied=require("admin")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        try:
            baseline=query.run_service.promote_baseline(str(payload["run_id"]),name=str(payload.get("name","Golden")),promoted_by=session.get("netregress_user",{}).get("username","admin"),device_scope=str(payload.get("device_scope","")),firmware_major_scope=str(payload.get("firmware_major_scope","")),test_suite_version=str(payload.get("test_suite_version","")),lab_class=str(payload.get("lab_class","")))
        except (KeyError,ValueError,TypeError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        return ok({"baseline_id":baseline.baseline_id,"name":baseline.name,"baseline_run_id":baseline.baseline_run_id}),201

    @api.post("/baselines/<baseline_id>/promote")
    def promote_baseline(baseline_id):
        denied=require("admin")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        run_id=str(payload.get("run_id") or baseline_id)
        try:
            baseline=query.run_service.promote_baseline(run_id,name=str(payload.get("name","Golden")),promoted_by=session.get("netregress_user",{}).get("username","admin"))
        except (ValueError,TypeError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        return ok({"baseline_id":baseline.baseline_id,"baseline_run_id":baseline.baseline_run_id}),201

    @api.post("/firmware/operations")
    def firmware_operation():
        denied=require("execute")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        run_id=str(payload["run_id"]);device_id=str(payload["device_id"]);image_path=str(payload["image_path"]);version=str(payload["version"]);reason=str(payload.get("reason","authorized firmware operation"))
        firmware_root=Path(os.getenv("NETREGRESS_FIRMWARE_ROOT",Path(__file__).resolve().parents[1]/"firmware"))
        try:image_path=str(resolve_confined_path(image_path,firmware_root))
        except RequestSecurityError as exc:return error("PATH_TRAVERSAL_DENIED",str(exc),400)
        devices=load_devices()
        values=devices.get(device_id)
        if values is None:return error("INVALID_REQUEST",f"device not configured: {device_id}",400)
        profile=DeviceProfile.from_mapping(device_id,values)
        command_runner=SecureCommandRunner(NetmikoRunner(ConnectionPool()),security_policy=CommandSecurityPolicy.compatibility())
        adapter=OpenWrtDeviceAdapter.from_profile(profile,command_runner) if profile.device_type.lower()=="openwrt" else VirtualLinuxDeviceAdapter.from_profile(profile,command_runner)
        firmware_adapter=SSHFirmwareAdapter(adapter)
        artifact_service=__import__("lib.services",fromlist=["ArtifactService"]).ArtifactService.from_sqlite(query.run_service.run_repository.database)
        from lib.adapters.firmware import FirmwareAuthorization,FirmwareImage
        auth=FirmwareAuthorization(session.get("netregress_user",{}).get("username","operator"),reason,True,"FLASH")
        try:
            result=FirmwareOperationService(run_repository=query.run_service.run_repository,event_repository=query.event_repository,artifact_service=artifact_service).update(adapter=firmware_adapter,image=FirmwareImage.from_path(image_path,version=version),authorization=auth,run_id=run_id)
        except (ValueError, RuntimeError) as exc:
            return error("FIRMWARE_OPERATION_FAILED",str(exc),400)
        return ok({"device_id":result.device_id,"image_version":result.image_version,"stage":result.stage,"verified_version":result.verified_version}),202

    @api.post("/firmware/<device_id>/rollback")
    def firmware_rollback(device_id):
        denied=require("execute")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {};run_id=str(payload["run_id"]);reason=str(payload.get("reason","authorized firmware rollback"))
        values=load_devices().get(device_id)
        if values is None:return error("INVALID_REQUEST",f"device not configured: {device_id}",400)
        profile=DeviceProfile.from_mapping(device_id,values)
        command_runner=SecureCommandRunner(NetmikoRunner(ConnectionPool()),security_policy=CommandSecurityPolicy.compatibility())
        adapter=OpenWrtDeviceAdapter.from_profile(profile,command_runner) if profile.device_type.lower()=="openwrt" else VirtualLinuxDeviceAdapter.from_profile(profile,command_runner)
        firmware_adapter=SSHFirmwareAdapter(adapter)
        from lib.adapters.firmware import FirmwareAuthorization
        auth=FirmwareAuthorization(session.get("netregress_user",{}).get("username","operator"),reason,True,"ROLLBACK")
        try:
            identity=FirmwareOperationService(run_repository=query.run_service.run_repository,event_repository=query.event_repository).rollback(adapter=firmware_adapter,authorization=auth,run_id=run_id)
        except (ValueError, RuntimeError) as exc:
            return error("FIRMWARE_ROLLBACK_FAILED",str(exc),400)
        return ok({"device_id":identity.device_id,"firmware_version":identity.firmware_version})

    @api.post("/waivers")
    def create_waiver():
        denied=require("admin")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        try:
            scope=WaiverScope(str(payload.get("scope","RELEASE")).upper())
            target_id=str(payload["target_id"])
            issue_code=str(payload["issue_code"])
            reason=str(payload["reason"])
            expires_at=None
            if payload.get("expires_at"):
                from datetime import datetime
                expires_at=datetime.fromisoformat(str(payload["expires_at"]))
            waiver=WaiverService.from_sqlite(query.database).create(
                scope=scope,
                target_id=target_id,
                issue_code=issue_code,
                reason=reason,
                created_by=session.get("netregress_user",{}).get("username","admin"),
                expires_at=expires_at,
            )
        except (KeyError,ValueError,TypeError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        return ok({
            "waiver_id":waiver.waiver_id,
            "scope":waiver.scope.value,
            "target_id":waiver.target_id,
            "issue_code":waiver.issue_code,
            "created_by":waiver.created_by,
            "expires_at":waiver.expires_at.isoformat() if waiver.expires_at else None,
        }),201

    @api.get("/baselines")
    @protected
    def baselines():return guarded(lambda:ok({"items":query.baselines()}))
    return api

def create_query(database_path:str|Path)->DashboardQueryService:return DashboardQueryService(SQLiteDatabase(database_path))
