"""EVE-NG .unl XML lab codec with explicit shared-network semantics."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from .contracts import DecodedNativeTopology, EncodedNativeTopology, NativeTopologyCodecError
from .helpers import (
    bounded_int, compare_native_identity, empty_native_presentation,
    ensure_unique, finite_number, local_name, map_node_type, parse_xml,
    safe_label, stable_id, text,
)


class EVENGTopologyCodec:
    format_id = "EVE_NG_UNL"
    codec_name = "eve-ng-unl-xml"
    codec_version = "1.0"
    extensions = (".unl",)
    supported_versions = ("1", "2")
    scope = "EVE-NG .unl lab topology and network segment edit subset"

    def detect(self, source: bytes, filename: str) -> bool:
        if not filename.lower().endswith(".unl"):
            return False
        root = parse_xml(source, expected_root="lab")
        return root.attrib.get("version") in self.supported_versions and any(
            local_name(child.tag) == "topology" for child in list(root)
        )

    @staticmethod
    def _children(parent, name):
        # EVE .unl declares interfaces as direct children of each <node>;
        # <nodes> and <networks> are wrapper containers.
        if name == "interfaces":
            return [item for item in list(parent) if local_name(item.tag) == "interface"]
        container = next((item for item in list(parent) if local_name(item.tag) == name), None)
        return list(container) if container is not None else []

    def decode(self, source: bytes, filename: str) -> DecodedNativeTopology:
        root = parse_xml(source, expected_root="lab")
        version = str(root.attrib.get("version", ""))
        if version not in self.supported_versions:
            raise NativeTopologyCodecError("EVE-NG .unl version is not supported")
        topology = next((item for item in list(root) if local_name(item.tag) == "topology"), None)
        if topology is None:
            raise ValueError("EVE-NG .unl topology element is missing")
        raw_nodes = self._children(topology, "nodes")
        raw_networks = self._children(topology, "networks")
        if not raw_nodes or len(raw_nodes) > 128 or len(raw_networks) > 512:
            raise ValueError("EVE-NG lab must contain 1–128 devices and at most 512 networks")

        native_nodes: dict[str, ET.Element] = {}
        positions: dict[str, tuple[float, float]] = {}
        interfaces_by_node: dict[str, list[ET.Element]] = {}
        interface_indexes: dict[tuple[str, str], int] = {}
        for index, node in enumerate(raw_nodes):
            native_id = text(node.attrib.get("id"), f"EVE node[{index}].id", maximum=64)
            if native_id in native_nodes:
                raise ValueError("EVE-NG lab contains duplicate node IDs")
            native_nodes[native_id] = node
            positions[native_id] = (
                finite_number(float(node.attrib.get("left", "0")), "EVE node left"),
                finite_number(float(node.attrib.get("top", "0")), "EVE node top"),
            )
            interfaces = self._children(node, "interfaces")
            if len(interfaces) > 64:
                raise ValueError(f"EVE node {native_id} has more than 64 interfaces")
            ids = []
            for port_index, interface in enumerate(interfaces):
                interface_id = text(interface.attrib.get("id"), "EVE interface id", maximum=64)
                ids.append(interface_id)
                interface_indexes[(native_id, interface_id)] = port_index
            ensure_unique(ids, f"EVE node {native_id} interface IDs")
            interfaces_by_node[native_id] = interfaces
        network_by_id: dict[str, ET.Element] = {}
        network_positions = {}
        for index, network in enumerate(raw_networks):
            native_id = text(network.attrib.get("id"), f"EVE network[{index}].id", maximum=64)
            if native_id in network_by_id:
                raise ValueError("EVE-NG lab contains duplicate network IDs")
            network_by_id[native_id] = network
            network_positions[native_id] = (
                finite_number(float(network.attrib.get("left", "0")), "EVE network left"),
                finite_number(float(network.attrib.get("top", "0")), "EVE network top"),
            )

        all_positions = {**positions, **{f"network:{key}": value for key, value in network_positions.items()}}
        if not all_positions:
            raise ValueError("EVE-NG .unl contains no placed objects")
        min_x = min(value[0] for value in all_positions.values())
        min_y = min(value[1] for value in all_positions.values())
        max_x = max(value[0] for value in all_positions.values())
        max_y = max(value[1] for value in all_positions.values())
        if max_x - min_x > 10000 or max_y - min_y > 10000:
            raise ValueError("EVE-NG placement exceeds canonical topology coordinate span")

        logical_by_native = {native_id: stable_id("eve_", native_id) for native_id in native_nodes}
        network_logical = {native_id: stable_id("eve_net_", native_id) for native_id in network_by_id}
        definitions = []
        presentation_nodes = []
        network_members: dict[str, list[tuple[str, ET.Element, int, str]]] = {
            key: [] for key in network_by_id
        }
        for native_id, node in native_nodes.items():
            name = safe_label(node.attrib.get("name"), native_id)
            template = str(node.attrib.get("template") or node.attrib.get("type") or "")
            interfaces = []
            ports_presentation = []
            for port_index, interface in enumerate(interfaces_by_node[native_id]):
                interface_id = str(interface.attrib.get("id"))
                network_id = str(interface.attrib.get("network_id", "")).strip()
                interface_name = safe_label(interface.attrib.get("name"), f"interface{port_index}")
                interfaces.append({"name": interface_name, "adapter": 0, "port": port_index})
                ports_presentation.append({
                    "interface_name": interface_name, "adapter": 0, "port": port_index,
                    "native_id": interface_id,
                })
                if network_id:
                    if network_id not in network_by_id:
                        raise ValueError(f"EVE interface {native_id}/{interface_id} references an unknown network")
                    network_members[network_id].append((native_id, interface, port_index, interface_name))
            x, y = positions[native_id]
            definitions.append({
                "id": logical_by_native[native_id], "name": name,
                "node_type": map_node_type(node.attrib.get("type"), template),
                "template_id": template[:128],
                "vendor": "EVE-NG", "operating_system": template[:80],
                "image": str(node.attrib.get("image", ""))[:128],
                "x": round(x - min_x, 3), "y": round(y - min_y, 3),
                "interfaces": interfaces,
            })
            presentation_nodes.append({
                "node_id": logical_by_native[native_id], "native_id": "node:" + native_id,
                "x": x, "y": y, "label": name, "ports": ports_presentation,
            })

        logical_links = []
        presentation_links = []
        for native_id, network in network_by_id.items():
            network_type = str(network.attrib.get("type") or "bridge").lower()
            segment_type = "CLOUD" if network_type in {"pnet", "cloud", "nat"} else "SWITCH"
            segment_name = safe_label(network.attrib.get("name"), "Network " + native_id)
            network_ports = []
            members = network_members[native_id]
            if len(members) > 64:
                raise ValueError(f"EVE network {native_id} has more than 64 attached interfaces")
            for port_index, (node_native, interface, node_port, interface_name) in enumerate(members):
                network_ports.append({"name": f"member-{port_index}", "adapter": 0, "port": port_index})
                link_id = stable_id("eve_link_", native_id + ":" + node_native + ":" + str(interface.attrib.get("id")))
                logical_links.append({
                    "id": link_id,
                    "source_node_id": logical_by_native[node_native],
                    "source_adapter": 0, "source_port": node_port,
                    "source_interface_name": interface_name,
                    "target_node_id": network_logical[native_id],
                    "target_adapter": 0, "target_port": port_index,
                    "target_interface_name": f"member-{port_index}",
                })
                presentation_links.append({
                    "link_id": link_id,
                    "native_id": "interface:" + node_native + ":" + str(interface.attrib.get("id")),
                    "route_style": "direct",
                })
            definitions.append({
                "id": network_logical[native_id],
                "name": segment_name, "node_type": segment_type,
                "template_id": "EVE_NETWORK_" + network_type.upper(),
                "vendor": "EVE-NG", "operating_system": network_type,
                "x": round(network_positions[native_id][0] - min_x, 3),
                "y": round(network_positions[native_id][1] - min_y, 3),
                "interfaces": network_ports,
            })
            presentation_nodes.append({
                "node_id": network_logical[native_id],
                "native_id": "network:" + native_id,
                "x": network_positions[native_id][0], "y": network_positions[native_id][1],
                "label": segment_name,
            })

        presentation = empty_native_presentation(self.format_id, version)
        presentation["coordinate_space"].update({"offset_x": min_x, "offset_y": min_y})
        presentation["nodes"] = presentation_nodes
        presentation["links"] = presentation_links
        warnings = [
            "EVE-NG network bridge objects are represented as explicit logical segment nodes, preserving one-to-many attachment semantics in the canonical point-to-point link model.",
            "Node configuration files, image payloads, startup state and external EVE-NG assets are retained only in the original .unl/project environment; the .unl source itself does not embed external image files.",
        ]
        return DecodedNativeTopology(
            format_id=self.format_id, format_version=version, filename=filename,
            topology_definition={"nodes": definitions, "links": logical_links},
            presentation=presentation,
            metadata={
                "native_project_name": safe_label(root.attrib.get("name"), filename),
                "native_project_id": root.attrib.get("id"),
                "author": safe_label(root.attrib.get("author"), ""),
            },
            warnings=tuple(warnings),
        )

    def encode(self, topology_definition, presentation, *, original_source, filename):
        root = parse_xml(original_source, expected_root="lab")
        topology = next((item for item in list(root) if local_name(item.tag) == "topology"), None)
        if topology is None:
            raise ValueError("EVE-NG topology element is missing")
        nodes = self._children(topology, "nodes")
        networks = self._children(topology, "networks")
        native_node_ids = {str(item.attrib.get("id")) for item in nodes}
        native_network_ids = {str(item.attrib.get("id")) for item in networks}
        expected_nodes = {"node:" + value for value in native_node_ids} | {"network:" + value for value in native_network_ids}
        expected_links = set()
        for node in nodes:
            node_id = str(node.attrib.get("id"))
            for interface in self._children(node, "interfaces"):
                network_id = str(interface.attrib.get("network_id", "")).strip()
                if network_id:
                    expected_links.add("interface:" + node_id + ":" + str(interface.attrib.get("id")))
        node_map, _ = compare_native_identity(
            expected_nodes, expected_links, topology_definition, presentation, native_name="EVE-NG",
        )
        views = {str(item.get("native_id")): item for item in presentation.get("nodes", [])}
        for node in nodes:
            view = views["node:" + str(node.attrib.get("id"))]
            node.attrib["left"] = str(int(round(float(view.get("x", node.attrib.get("left", 0))))))
            node.attrib["top"] = str(int(round(float(view.get("y", node.attrib.get("top", 0))))))
            if view.get("label"):
                node.attrib["name"] = str(view["label"])
        for network in networks:
            view = views["network:" + str(network.attrib.get("id"))]
            network.attrib["left"] = str(int(round(float(view.get("x", network.attrib.get("left", 0))))))
            network.attrib["top"] = str(int(round(float(view.get("y", network.attrib.get("top", 0))))))
            if view.get("label"):
                network.attrib["name"] = str(view["label"])
        namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
        if namespace:
            ET.register_namespace("", namespace)
        content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return EncodedNativeTopology(
            format_id=self.format_id, format_version=str(root.attrib.get("version", "unknown")),
            filename=filename, media_type="application/xml", content=content,
            losses=("Device/network placement and labels are the supported edit subset; native interfaces, network IDs, device images, config references and unknown XML attributes are preserved unchanged.",),
        )
