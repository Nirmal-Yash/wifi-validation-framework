"""Vendor-neutral network configuration compilation and adapter registry."""
from .contracts import AdapterCompileError, AdapterDescriptor, CompilationDiagnostic, CompiledArtifact
from .registry import AdapterResolutionError, NetworkConfigAdapterRegistry

__all__ = (
    "AdapterCompileError", "AdapterDescriptor", "CompilationDiagnostic",
    "CompiledArtifact", "AdapterResolutionError", "NetworkConfigAdapterRegistry",
)
