import pytest

from lib.traffic import run_ping


ROUTER_IP = "192.168.122.10"


@pytest.mark.perf
def test_ping_success(params):
    result = run_ping(ROUTER_IP)
    assert result["success"], "Ping to router failed"


@pytest.mark.perf
def test_packet_loss_within_threshold(params):
    result = run_ping(ROUTER_IP, count=20)
    threshold = params["thresholds"]["max_packet_loss_pct"]
    assert result["packet_loss_pct"] <= threshold, (
        f"Packet loss {result['packet_loss_pct']}% exceeds {threshold}%"
    )


@pytest.mark.perf
def test_latency_within_threshold(params):
    result = run_ping(ROUTER_IP)
    threshold = params["thresholds"]["max_latency_ms"]
    assert result["avg_rtt_ms"] is not None, "Could not parse RTT from ping output"
    assert result["avg_rtt_ms"] <= threshold, (
        f"Latency {result['avg_rtt_ms']}ms exceeds {threshold}ms"
    )
