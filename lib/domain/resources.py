"""Product resource entities shared by workspace, lab and provider services."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import uuid


class ResourceValidationError(ValueError):
    """Raised when a persisted product resource violates its domain contract."""


class ResourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


def new_resource_id() -> str:
    """Create a non-guessable, platform-independent resource identifier."""
    return str(uuid.uuid4())


def _required(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ResourceValidationError(f"{field} must be a non-empty string")


def _status(value: ResourceStatus, field: str) -> None:
    if not isinstance(value, ResourceStatus):
        raise ResourceValidationError(f"{field} must be a ResourceStatus")


@dataclass(frozen=True, slots=True)
class Organization:
    organization_id: str
    slug: str
    name: str
    created_at: datetime
    updated_at: datetime
    status: ResourceStatus = ResourceStatus.ACTIVE

    def __post_init__(self) -> None:
        _required(self.organization_id, "organization_id")
        _required(self.slug, "slug")
        _required(self.name, "name")
        _status(self.status, "status")
        if self.updated_at < self.created_at:
            raise ResourceValidationError("organization updated_at cannot precede created_at")


@dataclass(frozen=True, slots=True)
class Project:
    project_id: str
    organization_id: str
    slug: str
    name: str
    created_at: datetime
    updated_at: datetime
    status: ResourceStatus = ResourceStatus.ACTIVE

    def __post_init__(self) -> None:
        _required(self.project_id, "project_id")
        _required(self.organization_id, "organization_id")
        _required(self.slug, "slug")
        _required(self.name, "name")
        _status(self.status, "status")
        if self.updated_at < self.created_at:
            raise ResourceValidationError("project updated_at cannot precede created_at")


@dataclass(frozen=True, slots=True)
class Lab:
    lab_id: str
    project_id: str
    name: str
    provider_id: str
    created_at: datetime
    updated_at: datetime
    topology_version: int = 1
    status: ResourceStatus = ResourceStatus.ACTIVE

    def __post_init__(self) -> None:
        _required(self.lab_id, "lab_id")
        _required(self.project_id, "project_id")
        _required(self.name, "name")
        _required(self.provider_id, "provider_id")
        _status(self.status, "status")
        if self.updated_at < self.created_at:
            raise ResourceValidationError("lab updated_at cannot precede created_at")
        if isinstance(self.topology_version, bool) or not isinstance(self.topology_version, int) or self.topology_version < 1:
            raise ResourceValidationError("topology_version must be a positive integer")
