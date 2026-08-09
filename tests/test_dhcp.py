import pytest
import subprocess
import time

def test_dhcp_lease_allocation(system_config, test_params, async_sniffer, fw_version):
    client = system_config["nodes"]["client"]
    
    # SIMULATED FIRMWARE BUG: Break DHCP exclusively for firmware v1.0.1
    if fw_version == "1.0.1":
        print("\n[!] Simulated Firmware Bug Triggered: Crashing DHCP daemon...")
        subprocess.run(f"sudo ip netns exec {client['namespace']} ip addr flush dev {client['interface']}", shell=True)
        time.sleep(1)
        addr_check = f"sudo ip netns exec {client['namespace']} ip addr show dev {client['interface']}"
        addr_out = subprocess.run(addr_check, shell=True, capture_output=True, text=True).stdout
        assert "inet 192.168.50." in addr_out, "Client failed to obtain an IP lease from DHCP server (Simulated Regression)"
        return

    # Normal execution for v1.0.0 Baseline
    subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient -r {client['interface']} 2>/dev/null", shell=True)
    subprocess.run(f"sudo ip netns exec {client['namespace']} ip addr flush dev {client['interface']}", shell=True)
    
    dhcp_cmd = f"sudo ip netns exec {client['namespace']} dhclient -1 -v {client['interface']}"
    subprocess.run(dhcp_cmd, shell=True, capture_output=True)
    
    addr_check = f"sudo ip netns exec {client['namespace']} ip addr show dev {client['interface']}"
    addr_out = subprocess.run(addr_check, shell=True, capture_output=True, text=True).stdout
    
    assert "inet 192.168.50." in addr_out, "Client failed to obtain an IP lease from DHCP server"
