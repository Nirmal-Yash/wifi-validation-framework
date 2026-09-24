from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import uuid
from typing import Any, Mapping, Protocol, Sequence

from lib.domain import ArtifactType, LifecycleEvent
from .command_runner import CommandResult, CommandRunner, NetmikoRunner


_SECRET_ASSIGN_RE = re.compile(
    r"(?i)(\b(?:password|passwd|secret|token|private_key|api_key|psk)\b\s*(?:=|:)\s*)([^\s'\";]+)"
)
_SECRET_FLAG_RE = re.compile(
    r"(?i)(--?(?:password|passwd|secret|token|private[-_]key|api[-_]key|psk)\s+)([^\s'\";]+)"
)
_SECRET_HEADER_RE = re.compile(
    r"(?i)(\b(?:authorization|proxy-authorization)\s*:\s*(?:bearer|basic)\s+)([^\s,;]+)"
)
_SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:token|access_token|password|passwd|secret|api_key|psk)=)([^&\s]+)"
)
_SHELL_META_RE = re.compile(r"(?:\x60|\$\(|\$\{|\r|\n)")
_ALLOWED_REDIRECT_RE = re.compile(r"2>/dev/null|2>&1")
_CHAIN_SPLIT_RE = re.compile(r"\s*(?:;|\|\|)\s*")

DEFAULT_ALLOWED_EXECUTABLES = frozenset(
    {
        "cat", "chmod", "cp", "chronyc", "date", "df", "dhclient", "echo", "getent",
        "grep", "hostname", "id", "iperf3", "ip", "iptables", "iw", "nslookup",
        "pgrep", "ping", "pkill", "printf", "sed", "sha256sum", "stat", "sudo",
        "systemctl", "tc", "test", "timedatectl", "true",
        "uname", "ubus", "whoami", "wpa_cli",
    }
)

DEFAULT_DESTRUCTIVE_PREFIXES = (
    ("dhclient",),
    ("dnsmasq",),
    ("hostapd",),
    ("ip", "link", "set"),
    ("iptables",),
    ("pkill",),
    ("systemctl", "start"),
    ("systemctl", "stop"),
    ("tc", "qdisc"),
    ("wpa_cli", "disable_network"),
    ("wpa_cli", "disconnect"),
    ("wpa_cli", "set_network"),
    ("wpa_cli", "terminate"),
    ("wpa_supplicant",),
)


class CommandSecurityError(PermissionError):
    """Raised when a command violates the execution security policy."""


class CommandAuditError(RuntimeError):
    """Raised when command execution evidence cannot be recorded."""


@dataclass(frozen=True, slots=True)
class CommandSecurityPolicy:
    """Per-target command authorization and shell-safety policy."""

    allowed_executables: frozenset[str] = DEFAULT_ALLOWED_EXECUTABLES
    allowed_executables_by_target: Mapping[str, frozenset[str]] = field(default_factory=dict)
    destructive_prefixes: tuple[tuple[str, ...], ...] = DEFAULT_DESTRUCTIVE_PREFIXES
    destructive_prefixes_by_target: Mapping[str, tuple[tuple[str, ...], ...]] = field(default_factory=dict)
    allow_shell: bool = False
    allow_destructive: bool = False

    @classmethod
    def default(cls) -> "CommandSecurityPolicy":
        return cls()

    @classmethod
    def compatibility(cls) -> "CommandSecurityPolicy":
        """Migration policy for the existing validation suite's explicit shell commands."""
        return cls(allow_shell=True, allow_destructive=True)

    def _allowed_for_target(self, target: str) -> frozenset[str]:
        return self.allowed_executables_by_target.get(target, self.allowed_executables)

    def _destructive_for_target(self, target: str) -> tuple[tuple[str, ...], ...]:
        return self.destructive_prefixes_by_target.get(target, self.destructive_prefixes)

    @staticmethod
    def _strip_privilege(tokens: Sequence[str]) -> list[str]:
        values = list(tokens)
        if values and values[0] == "sudo":
            values = values[1:]
            while values and values[0] in {"-n", "--non-interactive"}:
                values.pop(0)
        return values

    @staticmethod
    def _parse(command: str | Sequence[str], *, shell: bool) -> list[list[str]]:
        if isinstance(command, str):
            if shell:
                if _SHELL_META_RE.search(command):
                    raise CommandSecurityError(
                        "shell command contains command substitution or control characters"
                    )
                scrubbed = _ALLOWED_REDIRECT_RE.sub("", command)
                scrubbed = scrubbed.replace("||", "")
                if any(token in scrubbed for token in ("&&", "|", "<", ">", "&")):
                    raise CommandSecurityError(
                        "unsupported shell operator; only ';' and '||' are allowed"
                    )
                parts = [part for part in _CHAIN_SPLIT_RE.split(command) if part.strip()]
                if not parts:
                    raise CommandSecurityError("shell command is empty")
                parsed: list[list[str]] = []
                for part in parts:
                    tokens = [
                        token
                        for token in shlex.split(part)
                        if token not in {"2>/dev/null", "2>&1"}
                    ]
                    if tokens:
                        parsed.append(tokens)
                return parsed
            if _SHELL_META_RE.search(command) or any(
                token in command for token in (";", "&&", "||", "|", "<", ">", "&")
            ):
                raise CommandSecurityError(
                    "structured command contains shell syntax; use execute_shell() explicitly"
                )
            tokens = shlex.split(command)
            return [tokens] if tokens else []

        tokens = [str(item) for item in command]
        return [tokens] if tokens else []

    def validate(self, target: str, command: str | Sequence[str], *, shell: bool) -> None:
        if shell and not self.allow_shell:
            raise CommandSecurityError("shell execution is disabled by this policy")

        allowed = self._allowed_for_target(target)
        destructive = self._destructive_for_target(target)
        for tokens in self._parse(command, shell=shell):
            canonical = self._strip_privilege(tokens)
            if not canonical:
                raise CommandSecurityError("command is empty after privilege prefix")
            executable = Path(canonical[0]).name
            if executable not in allowed:
                raise CommandSecurityError(
                    f"executable '{executable}' is not allow-listed for target '{target}'"
                )
            is_destructive = any(
                tuple(canonical[: len(prefix)]) == prefix for prefix in destructive
            )
            if is_destructive and not self.allow_destructive:
                raise CommandSecurityError(
                    f"destructive command '{' '.join(canonical[:3])}' is not authorized"
                )

    @staticmethod
    def _normalize_sudo(segment: str, privilege_mode: str) -> str:
        prefix = re.compile(r"^\s*sudo(?:\s+-n)?\s+")
        if prefix.match(segment):
            return prefix.sub("sudo -n ", segment, count=1).strip()
        if privilege_mode.upper() in {"SUDO", "ROOT", "PRIVILEGED"}:
            return f"sudo -n {segment.strip()}"
        return segment.strip()

    def prepare(
        self,
        target: str,
        command: str | Sequence[str],
        *,
        shell: bool,
        privilege_mode: str,
    ) -> str:
        self.validate(target, command, shell=shell)
        if isinstance(command, str):
            if not shell:
                return self._normalize_sudo(
                    shlex.join(shlex.split(command)), privilege_mode
                )
            normalized = [
                self._normalize_sudo(part, privilege_mode)
                for part in _CHAIN_SPLIT_RE.split(command)
                if part.strip()
            ]
            return (" ; " if ";" in command else " || ").join(normalized)
        return self._normalize_sudo(
            shlex.join([str(item) for item in command]), privilege_mode
        )


