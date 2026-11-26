"""GNS3 .gns3 JSON project codec.

The codec intentionally handles the versioned project document, not the live
GNS3 REST provider. Source JSON is retained intact; exports edit only the
supported node placement/label subset.
"""
from __future__ import annotations

import json
from typing import Any

from .contracts import DecodedNativeTopology, EncodedNativeTopology, NativeTopologyCodecError
from .helpers import (
    bounded_int, empty_native_presentation, ensure_unique, finite_number,
    map_node_type, parse_json, require_list, safe_label, stable_id, text,
)


_REVISION_VERSIONS = {7: "2.0", 8: "2.1", 9: "2.2"}


class GNS3TopologyCodec:
    format_id = "GNS3_PROJECT"
    codec_name = "gns3-json"
    codec_version = "1.0"
    extensions = (".gns3",)
    supported_versions = ("2.0", "2.1", "2.2")
    scope = "GNS3 2.0–2.2 project JSON; placement/label edit subset"

    def detect(self, source: bytes, filename: str) -> bool:
        if not filename.lower().endswith(".gns3"):
            return False
        root = parse_json(source)
        return (
            root.get("type") == "topology"
            and isinstance(root.get("topology"), dict)
            and root.get("revision") in _REVISION_VERSIONS
        )

    @staticmethod
    def _port_name(native_node: dict, adapter: int, port: int) -> str:
        ports = native_node.get("ports")
        if isinstance(ports, list):
            for item in ports:
                if not isinstance(item, dict):
                    continue
                adapter_value = item.get("adapter_number", item.get("adapter"))
                port_value = item.get("port_number", item.get("port"))
                if adapter_value == adapter and port_value == port:
                    for field in ("name", "label", "short_name"):
                        value = item.get(field)
                        if isinstance(value, str) and value.strip():
                            return value.strip()[:64]
        return f"adapter{adapter}/port{port}"

    def decode(self, source: bytes, filename: str) -> DecodedNativeTopology:
        root = parse_json(source)
        revision = root.get("revision")
        if revision not in _REVISION_VERSIONS or root.get("type") != "topology":
            raise NativeTopologyCodecError("GNS3 project file revision/type is not supported")
        version = str(root.get("version") or _REVISION_VERSIONS[revision])
        topology = root.get("topology")
        if not isinstance(topology, dict):
            raise ValueError("GNS3 topology must be an object")
        raw_nodes = require_list(topology.get("nodes"), "GNS3 topology.nodes", 128)
        raw_links = require_list(topology.get("links"), "GNS3 topology.links", 512)
        native_nodes: dict[str, dict[str, Any]] = {}
        positions: dict[str, tuple[float, float]] = {}
        for index, node in enumerate(raw_nodes):
            if not isinstance(node, dict):
                raise ValueError(f"GNS3 node {index} must be an object")
            native_id = text(node.get("node_id"), f"nodes[{index}].node_id", maximum=64)
            if native_id in native_nodes:
                raise ValueError("GNS3 project contains duplicate node_id values")
            x = finite_number(node.get("x"), f"nodes[{index}].x")
            y = finite_number(node.get("y"), f"nodes[{index}].y")
            native_nodes[native_id] = node
            positions[native_id] = (x, y)
        if not raw_nodes:
            raise ValueError("GNS3 project has no nodes to import")
        min_x = min(value[0] for value in positions.values())
        min_y = min(value[1] for value in positions.values())
        max_x = max(value[0] for value in positions.values())
        max_y = max(value[1] for value in positions.values())
        if max_x - min_x > 10000 or max_y - min_y > 10000:
            raise ValueError("GNS3 node placement exceeds the canonical topology coordinate span")

        port_names: dict[tuple[str, int, int], str] = {}
        link_rows: list[dict[str, Any]] = []
        used_ports: set[tuple[str, int, int]] = set()
        native_link_ids: list[str] = []
        for index, link in enumerate(raw_links):
            if not isinstance(link, dict):
                raise ValueError(f"GNS3 link {index} must be an object")
            native_link_id = text(link.get("link_id"), f"links[{index}].link_id", maximum=64)
            native_link_ids.append(native_link_id)
            endpoints = require_list(link.get("nodes"), f"links[{index}].nodes", 2)
            if len(endpoints) != 2:
                raise ValueError(f"GNS3 link {index} must contain exactly two endpoints")
            normalized_endpoints = []
            for endpoint_index, endpoint in enumerate(endpoints):
                if not isinstance(endpoint, dict):
                    raise ValueError(f"GNS3 link {index} endpoint {endpoint_index} must be an object")
                native_node_id = text(endpoint.get("node_id"), "GNS3 link endpoint node_id", maximum=64)
                if native_node_id not in native_nodes:
                    raise ValueError(f"GNS3 link {index} references an unknown node")
                adapter = bounded_int(endpoint.get("adapter_number"), "GNS3 adapter_number")
                port = bounded_int(endpoint.get("port_number"), "GNS3 port_number")
                slot = (native_node_id, adapter, port)
                if slot in used_ports:
                    raise ValueError("GNS3 project connects the same adapter/port more than once")
                used_ports.add(slot)
                name = self._port_name(native_nodes[native_node_id], adapter, port)
                previous = port_names.get(slot)
                if previous and previous != name:
                    raise ValueError("GNS3 port name mapping is inconsistent")
                port_names[slot] = name
                normalized_endpoints.append((native_node_id, adapter, port, name))
            link_rows.append({
                "native_id": native_link_id,
                "endpoints": normalized_endpoints,
                "label": safe_label(link.get("label"), ""),
            })
        ensure_unique(native_link_ids, "GNS3 link identifiers")

        definitions = []
        presentations = []
        native_to_logical: dict[str, str] = {}
        for native_id, node in native_nodes.items():
            logical_id = stable_id("gns3_", native_id)
            native_to_logical[native_id] = logical_id
            node_type = str(node.get("node_type") or "unknown")
            canonical_type = map_node_type(node_type, node.get("template_id", ""))
            x, y = positions[native_id]
            interfaces = []
            for (node_id, adapter, port), name in sorted(port_names.items()):
                if node_id == native_id:
                    interfaces.append({
                        "name": name, "adapter": adapter, "port": port,
                        "description": "Imported from GNS3 project port",
                    })
            definitions.append({
                "id": logical_id,
                "name": safe_label(node.get("name"), native_id),
                "node_type": canonical_type,
                "template_id": str(node.get("template_id") or node_type or "")[:128],
                "vendor": "GNS3",
                "operating_system": str(node.get("node_type") or "")[:80],
                "x": round(x - min_x, 3),
                "y": round(y - min_y, 3),
                "interfaces": interfaces,
            })
            presentation = {
                "node_id": logical_id,
                "native_id": native_id,
                "x": x,
                "y": y,
                "label": safe_label(node.get("name"), native_id),
                "z_index": 0,
            }
            if isinstance(node.get("width"), (int, float)) and not isinstance(node.get("width"), bool):
                width = finite_number(node["width"], "GNS3 node width", minimum=1, maximum=2000)
                presentation["width"] = width
            if isinstance(node.get("height"), (int, float)) and not isinstance(node.get("height"), bool):
                height = finite_number(node["height"], "GNS3 node height", minimum=1, maximum=2000)
                presentation["height"] = height
            presentations.append(presentation)

        logical_links = []
        presentation_links = []
        for row in link_rows:
            first, second = row["endpoints"]
            link_id = stable_id("gns3_link_", row["native_id"])
            logical_links.append({
                "id": link_id,
                "source_node_id": native_to_logical[first[0]],
                "source_adapter": first[1],
                "source_port": first[2],
                "source_interface_name": first[3],
                "target_node_id": native_to_logical[second[0]],
                "target_adapter": second[1],
                "target_port": second[2],
                "target_interface_name": second[3],
            })
            presentation_links.append({
                "link_id": link_id,
                "native_id": row["native_id"],
                "route_style": "direct",
                "label": row["label"],
            })

        presentation = empty_native_presentation(self.format_id, version)
        presentation["coordinate_space"].update({"offset_x": min_x, "offset_y": min_y})
        presentation["nodes"] = presentations
        presentation["links"] = presentation_links
        if isinstance(root.get("scene_width"), int) and isinstance(root.get("scene_height"), int):
            presentation["canvas"] = {
                "width": max(1, min(root["scene_width"], 100000)),
                "height": max(1, min(root["scene_height"], 100000)),
            }
        if isinstance(root.get("zoom"), (int, float)) and not isinstance(root.get("zoom"), bool):
            zoom = float(root["zoom"])
            if 0.01 <= zoom <= 100:
                presentation["viewport"] = {
                    "x": min_x, "y": min_y,
                    "width": 1000.0, "height": 620.0, "zoom": zoom,
                }

        warnings = []
        if topology.get("drawings"):
            warnings.append("GNS3 drawing SVG objects remain preserved in the immutable source; they are not editable in the shared v1 presentation canvas.")
        if any(node.get("ports") for node in raw_nodes):
            warnings.append("GNS3 native port metadata not referenced by a link remains preserved in the source document.")
        warnings.append("Compute bindings, node configurations, console settings and external project assets are retained in the source document and are not interpreted as execution instructions.")
        return DecodedNativeTopology(
            format_id=self.format_id,
            format_version=version,
            filename=filename,
            topology_definition={"nodes": definitions, "links": logical_links},
            presentation=presentation,
            metadata={
                "native_project_name": safe_label(root.get("name"), filename),
                "file_format_revision": revision,
                "source_project_id": root.get("project_id"),
            },
            warnings=tuple(warnings),
        )

    def encode(self, topology_definition, presentation, *, original_source, filename):
        root = parse_json(original_source)
        revision = root.get("revision")
        version = str(root.get("version") or _REVISION_VERSIONS.get(revision, ""))
        if revision not in _REVISION_VERSIONS or root.get("type") != "topology":
            raise NativeTopologyCodecError("GNS3 source version is not supported for export")
        topology = root["topology"]
        nodes = require_list(topology.get("nodes"), "GNS3 topology.nodes", 128)
        links = require_list(topology.get("links"), "GNS3 topology.links", 512)
        expected_nodes = {str(item.get("node_id")) for item in nodes}
        expected_links = {str(item.get("link_id")) for item in links}
        from .helpers import compare_native_identity
        node_map, link_map = compare_native_identity(
            expected_nodes, expected_links, topology_definition, presentation,
            native_name="GNS3",
        )
        by_id = {
            str(item.get("node_id")): item
            for item in presentation.get("nodes", [])
            if item.get("native_id") is not None
        }
        for item in nodes:
            native_id = str(item.get("node_id"))
            view = by_id[node_map[next(key for key, value in node_map.items() if value == native_id)]]
            if "x" in view:
                item["x"] = int(round(float(view["x"])))
            if "y" in view:
                item["y"] = int(round(float(view["y"])))
            if view.get("label"):
                item["name"] = str(view["label"])
        link_views = {
            str(item.get("native_id")): item
            for item in presentation.get("links", [])
            if item.get("native_id") is not None
        }
        for item in links:
            view = link_views.get(str(item.get("link_id")))
            if view is not None and view.get("label") is not None:
                item["label"] = str(view["label"])
        encoded = json.dumps(root, ensure_ascii=False, allow_nan=False, indent=4).encode("utf-8") + b"\n"
        return EncodedNativeTopology(
            format_id=self.format_id, format_version=version,
            filename=filename if filename.lower().endswith(".gns3") else filename + ".gns3",
            media_type="application/json", content=encoded,
            losses=("Node position/label and link label are the supported edit subset; all other native source fields are retained unchanged.",),
        )
