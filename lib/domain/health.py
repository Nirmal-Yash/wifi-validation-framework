from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class EnvironmentHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class HealthObservationStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class HealthObservation:
    component: str
    status: HealthObservationStatus
    duration_ms: int
    summary: str
    observed_at: datetime
    details: Mapping[str, Any] = field(default_factory=dict)
    required: bool = True
    tool_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.component.strip():
            raise ValueError("component must not be empty")
        if not self.summary.strip():
            raise ValueError("summary must not be empty")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")


@dataclass(frozen=True, slots=True)
class LabHealthSnapshot:
    snapshot_id: str
    run_id: str
    phase: str
    overall_status: EnvironmentHealthStatus
    observations: tuple[HealthObservation, ...]
    started_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("snapshot_id", self.snapshot_id),
            ("run_id", self.run_id),
            ("phase", self.phase),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")

    @property
    def unhealthy(self) -> bool:
        return self.overall_status in {
            EnvironmentHealthStatus.DEGRADED,
            EnvironmentHealthStatus.FAILED,
            EnvironmentHealthStatus.UNKNOWN,
        }
