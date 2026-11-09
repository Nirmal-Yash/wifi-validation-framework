from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence

from lib.domain import (
    ComparabilityStatus,
    FlakyTestHistory,
    RegressionAssessment,
    RegressionClass,
    RegressionDimension,
    RegressionMetricComparison,
    Run,
    RunRegressionReport,
    TestResult,
    TestResultStatus,
)
from lib.domain.statistics import MeasurementPolicyEvaluator
from .run_service import RunService
from .test_registry import TestRegistry


class RegressionIntelligenceError(RuntimeError):
    pass


LOWER_IS_BETTER_METRICS = ("latency", "rtt", "round_trip", "packet_loss", "loss", "jitter", "recovery_time", "duration", "error_rate", "retransmission", "retry_count")
HIGHER_IS_BETTER_METRICS = ("throughput", "bandwidth", "goodput", "success_rate", "ping_success", "rssi", "signal_strength", "snr", "data_rate", "tx_rate", "rx_rate")


@dataclass(frozen=True, slots=True)
class _MetricValue:
    value: float
    unit: str


class RegressionIntelligenceService:
    """Run-scoped regression comparison with explicit baseline and context gates."""

    def __init__(
        self,
        *,
        run_service: RunService,
        test_registry: TestRegistry,
        default_threshold_pct: float = 20.0,
    ) -> None:
        if not isfinite(float(default_threshold_pct)) or default_threshold_pct <= 0:
            raise ValueError("default_threshold_pct must be finite and positive")
        self.run_service = run_service
        self.test_registry = test_registry
        self.default_threshold_pct = float(default_threshold_pct)

    def compare_runs(
        self,
        *,
        baseline_run_id: str,
        current_run_id: str,
        baseline_environment_class: str | None = None,
        current_environment_class: str | None = None,
        threshold_overrides: Mapping[tuple[str, str], float] | None = None,
        flaky_history: Mapping[str, Sequence[str]] | None = None,
    ) -> RunRegressionReport:
        baseline = self.run_service.run_repository.get(baseline_run_id)
        current = self.run_service.run_repository.get(current_run_id)
        history = flaky_history or {}

        if baseline is None:
            results = self._latest_results(current)
            return RunRegressionReport(
                baseline_run_id=baseline_run_id,
                current_run_id=current_run_id,
                comparability=ComparabilityStatus.INSUFFICIENT_CONTEXT,
                reason="explicit baseline Run does not exist",
                assessments=tuple(
                    self._missing_baseline_assessment(
                        item, baseline_run_id, current_run_id, history
                    )
                    for item in results
                ),
            )
        if current is None:
            return RunRegressionReport(
                baseline_run_id=baseline_run_id,
                current_run_id=current_run_id,
                comparability=ComparabilityStatus.INSUFFICIENT_CONTEXT,
                reason="current Run does not exist",
            )

        comparability, reason = self._compare_context(
            baseline, current, baseline_environment_class, current_environment_class
        )
        base_results = {
            item.test_id: item for item in self._latest_results(baseline)
        }
        current_results = {
            item.test_id: item for item in self._latest_results(current)
        }
        test_ids = sorted(
            set(self._selected_test_ids(baseline))
            | set(self._selected_test_ids(current))
        )
        assessments = []

        for test_id in test_ids:
            base = base_results.get(test_id)
            curr = current_results.get(test_id)

            if curr is None:
                assessments.append(
                    self._missing_current(
                        test_id, baseline_run_id, current_run_id, base, history
                    )
                )
                continue

            if comparability is not ComparabilityStatus.COMPARABLE:
                assessments.append(
                    self._context_blocked(
                        test_id,
                        baseline_run_id,
                        current_run_id,
                        base,
                        curr,
                        reason,
                        history,
                    )
                )
                continue

            if base is None:
                assessments.append(
                    self._new_test(
                        test_id, baseline_run_id, current_run_id, curr, history
                    )
                )
                continue

            assessments.append(
                self._compare_test(
                    baseline,
                    current,
                    base,
                    curr,
                    threshold_overrides or {},
                    history,
                )
            )

        return RunRegressionReport(
            baseline_run_id=baseline_run_id,
            current_run_id=current_run_id,
            comparability=comparability,
            reason=reason,
            assessments=tuple(assessments),
        )

    def _selected_test_ids(self, run: Run) -> tuple[str, ...]:
        values: list[str] = []
        for selected in run.selected_tests:
            try:
                values.append(self.test_registry.get(selected).test_id)
            except KeyError:
                values.append(self.test_registry.resolve_or_fallback(selected).test_id)
        return tuple(dict.fromkeys(values))

    def _latest_results(self, run: Run | None) -> tuple[TestResult, ...]:
        if run is None or self.run_service.test_result_repository is None:
            return ()
        attempts = self.run_service.attempt_repository.list_for_run(run.run_id)
        if not attempts:
            return ()
        latest = sorted(attempts, key=lambda item: item.number)[-1]
        return tuple(
            self.run_service.test_result_repository.list_for_attempt(latest.attempt_id)
        )

    def _suite_signature(self, run: Run) -> tuple[tuple[str, str], ...]:
        versions: dict[str, set[str]] = {}
        for selected in run.selected_tests:
            try:
                definition = self.test_registry.get(selected)
            except KeyError:
                definition = self.test_registry.resolve_or_fallback(selected)
            versions.setdefault(definition.test_id, set()).add(
                str(run.test_definition_versions[selected])
            )
        return tuple(
            (test_id, "|".join(sorted(values)))
            for test_id, values in sorted(versions.items())
        )

    def _compare_context(
        self,
        baseline: Run,
        current: Run,
        baseline_environment_class: str | None,
        current_environment_class: str | None,
    ) -> tuple[ComparabilityStatus, str]:
        if baseline.lifecycle.value != "COMPLETED":
            return ComparabilityStatus.INCOMPATIBLE, "baseline Run is not completed"
        if baseline.environment_health is None:
            return ComparabilityStatus.INSUFFICIENT_CONTEXT, "baseline Run has no persisted healthy-lab result"
        if baseline.environment_health.value != "HEALTHY":
            return ComparabilityStatus.INCOMPATIBLE, f"baseline lab health is {baseline.environment_health.value}"
        if baseline.validation_profile != current.validation_profile:
            return ComparabilityStatus.INCOMPATIBLE, "validation profiles differ"
        if baseline.lab_id != current.lab_id:
            return ComparabilityStatus.INCOMPATIBLE, "lab identities differ"
        if self._suite_signature(baseline) != self._suite_signature(current):
            return (
                ComparabilityStatus.INCOMPATIBLE,
                "test selection or definition versions differ",
            )
        if not baseline_environment_class or not current_environment_class:
            return (
                ComparabilityStatus.INSUFFICIENT_CONTEXT,
                "environment class is required for regression comparability",
            )
        if baseline_environment_class != current_environment_class:
            return (
                ComparabilityStatus.INCOMPATIBLE,
                f"environment classes differ: {baseline_environment_class} vs {current_environment_class}",
            )
        return ComparabilityStatus.COMPARABLE, "Run contexts are comparable"

    def _compare_test(
        self,
        baseline: Run,
        current: Run,
        base: TestResult,
        curr: TestResult,
        threshold_overrides: Mapping[tuple[str, str], float],
        history: Mapping[str, Sequence[str]],
    ) -> RegressionAssessment:
        flaky = self._flaky(curr.test_id, history.get(curr.test_id, ()))
        dimensions = self._dimensions(curr.test_id)

        if base.test_version != curr.test_version:
            return self._assessment(
                base,
                curr,
                RegressionClass.NO_BASELINE,
                dimensions,
                flaky,
                reason="test definition versions differ",
            )
        if base.evidence_state.value not in {"COMPLETE", "NOT_REQUIRED"}:
            return self._assessment(
                base, curr, RegressionClass.NO_BASELINE, dimensions, flaky,
                reason=f"baseline evidence is not valid comparison evidence ({base.evidence_state.value})",
            )
        if curr.evidence_state.value not in {"COMPLETE", "NOT_REQUIRED"}:
            return self._assessment(
                base, curr, RegressionClass.UNVALIDATED, dimensions, flaky,
                reason=f"current evidence is not valid comparison evidence ({curr.evidence_state.value})",
            )
        if base.status in {
            TestResultStatus.ERROR,
            TestResultStatus.BLOCKED,
            TestResultStatus.UNVALIDATED,
            TestResultStatus.SKIPPED,
        }:
            return self._assessment(
                base,
                curr,
                RegressionClass.NO_BASELINE,
                dimensions,
                flaky,
                reason="baseline result is not valid comparison evidence",
            )
        if (
            curr.status in {
                TestResultStatus.ERROR,
                TestResultStatus.BLOCKED,
                TestResultStatus.UNVALIDATED,
                TestResultStatus.SKIPPED,
            }
            or curr.evidence_state.value in {"INCOMPLETE", "INVALID"}
        ):
            return self._assessment(
                base,
                curr,
                RegressionClass.UNVALIDATED,
                dimensions,
                flaky,
                reason="current result cannot support a trustworthy regression decision",
            )

        if base.status is TestResultStatus.PASS and curr.status is TestResultStatus.FAIL:
            return self._assessment(
                base,
                curr,
                RegressionClass.REGRESSION,
                dimensions,
                flaky,
                reason="functional status changed from PASS to FAIL",
            )
        if base.status is TestResultStatus.FAIL and curr.status is TestResultStatus.PASS:
            return self._assessment(
                base,
                curr,
                RegressionClass.FIXED,
                dimensions,
                flaky,
                reason="functional status changed from FAIL to PASS",
            )
        if base.status is not TestResultStatus.PASS or curr.status is not TestResultStatus.PASS:
            return self._assessment(
                base,
                curr,
                RegressionClass.UNCHANGED,
                dimensions,
                flaky,
                reason="functional statuses are unchanged",
            )

        comparisons = []
        definition = self.test_registry.get(curr.test_id)
        base_metrics = {metric.name: metric for metric in base.metrics}
        current_metrics = {metric.name: metric for metric in curr.metrics}
        decision_metrics = (definition.decision_metric,) if definition.decision_metric else ()

        # Diagnostic metrics without a registry decision policy must not affect
        # release classification. A declared decision metric missing from either
        # Run is instead a fail-closed, UNVALIDATED comparison.
        for name in decision_metrics:
            bm = base_metrics.get(name)
            cm = current_metrics.get(name)
            dimension = self._dimensions(curr.test_id)[0]
            metric_unit = definition.metric_definitions.get(name, "")

            if bm is None or cm is None:
                comparisons.append(
                    RegressionMetricComparison(
                        name,
                        cm.unit if cm else bm.unit if bm else metric_unit,
                        None,
                        None,
                        None,
                        None,
                        RegressionClass.UNVALIDATED,
                        dimension,
                        "metric is missing from one Run",
                    )
                )
                continue

            if bm.unit != cm.unit:
                comparisons.append(
                    RegressionMetricComparison(
                        name,
                        cm.unit,
                        None,
                        None,
                        None,
                        None,
                        RegressionClass.UNVALIDATED,
                        dimension,
                        "metric units differ",
                    )
                )
                continue

            try:
                base_value = self._metric_value(base, bm, curr.test_id)
                current_value = self._metric_value(current, cm, curr.test_id)
                direction = self._metric_direction(current, curr.test_id, name)
                threshold_override = threshold_overrides.get((curr.test_id, name))
                threshold = (
                    threshold_override
                    if threshold_override is not None
                    else self._threshold(current, curr.test_id, name)
                )
                threshold = float(threshold)
                if not isfinite(threshold) or threshold <= 0:
                    raise RegressionIntelligenceError(
                        f"regression threshold for {curr.test_id}:{name} must be finite and positive"
                    )
                delta = self._delta(base_value.value, current_value.value, direction)
            except Exception as exc:
                comparisons.append(
                    RegressionMetricComparison(
                        name, cm.unit, None, None, None, None,
                        RegressionClass.UNVALIDATED, dimension, str(exc),
                    )
                )
                continue

            if delta is None:
                comparisons.append(
                    RegressionMetricComparison(
                        name, cm.unit, base_value.value, current_value.value,
                        None, threshold, RegressionClass.UNVALIDATED, dimension,
                        "percentage change is undefined for a zero baseline",
                    )
                )
                continue
            classification = RegressionClass.UNCHANGED
            if delta >= threshold:
                classification = RegressionClass.SOFT_REGRESSION
            elif delta <= -threshold:
                classification = RegressionClass.IMPROVED

            comparisons.append(
                RegressionMetricComparison(
                    name, cm.unit, base_value.value, current_value.value,
                    delta, threshold, classification, dimension,
                )
            )

        primary = self._aggregate_metric_classification(
            tuple(item.classification for item in comparisons)
        )
        return self._assessment(
            base,
            curr,
            primary,
            dimensions,
            flaky,
            comparisons=tuple(comparisons),
            reason="metric-aware PASS to PASS comparison",
        )

    def _metric_value(self, _run: Run, metric, test_id: str) -> _MetricValue:
        definition = self.test_registry.metric_definition(test_id, metric.name)
        summary = MeasurementPolicyEvaluator.evaluate(
            metric, definition.measurement_policy
        )
        return _MetricValue(summary.decision_value, metric.unit)

    @staticmethod
    def _metric_direction(run: Run, test_id: str, metric_name: str) -> str:
        regression = run.resolved_config.get("regression", {})
        directions = regression.get("metric_directions", {}) if isinstance(regression, Mapping) else {}
        per_test = directions.get(test_id, {}) if isinstance(directions, Mapping) else {}
        configured = per_test.get(metric_name) if isinstance(per_test, Mapping) else None
        if configured is not None:
            value = str(configured).strip().upper().replace("-", "_").replace(" ", "_")
            if value in {"LOWER_IS_BETTER", "HIGHER_IS_BETTER"}:
                return value
            raise RegressionIntelligenceError(
                f"invalid metric direction for {test_id}:{metric_name}: {configured}"
            )
        normalized = metric_name.lower().replace("-", "_")
        if any(token in normalized for token in LOWER_IS_BETTER_METRICS):
            return "LOWER_IS_BETTER"
        if any(token in normalized for token in HIGHER_IS_BETTER_METRICS):
            return "HIGHER_IS_BETTER"
        raise RegressionIntelligenceError(
            f"metric direction is not defined for {test_id}:{metric_name}; configure regression.metric_directions"
        )

    def _threshold(self, run: Run, test_id: str, metric_name: str) -> float:
        regression = run.resolved_config.get("regression", {})
        thresholds = regression.get("thresholds", {}) if isinstance(regression, Mapping) else {}
        per_test = thresholds.get(test_id, {}) if isinstance(thresholds, Mapping) else {}
        value = per_test.get(metric_name) if isinstance(per_test, Mapping) else None
        if value is None and isinstance(regression, Mapping):
            value = regression.get("default_threshold_pct")
        if value is None:
            return self.default_threshold_pct
        value = float(value)
        if not isfinite(value) or value <= 0:
            raise RegressionIntelligenceError(
                f"invalid regression threshold for {test_id}:{metric_name}"
            )
        return value

    @staticmethod
    def _delta(base: float, current: float, direction: str) -> float | None:
        if direction not in {"LOWER_IS_BETTER", "HIGHER_IS_BETTER"}:
            raise RegressionIntelligenceError(f"unsupported metric direction: {direction}")
        if base == 0:
            return 0.0 if current == 0 else None
        change = ((current - base) / abs(base)) * 100.0
        return round(change if direction == "LOWER_IS_BETTER" else -change, 2)

    @staticmethod
    def _aggregate_metric_classification(
        values: tuple[RegressionClass, ...],
    ) -> RegressionClass:
        if not values:
            return RegressionClass.UNCHANGED
        if RegressionClass.UNVALIDATED in values:
            return RegressionClass.UNVALIDATED
        if RegressionClass.SOFT_REGRESSION in values:
            return RegressionClass.SOFT_REGRESSION
        if RegressionClass.IMPROVED in values and all(
            value in {RegressionClass.IMPROVED, RegressionClass.UNCHANGED}
            for value in values
        ):
            return RegressionClass.IMPROVED
        return RegressionClass.UNCHANGED

    def _dimensions(self, test_id: str) -> tuple[RegressionDimension, ...]:
        definition = self.test_registry.get(test_id)
        values = []
        category = definition.category.lower()
        if category == "recovery":
            values.append(RegressionDimension.RECOVERY)
        elif category == "performance":
            values.append(RegressionDimension.PERFORMANCE)
        else:
            values.append(RegressionDimension.FUNCTIONAL)

        protocol = definition.protocol.upper()
        if any(
            token in protocol
            for token in ("DHCP", "DNS", "EAPOL", "802.11", "PCAP")
        ):
            values.append(RegressionDimension.PROTOCOL)
        if "CONFIG" in definition.category.upper():
            values.append(RegressionDimension.CONFIGURATION)
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _flaky(
        test_id: str, observations: Sequence[str]
    ) -> FlakyTestHistory:
        values = tuple(str(value) for value in observations if value)
        pass_count = sum(value == "PASS" for value in values)
        fail_count = sum(value == "FAIL" for value in values)
        transitions = sum(
            previous != current
            for previous, current in zip(values, values[1:])
        )
        flagged = pass_count > 0 and fail_count > 0
        reason = (
            "mixed PASS/FAIL history under supplied observations"
            if flagged
            else "stable supplied history"
        )
        return FlakyTestHistory(
            test_id,
            values,
            pass_count,
            fail_count,
            transitions,
            flagged,
            reason,
        )

    def _assessment(
        self,
        base,
        curr,
        classification,
        dimensions,
        flaky,
        *,
        comparisons=(),
        reason="",
    ):
        return RegressionAssessment(
            test_id=curr.test_id,
            node_id=curr.node_id,
            baseline_run_id=base.run_id,
            current_run_id=curr.run_id,
            baseline_status=base.status.value,
            current_status=curr.status.value,
            classification=classification,
            dimensions=tuple(dimensions),
            metric_comparisons=tuple(comparisons),
            flaky_history=flaky,
            reason=reason,
        )

    def _missing_baseline_assessment(self, curr, baseline_id, current_id, history):
        return RegressionAssessment(
            curr.test_id,
            curr.node_id,
            baseline_id,
            current_id,
            "N/A",
            curr.status.value,
            RegressionClass.NO_BASELINE,
            self._dimensions(curr.test_id),
            flaky_history=self._flaky(
                curr.test_id, history.get(curr.test_id, ())
            ),
            reason="no explicit baseline Run is available",
        )

    def _context_blocked(
        self,
        test_id,
        baseline_id,
        current_id,
        base,
        curr,
        reason,
        history,
    ):
        return RegressionAssessment(
            test_id,
            curr.node_id,
            baseline_id,
            current_id,
            base.status.value if base else "N/A",
            curr.status.value,
            RegressionClass.NO_BASELINE,
            self._dimensions(test_id),
            flaky_history=self._flaky(
                test_id, history.get(test_id, ())
            ),
            reason=reason,
        )

    def _missing_current(
        self,
        test_id,
        baseline_id,
        current_id,
        base,
        history,
    ):
        definition = self.test_registry.get(test_id)
        return RegressionAssessment(
            test_id,
            base.node_id if base else definition.node_id,
            baseline_id,
            current_id,
            base.status.value if base else "N/A",
            "MISSING",
            RegressionClass.UNVALIDATED,
            self._dimensions(test_id),
            flaky_history=self._flaky(
                test_id, history.get(test_id, ())
            ),
            reason="required current TestResult is missing",
        )

    def _new_test(self, test_id, baseline_id, current_id, curr, history):
        classification = (
            RegressionClass.NEW_PASS
            if curr.status is TestResultStatus.PASS
            else RegressionClass.NEW_FAILURE
        )
        return RegressionAssessment(
            test_id,
            curr.node_id,
            baseline_id,
            current_id,
            "N/A",
            curr.status.value,
            classification,
            self._dimensions(test_id),
            flaky_history=self._flaky(
                test_id, history.get(test_id, ())
            ),
            reason="current test has no baseline TestResult",
        )
