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
    Criticality,
    EnvironmentHealthStatus,
    EvidenceState,
    LifecycleEvent,
    Metric,
    Run,
    RunLifecycle,
    Severity,
    TestResult,
    TestResultStatus,
)
from lib.repositories import (
    AttemptRepository,
    EventRepository,
    RunRepository,
    TestResultRepository,
    SQLiteAttemptRepository,
    SQLiteDatabase,
    SQLiteEventRepository,
    SQLiteRunRepository,
    SQLiteTestResultRepository,
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
        test_result_repository: TestResultRepository | None = None,
        *,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self.run_repository = run_repository
        self.attempt_repository = attempt_repository
        self.event_repository = event_repository
        self.test_result_repository = test_result_repository
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
            SQLiteTestResultRepository(database),
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

    def record_test_result(
        self,
        *,
        run_id: str,
        attempt_id: str,
        test_id: str,
        node_id: str,
        status: TestResultStatus,
        metrics: tuple[Metric, ...] = (),
        test_version: str | None = None,
        error_reason: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        criticality: Criticality = Criticality.INFORMATIONAL,
        severity: Severity = Severity.LOW,
        evidence_state: EvidenceState = EvidenceState.NOT_REQUIRED,
    ) -> TestResult:
        if self.test_result_repository is None:
            raise DomainValidationError("test result repository is not configured")
        run = self._require_run(run_id)
        attempt = self.attempt_repository.get(attempt_id)
        if attempt is None or attempt.run_id != run_id:
            raise DomainValidationError(f"Attempt does not belong to Run: {attempt_id}")
        result = TestResult(
            test_result_id=self.id_generator(),
            run_id=run_id,
            attempt_id=attempt_id,
            test_id=test_id,
            node_id=node_id,
            test_version=test_version or run.test_definition_versions.get(test_id, "1.0"),
            status=status,
            criticality=criticality,
            severity=severity,
            evidence_state=evidence_state,
            metrics=metrics,
            error_reason=error_reason,
            started_at=started_at,
            completed_at=completed_at,
        )
        self.test_result_repository.save(result)
        self._event(run_id, "TEST_COMPLETED", completed_at or self.clock(), attempt_id=attempt_id)
        return result
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

    def begin_lab_health_check(self, run_id: str) -> Run:
        return self.transition(run_id, RunLifecycle.LAB_HEALTH_CHECK)

    def record_environment_health(
        self,
        run_id: str,
        status: EnvironmentHealthStatus,
    ) -> Run:
        run = self._require_run(run_id)
        if run.lifecycle not in {
            RunLifecycle.LAB_HEALTH_CHECK,
            RunLifecycle.RUNNING,
            RunLifecycle.COMPLETED,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
        }:
            raise DomainValidationError(
                f"cannot record environment health while Run is {run.lifecycle.value}"
            )
        severity = {
            EnvironmentHealthStatus.HEALTHY: 0,
            EnvironmentHealthStatus.DEGRADED: 1,
            EnvironmentHealthStatus.UNKNOWN: 1,
            EnvironmentHealthStatus.FAILED: 2,
        }
        current = run.environment_health
        if current is None or severity[status] > severity[current]:
            run.environment_health = status
            self.run_repository.update(run)
        return run

    def start_run_after_health(self, run_id: str) -> Run:
        run = self._require_run(run_id)
        if run.lifecycle != RunLifecycle.LAB_HEALTH_CHECK:
            raise DomainValidationError(
                f"Run must be in LAB_HEALTH_CHECK before execution: {run.lifecycle.value}"
            )
        run = self.transition(run_id, RunLifecycle.RUNNING)
        now = self.clock()
        run.started_at = now
        self.run_repository.update(run)
        attempts = self.attempt_repository.list_for_run(run_id)
        if attempts and attempts[0].started_at is None:
            attempts[0].started_at = now
            self.attempt_repository.update(attempts[0])
        self._event(
            run_id,
            "RUN_STARTED",
            now,
            attempt_id=attempts[0].attempt_id if attempts else None,
        )
        return run

    def start_run(self, run_id: str) -> Run:
        """Backward-compatible start path for callers that have no health phase yet."""
        run = self.transition(run_id, RunLifecycle.PREPARING)
        return self.start_run_after_health(run_id)

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
