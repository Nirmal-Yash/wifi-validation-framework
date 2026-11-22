"""Shared provider adapter contracts, capability metadata and registry."""
from .contracts import (
    ProviderAdapter, ProviderCapability, ProviderCapabilityError,
    ProviderConnectionRecord, ProviderContractError, ProviderDescriptor,
    ProviderNotRegisteredError, ProviderRegistryError,
)
from .registry import CapabilityRegistry, DEFAULT_CAPABILITIES, ProviderRegistry

__all__ = (
    "ProviderAdapter", "ProviderCapability", "ProviderCapabilityError",
    "ProviderConnectionRecord", "ProviderContractError", "ProviderDescriptor",
    "ProviderNotRegisteredError", "ProviderRegistryError", "CapabilityRegistry",
    "DEFAULT_CAPABILITIES", "ProviderRegistry",
)
