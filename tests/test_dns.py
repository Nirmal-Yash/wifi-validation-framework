import pytest

from lib.traffic import run_dns_lookup


@pytest.mark.smoke
def test_dns_resolution(connection_pool, params):
    """Client VM should resolve the configured hostname."""
    hostname = params["dns"]["test_hostname"]
    result = run_dns_lookup(connection_pool, "client_vm", hostname)
    assert result["success"], f"DNS lookup failed for {hostname}. Output: {result['output']}"
    assert result["resolved_ip"], "No IP address returned from DNS lookup"
