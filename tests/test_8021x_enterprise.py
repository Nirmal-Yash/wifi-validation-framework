import pytest
import subprocess
import time
import os

def test_enterprise_8021x_authentication(system_config):
    """Validates WPA-Enterprise (EAP-PEAP) authentication handshakes."""
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    
    abs_ap_ent_config = os.path.abspath("config/hostapd_enterprise.conf")
    abs_client_ent_config = os.path.abspath("config/wpa_supplicant_enterprise.conf")
    
    try:
        # 1. Swap Daemons to Enterprise Mode
        subprocess.run("sudo killall hostapd wpa_supplicant 2>/dev/null", shell=True)
        time.sleep(1)
        
        ap_cmd = f"sudo ip netns exec {ap['namespace']} hostapd {abs_ap_ent_config}"
        subprocess.Popen(ap_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        
        # 2. Start Enterprise Client
        client_cmd = f"sudo ip netns exec {client['namespace']} wpa_supplicant -B -i {client['interface']} -c {abs_client_ent_config}"
        subprocess.run(client_cmd, shell=True)
        
        # 3. Await Authentication
        connected = False
        for _ in range(15):
            status = subprocess.run(
                f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} status", 
                shell=True, capture_output=True, text=True
            ).stdout
            if "wpa_state=COMPLETED" in status and "EAP-PEAP" in status:
                connected = True
                break
            time.sleep(1)
            
        assert connected, "Client failed to authenticate via WPA2-Enterprise EAP-PEAP."

    finally:
        # 4. Restore Standard Personal Mode for Subsequent Tests
        subprocess.run("sudo killall hostapd wpa_supplicant 2>/dev/null", shell=True)
        time.sleep(1)
        
        abs_ap_std = os.path.abspath(ap['config_path'])
        subprocess.Popen(f"sudo ip netns exec {ap['namespace']} hostapd {abs_ap_std}".split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        
        abs_client_std = os.path.abspath(client['config_path'])
        subprocess.run(f"sudo ip netns exec {client['namespace']} wpa_supplicant -B -i {client['interface']} -c {abs_client_std}", shell=True)
        
        # 5. CRITICAL FIX: Block test completion until Personal network is fully restored
        for _ in range(15):
            status = subprocess.run(
                f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} status", 
                shell=True, capture_output=True, text=True
            ).stdout
            if "wpa_state=COMPLETED" in status:
                break
            time.sleep(1)
            
        time.sleep(2)  # Allow DHCP extra settlement time before the next test begins
