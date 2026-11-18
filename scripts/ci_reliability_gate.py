#!/usr/bin/env python3
"""Repeat Linux state, process-ownership and recovery contracts to expose flakiness."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RELIABILITY_TESTS = (
    "tests/test_resource_lock.py",
    "tests/test_run_process.py",
    "tests/test_negative_recovery.py",
    "tests/test_pipeline_orchestration.py",
    "tests/test_pipeline_runtime.py",
    "tests/test_standalone_operations.py",
    "tests/test_sync_queue.py",
)


def run_iteration(iteration: int, *, timeout_seconds: int = 600) -> dict[str, Any]:
    """Run one isolated reliability pass and return a machine-readable result."""
    env = os.environ.copy()
    env.update({
        "NETREGRESS_CI_MODE": "1",
        "NETREGRESS_SESSION_SECRET": "netregress-reliability-ci-session-secret",
        "NETREGRESS_SESSION_COOKIE_SECURE": "0",
        "PYTHONNOUSERSITE": "1",
    })
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--disable-warnings",
        *RELIABILITY_TESTS,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {
            "iteration": iteration,
            "status": "FAIL",
            "reason": "TIMEOUT",
            "timeout_seconds": timeout_seconds,
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
        }
    return {
        "iteration": iteration,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=600, help="per-iteration timeout in seconds")
    args = parser.parse_args(argv)
    if not 1 <= args.iterations <= 5:
        parser.error("--iterations must be between 1 and 5")
    if not 30 <= args.timeout <= 1800:
        parser.error("--timeout must be between 30 and 1800 seconds")

    results = [
        run_iteration(index, timeout_seconds=args.timeout)
        for index in range(1, args.iterations + 1)
    ]
    report = {
        "schema_version": "netregress-reliability.v1",
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "iterations_requested": args.iterations,
        "tests": list(RELIABILITY_TESTS),
        "iterations": results,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
