"""WiFi & Protocol Frame Analyzer using Scapy.

Provides frame-level validation for:
- 802.11 Beacon frames and Information Elements (SSID, RSN/WPA2, Channel)
- DHCP 4-way DORA sequence (Discover, Offer, Request, Ack)
- WPA2 EAPOL 4-way handshake
- DNS Query/Response traffic
"""

from pathlib import Path

try:
    from scapy.all import (
        DHCP,
        DNS,
        EAPOL,
        IP,
        UDP,
        BOOTP,
        Dot11,
        Dot11Beacon,
        Dot11Elt,
        Ether,
        rdpcap,
        wrpcap,
    )
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False


def check_scapy():
    if not SCAPY_AVAILABLE:
        raise ImportError("Scapy is required for wifi_analyzer. Install via 'pip install scapy'")


def analyze_beacon(pcap_path, expected_ssid=None):
    """Analyze 802.11 Beacon frames in pcap."""
    check_scapy()
    path = Path(pcap_path)
    if not path.exists():
        raise FileNotFoundError(f"PCAP file not found: {pcap_path}")

    pkts = rdpcap(str(path))
    beacons = [p for p in pkts if p.haslayer(Dot11Beacon)]

    if not beacons:
        return {
            "found": False,
            "beacon_count": 0,
            "ssid": None,
            "has_rsn": False,
        }

    first_beacon = beacons[0]
    ssid = None
    has_rsn = False
    channel = None

    # Iterate through Information Elements (Dot11Elt)
    elt = first_beacon.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 0:  # SSID parameter set
            ssid = elt.info.decode("utf-8", errors="replace")
        elif elt.ID == 3:  # DS Parameter Set (Channel)
            if len(elt.info) >= 1:
                channel = int(elt.info[0])
        elif elt.ID == 48:  # RSN Information Element (WPA2/WPA3)
            has_rsn = True
        elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None

    matches_ssid = True if expected_ssid is None else (ssid == expected_ssid)

    return {
        "found": True,
        "beacon_count": len(beacons),
        "ssid": ssid,
        "channel": channel,
        "has_rsn": has_rsn,
        "matches_expected_ssid": matches_ssid,
    }


def analyze_dhcp_sequence(pcap_path):
    """Verify DHCP DORA (Discover, Offer, Request, Ack) sequence in pcap."""
    check_scapy()
    path = Path(pcap_path)
    if not path.exists():
        raise FileNotFoundError(f"PCAP file not found: {pcap_path}")

    pkts = rdpcap(str(path))
    dhcp_pkts = [p for p in pkts if p.haslayer(DHCP)]

    message_counts = {
        "DISCOVER": 0,
        "OFFER": 0,
        "REQUEST": 0,
        "ACK": 0,
        "NAK": 0,
    }
    type_map = {1: "DISCOVER", 2: "OFFER", 3: "REQUEST", 5: "ACK", 6: "NAK"}

    for p in dhcp_pkts:
        for opt in p[DHCP].options:
            if isinstance(opt, tuple) and opt[0] == "message-type":
                m_type = type_map.get(opt[1])
                if m_type in message_counts:
                    message_counts[m_type] += 1

    total_dhcp = sum(message_counts.values())
    has_dora = (
        message_counts["DISCOVER"] >= 1
        and message_counts["OFFER"] >= 1
        and message_counts["REQUEST"] >= 1
        and message_counts["ACK"] >= 1
    )

    return {
        "total_packets": total_dhcp,
        "message_counts": message_counts,
        "has_dora": has_dora,
        "has_lease_acquired": message_counts["ACK"] >= 1,
    }


def analyze_eapol_handshake(pcap_path):
    """Verify WPA2/WPA3 4-way handshake EAPOL key exchange frames."""
    check_scapy()
    path = Path(pcap_path)
    if not path.exists():
        raise FileNotFoundError(f"PCAP file not found: {pcap_path}")

    pkts = rdpcap(str(path))
    eapol_pkts = [p for p in pkts if p.haslayer(EAPOL)]

    return {
        "total_eapol_packets": len(eapol_pkts),
        "handshake_completed": len(eapol_pkts) >= 4,
    }


def analyze_dns_traffic(pcap_path, expected_domain=None):
    """Verify DNS queries and responses in pcap."""
    check_scapy()
    path = Path(pcap_path)
    if not path.exists():
        raise FileNotFoundError(f"PCAP file not found: {pcap_path}")

    pkts = rdpcap(str(path))
    dns_pkts = [p for p in pkts if p.haslayer(DNS)]

    queries = 0
    responses = 0
    resolved_ips = []

    for p in dns_pkts:
        dns_layer = p[DNS]
        if dns_layer.qr == 0:  # Query
            queries += 1
        elif dns_layer.qr == 1:  # Response
            responses += 1
            if dns_layer.an:
                for i in range(dns_layer.ancount):
                    an = dns_layer.an[i]
                    if hasattr(an, "rdata"):
                        resolved_ips.append(str(an.rdata))

    return {
        "total_dns_packets": len(dns_pkts),
        "query_count": queries,
        "response_count": responses,
        "resolved_ips": resolved_ips,
    }


def generate_synthetic_dhcp_pcap(output_path):
    """Generate a clean synthetic DHCP pcap for offline verification and testing."""
    check_scapy()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1. DHCP Discover
    p_disc = (
        Ether(src="00:11:22:33:44:55", dst="ff:ff:ff:ff:ff:ff")
        / IP(src="0.0.0.0", dst="255.255.255.255")
        / UDP(sport=68, dport=67)
        / BOOTP(chaddr=b"\x00\x11\x22\x33\x44\x55", xid=0x12345678)
        / DHCP(options=[("message-type", 1), "end"])
    )

    # 2. DHCP Offer
    p_offer = (
        Ether(src="aa:bb:cc:dd:ee:ff", dst="00:11:22:33:44:55")
        / IP(src="192.168.122.10", dst="192.168.122.150")
        / UDP(sport=67, dport=68)
        / BOOTP(yiaddr="192.168.122.150", chaddr=b"\x00\x11\x22\x33\x44\x55", xid=0x12345678)
        / DHCP(options=[("message-type", 2), ("server_id", "192.168.122.10"), "end"])
    )

    # 3. DHCP Request
    p_req = (
        Ether(src="00:11:22:33:44:55", dst="ff:ff:ff:ff:ff:ff")
        / IP(src="0.0.0.0", dst="255.255.255.255")
        / UDP(sport=68, dport=67)
        / BOOTP(chaddr=b"\x00\x11\x22\x33\x44\x55", xid=0x12345678)
        / DHCP(options=[("message-type", 3), ("requested_addr", "192.168.122.150"), "end"])
    )

    # 4. DHCP Ack
    p_ack = (
        Ether(src="aa:bb:cc:dd:ee:ff", dst="00:11:22:33:44:55")
        / IP(src="192.168.122.10", dst="192.168.122.150")
        / UDP(sport=67, dport=68)
        / BOOTP(yiaddr="192.168.122.150", chaddr=b"\x00\x11\x22\x33\x44\x55", xid=0x12345678)
        / DHCP(options=[("message-type", 5), ("lease_time", 43200), "end"])
    )

    wrpcap(str(out), [p_disc, p_offer, p_req, p_ack])
    return str(out)
