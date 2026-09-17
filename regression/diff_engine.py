"""Compare current test results against saved baseline, detecting both functional and metric regressions."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db_helper import get_baseline, get_latest_results, init_db
from regression.regression_classifier import REGRESSION, SOFT_REGRESSION, classify_all
from regression.report_generator import generate_diff_report


def run_diff(firmware_version="v1.0", current_firmware=None, output_file="diff_report.html", fail_on_regression=False):
    init_db()
    baseline_rows = get_baseline(firmware_version)
    current_rows = get_latest_results(current_firmware)

    baseline_map = {
        r["test_name"]: {
            "status": r["status"],
            "metric_value": r["metric_value"],
            "metric_unit": r["metric_unit"],
        }
        for r in baseline_rows
    }
    current_map = {
        r["test_name"]: {
            "status": r["status"],
            "metric_value": r["metric_value"],
            "metric_unit": r["metric_unit"],
        }
        for r in current_rows
    }

    deltas = classify_all(baseline_map, current_map)
    report_path = generate_diff_report(deltas, output_file, baseline_version=firmware_version)

    regressions = [d for d in deltas if d["classification"] == REGRESSION]
    soft_regressions = [d for d in deltas if d["classification"] == SOFT_REGRESSION]

    print("\n" + "=" * 60)
    print(f"REGRESSION ANALYSIS SUMMARY (Baseline: {firmware_version})")
    print("=" * 60)
    print(f"Diff report written to: {report_path}")
    print(f"Total tests compared:    {len(deltas)}")
    print(f"Hard Regressions (FAIL): {len(regressions)}")
    print(f"Soft Regressions (Perf): {len(soft_regressions)}")

    for r in regressions:
        print(f"  [HARD REGRESSION] {r['test_name']}: {r['baseline']} -> {r['current']}")
    for sr in soft_regressions:
        print(
            f"  [SOFT REGRESSION] {sr['test_name']}: "
            f"{sr['baseline_metric']}{sr['metric_unit']} -> {sr['current_metric']}{sr['metric_unit']} "
            f"(+{sr['delta_pct']}% degradation)"
        )
    print("=" * 60 + "\n")

    if fail_on_regression and (len(regressions) > 0 or len(soft_regressions) > 0):
        print("CI Gate: Failing execution due to detected regressions.")
        sys.exit(1)

    return deltas


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare test results against baseline")
    parser.add_argument("--version", default="v1.0", help="Baseline firmware version")
    parser.add_argument("--current-version", default=None, help="Current firmware version (optional)")
    parser.add_argument("--output", default="diff_report.html", help="Output HTML filename")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with returncode 1 if regressions are detected (CI gate)",
    )
    args = parser.parse_args()
    run_diff(
        firmware_version=args.version,
        current_firmware=args.current_version,
        output_file=args.output,
        fail_on_regression=args.fail_on_regression,
    )
