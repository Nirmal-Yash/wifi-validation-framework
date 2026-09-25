from __future__ import annotations

import re
import time

import pytest

pytestmark = pytest.mark.real_lab

from lib.services.wifi_state import assess_wifi_association
from lib.traffic import run_dns_lookup


def _runner(run_context):
    assert run_context is not None
    assert run_context.command_runner is not None
    return run_context.command_runner


def _client_output(run_context, command: str) -> str:
    return _runner(run_context).execute_shell(
        "client_vm",
        command,
        command_category="recovery.validation",
        idempotent=True,
        privilege_mode="SUDO",
    ).stdout


def _wifi_observation(run_context) -> tuple[str, str]:
    status = _client_output(
        run_context,
        "sudo wpa_cli -i wlan0 status 2>/dev/null || true",
    )
    link = _client_output(
        run_context,
        "sudo iw dev wlan0 link 2>/dev/null || true",
    )
    return status, link


def _wifi_state(run_context) -> str:
    status, link = _wifi_observation(run_context)
    return f"{status}\n--- iw link ---\n{link}"


def _wifi_connected(run_context) -> bool:
    status, link = _wifi_observation(run_context)
    expected_ssid = (
        run_context.resolved_config.get("wifi", {}).get("ssid")
        if run_context is not None
        else None
    )
    return assess_wifi_association(
        wpa_status=status,
        iw_link=link,
        expected_ssid=expected_ssid,
    ).connected


def _wait_for_wifi(run_context, *, connected: bool, timeout_sec: float) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if _wifi_connected(run_context) is connected:
            return True
        time.sleep(0.5)
    return False


def _client_ip(run_context, interface: str = "wlan0") -> str:
    output = _client_output(
        run_context,
        f"sudo ip -4 addr show {interface} 2>/dev/null || true",
    )
    match = re.search(r"inet (\d+(?:\.\d+){3})/", output)
    return match.group(1) if match else ""


def _network_id(run_context, expected_ssid: str) -> str:
    output = _client_output(
        run_context,
        "sudo wpa_cli -i wlan0 list_networks 2>/dev/null || true",
    )
    for line in output.splitlines():
        match = re.match(r"^(\d+)\s+(.*?)\s+.*$", line.strip())
        if match and match.group(2).strip() == expected_ssid:
            return match.group(1)
    raise AssertionError(
        f"Configured SSID {expected_ssid!r} was not present in wpa_cli list_networks: {output!r}"
    )


def _ping(connection_pool, router_ip: str) -> dict:
    output = connection_pool.send_command(
        "client_vm",
        f"ping -c 3 -W 2 {router_ip} 2>&1",
    )
    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    loss = float(match.group(1)) if match else 100.0
    return {"success": loss < 100.0, "packet_loss_pct": loss, "output": output}


def _assert_baseline(run_context, connection_pool, router_ip: str) -> None:
    assert _wifi_connected(run_context), f"WiFi is not connected before fault injection: {_wifi_state(run_context)}"
    baseline = _ping(connection_pool, router_ip)
    assert baseline["success"], f"Baseline WiFi connectivity is unavailable: {baseline['output']}"


@pytest.mark.regression
@pytest.mark.recovery
def test_wrong_psk_rejected_and_recovers(
    params, run_context, fault_service, connection_pool, metric_logger
):
    """A real bad PSK must disrupt authentication and the original PSK must recover it."""
    router_ip = params["network"]["router_ip"]
    ssid = params["wifi"]["ssid"]
    correct_psk = params["wifi"]["password"]
    network_id = _network_id(run_context, ssid)

    _assert_baseline(run_context, connection_pool, router_ip)
    wrong_psk = correct_psk + "_invalid"
    fault = fault_service.wrong_psk(
        interface="wlan0",
        network_id=network_id,
        wrong_psk=wrong_psk,
        correct_psk=correct_psk,
    )

    fault_applied_at = time.monotonic()
    try:
        with fault_service.context(fault):
            disrupted = _wait_for_wifi(
                run_context,
                connected=False,
                timeout_sec=max(5, params["auth"]["connection_timeout_sec"]),
            )
            metric_logger.log(1.0 if disrupted else 0.0, "bool", name="fault_observed")
            assert disrupted, f"Wrong PSK did not disrupt WPA2 state: {_wifi_state(run_context)}"
            assert not _ping(connection_pool, router_ip)["success"], "Traffic still passed with the wrong PSK"
    finally:
        recovered = _wait_for_wifi(
            run_context,
            connected=True,
            timeout_sec=max(10, params["auth"]["connection_timeout_sec"]),
        )
        recovery_seconds = time.monotonic() - fault_applied_at
        metric_logger.log(recovery_seconds, "seconds", name="recovery_time")

    assert recovered, f"Correct PSK did not restore WPA2 association: {_wifi_state(run_context)}"
    final = _ping(connection_pool, router_ip)
    assert final["success"], f"Connectivity did not recover after restoring PSK: {final}"


