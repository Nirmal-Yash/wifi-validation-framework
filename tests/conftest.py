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
def test_params():
    default_params = {
        "timeouts": {"wpa_association_seconds": 6, "dhcp_lease_seconds": 5},
        "thresholds": {"minimum_throughput_mbps": 15.0, "maximum_latency_ms": 45.0}
    }
    if os.path.exists("config/test_params.yaml"):
        with open("config/test_params.yaml", "r") as f:
            return yaml.safe_load(f)
    return default_params

@pytest.fixture(scope="session")
def system_config():
    with open("config/devices.yaml", "r") as f:
        raw_config = yaml.safe_load(f)
    
    config = {
        "target_environment": raw_config.get("target_environment", {}),
        "nodes": {
            "ap": {"namespace": "ap_ns", "interface": "wlan0", "config_path": "config/ap.conf"},
            "client": {"namespace": "client_ns", "interface": "wlan1", "config_path": "config/client.conf"},
            "monitor": {"namespace": "monitor_ns", "interface": "wlan2"}
        }
    }
    
    config["target_environment"]["environment_type"] = "localized_netns"
    config["target_environment"]["log_directory"] = "artifacts/pcaps"
    return config

def ensure_daemon_configs():
    os.makedirs("config", exist_ok=True)
    with open("config/ap.conf", "w") as f:
        f.write("interface=wlan0\ndriver=nl80211\nssid=NetForge_Test\nhw_mode=g\nchannel=6\nwpa=2\nwpa_passphrase=Password123!\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n")
    with open("config/client.conf", "w") as f:
        f.write("ctrl_interface=/var/run/wpa_supplicant\nupdate_config=1\nnetwork={\n    ssid=\"NetForge_Test\"\n    psk=\"Password123!\"\n}\n")
    
    # Internal RADIUS Simulation for Enterprise 802.1X
    with open("config/hostapd.eap_user", "w") as f:
        f.write('* PEAP\n"admin" PEAP "Password123!" [2]\n')
    with open("config/hostapd_enterprise.conf", "w") as f:
        f.write("interface=wlan0\ndriver=nl80211\nssid=NetForge_Enterprise\nieee8021x=1\nwpa=2\nwpa_key_mgmt=WPA-EAP\nrsn_pairwise=CCMP\nauth_algs=1\neapol_version=2\neap_server=1\neap_user_file=config/hostapd.eap_user\n")
    with open("config/wpa_supplicant_enterprise.conf", "w") as f:
        f.write("ctrl_interface=/var/run/wpa_supplicant\nnetwork={\n    ssid=\"NetForge_Enterprise\"\n    key_mgmt=WPA-EAP\n    eap=PEAP\n    identity=\"admin\"\n    password=\"Password123!\"\n    phase2=\"auth=MSCHAPV2\"\n}\n")

@pytest.fixture(scope="session", autouse=True)
def ensure_firmware_record(fw_version):
    os.makedirs("db", exist_ok=True)
    try:
        conn = sqlite3.connect("db/results.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO firmware_metadata (firmware_version) VALUES (?)", (fw_version,))
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        pass

# STRICT ISOLATION: Scope changed to function to guarantee a clean slate per test
@pytest.fixture(scope="function", autouse=True)
def lifecycle_management(system_config):
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    
    ensure_daemon_configs()
    
    subprocess.run("sudo killall hostapd dnsmasq wpa_supplicant iperf3 dhclient tcpdump 2>/dev/null", shell=True)
    
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip addr flush dev {ap['interface']} 2>/dev/null", shell=True)
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip addr add 192.168.50.1/24 dev {ap['interface']} 2>/dev/null", shell=True)
    
    dnsmasq_cmd = f"sudo ip netns exec {ap['namespace']} dnsmasq --interface={ap['interface']} --dhcp-range=192.168.50.10,192.168.50.50,255.255.255.0,12h --no-daemon"
    dns_proc = subprocess.Popen(dnsmasq_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    abs_ap_config = os.path.abspath(ap['config_path'])
    ap_cmd = f"sudo ip netns exec {ap['namespace']} hostapd {abs_ap_config}"
    hostapd_proc = subprocess.Popen(ap_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    
    abs_client_config = os.path.abspath(client['config_path'])
    client_cmd = f"sudo ip netns exec {client['namespace']} wpa_supplicant -B -i {client['interface']} -c {abs_client_config}"
    subprocess.run(client_cmd, shell=True)
    time.sleep(3)
    
    subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient {client['interface']} 2>/dev/null", shell=True)
    time.sleep(1)
    
    yield
    
    hostapd_proc.terminate()
    dns_proc.terminate()
    subprocess.run("sudo killall hostapd dnsmasq wpa_supplicant dhclient iperf3 tcpdump 2>/dev/null", shell=True)

@pytest.fixture(scope="function")
def async_sniffer(request, system_config):
    test_name = request.node.name
    monitor = system_config["nodes"]["monitor"]
    pcap_dir = os.path.abspath(system_config["target_environment"].get("log_directory", "artifacts/pcaps"))
    os.makedirs(pcap_dir, exist_ok=True)
    
    pcap_path = f"{pcap_dir}/{test_name}.pcap"
    tmp_pcap = f"/tmp/{test_name}.pcap"
    
    if os.path.exists(pcap_path): os.remove(pcap_path)
    if os.path.exists(tmp_pcap): os.remove(tmp_pcap)
        
    cmd_args = ["sudo", "ip", "netns", "exec", monitor["namespace"], "tcpdump", "-i", monitor["interface"], "-w", tmp_pcap, "-U"]
    sniffer_proc = subprocess.Popen(cmd_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    
    yield tmp_pcap
    
    subprocess.run(["sudo", "kill", str(sniffer_proc.pid)], stderr=subprocess.DEVNULL)
    sniffer_proc.wait()
    
    if os.path.exists(tmp_pcap):
        subprocess.run(["sudo", "mv", tmp_pcap, pcap_path], stderr=subprocess.DEVNULL)
        subprocess.run(["sudo", "chown", str(os.getuid()), pcap_path], stderr=subprocess.DEVNULL)

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
        
        try:
            conn = sqlite3.connect("db/results.db")
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO test_logs (firmware_version, test_name, status, execution_time, error_message, pcap_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (fw, test_name, status, duration, err_msg, pcap_path))
            conn.commit()
            conn.close()
        except sqlite3.OperationalError:
            pass
