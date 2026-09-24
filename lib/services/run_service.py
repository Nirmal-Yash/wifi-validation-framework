from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from lib.domain import (
    Attempt,
    BusinessOutcome,
    DomainValidationError,
    LifecycleEvent,
    Run,
    RunLifecycle,
)
from lib.repositories import (
    AttemptRepository,
    EventRepository,
    RunRepository,
    SQLiteAttemptRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
)

ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]

_ALLOWED_TRANSITIONS: dict[RunLifecycle, frozenset[RunLifecycle]] = {
    RunLifecycle.QUEUED: frozenset(
        {RunLifecycle.PREPARING, RunLifecycle.CANCELLED}
    ),
    RunLifecycle.PREPARING: frozenset(
        {
            RunLifecycle.LAB_HEALTH_CHECK,
            RunLifecycle.RUNNING,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
        }
    ),
    RunLifecycle.LAB_HEALTH_CHECK: frozenset(
        {
            RunLifecycle.RUNNING,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
        }
    ),
    RunLifecycle.RUNNING: frozenset(
        {
            RunLifecycle.COMPLETED,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
        }
    ),
    RunLifecycle.COMPLETED: frozenset(),
    RunLifecycle.FAILED: frozenset(),
    RunLifecycle.LAB_FAILED: frozenset(),
    RunLifecycle.CANCELLED: frozenset(),
    RunLifecycle.ABORTED: frozenset(),
}


def generate_ulid(now: datetime | None = None) -> str:
    """Generate a sortable 128-bit ULID without an external dependency."""
    timestamp_ms = int(
        ((now or datetime.now(timezone.utc)).astimezone(timezone.utc)).timestamp()
        * 1000
    )
    if not 0 <= timestamp_ms < (1 << 48):
        raise ValueError("ULID timestamp is outside the 48-bit range")
    value = (timestamp_ms << 80) | secrets.randbits(80)
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        chars[index] = ULID_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


