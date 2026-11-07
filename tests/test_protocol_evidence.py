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
    LLC,
    SNAP,
    UDP,
    wrpcap,
)
from scapy.layers.eap import EAPOL_KEY

from lib.domain import ArtifactType
from lib.services import ProtocolEvidenceService
from lib.services.test_registry import TestRegistry


CLIENT_MAC = "02:00:00:00:00:30"
AP_MAC = "02:00:00:00:00:20"
VALID_RSN = (
    b"\x01\x00"
    b"\x00\x0f\xac\x04"
    b"\x01\x00"
    b"\x00\x0f\xac\x04"
    b"\x01\x00"
    b"\x00\x0f\xac\x02"
)


def dhcp_packet(
    xid: int,
    message_type: int,
    *,
    yiaddr="0.0.0.0",
    include_server=False,
    ciaddr="0.0.0.0",
    include_timers=False,
    dst="255.255.255.255",
):
    options = [("message-type", message_type)]
    if message_type == 3 and ciaddr == "0.0.0.0":
        options.append(("requested_addr", "192.168.122.30"))
    if include_server:
        options.append(("server_id", "192.168.122.10"))
    if include_timers:
        options.extend([("renewal_time", 60), ("rebinding_time", 105)])
    options.append("end")
    return (
        Ether(src=CLIENT_MAC)
        / IP(src=ciaddr, dst=dst)
        / UDP(sport=68, dport=67)
        / BOOTP(
            xid=xid,
            chaddr=bytes.fromhex("020000000030"),
            ciaddr=ciaddr,
            yiaddr=yiaddr,
        )
        / DHCP(options=options)
    )


def eapol_packet(number: int, replay: int, *, reverse_direction=False):
    shapes = {
        1: {"key_ack": 1, "has_key_mic": 0, "install": 0, "secure": 0},
        2: {"key_ack": 0, "has_key_mic": 1, "install": 0, "secure": 0},
        3: {"key_ack": 1, "has_key_mic": 1, "install": 1, "secure": 1},
        4: {"key_ack": 0, "has_key_mic": 1, "install": 0, "secure": 1},
    }
    ap_to_client = number in {1, 3}
    if reverse_direction:
        ap_to_client = not ap_to_client
    sender, receiver = (AP_MAC, CLIENT_MAC) if ap_to_client else (CLIENT_MAC, AP_MAC)
    return (
        Dot11(addr1=receiver, addr2=sender, addr3=AP_MAC)
        / LLC(dsap=0xAA, ssap=0xAA, ctrl=3)
        / SNAP(OUI=0x000000, code=0x888E)
        / EAPOL(version=2, type=3)
        / EAPOL_KEY(
            key_descriptor_type=2,
            key_type=1,
            key_descriptor_type_version=2,
            key_replay_counter=replay,
            **shapes[number],
        )
    )


def beacon_frame(ssid="TestNet_5G", bssid=AP_MAC, *, channel=6, rsn=VALID_RSN):
    return (
        Dot11(
            addr1="ff:ff:ff:ff:ff:ff",
            addr2=bssid,
            addr3=bssid,
        )
        / Dot11Beacon(beacon_interval=100, cap="ESS+privacy")
        / Dot11Elt(ID=0, info=ssid.encode())
        / Dot11Elt(ID=3, info=bytes([channel]))
        / Dot11Elt(ID=48, info=rsn)
    )


def dns_packet(
    *,
    src="192.168.122.30",
    dst="8.8.8.8",
    sport=40000,
    dport=53,
    transaction_id=1234,
    name="example.com.",
    qr=0,
    answer=None,
):
    packet = (
        Ether()
        / IP(src=src, dst=dst)
        / UDP(sport=sport, dport=dport)
        / DNS(
            id=transaction_id,
            qr=qr,
            qd=DNSQR(qname=name, qtype="A"),
        )
    )
    if qr and answer:
        packet[DNS].an = DNSRR(rrname=name, type="A", rdata=answer)
        packet[DNS].ancount = 1
    return packet


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


def test_scapy_eapol_key_api_is_available():
    assert EAPOL_KEY is not None


