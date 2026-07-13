"""Save current test results as firmware baseline."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.db_helper import init_db, save_baseline_from_latest_passes


def run_baseline(firmware_version="v1.0", run_tests=False):
    root = Path(__file__).resolve().parent.parent
    if run_tests:
        print("Running full test suite before saving baseline...")
        subprocess.run(
            [
                sys.executable, "-m", "pytest", "tests/", "-v",
                f"--firmware-version={firmware_version}",
            ],
            cwd=root,
            check=True,
        )
    init_db()
    count = save_baseline_from_latest_passes(firmware_version)
    print(f"Baseline saved for firmware {firmware_version}: {count} test(s)")
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Save test results as baseline")
    parser.add_argument("--version", default="v1.0", help="Firmware version tag")
    parser.add_argument("--run-tests", action="store_true", help="Run tests before saving")
    args = parser.parse_args()
    run_baseline(args.version, args.run_tests)
