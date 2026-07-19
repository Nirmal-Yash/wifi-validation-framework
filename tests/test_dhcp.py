import pytest
import subprocess

def test_dhcp_lease_allocation(system_config, test_params, async_sniffer):
    client = system_config["nodes"]["client"]
    subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient -r {client['interface']} 2>/dev/null", shell=True)
    subprocess.run(f"sudo ip netns exec {client['namespace']} ip addr flush dev {client['interface']}", shell=True)
    
    dhcp_cmd = f"sudo ip netns exec {client['namespace']} dhclient -1 -v {client['interface']}"
    subprocess.run(dhcp_cmd, shell=True, capture_output=True)
    
    addr_check = f"sudo ip netns exec {client['namespace']} ip addr show dev {client['interface']}"
    addr_out = subprocess.run(addr_check, shell=True, capture_output=True, text=True).stdout
    assert "inet 192.168.50." in addr_out, "Client failed to obtain an IP lease from DHCP server"
