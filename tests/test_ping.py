import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

pytestmark = pytest.mark.real_lab


def client_ping(connection_pool, router_ip, count):
    output = connection_pool.send_command(
        "client_vm",
        f"ping -c {count} -W 3 {router_ip} 2>&1",
    )
    loss_match = re.search(r"(\d+(?:\.\d+)?)% packet loss", output)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    rtt_match = re.search(r"rtt min/avg/max/(?:mdev|stddev)\s*=\s*[\d.]+/([\d.]+)/", output, re.IGNORECASE)
    avg = float(rtt_match.group(1)) if rtt_match else None
    return {"success": loss < 100.0, "packet_loss_pct": loss, "avg_rtt_ms": avg, "output": output}


@pytest.mark.perf
def test_ping_success(params, connection_pool, metric_logger):
    router_ip = params["network"]["router_ip"]
    result = client_ping(connection_pool, router_ip, 5)
    metric_logger.log(1.0 if result["success"] else 0.0, "bool")
    assert result["success"], f"Client WiFi ping to router {router_ip} failed: {result['output']}"


@pytest.mark.perf
def test_packet_loss_within_threshold(params, connection_pool, metric_logger):
    router_ip = params["network"]["router_ip"]
    result = client_ping(connection_pool, router_ip, 20)
    loss = result["packet_loss_pct"]
    metric_logger.log(loss, "%")
    threshold = params["thresholds"]["max_packet_loss_pct"]
    assert loss <= threshold, f"Client WiFi packet loss of {loss}% exceeds threshold {threshold}%"


@pytest.mark.perf
def test_latency_within_threshold(params, connection_pool, metric_logger):
    router_ip = params["network"]["router_ip"]
    result = client_ping(connection_pool, router_ip, 10)
    rtt = result["avg_rtt_ms"]
    assert rtt is not None, f"Could not parse client WiFi average RTT: {result['output']}"
    metric_logger.log(rtt, "ms")
    threshold = params["thresholds"]["max_latency_ms"]
    assert rtt <= threshold, f"Client WiFi latency of {rtt}ms exceeds threshold {threshold}ms"