def redact_text(value: str) -> tuple[str, bool]:
    redacted = _SECRET_ASSIGN_RE.sub(r"\1***", value)
    redacted = _SECRET_FLAG_RE.sub(r"\1***", redacted)
    redacted = _SECRET_HEADER_RE.sub(r"\1***", redacted)
    redacted = _SECRET_QUERY_RE.sub(r"\1***", redacted)
    return redacted, redacted != value


def redact_command(command: str) -> str:
    return redact_text(command)[0]


def redact_output(output: str) -> str:
    return redact_text(output)[0]


class CommandAuditRecorder:
    """Persist redacted command output and a COMMAND_EXECUTED lifecycle event."""

    def __init__(
        self,
        *,
        artifact_service: Any | None,
        event_repository: Any | None,
        run_id: str,
        attempt_id: str | None,
        directory: str | Path,
        clock=lambda: datetime.now(timezone.utc),
    ):
        self.artifact_service = artifact_service
        self.event_repository = event_repository
        self.run_id = run_id
        self.attempt_id = attempt_id
        self.clock = clock
        self.path = Path(directory) / f"{run_id}.jsonl"
        self._records = 0
        self._closed = False
        self._artifact_registered = False

    def record(self, result: CommandResult) -> None:
        if self._closed:
            raise CommandAuditError("command audit recorder is already closed")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "command_id": result.command_id,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "target": result.target,
            "command_category": result.command_category,
            "safe_display_command": result.safe_display_command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "idempotent": result.idempotent,
            "privilege_mode": result.privilege_mode,
            "redaction_applied": result.redaction_applied,
            "transport": result.transport,
            "transport_error": result.transport_error,
            "occurred_at": self.clock().isoformat(),
        }
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError as exc:
            raise CommandAuditError(f"unable to write command evidence: {exc}") from exc

        self._records += 1
        if self.event_repository is not None:
            try:
                self.event_repository.append(
                    LifecycleEvent(
                        event_id=uuid.uuid4().hex,
                        run_id=self.run_id,
                        attempt_id=self.attempt_id,
                        event_type="COMMAND_EXECUTED",
                        occurred_at=self.clock(),
                        details={
                            "command_id": result.command_id,
                            "target": result.target,
                            "command_category": result.command_category,
                            "safe_display_command": result.safe_display_command,
                            "exit_code": result.exit_code,
                            "timed_out": result.timed_out,
                            "idempotent": result.idempotent,
                            "privilege_mode": result.privilege_mode,
                            "transport": result.transport,
                        },
                    )
                )
            except Exception as exc:
                raise CommandAuditError(
                    f"unable to persist command audit event: {exc}"
                ) from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._records and self.artifact_service is not None and not self._artifact_registered:
            try:
                self.artifact_service.register_file(
                    run_id=self.run_id,
                    path=self.path,
                    artifact_type=ArtifactType.COMMAND_OUTPUT,
                    display_name=f"command-output-{self.run_id}.jsonl",
                    sensitivity_class="SENSITIVE",
                )
            except Exception as exc:
                raise CommandAuditError(
                    f"unable to register command evidence artifact: {exc}"
                ) from exc
            self._artifact_registered = True


