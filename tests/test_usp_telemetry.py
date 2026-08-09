import pytest
import subprocess
import time
import os
from scapy.all import rdpcap, Dot11Beacon

def test_usp_radio_disable_command(system_config):
    """Simulates an ISP TR-369 USP command disabling the SSID and validates daemon silence."""
    ap = system_config["nodes"]["ap"]
    monitor = system_config["nodes"]["monitor"]
    pcap_file = "/tmp/telemetry_test.pcap"
    
    if os.path.exists(pcap_file):
        os.remove(pcap_file)
        
    # 1. Align Monitor Interface to AP Channel (Channel 6) to capture 802.11 Management Frames
    subprocess.run(f"sudo ip netns exec {monitor['namespace']} iw dev {monitor['interface']} set channel 6", shell=True)
    
    # 2. Start continuous capture on the Monitor interface (Unbuffered -U)
    cmd = ["sudo", "ip", "netns", "exec", monitor['namespace'], "tcpdump", "-i", monitor['interface'], "-w", pcap_file, "-U"]
    sniffer = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait for the sniffer to capture baseline beacon traffic
    time.sleep(3)
    
    # 3. Simulate TR-369 Protobuf command to kill radio
    print("\n[*] Sending TR-369 USP Set: Device.WiFi.Radio.1.Enable = False")
    subprocess.run(f"sudo ip netns exec {ap['namespace']} killall hostapd", shell=True)
    time.sleep(1)
    
    # 4. Check if the daemon successfully died to enforce radio silence
    pid_check = subprocess.run(f"sudo ip netns exec {ap['namespace']} pgrep hostapd", shell=True, capture_output=True).stdout
    assert not pid_check, "TR-369 Command failed! hostapd daemon bypassed the kill signal and is still running."
    
    # 5. Gracefully terminate tcpdump
    subprocess.run(f"sudo pkill -f 'tcpdump -i {monitor['interface']}'", shell=True)
    try:
        sniffer.wait(timeout=3)
    except subprocess.TimeoutExpired:
        subprocess.run(["sudo", "kill", "-9", str(sniffer.pid)])
    
    # 6. Read PCAP safely
    try:
        packets = rdpcap(pcap_file)
        beacons = [pkt for pkt in packets if pkt.haslayer(Dot11Beacon)]
        
        # We ensure beacons were captured initially, proving the radio was active before the kill command
        assert len(beacons) > 0, "No initial beacons detected; monitor interface failed to capture 802.11 frames."
    except Exception as e:
        pytest.fail(f"Failed to analyze telemetry PCAP data: {e}")
