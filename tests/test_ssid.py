import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.mark.smoke
def test_ssid_visible(connection_pool, params, metric_logger):
    """Configured SSID should be visible on the active WiFi link (non-destructive)."""
    ssid = params["wifi"]["ssid"]
    output = connection_pool.send_command(
        "client_vm",
        "wpa_cli -i wlan0 status 2>/dev/null; iw dev wlan0 link 2>/dev/null",
    )
    found = ssid in output and "wpa_state=COMPLETED" in output
    metric_logger.log(1.0 if found else 0.0, "bool")
    assert found, f"SSID '{ssid}' not active on wlan0. Output: {output[:500]}"
