from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Any,Callable
from functools import wraps
from flask import Blueprint,jsonify,request,session,send_file
from lib.repositories import SQLiteDatabase
from lib.services import RunProcessManager, WaiverService, FirmwareOperationService, IdempotencyStore, CsrfService, LoginRateLimiter, RequestSecurityError, resolve_confined_path, RunnerDoctor
from lib.adapters import DeviceProfile, OpenWrtDeviceAdapter, SSHFirmwareAdapter, VirtualLinuxDeviceAdapter
from lib.adapters.firmware import FirmwareImage, FirmwareAuthorization, GPGSignatureVerifier
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

    def idempotency_preflight(scope:str, payload:dict[str,Any]):
        try:
            key=IdempotencyStore.validate_key(request.headers.get("Idempotency-Key",""))
        except RequestSecurityError as exc:
            return None,None,None,error("INVALID_IDEMPOTENCY_KEY",str(exc),400)
        request_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
        try:
            cached=idempotency_store.get(scope,key,request_hash)
        except RequestSecurityError as exc:
            return None,None,None,error("IDEMPOTENCY_KEY_REUSE",str(exc),409)
        return key,request_hash,cached,None

    def idempotency_store_response(scope:str,key:str,request_hash:str,data:Any,status:int):
        idempotency_store.put(scope,key,request_hash,{"data":data},status)
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
        report=RunnerDoctor(Path(__file__).resolve().parents[1]).run(database=query.database.path)
        checks=[{"check_id":item.check_id,"status":item.status,"message":item.message} for item in report.checks]
        payload={"status":"ready" if report.ready else "not_ready","summary":report.summary,"checks":checks}
        return ok(payload) if report.ready else error("NOT_READY",report.summary,503,{"checks":checks})
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
        payload=request.get_json(silent=True) or {}
        reason=str(payload.get("reason","Cancelled by operator"))
        idem_payload={"run_id":run_id,"reason":reason}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/runs/cancel/"+run_id,idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
        actor=session.get("netregress_user",{}).get("username","operator")
        query.run_service.cancel_run(run_id,actor=actor,reason=reason)
        if run.execution_pid:
            try: RunProcessManager(Path(__file__).resolve().parents[1]).cancel(run.execution_pid)
            except ProcessLookupError: pass
        response_data={"run_id":run_id,"status":"CANCELLED"}
        idempotency_store_response("/api/v1/runs/cancel/"+run_id,key,request_hash,response_data,200)
        return ok(response_data)

    @api.post("/runs/<run_id>/retry")
    def retry_run(run_id):
        denied=require("execute")
        if denied is not None: return denied
        run=query.run_repository.get(run_id)
        if run is None: return error("NOT_FOUND","Run not found",404)
        idem_payload={"run_id":run_id,"selected_tests":list(run.selected_tests),"firmware_version":run.firmware_version}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/runs/retry/"+run_id,idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
        manager=RunProcessManager(Path(__file__).resolve().parents[1])
        handle=manager.start(tests=tuple(run.selected_tests),firmware_version=run.firmware_version)
        response_data={"source_run_id":run_id,"process_id":handle.pid,"command":list(handle.command),"status":"STARTED"}
        idempotency_store_response("/api/v1/runs/retry/"+run_id,key,request_hash,response_data,202)
        return ok(response_data),202

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
            run_id=str(payload["run_id"])
        except (KeyError,TypeError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        idem_payload={k:payload.get(k) for k in ("run_id","name","device_scope","firmware_major_scope","test_suite_version","lab_class")}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/baselines",idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
        try:
            baseline=query.run_service.promote_baseline(
                run_id,
                name=str(payload.get("name","Golden")),
                promoted_by=session.get("netregress_user",{}).get("username","admin"),
                device_scope=str(payload.get("device_scope","")),
                firmware_major_scope=str(payload.get("firmware_major_scope","")),
                test_suite_version=str(payload.get("test_suite_version","")),
                lab_class=str(payload.get("lab_class","")),
            )
        except (ValueError,TypeError,KeyError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        response_data={"baseline_id":baseline.baseline_id,"name":baseline.name,"baseline_run_id":baseline.baseline_run_id}
        idempotency_store_response("/api/v1/baselines",key,request_hash,response_data,201)
        return ok(response_data),201

    @api.post("/baselines/<baseline_id>/promote")
    def promote_baseline(baseline_id):
        denied=require("admin")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        run_id=str(payload.get("run_id") or baseline_id)
        idem_payload={"baseline_id":baseline_id,"run_id":run_id,"name":payload.get("name","Golden")}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/baselines/"+baseline_id+"/promote",idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
        try:
            baseline=query.run_service.promote_baseline(
                run_id,
                name=str(payload.get("name","Golden")),
                promoted_by=session.get("netregress_user",{}).get("username","admin"),
            )
        except (ValueError,TypeError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        response_data={"baseline_id":baseline.baseline_id,"baseline_run_id":baseline.baseline_run_id}
        idempotency_store_response("/api/v1/baselines/"+baseline_id+"/promote",key,request_hash,response_data,201)
        return ok(response_data),201

    @api.post("/firmware/operations")
    def firmware_operation():
        denied=require("execute")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        try:
            run_id=str(payload["run_id"]);device_id=str(payload["device_id"]);image_path_raw=str(payload["image_path"]);version=str(payload["version"])
        except KeyError as exc:
            return error("INVALID_REQUEST",str(exc),400)
        reason=str(payload.get("reason","authorized firmware operation"))
        compatible_models=tuple(str(item) for item in (payload.get("compatible_models") or ()))
        expected_sha256=str(payload.get("expected_sha256","")).strip() or None
        signature_path_raw=str(payload.get("signature_path","")).strip() or None
        require_signature=os.getenv("NETREGRESS_REQUIRE_FIRMWARE_SIGNATURE","0").lower() not in {"0","false","no"}
        if require_signature and not signature_path_raw:
            return error("SIGNATURE_REQUIRED","firmware signature is required by policy",400)
        firmware_root=Path(os.getenv("NETREGRESS_FIRMWARE_ROOT",Path(__file__).resolve().parents[1]/"firmware"))
        try:
            image_path=str(resolve_confined_path(image_path_raw,firmware_root))
            signature_path=str(resolve_confined_path(signature_path_raw,firmware_root)) if signature_path_raw else None
        except RequestSecurityError as exc:return error("PATH_TRAVERSAL_DENIED",str(exc),400)
        idem_payload={
            "run_id":run_id,"device_id":device_id,"image_path":image_path,"version":version,
            "compatible_models":list(compatible_models),"expected_sha256":expected_sha256,
            "signature_path":signature_path,"reason":reason,
        }
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/firmware/operations",idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
        devices=load_devices()
        values=devices.get(device_id)
        if values is None:return error("INVALID_REQUEST",f"device not configured: {device_id}",400)
        profile=DeviceProfile.from_mapping(device_id,values)
        command_runner=SecureCommandRunner(NetmikoRunner(ConnectionPool()),security_policy=CommandSecurityPolicy.compatibility())
        adapter=OpenWrtDeviceAdapter.from_profile(profile,command_runner) if profile.device_type.lower()=="openwrt" else VirtualLinuxDeviceAdapter.from_profile(profile,command_runner)
        firmware_adapter=SSHFirmwareAdapter(adapter,signature_verifier=GPGSignatureVerifier() if signature_path else None)
        artifact_service=__import__("lib.services",fromlist=["ArtifactService"]).ArtifactService.from_sqlite(query.run_service.run_repository.database)
        auth=FirmwareAuthorization(session.get("netregress_user",{}).get("username","operator"),reason,True,"FLASH")
        try:
            result=FirmwareOperationService(
                run_repository=query.run_service.run_repository,
                event_repository=query.event_repository,
                artifact_service=artifact_service,
            ).update(
                adapter=firmware_adapter,
                image=FirmwareImage.from_path(
                    image_path,version=version,compatible_models=compatible_models,
                    expected_sha256=expected_sha256,signature_path=signature_path,
                ),
                authorization=auth,
                run_id=run_id,
            )
        except (ValueError,RuntimeError,OSError) as exc:
            return error("FIRMWARE_OPERATION_FAILED",str(exc),400)
        response_data={
            "device_id":result.device_id,"image_version":result.image_version,"stage":result.stage,
            "verified_version":result.verified_version,"sha256":result.validation.sha256,
            "signature_verified":result.validation.signature_verified,"compatible":result.validation.compatible,
        }
        idempotency_store_response("/api/v1/firmware/operations",key,request_hash,response_data,202)
        return ok(response_data),202

    @api.post("/firmware/<device_id>/rollback")
    def firmware_rollback(device_id):
        denied=require("execute")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        try: run_id=str(payload["run_id"])
        except KeyError as exc:return error("INVALID_REQUEST",str(exc),400)
        reason=str(payload.get("reason","authorized firmware rollback"))
        idem_payload={"device_id":device_id,"run_id":run_id,"reason":reason}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/firmware/rollback/"+device_id,idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
        values=load_devices().get(device_id)
        if values is None:return error("INVALID_REQUEST",f"device not configured: {device_id}",400)
        profile=DeviceProfile.from_mapping(device_id,values)
        command_runner=SecureCommandRunner(NetmikoRunner(ConnectionPool()),security_policy=CommandSecurityPolicy.compatibility())
        adapter=OpenWrtDeviceAdapter.from_profile(profile,command_runner) if profile.device_type.lower()=="openwrt" else VirtualLinuxDeviceAdapter.from_profile(profile,command_runner)
        firmware_adapter=SSHFirmwareAdapter(adapter)
        auth=FirmwareAuthorization(session.get("netregress_user",{}).get("username","operator"),reason,True,"ROLLBACK")
        try:
            identity=FirmwareOperationService(
                run_repository=query.run_service.run_repository,
                event_repository=query.event_repository,
            ).rollback(adapter=firmware_adapter,authorization=auth,run_id=run_id)
        except (ValueError,RuntimeError,OSError) as exc:
            return error("FIRMWARE_ROLLBACK_FAILED",str(exc),400)
        response_data={"device_id":identity.device_id,"firmware_version":identity.firmware_version}
        idempotency_store_response("/api/v1/firmware/rollback/"+device_id,key,request_hash,response_data,200)
        return ok(response_data)

    @api.post("/waivers")
    def create_waiver():
        denied=require("admin")
        if denied is not None: return denied
        payload=request.get_json(silent=True) or {}
        idem_payload={k:payload.get(k) for k in ("scope","target_id","issue_code","reason","expires_at")}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/waivers",idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
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
        response_data={
            "waiver_id":waiver.waiver_id,
            "scope":waiver.scope.value,
            "target_id":waiver.target_id,
            "issue_code":waiver.issue_code,
            "created_by":waiver.created_by,
            "expires_at":waiver.expires_at.isoformat() if waiver.expires_at else None,
        }
        idempotency_store_response("/api/v1/waivers",key,request_hash,response_data,201)
        return ok(response_data),201

    @api.get("/baselines")
    @protected
    def baselines():return guarded(lambda:ok({"items":query.baselines()}))
    return api

def create_query(database_path:str|Path)->DashboardQueryService:return DashboardQueryService(SQLiteDatabase(database_path))
