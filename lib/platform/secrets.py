"""Secret Service-backed credentials and explicit fail-closed placeholders."""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable, Sequence

from .contracts import SecretStoreError


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SecretServiceSecretStore:
    """Linux Secret Service adapter using secret-tool without argv secrets."""

    def __init__(
        self,
        *,
        executable: str = "secret-tool",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.executable = executable
        self.runner = runner
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError("secret name must be 1-128 safe identifier characters")
        return name

    def _run(self, args: Sequence[str], *, secret: str | None = None):
        if shutil.which(self.executable) is None:
            raise SecretStoreError(
                "Linux Secret Service is unavailable: install secret-tool and configure a Secret Service provider"
            )
        try:
            result = self.runner(
                [self.executable, *args],
                input=secret,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretStoreError(
                "Linux Secret Service request failed: " + type(exc).__name__
            ) from exc
        return result

    def set(self, name: str, secret: str) -> None:
        safe_name = self._validate_name(name)
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret must be a non-empty string")
        result = self._run(
            ["store", "--label=NetRegress credential", "application", "netregress", "name", safe_name],
            secret=secret,
        )
        if result.returncode != 0:
            raise SecretStoreError("Secret Service refused to store the credential")

    def get(self, name: str) -> str | None:
        safe_name = self._validate_name(name)
        result = self._run(["lookup", "application", "netregress", "name", safe_name])
        if result.returncode == 1:
            return None
        if result.returncode != 0:
            raise SecretStoreError("Secret Service could not retrieve the credential")
        # secret-tool writes a presentation newline after the stored value.
        return result.stdout[:-1] if result.stdout.endswith("\n") else result.stdout

    def delete(self, name: str) -> bool:
        safe_name = self._validate_name(name)
        result = self._run(["clear", "application", "netregress", "name", safe_name])
        if result.returncode == 1:
            return False
        if result.returncode != 0:
            raise SecretStoreError("Secret Service could not delete the credential")
        return True


class UnavailableSecretStore:
    """A deliberate placeholder where a secure OS adapter is not yet shipped."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _raise(self):
        raise SecretStoreError(self.reason)

    def set(self, name: str, secret: str) -> None:
        self._raise()

    def get(self, name: str) -> str | None:
        self._raise()

    def delete(self, name: str) -> bool:
        self._raise()
