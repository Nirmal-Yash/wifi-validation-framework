from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from lib.adapters.fake import FakeDeviceAdapter
from lib.domain import (
    ArtifactType,
    Criticality,
    EvidenceState,
    Metric,
    Run,
    RunLifecycle,
    Severity,
    TestResult,
    TestResultStatus,
    Sample,
)
from lib.repositories import (
    SQLiteDatabase,
    SQLiteRunRepository,
    SQLiteAttemptRepository,
    SQLiteTestResultRepository,
    SQLiteArtifactRepository,
    SQLiteEventRepository,
)
from lib.services import RunService, RunnerSyncService
from lib.services.sync_service import HttpSyncTransport, SyncAck, SyncTransport, SyncTransportError


class FakeTransport:
    def __init__(self):
        self.envelopes=[]
        self.fail=True
    def publish(self,envelope):
        self.envelopes.append(envelope)
        if self.fail:
            raise RuntimeError("offline")
        return SyncAck(True,"remote-1")


def create_run(db):
    service=RunService.from_sqlite(db)
    run,attempt=service.create_run(
        firmware_version="v1.0",lab_id="lab-1",validation_profile="Full",
        selected_tests=["wifi.latency.threshold"],
        test_definition_versions={"wifi.latency.threshold":"1.0"},
        resolved_config={"thresholds":{"max_latency_ms":50}},
        repository_commit="commit",
    )
    service.begin_lab_health_check(run.run_id)
    service.record_environment_health(run.run_id,__import__("lib.domain",fromlist=["EnvironmentHealthStatus"]).EnvironmentHealthStatus.HEALTHY)
    service.start_run_after_health(run.run_id)
    service.record_test_result(
        run_id=run.run_id,attempt_id=attempt.attempt_id,test_id="wifi.latency.threshold",
        node_id="tests/test_ping.py::test_latency_within_threshold",
        status=TestResultStatus.PASS,
        criticality=Criticality.BLOCKING,severity=Severity.MEDIUM,
        evidence_state=EvidenceState.NOT_REQUIRED,
        metrics=(Metric("latency","ms",(Sample(10),Sample(11))),),
    )
    service.complete_run(run.run_id)
    return run.run_id


def test_http_sync_transport_does_not_follow_redirects(monkeypatch):
    observed = {}

    class RedirectResponse:
        status_code = 302
        text = "redirect"
        content = b""

    def post(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return RedirectResponse()

    monkeypatch.setattr("lib.services.sync_service.requests.post", post)
    transport = HttpSyncTransport.__new__(HttpSyncTransport)
    transport.url = "https://collector.example/ingest"
    transport.bearer_token = "test-token"
    transport.timeout_sec = 5
    envelope = SimpleNamespace(
        payload_json='{"run_id":"run-1"}',
        idempotency_key="run-1:digest",
        envelope_id="envelope-1",
        schema_version="runner-sync.v1",
    )

    with pytest.raises(SyncTransportError, match="non-retryable sync response 302"):
        transport.publish(envelope)

    assert observed["allow_redirects"] is False
    assert observed["headers"]["Authorization"] == "Bearer test-token"


def test_http_sync_transport_handles_non_object_ack_body(monkeypatch):
    class AcceptedResponse:
        status_code = 202
        text = ""
        content = b"[]"

        @staticmethod
        def json():
            return []

    monkeypatch.setattr(
        "lib.services.sync_service.requests.post",
        lambda *args, **kwargs: AcceptedResponse(),
    )
    transport = HttpSyncTransport.__new__(HttpSyncTransport)
    transport.url = "https://collector.example/ingest"
    transport.bearer_token = None
    transport.timeout_sec = 5
    envelope = SimpleNamespace(
        payload_json='{"run_id":"run-1"}',
        idempotency_key="run-1:digest",
        envelope_id="envelope-1",
        schema_version="runner-sync.v1",
    )

    ack = transport.publish(envelope)
    assert ack.accepted is True
    assert ack.remote_id is None


def test_queue_and_retry_stays_local_when_transport_is_offline(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    run_id=create_run(db)
    sync=RunnerSyncService.from_sqlite(db,runner_id="runner-1",max_attempts=2)
    item=sync.queue_run(run_id)
    transport=FakeTransport()
    first=sync.sync_pending(transport)
    assert first["failed"]==1
    assert transport.envelopes[0].run_id==run_id
    item_after=sync.queue_repository.get(item.envelope.envelope_id)
    assert item_after.state.value=="FAILED"


def test_retry_is_idempotent_after_transport_recovers(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    run_id=create_run(db)
    sync=RunnerSyncService.from_sqlite(db,runner_id="runner-1")
    sync_item=sync.queue_run(run_id)
    transport=FakeTransport()
    transport.fail=False
    result=sync.sync_pending(transport)
    assert result["delivered"]==1
    assert sync.queue_repository.get(sync_item.envelope.envelope_id).state.value=="ACKED"
    assert transport.envelopes[0].idempotency_key == sync_item.envelope.idempotency_key


def test_sync_queue_excludes_its_own_audit_events_for_stable_idempotency(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    run_id=create_run(db)
    sync=RunnerSyncService.from_sqlite(db,runner_id="runner-1")
    first=sync.queue_run(run_id)
    second=sync.queue_run(run_id)
    assert first.envelope.idempotency_key == second.envelope.idempotency_key
    assert first.envelope.envelope_id == second.envelope.envelope_id
    queued_events=[e for e in sync.event_repository.list_for_run(run_id) if e.event_type=="SYNC_QUEUED"]
    assert len(queued_events) == 1



def test_non_terminal_run_cannot_be_queued(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    service=RunService.from_sqlite(db)
    run,_=service.create_run(
        firmware_version="v1.0",lab_id="lab-1",validation_profile="Full",
        selected_tests=["wifi.latency.threshold"],
        test_definition_versions={"wifi.latency.threshold":"1.0"},
        resolved_config={},repository_commit="commit",
    )
    sync=RunnerSyncService.from_sqlite(db,runner_id="runner-1")
    with pytest.raises(ValueError,match="only terminal Runs"):
        sync.queue_run(run.run_id)


def test_corrupt_queued_payload_is_blocked_without_transport_attempt(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    run_id=create_run(db)
    sync=RunnerSyncService.from_sqlite(db,runner_id="runner-1")
    item=sync.queue_run(run_id)
    with db.transaction(immediate=True) as connection:
        connection.execute(
            "UPDATE sync_queue SET payload_json = ? WHERE envelope_id = ?",
            ('{"tampered":true}',item.envelope.envelope_id),
        )
    transport=FakeTransport(); transport.fail=False
    result=sync.sync_pending(transport)
    assert result["blocked"] == 1
    assert transport.envelopes == []
    assert sync.queue_repository.get(item.envelope.envelope_id).state.value == "BLOCKED"


def test_audit_failure_after_remote_ack_does_not_downgrade_delivery(tmp_path, monkeypatch):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    run_id=create_run(db)
    sync=RunnerSyncService.from_sqlite(db,runner_id="runner-1")
    item=sync.queue_run(run_id)
    transport=FakeTransport(); transport.fail=False

    def fail_append(_event):
        raise RuntimeError("audit store temporarily unavailable")

    monkeypatch.setattr(sync.event_repository,"append",fail_append)
    result=sync.sync_pending(transport)
    assert result["delivered"] == 1
    assert sync.queue_repository.get(item.envelope.envelope_id).state.value == "ACKED"
