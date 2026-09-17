import pytest

from lib.traffic import run_dns_lookup


@pytest.mark.smoke
def test_dns_resolution(connection_pool, params, metric_logger):
    """Client VM should resolve configured domain name into valid IP address."""
    hostname = params["dns"]["test_hostname"]
    result = run_dns_lookup(connection_pool, "client_vm", hostname)

    metric_logger.log(1.0 if result["success"] else 0.0, "bool")

    assert result["success"], f"DNS lookup failed for {hostname}. Output:\n{result['output']}"
    assert result["resolved_ip"] is not None, f"No IP address resolved for {hostname}"
