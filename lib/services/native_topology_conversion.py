"""Bounded cross-vendor native project conversion through canonical topology.

Conversion is deliberately template-based: both source and destination files
must decode to equivalent canonical node/link structures. This transfers
portable placement/labels into an existing destination-native project without
pretending to translate vendor device configuration, images or arbitrary
proprietary objects.
"""
from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping

from lib.native_topology.contracts import NativeTopologyCodecError
from lib.native_topology.registry import NativeTopologyCodecRegistry


class NativeTopologyConversionError(ValueError):
    """A native conversion cannot be performed without semantic loss."""


@dataclass(frozen=True, slots=True)
class NativeTopologyConversion:
    filename: str
    media_type: str
    content: bytes
    report: dict[str, Any]


class NativeTopologyConversionService:
    """Transfer compatible canonical topology presentation across native formats."""

    MAX_MAPPING_ITEMS = 1024
    MAX_MAPPING_BYTES = 64 * 1024
    _FORMAT_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,255}$")

    def __init__(self, registry: NativeTopologyCodecRegistry | None = None) -> None:
        self.registry = registry or __import__(
            "lib.native_topology.registry", fromlist=["default_registry"]
        ).default_registry()

    @staticmethod
    def _safe_filename(value: object, field: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 255:
            raise NativeTopologyConversionError(f"{field} must be a safe native project filename")
        if value in {".", ".."} or "/" in value or "\\" in value or any(ord(ch) < 32 for ch in value):
            raise NativeTopologyConversionError(f"{field} must be a filename, not a path")
        return value

    @staticmethod
    def _canvas_size(presentation: Mapping[str, Any]) -> tuple[float, float]:
        canvas = presentation.get("canvas") or {}
        width, height = canvas.get("width", 1000), canvas.get("height", 620)
        if isinstance(width, bool) or isinstance(height, bool):
            raise NativeTopologyConversionError("native presentation canvas dimensions are invalid")
        try:
            width, height = float(width), float(height)
        except (TypeError, ValueError) as exc:
            raise NativeTopologyConversionError("native presentation canvas dimensions are invalid") from exc
        if not (0 < width <= 100000 and 0 < height <= 100000):
            raise NativeTopologyConversionError("native presentation canvas dimensions are outside the supported range")
        return width, height

    @classmethod
    def _to_canvas(cls, x: float, y: float, space: Mapping[str, Any], size: tuple[float, float]) -> tuple[float, float]:
        width, height = size
        origin = str(space.get("origin", "top_left")).lower()
        axis_x = str(space.get("x_axis", "right")).lower()
        axis_y = str(space.get("y_axis", "down")).lower()
        if origin == "center":
            return (
                width / 2 + (-x if axis_x == "left" else x),
                height / 2 + (-y if axis_y == "up" else y),
            )
        return (
            width - x if axis_x == "left" else x,
            height - y if axis_y == "up" else y,
        )

    @classmethod
    def _from_canvas(cls, x: float, y: float, space: Mapping[str, Any], size: tuple[float, float]) -> tuple[float, float]:
        width, height = size
        origin = str(space.get("origin", "top_left")).lower()
        axis_x = str(space.get("x_axis", "right")).lower()
        axis_y = str(space.get("y_axis", "down")).lower()
        if origin == "center":
            return (
                (x - width / 2) * (-1 if axis_x == "left" else 1),
                (y - height / 2) * (-1 if axis_y == "up" else 1),
            )
        return (
            width - x if axis_x == "left" else x,
            height - y if axis_y == "up" else y,
        )

    @staticmethod
    def _node_map(
        source_nodes: list[dict], target_nodes: list[dict], supplied: object,
    ) -> tuple[dict[str, str], str]:
        source_ids = {str(item["id"]) for item in source_nodes}
        target_by_id = {str(item["id"]): item for item in target_nodes}
        if supplied is None:
            target_by_name: dict[str, list[str]] = {}
            for item in target_nodes:
                target_by_name.setdefault(str(item.get("name", "")).strip().casefold(), []).append(str(item["id"]))
            mapping = {}
            for item in source_nodes:
                name = str(item.get("name", "")).strip().casefold()
                candidates = target_by_name.get(name, [])
                if len(candidates) != 1:
                    raise NativeTopologyConversionError(
                        f"node {item['id']} cannot be mapped uniquely by name; supply an explicit node mapping"
                    )
                mapping[str(item["id"])] = candidates[0]
            method = "EXACT_UNIQUE_NAME"
        else:
            if not isinstance(supplied, Mapping) or len(supplied) > NativeTopologyConversionService.MAX_MAPPING_ITEMS:
                raise NativeTopologyConversionError("node_mapping must be a bounded source-ID to target-ID object")
            mapping = {}
            for source_id, target_id in supplied.items():
                if not isinstance(source_id, str) or not isinstance(target_id, str):
                    raise NativeTopologyConversionError("node_mapping keys and values must be strings")
                mapping[source_id] = target_id
            method = "EXPLICIT"
        if set(mapping) != source_ids:
            raise NativeTopologyConversionError("node_mapping must cover every source node exactly once")
        values = list(mapping.values())
        if len(values) != len(set(values)) or set(values) != set(target_by_id):
            raise NativeTopologyConversionError("node_mapping must be a one-to-one mapping covering every destination node")
        for source in source_nodes:
            target = target_by_id[mapping[str(source["id"])]]
            if str(source.get("node_type", "OTHER")).upper() != str(target.get("node_type", "OTHER")).upper():
                raise NativeTopologyConversionError(
                    f"node type mismatch for {source['id']}: {source.get('node_type')} cannot map to {target.get('node_type')}"
                )
            source_ports = {
                (int(port.get("adapter", 0)), int(port.get("port", 0)))
                for port in source.get("interfaces", [])
            }
            target_ports = {
                (int(port.get("adapter", 0)), int(port.get("port", 0)))
                for port in target.get("interfaces", [])
            }
            if source_ports != target_ports:
                raise NativeTopologyConversionError(
                    f"interface adapter/port inventory differs for mapped node {source['id']}; conversion was refused"
                )
        return mapping, method

    @staticmethod
    def _link_signature(link: Mapping[str, Any], node_map: Mapping[str, str] | None = None) -> tuple:
        source_id = str(link["source_node_id"])
        target_id = str(link["target_node_id"])
        if node_map is not None:
            source_id = node_map[source_id]
            target_id = node_map[target_id]
        ends = (
            (source_id, int(link.get("source_adapter", 0)), int(link.get("source_port", 0))),
            (target_id, int(link.get("target_adapter", 0)), int(link.get("target_port", 0))),
        )
        return tuple(sorted(ends))

    @classmethod
    def _link_map(cls, source_links: list[dict], target_links: list[dict], node_map: Mapping[str, str], supplied: object) -> tuple[dict[str, str], str]:
        target_by_id = {str(item["id"]): item for item in target_links}
        if supplied is None:
            target_signatures: dict[tuple, list[str]] = {}
            for item in target_links:
                target_signatures.setdefault(cls._link_signature(item), []).append(str(item["id"]))
            mapping = {}
            for item in source_links:
                signature = cls._link_signature(item, node_map)
                candidates = target_signatures.get(signature, [])
                if len(candidates) != 1:
                    raise NativeTopologyConversionError(
                        f"link {item['id']} cannot be mapped uniquely by endpoints; supply an explicit link mapping"
                    )
                mapping[str(item["id"])] = candidates[0]
            method = "CANONICAL_ENDPOINTS"
        else:
            if not isinstance(supplied, Mapping) or len(supplied) > cls.MAX_MAPPING_ITEMS:
                raise NativeTopologyConversionError("link_mapping must be a bounded source-ID to target-ID object")
            mapping = {}
            for source_id, target_id in supplied.items():
                if not isinstance(source_id, str) or not isinstance(target_id, str):
                    raise NativeTopologyConversionError("link_mapping keys and values must be strings")
                mapping[source_id] = target_id
            method = "EXPLICIT"
        if set(mapping) != {str(item["id"]) for item in source_links}:
            raise NativeTopologyConversionError("link_mapping must cover every source link exactly once")
        if len(set(mapping.values())) != len(mapping) or set(mapping.values()) != set(target_by_id):
            raise NativeTopologyConversionError("link_mapping must be a one-to-one mapping covering every destination link")
        for source in source_links:
            target = target_by_id[mapping[str(source["id"])]]
            if cls._link_signature(source, node_map) != cls._link_signature(target):
                raise NativeTopologyConversionError(
                    f"mapped link {source['id']} does not preserve the same logical endpoints and ports"
                )
        return mapping, method

    @staticmethod
    def _presentation_nodes(presentation: Mapping[str, Any]) -> dict[str, dict]:
        return {
            str(item.get("node_id")): item
            for item in presentation.get("nodes", [])
            if isinstance(item, Mapping) and item.get("node_id")
        }

    def convert(
        self,
        source_bytes: bytes,
        target_template_bytes: bytes,
        *,
        source_filename: str,
        target_template_filename: str,
        mapping: Mapping[str, Any] | None = None,
    ) -> NativeTopologyConversion:
        source_name = self._safe_filename(source_filename, "source_filename")
        target_name = self._safe_filename(target_template_filename, "target_template_filename")
        if not isinstance(source_bytes, bytes) or not source_bytes or len(source_bytes) > 50 * 1024 * 1024:
            raise NativeTopologyConversionError("source project must contain 1 byte to 50 MiB")
        if not isinstance(target_template_bytes, bytes) or not target_template_bytes or len(target_template_bytes) > 50 * 1024 * 1024:
            raise NativeTopologyConversionError("destination template must contain 1 byte to 50 MiB")
        if mapping is not None:
            if not isinstance(mapping, Mapping):
                raise NativeTopologyConversionError("mapping must be an object")
            if set(mapping) - {"nodes", "links"}:
                raise NativeTopologyConversionError("mapping accepts only nodes and links")
            if len(str(mapping).encode("utf-8")) > self.MAX_MAPPING_BYTES:
                raise NativeTopologyConversionError("mapping exceeds the 64 KiB limit")

        try:
            source = self.registry.decode(source_bytes, source_name)
            target = self.registry.decode(target_template_bytes, target_name)
        except (NativeTopologyCodecError, ValueError, TypeError) as exc:
            raise NativeTopologyConversionError(str(exc)) from exc
        if source.format_id == target.format_id:
            raise NativeTopologyConversionError("cross-vendor conversion requires different source and destination formats")

        source_definition = source.topology_definition
        target_definition = target.topology_definition
        if len(source_definition.get("nodes", [])) != len(target_definition.get("nodes", [])):
            raise NativeTopologyConversionError("source and destination templates must contain the same number of nodes")
        if len(source_definition.get("links", [])) != len(target_definition.get("links", [])):
            raise NativeTopologyConversionError("source and destination templates must contain the same number of links")

        node_mapping, node_method = self._node_map(
            source_definition["nodes"], target_definition["nodes"],
            mapping.get("nodes") if mapping else None,
        )
        link_mapping, link_method = self._link_map(
            source_definition["links"], target_definition["links"], node_mapping,
            mapping.get("links") if mapping else None,
        )

        source_presentation = source.presentation
        target_presentation = copy.deepcopy(target.presentation)
        source_nodes = self._presentation_nodes(source_presentation)
        target_nodes = self._presentation_nodes(target_presentation)
        if set(source_nodes) != set(node_mapping) or set(target_nodes) != set(node_mapping.values()):
            raise NativeTopologyConversionError("source or destination presentation is missing mapped native node objects")
        source_size = self._canvas_size(source_presentation)
        target_size = self._canvas_size(target_presentation)
        source_space = source_presentation.get("coordinate_space") or {}
        target_space = target_presentation.get("coordinate_space") or {}

        target_by_id = target_nodes
        mapped_objects = []
        for source_id, target_id in sorted(node_mapping.items()):
            source_node = source_nodes[source_id]
            target_node = target_by_id[target_id]
            raw_x, raw_y = float(source_node.get("x", 0)), float(source_node.get("y", 0))
            canvas_x, canvas_y = self._to_canvas(raw_x, raw_y, source_space, source_size)
            scaled_x = canvas_x / source_size[0] * target_size[0]
            scaled_y = canvas_y / source_size[1] * target_size[1]
            native_x, native_y = self._from_canvas(scaled_x, scaled_y, target_space, target_size)
            target_node["x"] = native_x
            target_node["y"] = native_y
            source_label = str(source_node.get("label") or next(
                (item["name"] for item in source_definition["nodes"] if item["id"] == source_id), source_id
            ))
            target_node["label"] = source_label
            mapped_objects.append({
                "source_node_id": source_id,
                "target_node_id": target_id,
                "source_label": source_label,
                "target_native_id": target_node.get("native_id"),
                "mapping": "EXPLICIT" if node_method == "EXPLICIT" else "NAME",
            })

        source_links = {
            str(item.get("link_id")): item
            for item in source_presentation.get("links", [])
            if isinstance(item, Mapping) and item.get("link_id")
        }
        target_links = {
            str(item.get("link_id")): item
            for item in target_presentation.get("links", [])
            if isinstance(item, Mapping) and item.get("link_id")
        }
        if set(source_links) != set(link_mapping) or set(target_links) != set(link_mapping.values()):
            raise NativeTopologyConversionError("source or destination presentation is missing mapped native link objects")
        mapped_links = []
        for source_id, target_id in sorted(link_mapping.items()):
            label = source_links[source_id].get("label")
            if label:
                target_links[target_id]["label"] = str(label)[:256]
            mapped_links.append({
                "source_link_id": source_id,
                "target_link_id": target_id,
                "target_native_id": target_links[target_id].get("native_id"),
                "mapping": "EXPLICIT" if link_method == "EXPLICIT" else "CANONICAL_ENDPOINTS",
            })

        try:
            encoded = self.registry.encode(
                target.format_id,
                target_definition,
                target_presentation,
                original_source=target_template_bytes,
                filename=target_name,
            )
        except (NativeTopologyCodecError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise NativeTopologyConversionError(str(exc)) from exc

        source_drawings = len(source_presentation.get("drawings", []))
        source_assets = len(source.assets)
        losses = [
            {
                "category": "CONFIGURATION",
                "severity": "NOT_TRANSLATED",
                "message": "Vendor/device configuration is not translated; the destination template's native configuration remains unchanged.",
            },
            {
                "category": "DEVICE_MODEL_AND_IMAGE",
                "severity": "TEMPLATE_RETAINED",
                "message": "Destination device definitions, models, images and runtime properties come from the destination template.",
            },
            {
                "category": "LINK_GEOMETRY",
                "severity": "NOT_TRANSLATED",
                "message": "Source-specific route control points and routing styles are not copied; destination native link geometry is retained.",
            },
        ]
        if source_drawings:
            losses.append({
                "category": "DRAWINGS",
                "severity": "NOT_TRANSLATED",
                "count": source_drawings,
                "message": "Source drawings and annotations are not translated across vendor formats.",
            })
        if source_assets:
            losses.append({
                "category": "ASSETS",
                "severity": "NOT_TRANSLATED",
                "count": source_assets,
                "message": "Source asset bytes are not copied; destination template assets remain unchanged.",
            })
        losses.extend({"category": "DESTINATION_CODEC", "severity": "REPORTED", "message": item} for item in encoded.losses)

        report = {
            "schema_version": "1.0",
            "status": "CONVERTED_WITH_DECLARED_LOSSES" if losses else "CONVERTED",
            "conversion_scope": "STRUCTURE_PRESERVING_NATIVE_TEMPLATE_TRANSFER",
            "semantic_conversion": "SAME_CANONICAL_NODE_TYPES_AND_LINK_ENDPOINTS_REQUIRED",
            "source": {
                "format_id": source.format_id, "format_version": source.format_version,
                "filename": source_name, "sha256": hashlib.sha256(source_bytes).hexdigest(),
            },
            "destination_template": {
                "format_id": target.format_id, "format_version": target.format_version,
                "filename": target_name, "sha256": hashlib.sha256(target_template_bytes).hexdigest(),
            },
            "output": {
                "format_id": encoded.format_id, "format_version": encoded.format_version,
                "filename": encoded.filename, "sha256": hashlib.sha256(encoded.content).hexdigest(),
            },
            "mapping": {
                "node_method": node_method, "link_method": link_method,
                "nodes": mapped_objects, "links": mapped_links,
            },
            "counts": {
                "nodes_mapped": len(mapped_objects), "links_mapped": len(mapped_links),
                "source_drawings": source_drawings, "source_assets": source_assets,
            },
            "losses": losses,
            "codec_read_back": "DESTINATION_CODEC_VERIFIED",
            "originating_application_reopen": "NOT_VERIFIED",
        }
        return NativeTopologyConversion(
            filename=encoded.filename, media_type=encoded.media_type,
            content=encoded.content, report=report,
        )
