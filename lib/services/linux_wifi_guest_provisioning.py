"""Python-owned Docker/GNS3 guest provisioning for the protected Wi-Fi lab.

Migrates reusable guest, hwsim, WPA, DHCP/DNS, SSH and capture-readiness
operations from wifi_lab_reprovision_robust.sh. Uses plan-first guarded
operations, argument-vector commands and stdin-only secrets. It never unloads
or recycles mac80211_hwsim. The compatibility script remains available until
the physical protected lab accepts this adapter.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
import ipaddress
import os
import re
import subprocess
import time


class LinuxWiFiGuestProvisioningError(RuntimeError):
    """Guest provisioning failed without intentionally exposing secret data."""


class LinuxWiFiGuestProvisioningConflict(LinuxWiFiGuestProvisioningError):
    """Observed host or guest state conflicts with the protected lab contract."""


class LinuxWiFiGuestProvisioningUncertain(LinuxWiFiGuestProvisioningError):
    """Some mutations completed before a later operation failed."""

    def __init__(self, message: str, *, completed_steps: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.completed_steps = tuple(completed_steps)


class LinuxWiFiGuestProvisioningService:
    NODE_PREFIXES = {
        "frr-router": "GNS3.frr-router",
        "hostapd-ap": "GNS3.hostapd-ap",
        "wifi-client": "GNS3.wifi-client",
        "monitor": "GNS3.monitor",
    }
    REQUIRED_INTERFACES = {
        "frr-router": ("eth1",),
        "hostapd-ap": ("eth0",),
        "wifi-client": ("eth0", "eth1"),
        "monitor": ("eth0",),
    }
    LAB_GATEWAY = "192.168.122.1"
    ROUTER_IP = "192.168.122.10"
    AP_IP = "192.168.122.20"
    CLIENT_WIFI_IP = "192.168.122.30"
    MONITOR_IP = "192.168.122.40"
    MANAGEMENT_GATEWAY = "10.10.10.1"
    CLIENT_MANAGEMENT_IP = "10.10.10.30"
    COMMAND_TIMEOUT = 30.0
    PACKAGE_TIMEOUT = 240.0

    def __init__(
        self,
        host_network,
        *,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        system: str | None = None,
        effective_uid: int | None = None,
        module_path: str | os.PathLike[str] = "/sys/module/mac80211_hwsim",
        resource_lock_manager=None,
        sleep: Callable[[float], None] = time.sleep,
        ssh_probe: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.host_network = host_network
        self.runner = runner or subprocess.run
        self.system = system or __import__("platform").system()
        self.effective_uid = effective_uid if effective_uid is not None else (
            os.geteuid() if hasattr(os, "geteuid") else -1
        )
        self.module_path = Path(module_path)
        self.resource_lock_manager = resource_lock_manager
        self.sleep = sleep
        self.ssh_probe = ssh_probe or self._netmiko_ssh_probe
        self.docker_prefix: tuple[str, ...] = ("docker",)
        self._docker_access_checked = False

    @staticmethod
    def _actor(value: object) -> str:
        actor = str(value or "").strip()
        if not actor or len(actor) > 128 or any(ord(char) < 33 for char in actor):
            raise ValueError("actor must contain 1 to 128 printable characters")
        return actor

    @staticmethod
    def _container_name(value: object) -> str:
        name = str(value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            raise ValueError("Docker container identifier is invalid")
        return name

    @staticmethod
    def _validate_wifi(ssid: str, psk: str) -> None:
        if (
            not isinstance(ssid, str)
            or not 1 <= len(ssid.encode("utf-8")) <= 32
            or any(ord(char) < 32 or ord(char) == 127 for char in ssid)
        ):
            raise ValueError("SSID must contain 1 to 32 printable UTF-8 bytes")
        if (
            not isinstance(psk, str)
            or not 8 <= len(psk) <= 63
            or any(ord(char) < 32 or ord(char) > 126 for char in psk)
        ):
            raise ValueError("WPA2 passphrase must contain 8 to 63 printable ASCII characters")

    @staticmethod
    def _validate_passwords(passwords: Mapping[str, str]) -> dict[str, str]:
        required = {"router1", "ap", "client", "monitor", "wifi_psk"}
        if not isinstance(passwords, Mapping) or set(passwords) != required:
            raise ValueError("guest credentials must provide router1, ap, client, monitor and wifi_psk")
        result: dict[str, str] = {}
        for key, raw in passwords.items():
            value = str(raw or "")
            if not value or len(value) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError(f"{key} credential must be 1 to 256 printable characters")
            result[key] = value
        LinuxWiFiGuestProvisioningService._validate_wifi("TestNet_5G", result["wifi_psk"])
        return result

    def _run(
        self,
        command: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float | None = None,
        privileged: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        if isinstance(command, (str, bytes)):
            raise TypeError("host and Docker commands must be argument sequences")
        args = tuple(command)
        if not args or any(not isinstance(item, str) or not item or "\x00" in item for item in args):
            raise ValueError("command arguments must be non-empty strings without NUL bytes")
        actual = (("sudo", "-n") if privileged else ()) + args
        try:
            result = self.runner(
                list(actual),
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout or self.COMMAND_TIMEOUT,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LinuxWiFiGuestProvisioningError(
                f"command timed out after {timeout or self.COMMAND_TIMEOUT:g}s ({args[0]})"
            ) from exc
        except OSError as exc:
            raise LinuxWiFiGuestProvisioningError(
                f"command could not start ({args[0]}, {type(exc).__name__})"
            ) from exc
        if check and result.returncode != 0:
            # Suppress subprocess output: package and SSH tools can echo
            # configuration data and it is not needed for recovery.
            raise LinuxWiFiGuestProvisioningError(
                f"command failed ({args[0]}, exit {result.returncode}); inspect the target guest locally"
            )
        return result

    def _ensure_docker_access(self) -> None:
        if self._docker_access_checked:
            return
        direct = self._run(["docker", "info"], timeout=15, check=False)
        if direct.returncode == 0:
            self.docker_prefix = ("docker",)
        else:
            privileged = self._run(
                ["sudo", "-n", "docker", "info"], timeout=15, check=False,
            )
            if privileged.returncode != 0:
                raise LinuxWiFiGuestProvisioningConflict(
                    "Docker daemon is not available to the current user or through non-interactive sudo"
                )
            self.docker_prefix = ("sudo", "-n", "docker")
        self._docker_access_checked = True

    def _docker(
        self, *arguments: str, input_text: str | None = None,
        timeout: float | None = None, check: bool = True,
    ) -> subprocess.CompletedProcess:
        return self._run(
            [*self.docker_prefix, *arguments],
            input_text=input_text, timeout=timeout, check=check,
        )

    def _guest(
        self, container: str, *command: str, input_text: str | None = None,
        timeout: float | None = None, check: bool = True,
    ) -> subprocess.CompletedProcess:
        safe_container = self._container_name(container)
        if not command:
            raise ValueError("guest command is required")
        args = ["exec"]
        if input_text is not None:
            args.append("-i")
        args.extend([safe_container, *command])
        return self._docker(*args, input_text=input_text, timeout=timeout, check=check)

    def _write_guest_file(self, container: str, path: str, content: str) -> None:
        target = PurePosixPath(path)
        if not target.is_absolute() or ".." in target.parts or str(target) != path:
            raise ValueError("guest configuration path must be a normalized absolute path")
        # Private config content, including WPA credentials, travels over stdin
        # and is created owner-only. It is never passed in process arguments.
        self._guest(
            container, "sh", "-c", 'umask 077; cat > "$1"', "netregress", path,
            input_text=content, timeout=15,
        )

    def _find_containers(self) -> dict[str, str]:
        names = self._docker("ps", "-a", "--format", "{{.Names}}").stdout.splitlines()
        result = {}
        for node, prefix in self.NODE_PREFIXES.items():
            matches = sorted(
                self._container_name(name)
                for name in names
                if name == prefix or name.startswith(prefix + ".")
            )
            if not matches:
                raise LinuxWiFiGuestProvisioningConflict(f"GNS3 Docker node is missing: {node}")
            if len(matches) > 1:
                raise LinuxWiFiGuestProvisioningConflict(f"GNS3 Docker node name is ambiguous: {node}")
            result[node] = matches[0]
        return result

    def _inspect_container(self, container: str) -> dict:
        running = self._docker(
            "inspect", "--format", "{{.State.Running}}", container,
        ).stdout.strip().lower() == "true"
        pid_text = self._docker("inspect", "--format", "{{.State.Pid}}", container).stdout.strip()
        try:
            pid = int(pid_text)
        except ValueError as exc:
            raise LinuxWiFiGuestProvisioningError("Docker returned an invalid container PID") from exc
        return {"name": container, "running": running, "pid": pid}

    def _host_phys(self) -> list[str]:
        output = self._run(["iw", "phy"], timeout=15).stdout
        found = set(re.findall(r"^Wiphy\s+(\S+)", output, flags=re.MULTILINE))
        def natural(value: str):
            match = re.fullmatch(r"phy(\d+)", value)
            return (0, int(match.group(1))) if match else (1, value)
        return sorted(found, key=natural)

    def _interface_state(self, container: str, interface: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface):
            raise ValueError("network interface name is invalid")
        result = self._guest(container, "ip", "link", "show", "dev", interface, check=False)
        return {
            "exists": result.returncode == 0,
            "carrier": result.returncode == 0 and "LOWER_UP" in result.stdout,
        }

    def plan(self) -> dict:
        """Read host and Docker state without making mutations."""
        if self.system != "Linux":
            raise LinuxWiFiGuestProvisioningConflict("GNS3 Docker and mac80211_hwsim setup is Linux-only")
        if self.effective_uid == 0:
            raise LinuxWiFiGuestProvisioningConflict(
                "run protected lab provisioning as the normal Linux user, not as root"
            )
        host_plan = self.host_network.plan()
        self._ensure_docker_access()
        containers = self._find_containers()
        guest_state = {}
        for node, container in containers.items():
            state = self._inspect_container(container)
            interfaces = {}
            if state["running"] and state["pid"] > 0:
                for interface in self.REQUIRED_INTERFACES[node]:
                    interfaces[interface] = self._interface_state(container, interface)
            guest_state[node] = {**state, "interfaces": interfaces}
        missing_radios = int(not guest_state["hostapd-ap"]["interfaces"].get("wlan0", {}).get("exists", False))
        missing_radios += int(not guest_state["wifi-client"]["interfaces"].get("wlan0", {}).get("exists", False))
        module_loaded = self.module_path.exists()
        phys = self._host_phys() if module_loaded else []
        conflicts = []
        if not host_plan.get("can_apply"):
            conflicts.append({"code": "HOST_NETWORK_CONFLICT", "message": "virbr0 preflight has conflicts"})
        if module_loaded and len(phys) < missing_radios:
            conflicts.append({
                "code": "HWSIM_PHY_SHORTAGE",
                "message": (
                    f"{missing_radios} additional hwsim PHY(s) are needed but only "
                    f"{len(phys)} are visible; the module will not be unloaded/recycled"
                ),
            })
        return {
            "status": "PLANNED",
            "host_network": host_plan,
            "containers": guest_state,
            "hwsim": {
                "module_loaded": module_loaded,
                "host_phys": phys,
                "additional_radios_required": missing_radios,
                "will_load_module": not module_loaded and missing_radios > 0,
                "will_unload_module": False,
            },
            "conflicts": conflicts,
            "can_apply": not conflicts,
            "safety": {
                "deletes_gns3_resources": False,
                "stops_gns3_nodes": False,
                "unloads_hwsim": False,
                "rewires_ethernet": False,
                "requires_explicit_confirmation": True,
                "secrets_in_argv": False,
                "secrets_in_logs": False,
            },
        }

    def _wait_container(self, container: str, attempts: int = 30) -> dict:
        for index in range(attempts):
            state = self._inspect_container(container)
            if state["running"] and state["pid"] > 0:
                return state
            if index < attempts - 1:
                self.sleep(1)
        raise LinuxWiFiGuestProvisioningConflict(f"GNS3 Docker node did not start: {container}")

    def _wait_interface(self, container: str, interface: str, attempts: int = 40) -> None:
        for index in range(attempts):
            if self._interface_state(container, interface)["exists"]:
                return
            if index < attempts - 1:
                self.sleep(1)
        raise LinuxWiFiGuestProvisioningConflict(f"{container} is missing {interface}; inspect GNS3 cabling")

    def _wait_carrier(self, container: str, interface: str, attempts: int = 45) -> None:
        for index in range(attempts):
            self._guest(container, "ip", "link", "set", interface, "up", check=False)
            if self._interface_state(container, interface)["carrier"]:
                return
            if index < attempts - 1:
                self.sleep(1)
        raise LinuxWiFiGuestProvisioningConflict(
            f"{container} {interface} has no carrier; inspect the protected GNS3 link"
        )

    def _place_radio(self, phy: str, container: str, label: str) -> None:
        state = self._inspect_container(container)
        if not state["running"] or state["pid"] <= 0:
            raise LinuxWiFiGuestProvisioningConflict(f"{label} container is not running")
        self._run(["iw", "phy", phy, "set", "netns", str(state["pid"])], privileged=True, timeout=15)
        self.sleep(1)
        self._wait_interface(container, "wlan0")
        self._guest(container, "ip", "link", "set", "wlan0", "up")

    def _ensure_hwsim(self, ap: str, client: str) -> dict:
        ap_has = self._interface_state(ap, "wlan0")["exists"]
        client_has = self._interface_state(client, "wlan0")["exists"]
        if ap_has and client_has:
            self._guest(ap, "ip", "link", "set", "wlan0", "up")
            self._guest(client, "ip", "link", "set", "wlan0", "up")
            return {"ap_phy": "EXISTING", "client_phy": "EXISTING", "reused": True}
        needed = int(not ap_has) + int(not client_has)
        if not self.module_path.exists():
            self._run(["modprobe", "mac80211_hwsim", "radios=2"], privileged=True, timeout=30)
        phys = []
        for index in range(15):
            phys = self._host_phys()
            if len(phys) >= needed:
                break
            if index < 14:
                self.sleep(1)
        if len(phys) < needed:
            raise LinuxWiFiGuestProvisioningConflict(
                "not enough host-visible mac80211_hwsim PHYs; refusing to unload/recycle the module"
            )
        iterator = iter(phys)
        ap_phy = "EXISTING" if ap_has else next(iterator)
        client_phy = "EXISTING" if client_has else next(iterator)
        if not ap_has:
            self._place_radio(ap_phy, ap, "AP")
        if not client_has:
            self._place_radio(client_phy, client, "Client")
        return {"ap_phy": ap_phy, "client_phy": client_phy, "reused": False}

    def _install_ubuntu_packages(self, container: str, packages: Sequence[str]) -> None:
        missing = []
        for package in packages:
            if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]{0,80}", package):
                raise ValueError("package name is invalid")
            result = self._guest(
                container, "dpkg-query", "-W", "-f=" + "{Status}", package, check=False,
            )
            if result.returncode != 0 or "install ok installed" not in result.stdout:
                missing.append(package)
        if missing:
            self._guest(container, "apt-get", "-qq", "update", timeout=self.PACKAGE_TIMEOUT)
            self._guest(
                container, "apt-get", "-qq", "install", "-y", *missing,
                timeout=self.PACKAGE_TIMEOUT,
            )

    def _prepare_alpine_repositories(self, container: str) -> tuple[str, str, str]:
        release = self._guest(container, "cat", "/etc/alpine-release").stdout.strip()
        match = re.match(r"^(\d+\.\d+)", release)
        if not match:
            raise LinuxWiFiGuestProvisioningConflict("FRR container returned an invalid Alpine release")
        version = match.group(1)
        path = "/tmp/netregress-apk-repositories"
        for base in ("https://dl-cdn.alpinelinux.org", "https://archive.alpinelinux.org"):
            content = f"{base}/alpine/v{version}/main\n{base}/alpine/v{version}/community\n"
            self._write_guest_file(container, path, content)
            result = self._guest(
                container, "apk", "--repositories-file", path, "update",
                timeout=self.PACKAGE_TIMEOUT, check=False,
            )
            if result.returncode == 0:
                repos = content.splitlines()
                return path, repos[0], repos[1]
        raise LinuxWiFiGuestProvisioningError(
            "FRR Alpine repositories failed for both the CDN and archive mirrors"
        )

    def _apk_add(self, container: str, repo_a: str, repo_b: str, package: str) -> None:
        result = self._guest(
            container, "apk", "-q", "add", "--no-cache",
            "--repository", repo_a, "--repository", repo_b, package,
            timeout=self.PACKAGE_TIMEOUT, check=False,
        )
        if result.returncode != 0:
            raise LinuxWiFiGuestProvisioningError(f"FRR Alpine package could not be installed: {package}")

    def _ensure_frr_packages(self, container: str) -> None:
        commands = ("ip", "ss", "dnsmasq", "iperf3", "sshd", "ssh-keygen", "sudo", "ping", "pgrep", "pkill")
        missing = [
            command for command in commands
            if self._guest(container, "which", command, check=False).returncode != 0
        ]
        if not missing:
            return
        release = self._guest(container, "cat", "/etc/alpine-release").stdout.strip()
        match = re.match(r"^(\d+\.\d+)", release)
        if not match:
            raise LinuxWiFiGuestProvisioningConflict("FRR container returned an invalid Alpine release")
        path = "/tmp/netregress-apk-repositories"
        last_repos = None
        for base in ("https://dl-cdn.alpinelinux.org", "https://archive.alpinelinux.org"):
            repository_text = (
                f"{base}/alpine/v{match.group(1)}/main\n"
                f"{base}/alpine/v{match.group(1)}/community\n"
            )
            self._write_guest_file(container, path, repository_text)
            update = self._guest(
                container, "apk", "--repositories-file", path, "update",
                timeout=self.PACKAGE_TIMEOUT, check=False,
            )
            if update.returncode == 0:
                last_repos = repository_text.splitlines()
                break
        if not last_repos:
            raise LinuxWiFiGuestProvisioningError("FRR Alpine repositories failed for CDN and archive mirrors")
        packages = {
            "ip": "iproute2", "ss": "iproute2", "dnsmasq": "dnsmasq",
            "iperf3": "iperf3", "sshd": "openssh-server",
            "ssh-keygen": "openssh-keygen", "sudo": "sudo", "ping": "iputils",
        }
        for command in missing:
            if command in packages:
                self._apk_add(container, last_repos[0], last_repos[1], packages[command])
        if "pgrep" in missing or "pkill" in missing:
            result = self._guest(
                container, "apk", "--repositories-file", path,
                "-q", "add", "--no-cache", "procps-ng",
                timeout=self.PACKAGE_TIMEOUT, check=False,
            )
            if result.returncode != 0:
                self._guest(
                    container, "apk", "--repositories-file", path,
                    "-q", "add", "--no-cache", "procps",
                    timeout=self.PACKAGE_TIMEOUT,
                )
        for command in commands:
            if self._guest(container, "which", command, check=False).returncode != 0:
                raise LinuxWiFiGuestProvisioningError(f"FRR runtime command is missing: {command}")

    def _set_admin(self, container: str, os_id: str, password: str) -> None:
        if os_id == "ubuntu":
            if self._guest(container, "id", "admin", check=False).returncode != 0:
                self._guest(container, "useradd", "-m", "-s", "/bin/bash", "admin")
            self._guest(container, "usermod", "-aG", "sudo", "admin", check=False)
        elif os_id == "alpine":
            if self._guest(container, "id", "admin", check=False).returncode != 0:
                self._guest(container, "adduser", "-D", "-s", "/bin/sh", "admin")
            if self._guest(container, "id", "sshd", check=False).returncode != 0:
                shell = "/sbin/nologin"
                if self._guest(container, "test", "-x", shell, check=False).returncode != 0:
                    shell = "/bin/false"
                self._guest(
                    container, "adduser", "-S", "-D", "-H", "-h", "/var/empty",
                    "-s", shell, "sshd",
                )
            self._guest(container, "mkdir", "-p", "/var/empty")
        else:
            raise LinuxWiFiGuestProvisioningConflict(f"unsupported guest image on {container}")
        self._guest(container, "mkdir", "-p", "/etc/sudoers.d", "/etc/ssh", "/run/sshd", "/var/run/sshd")
        self._write_guest_file(
            container, "/etc/sudoers.d/netregress-admin",
            "admin ALL=(ALL) NOPASSWD: ALL\n",
        )
        self._guest(container, "chmod", "0440", "/etc/sudoers.d/netregress-admin")
        # Password is delivered through stdin, never passed as a process argument.
        self._guest(container, "chpasswd", input_text=f"admin:{password}\n", timeout=10)
        self._guest(container, "ssh-keygen", "-A", timeout=30)
        use_pam = "yes" if os_id == "ubuntu" else "no"
        config = (
            "Port 22\nAddressFamily inet\nListenAddress 0.0.0.0\n"
            "HostKey /etc/ssh/ssh_host_ed25519_key\nHostKey /etc/ssh/ssh_host_rsa_key\n"
            "PasswordAuthentication yes\nKbdInteractiveAuthentication no\n"
            "ChallengeResponseAuthentication no\nPermitRootLogin no\nAllowUsers admin\n"
            "PermitEmptyPasswords no\nPubkeyAuthentication yes\n"
            f"UsePAM {use_pam}\nPidFile /run/sshd.pid\nUseDNS no\n"
            "AllowAgentForwarding no\nX11Forwarding no\n"
        )
        self._write_guest_file(container, "/etc/ssh/sshd_config.netregress", config)
        self._guest(
            container, "/usr/sbin/sshd", "-t", "-f", "/etc/ssh/sshd_config.netregress",
            timeout=15,
        )
        self._guest(container, "pkill", "-TERM", "sshd", check=False)
        self.sleep(1)
        self._guest(container, "rm", "-f", "/run/sshd.pid")
        self._guest(
            container, "/usr/sbin/sshd", "-f", "/etc/ssh/sshd_config.netregress",
            "-E", "/var/log/netregress-sshd.log", timeout=15,
        )
        for index in range(10):
            sockets = self._guest(container, "ss", "-lnt", check=False).stdout
            if re.search(r":22\s", sockets):
                return
            if index < 9:
                self.sleep(1)
        raise LinuxWiFiGuestProvisioningConflict(f"SSH daemon did not listen on {container}:22")

    def _network_guest(self, container: str, interface: str, address: str) -> None:
        self._guest(container, "ip", "link", "set", interface, "up")
        self._guest(container, "ip", "addr", "replace", f"{address}/24", "dev", interface)
        self._guest(
            container, "ip", "route", "replace", "default",
            "via", self.LAB_GATEWAY, "dev", interface,
        )
        self._write_guest_file(container, "/etc/resolv.conf", "nameserver 8.8.8.8\n")

    def _configure_frr(self, container: str, password: str) -> None:
        self._guest(container, "ip", "link", "set", "eth1", "up")
        self._guest(container, "ip", "addr", "replace", f"{self.ROUTER_IP}/24", "dev", "eth1")
        self._guest(container, "ip", "route", "replace", "default", "via", self.LAB_GATEWAY, "dev", "eth1")
        self._write_guest_file(container, "/etc/resolv.conf", "nameserver 8.8.8.8\n")
        self._guest(container, "ping", "-c", "2", "-W", "3", self.LAB_GATEWAY, timeout=12)
        self._ensure_frr_packages(container)
        self._set_admin(container, "alpine", password)
        if self._guest(container, "pgrep", "-x", "iperf3", check=False).returncode != 0:
            self._guest(container, "iperf3", "-s", "-D", timeout=15)
        self._guest(container, "pgrep", "-x", "iperf3", timeout=10)

    def _configure_ap(self, container: str, *, ssid: str, psk: str, password: str) -> None:
        self._network_guest(container, "eth0", self.AP_IP)
        self._install_ubuntu_packages(
            container,
            ("hostapd", "openssh-server", "bridge-utils", "iw", "wpasupplicant",
             "sudo", "iproute2", "iputils-ping"),
        )
        self._set_admin(container, "ubuntu", password)
        self._guest(container, "rm", "-f", "/etc/profile.d/80-systemd-osc-context.sh")
        if self._guest(container, "ip", "link", "show", "dev", "br0", check=False).returncode != 0:
            self._guest(container, "ip", "link", "add", "br0", "type", "bridge")
        self._guest(container, "ip", "link", "set", "eth0", "master", "br0")
        self._guest(container, "ip", "link", "set", "br0", "up")
        self._guest(container, "ip", "addr", "flush", "dev", "eth0")
        self._guest(container, "ip", "addr", "replace", f"{self.AP_IP}/24", "dev", "br0")
        self._guest(container, "ip", "route", "replace", "default", "via", self.LAB_GATEWAY, "dev", "br0")
        config = (
            "interface=wlan0\nbridge=br0\ndriver=nl80211\n"
            f"ssid={ssid}\nhw_mode=g\nchannel=6\nwpa=2\nwpa_passphrase={psk}\n"
            "wpa_key_mgmt=WPA-PSK\nwpa_pairwise=CCMP\nrsn_pairwise=CCMP\n"
        )
        self._write_guest_file(container, "/etc/hostapd/hostapd.conf", config)
        self._guest(container, "pkill", "-9", "hostapd", check=False)
        self.sleep(1)
        self._guest(container, "ip", "link", "set", "wlan0", "down", check=False)
        self._guest(container, "iw", "dev", "wlan0", "set", "type", "managed", check=False)
        self._guest(container, "ip", "link", "set", "wlan0", "nomaster", check=False)
        self._guest(container, "ip", "addr", "flush", "dev", "wlan0", check=False)
        self._guest(container, "ip", "link", "set", "wlan0", "up")
        self._guest(container, "hostapd", "-B", "/etc/hostapd/hostapd.conf", timeout=20)
        info = self._guest(container, "iw", "dev", "wlan0", "info").stdout
        bridge = self._guest(container, "bridge", "link", check=False).stdout
        if f"ssid {ssid}" not in info or "master br0" not in bridge:
            raise LinuxWiFiGuestProvisioningConflict(
                "AP read-back did not confirm requested SSID and br0 bridge membership"
            )
        self._guest(container, "ping", "-c", "2", "-W", "3", self.ROUTER_IP, timeout=12)

    def _configure_monitor(self, container: str, password: str) -> None:
        self._network_guest(container, "eth0", self.MONITOR_IP)
        self._install_ubuntu_packages(
            container, ("openssh-server", "sudo", "tcpdump", "iproute2", "iputils-ping"),
        )
        self._set_admin(container, "ubuntu", password)
        self._guest(container, "rm", "-f", "/etc/profile.d/80-systemd-osc-context.sh")
        self._guest(container, "ping", "-c", "2", "-W", "3", self.ROUTER_IP, timeout=12)
        if (
            self._guest(container, "tcpdump", "--version", check=False).returncode != 0
            or self._guest(container, "tcpdump", "-D", check=False).returncode != 0
        ):
            raise LinuxWiFiGuestProvisioningConflict("monitor guest is not ready for packet capture")

    @staticmethod
    def _wpa_quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _wpa_config(self, ssid: str, psk: str) -> str:
        return (
            "ctrl_interface=DIR=/run/wpa_supplicant GROUP=admin\n"
            "update_config=1\ncountry=IN\np2p_disabled=1\n\nnetwork={\n"
            f"    ssid={self._wpa_quote(ssid)}\n    psk={self._wpa_quote(psk)}\n"
            "    key_mgmt=WPA-PSK\n}\n"
        )

    def _wait_wifi_association(self, container: str, ssid: str, attempts: int = 30) -> str:
        for index in range(attempts):
            control = self._guest(container, "test", "-S", "/run/wpa_supplicant/wlan0", check=False)
            status = self._guest(container, "wpa_cli", "-i", "wlan0", "status", check=False).stdout
            link = self._guest(container, "iw", "dev", "wlan0", "link", check=False).stdout
            if (
                control.returncode == 0
                and "wpa_state=COMPLETED" in status
                and ("SSID: " + ssid) in link
                and re.search(r"(?m)^key_mgmt=(?:WPA2-PSK|WPA-PSK)$", status)
            ):
                mac = self._guest(container, "cat", "/sys/class/net/wlan0/address").stdout.strip().lower()
                if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
                    raise LinuxWiFiGuestProvisioningError("client returned an invalid WLAN MAC address")
                return mac
            if index < attempts - 1:
                self.sleep(1)
        raise LinuxWiFiGuestProvisioningConflict(
            f"client did not complete a verified WPA2 association to SSID {ssid}"
        )

    def _configure_client_wifi(
        self, container: str, *, ssid: str, psk: str, password: str,
    ) -> str:
        self._network_guest(container, "eth0", "192.168.122.250")
        self._install_ubuntu_packages(
            container,
            ("iw", "wpasupplicant", "openssh-server", "iproute2", "iperf3",
             "bind9-dnsutils", "isc-dhcp-client", "iptables", "sudo", "iputils-ping"),
        )
        self._set_admin(container, "ubuntu", password)
        if self._guest(container, "which", "iptables", check=False).returncode != 0:
            raise LinuxWiFiGuestProvisioningConflict("client iptables is required for DNS fault injection")
        self._guest(container, "rm", "-f", "/etc/profile.d/80-systemd-osc-context.sh")
        self._write_guest_file(container, "/etc/wpa_supplicant.conf", self._wpa_config(ssid, psk))
        self._guest(container, "pkill", "-9", "wpa_supplicant", check=False)
        self.sleep(1)
        self._guest(container, "rm", "-rf", "/run/wpa_supplicant")
        self._guest(container, "mkdir", "-p", "/run/wpa_supplicant")
        self._guest(container, "ip", "link", "set", "wlan0", "down", check=False)
        self._guest(container, "iw", "dev", "wlan0", "set", "type", "managed", check=False)
        self._guest(container, "ip", "addr", "flush", "dev", "wlan0", check=False)
        self._guest(container, "ip", "link", "set", "wlan0", "up")
        self._guest(
            container, "wpa_supplicant", "-B", "-i", "wlan0",
            "-c", "/etc/wpa_supplicant.conf", "-D", "nl80211", timeout=20,
        )
        return self._wait_wifi_association(container, ssid)

    def _configure_frr_dhcp(self, container: str, client_mac: str) -> dict:
        if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", client_mac):
            raise ValueError("client Wi-Fi MAC address is invalid")
        config = (
            "interface=eth1\nbind-interfaces\nexcept-interface=lo\n"
            "dhcp-range=192.168.122.100,192.168.122.200,255.255.255.0,12h\n"
            f"dhcp-option=3,{self.LAB_GATEWAY}\ndhcp-option=6,8.8.8.8\n"
            f"dhcp-host={client_mac},{self.CLIENT_WIFI_IP}\n"
        )
        self._guest(container, "mkdir", "-p", "/etc/dnsmasq.d")
        self._write_guest_file(container, "/etc/dnsmasq.d/lab.conf", config)
        self._guest(container, "dnsmasq", "--test", "--conf-file=/etc/dnsmasq.d/lab.conf")
        self._guest(container, "pkill", "-TERM", "dnsmasq", check=False)
        self.sleep(1)
        if self._guest(container, "pgrep", "dnsmasq", check=False).returncode == 0:
            self._guest(container, "pkill", "-9", "dnsmasq", check=False)
            self.sleep(1)
        self._guest(container, "dnsmasq", "--conf-file=/etc/dnsmasq.d/lab.conf", timeout=20)
        self._guest(container, "pgrep", "dnsmasq", timeout=10)
        return {"interface": "eth1", "client_mac": client_mac, "reserved_ip": self.CLIENT_WIFI_IP}

    def _configure_client_routes(self, container: str) -> dict:
        self._guest(container, "dhclient", "-r", "wlan0", check=False, timeout=20)
        self._guest(container, "dhclient", "-v", "wlan0", timeout=60)
        self._guest(container, "ip", "route", "replace", "default", "via", self.LAB_GATEWAY, "dev", "wlan0")
        self._guest(container, "ip", "link", "set", "eth1", "up")
        self._guest(container, "ip", "addr", "replace", f"{self.CLIENT_MANAGEMENT_IP}/24", "dev", "eth1")
        self._guest(
            container, "ip", "route", "replace",
            f"{self.MANAGEMENT_GATEWAY}/32", "dev", "eth1",
        )
        self._guest(container, "ip", "addr", "flush", "dev", "eth0")
        self._guest(container, "ip", "route", "del", "default", "dev", "eth0", check=False)
        self._guest(container, "ip", "route", "replace", "default", "via", self.LAB_GATEWAY, "dev", "wlan0")
        address = self._guest(container, "ip", "-4", "-o", "addr", "show", "dev", "wlan0").stdout
        if not re.search(r"\binet\s+" + re.escape(self.CLIENT_WIFI_IP) + r"/24\b", address):
            raise LinuxWiFiGuestProvisioningConflict("client missed its deterministic Wi-Fi DHCP reservation")
        management = self._guest(container, "ip", "-4", "-o", "addr", "show", "dev", "eth1").stdout
        if not re.search(r"\binet\s+" + re.escape(self.CLIENT_MANAGEMENT_IP) + r"/24\b", management):
            raise LinuxWiFiGuestProvisioningConflict("client management address read-back failed")
        ethernet = self._guest(container, "ip", "-4", "-o", "addr", "show", "dev", "eth0").stdout
        if re.search(r"\binet\s+", ethernet):
            raise LinuxWiFiGuestProvisioningConflict("client eth0 retained an IPv4 address after isolation")
        return {
            "wifi_interface": "wlan0",
            "wifi_address": self.CLIENT_WIFI_IP,
            "management_interface": "eth1",
            "management_address": self.CLIENT_MANAGEMENT_IP,
        }

    def _verify_network(self, containers: Mapping[str, str], ssid: str) -> dict:
        client = containers["wifi-client"]
        link = self._guest(client, "iw", "dev", "wlan0", "link").stdout
        if "SSID: " + ssid not in link:
            raise LinuxWiFiGuestProvisioningConflict("final client SSID read-back failed")
        self._guest(client, "ping", "-c", "3", "-W", "3", self.ROUTER_IP, timeout=20)
        self._guest(client, "ping", "-c", "2", "-W", "3", self.LAB_GATEWAY, timeout=15)
        dns = self._guest(client, "nslookup", "google.com", check=False, timeout=20)
        if dns.returncode != 0:
            self._guest(client, "nslookup", "google.com", "8.8.8.8", timeout=20)
        route = self._guest(client, "ip", "route").stdout
        expected = (
            r"(?m)^default\s+via\s+" + re.escape(self.LAB_GATEWAY)
            + r"\s+dev\s+wlan0(?:\s|$)"
        )
        if not re.search(expected, route):
            raise LinuxWiFiGuestProvisioningConflict("client default route is not via wlan0 and the lab gateway")
        return {
            "ssid": ssid,
            "client_wifi_address": self.CLIENT_WIFI_IP,
            "client_management_address": self.CLIENT_MANAGEMENT_IP,
            "default_route": f"via {self.LAB_GATEWAY} dev wlan0",
            "dns": "verified",
        }

    @staticmethod
    def _netmiko_ssh_probe(host: str, username: str, password: str) -> None:
        from netmiko import ConnectHandler
        with ConnectHandler(
            device_type="linux", host=host, username=username, password=password,
            port=22, conn_timeout=10, auth_timeout=10, banner_timeout=10, fast_cli=False,
        ) as connection:
            output = connection.send_command("echo SSH_OK", read_timeout=10).strip()
            sudo_output = connection.send_command(
                "sudo -n true && echo SUDO_OK", read_timeout=10,
            ).strip()
            if output != "SSH_OK" or sudo_output != "SUDO_OK":
                raise LinuxWiFiGuestProvisioningConflict(f"SSH or sudo validation failed for {host}")

    def _verify_ssh(self, passwords: Mapping[str, str]) -> dict:
        targets = (
            (self.ROUTER_IP, passwords["router1"]),
            (self.AP_IP, passwords["ap"]),
            (self.CLIENT_MANAGEMENT_IP, passwords["client"]),
            (self.MONITOR_IP, passwords["monitor"]),
        )
        verified = []
        for host, password in targets:
            last_error = None
            for attempt in range(20):
                try:
                    self.ssh_probe(host, "admin", password)
                    verified.append(host)
                    break
                except Exception as exc:
                    last_error = type(exc).__name__
                    if attempt < 19:
                        self.sleep(1)
            else:
                raise LinuxWiFiGuestProvisioningConflict(
                    f"management SSH validation failed for {host} ({last_error or 'no response'})"
                )
        return {"verified_hosts": verified, "sudo": "verified"}

    def apply(
        self,
        *,
        lab_id: str,
        actor: str,
        passwords: Mapping[str, str],
        ssid: str = "TestNet_5G",
        confirmed: bool,
    ) -> dict:
        if confirmed is not True:
            raise LinuxWiFiGuestProvisioningConflict(
                "explicit operator confirmation is required before protected guest provisioning"
            )
        actor = self._actor(actor)
        if self.resource_lock_manager is None:
            raise LinuxWiFiGuestProvisioningError(
                "a shared Lab resource lock manager is required for guest provisioning"
            )
        secret_values = self._validate_passwords(passwords)
        self._validate_wifi(ssid, secret_values["wifi_psk"])
        plan = self.plan()
        if not plan["can_apply"]:
            raise LinuxWiFiGuestProvisioningConflict(
                "protected lab preflight has conflicts; no host or guest mutations were started"
            )
        lease = self.resource_lock_manager.acquire(
            "lab:" + str(lab_id),
            "linux-wifi-guest-setup:" + actor[:80],
            timeout=0.0,
            lease_seconds=900.0,
        )
        completed: list[str] = []
        try:
            host_result = self.host_network.apply(confirmed=True, actor=actor)
            completed.append("host_network")
            containers = {node: state["name"] for node, state in plan["containers"].items()}
            for node, container in containers.items():
                self._wait_container(container)
                for interface in self.REQUIRED_INTERFACES[node]:
                    self._wait_interface(container, interface)
                    self._wait_carrier(container, interface)
            completed.append("ethernet_interfaces")
            radio = self._ensure_hwsim(containers["hostapd-ap"], containers["wifi-client"])
            completed.append("hwsim_radios")
            self._configure_frr(containers["frr-router"], secret_values["router1"])
            completed.append("frr_runtime_and_iperf3")
            self._configure_ap(
                containers["hostapd-ap"], ssid=ssid,
                psk=secret_values["wifi_psk"], password=secret_values["ap"],
            )
            completed.append("access_point_and_hostapd")
            self._configure_monitor(containers["monitor"], secret_values["monitor"])
            completed.append("monitor_capture_tools")
            wifi_mac = self._configure_client_wifi(
                containers["wifi-client"], ssid=ssid,
                psk=secret_values["wifi_psk"], password=secret_values["client"],
            )
            completed.append("client_wpa_association")
            dhcp = self._configure_frr_dhcp(containers["frr-router"], wifi_mac)
            completed.append("frr_dhcp_dns")
            client = self._configure_client_routes(containers["wifi-client"])
            completed.append("client_dhcp_and_management")
            network = self._verify_network(containers, ssid)
            completed.append("end_to_end_wifi_dns_routes")
            ssh = self._verify_ssh(secret_values)
            completed.append("management_ssh")
            return {
                "status": "APPLIED",
                "lab_id": str(lab_id),
                "host_network": host_result,
                "containers": containers,
                "radio": radio,
                "dhcp": dhcp,
                "client": client,
                "network": network,
                "ssh": ssh,
                "completed_steps": completed,
                "safety": {
                    "stopped_gns3_nodes": False,
                    "deleted_gns3_resources": False,
                    "unloaded_hwsim": False,
                    "secrets_in_argv": False,
                    "secrets_in_logs": False,
                },
            }
        except Exception as exc:
            if completed:
                raise LinuxWiFiGuestProvisioningUncertain(
                    "protected guest provisioning stopped after partial changes; inspect host, GNS3 and guest state before retrying",
                    completed_steps=completed,
                ) from exc
            raise
        finally:
            lease.release()
