import pytest
from lib.connector import ssh_command
from lib.traffic import run_ping
import yaml

def test_dhcp_lease_assigned(params):
    """Client VM should get a DHCP IP in the correct subnet"""
    output = ssh_command("client_vm", "ip addr show eth0")
    assert "192.168." in output,         f"No DHCP IP found on client. Output: {output}"

def test_dhcp_within_timeout(params):
    """DHCP should assign IP within threshold seconds"""
    import time, subprocess
    start = time.time()
    subprocess.run(["sudo","dhclient","eth0"], timeout=
                   params["thresholds"]["dhcp_timeout_sec"])
    elapsed = time.time() - start
    assert elapsed < params["thresholds"]["dhcp_timeout_sec"],         f"DHCP took {elapsed:.1f}s, threshold is {params['thresholds']['dhcp_timeout_sec']}s"
