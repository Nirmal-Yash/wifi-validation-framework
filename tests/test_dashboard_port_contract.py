from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_runner_port(environment: dict[str, str]) -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from dashboard.app import RUNNER_PORT; print(RUNNER_PORT)",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
        text=True,
    )
    return int(result.stdout.strip())


def test_runner_api_defaults_to_5050_when_no_override_is_set():
    environment = os.environ.copy()
    environment.pop("NETREGRESS_PORT", None)
    assert _read_runner_port(environment) == 5050


def test_runner_api_respects_explicit_port_override():
    environment = os.environ.copy()
    environment["NETREGRESS_PORT"] = "5481"
    assert _read_runner_port(environment) == 5481


def test_runner_api_rejects_non_integer_port():
    environment = os.environ.copy()
    environment["NETREGRESS_PORT"] = "not-a-port"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from dashboard.app import RUNNER_PORT",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode != 0
    assert "NETREGRESS_PORT must be an integer" in result.stderr
