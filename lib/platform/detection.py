"""Host platform identification and explicit capability reporting."""
from __future__ import annotations

import platform
import sys

from .contracts import PlatformCapabilities, PlatformDescriptor, PlatformFamily


def platform_family_for(system: str | None = None) -> PlatformFamily:
    value = (system or platform.system()).strip().lower()
    if value in {"linux"}:
        return PlatformFamily.LINUX
    if value in {"windows", "win32", "cygwin"}:
        return PlatformFamily.WINDOWS
    if value in {"darwin", "mac", "macos"}:
        return PlatformFamily.MACOS
    return PlatformFamily.OTHER


def describe_platform(
    system: str | None = None,
    *,
    release: str | None = None,
    machine: str | None = None,
    python_version: str | None = None,
) -> PlatformDescriptor:
    """Return host facts without probing or changing the host."""
    detected_system = system or platform.system()
    family = platform_family_for(detected_system)
    capabilities = PlatformCapabilities(
        procfs_process_identity=family is PlatformFamily.LINUX,
        sysfs_network_interfaces=family is PlatformFamily.LINUX,
        native_hwsim_kernel=family is PlatformFamily.LINUX,
        systemd_services=family is PlatformFamily.LINUX,
        unix_permission_bits=family in {PlatformFamily.LINUX, PlatformFamily.MACOS},
        windows_process_groups=family is PlatformFamily.WINDOWS,
    )
    return PlatformDescriptor(
        family=family,
        system=detected_system,
        release=release if release is not None else platform.release(),
        machine=machine if machine is not None else platform.machine(),
        python_version=python_version if python_version is not None else sys.version.split()[0],
        capabilities=capabilities,
    )
