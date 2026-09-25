import sys
from pathlib import Path

import pytest

from lib.services.command_runner import CommandResult, LocalRunner, NetmikoRunner
from lib.services.command_security import (
    CommandAuditRecorder,
    CommandSecurityError,
    CommandSecurityPolicy,
    SecureCommandRunner,
    redact_command,
    redact_output,
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


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.closed = False

    def execute(self, target, command, **kwargs):
        self.calls.append(("execute", target, command, kwargs))
        return CommandResult(
            command_id="cmd-1",
            target=target,
            command_category=kwargs.get("command_category", "diagnostic"),
            safe_display_command=str(command),
            stdout="password=super-secret Authorization: Bearer abc123",
            stderr="",
            exit_code=0,
            transport="fake",
        )

    def execute_shell(self, target, command, **kwargs):
        self.calls.append(("execute_shell", target, command, kwargs))
        return CommandResult(
            command_id="cmd-2",
            target=target,
            command_category=kwargs.get("command_category", "shell"),
            safe_display_command=str(command),
            stdout="ok",
            stderr="",
            exit_code=0,
            transport="fake",
        )

    def close(self):
        self.closed = True


class FakeArtifactService:
    def __init__(self):
        self.calls = []

    def register_file(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class FakeEventRepository:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def test_redact_command_and_output_hide_secrets():
    command = "curl --token super-secret --password hunter2 psk=abc123"
    redacted_command = redact_command(command)
    redacted_output = redact_output(
        "Authorization: Bearer token-value password=secret123"
    )

    assert "super-secret" not in redacted_command
    assert "hunter2" not in redacted_command
    assert "abc123" not in redacted_command
    assert "token-value" not in redacted_output
    assert "secret123" not in redacted_output
    assert "***" in redacted_command
    assert "***" in redacted_output


def test_default_policy_blocks_shell_and_destructive_operations():
    policy = CommandSecurityPolicy.default()

    with pytest.raises(CommandSecurityError):
        policy.validate("client_vm", "echo ok; true", shell=True)

    with pytest.raises(CommandSecurityError):
        policy.validate("client_vm", ["rm", "-rf", "/"], shell=False)

    with pytest.raises(CommandSecurityError):
        policy.validate("client_vm", ["ip", "link", "set", "wlan0", "down"], shell=False)


def test_default_policy_allows_dnsmasq_for_router_dhcp_recovery():
    policy = CommandSecurityPolicy.compatibility()
    policy.validate(
        "router1",
        "sudo dnsmasq --conf-file=/etc/dnsmasq.d/lab.conf 2>/dev/null || true",
        shell=True,
    )


def test_compatibility_policy_allows_known_lab_commands_only():
    policy = CommandSecurityPolicy.compatibility()

    policy.validate(
        "client_vm",
        "sudo dhclient -r wlan0 2>/dev/null; sudo dhclient wlan0",
        shell=True,
    )

    with pytest.raises(CommandSecurityError):
        policy.validate("client_vm", "sudo rm -rf / || true", shell=True)


def test_secure_runner_applies_privilege_and_output_redaction():
    fake = FakeRunner()
    runner = SecureCommandRunner(fake, security_policy=CommandSecurityPolicy.default())

    result = runner.execute(
        "local",
        ["echo", "safe"],
        privilege_mode="SUDO",
        command_category="diagnostic",
    )

    assert fake.calls[0][2] == "sudo -n echo safe"
    assert "super-secret" not in result.stdout
    assert "token-value" not in result.stdout
    assert result.redaction_applied is True


def test_secure_shell_runner_uses_explicit_shell_policy():
    fake = FakeRunner()
    runner = SecureCommandRunner(
        fake,
        security_policy=CommandSecurityPolicy.compatibility(),
    )

    result = runner.execute_shell(
        "client_vm",
        "wpa_cli -i wlan0 status 2>/dev/null || wpa_cli status",
    )

    assert fake.calls[0][0] == "execute_shell"
    assert "sudo" not in fake.calls[0][2]
    assert result.command_succeeded is True


def test_command_audit_records_redacted_artifact_and_event(tmp_path):
    artifacts = FakeArtifactService()
    events = FakeEventRepository()
    recorder = CommandAuditRecorder(
        artifact_service=artifacts,
        event_repository=events,
        run_id="run-123",
        attempt_id="attempt-1",
        directory=tmp_path,
    )
    result = CommandResult(
        command_id="cmd-1",
        target="client_vm",
        command_category="diagnostic",
        safe_display_command="echo ok",
        stdout="***",
        exit_code=0,
        transport="fake",
        redaction_applied=True,
    )

    recorder.record(result)
    recorder.close()

    data = Path(recorder.path).read_text(encoding="utf-8")
    assert "cmd-1" in data
    assert "***" in data
    assert "super-secret" not in data
    assert len(events.events) == 1
    assert events.events[0].event_type == "COMMAND_EXECUTED"
    assert artifacts.calls[0]["artifact_type"].value == "COMMAND_OUTPUT"


def test_netmiko_runner_returns_structured_result_and_preserves_transport_behavior():
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
    runner = LocalRunner(security_policy=CommandSecurityPolicy.compatibility())
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
    with pytest.raises(ValueError):
        CommandResult(
            command_id="cmd-1",
            target="local",
            command_category="test",
            safe_display_command="echo ok",
            duration_ms=-1,
        )
