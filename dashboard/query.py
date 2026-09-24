from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from lib.domain import ArtifactType, TestResultStatus
from lib.repositories import (
    SQLiteArtifactRepository,
    SQLiteAttemptRepository,
    SQLiteBaselineRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
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

    def runs(self, *, firmware=None, lab=None, profile=None, status=None,
             outcome=None, page=1, limit=50) -> dict[str, Any]:
        runs = self.run_repository.list()
        filtered = []
        for run in runs:
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
            "started_at": self._iso(result.started_at),
            "completed_at": self._iso(result.completed_at),
            "metrics": [self.serialize_metric(item) for item in result.metrics],
            "artifacts": [self.serialize_artifact(item) for item in result.artifacts],
        }

    def serialize_metric(self, metric):
        return {
            "name": metric.name,
            "unit": metric.unit,
            "authoritative": metric.authoritative,
            "samples": [
                {
                    "value": sample.value,
                    "status": sample.status,
                    "warmup": sample.warmup,
                    "retried": sample.retried,
                    "captured_at": self._iso(sample.captured_at),
                    "metadata": dict(sample.metadata),
                }
                for sample in metric.samples
            ],
        }

    def serialize_artifact(self, artifact):
        return {
            "artifact_id": artifact.artifact_id,
            "run_id": artifact.run_id,
            "test_result_id": artifact.test_result_id,
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
            "threshold_definitions": dict(definition.threshold_definitions),
            "evidence_requirements": [item.value for item in definition.evidence_requirements],
        }

    def metrics_for_run(self, run_id: str):
        return [
            {
                "test_result_id": result.test_result_id,
                "test_id": result.test_id,
                "metrics": [self.serialize_metric(metric) for metric in result.metrics],
            }
            for result in self._latest_results(run_id)
        ]

    def metrics_history(self, test_id: str):
        rows = []
        for run in self.run_repository.list():
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

    def artifacts(self, run_id=None, artifact_type=None, page=1, limit=50):
        items = self.artifact_repository.list_for_run(run_id) if run_id else self.artifact_repository.list_all()
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
            "current_run_id": current_run_id,
            "baseline_run_id": baseline_run_id,
            "comparability": report.comparability.value,
            "comparability_reason": report.reason,
        }

    def baselines(self):
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
            for item in self.baseline_repository.list_active()
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
