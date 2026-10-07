from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import floor
from statistics import fmean, median, pstdev
from typing import Sequence

from lib.domain.models import DomainValidationError, Metric, Sample


class StatisticKind(str, Enum):
    COUNT = "count"
    MINIMUM = "min"
    MAXIMUM = "max"
    MEAN = "mean"
    MEDIAN = "median"
    P90 = "p90"
    P95 = "p95"
    STANDARD_DEVIATION = "stddev"


@dataclass(frozen=True, slots=True)
class MeasurementPolicy:
    aggregate: StatisticKind = StatisticKind.MEAN
    minimum_samples: int = 1
    allowed_statuses: tuple[str, ...] = ("VALID",)
    include_retried: bool = True

    def __post_init__(self) -> None:
        if self.minimum_samples < 1:
            raise DomainValidationError("minimum_samples must be at least 1")
        if not self.allowed_statuses:
            raise DomainValidationError("allowed_statuses must not be empty")
        if any(not status.strip() for status in self.allowed_statuses):
            raise DomainValidationError("allowed_statuses cannot contain empty values")


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    unit: str
    measurement_policy: MeasurementPolicy
    authoritative: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainValidationError("metric definition name must not be empty")
        if not self.unit.strip():
            raise DomainValidationError("metric definition unit must not be empty")


@dataclass(frozen=True, slots=True)
class StatisticSummary:
    metric_name: str
    unit: str
    aggregate: StatisticKind
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    p90: float
    p95: float
    standard_deviation: float
    decision_value: float

    def __post_init__(self) -> None:
        if self.count < 1:
            raise DomainValidationError("statistic summary requires at least one sample")


class MeasurementEvaluationError(DomainValidationError):
    """Raised when configured measurement policy cannot be evaluated."""


class InsufficientSamplesError(MeasurementEvaluationError):
    """Raised when a metric does not meet its configured sample minimum."""


class MeasurementPolicyEvaluator:
    """Apply deterministic statistical policies to preserved raw Metric samples."""

    @staticmethod
    def evaluate(metric: Metric, policy: MeasurementPolicy) -> StatisticSummary:
        candidates: list[Sample] = []
        for sample in metric.samples:
            if sample.warmup:
                continue
            if sample.status not in policy.allowed_statuses:
                continue
            if sample.retried and not policy.include_retried:
                continue
            candidates.append(sample)

        if len(candidates) < policy.minimum_samples:
            raise InsufficientSamplesError(
                f"metric '{metric.name}' has {len(candidates)} eligible samples; "
                f"{policy.minimum_samples} required"
            )

        values = [float(sample.value) for sample in candidates]
        ordered = sorted(values)
        p90 = MeasurementPolicyEvaluator._percentile(ordered, 0.90)
        p95 = MeasurementPolicyEvaluator._percentile(ordered, 0.95)
        mean = fmean(values)
        median_value = median(values)
        standard_deviation = pstdev(values)
        return StatisticSummary(
            metric_name=metric.name,
            unit=metric.unit,
            aggregate=policy.aggregate,
            count=len(values),
            minimum=min(values),
            maximum=max(values),
            mean=mean,
            median=median_value,
            p90=p90,
            p95=p95,
            standard_deviation=standard_deviation,
            decision_value=MeasurementPolicyEvaluator._decision_value(
                policy.aggregate,
                len(values),
                min(values),
                max(values),
                mean,
                median_value,
                p90,
                p95,
                standard_deviation,
            ),
        )

    @staticmethod
    def evaluate_definitions(
        metrics: Sequence[Metric],
        definitions: Sequence[MetricDefinition],
    ) -> tuple[StatisticSummary, ...]:
        metric_by_name = {metric.name: metric for metric in metrics}
        summaries: list[StatisticSummary] = []
        for definition in definitions:
            metric = metric_by_name.get(definition.name)
            if metric is None:
                raise MeasurementEvaluationError(
                    f"required metric not collected: {definition.name}"
                )
            if metric.unit != definition.unit:
                raise MeasurementEvaluationError(
                    f"metric '{definition.name}' unit mismatch: "
                    f"expected {definition.unit}, got {metric.unit}"
                )
            summaries.append(
                MeasurementPolicyEvaluator.evaluate(
                    metric,
                    definition.measurement_policy,
                )
            )
        return tuple(summaries)

    @staticmethod
    def _decision_value(
        aggregate: StatisticKind,
        count: int,
        minimum: float,
        maximum: float,
        mean: float,
        median_value: float,
        p90: float,
        p95: float,
        standard_deviation: float,
    ) -> float:
        if aggregate is StatisticKind.COUNT:
            return float(count)
        if aggregate is StatisticKind.MINIMUM:
            return minimum
        if aggregate is StatisticKind.MAXIMUM:
            return maximum
        if aggregate is StatisticKind.MEAN:
            return mean
        if aggregate is StatisticKind.MEDIAN:
            return median_value
        if aggregate is StatisticKind.P90:
            return p90
        if aggregate is StatisticKind.P95:
            return p95
        if aggregate is StatisticKind.STANDARD_DEVIATION:
            return standard_deviation
        raise MeasurementEvaluationError(
            f"unsupported aggregate statistic: {aggregate}"
        )

    @staticmethod
    def _percentile(ordered: Sequence[float], quantile: float) -> float:
        if not ordered:
            raise MeasurementEvaluationError("cannot calculate percentile of no samples")
        if len(ordered) == 1:
            return float(ordered[0])
        index = (len(ordered) - 1) * quantile
        lower = floor(index)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = index - lower
        return float(
            ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
        )
