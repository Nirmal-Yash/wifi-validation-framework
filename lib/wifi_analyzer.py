"""Compatibility wrappers over the typed protocol evidence service."""

from pathlib import Path

from lib.services.protocol_evidence import (
    SCAPY_AVAILABLE,
    ProtocolEvidenceService,
)


def check_scapy():
    if not SCAPY_AVAILABLE:
        raise ImportError(
            "Scapy is required for wifi_analyzer. Install via 'pip install scapy'"
        )


def analyze_beacon(pcap_path, expected_ssid=None):
    return ProtocolEvidenceService().analyze_beacon(
        pcap_path,
        expected_ssid=expected_ssid,
    ).as_dict()


def analyze_dhcp_sequence(pcap_path):
    return ProtocolEvidenceService().analyze_dhcp(pcap_path).as_dict()


def analyze_eapol_handshake(pcap_path):
    return ProtocolEvidenceService().analyze_eapol(pcap_path).as_dict()


def analyze_dns_traffic(pcap_path, expected_domain=None):
    return ProtocolEvidenceService().analyze_dns(
        pcap_path,
        expected_domain=expected_domain,
    ).as_dict()
