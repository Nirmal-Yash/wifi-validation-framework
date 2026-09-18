import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from lib.fault_injector import clear_conditions, fault_context, link_down, link_up


def client_ping(connection_pool, router_ip, count=3):
    output = connection_pool.send_command("client_vm", f"ping -c {count} {router_ip} 2>&1")
    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    loss = float(match.group(1)) if match else 100.0
    return {"success": loss < 100.0, "packet_loss_pct": loss, "output": output}


@pytest.mark.regression
def test_fault_injection_link_down_up(params, connection_pool, metric_logger):
    """Disrupt the real WiFi interface while SSH management stays on eth1."""
    router_ip = params["network"]["router_ip"]
    iface = params["network"]["client_interface"]
    assert iface == "wlan0", "Real fault injection requires client_interface=wlan0"

    baseline = client_ping(connection_pool, router_ip, 3)
    assert baseline["success"], (
        f"Baseline client WiFi connectivity to {router_ip} unavailable: {baseline['output']}"
    )

    def do_down():
        link_down(iface, pool=connection_pool, device="client_vm")

    def do_up():
        link_up(iface, pool=connection_pool, device="client_vm")
        clear_conditions(iface, pool=connection_pool, device="client_vm")
        connection_pool.send_command("client_vm", "wpa_cli -i wlan0 reconnect 2>/dev/null || true")

    with fault_context(do_down, do_up):
        down_result = client_ping(connection_pool, router_ip, 3)
        assert (not down_result["success"] or down_result["packet_loss_pct"] > 50), (
            f"WiFi traffic was not disrupted: {down_result}"
        )

    time.sleep(2)
    recovered = client_ping(connection_pool, router_ip, 3)
    metric_logger.log(recovered["packet_loss_pct"], "%")
    assert recovered["success"], f"WiFi connectivity did not recover: {recovered}"
