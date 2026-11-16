"""Durable, Project/Lab-scoped pipeline definitions and execution orchestration."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import secrets
from typing import Any, Callable, Mapping

from lib.repositories import SQLiteDatabase


class PipelineError(ValueError):
    """Invalid pipeline definition, scope or lifecycle transition."""


class PipelineNotFound(LookupError):
    """Pipeline or execution was not found in the requested scope."""


class PipelineConflict(PipelineError):
    """Pipeline state changed or an operation is not safe to retry."""


class PipelineRetryableError(RuntimeError):
    """A handler explicitly classified a failure as safe for bounded retry."""


class PipelineRecoveryRequired(RuntimeError):
    """A provider operation has an uncertain outcome and needs observation."""


_PIPELINE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_STEP_TYPES = frozenset({
    "WIFI_LAB_PROVISION", "TOPOLOGY_APPLY", "PROVIDER_RECONCILE",
    "CONFIGURATION_DEPLOY", "VALIDATION_RUN",
})
_SECRET_PARTS = ("password", "passwd", "secret", "private_key", "api_key", "psk")


class PipelineService:
    MAX_STEPS = 32
    MAX_INPUT_BYTES = 16384
    MAX_RESULT_BYTES = 32768
    MAX_TIMEOUT_SECONDS = 3600

    def __init__(self, database: SQLiteDatabase, *, clock: Callable[[], datetime] | None = None):
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> str:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise PipelineError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _text(value: object, field: str, maximum: int = 128) -> str:
        if not isinstance(value, str):
            raise PipelineError(f"{field} must be a string")
        result = value.strip()
        if not result or len(result) > maximum or any(ord(char) < 32 for char in result):
            raise PipelineError(f"{field} must contain 1 to {maximum} printable characters")
        return result

    @classmethod
    def _safe_object(cls, value: object, field: str, maximum: int) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise PipelineError(f"{field} must be a JSON object")

        def inspect(item: object, depth: int = 0):
            if depth > 6:
                raise PipelineError(f"{field} nesting exceeds the supported depth")
            if isinstance(item, Mapping):
                result = {}
                for raw_key, child in item.items():
                    key = str(raw_key)
                    lower = key.lower()
                    opaque_reference = lower.endswith("_id")
                    if (
                        not key or len(key) > 64
                        or (not opaque_reference and any(part in lower for part in cls_secret_parts))
                    ):
                        raise PipelineError(f"{field} cannot contain secret material or credential values")
                    result[key] = inspect(child, depth + 1)
                return result
            if isinstance(item, (list, tuple)):
                if len(item) > 256:
                    raise PipelineError(f"{field} arrays are limited to 256 entries")
                return [inspect(child, depth + 1) for child in item]
            if item is None or isinstance(item, (str, bool, int)):
                if isinstance(item, str) and (len(item) > 2048 or any(ord(ch) < 32 for ch in item)):
                    raise PipelineError(f"{field} contains an overlong string or control character")
                return item
            if isinstance(item, float):
                import math
                if not math.isfinite(item):
                    raise PipelineError(f"{field} numeric values must be finite")
                return item
            raise PipelineError(f"{field} contains an unsupported value")

        cls_secret_parts = _SECRET_PARTS
        result = inspect(value)
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > maximum:
            raise PipelineError(f"{field} exceeds {maximum} bytes")
        return result

    @classmethod
    def normalize_definition(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {"steps"}:
            raise PipelineError("pipeline definition must contain only a steps array")
        raw_steps = value.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps or len(raw_steps) > cls.MAX_STEPS:
            raise PipelineError(f"pipeline must contain between 1 and {cls.MAX_STEPS} steps")
        steps = []
        keys = set()
        for ordinal, raw in enumerate(raw_steps):
            if not isinstance(raw, Mapping) or set(raw) - {
                "key", "type", "name", "timeout_seconds", "max_attempts", "input",
            }:
                raise PipelineError(f"steps[{ordinal}] contains unsupported fields")
            key = cls._text(raw.get("key"), f"steps[{ordinal}].key", 64)
            if not _PIPELINE_KEY.fullmatch(key) or key in keys:
                raise PipelineError(f"steps[{ordinal}].key is invalid or duplicated")
            keys.add(key)
            step_type = cls._text(raw.get("type"), f"steps[{ordinal}].type", 32).upper()
            if step_type not in _STEP_TYPES:
                raise PipelineError(f"steps[{ordinal}].type is not supported")
            name = str(raw.get("name") or step_type.replace("_", " ").title()).strip()
            if not name or len(name) > 120:
                raise PipelineError(f"steps[{ordinal}].name must contain 1 to 120 characters")
            timeout = raw.get("timeout_seconds", 300)
            retries = raw.get("max_attempts", 1)
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 5 <= timeout <= cls.MAX_TIMEOUT_SECONDS:
                raise PipelineError(f"steps[{ordinal}].timeout_seconds must be 5 to {cls.MAX_TIMEOUT_SECONDS}")
            if isinstance(retries, bool) or not isinstance(retries, int) or not 1 <= retries <= 5:
                raise PipelineError(f"steps[{ordinal}].max_attempts must be between 1 and 5")
            if step_type in {"WIFI_LAB_PROVISION", "TOPOLOGY_APPLY", "CONFIGURATION_DEPLOY", "VALIDATION_RUN"} and retries > 1:
                raise PipelineError(f"steps[{ordinal}] is state-changing or execution-bearing; automatic retry is disabled")
            inputs = cls._safe_object(raw.get("input", {}), f"steps[{ordinal}].input", 8192)
            expected = {
                "WIFI_LAB_PROVISION": {"confirmed"},
                "TOPOLOGY_APPLY": {"profile_id", "revision_id", "expected_sha256", "confirmed"},
                "PROVIDER_RECONCILE": {"profile_id", "revision_id"},
                "CONFIGURATION_DEPLOY": {
                    "profile_id", "revision_id", "configuration_hash", "device_id",
                    "ssh_credential_id", "wifi_psk_credential_id", "confirmed",
                },
                "VALIDATION_RUN": {
                    "tests", "firmware_version", "performance_policy_revision_id",
                    "configuration_profile_id", "configuration_revision_id",
                    "topology_profile_id", "topology_revision_id",
                },
            }[step_type]
            if step_type != "VALIDATION_RUN" and set(inputs) != expected:
                raise PipelineError(f"steps[{ordinal}].input must contain exactly {sorted(expected)}")
            if step_type == "VALIDATION_RUN" and (not {"tests"} <= set(inputs) or set(inputs) - expected):
                raise PipelineError(f"steps[{ordinal}].input must contain tests and only supported Run references")
            if step_type in {"WIFI_LAB_PROVISION", "TOPOLOGY_APPLY", "CONFIGURATION_DEPLOY"} and inputs.get("confirmed") is not True:
                raise PipelineError(f"steps[{ordinal}] requires confirmed=true in its immutable pipeline revision")
            if step_type in {"TOPOLOGY_APPLY", "PROVIDER_RECONCILE"}:
                cls._text(inputs.get("profile_id"), f"steps[{ordinal}].input.profile_id")
                cls._text(inputs.get("revision_id"), f"steps[{ordinal}].input.revision_id")
            if step_type == "TOPOLOGY_APPLY" and not _HASH.fullmatch(str(inputs.get("expected_sha256", ""))):
                raise PipelineError(f"steps[{ordinal}].input.expected_sha256 must be a SHA-256 digest")
            if step_type == "CONFIGURATION_DEPLOY":
                for field_name in ("profile_id", "revision_id", "device_id", "ssh_credential_id", "wifi_psk_credential_id"):
                    cls._text(inputs.get(field_name), f"steps[{ordinal}].input.{field_name}")
                if not _HASH.fullmatch(str(inputs.get("configuration_hash", ""))):
                    raise PipelineError(f"steps[{ordinal}].input.configuration_hash must be a SHA-256 digest")
            if step_type == "VALIDATION_RUN":
                tests = inputs.get("tests")
                if not isinstance(tests, list) or not tests or len(tests) > 200 or any(not isinstance(t, str) or not t.strip() for t in tests):
                    raise PipelineError(f"steps[{ordinal}].input.tests must contain between 1 and 200 test identifiers")
                if len(set(tests)) != len(tests):
                    raise PipelineError(f"steps[{ordinal}].input.tests cannot contain duplicates")
                firmware = inputs.get("firmware_version", "v1.0")
                if not isinstance(firmware, str) or not firmware.strip() or len(firmware) > 80:
                    raise PipelineError(f"steps[{ordinal}].input.firmware_version is invalid")
                inputs.setdefault("firmware_version", firmware)
            steps.append({
                "key": key, "ordinal": ordinal, "type": step_type, "name": name,
                "timeout_seconds": timeout, "max_attempts": retries, "input": inputs,
            })
        return {"steps": steps}

    @classmethod
    def canonical_definition(cls, value: object) -> tuple[dict, str, str]:
        normalized = cls.normalize_definition(value)
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return normalized, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _audit(connection, actor: str, action: str, resource_type: str, resource_id: str, details: dict) -> None:
        connection.execute(
            """INSERT INTO audit_events(
               audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
               ) VALUES(?,?,?,?,?,?,?)""",
            ("AUD-" + secrets.token_hex(12), actor, action, resource_type, resource_id,
             json.dumps(details, sort_keys=True, separators=(",", ":")), datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def _pipeline(row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in (
            "pipeline_id", "project_id", "lab_id", "name", "description", "status",
            "created_at", "updated_at", "created_by", "updated_by",
        )}

    @staticmethod
    def _revision(row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in (
            "revision_id", "pipeline_id", "revision_number", "definition_sha256",
            "status", "created_at", "created_by", "published_at", "published_by",
        )} | {"definition": json.loads(row["definition_json"])}

    @staticmethod
    def _execution(row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in (
            "execution_id", "project_id", "lab_id", "pipeline_id", "revision_id",
            "definition_sha256", "status", "linked_run_id", "idempotency_key",
            "created_at", "started_at", "completed_at", "created_by", "worker_id",
            "lease_expires_at", "heartbeat_at", "attempt_count", "last_error",
        )} | {"inputs": json.loads(row["inputs_json"]), "result": json.loads(row["result_json"])}

    @staticmethod
    def _step(row) -> dict:
        return {key: row[key] for key in (
            "execution_id", "step_key", "ordinal", "step_type", "status", "max_attempts",
            "attempt_count", "timeout_seconds", "next_attempt_at", "worker_id",
            "lease_expires_at", "created_at", "started_at", "completed_at", "last_error",
        )} | {"definition": json.loads(row["definition_json"]), "result": json.loads(row["result_json"])}

    def create_pipeline(self, *, project_id: str, lab_id: str, name: str, description: str, definition: object, actor: str) -> dict:
        actor = self._actor(actor)
        project_id = self._text(project_id, "project_id")
        lab_id = self._text(lab_id, "lab_id")
        name = self._text(name, "name", 120)
        description = str(description or "").strip()
        if len(description) > 500:
            raise PipelineError("description must be at most 500 characters")
        _normalized, encoded, digest = self.canonical_definition(definition)
        with self.database.connection() as connection:
            scope = connection.execute(
                """SELECT l.status AS lab_status,p.status AS project_status
                   FROM labs l JOIN projects p ON p.project_id=l.project_id
                   WHERE l.lab_id=? AND l.project_id=?""",
                (lab_id, project_id),
            ).fetchone()
        if scope is None:
            raise PipelineNotFound("Lab not found in the selected Project")
        if scope["lab_status"] != "ACTIVE" or scope["project_status"] != "ACTIVE":
            raise PipelineConflict("pipelines require an active Project and Lab")
        pipeline_id = "pln_" + secrets.token_hex(12)
        revision_id = "plr_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            try:
                connection.execute(
                    """INSERT INTO pipeline_definitions(
                       pipeline_id,project_id,lab_id,name,description,status,created_at,updated_at,created_by,updated_by
                       ) VALUES(?,?,?,?,?,'ACTIVE',?,?,?,?)""",
                    (pipeline_id, project_id, lab_id, name, description, now, now, actor, actor),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise PipelineConflict("a pipeline with this name already exists in the selected Lab") from exc
                raise
            connection.execute(
                """INSERT INTO pipeline_revisions(
                   revision_id,pipeline_id,revision_number,definition_json,definition_sha256,status,
                   created_at,created_by,published_at,published_by)
                   VALUES(?,?,1,?,?,'DRAFT',?,?,NULL,NULL)""",
                (revision_id, pipeline_id, encoded, digest, now, actor),
            )
            self._audit(connection, actor, "PIPELINE_CREATED", "PIPELINE", pipeline_id,
                        {"project_id": project_id, "lab_id": lab_id, "revision_sha256": digest})
        return {"pipeline": self.get_pipeline(pipeline_id), "revision": self.get_revision(revision_id)}

    def get_pipeline(self, pipeline_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM pipeline_definitions WHERE pipeline_id=?", (pipeline_id,)).fetchone()
        return self._pipeline(row)

    def list_pipelines(self, project_id: str, *, lab_id: str | None = None) -> list[dict]:
        query = "SELECT * FROM pipeline_definitions WHERE project_id=?"
        params: list[object] = [project_id]
        if lab_id:
            query += " AND lab_id=?"
            params.append(lab_id)
        query += " ORDER BY name COLLATE NOCASE,pipeline_id"
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
            output = []
            for row in rows:
                item = self._pipeline(row)
                latest = connection.execute(
                    "SELECT revision_id,revision_number,status,definition_sha256 FROM pipeline_revisions WHERE pipeline_id=? ORDER BY revision_number DESC LIMIT 1",
                    (item["pipeline_id"],),
                ).fetchone()
                item["latest_revision"] = dict(latest) if latest else None
                output.append(item)
        return output

    def get_revision(self, revision_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM pipeline_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        return self._revision(row)

    def list_revisions(self, pipeline_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM pipeline_revisions WHERE pipeline_id=? ORDER BY revision_number DESC",
                (pipeline_id,),
            ).fetchall()
        return [self._revision(row) for row in rows]

    def create_revision(self, pipeline_id: str, *, definition: object, actor: str) -> dict:
        actor = self._actor(actor)
        pipeline = self.get_pipeline(pipeline_id)
        if pipeline is None:
            raise PipelineNotFound("pipeline not found")
        if pipeline["status"] != "ACTIVE":
            raise PipelineConflict("archived pipelines cannot receive revisions")
        _normalized, encoded, digest = self.canonical_definition(definition)
        revision_id = "plr_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            number = int(connection.execute(
                "SELECT COALESCE(MAX(revision_number),0)+1 FROM pipeline_revisions WHERE pipeline_id=?",
                (pipeline_id,),
            ).fetchone()[0])
            connection.execute(
                """INSERT INTO pipeline_revisions(
                   revision_id,pipeline_id,revision_number,definition_json,definition_sha256,status,
                   created_at,created_by,published_at,published_by)
                   VALUES(?,?,?,?,?,'DRAFT',?,?,NULL,NULL)""",
                (revision_id, pipeline_id, number, encoded, digest, now, actor),
            )
            connection.execute(
                "UPDATE pipeline_definitions SET updated_at=?,updated_by=? WHERE pipeline_id=? AND status='ACTIVE'",
                (now, actor, pipeline_id),
            )
            self._audit(connection, actor, "PIPELINE_REVISION_CREATED", "PIPELINE_REVISION", revision_id,
                        {"pipeline_id": pipeline_id, "revision_number": number, "definition_sha256": digest})
        return self.get_revision(revision_id)

    def publish_revision(self, pipeline_id: str, revision_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        pipeline = self.get_pipeline(pipeline_id)
        revision = self.get_revision(revision_id)
        if pipeline is None or revision is None or revision["pipeline_id"] != pipeline_id:
            raise PipelineNotFound("pipeline or revision not found")
        if pipeline["status"] != "ACTIVE" or revision["status"] != "DRAFT":
            raise PipelineConflict("only a draft revision on an active pipeline can be published")
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE pipeline_revisions SET status='PUBLISHED',published_at=?,published_by=? WHERE revision_id=? AND status='DRAFT'",
                (now, actor, revision_id),
            )
            if cursor.rowcount != 1:
                raise PipelineConflict("pipeline revision changed during publish")
            connection.execute(
                "UPDATE pipeline_definitions SET updated_at=?,updated_by=? WHERE pipeline_id=?",
                (now, actor, pipeline_id),
            )
            self._audit(connection, actor, "PIPELINE_REVISION_PUBLISHED", "PIPELINE_REVISION", revision_id,
                        {"pipeline_id": pipeline_id, "definition_sha256": revision["definition_sha256"]})
        return self.get_revision(revision_id)

    def enqueue(self, pipeline_id: str, *, revision_id: str | None = None, inputs: object = None,
                idempotency_key: str | None = None, actor: str) -> dict:
        actor = self._actor(actor)
        pipeline = self.get_pipeline(pipeline_id)
        if pipeline is None:
            raise PipelineNotFound("pipeline not found")
        if pipeline["status"] != "ACTIVE":
            raise PipelineConflict("archived pipelines cannot be executed")
        if revision_id is None:
            revision = next((item for item in self.list_revisions(pipeline_id) if item["status"] == "PUBLISHED"), None)
        else:
            revision = self.get_revision(revision_id)
        if revision is None or revision["pipeline_id"] != pipeline_id or revision["status"] != "PUBLISHED":
            raise PipelineConflict("execution requires a published revision belonging to this pipeline")
        safe_inputs = self._safe_object(inputs or {}, "execution inputs", self.MAX_INPUT_BYTES)
        execution_id = "plex_" + secrets.token_hex(12)
        now = self._now()
        steps = revision["definition"]["steps"]
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO pipeline_executions(
                   execution_id,project_id,lab_id,pipeline_id,revision_id,definition_sha256,status,
                   inputs_json,result_json,linked_run_id,idempotency_key,created_at,started_at,completed_at,
                   created_by,worker_id,lease_expires_at,heartbeat_at,attempt_count,last_error
                   ) VALUES(?,?,?,?,?,?,'QUEUED',?,'{}',NULL,?,?,NULL,NULL,?,NULL,NULL,NULL,0,NULL)""",
                (execution_id, pipeline["project_id"], pipeline["lab_id"], pipeline_id,
                 revision["revision_id"], revision["definition_sha256"],
                 json.dumps(safe_inputs, sort_keys=True, separators=(",", ":")),
                 idempotency_key, now, actor),
            )
            for step in steps:
                connection.execute(
                    """INSERT INTO pipeline_steps(
                       execution_id,step_key,ordinal,step_type,status,definition_json,result_json,
                       max_attempts,attempt_count,timeout_seconds,next_attempt_at,worker_id,
                       lease_expires_at,created_at,started_at,completed_at,last_error
                       ) VALUES(?,?,?,?,'PENDING',?,'{}',?,0,?,NULL,NULL,NULL,?,NULL,NULL,NULL)""",
                    (execution_id, step["key"], step["ordinal"], step["type"],
                     json.dumps(step, sort_keys=True, separators=(",", ":")),
                     step["max_attempts"], step["timeout_seconds"], now),
                )
            self._audit(connection, actor, "PIPELINE_EXECUTION_QUEUED", "PIPELINE_EXECUTION", execution_id,
                        {"pipeline_id": pipeline_id, "revision_id": revision["revision_id"]})
        return self.get_execution(execution_id)

    def get_execution(self, execution_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM pipeline_executions WHERE execution_id=?", (execution_id,)).fetchone()
            if row is None:
                return None
            execution = self._execution(row)
            step_rows = connection.execute(
                "SELECT * FROM pipeline_steps WHERE execution_id=? ORDER BY ordinal", (execution_id,),
            ).fetchall()
            attempt_rows = connection.execute(
                "SELECT * FROM pipeline_step_attempts WHERE execution_id=? ORDER BY started_at,attempt_number",
                (execution_id,),
            ).fetchall()
        execution["steps"] = [self._step(item) for item in step_rows]
        execution["attempts"] = [{
            key: item[key] for key in (
                "step_attempt_id", "execution_id", "step_key", "attempt_number", "status",
                "worker_id", "started_at", "completed_at", "error_summary",
            )
        } | {"result": json.loads(item["result_json"])} for item in attempt_rows]
        return execution

    def list_executions(self, pipeline_id: str, *, limit: int = 50) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise PipelineError("limit must be an integer")
        limit = max(1, min(limit, 100))
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT execution_id FROM pipeline_executions WHERE pipeline_id=? ORDER BY created_at DESC LIMIT ?",
                (pipeline_id, limit),
            ).fetchall()
        return [self.get_execution(row["execution_id"]) for row in rows]

    def cancel(self, execution_id: str, *, actor: str) -> dict:
        actor = self._actor(actor)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT status FROM pipeline_executions WHERE execution_id=?", (execution_id,)).fetchone()
            if row is None:
                raise PipelineNotFound("pipeline execution not found")
            if row["status"] == "QUEUED":
                status = "CANCELLED"
                connection.execute(
                    "UPDATE pipeline_steps SET status='CANCELLED',completed_at=? WHERE execution_id=? AND status IN ('PENDING','RETRY_WAIT')",
                    (now, execution_id),
                )
                connection.execute(
                    "UPDATE pipeline_executions SET status='CANCELLED',completed_at=?,last_error=? WHERE execution_id=?",
                    (now, "cancelled by " + actor, execution_id),
                )
            elif row["status"] == "RUNNING":
                status = "CANCELLING"
                connection.execute(
                    "UPDATE pipeline_steps SET status='CANCELLED',completed_at=? WHERE execution_id=? AND status IN ('PENDING','RETRY_WAIT')",
                    (now, execution_id),
                )
                connection.execute(
                    "UPDATE pipeline_executions SET status='CANCELLING',last_error=? WHERE execution_id=?",
                    ("cancellation requested by " + actor, execution_id),
                )
            elif row["status"] in {"CANCELLING", "CANCELLED"}:
                pass
            else:
                raise PipelineConflict("only queued or running pipeline executions can be cancelled")
            self._audit(connection, actor, "PIPELINE_EXECUTION_CANCEL_REQUESTED", "PIPELINE_EXECUTION", execution_id, {})
        return self.get_execution(execution_id)

    def recover(self, execution_id: str, *, confirmed: bool, actor: str) -> dict:
        actor = self._actor(actor)
        if confirmed is not True:
            raise PipelineConflict("explicit recovery confirmation is required")
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            execution = connection.execute("SELECT status FROM pipeline_executions WHERE execution_id=?", (execution_id,)).fetchone()
            if execution is None:
                raise PipelineNotFound("pipeline execution not found")
            if execution["status"] != "RECOVERY_REQUIRED":
                raise PipelineConflict("only a RECOVERY_REQUIRED execution can be resumed")
            steps = connection.execute(
                "SELECT step_key,max_attempts FROM pipeline_steps WHERE execution_id=? AND status='RECOVERY_REQUIRED'",
                (execution_id,),
            ).fetchall()
            if not steps:
                raise PipelineConflict("execution has no recoverable steps")
            for step in steps:
                if int(step["max_attempts"]) >= 5:
                    raise PipelineConflict("step attempt limit reached; create a new execution after reviewing provider state")
                connection.execute(
                    """UPDATE pipeline_steps SET status='PENDING',max_attempts=max_attempts+1,
                       worker_id=NULL,lease_expires_at=NULL,next_attempt_at=NULL,last_error=NULL,completed_at=NULL
                       WHERE execution_id=? AND step_key=?""",
                    (execution_id, step["step_key"]),
                )
            connection.execute(
                """UPDATE pipeline_executions SET status='QUEUED',worker_id=NULL,lease_expires_at=NULL,
                   heartbeat_at=?,last_error=? WHERE execution_id=?""",
                (now, "recovery explicitly approved by " + actor, execution_id),
            )
            self._audit(connection, actor, "PIPELINE_EXECUTION_RECOVERY_APPROVED", "PIPELINE_EXECUTION", execution_id,
                        {"recoverable_steps": [step["step_key"] for step in steps]})
        return self.get_execution(execution_id)

    def link_run(self, execution_id: str, run_id: str) -> dict:
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            execution = connection.execute(
                "SELECT project_id,lab_id,linked_run_id,status FROM pipeline_executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            run = connection.execute(
                "SELECT project_id,lab_id FROM runs WHERE run_id=?", (run_id,),
            ).fetchone()
            if execution is None or run is None:
                raise PipelineNotFound("pipeline execution or Run not found")
            if run["project_id"] != execution["project_id"] or run["lab_id"] != execution["lab_id"]:
                raise PipelineConflict("linked Run must belong to the same Project and Lab")
            if execution["status"] not in {"RUNNING", "CANCELLING"}:
                raise PipelineConflict("Run can only be linked while a pipeline execution is active")
            if execution["linked_run_id"] not in {None, run_id}:
                raise PipelineConflict("pipeline execution is already linked to another Run")
            connection.execute(
                "UPDATE pipeline_executions SET linked_run_id=?,heartbeat_at=? WHERE execution_id=?",
                (run_id, now, execution_id),
            )
        return self.get_execution(execution_id)

    def run_once(self, worker_id: str, handlers: Mapping[str, Callable[[dict, dict], Mapping[str, Any]]],
                 *, lease_grace_seconds: int = 90) -> dict | None:
        worker_id = self._actor(worker_id)
        now = self._now()
        parsed_now = datetime.fromisoformat(now)
        execution = None
        step = None
        attempt_id = None
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                """SELECT * FROM pipeline_executions
                   WHERE status IN ('QUEUED','RUNNING','CANCELLING')
                     AND (worker_id IS NULL OR worker_id=? OR lease_expires_at IS NULL OR lease_expires_at<=?)
                   ORDER BY created_at,execution_id LIMIT 1""",
                (worker_id, now),
            ).fetchone()
            if row is None:
                return None
            execution = self._execution(row)
            active_steps = connection.execute(
                "SELECT * FROM pipeline_steps WHERE execution_id=? AND status='RUNNING'",
                (execution["execution_id"],),
            ).fetchall()
            if active_steps and row["worker_id"] != worker_id:
                connection.execute(
                    """UPDATE pipeline_steps SET status='RECOVERY_REQUIRED',worker_id=NULL,
                       lease_expires_at=NULL,last_error='worker lease expired during an operation'
                       WHERE execution_id=? AND status='RUNNING'""",
                    (execution["execution_id"],),
                )
                connection.execute(
                    """UPDATE pipeline_step_attempts SET status='RECOVERY_REQUIRED',completed_at=?,
                       error_summary='worker lease expired during an operation'
                       WHERE execution_id=? AND status='RUNNING'""",
                    (now, execution["execution_id"]),
                )
                connection.execute(
                    """UPDATE pipeline_executions SET status='RECOVERY_REQUIRED',worker_id=NULL,
                       lease_expires_at=NULL,heartbeat_at=?,last_error=?
                       WHERE execution_id=?""",
                    (now, "worker lease expired while an operation was in progress", execution["execution_id"]),
                )
                return {"execution_id": execution["execution_id"], "status": "RECOVERY_REQUIRED"}
            if row["worker_id"] and row["worker_id"] != worker_id and row["lease_expires_at"] and row["lease_expires_at"] > now:
                return None
            if row["status"] == "CANCELLING" and not active_steps:
                connection.execute(
                    "UPDATE pipeline_executions SET status='CANCELLED',worker_id=NULL,lease_expires_at=NULL,completed_at=?,heartbeat_at=? WHERE execution_id=?",
                    (now, now, execution["execution_id"]),
                )
                return {"execution_id": execution["execution_id"], "status": "CANCELLED"}
            pending = connection.execute(
                """SELECT * FROM pipeline_steps WHERE execution_id=? AND (
                     status='PENDING' OR (status='RETRY_WAIT' AND (next_attempt_at IS NULL OR next_attempt_at<=?))
                   ) ORDER BY ordinal LIMIT 1""",
                (execution["execution_id"], now),
            ).fetchone()
            if pending is None:
                states = [item["status"] for item in connection.execute(
                    "SELECT status FROM pipeline_steps WHERE execution_id=?", (execution["execution_id"],),
                ).fetchall()]
                if any(state == "RECOVERY_REQUIRED" for state in states):
                    final = "RECOVERY_REQUIRED"
                elif any(state == "FAILED" for state in states):
                    final = "FAILED"
                elif all(state in {"SUCCEEDED", "SKIPPED", "CANCELLED"} for state in states):
                    final = "CANCELLED" if row["status"] == "CANCELLING" or "CANCELLED" in states else "SUCCEEDED"
                else:
                    final = "RUNNING"
                complete = final in {"RECOVERY_REQUIRED", "FAILED", "CANCELLED", "SUCCEEDED"}
                connection.execute(
                    """UPDATE pipeline_executions SET status=?,worker_id=NULL,lease_expires_at=NULL,
                       heartbeat_at=?,completed_at=? WHERE execution_id=?""",
                    (final, now, now if complete else None, execution["execution_id"]),
                )
                return {"execution_id": execution["execution_id"], "status": final}
            lease_until = (parsed_now + timedelta(seconds=int(pending["timeout_seconds"]) + lease_grace_seconds)).isoformat()
            attempt_number = int(pending["attempt_count"]) + 1
            attempt_id = "pla_" + secrets.token_hex(12)
            connection.execute(
                """UPDATE pipeline_executions SET status='RUNNING',worker_id=?,lease_expires_at=?,
                   heartbeat_at=?,started_at=COALESCE(started_at,?),attempt_count=attempt_count+1
                   WHERE execution_id=?""",
                (worker_id, lease_until, now, now, execution["execution_id"]),
            )
            connection.execute(
                """UPDATE pipeline_steps SET status='RUNNING',attempt_count=?,worker_id=?,
                   lease_expires_at=?,started_at=COALESCE(started_at,?),last_error=NULL
                   WHERE execution_id=? AND step_key=?""",
                (attempt_number, worker_id, lease_until, now, execution["execution_id"], pending["step_key"]),
            )
            connection.execute(
                """INSERT INTO pipeline_step_attempts(
                   step_attempt_id,execution_id,step_key,attempt_number,status,worker_id,
                   started_at,completed_at,result_json,error_summary
                   ) VALUES(?,?,?,?,'RUNNING',?,?,NULL,'{}',NULL)""",
                (attempt_id, execution["execution_id"], pending["step_key"], attempt_number, worker_id, now),
            )
            step = self._step(connection.execute(
                "SELECT * FROM pipeline_steps WHERE execution_id=? AND step_key=?",
                (execution["execution_id"], pending["step_key"]),
            ).fetchone())
        handler = handlers.get(step["step_type"])
        try:
            if handler is None:
                raise PipelineError("no worker handler is registered for step type " + step["step_type"])
            raw_result = handler(execution, step)
            safe_result = self._safe_object(raw_result or {}, "step result", self.MAX_RESULT_BYTES)
            outcome = "SUCCEEDED"
            error_summary = None
            next_attempt = None
        except PipelineRecoveryRequired as exc:
            safe_result = {"error_code": "RECOVERY_REQUIRED", "error_type": type(exc).__name__}
            outcome = "RECOVERY_REQUIRED"
            error_summary = "operation outcome is uncertain; observe provider state before retry"
            next_attempt = None
        except PipelineRetryableError as exc:
            retryable = step["attempt_count"] < step["max_attempts"]
            outcome = "RETRY_WAIT" if retryable else "FAILED"
            safe_result = {"error_code": "RETRYABLE_FAILURE", "error_type": type(exc).__name__}
            error_summary = "handler classified the operation as safe for retry"
            delay = min(300, 5 * (2 ** max(0, step["attempt_count"] - 1)))
            next_attempt = (self.clock() + timedelta(seconds=delay)).astimezone(timezone.utc).isoformat() if retryable else None
        except Exception as exc:
            safe_result = {"error_code": "STEP_FAILED", "error_type": type(exc).__name__}
            outcome = "FAILED"
            error_summary = "step failed; inspect its safe result and provider state before another execution"
            next_attempt = None

        finished = self._now()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """UPDATE pipeline_step_attempts SET status=?,completed_at=?,result_json=?,error_summary=?
                   WHERE step_attempt_id=? AND status='RUNNING'""",
                (outcome, finished, json.dumps(safe_result, sort_keys=True, separators=(",", ":")),
                 error_summary, attempt_id),
            )
            connection.execute(
                """UPDATE pipeline_steps SET status=?,result_json=?,worker_id=NULL,lease_expires_at=?,
                   next_attempt_at=?,completed_at=?,last_error=?
                   WHERE execution_id=? AND step_key=? AND status='RUNNING'""",
                (outcome, json.dumps(safe_result, sort_keys=True, separators=(",", ":")),
                 None, next_attempt, finished if outcome in {"SUCCEEDED", "FAILED", "RECOVERY_REQUIRED"} else None,
                 error_summary, execution["execution_id"], step["step_key"]),
            )
            if outcome == "RECOVERY_REQUIRED":
                exec_status, completed_at = "RECOVERY_REQUIRED", finished
            elif outcome == "FAILED":
                exec_status, completed_at = "FAILED", finished
                connection.execute(
                    """UPDATE pipeline_steps SET status='SKIPPED',completed_at=?,last_error='prior step failed'
                       WHERE execution_id=? AND status IN ('PENDING','RETRY_WAIT')""",
                    (finished, execution["execution_id"]),
                )
            elif outcome == "RETRY_WAIT":
                exec_status, completed_at = "QUEUED", None
            else:
                remaining = connection.execute(
                    "SELECT COUNT(*) AS count FROM pipeline_steps WHERE execution_id=? AND status NOT IN ('SUCCEEDED','SKIPPED','CANCELLED')",
                    (execution["execution_id"],),
                ).fetchone()["count"]
                if remaining == 0:
                    exec_status = "CANCELLED" if execution["status"] == "CANCELLING" else "SUCCEEDED"
                    completed_at = finished
                else:
                    exec_status, completed_at = "RUNNING", None
            if execution["status"] == "CANCELLING" and outcome == "SUCCEEDED":
                connection.execute(
                    """UPDATE pipeline_steps SET status='CANCELLED',completed_at=?,last_error='execution cancellation requested'
                       WHERE execution_id=? AND status IN ('PENDING','RETRY_WAIT')""",
                    (finished, execution["execution_id"]),
                )
                exec_status, completed_at = "CANCELLED", finished
            connection.execute(
                """UPDATE pipeline_executions SET status=?,worker_id=NULL,lease_expires_at=NULL,
                   heartbeat_at=?,completed_at=?,last_error=? WHERE execution_id=?""",
                (exec_status, finished, completed_at, error_summary, execution["execution_id"]),
            )
            self._audit(connection, execution["created_by"], "PIPELINE_STEP_" + outcome,
                        "PIPELINE_EXECUTION", execution["execution_id"],
                        {"step_key": step["step_key"], "attempt_number": step["attempt_count"]})
        return {
            "execution_id": execution["execution_id"], "step_key": step["step_key"],
            "step_status": outcome, "execution_status": exec_status, "result": safe_result,
        }
