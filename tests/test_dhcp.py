import pytest

from lib.connector import ssh_command


@pytest.mark.smoke
def test_dhcp_lease_assigned(connection_pool, params):
    """Client VM should have a DHCP-assigned IP in the expected subnet."""
    iface = params["network"]["client_interface"]
    output = connection_pool.send_command("client_vm", f"ip addr show {iface}")
    assert "inet 192.168." in output, f"No DHCP IP found on client. Output: {output}"


@pytest.mark.smoke
def test_dhcp_within_timeout(connection_pool, params):
    """DHCP renewal on client VM should complete within threshold."""
    import time

    iface = params["network"]["client_interface"]
    timeout = params["thresholds"]["dhcp_timeout_sec"]
    start = time.time()
    connection_pool.send_command("client_vm", f"sudo dhclient -r {iface} 2>/dev/null; sudo dhclient {iface}")
    elapsed = time.time() - start
    output = connection_pool.send_command("client_vm", f"ip addr show {iface}")
    assert "inet 192.168." in output, f"DHCP did not assign IP. Output: {output}"
    assert elapsed < timeout, f"DHCP took {elapsed:.1f}s, threshold is {timeout}s"