class SecureCommandRunner:
    """Security decorator that authorizes, redacts, audits and delegates execution."""

    def __init__(
        self,
        runner: CommandRunner,
        *,
        security_policy: CommandSecurityPolicy | None = None,
        audit_recorder: CommandAuditRecorder | None = None,
    ):
        self.runner = runner
        self.security_policy = security_policy or CommandSecurityPolicy.default()
        self.audit_recorder = audit_recorder

    @staticmethod
    def _redact_result(result: CommandResult, prepared: str) -> CommandResult:
        safe_command, command_redacted = redact_text(prepared)
        stdout, stdout_redacted = redact_text(result.stdout)
        stderr, stderr_redacted = redact_text(result.stderr)
        error = result.transport_error
        error_redacted = False
        if error:
            error, error_redacted = redact_text(error)
        return CommandResult(
            command_id=result.command_id,
            target=result.target,
            command_category=result.command_category,
            safe_display_command=safe_command,
            stdout=stdout,
            stderr=stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            connect_timeout_sec=result.connect_timeout_sec,
            execution_timeout_sec=result.execution_timeout_sec,
            idle_timeout_sec=result.idle_timeout_sec,
            timed_out=result.timed_out,
            idempotent=result.idempotent,
            privilege_mode=result.privilege_mode,
            redaction_applied=(
                result.redaction_applied
                or command_redacted
                or stdout_redacted
                or stderr_redacted
                or error_redacted
            ),
            transport=result.transport,
            transport_error=error,
        )

    def execute(self, target: str, command: str | Sequence[str], **kwargs) -> CommandResult:
        privilege_mode = kwargs.get("privilege_mode", "USER")
        prepared = self.security_policy.prepare(
            target, command, shell=False, privilege_mode=privilege_mode
        )
        result = self.runner.execute(target, prepared, **kwargs)
        secure = self._redact_result(result, prepared)
        if self.audit_recorder is not None:
            self.audit_recorder.record(secure)
        return secure

    def execute_shell(self, target: str, command: str, **kwargs) -> CommandResult:
        privilege_mode = kwargs.get("privilege_mode", "USER")
        prepared = self.security_policy.prepare(
            target, command, shell=True, privilege_mode=privilege_mode
        )
        result = self.runner.execute_shell(target, prepared, **kwargs)
        secure = self._redact_result(result, prepared)
        if self.audit_recorder is not None:
            self.audit_recorder.record(secure)
        return secure

    @property
    def transport(self) -> Any:
        return self.runner

    def close(self) -> None:
        audit_error = None
        if self.audit_recorder is not None:
            try:
                self.audit_recorder.close()
            except Exception as exc:
                audit_error = exc
        try:
            close = getattr(self.runner, "close", None)
            if close is not None:
                close()
        finally:
            if audit_error is not None:
                raise audit_error


class LegacyConnectionPoolAdapter:
    """Compatibility facade routing legacy send_command calls through SecureCommandRunner."""

    def __init__(self, runner: SecureCommandRunner):
        self.command_runner = runner
        transport = runner.transport
        if not isinstance(transport, NetmikoRunner):
            raise TypeError("LegacyConnectionPoolAdapter requires a NetmikoRunner transport")
        self._raw_pool = transport.pool

    def send_command(self, device_name: str, command: str, **kwargs) -> str:
        timeout = kwargs.pop("read_timeout", kwargs.pop("timeout", 30.0))
        result = self.command_runner.execute_shell(
            device_name,
            command,
            command_category=kwargs.pop("command_category", "legacy_shell"),
            execution_timeout_sec=timeout,
            idempotent=kwargs.pop("idempotent", False),
            privilege_mode=kwargs.pop("privilege_mode", "USER"),
            display_command=kwargs.pop("display_command", None),
        )
        if result.transport_error:
            raise RuntimeError(result.transport_error)
        return result.stdout

    def get_connection(self, device_name: str):
        """Protected raw-connection escape hatch used only by the DHCP capture test."""
        return self._raw_pool.get_connection(device_name)

    def send_config_set(self, device_name: str, commands, **kwargs):
        for command in commands:
            self.command_runner.security_policy.validate(
                device_name, str(command), shell=False
            )
        return self._raw_pool.send_config_set(device_name, commands, **kwargs)

    def close_all(self) -> None:
        self.command_runner.close()


def legacy_pool_adapter(runner: SecureCommandRunner) -> LegacyConnectionPoolAdapter:
    return LegacyConnectionPoolAdapter(runner)
