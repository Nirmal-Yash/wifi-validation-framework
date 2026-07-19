import pytest
import subprocess
import time
from scapy.all import rdpcap, Dot11AssoReq

def test_wpa3_sae_association(system_config, test_params, async_sniffer):
    client = system_config["nodes"]["client"]
    subprocess.run(f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} disconnect", shell=True, capture_output=True)
    time.sleep(1)
    subprocess.run(f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} reconnect", shell=True, capture_output=True)
    
    timeout = test_params["timeouts"]["wpa_association_seconds"]
    connected = False
    for _ in range(timeout * 2):
        status_cmd = f"sudo ip netns exec {client['namespace']} wpa_cli -i {client['interface']} status"
        status_out = subprocess.run(status_cmd, shell=True, capture_output=True, text=True).stdout
        if "wpa_state=COMPLETED" in status_out:
            connected = True
            break
        time.sleep(0.5)
    assert connected, "Client failed to authenticate and complete the connection."
