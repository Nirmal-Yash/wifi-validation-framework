"""Independent native topology codec registry and deterministic format detection."""
from __future__ import annotations

from collections.abc import Iterable

from .contracts import NativeCodecDescriptor, NativeTopologyCodec, NativeTopologyCodecError


class NativeTopologyCodecRegistry:
    """Registry for native project-file formats; never registers runtime providers."""

    def __init__(self, codecs: Iterable[NativeTopologyCodec] = ()) -> None:
        self._codecs: dict[str, NativeTopologyCodec] = {}
        for codec in codecs:
            self.register(codec)

    def register(self, codec: NativeTopologyCodec) -> None:
        format_id = getattr(codec, "format_id", None)
        codec_name = getattr(codec, "codec_name", None)
        if not isinstance(format_id, str) or not format_id or not isinstance(codec_name, str) or not codec_name:
            raise NativeTopologyCodecError("codec must declare format_id and codec_name")
        if format_id in self._codecs:
            raise NativeTopologyCodecError(f"native topology codec {format_id!r} is already registered")
        extensions = getattr(codec, "extensions", ())
        if not extensions or any(not isinstance(item, str) or not item.startswith(".") for item in extensions):
            raise NativeTopologyCodecError("codec must declare supported file extensions")
        self._codecs[format_id] = codec

    def get(self, format_id: str) -> NativeTopologyCodec:
        codec = self._codecs.get(format_id)
        if codec is None:
            raise NativeTopologyCodecError(f"native topology format {format_id!r} is not supported")
        return codec

    def detect(self, source: bytes, filename: str) -> NativeTopologyCodec:
        if not isinstance(filename, str) or not filename.strip():
            raise NativeTopologyCodecError("native project filename is required")
        matches = []
        errors = []
        for codec in self._codecs.values():
            try:
                if codec.detect(source, filename):
                    matches.append(codec)
            except (ValueError, TypeError):
                errors.append(getattr(codec, "format_id", "unknown"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise NativeTopologyCodecError("native project file matches multiple codecs; format detection is ambiguous")
        if errors:
            raise NativeTopologyCodecError("native project could not be safely inspected by the registered codecs")
        raise NativeTopologyCodecError("unsupported native file; accepted .gns3, CML .yaml/.yml/.virl and EVE-NG .unl")

    def decode(self, source: bytes, filename: str):
        codec = self.detect(source, filename)
        try:
            result = codec.decode(source, filename)
        except NativeTopologyCodecError:
            raise
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise NativeTopologyCodecError(f"{codec.format_id} project file is invalid or unsupported: {exc}") from exc
        if result.format_id != codec.format_id:
            raise NativeTopologyCodecError("codec returned a format identifier inconsistent with its registry entry")
        return result

    def encode(self, format_id, topology_definition, presentation, *, original_source, filename):
        codec = self.get(format_id)
        try:
            return codec.encode(
                topology_definition, presentation,
                original_source=original_source, filename=filename,
            )
        except NativeTopologyCodecError:
            raise
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise NativeTopologyCodecError(f"{codec.format_id} export was refused: {exc}") from exc

    def descriptors(self) -> list[NativeCodecDescriptor]:
        return [
            NativeCodecDescriptor(
                format_id=codec.format_id,
                codec_name=codec.codec_name,
                codec_version=codec.codec_version,
                extensions=tuple(codec.extensions),
                supported_versions=tuple(codec.supported_versions),
                scope=codec.scope,
                external_reopen_required=True,
            )
            for codec in self._codecs.values()
        ]


def default_registry() -> NativeTopologyCodecRegistry:
    from .cml import CMLTopologyCodec
    from .eve_ng import EVENGTopologyCodec
    from .gns3 import GNS3TopologyCodec

    return NativeTopologyCodecRegistry((
        GNS3TopologyCodec(),
        CMLTopologyCodec(),
        EVENGTopologyCodec(),
    ))
