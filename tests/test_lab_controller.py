from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.services.command_runner import CommandResult
from lib.services.lab_controller import LabController, LabControllerError


class FakeCommandRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute_shell(self, target, command, **kwargs):
        self.calls.append((target, command, kwargs))
        return self.result


def _result(*, exit_code=0, timed_out=False, transport_error=None):
    return CommandResult(
        command_id="command-1",
        target="local-lab",
        command_category="lab_provision",
        safe_display_command="bash wifi_lab_reprovision_robust.sh",
        exit_code=exit_code,
        timed_out=timed_out,
        transport="local-shell",
        transport_error=transport_error,
    )


def _controller(tmp_path, result=None):
    script = tmp_path / "wifi lab; launcher.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    runner = FakeCommandRunner(result or _result())
    return LabController(
        command_runner=runner,
        provisioning_script=script,
        lab_id="test-lab",
    ), runner, script


def test_validate_launcher_is_read_only(tmp_path):
    controller, runner, script = _controller(tmp_path)
    before = script.read_bytes()
    assert controller.validate_launcher() == script.resolve()
    assert script.read_bytes() == before
    assert runner.calls == []


def test_lab_operation_preserves_argv_boundaries_and_timeout(tmp_path):
    controller, runner, _ = _controller(tmp_path)
    result = controller.provision("project one", "--label", "ap; touch /tmp/pwned", timeout=45)
    target, command, kwargs = runner.calls[0]

    assert result.operation == "provision"
    assert target == "local-lab"
    assert "'project one'" in command
    assert "'ap; touch /tmp/pwned'" in command
    assert kwargs["execution_timeout_sec"] == 45
    assert kwargs["idempotent"] is False


@pytest.mark.parametrize(
    "result",
    [
        _result(exit_code=2),
        _result(exit_code=None),
        _result(exit_code=None, timed_out=True, transport_error="timeout"),
    ],
)
def test_lab_operation_fails_closed_on_unknown_or_failed_exit(result, tmp_path):
    controller, _, _ = _controller(tmp_path, result)
    with pytest.raises(LabControllerError):
        controller.provision("--check")


def test_lab_controller_rejects_missing_or_non_executable_launcher(tmp_path):
    controller, _, script = _controller(tmp_path)
    script.unlink()
    with pytest.raises(LabControllerError, match="not found"):
        controller.validate_launcher()
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o644)
    with pytest.raises(LabControllerError, match="not executable"):
        controller.validate_launcher()


def test_lab_operation_timeout_must_be_positive_and_finite(tmp_path):
    controller, runner, _ = _controller(tmp_path)
    with pytest.raises(ValueError):
        controller.provision(timeout=0)
    with pytest.raises(ValueError):
        controller.cleanup(timeout=float("inf"))
    assert runner.calls == []
