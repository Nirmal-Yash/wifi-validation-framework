"""Cisco Packet Tracer .pkt codec built on the existing pinned P07-B implementation.

This adapter joins the established bounded pktlib parser/serializer to the
generic native-topology provenance lifecycle. It intentionally supports only
the existing node-name and X/Y presentation write subset.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

from .contracts import DecodedNativeTopology, EncodedNativeTopology, NativeTopologyCodecError
from .helpers import empty_native_presentation
from lib.services.packet_tracer_interop import (
    PacketTracerInteropError,
    PacketTracerInteropService,
)
from lib.services.topology_studio import TopologyStudioService


class PacketTracerTopologyCodec:
    format_id = "CISCO_PACKET_TRACER_PKT"
    codec_name = "pktlib"
    codec_version = PacketTracerInteropService._codec_version()
    extensions = (".pkt",)
    supported_versions = ("8.2.0",)
    scope = "Packet Tracer .pkt; pktlib strict decode; device name and placement export"

    MAX_SOURCE_BYTES = PacketTracerInteropService.MAX_SOURCE_BYTES

    @classmethod
    def _load(cls, source: bytes):
        try:
            raw = PacketTracerInteropService._source_bytes(source)
            return PacketTracerInteropService._load(raw)
        except (PacketTracerInteropError, TypeError, ValueError) as exc:
            raise NativeTopologyCodecError(str(exc)) from exc

    def detect(self, source: bytes, filename: str) -> bool:
        if not isinstance(filename, str) or not filename.lower().endswith(".pkt"):
            return False
        self._load(source)
        return True

    def decode(self, source: bytes, filename: str) -> DecodedNativeTopology:
        if not isinstance(filename, str) or not filename.lower().endswith(".pkt"):
            raise NativeTopologyCodecError("Packet Tracer codec requires a .pkt filename")
        network = self._load(source)
        try:
            definition, mapping, report = PacketTracerInteropService._convert_network(network)
        except (PacketTracerInteropError, TypeError, ValueError, KeyError) as exc:
            raise NativeTopologyCodecError(str(exc)) from exc

        version = str(network.version or network.edition or "unknown")[:32]
        presentation = empty_native_presentation(self.format_id, version)
        transform = mapping.get("coordinate_transform", {})
        scale = float(transform.get("scale", 1.0))
        offset_x = float(transform.get("offset_x", 0.0))
        offset_y = float(transform.get("offset_y", 0.0))
        if not math.isfinite(scale) or scale <= 0:
            raise NativeTopologyCodecError("Packet Tracer source coordinate scale is invalid")
        presentation["coordinate_space"].update({
            "unit": "native", "scale": scale, "offset_x": offset_x, "offset_y": offset_y,
        })
        coordinates = [device.xy for device in network.devices]
        if coordinates:
            min_x = min(float(point[0]) for point in coordinates)
            min_y = min(float(point[1]) for point in coordinates)
            max_x = max(float(point[0]) for point in coordinates)
            max_y = max(float(point[1]) for point in coordinates)
            width = max(1, min(100000, math.ceil(max_x - min_x + 120)))
            height = max(1, min(100000, math.ceil(max_y - min_y + 120)))
            presentation["canvas"] = {"width": width, "height": height}
            presentation["viewport"] = {
                "x": min_x - 60, "y": min_y - 60,
                "width": max(250, min(16000, width)),
                "height": max(155, min(9920, height)), "zoom": 1,
            }
        else:
            presentation["canvas"] = {"width": 1000, "height": 620}
        presentation["nodes"] = []
        native_devices = mapping.get("devices", {})
        for node in definition["nodes"]:
            native = native_devices.get(node["id"], {})
            ports = []
            for interface in node.get("interfaces", []):
                ports.append({
                    "interface_name": interface["name"],
                    "adapter": interface["adapter"],
                    "port": interface["port"],
                    "native_id": str(native.get("ref", "")) + ":" + interface["name"],
                })
            device_by_ref = {str(device.ref): device for device in network.devices}
            native_device = device_by_ref.get(str(native.get("ref", "")))
            if native_device is None:
                raise NativeTopologyCodecError("Packet Tracer native device identity could not be resolved")
            native_x, native_y = native_device.xy
            presentation["nodes"].append({
                "node_id": node["id"],
                "native_id": str(native.get("ref", "")),
                "x": float(native_x),
                "y": float(native_y),
                "label": node["name"],
                "ports": ports,
            })

        presentation["links"] = []
        native_links = mapping.get("links", [])
        if len(native_links) != len(definition["links"]):
            raise NativeTopologyCodecError("Packet Tracer native link mapping is inconsistent")
        for index, link in enumerate(definition["links"]):
            native_link = native_links[index]
            identity = "|".join((
                str(native_link.get("first_ref", "")),
                str(native_link.get("first_port", "")),
                str(native_link.get("second_ref", "")),
                str(native_link.get("second_port", "")),
            ))
            presentation["links"].append({
                "link_id": link["id"],
                "native_id": "pt-link-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                "route_style": "direct",
            })

        warnings = list(report.get("warnings", []))
        warnings.append(
            "Packet Tracer drawing objects and notes remain in the immutable .pkt source; "
            "the installed codec does not expose them as editable presentation objects."
        )
        return DecodedNativeTopology(
            format_id=self.format_id,
            format_version=version,
            filename=Path(filename).name,
            topology_definition=definition,
            presentation=presentation,
            metadata={
                "source_edition": str(network.edition or ""),
                "codec": {"name": self.codec_name, "version": self.codec_version},
                "counts": report.get("counts", {}),
                "warnings": sorted(set(warnings)),
                "native_application_reopen_verified": False,
                "native_coordinate_transform": mapping.get("coordinate_transform", {}),
            },
            warnings=tuple(sorted(set(warnings))),
        )

    def encode(
        self,
        topology_definition: dict[str, Any],
        presentation: dict[str, Any],
        *,
        original_source: bytes,
        filename: str,
    ) -> EncodedNativeTopology:
        if not isinstance(filename, str) or not filename.lower().endswith(".pkt"):
            raise NativeTopologyCodecError("Packet Tracer export requires a .pkt source filename")
        network = self._load(original_source)
        try:
            baseline, mapping, _report = PacketTracerInteropService._convert_network(network)
            current, _canonical_json, _canonical_hash = TopologyStudioService.canonical_payload(
                topology_definition
            )
        except (PacketTracerInteropError, TypeError, ValueError, KeyError) as exc:
            raise NativeTopologyCodecError(str(exc)) from exc

        baseline_nodes = {item["id"]: item for item in baseline.get("nodes", [])}
        current_nodes = {item["id"]: item for item in current.get("nodes", [])}
        if set(current_nodes) != set(baseline_nodes):
            raise NativeTopologyCodecError(
                "Packet Tracer export supports presentation/name edits only; node identity or membership changed"
            )
        if current.get("links") != baseline.get("links"):
            raise NativeTopologyCodecError(
                "Packet Tracer export does not yet support link creation, removal, rewiring or link-property edits"
            )
        for node_id, old in baseline_nodes.items():
            new = current_nodes[node_id]
            old_semantics = {key: value for key, value in old.items() if key not in {"name", "x", "y"}}
            new_semantics = {key: value for key, value in new.items() if key not in {"name", "x", "y"}}
            if old_semantics != new_semantics:
                raise NativeTopologyCodecError(
                    f"Packet Tracer export does not serialize interface or configuration changes for {node_id}"
                )

        if presentation.get("drawings"):
            raise NativeTopologyCodecError(
                "Packet Tracer drawing/annotation creation and editing are not supported by the installed native serializer"
            )
        native_devices = mapping.get("devices", {})
        expected_nodes = set(baseline_nodes)
        layout_nodes = {
            str(item.get("node_id")): item
            for item in presentation.get("nodes", [])
            if isinstance(item, Mapping) and item.get("node_id")
        }
        if layout_nodes and set(layout_nodes) != expected_nodes:
            raise NativeTopologyCodecError("Packet Tracer presentation node identity does not match the native source")
        expected_links = {item["id"] for item in baseline.get("links", [])}
        layout_links = {
            str(item.get("link_id")): item
            for item in presentation.get("links", [])
            if isinstance(item, Mapping) and item.get("link_id")
        }
        if layout_links and set(layout_links) != expected_links:
            raise NativeTopologyCodecError("Packet Tracer presentation link identity does not match the native source")
        if any(
            item.get("route_style", "direct") != "direct" or item.get("points")
            for item in layout_links.values()
        ):
            raise NativeTopologyCodecError("Packet Tracer native link route editing is not supported")

        transform = mapping.get("coordinate_transform", {})
        scale = float(transform.get("scale", 1.0))
        offset_x = float(transform.get("offset_x", 0.0))
        offset_y = float(transform.get("offset_y", 0.0))
        if not math.isfinite(scale) or scale <= 0 or not all(
            math.isfinite(value) for value in (offset_x, offset_y)
        ):
            raise NativeTopologyCodecError("The Packet Tracer source coordinate transform is invalid")

        targets = []
        devices_by_ref = {str(device.ref): device for device in network.devices}
        for node_id, node in current_nodes.items():
            native = native_devices.get(node_id)
            if not isinstance(native, Mapping):
                raise NativeTopologyCodecError(f"Packet Tracer source mapping is missing for {node_id}")
            target = devices_by_ref.get(str(native.get("ref")))
            if target is None:
                raise NativeTopologyCodecError(f"Packet Tracer native device identity is missing for {node_id}")
            view = layout_nodes.get(node_id)
            if view is None:
                # Backward compatibility for callers that still provide only
                # the canonical, normalized topology coordinates.
                native_x = float(node["x"]) / scale - offset_x
                native_y = float(node["y"]) / scale - offset_y
            else:
                # G08 presentation snapshots store the raw native Packet Tracer
                # coordinate values. They must not be normalized a second time.
                native_x = float(view.get("x", target.xy[0]))
                native_y = float(view.get("y", target.xy[1]))
            if not math.isfinite(native_x) or not math.isfinite(native_y):
                raise NativeTopologyCodecError("Packet Tracer presentation contains invalid native coordinates")
            label = str(node.get("name", ""))
            if view.get("label") and view["label"] != baseline_nodes[node_id]["name"]:
                label = str(view["label"])
            targets.append((node_id, target, label, native_x, native_y))

        no_native_edits = all(
            target.name == label
            and math.isclose(float(target.xy[0]), x, abs_tol=1.0)
            and math.isclose(float(target.xy[1]), y, abs_tol=1.0)
            for _node_id, target, label, x, y in targets
        )
        if not no_native_edits:
            for _node_id, target, label, _x, _y in targets:
                if target.name != label:
                    target.name = "NRX" + hashlib.sha256(
                        (str(target.ref) + label).encode("utf-8")
                    ).hexdigest()[:16]
            for _node_id, target, label, x, y in targets:
                if target.name != label:
                    target.name = label
                target.xy = (x, y)
            try:
                encoded = network.to_bytes()
            except Exception as exc:
                raise NativeTopologyCodecError(
                    "The Packet Tracer native serializer could not produce a valid .pkt file"
                ) from exc
        else:
            encoded = bytes(original_source)

        if len(encoded) > self.MAX_SOURCE_BYTES:
            raise NativeTopologyCodecError(
                f"Serialized Packet Tracer project exceeds the {self.MAX_SOURCE_BYTES}-byte native file limit"
            )
        try:
            reopened = PacketTracerInteropService._load(encoded)
        except PacketTracerInteropError as exc:
            raise NativeTopologyCodecError("Serialized Packet Tracer output failed codec read-back") from exc

        expected_by_ref = {str(target.ref): (label, x, y) for _id, target, label, x, y in targets}
        reopened_by_ref = {str(device.ref): device for device in reopened.devices}
        if set(reopened_by_ref) != set(expected_by_ref):
            raise NativeTopologyCodecError("Packet Tracer serialized output changed the native device identity set")
        for ref, (label, x, y) in expected_by_ref.items():
            item = reopened_by_ref.get(ref)
            if item is None or item.name != label or not (
                math.isclose(float(item.xy[0]), x, abs_tol=1.0)
                and math.isclose(float(item.xy[1]), y, abs_tol=1.0)
            ):
                raise NativeTopologyCodecError("Packet Tracer serialized output failed name/coordinate read-back")
        if PacketTracerInteropService._endpoint_signatures(reopened) != PacketTracerInteropService._endpoint_signatures(network):
            raise NativeTopologyCodecError("Packet Tracer serialized output failed native link-endpoint read-back")

        losses = (
            "Only device name and X/Y placement are writable. Device/model changes, links, "
            "interfaces, VLAN/IP/configuration, native drawings and notes remain unsupported.",
            "pktlib output edition is determined by the installed codec; desktop application reopening is not verified by codec read-back.",
        )
        return EncodedNativeTopology(
            format_id=self.format_id,
            format_version=str(reopened.edition or reopened.version or "unknown")[:32],
            filename=Path(filename).stem[:200] + "-netregress-export.pkt",
            media_type="application/octet-stream",
            content=encoded,
            losses=losses,
        )