def configuration_hash(configuration: Mapping[str, Any]) -> str:
    payload = json.dumps(
        configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def redact_configuration(value: Any, key: str = "") -> Any:
    """Recursively redact credential-like configuration values before persistence."""
    sensitive = (
        "password",
        "passwd",
        "secret",
        "token",
        "private_key",
        "api_key",
        "psk",
    )
    key_lower = key.lower()
    if any(token in key_lower for token in sensitive):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            str(child_key): redact_configuration(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [redact_configuration(item, key) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_configuration(item, key) for item in value)
    return value


def repository_commit(root_path: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        commit = result.stdout.strip()
        if commit:
            return commit
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


class RunService:
    """Application service owning Run/Attempt creation and lifecycle semantics."""

    def __init__(
        self,
        run_repository: RunRepository,
        attempt_repository: AttemptRepository,
        event_repository: EventRepository,
        *,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self.run_repository = run_repository
        self.attempt_repository = attempt_repository
        self.event_repository = event_repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.id_generator = id_generator or generate_ulid

    @classmethod
    def from_sqlite(
        cls, database: SQLiteDatabase, **kwargs: Any
    ) -> "RunService":
        database.initialize()
        return cls(
            SQLiteRunRepository(database),
            SQLiteAttemptRepository(database),
            SQLiteEventRepository(database),
            **kwargs,
        )

    def create_run(
        self,
        *,
        firmware_version: str,
        lab_id: str,
        validation_profile: str,
        selected_tests: list[str] | tuple[str, ...],
        test_definition_versions: Mapping[str, str],
        resolved_config: Mapping[str, Any],
        repository_commit: str,
    ) -> tuple[Run, Attempt]:
        if not selected_tests:
            raise DomainValidationError("cannot create a run with no selected tests")
        if set(selected_tests) != set(test_definition_versions):
            raise DomainValidationError(
                "every selected test must have a test definition version"
            )

        now = self.clock()
        run_id = self.id_generator()
        display_id = f"RUN-{now.astimezone(timezone.utc):%Y%m%d-%H%M%S}-{run_id[-4:]}"
        persisted_config = redact_configuration(resolved_config)
        run = Run(
            run_id=run_id,
            display_id=display_id,
            firmware_version=firmware_version,
            lab_id=lab_id,
            validation_profile=validation_profile,
            selected_tests=tuple(selected_tests),
            test_definition_versions=dict(test_definition_versions),
            resolved_config=persisted_config,
            configuration_hash=configuration_hash(persisted_config),
            repository_commit=repository_commit,
            lifecycle=RunLifecycle.QUEUED,
            created_at=now,
        )
        self.run_repository.save(run)
        self._event(run.run_id, "RUN_CREATED", now)

        attempt = Attempt(
            attempt_id=self.id_generator(),
            run_id=run.run_id,
            number=1,
        )
        self.attempt_repository.save(attempt)
        self._event(run.run_id, "ATTEMPT_CREATED", now, attempt_id=attempt.attempt_id)
        return run, attempt

    def create_attempt(self, run_id: str) -> Attempt:
        run = self._require_run(run_id)
        if run.lifecycle in _terminal_states():
            raise DomainValidationError("cannot create an attempt for a terminal run")
        number = len(self.attempt_repository.list_for_run(run_id)) + 1
        attempt = Attempt(
            attempt_id=self.id_generator(),
            run_id=run_id,
            number=number,
        )
        self.attempt_repository.save(attempt)
        self._event(run_id, "ATTEMPT_CREATED", self.clock(), attempt_id=attempt.attempt_id)
        return attempt

    def start_run(self, run_id: str) -> Run:
        run = self.transition(run_id, RunLifecycle.PREPARING)
        run = self.transition(run_id, RunLifecycle.RUNNING)
        now = self.clock()
        run.started_at = now
        self.run_repository.update(run)
        attempts = self.attempt_repository.list_for_run(run_id)
        if attempts and attempts[0].started_at is None:
            attempts[0].started_at = now
            self.attempt_repository.update(attempts[0])
        self._event(run_id, "RUN_STARTED", now, attempt_id=attempts[0].attempt_id if attempts else None)
        return run

    def complete_run(self, run_id: str, outcome: BusinessOutcome | None = None) -> Run:
        return self._finish(run_id, RunLifecycle.COMPLETED, outcome, "RUN_COMPLETED")

    def fail_run(self, run_id: str) -> Run:
        return self._finish(run_id, RunLifecycle.FAILED, None, "RUN_FAILED")

    def lab_fail_run(self, run_id: str) -> Run:
        return self._finish(run_id, RunLifecycle.LAB_FAILED, BusinessOutcome.UNVALIDATED, "RUN_LAB_FAILED")

    def cancel_run(self, run_id: str) -> Run:
        return self._finish(run_id, RunLifecycle.CANCELLED, BusinessOutcome.UNVALIDATED, "RUN_CANCELLED")

    def abort_run(self, run_id: str) -> Run:
        return self._finish(run_id, RunLifecycle.ABORTED, BusinessOutcome.UNVALIDATED, "RUN_ABORTED")

    def transition(self, run_id: str, target: RunLifecycle) -> Run:
        run = self._require_run(run_id)
        allowed = _ALLOWED_TRANSITIONS[run.lifecycle]
        if target not in allowed:
            raise DomainValidationError(
                f"invalid Run lifecycle transition: {run.lifecycle.value} -> {target.value}"
            )
        run.lifecycle = target
        self.run_repository.update(run)
        self._event(run_id, f"RUN_{target.value}", self.clock())
        return run

    def _finish(
        self,
        run_id: str,
        target: RunLifecycle,
        outcome: BusinessOutcome | None,
        event_type: str,
    ) -> Run:
        run = self._require_run(run_id)
        if target not in _ALLOWED_TRANSITIONS[run.lifecycle]:
            raise DomainValidationError(
                f"invalid Run lifecycle transition: {run.lifecycle.value} -> {target.value}"
            )
        now = self.clock()
        run.lifecycle = target
        run.outcome = outcome
        run.completed_at = now
        self.run_repository.update(run)
        attempts = self.attempt_repository.list_for_run(run_id)
        for attempt in attempts:
            if attempt.completed_at is None:
                attempt.completed_at = now
                self.attempt_repository.update(attempt)
        self._event(run_id, event_type, now, attempt_id=attempts[-1].attempt_id if attempts else None)
        return run

    def _require_run(self, run_id: str) -> Run:
        run = self.run_repository.get(run_id)
        if run is None:
            raise DomainValidationError(f"Run not found: {run_id}")
        return run

    def _event(
        self,
        run_id: str,
        event_type: str,
        occurred_at: datetime,
        *,
        attempt_id: str | None = None,
    ) -> None:
        self.event_repository.append(
            LifecycleEvent(
                event_id=self.id_generator(),
                run_id=run_id,
                event_type=event_type,
                occurred_at=occurred_at,
                attempt_id=attempt_id,
            )
        )


def _terminal_states() -> frozenset[RunLifecycle]:
    return frozenset(
        {
            RunLifecycle.COMPLETED,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
        }
    )
