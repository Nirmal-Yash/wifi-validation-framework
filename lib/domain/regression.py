from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

from .models import RegressionClass


class ComparabilityStatus(str, Enum):
    COMPARABLE = "COMPARABLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class RegressionDimension(str, Enum):
    FUNCTIONAL = "FUNCTIONAL"
    PERFORMANCE = "PERFORMANCE"
    CONFIGURATION = "CONFIGURATION"
    PROTOCOL = "PROTOCOL"
    AVAILABILITY = "AVAILABILITY"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True, slots=True)
class FlakyTestHistory:
    test_id: str
    observations: Tuple[str, ...]
    pass_count: int
    fail_count: int
    transition_count: int
    flagged: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RegressionMetricComparison:
    metric_name: str
    unit: str
    baseline_value: float | None
    current_value: float | None
    delta_pct: float | None
    threshold_pct: float | None
    classification: RegressionClass
    dimension: RegressionDimension
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RegressionAssessment:
    test_id: str
    node_id: str
    baseline_run_id: str
    current_run_id: str
    baseline_status: str
    current_status: str
    classification: RegressionClass
    dimensions: Tuple[RegressionDimension, ...] = ()
    metric_comparisons: Tuple[RegressionMetricComparison, ...] = ()
    flaky_history: FlakyTestHistory | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RunRegressionReport:
    baseline_run_id: str
    current_run_id: str
    comparability: ComparabilityStatus
    reason: str
    assessments: Tuple[RegressionAssessment, ...] = field(default_factory=tuple)

    @property
    def no_baseline(self) -> bool:
        return self.comparability is not ComparabilityStatus.COMPARABLE

    @property
    def unvalidated(self) -> bool:
        return any(
            item.classification is RegressionClass.UNVALIDATED
            for item in self.assessments
        )
