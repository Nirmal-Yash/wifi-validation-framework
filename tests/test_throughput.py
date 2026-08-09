import pytest
import subprocess
import time

def test_data_plane_throughput(system_config, test_params):
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    
    # Ensure IP exists before running iperf3
    addr_check = f"sudo ip netns exec {client['namespace']} ip addr show dev {client['interface']}"
    addr_out = subprocess.run(addr_check, shell=True, capture_output=True, text=True).stdout
    if "inet 192.168.50." not in addr_out:
        subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient {client['interface']}", shell=True)
        time.sleep(2)
        
    subprocess.run("sudo killall iperf3 2>/dev/null", shell=True)
    time.sleep(0.5)
    
    server_cmd = f"sudo ip netns exec {ap['namespace']} iperf3 -s -D"
    subprocess.run(server_cmd, shell=True, check=True)
    
    client_cmd = f"sudo ip netns exec {client['namespace']} iperf3 -c 192.168.50.1 -t 3 -J"
    res = subprocess.run(client_cmd, shell=True, capture_output=True, text=True)
    
    subprocess.run("sudo killall iperf3 2>/dev/null", shell=True)
    assert "error" not in res.stdout, "Throughput test failed to execute properly."
