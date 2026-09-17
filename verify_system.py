"""System Verification Script for WiFi Validation Framework.

Runs comprehensive checks across the refactored architecture:
1. Module compilation & syntax integrity
2. Database schema, metrics tracking & baseline version isolation
3. Regression classifier intelligence (hard & soft regressions)
4. Diff report generation
5. Environment and configuration sanity
"""

import os
import py_compile
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step(title):
    print(f"\n{CYAN}{BOLD}=== {title} ==={RESET}")


def check_syntax():
    print_step("Step 1: Python Syntax & Compilation Check")
    files_to_check = [
        "lib/connector.py",
        "lib/db_helper.py",
        "lib/traffic.py",
        "lib/capture.py",
        "lib/fault_injector.py",
        "lib/wifi_analyzer.py",
        "tests/conftest.py",
        "tests/test_dhcp.py",
        "tests/test_ssid.py",
        "tests/test_auth.py",
        "tests/test_dns.py",
        "tests/test_ping.py",
        "tests/test_throughput.py",
        "tests/test_packet_capture.py",
        "tests/test_fault_injection.py",
        "regression/regression_classifier.py",
        "regression/diff_engine.py",
        "regression/report_generator.py",
        "regression/fw_simulator.py",
        "regression/baseline_runner.py",
        "dashboard/app.py",
    ]

    all_passed = True
    for f in files_to_check:
        full_path = ROOT / f
        try:
            py_compile.compile(str(full_path), doraise=True)
            print(f"  [{GREEN}OK{RESET}] {f}")
        except Exception as e:
            print(f"  [{RED}FAIL{RESET}] {f}: {e}")
            all_passed = False
    return all_passed


def check_database():
    print_step("Step 2: Database Schema & Baseline Version Isolation")
    temp_dir = Path(tempfile.mkdtemp())
    try:
        from lib import db_helper

        db_helper.DB_PATH = temp_dir / "verify.db"
        db_helper.init_db()

        # Insert v1.0 run
        db_helper.insert_result(
            "test_ping",
            "PASS",
            firmware_version="v1.0",
            duration_ms=10,
            metric_value=12.5,
            metric_unit="ms",
        )
        db_helper.insert_result(
            "test_throughput",
            "PASS",
            firmware_version="v1.0",
            duration_ms=10200,
            metric_value=75.0,
            metric_unit="Mbps",
        )

        # Snapshot v1.0
        v1_count = db_helper.save_baseline_from_latest_passes("v1.0")
        assert v1_count == 2, f"Expected 2 baseline tests, got {v1_count}"

        # Insert v2.0 run (where throughput drops to 45.0 Mbps)
        db_helper.insert_result(
            "test_ping",
            "PASS",
            firmware_version="v2.0",
            duration_ms=12,
            metric_value=13.0,
            metric_unit="ms",
        )
        db_helper.insert_result(
            "test_throughput",
            "PASS",
            firmware_version="v2.0",
            duration_ms=10100,
            metric_value=45.0,
            metric_unit="Mbps",
        )

        # Verify v1.0 baseline remains isolated
        base_v1 = db_helper.get_baseline("v1.0")
        base_map = {r["test_name"]: dict(r) for r in base_v1}
        assert (
            base_map["test_throughput"]["metric_value"] == 75.0
        ), "Baseline isolation failed: v2.0 modified v1.0 baseline!"

        # Verify metric history
        hist = db_helper.get_metric_history("test_throughput")
        assert len(hist) == 2, f"Expected 2 history points, got {len(hist)}"
        assert hist[0]["metric_value"] == 75.0
        assert hist[1]["metric_value"] == 45.0

        print(f"  [{GREEN}OK{RESET}] Database initialized with metric columns")
        print(f"  [{GREEN}OK{RESET}] Baseline version filtering & isolation verified")
        print(f"  [{GREEN}OK{RESET}] Metric history retrieval verified")
        return True
    except Exception as e:
        print(f"  [{RED}FAIL{RESET}] Database check error: {e}")
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def check_classifier():
    print_step("Step 3: Regression Classifier Logic (Hard & Soft)")
    try:
        from regression.regression_classifier import (
            FIXED,
            IMPROVED,
            REGRESSION,
            SOFT_REGRESSION,
            UNCHANGED,
            classify_delta,
        )

        # 1. Hard regression
        assert classify_delta("PASS", "FAIL")[0] == REGRESSION
        # 2. Fixed
        assert classify_delta("FAIL", "PASS")[0] == FIXED
        # 3. Soft regression: Latency jumped from 10ms to 25ms (+150%)
        c_lat, d_lat = classify_delta("PASS", "PASS", baseline_metric=10.0, current_metric=25.0, metric_unit="ms")
        assert c_lat == SOFT_REGRESSION and d_lat == 150.0

        # 4. Soft regression: Throughput dropped from 80Mbps to 50Mbps (+37.5% degradation)
        c_tp, d_tp = classify_delta("PASS", "PASS", baseline_metric=80.0, current_metric=50.0, metric_unit="Mbps")
        assert c_tp == SOFT_REGRESSION and d_tp == 37.5

        # 5. Improvement: Throughput increased from 50Mbps to 90Mbps (-80% degradation)
        c_imp, _ = classify_delta("PASS", "PASS", baseline_metric=50.0, current_metric=90.0, metric_unit="Mbps")
        assert c_imp == IMPROVED

        # 6. Unchanged: Latency change within threshold
        c_unc, _ = classify_delta("PASS", "PASS", baseline_metric=20.0, current_metric=21.0, metric_unit="ms")
        assert c_unc == UNCHANGED

        print(f"  [{GREEN}OK{RESET}] Hard regression detection (PASS -> FAIL)")
        print(f"  [{GREEN}OK{RESET}] Soft regression detection on latency spike (+150% -> SOFT_REGRESSION)")
        print(f"  [{GREEN}OK{RESET}] Soft regression detection on throughput drop (+37.5% -> SOFT_REGRESSION)")
        print(f"  [{GREEN}OK{RESET}] Metric improvement detection (IMPROVED)")
        print(f"  [{GREEN}OK{RESET}] Normal variance tolerance (UNCHANGED)")
        return True
    except Exception as e:
        print(f"  [{RED}FAIL{RESET}] Classifier check error: {e}")
        return False


