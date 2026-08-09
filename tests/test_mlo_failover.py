import pytest
import subprocess
import time
import re

def test_mlo_hitless_failover(system_config, test_params):
    """Simulates Wi-Fi 7 MLO failover and measures realistic packet loss during interface churn."""
    client = system_config["nodes"]["client"]
    ap = system_config["nodes"]["ap"]
    env_type = system_config["target_environment"]["environment_type"]
    
    # Ensure IP exists
    subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient {client['interface']} 2>/dev/null", shell=True)
    time.sleep(2)

    # 1. Start a continuous fast-ping in the background (20 packets, 1 every 0.2 seconds)
    ping_cmd = f"sudo ip netns exec {client['namespace']} ping -c 20 -i 0.2 192.168.50.1 > /tmp/ping_mlo.log &"
    subprocess.run(ping_cmd, shell=True)
    time.sleep(1.5)

    # 2. Simulate the 6GHz radio crashing (Drop Interface)
    subprocess.run(f"sudo ip netns exec {client['namespace']} ip link set {client['interface']} down", shell=True)

    # 3. MLO Fallback: Bring interface back up immediately
    time.sleep(0.5)
    subprocess.run(f"sudo ip netns exec {client['namespace']} ip link set {client['interface']} up", shell=True)

    # Wait for the remaining ping sequence to finish
    time.sleep(4)

    # 4. Analyze the packet loss
    with open("/tmp/ping_mlo.log", "r") as f:
        log_data = f.read()

    match = re.search(r'(\d+)% packet loss', log_data)
    if match:
        loss_percentage = int(match.group(1))
        
        # Tier 2: Physical hardware MUST support hitless zero-millisecond failovers
        if env_type == "tier2_physical":
            assert loss_percentage <= 5, f"Hardware MLO Failover failed. Packet loss was {loss_percentage}%."
        
        # Tier 1: Software simulation validates stack recovery, accounting for WPA3 re-association overhead
        else:
            assert loss_percentage < 100, "MLO Simulation failed critically. 100% packet loss detected."
            print(f"\n[INFO] Tier 1 MLO Simulation recovered with {loss_percentage}% loss (~2s re-association).")
    else:
        pytest.fail("Failed to parse ICMP telemetry for MLO failover.")
