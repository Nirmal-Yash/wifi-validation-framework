from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
from typing import Any

from lib.domain.protocol_evidence import (
    BeaconEvidence,
    DhcpEvidence,
    DhcpTransactionEvidence,
    DnsEvidence,
    DnsTransactionEvidence,
    EapolEvidence,
    EapolHandshakeEvidence,
)

try:
    from scapy.all import BOOTP, DHCP, DNS, Dot11, Dot11Beacon, Dot11Elt, EAPOL
    from scapy.layers.eap import EAPOL_KEY
    from scapy.all import rdpcap
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False


class ProtocolEvidenceError(RuntimeError):
    """Raised when protocol evidence cannot be parsed."""


class ProtocolEvidenceService:
    """Correlate protocol transactions from captured PCAP evidence."""

    def __init__(self, *, packet_reader=rdpcap if SCAPY_AVAILABLE else None) -> None:
        self.packet_reader = packet_reader

    def _load(self, pcap_path: str | Path) -> list[Any]:
        if self.packet_reader is None:
            raise ImportError("Scapy is required for protocol evidence analysis")
        path = Path(pcap_path)
        if not path.exists():
            raise FileNotFoundError(f"PCAP file not found: {pcap_path}")
        return list(self.packet_reader(str(path)))

    @staticmethod
    def _dhcp_option(packet: Any, name: str) -> Any:
        for option in packet[DHCP].options:
            if isinstance(option, tuple) and option[0] == name:
                return option[1]
        return None

    @staticmethod
    def _client_mac(packet: Any) -> str | None:
        if BOOTP not in packet:
            return None
        value = packet[BOOTP].chaddr
        if isinstance(value, bytes):
            raw = value[:6]
            if len(raw) == 6:
                return ":".join(f"{byte:02x}" for byte in raw)
            return None
        text = str(value).strip().strip("'")
        if not text or set(text) == {"\x00"}:
            return None
        return text

    @staticmethod
    def _dhcp_message_type(packet: Any) -> str | None:
        mapping = {
            1: "DISCOVER",
            2: "OFFER",
            3: "REQUEST",
            4: "DECLINE",
            5: "ACK",
            6: "NAK",
            7: "RELEASE",
            8: "INFORM",
        }
        value = ProtocolEvidenceService._dhcp_option(packet, "message-type")
        return mapping.get(value)

    @staticmethod
    def _ordered_dora(message_types: list[str]) -> bool:
        required = ("DISCOVER", "OFFER", "REQUEST", "ACK")
        position = 0
        for message_type in message_types:
            if message_type == required[position]:
                position += 1
                if position == len(required):
                    return True
        return False

    def analyze_dhcp(self, pcap_path: str | Path) -> DhcpEvidence:
        packets = [
            packet
            for packet in self._load(pcap_path)
            if packet.haslayer(DHCP) and packet.haslayer(BOOTP)
        ]
        counts = {
            "DISCOVER": 0,
            "OFFER": 0,
            "REQUEST": 0,
            "ACK": 0,
            "NAK": 0,
        }
        grouped: dict[tuple[int, str | None], list[tuple[float, Any, str]]] = defaultdict(list)

        for packet in packets:
            message_type = self._dhcp_message_type(packet)
            if message_type is None:
                continue
            if message_type in counts:
                counts[message_type] += 1
            xid = int(packet[BOOTP].xid)
            client_mac = self._client_mac(packet)
            timestamp = float(getattr(packet, "time", 0.0))
            grouped[(xid, client_mac)].append((timestamp, packet, message_type))

        transactions: list[DhcpTransactionEvidence] = []
        for (xid, client_mac), entries in grouped.items():
            entries.sort(key=lambda item: item[0])
            message_types = [item[2] for item in entries]
            offer = next((item[1] for item in entries if item[2] == "OFFER"), None)
            ack = next((item[1] for item in entries if item[2] == "ACK"), None)
            server_identifier = None
            if offer is not None:
                server_identifier = self._dhcp_option(offer, "server_id")
            if server_identifier is None and ack is not None:
                server_identifier = self._dhcp_option(ack, "server_id")

            transactions.append(
                DhcpTransactionEvidence(
                    xid=xid,
                    client_mac=client_mac,
                    message_types=tuple(message_types),
                    has_dora=self._ordered_dora(message_types),
                    offered_ip=str(offer[BOOTP].yiaddr) if offer is not None else None,
                    acknowledged_ip=str(ack[BOOTP].yiaddr) if ack is not None else None,
                    server_identifier=(
                        str(server_identifier)
                        if server_identifier is not None
                        else None
                    ),
                )
            )

        correlated = sum(item.has_dora for item in transactions)
        return DhcpEvidence(
            total_packets=len(packets),
            message_counts=counts,
            transactions=tuple(transactions),
            correlated_dora_count=correlated,
            has_dora=correlated > 0,
            has_lease_acquired=any(
                item.has_dora and item.acknowledged_ip not in {None, "0.0.0.0"}
                for item in transactions
            ),
        )

    @staticmethod
    def _endpoints(packet: Any) -> tuple[str | None, str | None]:
        if Dot11 in packet:
            return packet[Dot11].addr1, packet[Dot11].addr2
        return None, None

    def analyze_eapol(self, pcap_path: str | Path) -> EapolEvidence:
        packets = [
            packet
            for packet in self._load(pcap_path)
            if packet.haslayer(EAPOL) and packet.haslayer(EAPOL_KEY)
        ]
        grouped: dict[tuple[str | None, str | None], list[Any]] = defaultdict(list)

        for packet in packets:
            first, second = self._endpoints(packet)
            endpoints = tuple(sorted(value for value in (first, second) if value))
            key = (
                (endpoints[0], endpoints[1])
                if len(endpoints) == 2
                else (endpoints[0], None)
                if endpoints
                else (None, None)
            )
            grouped[key].append(packet)

        handshakes: list[EapolHandshakeEvidence] = []
        for endpoints, entries in grouped.items():
            entries.sort(key=lambda item: float(getattr(item, "time", 0.0)))
            key_numbers: list[int] = []
            replay_counters: list[int] = []
            for packet in entries:
                key = packet[EAPOL_KEY]
                try:
                    number = int(key.guess_key_number())
                except Exception:
                    number = 0
                if number:
                    key_numbers.append(number)
                    replay_counters.append(int(key.key_replay_counter))

            completed = self._contains_ordered_sequence(key_numbers, (1, 2, 3, 4))
            handshakes.append(
                EapolHandshakeEvidence(
                    endpoint_a=endpoints[0],
                    endpoint_b=endpoints[1],
                    key_numbers=tuple(key_numbers),
                    replay_counters=tuple(replay_counters),
                    handshake_completed=completed,
                )
            )

        return EapolEvidence(
            total_eapol_packets=len(packets),
            handshakes=tuple(handshakes),
            handshake_completed=any(item.handshake_completed for item in handshakes),
        )

    @staticmethod
    def _contains_ordered_sequence(values: list[int], required: tuple[int, ...]) -> bool:
        position = 0
        for value in values:
            if value == required[position]:
                position += 1
                if position == len(required):
                    return True
        return False

    @staticmethod
    def _iter_elements(packet: Any) -> list[Any]:
        values: list[Any] = []
        element = packet.getlayer(Dot11Elt)
        while element is not None:
            values.append(element)
            next_layer = element.payload.getlayer(Dot11Elt) if element.payload else None
            if next_layer is element:
                break
            element = next_layer
        return values

    @staticmethod
    def _suite_name(selector: bytes, *, akm: bool = False) -> str:
        if len(selector) != 4:
            return selector.hex(":")
        oui = selector[:3]
        kind = selector[3]
        if oui != b"\x00\x0f\xac":
            return selector.hex(":")
        if akm:
            return {
                1: "802.1X",
                2: "PSK",
                3: "FT-802.1X",
                4: "FT-PSK",
                8: "SAE",
                12: "FT-SAE",
            }.get(kind, f"AKM-{kind}")
        return {
            1: "WEP-40",
            2: "TKIP",
            4: "CCMP-128",
            5: "WEP-104",
            6: "AES-128-CMAC",
            8: "GCMP-128",
            9: "GCMP-256",
        }.get(kind, f"CIPHER-{kind}")

    @classmethod
    def _parse_rsn(cls, body: bytes) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
        if len(body) < 8:
            return None, (), ()
        offset = 2
        group = cls._suite_name(body[offset:offset + 4])
        offset += 4
        if len(body) < offset + 2:
            return group, (), ()
        pairwise_count = int.from_bytes(body[offset:offset + 2], "little")
        offset += 2
        pairwise: list[str] = []
        for _ in range(pairwise_count):
            selector = body[offset:offset + 4]
            if len(selector) != 4:
                return group, tuple(pairwise), ()
            pairwise.append(cls._suite_name(selector))
            offset += 4
        if len(body) < offset + 2:
            return group, tuple(pairwise), ()
        akm_count = int.from_bytes(body[offset:offset + 2], "little")
        offset += 2
        akms: list[str] = []
        for _ in range(akm_count):
            selector = body[offset:offset + 4]
            if len(selector) != 4:
                break
            akms.append(cls._suite_name(selector, akm=True))
            offset += 4
        return group, tuple(pairwise), tuple(akms)

    def analyze_beacon(self, pcap_path: str | Path, expected_ssid: str | None = None) -> BeaconEvidence:
        packets = [packet for packet in self._load(pcap_path) if packet.haslayer(Dot11Beacon)]
        if not packets:
            return BeaconEvidence(
                beacon_count=0,
                ssid=None,
                bssid=None,
                channel=None,
                has_rsn=False,
                group_cipher=None,
                matches_expected_ssid=expected_ssid is None,
            )

        beacon = packets[0]
        ssid = None
        channel = None
        group_cipher = None
        pairwise = ()
        akms = ()
        has_rsn = False

        for element in self._iter_elements(beacon):
            if element.ID == 0:
                ssid = element.info.decode("utf-8", errors="replace")
            elif element.ID == 3 and element.info:
                channel = int(element.info[0])
            elif element.ID == 48:
                has_rsn = True
                group_cipher, pairwise, akms = self._parse_rsn(bytes(element.info))

        return BeaconEvidence(
            beacon_count=len(packets),
            ssid=ssid,
            bssid=getattr(beacon, "addr3", None),
            channel=channel,
            has_rsn=has_rsn,
            group_cipher=group_cipher,
            pairwise_ciphers=pairwise,
            akms=akms,
            beacon_interval_ms=(
                float(beacon[Dot11Beacon].beacon_interval)
                if beacon[Dot11Beacon].beacon_interval is not None
                else None
            ),
            capabilities=str(beacon[Dot11Beacon].cap),
            matches_expected_ssid=(
                expected_ssid is None or ssid == expected_ssid
            ),
        )

    @staticmethod
    def _dns_qname(packet: Any) -> str | None:
        dns = packet[DNS]
        if dns.qd is None or not getattr(dns.qd, "qname", None):
            return None
        return bytes(dns.qd.qname).rstrip(b".").decode("utf-8", errors="replace")

    def analyze_dns(self, pcap_path: str | Path, expected_domain: str | None = None) -> DnsEvidence:
        packets = [packet for packet in self._load(pcap_path) if packet.haslayer(DNS)]
        queries: dict[tuple[int, str, int], Any] = {}
        responses: dict[tuple[int, str, int], list[Any]] = defaultdict(list)
        resolved: list[str] = []
        query_count = 0
        response_count = 0

        for packet in packets:
            dns = packet[DNS]
            name = self._dns_qname(packet)
            qtype = int(dns.qd.qtype) if dns.qd is not None else 0
            key = (int(dns.id), name or "", qtype)
            if int(dns.qr) == 0:
                query_count += 1
                if name is not None:
                    queries[key] = packet
            else:
                response_count += 1
                responses[key].append(packet)
                if dns.an:
                    for index in range(int(dns.ancount or 0)):
                        answer = dns.an[index]
                        if hasattr(answer, "rdata"):
                            value = str(answer.rdata)
                            resolved.append(value)

        transactions: list[DnsTransactionEvidence] = []
        for key, query in queries.items():
            response_packets = responses.get(key, [])
            answers: list[str] = []
            for packet in response_packets:
                dns = packet[DNS]
                for index in range(int(dns.ancount or 0)):
                    answer = dns.an[index]
                    if hasattr(answer, "rdata"):
                        answers.append(str(answer.rdata))
            transactions.append(
                DnsTransactionEvidence(
                    transaction_id=key[0],
                    query_name=key[1],
                    query_type=key[2],
                    response_count=len(response_packets),
                    answers=tuple(answers),
                    correlated=bool(response_packets),
                )
            )

        if expected_domain is not None:
            expected = expected_domain.rstrip(".").lower()
            transactions = [
                item
                for item in transactions
                if item.query_name.rstrip(".").lower() == expected
            ]

        correlated = sum(item.correlated for item in transactions)
        return DnsEvidence(
            total_dns_packets=len(packets),
            query_count=query_count,
            response_count=response_count,
            correlated_transaction_count=correlated,
            unmatched_query_count=max(query_count - correlated, 0),
            unmatched_response_count=max(response_count - correlated, 0),
            resolved_ips=tuple(resolved),
            transactions=tuple(transactions),
        )

    @staticmethod
    def write_json(evidence: Any, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence.as_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return output