@pytest.mark.regression
@pytest.mark.recovery
def test_wifi_disconnect_reconnect_recovers(
    params, run_context, fault_service, connection_pool, metric_logger
):
    """A deliberate WiFi disconnect must be observable while management remains available."""
    router_ip = params["network"]["router_ip"]
    ssid = params["wifi"]["ssid"]
    network_id = _network_id(run_context, ssid)

    _assert_baseline(run_context, connection_pool, router_ip)
    fault = fault_service.wifi_disconnect(network_id=network_id)

    fault_applied_at = time.monotonic()
    with fault_service.context(fault):
        disrupted = _wait_for_wifi(
            run_context,
            connected=False,
            timeout_sec=max(5, params["auth"]["connection_timeout_sec"]),
        )
        metric_logger.log(1.0 if disrupted else 0.0, "bool", name="fault_observed")
        assert disrupted, f"WiFi disconnect did not change association state: {_wifi_state(run_context)}"
        assert not _ping(connection_pool, router_ip)["success"], "Traffic continued after explicit WiFi disconnect"

    assert _wait_for_wifi(
        run_context,
        connected=True,
        timeout_sec=max(10, params["auth"]["connection_timeout_sec"]),
    ), f"WiFi did not reconnect: {_wifi_state(run_context)}"
    recovery_seconds = time.monotonic() - fault_applied_at
    metric_logger.log(recovery_seconds, "seconds", name="recovery_time")
    final = _ping(connection_pool, router_ip)
    assert final["success"], f"Connectivity did not recover after reconnect: {final}"


@pytest.mark.smoke
@pytest.mark.recovery
def test_dhcp_renewal_preserves_reserved_address(
    params, run_context, metric_logger
):
    """A live WiFi lease can renew without changing the reserved client address."""
    expected = params["network"]["client_wifi_ip"]
    iface = params["network"]["client_interface"]
    timeout = int(params["thresholds"]["dhcp_timeout_sec"])

    before = _client_ip(run_context, iface)
    assert before == expected, f"Unexpected pre-renewal address: {before!r}"

    started = time.monotonic()
    _client_output(
        run_context,
        f"sudo dhclient -1 -timeout {timeout} {iface} 2>&1 || true",
    )
    elapsed = time.monotonic() - started
    after = _client_ip(run_context, iface)

    metric_logger.log(elapsed, "seconds", name="renewal_time")
    assert after == expected, f"DHCP renewal changed/lost the reserved address: {after!r}"


@pytest.mark.regression
@pytest.mark.recovery
def test_dhcp_server_failure_and_recovery(
    params, run_context, fault_service, metric_logger
):
    """Stopping the real dnsmasq server must remove DHCP service and restoration must re-acquire the lease."""
    expected = params["network"]["client_wifi_ip"]
    iface = params["network"]["client_interface"]
    timeout = int(params["thresholds"]["dhcp_timeout_sec"])

    assert _client_ip(run_context, iface) == expected
    fault = fault_service.dhcp_server_stop()
    fault_applied_at = time.monotonic()

    try:
        with fault_service.context(fault):
            _client_output(
                run_context,
                f"sudo dhclient -r {iface} 2>/dev/null || true",
            )
            _client_output(
                run_context,
                f"sudo dhclient -1 -timeout 3 {iface} 2>&1 || true",
            )
            disrupted = _client_ip(run_context, iface) != expected
            metric_logger.log(1.0 if disrupted else 0.0, "bool", name="fault_observed")
            assert disrupted, "Client still held the DHCP address after server interruption"
    finally:
        _client_output(
            run_context,
            f"sudo dhclient -1 -timeout {timeout} {iface} 2>&1 || true",
        )

    recovery_seconds = time.monotonic() - fault_applied_at
    metric_logger.log(recovery_seconds, "seconds", name="recovery_time")
    recovered = _client_ip(run_context, iface)
    assert recovered == expected, (
        f"DHCP service did not recover reserved address {expected}; got {recovered!r}"
    )


