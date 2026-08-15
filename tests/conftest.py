from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / "db" / "results.db"
LIVE_TESTS = os.getenv("NETFORGE_LIVE_TESTS", "0") == "1"
LIVE_MODULES = {
    "test_8021x_enterprise.py", "test_attenuation_roaming.py", "test_auth.py",
    "test_chaos_throughput.py", "test_dhcp.py", "test_l2_l3_infrastructure.py",
    "test_mlo_failover.py", "test_throughput.py", "test_usp_telemetry.py",
}


def pytest_addoption(parser):
    parser.addoption("--fw-version", action="store", default="1.0.0")


def pytest_collection_modifyitems(config, items):
    live = pytest.mark.live
    for item in items:
        if item.fspath.basename in LIVE_MODULES:
            item.add_marker(live)


@pytest.fixture(scope="session")
def fw_version(request):
    return request.config.getoption("--fw-version")


@pytest.fixture(scope="session")
def test_params():
    default = {
        "timeouts": {"wpa_association_seconds": 20, "dhcp_lease_seconds": 15},
        "thresholds": {"minimum_throughput_mbps": 15.0, "maximum_latency_ms": 45.0},
    }
    path = ROOT / "config/test_params.yaml"
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    return {**default, **loaded}


@pytest.fixture(scope="session")
def system_config():
    with (ROOT / "config/devices.yaml").open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    nodes = raw.setdefault("nodes", {})
    nodes.setdefault("ap", {"namespace": "ap_ns", "interface": "wlan0", "config_path": "config/ap.conf"})
    nodes.setdefault("client", {"namespace": "client_ns", "interface": "wlan1", "config_path": "config/client.conf"})
    nodes.setdefault("monitor", {"namespace": "monitor_ns", "interface": "wlan2"})
    return raw


