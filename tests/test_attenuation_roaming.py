import pytest
import subprocess
import time

def test_dynamic_signal_attenuation(system_config, test_params):
    """Drops AP transmit power and validates client signal polling and scanning behavior."""
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    tx_power_low = test_params["attenuation"]["tx_power_low_mbm"]
    
    # 1. Verify baseline connection state
    status_cmd = f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} status"
    status_out = subprocess.run(status_cmd, shell=True, capture_output=True, text=True).stdout
    assert "wpa_state=COMPLETED" in status_out, "Client is not connected prior to attenuation."
    
    try:
        # 2. Drop AP Transmit Power to 1.00 dBm (100 mBm)
        drop_power_cmd = f"sudo ip netns exec {ap['namespace']} iw dev {ap['interface']} set txpower fixed {tx_power_low}"
        subprocess.run(drop_power_cmd, shell=True)
        time.sleep(1)
        
        # 3. Trigger a scan request on client to verify active scanning under low signal
        scan_cmd = f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} scan"
        scan_res = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True).stdout
        assert "OK" in scan_res, "Client failed to initiate background scan under attenuated signal."
        
        time.sleep(2)
        scan_results_cmd = f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} scan_results"
        results_out = subprocess.run(scan_results_cmd, shell=True, capture_output=True, text=True).stdout
        assert "StyleFusion_Secure_IoT" in results_out, "SSID not found in scan results during signal attenuation."
        
    finally:
        # 4. Restore AP Transmit Power to auto
        restore_power_cmd = f"sudo ip netns exec {ap['namespace']} iw dev {ap['interface']} set txpower auto"
        subprocess.run(restore_power_cmd, shell=True)
