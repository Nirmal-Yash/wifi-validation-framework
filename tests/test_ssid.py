import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.mark.smoke
def test_ssid_visible(connection_pool, params, metric_logger):
    """Configured SSID should appear in client WiFi scan results."""
    ssid = params["wifi"]["ssid"]
    # Ensure interface is UP, then trigger scan via iw or iwlist
    scan_cmd = (
        "sudo ip link set wlan0 up 2>/dev/null; "
        "sudo iw dev wlan0 scan 2>/dev/null | grep -i 'SSID:' || "
        "sudo iwlist wlan0 scan 2>/dev/null | grep -i 'ESSID:'"
    )
    output = connection_pool.send_command("client_vm", scan_cmd)
    found = ssid in output
    metric_logger.log(1.0 if found else 0.0, "bool")
    assert found, f"SSID '{ssid}' not found in scan results. Output: {output[:500]}"
