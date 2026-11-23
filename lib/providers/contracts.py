"""Provider-neutral adapter contracts and durable connection projections."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Protocol, runtime_checkable

_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_PROVIDER_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


class ProviderRegistryError(RuntimeError):
    """Base class for provider registration and lookup failures."""


class ProviderNotRegisteredError(ProviderRegistryError):
    """The requested provider has not been registered."""


class ProviderCapabilityError(ProviderRegistryError):
    """The selected provider does not advertise a required capability."""


class ProviderContractError(ProviderRegistryError):
    """An adapter does not implement the shared provider contract."""


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    capability_id: str
    name: str
    description: str
    mutates_state: bool = False
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not _CAPABILITY_ID.fullmatch(self.capability_id):
            raise ValueError("capability_id must be a stable lowercase identifier")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError("capability name must contain 1 to 100 characters")
        if not isinstance(self.description, str) or not self.description.strip() or len(self.description) > 500:
            raise ValueError("capability description must contain 1 to 500 characters")
        if self.requires_confirmation and not self.mutates_state:
            raise ValueError("read-only capabilities cannot require mutation confirmation")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.capability_id, "name": self.name, "description": self.description,
            "mutates_state": self.mutates_state, "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    provider_id: str
    name: str
    description: str
    capability_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not _PROVIDER_ID.fullmatch(self.provider_id):
            raise ValueError("provider_id must be a stable lowercase provider identifier")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError("provider name must contain 1 to 100 characters")
        if not isinstance(self.description, str) or not self.description.strip() or len(self.description) > 500:
            raise ValueError("provider description must contain 1 to 500 characters")
        if not isinstance(self.capability_ids, tuple) or len(set(self.capability_ids)) != len(self.capability_ids):
            raise ValueError("provider capability_ids must be a tuple of unique identifiers")
        if any(not isinstance(item, str) or not _CAPABILITY_ID.fullmatch(item) for item in self.capability_ids):
            raise ValueError("provider capability_ids contains an invalid identifier")

    def as_dict(self, registry: "CapabilityRegistry") -> dict[str, Any]:
        return {
            "provider_id": self.provider_id, "name": self.name, "description": self.description,
            "capabilities": [registry.get(item).as_dict() for item in self.capability_ids],
        }


@dataclass(frozen=True, slots=True)
class ProviderConnectionRecord:
    """Safe projection of a persisted Project/Lab binding; never contains credential material."""

    connection_id: str
    provider_id: str
    project_id: str
    lab_id: str
    endpoint_url: str
    provider_workspace_id: str
    controller_device_id: str
    credential_reference_id: str
    status: str
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str

    @classmethod
    def from_binding(cls, binding: Mapping[str, Any]) -> "ProviderConnectionRecord":
        if not isinstance(binding, Mapping):
            raise ValueError("provider binding must be a mapping")
        workspace_id = binding.get("provider_workspace_id") or binding.get("gns3_project_id")
        provider_id = binding.get("provider_id") or "gns3"
        required = (
            "binding_id", "project_id", "lab_id", "endpoint_url",
            "controller_device_id", "credential_id", "status", "created_at",
            "updated_at", "created_by", "updated_by",
        )
        missing = [key for key in required if not isinstance(binding.get(key), str) or not binding[key]]
        if not isinstance(workspace_id, str) or not workspace_id:
            missing.append("provider_workspace_id")
        if not isinstance(provider_id, str) or not provider_id:
            missing.append("provider_id")
        if missing:
            raise ValueError("provider binding is missing required fields: " + ", ".join(missing))
        return cls(
            connection_id=binding["binding_id"], provider_id=provider_id,
            project_id=binding["project_id"], lab_id=binding["lab_id"],
            endpoint_url=binding["endpoint_url"], provider_workspace_id=workspace_id,
            controller_device_id=binding["controller_device_id"],
            credential_reference_id=binding["credential_id"], status=binding["status"],
            created_at=binding["created_at"], updated_at=binding["updated_at"],
            created_by=binding["created_by"], updated_by=binding["updated_by"],
        )

    @classmethod
    def from_gns3_binding(cls, binding: Mapping[str, Any]) -> "ProviderConnectionRecord":
        """Compatibility alias for historical GNS3 binding callers."""
        return cls.from_binding(binding)

    def as_dict(self) -> dict[str, str]:
        return {
            "connection_id": self.connection_id, "provider_id": self.provider_id,
            "project_id": self.project_id, "lab_id": self.lab_id,
            "endpoint_url": self.endpoint_url, "provider_workspace_id": self.provider_workspace_id,
            "controller_device_id": self.controller_device_id,
            "credential_reference_id": self.credential_reference_id, "status": self.status,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "created_by": self.created_by, "updated_by": self.updated_by,
        }


@runtime_checkable
class ProviderAdapter(Protocol):
    """Complete typed lifecycle contract implemented by topology/emulator adapters.

    Providers may implement operations with different native semantics. An adapter
    must still expose every method and fail with a typed capability error when a
    declared operation is not supported; it must never silently emulate success.
    """

    def connect(self) -> dict: ...
    def disconnect(self) -> None: ...
    def health_check(self) -> dict: ...
    def get_capabilities(self) -> list[dict]: ...
    def version(self) -> dict: ...
    def list_projects(self) -> list[dict]: ...
    def create_lab(self, name: str, *, scene_width: int = 1600, scene_height: int = 900) -> dict: ...
    def delete_lab(self, project_id: str) -> dict: ...
    def list_templates(self) -> list[dict]: ...
    def list_nodes(self, project_id: str) -> list[dict]: ...
    def list_links(self, project_id: str) -> list[dict]: ...
    def create_node(self, project_id: str, template_id: str, *, name: str, x: float, y: float) -> dict: ...
    def delete_node(self, project_id: str, node_id: str) -> dict: ...
    def start_node(self, project_id: str, node_id: str) -> Any: ...
    def stop_node(self, project_id: str, node_id: str) -> Any: ...
    def get_node_state(self, project_id: str, node_id: str) -> dict: ...
    def create_link(
        self, project_id: str, *, source_node_id: str, source_adapter: int,
        source_port: int, target_node_id: str, target_adapter: int, target_port: int,
    ) -> dict: ...
    def delete_link(self, project_id: str, link_id: str) -> dict: ...
    def get_interfaces(self, project_id: str, node_id: str) -> list[dict]: ...
    def get_observed_topology(self, project_id: str) -> dict: ...
    def capture_support(self) -> dict: ...
    def get_resource_availability(self) -> dict: ...
    def get_template_image_availability(self, template_id: str) -> dict: ...
