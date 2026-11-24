"""Pure, deterministic compilers for Linux/FRR and network operating systems.

These adapters only render configuration artifacts. They never open sockets,
read credentials, run a CLI, write device state, or claim a deployment succeeded.
"""
from __future__ import annotations

import ipaddress
import re
from collections import defaultdict
from typing import Mapping

from .contracts import AdapterCompileError, AdapterDescriptor


COMMON_ROUTING = frozenset({
    "addressing.ipv4", "addressing.ipv6", "interfaces.admin_state",
    "routing.static_ipv4", "routing.static_ipv6", "routing.ospf", "routing.bgp",
    "aggregation.lacp",
})
L2_FEATURES = frozenset({"vlans.access", "vlans.trunk"})
FIREWALL_FEATURES = frozenset({"firewall.zones", "firewall.basic_acl"})
LINUX_FEATURES = frozenset({"linux.bridge", "linux.vlan_interface"})
SERVICE_FEATURES = frozenset({"services.dhcp", "services.dns"})


def _rows(intent: Mapping[str, object], key: str) -> list[dict]:
    value = intent.get(key, [])
    return list(value) if isinstance(value, list) else []


def _slug(value: object, field: str, maximum: int = 48) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]*", text):
        raise AdapterCompileError("UNSAFE_CONFIGURATION_IDENTIFIER", f"{field} contains characters that cannot be represented safely")
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_.-")
    if not result:
        raise AdapterCompileError("UNSAFE_CONFIGURATION_IDENTIFIER", f"{field} is empty after normalization")
    return result[:maximum]


def _safe_host(value: object) -> str:
    return _slug(value, "Device name", 48).replace(".", "-").replace("_", "-")


def _interface(value: object, *, family: str) -> str:
    name = str(value or "").strip()
    if family == "linux":
        valid = len(name.encode("utf-8")) <= 15 and bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", name))
    elif family == "junos":
        valid = bool(re.fullmatch(r"(?:ge|xe|et|fe|ae|irb|reth|lo|vlan)[A-Za-z0-9./:-]{0,47}", name, re.I))
    elif family == "panos":
        valid = bool(re.fullmatch(r"(?:ethernet|ae|vlan|loopback|tunnel)[A-Za-z0-9./:-]{0,47}", name, re.I))
    elif family == "eos":
        valid = bool(re.fullmatch(r"(?:Ethernet|Management|Loopback|Vlan|Port-Channel|Port-channel|Vxlan)[A-Za-z0-9./:-]{0,47}", name, re.I))
    else:
        valid = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9./:-]{0,63}", name))
    if not valid:
        raise AdapterCompileError(
            "UNSAFE_OR_INVALID_INTERFACE",
            f"Interface name {name!r} is not valid for the {family} configuration adapter",
        )
    return name


def _description(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > 80 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.,:/()-]{0,79}", text):
        raise AdapterCompileError(
            "UNSAFE_CONFIGURATION_TEXT",
            "A description contains characters that could alter the generated configuration",
        )
    return text


def _addresses(interface: Mapping[str, object]) -> list[str]:
    result = []
    for value in interface.get("addresses", []) or []:
        try:
            result.append(str(ipaddress.ip_interface(str(value))))
        except ValueError as exc:
            raise AdapterCompileError("INVALID_ADDRESS", "An interface address is invalid") from exc
    return result


def _network(value: object) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        return ipaddress.ip_network(str(value), strict=True)
    except ValueError as exc:
        raise AdapterCompileError("INVALID_NETWORK", "A network prefix is invalid") from exc


