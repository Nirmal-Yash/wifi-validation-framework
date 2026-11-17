from __future__ import annotations

import json
import subprocess

import pytest

from lib.services.linux_lab_host_network import (
    LinuxLabHostNetworkError,
    LinuxLabHostNetworkService,
    LinuxLabHostNetworkUncertain,
)


def ip_state(addresses=()):
    return json.dumps([{
        "ifname": "virbr0",
        "addr_info": [
            {"family": "inet", "local": ip, "prefixlen": prefix}
            for ip, prefix in addresses
        ],
    }])


def network_xml(*, ranges=True, hosts=True, bridge="virbr0", gateway="192.168.122.1"):
    dhcp = "<dhcp>"
    if ranges:
        dhcp += '<range start="192.168.122.100" end="192.168.122.200"/>'
    if hosts:
        dhcp += '<host mac="52:54:00:aa:bb:cc" name="protected-client" ip="192.168.122.30"/>'
    dhcp += "</dhcp>" if ranges or hosts else ""
    return (
        "<network><name>default</name>"
        f'<bridge name="{bridge}"/>'
        f'<ip address="{gateway}" netmask="255.255.255.0">{dhcp}</ip>'
        "</network>"
    )


class FakeHost:
    def __init__(self):
        self.addresses = []
        self.ranges = True
        self.hosts = True
        self.calls = []
        self.fail_command = None

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append(command)
        if self.fail_command and self.fail_command(command):
            return subprocess.CompletedProcess(command, 1, "", "injected failure")
        if "ip" in command and "-json" in command:
            return subprocess.CompletedProcess(command, 0, ip_state(self.addresses), "")
        if "virsh" in command and "net-dumpxml" in command:
            return subprocess.CompletedProcess(
                command, 0,
                network_xml(ranges=self.ranges, hosts=self.hosts),
                "",
            )
        if "virsh" in command and "net-update" in command:
            if "ip-dhcp-range" in command:
                self.ranges = False
            elif "ip-dhcp-host" in command:
                self.hosts = False
            return subprocess.CompletedProcess(command, 0, "", "")
        if "ip" in command and "address" in command and "replace" in command:
            value = command[command.index("replace") + 1]
            address, prefix_text = value.split("/", 1)
            item = (address, int(prefix_text))
            self.addresses = [entry for entry in self.addresses if entry[0] != address]
            self.addresses.append(item)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "unexpected test command")


def make_service(fake, **kwargs):
    return LinuxLabHostNetworkService(
        runner=fake,
        system=kwargs.get("system", "Linux"),
        sudo_prefix=kwargs.get("sudo_prefix", ("sudo", "-n")),
    )


def test_host_network_plan_is_read_only_and_reports_exact_mutations():
    fake = FakeHost()
    service = make_service(fake)

    plan = service.plan()

    assert plan["can_apply"] is True
    assert plan["gateway_status"] == "MISSING"
    assert plan["management_gateway_status"] == "MISSING"
    assert plan["mutations"]["add_gateway_address"] is True
    assert plan["mutations"]["add_management_gateway_address"] is True
    assert plan["dhcp_ranges_to_remove"] == 1
    assert plan["dhcp_hosts_to_remove"] == 1
    assert plan["safety"]["recreates_network"] is False
    assert plan["safety"]["changes_routes"] is False
    assert len(fake.calls) == 2
    assert all("net-update" not in command for command in fake.calls)
    assert all("address" not in command for command in fake.calls)


