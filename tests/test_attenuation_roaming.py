import pytest
import subprocess
import time

def test_dynamic_signal_attenuation(system_config, test_params):
    """Drops AP transmit power and realistically validates client background scanning behavior."""
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    tx_power_low = test_params.get("attenuation", {}).get("tx_power_low_mbm", 100)
    
    # 1. Verify baseline connection
    status_cmd = f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} status"
    assert "wpa_state=COMPLETED" in subprocess.run(status_cmd, shell=True, capture_output=True, text=True).stdout
    
    try:
        # 2. Simulate moving away from the AP (Drop TX Power)
        subprocess.run(f"sudo ip netns exec {ap['namespace']} iw dev {ap['interface']} set txpower fixed {tx_power_low}", shell=True)
        time.sleep(2) # Give kernel time to process RF change
        
        # 3. Trigger roaming scan
        subprocess.run(f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} scan", shell=True)
        
        # 4. Realistic polling loop (Hardware scans take 3-5 seconds)
        ssid_found = False
        for _ in range(10):
            time.sleep(1)
            results_out = subprocess.run(f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} scan_results", shell=True, capture_output=True, text=True).stdout
            if "NetForge_Test" in results_out:
                ssid_found = True
                break
                
        assert ssid_found, "Client failed to detect the SSID during background roaming scan."
    finally:
        # Restore AP power
        subprocess.run(f"sudo ip netns exec {ap['namespace']} iw dev {ap['interface']} set txpower auto", shell=True)
