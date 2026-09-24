from __future__ import annotations

from dataclasses import dataclass
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


LOWER_IS_BETTER_UNITS = frozenset({"ms", "%", "seconds", "sec", "s", "db"})


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
        if default_threshold_pct <= 0:
            raise ValueError("default_threshold_pct must be positive")
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
        test_ids = sorted(set(baseline.selected_tests) | set(current.selected_tests))
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

    @staticmethod
    def _suite_signature(run: Run) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(run.test_definition_versions.items()))

    def _compare_context(
        self,
        baseline: Run,
        current: Run,
        baseline_environment_class: str | None,
        current_environment_class: str | None,
    ) -> tuple[ComparabilityStatus, str]:
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
        base_metrics = {metric.name: metric for metric in base.metrics}
        current_metrics = {metric.name: metric for metric in curr.metrics}

        for name in sorted(set(base_metrics) | set(current_metrics)):
            bm = base_metrics.get(name)
            cm = current_metrics.get(name)
            dimension = self._dimensions(curr.test_id)[0]

            if bm is None or cm is None:
                comparisons.append(
                    RegressionMetricComparison(
                        name,
                        cm.unit if cm else bm.unit,
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
            except Exception as exc:
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
                        str(exc),
                    )
                )
                continue

            threshold = threshold_overrides.get(
                (curr.test_id, name),
                self._threshold(current, curr.test_id, name),
            )
            delta = self._delta(
                base_value.value, current_value.value, cm.unit
            )
            classification = RegressionClass.UNCHANGED
            if delta is not None and delta >= threshold:
                classification = RegressionClass.SOFT_REGRESSION
            elif delta is not None and delta <= -threshold:
                classification = RegressionClass.IMPROVED

            comparisons.append(
                RegressionMetricComparison(
                    name,
                    cm.unit,
                    base_value.value,
                    current_value.value,
                    delta,
                    threshold,
                    classification,
                    dimension,
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

    def _metric_value(self, _run: Run, result: TestResult, metric) -> _MetricValue:
        definition = self.test_registry.metric_definition(result.test_id, metric.name)
        summary = MeasurementPolicyEvaluator.evaluate(
            metric, definition.measurement_policy
        )
        return _MetricValue(summary.decision_value, metric.unit)

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
        if value <= 0:
            raise RegressionIntelligenceError(
                f"invalid regression threshold for {test_id}:{metric_name}"
            )
        return value

    @staticmethod
    def _delta(base: float, current: float, unit: str) -> float | None:
        if base == 0:
            return 0.0 if current == 0 else 100.0
        if unit.lower() in LOWER_IS_BETTER_UNITS:
            return round(((current - base) / base) * 100.0, 2)
        return round(((base - current) / base) * 100.0, 2)

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