def test_apply_requires_confirmation_and_preserves_existing_network_structure():
    fake = FakeHost()
    service = make_service(fake)
    with pytest.raises(LinuxLabHostNetworkError, match="confirmation"):
        service.apply(confirmed=False, actor="operator")
    assert len(fake.calls) == 0

    result = service.apply(confirmed=True, actor="operator")
    assert result["status"] == "APPLIED"
    assert result["removed_dhcp_ranges"] == 1
    assert result["removed_dhcp_hosts"] == 1
    assert result["gateway"] == "192.168.122.1/24"
    assert result["management_gateway"] == "10.10.10.1/24"
    assert result["reconciliation"]["management_gateway_status"] == "PRESENT"
    updates = [command for command in fake.calls if "net-update" in command]
    assert len(updates) == 2
    assert all("--live" in command and "--config" in command for command in updates)
    assert all(command[2:4] == ["default", "delete"] for command in updates)
    assert ["sudo", "-n", "ip", "address", "replace", "192.168.122.1/24", "dev", "virbr0"] in fake.calls
    assert ["sudo", "-n", "ip", "address", "replace", "10.10.10.1/24", "dev", "virbr0"] in fake.calls


def test_apply_is_idempotent_after_protected_network_is_already_prepared():
    fake = FakeHost()
    fake.ranges = False
    fake.hosts = False
    fake.addresses = [("192.168.122.1", 24), ("10.10.10.1", 24)]
    service = make_service(fake)

    result = service.apply(confirmed=True, actor="operator")

    assert result["status"] == "APPLIED"
    assert result["completed_operations"] == []
    assert len(fake.calls) == 4
    assert result["reconciliation"]["gateway_status"] == "PRESENT"
    assert result["reconciliation"]["management_gateway_status"] == "PRESENT"


def test_host_network_adds_only_missing_management_address_when_libvirt_gateway_is_present():
    fake = FakeHost()
    fake.addresses = [("192.168.122.1", 24)]
    fake.ranges = False
    fake.hosts = False
    service = make_service(fake)

    plan = service.plan()
    assert plan["gateway_status"] == "PRESENT"
    assert plan["management_gateway_status"] == "MISSING"
    assert plan["mutations"]["add_gateway_address"] is False
    assert plan["mutations"]["add_management_gateway_address"] is True

    result = service.apply(confirmed=True, actor="operator")
    assert result["status"] == "APPLIED"
    assert result["completed_operations"] == ["add_management_gateway_address"]
    assert fake.addresses == [("192.168.122.1", 24), ("10.10.10.1", 24)]


def test_host_network_refuses_unrelated_gateway_address_without_replacing_it():
    fake = FakeHost()
    fake.addresses = [("10.0.0.1", 24)]
    service = make_service(fake)

    plan = service.plan()
    assert not plan["can_apply"]
    assert "MANAGEMENT_BRIDGE_ADDRESS_CONFLICT" in {
        item["code"] for item in plan["conflicts"]
    }
    with pytest.raises(LinuxLabHostNetworkError, match="preflight"):
        service.apply(confirmed=True, actor="operator")
    assert not any("net-update" in command for command in fake.calls)


def test_host_network_refuses_bridge_or_subnet_mismatch():
    fake = FakeHost()
    fake.fail_command = lambda command: False
    service = LinuxLabHostNetworkService(
        runner=lambda command, **kwargs: (
            subprocess.CompletedProcess(command, 0, ip_state(), "")
            if "ip" in command else
            subprocess.CompletedProcess(
                command, 0, network_xml(bridge="virbr2"), "",
            )
        ),
        system="Linux",
        sudo_prefix=(),
    )
    with pytest.raises(LinuxLabHostNetworkError, match="bridge"):
        service.plan()


def test_host_network_is_linux_only():
    fake = FakeHost()
    service = make_service(fake, system="Windows")
    with pytest.raises(LinuxLabHostNetworkError, match="Linux Runner"):
        service.plan()
    assert fake.calls == []


def test_partial_host_mutation_is_marked_uncertain_for_operator_reconciliation():
    fake = FakeHost()
    fake.fail_command = lambda command: "ip" in command and "address" in command and "replace" in command
    service = make_service(fake)
    with pytest.raises(LinuxLabHostNetworkUncertain, match="partially applied"):
        service.apply(confirmed=True, actor="operator")
    assert fake.ranges is False
    assert fake.hosts is False
