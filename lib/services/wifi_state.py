from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class WifiAssociation:
    connected: bool
    ssid: str | None
    bssid: str | None
    wpa_state: str | None
    key_mgmt: str | None
    pairwise_cipher: str | None
    group_cipher: str | None


def _status_fields(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def _iw_fields(output: str) -> tuple[str | None, str | None]:
    bssid_match = re.search(
        r"^Connected to ([0-9a-f:]{17})",
        output,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    ssid_match = re.search(
        r"^\s*SSID:\s*(.+?)\s*$",
        output,
        flags=re.MULTILINE,
    )
    return (
        bssid_match.group(1).lower() if bssid_match else None,
        ssid_match.group(1).strip() if ssid_match else None,
    )


def assess_wifi_association(
    *,
    wpa_status: str,
    iw_link: str,
    expected_ssid: str | None = None,
    require_wpa2: bool = False,
) -> WifiAssociation:
    """Derive Wi-Fi association from both control-plane and driver state.

    wpa_cli status is authoritative when it explicitly reports wpa_state.
    Some deployed wpa_cli/transport combinations omit that field even though
    the driver reports an active association, so the driver link is used as a
    controlled fallback in that case.
    """
    fields = _status_fields(wpa_status)
    bssid, link_ssid = _iw_fields(iw_link)
    wpa_state = fields.get("wpa_state")
    status_ssid = fields.get("ssid")

    if expected_ssid is not None:
        ssid_matches = (
            (not status_ssid or status_ssid == expected_ssid)
            and (not link_ssid or link_ssid == expected_ssid)
        )
    else:
        ssid_matches = True

    driver_connected = bssid is not None
    if wpa_state is not None:
        connected = wpa_state.upper() == "COMPLETED"
    else:
        connected = driver_connected

    if not ssid_matches:
        connected = False

    if require_wpa2:
        key_mgmt = fields.get("key_mgmt", "").upper()
        pairwise = fields.get("pairwise_cipher", "").upper()
        group = fields.get("group_cipher", "").upper()
        security_ok = (
            key_mgmt in {"WPA2-PSK", "WPA-PSK"}
            and pairwise == "CCMP"
            and group == "CCMP"
        )
        connected = connected and driver_connected and security_ok

    return WifiAssociation(
        connected=connected,
        ssid=status_ssid or link_ssid,
        bssid=fields.get("bssid") or bssid,
        wpa_state=wpa_state,
        key_mgmt=fields.get("key_mgmt"),
        pairwise_cipher=fields.get("pairwise_cipher"),
        group_cipher=fields.get("group_cipher"),
    )
