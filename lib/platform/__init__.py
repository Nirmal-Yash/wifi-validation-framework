"""Platform abstractions for the NetRegress desktop/runtime architecture."""
from .adapters import (
    LinuxPlatformAdapter,
    UnsupportedPlatformAdapter,
    WindowsPlatformAdapter,
    platform_adapter_for,
)
from .contracts import (
    PlatformAdapter,
    PlatformCapabilities,
    PlatformCapabilityError,
    PlatformDescriptor,
    PlatformFamily,
    ProcessExecutor,
    ProviderAdapter,
    ProviderAvailability,
    SecretStore,
    SecretStoreError,
)
from .detection import describe_platform, platform_family_for
from .paths import ApplicationPaths, resolve_application_paths
from .process import ManagedSubprocess, SubprocessExecutor
from .secrets import SecretServiceSecretStore, UnavailableSecretStore

__all__ = [
    "ApplicationPaths",
    "LinuxPlatformAdapter",
    "ManagedSubprocess",
    "PlatformAdapter",
    "PlatformCapabilities",
    "PlatformCapabilityError",
    "PlatformDescriptor",
    "PlatformFamily",
    "ProcessExecutor",
    "ProviderAdapter",
    "ProviderAvailability",
    "SecretServiceSecretStore",
    "SecretStore",
    "SecretStoreError",
    "SubprocessExecutor",
    "UnsupportedPlatformAdapter",
    "UnavailableSecretStore",
    "WindowsPlatformAdapter",
    "describe_platform",
    "platform_adapter_for",
    "platform_family_for",
    "resolve_application_paths",
]