def test_eapol_requires_directional_replay_paired_four_way_handshake(tmp_path):
    frames = [
        eapol_packet(1, 7),
        eapol_packet(2, 7),
        eapol_packet(3, 8),
        eapol_packet(4, 8),
    ]
    pcap = write_pcap(tmp_path / "eapol.pcap", frames)

    evidence = ProtocolEvidenceService().analyze_eapol(pcap)

    assert evidence.total_eapol_packets == 4
    assert evidence.handshake_completed is True
    assert evidence.handshakes[0].key_numbers == (1, 2, 3, 4)
    assert evidence.handshakes[0].replay_counters == (7, 7, 8, 8)


def test_eapol_rejects_invalid_replay_counter_pairing(tmp_path):
    frames = [
        eapol_packet(1, 7),
        eapol_packet(2, 7),
        eapol_packet(3, 8),
        eapol_packet(4, 9),
    ]
    evidence = ProtocolEvidenceService().analyze_eapol(
        write_pcap(tmp_path / "bad-replay.pcap", frames)
    )
    assert evidence.handshake_completed is False


def test_eapol_rejects_wrong_message_direction(tmp_path):
    frames = [
        eapol_packet(1, 7),
        eapol_packet(2, 7, reverse_direction=True),
        eapol_packet(3, 8),
        eapol_packet(4, 8),
    ]
    evidence = ProtocolEvidenceService().analyze_eapol(
        write_pcap(tmp_path / "wrong-direction.pcap", frames)
    )
    assert evidence.handshake_completed is False


def test_beacon_selects_expected_identity_and_validates_rsn(tmp_path):
    other = beacon_frame(ssid="OtherNet", bssid="02:00:00:00:00:99", channel=1)
    target = beacon_frame()
    evidence = ProtocolEvidenceService().analyze_beacon(
        write_pcap(tmp_path / "beacons.pcap", [other, target]),
        expected_ssid="TestNet_5G",
        expected_bssid=AP_MAC,
    )

    assert evidence.beacon_count == 2
    assert evidence.ssid == "TestNet_5G"
    assert evidence.bssid == AP_MAC
    assert evidence.channel == 6
    assert evidence.has_rsn is True
    assert evidence.rsn_valid is True
    assert evidence.group_cipher == "CCMP-128"
    assert evidence.pairwise_ciphers == ("CCMP-128",)
    assert evidence.akms == ("PSK",)
    assert evidence.beacon_interval_ms == 102.4
    assert evidence.matches_expected_ssid is True
    assert evidence.matches_expected_bssid is True


def test_beacon_reports_truncated_rsn_as_invalid(tmp_path):
    truncated = (
        b"\x01\x00"
        b"\x00\x0f\xac\x04"
        b"\x01\x00"
        b"\x00\x0f"
    )
    evidence = ProtocolEvidenceService().analyze_beacon(
        write_pcap(tmp_path / "truncated-rsn.pcap", [beacon_frame(rsn=truncated)])
    )
    assert evidence.has_rsn is True
    assert evidence.rsn_valid is False


def test_beacon_expected_identity_mismatch_is_explicit(tmp_path):
    evidence = ProtocolEvidenceService().analyze_beacon(
        write_pcap(tmp_path / "wrong-beacon.pcap", [beacon_frame(ssid="OtherNet")]),
        expected_ssid="TestNet_5G",
        expected_bssid="02:00:00:00:00:99",
    )
    assert evidence.matches_expected_ssid is False
    assert evidence.matches_expected_bssid is False


def test_dns_correlates_transaction_id_question_and_reverse_flow(tmp_path):
    query = dns_packet()
    response = dns_packet(
        src="8.8.8.8",
        dst="192.168.122.30",
        sport=53,
        dport=40000,
        qr=1,
        answer="93.184.216.34",
    )
    evidence = ProtocolEvidenceService().analyze_dns(
        write_pcap(tmp_path / "dns.pcap", [query, response]),
        expected_domain="example.com",
    )

    assert evidence.query_count == 1
    assert evidence.response_count == 1
    assert evidence.correlated_transaction_count == 1
    assert evidence.unmatched_query_count == 0
    assert evidence.unmatched_response_count == 0
    assert evidence.transactions[0].correlated is True
    assert evidence.resolved_ips == ("93.184.216.34",)


