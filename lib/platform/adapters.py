"""Concrete host adapters selected by platform detection."""
from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import stat
import subprocess
from typing import Callable

from .contracts import (
    PlatformCapabilityError,
    PlatformDescriptor,
    PlatformFamily,
    ProviderAvailability,
    SecretStore,
)
from .detection import describe_platform
from .process import SubprocessExecutor
from .secrets import SecretServiceSecretStore, UnavailableSecretStore, WindowsCredentialManagerSecretStore


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
        target = Path(path).expanduser().absolute()
        # Refuse symlinks in the entire path, not merely the leaf. Checking
        # every existing component prevents a trusted-looking child directory
        # from redirecting private state through a symlinked parent.
        for component in (target, *target.parents):
            try:
                metadata = component.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode):
                raise PlatformCapabilityError("private directory path must not contain a symlink")
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
    """Windows host adapter with native Credential Manager secret storage."""

    def __init__(
        self, descriptor: PlatformDescriptor | None = None, *,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        executable: str | None = None,
    ) -> None:
        self._descriptor = descriptor or describe_platform("Windows")
        self._runner = runner or subprocess.run
        self._executable = executable

    @property
    def descriptor(self) -> PlatformDescriptor:
        return self._descriptor

    def create_process_executor(self) -> SubprocessExecutor:
        return SubprocessExecutor()

    def create_secret_store(self) -> SecretStore:
        return WindowsCredentialManagerSecretStore()

    _ACL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$path = $env:NETREGRESS_PRIVATE_DIRECTORY
if ([string]::IsNullOrWhiteSpace($path)) { throw 'directory path is missing' }
$current = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
if ($null -eq $current) { throw 'current user SID is unavailable' }
if ($env:NETREGRESS_ACL_CREATE -eq '1') {
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($current)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $current,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    [void]$acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $path -AclObject $acl
}
$verified = Get-Acl -LiteralPath $path
$ownerSid = $verified.Owner
try { $ownerSid = ([System.Security.Principal.NTAccount]$verified.Owner).Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $ownerSid = [string]$verified.Owner }
$rules = @($verified.Access | ForEach-Object {
    $sid = $_.IdentityReference
    try { $sid = $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { $sid = [string]$_.IdentityReference }
    @{
        sid = [string]$sid
        allow = ($_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow)
        full_control = ($_.FileSystemRights -eq [System.Security.AccessControl.FileSystemRights]::FullControl)
        inherited = [bool]$_.IsInherited
    }
})
@{ owner = [string]$ownerSid; current_sid = [string]$current.Value; protected = [bool]$verified.AreAccessRulesProtected; rules = $rules } | ConvertTo-Json -Compress -Depth 4
"""

    def ensure_private_directory(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        if target.is_symlink():
            raise PlatformCapabilityError("Windows private directory must not be a symbolic link")
        existed = target.exists()
        if existed and not target.is_dir():
            raise PlatformCapabilityError("Windows private directory path exists but is not a directory")
        created = False
        try:
            if not existed:
                try:
                    target.mkdir(parents=True, exist_ok=False)
                    created = True
                except FileExistsError:
                    # A concurrent creator wins; verify its ACL rather than replacing it.
                    created = False
            if target.is_symlink() or not target.is_dir():
                raise PlatformCapabilityError("Windows private directory must be a real directory")
            try:
                attributes = getattr(target.lstat(), "st_file_attributes", 0)
            except OSError as exc:
                raise PlatformCapabilityError("Windows private directory could not be inspected safely") from exc
            if attributes & 0x400:
                raise PlatformCapabilityError("Windows private directory must not be a reparse point")
            executable = self._executable or shutil.which("powershell.exe") or shutil.which("powershell")
            if not executable:
                raise PlatformCapabilityError("Windows ACL verification requires Windows PowerShell; refusing private state access")
            environment = os.environ.copy()
            environment["NETREGRESS_PRIVATE_DIRECTORY"] = str(target.resolve(strict=True))
            environment["NETREGRESS_ACL_CREATE"] = "1" if created else "0"
            try:
                result = self._runner(
                    [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", self._ACL_SCRIPT],
                    capture_output=True, text=True, timeout=15, check=False, env=environment,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise PlatformCapabilityError("Windows ACL verification could not be executed safely") from exc
            if result.returncode != 0:
                raise PlatformCapabilityError("Windows ACL verification failed; refusing private state access")
            try:
                payload = json.loads(result.stdout)
            except (TypeError, ValueError) as exc:
                raise PlatformCapabilityError("Windows ACL verification returned an invalid result") from exc
            rules = payload.get("rules") if isinstance(payload, dict) else None
            if (
                payload.get("owner") != payload.get("current_sid")
                or not payload.get("protected")
                or not isinstance(rules, list)
                or len(rules) != 1
                or rules[0].get("sid") != payload.get("current_sid")
                or rules[0].get("allow") is not True
                or rules[0].get("full_control") is not True
                or rules[0].get("inherited") is not False
            ):
                raise PlatformCapabilityError("Windows directory ACL is not private to the current user; refusing access")
            return target.resolve(strict=True)
        except Exception:
            if created:
                try:
                    target.rmdir()
                except OSError:
                    pass
            raise

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
