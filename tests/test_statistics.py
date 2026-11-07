from math import isclose

import pytest

from lib.domain import Metric, MetricDefinition, Sample, StatisticKind
from lib.domain import MeasurementPolicy
from lib.services import InsufficientSamplesError, MeasurementPolicyEvaluator
from lib.services.test_registry import TestRegistry


def metric(*values: float) -> Metric:
    return Metric(
        name="latency",
        unit="ms",
        samples=tuple(Sample(value=value) for value in values),
    )


def test_evaluator_computes_initial_statistics_and_uses_p95():
    result = MeasurementPolicyEvaluator.evaluate(
        metric(1, 2, 3, 4, 5),
        MeasurementPolicy(aggregate=StatisticKind.P95),
    )

    assert result.count == 5
    assert result.minimum == 1
    assert result.maximum == 5
    assert result.mean == 3
    assert result.median == 3
    assert isclose(result.p90, 4.6)
    assert isclose(result.p95, 4.8)
    assert isclose(result.standard_deviation, 2 ** 0.5)
    assert result.decision_value == result.p95


def test_warmup_and_invalid_status_are_excluded_from_aggregate():
    metric_value = Metric(
        name="latency",
        unit="ms",
        samples=(
            Sample(value=100, warmup=True),
            Sample(value=10, status="VALID"),
            Sample(value=20, status="FAILED"),
        ),
    )

    result = MeasurementPolicyEvaluator.evaluate(
        metric_value,
        MeasurementPolicy(aggregate=StatisticKind.MEAN),
    )

    assert result.count == 1
    assert result.mean == 10


def test_retried_sample_counts_as_one_measurement_not_retry_multiplicity():
    metric_value = Metric(
        name="throughput",
        unit="Mbps",
        samples=(
            Sample(value=100, retried=True),
            Sample(value=120),
        ),
    )

    result = MeasurementPolicyEvaluator.evaluate(
        metric_value,
        MeasurementPolicy(aggregate=StatisticKind.MEAN),
    )

    assert result.count == 2
    assert result.mean == 110


def test_minimum_samples_is_enforced():
    with pytest.raises(InsufficientSamplesError):
        MeasurementPolicyEvaluator.evaluate(
            metric(10, 20),
            MeasurementPolicy(minimum_samples=3),
        )


def test_definition_evaluation_checks_name_and_unit():
    definition = MetricDefinition(
        name="latency",
        unit="ms",
        measurement_policy=MeasurementPolicy(aggregate=StatisticKind.P95),
        authoritative=True,
    )
    summaries = MeasurementPolicyEvaluator.evaluate_definitions(
        (metric(10, 20, 30),),
        (definition,),
    )

    assert len(summaries) == 1
    assert summaries[0].aggregate is StatisticKind.P95
    assert summaries[0].decision_value == summaries[0].p95



def test_retried_samples_can_be_excluded_without_mutating_raw_history():
    metric_value = Metric(
        name="latency", unit="ms",
        samples=(Sample(value=100, retried=True), Sample(value=10), Sample(value=20)),
    )
    original_samples = metric_value.samples
    result = MeasurementPolicyEvaluator.evaluate(
        metric_value,
        MeasurementPolicy(aggregate=StatisticKind.MEAN, minimum_samples=2, include_retried=False),
    )
    assert result.count == 2
    assert result.mean == 15
    assert metric_value.samples is original_samples
    assert tuple(sample.value for sample in metric_value.samples) == (100, 10, 20)


def test_policy_rejects_boolean_sample_minimum():
    from lib.domain.models import DomainValidationError
    with pytest.raises(DomainValidationError, match="positive integer"):
        MeasurementPolicy(minimum_samples=True)


def test_definition_evaluation_rejects_duplicate_metric_names():
    from lib.services import MeasurementEvaluationError
    duplicate = metric(1, 2)
    definition = MetricDefinition(
        name="latency", unit="ms", measurement_policy=MeasurementPolicy(),
    )
    with pytest.raises(MeasurementEvaluationError, match="duplicate collected metric"):
        MeasurementPolicyEvaluator.evaluate_definitions((duplicate, duplicate), (definition,))


def test_performance_registry_policies_require_three_eligible_samples():
    registry = TestRegistry.default()
    expected = {
        "wifi.ping.success": "ping_success",
        "wifi.latency.threshold": "latency",
        "wifi.packet_loss.threshold": "packet_loss",
        "wifi.throughput.minimum": "throughput",
    }
    for test_id, metric_name in expected.items():
        assert registry.metric_definition(
            test_id, metric_name
        ).measurement_policy.minimum_samples == 3
