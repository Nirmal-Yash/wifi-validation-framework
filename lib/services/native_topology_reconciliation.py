"""Unified, read-only native topology reconciliation and restart-safe evidence history."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import secrets
from typing import Any

from .native_topology_interop import (
    NativeTopologyInteropConflict,
    NativeTopologyInteropError,
    NativeTopologyInteropNotFound,
    NativeTopologyInteropService,
)
from .topology_presentation import TopologyPresentationService
from .topology_source_artifacts import (
    TopologySourceArtifactError,
    TopologySourceArtifactService,
)
from .topology_studio import TopologyStudioService


class NativeTopologyReconciliationError(ValueError):
    """A reconciliation request or its persisted evidence is invalid."""


class NativeTopologyReconciliationNotFound(LookupError):
    """The selected reconciliation is outside the requested topology profile."""


class NativeTopologyReconciliationConflict(NativeTopologyReconciliationError):
    """The selected revisions and immutable native source do not agree."""


class NativeTopologyReconciliationService:
    """Join existing immutable records; never repair or retry a live network."""

    SCHEMA_VERSION = "1.0"
    MAX_DETAILS_BYTES = 4 * 1024 * 1024
    MAX_HISTORY_ITEMS = 100
    MAX_OPERATION_ROWS = 500
    OBSERVATION_MAX_AGE_SECONDS = 24 * 60 * 60

    def __init__(
        self,
        database,
        *,
        topology_studio: TopologyStudioService | None = None,
        topology_presentation: TopologyPresentationService | None = None,
        source_artifacts: TopologySourceArtifactService | None = None,
        native_interop: NativeTopologyInteropService | None = None,
        clock=None,
    ) -> None:
        self.database = database
        self.topology = topology_studio or TopologyStudioService(database)
        self.presentation = topology_presentation or TopologyPresentationService(database)
        self.sources = source_artifacts or TopologySourceArtifactService(database)
        self.interop = native_interop or NativeTopologyInteropService(
            database,
            topology_studio=self.topology,
            topology_presentation=self.presentation,
            source_artifacts=self.sources,
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise NativeTopologyReconciliationError(
                "actor must contain 1 to 128 printable characters"
            )
        return actor

    @staticmethod
    def _canonical(value: object) -> str:
        try:
            return json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise NativeTopologyReconciliationError(
                "reconciliation evidence is not finite canonical JSON"
            ) from exc

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise NativeTopologyReconciliationError(
                "reconciliation clock must return a timezone-aware datetime"
            )
        return value.astimezone(timezone.utc)

    @classmethod
    def _age_seconds(cls, value: object, now: datetime) -> int | None:
        if not isinstance(value, str):
            return None
        try:
            observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if observed.tzinfo is None or observed.utcoffset() is None:
            return None
        age = (now - observed.astimezone(timezone.utc)).total_seconds()
        if age < -300:
            return None
        return max(0, int(age))

    @staticmethod
    def _finding(code: str, severity: str, message: str, **metadata: Any) -> dict[str, Any]:
        return {"code": code, "severity": severity, "message": message, **metadata}

    @staticmethod
    def _decode_json(value: object) -> dict[str, Any]:
        try:
            decoded = json.loads(value or "{}")
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def _operation_history(self, profile: dict, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), self.MAX_HISTORY_ITEMS))
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT action,resource_type,resource_id,details_json,occurred_at
                   FROM audit_events
                   WHERE resource_type IN ('TOPOLOGY_SOURCE_ARTIFACT','NATIVE_TOPOLOGY_OPERATION')
                     AND json_valid(details_json)
                     AND (
                       json_extract(details_json,'$.profile_id')=?
                       OR (
                         resource_type='NATIVE_TOPOLOGY_OPERATION'
                         AND json_extract(details_json,'$.project_id')=?
                       )
                     )
                   ORDER BY occurred_at DESC,audit_id DESC LIMIT ?""",
                (profile["profile_id"], profile["project_id"], self.MAX_OPERATION_ROWS),
            ).fetchall()
        operations = []
        for row in rows:
            details = self._decode_json(row["details_json"])
            if details.get("profile_id") != profile["profile_id"] and not (
                row["resource_type"] == "NATIVE_TOPOLOGY_OPERATION"
                and details.get("project_id") == profile["project_id"]
            ):
                continue
            operations.append({
                "action": row["action"],
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "occurred_at": row["occurred_at"],
                "details": details,
            })
            if len(operations) >= limit:
                break
        return operations

    def list_operations(self, profile_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        profile = self.topology.get_profile(profile_id)
        if profile is None:
            raise NativeTopologyReconciliationNotFound("topology profile not found")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise NativeTopologyReconciliationError("limit must be an integer")
        return self._operation_history(profile, max(1, min(limit, self.MAX_HISTORY_ITEMS)))

    def _snapshot_integrity(self, row) -> dict[str, Any]:
        details_text = row["details_json"]
        if (
            not isinstance(details_text, str)
            or len(details_text.encode("utf-8")) > self.MAX_DETAILS_BYTES
            or hashlib.sha256(details_text.encode("utf-8")).hexdigest() != row["reconciliation_sha256"]
        ):
            raise NativeTopologyReconciliationError(
                "stored native topology reconciliation failed its SHA-256 integrity check"
            )
        try:
            details = json.loads(details_text)
        except ValueError as exc:
            raise NativeTopologyReconciliationError(
                "stored native topology reconciliation JSON is invalid"
            ) from exc
        if not isinstance(details, dict):
            raise NativeTopologyReconciliationError(
                "stored native topology reconciliation payload is invalid"
            )
        expected_scope = {
            "project_id": row["project_id"],
            "profile_id": row["profile_id"],
            "topology_revision_id": row["topology_revision_id"],
            "presentation_id": row["presentation_id"],
            "source_id": row["source_id"],
        }
        if (
            details.get("status") != row["status"]
            or details.get("scope") != expected_scope
        ):
            raise NativeTopologyReconciliationError(
                "stored native topology reconciliation scope or status does not match its immutable record"
            )
        return {
            "reconciliation_id": row["reconciliation_id"],
            "project_id": row["project_id"],
            "profile_id": row["profile_id"],
            "topology_revision_id": row["topology_revision_id"],
            "presentation_id": row["presentation_id"],
            "source_id": row["source_id"],
            "status": row["status"],
            "reconciliation_sha256": row["reconciliation_sha256"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "details": details,
        }

    def get_reconciliation(
        self, profile_id: str, reconciliation_id: str
    ) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM native_topology_reconciliations
                   WHERE reconciliation_id=? AND profile_id=?""",
                (reconciliation_id, profile_id),
            ).fetchone()
        return self._snapshot_integrity(row) if row else None

    def list_reconciliations(self, profile_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise NativeTopologyReconciliationError("limit must be an integer")
        bounded = max(1, min(limit, self.MAX_HISTORY_ITEMS))
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM native_topology_reconciliations
                   WHERE profile_id=?
                   ORDER BY created_at DESC,reconciliation_id DESC LIMIT ?""",
                (profile_id, bounded),
            ).fetchall()
        return [self._snapshot_integrity(row) for row in rows]

    def _collect_configuration_snapshots(
        self, profile: dict, revision: dict, now: datetime, findings: list[dict]
    ) -> tuple[list[dict], set[str]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT s.snapshot_id,s.logical_node_id,s.device_id,s.capability_report_id,
                          s.capability_sha256,s.sha256,s.size_bytes,s.content_bytes,s.created_at,
                          c.capability_sha256 AS reported_capability_sha256
                   FROM native_configuration_snapshots s
                   LEFT JOIN device_capability_reports c ON c.report_id=s.capability_report_id
                   WHERE s.project_id=? AND s.profile_id=? AND s.topology_revision_id=?
                   ORDER BY s.created_at DESC,s.snapshot_id DESC LIMIT ?""",
                (profile["project_id"], profile["profile_id"], revision["revision_id"], self.MAX_HISTORY_ITEMS),
            ).fetchall()
        snapshots: list[dict] = []
        devices: set[str] = set()
        for row in rows:
            content = bytes(row["content_bytes"])
            digest = hashlib.sha256(content).hexdigest()
            valid = len(content) == row["size_bytes"] and digest == row["sha256"]
            capability_hash = row["capability_sha256"]
            if capability_hash and (
                len(capability_hash) != 64
                or any(char not in "0123456789abcdef" for char in capability_hash)
                or row["reported_capability_sha256"] != capability_hash
            ):
                valid = False
                findings.append(self._finding(
                    "CONFIGURATION_CAPABILITY_PROVENANCE_MISMATCH", "ERROR",
                    "A native configuration snapshot is not bound to the matching immutable capability report hash",
                    snapshot_id=row["snapshot_id"],
                ))
            if row["device_id"]:
                devices.add(row["device_id"])
            if not valid:
                findings.append(self._finding(
                    "CONFIGURATION_SNAPSHOT_INTEGRITY_FAILED", "ERROR",
                    "A native configuration snapshot failed its stored size or SHA-256 verification",
                    snapshot_id=row["snapshot_id"],
                ))
            snapshots.append({
                "snapshot_id": row["snapshot_id"],
                "logical_node_id": row["logical_node_id"],
                "device_id": row["device_id"],
                "capability_report_id": row["capability_report_id"],
                "capability_sha256": row["capability_sha256"],
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
                "created_at": row["created_at"],
                "integrity": "VERIFIED" if valid else "FAILED",
            })
        return snapshots, devices

    def _collect_live_observations(
        self, profile: dict, devices: set[str], now: datetime, findings: list[dict]
    ) -> dict[str, list[dict]]:
        device_rows = []
        if devices:
            placeholders = ",".join("?" for _ in devices)
            with self.database.connection() as connection:
                device_rows = connection.execute(
                    f"""SELECT observation_id,project_id,lab_id,device_id,source,captured_at,
                               payload_json,payload_sha256,observed_by
                        FROM device_observation_snapshots
                        WHERE project_id=? AND device_id IN ({placeholders})
                        ORDER BY captured_at DESC,observation_id DESC LIMIT ?""",
                    (profile["project_id"], *sorted(devices), self.MAX_HISTORY_ITEMS),
                ).fetchall()
        device_observations = []
        for row in device_rows:
            payload = row["payload_json"].encode("utf-8")
            valid = hashlib.sha256(payload).hexdigest() == row["payload_sha256"]
            age = self._age_seconds(row["captured_at"], now)
            if not valid:
                findings.append(self._finding(
                    "DEVICE_OBSERVATION_INTEGRITY_FAILED", "ERROR",
                    "A persisted device observation failed its SHA-256 verification",
                    observation_id=row["observation_id"],
                ))
            device_observations.append({
                "observation_id": row["observation_id"], "device_id": row["device_id"],
                "lab_id": row["lab_id"], "source": row["source"],
                "captured_at": row["captured_at"], "age_seconds": age,
                "sha256": row["payload_sha256"], "integrity": "VERIFIED" if valid else "FAILED",
            })

        lab_ids = set()
        if profile.get("lab_id"):
            lab_ids.add(profile["lab_id"])
        if devices:
            placeholders = ",".join("?" for _ in devices)
            with self.database.connection() as connection:
                rows = connection.execute(
                    f"SELECT DISTINCT lab_id FROM devices WHERE project_id=? AND device_id IN ({placeholders})",
                    (profile["project_id"], *sorted(devices)),
                ).fetchall()
            lab_ids.update(row["lab_id"] for row in rows if row["lab_id"])
        if not lab_ids:
            with self.database.connection() as connection:
                rows = connection.execute(
                    "SELECT DISTINCT lab_id FROM topology_provider_mappings WHERE profile_id=?",
                    (profile["profile_id"],),
                ).fetchall()
            lab_ids.update(row["lab_id"] for row in rows if row["lab_id"])

        provider_rows = []
        if lab_ids:
            placeholders = ",".join("?" for _ in lab_ids)
            with self.database.connection() as connection:
                provider_rows = connection.execute(
                    f"""SELECT observation_id,project_id,lab_id,binding_id,provider_id,
                               observed_at,payload_json,payload_sha256
                        FROM provider_observation_snapshots
                        WHERE project_id=? AND lab_id IN ({placeholders})
                        ORDER BY observed_at DESC,observation_id DESC LIMIT ?""",
                    (profile["project_id"], *sorted(lab_ids), self.MAX_HISTORY_ITEMS),
                ).fetchall()
        provider_observations = []
        for row in provider_rows:
            valid = hashlib.sha256(row["payload_json"].encode("utf-8")).hexdigest() == row["payload_sha256"]
            age = self._age_seconds(row["observed_at"], now)
            if not valid:
                findings.append(self._finding(
                    "PROVIDER_OBSERVATION_INTEGRITY_FAILED", "ERROR",
                    "A persisted provider observation failed its SHA-256 verification",
                    observation_id=row["observation_id"],
                ))
            provider_observations.append({
                "observation_id": row["observation_id"], "lab_id": row["lab_id"],
                "binding_id": row["binding_id"], "provider_id": row["provider_id"],
                "observed_at": row["observed_at"], "age_seconds": age,
                "sha256": row["payload_sha256"], "integrity": "VERIFIED" if valid else "FAILED",
            })

        all_observations = device_observations + provider_observations
        if not all_observations:
            findings.append(self._finding(
                "LIVE_OBSERVATION_NOT_AVAILABLE", "INFO",
                "No persisted device or provider observation is available for the selected topology scope",
            ))
        elif not any(
            item["integrity"] == "VERIFIED"
            and item["age_seconds"] is not None
            and item["age_seconds"] <= self.OBSERVATION_MAX_AGE_SECONDS
            for item in all_observations
        ):
            findings.append(self._finding(
                "LIVE_OBSERVATION_STALE_OR_UNVERIFIABLE", "INFO",
                "No verified device or provider observation is within the 24-hour freshness window",
            ))
        return {
            "device": device_observations,
            "provider": provider_observations,
        }

    def _collect_partial_operations(
        self, profile: dict, revision: dict, now: datetime, findings: list[dict]
    ) -> dict[str, Any]:
        topology_apply = []
        ansible = []
        opentofu = []
        uncertain = []

        with self.database.connection() as connection:
            apply_rows = connection.execute(
                """SELECT apply_id,revision_id,status,result_json,observed_before_json,observed_after_json,
                          created_at,started_at,completed_at
                   FROM topology_apply_records
                   WHERE project_id=? AND profile_id=?
                   ORDER BY created_at DESC,apply_id DESC LIMIT ?""",
                (profile["project_id"], profile["profile_id"], self.MAX_HISTORY_ITEMS),
            ).fetchall()
            latest_apply_row = connection.execute(
                """SELECT apply_id,revision_id,status,result_json,completed_at
                   FROM topology_apply_records
                   WHERE project_id=? AND profile_id=?
                   ORDER BY COALESCE(completed_at,started_at,created_at) DESC,apply_id DESC LIMIT 1""",
                (profile["project_id"], profile["profile_id"]),
            ).fetchone()
            ansible_rows = connection.execute(
                """SELECT p.plan_id,p.status AS plan_status,p.plan_sha256,
                          ir.topology_revision_id,e.execution_id,e.status AS execution_status,e.result_json,
                          e.started_at,e.completed_at
                   FROM network_intent_profiles ip
                   JOIN network_intent_revisions ir ON ir.profile_id=ip.profile_id
                   JOIN ansible_automation_plans p
                     ON p.profile_id=ip.profile_id AND p.revision_id=ir.revision_id
                   LEFT JOIN ansible_automation_executions e ON e.plan_id=p.plan_id
                   WHERE ip.topology_profile_id=?
                   ORDER BY p.created_at DESC,e.started_at DESC LIMIT ?""",
                (profile["profile_id"], self.MAX_HISTORY_ITEMS),
            ).fetchall()
            opentofu_rows = connection.execute(
                """SELECT b.binding_id,b.workspace_id,b.topology_revision_id,w.status AS workspace_status,
                          p.plan_id,p.status AS plan_status,e.execution_id,
                          e.status AS execution_status,e.result_json,e.started_at,e.completed_at
                   FROM infrastructure_resource_bindings b
                   JOIN opentofu_workspaces w ON w.workspace_id=b.workspace_id
                   LEFT JOIN opentofu_plans p ON p.workspace_id=b.workspace_id
                   LEFT JOIN opentofu_executions e ON e.plan_id=p.plan_id
                   WHERE b.topology_profile_id=?
                   ORDER BY p.created_at DESC,e.started_at DESC LIMIT ?""",
                (profile["profile_id"], self.MAX_HISTORY_ITEMS),
            ).fetchall()

        for row in apply_rows:
            result = self._decode_json(row["result_json"])
            summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
            summary_fields = (
                "created_nodes", "recovered_nodes", "created_links", "missing_nodes",
                "missing_links", "conflicts", "completed_operations", "uncertain_operations",
                "error_type",
            )
            result_summary = {
                key: summary[key] for key in summary_fields
                if isinstance(summary.get(key), (str, int)) and not isinstance(summary.get(key), bool)
            }
            observed_before = str(row["observed_before_json"] or "{}").encode("utf-8")
            observed_after = str(row["observed_after_json"] or "{}").encode("utf-8")
            item = {
                "apply_id": row["apply_id"], "revision_id": row["revision_id"], "status": row["status"],
                "created_at": row["created_at"], "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "observed_before_sha256": hashlib.sha256(observed_before).hexdigest(),
                "observed_after_sha256": hashlib.sha256(observed_after).hexdigest(),
                "result_summary": result_summary,
                "reconciliation_status": (
                    result.get("reconciliation", {}).get("status")
                    if isinstance(result.get("reconciliation"), dict) else None
                ),
                "partial_changes_possible": row["status"] == "PARTIAL" or result.get("partial_changes_possible") is True,
                "reconciliation_required": row["status"] in {"APPLYING", "PARTIAL"} or result.get("reconciliation_required") is True,
            }
            topology_apply.append(item)
            if row["status"] in {"APPLYING", "PARTIAL"} or item["partial_changes_possible"] or item["reconciliation_required"]:
                uncertain.append({"system": "TOPOLOGY_APPLY", **item})

        for row in ansible_rows:
            result = self._decode_json(row["result_json"])
            item = {
                "plan_id": row["plan_id"], "execution_id": row["execution_id"],
                "topology_revision_id": row["topology_revision_id"],
                "plan_status": row["plan_status"], "execution_status": row["execution_status"],
                "plan_sha256": row["plan_sha256"], "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "partial_changes_possible": result.get("partial_changes_possible") is True,
                "reconciliation_required": result.get("reconciliation_required") is True,
                "readback_status": result.get("readback_status"),
            }
            ansible.append(item)
            if (
                row["plan_status"] == "EXECUTING"
                or row["execution_status"] == "RUNNING"
                or item["partial_changes_possible"]
                or item["reconciliation_required"]
            ):
                uncertain.append({"system": "ANSIBLE", **item})

        for row in opentofu_rows:
            result = self._decode_json(row["result_json"])
            item = {
                "binding_id": row["binding_id"], "workspace_id": row["workspace_id"],
                "topology_revision_id": row["topology_revision_id"],
                "plan_id": row["plan_id"], "execution_id": row["execution_id"],
                "workspace_status": row["workspace_status"], "plan_status": row["plan_status"],
                "execution_status": row["execution_status"], "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "partial_changes_possible": result.get("partial_changes_possible") is True,
                "reconciliation_required": result.get("reconciliation_required") is True,
            }
            opentofu.append(item)
            if (
                row["workspace_status"] == "RECOVERY_REQUIRED"
                or row["execution_status"] == "RUNNING"
                or item["partial_changes_possible"]
                or item["reconciliation_required"]
            ):
                uncertain.append({"system": "OPENTOFU", **item})

        topology_readback = {
            "verified": False,
            "apply_id": None,
            "revision_id": None,
            "status": "NOT_AVAILABLE",
            "reconciliation_status": None,
            "completed_at": None,
            "age_seconds": None,
        }
        if latest_apply_row is not None:
            latest_result = self._decode_json(latest_apply_row["result_json"])
            latest_reconciliation = latest_result.get("reconciliation")
            latest_reconciliation_status = (
                latest_reconciliation.get("status")
                if isinstance(latest_reconciliation, dict) else None
            )
            age = self._age_seconds(latest_apply_row["completed_at"], now)
            verified = (
                latest_apply_row["status"] == "APPLIED"
                and latest_apply_row["revision_id"] == revision["revision_id"]
                and latest_reconciliation_status == "IN_SYNC"
                and age is not None
                and age <= self.OBSERVATION_MAX_AGE_SECONDS
            )
            topology_readback = {
                "verified": verified,
                "apply_id": latest_apply_row["apply_id"],
                "revision_id": latest_apply_row["revision_id"],
                "status": latest_apply_row["status"],
                "reconciliation_status": latest_reconciliation_status,
                "completed_at": latest_apply_row["completed_at"],
                "age_seconds": age,
            }
        if not topology_readback["verified"]:
            if latest_apply_row is None:
                code = "LIVE_TOPOLOGY_READBACK_NOT_AVAILABLE"
                message = "No provider topology apply/read-back evidence exists for this topology profile"
            elif topology_readback["revision_id"] != revision["revision_id"]:
                code = "LIVE_TOPOLOGY_READBACK_REVISION_MISMATCH"
                message = "The latest provider topology apply/read-back belongs to a different topology revision"
            elif topology_readback["age_seconds"] is None or topology_readback["age_seconds"] > self.OBSERVATION_MAX_AGE_SECONDS:
                code = "LIVE_TOPOLOGY_READBACK_STALE"
                message = "The latest provider topology read-back is older than the 24-hour freshness window"
            else:
                code = "LIVE_TOPOLOGY_READBACK_NOT_VERIFIED"
                message = "The latest provider topology apply has no verified IN_SYNC read-back"
            findings.append(self._finding(code, "WARNING", message))
        def guidance(system: str) -> str:
            return {
                "TOPOLOGY_APPLY": (
                    "Read the current provider catalogue and compare it with the stored before/after evidence. "
                    "Reconcile logical-to-provider mappings, then obtain approval for a new plan; never blindly retry."
                ),
                "ANSIBLE": (
                    "Use an approved read-only device read-back to identify which targets changed. "
                    "Resolve candidate/running configuration differences and re-approve a new exact plan before any push."
                ),
                "OPENTOFU": (
                    "Inspect the backend state, lock and last apply evidence; run a reviewed refresh/plan. "
                    "Restore state only from a verified backup and under change control."
                ),
            }[system]
        for item in uncertain:
            item["recovery_guidance"] = guidance(item["system"])
        if uncertain:
            findings.append(self._finding(
                "PARTIAL_OR_UNCERTAIN_OPERATION", "CRITICAL",
                "An operation may have changed part of the selected topology; perform reviewed reconciliation before any new apply",
                count=len(uncertain),
            ))
        return {
            "topology_apply": topology_apply,
            "topology_readback": topology_readback,
            "ansible": ansible,
            "opentofu": opentofu,
            "uncertain": uncertain,
        }

    def record_operation(
        self,
        project_id: str,
        operation_type: str,
        *,
        actor: str,
        details: dict[str, Any],
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a bounded, secret-free export/conversion summary in audit history."""
        actor = self._actor(actor)
        project_id = str(project_id or "").strip()
        if not project_id or len(project_id) > 128 or any(ord(ch) < 33 for ch in project_id):
            raise NativeTopologyReconciliationError("project_id is invalid")
        operation_type = str(operation_type or "").strip().upper()
        if operation_type not in {"EXPORT", "CONVERSION"}:
            raise NativeTopologyReconciliationError("operation_type must be EXPORT or CONVERSION")
        if not isinstance(details, dict):
            raise NativeTopologyReconciliationError("operation details must be an object")
        forbidden = {"content", "content_bytes", "source_bytes", "private_key", "password", "token", "secret", "credential"}
        def inspect(value: Any, depth: int = 0) -> None:
            if depth > 10:
                raise NativeTopologyReconciliationError("operation report exceeds the maximum nesting depth")
            if isinstance(value, dict):
                for key, item in value.items():
                    normalized = str(key).lower()
                    if any(part in normalized for part in forbidden):
                        raise NativeTopologyReconciliationError("operation report contains a prohibited content or credential field")
                    inspect(item, depth + 1)
            elif isinstance(value, list):
                if len(value) > 4096:
                    raise NativeTopologyReconciliationError("operation report contains too many items")
                for item in value:
                    inspect(item, depth + 1)
        inspect(details)
        details_json = self._canonical(details)
        if len(details_json.encode("utf-8")) > 512 * 1024:
            raise NativeTopologyReconciliationError("operation report exceeds the 512 KiB audit limit")
        with self.database.connection() as connection:
            project = connection.execute(
                "SELECT project_id FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
            if project is None:
                raise NativeTopologyReconciliationNotFound("Project not found")
            if profile_id is not None:
                profile = connection.execute(
                    "SELECT profile_id FROM topology_profiles WHERE profile_id=? AND project_id=?",
                    (profile_id, project_id),
                ).fetchone()
                if profile is None:
                    raise NativeTopologyReconciliationNotFound("Topology profile not found in the selected Project")
        operation_id = "nto_" + secrets.token_hex(12)
        now = self._now().isoformat()
        audit_details = {
            "project_id": project_id,
            "profile_id": profile_id,
            "operation_type": operation_type,
            "report": json.loads(details_json),
        }
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO audit_events(
                    audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    "AUD-" + secrets.token_hex(12), actor,
                    "NATIVE_TOPOLOGY_" + operation_type + "_RECORDED",
                    "NATIVE_TOPOLOGY_OPERATION", operation_id,
                    self._canonical(audit_details), now,
                ),
            )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "profile_id": profile_id,
            "operation_type": operation_type,
            "occurred_at": now,
        }

    def reconcile(
        self,
        profile_id: str,
        *,
        topology_revision_id: str,
        presentation_id: str,
        source_id: str,
        actor: str,
    ) -> dict[str, Any]:
        actor = self._actor(actor)
        profile = self.topology.get_profile(profile_id)
        revision = self.topology.get_revision(topology_revision_id)
        presentation = self.presentation.get_revision(presentation_id)
        if profile is None or revision is None or presentation is None:
            raise NativeTopologyReconciliationNotFound(
                "topology profile, revision or presentation was not found"
            )
        if (
            profile["status"] != "ACTIVE"
            or revision["profile_id"] != profile_id
            or presentation["profile_id"] != profile_id
            or presentation["topology_revision_id"] != topology_revision_id
        ):
            raise NativeTopologyReconciliationNotFound(
                "selected topology revision and presentation are not in the requested profile"
            )

        findings: list[dict[str, Any]] = []
        profile_scope = {
            "project_id": profile["project_id"],
            "profile_id": profile_id,
            "topology_revision_id": topology_revision_id,
            "presentation_id": presentation_id,
            "source_id": source_id,
        }
        source = None
        source_bytes = None
        try:
            source = self.sources.get_source_artifact(source_id, include_bytes=True)
            if source is None or source["profile_id"] != profile_id or source["project_id"] != profile["project_id"]:
                raise NativeTopologyReconciliationNotFound("native source artifact was not found in this profile")
            source_bytes = source["source_bytes"]
        except (TopologySourceArtifactError, NativeTopologyReconciliationNotFound) as exc:
            if isinstance(exc, NativeTopologyReconciliationNotFound):
                raise
            findings.append(self._finding(
                "NATIVE_SOURCE_INTEGRITY_FAILED", "ERROR",
                "The retained native source bytes failed size or SHA-256 verification",
            ))

        if source is not None:
            if (
                source["topology_revision_id"] != topology_revision_id
                or source["topology_content_sha256"] != revision["content_sha256"]
                or presentation.get("source_artifact_id") != source_id
                or presentation.get("topology_content_sha256") != revision["content_sha256"]
            ):
                findings.append(self._finding(
                    "NATIVE_PROVENANCE_BINDING_MISMATCH", "ERROR",
                    "The source, canonical topology revision and presentation do not share one immutable revision/hash binding",
                ))

        if source is not None and source_bytes is not None:
            try:
                decoded = self.interop.codecs.decode(source_bytes, source["filename"])
                _normalized, _encoded, decoded_hash = self.topology.canonical_payload(
                    decoded.topology_definition
                )
                if decoded_hash != revision["content_sha256"]:
                    findings.append(self._finding(
                        "NATIVE_SOURCE_TOPOLOGY_DRIFT", "ERROR",
                        "The retained native source decodes to a different canonical topology hash",
                        decoded_topology_sha256=decoded_hash,
                        expected_topology_sha256=revision["content_sha256"],
                    ))
                if decoded.format_id != source["format_id"] or decoded.format_version != source["format_version"]:
                    findings.append(self._finding(
                        "NATIVE_FORMAT_PROVENANCE_MISMATCH", "ERROR",
                        "The decoded native source format/version differs from its immutable provenance record",
                    ))
                source_warnings = list(decoded.warnings)
                if source_warnings:
                    findings.append(self._finding(
                        "NATIVE_SOURCE_CODEC_WARNINGS", "WARNING",
                        "The retained native source decoder reported unsupported or omitted fields",
                        warning_count=len(source_warnings),
                    ))
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                source_warnings = []
                findings.append(self._finding(
                    "NATIVE_SOURCE_DECODE_FAILED", "ERROR",
                    "The retained native source could not be decoded by its recorded format codec",
                    error_type=type(exc).__name__,
                ))
        else:
            source_warnings = []

        asset_evidence = []
        if source is not None:
            try:
                for asset in self.sources.list_assets(source_id):
                    try:
                        asset_bytes = self.sources.get_asset_bytes(source_id, asset["asset_id"])
                        valid = len(asset_bytes) == asset["size_bytes"] and hashlib.sha256(asset_bytes).hexdigest() == asset["sha256"]
                    except TopologySourceArtifactError:
                        valid = False
                    if not valid:
                        findings.append(self._finding(
                            "NATIVE_ASSET_INTEGRITY_FAILED", "ERROR",
                            "A native source asset failed its stored size or SHA-256 verification",
                            asset_id=asset["asset_id"], relative_path=asset["relative_path"],
                        ))
                    asset_evidence.append({
                        "asset_id": asset["asset_id"], "relative_path": asset["relative_path"],
                        "media_type": asset["media_type"], "sha256": asset["sha256"],
                        "size_bytes": asset["size_bytes"], "integrity": "VERIFIED" if valid else "FAILED",
                    })
            except TopologySourceArtifactError:
                findings.append(self._finding(
                    "NATIVE_ASSET_MANIFEST_UNAVAILABLE", "ERROR",
                    "Native source asset manifest could not be read",
                ))

        export_evidence = {
            "status": "NOT_RUN",
            "originating_application_reopen": "NOT_VERIFIED",
            "losses": [],
        }
        if (
            source is not None and source_bytes is not None
            and revision["status"] == "PUBLISHED"
            and presentation["status"] == "PUBLISHED"
        ):
            try:
                exported = self.interop.export_revision(
                    profile_id=profile_id,
                    revision_id=topology_revision_id,
                    presentation_id=presentation_id,
                    source_id=source_id,
                )
                reopened = self.interop.codecs.decode(exported.content, exported.filename)
                _out, _out_json, exported_topology_hash = self.topology.canonical_payload(
                    reopened.topology_definition
                )
                matched = exported_topology_hash == revision["content_sha256"]
                export_evidence = {
                    "status": "VERIFIED" if matched else "DRIFT_DETECTED",
                    "filename": exported.filename,
                    "sha256": hashlib.sha256(exported.content).hexdigest(),
                    "size_bytes": len(exported.content),
                    "decoded_topology_sha256": exported_topology_hash,
                    "expected_topology_sha256": revision["content_sha256"],
                    "codec_read_back": exported.report.get("codec_read_back"),
                    "losses": exported.report.get("losses", []),
                    "originating_application_reopen": "NOT_VERIFIED",
                }
                if not matched:
                    findings.append(self._finding(
                        "NATIVE_EXPORT_ROUNDTRIP_MISMATCH", "ERROR",
                        "The exported native file did not decode to the selected canonical topology revision",
                    ))
                if export_evidence["losses"]:
                    findings.append(self._finding(
                        "NATIVE_EXPORT_DECLARED_LOSSES", "WARNING",
                        "The native codec reported fields that are outside its supported export subset",
                        loss_count=len(export_evidence["losses"]),
                    ))
            except (NativeTopologyInteropConflict, NativeTopologyInteropError, NativeTopologyInteropNotFound, ValueError, TypeError, KeyError, IndexError) as exc:
                export_evidence = {
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                    "originating_application_reopen": "NOT_VERIFIED",
                    "losses": [],
                }
                findings.append(self._finding(
                    "NATIVE_EXPORT_VERIFICATION_FAILED", "ERROR",
                    "The selected native presentation could not be exported and read back by its codec",
                    error_type=type(exc).__name__,
                ))
        else:
            findings.append(self._finding(
                "NATIVE_EXPORT_NOT_VERIFIED", "WARNING",
                "Native codec export/read-back requires both selected topology and presentation revisions to be published",
            ))

        configuration_snapshots, device_ids = self._collect_configuration_snapshots(
            profile, revision, self._now(), findings
        )
        now = self._now()
        observations = self._collect_live_observations(profile, device_ids, now, findings)
        partial_operations = self._collect_partial_operations(profile, revision, now, findings)
        operations = self._operation_history(profile, limit=100)

        integrity_errors = any(item["severity"] == "ERROR" for item in findings)
        if partial_operations["uncertain"]:
            status = "RECONCILIATION_REQUIRED"
        elif integrity_errors:
            status = "DRIFT_DETECTED"
        elif (
            revision["status"] != "PUBLISHED"
            or presentation["status"] != "PUBLISHED"
            or export_evidence["status"] != "VERIFIED"
            or not partial_operations["topology_readback"]["verified"]
            or any(item["severity"] == "WARNING" for item in findings)
        ):
            status = "INCOMPLETE"
        else:
            status = "CLEAN"

        details = {
            "schema_version": self.SCHEMA_VERSION,
            "scope": profile_scope,
            "status": status,
            "topology": {
                "status": revision["status"],
                "content_sha256": revision["content_sha256"],
                "node_count": len(revision["definition"]["nodes"]),
                "link_count": len(revision["definition"]["links"]),
            },
            "presentation": {
                "status": presentation["status"],
                "presentation_sha256": presentation["presentation_sha256"],
                "topology_content_sha256": presentation["topology_content_sha256"],
                "source_artifact_id": presentation.get("source_artifact_id"),
            },
            "native_source": None if source is None else {
                "source_id": source["source_id"], "format_id": source["format_id"],
                "format_version": source["format_version"], "filename": source["filename"],
                "codec_name": source["codec_name"], "codec_version": source["codec_version"],
                "sha256": source["sha256"], "size_bytes": source["size_bytes"],
                "asset_count": source["asset_count"], "imported_at": source["imported_at"],
                "integrity": "VERIFIED" if source_bytes is not None else "FAILED",
                "decoder_warnings": source_warnings,
            },
            "assets": asset_evidence,
            "native_export": export_evidence,
            "native_configuration_snapshots": configuration_snapshots,
            "observations": observations,
            "operations": partial_operations,
            "operation_history": operations,
            "external_acceptance": {
                "originating_vendor_application_reopen": "NOT_VERIFIED",
                "live_device_configuration_convergence": "NOT_VERIFIED",
                "protected_lab_acceptance": "NOT_VERIFIED",
            },
            "findings": findings,
            "summary": {
                "finding_count": len(findings),
                "error_count": sum(item["severity"] == "ERROR" for item in findings),
                "warning_count": sum(item["severity"] == "WARNING" for item in findings),
                "uncertain_operation_count": len(partial_operations["uncertain"]),
                "configuration_snapshot_count": len(configuration_snapshots),
                "device_observation_count": len(observations["device"]),
                "provider_observation_count": len(observations["provider"]),
                "asset_count": len(asset_evidence),
            },
        }
        details_json = self._canonical(details)
        details_size = len(details_json.encode("utf-8"))
        if details_size > self.MAX_DETAILS_BYTES:
            raise NativeTopologyReconciliationError(
                "reconciliation evidence exceeds the four MiB persistence limit"
            )
        digest = hashlib.sha256(details_json.encode("utf-8")).hexdigest()
        reconciliation_id = "ntr_" + secrets.token_hex(12)
        created_at = self._now().isoformat()

        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO native_topology_reconciliations(
                    reconciliation_id,project_id,profile_id,topology_revision_id,
                    presentation_id,source_id,status,reconciliation_sha256,details_json,
                    created_at,created_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    reconciliation_id, profile["project_id"], profile_id,
                    topology_revision_id, presentation_id, source_id, status,
                    digest, details_json, created_at, actor,
                ),
            )
            connection.execute(
                """INSERT INTO audit_events(
                    audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    "AUD-" + secrets.token_hex(12), actor, "NATIVE_TOPOLOGY_RECONCILED",
                    "NATIVE_TOPOLOGY_RECONCILIATION", reconciliation_id,
                    self._canonical({
                        "project_id": profile["project_id"], "profile_id": profile_id,
                        "topology_revision_id": topology_revision_id,
                        "presentation_id": presentation_id, "source_id": source_id,
                        "status": status, "reconciliation_sha256": digest,
                        "finding_count": len(findings),
                        "uncertain_operation_count": len(partial_operations["uncertain"]),
                    }),
                    created_at,
                ),
            )
        return self.get_reconciliation(profile_id, reconciliation_id) or {}
