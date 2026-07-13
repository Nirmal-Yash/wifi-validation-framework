import pytest


@pytest.mark.smoke
def test_ssid_visible(connection_pool, params):
    """Configured SSID should appear in client WiFi scan results."""
    ssid = params["wifi"]["ssid"]
    output = connection_pool.send_command("client_vm", "sudo iwlist wlan0 scan 2>/dev/null || iw dev")
    assert ssid in output, f"SSID '{ssid}' not found in scan. Output: {output[:500]}"
