from __future__ import annotations

import hashlib
import json
from pathlib import Path
from math import isfinite
from typing import Any, Mapping

from lib.domain import ArtifactType, TestResultStatus
from lib.domain.statistics import MeasurementEvaluationError, MeasurementPolicyEvaluator
from lib.repositories import (
    SQLiteArtifactRepository,
    SQLiteAttemptRepository,
    SQLiteBaselineRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteSyncQueueRepository,
    SQLiteTestResultRepository,
)
from lib.services.regression_intelligence import RegressionIntelligenceService
from lib.services.run_service import RunService
from lib.services.release_gate import ReleaseGateEvaluator, ReleaseGateInput
from lib.services.test_registry import TestRegistry
from lib.services.waiver_service import WaiverService


class DashboardQueryError(RuntimeError):
    pass


class DashboardQueryService:
    """Read-only query facade for the Flask/Jinja dashboard and /api/v1."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.database.initialize()
        self.run_repository = SQLiteRunRepository(database)
        self.attempt_repository = SQLiteAttemptRepository(database)
        self.result_repository = SQLiteTestResultRepository(database)
        self.artifact_repository = SQLiteArtifactRepository(database)
        self.event_repository = SQLiteEventRepository(database)
        self.baseline_repository = SQLiteBaselineRepository(database)
        self.test_registry = TestRegistry.default()
        self.run_service = RunService(
            self.run_repository,
            self.attempt_repository,
            self.event_repository,
            self.result_repository,
            self.baseline_repository,
        )
        self.regression_service = RegressionIntelligenceService(
            run_service=self.run_service,
            test_registry=self.test_registry,
        )
        self.results_root = Path(__file__).resolve().parents[2] / "results"

    @staticmethod
    def _iso(value: Any) -> str | None:
        return value.isoformat() if value is not None else None


    def operations_overview(
        self, project_id: str, *, lab_id: str | None = None,
        include_devices: bool = True, include_topology: bool = True,
        include_pipelines: bool = True, include_runs: bool = True,
        include_configuration: bool = True, include_evidence: bool = True,
        include_performance: bool = True,
    ) -> dict[str, Any]:
        """Aggregate persisted Project/Lab operations data without mutating state.

        Every section identifies its source and request observation time. Provider
        binding is configuration metadata only; this method never claims that a
        controller is reachable or healthy.
        """
        project_id = str(project_id or "").strip()
        lab_id = str(lab_id or "").strip() or None
        if not project_id:
            raise DashboardQueryError("project_id is required")

        from datetime import datetime, timezone

        observed_at = datetime.now(timezone.utc).isoformat()
        with self.database.read_only_connection() as connection:
            project = connection.execute(
                "SELECT project_id,organization_id,name,status,updated_at FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise DashboardQueryError("Project not found")

            lab_sql = (
                "SELECT lab_id,name,provider_id,status,topology_version,created_at,updated_at "
                "FROM labs WHERE project_id=?"
            )
            lab_params: list[object] = [project_id]
            if lab_id:
                lab_sql += " AND lab_id=?"
                lab_params.append(lab_id)
            lab_sql += " ORDER BY name COLLATE NOCASE,lab_id"
            labs = connection.execute(lab_sql, lab_params).fetchall()
            if lab_id and not labs:
                raise DashboardQueryError("Lab not found in this Project")

            lab_status_counts: dict[str, int] = {}
            for item in labs:
                status = str(item["status"])
                lab_status_counts[status] = lab_status_counts.get(status, 0) + 1
            all_lab_count = connection.execute(
                "SELECT COUNT(*) FROM labs WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            latest_lab_update = max((item["updated_at"] for item in labs if item["updated_at"]), default=None)

            scope_sql = " AND lab_id=?" if lab_id else ""
            scope_params: list[object] = [project_id] + ([lab_id] if lab_id else [])

            if include_devices:
                device_rows = connection.execute(
                    "SELECT status,COUNT(*) AS total,MAX(updated_at) AS last_updated_at "
                    "FROM devices WHERE project_id=?" + scope_sql + " GROUP BY status",
                    scope_params,
                ).fetchall()
                device_counts = {str(row["status"]): int(row["total"]) for row in device_rows}
                device_last_update = max((row["last_updated_at"] for row in device_rows if row["last_updated_at"]), default=None)
                devices = {
                    "access": "AVAILABLE",
                    "total": sum(device_counts.values()),
                    "active": device_counts.get("ACTIVE", 0),
                    "archived": device_counts.get("ARCHIVED", 0),
                    "by_status": device_counts,
                    "source": "devices",
                    "observed_at": observed_at,
                    "source_updated_at": device_last_update,
                }
            else:
                devices = {
                    "access": "RESTRICTED", "total": None, "active": None,
                    "archived": None, "by_status": None, "source": None,
                    "observed_at": None, "source_updated_at": None,
                }

            if include_topology:
                profile_filter = " AND (lab_id=? OR lab_id IS NULL)" if lab_id else ""
                profile_params: list[object] = [project_id] + ([lab_id] if lab_id else [])
                profile_rows = connection.execute(
                    "SELECT status,COUNT(*) AS total,MAX(updated_at) AS last_updated_at "
                    "FROM topology_profiles WHERE project_id=?" + profile_filter + " GROUP BY status",
                    profile_params,
                ).fetchall()
                profile_counts = {str(row["status"]): int(row["total"]) for row in profile_rows}
                profile_last_update = max((row["last_updated_at"] for row in profile_rows if row["last_updated_at"]), default=None)
                revision_rows = connection.execute(
                    "SELECT r.status,COUNT(*) AS total,MAX(COALESCE(r.published_at,r.created_at)) AS last_updated_at "
                    "FROM topology_revisions r JOIN topology_profiles p ON p.profile_id=r.profile_id "
                    "WHERE p.project_id=?" + profile_filter.replace("lab_id", "p.lab_id") + " GROUP BY r.status",
                    profile_params,
                ).fetchall()
                revision_counts = {str(row["status"]): int(row["total"]) for row in revision_rows}
                apply_rows = connection.execute(
                    "SELECT status,COUNT(*) AS total,MAX(COALESCE(completed_at,started_at,created_at)) AS last_updated_at "
                    "FROM topology_apply_records WHERE project_id=?" + scope_sql + " GROUP BY status",
                    scope_params,
                ).fetchall()
                apply_counts = {str(row["status"]): int(row["total"]) for row in apply_rows}
                latest_published_rows = connection.execute(
                    "SELECT p.profile_id,p.name,r.revision_id,r.revision_number,r.published_at "
                    "FROM topology_profiles p JOIN topology_revisions r ON r.profile_id=p.profile_id "
                    "WHERE p.project_id=? AND p.status='ACTIVE' AND r.status='PUBLISHED'"
                    + profile_filter.replace("lab_id", "p.lab_id")
                    + " ORDER BY r.published_at DESC,r.revision_number DESC LIMIT 20",
                    profile_params,
                ).fetchall()
                latest_published = [{
                    "profile_id": row["profile_id"],
                    "profile_name": row["name"],
                    "revision_id": row["revision_id"],
                    "revision_number": int(row["revision_number"]),
                    "published_at": row["published_at"],
                } for row in latest_published_rows]
                topology_last_update = max(
                    [value for value in (profile_last_update, *(row["last_updated_at"] for row in revision_rows), *(row["last_updated_at"] for row in apply_rows)) if value],
                    default=None,
                )
                topology = {
                    "access": "AVAILABLE",
                    "profiles": sum(profile_counts.values()),
                    "profiles_by_status": profile_counts,
                    "revisions": sum(revision_counts.values()),
                    "revisions_by_status": revision_counts,
                    "latest_published_revisions": latest_published,
                    "apply_records": sum(apply_counts.values()),
                    "apply_by_status": apply_counts,
                    "source": ["topology_profiles", "topology_revisions", "topology_apply_records"],
                    "observed_at": observed_at,
                    "source_updated_at": topology_last_update,
                }
            else:
                topology = {
                    "access": "RESTRICTED",
                    "profiles": None,
                    "profiles_by_status": None,
                    "revisions": None,
                    "revisions_by_status": None,
                    "latest_published_revisions": None,
                    "apply_records": None,
                    "apply_by_status": None,
                    "source": None,
                    "observed_at": None,
                    "source_updated_at": None,
                }

            if include_pipelines:
                pipeline_rows = connection.execute(
                    "SELECT status,COUNT(*) AS total,MAX(updated_at) AS last_updated_at "
                    "FROM pipeline_definitions WHERE project_id=?" + scope_sql + " GROUP BY status",
                    scope_params,
                ).fetchall()
                pipeline_counts = {str(row["status"]): int(row["total"]) for row in pipeline_rows}
                execution_rows = connection.execute(
                    "SELECT status,COUNT(*) AS total,MAX(COALESCE(completed_at,started_at,created_at)) AS last_activity_at "
                    "FROM pipeline_executions WHERE project_id=?" + scope_sql + " GROUP BY status",
                    scope_params,
                ).fetchall()
                execution_counts = {str(row["status"]): int(row["total"]) for row in execution_rows}
                step_scope_sql = " AND e.lab_id=?" if lab_id else ""
                step_rows = connection.execute(
                    "SELECT s.status,COUNT(*) AS total,"
                    "MAX(COALESCE(s.completed_at,s.started_at,s.created_at)) AS last_activity_at "
                    "FROM pipeline_steps s JOIN pipeline_executions e ON e.execution_id=s.execution_id "
                    "WHERE e.project_id=?" + step_scope_sql + " GROUP BY s.status",
                    scope_params,
                ).fetchall()
                step_counts = {str(row["status"]): int(row["total"]) for row in step_rows}
                pipeline_last_update = max(
                    [value for value in (
                        *(row["last_updated_at"] for row in pipeline_rows),
                        *(row["last_activity_at"] for row in execution_rows),
                        *(row["last_activity_at"] for row in step_rows),
                    ) if value],
                    default=None,
                )
                pipelines = {
                    "access": "AVAILABLE",
                    "total": sum(pipeline_counts.values()),
                    "active": pipeline_counts.get("ACTIVE", 0),
                    "by_status": pipeline_counts,
                    "executions": sum(execution_counts.values()),
                    "executions_by_status": execution_counts,
                    "queued": execution_counts.get("QUEUED", 0),
                    "running": execution_counts.get("RUNNING", 0),
                    "cancelling": execution_counts.get("CANCELLING", 0),
                    "active_executions": sum(execution_counts.get(value, 0) for value in ("QUEUED", "RUNNING", "CANCELLING")),
                    "recovery_required": execution_counts.get("RECOVERY_REQUIRED", 0),
                    "steps": sum(step_counts.values()),
                    "steps_by_status": step_counts,
                    "active_steps": sum(step_counts.get(value, 0) for value in ("PENDING", "RUNNING", "RETRY_WAIT")),
                    "failed_steps": step_counts.get("FAILED", 0),
                    "recovery_required_steps": step_counts.get("RECOVERY_REQUIRED", 0),
                    "source": ["pipeline_definitions", "pipeline_executions"],
                    "observed_at": observed_at,
                    "source_updated_at": pipeline_last_update,
                }
            else:
                pipelines = {
                    "access": "RESTRICTED",
                    "total": None, "active": None, "by_status": None,
                    "executions": None, "executions_by_status": None,
                    "queued": None, "running": None, "cancelling": None,
                    "active_executions": None, "recovery_required": None,
                    "steps": None, "steps_by_status": None, "active_steps": None,
                    "failed_steps": None, "recovery_required_steps": None,
                    "source": None, "observed_at": None, "source_updated_at": None,
                }

            if include_configuration:
                deployment_rows = connection.execute(
                    "SELECT status,COUNT(*) AS total,"
                    "MAX(COALESCE(completed_at,started_at,created_at)) AS last_activity_at "
                    "FROM device_configuration_deployments WHERE project_id=?"
                    + scope_sql + " GROUP BY status",
                    scope_params,
                ).fetchall()
                deployment_counts = {str(row["status"]): int(row["total"]) for row in deployment_rows}
                latest_deployment_row = connection.execute(
                    "SELECT deployment_id,device_id,lab_id,status,created_at,completed_at "
                    "FROM device_configuration_deployments WHERE project_id=?"
                    + scope_sql + " ORDER BY created_at DESC,deployment_id DESC LIMIT 1",
                    scope_params,
                ).fetchone()
                configuration_last_update = max(
                    (row["last_activity_at"] for row in deployment_rows if row["last_activity_at"]),
                    default=None,
                )
                configuration = {
                    "access": "AVAILABLE",
                    "deployments": sum(deployment_counts.values()),
                    "by_status": deployment_counts,
                    "applying": deployment_counts.get("APPLYING", 0),
                    "applied": deployment_counts.get("APPLIED", 0),
                    "partial": deployment_counts.get("PARTIAL", 0),
                    "failed": deployment_counts.get("FAILED", 0),
                    "latest": ({
                        "deployment_id": latest_deployment_row["deployment_id"],
                        "device_id": latest_deployment_row["device_id"],
                        "lab_id": latest_deployment_row["lab_id"],
                        "status": latest_deployment_row["status"],
                        "created_at": latest_deployment_row["created_at"],
                        "completed_at": latest_deployment_row["completed_at"],
                    } if latest_deployment_row else None),
                    "source": "device_configuration_deployments",
                    "observed_at": observed_at,
                    "source_updated_at": configuration_last_update,
                }
            else:
                configuration = {
                    "access": "RESTRICTED", "deployments": None, "by_status": None,
                    "applying": None, "applied": None, "partial": None, "failed": None,
                    "latest": None, "source": None, "observed_at": None,
                    "source_updated_at": None,
                }

            if include_runs:
                run_rows = connection.execute(
                    "SELECT lifecycle,outcome,COUNT(*) AS total,"
                    "MAX(COALESCE(completed_at,started_at,created_at)) AS last_activity_at "
                    "FROM runs WHERE project_id=?" + scope_sql + " GROUP BY lifecycle,outcome",
                    scope_params,
                ).fetchall()
                lifecycle_counts: dict[str, int] = {}
                outcome_counts: dict[str, int] = {}
                latest_run_activity = None
                for row in run_rows:
                    lifecycle = str(row["lifecycle"])
                    outcome = str(row["outcome"] or "PENDING")
                    count = int(row["total"])
                    lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + count
                    outcome_counts[outcome] = outcome_counts.get(outcome, 0) + count
                    timestamp = row["last_activity_at"]
                    if timestamp and (latest_run_activity is None or timestamp > latest_run_activity):
                        latest_run_activity = timestamp
                runs = {
                    "total": sum(lifecycle_counts.values()),
                    "by_lifecycle": lifecycle_counts,
                    "by_outcome": outcome_counts,
                    "active": sum(lifecycle_counts.get(value, 0) for value in ("QUEUED", "PREPARING", "LAB_HEALTH_CHECK", "RUNNING")),
                    "source": "runs",
                    "observed_at": observed_at,
                    "source_updated_at": latest_run_activity,
                }
            else:
                runs = {
                    "access": "RESTRICTED",
                    "total": None,
                    "by_lifecycle": None,
                    "by_outcome": None,
                    "active": None,
                    "source": None,
                    "observed_at": None,
                    "source_updated_at": None,
                }

            if include_evidence:
                evidence_rows = connection.execute(
                    "SELECT a.artifact_type,COUNT(*) AS total,MAX(a.created_at) AS last_created_at "
                    "FROM artifacts a JOIN runs r ON r.run_id=a.run_id "
                    "WHERE r.project_id=?" + (" AND r.lab_id=?" if lab_id else "")
                    + " AND a.soft_deleted_at IS NULL"
                    + " AND a.artifact_type IN ('TELEMETRY','LAB_HEALTH_SNAPSHOT') "
                    "GROUP BY a.artifact_type",
                    scope_params,
                ).fetchall()
                evidence_counts = {str(row["artifact_type"]): int(row["total"]) for row in evidence_rows}
                telemetry_rows = connection.execute(
                    "SELECT a.artifact_id,a.run_id,a.created_at "
                    "FROM artifacts a JOIN runs r ON r.run_id=a.run_id "
                    "WHERE r.project_id=?" + (" AND r.lab_id=?" if lab_id else "")
                    + " AND a.soft_deleted_at IS NULL AND a.artifact_type='TELEMETRY' "
                    "ORDER BY a.created_at DESC,a.artifact_id DESC LIMIT 200",
                    scope_params,
                ).fetchall()
                wifi_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
                valid_wifi_artifacts = 0
                for telemetry_row in telemetry_rows:
                    artifact = self.artifact_repository.get(str(telemetry_row["artifact_id"]))
                    snapshot = self._read_json_artifact(artifact) if artifact is not None else None
                    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("points"), list):
                        continue
                    valid_wifi_artifacts += 1
                    for point in snapshot["points"]:
                        if not isinstance(point, dict):
                            continue
                        name = str(point.get("metric") or "").strip()
                        unit = str(point.get("unit") or "").strip()
                        interface = str(point.get("interface") or snapshot.get("interface") or "").strip()
                        raw_value = point.get("value")
                        captured_at = point.get("captured_at") or snapshot.get("captured_at")
                        if (
                            not name or not unit or not interface
                            or isinstance(raw_value, bool)
                            or not isinstance(raw_value, (int, float))
                            or not isfinite(float(raw_value))
                            or not isinstance(captured_at, str) or not captured_at.strip()
                        ):
                            continue
                        key = (name, unit, interface)
                        value = float(raw_value)
                        group = wifi_groups.setdefault(key, {
                            "metric": name,
                            "unit": unit,
                            "interface": interface,
                            "sample_count": 0,
                            "sum_value": 0.0,
                            "min_value": value,
                            "max_value": value,
                            "latest_value": value,
                            "captured_at": captured_at,
                            "run_id": telemetry_row["run_id"],
                            "environment_class": point.get("environment_class") or snapshot.get("environment_class"),
                        })
                        group["sample_count"] += 1
                        group["sum_value"] += value
                        group["min_value"] = min(group["min_value"], value)
                        group["max_value"] = max(group["max_value"], value)
                        if captured_at >= group["captured_at"]:
                            group["latest_value"] = value
                            group["captured_at"] = captured_at
                            group["run_id"] = telemetry_row["run_id"]
                            group["environment_class"] = point.get("environment_class") or snapshot.get("environment_class")
                wifi_metrics = [{
                    "metric": item["metric"],
                    "unit": item["unit"],
                    "interface": item["interface"],
                    "sample_count": item["sample_count"],
                    "mean_value": item["sum_value"] / item["sample_count"],
                    "min_value": item["min_value"],
                    "max_value": item["max_value"],
                    "latest_value": item["latest_value"],
                    "captured_at": item["captured_at"],
                    "run_id": item["run_id"],
                    "environment_class": item["environment_class"],
                } for item in sorted(wifi_groups.values(), key=lambda item: (item["metric"], item["interface"]))]
                evidence_last_update = max(
                    [
                        value for value in (
                            *(row["last_created_at"] for row in evidence_rows),
                            *(item["captured_at"] for item in wifi_metrics),
                        ) if value
                    ],
                    default=None,
                )
                evidence = {
                    "access": "AVAILABLE",
                    "telemetry_artifacts": evidence_counts.get("TELEMETRY", 0),
                    "lab_health_snapshots": evidence_counts.get("LAB_HEALTH_SNAPSHOT", 0),
                    "valid_wifi_telemetry_artifacts": valid_wifi_artifacts,
                    "wifi_metrics": wifi_metrics,
                    "by_type": evidence_counts,
                    "source": ["artifacts", "runs"],
                    "observed_at": observed_at,
                    "source_updated_at": evidence_last_update,
                }
            else:
                evidence = {
                    "access": "RESTRICTED", "telemetry_artifacts": None,
                    "lab_health_snapshots": None, "valid_wifi_telemetry_artifacts": None,
                    "wifi_metrics": None, "by_type": None, "source": None,
                    "observed_at": None, "source_updated_at": None,
                }

            performance_metrics = []
            if include_performance:
                metric_scope_sql = " AND r.lab_id=?" if lab_id else ""
                metric_rows = connection.execute(
                    "SELECT m.name,m.unit,m.authoritative,s.value,s.captured_at,r.run_id,tr.test_id "
                    "FROM runs r "
                    "JOIN attempts a ON a.run_id=r.run_id "
                    "JOIN test_results tr ON tr.run_id=r.run_id AND tr.attempt_id=a.attempt_id "
                    "JOIN metrics m ON m.test_result_id=tr.test_result_id "
                    "JOIN samples s ON s.metric_id=m.metric_id "
                    "WHERE r.project_id=?" + metric_scope_sql
                    + " AND a.number=(SELECT MAX(a2.number) FROM attempts a2 WHERE a2.run_id=r.run_id)"
                    + " AND s.status='VALID' AND s.warmup=0 AND s.retried=0 AND s.captured_at IS NOT NULL"
                    + " AND (lower(m.name) LIKE '%throughput%' OR lower(m.name) LIKE '%bandwidth%'"
                    + " OR lower(m.name) LIKE '%goodput%' OR lower(m.name) LIKE '%latency%'"
                    + " OR lower(m.name) LIKE '%rtt%' OR lower(m.name) LIKE '%round_trip%'"
                    + " OR lower(m.name) LIKE '%packet_loss%' OR lower(m.name) LIKE '%jitter%'"
                    + " OR lower(m.name) LIKE '%utilization%' OR lower(m.name) LIKE '%data_rate%'"
                    + " OR lower(m.name) LIKE '%tx_rate%' OR lower(m.name) LIKE '%rx_rate%'"
                    + " OR lower(m.name) LIKE '%rssi%' OR lower(m.name) LIKE '%snr%')"
                    + " ORDER BY s.captured_at DESC,s.sequence DESC LIMIT 2000",
                    [project_id] + ([lab_id] if lab_id else []),
                ).fetchall()
                metric_groups: dict[tuple[str, str], dict[str, Any]] = {}
                for row in metric_rows:
                    metric_key = (str(row["name"]), str(row["unit"]))
                    value = float(row["value"])
                    if not isfinite(value):
                        continue
                    group = metric_groups.setdefault(metric_key, {
                        "name": metric_key[0],
                        "unit": metric_key[1],
                        "sample_count": 0,
                        "sum_value": 0.0,
                        "min_value": value,
                        "max_value": value,
                        "value": value,
                        "captured_at": row["captured_at"],
                        "run_id": row["run_id"],
                        "test_id": row["test_id"],
                        "authoritative": bool(row["authoritative"]),
                    })
                    group["sample_count"] += 1
                    group["sum_value"] += value
                    group["min_value"] = min(group["min_value"], value)
                    group["max_value"] = max(group["max_value"], value)
                    if row["captured_at"] >= group["captured_at"]:
                        group["value"] = value
                        group["captured_at"] = row["captured_at"]
                        group["run_id"] = row["run_id"]
                        group["test_id"] = row["test_id"]
                        group["authoritative"] = bool(row["authoritative"])
                performance_metrics = [{
                    "name": item["name"],
                    "unit": item["unit"],
                    "value": item["value"],
                    "mean_value": item["sum_value"] / item["sample_count"],
                    "min_value": item["min_value"],
                    "max_value": item["max_value"],
                    "sample_count": item["sample_count"],
                    "authoritative": item["authoritative"],
                    "captured_at": item["captured_at"],
                    "run_id": item["run_id"],
                    "test_id": item["test_id"],
                } for item in sorted(metric_groups.values(), key=lambda item: (item["name"], item["unit"]))]
                performance_source_updated = max(
                    (item["captured_at"] for item in performance_metrics if item["captured_at"]),
                    default=None,
                )
                performance = {
                    "access": "AVAILABLE",
                    "status": "AVAILABLE" if performance_metrics else "UNAVAILABLE",
                    "reason": None if performance_metrics else (
                        "No valid, non-warmup, non-retried Project/Lab performance sample with a timestamp is recorded."
                    ),
                    "metrics": performance_metrics,
                    "source": ["runs", "test_results", "metrics", "samples"],
                    "observed_at": observed_at,
                    "source_updated_at": performance_source_updated,
                }
            else:
                performance = {
                    "access": "RESTRICTED", "status": "RESTRICTED", "reason": None,
                    "metrics": None, "source": None, "observed_at": None,
                    "source_updated_at": None,
                }

            provider_items = []
            for item in labs:
                provider_id = str(item["provider_id"] or "")
                if provider_id.lower() == "gns3":
                    binding = connection.execute(
                        "SELECT status,updated_at FROM gns3_lab_bindings WHERE project_id=? AND lab_id=?",
                        (project_id, item["lab_id"]),
                    ).fetchone()
                    binding_status = "CONFIGURED" if binding and binding["status"] == "ACTIVE" else "NOT_CONFIGURED"
                    binding_updated = binding["updated_at"] if binding else None
                else:
                    binding_status = "NOT_APPLICABLE"
                    binding_updated = None
                provider_source_updated = max(
                    (value for value in (item["updated_at"], binding_updated) if value),
                    default=None,
                )
                provider_items.append({
                    "lab_id": item["lab_id"],
                    "provider_id": provider_id,
                    "binding_status": binding_status,
                    "connection_health": "UNKNOWN",
                    "last_health_check_at": None,
                    "source": ["labs", "gns3_lab_bindings"] if provider_id.lower() == "gns3" else ["labs"],
                    "source_updated_at": provider_source_updated,
                })

        provider_summary = {
            "access": "AVAILABLE",
            "items": provider_items,
            "configured": sum(1 for item in provider_items if item["binding_status"] == "CONFIGURED"),
            "health": "UNKNOWN",
            "source": ["labs", "gns3_lab_bindings"],
            "observed_at": observed_at,
            "source_updated_at": max(
                (item["source_updated_at"] for item in provider_items if item["source_updated_at"]),
                default=None,
            ),
        } if include_topology else {
            "access": "RESTRICTED",
            "items": [],
            "configured": None,
            "health": "UNKNOWN",
            "source": None,
            "observed_at": None,
            "source_updated_at": None,
        }

        return {
            "observed_at": observed_at,
            "scope": {
                "project": {
                    "project_id": project["project_id"],
                    "organization_id": project["organization_id"],
                    "name": project["name"],
                    "status": project["status"],
                    "source": "projects",
                    "observed_at": observed_at,
                    "source_updated_at": project["updated_at"],
                },
                "lab_id": lab_id,
            },
            "labs": {
                "total": int(all_lab_count),
                "in_scope": len(labs),
                "by_status": lab_status_counts,
                "items": [{
                    "lab_id": item["lab_id"], "name": item["name"],
                    "provider_id": item["provider_id"] if include_topology else None,
                    "status": item["status"],
                    "topology_version": item["topology_version"] if include_topology else None,
                    "source_updated_at": item["updated_at"],
                } for item in labs],
                "source": "labs",
                "observed_at": observed_at,
                "source_updated_at": latest_lab_update,
            },
            "devices": devices,
            "topology": topology,
            "providers": provider_summary,
            "pipelines": pipelines,
            "runs": runs,
            "configuration": configuration,
            "evidence": evidence,
            "performance": performance,
            "network_health": {
                "access": "AVAILABLE",
                "provider_health": "UNKNOWN" if include_topology else "RESTRICTED",
                "device_reachability": {
                    "status": "UNAVAILABLE" if include_devices else "RESTRICTED",
                    "reason": (
                        "No current Project/Lab device reachability probe is available."
                        if include_devices else None
                    ),
                },
                "configuration_sync": {
                    "status": "UNAVAILABLE" if include_configuration else "RESTRICTED",
                    "reason": (
                        "Deployment history is available, but no current desired-versus-observed configuration drift source exists."
                        if include_configuration else None
                    ),
                },
                "infrastructure_resources": {
                    "status": "UNAVAILABLE",
                    "reason": "No Project/Lab-scoped OpenTofu resource observation is currently recorded.",
                },
                "source": ["labs", "devices", "device_configuration_deployments"],
                "observed_at": observed_at,
                "source_updated_at": max(
                    (value for value in (
                        latest_lab_update,
                        devices.get("source_updated_at"),
                        configuration.get("source_updated_at"),
                    ) if value),
                    default=None,
                ),
            },
            "action_items": {
                "access": "AVAILABLE",
                "topology_apply_failures": (
                    apply_counts.get("FAILED", 0) + apply_counts.get("PARTIAL", 0)
                    if include_topology else None
                ),
                "configuration_deployment_failures": (
                    configuration.get("failed", 0) + configuration.get("partial", 0)
                    if include_configuration else None
                ),
                "pipeline_recovery_required": (
                    pipelines.get("recovery_required", 0) if include_pipelines else None
                ),
                "pipeline_recovery_required_steps": (
                    pipelines.get("recovery_required_steps", 0) if include_pipelines else None
                ),
                "regressions": {
                    "status": "UNAVAILABLE",
                    "reason": "Blocking regression totals require an explicit baseline/current Run comparison.",
                    "source": None,
                    "observed_at": observed_at,
                },
                "configuration_drift": {
                    "status": "UNAVAILABLE" if include_configuration else "RESTRICTED",
                    "reason": (
                        "No current desired-versus-observed configuration comparison is persisted."
                        if include_configuration else None
                    ),
                    "source": None,
                    "observed_at": observed_at if include_configuration else None,
                },
                "provider_sync_errors": {
                    "status": "UNAVAILABLE",
                    "reason": "No separate current provider synchronization observation is persisted; apply failures remain visible in topology history.",
                    "source": None,
                    "observed_at": observed_at,
                },
                "source": [
                    "topology_apply_records", "device_configuration_deployments",
                    "pipeline_executions",
                ],
                "observed_at": observed_at,
            },
        }

    def runs(self, *, firmware=None, lab=None, profile=None, status=None,
             outcome=None, page=1, limit=50, project_ids=None) -> dict[str, Any]:
        runs = self.run_repository.list()
        allowed_projects = None if project_ids is None else set(project_ids)
        filtered = []
        for run in runs:
            if allowed_projects is not None and run.project_id not in allowed_projects:
                continue
            if firmware and run.firmware_version != firmware:
                continue
            if lab and run.lab_id != lab:
                continue
            if profile and run.validation_profile != profile:
                continue
            if status and run.lifecycle.value != status:
                continue
            if outcome and (not run.outcome or run.outcome.value != outcome):
                continue
            filtered.append(run)
        page = max(1, int(page))
        limit = min(200, max(1, int(limit)))
        start = (page - 1) * limit
        items = filtered[start:start + limit]
        return {
            "items": [self.serialize_run(run, summary=True) for run in items],
            "page": page,
            "limit": limit,
            "total": len(filtered),
            "pages": (len(filtered) + limit - 1) // limit,
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.run_repository.get(run_id)
        if run is None:
            raise DashboardQueryError(f"Run not found: {run_id}")
        attempts = self.attempt_repository.list_for_run(run_id)
        latest = attempts[-1] if attempts else None
        results = self.result_repository.list_for_attempt(latest.attempt_id) if latest else []
        artifacts = self.artifact_repository.list_for_run(run_id)
        return {
            **self.serialize_run(run, summary=False),
            "attempts": [self.serialize_attempt(item) for item in attempts],
            "latest_attempt_id": latest.attempt_id if latest else None,
            "test_counts": {
                "total": len(results),
                "pass": sum(item.status is TestResultStatus.PASS for item in results),
                "fail": sum(item.status is TestResultStatus.FAIL for item in results),
                "error": sum(item.status is TestResultStatus.ERROR for item in results),
                "skipped": sum(item.status is TestResultStatus.SKIPPED for item in results),
                "blocked": sum(item.status is TestResultStatus.BLOCKED for item in results),
                "unvalidated": sum(item.status is TestResultStatus.UNVALIDATED for item in results),
            },
            "artifacts": [self.serialize_artifact(item) for item in artifacts],
            "environment_class": self.environment_class(run_id),
            "health": self.health(run_id),
        }

    def tests(self, run_id: str) -> list[dict[str, Any]]:
        if self.run_repository.get(run_id) is None:
            raise DashboardQueryError(f"Run not found: {run_id}")
        attempts = self.attempt_repository.list_for_run(run_id)
        if not attempts:
            return []
        return [self.serialize_test_result(item) for item in self.result_repository.list_for_attempt(attempts[-1].attempt_id)]

    def test(self, run_id: str, test_result_id: str) -> dict[str, Any]:
        result = self.result_repository.get(test_result_id)
        if result is None or result.run_id != run_id:
            raise DashboardQueryError(f"TestResult not found: {test_result_id}")
        data = self.serialize_test_result(result)
        data["definition"] = self.serialize_definition(result.test_id)
        return data

    def serialize_run(self, run, *, summary: bool) -> dict[str, Any]:
        device_id = "unknown"
        if isinstance(run.resolved_config, Mapping):
            device_value = run.resolved_config.get("device")
            device_id = str(
                run.resolved_config.get("device_id")
                or (device_value.get("id") if isinstance(device_value, Mapping) else device_value)
                or "unknown"
            )
        payload = {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "source_run_id": run.source_run_id,
            "display_id": run.display_id,
            "firmware_version": run.firmware_version,
            "device_id": device_id,
            "lab_id": run.lab_id,
            "validation_profile": run.validation_profile,
            "lifecycle_status": run.lifecycle.value,
            "business_outcome": run.outcome.value if run.outcome else None,
            "environment_health": run.environment_health.value if run.environment_health else None,
            "started_at": self._iso(run.started_at),
            "completed_at": self._iso(run.completed_at),
            "created_at": self._iso(run.created_at),
            "configuration_hash": run.configuration_hash,
            "repository_commit": run.repository_commit,
            "failure_class": run.failure_class.value if run.failure_class else None,
            "failure_reason": run.failure_reason,
            "execution_pid": run.execution_pid,
        }
        if summary:
            payload["environment_class"] = self.environment_class(run.run_id)
        else:
            payload["selected_tests"] = list(run.selected_tests)
            payload["test_definition_versions"] = dict(run.test_definition_versions)
            payload["environment"] = (
                {
                    "snapshot_id": run.environment.snapshot_id,
                    "host_os": run.environment.host_os,
                    "kernel": run.environment.kernel,
                    "python_version": run.environment.python_version,
                    "repository_commit": run.environment.repository_commit,
                    "configuration_hash": run.environment.configuration_hash,
                    "tools": dict(run.environment.tools),
                } if run.environment else None
            )
            payload["config_snapshot"] = (
                {
                    "snapshot_id": run.config_snapshot.snapshot_id,
                    "configuration_hash": run.config_snapshot.configuration_hash,
                    "resolved_config": dict(run.config_snapshot.resolved_config),
                } if run.config_snapshot else None
            )
        return payload

    def serialize_attempt(self, attempt):
        return {
            "attempt_id": attempt.attempt_id,
            "number": attempt.number,
            "started_at": self._iso(attempt.started_at),
            "completed_at": self._iso(attempt.completed_at),
        }

    def serialize_test_result(self, result):
        return {
            "test_result_id": result.test_result_id,
            "run_id": result.run_id,
            "attempt_id": result.attempt_id,
            "test_id": result.test_id,
            "node_id": result.node_id,
            "test_version": result.test_version,
            "status": result.status.value,
            "criticality": result.criticality.value,
            "severity": result.severity.value,
            "evidence_state": result.evidence_state.value,
            "error_reason": result.error_reason,
            "execution_metadata": dict(result.execution_metadata),
            "started_at": self._iso(result.started_at),
            "completed_at": self._iso(result.completed_at),
            "metrics": [self.serialize_metric(item, result.test_id) for item in result.metrics],
            "artifacts": [self.serialize_artifact(item) for item in result.artifacts],
        }

    def serialize_metric(self, metric, test_id=None):
        measurement_policy = None
        if test_id:
            try:
                definition = self.test_registry.metric_definition(test_id, metric.name)
            except KeyError:
                definition = None
            if definition is not None:
                policy = definition.measurement_policy
                eligible = [s for s in metric.samples if not s.warmup and s.status in policy.allowed_statuses and (policy.include_retried or not s.retried)]
                try:
                    summary = MeasurementPolicyEvaluator.evaluate(metric, policy)
                    measurement_policy = {"aggregate":policy.aggregate.value,"minimum_samples":policy.minimum_samples,"eligible_samples":summary.count,"decision_value":summary.decision_value,"status":"READY","authoritative":definition.authoritative,"error":None}
                except MeasurementEvaluationError as exc:
                    measurement_policy = {"aggregate":policy.aggregate.value,"minimum_samples":policy.minimum_samples,"eligible_samples":len(eligible),"decision_value":None,"status":"UNVALIDATED","authoritative":definition.authoritative,"error":str(exc)}
        return {
            "name": metric.name,"unit": metric.unit,"authoritative": metric.authoritative,
            "measurement_policy": measurement_policy,
            "samples": [{"value":sample.value,"status":sample.status,"warmup":sample.warmup,"retried":sample.retried,"captured_at":self._iso(sample.captured_at),"metadata":dict(sample.metadata)} for sample in metric.samples],
        }

    def serialize_artifact(self, artifact):
        return {
            "artifact_id": artifact.artifact_id,
            "run_id": artifact.run_id,
            "test_result_id": artifact.test_result_id,
            "test_node_id": artifact.test_node_id,
            "attempt_id": artifact.attempt_id,
            "artifact_type": artifact.artifact_type.value,
            "display_name": artifact.display_name,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
            "evidence_state": artifact.evidence_state.value,
            "created_at": self._iso(artifact.created_at),
            "sensitivity_class": artifact.sensitivity_class,
            "provenance": artifact.provenance,
            "downloadable": self._contained_artifact_path(artifact) is not None,
        }

    def serialize_definition(self, test_id):
        definition = self.test_registry.get(test_id)
        return {
            "test_id": definition.test_id,
            "version": definition.version,
            "node_id": definition.node_id,
            "category": definition.category,
            "protocol": definition.protocol,
            "severity": definition.severity.value,
            "criticality": definition.criticality.value,
            "equipment": list(definition.equipment),
            "direction": definition.direction,
            "requires": list(definition.requires),
            "destructive": definition.destructive,
            "estimated_duration_sec": definition.estimated_duration_sec,
            "capabilities": list(definition.capabilities),
            "metric_definitions": dict(definition.metric_definitions),
            "measurement_policies": {name:{"aggregate":policy.aggregate.value,"minimum_samples":policy.minimum_samples,"allowed_statuses":list(policy.allowed_statuses),"include_retried":policy.include_retried} for name,policy in definition.measurement_policies.items()},
            "decision_metric": definition.decision_metric,
            "threshold_definitions": dict(definition.threshold_definitions),
            "evidence_requirements": [item.value for item in definition.evidence_requirements],
        }

    def metrics_for_run(self, run_id: str):
        return [
            {
                "test_result_id": result.test_result_id,
                "test_id": result.test_id,
                "metrics": [self.serialize_metric(metric, result.test_id) for metric in result.metrics],
            }
            for result in self._latest_results(run_id)
        ]

    def metrics_history(self, test_id: str, project_ids=None):
        rows = []
        allowed_projects = None if project_ids is None else set(project_ids)
        for run in self.run_repository.list():
            if allowed_projects is not None and run.project_id not in allowed_projects:
                continue
            for result in self._latest_results(run.run_id):
                if result.test_id != test_id:
                    continue
                for metric in result.metrics:
                    rows.append({
                        "run_id": run.run_id,
                        "firmware_version": run.firmware_version,
                        "captured_at": self._iso(result.completed_at or result.started_at or run.created_at),
                        "test_id": test_id,
                        "metric_name": metric.name,
                        "unit": metric.unit,
                        "measurement_policy": self.serialize_metric(metric, test_id).get("measurement_policy"),
                        "samples": [
                            {
                                "value": sample.value,
                                "status": sample.status,
                                "warmup": sample.warmup,
                                "retried": sample.retried,
                                "captured_at": self._iso(sample.captured_at),
                            }
                            for sample in metric.samples
                        ],
                    })
        return rows

    def _latest_results(self, run_id: str):
        attempts = self.attempt_repository.list_for_run(run_id)
        if not attempts:
            return []
        return self.result_repository.list_for_attempt(attempts[-1].attempt_id)

    def artifacts(self, run_id=None, artifact_type=None, page=1, limit=50, project_ids=None):
        if run_id:
            items = self.artifact_repository.list_for_run(run_id)
        elif project_ids is None:
            items = self.artifact_repository.list_all()
        else:
            allowed = set(project_ids)
            run_ids = [item.run_id for item in self.run_repository.list() if item.project_id in allowed]
            items = [
                artifact
                for selected_run_id in run_ids
                for artifact in self.artifact_repository.list_for_run(selected_run_id)
            ]
        if artifact_type:
            items = [item for item in items if item.artifact_type.value == artifact_type]
        page = max(1, int(page))
        limit = min(200, max(1, int(limit)))
        total = len(items)
        start = (page - 1) * limit
        return {
            "items": [self.serialize_artifact(item) for item in items[start:start + limit]],
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit,
        }

    def artifact(self, artifact_id):
        artifact = self.artifact_repository.get(artifact_id)
        if artifact is None:
            raise DashboardQueryError(f"Artifact not found: {artifact_id}")
        return artifact

    def telemetry(self, run_id: str):
        if self.run_repository.get(run_id) is None:
            raise DashboardQueryError(f"Run not found: {run_id}")
        payloads = []
        for artifact in self.artifact_repository.list_for_run(run_id):
            if artifact.artifact_type is not ArtifactType.TELEMETRY:
                continue
            data = self._read_json_artifact(artifact)
            if data is not None:
                payloads.append({"artifact": self.serialize_artifact(artifact), "snapshot": data})
        return payloads

    def health(self, run_id: str):
        if self.run_repository.get(run_id) is None:
            raise DashboardQueryError(f"Run not found: {run_id}")
        payloads = []
        for artifact in self.artifact_repository.list_for_run(run_id):
            if artifact.artifact_type is not ArtifactType.LAB_HEALTH_SNAPSHOT:
                continue
            data = self._read_json_artifact(artifact)
            if data is not None:
                payloads.append({"artifact": self.serialize_artifact(artifact), "snapshot": data})
        return sorted(payloads, key=lambda item: item["snapshot"].get("completed_at") or "")

    def environment_class(self, run_id: str) -> str | None:
        classes = set()
        for item in self.telemetry(run_id):
            snapshot = item["snapshot"]
            if snapshot.get("environment_class"):
                classes.add(snapshot["environment_class"])
            for point in snapshot.get("points", []):
                if point.get("environment_class"):
                    classes.add(point["environment_class"])
        return next(iter(classes)) if len(classes) == 1 else None

    def regression(self, baseline_run_id: str, current_run_id: str):
        baseline_env = self.environment_class(baseline_run_id)
        current_env = self.environment_class(current_run_id)
        report = self.regression_service.compare_runs(
            baseline_run_id=baseline_run_id,
            current_run_id=current_run_id,
            baseline_environment_class=baseline_env,
            current_environment_class=current_env,
        )
        current_map = {item.test_id: item for item in self._latest_results(current_run_id)}
        assessments = []
        for item in report.assessments:
            entry = {
                "test_id": item.test_id,
                "node_id": item.node_id,
                "baseline_status": item.baseline_status,
                "current_status": item.current_status,
                "classification": item.classification.value,
                "dimensions": [value.value for value in item.dimensions],
                "reason": item.reason,
                "metric_comparisons": [
                    {
                        "metric_name": metric.metric_name,
                        "unit": metric.unit,
                        "baseline_value": metric.baseline_value,
                        "current_value": metric.current_value,
                        "delta_pct": metric.delta_pct,
                        "threshold_pct": metric.threshold_pct,
                        "classification": metric.classification.value,
                        "dimension": metric.dimension.value,
                        "reason": metric.reason,
                    }
                    for metric in item.metric_comparisons
                ],
            }
            current_result = current_map.get(item.test_id)
            entry["current_test_result_id"] = current_result.test_result_id if current_result else None
            if item.flaky_history:
                entry["flaky_history"] = {
                    "observations": list(item.flaky_history.observations),
                    "pass_count": item.flaky_history.pass_count,
                    "fail_count": item.flaky_history.fail_count,
                    "transition_count": item.flaky_history.transition_count,
                    "flagged": item.flaky_history.flagged,
                    "reason": item.flaky_history.reason,
                }
            assessments.append(entry)
        return {
            "baseline_run_id": report.baseline_run_id,
            "current_run_id": report.current_run_id,
            "comparability": report.comparability.value,
            "reason": report.reason,
            "environment": {"baseline": baseline_env, "current": current_env},
            "assessments": assessments,
        }

    def release_gate(self, current_run_id: str, baseline_run_id: str) -> dict[str, Any]:
        current = self.run_repository.get(current_run_id)
        if current is None:
            raise DashboardQueryError(f"Run not found: {current_run_id}")
        baseline = self.run_repository.get(baseline_run_id)
        if baseline is None:
            raise DashboardQueryError(f"Baseline Run not found: {baseline_run_id}")

        baseline_env = self.environment_class(baseline_run_id)
        current_env = self.environment_class(current_run_id)
        report = self.regression_service.compare_runs(
            baseline_run_id=baseline_run_id,
            current_run_id=current_run_id,
            baseline_environment_class=baseline_env,
            current_environment_class=current_env,
        )
        current_results = self._latest_results(current_run_id)
        required_list = []
        for selected in current.selected_tests:
            try:
                required_list.append(self.test_registry.get(selected).test_id)
            except KeyError:
                required_list.append(self.test_registry.resolve_or_fallback(selected).test_id)
        required = tuple(dict.fromkeys(required_list))
        waivers = tuple(WaiverService.from_sqlite(self.database).repository.list_active())
        decision = ReleaseGateEvaluator().evaluate(
            ReleaseGateInput(
                run_lifecycle=current.lifecycle.value,
                run_id=current.run_id,
                lab_health=current.environment_health.value if current.environment_health else None,
                baseline_available=not report.no_baseline,
                required_test_ids=required,
                observed_test_ids=tuple(item.test_id for item in current_results),
                test_statuses={item.test_id: item.status.value for item in current_results},
                evidence_states={item.test_id: item.evidence_state.value for item in current_results},
                regression_classifications={
                    item.test_id: item.classification.value for item in report.assessments
                },
                waivers=waivers,
            )
        )
        return {
            "status": decision.status.value,
            "accepted": decision.accepted,
            "summary": decision.summary,
            "issues": [
                {"code": item.code, "message": item.message, "test_id": item.test_id}
                for item in decision.issues
            ],
            "waived_issues": [
                {
                    "issue": {"code": item.issue.code, "message": item.issue.message, "test_id": item.issue.test_id},
                    "waiver_id": item.waiver_id,
                    "audit_reference": item.audit_reference,
                }
                for item in decision.waived_issues
            ],
            "current_run_id": current_run_id,
            "baseline_run_id": baseline_run_id,
            "comparability": report.comparability.value,
            "comparability_reason": report.reason,
        }

    def sync_queue(self, limit: int = 50) -> dict[str, Any]:
        repository = SQLiteSyncQueueRepository(self.database)
        items = repository.list_recent(limit)
        return {
            "summary": repository.summary(),
            "items": [
                {
                    "envelope_id": item.envelope.envelope_id,
                    "run_id": item.envelope.run_id,
                    "kind": item.envelope.kind,
                    "schema_version": item.envelope.schema_version,
                    "state": item.state.value,
                    "attempt_count": item.attempt_count,
                    "next_attempt_at": self._iso(item.next_attempt_at),
                    "lease_expires_at": self._iso(item.leased_at),
                    "last_error": item.last_error,
                    "created_at": self._iso(item.envelope.created_at),
                    "updated_at": self._iso(item.updated_at),
                }
                for item in items
            ],
        }

    def baselines(self, project_ids=None):
        allowed = None if project_ids is None else set(project_ids)
        items = self.baseline_repository.list_active()
        if allowed is not None:
            owned_runs = {
                run.run_id for run in self.run_repository.list()
                if run.project_id in allowed
            }
            items = [item for item in items if item.baseline_run_id in owned_runs]
        return [
            {
                "baseline_id": item.baseline_id,
                "name": item.name,
                "baseline_run_id": item.baseline_run_id,
                "status": item.status,
                "device_scope": item.device_scope,
                "firmware_major_scope": item.firmware_major_scope,
                "test_suite_version": item.test_suite_version,
                "lab_class": item.lab_class,
                "promoted_by": item.promoted_by,
                "promoted_at": self._iso(item.promoted_at),
                "provenance": item.provenance,
            }
            for item in items
        ]

    def latest_lab_health(self, lab_id: str):
        for run in self.run_repository.list():
            if run.lab_id != lab_id:
                continue
            health = self.health(run.run_id)
            if health:
                return health[-1]
        return None

    def _contained_artifact_path(self, artifact) -> Path | None:
        try:
            root = self.results_root.resolve()
            candidate = Path(artifact.path).resolve()
            if candidate != root and root not in candidate.parents:
                return None
            return candidate if candidate.is_file() else None
        except OSError:
            return None

    def _safe_artifact_path(self, artifact) -> Path | None:
        candidate = self._contained_artifact_path(artifact)
        if candidate is None:
            return None
        try:
            digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().lower() != artifact.sha256.lower():
                return None
            return candidate
        except OSError:
            return None

    def _read_json_artifact(self, artifact):
        path = self._safe_artifact_path(artifact)
        if path is None:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None


    def active_baseline(self, baseline_id: str):
        baseline = self.baseline_repository.get(baseline_id)
        if baseline is None:
            raise DashboardQueryError(f"Baseline not found: {baseline_id}")
        return self.baselines_for([baseline])[0]

    def baselines_for(self, items):
        return [{
            "baseline_id": item.baseline_id,
            "name": item.name,
            "baseline_run_id": item.baseline_run_id,
            "status": item.status,
            "device_scope": item.device_scope,
            "firmware_major_scope": item.firmware_major_scope,
            "test_suite_version": item.test_suite_version,
            "lab_class": item.lab_class,
            "promoted_by": item.promoted_by,
            "promoted_at": self._iso(item.promoted_at),
            "provenance": item.provenance,
        } for item in items]
