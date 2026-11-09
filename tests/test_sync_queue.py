from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import pytest

from lib.domain import Run, SyncEnvelope, SyncState
from lib.repositories import SQLiteDatabase, SQLiteRunRepository, SQLiteSyncQueueRepository
from lib.repositories.interfaces import RepositoryConflictError


def create_run(db, run_id="run-1"):
    SQLiteRunRepository(db).save(
        Run(
            run_id=run_id,
            display_id=run_id.upper(),
            firmware_version="v1.0",
            lab_id="lab-1",
            validation_profile="Full",
            selected_tests=("t",),
            test_definition_versions={"t": "1.0"},
            resolved_config={},
            configuration_hash="c" * 64,
            repository_commit="commit",
        )
    )

def envelope(run_id="run-1", payload='{"run_id":"run-1"}'):
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return SyncEnvelope(
        envelope_id=hashlib.sha256((run_id + digest).encode()).hexdigest()[:32],
        runner_id="runner-1",
        run_id=run_id,
        kind="RUN_SNAPSHOT",
        schema_version="runner-sync.v1",
        idempotency_key=f"{run_id}:{digest}",
        payload_json=payload,
        payload_sha256=digest,
        created_at=datetime.now(timezone.utc),
    )


def test_queue_is_idempotent(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    create_run(db)
    repo=SQLiteSyncQueueRepository(db)
    first=repo.enqueue(envelope())
    second=repo.enqueue(envelope())
    assert first.envelope.envelope_id == second.envelope.envelope_id
    assert first.state is SyncState.QUEUED


def test_claim_ack_persists_across_repository_instances(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    create_run(db)
    repo=SQLiteSyncQueueRepository(db)
    item=repo.enqueue(envelope())
    now=datetime.now(timezone.utc)
    claimed=repo.claim(item.envelope.envelope_id,now,now)
    assert claimed is not None and claimed.state is SyncState.IN_FLIGHT
    repo2=SQLiteSyncQueueRepository(db)
    repo2.ack(item.envelope.envelope_id,now)
    assert repo2.get(item.envelope.envelope_id).state is SyncState.ACKED


def test_expired_lease_becomes_retryable(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    create_run(db)
    repo=SQLiteSyncQueueRepository(db)
    item=repo.enqueue(envelope())
    now=datetime.now(timezone.utc)
    repo.claim(item.envelope.envelope_id,now,now-timedelta(seconds=1))
    assert repo.recover_expired(now) == 1
    assert repo.list_ready(datetime.now(timezone.utc))


def test_failure_can_become_blocked(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    create_run(db)
    repo=SQLiteSyncQueueRepository(db)
    item=repo.enqueue(envelope())
    now=datetime.now(timezone.utc)
    repo.claim(item.envelope.envelope_id,now,now)
    repo.fail(item.envelope.envelope_id,next_attempt_at=now,error="offline",updated_at=now,blocked=True)
    assert repo.get(item.envelope.envelope_id).state is SyncState.BLOCKED



def test_enqueue_rejects_idempotency_key_reuse_with_different_payload(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    create_run(db)
    repo=SQLiteSyncQueueRepository(db)
    original=envelope()
    repo.enqueue(original)
    payload='{"run_id":"different"}'
    conflicting=replace(
        original,
        payload_json=payload,
        payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
    )
    with pytest.raises(RepositoryConflictError):
        repo.enqueue(conflicting)


def test_expired_lease_consumes_retry_budget_and_blocks_at_limit(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    create_run(db)
    repo=SQLiteSyncQueueRepository(db)
    item=repo.enqueue(envelope())
    now=datetime.now(timezone.utc)
    claimed=repo.claim(item.envelope.envelope_id,now,now+timedelta(seconds=1))
    assert claimed is not None
    recovered=repo.recover_expired(now+timedelta(seconds=2),max_attempts=1)
    assert recovered == 1
    final=repo.get(item.envelope.envelope_id)
    assert final.state is SyncState.BLOCKED
    assert final.attempt_count == 1
    assert final.next_attempt_at is None


def test_ack_requires_current_lease_when_lease_token_is_supplied(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    create_run(db)
    repo=SQLiteSyncQueueRepository(db)
    item=repo.enqueue(envelope())
    now=datetime.now(timezone.utc)
    claimed=repo.claim(item.envelope.envelope_id,now,now+timedelta(seconds=30))
    assert claimed is not None
    with pytest.raises(RepositoryConflictError):
        repo.ack(
            item.envelope.envelope_id,now,
            expected_lease=claimed.leased_at+timedelta(seconds=1),
        )
    assert repo.get(item.envelope.envelope_id).state is SyncState.IN_FLIGHT
    repo.ack(item.envelope.envelope_id,now,expected_lease=claimed.leased_at)
    assert repo.get(item.envelope.envelope_id).state is SyncState.ACKED
