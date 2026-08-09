import pytest
import subprocess
import time

def test_chaos_network_resilience(system_config, test_params):
    """Injects packet loss and latency to validate TCP stack resilience under chaos."""
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    
    loss = test_params.get("chaos", {}).get("packet_loss_percent", "2%")
    delay = test_params.get("chaos", {}).get("latency_ms", "20ms")
    
    # Ensure IP exists realistically
    addr_check = f"sudo ip netns exec {client['namespace']} ip addr show dev {client['interface']}"
    if "inet 192.168.50." not in subprocess.run(addr_check, shell=True, capture_output=True, text=True).stdout:
        subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient {client['interface']} 2>/dev/null", shell=True)
        time.sleep(3)
    
    # Inject Chaos via TC Netem
    subprocess.run(f"sudo ip netns exec {client['namespace']} tc qdisc add dev {client['interface']} root netem loss {loss} delay {delay}", shell=True)
    
    try:
        subprocess.run("sudo killall iperf3 2>/dev/null", shell=True)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} iperf3 -s -D", shell=True, check=True)
        
        client_cmd = f"sudo ip netns exec {client['namespace']} iperf3 -c 192.168.50.1 -t 3 -J"
        res = subprocess.run(client_cmd, shell=True, capture_output=True, text=True)
        
        assert "error" not in res.stdout and "sum_received" in res.stdout, "iPerf3 TCP stream crashed critically under chaos conditions."
    finally:
        # Teardown chaos rules
        subprocess.run(f"sudo ip netns exec {client['namespace']} tc qdisc del dev {client['interface']} root 2>/dev/null", shell=True)
        subprocess.run("sudo killall iperf3 2>/dev/null", shell=True)
