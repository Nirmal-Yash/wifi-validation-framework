import pytest

from lib.traffic import run_iperf3_via_ssh


@pytest.mark.perf
def test_throughput_meets_minimum(params, connection_pool, metric_logger):
    """Client VM to Router throughput must satisfy minimum Mbps bandwidth requirement."""
    minimum = params["thresholds"]["min_throughput_mbps"]
    router_ip = params["network"]["router_ip"]

    # Execute on client_vm over SSH — no silent local fallback
    result = run_iperf3_via_ssh(connection_pool, "client_vm", router_ip, duration=10)

    throughput = result["throughput_mbps"]
    metric_logger.log(throughput, "Mbps")

    assert throughput >= minimum, (
        f"Measured throughput {throughput} Mbps is below minimum threshold of {minimum} Mbps"
    )
