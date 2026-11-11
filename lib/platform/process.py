"""Portable, shell-free direct-child process execution."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from .contracts import PlatformCapabilityError


class ManagedSubprocess:
    """A handle for exactly one child process owned by this executor.

    terminate() intentionally controls only this child. It is not a replacement
    for RunProcessManager's Linux process-group identity and recovery safeguards.
    """

    def __init__(self, process: subprocess.Popen, command: tuple[str, ...]) -> None:
        self._process = process
        self._command = command

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def command(self) -> tuple[str, ...]:
        return self._command

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout=timeout)

    def terminate(self, *, grace_seconds: float = 5.0) -> int:
        if grace_seconds < 0:
            raise ValueError("grace_seconds must be non-negative")
        if self._process.poll() is not None:
            return int(self._process.returncode)
        try:
            self._process.terminate()
        except ProcessLookupError:
            pass
        try:
            return self._process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            self._process.kill()
            return self._process.wait()


class SubprocessExecutor:
    """Start validated argument vectors with shell execution disabled."""

    def start(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ManagedSubprocess:
        if isinstance(command, (str, bytes)):
            raise TypeError("command must be a sequence of arguments, not a shell string")
        args = tuple(command)
        if not args or any(not isinstance(part, str) or not part or "\x00" in part for part in args):
            raise ValueError("command must contain non-empty string arguments without NUL bytes")
        child_env = os.environ.copy()
        for key, value in (env or {}).items():
            if not isinstance(key, str) or not key or "=" in key or "\x00" in key:
                raise ValueError("environment variable names must be valid strings")
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError("environment variable values must be strings without NUL bytes")
            child_env[key] = value

        kwargs = {
            "cwd": str(Path(cwd).expanduser()) if cwd is not None else None,
            "env": child_env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "shell": False,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(args, **kwargs)
        except OSError as exc:
            raise PlatformCapabilityError(
                "unable to start requested process: " + type(exc).__name__
            ) from exc
        return ManagedSubprocess(process, args)
