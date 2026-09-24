from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request, send_file

from lib.repositories import SQLiteDatabase
from .query import DashboardQueryError, DashboardQueryService


def create_api_blueprint(query: DashboardQueryService) -> Blueprint:
    api = Blueprint("api_v1", __name__, url_prefix="/api/v1")

    def ok(data: Any):
        return jsonify({"data": data})

    def error(code: str, message: str, status: int, details=None):
        return jsonify({"error": {"code": code, "message": message, "details": details or {}}}), status

    def guarded(fn):
        try:
            return fn()
        except DashboardQueryError as exc:
            return error("NOT_FOUND", str(exc), 404)
        except (ValueError, TypeError) as exc:
            return error("INVALID_REQUEST", str(exc), 400)
        except Exception as exc:
            return error("INTERNAL_ERROR", "Dashboard query failed", 500, {"type": type(exc).__name__})

    @api.get("/runs")
    def runs():
        return guarded(lambda: ok(query.runs(
            firmware=request.args.get("firmware"),
            lab=request.args.get("lab"),
            profile=request.args.get("profile"),
            status=request.args.get("status"),
            outcome=request.args.get("outcome"),
            page=int(request.args.get("page", "1")),
            limit=int(request.args.get("limit", "50")),
        )))

    @api.get("/runs/<run_id>")
    def run_detail(run_id):
        return guarded(lambda: ok(query.get_run(run_id)))

    @api.get("/runs/<run_id>/tests")
    def run_tests(run_id):
        return guarded(lambda: ok({"items": query.tests(run_id)}))

    @api.get("/runs/<run_id>/tests/<test_result_id>")
    def run_test_detail(run_id, test_result_id):
        return guarded(lambda: ok(query.test(run_id, test_result_id)))

    @api.get("/runs/<run_id>/metrics")
    def run_metrics(run_id):
        return guarded(lambda: ok({"items": query.metrics_for_run(run_id)}))

    @api.get("/tests/<path:test_id>/metrics")
    def test_metrics(test_id):
        return guarded(lambda: ok({"items": query.metrics_history(test_id)}))

    @api.get("/regressions")
    def regressions():
        baseline_id = request.args.get("baseline_run_id")
        current_id = request.args.get("current_run_id")
        if not baseline_id or not current_id:
            return error("MISSING_PARAMETER", "baseline_run_id and current_run_id are required", 400)
        return guarded(lambda: ok(query.regression(baseline_id, current_id)))

    @api.get("/runs/<run_id>/regressions")
    def run_regressions(run_id):
        baseline_id = request.args.get("baseline_run_id")
        if not baseline_id:
            return error("MISSING_PARAMETER", "baseline_run_id is required", 400)
        return guarded(lambda: ok(query.regression(baseline_id, run_id)))

    @api.get("/runs/<run_id>/telemetry")
    def run_telemetry(run_id):
        return guarded(lambda: ok({
            "environment_class": query.environment_class(run_id),
            "items": query.telemetry(run_id),
        }))

    @api.get("/runs/<run_id>/health")
    def run_health(run_id):
        return guarded(lambda: ok({"items": query.health(run_id)}))

    @api.get("/labs/<lab_id>/health")
    def lab_health(lab_id):
        return guarded(lambda: ok({"item": query.latest_lab_health(lab_id)}))

    @api.get("/artifacts")
    def artifacts():
        try:
            page = max(1, int(request.args.get("page", "1")))
            limit = min(200, max(1, int(request.args.get("limit", "50"))))
        except ValueError:
            return error("INVALID_REQUEST", "page and limit must be integers", 400)
        return guarded(lambda: ok(query.artifacts(
            run_id=request.args.get("run_id"),
            artifact_type=request.args.get("artifact_type"),
            page=page,
            limit=limit,
        )))

    @api.get("/artifacts/<artifact_id>")
    def artifact_detail(artifact_id):
        return guarded(lambda: ok(query.serialize_artifact(query.artifact(artifact_id))))

    @api.get("/artifacts/<artifact_id>/download")
    def artifact_download(artifact_id):
        try:
            artifact = query.artifact(artifact_id)
            token = os.getenv("NETREGRESS_DASHBOARD_TOKEN")
            remote = request.remote_addr not in {"127.0.0.1", "::1"}
            if token and request.headers.get("Authorization") != "Bearer " + token:
                return error("FORBIDDEN", "valid bearer token required", 403)
            if not token and remote:
                return error("FORBIDDEN", "remote artifact download requires NETREGRESS_DASHBOARD_TOKEN", 403)
            path = query._safe_artifact_path(artifact)
            if path is None:
                return error("ARTIFACT_UNAVAILABLE", "artifact is missing or failed integrity verification", 404)
            return send_file(path, as_attachment=True, download_name=artifact.display_name)
        except DashboardQueryError as exc:
            return error("NOT_FOUND", str(exc), 404)

    @api.get("/baselines")
    def baselines():
        return guarded(lambda: ok({"items": query.baselines()}))

    return api


def create_query(database_path: str | Path) -> DashboardQueryService:
    return DashboardQueryService(SQLiteDatabase(database_path))
