from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SyncState(str, Enum):
    QUEUED = "QUEUED"
    IN_FLIGHT = "IN_FLIGHT"
    ACKED = "ACKED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SyncEnvelope:
    envelope_id: str
    runner_id: str
    run_id: str
    kind: str
    schema_version: str
    idempotency_key: str
    payload_json: str
    payload_sha256: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("envelope_id", self.envelope_id),
            ("runner_id", self.runner_id),
            ("run_id", self.run_id),
            ("kind", self.kind),
            ("schema_version", self.schema_version),
            ("idempotency_key", self.idempotency_key),
            ("payload_json", self.payload_json),
            ("payload_sha256", self.payload_sha256),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class SyncQueueItem:
    envelope: SyncEnvelope
    state: SyncState = SyncState.QUEUED
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    leased_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.attempt_count < 0:
            raise ValueError("attempt_count cannot be negative")
