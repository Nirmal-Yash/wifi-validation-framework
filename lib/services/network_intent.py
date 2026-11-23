"""Canonical, versioned network intent and observed device capability snapshots.

This domain owns vendor-neutral intent only. It never emits vendor CLI, connects to
devices, or mutates provider resources; those responsibilities belong to EXP-P09.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import re
import secrets
from typing import Any, Mapping

from lib.services.topology_studio import TopologyStudioService


class NetworkIntentError(ValueError):
    """Invalid network intent, lifecycle transition or capability observation."""


class NetworkIntentNotFound(LookupError):
    """A profile, revision, topology or target is outside the requested Project."""


class NetworkIntentConflict(NetworkIntentError):
    """The requested operation conflicts with published or observed state."""


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SECRET_NAME = re.compile(r"(?:password|passwd|secret|token|private.?key|api.?key|psk|community)", re.I)
_CAPABILITY_FEATURES = frozenset({
    "addressing.ipv4",
    "addressing.ipv6",
    "interfaces.admin_state",
    "vlans.access",
    "vlans.trunk",
    "routing.static_ipv4",
    "routing.static_ipv6",
    "routing.ospf",
    "routing.bgp",
    "aggregation.lacp",
    "firewall.zones",
    "firewall.basic_acl",
    "services.dhcp",
    "services.dns",
    "linux.bridge",
    "linux.vlan_interface",
})
_ROOT_ARRAYS = (
    "targets", "segments", "interfaces", "static_routes", "ospf", "bgp",
    "aggregations", "firewall_zones", "firewall_rules", "service_references",
    "linux_bridges", "linux_vlan_interfaces",
)
_MAX_ITEMS = 512
_MAX_TEXT = 120


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise NetworkIntentError("network intent must contain finite JSON-compatible values") from exc


class NetworkIntentService:
    SCHEMA_VERSION = "1.0"
    CAPABILITY_REPORT_MAX_AGE = timedelta(days=7)
    CAPABILITY_REPORT_MAX_FUTURE_SKEW = timedelta(minutes=5)
    SUPPORTED_PROVIDERS = frozenset({"gns3", "cml", "eve-ng", "linux-native", "openwrt"})

    def __init__(self, database, topology_studio: TopologyStudioService | None = None):
        self.database = database
        self.topology = topology_studio or TopologyStudioService(database)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise NetworkIntentError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _text(value: object, field: str, maximum: int = _MAX_TEXT) -> str:
        if not isinstance(value, str):
            raise NetworkIntentError(f"{field} must be a string")
        normalized = value.strip()
        if not normalized or len(normalized) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in normalized):
            raise NetworkIntentError(f"{field} must contain 1 to {maximum} printable characters")
        return normalized

    @classmethod
    def _identifier(cls, value: object, field: str) -> str:
        item = cls._text(value, field, 64)
        if not _ID.fullmatch(item):
            raise NetworkIntentError(f"{field} contains unsupported identifier characters")
        return item

    @staticmethod
    def _object(value: object, field: str, allowed: set[str], required: set[str] = frozenset()) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise NetworkIntentError(f"{field} must be an object")
        if set(value) - allowed:
            unknown = sorted(set(value) - allowed)
            raise NetworkIntentError(f"{field} contains unsupported fields: {unknown}")
        missing = sorted(required - set(value))
        if missing:
            raise NetworkIntentError(f"{field} is missing required fields: {missing}")
        return value

    @staticmethod
    def _array(value: object, field: str, maximum: int = _MAX_ITEMS) -> list:
        if not isinstance(value, list):
            raise NetworkIntentError(f"{field} must be an array")
        if len(value) > maximum:
            raise NetworkIntentError(f"{field} exceeds the {maximum}-item limit")
        return value

    @staticmethod
    def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise NetworkIntentError(f"{field} must be an integer from {minimum} to {maximum}")
        return value

    @classmethod
    def _ip_interface(cls, value: object, field: str) -> str:
        if not isinstance(value, str):
            raise NetworkIntentError(f"{field} must be an IP interface in CIDR notation")
        try:
            return str(ipaddress.ip_interface(value.strip()))
        except ValueError as exc:
            raise NetworkIntentError(f"{field} is not a valid IPv4 or IPv6 interface") from exc

    @classmethod
    def _ip_address(cls, value: object, field: str, version: int | None = None) -> str:
        if not isinstance(value, str):
            raise NetworkIntentError(f"{field} must be an IP address")
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError as exc:
            raise NetworkIntentError(f"{field} is not a valid IP address") from exc
        if version is not None and address.version != version:
            raise NetworkIntentError(f"{field} must be IPv{version}")
        return str(address)

    @classmethod
    def _network(cls, value: object, field: str) -> str:
        if not isinstance(value, str):
            raise NetworkIntentError(f"{field} must be a CIDR network")
        try:
            return str(ipaddress.ip_network(value.strip(), strict=True))
        except ValueError as exc:
            raise NetworkIntentError(f"{field} must be a canonical IPv4 or IPv6 CIDR network") from exc

    @classmethod
    def _string_list(cls, value: object, field: str, *, maximum: int = 64, item_maximum: int = 120) -> list[str]:
        items = cls._array(value, field, maximum)
        result = [cls._text(item, f"{field}[{index}]", item_maximum) for index, item in enumerate(items)]
        if len(set(result)) != len(result):
            raise NetworkIntentError(f"{field} contains duplicate values")
        return sorted(result, key=str.casefold)

    @classmethod
    def _validate_secret_free(cls, value: object, path: str = "$") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str) or not key.strip():
                    raise NetworkIntentError(f"{path} contains an invalid field name")
                if _SECRET_NAME.search(key):
                    raise NetworkIntentError(
                        f"{path}.{key}: inline secret-like fields are not allowed; use the Credential Vault reference"
                    )
                cls._validate_secret_free(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                cls._validate_secret_free(child, f"{path}[{index}]")
        elif isinstance(value, float) and not __import__("math").isfinite(value):
            raise NetworkIntentError(f"{path} contains a non-finite number")
        elif not isinstance(value, (str, int, float, bool, type(None))):
            raise NetworkIntentError(f"{path} contains a non-JSON value")

    @classmethod
    def normalize_definition(cls, definition: object) -> dict[str, Any]:
        allowed_root = {"schema_version", *_ROOT_ARRAYS}
        root = cls._object(definition, "$", allowed_root, {"schema_version"})
        if root["schema_version"] != cls.SCHEMA_VERSION:
            raise NetworkIntentError(
                f"schema_version must be {cls.SCHEMA_VERSION}; unsupported versions require an explicit schema migration"
            )
        cls._validate_secret_free(root)

        normalized: dict[str, Any] = {"schema_version": cls.SCHEMA_VERSION}
        for name in _ROOT_ARRAYS:
            normalized[name] = []

        # Device/target bindings preserve the topology logical ID as the
        # identity and map it to a Project-owned managed Device separately.
        seen_nodes: set[str] = set()
        seen_devices: set[str] = set()
        for index, raw in enumerate(cls._array(root.get("targets", []), "targets", 256)):
            item = cls._object(raw, f"targets[{index}]", {"logical_node_id", "device_id"}, {"logical_node_id", "device_id"})
            node_id = cls._identifier(item["logical_node_id"], f"targets[{index}].logical_node_id")
            device_id = cls._identifier(item["device_id"], f"targets[{index}].device_id")
            if node_id in seen_nodes:
                raise NetworkIntentError(f"targets contains duplicate logical node {node_id}")
            if device_id in seen_devices:
                raise NetworkIntentError(f"targets maps more than one logical node to Device {device_id}")
            seen_nodes.add(node_id)
            seen_devices.add(device_id)
            normalized["targets"].append({"logical_node_id": node_id, "device_id": device_id})
        normalized["targets"].sort(key=lambda item: item["logical_node_id"])

        # Shared L2/L3 network segment declarations.
        segment_ids: set[str] = set()
        vlan_ids: set[int] = set()
        for index, raw in enumerate(cls._array(root.get("segments", []), "segments", 256)):
            field = f"segments[{index}]"
            item = cls._object(
                raw, field,
                {"segment_id", "name", "vlan_id", "ipv4_cidr", "ipv6_cidr"},
                {"segment_id", "name"},
            )
            segment_id = cls._identifier(item["segment_id"], field + ".segment_id")
            if segment_id in segment_ids:
                raise NetworkIntentError(f"segments contains duplicate ID {segment_id}")
            segment_ids.add(segment_id)
            record: dict[str, Any] = {
                "segment_id": segment_id,
                "name": cls._text(item["name"], field + ".name"),
            }
            if "vlan_id" in item and item["vlan_id"] is not None:
                vlan_id = cls._integer(item["vlan_id"], field + ".vlan_id", 1, 4094)
                if vlan_id in vlan_ids:
                    raise NetworkIntentError(f"VLAN {vlan_id} is assigned to more than one segment")
                vlan_ids.add(vlan_id)
                record["vlan_id"] = vlan_id
            for key, version in (("ipv4_cidr", 4), ("ipv6_cidr", 6)):
                if key in item and item[key] not in (None, ""):
                    network = ipaddress.ip_network(cls._network(item[key], field + "." + key))
                    if network.version != version:
                        raise NetworkIntentError(f"{field}.{key} must be IPv{version}")
                    record[key] = str(network)
            if not any(key in record for key in ("ipv4_cidr", "ipv6_cidr", "vlan_id")):
                raise NetworkIntentError(f"{field} must define at least one VLAN or IP network")
            normalized["segments"].append(record)
        normalized["segments"].sort(key=lambda item: item["segment_id"])

        # Interface L2/L3 configuration is expressed independently of CLI.
        interface_keys: set[tuple[str, str]] = set()
        interface_names: dict[str, set[str]] = {}
        for index, raw in enumerate(cls._array(root.get("interfaces", []), "interfaces", 1024)):
            field = f"interfaces[{index}]"
            item = cls._object(
                raw, field,
                {"logical_node_id", "name", "admin_state", "mode", "addresses", "segment_id",
                 "access_vlan_id", "native_vlan_id", "allowed_vlans"},
                {"logical_node_id", "name", "admin_state", "mode"},
            )
            node_id = cls._identifier(item["logical_node_id"], field + ".logical_node_id")
            name = cls._text(item["name"], field + ".name", 64)
            key = (node_id, name.casefold())
            if key in interface_keys:
                raise NetworkIntentError(f"{field} duplicates interface {name} on {node_id}")
            interface_keys.add(key)
            interface_names.setdefault(node_id, set()).add(name.casefold())
            admin_state = str(item["admin_state"]).upper()
            mode = str(item["mode"]).upper()
            if admin_state not in {"UP", "DOWN"}:
                raise NetworkIntentError(f"{field}.admin_state must be UP or DOWN")
            if mode not in {"ROUTED", "ACCESS", "TRUNK"}:
                raise NetworkIntentError(f"{field}.mode must be ROUTED, ACCESS or TRUNK")
            addresses = [
                cls._ip_interface(value, f"{field}.addresses[{position}]")
                for position, value in enumerate(cls._array(item.get("addresses", []), field + ".addresses", 32))
            ]
            if len(set(addresses)) != len(addresses):
                raise NetworkIntentError(f"{field}.addresses contains duplicates")
            record = {
                "logical_node_id": node_id, "name": name,
                "admin_state": admin_state, "mode": mode,
                "addresses": sorted(addresses, key=lambda value: (ipaddress.ip_interface(value).version, value)),
            }
            segment_id = item.get("segment_id")
            if segment_id not in (None, ""):
                record["segment_id"] = cls._identifier(segment_id, field + ".segment_id")
            if "access_vlan_id" in item and item["access_vlan_id"] is not None:
                record["access_vlan_id"] = cls._integer(item["access_vlan_id"], field + ".access_vlan_id", 1, 4094)
            if "native_vlan_id" in item and item["native_vlan_id"] is not None:
                record["native_vlan_id"] = cls._integer(item["native_vlan_id"], field + ".native_vlan_id", 1, 4094)
            if "allowed_vlans" in item:
                record["allowed_vlans"] = sorted({
                    cls._integer(value, f"{field}.allowed_vlans[{position}]", 1, 4094)
                    for position, value in enumerate(cls._array(item["allowed_vlans"], field + ".allowed_vlans", 256))
                })
            if mode == "ACCESS":
                if "access_vlan_id" not in record:
                    raise NetworkIntentError(f"{field} in ACCESS mode requires access_vlan_id")
                if "native_vlan_id" in record or "allowed_vlans" in record:
                    raise NetworkIntentError(f"{field} in ACCESS mode cannot declare trunk VLAN settings")
            elif mode == "TRUNK":
                if "access_vlan_id" in record:
                    raise NetworkIntentError(f"{field} in TRUNK mode cannot declare access_vlan_id")
                if "allowed_vlans" in record and not record["allowed_vlans"]:
                    raise NetworkIntentError(f"{field}.allowed_vlans cannot be empty")
            else:
                if any(key in record for key in ("access_vlan_id", "native_vlan_id", "allowed_vlans")):
                    raise NetworkIntentError(f"{field} in ROUTED mode cannot declare switchport VLAN settings")
            normalized["interfaces"].append(record)
        normalized["interfaces"].sort(key=lambda item: (item["logical_node_id"], item["name"].casefold()))

        for section in ("static_routes",):
            for index, raw in enumerate(cls._array(root.get(section, []), section, 1024)):
                field = f"{section}[{index}]"
                item = cls._object(
                    raw, field,
                    {"logical_node_id", "destination", "next_hop", "metric", "interface_name"},
                    {"logical_node_id", "destination", "next_hop"},
                )
                node_id = cls._identifier(item["logical_node_id"], field + ".logical_node_id")
                destination = ipaddress.ip_network(cls._network(item["destination"], field + ".destination"))
                next_hop = ipaddress.ip_address(cls._ip_address(item["next_hop"], field + ".next_hop"))
                if destination.version != next_hop.version:
                    raise NetworkIntentError(f"{field}.destination and next_hop must use the same IP family")
                record = {
                    "logical_node_id": node_id,
                    "destination": str(destination),
                    "next_hop": str(next_hop),
                    "metric": cls._integer(item.get("metric", 1), field + ".metric", 0, 16_777_215),
                }
                if item.get("interface_name"):
                    record["interface_name"] = cls._text(item["interface_name"], field + ".interface_name", 64)
                normalized[section].append(record)
            normalized[section].sort(key=lambda item: (item["logical_node_id"], item["destination"], item["next_hop"]))

        for index, raw in enumerate(cls._array(root.get("ospf", []), "ospf", 256)):
            field = f"ospf[{index}]"
            item = cls._object(raw, field, {"logical_node_id", "process_id", "router_id", "areas"}, {"logical_node_id", "process_id", "router_id", "areas"})
            node_id = cls._identifier(item["logical_node_id"], field + ".logical_node_id")
            process_id = cls._integer(item["process_id"], field + ".process_id", 1, 65535)
            router_id = cls._ip_address(item["router_id"], field + ".router_id", 4)
            areas = []
            area_ids: set[str] = set()
            for area_index, area_raw in enumerate(cls._array(item["areas"], field + ".areas", 256)):
                area_field = f"{field}.areas[{area_index}]"
                area = cls._object(area_raw, area_field, {"area_id", "networks"}, {"area_id", "networks"})
                area_id = cls._text(area["area_id"], area_field + ".area_id", 32)
                try:
                    ipaddress.IPv4Address(area_id)
                except ValueError:
                    if not area_id.isdigit() or not 0 <= int(area_id) <= 4_294_967_295:
                        raise NetworkIntentError(f"{area_field}.area_id must be a 32-bit OSPF area identifier")
                if area_id in area_ids:
                    raise NetworkIntentError(f"{field} contains duplicate OSPF area {area_id}")
                area_ids.add(area_id)
                networks = [cls._network(value, f"{area_field}.networks[{i}]") for i, value in enumerate(cls._array(area["networks"], area_field + ".networks", 256))]
                if not networks:
                    raise NetworkIntentError(f"{area_field}.networks must not be empty")
                areas.append({"area_id": area_id, "networks": sorted(set(networks))})
            if not areas:
                raise NetworkIntentError(f"{field}.areas must not be empty")
            normalized["ospf"].append({"logical_node_id": node_id, "process_id": process_id, "router_id": router_id, "areas": sorted(areas, key=lambda item: item["area_id"])})
        normalized["ospf"].sort(key=lambda item: (item["logical_node_id"], item["process_id"]))

        for index, raw in enumerate(cls._array(root.get("bgp", []), "bgp", 256)):
            field = f"bgp[{index}]"
            item = cls._object(raw, field, {"logical_node_id", "local_asn", "router_id", "neighbors"}, {"logical_node_id", "local_asn", "router_id", "neighbors"})
            node_id = cls._identifier(item["logical_node_id"], field + ".logical_node_id")
            local_asn = cls._integer(item["local_asn"], field + ".local_asn", 1, 4_294_967_295)
            router_id = cls._ip_address(item["router_id"], field + ".router_id", 4)
            neighbors = []
            neighbor_addresses: set[str] = set()
            for neighbor_index, neighbor_raw in enumerate(cls._array(item["neighbors"], field + ".neighbors", 256)):
                neighbor_field = f"{field}.neighbors[{neighbor_index}]"
                neighbor = cls._object(neighbor_raw, neighbor_field, {"address", "remote_asn", "description"}, {"address", "remote_asn"})
                address = cls._ip_address(neighbor["address"], neighbor_field + ".address")
                if address in neighbor_addresses:
                    raise NetworkIntentError(f"{field} contains duplicate BGP neighbor {address}")
                neighbor_addresses.add(address)
                record = {"address": address, "remote_asn": cls._integer(neighbor["remote_asn"], neighbor_field + ".remote_asn", 1, 4_294_967_295)}
                if neighbor.get("description"):
                    record["description"] = cls._text(neighbor["description"], neighbor_field + ".description", 120)
                neighbors.append(record)
            if not neighbors:
                raise NetworkIntentError(f"{field}.neighbors must not be empty")
            normalized["bgp"].append({"logical_node_id": node_id, "local_asn": local_asn, "router_id": router_id, "neighbors": sorted(neighbors, key=lambda item: item["address"])})
        normalized["bgp"].sort(key=lambda item: item["logical_node_id"])

        for index, raw in enumerate(cls._array(root.get("aggregations", []), "aggregations", 256)):
            field = f"aggregations[{index}]"
            item = cls._object(raw, field, {"logical_node_id", "name", "protocol", "mode", "members"}, {"logical_node_id", "name", "protocol", "mode", "members"})
            node_id = cls._identifier(item["logical_node_id"], field + ".logical_node_id")
            protocol = str(item["protocol"]).upper()
            mode = str(item["mode"]).upper()
            if protocol != "LACP" or mode not in {"ACTIVE", "PASSIVE"}:
                raise NetworkIntentError(f"{field} supports only protocol LACP and mode ACTIVE or PASSIVE")
            members = cls._string_list(item["members"], field + ".members", maximum=32, item_maximum=64)
            if len(members) < 2:
                raise NetworkIntentError(f"{field}.members must contain at least two interfaces")
            normalized["aggregations"].append({"logical_node_id": node_id, "name": cls._text(item["name"], field + ".name", 64), "protocol": protocol, "mode": mode, "members": members})
        normalized["aggregations"].sort(key=lambda item: (item["logical_node_id"], item["name"].casefold()))

        for index, raw in enumerate(cls._array(root.get("firewall_zones", []), "firewall_zones", 256)):
            field = f"firewall_zones[{index}]"
            item = cls._object(raw, field, {"logical_node_id", "zone_id", "name", "interfaces"}, {"logical_node_id", "zone_id", "name", "interfaces"})
            node_id = cls._identifier(item["logical_node_id"], field + ".logical_node_id")
            normalized["firewall_zones"].append({
                "logical_node_id": node_id,
                "zone_id": cls._identifier(item["zone_id"], field + ".zone_id"),
                "name": cls._text(item["name"], field + ".name"),
                "interfaces": cls._string_list(item["interfaces"], field + ".interfaces", maximum=64, item_maximum=64),
            })
        normalized["firewall_zones"].sort(key=lambda item: (item["logical_node_id"], item["zone_id"]))

        for index, raw in enumerate(cls._array(root.get("firewall_rules", []), "firewall_rules", 1024)):
            field = f"firewall_rules[{index}]"
            item = cls._object(
                raw, field,
                {"logical_node_id", "rule_id", "name", "source_zone_id", "destination_zone_id",
                 "action", "protocol", "source_cidrs", "destination_cidrs", "destination_ports"},
                {"logical_node_id", "rule_id", "name", "source_zone_id", "destination_zone_id", "action", "protocol"},
            )
            node_id = cls._identifier(item["logical_node_id"], field + ".logical_node_id")
            action = str(item["action"]).upper()
            protocol = str(item["protocol"]).upper()
            if action not in {"ALLOW", "DENY"}:
                raise NetworkIntentError(f"{field}.action must be ALLOW or DENY")
            if protocol not in {"ANY", "TCP", "UDP", "ICMP"}:
                raise NetworkIntentError(f"{field}.protocol must be ANY, TCP, UDP or ICMP")
            ports = []
            for port_index, port_raw in enumerate(cls._array(item.get("destination_ports", []), field + ".destination_ports", 64)):
                port_field = f"{field}.destination_ports[{port_index}]"
                port = cls._object(port_raw, port_field, {"start", "end"}, {"start", "end"})
                start = cls._integer(port["start"], port_field + ".start", 1, 65535)
                end = cls._integer(port["end"], port_field + ".end", start, 65535)
                if protocol not in {"TCP", "UDP"}:
                    raise NetworkIntentError(f"{port_field} is only valid for TCP or UDP rules")
                ports.append({"start": start, "end": end})
            source_cidrs = sorted(set(cls._network(value, f"{field}.source_cidrs[{i}]") for i, value in enumerate(cls._array(item.get("source_cidrs", []), field + ".source_cidrs", 128))))
            destination_cidrs = sorted(set(cls._network(value, f"{field}.destination_cidrs[{i}]") for i, value in enumerate(cls._array(item.get("destination_cidrs", []), field + ".destination_cidrs", 128))))
            normalized["firewall_rules"].append({
                "logical_node_id": node_id,
                "rule_id": cls._identifier(item["rule_id"], field + ".rule_id"),
                "name": cls._text(item["name"], field + ".name"),
                "source_zone_id": cls._identifier(item["source_zone_id"], field + ".source_zone_id"),
                "destination_zone_id": cls._identifier(item["destination_zone_id"], field + ".destination_zone_id"),
                "action": action, "protocol": protocol,
                "source_cidrs": source_cidrs, "destination_cidrs": destination_cidrs,
                "destination_ports": sorted(ports, key=lambda entry: (entry["start"], entry["end"])),
            })
        normalized["firewall_rules"].sort(key=lambda item: (item["logical_node_id"], item["rule_id"]))

        for index, raw in enumerate(cls._array(root.get("service_references", []), "service_references", 256)):
            field = f"service_references[{index}]"
            item = cls._object(raw, field, {"logical_node_id", "service_type", "profile_id", "revision_id"}, {"logical_node_id", "service_type", "profile_id", "revision_id"})
            service_type = str(item["service_type"]).upper()
            if service_type not in {"DHCP", "DNS"}:
                raise NetworkIntentError(f"{field}.service_type must be DHCP or DNS")
            normalized["service_references"].append({
                "logical_node_id": cls._identifier(item["logical_node_id"], field + ".logical_node_id"),
                "service_type": service_type,
                "profile_id": cls._identifier(item["profile_id"], field + ".profile_id"),
                "revision_id": cls._identifier(item["revision_id"], field + ".revision_id"),
            })
        normalized["service_references"].sort(key=lambda item: (item["logical_node_id"], item["service_type"], item["profile_id"]))

        for index, raw in enumerate(cls._array(root.get("linux_bridges", []), "linux_bridges", 256)):
            field = f"linux_bridges[{index}]"
            item = cls._object(raw, field, {"logical_node_id", "name", "members"}, {"logical_node_id", "name", "members"})
            members = cls._string_list(item["members"], field + ".members", maximum=64, item_maximum=64)
            if len(members) < 1:
                raise NetworkIntentError(f"{field}.members must contain at least one interface")
            normalized["linux_bridges"].append({"logical_node_id": cls._identifier(item["logical_node_id"], field + ".logical_node_id"), "name": cls._text(item["name"], field + ".name", 64), "members": members})
        normalized["linux_bridges"].sort(key=lambda item: (item["logical_node_id"], item["name"].casefold()))

        for index, raw in enumerate(cls._array(root.get("linux_vlan_interfaces", []), "linux_vlan_interfaces", 512)):
            field = f"linux_vlan_interfaces[{index}]"
            item = cls._object(raw, field, {"logical_node_id", "name", "parent_interface", "vlan_id"}, {"logical_node_id", "name", "parent_interface", "vlan_id"})
            normalized["linux_vlan_interfaces"].append({
                "logical_node_id": cls._identifier(item["logical_node_id"], field + ".logical_node_id"),
                "name": cls._text(item["name"], field + ".name", 64),
                "parent_interface": cls._text(item["parent_interface"], field + ".parent_interface", 64),
                "vlan_id": cls._integer(item["vlan_id"], field + ".vlan_id", 1, 4094),
            })
        normalized["linux_vlan_interfaces"].sort(key=lambda item: (item["logical_node_id"], item["name"].casefold()))

        encoded = _canonical(normalized)
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise NetworkIntentError("canonical network intent exceeds the 1,000,000-byte limit")
        return normalized

    def _load_profile_and_topology(self, project_id: str, topology_revision_id: str, profile_id: str | None = None):
        topology_revision_id = self._identifier(topology_revision_id, "topology_revision_id")
        if profile_id:
            profile_id = self._identifier(profile_id, "profile_id")
        topology_revision = self.topology.get_revision(topology_revision_id)
        if topology_revision is None:
            raise NetworkIntentNotFound("topology revision not found")
        topology_profile = self.topology.get_profile(topology_revision["profile_id"])
        if topology_profile is None or topology_profile["project_id"] != project_id:
            raise NetworkIntentNotFound("topology revision not found in this Project")
        if topology_profile["status"] != "ACTIVE":
            raise NetworkIntentConflict("archived topology profiles cannot receive network intent")
        if profile_id:
            profile = self.get_profile(profile_id)
            if profile is None or profile["project_id"] != project_id:
                raise NetworkIntentNotFound("network intent profile not found in this Project")
            if profile["topology_profile_id"] != topology_profile["profile_id"]:
                raise NetworkIntentConflict("network intent revision must reference a topology revision from its bound topology profile")
        else:
            profile = None
        return profile, topology_profile, topology_revision

    def _validate_service_references(self, project_id: str, intent: dict[str, Any]) -> None:
        for item in intent["service_references"]:
            with self.database.connection() as connection:
                row = connection.execute(
                    """SELECT p.project_id,p.status,r.profile_id,r.status AS revision_status,
                              s.status AS schema_status
                       FROM configuration_profiles p
                       JOIN configuration_revisions r ON r.revision_id=? AND r.profile_id=p.profile_id
                       JOIN configuration_schemas s ON s.schema_record_id=p.schema_record_id
                       WHERE p.profile_id=?""",
                    (item["revision_id"], item["profile_id"]),
                ).fetchone()
            if row is None or row["project_id"] != project_id or row["profile_id"] != item["profile_id"]:
                raise NetworkIntentNotFound("DHCP/DNS configuration reference is not available in this Project")
            if row["status"] != "PUBLISHED" or row["revision_status"] != "PUBLISHED":
                raise NetworkIntentConflict("DHCP/DNS references must point to published configuration profiles and revisions")
            if row["schema_status"] != "ACTIVE":
                raise NetworkIntentConflict("DHCP/DNS references must use an active registered configuration schema")

    def _validate_targets_and_references(
        self, project_id: str, topology_profile: dict, topology_revision: dict,
        intent: dict[str, Any],
    ) -> None:
        nodes = {item["id"]: item for item in topology_revision["definition"]["nodes"]}
        for section in ("interfaces", "static_routes", "ospf", "bgp", "aggregations",
                        "firewall_zones", "firewall_rules", "service_references",
                        "linux_bridges", "linux_vlan_interfaces"):
            for item in intent[section]:
                if item["logical_node_id"] not in nodes:
                    raise NetworkIntentError(
                        f"{section} references unknown topology logical node {item['logical_node_id']}"
                    )
        for item in intent["targets"]:
            if item["logical_node_id"] not in nodes:
                raise NetworkIntentError(f"target binding references unknown topology logical node {item['logical_node_id']}")
            with self.database.connection() as connection:
                device = connection.execute(
                    "SELECT project_id,lab_id,status FROM devices WHERE device_id=?",
                    (item["device_id"],),
                ).fetchone()
            if device is None or device["project_id"] != project_id:
                raise NetworkIntentNotFound("target Device not found in this Project")
            if device["status"] != "ACTIVE":
                raise NetworkIntentConflict("network intent targets must use active Devices")
            if topology_profile["scope_type"] == "LAB" and device["lab_id"] != topology_profile["lab_id"]:
                raise NetworkIntentNotFound("target Device is not in the topology profile Lab")
        segment_ids = {item["segment_id"] for item in intent["segments"]}
        zone_ids: dict[str, set[str]] = {}
        for item in intent["firewall_zones"]:
            key = item["logical_node_id"]
            zone_ids.setdefault(key, set())
            if item["zone_id"] in zone_ids[key]:
                raise NetworkIntentError(f"firewall_zones has duplicate zone ID {item['zone_id']} on {key}")
            zone_ids[key].add(item["zone_id"])
        for item in intent["interfaces"]:
            if item.get("segment_id") and item["segment_id"] not in segment_ids:
                raise NetworkIntentError(f"interface {item['name']} references an unknown network segment")
        for item in intent["firewall_rules"]:
            zones = zone_ids.get(item["logical_node_id"], set())
            if item["source_zone_id"] not in zones or item["destination_zone_id"] not in zones:
                raise NetworkIntentError(f"firewall rule {item['rule_id']} references an unknown zone")
        interface_names: dict[str, set[str]] = {}
        for item in intent["interfaces"]:
            interface_names.setdefault(item["logical_node_id"], set()).add(item["name"].casefold())
        for node_id, node in nodes.items():
            for interface in node.get("interfaces", []):
                interface_names.setdefault(node_id, set()).add(str(interface.get("name", "")).casefold())
        def require_interface(node_id: str, name: str, field: str) -> None:
            if name.casefold() not in interface_names.get(node_id, set()):
                raise NetworkIntentError(f"{field} references undeclared interface {name} on {node_id}")
        for item in intent["static_routes"]:
            if item.get("interface_name"):
                require_interface(item["logical_node_id"], item["interface_name"], "static route")
        for item in intent["aggregations"]:
            for name in item["members"]:
                require_interface(item["logical_node_id"], name, "LACP aggregation")
        for item in intent["firewall_zones"]:
            for name in item["interfaces"]:
                require_interface(item["logical_node_id"], name, "firewall zone")
        for item in intent["linux_bridges"]:
            for name in item["members"]:
                require_interface(item["logical_node_id"], name, "Linux bridge")
        for item in intent["linux_vlan_interfaces"]:
            require_interface(item["logical_node_id"], item["parent_interface"], "Linux VLAN interface")

    @staticmethod
    def _required_capabilities(intent: dict[str, Any]) -> dict[str, set[str]]:
        required: dict[str, set[str]] = {}
        def add(node_id: str, feature: str) -> None:
            required.setdefault(node_id, set()).add(feature)
        for item in intent["interfaces"]:
            add(item["logical_node_id"], "interfaces.admin_state")
            for address in item["addresses"]:
                family = ipaddress.ip_interface(address).version
                add(item["logical_node_id"], f"addressing.ipv{family}")
            if item["mode"] == "ACCESS":
                add(item["logical_node_id"], "vlans.access")
            elif item["mode"] == "TRUNK":
                add(item["logical_node_id"], "vlans.trunk")
        for item in intent["static_routes"]:
            family = ipaddress.ip_network(item["destination"]).version
            add(item["logical_node_id"], f"routing.static_ipv{family}")
        for item in intent["ospf"]:
            add(item["logical_node_id"], "routing.ospf")
        for item in intent["bgp"]:
            add(item["logical_node_id"], "routing.bgp")
        for item in intent["aggregations"]:
            add(item["logical_node_id"], "aggregation.lacp")
        for item in intent["firewall_zones"]:
            add(item["logical_node_id"], "firewall.zones")
        for item in intent["firewall_rules"]:
            add(item["logical_node_id"], "firewall.basic_acl")
        for item in intent["service_references"]:
            add(item["logical_node_id"], f"services.{item['service_type'].lower()}")
        for item in intent["linux_bridges"]:
            add(item["logical_node_id"], "linux.bridge")
        for item in intent["linux_vlan_interfaces"]:
            add(item["logical_node_id"], "linux.vlan_interface")
        return required

    def _latest_capability_report(self, device_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM device_capability_reports WHERE device_id=?
                   ORDER BY observed_at DESC, recorded_at DESC, report_id DESC LIMIT 1""",
                (device_id,),
            ).fetchone()
        return self._capability_report(row) if row is not None else None

    @staticmethod
    def _capability_report(row) -> dict[str, Any] | None:
        if row is None:
            return None
        result = {key: row[key] for key in (
            "report_id", "project_id", "device_id", "provider_id", "platform",
            "software_version", "adapter_name", "adapter_version", "source_type",
            "capability_sha256", "observed_at", "recorded_at", "recorded_by",
        )}
        result["capabilities"] = json.loads(row["capabilities_json"])
        encoded = _canonical(result["capabilities"])
        if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != result["capability_sha256"]:
            raise NetworkIntentError("stored device capability report failed its SHA-256 integrity check")
        return result

    def validate(
        self, project_id: str, topology_revision_id: str, definition: object,
        *, profile_id: str | None = None, evaluate_capabilities: bool = False,
    ) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        try:
            project_id = self._text(project_id, "project_id", 128)
            intent = self.normalize_definition(definition)
            profile, topology_profile, topology_revision = self._load_profile_and_topology(
                project_id, topology_revision_id, profile_id
            )
            self._validate_targets_and_references(project_id, topology_profile, topology_revision, intent)
            self._validate_service_references(project_id, intent)
        except NetworkIntentNotFound as exc:
            return {
                "valid": False, "capability_status": "NOT_EVALUATED",
                "ready_for_compilation": False, "schema_version": self.SCHEMA_VERSION,
                "diagnostics": [{"code": "REFERENCE_NOT_FOUND", "severity": "ERROR", "message": str(exc)}],
            }
        except (NetworkIntentError, TypeError, ValueError) as exc:
            return {
                "valid": False, "capability_status": "NOT_EVALUATED",
                "ready_for_compilation": False, "schema_version": self.SCHEMA_VERSION,
                "diagnostics": [{"code": "INVALID_NETWORK_INTENT", "severity": "ERROR", "message": str(exc)}],
            }

        required = self._required_capabilities(intent)
        capability_status = "NOT_REQUIRED" if not required else ("NOT_EVALUATED" if not evaluate_capabilities else "COMPATIBLE")
        target_devices = {item["logical_node_id"]: item["device_id"] for item in intent["targets"]}
        if evaluate_capabilities:
            for node_id, features in sorted(required.items()):
                device_id = target_devices.get(node_id)
                if not device_id:
                    diagnostics.append({
                        "code": "TARGET_BINDING_REQUIRED", "severity": "ERROR",
                        "logical_node_id": node_id,
                        "message": f"Logical node {node_id} needs an explicit managed Device binding before capability validation",
                    })
                    capability_status = "UNKNOWN"
                    continue
                report = self._latest_capability_report(device_id)
                if report is None:
                    diagnostics.append({
                        "code": "CAPABILITY_REPORT_MISSING", "severity": "ERROR",
                        "logical_node_id": node_id, "device_id": device_id,
                        "message": f"No adapter-observed capability report exists for Device {device_id}",
                    })
                    capability_status = "UNKNOWN"
                    continue
                observed_at = datetime.fromisoformat(report["observed_at"].replace("Z", "+00:00"))
                age = datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)
                if age > self.CAPABILITY_REPORT_MAX_AGE or age < -self.CAPABILITY_REPORT_MAX_FUTURE_SKEW:
                    code = "CAPABILITY_REPORT_STALE" if age > self.CAPABILITY_REPORT_MAX_AGE else "CAPABILITY_REPORT_FUTURE"
                    reason = "older than seven days" if code == "CAPABILITY_REPORT_STALE" else "more than five minutes in the future"
                    diagnostics.append({
                        "code": code, "severity": "ERROR",
                        "logical_node_id": node_id, "device_id": device_id,
                        "message": f"Device {device_id} capability observation is {reason}; record a fresh adapter observation",
                    })
                    capability_status = "UNKNOWN"
                    continue
                for feature in sorted(features):
                    observed = report["capabilities"].get(feature)
                    state = observed.get("status") if isinstance(observed, Mapping) else None
                    if state == "UNSUPPORTED":
                        diagnostics.append({
                            "code": "CAPABILITY_UNSUPPORTED", "severity": "ERROR",
                            "logical_node_id": node_id, "device_id": device_id,
                            "feature_id": feature,
                            "message": f"Device {device_id} explicitly reports {feature} as unsupported",
                        })
                        capability_status = "INCOMPATIBLE"
                    elif state != "SUPPORTED":
                        diagnostics.append({
                            "code": "CAPABILITY_UNKNOWN", "severity": "ERROR",
                            "logical_node_id": node_id, "device_id": device_id,
                            "feature_id": feature,
                            "message": f"Device {device_id} has no observation for required capability {feature}",
                        })
                        if capability_status != "INCOMPATIBLE":
                            capability_status = "UNKNOWN"
        canonical = _canonical(intent)
        errors = sum(1 for item in diagnostics if item["severity"] == "ERROR")
        valid = errors == 0
        return {
            "valid": valid,
            "capability_status": capability_status,
            "ready_for_compilation": valid and capability_status in {"NOT_REQUIRED", "COMPATIBLE"},
            "schema_version": self.SCHEMA_VERSION,
            "topology_revision_id": topology_revision_id,
            "topology_content_sha256": self.topology.get_revision(topology_revision_id)["content_sha256"],
            "intent_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "required_capabilities": {
                node_id: sorted(features) for node_id, features in sorted(required.items())
            },
            "diagnostics": diagnostics,
            "summary": {"errors": errors, "warnings": 0, "target_nodes": len(required)},
            "normalized_intent": intent,
        }

    def get_profile(self, profile_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM network_intent_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        return self._profile(row)

    @staticmethod
    def _profile(row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in (
            "profile_id", "project_id", "topology_profile_id", "name", "description",
            "scope_type", "scope_id", "lab_id", "status", "created_at", "updated_at",
            "created_by", "updated_by",
        )}

    @staticmethod
    def _revision(row) -> dict | None:
        if row is None:
            return None
        result = {key: row[key] for key in (
            "revision_id", "profile_id", "topology_revision_id", "topology_content_sha256", "schema_version",
            "revision_number", "intent_sha256", "provenance_json", "parent_revision_id",
            "status", "created_at", "created_by", "published_at", "published_by",
        )}
        result["definition"] = json.loads(row["definition_json"])
        result["provenance"] = json.loads(row["provenance_json"])
        encoded = _canonical(result["definition"])
        if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != result["intent_sha256"]:
            raise NetworkIntentError("stored network intent revision failed its SHA-256 integrity check")
        return result

    @staticmethod
    def _audit(connection, actor: str, action: str, resource_type: str, resource_id: str, details: dict) -> None:
        connection.execute(
            """INSERT INTO audit_events(
               audit_id,actor_username,action,resource_type,resource_id,details_json,occurred_at
            ) VALUES(?,?,?,?,?,?,?)""",
            ("AUD-" + secrets.token_hex(12), actor, action, resource_type, resource_id,
             _canonical(details), NetworkIntentService._now()),
        )

    def list_profiles(self, project_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM network_intent_profiles WHERE project_id=?
                   ORDER BY scope_type,scope_id,name COLLATE NOCASE""",
                (project_id,),
            ).fetchall()
        return [self._profile(row) for row in rows]

    def create_profile(
        self, *, project_id: str, topology_profile_id: str, name: str,
        description: str = "", actor: str,
    ) -> dict[str, Any]:
        project_id = self._text(project_id, "project_id", 128)
        topology_profile_id = self._identifier(topology_profile_id, "topology_profile_id")
        name = self._text(name, "name", 120)
        description = str(description or "").strip()
        if len(description) > 500 or any(ord(char) < 32 for char in description):
            raise NetworkIntentError("description must be at most 500 printable characters")
        actor = self._actor(actor)
        topology_profile = self.topology.get_profile(topology_profile_id)
        if topology_profile is None or topology_profile["project_id"] != project_id:
            raise NetworkIntentNotFound("topology profile not found in this Project")
        if topology_profile["status"] != "ACTIVE":
            raise NetworkIntentConflict("network intent profiles require an active topology profile")
        now = self._now()
        profile_id = "nipt_" + secrets.token_hex(12)
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO network_intent_profiles(
                       profile_id,project_id,topology_profile_id,name,description,
                       scope_type,scope_id,lab_id,status,created_at,updated_at,created_by,updated_by
                    ) VALUES(?,?,?,?,?,?,?,?, 'ACTIVE',?,?,?,?)""",
                    (
                        profile_id, project_id, topology_profile_id, name, description,
                        topology_profile["scope_type"], topology_profile["scope_id"],
                        topology_profile["lab_id"], now, now, actor, actor,
                    ),
                )
                self._audit(connection, actor, "NETWORK_INTENT_PROFILE_CREATED",
                            "NETWORK_INTENT_PROFILE", profile_id,
                            {"project_id": project_id, "topology_profile_id": topology_profile_id,
                             "scope_type": topology_profile["scope_type"], "scope_id": topology_profile["scope_id"]})
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise NetworkIntentConflict("a network intent profile with this name already exists for the selected topology") from exc
            if "FOREIGN KEY constraint failed" in str(exc):
                raise NetworkIntentNotFound("Project or topology profile no longer exists") from exc
            raise
        return self.get_profile(profile_id) or {}

    def list_revisions(self, profile_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM network_intent_revisions WHERE profile_id=? ORDER BY revision_number DESC",
                (profile_id,),
            ).fetchall()
        return [self._revision(row) for row in rows]

    def get_revision(self, revision_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM network_intent_revisions WHERE revision_id=?",
                (revision_id,),
            ).fetchone()
        return self._revision(row)

    def create_revision(
        self, profile_id: str, *, topology_revision_id: str, definition: object,
        actor: str, provenance: Mapping[str, Any] | None = None,
        parent_revision_id: str | None = None,
    ) -> dict[str, Any]:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise NetworkIntentNotFound("network intent profile not found")
        if profile["status"] != "ACTIVE":
            raise NetworkIntentConflict("archived network intent profiles cannot receive revisions")
        actor = self._actor(actor)
        topology_revision_id = self._identifier(topology_revision_id, "topology_revision_id")
        _loaded, topology_profile, topology_revision = self._load_profile_and_topology(
            profile["project_id"], topology_revision_id, profile_id
        )
        intent = self.normalize_definition(definition)
        self._validate_targets_and_references(profile["project_id"], topology_profile, topology_revision, intent)
        self._validate_service_references(profile["project_id"], intent)
        if provenance is None:
            provenance_value = {"source": "dashboard", "schema_version": self.SCHEMA_VERSION}
        elif isinstance(provenance, Mapping):
            provenance_value = dict(provenance)
        else:
            raise NetworkIntentError("provenance must be an object")
        self._validate_secret_free(provenance_value, "$.provenance")
        provenance_json = _canonical(provenance_value)
        if len(provenance_json.encode("utf-8")) > 16_384:
            raise NetworkIntentError("network intent provenance exceeds the 16,384-byte limit")
        encoded = _canonical(intent)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if parent_revision_id:
            parent_revision_id = self._identifier(parent_revision_id, "parent_revision_id")
            parent = self.get_revision(parent_revision_id)
            if parent is None or parent["profile_id"] != profile_id:
                raise NetworkIntentNotFound("parent revision does not belong to this network intent profile")
        now = self._now()
        revision_id = "nitr_" + secrets.token_hex(12)
        with self.database.transaction(immediate=True) as connection:
            number = int(connection.execute(
                "SELECT COALESCE(MAX(revision_number),0)+1 FROM network_intent_revisions WHERE profile_id=?",
                (profile_id,),
            ).fetchone()[0])
            connection.execute(
                """INSERT INTO network_intent_revisions(
                   revision_id,profile_id,topology_revision_id,topology_content_sha256,schema_version,
                   revision_number,definition_json,intent_sha256,provenance_json,parent_revision_id,
                   status,created_at,created_by,published_at,published_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,'DRAFT',?,?,NULL,NULL)""",
                (revision_id, profile_id, topology_revision_id, topology_revision["content_sha256"],
                 self.SCHEMA_VERSION, number, encoded, digest, provenance_json,
                 parent_revision_id, now, actor),
            )
            self._audit(connection, actor, "NETWORK_INTENT_REVISION_CREATED",
                        "NETWORK_INTENT_REVISION", revision_id,
                        {"profile_id": profile_id, "topology_revision_id": topology_revision_id,
                         "revision_number": number, "intent_sha256": digest})
        return self.get_revision(revision_id) or {}

    def publish(self, profile_id: str, revision_id: str, *, actor: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id)
        revision = self.get_revision(revision_id)
        if profile is None or revision is None or revision["profile_id"] != profile_id:
            raise NetworkIntentNotFound("network intent profile or revision not found")
        if revision["status"] != "DRAFT":
            raise NetworkIntentConflict("only draft network intent revisions can be published")
        topology_revision = self.topology.get_revision(revision["topology_revision_id"])
        if topology_revision is None or topology_revision["status"] != "PUBLISHED":
            raise NetworkIntentConflict("network intent can be published only against a published topology revision")
        if topology_revision["content_sha256"] != revision["topology_content_sha256"]:
            raise NetworkIntentConflict("the pinned topology content hash no longer matches the selected topology revision")
        validation = self.validate(
            profile["project_id"], revision["topology_revision_id"], revision["definition"],
            profile_id=profile_id, evaluate_capabilities=True,
        )
        if not validation["ready_for_compilation"]:
            raise NetworkIntentConflict(
                "network intent cannot be published until structural and observed-capability validation succeeds"
            )
        actor = self._actor(actor)
        now = self._now()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE network_intent_revisions SET status='PUBLISHED',published_at=?,published_by=?
                   WHERE revision_id=? AND status='DRAFT'""",
                (now, actor, revision_id),
            )
            if cursor.rowcount != 1:
                raise NetworkIntentConflict("network intent revision changed during publication")
            connection.execute(
                "UPDATE network_intent_profiles SET updated_at=?,updated_by=? WHERE profile_id=?",
                (now, actor, profile_id),
            )
            self._audit(connection, actor, "NETWORK_INTENT_REVISION_PUBLISHED",
                        "NETWORK_INTENT_REVISION", revision_id,
                        {"profile_id": profile_id, "intent_sha256": revision["intent_sha256"],
                         "topology_revision_id": revision["topology_revision_id"]})
        return self.get_revision(revision_id) or {}

    def rollback(self, profile_id: str, source_revision_id: str, *, actor: str) -> dict[str, Any]:
        source = self.get_revision(source_revision_id)
        if source is None or source["profile_id"] != profile_id:
            raise NetworkIntentNotFound("rollback source does not belong to this profile")
        if source["status"] != "PUBLISHED":
            raise NetworkIntentConflict("rollback source must be a published revision")
        return self.create_revision(
            profile_id, topology_revision_id=source["topology_revision_id"],
            definition=source["definition"], actor=actor,
            provenance={"source": "rollback", "source_revision_id": source_revision_id,
                        "source_intent_sha256": source["intent_sha256"]},
            parent_revision_id=source_revision_id,
        )

    def record_capability_report(
        self, *, project_id: str, device_id: str, platform: str,
        software_version: str, adapter_name: str, adapter_version: str,
        capabilities: Mapping[str, Any], actor: str, source_type: str = "PROVIDER_ADAPTER",
        provider_id: str | None = None, observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Append a provider/device adapter observation; there is deliberately no public write API."""
        project_id = self._text(project_id, "project_id", 128)
        device_id = self._identifier(device_id, "device_id")
        platform = self._text(platform, "platform", 120)
        software_version = self._text(software_version, "software_version", 80)
        adapter_name = self._text(adapter_name, "adapter_name", 80)
        adapter_version = self._text(adapter_version, "adapter_version", 80)
        actor = self._actor(actor)
        source_type = str(source_type or "").upper()
        if source_type not in {"PROVIDER_ADAPTER", "DEVICE_DISCOVERY"}:
            raise NetworkIntentError("source_type must be PROVIDER_ADAPTER or DEVICE_DISCOVERY")
        if source_type == "PROVIDER_ADAPTER" and not provider_id:
            raise NetworkIntentError("provider_id is required for PROVIDER_ADAPTER capability reports")
        if provider_id is not None:
            provider_id = str(provider_id).strip().lower()
            if provider_id not in self.SUPPORTED_PROVIDERS:
                raise NetworkIntentError("provider_id is not a supported adapter identity")
        if not isinstance(capabilities, Mapping) or not capabilities:
            raise NetworkIntentError("capabilities must be a non-empty feature map")
        normalized_capabilities = {}
        if set(capabilities) - _CAPABILITY_FEATURES:
            raise NetworkIntentError("capability report contains unknown feature IDs")
        for feature, raw in sorted(capabilities.items()):
            item = self._object(raw, f"capabilities.{feature}", {"status", "constraints"}, {"status"})
            status = str(item["status"]).upper()
            if status not in {"SUPPORTED", "UNSUPPORTED"}:
                raise NetworkIntentError(f"capabilities.{feature}.status must be SUPPORTED or UNSUPPORTED")
            constraints = item.get("constraints", {})
            if not isinstance(constraints, Mapping) or len(constraints) > 16:
                raise NetworkIntentError(f"capabilities.{feature}.constraints must be a bounded object")
            self._validate_secret_free(constraints, f"capabilities.{feature}.constraints")
            normalized_capabilities[feature] = {"status": status, "constraints": dict(constraints)}
        observed_value = observed_at or self._now()
        try:
            parsed = datetime.fromisoformat(str(observed_value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NetworkIntentError("observed_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise NetworkIntentError("observed_at must include a timezone offset")
        observed_value = parsed.astimezone(timezone.utc).isoformat()
        with self.database.connection() as connection:
            device = connection.execute(
                "SELECT project_id,status FROM devices WHERE device_id=?", (device_id,)
            ).fetchone()
        if device is None or device["project_id"] != project_id:
            raise NetworkIntentNotFound("Device not found in this Project")
        if device["status"] != "ACTIVE":
            raise NetworkIntentConflict("capability observations require an active Device")
        encoded = _canonical(normalized_capabilities)
        if len(encoded.encode("utf-8")) > 200_000:
            raise NetworkIntentError("device capability report exceeds the 200,000-byte limit")
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        report_id = "cap_" + secrets.token_hex(12)
        now = self._now()
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    """INSERT INTO device_capability_reports(
                       report_id,project_id,device_id,provider_id,platform,software_version,
                       adapter_name,adapter_version,source_type,capabilities_json,capability_sha256,
                       observed_at,recorded_at,recorded_by
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (report_id, project_id, device_id, provider_id, platform, software_version,
                     adapter_name, adapter_version, source_type, encoded, digest,
                     observed_value, now, actor),
                )
                self._audit(connection, actor, "DEVICE_CAPABILITIES_OBSERVED",
                            "DEVICE_CAPABILITY_REPORT", report_id,
                            {"project_id": project_id, "device_id": device_id,
                             "provider_id": provider_id, "source_type": source_type,
                             "capability_sha256": digest, "observed_at": observed_value})
        except Exception as exc:
            if "FOREIGN KEY constraint failed" in str(exc):
                raise NetworkIntentNotFound("Project or Device no longer exists") from exc
            raise
        return self.get_capability_report(report_id) or {}

    def get_capability_report(self, report_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM device_capability_reports WHERE report_id=?", (report_id,)).fetchone()
        return self._capability_report(row)

    def list_capability_reports(self, project_id: str, *, device_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            if device_id:
                rows = connection.execute(
                    """SELECT * FROM device_capability_reports WHERE project_id=? AND device_id=?
                       ORDER BY observed_at DESC,recorded_at DESC""",
                    (project_id, device_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM device_capability_reports WHERE project_id=?
                       ORDER BY observed_at DESC,recorded_at DESC""",
                    (project_id,),
                ).fetchall()
        return [self._capability_report(row) for row in rows]
