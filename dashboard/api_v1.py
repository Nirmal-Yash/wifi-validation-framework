from __future__ import annotations
import os
from pathlib import Path
from typing import Any,Callable
from functools import wraps
from flask import Blueprint,jsonify,request,session,send_file
from lib.repositories import SQLiteDatabase
from lib.security import AuthManager,AuthConfigurationError,AuthenticatedUser,Role
from .query import DashboardQueryError,DashboardQueryService

def create_api_blueprint(query:DashboardQueryService,auth_manager:AuthManager|None=None)->Blueprint:
    api=Blueprint("api_v1",__name__,url_prefix="/api/v1"); auth=auth_manager or AuthManager.from_env()
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
        try:auth.require_configured()
        except AuthConfigurationError as exc:return error("AUTH_NOT_CONFIGURED",str(exc),503)
        user=auth.authenticate(str(payload.get("username","")).strip(),str(payload.get("password","")))
        if user is None:return error("INVALID_CREDENTIALS","invalid credentials",401)
        session.clear();session["netregress_user"]={"username":user.username,"role":user.role.value,"projects":list(user.projects)};session.permanent=True
        return ok(session["netregress_user"])
    @api.post("/auth/logout")
    def logout():session.clear();return ok({"logged_out":True})
    @api.get("/auth/me")
    def me():
        raw=session.get("netregress_user");return ok(raw) if raw else error("UNAUTHENTICATED","authentication required",401)
    def protected(fn:Callable):
        @wraps(fn)
        def wrapper(*args,**kwargs):
            denied=require("view");return denied if denied is not None else fn(*args,**kwargs)
        return wrapper
    @api.get("/runs")
    @protected
    def runs():return guarded(lambda:ok(query.runs(firmware=request.args.get("firmware"),lab=request.args.get("lab"),profile=request.args.get("profile"),status=request.args.get("status"),outcome=request.args.get("outcome"),page=int(request.args.get("page","1")),limit=int(request.args.get("limit","50")))))
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
    @api.get("/baselines")
    @protected
    def baselines():return guarded(lambda:ok({"items":query.baselines()}))
    return api

def create_query(database_path:str|Path)->DashboardQueryService:return DashboardQueryService(SQLiteDatabase(database_path))
