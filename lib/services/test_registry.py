from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Mapping

from lib.domain import ArtifactType, Criticality, Severity


@dataclass(frozen=True, slots=True)
class TestDefinition:
    test_id: str
    node_id: str
    version: str
    category: str
    protocol: str
    severity: Severity
    criticality: Criticality
    equipment: tuple[str, ...] = ()
    direction: str = "N/A"
    requires: tuple[str, ...] = ()
    destructive: bool = False
    estimated_duration_sec: int = 0
    capabilities: tuple[str, ...] = ()
    metric_definitions: Mapping[str, str] = field(default_factory=dict)
    threshold_definitions: Mapping[str, str] = field(default_factory=dict)
    evidence_requirements: tuple[ArtifactType, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("test_id", self.test_id),
            ("node_id", self.node_id),
            ("version", self.version),
            ("category", self.category),
            ("protocol", self.protocol),
            ("direction", self.direction),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.estimated_duration_sec < 0:
            raise ValueError("estimated_duration_sec cannot be negative")
        if len(set(self.requires)) != len(self.requires):
            raise ValueError("requires must not contain duplicates")


class TestRegistry:
    """Semantic test metadata registry mapped 1:1 to stable pytest node IDs."""

    def __init__(self, definitions: tuple[TestDefinition, ...] = ()) -> None:
        self._by_test_id: dict[str, TestDefinition] = {}
        self._by_node_id: dict[str, TestDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: TestDefinition) -> None:
        if definition.test_id in self._by_test_id:
            raise ValueError(f"duplicate semantic test id: {definition.test_id}")
        if definition.node_id in self._by_node_id:
            raise ValueError(f"duplicate pytest node id: {definition.node_id}")
        self._by_test_id[definition.test_id] = definition
        self._by_node_id[definition.node_id] = definition

    def get(self, test_id: str) -> TestDefinition:
        try:
            return self._by_test_id[test_id]
        except KeyError as exc:
            raise KeyError(f"unknown semantic test id: {test_id}") from exc

    def resolve(self, node_id: str) -> TestDefinition:
        try:
            return self._by_node_id[node_id]
        except KeyError as exc:
            raise KeyError(f"pytest node is not registered: {node_id}") from exc

    def resolve_or_fallback(self, node_id: str) -> TestDefinition:
        try:
            return self.resolve(node_id)
        except KeyError:
            slug = re.sub(r"[^a-zA-Z0-9]+", ".", node_id).strip(".").lower()
            return TestDefinition(
                test_id=f"internal.{slug}",
                node_id=node_id,
                version="1.0",
                category="internal",
                protocol="internal",
                severity=Severity.LOW,
                criticality=Criticality.INFORMATIONAL,
                estimated_duration_sec=0,
            )

    def definitions(self) -> tuple[TestDefinition, ...]:
        return tuple(self._by_test_id.values())

    def version_map(self, node_ids: list[str] | tuple[str, ...]) -> dict[str, str]:
        return {
            node_id: self.resolve_or_fallback(node_id).version
            for node_id in node_ids
        }

    @classmethod
    def default(cls) -> "TestRegistry":
        return cls(
            (
                TestDefinition(
                    "wifi.ssid.visibility",
                    "tests/test_ssid.py::test_ssid_visible",
                    "1.0", "Smoke", "802.11",
                    Severity.MEDIUM, Criticality.BLOCKING,
                    ("ap_host", "client_vm"), "AP→client",
                    destructive=False, estimated_duration_sec=15,
                    capabilities=("wifi_scan",),
                    evidence_requirements=(),
                ),
                TestDefinition(
                    "wifi.auth.wpa2",
                    "tests/test_auth.py::test_wpa2_authentication",
                    "1.0", "Standard Regression", "WPA2/EAPOL",
                    Severity.HIGH, Criticality.BLOCKING,
                    ("ap_host", "client_vm"), "client→AP",
                    requires=("wifi.ssid.visibility",),
                    destructive=False, estimated_duration_sec=20,
                    capabilities=("wpa2_psk",),
                    evidence_requirements=(),
                ),
                TestDefinition(
                    "wifi.dhcp.lease",
                    "tests/test_dhcp.py::test_dhcp_lease_assigned",
                    "1.0", "Smoke", "DHCP",
                    Severity.HIGH, Criticality.BLOCKING,
                    ("router", "client_vm"), "router→client",
                    requires=("wifi.auth.wpa2",),
                    destructive=False, estimated_duration_sec=20,
                    capabilities=("dhcp",),
                    metric_definitions={"lease_age": "seconds"},
                ),
                TestDefinition(
                    "wifi.dhcp.timeout",
                    "tests/test_dhcp.py::test_dhcp_within_timeout",
                    "1.0", "Smoke", "DHCP",
                    Severity.HIGH, Criticality.BLOCKING,
                    ("router", "client_vm"), "client↔router",
                    requires=("wifi.auth.wpa2",),
                    destructive=False, estimated_duration_sec=20,
                    capabilities=("dhcp",),
                    metric_definitions={"dhcp_duration": "seconds"},
                    threshold_definitions={"max_dhcp_duration": "thresholds.dhcp_timeout_sec"},
                ),
                TestDefinition(
                    "wifi.dns.resolution",
                    "tests/test_dns.py::test_dns_resolution",
                    "1.0", "Smoke", "DNS",
                    Severity.HIGH, Criticality.BLOCKING,
                    ("router", "client_vm"), "client→resolver",
                    requires=("wifi.dhcp.lease",),
                    destructive=False, estimated_duration_sec=15,
                    capabilities=("dns",),
                ),
                TestDefinition(
                    "wifi.ping.success",
                    "tests/test_ping.py::test_ping_success",
                    "1.0", "Performance", "ICMP",
                    Severity.MEDIUM, Criticality.BLOCKING,
                    ("router", "client_vm"), "client→router",
                    requires=("wifi.dhcp.lease",),
                    destructive=False, estimated_duration_sec=15,
                    capabilities=("icmp",),
                    metric_definitions={"ping_rtt": "ms"},
                ),
                TestDefinition(
                    "wifi.latency.threshold",
                    "tests/test_ping.py::test_latency_within_threshold",
                    "1.0", "Performance", "ICMP",
                    Severity.MEDIUM, Criticality.BLOCKING,
                    ("router", "client_vm"), "client→router",
                    requires=("wifi.ping.success",),
                    destructive=False, estimated_duration_sec=20,
                    capabilities=("icmp",),
                    metric_definitions={"latency": "ms"},
                    threshold_definitions={"max_latency": "thresholds.max_latency_ms"},
                ),
                TestDefinition(
                    "wifi.packet_loss.threshold",
                    "tests/test_ping.py::test_packet_loss_within_threshold",
                    "1.0", "Performance", "ICMP",
                    Severity.MEDIUM, Criticality.BLOCKING,
                    ("router", "client_vm"), "client→router",
                    requires=("wifi.ping.success",),
                    destructive=False, estimated_duration_sec=20,
                    capabilities=("icmp",),
                    metric_definitions={"packet_loss": "percent"},
                    threshold_definitions={"max_packet_loss": "thresholds.max_packet_loss_pct"},
                ),
                TestDefinition(
                    "wifi.throughput.minimum",
                    "tests/test_throughput.py::test_throughput_meets_minimum",
                    "1.0", "Performance", "iperf3",
                    Severity.HIGH, Criticality.BLOCKING,
                    ("router", "client_vm"), "client→router",
                    requires=("wifi.dhcp.lease",),
                    destructive=False, estimated_duration_sec=30,
                    capabilities=("iperf3",),
                    metric_definitions={"throughput": "Mbps"},
                    threshold_definitions={"min_throughput": "thresholds.min_throughput_mbps"},
                ),
                TestDefinition(
                    "wifi.recovery.link_flap",
                    "tests/test_fault_injection.py::test_fault_injection_link_down_up",
                    "1.0", "Recovery", "802.11/link",
                    Severity.HIGH, Criticality.BLOCKING,
                    ("client_vm",), "client↔router",
                    requires=("wifi.ping.success",),
                    destructive=True, estimated_duration_sec=45,
                    capabilities=("link_control",),
                    evidence_requirements=(),
                ),
                TestDefinition(
                    "wifi.dhcp.capture",
                    "tests/test_packet_capture.py::test_pcap_contains_dhcp_packets",
                    "1.0", "Standard Regression", "DHCP/PCAP",
                    Severity.HIGH, Criticality.BLOCKING,
                    ("ap_host", "client_vm"), "client↔AP",
                    requires=("wifi.dhcp.lease",),
                    destructive=False, estimated_duration_sec=45,
                    capabilities=("pcap_capture", "sftp"),
                    metric_definitions={"dhcp_packets": "packets"},
                    evidence_requirements=(ArtifactType.PCAP,),
                ),
            )
        )
