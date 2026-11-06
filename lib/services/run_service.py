from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from lib.domain import (
    Attempt,
    Baseline,
    FailureClass,
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
    MeasurementPolicyEvaluator,
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
    SQLiteBaselineRepository,
)

ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
Clock = Callable[[], datetime]
IdGenerator = Callable[[], str]

_ALLOWED_TRANSITIONS: dict[RunLifecycle, frozenset[RunLifecycle]] = {
    RunLifecycle.QUEUED: frozenset(
        {
            RunLifecycle.PREPARING,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
            RunLifecycle.LAB_FAILED,
        }
    ),
    RunLifecycle.PREPARING: frozenset(
        {
            RunLifecycle.LAB_HEALTH_CHECK,
            RunLifecycle.RUNNING,
            RunLifecycle.FAILED,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
        }
    ),
    RunLifecycle.LAB_HEALTH_CHECK: frozenset(
        {
            RunLifecycle.RUNNING,
            RunLifecycle.LAB_FAILED,
            RunLifecycle.CANCELLED,
            RunLifecycle.ABORTED,
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
        baseline_repository=None,
        *,
        test_registry=None,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self.run_repository = run_repository
        self.attempt_repository = attempt_repository
        self.event_repository = event_repository
        self.test_result_repository = test_result_repository
        self.baseline_repository = baseline_repository
        self.test_registry = test_registry
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
            SQLiteBaselineRepository(database),
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
        source_run_id: str | None = None,
    ) -> tuple[Run, Attempt]:
        if source_run_id is not None:
            source_run = self.run_repository.get(source_run_id)
            if source_run is None:
                raise DomainValidationError(f"source Run does not exist: {source_run_id}")
            if source_run.lifecycle not in _terminal_states():
                raise DomainValidationError("only terminal Runs can be used as retry sources")
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
            source_run_id=source_run_id,
            created_at=now,
        )
        run_created_event = LifecycleEvent(
            event_id=self.id_generator(),
            run_id=run.run_id,
            event_type="RUN_CREATED",
            occurred_at=now,
            details={},
        )
        attempt = Attempt(
            attempt_id=self.id_generator(),
            run_id=run.run_id,
            number=1,
        )
        attempt_created_event = LifecycleEvent(
            event_id=self.id_generator(),
            run_id=run.run_id,
            event_type="ATTEMPT_CREATED",
            occurred_at=now,
            attempt_id=attempt.attempt_id,
            details={},
        )
        self.run_repository.save_initial_bundle(
            run, attempt, (run_created_event, attempt_created_event)
        )
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
        failure_class: FailureClass | None = None,
        failure_reason: str | None = None,
        execution_pid: int | None = None,
        provenance: str = "NATIVE",
        execution_metadata: Mapping[str, Any] | None = None,
    ) -> TestResult:
        if self.test_result_repository is None:
            raise DomainValidationError("test result repository is not configured")
        run = self._require_run(run_id)
        attempt = self.attempt_repository.get(attempt_id)
        if attempt is None or attempt.run_id != run_id:
            raise DomainValidationError(f"Attempt does not belong to Run: {attempt_id}")

        if self.test_registry is not None:
            try:
                definition = self.test_registry.get(test_id)
            except KeyError:
                definition = None
            if definition is not None and definition.decision_metric:
                declared_metric = self.test_registry.metric_definition(
                    test_id, definition.decision_metric
                )
                normalized_metrics = []
                for metric in metrics:
                    if metric.name == definition.decision_metric:
                        if metric.unit != declared_metric.unit:
                            raise DomainValidationError(
                                f"decision metric unit mismatch for {test_id}:{metric.name}: "
                                f"expected {declared_metric.unit}, got {metric.unit}"
                            )
                        metric = Metric(
                            name=metric.name,
                            unit=metric.unit,
                            samples=metric.samples,
                            authoritative=True,
                        )
                    normalized_metrics.append(metric)
                metrics = tuple(normalized_metrics)

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
            failure_class=failure_class,
            failure_reason=failure_reason,
            execution_pid=execution_pid,
            provenance=provenance,
            execution_metadata=dict(execution_metadata or {}),
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
        run = self._require_run(run_id)
        if run.lifecycle is RunLifecycle.QUEUED:
            self.transition(run_id, RunLifecycle.PREPARING)
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
        """Backward-compatible start path that preserves the full lifecycle ordering."""
        self.transition(run_id, RunLifecycle.PREPARING)
        self.transition(run_id, RunLifecycle.LAB_HEALTH_CHECK)
        return self.start_run_after_health(run_id)

    def complete_run(self, run_id: str, outcome: BusinessOutcome | None = None) -> Run:
        derived_outcome = self.derive_business_outcome(run_id)
        if outcome is not None and outcome is not derived_outcome:
            raise DomainValidationError(
                "caller-supplied Run outcome cannot override persisted test/evidence facts"
            )
        return self._finish(
            run_id, RunLifecycle.COMPLETED, derived_outcome, "RUN_COMPLETED", None
        )

    def _latest_attempt_results(self, run_id: str) -> tuple[TestResult, ...]:
        """Return results only from the most recent persisted Attempt."""
        if self.test_result_repository is None:
            return ()
        attempts = self.attempt_repository.list_for_run(run_id)
        if not attempts:
            return ()
        latest = max(attempts, key=lambda item: item.number)
        return tuple(self.test_result_repository.list_for_attempt(latest.attempt_id))

    @staticmethod
    def _selected_result_map(
        run: Run, results: tuple[TestResult, ...]
    ) -> dict[str, TestResult] | None:
        """Require a one-to-one match to each selected node or semantic test ID."""
        selected = tuple(run.selected_tests)
        if not selected or len(set(selected)) != len(selected):
            return None
        matches: dict[str, list[TestResult]] = {identifier: [] for identifier in selected}
        for result in results:
            owners = [
                identifier
                for identifier in selected
                if identifier == result.node_id or identifier == result.test_id
            ]
            if len(owners) != 1:
                return None
            matches[owners[0]].append(result)
        if any(len(items) != 1 for items in matches.values()):
            return None
        return {identifier: items[0] for identifier, items in matches.items()}

    def derive_business_outcome(self, run_id: str) -> BusinessOutcome:
        """Derive validation outcome from the latest Attempt and exact selected test set."""
        run = self._require_run(run_id)
        if run.environment_health in {
            None,
            EnvironmentHealthStatus.FAILED,
            EnvironmentHealthStatus.UNKNOWN,
        }:
            return BusinessOutcome.UNVALIDATED
        results = self._latest_attempt_results(run_id)
        selected_results = self._selected_result_map(run, results)
        if selected_results is None:
            return BusinessOutcome.UNVALIDATED

        warning = False
        for result in selected_results.values():
            if result.status is TestResultStatus.UNVALIDATED:
                return BusinessOutcome.UNVALIDATED
            if result.status in {TestResultStatus.PASS, TestResultStatus.XPASS} and result.evidence_state in {
                EvidenceState.REQUIRED,
                EvidenceState.INCOMPLETE,
                EvidenceState.INVALID,
            }:
                return BusinessOutcome.UNVALIDATED
            if result.status is TestResultStatus.ERROR:
                if result.failure_class is FailureClass.PRODUCT_FAILED:
                    return BusinessOutcome.REJECTED
                return BusinessOutcome.UNVALIDATED
            if result.criticality is Criticality.BLOCKING:
                if result.status in {
                    TestResultStatus.FAIL,
                    TestResultStatus.KNOWN_FAILURE,
                }:
                    return BusinessOutcome.REJECTED
                if result.status is TestResultStatus.BLOCKED:
                    return BusinessOutcome.REJECTED
                if result.status in {TestResultStatus.SKIPPED, TestResultStatus.XPASS}:
                    return BusinessOutcome.UNVALIDATED
                if result.status is not TestResultStatus.PASS:
                    return BusinessOutcome.UNVALIDATED
            elif result.status is not TestResultStatus.PASS:
                warning = True

        return (
            BusinessOutcome.VALIDATED_WITH_WARNINGS
            if warning
            else BusinessOutcome.VALIDATED
        )

    def fail_run(
        self,
        run_id: str,
        reason: str | None = None,
        failure_class: FailureClass | None = FailureClass.PRODUCT_FAILED,
    ) -> Run:
        if failure_class is FailureClass.PRODUCT_FAILED:
            outcome = BusinessOutcome.REJECTED
        elif failure_class is None:
            outcome = self.derive_business_outcome(run_id)
            if outcome in {
                BusinessOutcome.VALIDATED,
                BusinessOutcome.VALIDATED_WITH_WARNINGS,
            }:
                outcome = BusinessOutcome.UNVALIDATED
        else:
            outcome = BusinessOutcome.UNVALIDATED
        return self._finish(
            run_id, RunLifecycle.FAILED, outcome, "RUN_FAILED", failure_class, reason
        )

    def lab_fail_run(self, run_id: str, reason: str | None = None) -> Run:
        return self._finish(run_id, RunLifecycle.LAB_FAILED, BusinessOutcome.UNVALIDATED, "RUN_LAB_FAILED", FailureClass.LAB_FAILED, reason)

    def request_cancel(
        self,
        run_id: str,
        *,
        actor: str = "operator",
        reason: str = "Run cancellation requested",
    ) -> Run:
        """Persist cancellation intent before the worker receives a signal."""
        run = self._require_run(run_id)
        if run.lifecycle in _terminal_states():
            raise DomainValidationError("cannot request cancellation for a terminal Run")
        if not self.cancellation_requested(run_id):
            self._event(
                run_id,
                "RUN_CANCEL_REQUESTED",
                self.clock(),
                details={"actor": actor, "reason": reason},
            )
        return run

    def cancellation_requested(self, run_id: str) -> bool:
        return any(
            event.event_type == "RUN_CANCEL_REQUESTED"
            for event in self.event_repository.list_for_run(run_id)
        )

    def cancel_run(self, run_id: str, actor: str = "operator", reason: str = "Run cancelled by operator") -> Run:
        return self._finish(run_id, RunLifecycle.CANCELLED, BusinessOutcome.UNVALIDATED, "RUN_CANCELLED", FailureClass.CANCELLED, f"{actor}: {reason}")

    def timeout_run(self, run_id: str, reason: str = "Run execution timeout") -> Run:
        return self._finish(run_id, RunLifecycle.ABORTED, BusinessOutcome.UNVALIDATED, "RUN_TIMED_OUT", FailureClass.TIMED_OUT, reason)

    def runner_disconnected(self, run_id: str, reason: str = "Runner connection lost") -> Run:
        return self._finish(run_id, RunLifecycle.ABORTED, BusinessOutcome.UNVALIDATED, "RUN_RUNNER_DISCONNECTED", FailureClass.RUNNER_DISCONNECTED, reason)

    def worker_crashed(self, run_id: str, reason: str = "Worker process terminated unexpectedly") -> Run:
        return self._finish(run_id, RunLifecycle.ABORTED, BusinessOutcome.UNVALIDATED, "RUN_WORKER_CRASHED", FailureClass.WORKER_CRASHED, reason)

    def abort_run(self, run_id: str, reason: str | None = None) -> Run:
        return self._finish(run_id, RunLifecycle.ABORTED, BusinessOutcome.UNVALIDATED, "RUN_ABORTED", FailureClass.ABORTED, reason)

    def promote_baseline(self, run_id: str, *, name: str, promoted_by: str, device_scope: str = "", firmware_major_scope: str = "", test_suite_version: str = "", lab_class: str = "") -> Baseline:
        if self.baseline_repository is None:
            raise DomainValidationError("baseline repository is not configured")
        run = self._require_run(run_id)
        if run.lifecycle is not RunLifecycle.COMPLETED or run.environment_health is not EnvironmentHealthStatus.HEALTHY:
            raise DomainValidationError("only completed Runs with healthy lab state can become baselines")
        derived_outcome = self.derive_business_outcome(run_id)
        if (
            run.outcome is not derived_outcome
            or derived_outcome not in {
                BusinessOutcome.VALIDATED,
                BusinessOutcome.VALIDATED_WITH_WARNINGS,
            }
        ):
            raise DomainValidationError(
                "Run outcome does not match currently persisted TestResult/evidence facts"
            )
        if not name.strip() or not promoted_by.strip():
            raise DomainValidationError("baseline name and promoter are required")

        results = self._latest_attempt_results(run_id)
        selected_results = self._selected_result_map(run, results)
        if selected_results is None:
            raise DomainValidationError(
                "baseline requires exactly one TestResult for every selected test in the latest Attempt"
            )

        from lib.services.test_registry import TestRegistry
        registry = self.test_registry or TestRegistry.default()
        for result in selected_results.values():
            if result.status is TestResultStatus.UNVALIDATED:
                raise DomainValidationError(f"unvalidated TestResult cannot be promoted: {result.test_id}")
            if result.status is TestResultStatus.XPASS:
                raise DomainValidationError(f"unexpected pytest pass requires review before baseline promotion: {result.test_id}")
            if result.evidence_state in {
                EvidenceState.INCOMPLETE, EvidenceState.INVALID, EvidenceState.REQUIRED
            }:
                raise DomainValidationError(f"TestResult evidence is not complete: {result.test_id}")
            if result.criticality is Criticality.BLOCKING and result.status is not TestResultStatus.PASS:
                raise DomainValidationError(f"blocking test is not PASS: {result.test_id}")

            try:
                test_definition = registry.get(result.test_id)
            except KeyError as exc:
                if any(metric.authoritative for metric in result.metrics):
                    raise DomainValidationError(
                        f"authoritative metric definition missing for {result.test_id}"
                    ) from exc
                continue

            metrics_by_name = {metric.name: metric for metric in result.metrics}
            if test_definition.decision_metric:
                decision_metric = metrics_by_name.get(test_definition.decision_metric)
                if decision_metric is None:
                    raise DomainValidationError(
                        f"required authoritative decision metric missing: {result.test_id}:{test_definition.decision_metric}"
                    )
                if not decision_metric.authoritative:
                    raise DomainValidationError(
                        f"decision metric is not marked authoritative: {result.test_id}:{test_definition.decision_metric}"
                    )
                try:
                    definition = registry.metric_definition(result.test_id, test_definition.decision_metric)
                    if definition.unit != decision_metric.unit:
                        raise DomainValidationError(
                            f"authoritative metric unit mismatch: {result.test_id}:{decision_metric.name}"
                        )
                    MeasurementPolicyEvaluator.evaluate(
                        decision_metric, definition.measurement_policy
                    )
                except Exception as exc:
                    raise DomainValidationError(
                        f"authoritative measurement policy not satisfied for {result.test_id}:{decision_metric.name}: {exc}"
                    ) from exc

            for metric in result.metrics:
                if not metric.authoritative or metric.name == test_definition.decision_metric:
                    continue
                try:
                    definition = registry.metric_definition(result.test_id, metric.name)
                    if not definition.authoritative:
                        raise DomainValidationError(
                            f"metric is not declared authoritative: {result.test_id}:{metric.name}"
                        )
                    if definition.unit != metric.unit:
                        raise DomainValidationError(
                            f"authoritative metric unit mismatch: {result.test_id}:{metric.name}"
                        )
                    MeasurementPolicyEvaluator.evaluate(metric, definition.measurement_policy)
                except Exception as exc:
                    raise DomainValidationError(
                        f"authoritative measurement policy not satisfied for {result.test_id}:{metric.name}: {exc}"
                    ) from exc

        now = self.clock()
        baseline = Baseline(
            baseline_id=self.id_generator(),
            name=name.strip(),
            baseline_run_id=run_id,
            status="ACTIVE",
            promoted_by=promoted_by.strip(),
            promoted_at=now,
            device_scope=device_scope or str(run.resolved_config.get("device_id", "")),
            firmware_major_scope=firmware_major_scope or run.firmware_version.split(".")[0],
            test_suite_version=test_suite_version or configuration_hash(run.test_definition_versions),
            lab_class=lab_class or run.lab_id,
        )
        save_replacing_active = getattr(self.baseline_repository, "save_replacing_active", None)
        if save_replacing_active is None:
            raise DomainValidationError("baseline repository does not support atomic replacement")
        save_replacing_active(baseline)
        self._event(run_id, "BASELINE_PROMOTED", now, details={"baseline_id": baseline.baseline_id, "name": baseline.name, "promoted_by": baseline.promoted_by})
        return baseline

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
        failure_class: FailureClass | None,
        failure_reason: str | None = None,
    ) -> Run:
        run = self._require_run(run_id)
        if target not in _ALLOWED_TRANSITIONS[run.lifecycle]:
            raise DomainValidationError(
                f"invalid Run lifecycle transition: {run.lifecycle.value} -> {target.value}"
            )
        now = self.clock()
        run.lifecycle = target
        run.outcome = outcome
        run.failure_class = failure_class
        run.failure_reason = failure_reason
        run.completed_at = now
        self.run_repository.update(run)
        attempts = self.attempt_repository.list_for_run(run_id)
        for attempt in attempts:
            if attempt.completed_at is None:
                attempt.completed_at = now
                self.attempt_repository.update(attempt)
        self._event(run_id, event_type, now, attempt_id=attempts[-1].attempt_id if attempts else None, details={"failure_class": failure_class.value if failure_class else None, "failure_reason": failure_reason} if failure_class or failure_reason else {})
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
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.event_repository.append(
            LifecycleEvent(
                event_id=self.id_generator(),
                run_id=run_id,
                event_type=event_type,
                occurred_at=occurred_at,
                attempt_id=attempt_id,
                details=dict(details or {}),
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
