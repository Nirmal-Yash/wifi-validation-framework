import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from lib.traffic import run_ping


@pytest.mark.perf
def test_ping_success(params, metric_logger):
    """Router must be reachable with ICMP echo requests."""
    router_ip = params["network"]["router_ip"]
    result = run_ping(router_ip, count=5)
    metric_logger.log(1.0 if result["success"] else 0.0, "bool")
    assert result["success"], f"Ping to router {router_ip} failed completely. Output: {result.get('stdout')}"


@pytest.mark.perf
def test_packet_loss_within_threshold(params, metric_logger):
    """Packet loss to router should remain below the configured maximum percentage threshold."""
    router_ip = params["network"]["router_ip"]
    result = run_ping(router_ip, count=20)
    loss = result["packet_loss_pct"]
    metric_logger.log(loss, "%")

    threshold = params["thresholds"]["max_packet_loss_pct"]
    assert loss <= threshold, f"Packet loss of {loss}% exceeds allowable threshold of {threshold}%"


@pytest.mark.perf
def test_latency_within_threshold(params, metric_logger):
    """Average RTT latency to router should remain within acceptable threshold."""
    router_ip = params["network"]["router_ip"]
    result = run_ping(router_ip, count=10)
    rtt = result["avg_rtt_ms"]

    assert rtt is not None, f"Could not parse average RTT from ping output: {result.get('stdout')}"
    metric_logger.log(rtt, "ms")

    threshold = params["thresholds"]["max_latency_ms"]
    assert rtt <= threshold, f"Latency of {rtt}ms exceeds threshold of {threshold}ms"
