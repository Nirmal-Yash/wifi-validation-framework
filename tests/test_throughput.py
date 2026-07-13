import pytest

from lib.traffic import run_iperf3, run_iperf3_via_ssh

IPERF_SERVER = "192.168.122.10"


@pytest.mark.perf
def test_throughput_meets_minimum(params, connection_pool):
    minimum = params["thresholds"]["min_throughput_mbps"]
    try:
        result = run_iperf3_via_ssh(connection_pool, "client_vm", IPERF_SERVER, duration=10)
    except Exception:
        result = run_iperf3(IPERF_SERVER, duration=10)
    assert result["throughput_mbps"] >= minimum, (
        f"Throughput {result['throughput_mbps']} Mbps is below minimum {minimum} Mbps"
    )
