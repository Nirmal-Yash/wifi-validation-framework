import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

pytestmark = pytest.mark.real_lab


@pytest.mark.smoke
def test_dhcp_lease_assigned(connection_pool, params, metric_logger):
    """Client wlan0 should have the reserved lab DHCP WiFi address."""
    iface = params["network"]["client_interface"]
    expected = params["network"]["client_wifi_ip"]
    output = connection_pool.send_command("client_vm", f"ip -4 addr show {iface}")
    assert f"inet {expected}/" in output or f"inet {expected} " in output, (
        f"Expected DHCP IP {expected} on {iface}. Output: {output}"
    )
    metric_logger.log(1.0, "status")


@pytest.mark.smoke
def test_dhcp_within_timeout(connection_pool, params, metric_logger):
    """DHCP renewal on client wlan0 should complete within configured timeout."""
    iface = params["network"]["client_interface"]
    expected = params["network"]["client_wifi_ip"]
    timeout = params["thresholds"]["dhcp_timeout_sec"]

    start = time.time()
    connection_pool.send_command(
        "client_vm",
        f"sudo dhclient -r {iface} 2>/dev/null; sudo dhclient {iface}",
    )
    elapsed = round(time.time() - start, 2)
    metric_logger.log(elapsed, "seconds")

    output = connection_pool.send_command("client_vm", f"ip -4 addr show {iface}")
    assert f"inet {expected}/" in output or f"inet {expected} " in output, (
        f"DHCP did not restore {expected} after renewal. Output: {output}"
    )
    assert elapsed <= timeout, f"DHCP lease acquisition took {elapsed}s, exceeding threshold of {timeout}s"
