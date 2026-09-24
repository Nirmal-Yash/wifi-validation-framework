from __future__ import annotations

from dataclasses import dataclass, field
import re
import shlex
import socket
import subprocess
import time
from typing import Protocol, Sequence
import uuid

import paramiko
from netmiko.exceptions import NetmikoTimeoutException

from lib.connector import ConnectionPool


_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(\b(?:password|passwd|secret|token|private_key|api_key|psk)\b\s*(?:=|:)\s*)([^\s'\";]+)"
)
_SECRET_FLAG_RE = re.compile(
    r"(?i)(--?(?:password|passwd|secret|token|private[-_]key|api[-_]key|psk)\s+)([^\s'\";]+)"
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Structured outcome of one command execution attempt."""

    command_id: str
    target: str
    command_category: str
    safe_display_command: str
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
    exit_code: int | None = None
    duration_ms: int = 0
    connect_timeout_sec: float | None = 10.0
    execution_timeout_sec: float | None = 30.0
    idle_timeout_sec: float | None = None
    timed_out: bool = False
    idempotent: bool = False
    privilege_mode: str = "USER"
    redaction_applied: bool = False
    transport: str = "unknown"
    transport_error: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("command_id", self.command_id),
            ("target", self.target),
            ("command_category", self.command_category),
            ("safe_display_command", self.safe_display_command),
            ("privilege_mode", self.privilege_mode),
            ("transport", self.transport),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        for name, value in (
            ("connect_timeout_sec", self.connect_timeout_sec),
            ("execution_timeout_sec", self.execution_timeout_sec),
            ("idle_timeout_sec", self.idle_timeout_sec),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")

    @property
    def transport_succeeded(self) -> bool:
        """Return whether transport completed without a transport error."""
        return not self.timed_out and self.transport_error is None

    @property
    def command_succeeded(self) -> bool:
        """Return command-level success only when an exit code is available."""
        return self.exit_code == 0


class CommandRunner(Protocol):
    """Execution boundary used by adapters and orchestration."""

    def execute(
        self,
        target: str,
        command: str,
        *,
        command_category: str = "diagnostic",
        connect_timeout_sec: float | None = 10.0,
        execution_timeout_sec: float | None = 30.0,
        idle_timeout_sec: float | None = None,
        idempotent: bool = False,
        privilege_mode: str = "USER",
        display_command: str | None = None,
    ) -> CommandResult:
        ...

    def execute_shell(
        self,
        target: str,
        command: str,
        *,
        command_category: str = "shell",
        connect_timeout_sec: float | None = 10.0,
        execution_timeout_sec: float | None = 30.0,
        idle_timeout_sec: float | None = None,
        idempotent: bool = False,
        privilege_mode: str = "USER",
        display_command: str | None = None,
    ) -> CommandResult:
        ...


@dataclass(frozen=True, slots=True)
class SSHConnectionSpec:
    """Minimal SSH connection material for ParamikoExecRunner."""

    target: str
    host: str
    username: str
    port: int = 22
    password: str | None = field(default=None, repr=False)
    key_filename: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("target", self.target),
            ("host", self.host),
            ("username", self.username),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.port <= 0:
            raise ValueError("port must be positive")


def redact_command(command: str) -> str:
    """Redact common secret-bearing command arguments for logs and UI."""
    redacted = _SECRET_ASSIGN_RE.sub(r"\1***", command)
    return _SECRET_FLAG_RE.sub(r"\1***", redacted)


def _command_id() -> str:
    return uuid.uuid4().hex


def _is_timeout_error(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, socket.timeout, NetmikoTimeoutException)) or (
        "timed out" in str(exc).lower()
    )


def _normalize_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _display_command(command: str, display_command: str | None) -> tuple[str, bool]:
    source = command if display_command is None else display_command
    redacted = redact_command(source)
    return redacted, redacted != source


class NetmikoRunner:
    """Structured runner backed by the existing ConnectionPool transport."""

    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def execute(
        self,
        target: str,
        command: str,
        *,
        command_category: str = "diagnostic",
        connect_timeout_sec: float | None = 10.0,
        execution_timeout_sec: float | None = 30.0,
        idle_timeout_sec: float | None = None,
        idempotent: bool = False,
        privilege_mode: str = "USER",
        display_command: str | None = None,
    ) -> CommandResult:
        started = time.monotonic()
        safe_command, redacted = _display_command(command, display_command)
        kwargs = {}
        if execution_timeout_sec is not None:
            kwargs["read_timeout"] = execution_timeout_sec

        try:
            stdout = self.pool.send_command(target, command, **kwargs)
            timed_out = False
            transport_error = None
        except Exception as exc:
            stdout = ""
            timed_out = _is_timeout_error(exc)
            transport_error = f"{type(exc).__name__}: {exc}"

        return CommandResult(
            command_id=_command_id(),
            target=target,
            command_category=command_category,
            safe_display_command=safe_command,
            stdout=_normalize_output(stdout),
            stderr="",
            exit_code=None,
            duration_ms=int((time.monotonic() - started) * 1000),
            connect_timeout_sec=connect_timeout_sec,
            execution_timeout_sec=execution_timeout_sec,
            idle_timeout_sec=idle_timeout_sec,
            timed_out=timed_out,
            idempotent=idempotent,
            privilege_mode=privilege_mode,
            redaction_applied=redacted,
            transport="netmiko",
            transport_error=transport_error,
        )

    def execute_shell(self, target: str, command: str, **kwargs) -> CommandResult:
        return self.execute(
            target,
            command,
            command_category=kwargs.pop("command_category", "shell"),
            **kwargs,
        )

    def close(self) -> None:
        self.pool.close_all()


class ParamikoExecRunner:
    """Structured non-interactive SSH exec runner.

    This runner is distinct from the dedicated DHCP capture channel. That raw
    foreground Paramiko channel remains protected for tcpdump lifecycle control.
    """

    def __init__(self, spec: SSHConnectionSpec):
        self.spec = spec
        self._client: paramiko.SSHClient | None = None

    def _connect(self, timeout: float | None) -> paramiko.SSHClient:
        if self._client is not None and self._client.get_transport() is not None:
            return self._client

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        connect_kwargs = {
            "hostname": self.spec.host,
            "port": self.spec.port,
            "username": self.spec.username,
            "password": self.spec.password,
            "key_filename": self.spec.key_filename,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if timeout is not None:
            connect_kwargs["timeout"] = timeout
            connect_kwargs["auth_timeout"] = timeout
            connect_kwargs["banner_timeout"] = timeout
        client.connect(**connect_kwargs)
        self._client = client
        return client

    def execute(
        self,
        target: str,
        command: str,
        *,
        command_category: str = "diagnostic",
        connect_timeout_sec: float | None = 10.0,
        execution_timeout_sec: float | None = 30.0,
        idle_timeout_sec: float | None = None,
        idempotent: bool = False,
        privilege_mode: str = "USER",
        display_command: str | None = None,
    ) -> CommandResult:
        started = time.monotonic()
        safe_command, redacted = _display_command(command, display_command)
        stdout_text = ""
        stderr_text = ""
        exit_code = None
        timed_out = False
        transport_error = None

        try:
            client = self._connect(connect_timeout_sec)
            channel_timeout = idle_timeout_sec or execution_timeout_sec
            stdin, stdout, stderr = client.exec_command(
                command,
                timeout=channel_timeout,
            )
            del stdin
            stdout_text = _normalize_output(stdout.read())
            stderr_text = _normalize_output(stderr.read())
            exit_code = stdout.channel.recv_exit_status()
        except (socket.timeout, TimeoutError) as exc:
            timed_out = True
            transport_error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            timed_out = _is_timeout_error(exc)
            transport_error = f"{type(exc).__name__}: {exc}"
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)

        return CommandResult(
            command_id=_command_id(),
            target=target,
            command_category=command_category,
            safe_display_command=safe_command,
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            duration_ms=duration_ms,
            connect_timeout_sec=connect_timeout_sec,
            execution_timeout_sec=execution_timeout_sec,
            idle_timeout_sec=idle_timeout_sec,
            timed_out=timed_out,
            idempotent=idempotent,
            privilege_mode=privilege_mode,
            redaction_applied=redacted,
            transport="paramiko",
            transport_error=transport_error,
        )

    def execute_shell(self, target: str, command: str, **kwargs) -> CommandResult:
        return self.execute(
            target,
            command,
            command_category=kwargs.pop("command_category", "shell"),
            **kwargs,
        )

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None


class LocalRunner:
    """Local execution runner that avoids shell=True unless explicitly requested."""

    def __init__(self, security_policy=None):
        self.security_policy = security_policy

    def execute(
        self,
        target: str,
        command: str,
        *,
        command_category: str = "diagnostic",
        connect_timeout_sec: float | None = None,
        execution_timeout_sec: float | None = 30.0,
        idle_timeout_sec: float | None = None,
        idempotent: bool = False,
        privilege_mode: str = "USER",
        display_command: str | None = None,
    ) -> CommandResult:
        if self.security_policy is not None:
            command = self.security_policy.prepare(
                target, command, shell=False, privilege_mode=privilege_mode
            )
        started = time.monotonic()
        safe_command, redacted = _display_command(command, display_command)
        timed_out = False
        transport_error = None
        try:
            argv: Sequence[str] = shlex.split(command)
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=execution_timeout_sec,
                check=False,
            )
            stdout_text = _normalize_output(result.stdout)
            stderr_text = _normalize_output(result.stderr)
            exit_code = result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout_text = _normalize_output(exc.stdout)
            stderr_text = _normalize_output(exc.stderr)
            exit_code = None
            timed_out = True
            transport_error = f"TimeoutExpired: command exceeded {execution_timeout_sec}s"
        except Exception as exc:
            stdout_text = ""
            stderr_text = ""
            exit_code = None
            transport_error = f"{type(exc).__name__}: {exc}"

        return CommandResult(
            command_id=_command_id(),
            target=target,
            command_category=command_category,
            safe_display_command=safe_command,
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            connect_timeout_sec=connect_timeout_sec,
            execution_timeout_sec=execution_timeout_sec,
            idle_timeout_sec=idle_timeout_sec,
            timed_out=timed_out,
            idempotent=idempotent,
            privilege_mode=privilege_mode,
            redaction_applied=redacted,
            transport="local",
            transport_error=transport_error,
        )

    def execute_shell(self, target: str, command: str, **kwargs) -> CommandResult:
        command_category = kwargs.pop("command_category", "shell")
        if self.security_policy is not None:
            command = self.security_policy.prepare(
                target,
                command,
                shell=True,
                privilege_mode=kwargs.get("privilege_mode", "USER"),
            )
        started = time.monotonic()
        execution_timeout_sec = kwargs.get("execution_timeout_sec", 30.0)
        connect_timeout_sec = kwargs.get("connect_timeout_sec")
        idle_timeout_sec = kwargs.get("idle_timeout_sec")
        idempotent = kwargs.get("idempotent", False)
        privilege_mode = kwargs.get("privilege_mode", "USER")
        display_command = kwargs.get("display_command")
        safe_command, redacted = _display_command(command, display_command)
        timed_out = False
        transport_error = None
        try:
            result = subprocess.run(
                ["/bin/sh", "-c", command],
                shell=False,
                capture_output=True,
                text=True,
                timeout=execution_timeout_sec,
                check=False,
            )
            stdout_text = _normalize_output(result.stdout)
            stderr_text = _normalize_output(result.stderr)
            exit_code = result.returncode
        except subprocess.TimeoutExpired as exc:
            stdout_text = _normalize_output(exc.stdout)
            stderr_text = _normalize_output(exc.stderr)
            exit_code = None
            timed_out = True
            transport_error = f"TimeoutExpired: command exceeded {execution_timeout_sec}s"
        except Exception as exc:
            stdout_text = ""
            stderr_text = ""
            exit_code = None
            transport_error = f"{type(exc).__name__}: {exc}"

        return CommandResult(
            command_id=_command_id(),
            target=target,
            command_category=command_category,
            safe_display_command=safe_command,
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            connect_timeout_sec=connect_timeout_sec,
            execution_timeout_sec=execution_timeout_sec,
            idle_timeout_sec=idle_timeout_sec,
            timed_out=timed_out,
            idempotent=idempotent,
            privilege_mode=privilege_mode,
            redaction_applied=redacted,
            transport="local-shell",
            transport_error=transport_error,
        )

    def close(self) -> None:
        return None
