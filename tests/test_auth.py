import pytest


@pytest.mark.regression
def test_wpa2_authentication(connection_pool, params):
    """Client should be authenticated to the AP with WPA2."""
    output = connection_pool.send_command("client_vm", "wpa_cli -i wlan0 status 2>/dev/null || wpa_cli status")
    assert "wpa_state=COMPLETED" in output, f"WPA2 auth not completed. Output: {output}"
    ssid = params["wifi"]["ssid"]
    assert ssid in output, f"Connected SSID does not match '{ssid}'. Output: {output}"
