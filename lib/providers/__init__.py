"""Shared provider adapter contracts, capability metadata and registry."""
from .contracts import (
    ProviderAdapter, ProviderCapability, ProviderCapabilityError,
    ProviderConnectionRecord, ProviderContractError, ProviderDescriptor,
    ProviderNotRegisteredError, ProviderRegistryError,
)
from .registry import CapabilityRegistry, DEFAULT_CAPABILITIES, ProviderRegistry
from .session import ProviderSessionError, ProviderSessionService
from .cml import CMLProvider, CMLProviderError
from .http import ProviderHTTPError, validate_provider_endpoint

__all__ = (
    "ProviderAdapter", "ProviderCapability", "ProviderCapabilityError",
    "ProviderConnectionRecord", "ProviderContractError", "ProviderDescriptor",
    "ProviderNotRegisteredError", "ProviderRegistryError", "CapabilityRegistry",
    "DEFAULT_CAPABILITIES", "ProviderRegistry", "ProviderSessionError", "ProviderSessionService",
    "CMLProvider", "CMLProviderError",
    "ProviderHTTPError", "validate_provider_endpoint",
)
