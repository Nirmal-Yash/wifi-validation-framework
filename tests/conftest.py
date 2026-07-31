import pytest
import yaml
import subprocess
import time
import os
import sqlite3

def pytest_addoption(parser):
    parser.addoption("--fw-version", action="store", default="1.0.0", help="Target firmware")

@pytest.fixture(scope="session")
def fw_version(request):
    return request.config.getoption("--fw-version")

@pytest.fixture(scope="session")
def system_config():
    with open("config/devices.yaml", "r") as f:
        return yaml.safe_load(f)

@pytest.fixture(scope="session")
def test_params():
    with open("config/test_params.yaml", "r") as f:
        return yaml.safe_load(f)

@pytest.fixture(scope="session", autouse=True)
def ensure_firmware_record(fw_version):
    with sqlite3.connect("db/results.db", timeout=10) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("INSERT OR IGNORE INTO firmware_metadata (firmware_version) VALUES (?)", (fw_version,))
        conn.commit()

def get_phy_name(wlan_iface):
    """Dynamically queries the Linux sysfs tree to map wlanX to its underlying phyX name."""
    try:
        with open(f"/sys/class/net/{wlan_iface}/phy80211/name", "r") as f:
            return f.read().strip()
    except Exception:
        return None

@pytest.fixture(scope="session", autouse=True)
def lifecycle_management(system_config):
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    monitor = system_config["nodes"]["monitor"]
    
    # 1. Clean slate and build Enterprise Topology
    subprocess.run("sudo ./scripts/teardown_topology.sh", shell=True)
    subprocess.run("sudo modprobe mac80211_hwsim radios=3", shell=True)
    time.sleep(2)
    subprocess.run("sudo ./scripts/setup_enterprise_topology.sh", shell=True)
    
    # 2. Dynamically resolve PHY names from the host kernel
    phy_ap = get_phy_name(ap['interface'])
    phy_client = get_phy_name(client['interface'])
    phy_monitor = get_phy_name(monitor['interface'])
    
    # 3. Assign Virtual Radios to Namespaces dynamically
    subprocess.run(f"sudo iw phy {phy_ap} set netns name {ap['namespace']}", shell=True)
    subprocess.run(f"sudo iw phy {phy_client} set netns name {client['namespace']}", shell=True)
    subprocess.run(f"sudo iw phy {phy_monitor} set netns name {monitor['namespace']}", shell=True)
    
    # 4. Bring Radios UP & Configure Monitor Mode
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link set {ap['interface']} up", shell=True)
    subprocess.run(f"sudo ip netns exec {client['namespace']} ip link set {client['interface']} up", shell=True)
    
    subprocess.run(f"sudo ip netns exec {monitor['namespace']} ip link set {monitor['interface']} down", shell=True)
    subprocess.run(f"sudo ip netns exec {monitor['namespace']} iw dev {monitor['interface']} set type monitor", shell=True)
    subprocess.run(f"sudo ip netns exec {monitor['namespace']} ip link set {monitor['interface']} up", shell=True)
    
    # 5. Create the Layer 2 Bridge in the AP (Linking Wi-Fi to the VLAN 10 Trunk)
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link add name br-vlan10 type bridge", shell=True)
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link set veth_ap.10 master br-vlan10", shell=True)
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip link set br-vlan10 up", shell=True)
    
    # 6. Start Core Router DHCP Server (10.0.10.x Subnet)
    dnsmasq_cmd = f"sudo ip netns exec router_ns dnsmasq --interface=veth_rtr.10 --dhcp-range=10.0.10.50,10.0.10.150,255.255.255.0,12h --no-daemon"
    dns_proc = subprocess.Popen(dnsmasq_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 7. Start Wireless Daemons
    abs_ap_config = os.path.abspath(ap['config_path'])
    ap_cmd = f"sudo ip netns exec {ap['namespace']} hostapd {abs_ap_config}"
    hostapd_proc = subprocess.Popen(ap_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    
    abs_client_config = os.path.abspath(client['config_path'])
    client_cmd = f"sudo ip netns exec {client['namespace']} wpa_supplicant -B -i {client['interface']} -c {abs_client_config}"
    subprocess.run(client_cmd, shell=True)
    time.sleep(4)
    
    # 8. Global DHCP Request
    subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient -1 {client['interface']} 2>/dev/null", shell=True)
    time.sleep(2)
    
    yield
    
    hostapd_proc.terminate()
    dns_proc.terminate()
    subprocess.run("sudo ./scripts/teardown_topology.sh", shell=True)

@pytest.fixture
def async_sniffer(request, system_config):
    test_name = request.node.name
    monitor = system_config["nodes"]["monitor"]
    pcap_dir = system_config["target_environment"]["log_directory"]
    os.makedirs(pcap_dir, exist_ok=True)
    pcap_path = f"{pcap_dir}/{test_name}.pcap"
    
    if os.path.exists(pcap_path):
        os.remove(pcap_path)
        
    cmd = f"sudo ip netns exec {monitor['namespace']} tcpdump -i {monitor['interface']} -w {pcap_path} -U"
    sniffer_proc = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.5)
    yield pcap_path
    sniffer_proc.terminate()
    sniffer_proc.wait()

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        fw = item.config.getoption("--fw-version")
        test_name = item.name
        status = report.outcome.upper()
        duration = report.duration
        err_msg = str(report.longrepr) if report.failed else ""
        pcap_path = f"artifacts/pcaps/{test_name}.pcap"
        
        with sqlite3.connect("db/results.db", timeout=10) as conn:
            conn.execute("""
                INSERT INTO test_logs (firmware_version, test_name, status, execution_time, error_message, pcap_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (fw, test_name, status, duration, err_msg, pcap_path))
            conn.commit()
