"""Packet Tracer .pkt import/export with immutable native-file provenance.

This module deliberately implements a bounded compatibility bridge, not a
Packet Tracer provider or emulator controller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import secrets
import sqlite3
import tempfile
from typing import Any, Mapping

import pktlib

from lib.services.topology_studio import TopologyStudioService, TopologyStudioError


class PacketTracerInteropError(ValueError):
    """The native file or requested conversion is invalid or unsupported."""


class PacketTracerInteropConflict(PacketTracerInteropError):
    """The requested native export would lose unsupported topology changes."""


class PacketTracerInteropNotFound(LookupError):
    """A Project, Lab, topology or imported native source was not found."""


@dataclass(frozen=True, slots=True)
class PacketTracerExport:
    content: bytes
    filename: str
    report: dict[str, Any]


class PacketTracerInteropService:
    FORMAT = "CISCO_PACKET_TRACER_PKT"
    CODEC = "pktlib"
    MAX_SOURCE_BYTES = 3_500_000
    MAX_FILENAME_LENGTH = 255
    MAX_COORDINATE = 10_000
    MAX_EXPANDED_XML_BYTES = 24_000_000

    def __init__(self, database) -> None:
        self.database = database
        self.topology = TopologyStudioService(database)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        return TopologyStudioService._actor(value)

    @classmethod
    def _filename(cls, value: object) -> str:
        if not isinstance(value, str):
            raise PacketTracerInteropError("A .pkt filename is required")
        basename = value.replace("\\", "/").split("/")[-1].strip()
        if (
            not basename
            or basename in {".", ".."}
            or len(basename) > cls.MAX_FILENAME_LENGTH
            or any(ord(char) < 32 for char in basename)
            or not basename.lower().endswith(".pkt")
        ):
            raise PacketTracerInteropError("Only a safe .pkt filename is supported")
        return basename

    @classmethod
    def _source_bytes(cls, value: object) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise PacketTracerInteropError("The uploaded Packet Tracer file is invalid")
        data = bytes(value)
        if not data or len(data) > cls.MAX_SOURCE_BYTES:
            raise PacketTracerInteropError(
                f"Packet Tracer .pkt files must contain 1 to {cls.MAX_SOURCE_BYTES} bytes"
            )
        return data

    @staticmethod
    def _codec_version() -> str:
        try:
            return importlib.metadata.version("pktlib")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    @classmethod
    def _bounded_decompression_preflight(cls, data: bytes) -> None:
        """Bound the authenticated zlib payload before pktlib parses the XML.

        pktlib 0.2.2's public decoder decompresses before comparing the
        declared XML size. This preflight uses the pinned codec's low-level
        primitives and a bounded zlib decompressor so a small compressed
        upload cannot expand without limit. pktlib then parses the exact same
        immutable bytes in a private temporary directory.
        """
        import zlib
        try:
            from pktlib._codec import KEY, NONCE, _unscramble_outer, _xor_inner
            from pktlib._twofish import eax_decrypt

            plain = eax_decrypt(KEY, NONCE, _unscramble_outer(data), verify=True)
            packed = _xor_inner(plain)
            if len(packed) < 6:
                raise PacketTracerInteropError("The .pkt file is too short to contain a valid compressed document")
            declared_size = int.from_bytes(packed[:4], "big")
            if not 1 <= declared_size <= cls.MAX_EXPANDED_XML_BYTES:
                raise PacketTracerInteropError(
                    f"The native Packet Tracer XML document exceeds the {cls.MAX_EXPANDED_XML_BYTES}-byte safety limit"
                )
            decoder = zlib.decompressobj()
            pending = packed[4:]
            expanded = 0
            while pending:
                chunk = decoder.decompress(pending, cls.MAX_EXPANDED_XML_BYTES - expanded + 1)
                expanded += len(chunk)
                if expanded > cls.MAX_EXPANDED_XML_BYTES:
                    raise PacketTracerInteropError(
                        f"The native Packet Tracer XML document exceeds the {cls.MAX_EXPANDED_XML_BYTES}-byte safety limit"
                    )
                remainder = decoder.unconsumed_tail
                if remainder == pending and not chunk:
                    raise PacketTracerInteropError("The .pkt compressed document could not be decoded safely")
                pending = remainder
            tail = decoder.flush(cls.MAX_EXPANDED_XML_BYTES - expanded + 1)
            expanded += len(tail)
            if expanded > cls.MAX_EXPANDED_XML_BYTES:
                raise PacketTracerInteropError(
                    f"The native Packet Tracer XML document exceeds the {cls.MAX_EXPANDED_XML_BYTES}-byte safety limit"
                )
            if not decoder.eof or decoder.unused_data or expanded != declared_size:
                raise PacketTracerInteropError("The .pkt compressed document length or trailer is invalid")
        except PacketTracerInteropError:
            raise
        except Exception as exc:
            raise PacketTracerInteropError(
                "The .pkt file is malformed, has an invalid authentication tag, or has an unsupported compression stream"
            ) from exc

    @classmethod
    def _load(cls, data: bytes):
        # The public pktlib decoder currently inflates before validating its
        # declared length. Validate its pinned container primitives first.
        cls._bounded_decompression_preflight(data)
        # pktlib's public load() API accepts a path. The file is written only
        # inside a private temporary directory and is never executed.
        with tempfile.TemporaryDirectory(prefix="netregress-pkt-") as directory:
            path = Path(directory) / "source.pkt"
            path.write_bytes(data)
            try:
                return pktlib.load(path, seed=0, strict=True)
            except Exception as exc:
                raise PacketTracerInteropError(
                    "The .pkt file is malformed or its Packet Tracer version is not supported by the installed codec"
                ) from exc

    @staticmethod
    def _node_type(kind: str) -> tuple[str, bool]:
        value = kind.casefold().replace(" ", "").replace("-", "")
        if "router" in value:
            return "ROUTER", True
        if "switch" in value:
            return "SWITCH", True
        if "accesspoint" in value:
            return "ACCESS_POINT", True
        if value in {"pc", "laptop", "server", "printer", "ipphone", "phone", "tablet"}:
            return "CLIENT", True
        if "cloud" in value:
            return "CLOUD", True
        return "OTHER", False

    @staticmethod
    def _coordinate_transform(devices: list[Any]) -> dict[str, float]:
        coordinates = [device.xy for device in devices]
        if not coordinates:
            return {"scale": 1.0, "offset_x": 0.0, "offset_y": 0.0}
        values = [float(value) for pair in coordinates for value in pair]
        if any(not math.isfinite(value) for value in values):
            raise PacketTracerInteropError("The native project contains non-finite node coordinates")
        min_x = min(float(pair[0]) for pair in coordinates)
        min_y = min(float(pair[1]) for pair in coordinates)
        offset_x = max(0.0, -min_x)
        offset_y = max(0.0, -min_y)
        maximum = max(
            max(float(pair[0]) + offset_x for pair in coordinates),
            max(float(pair[1]) + offset_y for pair in coordinates),
        )
        scale = min(1.0, PacketTracerInteropService.MAX_COORDINATE / maximum) if maximum > 0 else 1.0
        return {
            "scale": scale,
            "offset_x": offset_x,
            "offset_y": offset_y,
        }

    @staticmethod
    def _logical_id(device: Any) -> str:
        identity = f"{device.ref}\0{device.uuid}".encode("utf-8", errors="replace")
        return "pt-" + hashlib.sha256(identity).hexdigest()[:24]

    @classmethod
    def _convert_network(cls, network: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        devices = list(network.devices)
        links = list(network.links)
        if len(devices) > TopologyStudioService.MAX_NODES:
            raise PacketTracerInteropError(
                f"The native project has {len(devices)} devices; the canonical topology limit is {TopologyStudioService.MAX_NODES}"
            )
        if len(links) > TopologyStudioService.MAX_LINKS:
            raise PacketTracerInteropError(
                f"The native project has {len(links)} links; the canonical topology limit is {TopologyStudioService.MAX_LINKS}"
            )

        transform = cls._coordinate_transform(devices)
        scale = transform["scale"]
        node_ids: dict[str, str] = {}
        native_devices: dict[str, dict[str, Any]] = {}
        node_records: list[dict[str, Any]] = []
        warnings: list[str] = []
        unsupported: list[dict[str, str]] = []

        for device in devices:
            logical_id = cls._logical_id(device)
            if logical_id in node_ids.values():
                raise PacketTracerInteropError("The native project contains duplicate device identity references")
            node_ids[str(device.ref)] = logical_id
            kind = str(device.kind or "Unknown")
            node_type, supported_kind = cls._node_type(kind)
            if not supported_kind:
                unsupported.append({
                    "object_type": "DEVICE_KIND",
                    "native_name": str(device.name)[:120],
                    "native_kind": kind[:120],
                    "reason": "The device kind has no direct canonical node-type mapping; it is represented as OTHER",
                })
            ports = list(device.ports.values())
            if len(ports) > 64:
                raise PacketTracerInteropError(
                    f"Device {device.name!r} exposes more than the canonical 64-interface limit"
                )
            interfaces: list[dict[str, Any]] = []
            port_indexes: dict[str, int] = {}
            for index, port in enumerate(ports):
                port_name = str(port.name)
                if not port_name or len(port_name) > 64 or index > 255:
                    raise PacketTracerInteropError(
                        f"Device {device.name!r} has an interface that cannot be represented safely"
                    )
                port_indexes[port_name] = index
                interface: dict[str, Any] = {
                    "name": port_name,
                    "adapter": 0,
                    "port": index,
                }
                mode = str(port.mode or "").casefold()
                if mode == "access":
                    interface["mode"] = "ACCESS"
                elif mode == "trunk":
                    interface["mode"] = "TRUNK"
                else:
                    try:
                        address = port.address
                    except Exception:
                        address = None
                        warnings.append(
                            f"An invalid or unsupported interface address on {device.name}.{port_name} was not mapped"
                        )
                    if address:
                        interface["mode"] = "ROUTED"
                try:
                    address = port.address
                except Exception:
                    address = None
                if address:
                    interface["ip_address"] = str(address)
                try:
                    vlan = port.access_vlan
                except Exception:
                    vlan = None
                if isinstance(vlan, int) and not isinstance(vlan, bool) and 1 <= vlan <= 4094:
                    interface["vlan_id"] = vlan
                interfaces.append(interface)

            x, y = device.xy
            node: dict[str, Any] = {
                "id": logical_id,
                "name": str(device.name),
                "node_type": node_type,
                "template_id": "",
                "x": round((float(x) + transform["offset_x"]) * scale, 3),
                "y": round((float(y) + transform["offset_y"]) * scale, 3),
                "vendor": "Cisco",
                "operating_system": "Packet Tracer",
                "image": str(device.model or "")[:128],
                "properties": {
                    "packet_tracer_kind": kind[:120],
                    "packet_tracer_model": str(device.model or "")[:128],
                },
                "interfaces": interfaces,
            }
            node_records.append(node)
            native_devices[logical_id] = {
                "ref": str(device.ref),
                "uuid": str(device.uuid),
                "name": str(device.name),
                "kind": kind,
                "model": str(device.model or ""),
                "ports": port_indexes,
            }

        links_records: list[dict[str, Any]] = []
        native_links: list[dict[str, str]] = []
        for index, link in enumerate(links):
            try:
                first, second = link.ports
            except Exception as exc:
                raise PacketTracerInteropError(
                    "The native project contains a link with an unresolved endpoint"
                ) from exc
            source_id = node_ids.get(str(first.device.ref))
            target_id = node_ids.get(str(second.device.ref))
            source_port = native_devices.get(source_id, {}).get("ports", {}).get(str(first.name))
            target_port = native_devices.get(target_id, {}).get("ports", {}).get(str(second.name))
            if source_id is None or target_id is None or source_port is None or target_port is None:
                raise PacketTracerInteropError("A native link endpoint cannot be mapped to a canonical interface")
            signature = f"{first.device.ref}:{first.name}|{second.device.ref}:{second.name}|{index}"
            link_id = "pt-link-" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:22]
            cable = str(link.cable or "").casefold()
            link_type = "SERIAL" if "serial" in cable else "ETHERNET" if cable in {
                "straight", "cross", "coax", "fiber", "optical",
            } else "OTHER"
            links_records.append({
                "id": link_id,
                "source_node_id": source_id,
                "source_adapter": 0,
                "source_port": source_port,
                "source_interface_name": str(first.name),
                "target_node_id": target_id,
                "target_adapter": 0,
                "target_port": target_port,
                "target_interface_name": str(second.name),
                "link_type": link_type,
            })
            native_links.append({
                "first_ref": str(first.device.ref),
                "first_port": str(first.name),
                "second_ref": str(second.device.ref),
                "second_port": str(second.name),
            })

        try:
            definition, _encoded, digest = TopologyStudioService.canonical_payload({
                "nodes": node_records,
                "links": links_records,
            })
        except (TopologyStudioError, TypeError, ValueError) as exc:
            raise PacketTracerInteropError(
                "The Packet Tracer project contains nodes or links that cannot be represented by the canonical topology model"
            ) from exc
        try:
            shapes = len(network.shapes)
        except Exception:
            shapes = 0
        try:
            notes = len(network.notes)
        except Exception:
            notes = 0
        if shapes or notes:
            unsupported.append({
                "object_type": "PRESENTATION_OBJECTS",
                "native_name": "",
                "native_kind": "",
                "reason": f"{shapes} drawing objects and {notes} notes remain in the preserved native source; they are not yet editable on the NetRegress canvas",
            })
        if any(getattr(device, "has_ios", False) and device.running_config for device in devices):
            warnings.append(
                "Device running/startup configurations are retained in the immutable native source file; they are not compiled into vendor-neutral network intent"
            )
        warnings.extend([
            "Packet Tracer devices are imported as logical nodes with no provider template mapping; provider apply remains blocked until each node is mapped to a compatible provider template.",
            "The original .pkt bytes are retained unchanged. Export reserializes the native document using the installed codec and may update an older source format to the codec's supported output edition.",
        ])
        mapping = {
            "baseline_definition": definition,
            "coordinate_transform": transform,
            "devices": native_devices,
            "links": native_links,
        }
        report = {
            "format": cls.FORMAT,
            "source_version": str(network.version),
            "source_edition": str(network.edition) if network.edition else None,
            "codec": {"name": cls.CODEC, "version": cls._codec_version(), "license": "MIT"},
            "canonical_content_sha256": digest,
            "counts": {
                "nodes": len(definition["nodes"]),
                "links": len(definition["links"]),
                "unmapped_device_kinds": sum(1 for item in unsupported if item["object_type"] == "DEVICE_KIND"),
                "preserved_presentation_objects": shapes + notes,
            },
            "warnings": sorted(set(warnings)),
            "unsupported_objects": unsupported,
            "native_application_reopen_verified": False,
        }
        return definition, mapping, report

    def import_file(
        self,
        *,
        project_id: str,
        name: str,
        filename: str,
        content: bytes,
        actor: str,
        scope_type: str = "PROJECT",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        project_id = TopologyStudioService._text(project_id, "project_id", 128)
        name = TopologyStudioService._text(name, "name", 120)
        actor = self._actor(actor)
        filename = self._filename(filename)
        content = self._source_bytes(content)
        network = self._load(content)
        definition, mapping, report = self._convert_network(network)
        scope_type = str(scope_type or "PROJECT").strip().upper()
        if scope_type not in {"PROJECT", "LAB"}:
            raise PacketTracerInteropError("scope_type must be PROJECT or LAB")
        if scope_type == "PROJECT":
            scope_id = project_id
            lab_id = None
        else:
            scope_id = TopologyStudioService._text(scope_id, "scope_id", 128)
            lab_id = scope_id

        now = self._now()
        profile_id = "top_" + secrets.token_hex(12)
        revision_id = "tpr_" + secrets.token_hex(12)
        source_id = "tns_" + secrets.token_hex(12)
        normalized, encoded, digest = TopologyStudioService.canonical_payload(definition)
        source_sha256 = hashlib.sha256(content).hexdigest()
        mapping_json = json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        report_json = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        try:
            # Profile, immutable revision and original native bytes are committed
            # together. A failed insert cannot leave a half-imported topology.
            with self.database.transaction(immediate=True) as connection:
                project = connection.execute(
                    "SELECT status FROM projects WHERE project_id=?", (project_id,)
                ).fetchone()
                if project is None or project["status"] != "ACTIVE":
                    raise PacketTracerInteropNotFound("Active Project not found")
                if lab_id is not None:
                    lab = connection.execute(
                        "SELECT project_id,status FROM labs WHERE lab_id=?", (lab_id,)
                    ).fetchone()
                    if lab is None or lab["project_id"] != project_id:
                        raise PacketTracerInteropNotFound("Lab not found in this Project")
                    if lab["status"] != "ACTIVE":
                        raise PacketTracerInteropError("Packet Tracer imports require an active Lab")

                connection.execute(
                    """INSERT INTO topology_profiles(
                       profile_id,project_id,name,description,scope_type,scope_id,lab_id,status,
                       created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,'Imported from Packet Tracer',?,?,?,'ACTIVE',?,?,?,?)""",
                    (profile_id, project_id, name, scope_type, scope_id, lab_id, now, now, actor, actor),
                )
                revision_number = int(connection.execute(
                    "SELECT COALESCE(MAX(revision_number),0)+1 FROM topology_revisions WHERE profile_id=?",
                    (profile_id,),
                ).fetchone()[0])
                connection.execute(
                    """INSERT INTO topology_revisions(
                       revision_id,profile_id,revision_number,definition_json,content_sha256,status,
                       created_at,created_by,published_at,published_by
                    ) VALUES(?,?,?,?,?,'DRAFT',?,?,NULL,NULL)""",
                    (revision_id, profile_id, revision_number, encoded, digest, now, actor),
                )
                connection.execute(
                    """INSERT INTO topology_native_sources(
                       source_id,project_id,profile_id,revision_id,format,format_version,filename,
                       sha256,size_bytes,source_bytes,codec_name,codec_version,mapping_json,
                       compatibility_report_json,imported_at,imported_by
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        source_id, project_id, profile_id, revision_id, self.FORMAT,
                        str(network.version), filename, source_sha256, len(content), content,
                        self.CODEC, self._codec_version(), mapping_json, report_json, now, actor,
                    ),
                )
                TopologyStudioService._audit(
                    connection, actor, "TOPOLOGY_PROFILE_CREATED", "TOPOLOGY_PROFILE", profile_id,
                    {"project_id": project_id, "scope_type": scope_type, "scope_id": scope_id},
                )
                TopologyStudioService._audit(
                    connection, actor, "TOPOLOGY_REVISION_CREATED", "TOPOLOGY_REVISION", revision_id,
                    {"profile_id": profile_id, "revision_number": revision_number, "content_sha256": digest,
                     "node_count": len(normalized["nodes"]), "link_count": len(normalized["links"])},
                )
                TopologyStudioService._audit(
                    connection, actor, "TOPOLOGY_NATIVE_IMPORTED", "TOPOLOGY_NATIVE_SOURCE", source_id,
                    {"project_id": project_id, "profile_id": profile_id, "revision_id": revision_id,
                     "format": self.FORMAT, "sha256": source_sha256, "size_bytes": len(content)},
                )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise PacketTracerInteropConflict(
                    "A topology profile with this name already exists at the selected scope"
                ) from exc
            if "FOREIGN KEY constraint failed" in str(exc):
                raise PacketTracerInteropNotFound("Project or Lab no longer exists") from exc
            raise

        profile = self.topology.get_profile(profile_id) or {}
        revision = self.topology.get_revision(revision_id) or {}
        source = self._source_metadata(source_id, include_report=True)
        return {"profile": profile, "revision": revision, "source": source, "report": report}

    def _source_metadata(self, source_id: str, *, include_report: bool = False) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT source_id,project_id,profile_id,revision_id,format,format_version,
                          filename,sha256,size_bytes,codec_name,codec_version,compatibility_report_json,
                          imported_at,imported_by
                   FROM topology_native_sources WHERE source_id=?""",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        result = {key: row[key] for key in (
            "source_id", "project_id", "profile_id", "revision_id", "format", "format_version",
            "filename", "sha256", "size_bytes", "codec_name", "codec_version", "imported_at", "imported_by",
        )}
        if include_report:
            result["compatibility_report"] = json.loads(row["compatibility_report_json"])
        return result

    def list_sources(self, profile_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT source_id,project_id,profile_id,revision_id,format,format_version,
                          filename,sha256,size_bytes,codec_name,codec_version,compatibility_report_json,
                          imported_at,imported_by
                   FROM topology_native_sources WHERE profile_id=? ORDER BY imported_at DESC""",
                (profile_id,),
            ).fetchall()
        return [
            {
                "source_id": row["source_id"],
                "project_id": row["project_id"],
                "profile_id": row["profile_id"],
                "revision_id": row["revision_id"],
                "format": row["format"],
                "format_version": row["format_version"],
                "filename": row["filename"],
                "sha256": row["sha256"],
                "size_bytes": row["size_bytes"],
                "codec_name": row["codec_name"],
                "codec_version": row["codec_version"],
                "compatibility_report": json.loads(row["compatibility_report_json"]),
                "imported_at": row["imported_at"],
                "imported_by": row["imported_by"],
            }
            for row in rows
        ]

    @staticmethod
    def _endpoint_signatures(network: Any) -> set[frozenset[tuple[str, str]]]:
        result: set[frozenset[tuple[str, str]]] = set()
        for link in network.links:
            first, second = link.ports
            result.add(frozenset({
                (str(first.device.ref), str(first.name)),
                (str(second.device.ref), str(second.name)),
            }))
        return result

    def export_revision(
        self,
        *,
        profile_id: str,
        revision_id: str,
        source_id: str,
    ) -> PacketTracerExport:
        with self.database.connection() as connection:
            source = connection.execute(
                """SELECT * FROM topology_native_sources
                   WHERE source_id=? AND profile_id=?""",
                (source_id, profile_id),
            ).fetchone()
            profile_row = connection.execute(
                "SELECT * FROM topology_profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
            revision_row = connection.execute(
                "SELECT * FROM topology_revisions WHERE revision_id=? AND profile_id=?",
                (revision_id, profile_id),
            ).fetchone()
        if source is None or profile_row is None or revision_row is None:
            raise PacketTracerInteropNotFound("Native source, topology profile or revision not found")
        if source["format"] != self.FORMAT:
            raise PacketTracerInteropNotFound("The selected native source is not a Packet Tracer .pkt file")
        original = bytes(source["source_bytes"])
        source_digest = hashlib.sha256(original).hexdigest()
        if source_digest != source["sha256"] or len(original) != int(source["size_bytes"]):
            raise PacketTracerInteropError("The stored native source failed its integrity check")

        current, _encoded, current_digest = TopologyStudioService.canonical_payload(
            json.loads(revision_row["definition_json"])
        )
        if current_digest != revision_row["content_sha256"]:
            raise PacketTracerInteropError("The selected topology revision failed its integrity check")
        mapping = json.loads(source["mapping_json"])
        baseline = mapping.get("baseline_definition", {})
        baseline_nodes = {item["id"]: item for item in baseline.get("nodes", [])}
        current_nodes = {item["id"]: item for item in current.get("nodes", [])}
        if set(current_nodes) != set(baseline_nodes):
            raise PacketTracerInteropConflict(
                "Native Packet Tracer export currently supports node presentation/name edits only; node additions or removals need an explicit native device mapping"
            )
        if current.get("links") != baseline.get("links"):
            raise PacketTracerInteropConflict(
                "Link creation, removal, rewiring and link-property edits are not yet supported by the Packet Tracer export subset"
            )
        for node_id, baseline_node in baseline_nodes.items():
            current_node = current_nodes[node_id]
            original_semantics = {key: value for key, value in baseline_node.items() if key not in {"name", "x", "y"}}
            current_semantics = {key: value for key, value in current_node.items() if key not in {"name", "x", "y"}}
            if original_semantics != current_semantics:
                raise PacketTracerInteropConflict(
                    f"Native Packet Tracer export does not yet serialize interface/configuration changes for logical node {node_id}"
                )

        native_devices = mapping.get("devices", {})
        no_native_edits = current == baseline
        if no_native_edits:
            reopened = self._load(original)
            expected_native = {
                str(item.get("ref")): str(item.get("name"))
                for item in native_devices.values()
                if isinstance(item, Mapping)
            }
            reopened_by_ref = {str(device.ref): device for device in reopened.devices}
            if set(reopened_by_ref) != set(expected_native):
                raise PacketTracerInteropError("The original Packet Tracer source failed device identity read-back")
            if any(reopened_by_ref[ref].name != name for ref, name in expected_native.items()):
                raise PacketTracerInteropError("The original Packet Tracer source failed device-name read-back")
            expected_endpoints = {
                frozenset({
                    (str(item["first_ref"]), str(item["first_port"])),
                    (str(item["second_ref"]), str(item["second_port"])),
                })
                for item in mapping.get("links", [])
            }
            if self._endpoint_signatures(reopened) != expected_endpoints:
                raise PacketTracerInteropError("The original Packet Tracer source failed native link-endpoint read-back")
            transform = mapping.get("coordinate_transform", {})
            scale = float(transform.get("scale", 1.0))
            offset_x = float(transform.get("offset_x", 0.0))
            offset_y = float(transform.get("offset_y", 0.0))
            if not math.isfinite(scale) or scale <= 0 or not all(math.isfinite(value) for value in (offset_x, offset_y)):
                raise PacketTracerInteropError("The saved native coordinate transform is invalid")
            for node_id, native in native_devices.items():
                baseline_node = baseline_nodes.get(node_id)
                ref = str(native.get("ref")) if isinstance(native, Mapping) else ""
                if baseline_node is None or ref not in reopened_by_ref:
                    raise PacketTracerInteropError("The original Packet Tracer source failed native coordinate identity read-back")
                expected_x = float(baseline_node["x"]) / scale - offset_x
                expected_y = float(baseline_node["y"]) / scale - offset_y
                actual_x, actual_y = reopened_by_ref[ref].xy
                if not (
                    math.isclose(float(actual_x), expected_x, abs_tol=1.0)
                    and math.isclose(float(actual_y), expected_y, abs_tol=1.0)
                ):
                    raise PacketTracerInteropError("The original Packet Tracer source failed native coordinate read-back")
            report = {
                "format": self.FORMAT,
                "source_sha256": source_digest,
                "source_version": source["format_version"],
                "output_version": str(reopened.edition or reopened.version),
                "codec": {"name": self.CODEC, "version": self._codec_version()},
                "serialized_bytes": len(original),
                "read_back": {
                    "codec_reopen": True,
                    "device_identity_and_name_check": True,
                    "coordinate_check": True,
                    "link_endpoint_check": True,
                    "native_application_reopen_verified": False,
                },
                "supported_changes": [],
                "unsupported_changes": [
                    "node addition/removal or model replacement",
                    "link addition/removal/rewiring",
                    "interface, VLAN, IP or device configuration changes",
                    "native drawings and notes remain in the retained source but are not projected into editable canonical objects; serializer preservation remains an external qualification item",
                ],
                "byte_identical_to_imported_source": True,
                "format_version_note": "The original imported bytes are returned unchanged when the canonical revision has no native-editable changes.",
            }
            stem = Path(str(source["filename"])).stem[:200] or "packet-tracer-project"
            return PacketTracerExport(
                content=original,
                filename=f"{stem}-netregress-export.pkt",
                report=report,
            )

        network = self._load(original)
        by_ref = {str(device.ref): device for device in network.devices}
        edit_targets: list[tuple[str, Any, dict[str, Any], dict[str, Any]]] = []
        transform = mapping.get("coordinate_transform", {})
        scale = float(transform.get("scale", 1.0))
        offset_x = float(transform.get("offset_x", 0.0))
        offset_y = float(transform.get("offset_y", 0.0))
        if not math.isfinite(scale) or scale <= 0 or not all(math.isfinite(value) for value in (offset_x, offset_y)):
            raise PacketTracerInteropError("The saved native coordinate transform is invalid")
        expected_positions: dict[str, tuple[float, float]] = {}
        for node_id, node in current_nodes.items():
            native = native_devices.get(node_id)
            device = by_ref.get(str(native.get("ref"))) if isinstance(native, Mapping) else None
            if device is None:
                raise PacketTracerInteropConflict(
                    f"The original Packet Tracer device for logical node {node_id} is no longer addressable"
                )
            edit_targets.append((node_id, device, node, baseline_nodes[node_id]))

        # Stage only changed names through unique temporary names so valid swaps
        # (R1 <-> R2) do not collide with Packet Tracer's unique device names.
        for _node_id, device, node, _baseline in edit_targets:
            if device.name != node["name"]:
                device.name = "NRX" + secrets.token_hex(6)
        for node_id, device, node, baseline_node in edit_targets:
            if device.name != node["name"]:
                device.name = node["name"]
            if node["x"] != baseline_node["x"] or node["y"] != baseline_node["y"]:
                native_x = float(node["x"]) / scale - offset_x
                native_y = float(node["y"]) / scale - offset_y
                if not math.isfinite(native_x) or not math.isfinite(native_y):
                    raise PacketTracerInteropError("The selected topology contains invalid native coordinates")
                device.xy = (native_x, native_y)
                expected_positions[str(device.ref)] = (native_x, native_y)

        try:
            exported = network.to_bytes()
            if len(exported) > self.MAX_SOURCE_BYTES:
                raise PacketTracerInteropError(
                    f"The serialized .pkt file exceeds the {self.MAX_SOURCE_BYTES}-byte native file limit"
                )
            reopened = self._load(exported)
        except PacketTracerInteropError:
            raise
        except Exception as exc:
            raise PacketTracerInteropError("The native Packet Tracer serializer could not produce a valid .pkt file") from exc

        expected_refs = {
            str(native_devices.get(node_id, {}).get("ref")): node["name"]
            for node_id, _device, node, _baseline in edit_targets
        }
        reopened_by_ref = {str(device.ref): device for device in reopened.devices}
        if set(reopened_by_ref) != set(by_ref):
            raise PacketTracerInteropError("The serialized Packet Tracer project changed its device identity set")
        for ref, name in expected_refs.items():
            if ref not in reopened_by_ref or reopened_by_ref[ref].name != name:
                raise PacketTracerInteropError("The serialized Packet Tracer project failed its device-name read-back check")
        for ref, (expected_x, expected_y) in expected_positions.items():
            actual_x, actual_y = reopened_by_ref[ref].xy
            if not (
                math.isclose(float(actual_x), expected_x, abs_tol=1.0)
                and math.isclose(float(actual_y), expected_y, abs_tol=1.0)
            ):
                raise PacketTracerInteropError("The serialized Packet Tracer project failed its native coordinate read-back check")
        if self._endpoint_signatures(reopened) != self._endpoint_signatures(network):
            raise PacketTracerInteropError("The serialized Packet Tracer project failed its native link-endpoint read-back check")

        output_edition = str(reopened.edition or reopened.version)
        report = {
            "format": self.FORMAT,
            "source_sha256": source_digest,
            "source_version": source["format_version"],
            "output_version": output_edition,
            "codec": {"name": self.CODEC, "version": self._codec_version()},
            "serialized_bytes": len(exported),
            "read_back": {
                "codec_reopen": True,
                "device_identity_and_name_check": True,
                "coordinate_check": True,
                "link_endpoint_check": True,
                "native_application_reopen_verified": False,
            },
            "supported_changes": ["node name", "node X/Y presentation coordinates"],
            "unsupported_changes": [
                "node addition/removal or model replacement",
                "link addition/removal/rewiring",
                "interface, VLAN, IP or device configuration changes",
                "native drawings and notes are preserved but not editable in the canonical canvas",
            ],
            "format_version_note": (
                "pktlib serializes to its latest known Packet Tracer edition; older supported source files may be upgraded during export."
            ),
        }
        stem = Path(str(source["filename"])).stem[:200] or "packet-tracer-project"
        return PacketTracerExport(
            content=exported,
            filename=f"{stem}-netregress-export.pkt",
            report=report,
        )
