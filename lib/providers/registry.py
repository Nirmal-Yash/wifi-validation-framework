"""Explicit provider adapter registration and capability resolution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .contracts import (
    ProviderCapability, ProviderCapabilityError, ProviderContractError,
    ProviderDescriptor, ProviderNotRegisteredError, ProviderRegistryError,
)

DEFAULT_CAPABILITIES = (
    ProviderCapability("connection.health.read", "Check provider health", "Perform a bounded, authenticated read-only health check."),
    ProviderCapability("controller.version.read", "Read controller version", "Read controller version and declared API metadata."),
    ProviderCapability("labs.create", "Create provider labs", "Create a provider workspace after explicit approval.", True, True),
    ProviderCapability("labs.delete", "Delete provider labs", "Delete a provider workspace after explicit destructive confirmation.", True, True),
    ProviderCapability("packet_capture.supported", "Report packet-capture support", "Report provider packet-capture capability; individual links may impose additional constraints."),
    ProviderCapability("projects.read", "List provider projects", "Discover projects visible to the configured provider credential."),
    ProviderCapability("resources.availability.read", "Read provider compute availability", "Read compute connectivity and reported CPU/RAM utilization without reserving resources."),
    ProviderCapability("templates.images.read", "Check template image availability", "Compare declared template image requirements with the selected compute image catalogue."),
    ProviderCapability("templates.read", "List provider templates", "Discover available node templates without creating resources."),
    ProviderCapability("topology.interfaces.read", "Read node interfaces", "Discover interfaces, adapter numbers and ports exposed by an observed node."),
    ProviderCapability("topology.links.create", "Create topology links", "Create links between observed provider nodes and ports.", True, True),
    ProviderCapability("topology.links.delete", "Delete topology links", "Delete an existing provider link after explicit confirmation.", True, True),
    ProviderCapability("topology.links.read", "Read topology links", "Observe provider link inventory and actual endpoints."),
    ProviderCapability("topology.nodes.create", "Create topology nodes", "Create nodes from an explicitly mapped provider template.", True, True),
    ProviderCapability("topology.nodes.delete", "Delete topology nodes", "Delete an existing provider node after explicit confirmation.", True, True),
    ProviderCapability("topology.nodes.read", "Read topology nodes", "Observe provider node inventory and actual node state."),
    ProviderCapability("topology.nodes.start", "Start topology nodes", "Explicitly start a mapped node and verify observed state.", True, True),
    ProviderCapability("topology.nodes.state.read", "Read topology node state", "Read the provider-observed state of a single node."),
    ProviderCapability("topology.nodes.stop", "Stop topology nodes", "Explicitly stop a mapped node and verify observed state.", True, True),
    ProviderCapability("topology.observed.read", "Read observed topology", "Retrieve the provider's actual node and link inventory."),
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
        "connect", "disconnect", "health_check", "get_capabilities", "version",
        "list_projects", "create_lab", "delete_lab", "list_templates", "list_nodes",
        "list_links", "create_node", "delete_node", "start_node", "stop_node",
        "get_node_state", "create_link", "delete_link", "get_interfaces",
        "get_observed_topology", "capture_support", "get_resource_availability",
        "get_template_image_availability",
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

    @classmethod
    def with_cml(
        cls, *, gns3_factory: Callable[..., Any] | None = None,
        cml_factory: Callable[..., Any] | None = None,
    ) -> "ProviderRegistry":
        """Register the GNS3 reference adapter and Cisco Modeling Labs."""
        if gns3_factory is None:
            from lib.services.gns3_provider import GNS3Provider
            gns3_factory = GNS3Provider
        if cml_factory is None:
            from .cml import CMLProvider
            cml_factory = CMLProvider
        registry = cls.with_gns3(gns3_factory)
        registry.register(
            ProviderDescriptor(
                provider_id="cml", name="Cisco Modeling Labs",
                description="Cisco Modeling Labs REST adapter with server-reported node definitions, image definitions, licensing and compute observations.",
                capability_ids=tuple(
                    item.capability_id for item in DEFAULT_CAPABILITIES
                    if item.capability_id != "packet_capture.supported"
                ),
            ),
            cml_factory,
        )
        return registry

    @classmethod
    def with_stage_b(
        cls, *, gns3_factory: Callable[..., Any] | None = None,
        cml_factory: Callable[..., Any] | None = None,
        eve_ng_factory: Callable[..., Any] | None = None,
    ) -> "ProviderRegistry":
        """Register GNS3, CML and EVE-NG as independent Stage B adapters."""
        if eve_ng_factory is None:
            from .eve_ng import EVENGProvider
            eve_ng_factory = EVENGProvider
        registry = cls.with_cml(gns3_factory=gns3_factory, cml_factory=cml_factory)
        registry.register(
            ProviderDescriptor(
                provider_id="eve-ng", name="EVE-NG",
                description="EVE-NG REST adapter using native .unl paths, JSend responses and observed Ethernet/serial interfaces; serial link creation and packet capture are not advertised.",
                capability_ids=tuple(
                    item.capability_id for item in DEFAULT_CAPABILITIES
                    if item.capability_id != "packet_capture.supported"
                ),
            ),
            eve_ng_factory,
        )
        return registry
