"""Bounded parser and deterministic mapping helpers for native topology codecs."""
from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

import yaml


MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_NATIVE_OBJECTS = 5000
_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def ensure_source(source: object) -> bytes:
    if not isinstance(source, (bytes, bytearray, memoryview)):
        raise ValueError("native project source must be bytes")
    raw = bytes(source)
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        raise ValueError(f"native project source must contain 1 to {MAX_SOURCE_BYTES} bytes")
    return raw


def _no_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"native JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str):
    raise ValueError(f"native JSON constant {value!r} is prohibited")


def _validate_json_tree(value: Any) -> None:
    stack = [(value, 1)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        if depth > MAX_JSON_DEPTH:
            raise ValueError("native JSON exceeds the nesting-depth limit")
        if visited > MAX_JSON_ITEMS:
            raise ValueError("native JSON exceeds the parsed item-count limit")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("native JSON contains a non-finite number")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for pair in item.items() for child in pair)
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def parse_json(source: bytes) -> dict[str, Any]:
    raw = ensure_source(source)
    try:
        value = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
        _validate_json_tree(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("native JSON is invalid, excessively nested, too large, or contains duplicate keys") from exc
    if not isinstance(value, dict):
        raise ValueError("native JSON root must be an object")
    return value


class StrictSafeLoader(yaml.SafeLoader):
    """Safe YAML loader rejecting aliases, duplicate keys, deep trees and oversized node counts."""

    MAX_DEPTH = 48
    MAX_NODES = 100_000

    def __init__(self, stream):
        super().__init__(stream)
        self._native_depth = 0
        self._native_nodes = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("native YAML aliases are not accepted")
        self._native_depth += 1
        self._native_nodes += 1
        if self._native_depth > self.MAX_DEPTH or self._native_nodes > self.MAX_NODES:
            self._native_depth -= 1
            raise ValueError("native YAML exceeds parser depth or object-count limits")
        try:
            return super().compose_node(parent, index)
        finally:
            self._native_depth -= 1

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("native YAML mapping is invalid")
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise ValueError("native YAML mapping keys must be scalar") from exc
            if duplicate:
                raise ValueError(f"native YAML contains duplicate key {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def parse_yaml(source: bytes) -> dict[str, Any]:
    raw = ensure_source(source)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("native YAML must be UTF-8") from exc
    try:
        value = yaml.load(text, Loader=StrictSafeLoader)
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        raise ValueError("native YAML is invalid or exceeds safe parser limits") from exc
    if not isinstance(value, dict):
        raise ValueError("native YAML root must be a mapping")
    return value


def parse_xml(source: bytes, *, expected_root: str | None = None) -> ET.Element:
    raw = ensure_source(source)
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("native XML DTD and entity declarations are prohibited")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("native XML is malformed") from exc
    if expected_root and local_name(root.tag) != expected_root:
        raise ValueError(f"native XML root must be {expected_root!r}")
    if sum(1 for _ in root.iter()) > MAX_NATIVE_OBJECTS * 16:
        raise ValueError("native XML exceeds the element-count limit")
    stack = [(root, 1)]
    while stack:
        node, level = stack.pop()
        if level > 64:
            raise ValueError("native XML exceeds the nesting-depth limit")
        stack.extend((child, level + 1) for child in list(node))
    return root


def local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].split(":")[-1]


def stable_id(prefix: str, native_id: object) -> str:
    return prefix + hashlib.sha256(str(native_id).encode("utf-8")).hexdigest()[:20]


def finite_number(value: object, name: str, *, minimum=-1_000_000, maximum=1_000_000) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if number < minimum or number > maximum:
        raise ValueError(f"{name} is outside the supported coordinate range")
    return round(number, 4)


def bounded_int(value: object, name: str, *, minimum=0, maximum=255) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def text(value: object, name: str, *, maximum=256, required=True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    result = value.strip()
    if (required and not result) or len(result) > maximum or any(ord(ch) < 32 for ch in result):
        raise ValueError(f"{name} must contain 1 to {maximum} printable characters")
    return result


def safe_label(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        cleaned = value.strip()
        if len(cleaned) <= 120 and all(ord(ch) >= 32 for ch in cleaned):
            return cleaned
    return fallback


def map_node_type(vendor_type: object, template: object = "") -> str:
    value = (str(vendor_type or "") + " " + str(template or "")).lower()
    if any(part in value for part in ("switch", "bridge", "hub", "unmanaged", "iosvl2")):
        return "SWITCH"
    if any(part in value for part in ("cloud", "nat", "external", "network-segment")):
        return "CLOUD"
    if any(part in value for part in ("vpcs", "desktop", "host", "alpine", "linux", "server", "pc")):
        return "CLIENT"
    if any(part in value for part in ("router", "dynamips", "ios", "nxos", "csr", "asav", "firewall", "qemu", "iou", "iol")):
        return "ROUTER"
    return "OTHER"


def require_list(value: object, name: str, maximum: int) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{name} must be an array containing at most {maximum} objects")
    return value


def ensure_unique(values: list[str], name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{name} contains duplicate native identifiers")


def empty_native_presentation(format_id: str, version: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "layout_origin": "NATIVE",
        "format_id": format_id,
        "format_version": version,
        "coordinate_space": {
            "unit": "px", "origin": "top_left",
            "x_axis": "right", "y_axis": "down",
            "scale": 1, "offset_x": 0, "offset_y": 0,
        },
        "layers": [{"id": "native", "name": "Native", "visible": True, "locked": False, "z_index": 0}],
        "nodes": [],
        "links": [],
        "drawings": [],
    }


def compare_native_identity(
    expected_nodes: set[str],
    expected_links: set[str],
    topology_definition: Mapping[str, Any],
    presentation: Mapping[str, Any],
    *,
    native_name: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Require one-to-one imported object identity before source-preserving export."""
    node_refs = {}
    for item in presentation.get("nodes", []):
        native_id, node_id = item.get("native_id"), item.get("node_id")
        if native_id and node_id:
            node_refs[str(node_id)] = str(native_id)
    link_refs = {}
    for item in presentation.get("links", []):
        native_id, link_id = item.get("native_id"), item.get("link_id")
        if native_id and link_id:
            link_refs[str(link_id)] = str(native_id)
    current_nodes = {str(item["id"]) for item in topology_definition.get("nodes", [])}
    current_links = {str(item["id"]) for item in topology_definition.get("links", [])}
    if current_nodes != set(node_refs):
        raise ValueError(f"{native_name} export currently supports presentation edits only; node identity changed")
    if current_links != set(link_refs):
        raise ValueError(f"{native_name} export currently supports presentation edits only; link identity changed")
    if set(node_refs.values()) != expected_nodes or set(link_refs.values()) != expected_links:
        raise ValueError(f"{native_name} native object identity does not match the imported source document")
    return node_refs, link_refs
