import pytest

from lib.services import FaultDefinition, FaultService
from lib.services.command_runner import CommandResult


class FakeRunner:
    def __init__(self):
        self.commands = []
        self.fail_on = set()

    def execute_shell(self, target, command, **kwargs):
        self.commands.append((target, command, kwargs["command_category"]))
        if len(self.commands) in self.fail_on:
            raise RuntimeError(f"forced failure {len(self.commands)}")
        return CommandResult(
            command_id=f"cmd-{len(self.commands)}",
            target=target,
            command_category=kwargs["command_category"],
            safe_display_command=command,
            stdout="",
            exit_code=None,
            transport="fake",
        )


def make_fault() -> FaultDefinition:
    return FaultDefinition(
        fault_id="test.fault",
        target="client_vm",
        apply_commands=("sudo ip link set wlan0 down",),
        restore_commands=("sudo ip link set wlan0 up",),
        description="test fault",
    )


def test_fault_service_restores_after_context():
    runner = FakeRunner()
    service = FaultService(runner)

    with service.context(make_fault()):
        assert runner.commands[0][1].endswith("wlan0 down")

    assert runner.commands[1][1].endswith("wlan0 up")
    assert runner.commands[0][2] == "fault.apply.test.fault"
    assert runner.commands[1][2] == "fault.restore.test.fault"


def test_fault_service_restores_when_validation_raises():
    runner = FakeRunner()
    service = FaultService(runner)

    with pytest.raises(RuntimeError, match="validation failed"):
        with service.context(make_fault()):
            raise RuntimeError("validation failed")

    assert runner.commands[-1][1].endswith("wlan0 up")


def test_fault_service_restores_after_partial_apply_failure():
    runner = FakeRunner()
    runner.fail_on.add(2)
    service = FaultService(runner)
    fault = FaultDefinition(
        fault_id="test.partial",
        target="client_vm",
        apply_commands=(
            "sudo ip link set wlan0 down",
            "sudo wpa_cli -i wlan0 disconnect",
        ),
        restore_commands=("sudo ip link set wlan0 up",),
        description="partial apply",
    )

    with pytest.raises(RuntimeError, match="forced failure"):
        with service.context(fault):
            pass

    assert runner.commands[-1][1].endswith("wlan0 up")


def test_fault_service_restore_runs_all_commands():
    runner = FakeRunner()
    service = FaultService(runner)
    fault = FaultDefinition(
        fault_id="test.multi",
        target="router1",
        apply_commands=("sudo systemctl stop dnsmasq",),
        restore_commands=(
            "sudo systemctl start dnsmasq",
            "sudo pgrep dnsmasq",
        ),
        description="test multi-command restore",
    )

    service.apply(fault)
    service.restore(fault)

    assert [item[1] for item in runner.commands] == [
        "sudo systemctl stop dnsmasq",
        "sudo systemctl start dnsmasq",
        "sudo pgrep dnsmasq",
    ]
