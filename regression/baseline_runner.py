"""Save current test results as firmware baseline."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db_helper import get_baseline, init_db, save_baseline_from_latest_passes


def run_baseline(firmware_version="v1.0", run_tests=False):
    root = Path(__file__).resolve().parent.parent
    if run_tests:
        print(f"Running full test suite for baseline {firmware_version}...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/",
                "-v",
                f"--firmware-version={firmware_version}",
            ],
            cwd=root,
            check=True,
        )

    init_db()
    count = save_baseline_from_latest_passes(firmware_version)
    print(f"\nSuccessfully snapshotted golden baseline for firmware '{firmware_version}': {count} test(s)")

    baseline_items = get_baseline(firmware_version)
    for item in baseline_items:
        metric_str = f" ({item['metric_value']} {item['metric_unit']})" if item["metric_value"] is not None else ""
        print(f"  - {item['test_name']}: {item['status']}{metric_str}")

    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Save test results as firmware baseline")
    parser.add_argument("--version", default="v1.0", help="Firmware version tag (e.g. v1.0)")
    parser.add_argument("--run-tests", action="store_true", help="Run test suite before snapshotting baseline")
    args = parser.parse_args()
    run_baseline(args.version, args.run_tests)
