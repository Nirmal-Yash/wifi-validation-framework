from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Protocol
import uuid

import requests

from .api_security import validate_https_endpoint

from lib.domain import Artifact, Run, SyncEnvelope, SyncQueueItem, SyncState
from lib.repositories import (
    ArtifactRepository,
    AttemptRepository,
    EventRepository,
    RunRepository,
    SQLiteArtifactRepository,
    SQLiteAttemptRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteSyncQueueRepository,
    SyncQueueRepository,
    TestResultRepository,
    SQLiteTestResultRepository,
)


class SyncTransportError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SyncAck:
    accepted: bool
    remote_id: str | None = None
    message: str = ""


class SyncTransport(Protocol):
    def publish(self, envelope: SyncEnvelope) -> SyncAck: ...


class HttpSyncTransport:
    """Minimal outbound transport; Cloud-specific authorization remains external."""

    def __init__(self, url: str, *, bearer_token: str | None = None, timeout_sec: float = 20.0):
        self.url = validate_https_endpoint(url)
        self.bearer_token = bearer_token
        self.timeout_sec = timeout_sec

    def publish(self, envelope: SyncEnvelope) -> SyncAck:
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": envelope.idempotency_key,
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        payload = json.loads(envelope.payload_json)
        payload["envelope_id"] = envelope.envelope_id
        payload["schema_version"] = envelope.schema_version
        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout_sec,
            )
        except requests.RequestException as exc:
            raise SyncTransportError(str(exc)) from exc
        if response.status_code in {200, 201, 202, 204}:
            remote_id = None
            if response.content:
                try:
                    remote_id = response.json().get("remote_id")
                except ValueError:
                    pass
            return SyncAck(True, remote_id=remote_id)
        if response.status_code in {408, 409, 429, 500, 502, 503, 504}:
            raise SyncTransportError(
                f"retryable sync response {response.status_code}: {response.text[:500]}"
            )
        raise SyncTransportError(
            f"non-retryable sync response {response.status_code}: {response.text[:500]}"
        )


