import pytest
from lib.traffic import run_iperf3

IPERF_SERVER = "192.168.122.10"

def test_throughput_meets_minimum(params):
    result = run_iperf3(IPERF_SERVER, duration=10)
    minimum = params["thresholds"]["min_throughput_mbps"]
    assert result["throughput_mbps"] >= minimum,         f"Throughput {result['throughput_mbps']} Mbps is below minimum {minimum} Mbps"
