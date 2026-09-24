from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from lib.domain import SyncEnvelope, SyncState
from lib.repositories import SQLiteDatabase, SQLiteSyncQueueRepository


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
    repo=SQLiteSyncQueueRepository(db)
    first=repo.enqueue(envelope())
    second=repo.enqueue(envelope())
    assert first.envelope.envelope_id == second.envelope.envelope_id
    assert first.state is SyncState.QUEUED


def test_claim_ack_persists_across_repository_instances(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
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
    repo=SQLiteSyncQueueRepository(db)
    item=repo.enqueue(envelope())
    old=datetime(2020,1,1,tzinfo=timezone.utc)
    repo.claim(item.envelope.envelope_id,old,old)
    assert repo.recover_expired(datetime.now(timezone.utc)) == 1
    assert repo.list_ready(datetime.now(timezone.utc))


def test_failure_can_become_blocked(tmp_path):
    db=SQLiteDatabase(tmp_path/"sync.db"); db.initialize()
    repo=SQLiteSyncQueueRepository(db)
    item=repo.enqueue(envelope())
    now=datetime.now(timezone.utc)
    repo.claim(item.envelope.envelope_id,now,now)
    repo.fail(item.envelope.envelope_id,next_attempt_at=now,error="offline",updated_at=now,blocked=True)
    assert repo.get(item.envelope.envelope_id).state is SyncState.BLOCKED
