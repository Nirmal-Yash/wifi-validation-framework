from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class DomainValidationError(ValueError):
    """Raised when a domain entity violates a business invariant."""


from .health import EnvironmentHealthStatus


class RunLifecycle(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    LAB_HEALTH_CHECK = "LAB_HEALTH_CHECK"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    LAB_FAILED = "LAB_FAILED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class BusinessOutcome(str, Enum):
    VALIDATED = "VALIDATED"
    VALIDATED_WITH_WARNINGS = "VALIDATED_WITH_WARNINGS"
    REJECTED = "REJECTED"
    UNVALIDATED = "UNVALIDATED"


class TestResultStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    KNOWN_FAILURE = "KNOWN_FAILURE"
    XPASS = "XPASS"
    UNVALIDATED = "UNVALIDATED"


class Criticality(str, Enum):
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"
    INFORMATIONAL = "INFORMATIONAL"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceState(str, Enum):
    REQUIRED = "REQUIRED"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"
    NOT_REQUIRED = "NOT_REQUIRED"


class ArtifactType(str, Enum):
    PCAP = "PCAP"
    PYTEST_REPORT = "PYTEST_REPORT"
    DIFF_REPORT = "DIFF_REPORT"
    SETUP_LOG = "SETUP_LOG"
    AUDIT_LOG = "AUDIT_LOG"
    COMMAND_OUTPUT = "COMMAND_OUTPUT"
    CONFIG_SNAPSHOT = "CONFIG_SNAPSHOT"
    LAB_HEALTH_SNAPSHOT = "LAB_HEALTH_SNAPSHOT"
    ENV_FINGERPRINT = "ENV_FINGERPRINT"
    DIAGNOSTIC_BUNDLE = "DIAGNOSTIC_BUNDLE"
    FIRMWARE_REFERENCE = "FIRMWARE_REFERENCE"
    OTHER = "OTHER"


class RegressionClass(str, Enum):
    REGRESSION = "REGRESSION"
    SOFT_REGRESSION = "SOFT_REGRESSION"
    FIXED = "FIXED"
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    NEW_FAILURE = "NEW_FAILURE"
    NEW_PASS = "NEW_PASS"
    NO_BASELINE = "NO_BASELINE"
    UNVALIDATED = "UNVALIDATED"


@dataclass(frozen=True, slots=True)
class Sample:
    value: float
    status: str = "VALID"
    warmup: bool = False
    retried: bool = False
    captured_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.value, (int, float)):
            raise DomainValidationError("sample value must be numeric")
        if not self.status.strip():
            raise DomainValidationError("sample status must not be empty")


@dataclass(frozen=True, slots=True)
class Metric:
    name: str
    unit: str
    samples: tuple[Sample, ...] = ()
    authoritative: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainValidationError("metric name must not be empty")
        if not self.unit.strip():
            raise DomainValidationError("metric unit must not be empty")
        if self.authoritative and not self.samples:
            raise DomainValidationError(
                "authoritative metric requires at least one sample"
            )


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    run_id: str
    artifact_type: ArtifactType
    path: str
    sha256: str
    size_bytes: int
    evidence_state: EvidenceState = EvidenceState.COMPLETE
    test_result_id: str | None = None
    display_name: str = ""
    created_at: datetime | None = None
    sensitivity_class: str = "INTERNAL"
    retain_until: datetime | None = None
    soft_deleted_at: datetime | None = None
    provenance: str = "NATIVE"

    def __post_init__(self) -> None:
        for name, value in (
            ("artifact_id", self.artifact_id),
            ("run_id", self.run_id),
            ("path", self.path),
            ("sensitivity_class", self.sensitivity_class),
        ):
            _require_text(name, value)
        if len(self.sha256) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in self.sha256
        ):
            raise DomainValidationError(
                "artifact sha256 must be a 64-character hexadecimal digest"
            )
        if self.size_bytes < 0:
            raise DomainValidationError("artifact size cannot be negative")
        if not self.display_name.strip():
            object.__setattr__(
                self, "display_name", self.path.rsplit("/", 1)[-1]
            )
        if not self.provenance.strip():
            raise DomainValidationError("artifact provenance must not be empty")


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    snapshot_id: str
    host_os: str
    kernel: str
    python_version: str
    repository_commit: str
    configuration_hash: str
    tools: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("snapshot_id", self.snapshot_id),
            ("host_os", self.host_os),
            ("kernel", self.kernel),
            ("python_version", self.python_version),
            ("repository_commit", self.repository_commit),
            ("configuration_hash", self.configuration_hash),
        ):
            _require_text(name, value)


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    snapshot_id: str
    resolved_config: Mapping[str, Any]
    configuration_hash: str

    def __post_init__(self) -> None:
        _require_text("snapshot_id", self.snapshot_id)
        _require_text("configuration_hash", self.configuration_hash)


