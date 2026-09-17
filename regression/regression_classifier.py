"""Classify test result deltas between baseline and current run.

Supports:
- Binary status deltas (PASS -> FAIL = REGRESSION, FAIL -> PASS = FIXED)
- Metric-level soft regressions (PASS with >20% throughput drop, latency spike, or loss)
- Metric-level improvements (PASS with >20% better metric)
"""

REGRESSION = "REGRESSION"            # Hard regression: PASS -> FAIL
SOFT_REGRESSION = "SOFT_REGRESSION"  # Performance regression: PASS -> PASS with >20% degradation
FIXED = "FIXED"                      # FAIL -> PASS
IMPROVED = "IMPROVED"                # PASS -> PASS with >20% performance improvement
NEW_FAILURE = "NEW_FAILURE"          # No baseline, current FAIL
NEW_PASS = "NEW_PASS"                # No baseline, current PASS
UNCHANGED = "UNCHANGED"              # Stable status and within normal metric variance

LOWER_IS_BETTER_UNITS = {"ms", "%", "seconds", "sec"}


def calculate_metric_delta(baseline_val, current_val, unit):
    """
    Calculate performance degradation percentage.
    Positive value means degradation (worse performance).
    Negative value means improvement.
    """
    if baseline_val is None or current_val is None:
        return None
    try:
        b = float(baseline_val)
        c = float(current_val)
    except (ValueError, TypeError):
        return None

    if b == 0:
        return 100.0 if c > 0 else 0.0

    unit_norm = (unit or "").lower()
    if unit_norm in LOWER_IS_BETTER_UNITS:
        # e.g. latency went from 10ms to 15ms -> +50% degradation
        return round(((c - b) / b) * 100.0, 1)
    else:
        # Higher is better (e.g. throughput went from 100Mbps to 70Mbps -> +30% degradation)
        return round(((b - c) / b) * 100.0, 1)


def classify_delta(
    baseline_status,
    current_status,
    baseline_metric=None,
    current_metric=None,
    metric_unit=None,
    threshold_pct=20.0,
):
    if baseline_status is None:
        return (NEW_PASS if current_status == "PASS" else NEW_FAILURE), None

    if baseline_status == "PASS" and current_status == "FAIL":
        return REGRESSION, None

    if baseline_status == "FAIL" and current_status == "PASS":
        return FIXED, None

    # Both are PASS: check for soft regressions in numerical metrics
    if baseline_status == "PASS" and current_status == "PASS":
        delta_pct = calculate_metric_delta(baseline_metric, current_metric, metric_unit)
        if delta_pct is not None:
            if delta_pct >= threshold_pct:
                return SOFT_REGRESSION, delta_pct
            elif delta_pct <= -threshold_pct:
                return IMPROVED, delta_pct
        return UNCHANGED, delta_pct

    return UNCHANGED, None


def _normalize_item(item):
    """Normalize dictionary or string input into uniform dict."""
    if isinstance(item, dict):
        return {
            "status": item.get("status"),
            "metric_value": item.get("metric_value"),
            "metric_unit": item.get("metric_unit"),
        }
    return {
        "status": item,
        "metric_value": None,
        "metric_unit": None,
    }


def classify_all(baseline_map, current_map):
    """
    Compare dictionary of baseline tests against current tests.
    Keys are test names, values can be status strings or dicts with status & metrics.
    """
    all_tests = set(baseline_map.keys()) | set(current_map.keys())
    results = []

    for test_name in sorted(all_tests):
        base_info = _normalize_item(baseline_map.get(test_name))
        curr_info = _normalize_item(current_map.get(test_name))

        if curr_info["status"] is None:
            continue

        classification, delta_pct = classify_delta(
            base_info["status"],
            curr_info["status"],
            base_info["metric_value"],
            curr_info["metric_value"],
            curr_info["metric_unit"],
        )

        results.append(
            {
                "test_name": test_name,
                "baseline": base_info["status"] or "N/A",
                "current": curr_info["status"],
                "baseline_metric": base_info["metric_value"],
                "current_metric": curr_info["metric_value"],
                "metric_unit": curr_info["metric_unit"] or base_info["metric_unit"] or "",
                "delta_pct": delta_pct,
                "classification": classification,
            }
        )

    return results