@pytest.mark.regression
@pytest.mark.recovery
def test_dns_failure_and_recovery(
    params, run_context, fault_service, connection_pool, metric_logger
):
    """Blocking real client DNS traffic must fail resolution and removal of the fault must restore it."""
    hostname = params["dns"]["test_hostname"]
    fault = fault_service.dns_block()

    baseline = run_dns_lookup(connection_pool, "client_vm", hostname)
    assert baseline["success"], f"Baseline DNS resolution failed: {baseline['output']}"

    fault_applied_at = time.monotonic()
    with fault_service.context(fault):
        failed_output = _client_output(
            run_context,
            f"sudo nslookup -timeout=2 -retry=1 {hostname} 2>&1 || true",
        )
        failed = (
            "server can't find" in failed_output.lower()
            or "timed out" in failed_output.lower()
            or "no servers could be reached" in failed_output.lower()
            or "connection timed out" in failed_output.lower()
        )
        metric_logger.log(1.0 if failed else 0.0, "bool", name="fault_observed")
        assert failed, f"DNS resolution unexpectedly succeeded while DNS traffic was blocked: {failed_output!r}"

    recovery_seconds = time.monotonic() - fault_applied_at
    recovered = run_dns_lookup(connection_pool, "client_vm", hostname)
    metric_logger.log(recovery_seconds, "seconds", name="recovery_time")
    assert recovered["success"], f"DNS did not recover after removing the fault: {recovered['output']}"


@pytest.mark.regression
@pytest.mark.recovery
def test_ap_restart_recovers_wifi(
    params, run_context, fault_service, connection_pool, metric_logger
):
    """Restarting the real AP process must disrupt and then restore the WiFi data path."""
    router_ip = params["network"]["router_ip"]
    _assert_baseline(run_context, connection_pool, router_ip)

    fault = fault_service.ap_restart()
    fault_applied_at = time.monotonic()
    with fault_service.context(fault):
        disrupted = _wait_for_wifi(
            run_context,
            connected=False,
            timeout_sec=8,
        ) or not _ping(connection_pool, router_ip)["success"]
        metric_logger.log(1.0 if disrupted else 0.0, "bool", name="fault_observed")
        assert disrupted, "Stopping hostapd did not disrupt the client WiFi path"

    recovered = _wait_for_wifi(
        run_context,
        connected=True,
        timeout_sec=max(12, params["auth"]["connection_timeout_sec"] + 5),
    )
    recovery_seconds = time.monotonic() - fault_applied_at
    metric_logger.log(recovery_seconds, "seconds", name="recovery_time")
    assert recovered, f"WiFi association did not recover after AP restart: {_wifi_state(run_context)}"
    final = _ping(connection_pool, router_ip)
    assert final["success"], f"Data path did not recover after AP restart: {final}"


@pytest.mark.regression
@pytest.mark.recovery
def test_client_wifi_restart_recovers(
    params, run_context, fault_service, connection_pool, metric_logger
):
    """Restarting the client wpa_supplicant must recover WiFi without losing management SSH."""
    router_ip = params["network"]["router_ip"]
    _assert_baseline(run_context, connection_pool, router_ip)

    fault = fault_service.client_wifi_restart()
    fault_applied_at = time.monotonic()
    with fault_service.context(fault):
        disrupted = _wait_for_wifi(
            run_context,
            connected=False,
            timeout_sec=8,
        )
        metric_logger.log(1.0 if disrupted else 0.0, "bool", name="fault_observed")
        assert disrupted, f"Client wpa_supplicant restart did not disrupt association: {_wifi_state(run_context)}"

    recovered = _wait_for_wifi(
        run_context,
        connected=True,
        timeout_sec=max(12, params["auth"]["connection_timeout_sec"] + 5),
    )
    _client_output(
        run_context,
        f"sudo dhclient -1 -timeout {int(params['thresholds']['dhcp_timeout_sec'])} "
        f"{params['network']['client_interface']} 2>&1 || true",
    )
    recovery_seconds = time.monotonic() - fault_applied_at
    metric_logger.log(recovery_seconds, "seconds", name="recovery_time")
    assert recovered, f"Client WiFi association did not recover: {_wifi_state(run_context)}"
    final = _ping(connection_pool, router_ip)
    assert final["success"], f"Data path did not recover after client WiFi restart: {final}"
