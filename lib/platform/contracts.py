"""Cross-platform contracts for the NetRegress product runtime.

These contracts describe platform facilities without claiming that existing
Linux Runner workflows are already portable. The legacy Runner remains the
behavioral authority until a later migration explicitly adopts these adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol, Sequence


class PlatformCapabilityError(RuntimeError):
    """Raised when an operation is unavailable or not safely implemented."""


class SecretStoreError(PlatformCapabilityError):
    """Raised when secure credential storage cannot be guaranteed."""


class PlatformFamily(str, Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    """Host facilities, not a statement of complete NetRegress support."""

    procfs_process_identity: bool = False
    sysfs_network_interfaces: bool = False
    native_hwsim_kernel: bool = False
    systemd_services: bool = False
    unix_permission_bits: bool = False
    windows_process_groups: bool = False


@dataclass(frozen=True, slots=True)
class PlatformDescriptor:
    family: PlatformFamily
    system: str
    release: str
    machine: str
    python_version: str
    capabilities: PlatformCapabilities


@dataclass(frozen=True, slots=True)
class ProviderAvailability:
    provider_id: str
    available: bool
    executable: str | None = None
    reason: str = ""


class ManagedProcess(Protocol):
    """Handle for a process started by a ProcessExecutor."""

    @property
    def pid(self) -> int: ...
    @property
    def command(self) -> tuple[str, ...]: ...
    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self, *, grace_seconds: float = 5.0) -> int: ...


class ProcessExecutor(Protocol):
    """Argument-vector process execution; shell execution is intentionally absent."""

    def start(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ManagedProcess: ...


class SecretStore(Protocol):
    """OS-backed secret storage. Implementations must not put secret values in argv."""

    def set(self, name: str, secret: str) -> None: ...
    def get(self, name: str) -> str | None: ...
    def delete(self, name: str) -> bool: ...


class PlatformAdapter(Protocol):
    @property
    def descriptor(self) -> PlatformDescriptor: ...
    def create_process_executor(self) -> ProcessExecutor: ...
    def create_secret_store(self) -> SecretStore: ...
    def ensure_private_directory(self, path: str | Path) -> Path: ...
    def provider_availability(
        self, provider_id: str, executable: str | None = None
    ) -> ProviderAvailability: ...


class ProviderAdapter(Protocol):
    """Contract for a lab provider; topology policy stays outside the provider."""

    @property
    def provider_id(self) -> str: ...
    def availability(self) -> ProviderAvailability: ...