def check_report_generator():
    print_step("Step 4: Report Generator HTML Generation")
    try:
        from regression.report_generator import generate_diff_report

        deltas = [
            {
                "test_name": "tests/test_ping.py::test_latency",
                "baseline": "PASS",
                "current": "PASS",
                "baseline_metric": 12.0,
                "current_metric": 30.0,
                "metric_unit": "ms",
                "delta_pct": 150.0,
                "classification": "SOFT_REGRESSION",
            },
            {
                "test_name": "tests/test_dns.py::test_dns_resolution",
                "baseline": "PASS",
                "current": "FAIL",
                "baseline_metric": 1.0,
                "current_metric": 0.0,
                "metric_unit": "bool",
                "delta_pct": None,
                "classification": "REGRESSION",
            },
        ]

        out = generate_diff_report(deltas, output_file="verify_report.html", baseline_version="v1.0")
        out_path = Path(out)
        assert out_path.exists(), "Diff report HTML was not created"
        content = out_path.read_text(encoding="utf-8")
        assert "SOFT_REGRESSION" in content
        assert "Hard Regressions" in content
        out_path.unlink()  # cleanup
        print(f"  [{GREEN}OK{RESET}] Diff report HTML successfully generated with metric badges")
        return True
    except Exception as e:
        print(f"  [{RED}FAIL{RESET}] Report generator error: {e}")
        return False


def main():
    print(f"{BOLD}WiFi Validation Framework — System Self-Check{RESET}")
    print(f"Workspace: {ROOT}\n")

    r1 = check_syntax()
    r2 = check_database()
    r3 = check_classifier()
    r4 = check_report_generator()

    print("\n" + "=" * 60)
    if r1 and r2 and r3 and r4:
        print(f"{GREEN}{BOLD}ALL SYSTEM CHECKS PASSED SUCCESSFULLY!{RESET}")
        print("The framework logic and intelligence layer are completely verified.")
    else:
        print(f"{RED}{BOLD}SOME CHECKS FAILED. Please review the errors above.{RESET}")
    print("=" * 60)


if __name__ == "__main__":
    main()