def ensure_database(version):
    from db.init_db import initialize
    initialize(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO firmware_metadata(firmware_version) VALUES (?)", (version,))
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def database_bootstrap(fw_version):
    ensure_database(fw_version)


def require_live_environment():
    if not LIVE_TESTS:
        pytest.skip("Privileged network test disabled; set NETFORGE_LIVE_TESTS=1 to run it")


@pytest.fixture(scope="session", autouse=True)
def live_lab(request):
    live_items = [item for item in request.session.items if item.get_closest_marker("live") is not None]
    if not live_items:
        yield
        return
    require_live_environment()
    subprocess.run(["sudo", "-v"], check=True)
    setup = subprocess.run(["sudo", "bash", str(ROOT / "scripts/setup_topology.sh")], capture_output=True, text=True)
    if setup.returncode != 0:
        raise RuntimeError(f"NetForge Tier-1 lab provisioning failed:\n{setup.stdout}\n{setup.stderr}")
    try:
        yield
    finally:
        subprocess.run(["sudo", "bash", str(ROOT / "scripts/teardown_topology.sh")], check=False)


def run_ns(ns, *args, check=False, capture=False):
    return subprocess.run(["sudo", "ip", "netns", "exec", ns, *args], check=check, capture_output=capture, text=True)


def set_monitor_channel(monitor_ns, monitor_if, channel=6):
    run_ns(monitor_ns, "ip", "link", "set", monitor_if, "up", check=True)
    last = ""
    for _ in range(5):
        result = run_ns(monitor_ns, "iw", "dev", monitor_if, "set", "channel", str(channel), capture=True)
        if result.returncode == 0:
            return
        last = (result.stderr or result.stdout or "").strip()
        time.sleep(0.5)
    info = run_ns(monitor_ns, "iw", "dev", monitor_if, "info", capture=True)
    raise RuntimeError(f"Unable to set monitor channel {channel}: {last}\n{info.stdout}\n{info.stderr}")


def _wait_for_hostapd(ap_ns, ap_if, timeout, log_path):
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        result = run_ns(ap_ns, "hostapd_cli", "-i", ap_if, "status", capture=True)
        last = result.stdout or result.stderr or ""
        if result.returncode == 0 and "state=ENABLED" in result.stdout:
            return
        time.sleep(0.25)
    raise RuntimeError(f"hostapd did not reach ENABLED state:\n{last}\nLog: {log_path}")


def _wait_for_ssid(client_ns, client_if, ssid, timeout):
    deadline = time.monotonic() + timeout
    last = ""
    run_ns(client_ns, "wpa_cli", "-i", client_if, "scan", capture=True)
    while time.monotonic() < deadline:
        result = run_ns(client_ns, "wpa_cli", "-i", client_if, "scan_results", capture=True)
        last = result.stdout or result.stderr or ""
        if ssid in last:
            return
        time.sleep(0.5)
        run_ns(client_ns, "wpa_cli", "-i", client_if, "scan", capture=True)
    raise RuntimeError(f"Client could not discover SSID {ssid!r}. scan_results:\n{last}")


def _wait_for_association(client_ns, client_if, timeout, log_path):
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        status = run_ns(client_ns, "wpa_cli", "-i", client_if, "status", capture=True)
        last = status.stdout or status.stderr or ""
        if status.returncode == 0 and "wpa_state=COMPLETED" in status.stdout:
            return status.stdout
        time.sleep(0.5)
    raise RuntimeError(f"WPA association did not complete:\n{last}\nLog: {log_path}")


def _wait_for_dhcp(client_ns, client_if, timeout):
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        result = run_ns(client_ns, "ip", "-4", "addr", "show", "dev", client_if, capture=True)
        last = result.stdout or result.stderr or ""
        if "192.168.50." in last and "/24" in last:
            return last
        time.sleep(0.5)
    raise RuntimeError(f"DHCP lease was not acquired on {client_if}:\n{last}")


@pytest.fixture(scope="function", autouse=True)
def lifecycle_management(request, test_params):
    if request.node.get_closest_marker("live") is None:
        yield
        return

    require_live_environment()
    nodes = request.getfixturevalue("system_config")["nodes"]
    ap, client, monitor = nodes["ap"], nodes["client"], nodes["monitor"]
    ap_ns, client_ns, monitor_ns = ap["namespace"], client["namespace"], monitor["namespace"]
    ap_if, client_if, monitor_if = ap["interface"], client["interface"], monitor["interface"]
    ap_conf = ROOT / ap["config_path"]

    log_dir = ROOT / "artifacts" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = request.node.name.replace("/", "_")
    hostapd_log = log_dir / f"{stem}-hostapd.log"
    wpa_log = log_dir / f"{stem}-wpa_supplicant.log"
    dns_log = log_dir / f"{stem}-dnsmasq.log"
    for path in (hostapd_log, wpa_log, dns_log):
        path.unlink(missing_ok=True)

    for ns in (ap_ns, client_ns, monitor_ns):
        for proc in ("hostapd", "dnsmasq", "wpa_supplicant", "dhclient", "iperf3", "tcpdump"):
            subprocess.run(["sudo", "ip", "netns", "exec", ns, "pkill", "-x", proc], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run_ns(ap_ns, "ip", "link", "set", ap_if, "down", check=True)
    run_ns(client_ns, "ip", "link", "set", client_if, "down", check=True)
    run_ns(ap_ns, "ip", "link", "set", ap_if, "up", check=True)
    run_ns(client_ns, "ip", "link", "set", client_if, "up", check=True)
    run_ns(ap_ns, "ip", "addr", "replace", "192.168.50.1/24", "dev", ap_if, check=True)

    dns_proc = hostapd_proc = wpa_proc = None
    try:
        with dns_log.open("w", encoding="utf-8") as dns_out, hostapd_log.open("w", encoding="utf-8") as ap_out:
            dns_proc = subprocess.Popen(
                ["sudo", "ip", "netns", "exec", ap_ns, "dnsmasq", f"--interface={ap_if}", "--bind-interfaces",
                 "--dhcp-range=192.168.50.10,192.168.50.50,255.255.255.0,12h",
                 "--dhcp-option=3,192.168.50.1", "--dhcp-option=6,192.168.50.1", "--no-daemon"],
                stdout=dns_out, stderr=subprocess.STDOUT, text=True,
            )
            hostapd_proc = subprocess.Popen(
                ["sudo", "ip", "netns", "exec", ap_ns, "hostapd", "-dd", str(ap_conf)],
                stdout=ap_out, stderr=subprocess.STDOUT, text=True,
            )

        deadline = time.monotonic() + 5
        while hostapd_proc.poll() is None and time.monotonic() < deadline:
            result = run_ns(ap_ns, "hostapd_cli", "-i", ap_if, "status", capture=True)
            if result.returncode == 0 and "state=ENABLED" in result.stdout:
                break
            time.sleep(0.25)
        _wait_for_hostapd(ap_ns, ap_if, 3, hostapd_log)

        # The AP owns channel 6. Only the passive monitor follows it after AP startup.
        set_monitor_channel(monitor_ns, monitor_if, 6)

        with wpa_log.open("w", encoding="utf-8") as wpa_out:
            wpa_proc = subprocess.Popen(
                ["sudo", "ip", "netns", "exec", client_ns, "wpa_supplicant", "-B", "-dd", "-Dnl80211",
                 f"-i{client_if}", f"-c{ROOT / 'config/client.conf'}"],
                stdout=wpa_out, stderr=subprocess.STDOUT, text=True,
            )
        time.sleep(1)
        _wait_for_ssid(client_ns, client_if, "NetForge_Test", 8)
        _wait_for_association(client_ns, client_if, test_params["timeouts"].get("wpa_association_seconds", 20), wpa_log)

        run_ns(client_ns, "dhclient", "-r", client_if, capture=True)
        dhcp = run_ns(client_ns, "dhclient", "-1", "-v", client_if, capture=True)
        if dhcp.returncode != 0:
            raise RuntimeError(f"DHCP client failed:\n{dhcp.stdout}\n{dhcp.stderr}")
        _wait_for_dhcp(client_ns, client_if, test_params["timeouts"].get("dhcp_lease_seconds", 15))

        ping = run_ns(client_ns, "ping", "-c", "2", "-W", "2", "192.168.50.1", capture=True)
        if ping.returncode != 0:
            raise RuntimeError(f"Client cannot reach AP after association/DHCP:\n{ping.stdout}\n{ping.stderr}")

        yield
    finally:
        for ns in (ap_ns, client_ns, monitor_ns):
            for proc in ("hostapd", "dnsmasq", "wpa_supplicant", "dhclient", "iperf3", "tcpdump"):
                subprocess.run(["sudo", "ip", "netns", "exec", ns, "pkill", "-x", proc], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for proc in (hostapd_proc, dns_proc, wpa_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()


@pytest.fixture(scope="function")
def async_sniffer(request, system_config):
    require_live_environment()
    monitor = system_config["nodes"]["monitor"]
    pcap_dir = ROOT / system_config.get("target_environment", {}).get("log_directory", "artifacts/pcaps")
    pcap_dir.mkdir(parents=True, exist_ok=True)
    pcap_path = pcap_dir / f"{request.node.name}.pcap"
    tmp = Path("/tmp") / f"netforge-{request.node.name}.pcap"
    for path in (pcap_path, tmp):
        path.unlink(missing_ok=True)
    proc = subprocess.Popen(["sudo", "ip", "netns", "exec", monitor["namespace"], "tcpdump", "-i", monitor["interface"], "-w", str(tmp), "-U"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        yield str(tmp)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if tmp.exists():
            subprocess.run(["sudo", "mv", str(tmp), str(pcap_path)], check=False)
            subprocess.run(["sudo", "chown", str(os.getuid()), str(pcap_path)], check=False)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO test_logs(firmware_version,test_name,status,execution_time,error_message,pcap_path) VALUES(?,?,?,?,?,?)",
                (item.config.getoption("--fw-version"), item.name, report.outcome.upper(), report.duration,
                 str(report.longrepr) if report.failed else "", f"artifacts/pcaps/{item.name}.pcap"),
            )
            conn.commit()
    except sqlite3.Error:
        pass
