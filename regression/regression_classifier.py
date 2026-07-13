"""Classify test result deltas between baseline and current run."""

REGRESSION = "REGRESSION"       # PASS -> FAIL
FIXED = "FIXED"                 # FAIL -> PASS
NEW_FAILURE = "NEW_FAILURE"     # No baseline, current FAIL
NEW_PASS = "NEW_PASS"           # No baseline, current PASS
UNCHANGED = "UNCHANGED"         # Same status


def classify_delta(baseline_status, current_status):
    if baseline_status is None:
        return NEW_PASS if current_status == "PASS" else NEW_FAILURE
    if baseline_status == "PASS" and current_status == "FAIL":
        return REGRESSION
    if baseline_status == "FAIL" and current_status == "PASS":
        return FIXED
    return UNCHANGED


def classify_all(baseline_map, current_map):
    all_tests = set(baseline_map) | set(current_map)
    results = []
    for test_name in sorted(all_tests):
        baseline_status = baseline_map.get(test_name)
        current_status = current_map.get(test_name)
        if current_status is None:
            continue
        classification = classify_delta(baseline_status, current_status)
        results.append({
            "test_name": test_name,
            "baseline": baseline_status or "N/A",
            "current": current_status,
            "classification": classification,
        })
    return results
