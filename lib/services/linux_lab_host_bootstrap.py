"""Plan-first Ubuntu host readiness for the protected GNS3 Wi-Fi lab."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Sequence


class LinuxLabHostBootstrapError(RuntimeError):
    """A host dependency or startup operation failed safely."""


class LinuxLabHostBootstrapConflict(LinuxLabHostBootstrapError):
    """The host is not in a state this additive bootstrap can repair safely."""


class LinuxLabHostBootstrapService:
    REQUIRED_PACKAGES = (
        "docker.io", "libvirt-clients", "libvirt-daemon-system",
        "iproute2", "iputils-ping", "iw", "openssh-client",
        "python3-venv", "python3-pip", "curl", "chrony",
    )
    REQUIRED_COMMANDS = (
        "apt-get", "dpkg-query", "docker", "virsh", "ip", "iw",
        "ping", "python3", "curl", "chronyc", "systemctl", "timedatectl",
    )
    INSTALLABLE_COMMANDS = {
        "docker": "docker.io", "virsh": "libvirt-clients",
        "ip": "iproute2", "iw": "iw", "ping": "iputils-ping",
        "curl": "curl", "chronyc": "chrony",
    }
    DEFAULT_NETWORK_XML = """<network>
  <name>default</name>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'/>
</network>
"""

    def __init__(
        self, host_network, *, runner: Callable[..., subprocess.CompletedProcess] | None = None,
        system: str | None = None, effective_uid: int | None = None,
        which: Callable[[str], str | None] = shutil.which,
        sudo_prefix: Sequence[str] | None = None,
    ) -> None:
        self.host_network = host_network
        self.runner = runner or host_network.runner or subprocess.run
        self.system = system or platform.system()
        self.effective_uid = (
            effective_uid if effective_uid is not None
            else (os.geteuid() if hasattr(os, "geteuid") else -1)
        )
        self.which = which
        self.sudo_prefix = tuple(
            sudo_prefix if sudo_prefix is not None else host_network.sudo_prefix
        )

    def _run(
        self, arguments: Sequence[str], *, privileged: bool = False,
        timeout: float = 30.0, check: bool = True,
    ) -> subprocess.CompletedProcess:
        if isinstance(arguments, (str, bytes)):
            raise TypeError("host commands must be argument sequences")
        args = tuple(arguments)
        if not args or any(not isinstance(x, str) or not x or "\x00" in x for x in args):
            raise ValueError("host command arguments must be non-empty strings")
        if privileged and not self.sudo_prefix:
            raise LinuxLabHostBootstrapConflict("normal-user passwordless sudo is required")
        actual = (*self.sudo_prefix, *args) if privileged else args
        try:
            result = self.runner(
                list(actual), capture_output=True, text=True,
                timeout=timeout, check=False, shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LinuxLabHostBootstrapError(f"host command timed out: {args[0]}") from exc
        except OSError as exc:
            raise LinuxLabHostBootstrapError(
                f"host command could not start: {args[0]} ({type(exc).__name__})"
            ) from exc
        if check and result.returncode != 0:
            raise LinuxLabHostBootstrapError(
                f"host command failed: {args[0]} (exit {result.returncode}); diagnostics suppressed"
            )
        return result

    def _sudo_ready(self) -> bool:
        if not self.sudo_prefix:
            return False
        try:
            return self._run(
                ["true"], privileged=True, check=False, timeout=5,
            ).returncode == 0
        except LinuxLabHostBootstrapError:
            return False

    def _installed_packages(self) -> tuple[list[str], list[str]]:
        if not self.which("dpkg-query"):
            return list(self.REQUIRED_PACKAGES), ["dpkg-query"]
        missing = []
        for package in self.REQUIRED_PACKAGES:
            result = self._run(
                ["dpkg-query", "-W", "-f=" + "{Status}", package],
                check=False, timeout=8,
            )
            if result.returncode != 0 or "install ok installed" not in (result.stdout or ""):
                missing.append(package)
        return missing, []

    def _docker_ready(self) -> tuple[bool, str]:
        if not self.which("docker"):
            return False, "unavailable"
        direct = self._run(["docker", "info"], check=False, timeout=20)
        if direct.returncode == 0:
            return True, "user"
        if self.sudo_prefix:
            elevated = self._run(
                ["docker", "info"], privileged=True, check=False, timeout=20,
            )
            if elevated.returncode == 0:
                return True, "sudo"
        return False, "unavailable"

    def _service_active(self, service: str) -> bool:
        return bool(self.which("systemctl")) and self._run(
            ["systemctl", "is-active", "--quiet", service],
            check=False, timeout=8,
        ).returncode == 0

    def _clock_synchronized(self) -> bool:
        return bool(self.which("timedatectl")) and self._run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            check=False, timeout=8,
        ).stdout.strip().lower() == "yes"

    def _virsh(self, *arguments: str, timeout: float = 30.0, check: bool = True):
        if not self.which("virsh"):
            raise LinuxLabHostBootstrapConflict("virsh is not installed")
        direct = self._run(["virsh", *arguments], check=False, timeout=timeout)
        if direct.returncode == 0:
            return direct
        detail = ((direct.stderr or "") + " " + (direct.stdout or "")).lower()
        if self.sudo_prefix and any(
            token in detail for token in (
                "permission denied", "failed to connect", "authentication",
                "cannot connect", "access denied", "not authorized",
            )
        ):
            elevated = self._run(
                ["virsh", *arguments], privileged=True,
                check=False, timeout=timeout,
            )
            if elevated.returncode == 0 or not check:
                return elevated
            return elevated
        if check:
            raise LinuxLabHostBootstrapError(
                f"virsh {arguments[0] if arguments else 'command'} failed; "
                "inspect libvirt state before retrying"
            )
        return direct

    def _network_info(self) -> dict:
        if not self.which("virsh"):
            return {
                "exists": None, "active": False, "autostart": False,
                "reason": "virsh is not installed",
            }
        result = self._virsh("net-info", "default", check=False, timeout=10)
        if result.returncode != 0:
            detail = ((result.stderr or "") + " " + (result.stdout or "")).lower()
            if any(marker in detail for marker in (
                "network not found", "no network with matching name",
                "failed to get network", "not found",
            )):
                return {"exists": False, "active": False, "autostart": False}
            raise LinuxLabHostBootstrapConflict(
                "could not inspect the libvirt default network; refusing to define over an uncertain provider state"
            )
        values = {}
        for line in (result.stdout or "").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                values[key.strip().lower()] = value.strip().lower()
        return {
            "exists": True,
            "active": values.get("active") == "yes",
            "autostart": values.get("autostart") == "yes",
        }

    def _validate_network_definition(self) -> None:
        result = self._virsh("net-dumpxml", "default", timeout=10)
        try:
            root = ET.fromstring(result.stdout or "")
        except ET.ParseError as exc:
            raise LinuxLabHostBootstrapConflict(
                "libvirt default network returned invalid XML; refusing to redefine it"
            ) from exc
        bridge = root.find("bridge")
        ip_node = root.find("ip")
        observed = (
            root.findtext("name"),
            bridge.get("name") if bridge is not None else None,
            ip_node.get("address") if ip_node is not None else None,
            ip_node.get("netmask") if ip_node is not None else None,
        )
        expected = ("default", "virbr0", "192.168.122.1", "255.255.255.0")
        if observed != expected:
            raise LinuxLabHostBootstrapConflict(
                "existing libvirt default network differs from the protected virbr0/192.168.122.1/24 contract; "
                "no definition was changed"
            )

    def plan(self) -> dict:
        if self.system != "Linux":
            raise LinuxLabHostBootstrapConflict(
                "protected GNS3/mac80211_hwsim host preparation requires Ubuntu/Linux"
            )
        if self.effective_uid == 0:
            raise LinuxLabHostBootstrapConflict(
                "run host preparation as the normal Linux user, not with sudo"
            )
        missing_packages, missing_commands = self._installed_packages()
        docker_ready, docker_access = self._docker_ready()
        chrony_active = self._service_active("chrony")
        docker_active = self._service_active("docker")
        clock_synchronized = self._clock_synchronized()
        network = self._network_info()
        if network["exists"] is True:
            self._validate_network_definition()
        # A missing virsh command is repairable when libvirt-clients is in the
        # same approved package transaction; otherwise its provider state is unknown.
        if network["exists"] is None and "libvirt-clients" in missing_packages:
            network = {"exists": False, "active": False, "autostart": False}

        mutations = {
            "install_packages": missing_packages,
            "enable_chrony": not chrony_active,
            "synchronize_clock": not clock_synchronized,
            "enable_docker": not docker_active or not docker_ready,
            "define_default_network": network["exists"] is False,
            "start_default_network": network["exists"] is False or not network["active"],
            "enable_default_network_autostart": network["exists"] is False or not network["autostart"],
        }
        privileged_changes = bool(
            missing_packages or mutations["enable_chrony"] or mutations["enable_docker"]
            or mutations["define_default_network"] or mutations["start_default_network"]
            or mutations["enable_default_network_autostart"]
        )
        sudo_ready = self._sudo_ready() if privileged_changes else True
        non_installable = [
            command for command in missing_commands
            if command not in self.INSTALLABLE_COMMANDS
        ]
        conflicts = []
        if non_installable:
            conflicts.append({
                "code": "HOST_BASE_COMMAND_MISSING",
                "message": "base Ubuntu commands are missing and are not part of the approved package install",
                "commands": non_installable,
            })
        if privileged_changes and not sudo_ready:
            conflicts.append({
                "code": "PASSWORDLESS_SUDO_REQUIRED",
                "message": "host packages, services or libvirt require passwordless sudo; no mutations were attempted",
            })
        if network["exists"] is None:
            conflicts.append({
                "code": "LIBVIRT_UNAVAILABLE",
                "message": "libvirt client tools are unavailable and cannot be installed by the approved package list",
            })
        return {
            "platform": self.system,
            "missing_packages": missing_packages,
            "missing_commands": missing_commands,
            "docker": {
                "daemon_ready": docker_ready,
                "service_active": docker_active,
                "access": docker_access,
            },
            "chrony": {
                "service_active": chrony_active,
                "clock_synchronized": clock_synchronized,
            },
            "libvirt_default_network": network,
            "mutations": mutations,
            "conflicts": conflicts,
            "can_apply": not conflicts,
            "safety": {
                "defines_network_only_when_absent": True,
                "redefines_existing_network": False,
                "deletes_network": False,
                "replaces_existing_network_addresses": False,
                "uses_noninteractive_sudo": True,
                "requires_explicit_confirmation": True,
            },
        }

    def apply(self, *, confirmed: bool) -> dict:
        if confirmed is not True:
            raise LinuxLabHostBootstrapConflict(
                "explicit operator confirmation is required before host preparation"
            )
        before = self.plan()
        if not before["can_apply"]:
            raise LinuxLabHostBootstrapConflict(
                "host preflight found conflicts; no host changes were started"
            )
        completed: list[str] = []
        try:
            missing = before["mutations"]["install_packages"]
            if missing:
                self._run(["apt-get", "-qq", "update"], privileged=True, timeout=600)
                self._run(
                    [
                        "env", "DEBIAN_FRONTEND=noninteractive",
                        "apt-get", "-qq", "install", "-y", *missing,
                    ],
                    privileged=True, timeout=1800,
                )
                completed.append("host_packages")
            missing_commands = [name for name in self.REQUIRED_COMMANDS if not self.which(name)]
            if missing_commands:
                raise LinuxLabHostBootstrapConflict(
                    "host packages installed but commands remain unavailable: " + ", ".join(missing_commands)
                )

            if before["mutations"]["enable_chrony"]:
                self._run(["systemctl", "enable", "--now", "chrony"], privileged=True, timeout=60)
                completed.append("chrony_enabled")
            self._run(["chronyc", "waitsync", "10", "0.5"], timeout=30)
            if not self._clock_synchronized():
                raise LinuxLabHostBootstrapConflict(
                    "Chrony waitsync returned but timedatectl still reports an unsynchronized host clock"
                )
            completed.append("clock_synchronized")

            if before["mutations"]["enable_docker"]:
                self._run(["systemctl", "enable", "--now", "docker"], privileged=True, timeout=90)
                completed.append("docker_enabled")
            docker_ready, docker_access = self._docker_ready()
            if not docker_ready:
                raise LinuxLabHostBootstrapConflict(
                    "Docker daemon is not available to this user or through non-interactive sudo"
                )

            network = self._network_info()
            if network["exists"] is False:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", prefix="netregress-default-",
                    suffix=".xml", delete=False,
                ) as handle:
                    handle.write(self.DEFAULT_NETWORK_XML)
                    xml_path = Path(handle.name)
                try:
                    xml_path.chmod(0o600)
                    self._virsh("net-define", str(xml_path), timeout=45)
                finally:
                    xml_path.unlink(missing_ok=True)
                completed.append("default_network_defined")
                network = self._network_info()
            if network["exists"] is not True:
                raise LinuxLabHostBootstrapConflict(
                    "libvirt default network is still unavailable after the requested definition"
                )
            self._validate_network_definition()
            if not network["active"]:
                self._virsh("net-start", "default", timeout=60)
                completed.append("default_network_started")
            if not network["autostart"]:
                self._virsh("net-autostart", "default", timeout=30)
                completed.append("default_network_autostart")
            self._run(["ip", "link", "show", "dev", "virbr0"], timeout=10)

            after = self.plan()
            if (
                not after["can_apply"] or not after["docker"]["daemon_ready"]
                or not after["chrony"]["service_active"]
                or not after["chrony"]["clock_synchronized"]
                or not after["libvirt_default_network"]["active"]
                or not after["libvirt_default_network"]["autostart"]
            ):
                raise LinuxLabHostBootstrapConflict(
                    "host readiness postconditions were not satisfied after approved setup"
                )
            return {
                "status": "APPLIED",
                "before": before,
                "completed_steps": completed,
                "reconciliation": after,
            }
        except Exception as exc:
            if completed:
                raise LinuxLabHostBootstrapError(
                    "host preparation stopped after partial changes; inspect apt, Docker, Chrony and libvirt state before retrying"
                ) from exc
            raise
