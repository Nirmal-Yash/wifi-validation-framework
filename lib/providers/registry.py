"""Explicit provider adapter registration and capability resolution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .contracts import (
    ProviderCapability, ProviderCapabilityError, ProviderContractError,
    ProviderDescriptor, ProviderNotRegisteredError, ProviderRegistryError,
)

DEFAULT_CAPABILITIES = (
    ProviderCapability("controller.version.read", "Read controller version", "Read controller version and declared API metadata."),
    ProviderCapability("projects.read", "List provider projects", "Discover projects visible to the configured provider credential."),
    ProviderCapability("templates.read", "List provider templates", "Discover available node templates without creating resources."),
    ProviderCapability("topology.links.create", "Create topology links", "Create links between observed provider nodes and ports.", True, True),
    ProviderCapability("topology.links.read", "Read topology links", "Observe provider link inventory and actual endpoints."),
    ProviderCapability("topology.nodes.create", "Create topology nodes", "Create nodes from an explicitly mapped provider template.", True, True),
    ProviderCapability("topology.nodes.read", "Read topology nodes", "Observe provider node inventory and actual node state."),
    ProviderCapability("topology.nodes.start", "Start topology nodes", "Explicitly start a mapped node and verify observed state.", True, True),
    ProviderCapability("topology.nodes.stop", "Stop topology nodes", "Explicitly stop a mapped node and verify observed state.", True, True),
)


@dataclass(frozen=True, slots=True)
class _Registration:
    descriptor: ProviderDescriptor
    factory: Callable[..., Any]


class CapabilityRegistry:
    """Catalogue of stable provider capability IDs."""

    def __init__(self, capabilities: tuple[ProviderCapability, ...] = DEFAULT_CAPABILITIES):
        entries: dict[str, ProviderCapability] = {}
        for item in capabilities:
            if not isinstance(item, ProviderCapability):
                raise TypeError("capabilities must contain ProviderCapability values")
            if item.capability_id in entries:
                raise ValueError("duplicate provider capability: " + item.capability_id)
            entries[item.capability_id] = item
        self._entries = entries

    def get(self, capability_id: str) -> ProviderCapability:
        try:
            return self._entries[capability_id]
        except KeyError as exc:
            raise ProviderCapabilityError("unknown provider capability: " + str(capability_id)) from exc

    def list(self) -> tuple[ProviderCapability, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))


class ProviderRegistry:
    """Application-scoped registry; registrations are not process-global."""

    REQUIRED_METHODS = (
        "version", "list_projects", "list_templates", "list_nodes", "list_links",
        "create_node", "create_link", "start_node", "stop_node",
    )

    def __init__(self, capability_registry: CapabilityRegistry | None = None):
        self.capability_registry = capability_registry or CapabilityRegistry()
        self._registrations: dict[str, _Registration] = {}

    def register(self, descriptor: ProviderDescriptor, factory: Callable[..., Any]) -> None:
        if not isinstance(descriptor, ProviderDescriptor):
            raise TypeError("descriptor must be a ProviderDescriptor")
        if not callable(factory):
            raise TypeError("provider factory must be callable")
        if descriptor.provider_id in self._registrations:
            raise ProviderRegistryError("provider is already registered: " + descriptor.provider_id)
        for capability_id in descriptor.capability_ids:
            self.capability_registry.get(capability_id)
        self._registrations[descriptor.provider_id] = _Registration(descriptor, factory)

    def descriptor(self, provider_id: str) -> ProviderDescriptor:
        registration = self._registrations.get(provider_id)
        if registration is None:
            raise ProviderNotRegisteredError("provider is not registered: " + str(provider_id))
        return registration.descriptor

    def list_descriptors(self) -> list[dict[str, Any]]:
        return [
            self._registrations[key].descriptor.as_dict(self.capability_registry)
            for key in sorted(self._registrations)
        ]

    def capabilities_for(self, provider_id: str) -> tuple[str, ...]:
        return self.descriptor(provider_id).capability_ids

    def require_capability(self, provider_id: str, capability_id: str) -> ProviderCapability:
        descriptor = self.descriptor(provider_id)
        capability = self.capability_registry.get(capability_id)
        if capability_id not in descriptor.capability_ids:
            raise ProviderCapabilityError(
                f"provider '{provider_id}' does not support required capability '{capability_id}'"
            )
        return capability

    def create(self, provider_id: str, *args: Any, **kwargs: Any):
        registration = self._registrations.get(provider_id)
        if registration is None:
            raise ProviderNotRegisteredError("provider is not registered: " + str(provider_id))
        adapter = registration.factory(*args, **kwargs)
        missing = [name for name in self.REQUIRED_METHODS if not callable(getattr(adapter, name, None))]
        if missing:
            raise ProviderContractError(
                f"provider '{provider_id}' adapter is missing contract methods: {', '.join(missing)}"
            )
        return adapter

    @classmethod
    def with_gns3(cls, factory: Callable[..., Any] | None = None) -> "ProviderRegistry":
        """Create the reference registry using the existing GNS3 client."""
        if factory is None:
            from lib.services.gns3_provider import GNS3Provider
            factory = GNS3Provider
        registry = cls()
        registry.register(
            ProviderDescriptor(
                provider_id="gns3", name="GNS3",
                description="Local/private GNS3 Controller adapter for explicit Lab operations.",
                capability_ids=tuple(item.capability_id for item in DEFAULT_CAPABILITIES),
            ),
            factory,
        )
        return registry
