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
    conn = sqlite3.connect("db/results.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO firmware_metadata (firmware_version) VALUES (?)", (fw_version,))
    conn.commit()
    conn.close()

@pytest.fixture(scope="session", autouse=True)
def lifecycle_management(system_config):
    ap = system_config["nodes"]["ap"]
    client = system_config["nodes"]["client"]
    
    subprocess.run("sudo killall hostapd dnsmasq wpa_supplicant iperf3 dhclient 2>/dev/null", shell=True)
    subprocess.run("sudo rfkill unblock all 2>/dev/null", shell=True)
    
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip addr flush dev {ap['interface']}", shell=True)
    subprocess.run(f"sudo ip netns exec {ap['namespace']} ip addr add 192.168.50.1/24 dev {ap['interface']}", shell=True)
    
    dnsmasq_cmd = f"sudo ip netns exec {ap['namespace']} dnsmasq --interface={ap['interface']} --dhcp-range=192.168.50.10,192.168.50.50,255.255.255.0,12h --no-daemon"
    dns_proc = subprocess.Popen(dnsmasq_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    abs_ap_config = os.path.abspath(ap['config_path'])
    ap_cmd = f"sudo ip netns exec {ap['namespace']} hostapd {abs_ap_config}"
    hostapd_proc = subprocess.Popen(ap_cmd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    
    abs_client_config = os.path.abspath(client['config_path'])
    client_cmd = f"sudo ip netns exec {client['namespace']} wpa_supplicant -B -i {client['interface']} -c {abs_client_config}"
    subprocess.run(client_cmd, shell=True)
    time.sleep(4)
    
    # NEW: Ensure client has an IP address globally before any tests run
    subprocess.run(f"sudo ip netns exec {client['namespace']} dhclient {client['interface']} 2>/dev/null", shell=True)
    time.sleep(2)
    
    yield
    
    hostapd_proc.terminate()
    dns_proc.terminate()
    subprocess.run("sudo killall hostapd dnsmasq wpa_supplicant dhclient 2>/dev/null", shell=True)

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
        
        with open("config/devices.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        pcap_path = f"{cfg['target_environment']['log_directory']}/{test_name}.pcap"
        
        conn = sqlite3.connect("db/results.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO test_logs (firmware_version, test_name, status, execution_time, error_message, pcap_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fw, test_name, status, duration, err_msg, pcap_path))
        conn.commit()
        conn.close()
