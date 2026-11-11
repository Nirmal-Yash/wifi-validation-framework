"""Concrete host adapters selected by platform detection."""
from __future__ import annotations

from pathlib import Path
import shutil
import stat

from .contracts import (
    PlatformCapabilityError,
    PlatformDescriptor,
    PlatformFamily,
    ProviderAvailability,
    SecretStore,
)
from .detection import describe_platform
from .process import SubprocessExecutor
from .secrets import SecretServiceSecretStore, UnavailableSecretStore


class LinuxPlatformAdapter:
    def __init__(self, descriptor: PlatformDescriptor | None = None) -> None:
        self._descriptor = descriptor or describe_platform("Linux")

    @property
    def descriptor(self) -> PlatformDescriptor:
        return self._descriptor

    def create_process_executor(self) -> SubprocessExecutor:
        return SubprocessExecutor()

    def create_secret_store(self) -> SecretStore:
        return SecretServiceSecretStore()

    def ensure_private_directory(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        if target.is_symlink():
            raise PlatformCapabilityError("private directory must not be a symlink")
        existed = target.exists()
        if existed and not target.is_dir():
            raise PlatformCapabilityError("private directory path exists but is not a directory")
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        mode = stat.S_IMODE(target.stat().st_mode)
        if existed and mode & 0o077:
            raise PlatformCapabilityError(
                "existing private directory has group or world permissions; restrict it before use"
            )
        if not existed:
            target.chmod(0o700)
        return target.resolve(strict=False)

    def provider_availability(
        self, provider_id: str, executable: str | None = None
    ) -> ProviderAvailability:
        provider = provider_id.strip().lower()
        if provider == "hwsim":
            available = Path("/sys/module/mac80211_hwsim").exists()
            return ProviderAvailability(
                provider_id=provider,
                available=available,
                reason="Linux mac80211_hwsim kernel module detected" if available else "mac80211_hwsim kernel module is not loaded",
            )
        if not executable:
            return ProviderAvailability(provider, False, reason="No provider executable was configured")
        resolved = shutil.which(executable)
        return ProviderAvailability(
            provider_id=provider,
            available=resolved is not None,
            executable=resolved,
            reason="Executable found" if resolved else "Executable is not on PATH",
        )


class WindowsPlatformAdapter:
    """Windows host adapter; ACL and Credential Manager integration are pending."""

    def __init__(self, descriptor: PlatformDescriptor | None = None) -> None:
        self._descriptor = descriptor or describe_platform("Windows")

    @property
    def descriptor(self) -> PlatformDescriptor:
        return self._descriptor

    def create_process_executor(self) -> SubprocessExecutor:
        return SubprocessExecutor()

    def create_secret_store(self) -> SecretStore:
        return UnavailableSecretStore(
            "Windows Credential Manager integration is not implemented; credential operations are disabled."
        )

    def ensure_private_directory(self, path: str | Path) -> Path:
        raise PlatformCapabilityError(
            "Windows private-directory ACL verification is not implemented; refusing to create a credential or state directory."
        )

    def provider_availability(
        self, provider_id: str, executable: str | None = None
    ) -> ProviderAvailability:
        provider = provider_id.strip().lower()
        if provider == "hwsim":
            return ProviderAvailability(
                provider_id=provider,
                available=False,
                reason="mac80211_hwsim is a Linux kernel facility; use a Linux Runner or remote lab provider.",
            )
        resolved = shutil.which(executable) if executable else None
        return ProviderAvailability(
            provider_id=provider,
            available=resolved is not None,
            executable=resolved,
            reason="Executable found" if resolved else "Provider executable is unavailable or not configured",
        )


class UnsupportedPlatformAdapter:
    def __init__(self, descriptor: PlatformDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> PlatformDescriptor:
        return self._descriptor

    def create_process_executor(self) -> SubprocessExecutor:
        return SubprocessExecutor()

    def create_secret_store(self) -> SecretStore:
        return UnavailableSecretStore("No secure secret-store adapter exists for this operating system.")

    def ensure_private_directory(self, path: str | Path) -> Path:
        raise PlatformCapabilityError("Private-directory permission enforcement is not implemented for this operating system.")

    def provider_availability(self, provider_id: str, executable: str | None = None) -> ProviderAvailability:
        return ProviderAvailability(provider_id, False, reason="No provider adapter is implemented for this operating system.")


def platform_adapter_for(
    descriptor: PlatformDescriptor | None = None,
) -> LinuxPlatformAdapter | WindowsPlatformAdapter | UnsupportedPlatformAdapter:
    detected = descriptor or describe_platform()
    if detected.family is PlatformFamily.LINUX:
        return LinuxPlatformAdapter(detected)
    if detected.family is PlatformFamily.WINDOWS:
        return WindowsPlatformAdapter(detected)
    return UnsupportedPlatformAdapter(detected)