@dataclass(frozen=True, slots=True)
class TestResult:
    test_result_id: str
    run_id: str
    attempt_id: str
    test_id: str
    node_id: str
    test_version: str
    status: TestResultStatus
    criticality: Criticality
    severity: Severity
    evidence_state: EvidenceState
    metrics: tuple[Metric, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    error_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    provenance: str = "NATIVE"

    def __post_init__(self) -> None:
        for name, value in (
            ("test_result_id", self.test_result_id),
            ("run_id", self.run_id),
            ("attempt_id", self.attempt_id),
            ("test_id", self.test_id),
            ("node_id", self.node_id),
            ("test_version", self.test_version),
            ("provenance", self.provenance),
        ):
            _require_text(name, value)
        if self.status in {TestResultStatus.PASS, TestResultStatus.XPASS} and self.provenance != "LEGACY_IMPORTED" and (
            self.evidence_state in {EvidenceState.INCOMPLETE, EvidenceState.INVALID}
        ):
            raise DomainValidationError(
                "a PASS result cannot have incomplete or invalid required evidence"
            )
        if (
            self.status == TestResultStatus.UNVALIDATED
            and self.evidence_state == EvidenceState.COMPLETE
        ):
            raise DomainValidationError(
                "UNVALIDATED result must explain an evidence/environment problem"
            )


@dataclass(slots=True)
class Attempt:
    attempt_id: str
    run_id: str
    number: int
    results: list[TestResult] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("attempt_id", self.attempt_id)
        _require_text("run_id", self.run_id)
        if self.number < 1:
            raise DomainValidationError("attempt number must start at 1")

    def add_result(self, result: TestResult) -> None:
        if result.run_id != self.run_id or result.attempt_id != self.attempt_id:
            raise DomainValidationError("test result does not belong to this attempt")
        if any(item.test_result_id == result.test_result_id for item in self.results):
            raise DomainValidationError("duplicate test result id in attempt")
        self.results.append(result)


@dataclass(slots=True)
class Run:
    run_id: str
    display_id: str
    firmware_version: str
    lab_id: str
    validation_profile: str
    selected_tests: tuple[str, ...]
    test_definition_versions: Mapping[str, str]
    resolved_config: Mapping[str, Any]
    configuration_hash: str
    repository_commit: str
    lifecycle: RunLifecycle = RunLifecycle.QUEUED
    outcome: BusinessOutcome | None = None
    environment_health: EnvironmentHealthStatus | None = None
    attempts: list[Attempt] = field(default_factory=list)
    environment: EnvironmentSnapshot | None = None
    config_snapshot: ConfigSnapshot | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    provenance: str = "NATIVE"

    def __post_init__(self) -> None:
        for name, value in (
            ("run_id", self.run_id),
            ("display_id", self.display_id),
            ("firmware_version", self.firmware_version),
            ("lab_id", self.lab_id),
            ("validation_profile", self.validation_profile),
            ("configuration_hash", self.configuration_hash),
            ("repository_commit", self.repository_commit),
            ("provenance", self.provenance),
        ):
            _require_text(name, value)
        if not self.selected_tests:
            raise DomainValidationError("run must contain at least one selected test")
        if set(self.selected_tests) != set(self.test_definition_versions):
            raise DomainValidationError(
                "every selected test must have a test definition version"
            )

    def add_attempt(self, attempt: Attempt) -> None:
        if attempt.run_id != self.run_id:
            raise DomainValidationError("attempt does not belong to this run")
        expected_number = len(self.attempts) + 1
        if attempt.number != expected_number:
            raise DomainValidationError(f"attempt number must be {expected_number}")
        self.attempts.append(attempt)


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event_id: str
    run_id: str
    event_type: str
    occurred_at: datetime
    attempt_id: str | None = None
    test_result_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("event_id", self.event_id),
            ("run_id", self.run_id),
            ("event_type", self.event_type),
        ):
            _require_text(name, value)


@dataclass(frozen=True, slots=True)
class Baseline:
    baseline_id: str
    name: str
    baseline_run_id: str
    status: str
    promoted_by: str
    promoted_at: datetime
    device_scope: str = ""
    firmware_major_scope: str = ""
    test_suite_version: str = ""
    lab_class: str = ""
    superseded_by: str | None = None
    provenance: str = "NATIVE"

    def __post_init__(self) -> None:
        for name, value in (
            ("baseline_id", self.baseline_id),
            ("name", self.name),
            ("baseline_run_id", self.baseline_run_id),
            ("status", self.status),
            ("promoted_by", self.promoted_by),
            ("provenance", self.provenance),
        ):
            _require_text(name, value)


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{name} must not be empty")
