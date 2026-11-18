from __future__ import annotations

import subprocess

from scripts import ci_reliability_gate


def test_reliability_iteration_runs_state_and_recovery_contracts_in_ci_mode(monkeypatch):
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        observed["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 0, "12 passed in 1.2s", "")

    monkeypatch.setattr(ci_reliability_gate.subprocess, "run", fake_run)
    result = ci_reliability_gate.run_iteration(2, timeout_seconds=90)

    assert result["status"] == "PASS"
    assert observed["command"][1:4] == ["-m", "pytest", "-q"]
    assert "tests/test_resource_lock.py" in observed["command"]
    assert "tests/test_pipeline_runtime.py" in observed["command"]
    assert observed["env"]["NETREGRESS_CI_MODE"] == "1"
    assert observed["env"]["PYTHONNOUSERSITE"] == "1"
    assert observed["timeout"] == 90


def test_reliability_iteration_fails_closed_on_test_failure(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "1 failed", "failure detail")

    monkeypatch.setattr(ci_reliability_gate.subprocess, "run", fake_run)
    result = ci_reliability_gate.run_iteration(1)

    assert result["status"] == "FAIL"
    assert result["returncode"] == 1
    assert "failure detail" in result["stderr_tail"]


def test_reliability_iteration_reports_timeout_without_retrying(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="partial")

    monkeypatch.setattr(ci_reliability_gate.subprocess, "run", fake_run)
    result = ci_reliability_gate.run_iteration(3, timeout_seconds=30)

    assert result["status"] == "FAIL"
    assert result["reason"] == "TIMEOUT"
    assert result["iteration"] == 3
    assert "partial" in result["stdout_tail"]
