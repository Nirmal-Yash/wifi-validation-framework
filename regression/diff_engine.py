"""Compare current test results against saved baseline."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db_helper import get_baseline, get_latest_results, init_db
from regression.regression_classifier import classify_all
from regression.report_generator import generate_diff_report


def run_diff(firmware_version="v1.0", output_file="diff_report.html"):
    init_db()
    baseline_rows = get_baseline(firmware_version)
    current_rows = get_latest_results()

    baseline_map = {r["test_name"]: r["status"] for r in baseline_rows}
    current_map = {r["test_name"]: r["status"] for r in current_rows}

    deltas = classify_all(baseline_map, current_map)
    report_path = generate_diff_report(deltas, output_file, firmware_version)

    regressions = [d for d in deltas if d["classification"] == "REGRESSION"]
    print(f"Diff report written to: {report_path}")
    print(f"Total tests compared: {len(deltas)}")
    print(f"Regressions (PASS->FAIL): {len(regressions)}")
    for r in regressions:
        print(f"  REGRESSION: {r['test_name']}")
    return deltas


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare test results against baseline")
    parser.add_argument("--version", default="v1.0", help="Baseline firmware version")
    parser.add_argument("--output", default="diff_report.html", help="Output HTML filename")
    args = parser.parse_args()
    run_diff(args.version, args.output)
