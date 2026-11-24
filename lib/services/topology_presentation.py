"""Versioned native presentation snapshots pinned to canonical topology revisions."""
from __future__ import annotations

import json
import math
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from lib.services.topology_studio import TopologyStudioService
from lib.services.topology_metadata import (
    MetadataValidationError,
    canonical_json,
    normalize_extensions,
    safe_relative_path,
)


class TopologyPresentationError(ValueError):
    """Invalid topology presentation metadata or lifecycle transition."""


class TopologyPresentationNotFound(LookupError):
    """Presentation, topology revision or associated source artifact was not found."""


class TopologyPresentationConflict(TopologyPresentationError):
    """A presentation state transition conflicts with the pinned topology revision."""


_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_FORMAT_ID = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TopologyPresentationService:
    SCHEMA_VERSION = "1.0"
    MAX_PRESENTATION_BYTES = 1_000_000
    MAX_NODES = 128
    MAX_LINKS = 512
    MAX_DRAWINGS = 1000
    MAX_LAYERS = 64
    MAX_COORDINATE = 1_000_000.0

    def __init__(self, database) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise TopologyPresentationError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _text(value: object, name: str, maximum: int, *, required: bool = True) -> str:
        if value is None and not required:
            return ""
        if not isinstance(value, str):
            raise TopologyPresentationError(f"{name} must be a string")
        result = value.strip()
        if (required and not result) or len(result) > maximum or any(ord(char) < 32 for char in result):
            raise TopologyPresentationError(f"{name} must contain 1 to {maximum} printable characters")
        return result

    @staticmethod
    def _number(value: object, name: str, minimum: float, maximum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise TopologyPresentationError(f"{name} must be a finite number")
        number = float(value)
        if number < minimum or number > maximum:
            raise TopologyPresentationError(f"{name} must be between {minimum} and {maximum}")
        return round(number, 4)

    @staticmethod
    def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise TopologyPresentationError(f"{name} must be an integer from {minimum} to {maximum}")
        return value

    @classmethod
    def _extensions(cls, value: object, name: str) -> dict[str, Any]:
        try:
            return normalize_extensions(value, field_name=name)
        except MetadataValidationError as exc:
            raise TopologyPresentationError(str(exc)) from exc

    @classmethod
    def _point(cls, value: object, name: str) -> dict[str, float]:
        if not isinstance(value, Mapping) or set(value) != {"x", "y"}:
            raise TopologyPresentationError(f"{name} must contain only finite x and y coordinates")
        return {
            "x": cls._number(value["x"], f"{name}.x", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
            "y": cls._number(value["y"], f"{name}.y", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
        }

    @classmethod
    def normalize_presentation(cls, value: object, topology_definition: object) -> dict[str, Any]:
        allowed = {
            "schema_version", "layout_origin", "format_id", "format_version",
            "source_artifact_id", "coordinate_space", "canvas", "viewport", "grid",
            "nodes", "links", "drawings", "layers", "extensions",
        }
        required = {"schema_version", "layout_origin"}
        if not isinstance(value, Mapping) or required - set(value) or set(value) - allowed:
            raise TopologyPresentationError("presentation must be an object with schema_version and layout_origin only from the supported fields")
        schema_version = cls._text(value.get("schema_version"), "schema_version", 16)
        if schema_version != cls.SCHEMA_VERSION:
            raise TopologyPresentationError(f"presentation schema_version {schema_version!r} is not supported")
        layout_origin = cls._text(value.get("layout_origin"), "layout_origin", 16).upper()
        if layout_origin not in {"NATIVE", "MANUAL", "NETREGRESS"}:
            raise TopologyPresentationError("layout_origin must be NATIVE, MANUAL or NETREGRESS")

        try:
            canonical_definition = TopologyStudioService.normalize_definition(topology_definition)
        except Exception as exc:
            raise TopologyPresentationError("the pinned canonical topology definition is invalid") from exc
        canonical_nodes = {node["id"]: node for node in canonical_definition["nodes"]}
        canonical_links = {link["id"]: link for link in canonical_definition["links"]}

        result: dict[str, Any] = {"schema_version": schema_version, "layout_origin": layout_origin}
        format_id = cls._text(value.get("format_id"), "format_id", 64, required=False).upper()
        format_version = cls._text(value.get("format_version"), "format_version", 32, required=False)
        if format_id:
            if not _FORMAT_ID.fullmatch(format_id):
                raise TopologyPresentationError("format_id must be an uppercase native-format identifier")
            result["format_id"] = format_id
        if format_version:
            result["format_version"] = format_version
        if layout_origin == "NATIVE" and (not format_id or not format_version):
            raise TopologyPresentationError("NATIVE presentation requires format_id and format_version")

        source_artifact_id = cls._text(value.get("source_artifact_id"), "source_artifact_id", 64, required=False)
        if source_artifact_id:
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", source_artifact_id):
                raise TopologyPresentationError("source_artifact_id is invalid")
            result["source_artifact_id"] = source_artifact_id
        if layout_origin == "NATIVE" and not source_artifact_id:
            raise TopologyPresentationError("NATIVE presentation requires immutable source_artifact_id provenance")

        if "coordinate_space" in value:
            raw = value["coordinate_space"]
            fields = {"unit", "origin", "x_axis", "y_axis", "scale", "offset_x", "offset_y"}
            if not isinstance(raw, Mapping) or set(raw) - fields or not {"unit", "origin"} <= set(raw):
                raise TopologyPresentationError("coordinate_space contains missing or unsupported fields")
            unit = cls._text(raw["unit"], "coordinate_space.unit", 16).lower()
            origin = cls._text(raw["origin"], "coordinate_space.origin", 16).lower()
            if unit not in {"px", "pt", "mm", "grid", "native"}:
                raise TopologyPresentationError("coordinate_space.unit is not supported")
            if origin not in {"top_left", "bottom_left", "center"}:
                raise TopologyPresentationError("coordinate_space.origin is not supported")
            axis_x = cls._text(raw.get("x_axis", "right"), "coordinate_space.x_axis", 8).lower()
            axis_y = cls._text(raw.get("y_axis", "down"), "coordinate_space.y_axis", 8).lower()
            if axis_x not in {"left", "right"} or axis_y not in {"up", "down"}:
                raise TopologyPresentationError("coordinate_space axis directions are not supported")
            result["coordinate_space"] = {
                "unit": unit, "origin": origin, "x_axis": axis_x, "y_axis": axis_y,
                "scale": cls._number(raw.get("scale", 1), "coordinate_space.scale", 0.0001, 10000),
                "offset_x": cls._number(raw.get("offset_x", 0), "coordinate_space.offset_x", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
                "offset_y": cls._number(raw.get("offset_y", 0), "coordinate_space.offset_y", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
            }
        elif layout_origin == "NATIVE":
            raise TopologyPresentationError("NATIVE presentation requires an explicit coordinate_space")

        if "canvas" in value:
            raw = value["canvas"]
            if not isinstance(raw, Mapping) or set(raw) - {"width", "height", "background"} or not {"width", "height"} <= set(raw):
                raise TopologyPresentationError("canvas must contain width and height only from the supported fields")
            canvas = {
                "width": cls._integer(raw["width"], "canvas.width", 1, 100000),
                "height": cls._integer(raw["height"], "canvas.height", 1, 100000),
            }
            if raw.get("background") not in (None, ""):
                canvas["background"] = cls._text(raw["background"], "canvas.background", 64)
            result["canvas"] = canvas

        if "viewport" in value:
            raw = value["viewport"]
            fields = {"x", "y", "width", "height", "zoom"}
            if not isinstance(raw, Mapping) or set(raw) - fields or not {"x", "y", "width", "height"} <= set(raw):
                raise TopologyPresentationError("viewport contains missing or unsupported fields")
            result["viewport"] = {
                "x": cls._number(raw["x"], "viewport.x", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
                "y": cls._number(raw["y"], "viewport.y", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
                "width": cls._number(raw["width"], "viewport.width", 1, cls.MAX_COORDINATE),
                "height": cls._number(raw["height"], "viewport.height", 1, cls.MAX_COORDINATE),
                "zoom": cls._number(raw.get("zoom", 1), "viewport.zoom", 0.01, 100),
            }

        if "grid" in value:
            raw = value["grid"]
            if not isinstance(raw, Mapping) or set(raw) - {"enabled", "snap", "size"}:
                raise TopologyPresentationError("grid contains unsupported fields")
            if "enabled" in raw and not isinstance(raw["enabled"], bool):
                raise TopologyPresentationError("grid.enabled must be boolean")
            if "snap" in raw and not isinstance(raw["snap"], bool):
                raise TopologyPresentationError("grid.snap must be boolean")
            result["grid"] = {
                "enabled": raw.get("enabled", False),
                "snap": raw.get("snap", False),
                "size": cls._number(raw.get("size", 20), "grid.size", 1, 1000),
            }

        raw_layers = value.get("layers", [])
        if not isinstance(raw_layers, list) or len(raw_layers) > cls.MAX_LAYERS:
            raise TopologyPresentationError(f"layers must be an array of at most {cls.MAX_LAYERS} entries")
        layers: list[dict[str, Any]] = []
        layer_ids: set[str] = set()
        for index, raw in enumerate(raw_layers):
            name = f"layers[{index}]"
            fields = {"id", "name", "visible", "locked", "z_index", "native_id", "extensions"}
            if not isinstance(raw, Mapping) or set(raw) - fields or not {"id", "name"} <= set(raw):
                raise TopologyPresentationError(f"{name} contains missing or unsupported fields")
            layer_id = cls._text(raw["id"], f"{name}.id", 64)
            if not _ID.fullmatch(layer_id) or layer_id in layer_ids:
                raise TopologyPresentationError(f"{name}.id is invalid or duplicated")
            layer_ids.add(layer_id)
            visible, locked = raw.get("visible", True), raw.get("locked", False)
            if not isinstance(visible, bool) or not isinstance(locked, bool):
                raise TopologyPresentationError(f"{name}.visible and locked must be boolean")
            item = {
                "id": layer_id, "name": cls._text(raw["name"], f"{name}.name", 120),
                "visible": visible, "locked": locked,
                "z_index": cls._integer(raw.get("z_index", 0), f"{name}.z_index", -100000, 100000),
            }
            native_id = cls._text(raw.get("native_id"), f"{name}.native_id", 128, required=False)
            if native_id:
                item["native_id"] = native_id
            extensions = cls._extensions(raw.get("extensions"), f"{name}.extensions")
            if extensions:
                item["extensions"] = extensions
            layers.append(item)
        layers.sort(key=lambda item: (item["z_index"], item["id"]))
        result["layers"] = layers

        raw_nodes = value.get("nodes", [])
        if not isinstance(raw_nodes, list) or len(raw_nodes) > cls.MAX_NODES:
            raise TopologyPresentationError(f"nodes must be an array of at most {cls.MAX_NODES} entries")
        nodes: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        for index, raw in enumerate(raw_nodes):
            name = f"nodes[{index}]"
            fields = {
                "node_id", "native_id", "x", "y", "width", "height", "rotation",
                "icon_ref", "icon_asset_path", "template_ref", "z_index", "label",
                "layer_id", "ports", "extensions",
            }
            if not isinstance(raw, Mapping) or set(raw) - fields or not {"node_id", "x", "y"} <= set(raw):
                raise TopologyPresentationError(f"{name} contains missing or unsupported fields")
            node_id = cls._text(raw["node_id"], f"{name}.node_id", 64)
            if node_id not in canonical_nodes or node_id in seen_nodes:
                raise TopologyPresentationError(f"{name}.node_id must reference one unique canonical logical node")
            seen_nodes.add(node_id)
            item: dict[str, Any] = {
                "node_id": node_id,
                "x": cls._number(raw["x"], f"{name}.x", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
                "y": cls._number(raw["y"], f"{name}.y", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
            }
            native_id = cls._text(raw.get("native_id"), f"{name}.native_id", 128, required=False)
            if native_id:
                item["native_id"] = native_id
            for dimension in ("width", "height"):
                if dimension in raw and raw[dimension] is not None:
                    item[dimension] = cls._number(raw[dimension], f"{name}.{dimension}", 1, 10000)
            if "rotation" in raw:
                item["rotation"] = cls._number(raw["rotation"], f"{name}.rotation", -360, 360)
            for field, maximum in (("icon_ref", 256), ("template_ref", 256), ("label", 256)):
                text = cls._text(raw.get(field), f"{name}.{field}", maximum, required=False)
                if text:
                    item[field] = text
            if raw.get("icon_asset_path") not in (None, ""):
                try:
                    item["icon_asset_path"] = safe_relative_path(raw["icon_asset_path"], field_name=f"{name}.icon_asset_path")
                except MetadataValidationError as exc:
                    raise TopologyPresentationError(str(exc)) from exc
            item["z_index"] = cls._integer(raw.get("z_index", 0), f"{name}.z_index", -100000, 100000)
            layer_id = cls._text(raw.get("layer_id"), f"{name}.layer_id", 64, required=False)
            if layer_id:
                if layer_id not in layer_ids:
                    raise TopologyPresentationError(f"{name}.layer_id references an unknown layer")
                item["layer_id"] = layer_id

            raw_ports = raw.get("ports", [])
            if not isinstance(raw_ports, list) or len(raw_ports) > 64:
                raise TopologyPresentationError(f"{name}.ports must be an array of at most 64 entries")
            ports: list[dict[str, Any]] = []
            seen_port_keys: set[str] = set()
            canonical_interfaces = canonical_nodes[node_id].get("interfaces", [])
            for port_index, raw_port in enumerate(raw_ports):
                port_name = f"{name}.ports[{port_index}]"
                port_fields = {
                    "interface_name", "adapter", "port", "side", "anchor_x", "anchor_y",
                    "label", "native_id", "extensions",
                }
                if not isinstance(raw_port, Mapping) or set(raw_port) - port_fields:
                    raise TopologyPresentationError(f"{port_name} contains unsupported fields")
                interface_name = cls._text(raw_port.get("interface_name"), f"{port_name}.interface_name", 64, required=False)
                adapter, port_number = raw_port.get("adapter"), raw_port.get("port")
                if interface_name:
                    if canonical_interfaces:
                        matched = next((entry for entry in canonical_interfaces if entry["name"] == interface_name), None)
                        if matched is None:
                            raise TopologyPresentationError(f"{port_name}.interface_name is not declared on its logical node")
                        if adapter is not None and adapter != matched["adapter"]:
                            raise TopologyPresentationError(f"{port_name}.adapter does not match its logical interface")
                        if port_number is not None and port_number != matched["port"]:
                            raise TopologyPresentationError(f"{port_name}.port does not match its logical interface")
                        adapter, port_number = matched["adapter"], matched["port"]
                if adapter is not None or port_number is not None:
                    adapter = cls._integer(adapter, f"{port_name}.adapter", 0, 255)
                    port_number = cls._integer(port_number, f"{port_name}.port", 0, 255)
                    port_key = f"{adapter}:{port_number}"
                elif interface_name:
                    port_key = interface_name
                else:
                    raise TopologyPresentationError(f"{port_name} requires interface_name or adapter/port")
                if port_key in seen_port_keys:
                    raise TopologyPresentationError(f"{port_name} is duplicated")
                seen_port_keys.add(port_key)
                side = cls._text(raw_port.get("side"), f"{port_name}.side", 16, required=False).upper()
                if side and side not in {"N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST", "CENTER"}:
                    raise TopologyPresentationError(f"{port_name}.side is not supported")
                port_item: dict[str, Any] = {
                    "anchor_x": cls._number(raw_port.get("anchor_x", 0.5), f"{port_name}.anchor_x", 0, 1),
                    "anchor_y": cls._number(raw_port.get("anchor_y", 0.5), f"{port_name}.anchor_y", 0, 1),
                }
                if interface_name:
                    port_item["interface_name"] = interface_name
                if adapter is not None:
                    port_item["adapter"] = adapter
                    port_item["port"] = port_number
                if side:
                    port_item["side"] = side
                for field, maximum in (("label", 128), ("native_id", 128)):
                    field_value = cls._text(raw_port.get(field), f"{port_name}.{field}", maximum, required=False)
                    if field_value:
                        port_item[field] = field_value
                extensions = cls._extensions(raw_port.get("extensions"), f"{port_name}.extensions")
                if extensions:
                    port_item["extensions"] = extensions
                ports.append(port_item)
            if ports:
                ports.sort(key=lambda entry: (entry.get("adapter", 999), entry.get("port", 999), entry.get("interface_name", "")))
                item["ports"] = ports
            extensions = cls._extensions(raw.get("extensions"), f"{name}.extensions")
            if extensions:
                item["extensions"] = extensions
            nodes.append(item)
        nodes.sort(key=lambda item: item["node_id"])
        result["nodes"] = nodes

        raw_links = value.get("links", [])
        if not isinstance(raw_links, list) or len(raw_links) > cls.MAX_LINKS:
            raise TopologyPresentationError(f"links must be an array of at most {cls.MAX_LINKS} entries")
        links: list[dict[str, Any]] = []
        seen_links: set[str] = set()
        for index, raw in enumerate(raw_links):
            name = f"links[{index}]"
            fields = {"link_id", "native_id", "route_style", "points", "label", "z_index", "extensions"}
            if not isinstance(raw, Mapping) or set(raw) - fields or "link_id" not in raw:
                raise TopologyPresentationError(f"{name} contains missing or unsupported fields")
            link_id = cls._text(raw["link_id"], f"{name}.link_id", 64)
            if link_id not in canonical_links or link_id in seen_links:
                raise TopologyPresentationError(f"{name}.link_id must reference one unique canonical logical link")
            seen_links.add(link_id)
            item: dict[str, Any] = {"link_id": link_id}
            native_id = cls._text(raw.get("native_id"), f"{name}.native_id", 128, required=False)
            if native_id:
                item["native_id"] = native_id
            route_style = cls._text(raw.get("route_style"), f"{name}.route_style", 16, required=False).lower()
            if route_style:
                if route_style not in {"direct", "polyline", "orthogonal", "curved", "native"}:
                    raise TopologyPresentationError(f"{name}.route_style is not supported")
                item["route_style"] = route_style
            points_raw = raw.get("points", [])
            if not isinstance(points_raw, list) or len(points_raw) > 64:
                raise TopologyPresentationError(f"{name}.points must contain at most 64 points")
            if points_raw:
                item["points"] = [cls._point(point, f"{name}.points[{point_index}]") for point_index, point in enumerate(points_raw)]
            label = cls._text(raw.get("label"), f"{name}.label", 256, required=False)
            if label:
                item["label"] = label
            item["z_index"] = cls._integer(raw.get("z_index", 0), f"{name}.z_index", -100000, 100000)
            extensions = cls._extensions(raw.get("extensions"), f"{name}.extensions")
            if extensions:
                item["extensions"] = extensions
            links.append(item)
        links.sort(key=lambda item: item["link_id"])
        result["links"] = links

        raw_drawings = value.get("drawings", [])
        if not isinstance(raw_drawings, list) or len(raw_drawings) > cls.MAX_DRAWINGS:
            raise TopologyPresentationError(f"drawings must be an array of at most {cls.MAX_DRAWINGS} entries")
        drawings: list[dict[str, Any]] = []
        drawing_ids: set[str] = set()
        for index, raw in enumerate(raw_drawings):
            name = f"drawings[{index}]"
            fields = {
                "id", "native_id", "kind", "x", "y", "width", "height",
                "points", "text", "asset_path", "layer_id", "style", "z_index", "extensions",
            }
            if not isinstance(raw, Mapping) or set(raw) - fields or not {"id", "kind", "x", "y"} <= set(raw):
                raise TopologyPresentationError(f"{name} contains missing or unsupported fields")
            drawing_id = cls._text(raw["id"], f"{name}.id", 64)
            if not _ID.fullmatch(drawing_id) or drawing_id in drawing_ids:
                raise TopologyPresentationError(f"{name}.id is invalid or duplicated")
            drawing_ids.add(drawing_id)
            kind = cls._text(raw["kind"], f"{name}.kind", 16).upper()
            if kind not in {"RECTANGLE", "ELLIPSE", "LINE", "FREEHAND", "TEXT", "IMAGE"}:
                raise TopologyPresentationError(f"{name}.kind is not supported")
            item: dict[str, Any] = {
                "id": drawing_id, "kind": kind,
                "x": cls._number(raw["x"], f"{name}.x", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
                "y": cls._number(raw["y"], f"{name}.y", -cls.MAX_COORDINATE, cls.MAX_COORDINATE),
                "z_index": cls._integer(raw.get("z_index", 0), f"{name}.z_index", -100000, 100000),
            }
            native_id = cls._text(raw.get("native_id"), f"{name}.native_id", 128, required=False)
            if native_id:
                item["native_id"] = native_id
            for dimension in ("width", "height"):
                if dimension in raw and raw[dimension] is not None:
                    item[dimension] = cls._number(raw[dimension], f"{name}.{dimension}", 0, cls.MAX_COORDINATE)
            points_raw = raw.get("points", [])
            if not isinstance(points_raw, list) or len(points_raw) > 512:
                raise TopologyPresentationError(f"{name}.points must contain at most 512 points")
            if points_raw:
                item["points"] = [cls._point(point, f"{name}.points[{point_index}]") for point_index, point in enumerate(points_raw)]
            if kind in {"LINE", "FREEHAND"} and len(points_raw) < 2:
                raise TopologyPresentationError(f"{name} of kind {kind} requires at least two points")
            text_value = cls._text(raw.get("text"), f"{name}.text", 4096, required=False)
            if text_value:
                item["text"] = text_value
            if raw.get("asset_path") not in (None, ""):
                try:
                    item["asset_path"] = safe_relative_path(raw["asset_path"], field_name=f"{name}.asset_path")
                except MetadataValidationError as exc:
                    raise TopologyPresentationError(str(exc)) from exc
            layer_id = cls._text(raw.get("layer_id"), f"{name}.layer_id", 64, required=False)
            if layer_id:
                if layer_id not in layer_ids:
                    raise TopologyPresentationError(f"{name}.layer_id references an unknown layer")
                item["layer_id"] = layer_id
            style_raw = raw.get("style", {})
            style_fields = {"stroke", "fill", "stroke_width", "opacity", "font_size", "font_family", "dash", "text_align"}
            if not isinstance(style_raw, Mapping) or set(style_raw) - style_fields or len(style_raw) > 8:
                raise TopologyPresentationError(f"{name}.style contains unsupported fields")
            style: dict[str, Any] = {}
            for field in ("stroke", "fill"):
                field_value = cls._text(style_raw.get(field), f"{name}.style.{field}", 64, required=False)
                if field_value:
                    style[field] = field_value
            for field, low, high in (("stroke_width", 0, 64), ("opacity", 0, 1), ("font_size", 4, 256)):
                if field in style_raw:
                    style[field] = cls._number(style_raw[field], f"{name}.style.{field}", low, high)
            for field, maximum in (("font_family", 80), ("dash", 32), ("text_align", 16)):
                field_value = cls._text(style_raw.get(field), f"{name}.style.{field}", maximum, required=False)
                if field_value:
                    style[field] = field_value
            if style:
                item["style"] = style
            extensions = cls._extensions(raw.get("extensions"), f"{name}.extensions")
            if extensions:
                item["extensions"] = extensions
            drawings.append(item)
        drawings.sort(key=lambda item: (item["z_index"], item["id"]))
        result["drawings"] = drawings

        extensions = cls._extensions(value.get("extensions"), "extensions")
        if extensions:
            result["extensions"] = extensions

        try:
            encoded, _ = canonical_json(result, maximum_bytes=cls.MAX_PRESENTATION_BYTES)
        except MetadataValidationError as exc:
            raise TopologyPresentationError(str(exc)) from exc
        # Referenced asset paths are meaningful only when a source artifact is associated.
        asset_paths: set[str] = set()
        for node in result["nodes"]:
            if node.get("icon_asset_path"):
                asset_paths.add(node["icon_asset_path"])
        for drawing in result["drawings"]:
            if drawing.get("asset_path"):
                asset_paths.add(drawing["asset_path"])
        if asset_paths and not result.get("source_artifact_id"):
            raise TopologyPresentationError("asset paths require an associated source_artifact_id")
        return result

    @classmethod
    def canonical_payload(cls, presentation: object, topology_definition: object) -> tuple[dict[str, Any], str, str]:
        normalized = cls.normalize_presentation(presentation, topology_definition)
        try:
            encoded, digest = canonical_json(normalized, maximum_bytes=cls.MAX_PRESENTATION_BYTES)
        except MetadataValidationError as exc:
            raise TopologyPresentationError(str(exc)) from exc
        return normalized, encoded, digest

    @classmethod
    def _row(cls, row) -> dict | None:
        if row is None:
            return None
        try:
            presentation = json.loads(row["presentation_json"])
            encoded, digest = canonical_json(presentation, maximum_bytes=cls.MAX_PRESENTATION_BYTES)
        except (json.JSONDecodeError, MetadataValidationError) as exc:
            raise TopologyPresentationConflict("stored presentation JSON is malformed or exceeds its integrity limit") from exc
        if row["schema_version"] != cls.SCHEMA_VERSION or presentation.get("schema_version") != row["schema_version"]:
            raise TopologyPresentationConflict("stored presentation schema version is inconsistent")
        if encoded != row["presentation_json"] or digest != row["presentation_sha256"]:
            raise TopologyPresentationConflict("stored presentation snapshot failed its canonical SHA-256 integrity check")
        return {
            "presentation_id": row["presentation_id"],
            "project_id": row["project_id"],
            "profile_id": row["profile_id"],
            "topology_revision_id": row["topology_revision_id"],
            "revision_number": row["revision_number"],
            "schema_version": row["schema_version"],
            "topology_content_sha256": row["topology_content_sha256"],
            "presentation_sha256": row["presentation_sha256"],
            "source_artifact_id": row["source_artifact_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "published_at": row["published_at"],
            "published_by": row["published_by"],
            "presentation": presentation,
        }

    @staticmethod
    def _audit(connection, actor: str, action: str, presentation_id: str, details: Mapping[str, Any]) -> None:
        connection.execute(
            """INSERT INTO audit_events(audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                "AUD-" + secrets.token_hex(12), actor, action, "TOPOLOGY_PRESENTATION",
                presentation_id, json.dumps(details, sort_keys=True, separators=(",", ":")),
                TopologyPresentationService._now(),
            ),
        )

    def list_revisions(self, topology_revision_id: str) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM topology_presentation_revisions
                   WHERE topology_revision_id=? ORDER BY revision_number DESC""",
                (topology_revision_id,),
            ).fetchall()
        return [self._row(row) for row in rows]

    def get_revision(self, presentation_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM topology_presentation_revisions WHERE presentation_id=?",
                (presentation_id,),
            ).fetchone()
        return self._row(row)

    def create_revision(self, topology_revision_id: str, *, presentation: object, actor: str) -> dict:
        actor = self._actor(actor)
        presentation_id = "tpp_" + secrets.token_hex(12)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            base = connection.execute(
                """SELECT r.revision_id,r.profile_id,r.definition_json,r.content_sha256,r.status,
                          p.project_id,p.status AS profile_status
                   FROM topology_revisions r JOIN topology_profiles p ON p.profile_id=r.profile_id
                   WHERE r.revision_id=?""",
                (topology_revision_id,),
            ).fetchone()
            if base is None:
                raise TopologyPresentationNotFound("topology revision not found")
            if base["profile_status"] != "ACTIVE":
                raise TopologyPresentationConflict("archived topology profiles cannot receive presentation revisions")
            try:
                _definition, _encoded, topology_hash = TopologyStudioService.canonical_payload(
                    json.loads(base["definition_json"])
                )
                if topology_hash != base["content_sha256"]:
                    raise TopologyPresentationConflict("canonical topology revision hash does not match its stored definition")
                normalized, encoded, presentation_hash = self.canonical_payload(
                    presentation, json.loads(base["definition_json"])
                )
            except TopologyPresentationError:
                raise
            except TopologyPresentationConflict:
                raise
            except Exception as exc:
                raise TopologyPresentationError(str(exc)) from exc

            source_artifact_id = normalized.get("source_artifact_id")
            if source_artifact_id:
                source = connection.execute(
                    """SELECT source_id,format_id,format_version,topology_content_sha256 FROM topology_source_artifacts
                       WHERE source_id=? AND project_id=? AND profile_id=? AND topology_revision_id=?""",
                    (source_artifact_id, base["project_id"], base["profile_id"], topology_revision_id),
                ).fetchone()
                if source is None:
                    raise TopologyPresentationNotFound("source artifact not found for this topology revision")
                if source["topology_content_sha256"] != topology_hash:
                    raise TopologyPresentationConflict("source artifact is pinned to a different canonical topology hash")
                if normalized.get("layout_origin") == "NATIVE" and (
                    source["format_id"] != normalized.get("format_id")
                    or source["format_version"] != normalized.get("format_version")
                ):
                    raise TopologyPresentationConflict("native presentation format/version does not match its immutable source artifact")
                referenced_assets = {
                    item.get("icon_asset_path") for item in normalized["nodes"] if item.get("icon_asset_path")
                } | {
                    item.get("asset_path") for item in normalized["drawings"] if item.get("asset_path")
                }
                if referenced_assets:
                    placeholders = ",".join("?" for _ in referenced_assets)
                    rows = connection.execute(
                        f"""SELECT relative_path FROM topology_source_assets
                            WHERE source_id=? AND relative_path IN ({placeholders})""",
                        (source_artifact_id, *sorted(referenced_assets)),
                    ).fetchall()
                    if {row["relative_path"] for row in rows} != referenced_assets:
                        raise TopologyPresentationError("presentation references an asset absent from its source artifact")

            revision_number = int(connection.execute(
                """SELECT COALESCE(MAX(revision_number),0)+1
                   FROM topology_presentation_revisions WHERE topology_revision_id=?""",
                (topology_revision_id,),
            ).fetchone()[0])
            connection.execute(
                """INSERT INTO topology_presentation_revisions(
                    presentation_id,project_id,profile_id,topology_revision_id,revision_number,
                    schema_version,topology_content_sha256,presentation_json,presentation_sha256,
                    source_artifact_id,status,created_at,created_by,published_at,published_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,'DRAFT',?,?,NULL,NULL)""",
                (
                    presentation_id, base["project_id"], base["profile_id"], topology_revision_id,
                    revision_number, self.SCHEMA_VERSION, topology_hash, encoded, presentation_hash,
                    source_artifact_id, now, actor,
                ),
            )
            self._audit(
                connection, actor, "TOPOLOGY_PRESENTATION_REVISION_CREATED", presentation_id,
                {
                    "profile_id": base["profile_id"], "topology_revision_id": topology_revision_id,
                    "revision_number": revision_number, "topology_content_sha256": topology_hash,
                    "presentation_sha256": presentation_hash, "layout_origin": normalized["layout_origin"],
                    "source_artifact_id": source_artifact_id,
                },
            )
        return self.get_revision(presentation_id) or {}

    def publish(self, presentation_id: str, *, actor: str, expected_profile_id: str | None = None) -> dict:
        actor = self._actor(actor)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                """SELECT p.*,r.status AS topology_status
                   FROM topology_presentation_revisions p
                   JOIN topology_revisions r ON r.revision_id=p.topology_revision_id
                   WHERE p.presentation_id=?""",
                (presentation_id,),
            ).fetchone()
            if row is None:
                raise TopologyPresentationNotFound("presentation revision not found")
            if expected_profile_id is not None and row["profile_id"] != expected_profile_id:
                raise TopologyPresentationNotFound("presentation revision not found in this topology profile")
            if row["status"] != "DRAFT":
                raise TopologyPresentationConflict("only draft presentation revisions can be published")
            if row["topology_status"] != "PUBLISHED":
                raise TopologyPresentationConflict("publish the pinned canonical topology revision before publishing its presentation")
            cursor = connection.execute(
                """UPDATE topology_presentation_revisions SET status='PUBLISHED',published_at=?,published_by=?
                   WHERE presentation_id=? AND status='DRAFT'""",
                (now, actor, presentation_id),
            )
            if cursor.rowcount != 1:
                raise TopologyPresentationConflict("presentation revision changed during publish")
            self._audit(
                connection, actor, "TOPOLOGY_PRESENTATION_REVISION_PUBLISHED", presentation_id,
                {
                    "profile_id": row["profile_id"], "topology_revision_id": row["topology_revision_id"],
                    "presentation_sha256": row["presentation_sha256"],
                    "topology_content_sha256": row["topology_content_sha256"],
                },
            )
        return self.get_revision(presentation_id) or {}
