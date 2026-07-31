import pytest
import subprocess
import time
import json

def test_chaos_network_resilience(system_config, test_params):
    """Injects packet loss and latency to validate TCP stack resilience under chaos."""
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    
    loss = test_params["chaos"]["packet_loss_percent"]
    delay = test_params["chaos"]["latency_ms"]
    floor_mbps = test_params["chaos"]["throughput_floor_mbps"]
    
    # Failsafe: Ensure IP exists
    addr_check = f"sudo ip netns exec {client['namespace']} ip addr show dev {client['interface']}"
    if "inet 192.168.50." not in subprocess.run(addr_check, shell=True, capture_output=True, text=True).stdout:
        subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient {client['interface']}", shell=True)
        time.sleep(2)
        
    # Inject Chaos via TC Netem on client interface
    chaos_cmd = f"sudo ip netns exec {client['namespace']} tc qdisc add dev {client['interface']} root netem loss {loss} delay {delay}"
    subprocess.run(chaos_cmd, shell=True)
    
    try:
        subprocess.run("sudo killall iperf3 2>/dev/null", shell=True)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} iperf3 -s -D", shell=True, check=True)
        time.sleep(0.5)
        
        client_cmd = f"sudo ip netns exec {client['namespace']} iperf3 -c 192.168.50.1 -J -t 4"
        client_run = subprocess.run(client_cmd, shell=True, capture_output=True, text=True)
        
        assert client_run.returncode == 0, "Network completely crashed under chaos conditions."
        
        parsed_results = json.loads(client_run.stdout)
        actual_throughput_mbps = parsed_results["end"]["sum_received"]["bits_per_second"] / 1_000_000.0
        
        assert actual_throughput_mbps >= floor_mbps, (
            f"Throughput degraded too severely ({actual_throughput_mbps:.2f} Mbps) "
            f"below the chaos survival floor ({floor_mbps} Mbps)."
        )
        
    finally:
        # Clean up tc rules
        cleanup_cmd = f"sudo ip netns exec {client['namespace']} tc qdisc del dev {client['interface']} root 2>/dev/null"
        subprocess.run(cleanup_cmd, shell=True)
        subprocess.run("sudo killall iperf3 2>/dev/null", shell=True)
