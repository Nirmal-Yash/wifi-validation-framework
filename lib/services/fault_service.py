from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from .command_runner import CommandRunner


@dataclass(frozen=True, slots=True)
class FaultDefinition:
    fault_id: str
    target: str
    apply_commands: tuple[str, ...]
    restore_commands: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        for name, value in (
            ("fault_id", self.fault_id),
            ("target", self.target),
            ("description", self.description),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not self.apply_commands:
            raise ValueError("apply_commands must not be empty")
        if not self.restore_commands:
            raise ValueError("restore_commands must not be empty")


class FaultService:
    """Run explicit lab faults through the secured CommandRunner boundary."""

    def __init__(self, command_runner: CommandRunner) -> None:
        self.command_runner = command_runner

    def apply(self, fault: FaultDefinition) -> None:
        self._execute(fault, fault.apply_commands, phase="apply")

    def restore(self, fault: FaultDefinition) -> None:
        first_error: Exception | None = None
        for command in fault.restore_commands:
            try:
                result = self.command_runner.execute_shell(
                    fault.target,
                    command,
                    command_category=f"fault.restore.{fault.fault_id}",
                    idempotent=True,
                    privilege_mode="SUDO",
                )
                if not result.transport_succeeded:
                    raise RuntimeError(
                        f"fault restore transport failed for {fault.fault_id}: "
                        f"{result.safe_display_command}: {result.transport_error}"
                    )
            except Exception as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    @contextmanager
    def context(self, fault: FaultDefinition) -> Iterator[None]:
        try:
            self.apply(fault)
            yield
        finally:
            # Restoration is unconditional so a partially applied fault cannot
            # leave the shared lab in a mutated state.
            self.restore(fault)

    def _execute(
        self,
        fault: FaultDefinition,
        commands: tuple[str, ...],
        *,
        phase: str,
    ) -> None:
        for command in commands:
            result = self.command_runner.execute_shell(
                fault.target,
                command,
                command_category=f"fault.{phase}.{fault.fault_id}",
                idempotent=False,
                privilege_mode="SUDO",
            )
            if not result.transport_succeeded:
                raise RuntimeError(
                    f"fault command transport failed for {fault.fault_id}: "
                    f"{result.safe_display_command}: {result.transport_error}"
                )

    @staticmethod
    def wifi_link_flap(interface: str = "wlan0") -> FaultDefinition:
        return FaultDefinition(
            fault_id="wifi.link_flap",
            target="client_vm",
            apply_commands=(f"sudo ip link set {interface} down",),
            restore_commands=(
                f"sudo ip link set {interface} up",
                "sudo dhclient -1 -timeout 10 wlan0 2>/dev/null || true",
            ),
            description="Disable the client WiFi interface and restore it with DHCP.",
        )

    @staticmethod
    def wifi_disconnect(interface: str = "wlan0", network_id: str = "0") -> FaultDefinition:
        return FaultDefinition(
            fault_id="wifi.disconnect",
            target="client_vm",
            apply_commands=(
                f"sudo wpa_cli -i {interface} disable_network {network_id}",
                f"sudo wpa_cli -i {interface} disconnect",
            ),
            restore_commands=(
                f"sudo wpa_cli -i {interface} enable_network {network_id}",
                f"sudo wpa_cli -i {interface} reconnect",
            ),
            description="Disable the configured WiFi network and restore association.",
        )

    @staticmethod
    def wrong_psk(
        *,
        interface: str,
        network_id: str,
        wrong_psk: str,
        correct_psk: str,
    ) -> FaultDefinition:
        import shlex

        wrong = shlex.quote(f'"{wrong_psk}"')
        correct = shlex.quote(f'"{correct_psk}"')
        return FaultDefinition(
            fault_id="wifi.wrong_psk",
            target="client_vm",
            apply_commands=(
                f"sudo wpa_cli -i {interface} disconnect",
                f"sudo wpa_cli -i {interface} set_network {network_id} psk {wrong}",
                f"sudo wpa_cli -i {interface} enable_network {network_id}",
                f"sudo wpa_cli -i {interface} reconnect",
            ),
            restore_commands=(
                f"sudo wpa_cli -i {interface} set_network {network_id} psk {correct}",
                f"sudo wpa_cli -i {interface} enable_network {network_id}",
                f"sudo wpa_cli -i {interface} reconnect",
            ),
            description="Replace the active WPA2-PSK at runtime, prove authentication failure, then restore it.",
        )

    @staticmethod
    def dns_block() -> FaultDefinition:
        return FaultDefinition(
            fault_id="dns.block",
            target="client_vm",
            apply_commands=(
                "sudo iptables -I OUTPUT -p udp --dport 53 -j DROP",
                "sudo iptables -I OUTPUT -p tcp --dport 53 -j DROP",
            ),
            restore_commands=(
                "sudo iptables -D OUTPUT -p udp --dport 53 -j DROP 2>/dev/null || true",
                "sudo iptables -D OUTPUT -p tcp --dport 53 -j DROP 2>/dev/null || true",
            ),
            description="Block client DNS UDP queries and remove the rule during recovery.",
        )

    @staticmethod
    def dhcp_server_stop() -> FaultDefinition:
        return FaultDefinition(
            fault_id="dhcp.server_stop",
            target="router1",
            apply_commands=(
                "sudo systemctl stop dnsmasq 2>/dev/null || sudo pkill -TERM dnsmasq 2>/dev/null || true",
            ),
            restore_commands=(
                "sudo systemctl start dnsmasq 2>/dev/null || sudo dnsmasq --conf-file=/etc/dnsmasq.d/lab.conf 2>/dev/null || true",
            ),
            description="Stop the real FRR dnsmasq DHCP service and restore it.",
        )

    @staticmethod
    def ap_restart() -> FaultDefinition:
        return FaultDefinition(
            fault_id="wifi.ap_restart",
            target="ap_host",
            apply_commands=(
                "sudo pkill -TERM hostapd 2>/dev/null || true",
            ),
            restore_commands=(
                "sudo hostapd -B /etc/hostapd/hostapd.conf",
            ),
            description="Stop the real AP hostapd service/process and restore the configured AP.",
        )

    @staticmethod
    def client_wifi_restart() -> FaultDefinition:
        return FaultDefinition(
            fault_id="wifi.client_restart",
            target="client_vm",
            apply_commands=(
                "sudo wpa_cli -i wlan0 terminate 2>/dev/null || sudo pkill -TERM wpa_supplicant 2>/dev/null || true",
            ),
            restore_commands=(
                "sudo wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant.conf -D nl80211",
                "sudo wpa_cli -i wlan0 reconnect 2>/dev/null || true",
            ),
            description="Restart the client WiFi supplicant while preserving the management path.",
        )