class RunnerSyncService:
    SCHEMA_VERSION = "runner-sync.v1"

    def __init__(
        self,
        *,
        run_repository: RunRepository,
        attempt_repository: AttemptRepository,
        test_result_repository: TestResultRepository,
        artifact_repository: ArtifactRepository,
        event_repository: EventRepository,
        queue_repository: SyncQueueRepository,
        runner_id: str,
        clock=lambda: datetime.now(timezone.utc),
        lease_seconds: int = 120,
        max_attempts: int = 8,
    ):
        if not runner_id.strip():
            raise ValueError("runner_id must not be empty")
        if lease_seconds < 1 or max_attempts < 1:
            raise ValueError("lease_seconds and max_attempts must be positive")
        self.run_repository = run_repository
        self.attempt_repository = attempt_repository
        self.test_result_repository = test_result_repository
        self.artifact_repository = artifact_repository
        self.event_repository = event_repository
        self.queue_repository = queue_repository
        self.runner_id = runner_id
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    @classmethod
    def from_sqlite(cls, database: SQLiteDatabase, *, runner_id: str, **kwargs):
        database.initialize()
        return cls(
            run_repository=SQLiteRunRepository(database),
            attempt_repository=SQLiteAttemptRepository(database),
            test_result_repository=SQLiteTestResultRepository(database),
            artifact_repository=SQLiteArtifactRepository(database),
            event_repository=SQLiteEventRepository(database),
            queue_repository=SQLiteSyncQueueRepository(database),
            runner_id=runner_id,
            **kwargs,
        )

    def queue_run(self, run_id: str) -> SyncQueueItem:
        run = self.run_repository.get(run_id)
        if run is None:
            raise ValueError(f"Run not found: {run_id}")
        attempts = self.attempt_repository.list_for_run(run_id)
        results = self.test_result_repository.list_for_run(run_id)
        artifacts = self.artifact_repository.list_for_run(run_id)
        events = self.event_repository.list_for_run(run_id)
        for artifact in artifacts:
            if artifact.soft_deleted_at is None and not self._verify_artifact(artifact):
                raise ValueError(f"artifact failed local integrity verification: {artifact.artifact_id}")

        payload = self._build_payload(run, attempts, results, artifacts, events)
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        payload_sha256 = hashlib.sha256(payload_json.encode()).hexdigest()
        idempotency_key = f"{run_id}:{payload_sha256}"
        envelope_id = hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
        envelope = SyncEnvelope(
            envelope_id=envelope_id,
            runner_id=self.runner_id,
            run_id=run_id,
            kind="RUN_SNAPSHOT",
            schema_version=self.SCHEMA_VERSION,
            idempotency_key=idempotency_key,
            payload_json=payload_json,
            payload_sha256=payload_sha256,
            created_at=self.clock(),
        )
        item = self.queue_repository.enqueue(envelope)
        self.event_repository.append(
            __import__("lib.domain", fromlist=["LifecycleEvent"]).LifecycleEvent(
                event_id=uuid.uuid4().hex,
                run_id=run_id,
                event_type="SYNC_QUEUED",
                occurred_at=self.clock(),
                details={"envelope_id": envelope.envelope_id, "idempotency_key": envelope.idempotency_key},
            )
        )
        return item

    def sync_pending(self, transport: SyncTransport, *, limit: int = 20) -> dict[str, int]:
        now = self.clock()
        self.queue_repository.recover_expired(now)
        delivered = failed = blocked = 0
        for item in self.queue_repository.list_ready(now, limit):
            lease_until = now + timedelta(seconds=self.lease_seconds)
            claimed = self.queue_repository.claim(item.envelope.envelope_id, now, lease_until)
            if claimed is None:
                continue
            try:
                ack = transport.publish(claimed.envelope)
                if not ack.accepted:
                    raise SyncTransportError(ack.message or "transport rejected envelope")
                self.queue_repository.ack(claimed.envelope.envelope_id, self.clock())
                delivered += 1
                self.event_repository.append(
                    __import__("lib.domain", fromlist=["LifecycleEvent"]).LifecycleEvent(
                        event_id=uuid.uuid4().hex,
                        run_id=claimed.envelope.run_id,
                        event_type="SYNC_DELIVERED",
                        occurred_at=self.clock(),
                        details={"envelope_id": claimed.envelope.envelope_id, "remote_id": ack.remote_id},
                    )
                )
            except Exception as exc:
                attempts = claimed.attempt_count + 1
                blocked_now = attempts >= self.max_attempts
                delay = min(3600, 2 ** min(attempts, 10))
                next_attempt = self.clock() + timedelta(seconds=delay)
                self.queue_repository.fail(
                    claimed.envelope.envelope_id,
                    next_attempt_at=next_attempt,
                    error=str(exc),
                    updated_at=self.clock(),
                    blocked=blocked_now,
                )
                if blocked_now:
                    blocked += 1
                    event_type = "SYNC_BLOCKED"
                else:
                    failed += 1
                    event_type = "SYNC_FAILED"
                self.event_repository.append(
                    __import__("lib.domain", fromlist=["LifecycleEvent"]).LifecycleEvent(
                        event_id=uuid.uuid4().hex,
                        run_id=claimed.envelope.run_id,
                        event_type=event_type,
                        occurred_at=self.clock(),
                        details={"envelope_id": claimed.envelope.envelope_id, "attempt": attempts, "error": str(exc)[:500]},
                    )
                )
        return {"delivered": delivered, "failed": failed, "blocked": blocked}

    @staticmethod
    def _verify_artifact(artifact: Artifact) -> bool:
        path = Path(artifact.path)
        if not path.is_file() or path.stat().st_size != artifact.size_bytes:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower() == artifact.sha256.lower()

    def _build_payload(self, run: Run, attempts, results, artifacts, events) -> dict[str, Any]:
        def dt(value):
            return value.isoformat() if value else None

        def test_result_payload(result):
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
                "started_at": dt(result.started_at),
                "completed_at": dt(result.completed_at),
                "metrics": [
                    {
                        "name": metric.name,
                        "unit": metric.unit,
                        "authoritative": metric.authoritative,
                        "samples": [
                            {
                                "value": sample.value,
                                "status": sample.status,
                                "warmup": sample.warmup,
                                "retried": sample.retried,
                                "captured_at": dt(sample.captured_at),
                                "metadata": dict(sample.metadata),
                            }
                            for sample in metric.samples
                        ],
                    }
                    for metric in result.metrics
                ],
            }

        return {
            "schema_version": self.SCHEMA_VERSION,
            "runner_id": self.runner_id,
            "run": {
                "run_id": run.run_id,
                "display_id": run.display_id,
                "firmware_version": run.firmware_version,
                "lab_id": run.lab_id,
                "validation_profile": run.validation_profile,
                "selected_tests": list(run.selected_tests),
                "test_definition_versions": dict(run.test_definition_versions),
                "resolved_config": run.resolved_config,
                "configuration_hash": run.configuration_hash,
                "repository_commit": run.repository_commit,
                "lifecycle": run.lifecycle.value,
                "outcome": run.outcome.value if run.outcome else None,
                "environment_health": run.environment_health.value if run.environment_health else None,
                "created_at": dt(run.created_at),
                "started_at": dt(run.started_at),
                "completed_at": dt(run.completed_at),
                "provenance": run.provenance,
            },
            "attempts": [
                {
                    "attempt_id": attempt.attempt_id,
                    "run_id": attempt.run_id,
                    "number": attempt.number,
                    "started_at": dt(attempt.started_at),
                    "completed_at": dt(attempt.completed_at),
                }
                for attempt in attempts
            ],
            "test_results": [test_result_payload(item) for item in results],
            "artifacts": [
                {
                    "artifact_id": artifact.artifact_id,
                    "run_id": artifact.run_id,
                    "test_result_id": artifact.test_result_id,
                    "artifact_type": artifact.artifact_type.value,
                    "display_name": artifact.display_name,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                    "evidence_state": artifact.evidence_state.value,
                    "sensitivity_class": artifact.sensitivity_class,
                    "retain_until": dt(artifact.retain_until),
                }
                for artifact in artifacts
            ],
            "lifecycle_events": [
                {
                    "event_id": event.event_id,
                    "attempt_id": event.attempt_id,
                    "test_result_id": event.test_result_id,
                    "event_type": event.event_type,
                    "occurred_at": dt(event.occurred_at),
                    "details": dict(event.details),
                }
                for event in events
                if not event.event_type.startswith("SYNC_")
            ],
        }
