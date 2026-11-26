"""Contracts shared by native topology file codecs.

File codecs are deliberately independent of live provider adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class NativeTopologyCodecError(ValueError):
    """A native file is invalid, unsupported, unsafe, or cannot be losslessly exported."""


@dataclass(frozen=True, slots=True)
class DecodedNativeTopology:
    format_id: str
    format_version: str
    filename: str
    topology_definition: dict[str, Any]
    presentation: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EncodedNativeTopology:
    format_id: str
    format_version: str
    filename: str
    media_type: str
    content: bytes
    losses: tuple[str, ...] = ()


class NativeTopologyCodec(Protocol):
    """Strict parser/serializer for one native project-file family."""

    format_id: str
    codec_name: str
    codec_version: str
    extensions: tuple[str, ...]
    supported_versions: tuple[str, ...]
    scope: str

    def detect(self, source: bytes, filename: str) -> bool: ...
    def decode(self, source: bytes, filename: str) -> DecodedNativeTopology: ...

    def encode(
        self,
        topology_definition: dict[str, Any],
        presentation: dict[str, Any],
        *,
        original_source: bytes,
        filename: str,
    ) -> EncodedNativeTopology: ...


@dataclass(frozen=True, slots=True)
class NativeCodecDescriptor:
    format_id: str
    codec_name: str
    codec_version: str
    extensions: tuple[str, ...]
    supported_versions: tuple[str, ...]
    scope: str
    external_reopen_required: bool = True
