import sys

from lib.services.command_runner import (
    CommandResult,
    LocalRunner,
    NetmikoRunner,
    redact_command,
)


class FakePool:
    def __init__(self, output="ok"):
        self.output = output
        self.calls = []
        self.closed = False

    def send_command(self, target, command, **kwargs):
        self.calls.append((target, command, kwargs))
        return self.output

    def close_all(self):
        self.closed = True


def test_redact_command_hides_common_secrets():
    command = "curl --token super-secret --password hunter2 psk=abc123"
    redacted = redact_command(command)

    assert "super-secret" not in redacted
    assert "hunter2" not in redacted
    assert "abc123" not in redacted
    assert "***" in redacted


def test_netmiko_runner_returns_structured_result_and_preserves_raw_command():
    pool = FakePool("SSID=Test")
    runner = NetmikoRunner(pool)

    result = runner.execute(
        "client_vm",
        "wpa_cli -i wlan0 status",
        command_category="wifi_state",
        idempotent=True,
        privilege_mode="USER",
    )

    assert isinstance(result, CommandResult)
    assert result.target == "client_vm"
    assert result.transport == "netmiko"
    assert result.stdout == "SSID=Test"
    assert result.exit_code is None
    assert result.transport_succeeded is True
    assert result.idempotent is True
    assert pool.calls[0][0] == "client_vm"


def test_local_runner_returns_exit_code_and_output():
    runner = LocalRunner()
    result = runner.execute(
        "local",
        f"{sys.executable} -c \"print('runner-ok')\"",
        command_category="test",
        idempotent=True,
    )

    assert result.transport == "local"
    assert result.exit_code == 0
    assert result.stdout.strip() == "runner-ok"
    assert result.command_succeeded is True
    assert result.timed_out is False


def test_local_runner_shell_is_explicit():
    runner = LocalRunner()
    result = runner.execute_shell(
        "local",
        "printf shell-ok",
        command_category="test",
        idempotent=True,
    )

    assert result.transport == "local-shell"
    assert result.exit_code == 0
    assert result.stdout == "shell-ok"


def test_command_result_rejects_negative_duration():
    try:
        CommandResult(
            command_id="cmd-1",
            target="local",
            command_category="test",
            safe_display_command="echo ok",
            duration_ms=-1,
        )
    except ValueError as exc:
        assert "duration_ms" in str(exc)
    else:
        raise AssertionError("negative duration should be rejected")
