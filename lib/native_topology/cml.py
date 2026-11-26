"""Cisco Modeling Labs YAML and bounded legacy VIRL XML codecs."""
from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from typing import Any

import yaml

from .contracts import DecodedNativeTopology, EncodedNativeTopology, NativeTopologyCodecError
from .helpers import (
    bounded_int, compare_native_identity, empty_native_presentation, ensure_unique,
    finite_number, local_name, map_node_type, parse_xml, parse_yaml, safe_label,
    stable_id, text,
)


_CML_YAML_VERSION = re.compile(r"^0\\.1\\.\\d+$")
_VIRL_SCHEMA_VERSION = "0.95"


class CMLTopologyCodec:
    format_id = "CML_LAB"
    codec_name = "cml-yaml-virl"
    codec_version = "1.0"
    extensions = (".yaml", ".yml", ".virl")
    supported_versions = ("CML lab schema 0.1.x", "VIRL schema 0.95 subset")
    scope = "CML lab YAML 0.1.x and legacy VIRL 0.95 node/connection subset"

    def detect(self, source: bytes, filename: str) -> bool:
        suffix = filename.lower()
        if suffix.endswith(".virl"):
            root = parse_xml(source, expected_root="topology")
            return root.attrib.get("schemaVersion") == _VIRL_SCHEMA_VERSION
        if suffix.endswith((".yaml", ".yml")):
            root = parse_yaml(source)
            lab = root.get("lab")
            version = str(lab.get("version", "")) if isinstance(lab, dict) else ""
            return (
                _CML_YAML_VERSION.fullmatch(version) is not None
                and isinstance(root.get("nodes"), list)
                and isinstance(root.get("links"), list)
            )
        return False

    @staticmethod
    def _position_bounds(positions):
        if not positions:
            raise ValueError("CML/VIRL project contains no topology nodes")
        min_x = min(point[0] for point in positions.values())
        min_y = min(point[1] for point in positions.values())
        max_x = max(point[0] for point in positions.values())
        max_y = max(point[1] for point in positions.values())
        if max_x - min_x > 10000 or max_y - min_y > 10000:
            raise ValueError("CML/VIRL node placement exceeds canonical coordinate span")
        return min_x, min_y

    def decode(self, source: bytes, filename: str) -> DecodedNativeTopology:
        if filename.lower().endswith(".virl"):
            return self._decode_virl(source, filename)
        return self._decode_yaml(source, filename)

    def _decode_yaml(self, source: bytes, filename: str) -> DecodedNativeTopology:
        root = parse_yaml(source)
        lab = root.get("lab")
        if not isinstance(lab, dict):
            raise ValueError("CML YAML lab metadata is missing")
        schema_version = str(lab.get("version", ""))
        if not _CML_YAML_VERSION.fullmatch(schema_version):
            raise NativeTopologyCodecError(
                "CML lab YAML schema version is outside the supported 0.1.x family"
            )
        raw_nodes = root.get("nodes")
        raw_links = root.get("links")
        if not isinstance(raw_nodes, list) or len(raw_nodes) > 128:
            raise ValueError("CML YAML nodes must contain at most 128 entries")
        if not isinstance(raw_links, list) or len(raw_links) > 512:
            raise ValueError("CML YAML links must contain at most 512 entries")

        nodes_by_native: dict[str, dict[str, Any]] = {}
        positions = {}
        interface_maps: dict[str, dict[str, tuple[int, str]]] = {}
        for index, node in enumerate(raw_nodes):
            if not isinstance(node, dict):
                raise ValueError(f"CML YAML node {index} must be a mapping")
            native_id = text(node.get("id"), f"CML nodes[{index}].id", maximum=64)
            if native_id in nodes_by_native:
                raise ValueError("CML YAML has duplicate node IDs")
            nodes_by_native[native_id] = node
            positions[native_id] = (
                finite_number(node.get("x"), f"CML node {native_id} x"),
                finite_number(node.get("y"), f"CML node {native_id} y"),
            )
            raw_interfaces = node.get("interfaces", [])
            if not isinstance(raw_interfaces, list) or len(raw_interfaces) > 64:
                raise ValueError(f"CML node {native_id} interfaces must contain at most 64 entries")
            names = {}
            normalized_interfaces = []
            for port_index, interface in enumerate(raw_interfaces):
                if not isinstance(interface, dict):
                    raise ValueError(f"CML node {native_id} interface {port_index} must be a mapping")
                interface_id = text(interface.get("id"), "CML interface id", maximum=64)
                if interface_id in names:
                    raise ValueError(f"CML node {native_id} has duplicate interface IDs")
                interface_name = safe_label(interface.get("label"), interface_id)
                names[interface_id] = (port_index, interface_name)
                normalized_interfaces.append({
                    "name": interface_name, "adapter": 0, "port": port_index,
                    "description": "Imported CML interface",
                })
            interface_maps[native_id] = names
            node["_netregress_interfaces"] = normalized_interfaces

        min_x, min_y = self._position_bounds(positions)
        definitions = []
        presentations = []
        logical_by_native = {}
        for native_id, node in nodes_by_native.items():
            logical_id = stable_id("cml_", native_id)
            logical_by_native[native_id] = logical_id
            node_definition = text(node.get("node_definition"), f"CML node {native_id} node_definition", maximum=128)
            x, y = positions[native_id]
            definitions.append({
                "id": logical_id,
                "name": safe_label(node.get("label"), native_id),
                "node_type": map_node_type(node_definition, node_definition),
                "template_id": node_definition,
                "vendor": "Cisco",
                "operating_system": node_definition[:80],
                "x": round(x - min_x, 3),
                "y": round(y - min_y, 3),
                "interfaces": node["_netregress_interfaces"],
            })
            presentations.append({
                "node_id": logical_id, "native_id": native_id,
                "x": x, "y": y, "label": safe_label(node.get("label"), native_id),
            })
            node.pop("_netregress_interfaces", None)

        logical_links = []
        presentation_links = []
        native_link_ids = []
        endpoint_use = set()
        for index, link in enumerate(raw_links):
            if not isinstance(link, dict):
                raise ValueError(f"CML link {index} must be a mapping")
            native_id = text(link.get("id"), f"CML links[{index}].id", maximum=64)
            native_link_ids.append(native_id)
            n1 = text(link.get("n1"), f"CML link {native_id}.n1", maximum=64)
            n2 = text(link.get("n2"), f"CML link {native_id}.n2", maximum=64)
            i1 = text(link.get("i1"), f"CML link {native_id}.i1", maximum=64)
            i2 = text(link.get("i2"), f"CML link {native_id}.i2", maximum=64)
            if n1 not in logical_by_native or n2 not in logical_by_native:
                raise ValueError(f"CML link {native_id} references an unknown node")
            if i1 not in interface_maps[n1] or i2 not in interface_maps[n2]:
                raise ValueError(f"CML link {native_id} references an unknown interface")
            p1, name1 = interface_maps[n1][i1]
            p2, name2 = interface_maps[n2][i2]
            if (n1, p1) in endpoint_use or (n2, p2) in endpoint_use:
                raise ValueError("CML YAML connects one physical interface more than once")
            endpoint_use.add((n1, p1))
            endpoint_use.add((n2, p2))
            link_id = stable_id("cml_link_", native_id)
            logical_links.append({
                "id": link_id,
                "source_node_id": logical_by_native[n1],
                "source_adapter": 0, "source_port": p1, "source_interface_name": name1,
                "target_node_id": logical_by_native[n2],
                "target_adapter": 0, "target_port": p2, "target_interface_name": name2,
            })
            presentation_links.append({
                "link_id": link_id, "native_id": native_id, "route_style": "direct",
                "label": safe_label(link.get("label"), ""),
            })
        ensure_unique(native_link_ids, "CML link identifiers")

        presentation = empty_native_presentation(self.format_id, schema_version)
        presentation["coordinate_space"].update({"offset_x": min_x, "offset_y": min_y})
        presentation["nodes"] = presentations
        presentation["links"] = presentation_links
        annotations = root.get("annotations", [])
        warnings = []
        if annotations:
            if not isinstance(annotations, list) or len(annotations) > 1000:
                raise ValueError("CML annotations must contain at most 1000 entries")
            drawings = []
            for index, annotation in enumerate(annotations):
                if not isinstance(annotation, dict):
                    warnings.append(f"CML annotation {index} is not a mapping and remains source-only.")
                    continue
                kind = str(annotation.get("type", "")).lower()
                if kind not in {"rectangle", "ellipse", "text", "line"}:
                    warnings.append(f"CML annotation {index} type {kind!r} remains source-only.")
                    continue
                x1 = finite_number(annotation.get("x1", 0), f"CML annotation {index} x1")
                y1 = finite_number(annotation.get("y1", 0), f"CML annotation {index} y1")
                item = {
                    "id": stable_id("cml_draw_", index),
                    "native_id": str(index),
                    "kind": kind.upper(),
                    "x": x1, "y": y1,
                    "z_index": bounded_int(annotation.get("z_index", 0), "CML annotation z_index", minimum=-100000, maximum=100000),
                    "extensions": {"cml": {"annotation_type": kind}},
                }
                if kind == "line":
                    item["points"] = [
                        {"x": x1, "y": y1},
                        {"x": finite_number(annotation.get("x2", x1), "CML annotation x2"),
                         "y": finite_number(annotation.get("y2", y1), "CML annotation y2")},
                    ]
                elif kind in {"rectangle", "ellipse"}:
                    x2 = finite_number(annotation.get("x2", x1), f"CML annotation {index} x2")
                    y2 = finite_number(annotation.get("y2", y1), f"CML annotation {index} y2")
                    item.update({"x": min(x1, x2), "y": min(y1, y2),
                                 "width": abs(x2 - x1), "height": abs(y2 - y1)})
                else:
                    item["text"] = safe_label(annotation.get("text_content", annotation.get("text")), "")
                style = {}
                stroke = annotation.get("border_color") or annotation.get("color")
                fill = annotation.get("color") if kind in {"rectangle", "ellipse"} else None
                if isinstance(stroke, str) and stroke:
                    style["stroke"] = stroke[:64]
                if isinstance(fill, str) and fill:
                    style["fill"] = fill[:64]
                thickness = annotation.get("thickness")
                if isinstance(thickness, (int, float)) and not isinstance(thickness, bool):
                    style["stroke_width"] = max(0, min(64, float(thickness)))
                font = annotation.get("text_font")
                if isinstance(font, str) and font:
                    style["font_family"] = font[:80]
                font_size = annotation.get("text_size")
                if isinstance(font_size, (int, float)) and not isinstance(font_size, bool) and 4 <= font_size <= 256:
                    style["font_size"] = float(font_size)
                dash = annotation.get("border_style")
                if isinstance(dash, str) and dash:
                    style["dash"] = dash[:32]
                if style:
                    item["style"] = style
                drawings.append(item)
            presentation["drawings"] = drawings
        warnings.append("Node startup configurations and lab metadata are retained in the immutable native YAML source; they are not executed or copied into canonical topology properties.")
        return DecodedNativeTopology(
            format_id=self.format_id, format_version=schema_version, filename=filename,
            topology_definition={"nodes": definitions, "links": logical_links},
            presentation=presentation,
            metadata={
                "native_project_name": safe_label(lab.get("title"), filename),
                "lab_version": schema_version,
                "lab_description": safe_label(lab.get("description"), ""),
            },
            warnings=tuple(warnings),
        )

    def _decode_virl(self, source: bytes, filename: str) -> DecodedNativeTopology:
        root = parse_xml(source, expected_root="topology")
        version = str(root.attrib.get("schemaVersion") or "")
        if version != _VIRL_SCHEMA_VERSION:
            raise NativeTopologyCodecError(
                "legacy VIRL schema version is not supported; expected 0.95"
            )
        native_nodes = [item for item in list(root) if local_name(item.tag) == "node"]
        if not native_nodes or len(native_nodes) > 128:
            raise ValueError("legacy VIRL topology must contain 1 to 128 top-level nodes")
        node_names = []
        positions = {}
        interfaces = {}
        for index, node in enumerate(native_nodes, start=1):
            if node.attrib.get("type") != "SIMPLE":
                raise ValueError(
                    f"legacy VIRL node[{index}] is outside the supported SIMPLE-node subset"
                )
            name = text(node.attrib.get("name"), f"VIRL node[{index}].name", maximum=120)
            if name in positions:
                raise ValueError("legacy VIRL node names must be unique")
            node_names.append(name)
            location = node.attrib.get("location", "0,0")
            parts = location.split(",")
            if len(parts) != 2:
                raise ValueError(f"VIRL node {name} has an invalid location")
            positions[name] = (
                finite_number(float(parts[0]), f"VIRL node {name} x"),
                finite_number(float(parts[1]), f"VIRL node {name} y"),
            )
            interfaces[name] = [
                item for item in list(node) if local_name(item.tag) == "interface"
            ]
            if len(interfaces[name]) > 64:
                raise ValueError(f"VIRL node {name} has too many interfaces")
        min_x, min_y = self._position_bounds(positions)
        logical_by_name = {}
        definitions = []
        presentations = []
        for index, node in enumerate(native_nodes, start=1):
            name = node.attrib["name"]
            logical_id = stable_id("virl_", name)
            logical_by_name[name] = logical_id
            subtype = node.attrib.get("subtype", node.attrib.get("type", ""))
            intfs = []
            for port_index, interface in enumerate(interfaces[name]):
                interface_name = safe_label(interface.attrib.get("name"), f"interface{port_index}")
                intfs.append({"name": interface_name, "adapter": 0, "port": port_index})
            x, y = positions[name]
            definitions.append({
                "id": logical_id, "name": name,
                "node_type": map_node_type(subtype, node.attrib.get("type", "")),
                "template_id": subtype[:128],
                "vendor": "Cisco", "operating_system": subtype[:80],
                "x": round(x - min_x, 3), "y": round(y - min_y, 3),
                "interfaces": intfs,
            })
            presentations.append({
                "node_id": logical_id, "native_id": name,
                "x": x, "y": y, "label": name,
            })

        logical_links = []
        presentations_links = []
        connections = [item for item in list(root) if local_name(item.tag) == "connection"]
        if len(connections) > 512:
            raise ValueError("legacy VIRL connection count exceeds 512")
        endpoint_use = set()
        path_pattern = re.compile(r"/(?:[^/]+:)?topology/(?:[^/]+:)?node\[(\d+)\]/(?:[^/]+:)?interface\[(\d+)\]$")
        for index, connection in enumerate(connections):
            resolved = []
            for side in ("src", "dst"):
                path = connection.attrib.get(side, "")
                match = path_pattern.search(path)
                if not match:
                    raise ValueError(f"legacy VIRL connection {index} has an unsupported {side} XPath")
                node_index, interface_index = int(match.group(1)), int(match.group(2))
                if not 1 <= node_index <= len(native_nodes):
                    raise ValueError(f"legacy VIRL connection {index} references an unknown node")
                node_name = node_names[node_index - 1]
                if not 1 <= interface_index <= len(interfaces[node_name]):
                    raise ValueError(f"legacy VIRL connection {index} references an unknown interface")
                port = interface_index - 1
                interface_name = safe_label(interfaces[node_name][port].attrib.get("name"), f"interface{port}")
                if (node_name, port) in endpoint_use:
                    raise ValueError("legacy VIRL connects one interface more than once")
                endpoint_use.add((node_name, port))
                resolved.append((node_name, port, interface_name))
            first, second = resolved
            link_id = stable_id("virl_link_", index)
            logical_links.append({
                "id": link_id,
                "source_node_id": logical_by_name[first[0]],
                "source_adapter": 0, "source_port": first[1], "source_interface_name": first[2],
                "target_node_id": logical_by_name[second[0]],
                "target_adapter": 0, "target_port": second[1], "target_interface_name": second[2],
            })
            presentations_links.append({"link_id": link_id, "native_id": str(index), "route_style": "direct"})

        presentation = empty_native_presentation(self.format_id, "VIRL-" + version)
        presentation["coordinate_space"].update({"offset_x": min_x, "offset_y": min_y})
        presentation["nodes"] = presentations
        presentation["links"] = presentations_links
        return DecodedNativeTopology(
            format_id=self.format_id, format_version="VIRL-" + version, filename=filename,
            topology_definition={"nodes": definitions, "links": logical_links},
            presentation=presentation,
            metadata={"native_project_name": safe_label(root.attrib.get("name"), filename), "legacy_virl_schema": version},
            warnings=(
                "Legacy VIRL support is limited to SIMPLE node declarations, native interface ordering, node location and XPath connections.",
                "VIRL startup configurations and extensions remain source-only and are never executed.",
                "Legacy VIRL export rewrites XML serialization; desktop VM Maestro reopen remains an external acceptance gate.",
            ),
        )

    def encode(self, topology_definition, presentation, *, original_source, filename):
        if filename.lower().endswith(".virl"):
            return self._encode_virl(topology_definition, presentation, original_source, filename)
        return self._encode_yaml(topology_definition, presentation, original_source, filename)

    def _encode_yaml(self, topology_definition, presentation, original_source, filename):
        root = parse_yaml(original_source)
        native_nodes = root.get("nodes", [])
        native_links = root.get("links", [])
        native_node_ids = {str(item.get("id")) for item in native_nodes}
        native_link_ids = {str(item.get("id")) for item in native_links}
        node_map, _ = compare_native_identity(native_node_ids, native_link_ids, topology_definition, presentation, native_name="CML")
        node_views = {str(item.get("native_id")): item for item in presentation.get("nodes", [])}
        for node in native_nodes:
            view = node_views[str(node.get("id"))]
            node["x"] = int(round(float(view.get("x", node.get("x", 0)))))
            node["y"] = int(round(float(view.get("y", node.get("y", 0)))))
            if view.get("label"):
                node["label"] = str(view["label"])
        link_views = {str(item.get("native_id")): item for item in presentation.get("links", [])}
        for link in native_links:
            view = link_views.get(str(link.get("id")))
            if view and view.get("label") is not None:
                link["label"] = str(view["label"])
        annotations = root.get("annotations", [])
        drawings = presentation.get("drawings", [])
        drawing_by_native = {str(item.get("native_id")): item for item in drawings if item.get("native_id") is not None}
        for index, annotation in enumerate(annotations):
            view = drawing_by_native.get(str(index))
            if view is None:
                continue
            kind = str(annotation.get("type", "")).lower()
            if kind in {"rectangle", "ellipse"}:
                x, y = float(view.get("x", annotation.get("x1", 0))), float(view.get("y", annotation.get("y1", 0)))
                annotation["x1"], annotation["y1"] = x, y
                annotation["x2"] = x + float(view.get("width", 0))
                annotation["y2"] = y + float(view.get("height", 0))
            elif kind == "line":
                points = view.get("points", [])
                if len(points) >= 2:
                    annotation["x1"], annotation["y1"] = points[0]["x"], points[0]["y"]
                    annotation["x2"], annotation["y2"] = points[1]["x"], points[1]["y"]
            else:
                annotation["x1"], annotation["y1"] = view.get("x", 0), view.get("y", 0)
                if "text" in view:
                    annotation["text_content"] = str(view["text"])
            style = view.get("style", {})
            if not isinstance(style, dict):
                raise ValueError("CML annotation presentation style must be an object")
            if "stroke" in style:
                annotation["border_color"] = str(style["stroke"])
            if "fill" in style:
                annotation["color"] = str(style["fill"])
            elif kind == "text" and "stroke" in style:
                annotation["color"] = str(style["stroke"])
            if "stroke_width" in style:
                annotation["thickness"] = float(style["stroke_width"])
            if "font_family" in style:
                annotation["text_font"] = str(style["font_family"])
            if "font_size" in style:
                annotation["text_size"] = float(style["font_size"])
            if "dash" in style:
                annotation["border_style"] = str(style["dash"])
        payload = yaml.safe_dump(root, sort_keys=False, allow_unicode=True, default_flow_style=False).encode("utf-8")
        version = str(root.get("lab", {}).get("version", "0.1.0"))
        return EncodedNativeTopology(
            format_id=self.format_id, format_version=version,
            filename=filename if filename.lower().endswith((".yaml", ".yml")) else filename + ".yaml",
            media_type="application/yaml", content=payload,
            losses=("CML YAML serializer preserves mapped and unknown YAML fields; startup configuration contents are never applied or modified.",),
        )

    def _encode_virl(self, topology_definition, presentation, original_source, filename):
        root = parse_xml(original_source, expected_root="topology")
        if root.attrib.get("schemaVersion") != _VIRL_SCHEMA_VERSION:
            raise NativeTopologyCodecError("legacy VIRL schema version is not supported")
        nodes = [item for item in list(root) if local_name(item.tag) == "node"]
        if any(item.attrib.get("type") != "SIMPLE" for item in nodes):
            raise NativeTopologyCodecError(
                "legacy VIRL export is limited to the supported SIMPLE-node subset"
            )
        connections = [item for item in list(root) if local_name(item.tag) == "connection"]
        native_ids = {str(item.attrib.get("name")) for item in nodes}
        link_ids = {str(index) for index in range(len(connections))}
        compare_native_identity(native_ids, link_ids, topology_definition, presentation, native_name="legacy VIRL")
        views = {str(item.get("native_id")): item for item in presentation.get("nodes", [])}
        for node in nodes:
            view = views[str(node.attrib["name"])]
            node.attrib["location"] = f"{int(round(float(view.get('x', 0))))},{int(round(float(view.get('y', 0))))}"
            if view.get("label"):
                node.attrib["name"] = str(view["label"])
        namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
        if namespace:
            ET.register_namespace("", namespace)
        ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
        content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return EncodedNativeTopology(
            format_id=self.format_id, format_version="VIRL-" + str(root.attrib.get("schemaVersion", "unknown")),
            filename=filename, media_type="application/xml", content=content,
            losses=("Only native node placement/labels are edited; legacy VIRL connections, extensions and startup configuration are retained. XML formatting/comments may be normalized.",),
        )
