"""Typed contracts for deterministic network configuration compilation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class CompilationDiagnostic:
    code: str
    message: str
    severity: str = "ERROR"
    logical_node_id: str | None = None
    device_id: str | None = None
    feature_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "logical_node_id": self.logical_node_id,
            "device_id": self.device_id,
            "feature_id": self.feature_id,
        }


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    adapter_id: str
    name: str
    version: str
    platform_family: str
    supported_versions: str
    output_format: str

    def as_dict(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "name": self.name,
            "version": self.version,
            "platform_family": self.platform_family,
            "supported_versions": self.supported_versions,
            "output_format": self.output_format,
        }


@dataclass(frozen=True, slots=True)
class CompiledArtifact:
    path: str
    media_type: str
    content: str
    sha256: str
    change_type: str
    diff: str

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "media_type": self.media_type,
            "content": self.content,
            "sha256": self.sha256,
            "change_type": self.change_type,
            "diff": self.diff,
        }


class NetworkConfigAdapter(Protocol):
    descriptor: AdapterDescriptor

    def supported_features(self, device: Mapping[str, object]) -> frozenset[str]: ...

    def compile_target(
        self, device: Mapping[str, object], intent: Mapping[str, object]
    ) -> Mapping[str, str]: ...


class AdapterCompileError(ValueError):
    """An adapter cannot safely represent an intent construct."""

    def __init__(self, code: str, message: str, *, feature_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.feature_id = feature_id
