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


class _WindowsCredential:
    """Minimal ctypes representation of the Windows generic credential record."""

    # Structure is defined lazily by the native API wrapper on Windows.
    pass


class _WindowsCredentialManagerApi:
    """Thin Win32 Credential Manager binding; callers never place secrets in argv."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        if os.name != "nt":
            raise SecretStoreError(
                "Windows Credential Manager is available only on Windows hosts."
            )

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self.ctypes = ctypes
        self.credential_type = CREDENTIALW
        self.advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        self.advapi.CredWriteW.restype = wintypes.BOOL
        self.advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
        ]
        self.advapi.CredReadW.restype = wintypes.BOOL
        self.advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.advapi.CredDeleteW.restype = wintypes.BOOL
        self.advapi.CredFree.argtypes = [ctypes.c_void_p]
        self.advapi.CredFree.restype = None

    def write(self, target: str, secret: str) -> None:
        ctypes = self.ctypes
        encoded = secret.encode("utf-8")
        blob = ctypes.create_string_buffer(encoded, len(encoded))
        record = self.credential_type()
        record.Type = self.CRED_TYPE_GENERIC
        record.TargetName = target
        record.Comment = "NetRegress managed credential"
        record.CredentialBlobSize = len(encoded)
        record.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        record.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        record.UserName = "NetRegress"
        if not self.advapi.CredWriteW(ctypes.byref(record), 0):
            code = ctypes.get_last_error()
            raise OSError(code, "CredWriteW failed")

    def read(self, target: str) -> str | None:
        ctypes = self.ctypes
        record = ctypes.POINTER(self.credential_type)()
        if not self.advapi.CredReadW(
            target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(record)
        ):
            code = ctypes.get_last_error()
            if code == self.ERROR_NOT_FOUND:
                return None
            raise OSError(code, "CredReadW failed")
        try:
            raw = ctypes.string_at(record.contents.CredentialBlob, record.contents.CredentialBlobSize)
            return raw.decode("utf-8")
        finally:
            self.advapi.CredFree(record)

    def delete(self, target: str) -> bool:
        if self.advapi.CredDeleteW(target, self.CRED_TYPE_GENERIC, 0):
            return True
        code = self.ctypes.get_last_error()
        if code == self.ERROR_NOT_FOUND:
            return False
        raise OSError(code, "CredDeleteW failed")


class WindowsCredentialManagerSecretStore:
    """Windows Credential Manager provider for generic UTF-8 secrets.

    The OS associates entries with the current Windows user. Only opaque
    references are intended to be persisted by application repositories.
    """

    MAX_SECRET_BYTES = 2560
    TARGET_PREFIX = "NetRegress/"

    def __init__(self, *, api=None) -> None:
        self._api = api if api is not None else _WindowsCredentialManagerApi()

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise ValueError("secret name must be 1-128 safe identifier characters")
        return name

    def _target(self, name: str) -> str:
        return self.TARGET_PREFIX + self._validate_name(name)

    def set(self, name: str, secret: str) -> None:
        target = self._target(name)
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret must be a non-empty string")
        if len(secret.encode("utf-8")) > self.MAX_SECRET_BYTES:
            raise ValueError("secret exceeds the Windows Credential Manager generic credential limit")
        try:
            self._api.write(target, secret)
        except Exception as exc:
            raise SecretStoreError(
                "Windows Credential Manager could not store the credential: " + type(exc).__name__
            ) from exc

    def get(self, name: str) -> str | None:
        target = self._target(name)
        try:
            return self._api.read(target)
        except Exception as exc:
            raise SecretStoreError(
                "Windows Credential Manager could not retrieve the credential: " + type(exc).__name__
            ) from exc

    def delete(self, name: str) -> bool:
        target = self._target(name)
        try:
            return bool(self._api.delete(target))
        except Exception as exc:
            raise SecretStoreError(
                "Windows Credential Manager could not delete the credential: " + type(exc).__name__
            ) from exc
