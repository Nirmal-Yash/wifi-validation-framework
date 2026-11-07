from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
from .command_runner import CommandResult


class LabControllerError(RuntimeError):
    """A lab preflight or compatibility operation failed."""


@dataclass(frozen=True, slots=True)
class LabOperationResult:
    operation: str
    result: CommandResult


class LabController:
    """Safe boundary around the established provisioning shell interface.

    The controller validates the launcher before any Run is prepared. It does
    not provision or clean the physical lab implicitly.
    """

    def __init__(self, *, command_runner, provisioning_script, lab_id):
        if not isinstance(lab_id, str) or not lab_id.strip():
            raise ValueError("lab_id must be a non-empty string")
        self.command_runner = command_runner
        self.provisioning_script = Path(provisioning_script).expanduser().resolve()
        self.lab_id = lab_id

    def validate_launcher(self):
        if not self.provisioning_script.is_file():
            raise LabControllerError(
                f"provisioning script not found: {self.provisioning_script}"
            )
        if not self.provisioning_script.stat().st_mode & 0o111:
            raise LabControllerError("provisioning launcher is not executable")
        return self.provisioning_script

    def provision(self, *args, timeout: float = 300.0):
        return self._run("provision", *args, timeout=timeout)

    def cleanup(self, *args, timeout: float = 120.0):
        return self._run("cleanup", *args, timeout=timeout)

    def _run(self, operation, *args, timeout):
        if operation not in {"provision", "cleanup"}:
            raise LabControllerError(f"unsupported lab operation: {operation}")
        try:
            timeout = float(timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("lab operation timeout must be a positive number") from exc
        if not 0 < timeout < float("inf"):
            raise ValueError("lab operation timeout must be finite and positive")

        launcher = self.validate_launcher()
        values = tuple(str(value) for value in args)
        command = " ".join(
            shlex.quote(value)
            for value in ("bash", str(launcher), *values)
        )
        display = " ".join(
            shlex.quote(value)
            for value in ("bash", launcher.name, *values)
        )
        result = self.command_runner.execute_shell(
            "local-lab",
            command,
            command_category=f"lab_{operation}",
            execution_timeout_sec=timeout,
            idempotent=False,
            display_command=display,
        )
        if result.transport_error or result.timed_out:
            raise LabControllerError(
                result.transport_error or f"lab {operation} timed out"
            )
        if result.exit_code is None:
            raise LabControllerError(
                f"lab {operation} returned no exit status; outcome is unknown"
            )
        if result.exit_code != 0:
            raise LabControllerError(
                f"lab {operation} failed with exit code {result.exit_code}"
            )
        return LabOperationResult(operation, result)
