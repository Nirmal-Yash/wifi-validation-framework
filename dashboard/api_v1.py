from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from werkzeug.security import check_password_hash
from typing import Any,Callable
from functools import wraps
from flask import Blueprint,jsonify,request,session,send_file,current_app
from lib.platform import platform_adapter_for
from lib.services.configuration_schema_registry import (
    ConfigurationSchemaError, ConfigurationSchemaNotFound, ConfigurationSchemaRegistry,
)
from lib.services.credential_vault import (
    CredentialVaultError, CredentialVaultNotFound, CredentialVaultPolicyError,
    CredentialVaultService,
)
from lib.repositories import (
    SQLiteDatabase, SQLiteOrganizationRepository, SQLiteProjectRepository,
    SQLiteLabRepository, SQLiteProjectMembershipRepository, RepositoryConflictError,
)
from lib.services import RunProcessManager, ProcessNotManagedError, ProcessOwnershipError, ProcessTerminationError, RunProcessError, WaiverService, FirmwareOperationService, IdempotencyStore, CsrfService, LoginRateLimiter, RequestSecurityError, resolve_confined_path, RunnerDoctor
from lib.adapters import DeviceProfile, OpenWrtDeviceAdapter, SSHFirmwareAdapter, VirtualLinuxDeviceAdapter
from lib.adapters.firmware import FirmwareImage, FirmwareAuthorization, GPGSignatureVerifier
from lib.connector import load_devices, ConnectionPool
from lib.services.command_security import CommandSecurityPolicy, SecureCommandRunner
from lib.services.command_runner import NetmikoRunner
from lib.security import AuthManager,AuthConfigurationError,AuthenticatedUser,Role
from lib.domain import DomainValidationError, RunLifecycle, WaiverScope
from lib.domain.resources import (
    Organization, Project, Lab, ProjectMembership, ResourceStatus,
    ResourceValidationError, new_resource_id,
)
from lib.services.identity import (
    IdentityStore, IdentityConflictError, IdentityNotFoundError, IdentityPolicyError,
)
from .query import DashboardQueryError,DashboardQueryService

