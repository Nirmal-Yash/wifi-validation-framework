from __future__ import annotations

from scapy.all import (
    BOOTP,
    DHCP,
    DNS,
    DNSQR,
    DNSRR,
    Dot11,
    Dot11Beacon,
    Dot11Elt,
    EAPOL,
    Ether,
    IP,
    UDP,
    wrpcap,
)
from scapy.layers.eap import EAPOL_KEY

from lib.services import ProtocolEvidenceService


CLIENT_MAC = "02:00:00:00:00:30"
AP_MAC = "02:00:00:00:00:20"


def dhcp_packet(xid: int, message_type: int, *, yiaddr="0.0.0.0", include_server=False):
    options = [("message-type", message_type)]
    if message_type == 3:
        options.append(("requested_addr", "192.168.122.30"))
    if include_server:
        options.append(("server_id", "192.168.122.10"))
    options.append("end")
    return (
        Ether(src=CLIENT_MAC)
        / IP(src="0.0.0.0", dst="255.255.255.255")
        / UDP(sport=68, dport=67)
        / BOOTP(xid=xid, chaddr=bytes.fromhex("020000000030"), yiaddr=yiaddr)
        / DHCP(options=options)
    )


def write_pcap(path, packets):
    wrpcap(str(path), packets)
    return path


def test_dhcp_requires_correlated_dora_transaction(tmp_path):
    pcap = write_pcap(
        tmp_path / "dhcp.pcap",
        [
            dhcp_packet(1, 1),
            dhcp_packet(1, 2, yiaddr="192.168.122.30", include_server=True),
            dhcp_packet(1, 3, include_server=True),
            dhcp_packet(1, 5, yiaddr="192.168.122.30", include_server=True),
        ],
    )

    evidence = ProtocolEvidenceService().analyze_dhcp(pcap)

    assert evidence.message_counts["DISCOVER"] == 1
    assert evidence.correlated_dora_count == 1
    assert evidence.has_dora is True
    assert evidence.has_lease_acquired is True
    assert evidence.transactions[0].xid == 1
    assert evidence.transactions[0].offered_ip == "192.168.122.30"


def test_dhcp_packet_counts_do_not_fake_correlation(tmp_path):
    pcap = write_pcap(
        tmp_path / "mismatched-dhcp.pcap",
        [
            dhcp_packet(10, 1),
            dhcp_packet(10, 2, yiaddr="192.168.122.30"),
            dhcp_packet(11, 3),
            dhcp_packet(11, 5, yiaddr="192.168.122.30"),
        ],
    )

    evidence = ProtocolEvidenceService().analyze_dhcp(pcap)

    assert evidence.message_counts["DISCOVER"] == 1
    assert evidence.message_counts["OFFER"] == 1
    assert evidence.message_counts["REQUEST"] == 1
    assert evidence.message_counts["ACK"] == 1
    assert evidence.correlated_dora_count == 0
    assert evidence.has_dora is False
    assert evidence.has_lease_acquired is False


def test_eapol_requires_ordered_four_way_handshake(tmp_path):
    frames = []
    key_shapes = (
        {"key_ack": 1, "has_key_mic": 0, "install": 0, "secure": 0},
        {"key_ack": 0, "has_key_mic": 1, "install": 0, "secure": 0},
        {"key_ack": 1, "has_key_mic": 1, "install": 1, "secure": 1},
        {"key_ack": 0, "has_key_mic": 1, "install": 0, "secure": 1},
    )
    for replay_counter, shape in enumerate(key_shapes, start=1):
        frame = (
            Dot11(
                addr1=CLIENT_MAC,
                addr2=AP_MAC,
                addr3=AP_MAC,
            )
            / EAPOL(version=2, type=3)
            / EAPOL_KEY(
                key_descriptor_type=2,
                key_type=1,
                key_descriptor_type_version=2,
                key_replay_counter=replay_counter,
                **shape,
            )
        )
        frames.append(frame)

    pcap = write_pcap(tmp_path / "eapol.pcap", frames)
    evidence = ProtocolEvidenceService().analyze_eapol(pcap)

    assert evidence.total_eapol_packets == 4
    assert evidence.handshake_completed is True
    assert evidence.handshakes[0].key_numbers == (1, 2, 3, 4)


def test_beacon_extracts_rsn_identity_and_security(tmp_path):
    rsn = (
        b"\x01\x00"
        b"\x00\x0f\xac\x04"
        b"\x01\x00"
        b"\x00\x0f\xac\x04"
        b"\x01\x00"
        b"\x00\x0f\xac\x02"
    )
    beacon = (
        Dot11(
            addr1="ff:ff:ff:ff:ff:ff",
            addr2=AP_MAC,
            addr3=AP_MAC,
        )
        / Dot11Beacon(beacon_interval=100, cap="ESS+privacy")
        / Dot11Elt(ID=0, info=b"TestNet_5G")
        / Dot11Elt(ID=3, info=b"\x06")
        / Dot11Elt(ID=48, info=rsn)
    )
    pcap = write_pcap(tmp_path / "beacon.pcap", [beacon])

    evidence = ProtocolEvidenceService().analyze_beacon(
        pcap,
        expected_ssid="TestNet_5G",
    )

    assert evidence.beacon_count == 1
    assert evidence.ssid == "TestNet_5G"
    assert evidence.bssid == AP_MAC
    assert evidence.channel == 6
    assert evidence.has_rsn is True
    assert evidence.group_cipher == "CCMP-128"
    assert evidence.pairwise_ciphers == ("CCMP-128",)
    assert evidence.akms == ("PSK",)
    assert evidence.matches_expected_ssid is True


def test_dns_correlates_transaction_id_and_question(tmp_path):
    query = (
        Ether()
        / IP(src="192.168.122.30", dst="8.8.8.8")
        / UDP(sport=40000, dport=53)
        / DNS(id=1234, qr=0, qd=DNSQR(qname="example.com.", qtype="A"))
    )
    response = (
        Ether()
        / IP(src="8.8.8.8", dst="192.168.122.30")
        / UDP(sport=53, dport=40000)
        / DNS(
            id=1234,
            qr=1,
            qd=DNSQR(qname="example.com.", qtype="A"),
            an=DNSRR(rrname="example.com.", type="A", rdata="93.184.216.34"),
        )
    )

    pcap = write_pcap(tmp_path / "dns.pcap", [query, response])
    evidence = ProtocolEvidenceService().analyze_dns(
        pcap,
        expected_domain="example.com",
    )

    assert evidence.query_count == 1
    assert evidence.response_count == 1
    assert evidence.correlated_transaction_count == 1
    assert evidence.unmatched_query_count == 0
    assert evidence.transactions[0].correlated is True
    assert "93.184.216.34" in evidence.resolved_ips
