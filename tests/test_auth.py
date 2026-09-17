import pytest


@pytest.mark.regression
def test_wpa2_authentication(connection_pool, params, metric_logger):
    """Client should be authenticated to the AP with WPA2-PSK and state COMPLETED."""
    output = connection_pool.send_command(
        "client_vm",
        "wpa_cli -i wlan0 status 2>/dev/null || wpa_cli status",
    )
    is_completed = "wpa_state=COMPLETED" in output
    metric_logger.log(1.0 if is_completed else 0.0, "bool")

    assert is_completed, f"WPA2 4-way handshake not completed. Status output: {output}"

    ssid = params["wifi"]["ssid"]
    assert ssid in output, f"Connected SSID does not match expected '{ssid}'. Output: {output}"