def test_dns_does_not_correlate_same_question_from_wrong_server(tmp_path):
    query = dns_packet()
    wrong_server_response = dns_packet(
        src="1.1.1.1",
        dst="192.168.122.30",
        sport=53,
        dport=40000,
        qr=1,
        answer="203.0.113.77",
    )
    evidence = ProtocolEvidenceService().analyze_dns(
        write_pcap(tmp_path / "wrong-dns-flow.pcap", [query, wrong_server_response])
    )

    assert evidence.correlated_transaction_count == 0
    assert evidence.unmatched_query_count == 1
    assert evidence.unmatched_response_count == 1
    assert evidence.resolved_ips == ()


def test_dns_response_is_consumed_once_and_orphan_answers_are_excluded(tmp_path):
    query = dns_packet()
    first_response = dns_packet(
        src="8.8.8.8", dst="192.168.122.30", sport=53, dport=40000,
        qr=1, answer="93.184.216.34",
    )
    duplicate_response = dns_packet(
        src="8.8.8.8", dst="192.168.122.30", sport=53, dport=40000,
        qr=1, answer="203.0.113.10",
    )
    evidence = ProtocolEvidenceService().analyze_dns(
        write_pcap(
            tmp_path / "duplicate-dns-response.pcap",
            [query, first_response, duplicate_response],
        )
    )

    assert evidence.correlated_transaction_count == 1
    assert evidence.unmatched_response_count == 1
    assert evidence.resolved_ips == ("93.184.216.34",)


def test_dns_expected_domain_filters_counts_before_correlation(tmp_path):
    packets = [
        dns_packet(name="example.com.", transaction_id=1, sport=41000),
        dns_packet(
            name="example.com.", transaction_id=1, src="8.8.8.8",
            dst="192.168.122.30", sport=53, dport=41000, qr=1,
            answer="93.184.216.34",
        ),
        dns_packet(name="other.example.", transaction_id=2, sport=42000),
        dns_packet(
            name="other.example.", transaction_id=2, src="8.8.8.8",
            dst="192.168.122.30", sport=53, dport=42000, qr=1,
            answer="203.0.113.5",
        ),
    ]
    evidence = ProtocolEvidenceService().analyze_dns(
        write_pcap(tmp_path / "filtered-dns.pcap", packets),
        expected_domain="example.com",
    )

    assert evidence.total_dns_packets == 4
    assert evidence.query_count == 1
    assert evidence.response_count == 1
    assert evidence.correlated_transaction_count == 1
    assert evidence.unmatched_response_count == 0
    assert evidence.resolved_ips == ("93.184.216.34",)


def test_dhcp_classifies_renewal_and_rebind_by_unicast_vs_broadcast(tmp_path):
    renewal_request = dhcp_packet(
        10, 3, ciaddr="192.168.122.30", include_server=False,
        dst="192.168.122.10",
    )
    renewal_ack = dhcp_packet(
        10, 5, yiaddr="192.168.122.30", include_server=True,
        dst="192.168.122.30", include_timers=True,
    )
    rebind_request = dhcp_packet(
        11, 3, ciaddr="192.168.122.30", include_server=False,
        dst="255.255.255.255",
    )
    rebind_ack = dhcp_packet(
        11, 5, yiaddr="192.168.122.30", include_server=True,
        dst="192.168.122.30", include_timers=True,
    )
    packets = [renewal_request, renewal_ack, rebind_request, rebind_ack]
    for index, packet in enumerate(packets):
        packet.time = 1000 + index
    evidence = ProtocolEvidenceService().analyze_dhcp(
        write_pcap(tmp_path / "dhcp-renew-rebind.pcap", packets)
    )

    assert evidence.correlated_renewal_count == 1
    assert evidence.correlated_rebind_count == 1
    assert evidence.has_renewal is True
    assert evidence.has_rebind is True
    renewal = next(item for item in evidence.transactions if item.is_renewal)
    rebind = next(item for item in evidence.transactions if item.is_rebind)
    assert renewal.renewal_time_seconds == 60
    assert renewal.rebinding_time_seconds == 105
    assert rebind.renewal_time_seconds == 60
    assert rebind.rebinding_time_seconds == 105


def test_dhcp_ack_before_request_does_not_satisfy_renewal(tmp_path):
    ack = dhcp_packet(
        12, 5, yiaddr="192.168.122.30", include_server=True,
        dst="192.168.122.30",
    )
    request = dhcp_packet(
        12, 3, ciaddr="192.168.122.30", include_server=False,
        dst="192.168.122.10",
    )
    ack.time = 1000
    request.time = 1001
    evidence = ProtocolEvidenceService().analyze_dhcp(
        write_pcap(tmp_path / "ack-before-renewal.pcap", [ack, request])
    )
    assert evidence.has_renewal is False


