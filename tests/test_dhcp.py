import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.mark.smoke
def test_dhcp_lease_assigned(connection_pool, params, metric_logger):
    """Client VM should have a valid DHCP-assigned IP address."""
    iface = params["network"]["client_interface"]
    output = connection_pool.send_command("client_vm", f"ip -4 addr show {iface}")
    match = re.search(r"inet\s+(192\.168\.\d+\.\d+)", output)
    assert match is not None, f"No DHCP IPv4 address found on client interface {iface}. Output: {output}"
    metric_logger.log(1.0, "status")


@pytest.mark.smoke
def test_dhcp_within_timeout(connection_pool, params, metric_logger):
    """DHCP renewal on client VM should complete within configured timeout threshold."""
    iface = params["network"]["client_interface"]
    timeout = params["thresholds"]["dhcp_timeout_sec"]

    start = time.time()
    connection_pool.send_command(
        "client_vm",
        f"sudo dhclient -r {iface} 2>/dev/null; sudo dhclient {iface}",
    )
    elapsed = round(time.time() - start, 2)
    metric_logger.log(elapsed, "seconds")

    output = connection_pool.send_command("client_vm", f"ip -4 addr show {iface}")
    match = re.search(r"inet\s+(192\.168\.\d+\.\d+)", output)
    assert match is not None, f"DHCP did not assign IP after renewal. Output: {output}"
    assert elapsed <= timeout, f"DHCP lease acquisition took {elapsed}s, exceeding threshold of {timeout}s"
