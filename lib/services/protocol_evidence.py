from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import ipaddress
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
    from scapy.all import (
        BOOTP, DHCP, DNS, Dot11, Dot11Beacon, Dot11Elt,
        IP, IPv6, TCP, UDP, rdpcap,
    )
    from scapy.layers.eap import EAPOL_KEY
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False


class ProtocolEvidenceError(RuntimeError):
    """Raised when protocol evidence cannot be parsed."""


class ProtocolEvidenceService:
    """Correlate protocol transactions from verified packet captures."""

    def __init__(self, *, packet_reader=rdpcap if SCAPY_AVAILABLE else None) -> None:
        self.packet_reader = packet_reader

    def _load(self, pcap_path: str | Path) -> list[Any]:
        if self.packet_reader is None:
            raise ImportError("Scapy is required for protocol evidence analysis")
        path = Path(pcap_path)
        if not path.is_file():
            raise FileNotFoundError(f"PCAP file not found: {pcap_path}")
        try:
            return list(self.packet_reader(str(path)))
        except Exception as exc:
            raise ProtocolEvidenceError(f"Could not parse PCAP {path}: {exc}") from exc

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
            if len(raw) != 6 or not any(raw):
                return None
            return ":".join(f"{byte:02x}" for byte in raw)
        text = str(value).strip().strip("'").lower()
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
        try:
            return mapping.get(int(value))
        except (TypeError, ValueError):
            return None

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

    @staticmethod
    def _ciaddr(packet: Any) -> str | None:
        if BOOTP not in packet:
            return None
        value = str(getattr(packet[BOOTP], "ciaddr", "") or "")
        return value if value not in {"", "0.0.0.0"} else None

    @staticmethod
    def _dhcp_destination(packet: Any) -> str | None:
        if IP not in packet:
            return None
        return str(packet[IP].dst)

    @classmethod
    def _dhcp_request_phase(cls, packet: Any) -> str | None:
        """Classify DHCPv4 RENEWING vs REBINDING from the request destination.

        Both request forms use ciaddr and normally omit option 54. A unicast
        request is renewal; a limited-broadcast request is rebinding. The
        Server Identifier option alone is not a valid discriminator.
        """
        if cls._ciaddr(packet) is None:
            return None
        destination = cls._dhcp_destination(packet)
        if destination is None:
            return None
        if destination == "255.255.255.255":
            return "REBIND"
        try:
            address = ipaddress.ip_address(destination)
        except ValueError:
            return None
        if address.version == 4 and not address.is_multicast and not address.is_unspecified:
            return "RENEW"
        return None

    def analyze_dhcp(self, pcap_path: str | Path) -> DhcpEvidence:
        packets = [
            packet for packet in self._load(pcap_path)
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
            ack_entry = next((item for item in entries if item[2] == "ACK"), None)
            ack = ack_entry[1] if ack_entry is not None else None
            requests = [item for item in entries if item[2] == "REQUEST"]

            renewal_request = next(
                (item for item in requests if self._dhcp_request_phase(item[1]) == "RENEW"),
                None,
            )
            rebind_request = next(
                (item for item in requests if self._dhcp_request_phase(item[1]) == "REBIND"),
                None,
            )

            renewal_ack = (
                any(item[2] == "ACK" and item[0] >= renewal_request[0] for item in entries)
                if renewal_request is not None else False
            )
            rebind_ack = (
                any(item[2] == "ACK" and item[0] >= rebind_request[0] for item in entries)
                if rebind_request is not None else False
            )

            server_identifier = None
            if offer is not None:
                server_identifier = self._dhcp_option(offer, "server_id")
            if server_identifier is None and ack is not None:
                server_identifier = self._dhcp_option(ack, "server_id")
            if server_identifier is None and renewal_request is not None:
                server_identifier = self._dhcp_option(renewal_request[1], "server_id")

            renewal_time = self._dhcp_option(ack, "renewal_time") if ack is not None else None
            rebinding_time = self._dhcp_option(ack, "rebinding_time") if ack is not None else None
            transactions.append(
                DhcpTransactionEvidence(
                    xid=xid,
                    client_mac=client_mac,
                    message_types=tuple(message_types),
                    has_dora=(
                        client_mac is not None and self._ordered_dora(message_types)
                    ),
                    is_renewal=(
                        client_mac is not None
                        and renewal_request is not None
                        and renewal_ack
                    ),
                    is_rebind=(
                        client_mac is not None
                        and rebind_request is not None
                        and rebind_ack
                    ),
                    offered_ip=str(offer[BOOTP].yiaddr) if offer is not None else None,
                    acknowledged_ip=str(ack[BOOTP].yiaddr) if ack is not None else None,
                    server_identifier=(
                        str(server_identifier) if server_identifier is not None else None
                    ),
                    renewal_time_seconds=(
                        int(renewal_time) if isinstance(renewal_time, int) else None
                    ),
                    rebinding_time_seconds=(
                        int(rebinding_time) if isinstance(rebinding_time, int) else None
                    ),
                )
            )

        correlated = sum(item.has_dora for item in transactions)
        renewal_count = sum(item.is_renewal for item in transactions)
        rebind_count = sum(item.is_rebind for item in transactions)
        return DhcpEvidence(
            total_packets=len(packets),
            message_counts=counts,
            transactions=tuple(transactions),
            correlated_dora_count=correlated,
            correlated_renewal_count=renewal_count,
            correlated_rebind_count=rebind_count,
            has_dora=correlated > 0,
            has_renewal=renewal_count > 0,
            has_rebind=rebind_count > 0,
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

    @staticmethod
    def _handshake_is_complete(records: list[dict[str, Any]]) -> bool:
        """Require a directionally valid M1/M2/M3/M4 exchange and replay pairing."""
        for index, first in enumerate(records):
            if first["number"] != 1 or first["key_type"] != 1:
                continue
            ap, client = first["sender"], first["receiver"]
            if not ap or not client or ap == client:
                continue

            for second_index in range(index + 1, len(records)):
                second = records[second_index]
                if (
                    second["number"] == 2
                    and second["key_type"] == 1
                    and second["sender"] == client
                    and second["receiver"] == ap
                    and second["replay"] == first["replay"]
                    and second["descriptor"] == first["descriptor"]
                ):
                    for third_index in range(second_index + 1, len(records)):
                        third = records[third_index]
                        if (
                            third["number"] == 3
                            and third["key_type"] == 1
                            and third["sender"] == ap
                            and third["receiver"] == client
                            and third["replay"] > first["replay"]
                            and third["descriptor"] == first["descriptor"]
                        ):
                            for fourth_index in range(third_index + 1, len(records)):
                                fourth = records[fourth_index]
                                if (
                                    fourth["number"] == 4
                                    and fourth["key_type"] == 1
                                    and fourth["sender"] == client
                                    and fourth["receiver"] == ap
                                    and fourth["replay"] == third["replay"]
                                    and fourth["descriptor"] == first["descriptor"]
                                ):
                                    return True
        return False

    def analyze_eapol(self, pcap_path: str | Path) -> EapolEvidence:
        packets = [
            packet for packet in self._load(pcap_path)
            if packet.haslayer(EAPOL_KEY)
        ]
        grouped: dict[tuple[str | None, str | None], list[Any]] = defaultdict(list)
        for packet in packets:
            first, second = self._endpoints(packet)
            endpoints = tuple(sorted(value.lower() for value in (first, second) if value))
            key = (
                (endpoints[0], endpoints[1]) if len(endpoints) == 2
                else (endpoints[0], None) if endpoints
                else (None, None)
            )
            grouped[key].append(packet)

        handshakes: list[EapolHandshakeEvidence] = []
        for endpoints, entries in grouped.items():
            entries.sort(key=lambda item: float(getattr(item, "time", 0.0)))
            key_numbers: list[int] = []
            replay_counters: list[int] = []
            records: list[dict[str, Any]] = []
            for packet in entries:
                key = packet[EAPOL_KEY]
                try:
                    number = int(key.guess_key_number())
                except Exception:
                    number = 0
                if not number:
                    continue
                sender = getattr(packet[Dot11], "addr2", None) if Dot11 in packet else None
                receiver = getattr(packet[Dot11], "addr1", None) if Dot11 in packet else None
                replay = int(key.key_replay_counter)
                key_numbers.append(number)
                replay_counters.append(replay)
                records.append(
                    {
                        "number": number,
                        "sender": sender.lower() if sender else None,
                        "receiver": receiver.lower() if receiver else None,
                        "replay": replay,
                        "descriptor": int(key.key_descriptor_type),
                        "key_type": int(key.key_type),
                    }
                )

            handshakes.append(
                EapolHandshakeEvidence(
                    endpoint_a=endpoints[0],
                    endpoint_b=endpoints[1],
                    key_numbers=tuple(key_numbers),
                    replay_counters=tuple(replay_counters),
                    handshake_completed=self._handshake_is_complete(records),
                )
            )

        return EapolEvidence(
            total_eapol_packets=len(packets),
            handshakes=tuple(handshakes),
            handshake_completed=any(item.handshake_completed for item in handshakes),
        )

    @staticmethod
    def _iter_elements(packet: Any) -> list[Any]:
        values: list[Any] = []
        element = packet.payload
        seen: set[int] = set()
        while element is not None and id(element) not in seen:
            seen.add(id(element))
            if isinstance(element, Dot11Elt):
                values.append(element)
            element = getattr(element, "payload", None)
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
    def _parse_rsn(
        cls, body: bytes
    ) -> tuple[str | None, tuple[str, ...], tuple[str, ...], bool]:
        if len(body) < 8:
            return None, (), (), False
        version = int.from_bytes(body[0:2], "little")
        if version != 1:
            return None, (), (), False

        offset = 2
        group = cls._suite_name(body[offset:offset + 4])
        offset += 4
        if len(body) < offset + 2:
            return group, (), (), False

        pairwise_count = int.from_bytes(body[offset:offset + 2], "little")
        offset += 2
        if pairwise_count < 1 or len(body) < offset + pairwise_count * 4 + 2:
            return group, (), (), False
        pairwise = tuple(
            cls._suite_name(body[offset + index * 4:offset + (index + 1) * 4])
            for index in range(pairwise_count)
        )
        offset += pairwise_count * 4

        akm_count = int.from_bytes(body[offset:offset + 2], "little")
        offset += 2
        if akm_count < 1 or len(body) < offset + akm_count * 4:
            return group, pairwise, (), False
        akms = tuple(
            cls._suite_name(body[offset + index * 4:offset + (index + 1) * 4], akm=True)
            for index in range(akm_count)
        )
        offset += akm_count * 4

        remaining = len(body) - offset
        if remaining == 0:
            return group, pairwise, akms, True
        if remaining < 2:
            return group, pairwise, akms, False
        offset += 2  # RSN capabilities
        if offset == len(body):
            return group, pairwise, akms, True
        if len(body) - offset < 2:
            return group, pairwise, akms, False
        pmkid_count = int.from_bytes(body[offset:offset + 2], "little")
        offset += 2
        offset += pmkid_count * 16
        if offset > len(body):
            return group, pairwise, akms, False
        remaining = len(body) - offset
        return group, pairwise, akms, remaining in {0, 4}

    @classmethod
    def _beacon_details(cls, beacon: Any) -> dict[str, Any]:
        ssid = None
        channel = None
        group_cipher = None
        pairwise: tuple[str, ...] = ()
        akms: tuple[str, ...] = ()
        has_rsn = False
        rsn_valid = False

        try:
            raw_ies = bytes(beacon[Dot11Beacon].payload)
        except Exception:
            raw_ies = b""

        offset = 0
        while offset + 2 <= len(raw_ies):
            element_id = raw_ies[offset]
            element_length = raw_ies[offset + 1]
            start = offset + 2
            end = start + element_length
            if element_id == 48:
                has_rsn = True
            if end > len(raw_ies):
                if element_id == 48:
                    rsn_valid = False
                break
            info = raw_ies[start:end]
            if element_id == 0:
                ssid = info.decode("utf-8", errors="replace")
            elif element_id == 3 and info:
                channel = int(info[0])
            elif element_id == 48:
                group_cipher, pairwise, akms, rsn_valid = cls._parse_rsn(info)
            offset = end

        if not has_rsn:
            for element in cls._iter_elements(beacon):
                if getattr(element, "ID", None) == 48:
                    has_rsn = True
                    raw_element = bytes(element)
                    info = raw_element[2:] if len(raw_element) >= 2 else b""
                    group_cipher, pairwise, akms, rsn_valid = cls._parse_rsn(info)
                    break

        interval_tu = getattr(beacon[Dot11Beacon], "beacon_interval", None)
        interval_ms = float(interval_tu) * 1.024 if interval_tu is not None else None
        bssid = getattr(beacon, "addr3", None) or getattr(beacon, "addr2", None)
        return {
            "ssid": ssid,
            "bssid": bssid.lower() if isinstance(bssid, str) else bssid,
            "channel": channel,
            "has_rsn": has_rsn,
            "rsn_valid": rsn_valid,
            "group_cipher": group_cipher,
            "pairwise_ciphers": pairwise,
            "akms": akms,
            "beacon_interval_ms": interval_ms,
            "capabilities": str(beacon[Dot11Beacon].cap),
        }

    def analyze_beacon(
        self,
        pcap_path: str | Path,
        expected_ssid: str | None = None,
        expected_bssid: str | None = None,
    ) -> BeaconEvidence:
        packets = [
            packet for packet in self._load(pcap_path)
            if packet.haslayer(Dot11Beacon)
        ]
        expected_bssid_normalized = (
            expected_bssid.strip().lower() if expected_bssid else None
        )
        if not packets:
            return BeaconEvidence(
                beacon_count=0,
                ssid=None,
                bssid=None,
                channel=None,
                has_rsn=False,
                group_cipher=None,
                rsn_valid=False,
                matches_expected_ssid=expected_ssid is None,
                matches_expected_bssid=expected_bssid_normalized is None,
            )

        candidates = [(packet, self._beacon_details(packet)) for packet in packets]

        def matches(details: dict[str, Any]) -> bool:
            ssid_matches = expected_ssid is None or details["ssid"] == expected_ssid
            bssid_matches = (
                expected_bssid_normalized is None
                or details["bssid"] == expected_bssid_normalized
            )
            return ssid_matches and bssid_matches

        _beacon, details = next(
            ((packet, item) for packet, item in candidates if matches(item)),
            candidates[0],
        )
        return BeaconEvidence(
            beacon_count=len(packets),
            ssid=details["ssid"],
            bssid=details["bssid"],
            channel=details["channel"],
            has_rsn=details["has_rsn"],
            group_cipher=details["group_cipher"],
            pairwise_ciphers=details["pairwise_ciphers"],
            akms=details["akms"],
            beacon_interval_ms=details["beacon_interval_ms"],
            capabilities=details["capabilities"],
            rsn_valid=details["rsn_valid"],
            matches_expected_ssid=(
                expected_ssid is None or details["ssid"] == expected_ssid
            ),
            matches_expected_bssid=(
                expected_bssid_normalized is None
                or details["bssid"] == expected_bssid_normalized
            ),
        )

    @staticmethod
    def _dns_qname(packet: Any) -> str | None:
        dns = packet[DNS]
        if dns.qd is None or not getattr(dns.qd, "qname", None):
            return None
        return bytes(dns.qd.qname).decode("utf-8", errors="replace").rstrip(".").lower()

    @staticmethod
    def _dns_flow(packet: Any) -> tuple[str, str, int, str, int] | None:
        if IP in packet:
            source = str(packet[IP].src)
            destination = str(packet[IP].dst)
        elif IPv6 in packet:
            source = str(packet[IPv6].src)
            destination = str(packet[IPv6].dst)
        else:
            return None

        if UDP in packet:
            protocol = "udp"
            source_port = int(packet[UDP].sport)
            destination_port = int(packet[UDP].dport)
        elif TCP in packet:
            protocol = "tcp"
            source_port = int(packet[TCP].sport)
            destination_port = int(packet[TCP].dport)
        else:
            return None
        return protocol, source, source_port, destination, destination_port

    @staticmethod
    def _dns_answer_values(packet: Any) -> tuple[str, ...]:
        dns = packet[DNS]
        values: list[str] = []
        for index in range(int(dns.ancount or 0)):
            answer = dns.an[index]
            if not hasattr(answer, "rdata"):
                continue
            value = str(answer.rdata)
            try:
                values.append(str(ipaddress.ip_address(value)))
            except ValueError:
                continue
        return tuple(values)

    def analyze_dns(
        self,
        pcap_path: str | Path,
        expected_domain: str | None = None,
    ) -> DnsEvidence:
        packets = [
            packet for packet in self._load(pcap_path)
            if packet.haslayer(DNS)
        ]
        expected = expected_domain.rstrip(".").lower() if expected_domain else None
        ordered = sorted(
            enumerate(packets),
            key=lambda item: (float(getattr(item[1], "time", 0.0)), item[0]),
        )

        # Each outstanding query is uniquely identified by DNS question and
        # its transport flow. Responses must reverse that flow and arrive later.
        pending: dict[tuple[Any, ...], deque[dict[str, Any]]] = defaultdict(deque)
        transactions: list[dict[str, Any]] = []
        query_count = 0
        response_count = 0
        unmatched_responses = 0

        for _, packet in ordered:
            dns = packet[DNS]
            name = self._dns_qname(packet)
            qtype = int(dns.qd.qtype) if dns.qd is not None else 0
            if name is None:
                if expected is None:
                    if int(dns.qr) == 0:
                        query_count += 1
                    else:
                        response_count += 1
                        unmatched_responses += 1
                continue
            if expected is not None and name != expected:
                continue

            flow = self._dns_flow(packet)
            timestamp = float(getattr(packet, "time", 0.0))
            question = (int(dns.id), name, qtype)

            if int(dns.qr) == 0:
                query_count += 1
                record = {
                    "transaction_id": question[0],
                    "query_name": name,
                    "query_type": qtype,
                    "response_count": 0,
                    "answers": (),
                    "correlated": False,
                    "timestamp": timestamp,
                }
                transactions.append(record)
                if flow is None:
                    continue
                protocol, source, source_port, destination, destination_port = flow
                key = (
                    question[0], question[1], question[2],
                    protocol, source, source_port, destination, destination_port,
                )
                pending[key].append(record)
            else:
                response_count += 1
                if flow is None:
                    unmatched_responses += 1
                    continue
                protocol, source, source_port, destination, destination_port = flow
                reverse_key = (
                    question[0], question[1], question[2],
                    protocol, destination, destination_port, source, source_port,
                )
                queue = pending.get(reverse_key)
                matched = None
                if queue:
                    while queue:
                        candidate = queue[0]
                        if candidate["timestamp"] <= timestamp:
                            matched = queue.popleft()
                            break
                        queue.popleft()
                if matched is None:
                    unmatched_responses += 1
                    continue

                answers = self._dns_answer_values(packet)
                matched["response_count"] = 1
                matched["answers"] = answers
                matched["correlated"] = True

        immutable_transactions = tuple(
            DnsTransactionEvidence(
                transaction_id=item["transaction_id"],
                query_name=item["query_name"],
                query_type=item["query_type"],
                response_count=item["response_count"],
                answers=tuple(item["answers"]),
                correlated=item["correlated"],
            )
            for item in transactions
        )
        correlated = sum(item.correlated for item in immutable_transactions)
        resolved_ips = tuple(
            answer
            for item in immutable_transactions if item.correlated
            for answer in item.answers
        )
        return DnsEvidence(
            total_dns_packets=len(packets),
            query_count=query_count,
            response_count=response_count,
            correlated_transaction_count=correlated,
            unmatched_query_count=query_count - correlated,
            unmatched_response_count=unmatched_responses,
            resolved_ips=resolved_ips,
            transactions=immutable_transactions,
        )

    @staticmethod
    def write_json(evidence: Any, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = evidence.as_dict() if hasattr(evidence, "as_dict") else evidence
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return output
