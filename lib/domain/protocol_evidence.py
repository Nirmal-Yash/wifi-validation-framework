from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DhcpTransactionEvidence:
    xid: int
    client_mac: str | None
    message_types: tuple[str, ...]
    has_dora: bool
    is_renewal: bool = False
    is_rebind: bool = False
    offered_ip: str | None = None
    acknowledged_ip: str | None = None
    server_identifier: str | None = None
    renewal_time_seconds: int | None = None
    rebinding_time_seconds: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DhcpEvidence:
    total_packets: int
    message_counts: Mapping[str, int]
    transactions: tuple[DhcpTransactionEvidence, ...]
    correlated_dora_count: int
    correlated_renewal_count: int
    correlated_rebind_count: int
    has_dora: bool
    has_renewal: bool
    has_rebind: bool
    has_lease_acquired: bool

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["transactions"] = [item.as_dict() for item in self.transactions]
        return data


@dataclass(frozen=True, slots=True)
class EapolHandshakeEvidence:
    endpoint_a: str | None
    endpoint_b: str | None
    key_numbers: tuple[int, ...]
    replay_counters: tuple[int, ...]
    handshake_completed: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EapolEvidence:
    total_eapol_packets: int
    handshakes: tuple[EapolHandshakeEvidence, ...]
    handshake_completed: bool

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["handshakes"] = [item.as_dict() for item in self.handshakes]
        return data


@dataclass(frozen=True, slots=True)
class BeaconEvidence:
    beacon_count: int
    ssid: str | None
    bssid: str | None
    channel: int | None
    has_rsn: bool
    group_cipher: str | None
    pairwise_ciphers: tuple[str, ...] = ()
    akms: tuple[str, ...] = ()
    beacon_interval_ms: float | None = None
    capabilities: str | None = None
    matches_expected_ssid: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DnsTransactionEvidence:
    transaction_id: int
    query_name: str
    query_type: int
    response_count: int
    answers: tuple[str, ...]
    correlated: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DnsEvidence:
    total_dns_packets: int
    query_count: int
    response_count: int
    correlated_transaction_count: int
    unmatched_query_count: int
    unmatched_response_count: int
    resolved_ips: tuple[str, ...]
    transactions: tuple[DnsTransactionEvidence, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["transactions"] = [item.as_dict() for item in self.transactions]
        return data