def _ip(value: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        return ipaddress.ip_address(str(value))
    except ValueError as exc:
        raise AdapterCompileError("INVALID_ADDRESS", "An IP address is invalid") from exc


def _cisco_network(value: object) -> tuple[str, str]:
    network = _network(value)
    if network.version != 4:
        raise AdapterCompileError("IPV6_ACL_NOT_SUPPORTED", "This IOS-XE ACL subset accepts IPv4 prefixes only", feature_id="firewall.basic_acl")
    wildcard = ipaddress.IPv4Address(int(network.hostmask))
    return str(network.network_address), str(wildcard)


def _cisco_acl_line(rule: Mapping[str, object]) -> list[str]:
    source_values = list(rule.get("source_cidrs", []) or []) or ["0.0.0.0/0"]
    destination_values = list(rule.get("destination_cidrs", []) or []) or ["0.0.0.0/0"]
    action = "permit" if str(rule.get("action", "")).upper() == "ALLOW" else "deny"
    protocol = str(rule.get("protocol", "ANY")).lower()
    protocol = {"any": "ip", "icmp": "icmp"}.get(protocol, protocol)
    ports = list(rule.get("destination_ports", []) or [])
    lines = []
    for source in source_values:
        src, src_mask = _cisco_network(source)
        for destination in destination_values:
            dst, dst_mask = _cisco_network(destination)
            base = f"{action} {protocol} {src} {src_mask} {dst} {dst_mask}"
            if not ports:
                lines.append(base)
            elif protocol not in {"tcp", "udp"}:
                raise AdapterCompileError("INVALID_ACL_PORT_PROTOCOL", "Destination ports require TCP or UDP", feature_id="firewall.basic_acl")
            else:
                for port in ports:
                    start, end = int(port["start"]), int(port["end"])
                    lines.append(base + (f" eq {start}" if start == end else f" range {start} {end}"))
    return lines


def _port_expression(ports: list[dict]) -> str:
    if not ports:
        return ""
    values = []
    for item in ports:
        start, end = int(item["start"]), int(item["end"])
        values.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(values)


def _nft_cidr_variants(source_values: list[str], destination_values: list[str]) -> list[tuple[str, str]]:
    source = {4: [], 6: []}
    destination = {4: [], 6: []}
    for value in source_values:
        network = _network(value)
        source[network.version].append(str(network))
    for value in destination_values:
        network = _network(value)
        destination[network.version].append(str(network))
    source_families = {family for family, values in source.items() if values}
    destination_families = {family for family, values in destination.items() if values}
    if source_families and destination_families:
        families = sorted(source_families & destination_families)
        if not families:
            raise AdapterCompileError(
                "FIREWALL_CIDR_FAMILY_MISMATCH",
                "A firewall rule cannot match source and destination CIDRs from different address families",
                feature_id="firewall.basic_acl",
            )
    else:
        families = sorted(source_families or destination_families) or [4]
    result = []
    for family in families:
        prefix = "ip" if family == 4 else "ip6"
        source_clause = f"{prefix} saddr {{ " + ", ".join(source[family]) + " }" if source[family] else ""
        destination_clause = f"{prefix} daddr {{ " + ", ".join(destination[family]) + " }" if destination[family] else ""
        result.append((source_clause, destination_clause))
    return result


def _frr_route(route: Mapping[str, object]) -> str:
    destination = _network(route["destination"])
    next_hop = _ip(route["next_hop"])
    metric = int(route.get("metric", 1))
    interface = route.get("interface_name")
    if destination.version != next_hop.version:
        raise AdapterCompileError("ROUTE_FAMILY_MISMATCH", "A static route next hop must match its destination address family")
    if not interface:
        raise AdapterCompileError(
            "STATIC_ROUTE_INTERFACE_REQUIRED",
            "Linux/FRR needs an explicit interface_name for each static route",
            feature_id=f"routing.static_ipv{destination.version}",
        )
    interface = _interface(interface, family="linux")
    command = "ip route" if destination.version == 4 else "ipv6 route"
    return f"{command} {destination} {next_hop} {interface} {metric}"


class BaseNetworkConfigAdapter:
    descriptor: AdapterDescriptor
    _features: frozenset[str] = frozenset()

    def supported_features(self, device: Mapping[str, object]) -> frozenset[str]:
        return self._features

    @staticmethod
    def _assert_no_service_payload(intent: Mapping[str, object]) -> None:
        if _rows(intent, "service_references"):
            raise AdapterCompileError(
                "SERVICE_PROFILE_REFERENCE_UNRESOLVED",
                "DHCP/DNS references identify published profiles but do not contain the service values needed by a vendor compiler",
                feature_id="services.dhcp" if any(x.get("service_type") == "DHCP" for x in _rows(intent, "service_references")) else "services.dns",
            )

    def compile_target(self, device: Mapping[str, object], intent: Mapping[str, object]) -> Mapping[str, str]:
        raise NotImplementedError


class LinuxFrrAdapter(BaseNetworkConfigAdapter):
    descriptor = AdapterDescriptor("linux_frr", "Linux + FRRouting", "1.0.0", "Linux/FRR", "FRR 7–10; systemd-networkd", "systemd-networkd + FRR + nftables")
    _features = COMMON_ROUTING | L2_FEATURES | FIREWALL_FEATURES | LINUX_FEATURES

    def compile_target(self, device: Mapping[str, object], intent: Mapping[str, object]) -> Mapping[str, str]:
        self._assert_no_service_payload(intent)
        node = _slug(intent.get("logical_node_id", "node"), "logical_node_id", 48)
        host = _safe_host(device.get("name"))
        interfaces = _rows(intent, "interfaces")
        bridges = _rows(intent, "linux_bridges")
        vlans = _rows(intent, "linux_vlan_interfaces")
        aggregations = _rows(intent, "aggregations")
        bridge_members = {member for bridge in bridges for member in bridge.get("members", [])}
        bond_members = {member for item in aggregations for member in item.get("members", [])}
        artifacts: dict[str, str] = {}
        state_lines = ["#!/bin/sh", "set -eu", "# Operator-reviewed link state actions; this file is not executed by NetRegress."]
        for interface in interfaces:
            name = _interface(interface["name"], family="linux")
            sections = ["[Match]", f"Name={name}", "", "[Network]"]
            for address in _addresses(interface):
                sections.append(f"Address={address}")
            if name in bridge_members:
                bridge = next(item for item in bridges if name in item.get("members", []))
                sections.append(f"Bridge={_interface(bridge['name'], family='linux')}")
            if name in bond_members:
                aggregation = next(item for item in aggregations if name in item.get("members", []))
                sections.append(f"Bond={_interface(aggregation['name'], family='linux')}")
            for vlan in vlans:
                if vlan["parent_interface"] == name:
                    sections.append(f"VLAN={_interface(vlan['name'], family='linux')}")
            if interface.get("mode") == "ACCESS":
                if name not in bridge_members:
                    raise AdapterCompileError(
                        "LINUX_ACCESS_PORT_REQUIRES_BRIDGE",
                        f"Linux ACCESS interface {name} must be a member of a declared Linux bridge",
                        feature_id="vlans.access",
                    )
                sections.extend(["", "[BridgeVLAN]", f"VLAN={int(interface['access_vlan_id'])}", "PVID=yes", "EgressUntagged=yes"])
            elif interface.get("mode") == "TRUNK":
                if name not in bridge_members:
                    raise AdapterCompileError(
                        "LINUX_TRUNK_PORT_REQUIRES_BRIDGE",
                        f"Linux TRUNK interface {name} must be a member of a declared Linux bridge",
                        feature_id="vlans.trunk",
                    )
                for vlan_id in interface.get("allowed_vlans", []) or []:
                    sections.extend(["", "[BridgeVLAN]", f"VLAN={int(vlan_id)}"])
            artifacts[f"systemd/network/10-{node}-{_slug(name, 'interface', 24)}.network"] = "\n".join(sections) + "\n"
            state_lines.append(f"/usr/sbin/ip link set dev {name} {'up' if interface['admin_state'] == 'UP' else 'down'}")
        for bridge in bridges:
            name = _interface(bridge["name"], family="linux")
            content = ["[NetDev]", f"Name={name}", "Kind=bridge", "", "[Bridge]", "VLANFiltering=yes"]
            artifacts[f"systemd/network/10-{node}-{_slug(name, 'bridge', 24)}.netdev"] = "\n".join(content) + "\n"
        for aggregation in aggregations:
            name = _interface(aggregation["name"], family="linux")
            if aggregation["protocol"] != "LACP":
                raise AdapterCompileError("AGGREGATION_PROTOCOL_UNSUPPORTED", "Linux adapter only supports LACP", feature_id="aggregation.lacp")
            content = ["[NetDev]", f"Name={name}", "Kind=bond", "", "[Bond]", "Mode=802.3ad", "LACPTransmitRate=fast"]
            artifacts[f"systemd/network/10-{node}-{_slug(name, 'bond', 24)}.netdev"] = "\n".join(content) + "\n"
            state_lines.append(f"echo {1 if aggregation['mode'] == 'ACTIVE' else 0} > /sys/class/net/{name}/bonding/lacp_active")
        for vlan in vlans:
            name = _interface(vlan["name"], family="linux")
            parent = _interface(vlan["parent_interface"], family="linux")
            content = ["[NetDev]", f"Name={name}", "Kind=vlan", "", "[VLAN]", f"Id={int(vlan['vlan_id'])}"]
            artifacts[f"systemd/network/10-{node}-{_slug(name, 'vlan', 24)}.netdev"] = "\n".join(content) + "\n"
            artifacts[f"systemd/network/20-{node}-{_slug(name, 'vlan', 24)}.network"] = f"[Match]\nName={name}\n\n[Network]\n"
        frr = ["frr version 8.0", "frr defaults traditional", f"hostname {host}", "service integrated-vtysh-config", "!"]
        for route in _rows(intent, "static_routes"):
            frr.append(_frr_route(route))
        for item in _rows(intent, "ospf"):
            frr.extend(["!", f"router ospf", f" ospf router-id {item['router_id']}"])
            for area in item["areas"]:
                for network in area["networks"]:
                    parsed = _network(network)
                    if parsed.version == 4:
                        matches = [
                            interface for interface in interfaces
                            if any(
                                ipaddress.ip_interface(address).version == 4
                                and ipaddress.ip_interface(address).ip in parsed
                                for address in _addresses(interface)
                            )
                        ]
                        if not matches:
                            raise AdapterCompileError(
                                "OSPF_NETWORK_WITHOUT_INTERFACE",
                                f"OSPF network {parsed} does not match a configured interface",
                                feature_id="routing.ospf",
                            )
                        frr.append(f" network {parsed.network_address}/{parsed.prefixlen} area {area['area_id']}")
                    else:
                        matches = [
                            _interface(interface["name"], family="linux")
                            for interface in interfaces
                            if any(
                                ipaddress.ip_interface(address).version == 6
                                and ipaddress.ip_interface(address).ip in parsed
                                for address in _addresses(interface)
                            )
                        ]
                        if not matches:
                            raise AdapterCompileError("OSPFV3_NETWORK_WITHOUT_INTERFACE", f"OSPFv3 network {parsed} does not match a configured interface", feature_id="routing.ospf")
                        frr.extend(["!", "router ospf6", f" ospf6 router-id {item['router_id']}"])
                        for name in matches:
                            frr.append(f" interface {name} area {area['area_id']}")
        for item in _rows(intent, "bgp"):
            frr.extend(["!", f"router bgp {int(item['local_asn'])}", f" bgp router-id {item['router_id']}"])
            for neighbor in item["neighbors"]:
                description = _description(neighbor.get("description"))
                frr.append(f" neighbor {neighbor['address']} remote-as {int(neighbor['remote_asn'])}")
                if description:
                    frr.append(f" neighbor {neighbor['address']} description {description}")
        if len(frr) > 5:
            frr.append("!")
            artifacts["frr/frr.conf"] = "\n".join(frr) + "\n"
        nft = ["#!/usr/sbin/nft -f", "table inet netregress {", " chain forward {", "  type filter hook forward priority filter; policy drop;"]
        zones = {zone["zone_id"]: [_interface(name, family="linux") for name in zone["interfaces"]] for zone in _rows(intent, "firewall_zones")}
        for rule in _rows(intent, "firewall_rules"):
            source_interfaces = zones.get(rule["source_zone_id"], [])
            destination_interfaces = zones.get(rule["destination_zone_id"], [])
            if not source_interfaces or not destination_interfaces:
                raise AdapterCompileError("FIREWALL_ZONE_WITHOUT_INTERFACE", "Linux firewall rules require interfaces in both referenced zones", feature_id="firewall.zones")
            for source_interface in source_interfaces:
                for destination_interface in destination_interfaces:
                    parts = [f'iifname "{source_interface}"', f'oifname "{destination_interface}"']
                    source_cidrs = list(rule.get("source_cidrs", []) or [])
                    destination_cidrs = list(rule.get("destination_cidrs", []) or [])
                    cidr_variants = _nft_cidr_variants(source_cidrs, destination_cidrs)
                    protocol = str(rule["protocol"]).lower()
                    if protocol in {"tcp", "udp"}:
                        ports = list(rule.get("destination_ports", []) or [])
                        protocol_clause = f"{protocol} dport {{ {_port_expression(ports)} }}" if ports else f"meta l4proto {protocol}"
                    elif protocol == "icmp":
                        protocol_clause = "meta l4proto { icmp, ipv6-icmp }"
                    else:
                        protocol_clause = ""
                    verdict = "accept" if rule["action"] == "ALLOW" else "drop"
                    for source_clause, destination_clause in cidr_variants:
                        clauses = parts + [item for item in (source_clause, destination_clause, protocol_clause) if item]
                        nft.append("  " + " ".join(clauses) + f" {verdict}")
        nft.extend([" }", "}", ""])
        if zones:
            artifacts["nftables/netregress.nft"] = "\n".join(nft)
        if state_lines[2:]:
            artifacts["operator/link-state.sh"] = "\n".join(state_lines) + "\n"
        return artifacts


class CiscoIosXeAdapter(BaseNetworkConfigAdapter):
    descriptor = AdapterDescriptor("cisco_iosxe", "Cisco IOS / IOS-XE", "1.0.0", "Cisco IOS/IOS-XE", "IOS 15.x; IOS-XE 16.x–17.x", "IOS/IOS-XE CLI")
    _features = COMMON_ROUTING | L2_FEATURES | FIREWALL_FEATURES

    def compile_target(self, device: Mapping[str, object], intent: Mapping[str, object]) -> Mapping[str, str]:
        self._assert_no_service_payload(intent)
        lines = ["!", f"hostname {_safe_host(device.get('name'))}", "ip routing", "ipv6 unicast-routing", "!"]
        segments = _rows(intent, "segments")
        for segment in segments:
            if segment.get("vlan_id") is not None:
                lines.extend([f"vlan {int(segment['vlan_id'])}", f" name {_slug(segment['name'], 'segment name', 32)}", " exit", "!"])
        aggregation_ids = {}
        for aggregation in _rows(intent, "aggregations"):
            name = _interface(aggregation["name"], family="cisco")
            match = re.fullmatch(r"(?:port-channel|po)([1-9][0-9]*)", name, re.I)
            if not match:
                raise AdapterCompileError("CISCO_PORT_CHANNEL_NAME_REQUIRED", "Cisco LACP names must be Port-channelN or PoN", feature_id="aggregation.lacp")
            number = int(match.group(1))
            aggregation_ids.update({member: number for member in aggregation["members"]})
            lines.extend([f"interface Port-channel{number}", " no shutdown", "!"])
        for interface in _rows(intent, "interfaces"):
            name = _interface(interface["name"], family="cisco")
            addresses = _addresses(interface)
            if addresses and interface["mode"] != "ROUTED":
                raise AdapterCompileError("L2_INTERFACE_CANNOT_HAVE_L3_ADDRESS", f"Cisco {interface['mode']} interface {name} cannot carry routed addresses in this compiler subset")
            lines.extend([f"interface {name}"])
            if interface["mode"] == "ROUTED":
                lines.append(" no switchport")
                for address in addresses:
                    parsed = ipaddress.ip_interface(address)
                    if parsed.version == 4:
                        lines.append(f" ip address {parsed.ip} {parsed.network.netmask}")
                    else:
                        lines.append(f" ipv6 address {address}")
            elif interface["mode"] == "ACCESS":
                lines.extend([" switchport", " switchport mode access", f" switchport access vlan {int(interface['access_vlan_id'])}"])
            else:
                lines.extend([" switchport", " switchport mode trunk"])
                if interface.get("native_vlan_id"):
                    lines.append(f" switchport trunk native vlan {int(interface['native_vlan_id'])}")
                if interface.get("allowed_vlans"):
                    lines.append(" switchport trunk allowed vlan " + ",".join(str(int(x)) for x in interface["allowed_vlans"]))
            if name in aggregation_ids:
                aggregation = next(item for item in _rows(intent, "aggregations") if name in item["members"])
                lacp_mode = "active" if aggregation["mode"] == "ACTIVE" else "passive"
                lines.append(f" channel-group {aggregation_ids[name]} mode {lacp_mode}")
            lines.append(" no shutdown" if interface["admin_state"] == "UP" else " shutdown")
            lines.append("!")
        for route in _rows(intent, "static_routes"):
            destination = _network(route["destination"])
            next_hop = _ip(route["next_hop"])
            metric = int(route["metric"])
            if destination.version != next_hop.version:
                raise AdapterCompileError("ROUTE_FAMILY_MISMATCH", "Static route next hop must match its destination address family")
            destination_text = (
                f"{destination.network_address} {destination.netmask}"
                if destination.version == 4 else str(destination)
            )
            lines.append(("ip route " if destination.version == 4 else "ipv6 route ") + f"{destination_text} {next_hop}" + (f" {metric}" if metric else ""))
        for item in _rows(intent, "ospf"):
            process = int(item["process_id"])
            v4_areas = [a for a in item["areas"] if any(_network(n).version == 4 for n in a["networks"])]
            v6_areas = [a for a in item["areas"] if any(_network(n).version == 6 for n in a["networks"])]
            if v4_areas:
                lines.extend(["!", f"router ospf {process}", f" router-id {item['router_id']}"])
                for area in v4_areas:
                    for value in area["networks"]:
                        network = _network(value)
                        if network.version == 4:
                            matches = [
                                interface for interface in _rows(intent, "interfaces")
                                if any(
                                    ipaddress.ip_interface(address).version == 4
                                    and ipaddress.ip_interface(address).ip in network
                                    for address in _addresses(interface)
                                )
                            ]
                            if not matches:
                                raise AdapterCompileError(
                                    "OSPF_NETWORK_WITHOUT_INTERFACE",
                                    f"OSPF network {network} does not match a configured interface",
                                    feature_id="routing.ospf",
                                )
                            lines.append(f" network {network.network_address} {ipaddress.IPv4Address(int(network.hostmask))} area {area['area_id']}")
                lines.append("!")
            if v6_areas:
                lines.extend(["!", f"ipv6 router ospf {process}", f" router-id {item['router_id']}", "!"])
                for area in v6_areas:
                    for value in area["networks"]:
                        network = _network(value)
                        if network.version == 6:
                            matches = [
                                interface for interface in _rows(intent, "interfaces")
                                if any(
                                    ipaddress.ip_interface(address).version == 6
                                    and ipaddress.ip_interface(address).ip in network
                                    for address in _addresses(interface)
                                )
                            ]
                            if not matches:
                                raise AdapterCompileError(
                                    "OSPFV3_NETWORK_WITHOUT_INTERFACE",
                                    f"OSPFv3 network {network} does not match a configured interface",
                                    feature_id="routing.ospf",
                                )
                            for interface in matches:
                                lines.extend([
                                    f"interface {_interface(interface['name'], family='cisco')}",
                                    f" ipv6 ospf {process} area {area['area_id']}",
                                    "!",
                                ])
        for item in _rows(intent, "bgp"):
            lines.extend(["!", f"router bgp {int(item['local_asn'])}", f" bgp router-id {item['router_id']}"])
            for neighbor in item["neighbors"]:
                lines.append(f" neighbor {neighbor['address']} remote-as {int(neighbor['remote_asn'])}")
                description = _description(neighbor.get("description"))
                if description:
                    lines.append(f" neighbor {neighbor['address']} description {description}")
            lines.append("!")
        self._append_zone_firewall(lines, intent)
        lines.extend(["end", ""])
        return {"running-config.txt": "\n".join(lines)}

    @staticmethod
    def _append_zone_firewall(lines: list[str], intent: Mapping[str, object]) -> None:
        zones = {zone["zone_id"]: _slug(zone["name"], "firewall zone", 24) for zone in _rows(intent, "firewall_zones")}
        for zone in zones.values():
            lines.extend(["!", f"zone security {zone}"])
        for zone in _rows(intent, "firewall_zones"):
            zone_name = zones[zone["zone_id"]]
            for interface in zone["interfaces"]:
                lines.extend([f"interface {_interface(interface, family='cisco')}", f" zone-member security {zone_name}", "!"])
        grouped = defaultdict(list)
        for rule in _rows(intent, "firewall_rules"):
            pair = (rule["source_zone_id"], rule["destination_zone_id"])
            grouped[pair].append(rule)
        for (source_id, destination_id), rules in sorted(grouped.items()):
            source, destination = zones[source_id], zones[destination_id]
            acl = _slug(f"NR_{source}_{destination}", "ACL", 28)
            class_name = _slug(f"NR_C_{source}_{destination}", "class-map", 28)
            policy = _slug(f"NR_P_{source}_{destination}", "policy-map", 28)
            pair_name = _slug(f"NR_Z_{source}_{destination}", "zone-pair", 28)
            lines.extend(["!", f"ip access-list extended {acl}"])
            for rule in rules:
                lines.extend([" " + line for line in _cisco_acl_line(rule)])
            lines.extend([" exit", f"class-map type inspect match-all {class_name}", f" match access-group name {acl}", " exit", f"policy-map type inspect {policy}", f" class type inspect {class_name}", "  inspect", " exit", " exit", f"zone-pair security {pair_name} source {source} destination {destination}", f" service-policy type inspect {policy}", "!"])


class AristaEosAdapter(BaseNetworkConfigAdapter):
    descriptor = AdapterDescriptor("arista_eos", "Arista EOS", "1.0.0", "Arista EOS", "EOS 4.x", "EOS CLI")
    _features = COMMON_ROUTING | L2_FEATURES

    def compile_target(self, device: Mapping[str, object], intent: Mapping[str, object]) -> Mapping[str, str]:
        self._assert_no_service_payload(intent)
        if _rows(intent, "firewall_zones") or _rows(intent, "firewall_rules"):
            raise AdapterCompileError(
                "ARISTA_ZONE_FIREWALL_UNSUPPORTED",
                "This EOS adapter does not translate zone-based security semantics into stateless EOS ACLs; firewall zones/rules are blocked instead of weakened",
                feature_id="firewall.zones",
            )
        lines = ["!", f"hostname {_safe_host(device.get('name'))}", "ip routing", "ipv6 unicast-routing", "!"]
        for segment in _rows(intent, "segments"):
            if segment.get("vlan_id") is not None:
                lines.extend([f"vlan {int(segment['vlan_id'])}", f" name {_slug(segment['name'], 'segment name', 32)}", "!"])
        members = {}
        for aggregation in _rows(intent, "aggregations"):
            match = re.fullmatch(r"(?:port-channel|po)([1-9][0-9]*)", str(aggregation["name"]), re.I)
            if not match:
                raise AdapterCompileError("ARISTA_PORT_CHANNEL_NAME_REQUIRED", "Arista LACP names must be Port-ChannelN", feature_id="aggregation.lacp")
            number = int(match.group(1))
            for member in aggregation["members"]:
                members[member] = number
            lines.extend([f"interface Port-Channel{number}", "   no shutdown", "!"])
        for interface in _rows(intent, "interfaces"):
            name = _interface(interface["name"], family="eos")
            addresses = _addresses(interface)
            if addresses and interface["mode"] != "ROUTED":
                raise AdapterCompileError("L2_INTERFACE_CANNOT_HAVE_L3_ADDRESS", f"EOS {interface['mode']} interface {name} cannot carry routed addresses in this compiler subset")
            lines.append(f"interface {name}")
            if interface["mode"] == "ROUTED":
                for address in addresses:
                    parsed = ipaddress.ip_interface(address)
                    lines.append(("   ip address " if parsed.version == 4 else "   ipv6 address ") + address)
            elif interface["mode"] == "ACCESS":
                lines.extend(["   switchport", "   switchport mode access", f"   switchport access vlan {int(interface['access_vlan_id'])}"])
            else:
                lines.extend(["   switchport", "   switchport mode trunk"])
                if interface.get("native_vlan_id"):
                    lines.append(f"   switchport trunk native vlan {int(interface['native_vlan_id'])}")
                if interface.get("allowed_vlans"):
                    lines.append("   switchport trunk allowed vlan " + ",".join(str(int(x)) for x in interface["allowed_vlans"]))
            if name in members:
                aggregation = next(item for item in _rows(intent, "aggregations") if name in item["members"])
                lacp_mode = "active" if aggregation["mode"] == "ACTIVE" else "passive"
                lines.append(f"   channel-group {members[name]} mode {lacp_mode}")
            lines.append("   no shutdown" if interface["admin_state"] == "UP" else "   shutdown")
            lines.append("!")
        for route in _rows(intent, "static_routes"):
            destination = _network(route["destination"])
            next_hop = _ip(route["next_hop"])
            if destination.version != next_hop.version:
                raise AdapterCompileError("ROUTE_FAMILY_MISMATCH", "Static route next hop must match its destination address family")
            lines.append(("ip route " if destination.version == 4 else "ipv6 route ") + f"{destination} {next_hop}" + (f" {int(route['metric'])}" if route.get("metric") else ""))
        for item in _rows(intent, "ospf"):
            ipv6_networks = [
                _network(value) for area in item["areas"] for value in area["networks"]
                if _network(value).version == 6
            ]
            if ipv6_networks:
                raise AdapterCompileError(
                    "ARISTA_OSPFV3_NOT_SUPPORTED",
                    "Arista EOS OSPFv3 is outside this adapter's validated compilation subset",
                    feature_id="routing.ospf",
                )
            lines.extend(["!", f"router ospf {int(item['process_id'])}", f"   router-id {item['router_id']}"])
            for area in item["areas"]:
                for value in area["networks"]:
                    network = _network(value)
                    matches = [
                        interface for interface in _rows(intent, "interfaces")
                        if any(
                            ipaddress.ip_interface(address).version == 4
                            and ipaddress.ip_interface(address).ip in network
                            for address in _addresses(interface)
                        )
                    ]
                    if not matches:
                        raise AdapterCompileError(
                            "OSPF_NETWORK_WITHOUT_INTERFACE",
                            f"OSPF network {network} does not match a configured interface",
                            feature_id="routing.ospf",
                        )
                    lines.append(f"   network {network} area {area['area_id']}")
            lines.append("!")
        for item in _rows(intent, "bgp"):
            lines.extend(["!", f"router bgp {int(item['local_asn'])}", f"   router-id {item['router_id']}"])
            for neighbor in item["neighbors"]:
                lines.append(f"   neighbor {neighbor['address']} remote-as {int(neighbor['remote_asn'])}")
                description = _description(neighbor.get("description"))
                if description:
                    lines.append(f"   neighbor {neighbor['address']} description {description}")
            lines.append("!")
        lines.extend(["end", ""])
        return {"startup-config.txt": "\n".join(lines)}


class JuniperJunosAdapter(BaseNetworkConfigAdapter):
    descriptor = AdapterDescriptor("juniper_junos", "Juniper Junos", "1.0.0", "Juniper Junos", "Junos 18.x–24.x; SRX firewall features", "Junos hierarchical set commands")
    _features = COMMON_ROUTING | L2_FEATURES | FIREWALL_FEATURES

    def supported_features(self, device: Mapping[str, object]) -> frozenset[str]:
        model = str(device.get("model") or "").upper()
        return self._features if "SRX" in model else self._features - FIREWALL_FEATURES

    def compile_target(self, device: Mapping[str, object], intent: Mapping[str, object]) -> Mapping[str, str]:
        self._assert_no_service_payload(intent)
        lines = [f"set system host-name {_safe_host(device.get('name'))}"]
        for segment in _rows(intent, "segments"):
            if segment.get("vlan_id") is not None:
                lines.extend([f"set vlans {_slug(segment['name'], 'VLAN name')} vlan-id {int(segment['vlan_id'])}"])
        interfaces = _rows(intent, "interfaces")
        interface_map = {}
        for interface in interfaces:
            name = _interface(interface["name"], family="junos")
            interface_map[name] = interface
            if interface["mode"] != "ROUTED" and _addresses(interface):
                raise AdapterCompileError("L2_INTERFACE_CANNOT_HAVE_L3_ADDRESS", f"Junos switching interface {name} cannot carry routed addresses in this compiler subset")
            if interface["admin_state"] == "DOWN":
                lines.append(f"set interfaces {name} disable")
            if interface["mode"] == "ROUTED":
                for address in _addresses(interface):
                    family = "inet" if ipaddress.ip_interface(address).version == 4 else "inet6"
                    lines.append(f"set interfaces {name} unit 0 family {family} address {address}")
            elif interface["mode"] == "ACCESS":
                segment = next((s for s in _rows(intent, "segments") if s.get("vlan_id") == interface.get("access_vlan_id")), None)
                vlan_name = _slug(segment["name"], "VLAN name") if segment else f"vlan_{int(interface['access_vlan_id'])}"
                lines.extend([f"set interfaces {name} unit 0 family ethernet-switching interface-mode access", f"set interfaces {name} unit 0 family ethernet-switching vlan members {vlan_name}"])
            else:
                lines.append(f"set interfaces {name} unit 0 family ethernet-switching interface-mode trunk")
                for vlan_id in interface.get("allowed_vlans", []) or []:
                    segment = next((s for s in _rows(intent, "segments") if s.get("vlan_id") == vlan_id), None)
                    vlan_name = _slug(segment["name"], "VLAN name") if segment else f"vlan_{int(vlan_id)}"
                    lines.append(f"set interfaces {name} unit 0 family ethernet-switching vlan members {vlan_name}")
        for aggregation in _rows(intent, "aggregations"):
            name = _interface(aggregation["name"], family="junos")
            if not re.fullmatch(r"ae[0-9]+", name):
                raise AdapterCompileError("JUNOS_AGGREGATE_NAME_REQUIRED", "Junos LACP aggregate interface names must use aeN", feature_id="aggregation.lacp")
            mode = "active" if aggregation["mode"] == "ACTIVE" else "passive"
            lines.extend([f"set interfaces {name} aggregated-ether-options lacp {mode}"])
            for member in aggregation["members"]:
                member_name = _interface(member, family="junos")
                lines.append(f"set interfaces {member_name} ether-options 802.3ad {name}")
        for route in _rows(intent, "static_routes"):
            network = _network(route["destination"])
            next_hop = _ip(route["next_hop"])
            if network.version != next_hop.version:
                raise AdapterCompileError("ROUTE_FAMILY_MISMATCH", "Static route next hop must match its destination address family")
            if int(route.get("metric", 1)) != 1:
                raise AdapterCompileError(
                    "JUNOS_STATIC_ROUTE_METRIC_UNSUPPORTED",
                    "Junos static route preference semantics differ from the canonical metric field; non-default metrics are blocked",
                    feature_id=f"routing.static_ipv{network.version}",
                )
            prefix = "set routing-options static route" if network.version == 4 else "set routing-options rib inet6.0 static route"
            lines.append(f"{prefix} {network} next-hop {next_hop}")
        for item in _rows(intent, "ospf"):
            for area in item["areas"]:
                for network_value in area["networks"]:
                    network = _network(network_value)
                    matches = []
                    for interface in interfaces:
                        if any(
                            ipaddress.ip_interface(address).version == network.version
                            and ipaddress.ip_interface(address).ip in network
                            for address in _addresses(interface)
                        ):
                            matches.append(_interface(interface["name"], family="junos"))
                    if not matches:
                        raise AdapterCompileError("OSPF_NETWORK_WITHOUT_INTERFACE", f"OSPF network {network} does not match a configured interface", feature_id="routing.ospf")
                    protocol = "ospf" if network.version == 4 else "ospf3"
                    for name in matches:
                        lines.append(f"set protocols {protocol} area {area['area_id']} interface {name}.0")
            lines.append(f"set routing-options router-id {item['router_id']}")
        for item in _rows(intent, "bgp"):
            group = _slug(f"AS{int(item['local_asn'])}", "BGP group", 24)
            lines.append(f"set routing-options autonomous-system {int(item['local_asn'])}")
            for neighbor in item["neighbors"]:
                lines.extend([
                    f"set protocols bgp group {group} type external",
                    f"set protocols bgp group {group} local-as {int(item['local_asn'])}",
                    f"set protocols bgp group {group} neighbor {neighbor['address']} peer-as {int(neighbor['remote_asn'])}",
                ])
                description = _description(neighbor.get("description"))
                if description:
                    lines.append(f"set protocols bgp group {group} neighbor {neighbor['address']} description {description}")
        self._append_srx_security(lines, intent, device)
        return {"candidate.set": "\n".join(sorted(set(lines))) + "\n"}

    @staticmethod
    def _append_srx_security(lines: list[str], intent: Mapping[str, object], device: Mapping[str, object]) -> None:
        zones = {zone["zone_id"]: _slug(zone["name"], "security zone", 32) for zone in _rows(intent, "firewall_zones")}
        if not zones:
            return
        if "SRX" not in str(device.get("model") or "").upper():
            raise AdapterCompileError("JUNOS_FIREWALL_REQUIRES_SRX", "Junos security zones and policies require an SRX model", feature_id="firewall.zones")
        for zone in _rows(intent, "firewall_zones"):
            zone_name = zones[zone["zone_id"]]
            for interface in zone["interfaces"]:
                name = _interface(interface, family="junos")
                lines.append(f"set security zones security-zone {zone_name} interfaces {name}.0")
        addresses = {}
        applications = {}
        for rule in _rows(intent, "firewall_rules"):
            source_zone, destination_zone = zones[rule["source_zone_id"]], zones[rule["destination_zone_id"]]
            policy = _slug(rule["rule_id"], "security policy", 32)
            source_names, destination_names = [], []
            for cidr in rule.get("source_cidrs", []) or []:
                obj = _slug("SRC_" + cidr.replace("/", "_").replace(":", "_"), "address object", 48)
                addresses[obj] = cidr
                source_names.append(obj)
            for cidr in rule.get("destination_cidrs", []) or []:
                obj = _slug("DST_" + cidr.replace("/", "_").replace(":", "_"), "address object", 48)
                addresses[obj] = cidr
                destination_names.append(obj)
            protocol = str(rule["protocol"]).lower()
            app_names = []
            if protocol == "ANY":
                app_names = ["any"]
            elif protocol == "ICMP":
                app_names = ["junos-icmp-all"]
            else:
                ports = list(rule.get("destination_ports", []) or [])
                if not ports:
                    app_names = ["junos-" + protocol]
                for position, port in enumerate(ports):
                    app = _slug(f"NR_{policy}_{position}", "application", 48)
                    applications[app] = (protocol, port)
                    app_names.append(app)
            base = f"set security policies from-zone {source_zone} to-zone {destination_zone} policy {policy}"
            for name in source_names or ["any"]:
                lines.append(f"{base} match source-address {name}")
            for name in destination_names or ["any"]:
                lines.append(f"{base} match destination-address {name}")
            for app in app_names:
                lines.append(f"{base} match application {app}")
            lines.append(f"{base} then {'permit' if rule['action'] == 'ALLOW' else 'deny'}")
        for name, cidr in addresses.items():
            lines.append(f"set security address-book global address {name} {cidr}")
        for name, (protocol, port) in applications.items():
            start, end = int(port["start"]), int(port["end"])
            port_value = str(start) if start == end else f"{start}-{end}"
            lines.append(f"set applications application {name} protocol {protocol}")
            lines.append(f"set applications application {name} destination-port {port_value}")


class PaloAltoPanOsAdapter(BaseNetworkConfigAdapter):
    descriptor = AdapterDescriptor("paloalto_panos", "Palo Alto PAN-OS", "1.0.0", "Palo Alto PAN-OS", "PAN-OS 10.x–12.x", "PAN-OS set CLI")
    _features = COMMON_ROUTING | FIREWALL_FEATURES

    def compile_target(self, device: Mapping[str, object], intent: Mapping[str, object]) -> Mapping[str, str]:
        self._assert_no_service_payload(intent)
        lines = [f"set deviceconfig system hostname {_safe_host(device.get('name'))}"]
        interfaces = _rows(intent, "interfaces")
        for interface in interfaces:
            if interface["mode"] != "ROUTED":
                raise AdapterCompileError(
                    "PANOS_SWITCHPORT_MODE_UNSUPPORTED",
                    "PAN-OS adapter supports routed ethernet interfaces; generic ACCESS/TRUNK switchport semantics are not translated to PAN-OS VLAN objects",
                    feature_id="vlans.access" if interface["mode"] == "ACCESS" else "vlans.trunk",
                )
            name = _interface(interface["name"], family="panos")
            lines.append(f"set network interface ethernet {name} layer3")
            for address in _addresses(interface):
                parsed = ipaddress.ip_interface(address)
                family = "ip" if parsed.version == 4 else "ipv6 address"
                lines.append(f"set network interface ethernet {name} layer3 {family} {address}")
            lines.append(f"set network virtual-router default interface {name}")
            lines.append(f"set network interface ethernet {name} link-state {'up' if interface['admin_state'] == 'UP' else 'down'}")
        for aggregation in _rows(intent, "aggregations"):
            name = _interface(aggregation["name"], family="panos")
            if not re.fullmatch(r"ae[0-9]+", name, re.I):
                raise AdapterCompileError("PANOS_AGGREGATE_NAME_REQUIRED", "PAN-OS aggregate interfaces must use aeN", feature_id="aggregation.lacp")
            lines.append(f"set network interface aggregate-ethernet {name}")
            lines.append(f"set network interface aggregate-ethernet {name} lacp enable yes")
            lines.append(f"set network interface aggregate-ethernet {name} lacp mode {'active' if aggregation['mode'] == 'ACTIVE' else 'passive'}")
            for member in aggregation["members"]:
                member_name = _interface(member, family="panos")
                lines.append(f"set network interface ethernet {member_name} aggregate-group {name}")
        for route in _rows(intent, "static_routes"):
            network = _network(route["destination"])
            next_hop = _ip(route["next_hop"])
            if network.version != next_hop.version:
                raise AdapterCompileError("ROUTE_FAMILY_MISMATCH", "Static route next hop must match its destination address family")
            name = _slug("NR_" + str(network).replace("/", "_").replace(":", "_"), "static route", 48)
            family = "ip" if network.version == 4 else "ipv6"
            next_hop_type = "ip-address" if next_hop.version == 4 else "ipv6-address"
            lines.extend([
                f"set network virtual-router default routing-table {family} static-route {name} destination {network}",
                f"set network virtual-router default routing-table {family} static-route {name} nexthop {next_hop_type} {next_hop}",
                f"set network virtual-router default routing-table {family} static-route {name} metric {int(route.get('metric', 1))}",
            ])
        for item in _rows(intent, "ospf"):
            lines.extend([
                "set network virtual-router default protocol ospf enable yes",
                f"set network virtual-router default protocol ospf router-id {item['router_id']}",
            ])
            for area in item["areas"]:
                area_id = str(area["area_id"])
                lines.append(f"set network virtual-router default protocol ospf area {area_id}")
                for network in area["networks"]:
                    prefix = _network(network)
                    matches = [
                        interface for interface in interfaces
                        if any(ipaddress.ip_interface(address).version == prefix.version and ipaddress.ip_interface(address).ip in prefix for address in _addresses(interface))
                    ]
                    if not matches:
                        raise AdapterCompileError("OSPF_NETWORK_WITHOUT_INTERFACE", f"OSPF network {prefix} does not match a configured interface", feature_id="routing.ospf")
                    for interface in matches:
                        lines.append(f"set network virtual-router default protocol ospf area {area_id} interface {interface['name']}")
        for item in _rows(intent, "bgp"):
            lines.extend([
                "set network virtual-router default protocol bgp enable yes",
                f"set network virtual-router default protocol bgp local-as {int(item['local_asn'])}",
                f"set network virtual-router default protocol bgp router-id {item['router_id']}",
            ])
            for neighbor in item["neighbors"]:
                name = _slug("NR_" + str(neighbor["address"]).replace(":", "_"), "BGP peer", 32)
                lines.extend([
                    f"set network virtual-router default protocol bgp peer-group NR",
                    f"set network virtual-router default protocol bgp peer-group NR peer {name} peer-as {int(neighbor['remote_asn'])}",
                    f"set network virtual-router default protocol bgp peer-group NR peer {name} peer-address {'ip' if _ip(neighbor['address']).version == 4 else 'ipv6'} {neighbor['address']}",
                ])
                description = _description(neighbor.get("description"))
                if description:
                    lines.append(f"set network virtual-router default protocol bgp peer-group NR peer {name} description {description}")
        self._append_security(lines, intent)
        return {"panos-set-commands.txt": "\n".join(sorted(set(lines))) + "\n"}

    @staticmethod
    def _append_security(lines: list[str], intent: Mapping[str, object]) -> None:
        zones = {zone["zone_id"]: _slug(zone["name"], "security zone", 32) for zone in _rows(intent, "firewall_zones")}
        for zone in _rows(intent, "firewall_zones"):
            name = zones[zone["zone_id"]]
            lines.append(f"set zone {name} network layer3 " + " ".join(_interface(item, family="panos") for item in zone["interfaces"]))
        address_objects = {}
        services = {}
        for rule in _rows(intent, "firewall_rules"):
            name = _slug(rule["rule_id"], "security rule", 48)
            source_names = []
            destination_names = []
            for value in rule.get("source_cidrs", []) or []:
                obj = _slug("SRC_" + value.replace("/", "_").replace(":", "_"), "address object", 48)
                address_objects[obj] = value
                source_names.append(obj)
            for value in rule.get("destination_cidrs", []) or []:
                obj = _slug("DST_" + value.replace("/", "_").replace(":", "_"), "address object", 48)
                address_objects[obj] = value
                destination_names.append(obj)
            protocol = str(rule["protocol"]).upper()
            application = "any" if protocol == "ANY" else "ping" if protocol == "ICMP" else "application-default"
            ports = list(rule.get("destination_ports", []) or [])
            if protocol in {"TCP", "UDP"} and ports:
                service_name = _slug("NR_" + name, "service object", 48)
                services[service_name] = (protocol.lower(), _port_expression(ports).replace(", ", ","))
                application = "any"
            base = f"set rulebase security rules {name}"
            lines.extend([
                f"{base} from {zones[rule['source_zone_id']]}",
                f"{base} to {zones[rule['destination_zone_id']]}",
                f"{base} source " + " ".join(source_names or ["any"]),
                f"{base} destination " + " ".join(destination_names or ["any"]),
                f"{base} application {application}",
            ])
            if ports and protocol in {"TCP", "UDP"}:
                lines.append(f"{base} service NR_{name}")
            lines.append(f"{base} action {'allow' if rule['action'] == 'ALLOW' else 'deny'}")
        for name, cidr in address_objects.items():
            lines.append(f"set address {name} ip-netmask {cidr}")
        for name, (protocol, ports) in services.items():
            lines.extend([f"set service {name} protocol {protocol} port {ports}"])


ADAPTERS = (
    LinuxFrrAdapter(),
    CiscoIosXeAdapter(),
    AristaEosAdapter(),
    JuniperJunosAdapter(),
    PaloAltoPanOsAdapter(),
)
