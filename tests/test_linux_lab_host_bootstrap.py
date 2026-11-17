from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from lib.services.linux_lab_host_bootstrap import (
    LinuxLabHostBootstrapConflict,
    LinuxLabHostBootstrapService,
)
from lib.services.linux_lab_host_network import LinuxLabHostNetworkService


NETWORK_XML = """<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'/>
</network>
"""


class FakeUbuntuHost:
    BASE_COMMANDS = {
        "apt-get", "dpkg-query", "ip", "ping", "python3",
        "systemctl", "timedatectl",
    }
    PACKAGE_COMMANDS = {
        "docker.io": "docker",
        "libvirt-clients": "virsh",
        "iproute2": "ip",
        "iputils-ping": "ping",
        "iw": "iw",
        "curl": "curl",
        "chrony": "chronyc",
    }

    def __init__(
        self,
        *,
        installed=None,
        network_exists=False,
        network_active=False,
        network_autostart=False,
        docker_ready=False,
        docker_active=False,
        chrony_active=False,
        clock_synchronized=False,
        sudo_ready=True,
        bridge_exists=False,
        network_xml=NETWORK_XML,
    ):
        self.installed = set(installed or ())
        self.network_exists = network_exists
        self.network_active = network_active
        self.network_autostart = network_autostart
        self.docker_ready = docker_ready
        self.docker_active = docker_active
        self.chrony_active = chrony_active
        self.clock_synchronized = clock_synchronized
        self.sudo_ready = sudo_ready
        self.bridge_exists = bridge_exists
        self.network_xml = network_xml
        self.calls = []
        self.defined_xml = None
        self.temporary_xml_path = None

    def which(self, name):
        if name in self.BASE_COMMANDS:
            return "/usr/bin/" + name
        return "/usr/bin/" + name if name in self.PACKAGE_COMMANDS.values() and any(
            command == name and package in self.installed
            for package, command in self.PACKAGE_COMMANDS.items()
        ) else None

    def __call__(self, command, **kwargs):
        args = list(command)
        self.calls.append((args, kwargs))
        privileged = args[:2] == ["sudo", "-n"]
        normalized = args[2:] if privileged else args

        if normalized == ["true"]:
            return subprocess.CompletedProcess(args, 0 if self.sudo_ready else 1, "", "")

        if normalized[:2] == ["dpkg-query", "-W"]:
            package = normalized[-1]
            installed = package in self.installed
            return subprocess.CompletedProcess(
                args, 0 if installed else 1,
                "Status: install ok installed" if installed else "",
                "",
            )

        if normalized[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(
                args, 0 if self.docker_ready else 1,
                "Docker Engine" if self.docker_ready else "",
                "" if self.docker_ready else "daemon unavailable",
            )

        if normalized[:4] == ["systemctl", "is-active", "--quiet", "chrony"]:
            return subprocess.CompletedProcess(args, 0 if self.chrony_active else 3, "", "")
        if normalized[:4] == ["systemctl", "is-active", "--quiet", "docker"]:
            return subprocess.CompletedProcess(args, 0 if self.docker_active else 3, "", "")
        if normalized[:4] == ["systemctl", "enable", "--now", "chrony"]:
            self.chrony_active = True
            return subprocess.CompletedProcess(args, 0, "", "")
        if normalized[:4] == ["systemctl", "enable", "--now", "docker"]:
            self.docker_active = True
            self.docker_ready = True
            return subprocess.CompletedProcess(args, 0, "", "")

        if normalized[:2] == ["timedatectl", "show"]:
            return subprocess.CompletedProcess(
                args, 0, "yes" if self.clock_synchronized else "no", "",
            )
        if normalized[:2] == ["chronyc", "waitsync"]:
            if self.chrony_active:
                self.clock_synchronized = True
            return subprocess.CompletedProcess(args, 0, "", "")

        if normalized[:3] == ["virsh", "net-info", "default"]:
            if not self.network_exists:
                return subprocess.CompletedProcess(args, 1, "", "Network not found")
            status = (
                "Name: default\n"
                "Active: " + ("yes" if self.network_active else "no") + "\n"
                "Autostart: " + ("yes" if self.network_autostart else "no") + "\n"
            )
            return subprocess.CompletedProcess(args, 0, status, "")
        if normalized[:3] == ["virsh", "net-dumpxml", "default"]:
            return subprocess.CompletedProcess(args, 0, self.network_xml, "")
        if len(normalized) == 3 and normalized[:2] == ["virsh", "net-define"]:
            self.temporary_xml_path = Path(normalized[2])
            self.defined_xml = self.temporary_xml_path.read_text(encoding="utf-8")
            self.network_exists = True
            self.network_xml = self.defined_xml
            return subprocess.CompletedProcess(args, 0, "", "")
        if normalized[:3] == ["virsh", "net-start", "default"]:
            self.network_active = True
            self.bridge_exists = True
            return subprocess.CompletedProcess(args, 0, "", "")
        if normalized[:3] == ["virsh", "net-autostart", "default"]:
            self.network_autostart = True
            return subprocess.CompletedProcess(args, 0, "", "")

        if normalized[:4] == ["ip", "link", "show", "dev"]:
            return subprocess.CompletedProcess(
                args, 0 if self.bridge_exists else 1,
                "virbr0" if self.bridge_exists else "",
                "",
            )
        if normalized[:4] == ["ip", "-json", "address", "show"]:
            payload = [{
                "ifname": "virbr0",
                "addr_info": [
                    {"family": "inet", "local": "192.168.122.1", "prefixlen": 24}
                ],
            }] if self.bridge_exists else []
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

        if normalized[:2] == ["apt-get", "update"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        if normalized[:2] == ["env", "DEBIAN_FRONTEND=noninteractive"]:
            for value in normalized:
                if value in LinuxLabHostBootstrapService.REQUIRED_PACKAGES:
                    self.installed.add(value)
            return subprocess.CompletedProcess(args, 0, "", "")

        return subprocess.CompletedProcess(args, 0, "", "")


def make_service(fake: FakeUbuntuHost, *, system="Linux", sudo_prefix=("sudo", "-n")):
    network = LinuxLabHostNetworkService(
        runner=fake,
        system=system,
        sudo_prefix=sudo_prefix,
    )
    return LinuxLabHostBootstrapService(
        network,
        runner=fake,
        system=system,
        effective_uid=1000,
        which=fake.which,
        sudo_prefix=sudo_prefix,
    )


def test_host_bootstrap_plan_is_read_only_and_lists_host_mutations():
    fake = FakeUbuntuHost()
    service = make_service(fake)

    plan = service.plan()

    assert plan["can_apply"] is True
    assert plan["missing_packages"] == list(service.REQUIRED_PACKAGES)
    assert plan["docker"]["daemon_ready"] is False
    assert plan["chrony"]["clock_synchronized"] is False
    assert plan["libvirt_default_network"]["exists"] is False
    assert plan["mutations"]["define_default_network"] is True
    assert plan["safety"]["redefines_existing_network"] is False
    assert not any(
        item[0][:2] in (
            ["apt-get", "-qq"],
            ["systemctl", "enable"],
            ["virsh", "net-define"],
            ["virsh", "net-start"],
            ["virsh", "net-autostart"],
        )
        for item in fake.calls
    )


def test_host_bootstrap_requires_confirmation_before_any_command():
    fake = FakeUbuntuHost()
    service = make_service(fake)

    with pytest.raises(LinuxLabHostBootstrapConflict, match="confirmation"):
        service.apply(confirmed=False)

    assert fake.calls == []


def test_host_bootstrap_installs_packages_starts_services_and_defines_missing_network():
    fake = FakeUbuntuHost()
    service = make_service(fake)

    result = service.apply(confirmed=True)

    assert result["status"] == "APPLIED"
    assert set(fake.installed) == set(service.REQUIRED_PACKAGES)
    assert fake.chrony_active is True
    assert fake.clock_synchronized is True
    assert fake.docker_active is True
    assert fake.docker_ready is True
    assert fake.network_exists is True
    assert fake.network_active is True
    assert fake.network_autostart is True
    assert fake.bridge_exists is True
    assert "<bridge name='virbr0'" in fake.defined_xml
    assert "192.168.122.1" in fake.defined_xml
    assert fake.temporary_xml_path is not None
    assert not fake.temporary_xml_path.exists()
    commands = [item[0] for item in fake.calls]
    assert ["sudo", "-n", "apt-get", "-qq", "update"] in commands
    assert any(item[:4] == ["sudo", "-n", "systemctl", "enable"] for item in commands)
    assert sum(item[:2] == ["virsh", "net-define"] for item in commands) == 1
    assert result["reconciliation"]["libvirt_default_network"]["active"] is True


def test_host_bootstrap_is_idempotent_for_an_already_ready_host():
    fake = FakeUbuntuHost(
        installed=LinuxLabHostBootstrapService.REQUIRED_PACKAGES,
        network_exists=True,
        network_active=True,
        network_autostart=True,
        docker_ready=True,
        docker_active=True,
        chrony_active=True,
        clock_synchronized=True,
        bridge_exists=True,
    )
    service = make_service(fake)

    result = service.apply(confirmed=True)

    assert result["status"] == "APPLIED"
    assert result["completed_steps"] == ["clock_synchronized"]
    commands = [item[0] for item in fake.calls]
    assert not any("apt-get" in item for item in commands)
    assert not any(item[:3] == ["virsh", "net-define", "default"] for item in commands)
    assert not any(item[:3] == ["virsh", "net-start", "default"] for item in commands)
    assert not any(item[:3] == ["virsh", "net-autostart", "default"] for item in commands)


def test_host_bootstrap_refuses_to_redefine_an_existing_mismatched_network():
    fake = FakeUbuntuHost(
        installed=LinuxLabHostBootstrapService.REQUIRED_PACKAGES,
        network_exists=True,
        network_active=True,
        network_autostart=True,
        docker_ready=True,
        docker_active=True,
        chrony_active=True,
        clock_synchronized=True,
        bridge_exists=True,
        network_xml=NETWORK_XML.replace("virbr0", "br-lab"),
    )
    service = make_service(fake)

    with pytest.raises(LinuxLabHostBootstrapConflict, match="differs from the protected"):
        service.plan()

    assert not any("net-define" in item[0] for item in fake.calls)


def test_host_bootstrap_fails_closed_when_passwordless_sudo_is_unavailable():
    fake = FakeUbuntuHost(sudo_ready=False)
    service = make_service(fake)

    plan = service.plan()
    assert plan["can_apply"] is False
    assert "PASSWORDLESS_SUDO_REQUIRED" in {
        item["code"] for item in plan["conflicts"]
    }
    with pytest.raises(LinuxLabHostBootstrapConflict, match="conflicts"):
        service.apply(confirmed=True)


def test_host_bootstrap_is_linux_only():
    fake = FakeUbuntuHost()
    service = make_service(fake, system="Windows")

    with pytest.raises(LinuxLabHostBootstrapConflict, match="Ubuntu/Linux"):
        service.plan()

    assert fake.calls == []
