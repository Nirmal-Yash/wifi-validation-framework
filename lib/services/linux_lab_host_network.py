"""Safe, incremental Python replacement for the libvirt host-network slice.

Only the named libvirt default network and its virbr0 management bridge are
managed. The adapter never deletes/recreates a network, flushes addresses,
changes routes, or modifies unrelated networks. It is plan-first and requires
explicit operator confirmation before touching DHCP or bridge addresses.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import xml.etree.ElementTree as ET
from typing import Callable, Sequence


class LinuxLabHostNetworkError(RuntimeError):
    """Host networking preflight or mutation was rejected safely."""


class LinuxLabHostNetworkUncertain(LinuxLabHostNetworkError):
    """A host mutation started but its final state could not be verified."""

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = dict(details or {})


class LinuxLabHostNetworkService:
    NETWORK_NAME = "default"
    BRIDGE_NAME = "virbr0"
    GATEWAY = "192.168.122.1"
    MANAGEMENT_GATEWAY = "10.10.10.1"
    PREFIX = 24
    NETMASK = "255.255.255.0"
    ADDRESS_CONTRACT = (
        ("lab_gateway", GATEWAY, PREFIX),
        ("management_gateway", MANAGEMENT_GATEWAY, PREFIX),
    )
    COMMAND_TIMEOUT = 20

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        system: str | None = None,
        sudo_prefix: Sequence[str] | None = None,
    ) -> None:
        self.runner = runner
        self.system = system or platform.system()
        self.sudo_prefix = tuple(sudo_prefix) if sudo_prefix is not None else (
            () if hasattr(os, "geteuid") and os.geteuid() == 0 else ("sudo", "-n")
        )

    def _run(self, arguments: Sequence[str], *, privileged: bool = False) -> str:
        if not arguments or any(not isinstance(part, str) or not part for part in arguments):
            raise LinuxLabHostNetworkError("host command arguments must be non-empty strings")
        command = (*self.sudo_prefix, *arguments) if privileged else tuple(arguments)
        try:
            result = self.runner(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.COMMAND_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LinuxLabHostNetworkError(
                f"could not execute the host networking command {arguments[0]!r}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            detail = detail[:500] if detail else "no diagnostic output"
            raise LinuxLabHostNetworkError(
                f"host command {arguments[0]!r} failed with exit code {result.returncode}: {detail}"
            )
        return result.stdout or ""

    def _inspect_bridge(self) -> dict:
        raw = self._run(["ip", "-json", "address", "show", "dev", self.BRIDGE_NAME])
        try:
            rows = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise LinuxLabHostNetworkError("ip returned invalid JSON for the management bridge") from exc
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return {"exists": False, "ipv4": []}
        addresses = []
        for item in rows[0].get("addr_info", []):
            if not isinstance(item, dict) or item.get("family") != "inet":
                continue
            addresses.append({
                "local": str(item.get("local", "")),
                "prefixlen": item.get("prefixlen"),
            })
        return {"exists": True, "ipv4": addresses}

    def _inspect_libvirt(self) -> dict:
        raw = self._run(["virsh", "net-dumpxml", self.NETWORK_NAME])
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise LinuxLabHostNetworkError("libvirt returned invalid network XML") from exc
        if root.tag != "network":
            raise LinuxLabHostNetworkError("libvirt response is not a network definition")
        name = root.findtext("name")
        if name != self.NETWORK_NAME:
            raise LinuxLabHostNetworkError("libvirt returned a network other than the protected default network")
        bridge = root.find("bridge")
        ip_element = root.find("ip")
        bridge_name = bridge.get("name") if bridge is not None else None
        network_ip = ip_element.get("address") if ip_element is not None else None
        network_netmask = ip_element.get("netmask") if ip_element is not None else None
        if bridge_name != self.BRIDGE_NAME:
            raise LinuxLabHostNetworkError(
                f"libvirt default network bridge is {bridge_name!r}, expected {self.BRIDGE_NAME!r}"
            )
        if network_ip != self.GATEWAY or network_netmask != self.NETMASK:
            raise LinuxLabHostNetworkError(
                "libvirt default network gateway/subnet differs from the protected lab contract"
            )

        dhcp = ip_element.find("dhcp") if ip_element is not None else None
        ranges = list(dhcp.findall("range")) if dhcp is not None else []
        hosts = list(dhcp.findall("host")) if dhcp is not None else []
        return {
            "name": name,
            "bridge": bridge_name,
            "gateway": network_ip,
            "netmask": network_netmask,
            "dhcp_ranges": [
                ET.tostring(item, encoding="unicode", short_empty_elements=True)
                for item in ranges
            ],
            "dhcp_hosts": [
                ET.tostring(item, encoding="unicode", short_empty_elements=True)
                for item in hosts
            ],
        }

    def plan(self) -> dict:
        """Read live bridge and libvirt state; do not mutate anything."""
        if self.system != "Linux":
            raise LinuxLabHostNetworkError(
                "libvirt bridge and host network provisioning is available only on a Linux Runner"
            )
        bridge = self._inspect_bridge()
        libvirt = self._inspect_libvirt()
        conflicts = []
        if not bridge["exists"]:
            conflicts.append({
                "code": "MANAGEMENT_BRIDGE_MISSING",
                "message": "The libvirt default network bridge virbr0 does not exist; start the libvirt default network first",
            })
        observed = {
            (item["local"], int(item["prefixlen"]))
            for item in bridge["ipv4"]
            if isinstance(item.get("prefixlen"), int)
        }
        allowed = {(address, prefix) for _label, address, prefix in self.ADDRESS_CONTRACT}
        unexpected = sorted(observed - allowed)
        missing = [
            (label, address, prefix)
            for label, address, prefix in self.ADDRESS_CONTRACT
            if (address, prefix) not in observed
        ]
        if unexpected:
            conflicts.append({
                "code": "MANAGEMENT_BRIDGE_ADDRESS_CONFLICT",
                "message": (
                    "virbr0 has IPv4 addresses outside the protected "
                    "192.168.122.1/24 and 10.10.10.1/24 lab contract; "
                    "refusing to remove or replace them"
                ),
                "observed": [
                    {"address": address, "prefix": prefix}
                    for address, prefix in unexpected
                ],
            })
        return {
            "platform": "Linux",
            "network": libvirt,
            "bridge": bridge,
            "gateway_status": (
                "PRESENT" if (self.GATEWAY, self.PREFIX) in observed else "MISSING"
            ),
            "management_gateway_status": (
                "PRESENT" if (self.MANAGEMENT_GATEWAY, self.PREFIX) in observed else "MISSING"
            ),
            "dhcp_ranges_to_remove": len(libvirt["dhcp_ranges"]),
            "dhcp_hosts_to_remove": len(libvirt["dhcp_hosts"]),
            "conflicts": conflicts,
            "can_apply": not conflicts,
            "mutations": {
                "add_gateway_address": bridge["exists"] and (self.GATEWAY, self.PREFIX) not in observed and not unexpected,
                "add_management_gateway_address": bridge["exists"] and (self.MANAGEMENT_GATEWAY, self.PREFIX) not in observed and not unexpected,
                "remove_default_network_dhcp_ranges": len(libvirt["dhcp_ranges"]),
                "remove_default_network_dhcp_hosts": len(libvirt["dhcp_hosts"]),
            },
            "safety": {
                "recreates_network": False,
                "flushes_bridge_addresses": False,
                "changes_routes": False,
                "modifies_unrelated_networks": False,
                "requires_explicit_confirmation": True,
            },
        }

    def apply(self, *, confirmed: bool, actor: str) -> dict:
        """Apply only the additive gateway and explicitly requested DHCP cleanup."""
        if confirmed is not True:
            raise LinuxLabHostNetworkError("explicit operator confirmation is required")
        actor = str(actor or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise LinuxLabHostNetworkError("actor must contain 1 to 128 printable characters")
        plan = self.plan()
        if not plan["can_apply"]:
            raise LinuxLabHostNetworkError(
                "host network preflight found a conflict; no host changes were made"
            )

        completed = []
        try:
            # DHCP records are deleted one at a time using libvirt's live and
            # persistent update API. The network itself is never redefined.
            for xml in plan["network"]["dhcp_ranges"]:
                self._run([
                    "virsh", "net-update", self.NETWORK_NAME, "delete",
                    "ip-dhcp-range", xml, "--live", "--config",
                ])
                completed.append("delete_dhcp_range")
            for xml in plan["network"]["dhcp_hosts"]:
                self._run([
                    "virsh", "net-update", self.NETWORK_NAME, "delete",
                    "ip-dhcp-host", xml, "--live", "--config",
                ])
                completed.append("delete_dhcp_host")

            for key, label, address in (
                ("add_gateway_address", "add_gateway_address", self.GATEWAY),
                ("add_management_gateway_address", "add_management_gateway_address", self.MANAGEMENT_GATEWAY),
            ):
                if plan["mutations"][key]:
                    self._run([
                        "ip", "address", "replace",
                        f"{address}/{self.PREFIX}",
                        "dev", self.BRIDGE_NAME,
                    ], privileged=True)
                    completed.append(label)

            after = self.plan()
            if (
                not after["can_apply"]
                or after["gateway_status"] != "PRESENT"
                or after["management_gateway_status"] != "PRESENT"
                or after["dhcp_ranges_to_remove"]
                or after["dhcp_hosts_to_remove"]
            ):
                raise LinuxLabHostNetworkUncertain(
                    "host network mutation completed but provider read-back did not satisfy all postconditions",
                    details={"completed_operations": completed, "observed": after},
                )
        except LinuxLabHostNetworkUncertain:
            raise
        except Exception as exc:
            if completed:
                raise LinuxLabHostNetworkUncertain(
                    "host network changes partially applied; inspect virbr0 and libvirt default DHCP state before retrying",
                    details={"completed_operations": completed},
                ) from exc
            raise

        return {
            "status": "APPLIED",
            "actor": actor,
            "network": self.NETWORK_NAME,
            "bridge": self.BRIDGE_NAME,
            "gateway": f"{self.GATEWAY}/{self.PREFIX}",
            "management_gateway": f"{self.MANAGEMENT_GATEWAY}/{self.PREFIX}",
            "removed_dhcp_ranges": plan["dhcp_ranges_to_remove"],
            "removed_dhcp_hosts": plan["dhcp_hosts_to_remove"],
            "reconciliation": after,
            "completed_operations": completed,
        }