def create_api_blueprint(query:DashboardQueryService,auth_manager:AuthManager|None=None)->Blueprint:
    api=Blueprint("api_v1",__name__,url_prefix="/api/v1"); auth=auth_manager or AuthManager.from_env()
    idempotency_store=IdempotencyStore(query.database)
    login_limiter=LoginRateLimiter()
    identity=IdentityStore(query.database)
    platform_adapter=platform_adapter_for()
    credential_vault=CredentialVaultService(
        query.database,platform_adapter.create_secret_store(),
        secret_provider=platform_adapter.descriptor.family.value,
    )
    configuration_schemas=ConfigurationSchemaRegistry(query.database)
    organization_repository=SQLiteOrganizationRepository(query.database)
    project_repository=SQLiteProjectRepository(query.database)
    lab_repository=SQLiteLabRepository(query.database)
    membership_repository=SQLiteProjectMembershipRepository(query.database)

    def identity_profile(username, *, wildcard=False):
        user=identity.get_user(username)
        if user is None:
            return None
        with query.database.connection() as connection:
            role=connection.execute(
                """SELECT r.role_id,r.name FROM role_assignments a
                   JOIN roles r ON r.role_id=a.role_id
                   WHERE a.username=? AND a.scope_type='GLOBAL' AND a.scope_id='*'""",
                (username,),
            ).fetchone()
        permissions=list(identity.permission_codes(username))
        wildcard=wildcard or user.get("workspace_scope","MEMBERSHIP")=="WILDCARD"
        return {
            "username":user["username"],
            "display_name":user["display_name"],
            "email":user["email"],
            "status":user["status"],
            "workspace_scope":user.get("workspace_scope","MEMBERSHIP"),
            "role":role["name"] if role else "VIEWER",
            "global_role_id":role["role_id"] if role else None,
            "permissions":permissions,
            "projects":["*"] if wildcard else list(identity.project_ids_for_user(username)),
        }

    def request_project_id():
        values=request.view_args or {}
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):
            payload={}
        explicit=values.get("project_id") or request.args.get("project_id") or payload.get("project_id")
        run_ids=[]
        for key in ("run_id","baseline_run_id","current_run_id"):
            candidate=values.get(key) or (
                values.get("baseline_id") if key=="run_id" else None
            ) or request.args.get(key) or payload.get(key)
            if candidate:
                run_ids.append(str(candidate))
        if run_ids:
            projects=[]
            for run_id in dict.fromkeys(run_ids):
                run=query.run_repository.get(run_id)
                if run is None:
                    return None
                projects.append(run.project_id or "__unowned__")
            if len(set(projects))>1:
                return "__cross_project__"
            resolved=projects[0]
            if explicit and resolved and str(explicit)!=resolved:
                return "__cross_project__"
            return resolved
        artifact_id=values.get("artifact_id")
        if artifact_id:
            try:
                artifact=query.artifact(str(artifact_id))
                run=query.run_repository.get(artifact.run_id)
                return (run.project_id or "__unowned__") if run else None
            except DashboardQueryError:
                return None
        lab_id=values.get("lab_id") or request.args.get("lab_id")
        if lab_id:
            lab=lab_repository.get(str(lab_id))
            return lab.project_id if lab else None
        return str(explicit) if explicit else None

    def require_permission(permission_code, *, project_id=None, global_scope=False):
        denied=require("view",project_id=project_id,global_scope=global_scope)
        if denied is not None:
            return denied
        raw=session.get("netregress_user")
        if raw is None:
            return None
        username=str(raw.get("username",""))
        wildcard=tuple(raw.get("projects",()))==("*",)
        if permission_code not in identity.permission_codes(username):
            return error("FORBIDDEN",f"permission required: {permission_code}",403)
        if project_id and not wildcard and permission_code not in identity.permission_codes(username,project_id):
            return error("FORBIDDEN",f"Project permission required: {permission_code}",403)
        return None
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
    def require(action="view",project_id=None,*,touch=False,global_scope=False):
        raw=session.get("netregress_user")
        if raw is None:
            if auth.required:
                return error("UNAUTHENTICATED","authentication required",401)
            actor=AuthenticatedUser("local",Role.OWNER,("*",))
            if not auth.authorize(actor,action,project_id):
                return error("FORBIDDEN","authorization denied",403)
            return None
        now=time.time()
        idle_timeout=float(current_app.config.get("SESSION_IDLE_TIMEOUT_SECONDS",1800))
        try:
            if not isinstance(raw,dict):
                raise TypeError("invalid session identity")
            last_activity=float(session.get("netregress_last_activity",0))
            if last_activity<=0 or now-last_activity>idle_timeout:
                session.clear()
                return error("SESSION_EXPIRED","session expired after inactivity",401)
            username=str(raw["username"])
            session_id=str(raw["session_id"])
            projects=raw.get("projects",[])
            if not isinstance(projects,(list,tuple)) or any(
                not isinstance(value,str) or not value.strip() for value in projects
            ):
                raise ValueError("invalid project scope")
        except (KeyError,ValueError,TypeError):
            session.clear()
            return error("UNAUTHENTICATED","invalid session",401)
        write_or_touch=touch or request.method in {"POST","PUT","PATCH","DELETE"}
        if not identity.validate_session(username,session_id,touch=write_or_touch,idle_timeout_seconds=int(idle_timeout)):
            session.clear()
            return error("SESSION_REVOKED","account session is no longer active",401)
        if request.method in {"POST","PUT","PATCH","DELETE"} and request.path!="/api/v1/auth/login" and not CsrfService.validate(session,request.headers.get("X-CSRF-Token")):
            return error("CSRF_REQUIRED","valid X-CSRF-Token header required for browser state changes",403)
        if not global_scope and project_id is None:
            project_id=request_project_id()
        wildcard=tuple(projects)==("*",)
        if not identity.authorize(username,action,project_id,wildcard=wildcard):
            return error("FORBIDDEN","authorization denied",403)
        if write_or_touch:
            session["netregress_last_activity"]=now
        return None
    @api.get("/health")
    def health():return ok({"status":"ok"})
    @api.get("/readiness")
    def readiness():
        denied = require("view")
        if denied is not None:
            return denied
        report=RunnerDoctor(Path(__file__).resolve().parents[1]).run(database=query.database.path)
        checks=[{"check_id":item.check_id,"status":item.status,"message":item.message} for item in report.checks]
        payload={"status":"ready" if report.ready else "not_ready","summary":report.summary,"checks":checks}
        return ok(payload) if report.ready else error("NOT_READY",report.summary,503,{"checks":checks})
    @api.post("/auth/login")
    def login():
        payload=request.get_json(silent=True) or {}
        username=str(payload.get("username","")).strip()
        password=str(payload.get("password",""))
        if not login_limiter.allow(f"{request.remote_addr or 'unknown'}:{username}"):
            return error("RATE_LIMITED","too many login attempts",429)
        persisted=identity.get_user(username)
        wildcard=False
        if persisted is not None:
            if persisted["status"]!="ACTIVE" or not persisted["password_hash"]:
                return error("ACCOUNT_INACTIVE","account is not active",403)
            wildcard=persisted.get("workspace_scope","MEMBERSHIP")=="WILDCARD"
            if not check_password_hash(persisted["password_hash"],password):
                return error("INVALID_CREDENTIALS","invalid credentials",401)
        else:
            try:
                auth.require_configured()
            except AuthConfigurationError as exc:
                return error("AUTH_NOT_CONFIGURED",str(exc),503)
            user=auth.authenticate(username,password)
            if user is None:
                return error("INVALID_CREDENTIALS","invalid credentials",401)
            configured=auth._users.get(user.username)
            if configured is None:
                return error("INVALID_CREDENTIALS","invalid credentials",401)
            try:
                wildcard=tuple(user.projects)==("*",)
                identity.ensure_bootstrap_user(
                    user.username,configured.password_hash,user.role.value,
                    actor="local-bootstrap",
                    workspace_scope="WILDCARD" if wildcard else "MEMBERSHIP",
                )
            except IdentityPolicyError:
                return error("ACCOUNT_INACTIVE","account is not active",403)
            wildcard=tuple(user.projects)==("*",)
            # Migrate explicit local project scopes into durable memberships.
            if not wildcard:
                for project_id in user.projects:
                    if project_repository.get(project_id) is None:
                        continue
                    if membership_repository.get(user.username,project_id) is None:
                        now=datetime.now(timezone.utc)
                        base_role=user.role.value
                        try:
                            membership_repository.save(ProjectMembership(
                                user.username,project_id,base_role,now,"local-bootstrap"
                            ))
                            with query.database.transaction(immediate=True) as connection:
                                connection.execute(
                                    """INSERT OR IGNORE INTO role_assignments(
                                        username,role_id,scope_type,scope_id,created_at,created_by
                                    ) VALUES(?,?,'PROJECT',?,?,?)""",
                                    (user.username,"project_"+base_role.lower(),project_id,now.isoformat(),"local-bootstrap"),
                                )
                        except RepositoryConflictError:
                            pass
        session.clear()
        session_id=identity.create_session(username)
        profile=identity_profile(username,wildcard=wildcard)
        if profile is None:
            return error("INTERNAL_ERROR","persistent account could not be loaded",500)
        session["netregress_user"]={**profile,"session_id":session_id}
        session["netregress_last_activity"]=time.time()
        session.permanent=True
        return ok({**session["netregress_user"],"csrf_token":CsrfService.token(session)})
    @api.get("/auth/csrf")
    def csrf():
        denied=require("view")
        if denied is not None:return denied
        return ok({"csrf_token":CsrfService.token(session)})

    @api.post("/auth/activity")
    def activity():
        denied=require("view",touch=True)
        if denied is not None:
            return denied
        return ok({"active":True})
    @api.post("/auth/logout")
    def logout():
        denied=require("view",global_scope=True)
        if denied is not None:
            return denied
        raw=session.get("netregress_user") or {}
        identity.revoke_current_session(str(raw.get("username","")),str(raw.get("session_id","")))
        session.clear()
        return ok({"logged_out":True})
    @api.get("/auth/me")
    def me():
        denied=require("view",global_scope=True,touch=True)
        if denied is not None:
            return denied
        raw=session.get("netregress_user") or {}
        profile=identity_profile(
            str(raw.get("username","")),
            wildcard=tuple(raw.get("projects",()))==("*",),
        )
        if profile is None:
            session.clear()
            return error("UNAUTHENTICATED","account not found",401)
        return ok({**profile,"session_id":raw.get("session_id")})

    def protected(fn:Callable):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            denied=require("view")
            return denied if denied is not None else fn(*args,**kwargs)
        return wrapper
    @api.post("/runs")
    def launch_run():
        payload=request.get_json(silent=True) or {}
        raw=session.get("netregress_user") or {}
        wildcard=session.get("netregress_user") is None or tuple(raw.get("projects",()))==("*",)
        project_id=str(payload.get("project_id","")).strip() or None
        lab_id=str(payload.get("lab_id","")).strip() or None
        if not wildcard and (not project_id or not lab_id):
            return error("PROJECT_AND_LAB_REQUIRED","Select a Project and one of its Labs before launching a scoped Run",400)
        denied=require("execute",project_id=project_id,global_scope=project_id is None)
        if denied is not None:
            return denied
        if project_id:
            project=project_repository.get(project_id)
            lab=lab_repository.get(lab_id) if lab_id else None
            if project is None:
                return error("NOT_FOUND","Project not found",404)
            if lab is None or lab.project_id!=project_id:
                return error("INVALID_LAB_SCOPE","Lab must belong to the selected Project",400)
            if project.status is not ResourceStatus.ACTIVE or lab.status is not ResourceStatus.ACTIVE:
                return error("RESOURCE_INACTIVE","Runs require an active Project and Lab",409)
        firmware=str(payload.get("firmware_version","v1.0"))
        tests=tuple(str(x) for x in (payload.get("tests") or ()))
        try:key=IdempotencyStore.validate_key(request.headers.get("Idempotency-Key",""))
        except RequestSecurityError as exc:return error("INVALID_IDEMPOTENCY_KEY",str(exc),400)
        request_hash=hashlib.sha256(json.dumps({"firmware_version":firmware,"tests":list(tests),"project_id":project_id,"lab_id":lab_id},sort_keys=True,separators=(",",":")).encode()).hexdigest()
        try:
            cached=idempotency_store.get("/api/v1/runs",key,request_hash)
        except RequestSecurityError as exc:return error("IDEMPOTENCY_KEY_REUSE",str(exc),409)
        if cached is not None:return jsonify(cached.response),cached.status_code
        manager=RunProcessManager(Path(__file__).resolve().parents[1])
        run_env={"NETREGRESS_RUN_REQUESTED_BY":raw.get("username","local")}
        if project_id:
            run_env["NETREGRESS_PROJECT_ID"]=project_id
            run_env["NETREGRESS_LAB_ID"]=lab_id
        handle=manager.start(tests=tests or None,firmware_version=firmware,env=run_env)
        response={"data":{"process_id":handle.pid,"command":list(handle.command),"status":"STARTED"}}
        idempotency_store.put("/api/v1/runs",key,request_hash,response,202)
        return jsonify(response),202

    @api.get("/runs")
    def runs():
        raw=session.get("netregress_user") or {}
        wildcard=session.get("netregress_user") is None or tuple(raw.get("projects",()))==("*",)
        requested=request.args.get("project_id")
        denied=require("view",project_id=requested,global_scope=requested is None)
        if denied is not None:
            return denied
        project_ids=(requested,) if requested else (
            None if wildcard else identity.project_ids_for_user(str(raw.get("username","")))
        )
        if not wildcard and not project_ids:
            return error("FORBIDDEN","no active Project memberships are assigned to this account",403)
        return guarded(lambda:ok(query.runs(
            firmware=request.args.get("firmware"),lab=request.args.get("lab"),
            profile=request.args.get("profile"),status=request.args.get("status"),
            outcome=request.args.get("outcome"),page=int(request.args.get("page","1")),
            limit=int(request.args.get("limit","50")),project_ids=project_ids,
        )))
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
        if run.lifecycle in {
            RunLifecycle.COMPLETED,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
        }:
            return error("RUN_NOT_ACTIVE","Run is already terminal",409)
        if not run.execution_pid:
            return error("RUN_PROCESS_UNAVAILABLE","Run has no registered execution process",409)

        actor=session.get("netregress_user",{}).get("username","operator")
        manager=RunProcessManager(Path(__file__).resolve().parents[1])
        try:
            if not manager.validate(run.execution_pid):
                return error("RUN_PROCESS_EXITED","Run process has already exited",409)
        except ProcessNotManagedError as exc:
            return error("PROCESS_NOT_MANAGED",str(exc),409)
        except ProcessOwnershipError as exc:
            return error("PROCESS_OWNERSHIP_MISMATCH",str(exc),409)
        except RunProcessError as exc:
            return error("PROCESS_CONTROL_FAILED",str(exc),500)

        try:
            query.run_service.request_cancel(run_id,actor=actor,reason=reason)
        except DomainValidationError:
            latest=query.run_repository.get(run_id)
            return error(
                "RUN_NOT_ACTIVE",
                f"Run became terminal before cancellation (state: {latest.lifecycle.value if latest else 'UNKNOWN'})",
                409,
            )
        try:
            stopped=manager.cancel(run.execution_pid)
        except ProcessNotManagedError as exc:
            latest=query.run_repository.get(run_id)
            if latest is not None and latest.lifecycle is RunLifecycle.CANCELLED:
                response_data={"run_id":run_id,"status":"CANCELLED"}
                idempotency_store_response("/api/v1/runs/cancel/"+run_id,key,request_hash,response_data,200)
                return ok(response_data)
            return error(
                "PROCESS_EXITED_DURING_CANCEL",
                f"{exc}; persisted Run state: {latest.lifecycle.value if latest else 'UNKNOWN'}",
                409,
            )
        except ProcessOwnershipError as exc:
            return error("PROCESS_OWNERSHIP_MISMATCH",str(exc),409)
        except ProcessTerminationError as exc:
            return error("PROCESS_TERMINATION_FAILED",str(exc),504)
        except RunProcessError as exc:
            return error("PROCESS_CONTROL_FAILED",str(exc),500)

        latest=query.run_repository.get(run_id)
        if not stopped:
            if latest is not None and latest.lifecycle not in {
                RunLifecycle.COMPLETED,
                RunLifecycle.FAILED,
                RunLifecycle.LAB_FAILED,
                RunLifecycle.CANCELLED,
                RunLifecycle.ABORTED,
            }:
                try:
                    query.run_service.cancel_run(run_id,actor=actor,reason=reason)
                except Exception:
                    pass
            latest=query.run_repository.get(run_id)
            if latest is None or latest.lifecycle is not RunLifecycle.CANCELLED:
                return error(
                    "RUN_PROCESS_EXITED",
                    f"Run process exited before cancellation completed (state: {latest.lifecycle.value if latest else 'UNKNOWN'})",
                    409,
                )

        latest=query.run_repository.get(run_id)
        if latest is not None and latest.lifecycle not in {
            RunLifecycle.COMPLETED,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
        }:
            try:
                query.run_service.cancel_run(run_id,actor=actor,reason=reason)
            except DomainValidationError:
                # The pytest finalizer may have completed the cancellation first.
                pass
        latest=query.run_repository.get(run_id)
        if latest is None or latest.lifecycle is not RunLifecycle.CANCELLED:
            return error("RUN_FINALIZATION_RACE","Process stopped but Run finalized with a different outcome",409)

        response_data={"run_id":run_id,"status":"CANCELLED"}
        idempotency_store_response("/api/v1/runs/cancel/"+run_id,key,request_hash,response_data,200)
        return ok(response_data)

    @api.post("/runs/<run_id>/retry")
    def retry_run(run_id):
        denied=require("execute")
        if denied is not None: return denied
        run=query.run_repository.get(run_id)
        if run is None: return error("NOT_FOUND","Run not found",404)
        if run.lifecycle not in {
            RunLifecycle.COMPLETED,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
        }:
            return error("RUN_NOT_TERMINAL", "Only terminal Runs can be retried", 409)
        idem_payload={"run_id":run_id,"selected_tests":list(run.selected_tests),"firmware_version":run.firmware_version}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/runs/retry/"+run_id,idem_payload)
        if security_error is not None:return security_error
        if cached is not None:return jsonify(cached.response),cached.status_code
        manager=RunProcessManager(Path(__file__).resolve().parents[1])
        handle=manager.start(
            tests=tuple(run.selected_tests),
            firmware_version=run.firmware_version,
            env={
                "NETREGRESS_SOURCE_RUN_ID": run_id,
                "NETREGRESS_DATABASE_PATH": str(query.database.path.resolve()),
                "TEST_DB_PATH": str(query.database.path.resolve()),
                "NETREGRESS_LAB_ID": run.lab_id,
                **({"NETREGRESS_PROJECT_ID": run.project_id} if run.project_id else {}),
            },
        )
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
    def test_metrics(test_id):
        denied=require("view",global_scope=True)
        if denied is not None:
            return denied
        raw=session.get("netregress_user") or {}
        projects=None if session.get("netregress_user") is None or tuple(raw.get("projects",()))==("*",) else identity.project_ids_for_user(str(raw.get("username","")))
        return guarded(lambda:ok({"items":query.metrics_history(test_id,project_ids=projects)}))
    @api.get("/regressions")
    @protected
    def regressions():
        b=request.args.get("baseline_run_id");c=request.args.get("current_run_id")
        if not b or not c:return error("MISSING_PARAMETER","baseline_run_id and current_run_id are required",400)
        return guarded(lambda:ok(query.regression(b,c)))
    @api.get("/runs/<run_id>/release-gate")
    @protected
    def run_release_gate(run_id):
        baseline_run_id=request.args.get("baseline_run_id")
        if not baseline_run_id:
            return error("MISSING_PARAMETER","baseline_run_id is required",400)
        return guarded(lambda:ok(query.release_gate(run_id,baseline_run_id)))

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
    def artifacts():
        raw=session.get("netregress_user") or {}
        wildcard=session.get("netregress_user") is None or tuple(raw.get("projects",()))==("*",)
        run_id=request.args.get("run_id")
        project_id=request.args.get("project_id") or (request_project_id() if run_id else None)
        denied=require("view",project_id=project_id,global_scope=not run_id and not project_id)
        if denied is not None:
            return denied
        project_ids=(project_id,) if project_id else (
            None if wildcard else identity.project_ids_for_user(str(raw.get("username","")))
        )
        try:
            page=max(1,int(request.args.get("page","1")))
            limit=min(200,max(1,int(request.args.get("limit","50"))))
        except ValueError:
            return error("INVALID_REQUEST","page and limit must be integers",400)
        return guarded(lambda:ok(query.artifacts(
            run_id=run_id,artifact_type=request.args.get("artifact_type"),
            page=page,limit=limit,project_ids=project_ids,
        )))
    @api.get("/artifacts/<artifact_id>")
    @protected
    def artifact_detail(artifact_id):return guarded(lambda:ok(query.serialize_artifact(query.artifact(artifact_id))))
    @api.get("/artifacts/<artifact_id>/download")
    @protected
    def artifact_download(artifact_id):
        try:
            artifact=query.artifact(artifact_id)
            sensitivity=str(artifact.sensitivity_class or "").strip().upper()
            if sensitivity not in {"PUBLIC","INTERNAL"}:
                denied=require("admin")
                if denied is not None:
                    return denied

            remote=request.remote_addr not in {"127.0.0.1","::1"}
            # Verified browser sessions may download via a reverse proxy. Remote
            # non-browser clients still require the dedicated bearer token.
            if remote and session.get("netregress_user") is None:
                token=(os.getenv("NETREGRESS_DASHBOARD_TOKEN") or "").strip()
                supplied=request.headers.get("Authorization","")
                if not token:
                    return error("FORBIDDEN","remote artifact downloads require an authenticated browser session or configured NETREGRESS_DASHBOARD_TOKEN",403)
                if not hmac.compare_digest(supplied,"Bearer "+token):
                    return error("FORBIDDEN","valid bearer token required for remote artifact download",403)

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
        try:
            run_id_raw = payload["run_id"]
            expected_version_raw = payload["expected_version"]
        except KeyError as exc:
            return error("INVALID_REQUEST",str(exc),400)
        if not isinstance(run_id_raw, str) or not run_id_raw.strip():
            return error("INVALID_REQUEST","run_id must be a non-empty string",400)
        if not isinstance(expected_version_raw, str) or not expected_version_raw.strip():
            return error("INVALID_REQUEST","expected_version must be a non-empty string",400)
        run_id = run_id_raw.strip()
        expected_version = expected_version_raw.strip()
        reason=str(payload.get("reason","authorized firmware rollback"))
        idem_payload={"device_id":device_id,"run_id":run_id,"expected_version":expected_version,"reason":reason}
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
            ).rollback(adapter=firmware_adapter,authorization=auth,expected_version=expected_version,run_id=run_id)
        except (ValueError,RuntimeError,OSError) as exc:
            return error("FIRMWARE_ROLLBACK_FAILED",str(exc),400)
        response_data={"device_id":identity.device_id,"firmware_version":identity.firmware_version,"verified_version":identity.firmware_version}
        idempotency_store_response("/api/v1/firmware/rollback/"+device_id,key,request_hash,response_data,200)
        return ok(response_data)

    @api.get("/sync/queue")
    def sync_queue():
        denied=require("admin")
        if denied is not None:
            return denied
        try:
            limit=int(request.args.get("limit",50))
        except (TypeError, ValueError):
            return error("INVALID_REQUEST","limit must be an integer from 1 to 200",400)
        if limit < 1 or limit > 200:
            return error("INVALID_REQUEST","limit must be between 1 and 200",400)
        return ok(query.sync_queue(limit))

    @api.get("/waivers")
    def list_waivers():
        denied=require("admin")
        if denied is not None:
            return denied
        from datetime import datetime, timezone
        now=datetime.now(timezone.utc)
        items=WaiverService.from_sqlite(query.database).repository.list_active()
        active=[item for item in items if item.is_active(now)]
        return ok({"items":[{
            "waiver_id":item.waiver_id,"scope":item.scope.value,"target_id":item.target_id,
            "issue_code":item.issue_code,"reason":item.reason,"created_by":item.created_by,
            "created_at":item.created_at.isoformat(),
            "expires_at":item.expires_at.isoformat() if item.expires_at else None,
            "audit_reference":item.audit_reference,
        } for item in active]})

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
                from datetime import datetime, timezone
                expires_at=datetime.fromisoformat(str(payload["expires_at"]).replace("Z","+00:00"))
                expires_at=expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at.astimezone(timezone.utc)
                if expires_at <= datetime.now(timezone.utc):
                    return error("INVALID_REQUEST","expires_at must be in the future",400)
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
    def baselines():
        denied=require("view",global_scope=True)
        if denied is not None:
            return denied
        raw=session.get("netregress_user") or {}
        projects=None if session.get("netregress_user") is None or tuple(raw.get("projects",()))==("*",) else identity.project_ids_for_user(str(raw.get("username","")))
        return guarded(lambda:ok({"items":query.baselines(project_ids=projects)}))

    # ---- Persistent identity and lifecycle APIs (Stage B / P04–P07) ----
    @api.post("/auth/invitations/accept")
    def accept_invitation():
        payload=request.get_json(silent=True) or {}
        try:
            user=identity.accept_invitation(str(payload.get("token","")),str(payload.get("password","")))
        except (ValueError,IdentityPolicyError) as exc:
            return error("INVITATION_INVALID",str(exc),400)
        return ok({"username":user["username"],"status":user["status"]}),200

    @api.post("/auth/password-resets/complete")
    def complete_password_reset():
        payload=request.get_json(silent=True) or {}
        try:
            user=identity.complete_password_reset(str(payload.get("token","")),str(payload.get("password","")))
        except (ValueError,IdentityPolicyError) as exc:
            return error("RESET_INVALID",str(exc),400)
        return ok({"username":user["username"],"password_reset":True})

    @api.get("/identity/users")
    def identity_users():
        denied=require_permission("users.read",global_scope=True)
        if denied is not None:
            return denied
        return ok({"items":identity.list_users()})

    @api.post("/identity/invitations")
    def invite_identity_user():
        denied=require_permission("users.manage",global_scope=True)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        requested_role=identity.get_role(str(payload.get("global_role_id","")))
        if requested_role is None or requested_role["scope_type"]!="GLOBAL":
            return error("INVALID_ROLE","a Global role is required",400)
        if not set(requested_role["permissions"]).issubset(set(identity.permission_codes(actor))):
            return error("FORBIDDEN","you cannot invite an account above your own Global authority",403)
        try:
            user,token=identity.invite_user(
                username=str(payload.get("username","")),
                email=payload.get("email"),
                display_name=str(payload.get("display_name") or payload.get("username","")),
                global_role_id=str(payload.get("global_role_id","")),
                actor=actor,
            )
        except IdentityConflictError as exc:
            return error("ACCOUNT_CONFLICT",str(exc),409)
        except (ValueError,IdentityPolicyError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        return ok({
            "user":{"username":user["username"],"email":user["email"],"display_name":user["display_name"],"status":user["status"]},
            "invitation_token":token,
            "delivery":"copy_token_securely",
        }),201

    @api.post("/identity/users/<username>/password-reset")
    def issue_identity_password_reset(username):
        denied=require_permission("users.manage",global_scope=True)
        if denied is not None:
            return denied
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        target=identity.get_user(username)
        if target is None:
            return error("NOT_FOUND","account not found",404)
        target_profile=identity_profile(username)
        if target_profile and not set(target_profile["permissions"]).issubset(set(identity.permission_codes(actor))):
            return error("FORBIDDEN","you cannot reset credentials for an account above your Global authority",403)
        try:
            token=identity.issue_password_reset(username,actor)
        except IdentityNotFoundError as exc:
            return error("NOT_FOUND",str(exc),404)
        except (ValueError,IdentityPolicyError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        return ok({"username":username,"reset_token":token,"delivery":"copy_token_securely"})

    @api.patch("/identity/users/<username>")
    def update_identity_user(username):
        denied=require_permission("users.manage",global_scope=True)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        target_profile=identity_profile(username)
        if target_profile and not set(target_profile["permissions"]).issubset(set(identity.permission_codes(actor))):
            return error("FORBIDDEN","you cannot change the status of an account above your Global authority",403)
        try:
            user=identity.set_user_status(username,str(payload.get("status","")),actor)
        except IdentityNotFoundError as exc:
            return error("NOT_FOUND",str(exc),404)
        except (ValueError,IdentityPolicyError) as exc:
            return error("ACCOUNT_POLICY",str(exc),409)
        if user is None:
            return error("INVALID_REQUEST","status is required",400)
        return ok({"username":user["username"],"status":user["status"]})

    @api.post("/identity/users/<username>/sessions/revoke")
    def revoke_identity_sessions(username):
        denied=require_permission("users.manage",global_scope=True)
        if denied is not None:
            return denied
        count=identity.revoke_sessions(username)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        identity.record_audit(actor,"SESSIONS_REVOKED","USER",username,{"count":count})
        return ok({"username":username,"revoked_sessions":count})

    @api.get("/identity/roles")
    def identity_roles():
        denied=require_permission("roles.read",global_scope=True)
        if denied is not None:
            return denied
        scope=request.args.get("scope")
        return ok({"items":identity.list_roles(scope)})

    @api.post("/identity/roles")
    def create_identity_role():
        denied=require_permission("roles.manage",global_scope=True)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        try:
            role=identity.create_role(
                name=str(payload.get("name","")),
                scope_type=str(payload.get("scope_type","")),
                description=str(payload.get("description","")),
                actor=actor,
            )
        except IdentityConflictError as exc:
            return error("ROLE_CONFLICT",str(exc),409)
        except ValueError as exc:
            return error("INVALID_REQUEST",str(exc),400)
        return ok(role),201

    @api.get("/identity/permissions")
    def identity_permissions():
        denied=require_permission("permissions.read",global_scope=True)
        if denied is not None:
            return denied
        return ok({"items":identity.list_permissions()})

    @api.put("/identity/roles/<role_id>/permissions")
    def set_identity_role_permissions(role_id):
        denied=require_permission("roles.manage",global_scope=True)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        try:
            requested_permissions=payload.get("permissions")
            actor_permissions=set(identity.permission_codes(actor))
            if not isinstance(requested_permissions,list) or not set(requested_permissions).issubset(actor_permissions):
                return error("FORBIDDEN","you cannot grant permissions above your own Global authority",403)
            role=identity.set_role_permissions(role_id,requested_permissions,actor)
        except IdentityNotFoundError as exc:
            return error("NOT_FOUND",str(exc),404)
        except (ValueError,IdentityPolicyError) as exc:
            return error("ROLE_POLICY",str(exc),400)
        return ok(role)

    @api.delete("/identity/roles/<role_id>")
    def delete_identity_role(role_id):
        denied=require_permission("roles.manage",global_scope=True)
        if denied is not None:
            return denied
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        try:
            identity.delete_role(role_id,actor)
        except IdentityNotFoundError as exc:
            return error("NOT_FOUND",str(exc),404)
        except IdentityPolicyError as exc:
            return error("ROLE_POLICY",str(exc),409)
        return ok({"deleted":True,"role_id":role_id})

    @api.put("/identity/users/<username>/role")
    def assign_identity_global_role(username):
        denied=require_permission("users.manage",global_scope=True)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        role_id=str(payload.get("role_id",""))
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        role=identity.get_role(role_id)
        if role is None or role["scope_type"]!="GLOBAL":
            return error("INVALID_ROLE","a Global role is required",400)
        actor_permissions=set(identity.permission_codes(actor))
        if not set(role["permissions"]).issubset(actor_permissions):
            return error("FORBIDDEN","you cannot assign permissions above your own Global authority",403)
        try:
            identity.assign_role(username=username,role_id=role_id,scope_type="GLOBAL",scope_id="*",actor=actor)
        except IdentityNotFoundError as exc:
            return error("NOT_FOUND",str(exc),404)
        except (ValueError,IdentityPolicyError) as exc:
            return error("ROLE_POLICY",str(exc),409)
        return ok({"username":username,"role_id":role_id})

    @api.put("/identity/projects/<project_id>/users/<username>/role")
    def assign_identity_project_role(project_id,username):
        denied=require_permission("members.manage",project_id=project_id)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        role_id=str(payload.get("role_id",""))
        if membership_repository.get(username,project_id) is None:
            return error("NOT_FOUND","Project membership not found",404)
        role=identity.get_role(role_id)
        if role is None or role["scope_type"]!="PROJECT":
            return error("INVALID_ROLE","a Project role is required",400)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        actor_permissions=set(identity.permission_codes(actor,project_id))
        if not set(role["permissions"]).issubset(actor_permissions):
            return error("FORBIDDEN","you cannot assign permissions above your effective Project authority",403)
        try:
            current_membership=membership_repository.get(username,project_id)
            if current_membership is None:
                return error("NOT_FOUND","Project membership not found",404)
            if current_membership.role=="OWNER" and role["name"]!="OWNER":
                owner_count=sum(item.role=="OWNER" for item in membership_repository.list_for_project(project_id))
                if owner_count<=1:
                    return error("LAST_PROJECT_OWNER","the last Project Owner cannot be demoted",409)
            now=datetime.now(timezone.utc).isoformat()
            base_role=role["name"] if role["name"] in {"OWNER","ADMIN","OPERATOR","VIEWER"} else "VIEWER"
            with query.database.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE project_memberships SET role=?,created_at=?,created_by=? WHERE username=? AND project_id=?",
                    (base_role,now,actor,username,project_id),
                )
                connection.execute(
                    """INSERT INTO role_assignments(username,role_id,scope_type,scope_id,created_at,created_by)
                       VALUES(?,?,'PROJECT',?,?,?)
                       ON CONFLICT(username,scope_type,scope_id) DO UPDATE SET
                         role_id=excluded.role_id,created_at=excluded.created_at,created_by=excluded.created_by""",
                    (username,role_id,project_id,now,actor),
                )
                connection.execute(
                    """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    ("AUD-"+new_resource_id(),actor,"PROJECT_MEMBER_ROLE_CHANGED","PROJECT",project_id,
                     json.dumps({"username":username,"role_id":role_id},sort_keys=True),now),
                )
        except IdentityNotFoundError as exc:
            return error("NOT_FOUND",str(exc),404)
        except (ValueError,IdentityPolicyError) as exc:
            return error("ROLE_POLICY",str(exc),409)
        return ok({"username":username,"project_id":project_id,"role_id":role_id})

    @api.get("/identity/audit")
    def identity_audit():
        denied=require_permission("audit.read",global_scope=True)
        if denied is not None:
            return denied
        try:
            limit=int(request.args.get("limit","100"))
        except ValueError:
            return error("INVALID_REQUEST","limit must be an integer",400)
        return ok({"items":identity.list_audit(limit=limit,resource_type=request.args.get("resource_type"))})

    # ---- Organization / Project / Lab ownership APIs (Stage B / P08) ----
    def project_role_id(username,project_id):
        with query.database.connection() as connection:
            row=connection.execute(
                """SELECT role_id FROM role_assignments
                   WHERE username=? AND scope_type='PROJECT' AND scope_id=?""",
                (username,project_id),
            ).fetchone()
        return row["role_id"] if row else None

    def serialize_organization(item):
        return {
            "organization_id":item.organization_id,"slug":item.slug,"name":item.name,
            "status":item.status.value,"created_at":item.created_at.isoformat(),
            "updated_at":item.updated_at.isoformat(),
        }

    def serialize_project(item):
        return {
            "project_id":item.project_id,"organization_id":item.organization_id,
            "slug":item.slug,"name":item.name,"status":item.status.value,
            "created_at":item.created_at.isoformat(),"updated_at":item.updated_at.isoformat(),
        }

    def serialize_lab(item):
        return {
            "lab_id":item.lab_id,"project_id":item.project_id,"name":item.name,
            "provider_id":item.provider_id,"topology_version":item.topology_version,
            "status":item.status.value,"created_at":item.created_at.isoformat(),
            "updated_at":item.updated_at.isoformat(),
        }

    @api.get("/workspace/organizations")
    def workspace_organizations():
        denied=require("view",global_scope=True)
        if denied is not None:
            return denied
        raw=session.get("netregress_user") or {}
        wildcard=session.get("netregress_user") is None or tuple(raw.get("projects",()))==("*",)
        items=organization_repository.list()
        if not wildcard and "organizations.manage" not in identity.permission_codes(str(raw.get("username",""))):
            allowed=set(identity.project_ids_for_user(str(raw.get("username",""))))
            visible={
                project.organization_id for project_id in allowed
                if (project:=project_repository.get(project_id)) is not None
            }
            items=[item for item in items if item.organization_id in visible]
        return ok({"items":[serialize_organization(item) for item in items]})

    @api.post("/workspace/organizations")
    def create_workspace_organization():
        denied=require_permission("organizations.manage",global_scope=True)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        try:
            now=datetime.now(timezone.utc)
            item=Organization(
                new_resource_id(),str(payload.get("slug","")).strip().lower(),
                str(payload.get("name","")).strip(),now,now,
            )
            organization_repository.save(item)
        except (ValueError,ResourceValidationError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except RepositoryConflictError as exc:
            return error("RESOURCE_CONFLICT",str(exc),409)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        identity.record_audit(actor,"ORGANIZATION_CREATED","ORGANIZATION",item.organization_id,{"slug":item.slug})
        return ok(serialize_organization(item)),201

    @api.patch("/workspace/organizations/<organization_id>")
    def update_workspace_organization(organization_id):
        denied=require_permission("organizations.manage",global_scope=True)
        if denied is not None:
            return denied
        item=organization_repository.get(organization_id)
        if item is None:
            return error("NOT_FOUND","Organization not found",404)
        payload=request.get_json(silent=True) or {}
        try:
            updated=Organization(
                item.organization_id,
                str(payload.get("slug",item.slug)).strip().lower(),
                str(payload.get("name",item.name)).strip(),
                item.created_at,datetime.now(timezone.utc),
                ResourceStatus(str(payload.get("status",item.status.value)).upper()),
            )
            organization_repository.update(updated)
        except (ValueError,ResourceValidationError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except RepositoryConflictError as exc:
            return error("RESOURCE_CONFLICT",str(exc),409)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        identity.record_audit(actor,"ORGANIZATION_UPDATED","ORGANIZATION",organization_id,{"status":updated.status.value})
        return ok(serialize_organization(updated))

    @api.get("/workspace/projects")
    def workspace_projects():
        denied=require("view",global_scope=True)
        if denied is not None:
            return denied
        raw=session.get("netregress_user") or {}
        wildcard=session.get("netregress_user") is None or tuple(raw.get("projects",()))==("*",)
        if wildcard:
            items=[]
            for organization in organization_repository.list():
                items.extend(project_repository.list_for_organization(organization.organization_id))
        else:
            items=[
                project_repository.get(project_id)
                for project_id in identity.project_ids_for_user(str(raw.get("username","")))
            ]
            items=[item for item in items if item is not None]
        organization_id=request.args.get("organization_id")
        if organization_id:
            items=[item for item in items if item.organization_id==organization_id]
        return ok({"items":[serialize_project(item) for item in items]})

    @api.post("/workspace/projects")
    def create_workspace_project():
        denied=require_permission("projects.manage",global_scope=True)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        organization_id=str(payload.get("organization_id","")).strip()
        if organization_repository.get(organization_id) is None:
            return error("NOT_FOUND","Organization not found",404)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        now=datetime.now(timezone.utc)
        try:
            item=Project(
                new_resource_id(),organization_id,
                str(payload.get("slug","")).strip().lower(),
                str(payload.get("name","")).strip(),now,now,
            )
            with query.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO projects(project_id,organization_id,slug,name,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (item.project_id,item.organization_id,item.slug,item.name,item.status.value,now.isoformat(),now.isoformat()),
                )
                connection.execute(
                    """INSERT INTO project_memberships(username,project_id,role,created_at,created_by)
                       VALUES(?,?,'OWNER',?,?)""",
                    (actor,item.project_id,now.isoformat(),actor),
                )
                connection.execute(
                    """INSERT INTO role_assignments(username,role_id,scope_type,scope_id,created_at,created_by)
                       VALUES(?,?,'PROJECT',?,?,?)""",
                    (actor,"project_owner",item.project_id,now.isoformat(),actor),
                )
        except (ValueError,ResourceValidationError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc) or "FOREIGN KEY constraint failed" in str(exc):
                return error("RESOURCE_CONFLICT","Project slug or parent relationship conflicts with existing data",409)
            return error("INTERNAL_ERROR","Project creation failed",500,{"type":type(exc).__name__})
        identity.record_audit(actor,"PROJECT_CREATED","PROJECT",item.project_id,{"organization_id":organization_id})
        return ok(serialize_project(item)),201

    @api.get("/workspace/projects/<project_id>")
    def workspace_project_detail(project_id):
        denied=require("view",project_id=project_id)
        if denied is not None:
            return denied
        item=project_repository.get(project_id)
        if item is None:
            return error("NOT_FOUND","Project not found",404)
        return ok({
            "project":serialize_project(item),
            "organization":serialize_organization(organization_repository.get(item.organization_id)),
            "labs":[serialize_lab(lab) for lab in lab_repository.list_for_project(project_id)],
        })

    @api.patch("/workspace/projects/<project_id>")
    def update_workspace_project(project_id):
        denied=require_permission("projects.manage",project_id=project_id)
        if denied is not None:
            return denied
        item=project_repository.get(project_id)
        if item is None:
            return error("NOT_FOUND","Project not found",404)
        payload=request.get_json(silent=True) or {}
        try:
            updated=Project(
                item.project_id,item.organization_id,
                str(payload.get("slug",item.slug)).strip().lower(),
                str(payload.get("name",item.name)).strip(),
                item.created_at,datetime.now(timezone.utc),
                ResourceStatus(str(payload.get("status",item.status.value)).upper()),
            )
            project_repository.update(updated)
        except (ValueError,ResourceValidationError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except RepositoryConflictError as exc:
            return error("RESOURCE_CONFLICT",str(exc),409)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        identity.record_audit(actor,"PROJECT_UPDATED","PROJECT",project_id,{"status":updated.status.value})
        return ok(serialize_project(updated))

    @api.get("/workspace/projects/<project_id>/labs")
    def workspace_labs(project_id):
        denied=require("view",project_id=project_id)
        if denied is not None:
            return denied
        return ok({"items":[serialize_lab(item) for item in lab_repository.list_for_project(project_id)]})

    @api.post("/workspace/projects/<project_id>/labs")
    def create_workspace_lab(project_id):
        denied=require_permission("labs.manage",project_id=project_id)
        if denied is not None:
            return denied
        if project_repository.get(project_id) is None:
            return error("NOT_FOUND","Project not found",404)
        payload=request.get_json(silent=True) or {}
        now=datetime.now(timezone.utc)
        try:
            item=Lab(
                new_resource_id(),project_id,
                str(payload.get("name","")).strip(),
                str(payload.get("provider_id","")).strip(),
                now,now,
            )
            lab_repository.save(item)
        except (ValueError,ResourceValidationError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except RepositoryConflictError as exc:
            return error("RESOURCE_CONFLICT",str(exc),409)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        identity.record_audit(actor,"LAB_CREATED","LAB",item.lab_id,{"project_id":project_id})
        return ok(serialize_lab(item)),201

    @api.patch("/workspace/labs/<lab_id>")
    def update_workspace_lab(lab_id):
        item=lab_repository.get(lab_id)
        if item is None:
            return error("NOT_FOUND","Lab not found",404)
        denied=require_permission("labs.manage",project_id=item.project_id)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        try:
            updated=Lab(
                item.lab_id,item.project_id,
                str(payload.get("name",item.name)).strip(),
                str(payload.get("provider_id",item.provider_id)).strip(),
                item.created_at,datetime.now(timezone.utc),
                int(payload.get("topology_version",item.topology_version)),
                ResourceStatus(str(payload.get("status",item.status.value)).upper()),
            )
            lab_repository.update(updated)
        except (ValueError,TypeError,ResourceValidationError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except RepositoryConflictError as exc:
            return error("RESOURCE_CONFLICT",str(exc),409)
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        identity.record_audit(actor,"LAB_UPDATED","LAB",lab_id,{"project_id":item.project_id})
        return ok(serialize_lab(updated))

    @api.get("/workspace/projects/<project_id>/members")
    def workspace_project_members(project_id):
        denied=require("view",project_id=project_id)
        if denied is not None:
            return denied
        return ok({"items":[{
            "username":item.username,"project_id":item.project_id,"role":item.role,
            "created_at":item.created_at.isoformat(),"created_by":item.created_by,
            "role_id":project_role_id(item.username,project_id),
        } for item in membership_repository.list_for_project(project_id)]})

    @api.post("/workspace/projects/<project_id>/members")
    def add_workspace_project_member(project_id):
        denied=require_permission("members.manage",project_id=project_id)
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        username=str(payload.get("username","")).strip()
        role_id=str(payload.get("role_id","")).strip()
        role_name=str(payload.get("role","VIEWER")).upper()
        actor=str((session.get("netregress_user") or {}).get("username","local"))
        user=identity.get_user(username)
        if user is None:
            return error("UNKNOWN_USER","Invite the account before assigning Project membership",404)
        if user["status"] not in {"ACTIVE","INVITED"}:
            return error("ACCOUNT_INACTIVE","Only active or invited accounts may be assigned",409)
        if role_id:
            role=identity.get_role(role_id)
            if role is None or role["scope_type"]!="PROJECT":
                return error("INVALID_ROLE","a Project role is required",400)
        else:
            if role_name not in {"OWNER","ADMIN","OPERATOR","VIEWER"}:
                return error("INVALID_ROLE","unsupported built-in Project role",400)
            role_id="project_"+role_name.lower()
            role=identity.get_role(role_id)
        actor_permissions=set(identity.permission_codes(actor,project_id))
        if not set(role["permissions"]).issubset(actor_permissions):
            return error("FORBIDDEN","you cannot grant permissions above your effective Project authority",403)
        # The legacy membership CHECK constraint remains stable. A custom role
        # uses VIEWER as its conservative compatibility label; role_assignments
        # is the effective permission source.
        membership_role=role_name if not payload.get("role_id") else "VIEWER"
        now=datetime.now(timezone.utc)
        try:
            with query.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO project_memberships(username,project_id,role,created_at,created_by)
                       VALUES(?,?,?,?,?)""",
                    (username,project_id,membership_role,now.isoformat(),actor),
                )
                connection.execute(
                    """INSERT INTO role_assignments(username,role_id,scope_type,scope_id,created_at,created_by)
                       VALUES(?,?,'PROJECT',?,?,?)
                       ON CONFLICT(username,scope_type,scope_id) DO UPDATE SET
                         role_id=excluded.role_id,created_at=excluded.created_at,created_by=excluded.created_by""",
                    (username,role_id,project_id,now.isoformat(),actor),
                )
                connection.execute(
                    """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    ("AUD-"+new_resource_id(),actor,"PROJECT_MEMBER_ASSIGNED","PROJECT",project_id,
                     json.dumps({"username":username,"role_id":role_id},sort_keys=True),now.isoformat()),
                )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                return error("MEMBERSHIP_EXISTS","user already has membership in this Project",409)
            if "FOREIGN KEY constraint failed" in str(exc):
                return error("NOT_FOUND","Project or role no longer exists",404)
            return error("INTERNAL_ERROR","Project membership assignment failed",500,{"type":type(exc).__name__})
        return ok({"username":username,"project_id":project_id,"role_id":role_id,"role":membership_role}),201

    @api.delete("/workspace/projects/<project_id>/members/<username>")
    def remove_workspace_project_member(project_id,username):
        denied=require_permission("members.manage",project_id=project_id)
        if denied is not None:
            return denied
        memberships=membership_repository.list_for_project(project_id)
        target=next((item for item in memberships if item.username==username),None)
        if target is None:
            return error("NOT_FOUND","Project membership not found",404)
        if target.role=="OWNER" and sum(item.role=="OWNER" for item in memberships)<=1:
            return error("LAST_PROJECT_OWNER","the last Project Owner cannot be removed",409)
        now=datetime.now(timezone.utc).isoformat()
        with query.database.transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM project_memberships WHERE username=? AND project_id=?",
                (username,project_id),
            )
            connection.execute(
                "DELETE FROM role_assignments WHERE username=? AND scope_type='PROJECT' AND scope_id=?",
                (username,project_id),
            )
            connection.execute(
                """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
                   VALUES(?,?,?,?,?,?,?)""",
                ("AUD-"+new_resource_id(),str((session.get("netregress_user") or {}).get("username","local")),
                 "PROJECT_MEMBER_REVOKED","PROJECT",project_id,
                 json.dumps({"username":username},sort_keys=True),now),
            )
        return ok({"removed":True,"username":username,"project_id":project_id})

    def _credential_actor() -> str:
        return str((session.get("netregress_user") or {}).get("username","local"))

    def _credential_ssh_verifier(record, secret):
        credential_type=record.get("credential_type")
        if credential_type not in {"SSH_PASSWORD","SSH_PRIVATE_KEY"}:
            return "UNAVAILABLE","This credential type has no configured protocol verification adapter."
        try:
            device=load_devices().get(str(record["device_id"]))
            if not isinstance(device,dict):
                return "UNAVAILABLE","The selected device is not present in the configured device inventory."
            host=str(device.get("host","")).strip()
            username=str(record.get("username") or device.get("username") or "").strip()
            port=int(device.get("port",22))
            if not host or not username or not 1 <= port <= 65535:
                return "UNAVAILABLE","The selected device is missing its host, username or valid SSH port."
            import io
            import paramiko
            pkey=None
            password=None
            if credential_type=="SSH_PASSWORD":
                password=secret
            else:
                key_classes=[
                    getattr(paramiko,"Ed25519Key",None),
                    getattr(paramiko,"ECDSAKey",None),
                    getattr(paramiko,"RSAKey",None),
                    getattr(paramiko,"DSSKey",None),
                ]
                for key_class in key_classes:
                    if key_class is None:
                        continue
                    try:
                        pkey=key_class.from_private_key(io.StringIO(secret))
                        break
                    except Exception:
                        continue
                if pkey is None:
                    return "FAILED","The stored private key could not be parsed; encrypted keys are not supported by this verifier."
            client=paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            try:
                client.connect(
                    hostname=host,port=port,username=username,password=password,pkey=pkey,
                    allow_agent=False,look_for_keys=False,timeout=6,auth_timeout=6,banner_timeout=6,
                )
                _stdin,stdout,_stderr=client.exec_command("true",timeout=6)
                exit_code=stdout.channel.recv_exit_status()
                if exit_code==0:
                    return "VERIFIED","SSH authentication and the harmless read-only health probe succeeded."
                return "FAILED","SSH connected, but the read-only health probe returned a non-zero status."
            finally:
                client.close()
        except Exception as exc:
            return "FAILED","SSH verification failed ("+type(exc).__name__+"); check reachability, credentials and trusted host keys."

    @api.get("/credentials")
    def list_managed_credentials():
        project_id=str(request.args.get("project_id","")).strip()
        if not project_id:
            return error("INVALID_REQUEST","project_id query parameter is required",400)
        denied=require_permission("credentials.read",project_id=project_id)
        if denied is not None:
            return denied
        device_id=str(request.args.get("device_id","")).strip() or None
        return ok({"items":credential_vault.list(project_id,device_id=device_id)})

    @api.post("/credentials")
    def create_managed_credential():
        payload=request.get_json(silent=True) or {}
        project_id=str(payload.get("project_id","")).strip()
        denied=require_permission("credentials.manage",project_id=project_id)
        if denied is not None:
            return denied
        if project_repository.get(project_id) is None:
            return error("NOT_FOUND","Project not found",404)
        if not isinstance(payload.get("secret"),str):
            return error("INVALID_REQUEST","secret is required",400)
        idem_payload={
            "project_id":project_id,"device_id":payload.get("device_id"),
            "label":payload.get("label"),"credential_type":payload.get("credential_type"),
            "username":payload.get("username"),
            "secret_sha256":hashlib.sha256(payload["secret"].encode("utf-8")).hexdigest(),
        }
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/credentials",idem_payload)
        if security_error is not None:
            return security_error
        if cached is not None:
            return jsonify(cached.response),cached.status_code
        try:
            item=credential_vault.create(
                project_id=project_id,device_id=payload.get("device_id"),
                label=payload.get("label"),credential_type=payload.get("credential_type"),
                username=payload.get("username"),secret=payload["secret"],actor=_credential_actor(),
            )
        except (ValueError,CredentialVaultPolicyError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except CredentialVaultNotFound as exc:
            return error("NOT_FOUND",str(exc),404)
        except CredentialVaultError as exc:
            return error("CREDENTIAL_STORE_UNAVAILABLE",str(exc),503)
        idempotency_store_response("/api/v1/credentials",key,request_hash,item,201)
        return ok(item),201

    @api.post("/credentials/<credential_id>/rotate")
    def rotate_managed_credential(credential_id):
        item=credential_vault.get(credential_id)
        if item is None:
            return error("NOT_FOUND","Credential not found",404)
        denied=require_permission("credentials.manage",project_id=item["project_id"])
        if denied is not None:
            return denied
        payload=request.get_json(silent=True) or {}
        secret=payload.get("secret")
        if not isinstance(secret,str):
            return error("INVALID_REQUEST","secret is required",400)
        idem_payload={
            "credential_id":credential_id,
            "secret_sha256":hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            "username":payload.get("username"),
        }
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/credentials/"+credential_id+"/rotate",idem_payload)
        if security_error is not None:
            return security_error
        if cached is not None:
            return jsonify(cached.response),cached.status_code
        try:
            updated=credential_vault.rotate(
                credential_id,secret=secret,username=payload.get("username"),actor=_credential_actor(),
            )
        except (ValueError,CredentialVaultPolicyError) as exc:
            return error("INVALID_REQUEST",str(exc),400)
        except CredentialVaultNotFound as exc:
            return error("NOT_FOUND",str(exc),404)
        except CredentialVaultError as exc:
            return error("CREDENTIAL_ROTATION_FAILED",str(exc),409)
        idempotency_store_response("/api/v1/credentials/"+credential_id+"/rotate",key,request_hash,updated,200)
        return ok(updated)

    @api.post("/credentials/<credential_id>/verify")
    def verify_managed_credential(credential_id):
        item=credential_vault.get(credential_id)
        if item is None:
            return error("NOT_FOUND","Credential not found",404)
        denied=require_permission("credentials.verify",project_id=item["project_id"])
        if denied is not None:
            return denied
        idem_payload={"credential_id":credential_id,"operation":"verify"}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/credentials/"+credential_id+"/verify",idem_payload)
        if security_error is not None:
            return security_error
        if cached is not None:
            return jsonify(cached.response),cached.status_code
        try:
            result=credential_vault.verify(
                credential_id,actor=_credential_actor(),verifier=_credential_ssh_verifier,
            )
        except CredentialVaultNotFound as exc:
            return error("NOT_FOUND",str(exc),404)
        except CredentialVaultPolicyError as exc:
            return error("INVALID_TRANSITION",str(exc),409)
        except CredentialVaultError as exc:
            return error("CREDENTIAL_VERIFICATION_FAILED",str(exc),409)
        idempotency_store_response("/api/v1/credentials/"+credential_id+"/verify",key,request_hash,result,200)
        return ok(result)

    @api.delete("/credentials/<credential_id>")
    def revoke_managed_credential(credential_id):
        item=credential_vault.get(credential_id)
        if item is None:
            return error("NOT_FOUND","Credential not found",404)
        denied=require_permission("credentials.manage",project_id=item["project_id"])
        if denied is not None:
            return denied
        idem_payload={"credential_id":credential_id,"operation":"revoke"}
        key,request_hash,cached,security_error=idempotency_preflight("/api/v1/credentials/"+credential_id+"/revoke",idem_payload)
        if security_error is not None:
            return security_error
        if cached is not None:
            return jsonify(cached.response),cached.status_code
        try:
            result=credential_vault.revoke(credential_id,actor=_credential_actor())
        except CredentialVaultPolicyError as exc:
            return error("INVALID_TRANSITION",str(exc),409)
        except CredentialVaultError as exc:
            return error("CREDENTIAL_REVOCATION_FAILED",str(exc),409)
        idempotency_store_response("/api/v1/credentials/"+credential_id+"/revoke",key,request_hash,result,200)
        if not result["secret_deleted"]:
            result["warning"]="Credential is revoked, but the provider did not confirm deletion of the underlying secret."
        return ok(result)


    @api.get("/configuration/schemas")
    def list_configuration_schemas():
        project_id=str(request.args.get("project_id","")).strip()
        if not project_id:
            return error("INVALID_REQUEST","project_id query parameter is required",400)
        denied=require_permission("configurations.read",project_id=project_id)
        if denied is not None:
            return denied
        if project_repository.get(project_id) is None:
            return error("NOT_FOUND","Project not found",404)
        return ok({"items":configuration_schemas.list(project_id)})

    @api.post("/configuration/schemas")
    def register_configuration_schema():
        payload=request.get_json(silent=True) or {}
        project_id=str(payload.get("project_id","")).strip()
        denied=require_permission("configurations.manage",project_id=project_id)
        if denied is not None:
            return denied
        if project_repository.get(project_id) is None:
            return error("NOT_FOUND","Project not found",404)
        try:
            definition=payload.get("definition")
            if not isinstance(definition,dict):
                raise ConfigurationSchemaError("definition must be a JSON schema object")
            canonical=json.dumps(definition,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
            idem_payload={
                "project_id":project_id,"schema_id":payload.get("schema_id"),
                "version":payload.get("version"),"name":payload.get("name"),
                "definition_sha256":hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
            key,request_hash,cached,security_error=idempotency_preflight("/api/v1/configuration/schemas",idem_payload)
            if security_error is not None:
                return security_error
            if cached is not None:
                return jsonify(cached.response),cached.status_code
            item=configuration_schemas.register(
                project_id=project_id,schema_id=payload.get("schema_id"),
                version=payload.get("version"),name=payload.get("name"),
                definition=definition,
                actor=str((session.get("netregress_user") or {}).get("username","local")),
            )
        except (ConfigurationSchemaError,TypeError,ValueError) as exc:
            return error("INVALID_CONFIGURATION_SCHEMA",str(exc),400)
        idempotency_store_response("/api/v1/configuration/schemas",key,request_hash,item,201)
        return ok(item),201

    return api

def create_query(database_path:str|Path)->DashboardQueryService:return DashboardQueryService(SQLiteDatabase(database_path))