def test_dns_response_before_query_is_not_correlated(tmp_path):
    response = dns_packet(
        src="8.8.8.8", dst="192.168.122.30", sport=53, dport=40000,
        qr=1, answer="203.0.113.10",
    )
    query = dns_packet()
    response.time = 1000
    query.time = 1001
    evidence = ProtocolEvidenceService().analyze_dns(
        write_pcap(tmp_path / "response-before-query.pcap", [response, query])
    )
    assert evidence.correlated_transaction_count == 0
    assert evidence.unmatched_query_count == 1
    assert evidence.unmatched_response_count == 1
    assert evidence.resolved_ips == ()


def test_protocol_analysis_does_not_modify_raw_pcap(tmp_path):
    import hashlib

    pcap = write_pcap(
        tmp_path / "immutable-source.pcap",
        [
            dns_packet(),
            dns_packet(
                src="8.8.8.8", dst="192.168.122.30", sport=53, dport=40000,
                qr=1, answer="93.184.216.34",
            ),
            beacon_frame(),
        ],
    )
    before = hashlib.sha256(pcap.read_bytes()).hexdigest()

    service = ProtocolEvidenceService()
    service.analyze_dns(pcap)
    service.analyze_beacon(pcap, expected_ssid="TestNet_5G")
    after = hashlib.sha256(pcap.read_bytes()).hexdigest()

    assert after == before


def test_registry_requires_raw_and_parsed_evidence_for_protocol_capture_nodes():
    registry = TestRegistry.default()
    expected = {ArtifactType.PCAP, ArtifactType.PROTOCOL_EVIDENCE}
    cases = {
        "wifi.dhcp.capture": "tests/test_packet_capture.py::test_pcap_contains_dhcp_packets",
        "wifi.protocol.eapol_beacon": (
            "tests/test_protocol_capture.py::test_real_wifi_capture_contains_eapol_and_beacon"
        ),
        "wifi.protocol.dns_capture": (
            "tests/test_protocol_capture.py::test_real_wifi_dns_capture_correlates_query_response"
        ),
    }
    for test_id, node_id in cases.items():
        definition = registry.get(test_id)
        assert definition.node_id == node_id
        assert set(definition.evidence_requirements) == expected


def test_dhcp_does_not_claim_correlation_without_client_identity(tmp_path):
    packets = [
        dhcp_packet(20, 1),
        dhcp_packet(20, 2, yiaddr="192.168.122.30"),
        dhcp_packet(20, 3),
        dhcp_packet(20, 5, yiaddr="192.168.122.30"),
    ]
    for packet in packets:
        packet[BOOTP].chaddr = b"\x00" * 16
    evidence = ProtocolEvidenceService().analyze_dhcp(
        write_pcap(tmp_path / "dhcp-no-client-identity.pcap", packets)
    )
    assert evidence.message_counts["DISCOVER"] == 1
    assert evidence.correlated_dora_count == 0
    assert evidence.has_dora is False


def test_dns_questionless_response_is_reported_as_unmatched(tmp_path):
    query = dns_packet()
    questionless_response = (
        Ether()
        / IP(src="8.8.8.8", dst="192.168.122.30")
        / UDP(sport=53, dport=40000)
        / DNS(id=1234, qr=1, qd=None, ancount=0)
    )
    evidence = ProtocolEvidenceService().analyze_dns(
        write_pcap(
            tmp_path / "questionless-dns-response.pcap",
            [query, questionless_response],
        )
    )
    assert evidence.query_count == 1
    assert evidence.response_count == 1
    assert evidence.unmatched_query_count == 1
    assert evidence.unmatched_response_count == 1
    assert evidence.correlated_transaction_count == 0


def test_dns_question_helper_handles_empty_question_list():
    packet = Ether() / DNS(qr=1, qdcount=1, qd=None, ancount=0)
    assert ProtocolEvidenceService._dns_question(packet) is None


def test_dns_answer_values_handles_inconsistent_answer_count():
    packet = Ether() / DNS(qr=1, ancount=2, an=[])
    assert ProtocolEvidenceService._dns_answer_values(packet) == ()
